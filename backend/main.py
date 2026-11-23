"""
TradeLab Paper Trading Backend - FastAPI Application.

Serves complete TradeLab API:
- Spot indices & live/historical candlestick charts
- Full Option Chain with Black-Scholes Greeks, PCR, and Max Pain
- Paper Trading Execution Engine (Wallet, Orders, Positions, SL/Target)
- Historical 1-Minute Candle Replay System
- Analytics (Strike-wise OI, PCR, P&L Calendar Heatmap)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager
from typing import Any, Optional

# Ensure backend directory and its subdirectories are on sys.path
_backend_dir = str(Path(__file__).resolve().parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from angel_service import angel_service
from auth import auth_router, decode_access_token, get_current_user, get_optional_user
from config import INDEX_CONFIG, normalize_index_symbol, settings
from database import UserModel, engine, init_db
from debate_engine import debate_engine
from greeks import BlackScholesEngine
from keep_alive import keep_alive_manager
from paper_engine import paper_engine
from replay_engine import replay_engine
from scheduler import get_scheduler
from scrip_master import scrip_master

logger = logging.getLogger("tradelab_main")
logging.basicConfig(level=logging.INFO)

# Background MTM periodic task
_mtm_task: Optional[asyncio.Task] = None


class ConnectionManager:
    """Manages real-time WebSocket connections for live terminal tick broadcasting."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket terminal client connected. Total clients: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("WebSocket terminal client disconnected. Remaining: %d", len(self.active_connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


ws_manager = ConnectionManager()


async def _periodic_mtm_loop() -> None:
    """Periodically update paper positions MTM (with REAL Angel One option prices) and square-off."""
    while True:
        try:
            await asyncio.sleep(0.5)
            # Check 15:15 IST MIS Auto Square-off
            await paper_engine.check_intraday_squareoff()

            if replay_engine.is_replaying and _is_market_open() and not settings.ALLOW_OFFHOURS_TRADING:
                logger.info("Market opened: stopping Historical Replay so live prices resume.")
                await replay_engine.stop_replay()

            has_work = bool(paper_engine.active_positions or paper_engine.active_orders)
            if not has_work and not ws_manager.active_connections:
                await asyncio.sleep(1.5)
                continue

            # Always fetch latest spots for WebSocket streaming and MTM
            spots = await angel_service.get_spot_indices()

            # Only update live prices if replay mode is not active and positions exist
            if not replay_engine.is_replaying and has_work:
                quotes_dict: dict[str, float] = {}
                live_feed = angel_service.is_configured()

                if live_feed:
                    # REAL option LTPs straight from Angel One (matches broker terminal)
                    legs = [
                        {
                            "symbol": x["symbol"],
                            "underlying": x.get("underlying", "NIFTY"),
                            "strike": x["strike"],
                            "option_type": x["option_type"],
                        }
                        for x in list(paper_engine.active_positions.values())
                        + list(paper_engine.active_orders.values())
                    ]
                    quotes_dict.update(await angel_service.get_option_ltps(legs))
                else:
                    # Offline / dev mode only: theoretical Black-Scholes prices
                    for s in spots:
                        sym = s["symbol"]
                        spot_p = float(s["ltp"])
                        quotes_dict[sym] = spot_p
                        spec = INDEX_CONFIG.get(sym, INDEX_CONFIG["NIFTY"])
                        step = spec["strike_step"]
                        atm = int(round(spot_p / step) * step)
                        for offset in range(-8, 9):
                            k = atm + (offset * step)
                            ce_p = BlackScholesEngine.calculate_price(spot_p, k, 3.0 / 365.0, iv=0.15, option_type="CE")
                            pe_p = BlackScholesEngine.calculate_price(spot_p, k, 3.0 / 365.0, iv=0.15, option_type="PE")
                            quotes_dict[f"{k}CE"] = ce_p
                            quotes_dict[f"{k}PE"] = pe_p
                            quotes_dict[f"{sym}{k}CE"] = ce_p
                            quotes_dict[f"{sym}{k}PE"] = pe_p

                await paper_engine.update_market_prices(quotes_dict)

            # Broadcast real-time market price TICK to all connected WebSockets
            if ws_manager.active_connections:
                await ws_manager.broadcast({
                    "type": "TICK",
                    "indices": spots,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Error in periodic MTM loop: %s", exc)
            await asyncio.sleep(2.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _mtm_task
    logger.info("Initializing TradeLab Backend...")
    # Initialize SQLite database schema
    await init_db()
    # Restore active paper positions from SQLite into memory
    await paper_engine.restore_from_db()
    # Restore AI debate history from the database and resume the auto-debate scheduler if it was on
    await debate_engine.load_history()
    await get_scheduler().restore()
    # Attempt initial auth
    asyncio.create_task(angel_service.authenticate())
    asyncio.create_task(angel_service.ensure_contracts())
    _mtm_task = asyncio.create_task(_periodic_mtm_loop())
    if getattr(settings, "ENABLE_KEEP_ALIVE", True):
        asyncio.create_task(keep_alive_manager.start())
    yield
    if _mtm_task and not _mtm_task.done():
        _mtm_task.cancel()
    try:
        await keep_alive_manager.stop()
    except Exception as exc:
        logger.warning("Error stopping keep-alive service: %s", exc)
    try:
        await get_scheduler().shutdown()
    except Exception as exc:
        logger.warning("Error stopping scheduler on shutdown: %s", exc)
    await angel_service.close()
    await replay_engine.stop_replay()
    logger.info("TradeLab Backend shutdown complete.")


app = FastAPI(
    title="TradeLab Paper Trading API",
    description="Professional Indian Options Paper Trading Platform & Replay Simulator",
    version="2.0.0",
    lifespan=lifespan,
)

# ── CORS Middleware ──────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://papertrade-ebon.vercel.app",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8000",
    ],
    allow_origin_regex=r"^https://.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Authentication Router ────────────────────────────────────────────────────
app.include_router(auth_router)


# ── Pydantic Request Models ──────────────────────────────────────────────────
class OrderCreateRequest(BaseModel):
    symbol: Optional[str] = Field(default="", description="Trading symbol e.g. NIFTY26112025400CE")
    underlying: str = Field(default="NIFTY", description="Underlying index: NIFTY, BANKNIFTY, FINNIFTY, SENSEX")
    strike: float = Field(default=0.0, description="Strike price")
    option_type: str = Field(default="CE", description="CE or PE")
    lots: int = Field(default=1, ge=1, description="Number of lots")
    side: str = Field(default="BUY", description="BUY or SELL")
    order_type: str = Field(default="MARKET", description="MARKET, LIMIT, or SL")
    price: float = Field(default=0.0, description="Limit price for LIMIT orders")
    trigger_price: float = Field(default=0.0, description="Trigger price for SL orders")
    stop_loss: Optional[float] = Field(default=None, description="Optional stop loss level")
    target: Optional[float] = Field(default=None, description="Optional profit target level")
    current_ltp: Optional[float] = Field(default=None, description="Current LTP estimate")
    expiry: Optional[str] = Field(default=None, description="Expiry ISO date (YYYY-MM-DD); nearest if omitted")
    stop_loss_pct: Optional[float] = Field(default=None, description="SL as % below the live fill price")
    target_pct: Optional[float] = Field(default=None, description="Target as % above the live fill price")


class UpdateSLRequest(BaseModel):
    stop_loss: Optional[float] = Field(default=None)
    target: Optional[float] = Field(default=None)


class ReplayStartRequest(BaseModel):
    date: str = Field(description="Historical date in YYYY-MM-DD format")
    symbol: str = Field(default="NIFTY", description="Index symbol")


class ReplayControlRequest(BaseModel):
    action: str = Field(description="pause | resume | speed | step_forward | step_backward | stop")
    speed: Optional[float] = Field(default=None, description="Speed multiplier for 'speed' action")


class StrategyLeg(BaseModel):
    strike: float
    option_type: str = Field(default="CE", description="CE or PE")
    side: str = Field(default="BUY", description="BUY or SELL")
    quantity: int = Field(default=25, ge=1)
    price: float = Field(default=0.0, ge=0.0)


class PayoffRequest(BaseModel):
    symbol: str = "NIFTY"
    spot: Optional[float] = None
    legs: list[StrategyLeg]


class DebateRunRequest(BaseModel):
    symbol: str = Field(default="NIFTY", description="Index symbol: NIFTY or BANKNIFTY")


class DebateExecuteRequest(BaseModel):
    lots: int = Field(default=1, ge=1, description="Number of lots to execute")
    strike: Optional[float] = None
    option_type: Optional[str] = None
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None


class SchedulerStartRequest(BaseModel):
    interval_minutes: int = Field(default=5, description="Interval in minutes: 3, 5, 10, or 15")
    symbol: str = Field(default="NIFTY", description="Underlying index: NIFTY or BANKNIFTY")
    auto_execute: bool = Field(default=False, description="Auto-execute Judge trades if confidence >= 70%")
    market_hours_only: bool = Field(default=True, description="Only debate 09:15-15:30 IST on weekdays")
    lots: int = Field(default=1, ge=1, le=50, description="Lots per auto-executed trade")


# ── Real-Time WebSocket Terminal Feed ────────────────────────────────────────
@app.websocket("/ws/terminal")
async def websocket_terminal_endpoint(websocket: WebSocket, token: Optional[str] = Query(None)):
    """Real-time streaming tick feed for options chain, MTM, and order updates."""
    await ws_manager.connect(websocket)
    try:
        user_id: Optional[int] = None
        if token:
            try:
                payload = decode_access_token(token)
                if payload and "sub" in payload:
                    user_id = int(payload["sub"])
            except Exception as e:
                logger.debug("WebSocket token decode non-fatal: %s", e)
                user_id = None

        spots = await angel_service.get_spot_indices()
        state = await paper_engine.get_state(user_id=user_id)
        replay = replay_engine.get_state()
        await websocket.send_json({
            "type": "INIT",
            "indices": spots,
            "trading_state": state,
            "replay_state": replay,
        })
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except (WebSocketDisconnect, asyncio.CancelledError):
        ws_manager.disconnect(websocket)
    except Exception as exc:
        logger.debug("WebSocket exception: %s", exc)
        ws_manager.disconnect(websocket)


# ── System & Status Endpoints ────────────────────────────────────────────────
@app.get("/api/health")
@app.get("/healthz")
@app.get("/api/ping")
async def health_check():
    """Lightweight 200 OK endpoint to reset cloud hosting idle timers (Render, Railway)."""
    db_dialect = engine.dialect.name
    is_postgres = db_dialect == "postgresql"
    return {
        "status": "ok",
        "service": "TradeLab Paper Trading Engine",
        "database": {
            "dialect": db_dialect,
            "provider": "Supabase PostgreSQL" if is_postgres else "Local SQLite",
            "is_postgres": is_postgres,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "keep_alive": keep_alive_manager.get_status(),
    }


@app.get("/api/keep-alive/status")
async def get_keep_alive_status():
    """Return diagnostics on the Render self-ping keep-alive loop."""
    return keep_alive_manager.get_status()


@app.post("/api/keep-alive/ping")
async def trigger_manual_keep_alive_ping():
    """Manually dispatch a keep-alive heartbeat ping immediately."""
    return await keep_alive_manager.ping_once()


def _is_market_open() -> bool:
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    if now.weekday() >= 5:
        return False
    return (now.hour, now.minute) >= (9, 15) and (now.hour, now.minute) < (15, 30)


@app.get("/api/status")
async def get_system_status():
    """Return platform and Angel One connection health status."""
    angel_configured = angel_service.is_configured()
    replay_state = replay_engine.get_state()
    return {
        "status": "ONLINE",
        "angel_one_connected": angel_configured,
        "data_source": angel_service.data_source,
        "vix": angel_service.vix,
        "market_open": _is_market_open(),
        "mode": "REPLAY" if replay_state["is_replaying"] else "LIVE",
        "replay_active": replay_state["is_replaying"],
        "virtual_capital": settings.VIRTUAL_STARTING_CAPITAL,
        "available_indices": list(INDEX_CONFIG.keys()),
    }


# ── Market Data Endpoints ────────────────────────────────────────────────────
@app.get("/api/indices")
async def get_indices():
    """Return real-time spot prices for major Indian benchmark indices."""
    if replay_engine.is_replaying:
        current_tick = replay_engine.get_current_tick()
        if current_tick:
            rep_sym = replay_engine.symbol
            spec = INDEX_CONFIG.get(rep_sym, INDEX_CONFIG["NIFTY"])
            spot = current_tick["close"]
            return [
                {
                    "symbol": rep_sym,
                    "name": spec["name"],
                    "trading_symbol": spec["trading_symbol"],
                    "token": spec["token"],
                    "exchange": spec["exchange"],
                    "ltp": spot,
                    "open": current_tick["open"],
                    "high": current_tick["high"],
                    "low": current_tick["low"],
                    "close": spot,
                    "net_change": round(spot - spec["default_spot"], 2),
                    "percent_change": round(((spot - spec["default_spot"]) / spec["default_spot"]) * 100, 2),
                    "timestamp": current_tick.get("timestamp"),
                }
            ]

    indices = await angel_service.get_spot_indices()
    return indices


@app.get("/api/candles")
async def get_candles(
    symbol: str = Query(default="NIFTY"),
    interval: str = Query(default="5m"),
    range_period: str = Query(default="5d"),
    strike: Optional[float] = Query(default=None),
    option_type: Optional[str] = Query(default=None),
    expiry: Optional[str] = Query(default=None),
):
    """Return historical candlestick data for spot index or specific option strike contract."""
    norm = normalize_index_symbol(symbol)
    replaying_symbol = replay_engine.is_replaying and replay_engine.symbol == norm
    if strike and option_type and not replaying_symbol and angel_service.is_configured():
        await angel_service.ensure_contracts()
        expiries = scrip_master.expiries(norm)
        selected_expiry = expiry or (expiries[0] if expiries else None)
        contract = scrip_master.contract(norm, selected_expiry, int(strike), option_type.upper()) if selected_expiry else None
        if not contract:
            return []
        return await angel_service.get_candles(
            symbol=symbol, interval=interval, range_period=range_period, contract=contract
        )

    if replaying_symbol:
        # Return replayed candles up to current candle index
        candles = replay_engine.candles[: replay_engine.candle_index + 1]
    else:
        candles = await angel_service.get_candles(symbol=symbol, interval=interval, range_period=range_period)

    # Offline fallback: translate spot candles to option candles via Black-Scholes
    if strike and option_type:
        from greeks import BlackScholesEngine
        opt_type = option_type.upper()
        opt_candles = []
        for c in candles:
            o = BlackScholesEngine.calculate_price(c["open"], strike, 3.0 / 365.0, iv=0.15, option_type=opt_type)
            cl = BlackScholesEngine.calculate_price(c["close"], strike, 3.0 / 365.0, iv=0.15, option_type=opt_type)
            p_high = BlackScholesEngine.calculate_price(c["high"], strike, 3.0 / 365.0, iv=0.15, option_type=opt_type)
            p_low = BlackScholesEngine.calculate_price(c["low"], strike, 3.0 / 365.0, iv=0.15, option_type=opt_type)
            opt_candles.append({
                "time": c["time"],
                "open": o,
                "high": max(o, cl, p_high, p_low),
                "low": min(o, cl, p_high, p_low),
                "close": cl,
                "volume": max(1000, int(c.get("volume", 50000) * 0.35)),
            })
        return opt_candles

    return candles


@app.get("/api/expiries")
async def get_expiries(symbol: str = Query(default="NIFTY")):
    """Return list of upcoming weekly and monthly expiry dates."""
    await angel_service.ensure_contracts()
    return angel_service.get_expiries(symbol=symbol)


@app.get("/api/option-chain")
async def get_option_chain(
    symbol: str = Query(default="NIFTY"),
    strikes: int = Query(default=10, ge=3, le=25),
    expiry: Optional[str] = Query(default=None),
):
    """Return TradeLab Option Chain with strikes, CE & PE quotes, Greeks, PCR, and Max Pain."""
    override_spot = None
    if replay_engine.is_replaying and replay_engine.symbol == normalize_index_symbol(symbol):
        current_tick = replay_engine.get_current_tick()
        if current_tick:
            override_spot = current_tick["close"]

    chain = await angel_service.get_option_chain(
        symbol=symbol,
        strikes_count=strikes,
        expiry=expiry,
        override_spot=override_spot,
    )
    return chain


class PositionExitRequest(BaseModel):
    position_id: Optional[str] = None
    exit_price: Optional[float] = None


# ── Paper Trading Execution Endpoints ────────────────────────────────────────
@app.get("/api/trading/state")
async def get_trading_state(current_user: Optional[UserModel] = Depends(get_optional_user)):
    """Return virtual wallet, active positions, pending orders, and P&L."""
    user_id = current_user.id if current_user else None
    return await paper_engine.get_state(user_id=user_id)


@app.post("/api/trading/order")
async def place_paper_order(order: OrderCreateRequest, current_user: Optional[UserModel] = Depends(get_optional_user)):
    """Place a paper trade order (Market, Limit, SL)."""
    user_id = current_user.id if current_user else None
    order_data = order.model_dump()
    order_data["user_id"] = user_id

    # If in replay mode and current_ltp not supplied, calculate from replay tick
    replaying_for_me = replay_engine.is_replaying and user_id is not None and replay_engine.owner_id == user_id
    if replaying_for_me and (order_data.get("current_ltp") is None or order_data["current_ltp"] <= 0):
        current_tick = replay_engine.get_current_tick()
        if current_tick:
            spot = current_tick["close"]
            strike = order_data.get("strike", spot)
            opt_type = order_data.get("option_type", "CE")
            calc_ltp = BlackScholesEngine.calculate_price(spot, strike, 3.0 / 365.0, iv=0.15, option_type=opt_type)
            order_data["current_ltp"] = calc_ltp

    if not replaying_for_me:
        quote = await angel_service.get_option_quote(
            order_data.get("underlying", "NIFTY"),
            order_data.get("strike", 0),
            order_data.get("option_type", "CE"),
            expiry=order_data.get("expiry"),
        )
        if quote:
            # Use the exchange trading symbol and the live Angel One price (not the client's guess)
            order_data["symbol"] = quote["symbol"]
            if str(order_data.get("order_type", "MARKET")).upper() == "MARKET":
                order_data["current_ltp"] = quote["ltp"]
                order_data["price"] = quote["ltp"]
        elif angel_service.data_source == "live" and str(order_data.get("order_type", "MARKET")).upper() == "MARKET":
            raise HTTPException(
                status_code=503,
                detail="Live option price unavailable for this contract right now. Please retry in a moment.",
            )

    fill_ref = float(order_data.get("current_ltp") or order_data.get("price") or 0)
    if fill_ref > 0 and str(order_data.get("side", "BUY")).upper() == "BUY":
        if order.stop_loss_pct and not order_data.get("stop_loss"):
            order_data["stop_loss"] = round(fill_ref * (1 - order.stop_loss_pct / 100.0), 2)
        if order.target_pct and not order_data.get("target"):
            order_data["target"] = round(fill_ref * (1 + order.target_pct / 100.0), 2)

    result = await paper_engine.place_order(
        order_data, user_id=user_id, enforce_hours=not replaying_for_me
    )
    if result.get("status") == "REJECTED":
        raise HTTPException(status_code=400, detail=result.get("reject_reason", "Order rejected."))
    if ws_manager.active_connections:
        asyncio.create_task(ws_manager.broadcast({
            "type": "ORDER_UPDATE",
            "user_id": user_id,
            "trading_state": await paper_engine.get_state(user_id=user_id),
        }))
    return result


@app.delete("/api/trading/order/{order_id}")
@app.post("/api/trading/order/{order_id}/cancel")
async def cancel_paper_order(order_id: str, current_user: Optional[UserModel] = Depends(get_optional_user)):
    """Cancel a pending paper order."""
    user_id = current_user.id if current_user else None
    result = await paper_engine.cancel_order(order_id, user_id=user_id)
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@app.post("/api/trading/position/{pos_id}/exit")
async def exit_paper_position(
    pos_id: str,
    exit_price: Optional[float] = Query(default=None),
    current_user: Optional[UserModel] = Depends(get_optional_user),
):
    """Exit / square off an active paper position at market price or specified limit."""
    user_id = current_user.id if current_user else None
    # If in replay mode and no price passed, resolve current option price
    if exit_price is None and replay_engine.is_replaying and user_id is not None and replay_engine.owner_id == user_id:
        current_tick = replay_engine.get_current_tick()
        if current_tick:
            state = await paper_engine.get_state(user_id=user_id)
            pos = next((p for p in state["positions"] if p["pos_id"] == pos_id), None)
            if pos:
                spot = current_tick["close"]
                strike = pos["strike"]
                opt_type = pos["option_type"]
                exit_price = BlackScholesEngine.calculate_price(spot, strike, 3.0 / 365.0, iv=0.15, option_type=opt_type)

    result = await paper_engine.exit_position(pos_id, exit_price=exit_price, user_id=user_id)
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=404, detail=result.get("message"))
    if ws_manager.active_connections:
        asyncio.create_task(ws_manager.broadcast({
            "type": "ORDER_UPDATE",
            "user_id": user_id,
            "trading_state": await paper_engine.get_state(user_id=user_id),
        }))
    return result


@app.post("/api/trading/exit")
async def exit_paper_position_legacy(
    req: PositionExitRequest,
    current_user: Optional[UserModel] = Depends(get_optional_user),
):
    """Legacy exit position endpoint by JSON body."""
    if not req.position_id:
        raise HTTPException(status_code=400, detail="position_id is required.")
    return await exit_paper_position(req.position_id, exit_price=req.exit_price, current_user=current_user)


@app.post("/api/trading/exit-all")
@app.post("/api/trading/positions/exit-all")
async def exit_all_paper_positions(current_user: Optional[UserModel] = Depends(get_optional_user)):
    """Exit / square off all active paper positions at current market price."""
    user_id = current_user.id if current_user else None
    results = await paper_engine.exit_all_positions(user_id=user_id)
    if ws_manager.active_connections:
        asyncio.create_task(ws_manager.broadcast({
            "type": "ORDER_UPDATE",
            "user_id": user_id,
            "trading_state": await paper_engine.get_state(user_id=user_id),
        }))
    return {"status": "SUCCESS", "message": f"Closed {len(results)} positions.", "results": results}


@app.post("/api/trading/position/{pos_id}/sl")
@app.post("/api/trading/position/{pos_id}/stoploss")
@app.put("/api/trading/position/{pos_id}")
async def update_position_stop_loss(
    pos_id: str,
    req: UpdateSLRequest,
    current_user: Optional[UserModel] = Depends(get_optional_user),
):
    """Update stop loss and target for an active position."""
    user_id = current_user.id if current_user else None
    result = await paper_engine.update_sl(pos_id, stop_loss=req.stop_loss, target=req.target, user_id=user_id)
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@app.post("/api/trading/reset")
async def reset_paper_wallet(current_user: Optional[UserModel] = Depends(get_optional_user)):
    """Reset virtual trading wallet back to default ₹10,00,000 INR."""
    user_id = current_user.id if current_user else None
    res = await paper_engine.reset_portfolio(
        initial_capital=getattr(settings, "VIRTUAL_STARTING_CAPITAL", 1000000.0),
        user_id=user_id,
    )
    if ws_manager.active_connections:
        asyncio.create_task(ws_manager.broadcast({
            "type": "ORDER_UPDATE",
            "user_id": user_id,
            "trading_state": await paper_engine.get_state(user_id=user_id),
        }))
    return res


@app.get("/api/trading/history")
async def get_trading_history(current_user: Optional[UserModel] = Depends(get_optional_user)):
    """Return closed trade history journal."""
    user_id = current_user.id if current_user else None
    return await paper_engine.get_history(user_id=user_id)


@app.get("/api/trading/export")
async def export_trading_history_csv(current_user: Optional[UserModel] = Depends(get_optional_user)):
    """Export closed trades as a downloadable CSV report."""
    import csv
    import io
    from fastapi.responses import Response

    user_id = current_user.id if current_user else None
    trades = await paper_engine.get_history(user_id=user_id)
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Position ID",
        "Symbol",
        "Underlying",
        "Strike",
        "Type",
        "Side",
        "Lots",
        "Quantity",
        "Entry Price",
        "Exit Price",
        "Gross P&L (INR)",
        "Charges & Taxes (INR)",
        "Net Realized P&L (INR)",
        "Return (%)",
        "Entry Time (IST)",
        "Exit Time (IST)",
        "Exit Reason",
    ])

    for t in trades:
        writer.writerow([
            t.get("pos_id", t.get("id", "")),
            t.get("symbol", ""),
            t.get("underlying", ""),
            t.get("strike", ""),
            t.get("option_type", ""),
            t.get("side", ""),
            t.get("lots", ""),
            t.get("quantity", ""),
            t.get("entry_price", ""),
            t.get("exit_price", ""),
            t.get("gross_pnl", t.get("realized_pnl", 0.0)),
            t.get("total_charges", t.get("charges", {}).get("total_charges", 0.0)),
            t.get("realized_pnl", ""),
            t.get("pnl_pct", ""),
            t.get("entry_time", t.get("created_at", "")),
            t.get("exit_time", t.get("closed_at", "")),
            t.get("exit_reason", ""),
        ])

    csv_data = output.getvalue()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="tradelab_trade_journal.csv"'},
    )


# ── Historical Replay Endpoints ──────────────────────────────────────────────
@app.get("/api/replay/dates")
async def get_replay_dates():
    """Return available trading dates for historical playback."""
    return replay_engine.get_available_dates()


def _replay_guard(current_user: Optional[UserModel], starting: bool) -> int:
    """Replay swaps the live prices for everyone, so it is restricted:
    sign-in required, never while the market is open, and only one account at a time."""
    if current_user is None:
        raise HTTPException(status_code=401, detail="Sign in to use Historical Replay.")
    if starting and _is_market_open() and not settings.ALLOW_OFFHOURS_TRADING:
        raise HTTPException(
            status_code=409,
            detail="Historical Replay is off while the market is open (09:15-15:30 IST, Mon-Fri) because it "
                   "replaces live prices for every user. Use it after 15:30 or on weekends.",
        )
    if replay_engine.is_replaying and replay_engine.owner_id != current_user.id:
        raise HTTPException(status_code=409, detail="Another account is using Historical Replay right now.")
    return current_user.id


@app.post("/api/replay/start")
async def start_historical_replay(
    req: ReplayStartRequest, current_user: Optional[UserModel] = Depends(get_optional_user)
):
    """Start 1-minute historical candle replay for a date."""
    uid = _replay_guard(current_user, starting=True)
    result = await replay_engine.start_replay(date_str=req.date, symbol=req.symbol)
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=result.get("message"))
    replay_engine.owner_id = uid
    return result


@app.post("/api/replay/control")
async def control_historical_replay(
    req: ReplayControlRequest, current_user: Optional[UserModel] = Depends(get_optional_user)
):
    """Control replay playback (pause, resume, speed, step_forward, step_backward, stop)."""
    _replay_guard(current_user, starting=False)
    action = req.action.lower()
    if action == "pause":
        return await replay_engine.pause()
    elif action in ("resume", "play", "start"):
        return await replay_engine.resume()
    elif action == "speed":
        if req.speed is None:
            raise HTTPException(status_code=400, detail="Speed parameter is required for speed control.")
        return await replay_engine.set_speed(req.speed)
    elif action in ("step_forward", "step", "next"):
        return await replay_engine.step_forward()
    elif action in ("step_backward", "prev", "back"):
        return await replay_engine.step_backward()
    elif action == "stop":
        return await replay_engine.stop_replay()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")


@app.get("/api/replay/state")
async def get_replay_state():
    """Return current replay playback state and current candle tick."""
    return replay_engine.get_state()


# ── Analytics Endpoints ──────────────────────────────────────────────────────
@app.get("/api/analytics/pcr-oi")
async def get_pcr_oi_analytics(
    symbol: str = Query(default="NIFTY"),
    expiry: Optional[str] = Query(default=None),
):
    """Return Strike-wise Open Interest distribution and PCR metrics for charts."""
    chain_data = await angel_service.get_option_chain(symbol=symbol, strikes_count=12, expiry=expiry)
    rows = chain_data.get("chain", [])

    strikes = []
    ce_oi_list = []
    pe_oi_list = []
    ce_vol_list = []
    pe_vol_list = []

    for r in rows:
        strikes.append(r["strike"])
        ce_oi_list.append(r.get("ce", {}).get("oi", 0))
        pe_oi_list.append(r.get("pe", {}).get("oi", 0))
        ce_vol_list.append(r.get("ce", {}).get("volume", 0))
        pe_vol_list.append(r.get("pe", {}).get("volume", 0))

    return {
        "symbol": chain_data.get("symbol"),
        "spot_price": chain_data.get("spot_price"),
        "atm_strike": chain_data.get("atm_strike"),
        "pcr": chain_data.get("pcr"),
        "pcr_volume": chain_data.get("pcr_volume"),
        "sentiment": chain_data.get("sentiment"),
        "max_pain": chain_data.get("max_pain"),
        "call_oi_wall": chain_data.get("call_oi_wall"),
        "put_oi_wall": chain_data.get("put_oi_wall"),
        "total_ce_oi": chain_data.get("total_ce_oi"),
        "total_pe_oi": chain_data.get("total_pe_oi"),
        "strikes": strikes,
        "ce_oi": ce_oi_list,
        "pe_oi": pe_oi_list,
        "ce_volume": ce_vol_list,
        "pe_volume": pe_vol_list,
    }


@app.get("/api/analytics/pnl-calendar")
@app.get("/api/trading/pnl-calendar")
async def get_pnl_calendar(current_user: Optional[UserModel] = Depends(get_optional_user)):
    """Return daily P&L heatmap data for trading journal calendar."""
    user_id = current_user.id if current_user else None
    return await paper_engine.get_pnl_calendar(user_id=user_id)


@app.post("/api/analytics/payoff")
async def calculate_payoff_endpoint(req: PayoffRequest):
    """Calculate multi-leg options strategy payoff curve at expiry."""
    from greeks import calculate_strategy_payoff

    spot = req.spot
    if spot is None or spot <= 0:
        spot = await angel_service.get_spot_price(req.symbol)
        if not spot or spot <= 0:
            spot = 25400.0 if req.symbol == "NIFTY" else 52000.0
    legs_dicts = [leg.model_dump() for leg in req.legs]
    return calculate_strategy_payoff(spot=float(spot), legs=legs_dicts)


# ── AI Debate Studio Endpoints ───────────────────────────────────────────────
@app.post("/api/debate/run")
async def run_debate_endpoint(
    req: Optional[DebateRunRequest] = None,
    symbol: Optional[str] = Query(default=None),
    current_user: Optional[UserModel] = Depends(get_optional_user),
):
    """Trigger live multi-agent AI debate (Bull vs Bear vs Judge) for NIFTY or BANKNIFTY."""
    target_symbol = symbol or (req.symbol if req else "NIFTY")
    try:
        session = await debate_engine.run_debate(
            target_symbol, user_id=current_user.id if current_user else None
        )
        return session
    except Exception as exc:
        logger.error("Debate execution failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"AI Debate failed: {str(exc)}")


@app.get("/api/debate/latest")
async def get_latest_debate_endpoint(
    symbol: Optional[str] = Query(default=None),
    current_user: Optional[UserModel] = Depends(get_optional_user),
):
    """The signed-in user's latest debate (never triggers a new debate)."""
    return debate_engine.get_latest_debate(symbol=symbol, user_id=current_user.id if current_user else None)


@app.get("/api/debate/history")
async def get_debate_history_endpoint(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: Optional[UserModel] = Depends(get_optional_user),
):
    """Historical AI debates; executed ones include their trade outcome (SL / target / P&L)."""
    return await debate_engine.get_history_with_outcomes(
        limit=limit, user_id=current_user.id if current_user else None
    )


@app.post("/api/debate/{debate_id}/execute")
async def execute_debate_verdict_endpoint(
    debate_id: str,
    req: Optional[DebateExecuteRequest] = None,
    current_user: Optional[UserModel] = Depends(get_optional_user),
):
    """Execute the Judge's recommended trade directly into the Paper Trading portfolio."""
    try:
        lots = req.lots if req else 1
        override = req.model_dump(exclude_none=True) if req else None
        if override is not None and set(override) <= {"lots"}:
            override = None
        result = await debate_engine.execute_verdict(
            debate_id=debate_id,
            lots=lots,
            override_payload=override,
            user_id=current_user.id if current_user else None,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to execute debate trade: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Trade execution failed: {str(exc)}")


# ── Auto-Debate Scheduler Endpoints ──────────────────────────────────────────
@app.post("/api/scheduler/start")
async def start_scheduler_endpoint(
    req: SchedulerStartRequest,
    current_user: Optional[UserModel] = Depends(get_optional_user),
):
    """Start automated periodic background debating (trades go to the caller's paper account)."""
    uid = current_user.id if current_user else None
    try:
        status = await get_scheduler().start(
            interval_minutes=req.interval_minutes,
            symbol=req.symbol,
            auto_execute=req.auto_execute,
            market_hours_only=req.market_hours_only,
            lots=req.lots,
            user_id=uid,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "started", "scheduler": get_scheduler().get_status(uid) if status else status}


@app.post("/api/scheduler/stop")
async def stop_scheduler_endpoint(current_user: Optional[UserModel] = Depends(get_optional_user)):
    """Stop automated periodic background debating (only the account that started it)."""
    uid = current_user.id if current_user else None
    try:
        await get_scheduler().stop(user_id=uid)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "stopped", "scheduler": get_scheduler().get_status(uid)}


@app.get("/api/scheduler/status")
async def get_scheduler_status_endpoint(current_user: Optional[UserModel] = Depends(get_optional_user)):
    """Scheduler status as seen by the caller (another account's schedule is reported as off)."""
    return get_scheduler().get_status(current_user.id if current_user else None)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
