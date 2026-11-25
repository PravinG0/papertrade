"""Dependency-light tests: no trading accounts, DB drivers or network needed."""
import math
from greeks import BlackScholesEngine, calculate_strategy_payoff
from scrip_master import ScripMaster


def test_put_call_parity():
    s = k = 25000
    t, r, sigma = 7 / 365, .07, .15
    c = BlackScholesEngine.calculate_price(s, k, t, r, sigma, "CE")
    p = BlackScholesEngine.calculate_price(s, k, t, r, sigma, "PE")
    assert abs(c - p - (s - k * math.exp(-r*t))) < .1


def test_delta_parity():
    args = (25000, 25000, 7/365, .07, .15)
    c = BlackScholesEngine.calculate_greeks(*args, "CE")
    p = BlackScholesEngine.calculate_greeks(*args, "PE")
    assert abs(c['delta'] - p['delta'] - 1) < .05


def test_implied_volatility():
    c = BlackScholesEngine.calculate_price(25000, 25000, 7/365, .07, .16, "CE")
    iv = BlackScholesEngine.calculate_implied_volatility(25000, 25000, 7/365, c, .07, "CE")
    assert abs(iv - 16) < .2


def test_spread_payoff():
    res = calculate_strategy_payoff(25000, [
        {"strike": 25000, "option_type": "CE", "side": "BUY", "quantity": 25, "price": 120},
        {"strike": 25200, "option_type": "CE", "side": "SELL", "quantity": 25, "price": 40},
    ])
    assert abs(res['max_loss'] + 2000) < 1


def test_exact_expiry_never_rolls_to_another_contract():
    master = ScripMaster()
    master._index([['NIFTY', '2099-12-31', 25000, 'CE', 'NFO', '123', 'NIFTY31DEC9925000CE', 65]])
    assert master.resolve('NIFTY31DEC9925000CE', 'NIFTY', 25000, 'CE').token == '123'
    assert master.resolve('NIFTY24DEC9925000CE', 'NIFTY', 25000, 'CE') is None
    assert master.resolve('NIFTY25000CE', 'NIFTY', 25000, 'CE').token == '123'
