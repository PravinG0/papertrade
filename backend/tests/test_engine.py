"""Comprehensive automated test suite for The TradeLab Paper Trading Engine.

Covers:
- Black-Scholes Greeks analytical formulas
- Indian Statutory Taxes & Regulatory Charges calculation
- Paper Portfolio, Order Book & Trailing Stop Loss
- Multi-leg Strategy Payoff Analyzer
- Market Replay Simulator
- Institutional AI Multi-Agent Quantitative Engine
"""

import pytest
import math
from greeks import (
    BlackScholesEngine,
    calculate_strategy_payoff,
)
from paper_engine import (
    PaperEngine,
    calculate_trade_charges,
)
from replay_engine import ReplayEngine
from debate_schemas import MarketSnapshot
from agents.bull_agent import BullAgent
from agents.bear_agent import BearAgent
from agents.judge_agent import JudgeAgent


# ── 1. Black-Scholes Greeks Tests ──────────────────────────────────────────────
def test_black_scholes_pricing():
    spot = 25000.0
    strike = 25000.0
    t_years = 7.0 / 365.0
    r = 0.07
    sigma = 0.15

    call_price = BlackScholesEngine.calculate_price(spot, strike, t_years, r, sigma, option_type="CE")
    put_price = BlackScholesEngine.calculate_price(spot, strike, t_years, r, sigma, option_type="PE")

    assert call_price > 0
    assert put_price > 0
    # Put-Call Parity: C - P ≈ S - K * exp(-r*T)
    discounted_k = strike * math.exp(-r * t_years)
    assert abs((call_price - put_price) - (spot - discounted_k)) < 0.1


def test_black_scholes_delta():
    spot = 25000.0
    strike = 25000.0
    t_years = 7.0 / 365.0
    r = 0.07
    sigma = 0.15

    ce_greeks = BlackScholesEngine.calculate_greeks(spot, strike, t_years, r, sigma, "CE")
    pe_greeks = BlackScholesEngine.calculate_greeks(spot, strike, t_years, r, sigma, "PE")

    ce_delta = ce_greeks["delta"]
    pe_delta = pe_greeks["delta"]

    assert 0.45 < ce_delta < 0.58
    assert -0.58 < pe_delta < -0.42
    # Call Delta - Put Delta ≈ 1
    assert abs((ce_delta - pe_delta) - 1.0) < 0.05


def test_black_scholes_implied_volatility():
    spot = 25000.0
    strike = 25000.0
    t_years = 7.0 / 365.0
    r = 0.07
    true_sigma = 0.16

    call_price = BlackScholesEngine.calculate_price(spot, strike, t_years, r, true_sigma, "CE")
    solved_iv = BlackScholesEngine.calculate_implied_volatility(
        spot=spot,
        strike=strike,
        time_to_expiry_years=t_years,
        market_price=call_price,
        risk_free_rate=r,
        option_type="CE",
    )

    # Solved IV in percentage (16.0%)
    assert abs(solved_iv - (true_sigma * 100)) < 0.2


def test_strategy_payoff_calculation():
    spot = 25000.0
    legs = [
        {"strike": 25000, "option_type": "CE", "side": "BUY", "quantity": 25, "price": 120.0},
        {"strike": 25200, "option_type": "CE", "side": "SELL", "quantity": 25, "price": 40.0},
    ]

    res = calculate_strategy_payoff(spot=spot, legs=legs)

    assert "curve" in res
    assert len(res["curve"]) > 0
    # Max loss is net premium debit = (120 - 40) * 25 = 2000
    assert abs(res["max_loss"] - (-2000.0)) < 1.0
    # Max profit = (200 - 80) * 25 = 3000
    assert abs(res["max_profit"] - 3000.0) < 1.0
    assert len(res["breakevens"]) == 1
    assert res["breakevens"][0] == 25080.0


# ── 2. Indian Statutory Taxes & Charges ──────────────────────────────────────
def test_statutory_charges_calculation():
    buy_turnover = 100.0 * 50   # ₹5,000
    sell_turnover = 120.0 * 50  # ₹6,000

    charges = calculate_trade_charges(buy_turnover, sell_turnover, orders_count=2)
    assert charges["brokerage"] == 40.0  # ₹20 on buy + ₹20 on sell
    assert charges["stt"] == round(sell_turnover * 0.000625, 2)  # 0.0625% on sell
    assert charges["exchange_charges"] > 0
    assert charges["stamp_duty"] > 0
    assert charges["gst"] > 0
    assert charges["total_charges"] > 40.0


# ── 3. Paper Trading Virtual Engine Tests ────────────────────────────────────
@pytest.mark.asyncio
async def test_paper_engine_lifecycle():
    engine = PaperEngine.get_instance()

    # Reset portfolio
    await engine.reset_portfolio(1000000.0)
    state = await engine.get_state()
    assert state["portfolio"]["capital"] == 1000000.0

    # Place Market Buy Order
    res = await engine.place_order({
        "symbol": "NIFTY26NOV25000CE",
        "underlying": "NIFTY",
        "strike": 25000.0,
        "option_type": "CE",
        "side": "BUY",
        "order_type": "MARKET",
        "lots": 1,
        "price": 100.0,
        "current_ltp": 100.0,
    })
    assert res.get("status") in ["SUCCESS", "EXECUTED"] or res.get("order_id")

    # Verify state has position
    state = await engine.get_state()
    assert len(state["positions"]) >= 1
    pos = state["positions"][-1]
    assert pos["symbol"] == "NIFTY26NOV25000CE"

    # Update Stop Loss
    sl_res = await engine.update_sl(pos["id"], 80.0)
    assert sl_res["status"] == "SUCCESS"

    # Exit Position
    exit_res = await engine.exit_position(pos["id"], exit_price=120.0)
    assert exit_res["status"] == "SUCCESS"
    assert exit_res["gross_pnl"] > 0
    assert exit_res["charges"]["total_charges"] > 0

    # Clean up
    await engine.reset_portfolio(1000000.0)


# ── 4. Market Replay Engine Tests ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_replay_engine():
    replay = ReplayEngine.get_instance()
    dates = replay.get_available_dates()
    assert len(dates) > 0

    test_date = dates[0]["date"]
    started = await replay.start_replay(test_date)
    assert started.get("status") == "SUCCESS"

    state = replay.get_state()
    assert state["is_replaying"] is True
    assert state["date"] == test_date

    # Step forward
    advanced = await replay.step_forward()
    assert advanced is not None

    # Change speed
    await replay.set_speed(5.0)
    assert replay.speed == 5.0

    # Stop replay
    await replay.stop_replay()
    assert replay.is_replaying is False


# ── 5. AI Multi-Agent Quantitative Engine Tests ──────────────────────────────
def test_quantitative_agents_fallbacks():
    snapshot = MarketSnapshot(
        symbol="NIFTY",
        spot_price=25100.0,
        ema_20=25050.0,
        ema_50=24950.0,
        vwap=25080.0,
        rsi=62.5,
        pcr=1.15,
        atm_strike=25100.0,
        higher_tf_trend="BULLISH",
    )

    bull = BullAgent()
    bull_out = bull._fallback_output(snapshot)
    assert bull_out.thesis != ""
    assert bull_out.confidence >= 5

    bear = BearAgent()
    bear_out = bear._fallback_output(snapshot)
    assert bear_out.thesis != ""
    assert 1 <= bear_out.confidence <= 10

    judge = JudgeAgent()
    judge_out = judge._fallback_output(snapshot, bull_out, bear_out)
    assert judge_out.verdict in ["BUY CE", "BUY PE", "NO_TRADE"]
    assert judge_out.reasoning != ""
