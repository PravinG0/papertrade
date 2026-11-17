"""
Auto-Debate Background Scheduler for TradeLab.

Periodically runs institutional multi-agent debates (Bull vs Bear vs Judge)
at configurable intervals (3m, 5m, 10m, 15m) and optionally executes high-conviction
Judge verdicts directly in the paper trading engine.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Optional
from zoneinfo import ZoneInfo

from config import get_index_spec, normalize_index_symbol
from debate_engine import debate_engine
from paper_engine import paper_engine

logger = logging.getLogger("debate_scheduler")
IST = ZoneInfo("Asia/Kolkata")


class DebateScheduler:
    """Async background debate scheduler with optional auto-execution."""

    def __init__(self) -> None:
        self.is_running: bool = False
        self.interval_minutes: int = 5
        self.symbol: str = "NIFTY"
        self.auto_execute: bool = False
        self.last_run: Optional[str] = None
        self.next_run: Optional[str] = None
        self.run_count: int = 0

        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def get_status(self) -> dict:
        """Return the current scheduler operational status."""
        return {
            "is_running": self.is_running,
            "interval_minutes": self.interval_minutes,
            "symbol": self.symbol,
            "auto_execute": self.auto_execute,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "run_count": self.run_count,
        }

    async def start(
        self,
        interval_minutes: int = 5,
        symbol: str = "NIFTY",
        auto_execute: bool = False,
    ) -> dict:
        """Start or restart the auto-debate background loop."""
        async with self._lock:
            # Stop existing task if active
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None

            # Update configuration
            self.interval_minutes = int(interval_minutes) if interval_minutes in (3, 5, 10, 15) else 5
            self.symbol = normalize_index_symbol(symbol)
            self.auto_execute = bool(auto_execute)
            self.is_running = True

            # Calculate initial next_run timestamp
            next_time = datetime.now(IST) + timedelta(minutes=self.interval_minutes)
            self.next_run = next_time.isoformat()

            # Launch background worker loop
            self._task = asyncio.create_task(self._run_loop())

            logger.info(
                "DebateScheduler started: interval=%dm, symbol=%s, auto_execute=%s, next_run=%s",
                self.interval_minutes,
                self.symbol,
                self.auto_execute,
                self.next_run,
            )
            return self.get_status()

    async def stop(self) -> dict:
        """Stop the background debate scheduler loop."""
        async with self._lock:
            self.is_running = False
            self.next_run = None

            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None

            logger.info("DebateScheduler stopped cleanly.")
            return self.get_status()

    async def _run_loop(self) -> None:
        """Periodic background execution loop."""
        logger.info("DebateScheduler loop initiated.")
        try:
            while self.is_running:
                sleep_seconds = max(10, self.interval_minutes * 60)
                await asyncio.sleep(sleep_seconds)

                if not self.is_running:
                    break

                try:
                    logger.info("DebateScheduler triggering scheduled debate for %s...", self.symbol)
                    session = await debate_engine.run_debate(symbol=self.symbol)
                    self.last_run = datetime.now(IST).isoformat()
                    self.run_count += 1

                    # Auto-execution check
                    if self.auto_execute and session and session.judge:
                        judge = session.judge
                        verdict = (judge.verdict or "").upper()
                        conf_val = getattr(judge, "confidence", 0)
                        # Confidence might be 1-10 or 0-100 scale
                        conf_pct = conf_val * 10 if conf_val <= 10 else conf_val

                        if conf_pct >= 70 and verdict in ("BUY CE", "BUY PE") and verdict != "NO_TRADE":
                            logger.info(
                                "Auto-executing Judge verdict '%s' (Confidence: %d%%)",
                                verdict,
                                conf_pct,
                            )
                            try:
                                await debate_engine.execute_verdict(session.id, lots=1)
                                logger.info("Auto-execution successful for session %s", session.id)
                            except Exception as exec_err:
                                logger.warning(
                                    "execute_verdict raised error: %s. Falling back to direct paper_engine.place_order",
                                    exec_err,
                                )
                                underlying = session.symbol
                                spec = get_index_spec(underlying)
                                lot_size = spec.get("lot_size", 25)
                                opt_type = "CE" if "CE" in verdict else "PE"
                                strike = float(judge.recommended_strike or session.market_snapshot.atm_strike)
                                entry_p = float(judge.entry_price or 120.0)
                                sl_p = float(judge.stop_loss or (entry_p - 25.0))
                                tgt_p = float(judge.target or (entry_p + 35.0))

                                order_symbol = f"{underlying}{int(strike)}{opt_type}"
                                order_req = {
                                    "symbol": order_symbol,
                                    "underlying": underlying,
                                    "strike": strike,
                                    "option_type": opt_type,
                                    "lots": 1,
                                    "lot_size": lot_size,
                                    "side": "BUY",
                                    "order_type": "MARKET",
                                    "price": entry_p,
                                    "current_ltp": entry_p,
                                    "stop_loss": sl_p,
                                    "target": tgt_p,
                                }
                                await paper_engine.place_order(order_req)
                                session.executed = True
                                debate_engine._save_history()

                except asyncio.CancelledError:
                    raise
                except Exception as cycle_err:
                    logger.error("Error executing scheduled debate cycle: %s", cycle_err, exc_info=True)

                # Set next scheduled run time
                next_time = datetime.now(IST) + timedelta(minutes=self.interval_minutes)
                self.next_run = next_time.isoformat()

        except asyncio.CancelledError:
            logger.info("DebateScheduler loop cancelled.")
        except Exception as loop_err:
            logger.error("Unexpected error in DebateScheduler loop: %s", loop_err, exc_info=True)
            self.is_running = False
            self.next_run = None


# Singleton instance
_scheduler: Optional[DebateScheduler] = None


def get_scheduler() -> DebateScheduler:
    """Return the global DebateScheduler singleton instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = DebateScheduler()
    return _scheduler
