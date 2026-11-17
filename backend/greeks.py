"""
Analytical Black-Scholes Greeks and Option Chain Analytics Engine.

Provides exact Black-Scholes Option Pricing, Greeks (Delta, Gamma, Theta, Vega),
Implied Volatility (IV) solver, Max Pain, Put-Call Ratio (PCR), and Call/Put OI Walls.
Uses pure standard library math for high performance and zero external dependencies.
"""

from __future__ import annotations

import math
from typing import Any, Optional


class BlackScholesEngine:
    """Exact analytical Black-Scholes pricing and Greeks calculator."""

    @staticmethod
    def norm_cdf(x: float) -> float:
        """Standard normal cumulative distribution function N(x)."""
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @staticmethod
    def norm_pdf(x: float) -> float:
        """Standard normal probability density function N'(x)."""
        return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)

    @classmethod
    def calculate_price(
        cls,
        spot: float,
        strike: float,
        time_to_expiry_years: float,
        risk_free_rate: float = 0.065,
        iv: float = 0.15,
        option_type: str = "CE",
    ) -> float:
        """Calculate theoretical Black-Scholes option price."""
        T = max(0.0001, time_to_expiry_years)
        sigma = max(0.01, iv)
        S = max(0.01, spot)
        K = max(0.01, strike)
        r = risk_free_rate

        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        if option_type.upper() == "CE":
            price = S * cls.norm_cdf(d1) - K * math.exp(-r * T) * cls.norm_cdf(d2)
        else:
            price = K * math.exp(-r * T) * (1.0 - cls.norm_cdf(d2)) - S * (1.0 - cls.norm_cdf(d1))

        return max(0.05, round(price, 2))

    @classmethod
    def calculate_greeks(
        cls,
        spot: float,
        strike: float,
        time_to_expiry_years: float,
        risk_free_rate: float = 0.065,
        iv: float = 0.15,
        option_type: str = "CE",
    ) -> dict[str, float]:
        """Calculate theoretical price and Greeks (Delta, Gamma, Theta, Vega, IV)."""
        T = max(0.0001, time_to_expiry_years)
        sigma = max(0.01, iv)
        S = max(0.01, spot)
        K = max(0.01, strike)
        r = risk_free_rate

        sqrt_T = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T

        pdf_d1 = cls.norm_pdf(d1)
        cdf_d1 = cls.norm_cdf(d1)
        cdf_d2 = cls.norm_cdf(d2)

        # Gamma and Vega are identical for CE and PE
        gamma = pdf_d1 / (S * sigma * sqrt_T)
        vega = (S * sqrt_T * pdf_d1) / 100.0  # Normalized for 1% change in IV

        if option_type.upper() == "CE":
            price = S * cdf_d1 - K * math.exp(-r * T) * cdf_d2
            delta = cdf_d1
            theta = (
                -(S * pdf_d1 * sigma) / (2.0 * sqrt_T)
                - r * K * math.exp(-r * T) * cdf_d2
            ) / 365.0
        else:
            price = K * math.exp(-r * T) * (1.0 - cdf_d2) - S * (1.0 - cdf_d1)
            delta = cdf_d1 - 1.0
            theta = (
                -(S * pdf_d1 * sigma) / (2.0 * sqrt_T)
                + r * K * math.exp(-r * T) * (1.0 - cdf_d2)
            ) / 365.0

        return {
            "price": max(0.05, round(price, 2)),
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "theta": round(theta, 2),
            "vega": round(vega, 2),
            "iv": round(sigma * 100.0, 2),
        }

    @classmethod
    def calculate_implied_volatility(
        cls,
        spot: float,
        strike: float,
        time_to_expiry_years: float,
        market_price: float,
        risk_free_rate: float = 0.065,
        option_type: str = "CE",
        max_iterations: int = 25,
        tolerance: float = 1e-4,
    ) -> float:
        """Solve for Implied Volatility (IV) given market price via Newton-Raphson with bisection fallback."""
        if market_price <= 0.05 or spot <= 0 or strike <= 0 or time_to_expiry_years <= 0:
            return 15.0  # Default 15% IV

        opt_type = option_type.upper()
        # Intrinsic value check
        intrinsic = max(0.0, spot - strike if opt_type == "CE" else strike - spot)
        if market_price < intrinsic:
            market_price = intrinsic + 0.05

        sigma = 0.20  # Initial guess 20%
        for _ in range(max_iterations):
            price = cls.calculate_price(spot, strike, time_to_expiry_years, risk_free_rate, sigma, opt_type)
            diff = price - market_price
            if abs(diff) < tolerance:
                return round(sigma * 100.0, 2)

            T = max(0.0001, time_to_expiry_years)
            sqrt_T = math.sqrt(T)
            d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
            vega_raw = spot * sqrt_T * cls.norm_pdf(d1)

            if abs(vega_raw) < 1e-6:
                break

            sigma -= diff / vega_raw
            if sigma <= 0.001 or sigma > 5.0:
                # Fall back to binary search
                break

        # Bisection search fallback
        low, high = 0.01, 3.0
        for _ in range(20):
            mid = (low + high) / 2.0
            price = cls.calculate_price(spot, strike, time_to_expiry_years, risk_free_rate, mid, opt_type)
            if abs(price - market_price) < 0.1:
                return round(mid * 100.0, 2)
            if price < market_price:
                low = mid
            else:
                high = mid

        return round(max(5.0, min(200.0, sigma * 100.0)), 2)


def calculate_max_pain(chain: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate Max Pain strike and highest Call/Put OI walls from option chain data.

    Max Pain is the strike at which option buyers lose the most money (option writers profit most).
    """
    if not chain:
        return {"max_pain": 0, "call_oi_wall": 0, "put_oi_wall": 0}

    strikes = [row["strike"] for row in chain if "strike" in row]
    if not strikes:
        return {"max_pain": 0, "call_oi_wall": 0, "put_oi_wall": 0}

    max_call_oi = -1
    call_wall = strikes[-1]
    max_put_oi = -1
    put_wall = strikes[0]

    for row in chain:
        k = row.get("strike", 0)
        ce_oi = row.get("ce", {}).get("oi", 0) or 0
        pe_oi = row.get("pe", {}).get("oi", 0) or 0

        if ce_oi > max_call_oi:
            max_call_oi = ce_oi
            call_wall = k
        if pe_oi > max_put_oi:
            max_put_oi = pe_oi
            put_wall = k

    min_loss = float("inf")
    max_pain_strike = strikes[len(strikes) // 2]

    for candidate in strikes:
        total_payout = 0.0
        for row in chain:
            k = row.get("strike", 0)
            ce_oi = row.get("ce", {}).get("oi", 0) or 0
            pe_oi = row.get("pe", {}).get("oi", 0) or 0

            # If settlement is at candidate strike:
            if candidate > k:
                # Call options finish in-the-money
                total_payout += (candidate - k) * ce_oi
            elif candidate < k:
                # Put options finish in-the-money
                total_payout += (k - candidate) * pe_oi

        if total_payout < min_loss:
            min_loss = total_payout
            max_pain_strike = candidate

    return {
        "max_pain": max_pain_strike,
        "call_oi_wall": call_wall,
        "put_oi_wall": put_wall,
    }


def calculate_pcr(chain: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate total Put-Call Ratio (PCR) for Open Interest and Volume."""
    total_ce_oi = 0
    total_pe_oi = 0
    total_ce_vol = 0
    total_pe_vol = 0

    for row in chain:
        ce = row.get("ce", {})
        pe = row.get("pe", {})
        total_ce_oi += int(ce.get("oi", 0) or 0)
        total_pe_oi += int(pe.get("oi", 0) or 0)
        total_ce_vol += int(ce.get("volume", 0) or 0)
        total_pe_vol += int(pe.get("volume", 0) or 0)

    pcr_oi = round(total_pe_oi / max(total_ce_oi, 1), 3) if total_ce_oi > 0 else 1.0
    pcr_vol = round(total_pe_vol / max(total_ce_vol, 1), 3) if total_ce_vol > 0 else 1.0

    if pcr_oi > 1.25:
        sentiment = "BULLISH"
    elif pcr_oi < 0.75:
        sentiment = "BEARISH"
    else:
        sentiment = "NEUTRAL"

    return {
        "pcr_oi": pcr_oi,
        "pcr_vol": pcr_vol,
        "total_ce_oi": total_ce_oi,
        "total_pe_oi": total_pe_oi,
        "total_ce_vol": total_ce_vol,
        "total_pe_vol": total_pe_vol,
        "sentiment": sentiment,
    }


def calculate_strategy_payoff(
    spot: float,
    legs: list[dict[str, Any]],
    price_range_pct: float = 0.08,
    steps: int = 60,
) -> dict[str, Any]:
    """Calculate multi-leg option strategy payoff curve at expiry.

    Each leg:
      - strike (float): option strike price
      - option_type (str): 'CE' or 'PE'
      - side (str): 'BUY' (long) or 'SELL' (short)
      - quantity (int): total contracts/units
      - price (float): entry premium
    """
    if not legs or spot <= 0:
        return {
            "curve": [],
            "max_profit": 0.0,
            "max_loss": 0.0,
            "breakevens": [],
            "net_premium": 0.0,
            "risk_reward": "N/A",
        }

    strikes = [float(leg.get("strike", spot)) for leg in legs]
    min_strike = min(strikes) if strikes else spot
    max_strike = max(strikes) if strikes else spot

    min_s = min(spot * (1.0 - price_range_pct), min_strike * 0.98)
    max_s = max(spot * (1.0 + price_range_pct), max_strike * 1.02)
    step_size = (max_s - min_s) / max(steps, 10)

    # Net premium (Positive = Net Credit, Negative = Net Debit)
    net_premium = 0.0
    for leg in legs:
        side = str(leg.get("side", "BUY")).upper()
        qty = int(leg.get("quantity", 1))
        price = float(leg.get("price", 0.0))
        if side == "BUY":
            net_premium -= price * qty
        else:
            net_premium += price * qty

    curve = []
    prices = [round(min_s + i * step_size, 1) for i in range(steps + 1)]

    # Include exact strikes & spot in evaluation points
    exact_points = sorted(set(strikes + [spot]))
    combined_eval = sorted(set(prices + exact_points))

    prev_pnl = None
    prev_spot = None
    breakevens = []

    for s in combined_eval:
        total_pnl = 0.0
        for leg in legs:
            k = float(leg.get("strike", spot))
            opt_type = str(leg.get("option_type", "CE")).upper()
            side = str(leg.get("side", "BUY")).upper()
            qty = int(leg.get("quantity", 1))
            entry_p = float(leg.get("price", 0.0))

            # Expiry intrinsic value per unit
            if opt_type == "CE":
                intrinsic = max(0.0, s - k)
            else:
                intrinsic = max(0.0, k - s)

            if side == "BUY":
                leg_pnl = (intrinsic - entry_p) * qty
            else:
                leg_pnl = (entry_p - intrinsic) * qty

            total_pnl += leg_pnl

        total_pnl = round(total_pnl, 2)
        curve.append({
            "spot": s,
            "pnl": total_pnl,
            "is_profit": total_pnl >= 0,
        })

        # Detect breakeven zero crossings
        if prev_pnl is not None and prev_spot is not None:
            if (prev_pnl < 0 and total_pnl >= 0) or (prev_pnl > 0 and total_pnl <= 0):
                # Linear interpolation for zero
                denom = total_pnl - prev_pnl
                if denom != 0:
                    be = prev_spot + (0 - prev_pnl) * (s - prev_spot) / denom
                    breakevens.append(round(be, 1))

        prev_pnl = total_pnl
        prev_spot = s

    pnl_values = [pt["pnl"] for pt in curve]
    min_pnl = min(pnl_values) if pnl_values else 0.0
    max_pnl = max(pnl_values) if pnl_values else 0.0

    # Risk to Reward
    if abs(min_pnl) > 0:
        rr = f"1 : {round(max_pnl / abs(min_pnl), 2)}" if max_pnl > 0 else "N/A"
    else:
        rr = "Zero Downside" if max_pnl > 0 else "Flat"

    return {
        "spot": spot,
        "curve": curve,
        "max_profit": max_pnl if max_pnl < 9999999 else "Unlimited",
        "max_loss": min_pnl if min_pnl > -9999999 else "Unlimited",
        "breakevens": breakevens,
        "net_premium": round(net_premium, 2),
        "is_credit": net_premium > 0,
        "risk_reward": rr,
    }

