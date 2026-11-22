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

import contextlib

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import INDEX_CONFIG, get_index_spec, normalize_index_symbol, settings
from database import PaperTradeModel, PortfolioModel, async_session_factory

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
            port = PortfolioModel(
                user_id=user_id,
                initial_capital=self.initial_capital,
                cash_balance=self.initial_capital,
                margin_used=0.0,
                updated_at=self._now_ist(),
            )
            session.add(port)
            await session.commit()
            await session.refresh(port)
        return port

    async def restore_from_db(self) -> None:
        """Restore active positions from SQLite into memory on server startup."""
        try:
            async with async_session_factory() as session:
                stmt = select(PaperTradeModel).where(PaperTradeModel.status == "ACTIVE")
                res = await session.execute(stmt)
                trades = res.scalars().all()
                async with self._lock:
                    for t in trades:
                        self.active_positions[t.id] = t.to_dict()
                logger.info("Restored %d active paper positions from DB.", len(trades))
        except Exception as exc:
            logger.warning("Could not restore active positions from DB: %s", exc)

    async def get_state(self, user_id: Optional[int] = None) -> dict[str, Any]:
        """Return full snapshot of the trading account for specified user or guest.

        Read-only: deliberately NOT holding the engine lock while it waits on the database, so
        slow DB reads (polled every few seconds by the UI) can never starve order placement.
        """
        async with contextlib.nullcontext():
            async with async_session_factory() as session:
                port = await self._get_or_create_portfolio(session, user_id)
                cash_balance = port.cash_balance
                used_margin = port.margin_used
                initial_capital = port.initial_capital

            # Filter active positions and orders for user
            user_positions = [
                p for p in self.active_positions.values()
                if p.get("user_id") == user_id
            ]
            user_orders = [
                o for o in self.active_orders.values()
                if o.get("user_id") == user_id
            ]

            # Query persistent closed trades from SQLite
            closed_trades = await self.get_history(user_id=user_id)

            unrealized_pnl = sum(p.get("unrealized_pnl", 0.0) for p in user_positions)
            realized_pnl = sum(t.get("realized_pnl", 0.0) for t in closed_trades)
            gross_realized_pnl = sum(t.get("gross_pnl", t.get("realized_pnl", 0.0)) for t in closed_trades)
            total_charges = sum(t.get("total_charges", 0.0) for t in closed_trades)
            total_pnl = round(realized_pnl + unrealized_pnl, 2)

            today_str = self._today_date()
            today_realized = sum(
                t.get("realized_pnl", 0.0)
                for t in closed_trades
                if (t.get("exit_time") or t.get("closed_at") or "").startswith(today_str)
            )
            today_pnl = round(today_realized + unrealized_pnl, 2)

            net_liquidation_value = round(cash_balance + used_margin + unrealized_pnl, 2)
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

            wallet_dict = {
                "initial_capital": initial_capital,
                "capital": round(cash_balance, 2),
                "cash_balance": round(cash_balance, 2),
                "available_margin": round(cash_balance, 2),
                "used_margin": round(used_margin, 2),
                "net_liquidation_value": net_liquidation_value,
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
                "active_orders": user_orders,
                "orders": user_orders,
                "statistics": {
                    "total_trades": total_trades,
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
                    "pending_orders_count": len(user_orders),
                },
                "timestamp": self._now_ist(),
            }

    @staticmethod
    def entry_window_open() -> bool:
        """Intraday entries allowed Mon-Fri 09:15-15:15 IST (positions are squared off at 15:15)."""
        if getattr(settings, "ALLOW_OFFHOURS_TRADING", False):
            return True
        now = datetime.now(tz=IST)
        if now.weekday() >= 5:
            return False
        return "09:15:00" <= now.strftime("%H:%M:%S") < "15:15:00"

    async def place_order(
        self,
        order_req: dict[str, Any],
        user_id: Optional[int] = None,
        enforce_hours: bool = True,
    ) -> dict[str, Any]:
        """Place a paper trade order (Market, Limit, SL) linked to user."""
        if (
            enforce_hours
            and str(order_req.get("order_type") or "MARKET").upper() == "MARKET"
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
            uid = user_id if user_id is not None else order_req.get("user_id")
            symbol = str(order_req.get("symbol", "")).strip().upper()
            underlying = normalize_index_symbol(order_req.get("underlying", "NIFTY"))
            spec = get_index_spec(underlying)
            lot_size = spec["lot_size"]

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
            current_ltp = _safe_float(order_req.get("current_ltp"), price if price > 0 else 100.0)
            stop_loss = _safe_float(order_req.get("stop_loss")) if order_req.get("stop_loss") is not None else None
            target = _safe_float(order_req.get("target")) if order_req.get("target") is not None else None

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

                return await self._execute_fill(order_record, fill_price, now_time, user_id=uid)
            else:
                # Add to active pending orders
                self.active_orders[order_id] = order_record
                return order_record

    async def _execute_fill(
        self,
        order: dict[str, Any],
        fill_price: float,
        fill_time: str,
        user_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """Internal helper to fill order, update wallet in DB, and create persistent active trade."""
        uid = user_id if user_id is not None else order.get("user_id")
        order["status"] = "EXECUTED"
        order["filled_price"] = round(fill_price, 2)
        order["filled_time"] = fill_time
        order["user_id"] = uid

        quantity = order["quantity"]
        side = order["side"]
        order_cost = round(fill_price * quantity, 2)

        # Create Position
        pos_id = f"POS-{uuid.uuid4().hex[:8].upper()}"
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
            "current_ltp": round(fill_price, 2),
            "ltp": round(fill_price, 2),
            "live_price": round(fill_price, 2),
            "unrealized_pnl": 0.0,
            "pnl": 0.0,
            "stop_loss": order.get("stop_loss"),
            "target": order.get("target"),
            "entry_time": fill_time,
        }

        # Update wallet cash & used margin in SQLite DB
        async with async_session_factory() as session:
            port = await self._get_or_create_portfolio(session, uid)
            # BUY pays the premium; SELL blocks the same amount as margin. Both are released on
            # exit together with the realised P&L, so the wallet always reconciles.
            port.cash_balance = round(port.cash_balance - order_cost, 2)
            port.margin_used = round(port.margin_used + order_cost, 2)
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
                stop_loss=order.get("stop_loss"),
                target=order.get("target"),
                pnl_pct=0.0,
                created_at=fill_time,
            )
            session.add(db_trade)
            await session.commit()

        self.active_positions[pos_id] = position
        order["position_id"] = pos_id
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
                self.active_orders.pop(order_id)
                order["status"] = "CANCELLED"
                order["cancelled_time"] = self._now_ist()
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
        not_found = {"status": "ERROR", "message": f"Position {pos_id} not found."}
        async with self._lock:
            pos = self.active_positions.get(pos_id)
            if pos is not None:
                if not system and pos.get("user_id") != user_id:
                    return not_found
                self.active_positions.pop(pos_id, None)
            else:
                # Check DB if not found in memory
                async with async_session_factory() as session:
                    stmt = select(PaperTradeModel).where(
                        PaperTradeModel.id == pos_id,
                        PaperTradeModel.status == "ACTIVE",
                    )
                    db_p = (await session.execute(stmt)).scalars().first()
                    if db_p:
                        if not system and db_p.user_id != user_id:
                            return not_found
                        pos = db_p.to_dict()
                if not pos:
                    return not_found

            uid = pos.get("user_id")
            exit_p = round(exit_price if exit_price is not None and exit_price > 0 else pos.get("current_ltp", 100.0), 2)
            exit_time = self._now_ist()
            quantity = pos["quantity"]
            side = pos["side"]

            # Calculate turnover and gross P&L
            if side == "BUY":
                buy_turnover = round(pos["entry_price"] * quantity, 2)
                sell_turnover = round(exit_p * quantity, 2)
                gross_pnl = round((exit_p - pos["entry_price"]) * quantity, 2)
            else:
                sell_turnover = round(pos["entry_price"] * quantity, 2)
                buy_turnover = round(exit_p * quantity, 2)
                gross_pnl = round((pos["entry_price"] - exit_p) * quantity, 2)

            charges = calculate_trade_charges(buy_turnover, sell_turnover, underlying=pos.get("underlying", "NIFTY"))
            realized_pnl = round(gross_pnl - charges["total_charges"], 2)
            pnl_pct = round((realized_pnl / (pos["entry_price"] * quantity)) * 100, 2) if pos["entry_price"] > 0 else 0.0

            # Update DB and user portfolio
            async with async_session_factory() as session:
                port = await self._get_or_create_portfolio(session, uid)
                margin_released = round(pos["entry_price"] * quantity, 2)
                port.margin_used = max(0.0, round(port.margin_used - margin_released, 2))
                port.cash_balance = round(port.cash_balance + margin_released + realized_pnl, 2)
                port.updated_at = exit_time

                # Update or insert closed trade record
                stmt = select(PaperTradeModel).where(PaperTradeModel.id == pos_id)
                db_trade = (await session.execute(stmt)).scalars().first()
                if db_trade:
                    db_trade.status = "CLOSED"
                    db_trade.exit_price = exit_p
                    db_trade.current_ltp = exit_p
                    db_trade.gross_pnl = gross_pnl
                    db_trade.realized_pnl = realized_pnl
                    db_trade.pnl = realized_pnl
                    db_trade.total_charges = charges["total_charges"]
                    db_trade.closed_at = exit_time
                    db_trade.exit_reason = reason
                    db_trade.pnl_pct = pnl_pct
                else:
                    db_trade = PaperTradeModel(
                        id=pos_id,
                        user_id=uid,
                        symbol=pos["symbol"],
                        underlying=pos.get("underlying", "NIFTY"),
                        strike=pos["strike"],
                        option_type=pos["option_type"],
                        side=side,
                        lots=pos.get("lots", 1),
                        quantity=quantity,
                        entry_price=pos["entry_price"],
                        exit_price=exit_p,
                        current_ltp=exit_p,
                        gross_pnl=gross_pnl,
                        realized_pnl=realized_pnl,
                        pnl=realized_pnl,
                        total_charges=charges["total_charges"],
                        status="CLOSED",
                        stop_loss=pos.get("stop_loss"),
                        target=pos.get("target"),
                        exit_reason=reason,
                        pnl_pct=pnl_pct,
                        created_at=pos.get("entry_time", exit_time),
                        closed_at=exit_time,
                    )
                    session.add(db_trade)
                await session.commit()

            trade_record = {
                "id": pos_id,
                "pos_id": pos_id,
                "user_id": uid,
                "symbol": pos["symbol"],
                "underlying": pos.get("underlying", "NIFTY"),
                "strike": pos["strike"],
                "option_type": pos["option_type"],
                "side": side,
                "lots": pos.get("lots", 1),
                "quantity": quantity,
                "entry_price": pos["entry_price"],
                "exit_price": exit_p,
                "gross_pnl": gross_pnl,
                "charges": charges,
                "total_charges": charges["total_charges"],
                "realized_pnl": realized_pnl,
                "pnl": realized_pnl,
                "pnl_pct": pnl_pct,
                "entry_time": pos["entry_time"],
                "exit_time": exit_time,
                "closed_at": exit_time,
                "exit_reason": reason,
            }

            logger.info(
                "Position %s exited @ ₹%.2f. Realized Net PnL: ₹%.2f (Charges: ₹%.2f, %s, user_id=%s)",
                pos_id, exit_p, realized_pnl, charges["total_charges"], reason, uid,
            )
            return {
                "status": "SUCCESS",
                "message": f"Position {pos_id} exited @ ₹{exit_p:.2f}",
                "realized_pnl": realized_pnl,
                "gross_pnl": gross_pnl,
                "charges": charges,
                "exit_price": exit_p,
                "trade": trade_record,
            }

    async def check_intraday_squareoff(
        self, current_time_str: Optional[str] = None, only_user: Optional[int] = None
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
            return await self.exit_all_positions(reason="AUTO_SQUAREOFF_315PM", system=True)
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

            if stop_loss is not None:
                pos["stop_loss"] = round(stop_loss, 2)
            if target is not None:
                pos["target"] = round(target, 2)

            async with async_session_factory() as session:
                stmt = select(PaperTradeModel).where(PaperTradeModel.id == pos_id)
                db_trade = (await session.execute(stmt)).scalars().first()
                if db_trade:
                    if stop_loss is not None:
                        db_trade.stop_loss = round(stop_loss, 2)
                    if target is not None:
                        db_trade.target = round(target, 2)
                    await session.commit()

            return {"status": "SUCCESS", "position": pos}

    async def reset_portfolio(self, initial_capital: float = 1000000.0, user_id: Optional[int] = None) -> dict[str, Any]:
        """Reset virtual paper trading wallet back to initial virtual funds in DB."""
        async with self._lock:
            # Clear active positions in memory for this user
            pids_to_remove = [
                pid for pid, pos in self.active_positions.items()
                if pos.get("user_id") == user_id
            ]
            for pid in pids_to_remove:
                self.active_positions.pop(pid, None)

            # Clear active orders in memory for this user
            oids_to_remove = [
                oid for oid, ord_rec in self.active_orders.items()
                if ord_rec.get("user_id") == user_id
            ]
            for oid in oids_to_remove:
                self.active_orders.pop(oid, None)

            # Update portfolio in SQLite DB
            async with async_session_factory() as session:
                port = await self._get_or_create_portfolio(session, user_id)
                port.initial_capital = initial_capital
                port.cash_balance = initial_capital
                port.margin_used = 0.0
                port.updated_at = self._now_ist()

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
                await session.commit()

            logger.info("Paper trading wallet reset to ₹%.2f (user_id=%s)", initial_capital, user_id)
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

    async def get_history(self, user_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Return full closed trades journal from SQLite database."""
        async with async_session_factory() as session:
            if user_id is not None:
                stmt = select(PaperTradeModel).where(
                    PaperTradeModel.status == "CLOSED",
                    PaperTradeModel.user_id == user_id,
                ).order_by(PaperTradeModel.closed_at.desc())
            else:
                stmt = select(PaperTradeModel).where(
                    PaperTradeModel.status == "CLOSED",
                    PaperTradeModel.user_id.is_(None),
                ).order_by(PaperTradeModel.closed_at.desc())

            res = await session.execute(stmt)
            trades = res.scalars().all()
            return [t.to_dict() for t in trades]

    async def get_pnl_calendar(self, user_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Generate calendar heatmap data grouped by date from persistent DB."""
        trades = await self.get_history(user_id=user_id)
        daily_stats: dict[str, dict[str, Any]] = {}
        for t in trades:
            exit_time = t.get("closed_at") or t.get("exit_time") or ""
            date_key = exit_time[:10]
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

    async def update_market_prices(self, quotes: dict[str, float]) -> None:
        """Update active positions MTM and execute pending SL / Target triggers."""
        async with self._lock:
            if not self.active_positions and not self.active_orders:
                return

            exited_positions: list[tuple[str, float, str, Optional[int]]] = []
            now_time = self._now_ist()

            # 1. Update Positions MTM and check SL/Target
            for pos_id, pos in list(self.active_positions.items()):
                sym = pos["symbol"]
                ltp = quotes.get(sym)
                if ltp is None:
                    alt_key = f"{int(pos['strike'])}{pos['option_type']}"
                    ltp = quotes.get(alt_key)

                if ltp is not None and ltp > 0:
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

                    # Check Stop Loss trigger
                    sl = pos.get("stop_loss")
                    if sl is not None and sl > 0:
                        if (side == "BUY" and ltp <= sl) or (side == "SELL" and ltp >= sl):
                            exited_positions.append((pos_id, sl, "STOP_LOSS_HIT", pos.get("user_id")))
                            continue

                    # Check Target trigger
                    tgt = pos.get("target")
                    if tgt is not None and tgt > 0:
                        if (side == "BUY" and ltp >= tgt) or (side == "SELL" and ltp <= tgt):
                            exited_positions.append((pos_id, tgt, "TARGET_HIT", pos.get("user_id")))
                            continue

            # Process triggers
            for pos_id, exit_p, reason, uid in exited_positions:
                pos = self.active_positions.pop(pos_id, None)
                if not pos:
                    continue
                quantity = pos["quantity"]
                side = pos["side"]
                if side == "BUY":
                    buy_turnover = round(pos["entry_price"] * quantity, 2)
                    sell_turnover = round(exit_p * quantity, 2)
                    gross_pnl = round((exit_p - pos["entry_price"]) * quantity, 2)
                else:
                    sell_turnover = round(pos["entry_price"] * quantity, 2)
                    buy_turnover = round(exit_p * quantity, 2)
                    gross_pnl = round((pos["entry_price"] - exit_p) * quantity, 2)

                charges = calculate_trade_charges(buy_turnover, sell_turnover, underlying=pos.get("underlying", "NIFTY"))
                realized_pnl = round(gross_pnl - charges["total_charges"], 2)
                pnl_pct = round((realized_pnl / (pos["entry_price"] * quantity)) * 100, 2) if pos["entry_price"] > 0 else 0.0

                async with async_session_factory() as session:
                    port = await self._get_or_create_portfolio(session, uid)
                    margin_released = round(pos["entry_price"] * quantity, 2)
                    port.margin_used = max(0.0, round(port.margin_used - margin_released, 2))
                    port.cash_balance = round(port.cash_balance + margin_released + realized_pnl, 2)
                    port.updated_at = now_time

                    stmt = select(PaperTradeModel).where(PaperTradeModel.id == pos_id)
                    db_trade = (await session.execute(stmt)).scalars().first()
                    if db_trade:
                        db_trade.status = "CLOSED"
                        db_trade.exit_price = exit_p
                        db_trade.current_ltp = exit_p
                        db_trade.gross_pnl = gross_pnl
                        db_trade.realized_pnl = realized_pnl
                        db_trade.pnl = realized_pnl
                        db_trade.total_charges = charges["total_charges"]
                        db_trade.closed_at = now_time
                        db_trade.exit_reason = reason
                        db_trade.pnl_pct = pnl_pct
                    await session.commit()

                logger.info(
                    "Automated %s on %s @ ₹%.2f. Net PnL: ₹%.2f (Charges: ₹%.2f, user_id=%s)",
                    reason, pos["symbol"], exit_p, realized_pnl, charges["total_charges"], uid,
                )

            # 2. Check Pending Limit / Stop-Loss orders
            executed_orders: list[tuple[str, float]] = []
            for order_id, order in list(self.active_orders.items()):
                sym = order["symbol"]
                ltp = quotes.get(sym)
                if ltp is None:
                    alt_key = f"{int(order['strike'])}{order['option_type']}"
                    ltp = quotes.get(alt_key)

                if ltp is not None and ltp > 0:
                    order_type = order["order_type"]
                    side = order["side"]
                    limit_p = order["price"]
                    trig_p = order["trigger_price"]

                    should_fill = False
                    fill_p = ltp

                    if order_type == "LIMIT":
                        if side == "BUY" and ltp <= limit_p:
                            should_fill = True
                            fill_p = limit_p
                        elif side == "SELL" and ltp >= limit_p:
                            should_fill = True
                            fill_p = limit_p
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
                order = self.active_orders.pop(order_id, None)
                if order:
                    await self._execute_fill(order, fill_p, now_time, user_id=order.get("user_id"))


# Singleton accessor
paper_engine = PaperEngine.get_instance()
