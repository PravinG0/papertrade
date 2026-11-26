"""
TradeLab Paper Trading Execution and Portfolio Engine with Persistent SQLite Storage.

Provides:
- Virtual cash wallet with ₹10,00,000 starting capital per user.
- Order management: Market, Limit, and Stop-Loss orders (Buy/Sell CE & PE).
- Real-time Mark-to-Market (MTM) P&L calculator and position tracker.
- Automated Stop-Loss and Target monitoring.
- Closed trades journal and calendar heatmap analytics persistently saved in SQLite.
"""

from __future__ import annotations


import asyncio
import logging
import math
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import INDEX_CONFIG, get_index_spec, get_session_bounds, normalize_index_symbol, settings, is_trading_day
from database import PaperTradeModel, PortfolioModel, PendingOrderModel, AppKVModel, AITradeEvidenceModel, async_session_factory
from adaptive_memory import parse_time
from wallet_accounting import wallet_accounting, position_margin

logger = logging.getLogger("paper_engine")
IST = ZoneInfo("Asia/Kolkata")


# ── Statutory charge rates for index OPTIONS (premium turnover) ─────────────────────────────
# Rates change: re-check against NSE/BSE circulars and the Finance Act before relying on net P&L.
#   STT        0.15% of premium on the SELL side only       (Budget 2026, effective 1 Apr 2026;
#                                                            was 0.10% from 1 Oct 2024)
#   Exchange   NSE index options 0.03553% of premium per side (NSE circular FA73061, from 1 Mar 2026,
#              includes the 0.0001% investor-protection fund);
#              BSE (SENSEX) options 0.0325% per side          (BSE, from 1 Oct 2024)
#   SEBI fee   Rs 10 per crore (0.0001%)
#   Stamp duty 0.003% of premium on the BUY side only
#   GST        18% on brokerage + exchange charge + SEBI fee
#   Brokerage  flat Rs 20 per executed order (Angel One)
STT_OPTIONS_SELL = 0.0015
EXCHANGE_CHARGE_RATE = {"NSE": 0.0003553, "BSE": 0.000325}
SEBI_FEE_RATE = 0.000001
STAMP_DUTY_BUY = 0.00003
GST_RATE = 0.18
BROKERAGE_PER_ORDER = 20.0


def calculate_trade_charges(
    buy_turnover: float,
    sell_turnover: float,
    orders_count: int = 2,
    underlying: str = "NIFTY",
) -> dict[str, float]:
    """Realistic Indian broker and statutory charges for one round trip in index options."""
    exch = "BSE" if normalize_index_symbol(underlying) == "SENSEX" else "NSE"
    brokerage = round(BROKERAGE_PER_ORDER * orders_count, 2)
    stt = round(sell_turnover * STT_OPTIONS_SELL, 2)
    tot_turnover = buy_turnover + sell_turnover
    exchange_charges = round(tot_turnover * EXCHANGE_CHARGE_RATE[exch], 2)
    sebi_charges = round(tot_turnover * SEBI_FEE_RATE, 2)
    stamp_duty = round(buy_turnover * STAMP_DUTY_BUY, 2)
    gst = round((brokerage + exchange_charges + sebi_charges) * GST_RATE, 2)

    total_charges = round(brokerage + stt + exchange_charges + sebi_charges + stamp_duty + gst, 2)
    return {
        "brokerage": brokerage,
        "stt": stt,
        "exchange_charges": exchange_charges,
        "sebi_charges": sebi_charges,
        "stamp_duty": stamp_duty,
        "gst": gst,
        "total_charges": total_charges,
    }


def compute_drawdown(closed_trades: list[dict[str, Any]], starting_capital: float) -> tuple[float, float]:
    """Compute max drawdown in currency and percentage from trade history."""
    if not closed_trades:
        return 0.0, 0.0
    equity = starting_capital
    peak = starting_capital
    max_dd = 0.0
    max_dd_pct = 0.0

    sorted_trades = sorted(closed_trades, key=lambda t: t.get("exit_time", "") or t.get("closed_at", ""))
    for t in sorted_trades:
        equity += t.get("realized_pnl", 0.0)
        if equity > peak:
            peak = equity
        dd = peak - equity
        dd_pct = (dd / peak) * 100.0 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    return round(max_dd, 2), round(max_dd_pct, 2)


class PaperEngine:
    """Paper Trading Engine with MTM tracking and SQLite persistence."""

    _instance: Optional[PaperEngine] = None

    def __init__(self, initial_capital: float = 1000000.0) -> None:
        self.initial_capital = initial_capital
        # Active in-memory tracking for real-time MTM and fast order management
        self.active_positions: dict[str, dict[str, Any]] = {}  # pos_id -> Position
        self.active_orders: dict[str, dict[str, Any]] = {}     # order_id -> Order
        self._lock = asyncio.Lock()
        self._change_callbacks: list[Any] = []

    def register_change_callback(self, cb: Any) -> None:
        if cb not in self._change_callbacks:
            self._change_callbacks.append(cb)

    async def _notify_change(self, user_id: Optional[int] = None) -> None:
        for cb in list(self._change_callbacks):
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.create_task(cb(user_id))
                else:
                    cb(user_id)
            except Exception as exc:
                logger.debug("Change callback error: %s", exc)

    @classmethod
    def get_instance(cls) -> PaperEngine:
        if cls._instance is None:
            cls._instance = cls(initial_capital=getattr(settings, "VIRTUAL_STARTING_CAPITAL", 1000000.0))
        return cls._instance

    def _now_ist(self) -> str:
        return datetime.now(tz=IST).strftime("%Y-%m-%d %H:%M:%S")

    def _today_date(self) -> str:
        return datetime.now(tz=IST).strftime("%Y-%m-%d")

    async def _get_or_create_portfolio(self, session: AsyncSession, user_id: Optional[int]) -> PortfolioModel:
        """Fetch or initialize persistent user portfolio in database."""
        if user_id is not None:
            stmt = select(PortfolioModel).where(PortfolioModel.user_id == user_id)
        else:
            stmt = select(PortfolioModel).where(PortfolioModel.user_id.is_(None))

        port = (await session.execute(stmt)).scalars().first()
        if not port:
            candidate = PortfolioModel(
                user_id=user_id,
                initial_capital=self.initial_capital,
                cash_balance=self.initial_capital,
                margin_used=0.0,
                updated_at=self._now_ist(),
            )
            try:
                async with session.begin_nested():
                    session.add(candidate)
                await session.commit()
                await session.refresh(candidate)
                port = candidate
            except IntegrityError:
                port = (await session.execute(stmt)).scalars().first()
                if port is None:
                    raise
        return port

    @staticmethod
    def _owner(model, user_id):
        return model.user_id.is_(None) if user_id is None else model.user_id == user_id

    async def _lock_portfolio(self, session, user_id):
        # UPDATE acquires a PostgreSQL row lock or SQLite writer lock until commit.
        # Acquire before reading balances/trade status; refresh any cached ORM values.
        result = await session.execute(update(PortfolioModel).where(self._owner(PortfolioModel, user_id))
                                       .values(updated_at=PortfolioModel.updated_at))
        port = await self._get_or_create_portfolio(session, user_id)
        if result.rowcount == 0:
            await session.execute(update(PortfolioModel).where(PortfolioModel.id == port.id)
                                  .values(updated_at=PortfolioModel.updated_at))
        await session.refresh(port)
        return port

    async def _active_margin(self, session, user_id):
        await session.flush()
        rows = (await session.execute(select(PaperTradeModel).where(
            self._owner(PaperTradeModel, user_id), PaperTradeModel.status == "ACTIVE"))).scalars().all()
        return position_margin([row.to_dict() for row in rows])

    async def restore_from_db(self) -> None:
        """Restore active positions from SQLite into memory on server startup."""
        try:
            async with async_session_factory() as session:
                stmt = select(PaperTradeModel).where(PaperTradeModel.status == "ACTIVE")
                res = await session.execute(stmt)
                trades = res.scalars().all()
                pending = (await session.execute(select(PendingOrderModel))).scalars().all()
                restored_orders = {}
                for row in pending:
                    order = json.loads(row.payload)
                    if order.get("replay") or not str(order.get("timestamp", "")).startswith(self._today_date()):
                        await session.delete(row)
                    else:
                        restored_orders[row.id] = order
                await session.commit()
                async with self._lock:
                    self.active_orders.update(restored_orders)
                    for t in trades:
                        td = t.to_dict()
                        td["trade_status"] = "OPEN"
                        self.active_positions[t.id] = td
                logger.info("Restored %d active paper positions from DB.", len(trades))
        except Exception as exc:
            logger.warning("Could not restore active positions from DB: %s", exc)

    async def get_state(self, user_id: Optional[int] = None, *, include_history: bool = True) -> dict[str, Any]:
        """Return full (or lightweight aggregate when include_history=False) snapshot of trading account."""
        async with self._lock:
            async with async_session_factory() as session:
                port = await self._get_or_create_portfolio(session, user_id)
                # Read wallet, reset baseline and trade rows in one SQL statement.
                snapshot = (await session.execute(select(PortfolioModel, PaperTradeModel, AppKVModel)
                    .select_from(PortfolioModel)
                    .outerjoin(PaperTradeModel, self._owner(PaperTradeModel, user_id))
                    .outerjoin(AppKVModel, AppKVModel.key == f"wallet-reset-baseline:{port.id}")
                    .where(PortfolioModel.id == port.id)
                    .execution_options(populate_existing=True))).all()
                port, _, baseline_record = snapshot[0]
                cash_balance = port.cash_balance
                stored_margin = port.margin_used
                initial_capital = port.initial_capital
                reset_baseline = float(baseline_record.value) if baseline_record else 0.0
                rows = [row.to_dict() for _, row, _ in snapshot if row is not None]
                pending = (await session.execute(select(PendingOrderModel).where(self._owner(PendingOrderModel, user_id)))).scalars().all()
                user_orders = [json.loads(row.payload) for row in pending]

            today_str = self._today_date()
            user_positions = []
            closed_trades = []
            for row in rows:
                if row["status"] == "ACTIVE":
                    cached = self.active_positions.get(row["id"])
                    if cached and cached.get("user_id") == user_id:
                        for key in ("current_ltp", "ltp", "live_price", "unrealized_pnl", "pnl", "quote_stale"):
                            if key in cached:
                                row[key] = cached[key]
                    row["stale_prior_day"] = str(row.get("created_at", ""))[:10] < today_str
                    user_positions.append(row)
                elif row["status"] == "CLOSED":
                    closed_trades.append(row)
            closed_trades.sort(key=lambda t: t.get("closed_at") or "", reverse=True)
            used_margin = position_margin(user_positions)

            # Combined chronological list of ALL executed trades (open + completed)
            all_trades = (list(user_positions) + list(closed_trades)) if include_history else []
            if include_history:
                all_trades.sort(
                    key=lambda t: t.get("entry_time") or t.get("created_at") or "",
                    reverse=True,
                )

            unrealized_pnl = sum(p.get("unrealized_pnl", 0.0) for p in user_positions)
            realized_pnl = sum(t.get("realized_pnl", 0.0) for t in closed_trades)
            gross_realized_pnl = sum(t.get("gross_pnl", t.get("realized_pnl", 0.0)) for t in closed_trades)
            total_charges = sum(t.get("total_charges", 0.0) for t in closed_trades)
            total_pnl = round(realized_pnl + unrealized_pnl, 2)

            today_realized = sum(
                t.get("realized_pnl", 0.0)
                for t in closed_trades
                if (t.get("exit_time") or t.get("closed_at") or "").startswith(today_str)
            )
            today_pnl = round(today_realized + unrealized_pnl, 2)

            accounting = wallet_accounting(initial_capital, cash_balance, used_margin, realized_pnl, unrealized_pnl, reset_baseline)
            total_trades = len(closed_trades)
            profit_trades = [t for t in closed_trades if t.get("realized_pnl", 0.0) > 0]
            loss_trades = [t for t in closed_trades if t.get("realized_pnl", 0.0) < 0]
            winning_trades = len(profit_trades)
            losing_trades = len(loss_trades)
            win_rate = round((winning_trades / total_trades) * 100, 1) if total_trades > 0 else 0.0

            gross_profit = sum(t.get("realized_pnl", 0.0) for t in profit_trades)
            gross_loss = abs(sum(t.get("realized_pnl", 0.0) for t in loss_trades))
            profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 1.0)
            avg_win = round(gross_profit / winning_trades, 2) if winning_trades > 0 else 0.0
            avg_loss = round(gross_loss / losing_trades, 2) if losing_trades > 0 else 0.0
            max_dd, max_dd_pct = compute_drawdown(closed_trades, initial_capital)

            sl_hit_count = len([t for t in closed_trades if t.get("exit_reason") == "STOP_LOSS_HIT"])
            target_hit_count = len([t for t in closed_trades if t.get("exit_reason") == "TARGET_HIT"])
            manual_exit_count = len([t for t in closed_trades if t.get("exit_reason") in ("MANUAL_EXIT", "EXIT_ALL", "AUTO_SQUAREOFF_315PM", "WALLET_RESET")])

            wallet_dict = {
                "initial_capital": initial_capital,
                "capital": round(cash_balance, 2),
                "cash_balance": round(cash_balance, 2),
                "available_margin": round(cash_balance, 2),
                "used_margin": round(used_margin, 2),
                "stored_margin": round(stored_margin, 2),
                "margin_discrepancy": round(stored_margin - used_margin, 2),
                "margin_model": "simplified_premium_reserve",
                **accounting,
                "realized_pnl": round(realized_pnl, 2),
                "gross_realized_pnl": round(gross_realized_pnl, 2),
                "total_charges": round(total_charges, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "total_pnl": total_pnl,
                "today_pnl": today_pnl,
            }

            return {
                "wallet": wallet_dict,
                "portfolio": wallet_dict,
                "positions": user_positions,
                "closed_positions": closed_trades if include_history else [],
                "recent_closed_positions": closed_trades[:50] if include_history else [],
                "all_trades": all_trades,
                "history_omitted": not include_history,
                "active_orders": user_orders,
                "orders": user_orders,
                "statistics": {
                    "total_trades": total_trades,
                    "total_executed_trades": len(user_positions) + total_trades,
                    "winning_trades": winning_trades,
                    "losing_trades": losing_trades,
                    "win_rate": win_rate,
                    "profit_factor": profit_factor,
                    "average_win": avg_win,
                    "average_loss": avg_loss,
                    "max_drawdown": max_dd,
                    "max_drawdown_pct": max_dd_pct,
                    "total_charges": round(total_charges, 2),
                    "open_positions_count": len(user_positions),
                    "sl_hit_count": sl_hit_count,
                    "target_hit_count": target_hit_count,
                    "manual_exit_count": manual_exit_count,
                    "pending_orders_count": len(user_orders),
                },
                "timestamp": self._now_ist(),
            }

    @staticmethod
    def entry_window_open() -> bool:
        """Intraday entries allowed Mon-Fri 09:15-15:15 IST (respecting configured holidays and special sessions)."""
        if getattr(settings, "ALLOW_OFFHOURS_TRADING", False):
            return True
        now = datetime.now(tz=IST)
        bounds = get_session_bounds(now)
        if not bounds:
            return False
        start_t, end_t = bounds
        # Stop entries 15 minutes before session close for intraday square-off
        close_dt = datetime.combine(now.date(), end_t, tzinfo=IST) - timedelta(minutes=15)
        return start_t <= now.time() < close_dt.time()

    async def place_order(
        self,
        order_req: dict[str, Any],
        user_id: Optional[int] = None,
        enforce_hours: bool = True,
        *, ai_evidence: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Place a paper trade order (Market, Limit, SL) linked to user."""
        if order_req.get("replay"):
            return {"status": "REJECTED", "reject_reason": "Replay playback is available; replay trading is paused until an isolated ledger is implemented."}
        if (
            enforce_hours
            and not self.entry_window_open()
        ):
            return {
                "status": "REJECTED",
                "user_id": user_id,
                "reject_reason": (
                    "Market is closed. Intraday paper trades can be opened Mon-Fri 09:15-15:15 IST "
                    "(all positions are auto-squared-off at 15:15)."
                ),
            }
        async with self._lock:
            from replay_engine import replay_engine
            if replay_engine.is_replaying:
                return {"status": "REJECTED", "reject_reason": "Live orders are blocked during playback."}
            uid = user_id if user_id is not None else order_req.get("user_id")
            symbol = str(order_req.get("symbol", "")).strip().upper()
            underlying = normalize_index_symbol(order_req.get("underlying", "NIFTY"))
            spec = get_index_spec(underlying)
            lot_size = int(order_req.get("lot_size") or spec["lot_size"])

            def _safe_float(val, default=0.0):
                if val is None:
                    return default
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return default

            lots = max(1, int(order_req.get("lots") or 1))
            quantity = lots * lot_size
            side = str(order_req.get("side") or "BUY").strip().upper()  # BUY or SELL
            order_type = str(order_req.get("order_type") or "MARKET").strip().upper()  # MARKET, LIMIT, SL
            strike = _safe_float(order_req.get("strike"), 0.0)
            option_type = str(order_req.get("option_type") or "CE").strip().upper()

            price = _safe_float(order_req.get("price"), 0.0)
            trigger_price = _safe_float(order_req.get("trigger_price"), 0.0)
            current_ltp = _safe_float(order_req.get("current_ltp"), price if price > 0 else 0.0)
            stop_loss = _safe_float(order_req.get("stop_loss")) if order_req.get("stop_loss") is not None else None
            target = _safe_float(order_req.get("target")) if order_req.get("target") is not None else None

            numeric = [strike, price, trigger_price, current_ltp] + [v for v in (stop_loss, target) if v is not None]
            if (not all(math.isfinite(v) and v >= 0 for v in numeric)
                or strike <= 0 or lot_size <= 0 or side not in ("BUY", "SELL")
                or option_type not in ("CE", "PE") or order_type not in ("MARKET", "LIMIT", "SL")
                or (order_type == "MARKET" and max(price, current_ltp) <= 0)
                or (order_type == "LIMIT" and price <= 0)
                or (order_type == "SL" and trigger_price <= 0)):
                return {"status": "REJECTED", "reject_reason": "Invalid order parameters or price."}
            if side == "SELL" and not getattr(settings, "ALLOW_SHORT_OPTIONS", True):
                return {"status": "REJECTED", "reject_reason": "Short option orders are disabled (ALLOW_SHORT_OPTIONS=false) because clearing margin is unavailable."}

            # Generate unique Order ID
            order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
            now_time = self._now_ist()

            order_record = {
                "order_id": order_id,
                "user_id": uid,
                "timestamp": now_time,
                "symbol": symbol or f"{underlying}{strike}{option_type}",
                "underlying": underlying,
                "strike": strike,
                "option_type": option_type,
                "lots": lots,
                "lot_size": lot_size,
                "quantity": quantity,
                "side": side,
                "order_type": order_type,
                "price": price,
                "trigger_price": trigger_price,
                "stop_loss": stop_loss,
                "target": target,
                "status": "PENDING",
                "replay": bool(order_req.get("replay")),
            }

            # Check execution
            if order_type == "MARKET":
                fill_price = current_ltp if current_ltp > 0 else price
                required_margin = round(fill_price * quantity, 2)

                async with async_session_factory() as session:
                    port = await self._get_or_create_portfolio(session, uid)
                    cash_balance = port.cash_balance

                if required_margin > cash_balance:
                    order_record["status"] = "REJECTED"
                    order_record["reject_reason"] = f"Insufficient margin. Required: ₹{required_margin:.2f}, Available: ₹{cash_balance:.2f}"
                    return order_record

                return await self._execute_fill(order_record, fill_price, now_time, user_id=uid, ai_evidence=ai_evidence)
            else:
                # Add to active pending orders
                async with async_session_factory() as session:
                    await self._lock_portfolio(session, uid)
                    session.add(PendingOrderModel(id=order_id, user_id=uid, payload=json.dumps(order_record)))
                    await session.commit()
                self.active_orders[order_id] = order_record
                await self._notify_change(uid)
                return order_record

    async def _execute_fill(
        self,
        order: dict[str, Any],
        fill_price: float,
        fill_time: str,
        user_id: Optional[int] = None,
        *, ai_evidence: Optional[dict[str, Any]] = None, require_pending: bool = False,
    ) -> dict[str, Any]:
        """Internal helper to fill order, update wallet in DB, and create persistent active trade."""
        uid = user_id if user_id is not None else order.get("user_id")
        order["user_id"] = uid

        quantity = order["quantity"]
        side = order["side"]
        fill_price = round(fill_price, 2)
        order_cost = round(fill_price * quantity, 2)

        # Create Position
        pos_id = f"POS-{uuid.uuid4().hex[:8].upper()}"
        stop_loss_val = round(float(order["stop_loss"]), 2) if order.get("stop_loss") is not None else None
        target_val = round(float(order["target"]), 2) if order.get("target") is not None else None

        position = {
            "id": pos_id,
            "pos_id": pos_id,
            "position_id": pos_id,
            "order_id": order["order_id"],
            "user_id": uid,
            "symbol": order["symbol"],
            "underlying": order["underlying"],
            "strike": order["strike"],
            "option_type": order["option_type"],
            "side": side,
            "lots": order["lots"],
            "lot_size": order["lot_size"],
            "quantity": quantity,
            "entry_price": round(fill_price, 2),
            "exit_price": None,
            "current_ltp": round(fill_price, 2),
            "ltp": round(fill_price, 2),
            "live_price": round(fill_price, 2),
            "unrealized_pnl": 0.0,
            "pnl": 0.0,
            "realized_pnl": 0.0,
            "gross_pnl": 0.0,
            "total_charges": 0.0,
            "status": "ACTIVE",
            "trade_status": "OPEN",
            "stop_loss": stop_loss_val,
            "target": target_val,
            "exit_reason": None,
            "entry_time": fill_time,
            "created_at": fill_time,
            "exit_time": "",
            "closed_at": None,
            "pnl_pct": 0.0,
        }

        # Update wallet cash & used margin in SQLite DB
        async with async_session_factory() as session:
            port = await self._lock_portfolio(session, uid)
            if ai_evidence:
                from adaptive_store import guard_auto_fill
                from adaptive_memory import trend_rejection
                reason = None
                if uid is None:
                    reason = "AI fills require a signed-in account."
                elif await session.get(AITradeEvidenceModel, ai_evidence["debate_id"]):
                    reason = "This debate verdict already has a durable fill."
                elif ai_evidence.get("auto_executed"):
                    if not self.entry_window_open():
                        return {**order, "status": "REJECTED", "reject_reason": "Market entry window closed before fill."}
                    snap = ai_evidence["snapshot"]
                    if snap.get('quant_version') == 'quant-v1':
                        check = snap.get('execution_validation') or {}
                        stamp = parse_time(check.get('quote_exchange_timestamp'))
                        spot_stamp = parse_time(snap.get('spot_exchange_timestamp'))
                        from quant_engine import snapshot_frames_current
                        fill_now = datetime.now(IST)
                        if (not check.get('eligible') or not stamp or not spot_stamp
                            or not all(0 <= (fill_now-t).total_seconds() <= 30 for t in (stamp,spot_stamp))
                            or not snapshot_frames_current(snap, fill_now, get_session_bounds)):
                            return {**order, "status":"REJECTED", "reject_reason":"Validated option quote expired before database fill."}
                    reason = trend_rejection(snap, order["option_type"], settings.AUTO_TREND_THRESHOLD_PCT)
                    if not reason:
                        reason = await guard_auto_fill(session, uid, order)
                if reason:
                    return {**order, "status": "REJECTED", "reject_reason": reason}
            # BUY pays the premium; SELL blocks the same amount as margin. Both are released on
            # exit together with the realised P&L, so the wallet always reconciles.
            pending = await session.get(PendingOrderModel, order["order_id"])
            if require_pending and (pending is None or pending.user_id != uid):
                return {**order, "status": "REJECTED", "reject_reason": "Pending order already filled or cancelled."}
            if pending is not None:
                await session.delete(pending)
            if not math.isfinite(fill_price) or fill_price <= 0 or order_cost > port.cash_balance:
                await session.commit()
                order["status"] = "REJECTED"
                order["reject_reason"] = "Invalid fill price or insufficient available balance."
                await self._notify_change(uid)
                return order
            port.cash_balance = round(port.cash_balance - order_cost, 2)
            port.updated_at = fill_time

            # Record active trade in SQLite DB
            db_trade = PaperTradeModel(
                id=pos_id,
                user_id=uid,
                symbol=order["symbol"],
                underlying=order["underlying"],
                strike=order["strike"],
                option_type=order["option_type"],
                side=side,
                lots=order["lots"],
                quantity=quantity,
                entry_price=round(fill_price, 2),
                current_ltp=round(fill_price, 2),
                pnl=0.0,
                gross_pnl=0.0,
                realized_pnl=0.0,
                total_charges=0.0,
                status="ACTIVE",
                stop_loss=stop_loss_val,
                target=target_val,
                pnl_pct=0.0,
                created_at=fill_time,
            )
            session.add(db_trade)
            port.margin_used = await self._active_margin(session, uid)
            if ai_evidence:
                await session.flush()
                session.add(AITradeEvidenceModel(
                    debate_id=ai_evidence["debate_id"], position_id=pos_id, user_id=uid,
                    auto_executed=int(bool(ai_evidence.get("auto_executed"))),
                    snapshot=json.dumps(ai_evidence["snapshot"]), confidence=ai_evidence["confidence"],
                    created_at=fill_time,
                ))
            await session.commit()

        self.active_positions[pos_id] = position
        order.update(status="EXECUTED", filled_price=round(fill_price, 2), filled_time=fill_time)
        order["position_id"] = pos_id
        await self._notify_change(uid)
        logger.info(
            "Order %s filled: %s %d qty %s @ ₹%.2f (user_id=%s)",
            order["order_id"], side, quantity, order["symbol"], fill_price, uid,
        )
        return order

    async def cancel_order(self, order_id: str, user_id: Optional[int] = None) -> dict[str, Any]:
        """Cancel a pending paper trade order."""
        async with self._lock:
            if order_id in self.active_orders:
                order = self.active_orders[order_id]
                if order.get("user_id") != user_id:
                    return {"status": "ERROR", "message": f"Order {order_id} not found or already filled."}
                async with async_session_factory() as session:
                    await self._lock_portfolio(session, user_id)
                    row = await session.get(PendingOrderModel, order_id)
                    if row is None or row.user_id != user_id:
                        self.active_orders.pop(order_id, None)
                        return {"status": "ERROR", "message": "Order no longer pending."}
                    await session.delete(row)
                    await session.commit()
                self.active_orders.pop(order_id)
                order["status"] = "CANCELLED"
                order["cancelled_time"] = self._now_ist()
                await self._notify_change(user_id)
                logger.info("Order %s cancelled.", order_id)
                return {"status": "SUCCESS", "order": order}
            return {"status": "ERROR", "message": f"Order {order_id} not found or already filled."}

    async def exit_all_positions(
        self, reason: str = "EXIT_ALL", user_id: Optional[int] = None, system: bool = False
    ) -> list[dict[str, Any]]:
        """Close all of ONE account's positions (guest = its own account), or every account's
        when called by the system itself (system=True, e.g. the 15:15 auto square-off)."""
        results = []
        targets = [
            (pid, pos.get("user_id")) for pid, pos in list(self.active_positions.items())
            if system or pos.get("user_id") == user_id
        ]
        for pid, owner in targets:
            res = await self.exit_position(pid, reason=reason, user_id=owner, system=system)
            results.append(res)
        return results

    async def exit_position(
        self,
        pos_id: str,
        exit_price: Optional[float] = None,
        reason: str = "MANUAL_EXIT",
        user_id: Optional[int] = None,
        system: bool = False,
    ) -> dict[str, Any]:
        """Close an active paper trade position and persist trade outcome to DB.

        Only the owning account can close it (guest positions belong to the guest account);
        system=True is for the engine's own exits (e.g. auto square-off).
        """
        async with self._lock:
            return await self._settle_position(pos_id, exit_price, reason, user_id, system)

    async def _settle_position(self, pos_id, exit_price, reason, user_id, system=False):
        """One settlement path for all exits; caller holds the process lock."""
        not_found = {"status": "ERROR", "message": f"Position {pos_id} not found or already closed."}
        cached = self.active_positions.get(pos_id)
        if cached and not system and cached.get("user_id") != user_id:
            return not_found
        async with async_session_factory() as session:
            # Resolve owner before locking; re-read status after the wallet lock.
            uid = cached.get("user_id") if cached else user_id
            if system and cached is None:
                row = await session.get(PaperTradeModel, pos_id)
                if row is None:
                    return not_found
                uid = row.user_id
            port = await self._lock_portfolio(session, uid)
            trade = (await session.execute(select(PaperTradeModel).where(
                PaperTradeModel.id == pos_id, self._owner(PaperTradeModel, uid),
                PaperTradeModel.status == "ACTIVE").execution_options(populate_existing=True))).scalars().first()
            if trade is None:
                if cached and cached.get("user_id") == uid:
                    self.active_positions.pop(pos_id, None)
                return not_found
            price = exit_price if exit_price is not None else (cached or {}).get("current_ltp", trade.current_ltp)
            if not math.isfinite(price) or price <= 0 or round(price, 2) <= 0:
                return {"status": "ERROR", "message": "Invalid exit price."}
            exit_p = round(price, 2)
            entry = trade.entry_price
            quantity = trade.quantity
            premium = round(entry * quantity, 2)
            exit_turnover = round(exit_p * quantity, 2)
            buy, sell = (premium, exit_turnover) if trade.side == "BUY" else (exit_turnover, premium)
            gross = round(sell - buy, 2)
            charges = calculate_trade_charges(buy, sell, underlying=trade.underlying)
            realized = round(gross - charges["total_charges"], 2)
            now = self._now_ist()
            trade.status = "CLOSED"
            trade.exit_price = trade.current_ltp = exit_p
            trade.gross_pnl = gross
            trade.realized_pnl = trade.pnl = realized
            trade.total_charges = charges["total_charges"]
            trade.closed_at = now
            trade.exit_reason = reason
            trade.pnl_pct = round(realized / premium * 100, 2) if premium else 0.0
            port.cash_balance = round(port.cash_balance + premium + realized, 2)
            port.margin_used = await self._active_margin(session, uid)
            port.updated_at = now
            record = trade.to_dict()
            record["charges"] = charges
            await session.commit()
        self.active_positions.pop(pos_id, None)
        await self._notify_change(uid)
        return {"status": "SUCCESS", "message": f"Position {pos_id} exited @ ₹{exit_p:.2f}",
                "realized_pnl": realized, "gross_pnl": gross, "charges": charges,
                "exit_price": exit_p, "trade": record}

    async def check_intraday_squareoff(
        self, current_time_str: Optional[str] = None, only_user: Optional[int] = None,
        *, fresh_quotes: Optional[dict[str, float]] = None
    ) -> list[dict[str, Any]]:
        """Auto square off intraday MIS positions at 15:15 IST."""
        if not self.active_positions:
            return []
        if getattr(settings, "ALLOW_OFFHOURS_TRADING", False) and not current_time_str:
            return []  # testing mode: no automatic square-off
        t_check = current_time_str
        if not t_check:
            now_dt = datetime.now(tz=IST)
            t_check = now_dt.strftime("%H:%M:%S")
        if t_check >= "15:15:00":
            logger.info("Auto-squareoff triggered at %s for %d active positions", t_check, len(self.active_positions))
            if current_time_str is not None:
                # Replay clock: never touch anyone else's real positions
                return await self.exit_all_positions(reason="AUTO_SQUAREOFF_315PM", user_id=only_user)
            # Never settle a live position using a restored entry price or stale cache.
            now = datetime.now(IST)
            if not is_trading_day(now) or t_check >= "15:30:00":
                return []
            results = []
            for pid, pos in list(self.active_positions.items()):
                price = (fresh_quotes or {}).get(pos["symbol"])
                if price is None or not math.isfinite(price) or price <= 0:
                    logger.warning("Square-off deferred for %s: current quote unavailable", pid)
                    continue
                results.append(await self.exit_position(pid, exit_price=price,
                    reason="AUTO_SQUAREOFF_315PM", user_id=pos.get("user_id"), system=True))
            return results
        return []

    async def update_sl(
        self,
        pos_id: str,
        stop_loss: Optional[float] = None,
        target: Optional[float] = None,
        user_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """Modify stop loss and/or target for an active position."""
        async with self._lock:
            if pos_id not in self.active_positions:
                return {"status": "ERROR", "message": f"Position {pos_id} not found."}

            pos = self.active_positions[pos_id]
            if pos.get("user_id") != user_id:
                return {"status": "ERROR", "message": f"Position {pos_id} not found."}

            if any(v is not None and (not math.isfinite(v) or v < 0) for v in (stop_loss, target)):
                return {"status": "ERROR", "message": "Invalid stop loss or target."}
            async with async_session_factory() as session:
                await self._lock_portfolio(session, user_id)
                db_trade = await session.get(PaperTradeModel, pos_id)
                if db_trade is None or db_trade.user_id != user_id or db_trade.status != "ACTIVE":
                    return {"status": "ERROR", "message": "Position no longer active."}
                if stop_loss is not None:
                    db_trade.stop_loss = round(stop_loss, 2)
                if target is not None:
                    db_trade.target = round(target, 2)
                await session.commit()
            if stop_loss is not None:
                pos["stop_loss"] = round(stop_loss, 2)
            if target is not None:
                pos["target"] = round(target, 2)

            await self._notify_change(user_id)
            return {"status": "SUCCESS", "position": pos}

    async def reset_portfolio(self, initial_capital: float = 1000000.0, user_id: Optional[int] = None) -> dict[str, Any]:
        """Reset virtual paper trading wallet back to initial virtual funds in DB."""
        async with self._lock:
            # Clear active positions in memory for this user
            pids_to_remove = [
                pid for pid, pos in self.active_positions.items()
                if pos.get("user_id") == user_id
            ]

            # Clear active orders in memory for this user
            oids_to_remove = [
                oid for oid, ord_rec in self.active_orders.items()
                if ord_rec.get("user_id") == user_id
            ]

            # Update portfolio in SQLite DB
            async with async_session_factory() as session:
                port = await self._lock_portfolio(session, user_id)
                port.initial_capital = initial_capital
                port.cash_balance = initial_capital
                port.margin_used = 0.0
                port.updated_at = self._now_ist()

                order_owner = PendingOrderModel.user_id.is_(None) if user_id is None else PendingOrderModel.user_id == user_id
                pending = (await session.execute(select(PendingOrderModel).where(order_owner))).scalars().all()
                for row in pending:
                    await session.delete(row)
                # Close this account's still-open DB positions too, or they would be restored
                # (and re-tracked) the next time the server restarts.
                owner = PaperTradeModel.user_id.is_(None) if user_id is None else PaperTradeModel.user_id == user_id
                stale = (await session.execute(
                    select(PaperTradeModel).where(PaperTradeModel.status == "ACTIVE", owner)
                )).scalars().all()
                for t in stale:
                    t.status = "CLOSED"
                    t.exit_reason = "WALLET_RESET"
                    t.exit_price = t.entry_price
                    t.current_ltp = t.entry_price
                    t.gross_pnl = t.realized_pnl = t.pnl = t.total_charges = t.pnl_pct = 0.0
                    t.closed_at = self._now_ist()
                await session.flush()
                # Keep the historic ledger but exclude pre-reset realized P&L from the new cycle.
                from sqlalchemy import func
                baseline = (await session.execute(select(func.coalesce(func.sum(PaperTradeModel.realized_pnl), 0.0)).where(owner, PaperTradeModel.status == "CLOSED"))).scalar_one()
                key = f"wallet-reset-baseline:{port.id}"
                record = await session.get(AppKVModel, key)
                if record is None:
                    session.add(AppKVModel(key=key, value=str(float(baseline))))
                else:
                    record.value = str(float(baseline))
                await session.commit()

            for pid in pids_to_remove:
                self.active_positions.pop(pid, None)
            for oid in oids_to_remove:
                self.active_orders.pop(oid, None)
            logger.info("Paper trading wallet reset to ₹%.2f (user_id=%s)", initial_capital, user_id)
            await self._notify_change(user_id)
            return {
                "status": "SUCCESS",
                "message": f"Portfolio reset to ₹{initial_capital:,.2f}",
                "wallet": {
                    "initial_capital": initial_capital,
                    "cash_balance": initial_capital,
                    "available_margin": initial_capital,
                    "used_margin": 0.0,
                },
            }

    async def get_history(
        self,
        user_id: Optional[int] = None,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        status_filter: Optional[str] = None,
        underlying: Optional[str] = None,
        search: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return closed trades journal from DB, supporting optional server-side filters and pagination."""
        async with async_session_factory() as session:
            stmt = select(PaperTradeModel).where(
                PaperTradeModel.status == "CLOSED",
                self._owner(PaperTradeModel, user_id),
            )
            if underlying:
                stmt = stmt.where(PaperTradeModel.underlying == normalize_index_symbol(underlying))
            stmt = stmt.order_by(PaperTradeModel.closed_at.desc())
            res = await session.execute(stmt)
            items = [t.to_dict() for t in res.scalars().all()]

        if any(v is not None and v != "" for v in (from_date, to_date, status_filter, search)):
            q = (search or "").strip().lower()
            st = (status_filter or "").strip().upper()
            filtered = []
            for t in items:
                dt = self._ist_date_str(t.get("closed_at") or t.get("exit_time") or "")
                if from_date and (not dt or dt < from_date[:10]):
                    continue
                if to_date and (not dt or dt > to_date[:10]):
                    continue
                if st and st != "ALL" and (t.get("trade_status") or t.get("status") or "").upper() != st:
                    continue
                if q and q not in (t.get("symbol") or "").lower() and q not in str(t.get("strike") or ""):
                    continue
                filtered.append(t)
            items = filtered
        if offset > 0:
            items = items[offset:]
        if limit is not None and limit >= 0:
            items = items[:limit]
        return items

    @staticmethod
    def _ist_date_str(value: Any) -> str:
        parsed = parse_time(value)
        if parsed is not None:
            return parsed.date().isoformat()
        return str(value or "")[:10]

    async def get_pnl_calendar(self, user_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Generate calendar heatmap data grouped by IST closing date from persistent DB."""
        trades = await self.get_history(user_id=user_id)
        daily_stats: dict[str, dict[str, Any]] = {}
        for t in trades:
            if t.get("exit_reason") == "REPLAY_STOPPED":
                continue
            exit_time = t.get("closed_at") or t.get("exit_time") or ""
            date_key = self._ist_date_str(exit_time)
            if not date_key:
                continue
            if date_key not in daily_stats:
                daily_stats[date_key] = {
                    "date": date_key,
                    "pnl": 0.0,
                    "trades_count": 0,
                    "wins": 0,
                    "losses": 0,
                }
            pnl = t.get("realized_pnl", 0.0)
            daily_stats[date_key]["pnl"] += pnl
            daily_stats[date_key]["trades_count"] += 1
            if pnl > 0:
                daily_stats[date_key]["wins"] += 1
            elif pnl < 0:
                daily_stats[date_key]["losses"] += 1

        calendar_data = []
        for d_key, data in sorted(daily_stats.items()):
            data["pnl"] = round(data["pnl"], 2)
            calendar_data.append(data)
        return calendar_data

    async def get_all_trades(self, user_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Return all trades (open active positions and closed history) for user or guest."""
        state = await self.get_state(user_id)
        all_t = state["all_trades"]
        return all_t

    async def get_daily_trades(
        self, date_str: Optional[str] = None, user_id: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Return all trades executed on or closed on date_str (default today YYYY-MM-DD)."""
        target_date = (date_str or self._today_date())[:10]
        all_t = await self.get_all_trades(user_id=user_id)
        daily = []
        for t in all_t:
            created = self._ist_date_str(t.get("created_at") or t.get("entry_time") or "")
            closed = self._ist_date_str(t.get("closed_at") or t.get("exit_time") or "")
            if closed == target_date:
                daily.append(t)
            elif created == target_date:
                if closed and closed > target_date:
                    # Earlier reports must not use a later closing outcome or price.
                    t = dict(t, status="ACTIVE", trade_status="OPEN", pnl_pct=0.0, closed_at=None, exit_time=None,
                             exit_price=None, exit_reason=None, gross_pnl=0.0,
                             realized_pnl=0.0, total_charges=0.0, unrealized_pnl=0.0,
                             pnl=0.0, current_ltp=t.get("entry_price"), ltp=t.get("entry_price"),
                             live_price=t.get("entry_price"))
                daily.append(t)
        return daily

    async def update_market_prices(self, quotes: dict[str, float], *, replay_owner: Optional[int] = None, replay: bool = False) -> None:
        """Update active positions MTM and execute pending SL / Target triggers."""
        async with self._lock:
            if not self.active_positions and not self.active_orders:
                return

            exited_positions: list[tuple[str, float, str, Optional[int]]] = []
            now_time = self._now_ist()

            # 1. Update Positions MTM and check SL/Target
            for pos_id, pos in list(self.active_positions.items()):
                if replay and (replay_owner is None or pos.get("user_id") != replay_owner):
                    continue
                sym = pos["symbol"]
                ltp = quotes.get(sym)
                if ltp is None:
                    alt_key = f"{pos['underlying']}{int(pos['strike'])}{pos['option_type']}"
                    if replay or sym == alt_key:
                        ltp = quotes.get(alt_key)

                if ltp is not None and math.isfinite(ltp) and ltp > 0:
                    pos["quote_stale"] = False
                    pos["current_ltp"] = round(ltp, 2)
                    pos["ltp"] = round(ltp, 2)
                    pos["live_price"] = round(ltp, 2)
                    side = pos["side"]
                    qty = pos["quantity"]

                    if side == "BUY":
                        unrealized = round((ltp - pos["entry_price"]) * qty, 2)
                    else:
                        unrealized = round((pos["entry_price"] - ltp) * qty, 2)
                    pos["unrealized_pnl"] = unrealized
                    pos["pnl"] = unrealized

                    if not replay:
                        # Durable last observed price and fresh DB SL/target sync (prevents stale worker trigger).
                        async with async_session_factory() as session:
                            await self._lock_portfolio(session, pos.get("user_id"))
                            row = (await session.execute(select(PaperTradeModel).where(
                                PaperTradeModel.id == pos_id).execution_options(populate_existing=True))).scalars().first()
                            if row is None or row.user_id != pos.get("user_id") or row.status != "ACTIVE":
                                self.active_positions.pop(pos_id, None)
                                continue
                            pos["stop_loss"] = round(row.stop_loss, 2) if row.stop_loss is not None else None
                            pos["target"] = round(row.target, 2) if row.target is not None else None
                            if row.current_ltp != pos["current_ltp"]:
                                row.current_ltp = pos["current_ltp"]
                                row.pnl = unrealized
                                await session.commit()
                    # Check Stop Loss trigger
                    sl = pos.get("stop_loss")
                    if sl is not None and sl > 0:
                        if (side == "BUY" and ltp <= sl) or (side == "SELL" and ltp >= sl):
                            exited_positions.append((pos_id, round(ltp, 2), "STOP_LOSS_HIT", pos.get("user_id")))
                            continue

                    # Check Target trigger
                    tgt = pos.get("target")
                    if tgt is not None and tgt > 0:
                        if (side == "BUY" and ltp >= tgt) or (side == "SELL" and ltp <= tgt):
                            exited_positions.append((pos_id, round(ltp, 2), "TARGET_HIT", pos.get("user_id")))
                            continue
                elif not replay:
                    pos["quote_stale"] = True

            # Use the same transactional settlement for SL, target and manual exits.
            for pos_id, exit_p, reason, uid in exited_positions:
                await self._settle_position(pos_id, exit_p, reason, uid)

            # 2. Check Pending Limit / Stop-Loss orders
            executed_orders: list[tuple[str, float]] = []
            for order_id, order in list(self.active_orders.items()):
                if replay and (replay_owner is None or order.get("user_id") != replay_owner):
                    continue
                if not replay and (order.get("replay") or not str(order.get("timestamp", "")).startswith(self._today_date())):
                    async with async_session_factory() as session:
                        await self._lock_portfolio(session, order.get("user_id"))
                        row = await session.get(PendingOrderModel, order_id)
                        if row is not None:
                            await session.delete(row)
                            await session.commit()
                    self.active_orders.pop(order_id, None)
                    await self._notify_change(order.get("user_id"))
                    continue
                if not replay and not self.entry_window_open():
                    continue
                sym = order["symbol"]
                ltp = quotes.get(sym)
                if ltp is None:
                    alt_key = f"{order['underlying']}{int(order['strike'])}{order['option_type']}"
                    if replay or sym == alt_key:
                        ltp = quotes.get(alt_key)

                if ltp is not None and math.isfinite(ltp) and ltp > 0:
                    order_type = order["order_type"]
                    side = order["side"]
                    limit_p = order["price"]
                    trig_p = order["trigger_price"]

                    should_fill = False
                    fill_p = ltp

                    if order_type == "LIMIT":
                        if side == "BUY" and ltp <= limit_p:
                            should_fill = True
                            fill_p = ltp
                        elif side == "SELL" and ltp >= limit_p:
                            should_fill = True
                            fill_p = ltp
                    elif order_type == "SL":
                        if side == "BUY" and ltp >= trig_p:
                            should_fill = True
                            fill_p = ltp
                        elif side == "SELL" and ltp <= trig_p:
                            should_fill = True
                            fill_p = ltp

                    if should_fill:
                        executed_orders.append((order_id, fill_p))

            for order_id, fill_p in executed_orders:
                order = self.active_orders.get(order_id)
                if order:
                    await self._execute_fill(order, fill_p, now_time, user_id=order.get("user_id"), require_pending=True)
                    self.active_orders.pop(order_id, None)
                    await self._notify_change(order.get("user_id"))


# Singleton accessor
paper_engine = PaperEngine.get_instance()
