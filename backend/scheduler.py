"""
Auto-Debate Background Scheduler for TradeLab.

Runs the Bull-vs-Bear-vs-Judge debate on a wall-clock aligned schedule (e.g. every 5 minutes
at hh:mm:08 so the just-closed 5m candle is included), and - when auto-execute is on - places
the Judge's BUY CE / BUY PE verdict as a paper trade at the LIVE option price. The paper engine
then manages stop-loss / target exits.

Design notes
- First debate runs immediately on start (if the market is open), then on the clock grid.
- `next_run` is always the real next due time, so the UI countdown is accurate.
- Config is persisted in the DB and resumed after a server restart / redeploy.
- At most one auto-trade is open per symbol (no stacking every 5 minutes) and no new entries
  after 15:00 IST (positions are squared off at 15:15).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from config import normalize_index_symbol
from database import AppKVModel, async_session_factory
from debate_engine import debate_engine
from paper_engine import paper_engine

logger = logging.getLogger("debate_scheduler")
IST = ZoneInfo("Asia/Kolkata")

SLOT_DELAY_SECONDS = 8          # run shortly after the candle closes
DEBATE_TIMEOUT_SECONDS = 120.0
EXEC_TIMEOUT_SECONDS = 30.0
MIN_CONFIDENCE_PCT = 70
NO_NEW_ENTRY_AFTER = (15, 0)
_KV_KEY = "scheduler"


def is_market_open(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(IST)
    if now.weekday() >= 5:
        return False
    hm = (now.hour, now.minute)
    return (9, 15) <= hm < (15, 30)


def _next_open_after(now: datetime) -> datetime:
    """Next 09:15 IST on a weekday strictly after `now`."""
    d = now.replace(hour=9, minute=15, second=0, microsecond=0)
    if d <= now:
        d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


class DebateScheduler:
    """Async background debate scheduler with optional auto-execution."""

    def __init__(self) -> None:
        self.is_running: bool = False
        self.interval_minutes: int = 5
        self.symbol: str = "NIFTY"
        self.auto_execute: bool = False
        self.market_hours_only: bool = True
        self.lots: int = 1
        self.user_id: Optional[int] = None

        self.last_run: Optional[str] = None
        self.next_run: Optional[str] = None
        self.run_count: int = 0
        self.last_session_id: Optional[str] = None
        self.last_error: Optional[str] = None
        self.status_text: str = "Standby"
        self._is_debating: bool = False

        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    # ── Status ───────────────────────────────────────────────────────────
    def get_status(self) -> dict:
        now = datetime.now(IST)
        return {
            "is_running": self.is_running,
            "interval_minutes": self.interval_minutes,
            "symbol": self.symbol,
            "auto_execute": self.auto_execute,
            "market_hours_only": self.market_hours_only,
            "lots": self.lots,
            "owner_user_id": self.user_id,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "run_count": self.run_count,
            "last_session_id": self.last_session_id,
            "last_error": self.last_error,
            "status_text": self.status_text,
            "is_debating": self._is_debating,
            "market_open": is_market_open(now),
            "server_time": now.isoformat(),
        }

    # ── Persistence ──────────────────────────────────────────────────────
    async def _save_state(self) -> None:
        payload = json.dumps({
            "is_running": self.is_running,
            "interval_minutes": self.interval_minutes,
            "symbol": self.symbol,
            "auto_execute": self.auto_execute,
            "market_hours_only": self.market_hours_only,
            "lots": self.lots,
            "user_id": self.user_id,
        })
        try:
            async with async_session_factory() as session:
                row = await session.get(AppKVModel, _KV_KEY)
                if row is None:
                    session.add(AppKVModel(key=_KV_KEY, value=payload))
                else:
                    row.value = payload
                await session.commit()
        except Exception as exc:
            logger.warning("Could not persist scheduler state: %s", exc)

    async def restore(self) -> None:
        """Resume the scheduler after a restart if it was running."""
        try:
            async with async_session_factory() as session:
                row = await session.get(AppKVModel, _KV_KEY)
            if not row:
                return
            cfg = json.loads(row.value)
            if cfg.get("is_running"):
                await self.start(
                    interval_minutes=cfg.get("interval_minutes", 5),
                    symbol=cfg.get("symbol", "NIFTY"),
                    auto_execute=cfg.get("auto_execute", False),
                    market_hours_only=cfg.get("market_hours_only", True),
                    lots=cfg.get("lots", 1),
                    user_id=cfg.get("user_id"),
                    immediate=False,
                )
                logger.info("Auto-debate scheduler resumed after restart.")
        except Exception as exc:
            logger.warning("Could not restore scheduler: %s", exc)

    # ── Control ──────────────────────────────────────────────────────────
    async def start(
        self,
        interval_minutes: int = 5,
        symbol: str = "NIFTY",
        auto_execute: bool = False,
        market_hours_only: bool = True,
        lots: int = 1,
        user_id: Optional[int] = None,
        immediate: bool = True,
    ) -> dict:
        """Start or restart the auto-debate background loop."""
        async with self._lock:
            await self._cancel_task()

            self.interval_minutes = int(interval_minutes) if interval_minutes in (3, 5, 10, 15) else 5
            self.symbol = normalize_index_symbol(symbol)
            self.auto_execute = bool(auto_execute)
            self.market_hours_only = bool(market_hours_only)
            self.lots = max(1, int(lots or 1))
            self.user_id = user_id
            self.is_running = True
            self.last_error = None

            now = datetime.now(IST)
            if immediate and self._market_ok(now):
                self.next_run = now.isoformat()
                self.status_text = "Starting - first debate now"
            else:
                self.next_run = self._next_run_after(now).isoformat()
                self.status_text = "Waiting for next slot" if self._market_ok(now) else "Market closed - waiting for open"

            self._task = asyncio.create_task(self._run_loop())
            logger.info(
                "DebateScheduler started: every %dm, %s, auto_execute=%s, user=%s, next_run=%s",
                self.interval_minutes, self.symbol, self.auto_execute, self.user_id, self.next_run,
            )
        await self._save_state()
        return self.get_status()

    async def stop(self) -> dict:
        """Stop the background debate scheduler loop."""
        async with self._lock:
            self.is_running = False
            self.next_run = None
            self.status_text = "Standby"
            await self._cancel_task()
            logger.info("DebateScheduler stopped cleanly.")
        await self._save_state()
        return self.get_status()

    async def shutdown(self) -> None:
        """Stop the loop on process shutdown WITHOUT clearing the persisted 'running' flag."""
        async with self._lock:
            await self._cancel_task()

    async def _cancel_task(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        self._is_debating = False

    # ── Scheduling helpers ───────────────────────────────────────────────
    def _market_ok(self, now: datetime) -> bool:
        return (not self.market_hours_only) or is_market_open(now)

    def _next_run_after(self, now: datetime) -> datetime:
        """Next wall-clock aligned slot (e.g. :00 :05 :10 ...) plus a small delay."""
        iv = self.interval_minutes
        base = now.replace(second=0, microsecond=0)
        slot = base + timedelta(minutes=iv - (base.minute % iv)) + timedelta(seconds=SLOT_DELAY_SECONDS)
        if self.market_hours_only and not is_market_open(slot):
            # first slot of the next session: one full interval after the open
            slot = _next_open_after(now) + timedelta(minutes=max(iv, 5), seconds=SLOT_DELAY_SECONDS)
        return slot

    # ── Main loop ────────────────────────────────────────────────────────
    async def _run_loop(self) -> None:
        logger.info("DebateScheduler loop initiated.")
        try:
            while self.is_running:
                target = datetime.fromisoformat(self.next_run) if self.next_run else datetime.now(IST)
                delay = (target - datetime.now(IST)).total_seconds()
                if delay > 0:
                    await asyncio.sleep(min(delay, 15.0))  # wake often so stop/config changes apply quickly
                    continue

                # Due: schedule the NEXT slot first so the countdown is always accurate
                self.next_run = self._next_run_after(datetime.now(IST)).isoformat()

                if not self._market_ok(datetime.now(IST)):
                    self.status_text = "Market closed - waiting for open"
                    continue

                await self._run_cycle()

                # If the cycle overran the next slot, skip ahead instead of firing back-to-back
                if datetime.fromisoformat(self.next_run) <= datetime.now(IST):
                    self.next_run = self._next_run_after(datetime.now(IST)).isoformat()
        except asyncio.CancelledError:
            logger.info("DebateScheduler loop cancelled.")
            raise
        except Exception as loop_err:  # pragma: no cover - defensive
            logger.error("Unexpected error in DebateScheduler loop: %s", loop_err, exc_info=True)
            self.last_error = f"Scheduler crashed: {loop_err}"
            self.status_text = "Stopped (error) - press Start again"
            self.is_running = False
            await self._save_state()
        finally:
            self._is_debating = False

    async def _run_cycle(self) -> None:
        self._is_debating = True
        self.status_text = "Agents deliberating..."
        try:
            logger.info("Scheduled debate for %s ...", self.symbol)
            session = await asyncio.wait_for(
                debate_engine.run_debate(symbol=self.symbol), timeout=DEBATE_TIMEOUT_SECONDS
            )
            self.last_run = datetime.now(IST).isoformat()
            self.last_session_id = session.id
            self.run_count += 1
            self.last_error = None

            verdict = (session.judge.verdict or "").upper()
            if verdict == "NO_TRADE":
                self.status_text = "Last verdict: NO TRADE"
            elif self.auto_execute:
                await self._maybe_execute(session)
            else:
                self.status_text = f"Last verdict: {verdict} (auto-execute off)"
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            self.last_error = f"Debate timed out after {int(DEBATE_TIMEOUT_SECONDS)}s"
            self.status_text = "Last run timed out - retrying next slot"
            logger.warning(self.last_error)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.status_text = "Last run failed - retrying next slot"
            logger.error("Scheduled debate cycle failed: %s", exc, exc_info=True)
        finally:
            self._is_debating = False

    async def _maybe_execute(self, session) -> None:
        judge = session.judge
        verdict = (judge.verdict or "").upper()
        conf = getattr(judge, "confidence", 0) or 0
        conf_pct = conf * 10 if conf <= 10 else conf

        async def skip(reason: str) -> None:
            logger.info("Auto-execute skipped: %s", reason)
            self.status_text = f"{verdict}: skipped - {reason}"
            await debate_engine.mark_skipped(session, reason)

        if verdict not in ("BUY CE", "BUY PE"):
            return
        if conf_pct < MIN_CONFIDENCE_PCT:
            return await skip(f"confidence {conf}/10 below {MIN_CONFIDENCE_PCT // 10}/10")

        now = datetime.now(IST)
        if (now.hour, now.minute) >= NO_NEW_ENTRY_AFTER:
            return await skip("no new entries after 15:00 IST")

        for pos in list(paper_engine.active_positions.values()):
            if pos.get("user_id") == self.user_id and pos.get("underlying") == session.symbol:
                return await skip("a position in this index is already open")

        try:
            res = await asyncio.wait_for(
                debate_engine.execute_verdict(
                    session.id, lots=self.lots, user_id=self.user_id, auto=True
                ),
                timeout=EXEC_TIMEOUT_SECONDS,
            )
            self.status_text = (
                f"Executed {verdict}: {res.get('symbol')} @ {res.get('entry_price')} "
                f"(SL {res.get('stop_loss')} / TGT {res.get('target')})"
            )
            logger.info("Auto-executed %s", self.status_text)
        except asyncio.TimeoutError:
            await skip("execution timed out")
        except Exception as exc:
            await skip(f"execution failed: {exc}")


# Singleton instance
_scheduler: Optional[DebateScheduler] = None


def get_scheduler() -> DebateScheduler:
    """Return the global DebateScheduler singleton instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = DebateScheduler()
    return _scheduler
