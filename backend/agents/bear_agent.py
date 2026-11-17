"""
Bear (bearish) agent for TradeLab AI Debate.

Analyses resistance, EMA breakdown, RSI overbought through a strictly BEARISH lens.
Calls Google Gemini and returns structured BearAgentOutput with:
{ confidence: int, strike: float, thesis: str, arguments: list[str] }
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from google import genai
from google.genai import types as genai_types

from config import settings
from debate_schemas import BearAgentOutput, MarketSnapshot

logger = logging.getLogger("bear_agent")

_BEAR_SYSTEM_PROMPT = """\
You are an elite institutional BEARISH options strategist and derivatives quantitative analyst specialising in NIFTY 50 and BANK NIFTY index options.
Your mandate is to build the MOST EXHAUSTIVE, multi-dimensional BEARISH case for buying an At-The-Money (ATM) or near-ATM Put (PE) option.

## Comprehensive Multi-Dimensional Analysis Framework
You must debate and analyse across technical, structural, and derivatives angles:
1. **Trend & Moving Average Breakdown**:
   - 20-EMA below 50-EMA deficit or proximity to downward crossover.
   - Price trading below key short-term moving averages signalling downward momentum.
2. **Price Action & Overhead Resistance**:
   - Rejections at intraday resistance, day high, or CPR TC.
   - Breakdown of intermediate support or formation of lower-highs and lower-lows.
3. **VWAP & Institutional Selling Pressure**:
   - Spot price trading at a discount below VWAP or repeated rejection at VWAP ceiling.
4. **Momentum & Exhaustion (RSI / MACD)**:
   - 14-period RSI showing exhaustion, breakdown below 50, or negative divergence against price.
5. **Option Chain, Open Interest (OI) & Put-Call Ratio (PCR)**:
   - Heavy Call OI writing at overhead strikes acting as a concrete resistance ceiling.
   - Declining PCR (< 0.90 or falling) showing institutional Call sellers dominating.
   - Put unwinding (long liquidation / panic stop trigger) accelerating index decline.
6. **Volatility & Greeks (India VIX, Theta, Delta, Gamma)**:
   - Expanding volatility or downside velocity favoring high negative delta capture on Put options.

## Output Requirements
Return ONLY a valid JSON object matching this schema (no markdown fences, no text outside JSON):
{
  "confidence": <integer between 1 and 10 reflecting conviction>,
  "strike": <float - exact strike price recommendation, e.g. 24500.0>,
  "thesis": "<One punchy, authoritative sentence stating the core bearish premise>",
  "arguments": [
    "<Argument 1: Trend & Resistance Rejection citing exact numbers>",
    "<Argument 2: VWAP & Distribution Pressure citing exact numbers>",
    "<Argument 3: Option Chain, Call OI Ceiling & PCR citing exact numbers>",
    "<Argument 4: Momentum Exhaustion & Downside Velocity citing exact numbers>"
  ],
  "key_levels": {
    "resistance_1": <float>,
    "resistance_2": <float>,
    "immediate_support": <float>,
    "breakdown_target": <float>
  }
}
"""


class BearAgent:
    """Generates a bearish derivatives analysis using Gemini."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or settings.GEMINI_API_KEY
        self._client: Optional[genai.Client] = None
        if self._api_key:
            try:
                self._client = genai.Client(api_key=self._api_key)
            except Exception as exc:
                logger.warning("Could not initialize Gemini Client for BearAgent: %s", exc)

    async def analyze(self, snapshot: MarketSnapshot) -> BearAgentOutput:
        """Run bear analysis and return structured BearAgentOutput."""
        user_prompt = self._build_prompt(snapshot)

        models_to_try = [
            settings.GEMINI_MODEL,
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash",
        ]
        models_to_try = list(dict.fromkeys([m for m in models_to_try if m]))

        if self._client:
            for model_name in models_to_try:
                try:
                    response = self._client.models.generate_content(
                        model=model_name,
                        contents=user_prompt,
                        config=genai_types.GenerateContentConfig(
                            system_instruction=_BEAR_SYSTEM_PROMPT,
                            response_mime_type="application/json",
                            temperature=0.2,
                        ),
                    )
                    raw_text = response.text.strip()
                    if raw_text.startswith("```"):
                        raw_text = raw_text.split("```")[1]
                        if raw_text.startswith("json"):
                            raw_text = raw_text[4:]
                        raw_text = raw_text.strip()

                    data = json.loads(raw_text)
                    strike_val = float(data.get("strike") or snapshot.atm_strike)
                    output = BearAgentOutput(
                        bias="BEARISH",
                        confidence=int(data.get("confidence", 7)),
                        strike=strike_val,
                        thesis=str(data.get("thesis") or "Bearish breakdown pressure dominant."),
                        arguments=list(data.get("arguments") or []),
                        recommended_strike=f"{int(strike_val)}PE",
                        key_levels=dict(data.get("key_levels") or {}),
                    )
                    logger.info("BearAgent generated output with %s: confidence=%d, strike=%.1f", model_name, output.confidence, output.strike)
                    return output
                except Exception as exc:
                    logger.warning("BearAgent attempt with %s failed: %s", model_name, exc)
                    continue

        # Fallback when LLM is unavailable
        logger.info("BearAgent utilizing institutional mathematical fallback")
        return self._fallback_output(snapshot)

    def _build_prompt(self, s: MarketSnapshot) -> str:
        return (
            f"Analyse the following {s.symbol} market data through a strictly BEARISH lens:\n\n"
            f"Symbol: {s.symbol}\n"
            f"Spot Price: {s.spot_price:.2f}\n"
            f"ATM Strike: {s.atm_strike:.0f}\n"
            f"EMA-20: {s.ema_20:.2f} | EMA-50: {s.ema_50:.2f}\n"
            f"VWAP: {s.vwap:.2f}\n"
            f"RSI (14): {s.rsi:.2f}\n"
            f"ATR (14): {s.atr:.2f}\n"
            f"India VIX: {s.vix:.2f}\n"
            f"PCR: {s.pcr:.2f}\n"
            f"CE OI Change: {s.ce_oi_change:+,.0f} | PE OI Change: {s.pe_oi_change:+,.0f}\n"
            f"Higher TF Trend: {s.higher_tf_trend}\n"
            f"Max Pain: {s.max_pain or 'N/A'}\n"
            f"Call OI Wall (Resistance): {s.call_oi_wall or 'N/A'}\n"
            f"Put OI Wall (Support): {s.put_oi_wall or 'N/A'}\n"
            f"CPR Pivot: {s.cpr_pivot or 'N/A'} (TC: {s.cpr_tc or 'N/A'}, BC: {s.cpr_bc or 'N/A'}, Regime: {s.cpr_width_type})\n"
            f"Supertrend: {s.supertrend_direction} ({s.supertrend_value or 'N/A'})\n"
        )

    def _fallback_output(self, s: MarketSnapshot) -> BearAgentOutput:
        strike_val = float(s.atm_strike)
        confidence = 7 if s.spot_price < s.ema_20 or s.pcr < 0.95 else 5
        return BearAgentOutput(
            bias="BEARISH",
            confidence=confidence,
            strike=strike_val,
            thesis=f"Intraday rallies are being met with aggressive institutional distribution and heavy Call writing near {s.spot_price + s.atr:.0f}.",
            arguments=[
                f"Overhead Resistance: Spot (₹{s.spot_price:.2f}) faces continuous selling pressure near recent highs, with EMA-20 at ₹{s.ema_20:.2f} capping sharp upward extensions.",
                f"VWAP Discount: Inability to sustain clear separation above VWAP (₹{s.vwap:.2f}) highlights buyer fatigue and lack of institutional aggressive market buying.",
                f"Derivatives Ceiling: Call OI additions (+{s.ce_oi_change:+,.0f} CE OI) combined with PCR at {s.pcr:.2f} demonstrate smart money hedging and resistance building overhead.",
                f"Downside Convexity: Any breakdown below immediate support (₹{round(s.spot_price - s.atr, 2)}) threatens to trigger rapid Put delta expansion towards breakdown targets.",
            ],
            recommended_strike=f"{int(strike_val)}PE",
            key_levels={
                "resistance_1": round(s.ema_20, 2),
                "resistance_2": round(s.ema_50, 2),
                "immediate_support": round(s.spot_price - s.atr, 2),
                "breakdown_target": round(s.spot_price - (2 * s.atr), 2),
            },
        )
