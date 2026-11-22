"""
Historical 1-Minute Candle Replay Engine for TradeLab.

Enables backtesting, trade simulation, and historical chart playback:
- Loads full 1-minute intraday session candles (09:15 - 15:30 IST, 375 candles).
- Controls playback: Start, Pause, Resume, Speed (1x, 2x, 5x, 10x), Step Forward, Step Backward, Stop.
- Feeds replayed tick data and simulated option premiums into the PaperEngine.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from config import INDEX_CONFIG, normalize_index_symbol
from greeks import BlackScholesEngine
from paper_engine import paper_engine

logger = logging.getLogger("replay_engine")
IST = ZoneInfo("Asia/Kolkata")


class ReplayEngine:
    """Historical market replay engine with synchronized paper trade execution."""

    _instance: Optional[ReplayEngine] = None

    def __init__(self) -> None:
        self.is_replaying: bool = False
        self.is_paused: bool = False
        self.owner_id: Optional[int] = None  # the one account that started this replay
        self.date: str = ""
        self.symbol: str = "NIFTY"
        self.speed: float = 1.0  # 1x, 2x, 5x, 10x
        self.candle_index: int = 0
        self.total_candles: int = 0
        self.candles: list[dict[str, Any]] = []

        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> ReplayEngine:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_available_dates(self) -> list[dict[str, str]]:
        """Return list of recent past trading dates available for replay."""
        today = datetime.now(tz=IST).date()
        dates = []
        d = today
        count = 0
        while count < 15:
            # Skip Saturday (5) and Sunday (6)
            if d.weekday() < 5:
                dates.append({
                    "date": d.strftime("%Y-%m-%d"),
                    "label": d.strftime("%d %b %Y (%a)"),
                    "is_today": (d == today),
                })
                count += 1
            d -= timedelta(days=1)
        return dates

    async def start_replay(self, date_str: str, symbol: str = "NIFTY") -> dict[str, Any]:
        """Initiate historical replay for a specific trading session."""
        from angel_service import angel_service

        async with self._lock:
            # Stop existing replay if active
            await self._stop_internal()

            sym_norm = normalize_index_symbol(symbol)
            candles = await angel_service.get_replay_candles(sym_norm, date_str)
            if not candles:
                return {
                    "status": "ERROR",
                    "message": f"Could not load 1-minute historical candles for {sym_norm} on {date_str}.",
                }

            self.candles = candles
            self.total_candles = len(candles)
            self.candle_index = 0
            self.date = date_str
            self.symbol = sym_norm
            self.is_replaying = True
            self.is_paused = False
            self.speed = 1.0

            # Start background replay loop
            self._task = asyncio.create_task(self._replay_loop())
            logger.info("Started replay for %s on %s (%d candles)", sym_norm, date_str, self.total_candles)

            # Send initial tick
            await self._broadcast_tick()

            return {
                "status": "SUCCESS",
                "message": f"Replay started for {sym_norm} on {date_str}",
                "state": self.get_state(),
            }

    async def _replay_loop(self) -> None:
        """Background coroutine that advances the replay clock according to speed multiplier."""
        try:
            while self.is_replaying:
                if not self.is_paused and self.candle_index < self.total_candles - 1:
                    await self._advance_tick()

                # Base delay per candle: 1.0s at 1x, 0.5s at 2x, 0.2s at 5x, 0.1s at 10x
                delay = max(0.08, 1.0 / max(0.5, self.speed))
                await asyncio.sleep(delay)

                if self.candle_index >= self.total_candles - 1:
                    logger.info("Historical replay reached end of session.")
                    self.is_paused = True
                    break
        except asyncio.CancelledError:
            logger.debug("Replay loop task cancelled.")
        except Exception as exc:
            logger.error("Exception in replay loop: %s", exc)

    async def _advance_tick(self) -> None:
        """Step to next candle tick and update market prices."""
        async with self._lock:
            if self.candle_index < self.total_candles - 1:
                self.candle_index += 1
                await self._broadcast_tick()

    async def _broadcast_tick(self) -> None:
        """Derive option quotes from replayed candle and feed into paper engine."""
        if not self.candles or self.candle_index >= len(self.candles):
            return

        candle = self.candles[self.candle_index]
        spot = candle["close"]
        spec = INDEX_CONFIG.get(self.symbol, INDEX_CONFIG["NIFTY"])
        step = spec["strike_step"]
        atm = int(round(spot / step) * step)

        # Generate quotes for ±10 strikes around ATM
        quotes_dict: dict[str, float] = {self.symbol: spot}
        days_to_expiry = 3.0 / 365.0

        for offset in range(-10, 11):
            k = atm + (offset * step)
            ce_p = BlackScholesEngine.calculate_price(spot, k, days_to_expiry, iv=0.15, option_type="CE")
            pe_p = BlackScholesEngine.calculate_price(spot, k, days_to_expiry, iv=0.15, option_type="PE")

            # Store by strike key
            quotes_dict[f"{k}CE"] = ce_p
            quotes_dict[f"{k}PE"] = pe_p
            quotes_dict[f"{self.symbol}{k}CE"] = ce_p
            quotes_dict[f"{self.symbol}{k}PE"] = pe_p

        # Update paper trading engine
        await paper_engine.update_market_prices(quotes_dict)

        # Check automated 3:15 PM intraday square-off
        candle_time = candle.get("time")
        if candle_time:
            time_str = datetime.fromtimestamp(candle_time, tz=IST).strftime("%H:%M:%S")
            if time_str >= "15:15:00":
                # The replay clock may only square off the replaying user's own trades
                await paper_engine.check_intraday_squareoff(time_str, only_user=self.owner_id)

    async def pause(self) -> dict[str, Any]:
        """Pause historical replay advancement."""
        async with self._lock:
            if not self.is_replaying:
                return {"status": "ERROR", "message": "Replay is not active."}
            self.is_paused = True
            return {"status": "SUCCESS", "state": self.get_state()}

    async def resume(self) -> dict[str, Any]:
        """Resume playback."""
        async with self._lock:
            if not self.is_replaying:
                return {"status": "ERROR", "message": "Replay is not active."}
            self.is_paused = False
            return {"status": "SUCCESS", "state": self.get_state()}

    async def set_speed(self, speed: float) -> dict[str, Any]:
        """Update playback speed multiplier (e.g. 1.0, 2.0, 5.0, 10.0)."""
        async with self._lock:
            self.speed = max(0.5, min(20.0, float(speed)))
            return {"status": "SUCCESS", "speed": self.speed, "state": self.get_state()}

    async def step_forward(self) -> dict[str, Any]:
        """Advance exactly one candle."""
        async with self._lock:
            if not self.is_replaying:
                return {"status": "ERROR", "message": "Replay is not active."}
            if self.candle_index < self.total_candles - 1:
                self.candle_index += 1
                await self._broadcast_tick()
            return {"status": "SUCCESS", "state": self.get_state()}

    async def step_backward(self) -> dict[str, Any]:
        """Step back one candle."""
        async with self._lock:
            if not self.is_replaying:
                return {"status": "ERROR", "message": "Replay is not active."}
            if self.candle_index > 0:
                self.candle_index -= 1
                await self._broadcast_tick()
            return {"status": "SUCCESS", "state": self.get_state()}

    async def stop_replay(self) -> dict[str, Any]:
        """Terminate replay mode and return to live market mode."""
        async with self._lock:
            await self._stop_internal()
            return {"status": "SUCCESS", "message": "Replay stopped.", "state": self.get_state()}

    async def _stop_internal(self) -> None:
        """Internal teardown of replay task."""
        self.is_replaying = False
        self.is_paused = False
        self.owner_id = None
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.candles.clear()
        self.candle_index = 0
        self.total_candles = 0

    def get_current_tick(self) -> Optional[dict[str, Any]]:
        """Return the current candle tick."""
        if not self.candles or self.candle_index >= len(self.candles):
            return None
        return self.candles[self.candle_index].copy()

    def get_state(self) -> dict[str, Any]:
        """Return current status of the replay manager."""
        current_tick = self.get_current_tick()
        progress_pct = round(((self.candle_index + 1) / max(self.total_candles, 1)) * 100, 1)

        return {
            "is_replaying": self.is_replaying,
            "is_paused": self.is_paused,
            "date": self.date,
            "symbol": self.symbol,
            "speed": self.speed,
            "candle_index": self.candle_index,
            "total_candles": self.total_candles,
            "progress_percent": progress_pct,
            "current_tick": current_tick,
            "current_time": current_tick.get("timestamp") if current_tick else None,
            "current_spot": current_tick.get("close") if current_tick else None,
        }


# Singleton accessor
replay_engine = ReplayEngine.get_instance()
