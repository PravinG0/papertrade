"""
Bull (bullish) agent for TradeLab AI Debate.

Analyses live spot price, 20/50 EMA, RSI, and option chain through a strictly BULLISH lens.
Calls Google Gemini and returns structured BullAgentOutput with:
{ confidence: int, strike: float, thesis: str, arguments: list[str] }
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from google import genai
from google.genai import types as genai_types

from config import settings
from debate_schemas import BullAgentOutput, MarketSnapshot

logger = logging.getLogger("bull_agent")

_BULL_SYSTEM_PROMPT = """\
You are an elite institutional BULLISH options strategist and derivatives quantitative analyst specialising in NIFTY 50 and BANK NIFTY index options.
Your mandate is to build the MOST EXHAUSTIVE, multi-dimensional BULLISH case for buying an At-The-Money (ATM) or near-ATM Call (CE) option.

## Comprehensive Multi-Dimensional Analysis Framework
You must debate and analyse across technical, structural, and derivatives angles:
1. **Trend & Moving Average Alignment**:
   - 20-EMA vs 50-EMA spread and slope. Quantify the gap.
   - Price position relative to key moving averages confirming bullish structure.
2. **Price Action & Key Levels**:
   - Defending intraday support / day low / CPR pivot.
   - Structure of higher-highs and higher-lows. Proximity to breakout velocity targets.
3. **VWAP & Institutional Order Flow**:
   - Spot price premium over VWAP confirming institutional buyer absorption.
4. **Momentum & Oscillators (RSI / MACD)**:
   - 14-period RSI trajectory, absence of negative divergence, room before extreme overbought levels.
5. **Option Chain, Open Interest (OI) & Put-Call Ratio (PCR)**:
   - Put OI additions at support strikes (Put writers providing cushion/floor).
   - PCR (> 1.0 or rising) showing aggressive Put selling by smart money.
   - Call short-covering / Call OI unwinding potential accelerating gamma.
6. **Volatility & Greeks (India VIX, Theta, Delta, Gamma)**:
   - Low/moderate India VIX providing reasonable entry premiums and asymmetric upside.

## Output Requirements
Return ONLY a valid JSON object matching this schema (no markdown fences, no text outside JSON):
{
  "confidence": <integer between 1 and 10 reflecting conviction>,
  "strike": <float - exact strike price recommendation, e.g. 24500.0>,
  "thesis": "<One punchy, authoritative sentence stating the core bullish premise>",
  "arguments": [
    "<Argument 1: Trend & Moving Averages citing exact numbers>",
    "<Argument 2: VWAP & Order Flow citing exact numbers>",
    "<Argument 3: Option Chain, PCR & Put OI floor citing exact numbers>",
    "<Argument 4: Momentum, RSI & Volatility citing exact numbers>"
  ],
  "key_levels": {
    "support_1": <float>,
    "support_2": <float>,
    "immediate_resistance": <float>,
    "breakout_target": <float>
  }
}
"""


class BullAgent:
    """Generates a bullish derivatives analysis using Gemini."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or settings.GEMINI_API_KEY
        self._client: Optional[genai.Client] = None
        if self._api_key:
            try:
                self._client = genai.Client(api_key=self._api_key)
            except Exception as exc:
                logger.warning("Could not initialize Gemini Client for BullAgent: %s", exc)

    async def analyze(self, snapshot: MarketSnapshot) -> BullAgentOutput:
        """Run bull analysis and return structured BullAgentOutput."""
        user_prompt = self._build_prompt(snapshot)

        models_to_try = [
            settings.GEMINI_MODEL,
            "gemini-3.8-flash",
        ]
        # Remove duplicates while preserving order
        models_to_try = list(dict.fromkeys([m for m in models_to_try if m]))
        # Gemini returns transient 503 'high demand' spikes: try the model twice before falling back
        models_to_try = models_to_try * 2

        if self._client:
            for model_name in models_to_try:
                try:
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._client.models.generate_content,
                            model=model_name,
                            contents=user_prompt,
                            config=genai_types.GenerateContentConfig(
                                system_instruction=_BULL_SYSTEM_PROMPT,
                                response_mime_type="application/json",
                                temperature=0.2,
                            ),
                        ),
                        timeout=20.0,
                    )
                    raw_text = response.text.strip()
                    if raw_text.startswith("```"):
                        raw_text = raw_text.split("```")[1]
                        if raw_text.startswith("json"):
                            raw_text = raw_text[4:]
                        raw_text = raw_text.strip()

                    data = json.loads(raw_text)
                    strike_val = float(data.get("strike") or snapshot.atm_strike)
                    output = BullAgentOutput(
                        bias="BULLISH",
                        confidence=int(data.get("confidence", 7)),
                        strike=strike_val,
                        thesis=str(data.get("thesis") or "Bullish trend continuation favored."),
                        arguments=list(data.get("arguments") or []),
                        recommended_strike=f"{int(strike_val)}CE",
                        key_levels=dict(data.get("key_levels") or {}),
                    )
                    logger.info("BullAgent generated output with %s: confidence=%d, strike=%.1f", model_name, output.confidence, output.strike)
                    return output
                except Exception as exc:
                    logger.warning("BullAgent attempt with %s failed: %s", model_name, exc)
                    continue

        # Fallback when LLM is unavailable
        logger.info("BullAgent utilizing institutional mathematical fallback")
        return self._fallback_output(snapshot)

    def _build_prompt(self, s: MarketSnapshot) -> str:
        return (
            f"Analyse the following {s.symbol} market data through a strictly BULLISH lens:\n\n"
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

    def _fallback_output(self, s: MarketSnapshot) -> BullAgentOutput:
        strike_val = float(s.atm_strike)
        confidence = 7 if s.spot_price >= s.ema_20 and s.pcr >= 0.95 else 5
        return BullAgentOutput(
            bias="BULLISH",
            confidence=confidence,
            strike=strike_val,
            thesis=f"Institutional accumulation is defending {s.symbol} spot above EMA-20 with aggressive Put writing cushion at {strike_val:.0f}.",
            arguments=[
                f"Trend Alignment: Spot (₹{s.spot_price:.2f}) is positioned above short-term support with EMA-20 at ₹{s.ema_20:.2f} providing active dynamic demand.",
                f"VWAP & Order Flow: Price action relative to VWAP (₹{s.vwap:.2f}) indicates buyer absorption on dips and refusal to break intraday value.",
                f"Option Chain & PCR: Put-Call Ratio of {s.pcr:.2f} with strong Put writing (+{s.pe_oi_change:+,.0f} PE OI) establishes a fortified institutional floor at {strike_val:.0f}.",
                f"Volatility & Greeks: India VIX at {s.vix:.1f} maintains manageable implied volatility, providing favorable delta expansion for ATM CE calls against intraday theta.",
            ],
            recommended_strike=f"{int(strike_val)}CE",
            key_levels={
                "support_1": round(s.ema_20, 2),
                "support_2": round(s.ema_50, 2),
                "immediate_resistance": round(s.spot_price + s.atr, 2),
                "breakout_target": round(s.spot_price + (2 * s.atr), 2),
            },
        )
