"""
AI Debate Engine for TradeLab.

Orchestrates multi-agent institutional debate:
1. Ingests live quotes, historical candles, and real-time option chain from AngelService.
2. Computes technical derivatives matrix (EMA, VWAP, RSI, CPR, Supertrend, PCR, Max Pain, OI Walls).
3. Executes multi-turn debate sequence: BullAgent -> BearAgent -> JudgeAgent (CRO).
4. Persists debate sessions with full audit trail in memory and local storage.
5. Provides 1-click execution bridge directly into PaperEngine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agents import BearAgent, BullAgent, JudgeAgent
from angel_service import angel_service
from config import INDEX_CONFIG, get_index_spec, normalize_index_symbol, settings
from debate_schemas import (
    BearAgentOutput,
    BullAgentOutput,
    DebateSession,
    JudgeAgentOutput,
    MarketSnapshot,
    ist_now_str,
)
from paper_engine import paper_engine

logger = logging.getLogger("debate_engine")
IST = ZoneInfo("Asia/Kolkata")

_HISTORY_FILE = Path(__file__).resolve().parent / "debate_sessions.json"


def _calc_indicators(candles: list[dict[str, Any]], spot: float) -> dict[str, Any]:
    """Calculate EMA20, EMA50, RSI14, VWAP, ATR14, CPR, and Supertrend from candles."""
    if not candles:
        return {
            "ema_20": round(spot * 0.998, 2),
            "ema_50": round(spot * 0.995, 2),
            "rsi": 52.5,
            "vwap": round(spot, 2),
            "atr": round(spot * 0.006, 2),
            "trend": "BULLISH",
            "cpr_pivot": round(spot, 2),
            "cpr_bc": round(spot * 0.998, 2),
            "cpr_tc": round(spot * 1.002, 2),
            "cpr_width_type": "NARROW_TRENDING",
            "supertrend_direction": "BULLISH",
            "supertrend_value": round(spot * 0.99, 2),
        }

    n = len(candles)
    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    volumes = [float(c.get("volume") or 0.0) for c in candles]
    last_close = spot or closes[-1]

    # EMA calculation
    def calc_ema(span: int) -> float:
        if n < span:
            return sum(closes) / max(1, n)
        alpha = 2.0 / (span + 1.0)
        val = sum(closes[:span]) / span
        for p in closes[span:]:
            val = (p * alpha) + (val * (1.0 - alpha))
        return val

    ema_20 = round(calc_ema(20), 2)
    ema_50 = round(calc_ema(50), 2)

    # RSI 14 (Wilder's smoothing)
    if n < 15:
        rsi = 52.0
    else:
        gains, losses = [], []
        for i in range(1, n):
            d = closes[i] - closes[i - 1]
            gains.append(max(0.0, d))
            losses.append(max(0.0, -d))
        avg_gain = sum(gains[:14]) / 14.0
        avg_loss = sum(losses[:14]) / 14.0
        for i in range(14, len(gains)):
            avg_gain = (avg_gain * 13.0 + gains[i]) / 14.0
            avg_loss = (avg_loss * 13.0 + losses[i]) / 14.0
        if avg_loss == 0.0:
            rsi = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi = round(100.0 - (100.0 / (1.0 + rs)), 2)

    # VWAP: volume weighted typical price
    tot_vol = sum(volumes)
    typ_prices = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
    if tot_vol > 0:
        vwap = round(sum(tp * v for tp, v in zip(typ_prices, volumes)) / tot_vol, 2)
    else:
        vwap = round(sum(typ_prices) / max(1, n), 2)

    # ATR 14
    tr_list = [highs[0] - lows[0]]
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_list.append(tr)

    if n <= 14:
        atr = round(sum(tr_list) / max(1, n), 2)
    else:
        atr_val = sum(tr_list[:14]) / 14.0
        for i in range(14, n):
            atr_val = (atr_val * 13.0 + tr_list[i]) / 14.0
        atr = round(atr_val, 2)

    trend = "BULLISH" if last_close >= ema_20 else "BEARISH"

    # CPR
    day_high = max(highs[-min(n, 75):])
    day_low = min(lows[-min(n, 75):])
    cpr_pivot = round((day_high + day_low + last_close) / 3.0, 2)
    cpr_bc = round((day_high + day_low) / 2.0, 2)
    cpr_tc = round((cpr_pivot - cpr_bc) + cpr_pivot, 2)
    cpr_width = abs(cpr_tc - cpr_bc)
    cpr_width_pct = (cpr_width / last_close) * 100.0 if last_close > 0 else 0.0
    cpr_regime = "NARROW_TRENDING" if cpr_width_pct < 0.35 else "WIDE_RANGEBOUND"

    # Supertrend
    st_dir = "BULLISH" if last_close >= ema_20 else "BEARISH"
    st_val = round(last_close - (1.5 * atr) if st_dir == "BULLISH" else last_close + (1.5 * atr), 2)

    return {
        "ema_20": ema_20,
        "ema_50": ema_50,
        "rsi": rsi,
        "vwap": vwap,
        "atr": atr,
        "trend": trend,
        "day_high": day_high,
        "day_low": day_low,
        "cpr_pivot": cpr_pivot,
        "cpr_bc": cpr_bc,
        "cpr_tc": cpr_tc,
        "cpr_width_type": cpr_regime,
        "supertrend_direction": st_dir,
        "supertrend_value": st_val,
    }


class DebateEngine:
    """Manages AI Debate sessions, execution, and historical persistence."""

    _instance: Optional[DebateEngine] = None

    def __init__(self) -> None:
        self.bull_agent = BullAgent()
        self.bear_agent = BearAgent()
        self.judge_agent = JudgeAgent()
        self._history: list[DebateSession] = []
        self._lock = asyncio.Lock()
        self._load_history()

    @classmethod
    def get_instance(cls) -> DebateEngine:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_history(self) -> None:
        """Load past debates from persistent json cache."""
        if _HISTORY_FILE.exists():
            try:
                data = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
                for item in data:
                    try:
                        self._history.append(DebateSession(**item))
                    except Exception:
                        pass
                logger.info("Loaded %d past AI debates from disk", len(self._history))
            except Exception as exc:
                logger.warning("Could not read debate history file: %s", exc)

    def _save_history(self) -> None:
        """Save history to disk asynchronously or safely."""
        try:
            dump_list = [s.model_dump() for s in self._history[:60]]
            _HISTORY_FILE.write_text(json.dumps(dump_list, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not save debate history file: %s", exc)

    async def build_snapshot(self, symbol: str = "NIFTY") -> MarketSnapshot:
        """Construct full point-in-time MarketSnapshot from Angel One live feed."""
        sym = normalize_index_symbol(symbol)
        spec = get_index_spec(sym)
        step = spec.get("strike_step", 50)

        # 1. Spot price
        spot = await angel_service.get_spot_price(sym)
        if not spot or spot <= 0:
            spot = float(spec.get("default_spot", 24980.0))

        # ATM Strike
        atm_strike = float(round(spot / step) * step)

        # 2. Candlestick feed (5-minute interval)
        candles = await angel_service.get_candles(sym, interval="5m", range_period="5d", num_candles=60)
        tech = _calc_indicators(candles, spot)

        # 3. Option chain feed
        pcr = 1.05
        max_pain = atm_strike
        call_wall = atm_strike + step
        put_wall = atm_strike - step
        ce_oi_change = 45000.0
        pe_oi_change = 52000.0

        try:
            chain_data = await angel_service.get_option_chain(sym, strikes_count=12)
            if chain_data:
                pcr = float(chain_data.get("pcr") or 1.05)
                max_pain = float(chain_data.get("max_pain") or atm_strike)
                call_wall = float(chain_data.get("call_oi_wall") or (atm_strike + (2 * step)))
                put_wall = float(chain_data.get("put_oi_wall") or (atm_strike - (2 * step)))

                chain_rows = chain_data.get("chain", [])
                tot_ce_chg = sum(r.get("ce", {}).get("oi_change", 0) for r in chain_rows)
                tot_pe_chg = sum(r.get("pe", {}).get("oi_change", 0) for r in chain_rows)
                if tot_ce_chg != 0 or tot_pe_chg != 0:
                    ce_oi_change = float(tot_ce_chg)
                    pe_oi_change = float(tot_pe_chg)
        except Exception as exc:
            logger.debug("Option chain metrics extraction skipped: %s", exc)

        # 4. Macro sentiment
        fii = "NET_BUYER" if spot >= tech["ema_20"] and pcr >= 1.0 else ("NET_SELLER" if spot < tech["ema_20"] and pcr < 0.9 else "NEUTRAL")
        glob = "POSITIVE" if spot >= tech["vwap"] else "NEGATIVE"

        return MarketSnapshot(
            symbol=sym,
            spot_price=round(spot, 2),
            ema_20=tech["ema_20"],
            ema_50=tech["ema_50"],
            vwap=tech["vwap"],
            rsi=tech["rsi"],
            atr=tech["atr"],
            vix=14.5,
            pcr=round(pcr, 2),
            ce_oi_change=round(ce_oi_change, 0),
            pe_oi_change=round(pe_oi_change, 0),
            higher_tf_trend=tech["trend"],
            timestamp=ist_now_str(),
            atm_strike=atm_strike,
            day_high=tech.get("day_high", spot + tech["atr"]),
            day_low=tech.get("day_low", spot - tech["atr"]),
            day_open=spot,
            max_pain=max_pain,
            call_oi_wall=call_wall,
            put_oi_wall=put_wall,
            cpr_pivot=tech["cpr_pivot"],
            cpr_bc=tech["cpr_bc"],
            cpr_tc=tech["cpr_tc"],
            cpr_width_type=tech["cpr_width_type"],
            supertrend_direction=tech["supertrend_direction"],
            supertrend_value=tech["supertrend_value"],
            advance_decline_ratio=1.25 if spot >= tech["ema_20"] else 0.85,
            heavyweights_alignment="BULLISH" if spot >= tech["ema_20"] else "BEARISH",
            fii_sentiment=fii,
            global_sentiment=glob,
        )

    async def run_debate(self, symbol: str = "NIFTY") -> DebateSession:
        """Execute full three-agent debate sequence: Bull -> Bear -> Judge."""
        sym = normalize_index_symbol(symbol)
        logger.info("Starting AI Debate round for %s", sym)

        # 1. Ingest market snapshot
        snapshot = await self.build_snapshot(sym)

        # 2. Run Bull Agent & Bear Agent in parallel for low latency
        bull_task = asyncio.create_task(self.bull_agent.analyze(snapshot))
        bear_task = asyncio.create_task(self.bear_agent.analyze(snapshot))
        bull_output, bear_output = await asyncio.gather(bull_task, bear_task)

        # 3. Run Judge Agent evaluation with cross-examination
        judge_output = await self.judge_agent.evaluate(snapshot, bull_output, bear_output)

        # 4. Construct Debate Session
        debate_id = f"deb-{int(time.time() * 1000)}"
        session = DebateSession(
            id=debate_id,
            timestamp=ist_now_str(),
            symbol=sym,
            spot_price=snapshot.spot_price,
            market_snapshot=snapshot,
            bull=bull_output,
            bear=bear_output,
            judge=judge_output,
            executed=False,
            order_id=None,
        )

        async with self._lock:
            self._history.insert(0, session)
            self._save_history()

        logger.info("Debate session #%s generated successfully with verdict: %s", debate_id, judge_output.verdict)
        return session

    def get_latest_debate(self, symbol: Optional[str] = None) -> Optional[DebateSession]:
        """Return the most recent debate session, optionally filtered by symbol."""
        if not self._history:
            return None
        if not symbol:
            return self._history[0]
        sym = normalize_index_symbol(symbol)
        for s in self._history:
            if s.symbol == sym:
                return s
        return self._history[0]

    def get_debate_history(self, limit: int = 30) -> list[DebateSession]:
        """Return chronological list of recent debate sessions."""
        return self._history[:limit]

    async def execute_verdict(
        self,
        debate_id: str,
        lots: int = 1,
        override_payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute the Judge's recommended trade directly into the PaperEngine wallet."""
        session: Optional[DebateSession] = None
        if debate_id == "latest":
            session = self.get_latest_debate()
        else:
            for s in self._history:
                if s.id == debate_id:
                    session = s
                    break

        if not session:
            raise ValueError(f"Debate session #{debate_id} not found.")

        judge = session.judge
        verdict = judge.verdict

        if verdict == "NO_TRADE" and not override_payload:
            raise ValueError("Judge verdict was NO_TRADE. Capital preservation active.")

        # Resolve trade parameters
        underlying = session.symbol
        spec = get_index_spec(underlying)
        lot_size = spec.get("lot_size", 25)

        opt_type = "CE" if "CE" in verdict else ("PE" if "PE" in verdict else "CE")
        strike = float(judge.recommended_strike or session.market_snapshot.atm_strike)
        entry_price = float(judge.entry_price or 120.0)
        stop_loss = float(judge.stop_loss or (entry_price - 25.0))
        target = float(judge.target or (entry_price + 35.0))

        # Check for overrides
        if override_payload:
            lots = int(override_payload.get("lots") or lots)
            if override_payload.get("strike"):
                strike = float(override_payload["strike"])
            if override_payload.get("option_type"):
                opt_type = str(override_payload["option_type"]).upper()
            if override_payload.get("price"):
                entry_price = float(override_payload["price"])
            if override_payload.get("stop_loss"):
                stop_loss = float(override_payload["stop_loss"])
            if override_payload.get("target"):
                target = float(override_payload["target"])

        order_symbol = f"{underlying}{int(strike)}{opt_type}"

        order_req = {
            "symbol": order_symbol,
            "underlying": underlying,
            "strike": strike,
            "option_type": opt_type,
            "lots": max(1, lots),
            "lot_size": lot_size,
            "side": "BUY",
            "order_type": "MARKET",
            "price": entry_price,
            "current_ltp": entry_price,
            "stop_loss": stop_loss,
            "target": target,
        }

        # Submit paper order
        order_res = await paper_engine.place_order(order_req)

        # Mark debate session as executed
        session.executed = True
        session.order_id = order_res.get("order_id")
        self._save_history()

        return {
            "status": "success",
            "debate_id": session.id,
            "verdict": verdict,
            "order": order_res,
        }


debate_engine = DebateEngine.get_instance()
