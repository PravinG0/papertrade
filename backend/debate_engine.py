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
from database import DebateRecordModel, PaperTradeModel, async_session_factory
from sqlalchemy import select
from config import compute_clamped_sl_target
from adaptive_memory import session_price_reference, trend_rejection
from adaptive_store import retrieve_memory

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
        self._execution_lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> DebateEngine:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def load_history(self) -> None:
        """Load past debates from the database (survives restarts / redeploys)."""
        try:
            async with async_session_factory() as session:
                rows = (
                    await session.execute(
                        select(DebateRecordModel).order_by(DebateRecordModel.created_at.desc()).limit(200)
                    )
                ).scalars().all()
            loaded: list[DebateSession] = []
            for r in rows:
                try:
                    loaded.append(DebateSession.model_validate(json.loads(r.payload)))
                except Exception:
                    continue
            async with self._lock:
                known = {x.id for x in self._history}
                self._history = sorted(
                    self._history + [x for x in loaded if x.id not in known],
                    key=lambda x: x.timestamp,
                    reverse=True,
                )
            logger.info("Loaded %d past AI debates from database", len(loaded))
        except Exception as exc:
            logger.warning("Could not load debate history from DB: %s", exc)

    async def _persist(self, sess: DebateSession) -> None:
        """Upsert one session into the database."""
        try:
            payload = json.dumps(sess.model_dump(mode="json"))
            async with async_session_factory() as session:
                row = await session.get(DebateRecordModel, sess.id)
                if row is None:
                    row = DebateRecordModel(id=sess.id, symbol=sess.symbol, created_at=sess.timestamp, payload=payload)
                    session.add(row)
                row.payload = payload
                row.user_id = sess.user_id
                row.executed = 1 if sess.executed else 0
                row.order_id = sess.order_id
                row.position_id = sess.position_id
                await session.commit()
        except Exception as exc:
            logger.warning("Could not persist debate %s: %s", sess.id, exc)

    async def get_history_with_outcomes(self, limit: int = 30, user_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Debate history; executed trades carry their live/closed outcome (SL/target/exit P&L)."""
        if user_id is None:
            return []  # sign in to keep a personal debate history
        sessions = [x for x in self._history if x.user_id == user_id][:limit]
        pos_ids = [x.position_id for x in sessions if x.position_id]
        closed: dict[str, PaperTradeModel] = {}
        if pos_ids:
            try:
                async with async_session_factory() as session:
                    rows = (
                        await session.execute(select(PaperTradeModel).where(PaperTradeModel.id.in_(pos_ids)))
                    ).scalars().all()
                closed = {r.id: r for r in rows}
            except Exception as exc:
                logger.warning("Outcome lookup failed: %s", exc)

        out: list[dict[str, Any]] = []
        for x in sessions:
            item = x.model_dump(mode="json")
            outcome = None
            if x.position_id and (x.user_id == user_id):
                live = paper_engine.active_positions.get(x.position_id)
                if live:
                    outcome = {
                        "status": "OPEN",
                        "entry_price": live.get("entry_price"),
                        "ltp": live.get("current_ltp"),
                        "stop_loss": live.get("stop_loss"),
                        "target": live.get("target"),
                        "pnl": live.get("unrealized_pnl", 0.0),
                        "exit_reason": None,
                    }
                elif x.position_id in closed:
                    t = closed[x.position_id]
                    outcome = {
                        "status": t.status,
                        "entry_price": t.entry_price,
                        "exit_price": t.exit_price,
                        "stop_loss": t.stop_loss,
                        "target": t.target,
                        "pnl": t.realized_pnl if t.status == "CLOSED" else t.pnl,
                        "exit_reason": t.exit_reason,
                        "closed_at": t.closed_at,
                    }
            item["outcome"] = outcome
            out.append(item)
        return out

    async def build_snapshot(self, symbol: str = "NIFTY") -> MarketSnapshot:
        """Construct full point-in-time MarketSnapshot from Angel One live feed."""
        sym = normalize_index_symbol(symbol)
        spec = get_index_spec(sym)
        step = spec.get("strike_step", 50)

        # 1. Spot price
        spots = await angel_service.get_spot_indices()
        selected = next((s for s in spots if s.get("symbol") == sym), {})
        require_live = angel_service.is_configured() or not settings.ALLOW_SIMULATED_TRADING
        if require_live and selected.get("source") != "live":
            raise ValueError(f"Live spot price unavailable for {sym}; debate skipped.")
        spot = float(selected.get("ltp") or 0)
        if spot <= 0:
            raise ValueError(f"Invalid spot price for {sym}.")

        # ATM Strike
        atm_strike = float(round(spot / step) * step)

        # 2. Candlestick feed (5-minute interval)
        candle_meta = await angel_service.get_candles_with_meta(sym, interval="5m", range_period="5d")
        candles = candle_meta.get("candles") or []
        candle_source = str(candle_meta.get("source") or "unavailable")
        last_candle_ist = candle_meta.get("last_candle_ist")
        candle_reason = candle_meta.get("reason")

        if not candles or candle_source == "unavailable":
            raise ValueError(candle_reason or f"Historical candle data for {sym} is unavailable; debate skipped.")
        if require_live and candle_source in ("stale", "simulated"):
            raise ValueError(
                candle_reason
                or f"Historical candle data for {sym} is {candle_source}; debate skipped to avoid stale or simulated data."
            )
        if len(candles) < 20:
            raise ValueError(
                f"Insufficient historical candles for {sym} ({len(candles)} received, minimum 20 required for EMA/RSI/ATR/VWAP)."
            )
        now = datetime.now(IST)
        opening, session_vwap, reference = session_price_reference(candles, now)
        # Use the broker's actual day-open if the opening candle was unavailable.
        if opening is None and selected.get("open") and float(selected["open"]) != spot:
            opening = float(selected["open"])
        today_candles = [
            c for c in candles
            if c.get("time") is not None and datetime.fromtimestamp(float(c["time"]), IST).date() == now.date()
        ]
        session_high = max((float(c["high"]) for c in today_candles), default=None)
        session_low = min((float(c["low"]) for c in today_candles), default=None)
        tech = _calc_indicators(candles[-60:], spot)
        if session_high is not None:
            tech["day_high"] = session_high
        if session_low is not None:
            tech["day_low"] = session_low
        from market_indicators import prior_session_cpr, supertrend
        tech.update(prior_session_cpr(candles, now) or dict(cpr_pivot=None, cpr_bc=None, cpr_tc=None, cpr_width_type="UNAVAILABLE"))
        tech.update(supertrend(candles) or dict(supertrend_direction="UNAVAILABLE", supertrend_value=None))

        # 3. Option chain feed
        pcr = None
        max_pain = atm_strike
        call_wall = atm_strike + step
        put_wall = atm_strike - step
        ce_oi_change = 0.0
        pe_oi_change = 0.0

        try:
            chain_data = await angel_service.get_option_chain(sym, strikes_count=12)
            if require_live and (not chain_data or chain_data.get("data_source") != "live"):
                raise ValueError("Live option chain unavailable; debate skipped.")
            if chain_data:
                pcr = float(chain_data["pcr"]) if chain_data.get("pcr") is not None else None
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
            if require_live:
                raise ValueError("Live option chain unavailable; debate skipped.") from exc
            logger.debug("Option chain metrics extraction skipped: %s", exc)

        # 4. Macro sentiment
        fii = "UNAVAILABLE"
        glob = "UNAVAILABLE"

        return MarketSnapshot(
            symbol=sym,
            spot_price=round(spot, 2),
            ema_20=tech["ema_20"],
            ema_50=tech["ema_50"],
            vwap=round(session_vwap, 2) if session_vwap is not None else tech["vwap"],
            session_reference=reference,
            rsi=tech["rsi"],
            atr=tech["atr"],
            vix=float(angel_service.vix) if angel_service.vix is not None else None,
            pcr=round(pcr, 2) if pcr is not None else None,
            ce_oi_change=round(ce_oi_change, 0),
            pe_oi_change=round(pe_oi_change, 0),
            higher_tf_trend=tech["trend"],
            timestamp=ist_now_str(),
            atm_strike=atm_strike,
            day_high=tech.get("day_high", spot + tech["atr"]),
            day_low=tech.get("day_low", spot - tech["atr"]),
            day_open=opening,
            max_pain=max_pain,
            call_oi_wall=call_wall,
            put_oi_wall=put_wall,
            cpr_pivot=tech["cpr_pivot"],
            cpr_bc=tech["cpr_bc"],
            cpr_tc=tech["cpr_tc"],
            cpr_width_type=tech["cpr_width_type"],
            supertrend_direction=tech["supertrend_direction"],
            supertrend_value=tech["supertrend_value"],
            advance_decline_ratio=None,
            heavyweights_alignment="UNAVAILABLE",
            fii_sentiment=fii,
            global_sentiment=glob,
            data_status=candle_source,
            last_candle_ist=last_candle_ist,
            candle_count=len(candles),
        )

    async def run_debate(self, symbol: str = "NIFTY", user_id: Optional[int] = None) -> DebateSession:
        """Execute full three-agent debate sequence: Bull -> Bear -> Judge."""
        sym = normalize_index_symbol(symbol)
        logger.info("Starting AI Debate round for %s", sym)

        # 1. Ingest market snapshot
        snapshot = await self.build_snapshot(sym)

        # Account-scoped memory per request; never mutate shared agent prompts.
        try:
            memory = await retrieve_memory(user_id, snapshot.model_dump())
        except Exception as exc:
            logger.warning("Memory lookup unavailable: %s", type(exc).__name__)
            memory = "### EPISODIC TRADING MEMORY (LESSONS FROM RECENT LOSSES & WINS)\nHistorical memory unavailable; do not invent prior results."
        # 2. Run Bull Agent & Bear Agent in parallel for low latency
        bull_task = asyncio.create_task(self.bull_agent.analyze(snapshot, memory=memory))
        bear_task = asyncio.create_task(self.bear_agent.analyze(snapshot, memory=memory))
        bull_output, bear_output = await asyncio.gather(bull_task, bear_task)

        # 3. Run Judge Agent evaluation with cross-examination
        judge_output = await self.judge_agent.evaluate(snapshot, bull_output, bear_output, memory=memory)
        if judge_output.verdict in ("BUY CE", "BUY PE"):
            rejection = trend_rejection(snapshot.model_dump(), judge_output.verdict[-2:], settings.AUTO_TREND_THRESHOLD_PCT)
            # A genuine counter-trend verdict becomes NO_TRADE. Unknown data is
            # flagged here and fails closed at automatic execution.
            if rejection and snapshot.day_open and snapshot.session_reference != "UNKNOWN":
                judge_output = judge_output.model_copy(update={
                    "verdict": "NO_TRADE", "recommended_strike": 0.0, "selected_strike": None,
                    "entry_price": 0.0, "stop_loss": 0.0, "target": 0.0,
                    "risk_reward_ratio": "N/A", "risk_warning": rejection,
                    "reasoning": rejection + " Original AI reasoning: " + judge_output.reasoning,
                })

        # 4. Construct Debate Session
        import uuid
        debate_id = f"deb-{uuid.uuid4().hex}"
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
            episodic_memory=memory,
            order_id=None,
            user_id=user_id,
        )

        async with self._lock:
            self._history.insert(0, session)
            del self._history[200:]
        await self._persist(session)

        logger.info("Debate session #%s generated successfully with verdict: %s", debate_id, judge_output.verdict)
        return session

    def get_latest_debate(
        self, symbol: Optional[str] = None, user_id: Optional[int] = None
    ) -> Optional[DebateSession]:
        """Most recent debate belonging to this account (guests have none), optionally by symbol."""
        if user_id is None:
            return None
        mine = [x for x in self._history if x.user_id == user_id]
        if not mine:
            return None
        if not symbol:
            return mine[0]
        sym = normalize_index_symbol(symbol)
        for s in mine:
            if s.symbol == sym:
                return s
        return None

    def get_debate_history(self, limit: int = 30) -> list[DebateSession]:
        """Return chronological list of recent debate sessions."""
        return self._history[:limit]

    async def execute_verdict(
        self,
        debate_id: str,
        lots: int = 1,
        override_payload: Optional[dict[str, Any]] = None,
        user_id: Optional[int] = None,
        auto: bool = False,
    ) -> dict[str, Any]:
        """Serialize execution to prevent duplicate fills of the same verdict."""
        async with self._execution_lock:
            return await self._execute_verdict_locked(debate_id, lots, override_payload, user_id, auto)

    async def _execute_verdict_locked(self, debate_id, lots, override_payload, user_id, auto):
        from replay_engine import replay_engine
        if replay_engine.is_replaying:
            raise ValueError("AI trade execution is unavailable during historical replay.")
        session: Optional[DebateSession] = None
        if debate_id == "latest":
            session = self.get_latest_debate(user_id=user_id)
        else:
            for x in self._history:
                if x.id == debate_id:
                    session = x
                    break
        if not session or session.user_id != user_id:
            raise ValueError(f"Debate session #{debate_id} not found.")
        if user_id is None:
            raise ValueError("AI execution requires a signed-in account.")
        if session.executed:
            raise ValueError("This debate verdict was already executed.")

        judge = session.judge
        if auto and not angel_service.is_configured():
            raise ValueError("Automatic trading requires a configured live market feed.")
        if auto and any(agent.analysis_source != "gemini" for agent in (session.bull, session.bear, judge)):
            raise ValueError("Automatic execution requires successful Gemini analysis from all three agents.")
        verdict = judge.verdict
        if verdict == "NO_TRADE":
            raise ValueError("Judge verdict was NO_TRADE. Capital preservation active.")

        underlying = session.symbol
        spec = get_index_spec(underlying)
        step = spec.get("strike_step", 50)

        opt_type = "CE" if "CE" in verdict else ("PE" if "PE" in verdict else "CE")
        strike = float(judge.recommended_strike or session.market_snapshot.atm_strike)
        strike = float(round(strike / step) * step)

        judge_entry = float(judge.entry_price or 0.0)
        judge_sl = float(judge.stop_loss or 0.0)
        judge_tgt = float(judge.target or 0.0)

        if override_payload:
            lots = int(override_payload.get("lots") or lots)
            if override_payload.get("strike"):
                strike = float(override_payload["strike"])
            if override_payload.get("option_type"):
                opt_type = str(override_payload["option_type"]).upper()

        # Rebuild live context at execution, not only at debate creation.
        evidence_snapshot = session.market_snapshot
        if auto:
            evidence_snapshot = await self.build_snapshot(underlying)
            if getattr(evidence_snapshot, "data_status", "unknown") not in ("live", "cached"):
                raise ValueError(
                    f"Automatic execution blocked: market candle feed for {underlying} is {evidence_snapshot.data_status}."
                )
            rejection = trend_rejection(evidence_snapshot.model_dump(), opt_type, settings.AUTO_TREND_THRESHOLD_PCT)
            if rejection:
                raise ValueError(rejection)

        if lots <= 0 or opt_type not in ("CE", "PE"):
            raise ValueError("Invalid quantity or option type")
        # ── Live price for the exact contract ────────────────────────────
        quote = await angel_service.get_option_quote(underlying, strike, opt_type)
        if quote:
            entry_price = quote["ltp"]
            order_symbol = quote["symbol"]
        elif angel_service.is_configured() or not settings.ALLOW_SIMULATED_TRADING:
            raise ValueError(f"Live price for {underlying} {int(strike)} {opt_type} is unavailable; trade not executed.")
        else:
            entry_price = judge_entry if judge_entry > 0 else 120.0
            order_symbol = f"{underlying}{int(strike)}{opt_type}"

        # Keep the Judge's risk shape (% distance) but anchor it to the real entry price
        if judge_entry > 0 and 0 < judge_sl < judge_entry:
            sl_pct = (judge_entry - judge_sl) / judge_entry
        else:
            sl_pct = 0.20
        if judge_entry > 0 and judge_tgt > judge_entry:
            tgt_pct = (judge_tgt - judge_entry) / judge_entry
        else:
            tgt_pct = 0.30
        stop_loss = round(entry_price * (1 - sl_pct), 2)
        target = round(entry_price * (1 + tgt_pct), 2)
        if override_payload:
            if override_payload.get("stop_loss"):
                stop_loss = float(override_payload["stop_loss"])
            if override_payload.get("target"):
                target = float(override_payload["target"])
        lot_size = int(quote["lot_size"] if quote else spec["lot_size"])
        stop_loss, target = compute_clamped_sl_target(
            underlying, entry_price, stop_loss, target, quantity=lots * lot_size)

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

        order_res = await paper_engine.place_order(order_req, user_id=user_id, ai_evidence={
            "debate_id": session.id, "auto_executed": auto,
            "snapshot": evidence_snapshot.model_dump(mode="json"), "confidence": judge.confidence,
        })
        if order_res.get("status") != "EXECUTED" or not order_res.get("position_id"):
            raise ValueError(order_res.get("reject_reason") or order_res.get("message") or "Order did not open a position.")

        session.executed = True
        session.auto_executed = auto
        session.user_id = user_id
        session.order_id = order_res.get("order_id")
        session.position_id = order_res.get("position_id")
        session.exec_entry_price = entry_price
        session.exec_symbol = order_symbol
        session.skip_reason = None
        await self._persist(session)

        return {
            "status": "success",
            "debate_id": session.id,
            "verdict": verdict,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "target": target,
            "symbol": order_symbol,
            "order": order_res,
        }

    async def mark_skipped(self, session: DebateSession, reason: str) -> None:
        session.skip_reason = reason
        await self._persist(session)


debate_engine = DebateEngine.get_instance()
