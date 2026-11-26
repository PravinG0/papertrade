"""Comprehensive QA audit tests for TradeLab V5 indicators, agents, quant rules, and research isolation."""

from __future__ import annotations

import math
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from angel_service import AngelService
from config import compute_clamped_sl_target
from debate_engine import DebateEngine, _calc_indicators
from debate_schemas import BearAgentOutput, BullAgentOutput, JudgeAgentOutput, MarketSnapshot
from market_indicators import supertrend
from paper_engine import calculate_trade_charges
from quant_engine import (
    calibration_summary,
    estimate_option_greeks,
    frame_features,
    market_regime,
    option_validation,
    validate_direction,
)
from research_backtest import run_research

IST = ZoneInfo("Asia/Kolkata")


def _ref_ema(values: list[float], span: int) -> float:
    alpha = 2.0 / (span + 1.0)
    val = sum(values[:span]) / span
    for p in values[span:]:
        val = p * alpha + val * (1.0 - alpha)
    return val


def _ref_rsi(closes: list[float], period: int = 14) -> float:
    gains = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    losses = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, len(closes))]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return 100.0 - (100.0 / (1.0 + ag / al))


def _ref_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    trs = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return atr


def test_indicators_match_independent_reference():
    candles = []
    base = 25000.0
    t0 = int(datetime(2026, 11, 26, 9, 15, tzinfo=IST).timestamp())
    for i in range(60):
        c = base + (i * 4.5) + math.sin(i / 3.0) * 12.0
        o = c - 3.0
        h = max(o, c) + 8.0
        l = min(o, c) - 7.0
        candles.append({"time": t0 + i * 300, "open": o, "high": h, "low": l, "close": c, "volume": 1000 + i * 25})

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    vols = [c["volume"] for c in candles]

    tech = _calc_indicators(candles, spot=closes[-1])
    assert tech["ema_20"] == pytest.approx(_ref_ema(closes, 20), abs=0.02)
    assert tech["ema_50"] == pytest.approx(_ref_ema(closes, 50), abs=0.02)
    assert tech["rsi"] == pytest.approx(_ref_rsi(closes, 14), abs=0.02)
    assert tech["atr"] == pytest.approx(_ref_atr(highs, lows, closes, 14), abs=0.02)

    typ = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
    ref_vwap = sum(tp * v for tp, v in zip(typ, vols)) / sum(vols)
    assert tech["vwap"] == pytest.approx(ref_vwap, abs=0.02)

    st = supertrend(candles)
    assert st["supertrend_direction"] in ("BULLISH", "BEARISH")
    assert st["supertrend_value"] is not None and st["supertrend_value"] > 0

    # Black-Scholes Greeks & IV sanity
    greeks = estimate_option_greeks(
        spot=25000.0, strike=25000.0, option_type="CE",
        expiry=(datetime.now(IST) + timedelta(days=5)).strftime("%Y-%m-%d"),
        quote={"bid": 179.5, "ask": 180.5, "ltp": 180.0},
        now=datetime.now(IST),
    )
    assert greeks["status"] == "estimated"
    assert "Black-Scholes midpoint" in greeks["basis"]
    assert 0.3 < greeks["delta"] < 0.7


def test_regime_and_direction_validation_scenarios():
    bull_frame = {"direction": "BULLISH", "count": 50, "ema_20": 25100, "ema_50": 25000, "atr": 40, "close": 25120, "ema_separation_atr": 2.5}
    bear_frame = {"direction": "BEARISH", "count": 50, "ema_20": 24900, "ema_50": 25000, "atr": 40, "close": 24880, "ema_separation_atr": 2.5}
    flat_frame = {"direction": "NEUTRAL", "count": 50, "ema_20": 25005, "ema_50": 25000, "atr": 50, "close": 25002, "ema_separation_atr": 0.1}

    assert market_regime({"1d": bull_frame, "1h": bull_frame, "15m": bull_frame, "5m": bull_frame, "1m": bull_frame}) == "BULL_TREND"
    assert market_regime({"1d": bear_frame, "1h": bear_frame, "15m": bear_frame, "5m": bear_frame, "1m": bear_frame}) == "BEAR_TREND"
    assert market_regime({"1d": flat_frame, "1h": flat_frame, "15m": flat_frame, "5m": flat_frame, "1m": flat_frame}) == "RANGE_OR_TRANSITION"

    # Conflicting timeframes rejected
    snap_conflict = {
        "data_status": "live", "spot_fresh": True, "spot_price": 25120, "vwap": 25080,
        "session_reference": "VWAP", "supertrend_direction": "BULLISH",
        "timeframes": {"1d": bull_frame, "1h": bull_frame, "15m": bull_frame, "5m": bull_frame, "1m": bear_frame},
    }
    res_conflict = validate_direction(snap_conflict, "BUY CE", confidence=9)
    assert res_conflict["eligible"] is False

    # Valid BUY PE accepted
    snap_bear = {
        "data_status": "live", "spot_fresh": True, "session_active": True, "spot_price": 24880, "vwap": 24920,
        "session_reference": "VWAP", "supertrend_direction": "BEARISH",
        "timeframes": {"1d": bear_frame, "1h": bear_frame, "15m": bear_frame, "5m": bear_frame, "1m": bear_frame},
    }
    res_pe = validate_direction(snap_bear, "BUY PE", confidence=8)
    assert res_pe["eligible"] is True

    # Calibration never treats <30 samples or confidence 8/10 as 80% probability
    cal = calibration_summary([{"verified": True, "confidence": 8, "net_pnl": 500.0} for _ in range(5)])
    band_7_8 = next(b for b in cal if b["band"] == "7-8")
    assert band_7_8["sufficient_sample"] is False
    assert band_7_8["n"] == 5


@pytest.mark.asyncio
async def test_agents_receive_memory_and_fallback_blocked_from_auto_exec():
    engine = DebateEngine()
    snap = MarketSnapshot(
        symbol="NIFTY", spot_price=25100.0, ema_20=25080.0, ema_50=25020.0, vwap=25050.0,
        rsi=61.0, atr=35.0, higher_tf_trend="BULLISH", atm_strike=25100.0,
        day_open=25000.0, session_reference="VWAP", supertrend_direction="BULLISH",
        data_status="live", spot_fresh=True,
        timeframes={k: {"direction": "BULLISH", "count": 50} for k in ("1d", "1h", "15m", "5m", "1m")},
    )
    bull_mock = AsyncMock(return_value=BullAgentOutput(
        analysis_source="gemini", confidence=8, strike=25100.0, thesis="Bullish alignment",
        arguments=["EMA20 > EMA50"],
    ))
    bear_mock = AsyncMock(return_value=BearAgentOutput(
        analysis_source="fallback", confidence=6, strike=25100.0, thesis="Overbought risk",
        arguments=["RSI 61"],
    ))
    judge_mock = AsyncMock(return_value=JudgeAgentOutput(
        analysis_source="gemini", verdict="BUY CE", confidence=8, recommended_strike=25100.0,
        entry_price=140.0, stop_loss=125.0, target=175.0, reasoning="Aligned setup",
    ))

    with (
        patch.object(engine, "build_snapshot", AsyncMock(return_value=snap)),
        patch("debate_engine.retrieve_memory", AsyncMock(return_value="TEST_MEMORY_TOKEN")),
        patch.object(engine.bull_agent, "analyze", bull_mock),
        patch.object(engine.bear_agent, "analyze", bear_mock),
        patch.object(engine.judge_agent, "evaluate", judge_mock),
        patch.object(engine, "_persist", AsyncMock()),
    ):
        sess = await engine.run_debate("NIFTY", user_id=1)

    assert bull_mock.await_args.kwargs["memory"] == "TEST_MEMORY_TOKEN"
    assert bear_mock.await_args.kwargs["memory"] == "TEST_MEMORY_TOKEN"
    assert judge_mock.await_args.kwargs["memory"] == "TEST_MEMORY_TOKEN"
    # Partial Gemini fallback must cause quantitative_validation to block automatic execution
    assert sess.quantitative_validation["eligible"] is False
    assert sess.judge.verdict == "NO_TRADE"
    assert sess.original_judge_verdict == "BUY CE"


def test_old_vs_v5_backtest_comparison_harness():
    # Chronological synthetic option OHLC fixture to verify research_backtest Champion vs Challenger
    bars = []
    t0 = datetime(2026, 11, 20, 9, 20, tzinfo=IST)
    candidates = []
    for i in range(12):
        dec_t = t0 + timedelta(minutes=i * 30)
        sym = f"NIFTY_OPT_{i}"
        # 6 good setups (quant_eligible=True) that hit target, 6 noisy setups (quant_eligible=False) that hit SL
        good = (i % 2 == 0)
        candidates.append({
            "id": f"cand-{i}",
            "decision_at": dec_t.isoformat(),
            "available_at": (dec_t + timedelta(seconds=2)).isoformat(),
            "features_at": dec_t.isoformat(),
            "expiry_at": (dec_t + timedelta(days=3)).isoformat(),
            "contract": sym,
            "verdict": "BUY CE",
            "quantity": 65,
            "reference_entry": 100.0,
            "stop": 90.0,
            "target": 120.0,
            "max_bars": 5,
            "quant_eligible": good,
            "features": {"confidence": 9 if good else 6, "net_rr": 1.7 if good else 0.9},
        })
        b1 = dec_t + timedelta(minutes=5)
        b2 = dec_t + timedelta(minutes=10)
        if good:
            bars_list = [
                {"timestamp": b1.isoformat(), "open": 100.0, "high": 104.0, "low": 98.0, "close": 103.0},
                {"timestamp": b2.isoformat(), "open": 103.0, "high": 121.0, "low": 102.0, "close": 120.0},
            ]
        else:
            bars_list = [
                {"timestamp": b1.isoformat(), "open": 100.0, "high": 102.0, "low": 89.0, "close": 90.0},
            ]
        bars.append((sym, bars_list))

    dataset = {
        "provenance": "historical_contract_ohlc",
        "initial_capital": 1000000.0,
        "assumptions": {"interval_minutes": 5, "slippage_bps": 10, "fixed_fee": 40, "turnover_fee_bps": 5},
        "candidates": candidates,
        "bars_by_contract": dict(bars),
    }
    report = run_research(dataset)
    champ = report["champion"]
    chall = report["challenger"]
    assert champ["trades"] == 12
    assert chall["trades"] == 6
    assert chall["net_pnl"] > champ["net_pnl"]
    assert chall["win_rate"] > champ["win_rate"]
    assert champ["ending_capital"] != chall["ending_capital"]
