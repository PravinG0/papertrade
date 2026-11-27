"""Comprehensive tests for TradeLab Cloud V6: Shadow Trading, Champion vs Challenger, Dynamic Risk Limits, and MCX Paper Trading."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from adaptive_store import guard_auto_fill
from database import PaperTradeModel, PortfolioModel, UserModel, async_session_factory, init_db
from mcx_market import (
    CommodityContract,
    calculate_mcx_charges,
    get_mcx_paper_state,
    mcx_technical_summary,
    place_mcx_paper_order,
    settle_mcx_positions,
)
from shadow_engine import (
    get_risk_settings,
    get_shadow_summary,
    record_debate_opportunity,
    update_risk_settings,
    update_shadow_positions,
)

IST = ZoneInfo("Asia/Kolkata")


@pytest.mark.asyncio
async def test_shadow_trading_and_champion_vs_challenger_isolation():
    await init_db()
    uid = 901

    # 1. Accepted V6 proposal -> opens in BOTH Champion & Challenger
    accepted_sess = SimpleNamespace(
        id="deb-v6-acc",
        timestamp="2026-11-27 10:00:00 IST",
        symbol="NIFTY",
        original_judge_verdict="BUY CE",
        judge=SimpleNamespace(verdict="BUY CE", confidence=9, recommended_strike=25800.0, entry_price=150.0, stop_loss=130.0, target=190.0),
        market_snapshot=SimpleNamespace(market_regime="BULL_TREND"),
        quantitative_validation={
            "eligible": True,
            "reasons": [],
            "option": {"symbol": "NIFTY01DEC2625800CE", "entry_price": 150.0, "quantity": 65},
        },
    )
    await record_debate_opportunity(uid, accepted_sess)

    # 2. Rejected V6 proposal -> opens in Champion ONLY, recorded as rejected for Challenger
    rejected_sess = SimpleNamespace(
        id="deb-v6-rej",
        timestamp="2026-11-27 10:15:00 IST",
        symbol="NIFTY",
        original_judge_verdict="BUY PE",
        judge=SimpleNamespace(verdict="NO_TRADE", confidence=7, recommended_strike=25800.0, entry_price=140.0, stop_loss=125.0, target=160.0),
        market_snapshot=SimpleNamespace(market_regime="RANGE_OR_TRANSITION"),
        quantitative_validation={
            "eligible": False,
            "reasons": ["15m timeframe disagrees"],
            "option": {"symbol": "NIFTY01DEC2625800PE", "entry_price": 140.0, "quantity": 65},
        },
    )
    await record_debate_opportunity(uid, rejected_sess)

    summary = await get_shadow_summary(uid)
    assert summary["opportunities_total"] == 2
    assert summary["accepted_count"] == 1
    assert summary["rejected_count"] == 1
    assert summary["champion"]["open_count"] == 2
    assert summary["challenger"]["open_count"] == 1

    # Settle Challenger CE at target (190) and Champion PE at stop loss (120)
    settled = await update_shadow_positions(uid, {"NIFTY01DEC2625800CE": 192.0, "NIFTY01DEC2625800PE": 120.0})
    assert settled == 3  # CE in both wallets + PE in Champion

    after = await get_shadow_summary(uid)
    assert after["challenger"]["closed_count"] == 1
    assert after["challenger"]["win_rate"] == 100.0
    assert after["champion"]["closed_count"] == 2
    assert after["champion"]["win_rate"] == 50.0
    assert after["challenger"]["net_pnl"] > after["champion"]["net_pnl"]


@pytest.mark.asyncio
async def test_dynamic_risk_limits_and_no_count_limit_mode():
    await init_db()
    uid = 902
    async with async_session_factory() as db:
        db.add(UserModel(id=uid, username="risk_tester", email="risk_tester@example.com", hashed_password="x"))
        db.add(PortfolioModel(user_id=uid, initial_capital=1000000.0, cash_balance=1000000.0, margin_used=0.0))
        now = datetime.now(IST)
        # Add 2 closed losing trades today totaling -4000 (exceeds max_daily_loss_inr=3500)
        for idx in range(2):
            ts = (now - timedelta(minutes=10 - idx * 3)).strftime("%Y-%m-%d %H:%M:%S")
            db.add(PaperTradeModel(
                id=f"LOSS-{idx}", user_id=uid, symbol=f"NIFTY01DEC2625{idx}00CE", underlying="NIFTY",
                strike=25000 + idx * 100, option_type="CE", side="BUY", lots=1, quantity=65,
                entry_price=150.0, exit_price=120.0, gross_pnl=-1950.0, realized_pnl=-2000.0,
                total_charges=50.0, status="CLOSED", exit_reason="STOP_LOSS_HIT",
                created_at=ts, closed_at=ts,
            ))
        await db.commit()

    cfg = await update_risk_settings(uid, {"no_count_limit": True, "max_daily_loss_inr": 3500.0})
    assert cfg["no_count_limit"] is True
    assert cfg["max_daily_trades"] == 0

    async with async_session_factory() as db:
        reason = await guard_auto_fill(db, uid, {"underlying": "NIFTY", "strike": 25800, "option_type": "CE"}, now=datetime.now(IST))
    assert reason is not None and "Daily loss limit reached" in reason


@pytest.mark.asyncio
async def test_mcx_charges_paper_order_and_isolated_settlement():
    await init_db()
    uid = 903
    chg = calculate_mcx_charges(35000.0, 40000.0)
    assert chg["brokerage"] == 40.0
    assert chg["ctt"] > 0 and chg["total_charges"] > 40.0

    contract = CommodityContract(
        name="CRUDEOIL", expiry="2026-12-16", strike=7800, option_type="PE",
        exchange="MCX", token="586071", symbol="CRUDEOIL16DEC267800PE", lot_size=100, tick_size=0.1,
    )
    # Winter session is open at 21:00 IST
    open_now = datetime(2026, 11, 27, 21, 0, tzinfo=IST)
    res = await place_mcx_paper_order(uid, contract, lots=1, entry_price=340.0, stop_loss=300.0, target=400.0, now=open_now)
    assert res["status"] == "FILLED"
    assert res["position"]["quantity"] == 100
    assert res["cash_balance"] == pytest.approx(1000000.0 - 34000.0, abs=0.01)

    # Settle at target 405.0 -> gross +6500 minus MCX charges
    settle = await settle_mcx_positions(uid, {"586071": 405.0})
    assert settle["settled"] == 1
    state = await get_mcx_paper_state(uid)
    assert len(state["positions"]) == 0
    assert len(state["trades"]) == 1
    assert state["realized_pnl"] > 6000.0

    # Technical summary on 30 MCX candles
    candles = [{"open": 7700 + i, "high": 7710 + i, "low": 7690 + i, "close": 7705 + i} for i in range(30)]
    tech = mcx_technical_summary(candles, 7734.0)
    assert tech["available"] is True
    assert tech["trend"] == "BULLISH"
