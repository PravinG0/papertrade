"""
Judge (Chief Risk Officer & Head of Options Desk) agent for TradeLab AI Debate.

Impartial institutional risk manager that arbitrates between Bull and Bear arguments,
evaluates against live market data, and issues high-probability trade setups with
strict capital guardrails (₹700 Max SL, ₹1000 Max Target).

Outputs:
{ verdict: "BUY CE" | "BUY PE" | "NO_TRADE", confidence: int, recommended_strike: float,
  stop_loss: float, target: float, risk_reward_ratio: float, reasoning: str, key_risks: list[str] }
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from google import genai
from google.genai import types as genai_types

from config import compute_clamped_sl_target, gemini_candidate_models, settings
from adaptive_memory import prompt_with_memory
from debate_schemas import (
    BearAgentOutput,
    BullAgentOutput,
    JudgeAgentOutput,
    MarketSnapshot,
)

logger = logging.getLogger("judge_agent")

_JUDGE_SYSTEM_PROMPT = """\
You are the CHIEF RISK OFFICER (CRO) and HEAD OF DERIVATIVES DESK for an institutional Indian index options trading fund.
You are evaluating an adversarial debate between a BULL strategist (advocating Call CE) and a BEAR strategist (advocating Put PE) based on real-time market data for NIFTY / BANK NIFTY.

## Your Mandate & Institutional Principles:
1. **Capital Preservation First**: Your default verdict is **NO_TRADE**. Only approve a directional trade (BUY CE or BUY PE) when one side demonstrates decisive multi-indicator confluence.
2. **Cross-Examination**: Verify the Bull and Bear claims against the raw market snapshot numbers (Moving Averages, VWAP, RSI, PCR, CPR, and OI walls). Reject hallucinated or weak claims.
3. **Institutional Risk Guardrails**:
   - Propose a valid positive stop-loss below entry and target above entry. Actual fill uses broker lot size and total quantity; the backend clamps gross stop risk to ₹700 and target gain to ₹1000 before fees and gaps.
   - Option premium estimate: ATM premium is roughly 0.5% to 0.7% of spot (or ~₹90 - ₹160 for Nifty, ~₹200 - ₹350 for Bank Nifty).
4. **Decisive Verdict**:
   - "BUY CE" when bullish confluence is dominant (e.g. spot > EMA20, PCR > 1.0, Put writing heavy).
   - "BUY PE" when bearish confluence is dominant (e.g. spot < EMA20, PCR < 0.9, Call writing heavy).
   - "NO_TRADE" when market is choppy, within CPR range, conflicting indicators, or balanced conviction.

## Output Requirements
Return ONLY a valid JSON object matching this schema (no markdown fences, no text outside JSON):
{
  "verdict": "BUY CE" | "BUY PE" | "NO_TRADE",
  "confidence": <integer between 1 and 10 reflecting judge conviction>,
  "recommended_strike": <float - strike price e.g. 24500.0, or 0.0 for NO_TRADE>,
  "entry_price": <float - estimated option entry premium e.g. 120.0, or 0.0 for NO_TRADE>,
  "stop_loss": <float - stop loss option premium level, or 0.0 for NO_TRADE>,
  "target": <float - target option premium level, or 0.0 for NO_TRADE>,
  "risk_reward_ratio": <float - reward divided by risk e.g. 1.5, or 0.0 for NO_TRADE>,
  "reasoning": "<Comprehensive paragraph detailing why the winning side was chosen or why NO_TRADE was mandated>",
  "key_risks": [
    "<Key risk 1: e.g. Overhead Call OI Wall at 24600>",
    "<Key risk 2: e.g. India VIX expansion or upcoming macroeconomic data>"
  ]
}
"""


class JudgeAgent:
    """Impartial judge agent evaluating Bull vs Bear arguments."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or settings.GEMINI_API_KEY
        self._client: Optional[genai.Client] = None
        if self._api_key:
            try:
                self._client = genai.Client(api_key=self._api_key)
            except Exception as exc:
                logger.warning("Could not initialize Gemini Client for JudgeAgent: %s", exc)

    async def evaluate(
        self,
        snapshot: MarketSnapshot,
        bull: BullAgentOutput,
        bear: BearAgentOutput,
        memory: str = "",
    ) -> JudgeAgentOutput:
        """Arbitrate between Bull and Bear, applying institutional risk guardrails."""
        user_prompt = self._build_prompt(snapshot, bull, bear)
        user_prompt += "\nIndependent completed-bar multi-timeframe data (UNKNOWN means unavailable; do not invent). Regime: " + snapshot.market_regime + "; frames: " + json.dumps(snapshot.timeframes)
        user_prompt += f"\nSession open: {snapshot.day_open}; session price reference: {snapshot.session_reference}. If not VWAP, do not call it true VWAP."

        models_to_try = gemini_candidate_models()

        if self._client:
            for model_name in models_to_try:
                try:
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._client.models.generate_content,
                            model=model_name,
                            contents=user_prompt,
                            config=genai_types.GenerateContentConfig(
                                system_instruction=prompt_with_memory(_JUDGE_SYSTEM_PROMPT, memory),
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
                    output = self._parse_and_guardrail(data, snapshot)
                    logger.info("JudgeAgent rendered verdict: %s (model=%s)", output.verdict, model_name)
                    return output.model_copy(update={"analysis_source": "gemini"})
                except Exception as exc:
                    logger.warning("JudgeAgent attempt with %s failed: %s", model_name, exc)
                    continue

        # Fallback when LLM is unavailable
        logger.info("JudgeAgent utilizing institutional quantitative fallback")
        return self._fallback_output(snapshot, bull, bear).model_copy(update={"analysis_source": "fallback"})

    def _build_prompt(
        self,
        s: MarketSnapshot,
        bull: BullAgentOutput,
        bear: BearAgentOutput,
    ) -> str:
        return (
            f"Adjudicate this options trade decision for {s.symbol}:\n\n"
            f"=== 1. MARKET GROUND TRUTH ===\n"
            f"Spot Price: {s.spot_price:.2f} | ATM Strike: {s.atm_strike:.0f}\n"
            f"EMA-20: {s.ema_20:.2f} | EMA-50: {s.ema_50:.2f} | VWAP: {s.vwap:.2f}\n"
            f"RSI: {s.rsi:.2f} | VIX: {format(s.vix, '.2f') if s.vix is not None else 'UNAVAILABLE'} | PCR: {format(s.pcr, '.2f') if s.pcr is not None else 'UNAVAILABLE'}\n"
            f"CE OI Change: {s.ce_oi_change:+,.0f} | PE OI Change: {s.pe_oi_change:+,.0f}\n"
            f"Higher TF Trend: {s.higher_tf_trend} | CPR Regime: {s.cpr_width_type}\n"
            f"Call OI Wall: {s.call_oi_wall or 'N/A'} | Put OI Wall: {s.put_oi_wall or 'N/A'}\n\n"
            f"=== 2. BULL AGENT (Advocating Call CE) ===\n"
            f"Conviction: {bull.confidence}/10 | Strike: {bull.strike}\n"
            f"Thesis: {bull.thesis}\n"
            f"Arguments: {json.dumps(bull.arguments)}\n\n"
            f"=== 3. BEAR AGENT (Advocating Put PE) ===\n"
            f"Conviction: {bear.confidence}/10 | Strike: {bear.strike}\n"
            f"Thesis: {bear.thesis}\n"
            f"Arguments: {json.dumps(bear.arguments)}\n"
        )

    def _parse_and_guardrail(self, data: dict[str, Any], snapshot: MarketSnapshot) -> JudgeAgentOutput:
        from verdict_validation import validated_verdict
        verdict, confidence, strike_val, entry, sl, tgt = validated_verdict(data)
        data = data if isinstance(data, dict) else {}

        # Apply strict ₹700 Max SL and ₹1000 Max Target clamp
        if verdict != "NO_TRADE" and entry > 0:
            try:
                sl, tgt = compute_clamped_sl_target(
                    symbol=snapshot.symbol,
                    entry_price=entry,
                    stop_loss=sl,
                    target=tgt,
                    max_loss_inr=700.0,
                    max_gain_inr=1000.0,
                )
            except ValueError as exc:
                verdict = "NO_TRADE"
                strike_val, entry, sl, tgt = 0.0, 0.0, 0.0, 0.0
                rr_val = 0.0
                rr_str = "N/A"
                selected_strike = None
                data = {**data, "reasoning": f"Risk guardrail rejected trade geometry ({exc}). " + str(data.get("reasoning") or "")}
            else:
                risk = entry - sl
                reward = tgt - entry
                rr_val = round(reward / risk, 2)
                rr_str = f"1:{rr_val}"
                selected_strike = f"{int(strike_val)}{'CE' if verdict == 'BUY CE' else 'PE'}"
        else:
            entry, sl, tgt = 0.0, 0.0, 0.0
            rr_val = 0.0
            rr_str = "N/A"
            selected_strike = None

        reasoning = str(data.get("reasoning") or "Institutional risk evaluation complete.")
        key_risks = [str(v) for v in data.get("key_risks", [])] if isinstance(data.get("key_risks"), list) else []
        risk_warning = "; ".join(key_risks) if key_risks else "Manage risk strictly."

        return JudgeAgentOutput(
            verdict=verdict,
            confidence=confidence,
            recommended_strike=strike_val,
            selected_strike=selected_strike,
            entry_price=round(entry, 2),
            stop_loss=round(sl, 2),
            target=round(tgt, 2),
            risk_reward_ratio=rr_str,
            reasoning=reasoning,
            key_risks=key_risks,
            risk_warning=risk_warning,
        )

    def _fallback_output(
        self,
        snapshot: MarketSnapshot,
        bull: BullAgentOutput,
        bear: BearAgentOutput,
    ) -> JudgeAgentOutput:
        """Deterministic institutional CRO decision rule."""
        diff = bull.confidence - bear.confidence
        is_bank = "BANK" in snapshot.symbol.upper()
        strike_val = float(snapshot.atm_strike)

        if diff >= 2 and bull.confidence >= 6:
            verdict = "BUY CE"
            entry = 240.0 if is_bank else 125.0
            sl, tgt = compute_clamped_sl_target(snapshot.symbol, entry, entry - 25.0, entry + 38.0)
            risk = entry - sl
            reward = tgt - entry
            rr_str = f"1:{round(reward / risk, 2)}"
            return JudgeAgentOutput(
                verdict=verdict,
                confidence=bull.confidence,
                recommended_strike=strike_val,
                selected_strike=f"{int(strike_val)}CE",
                entry_price=entry,
                stop_loss=sl,
                target=tgt,
                risk_reward_ratio=rr_str,
                reasoning=(
                    f"CRO Decision: Bullish confluence dominates ({bull.confidence}/10 vs {bear.confidence}/10). "
                    f"Spot is defending EMA-20 and VWAP with Put OI cushion. Recommending BUY {int(strike_val)} CE "
                    f"with disciplined ₹700 max risk stop loss."
                ),
                key_risks=[
                    f"Overhead resistance at {snapshot.spot_price + snapshot.atr:.0f}",
                    "Potential IV contraction on slow consolidation",
                ],
                risk_warning=f"Watch resistance at {snapshot.spot_price + snapshot.atr:.0f}. Keep hard stop loss.",
            )
        elif diff <= -2 and bear.confidence >= 6:
            verdict = "BUY PE"
            entry = 240.0 if is_bank else 125.0
            sl, tgt = compute_clamped_sl_target(snapshot.symbol, entry, entry - 25.0, entry + 38.0)
            risk = entry - sl
            reward = tgt - entry
            rr_str = f"1:{round(reward / risk, 2)}"
            return JudgeAgentOutput(
                verdict=verdict,
                confidence=bear.confidence,
                recommended_strike=strike_val,
                selected_strike=f"{int(strike_val)}PE",
                entry_price=entry,
                stop_loss=sl,
                target=tgt,
                risk_reward_ratio=rr_str,
                reasoning=(
                    f"CRO Decision: Bearish exhaustion confirmed ({bear.confidence}/10 vs {bull.confidence}/10). "
                    f"Spot trading under pressure with Call writing resistance overhead. Recommending BUY {int(strike_val)} PE "
                    f"with strict ₹700 capital protection."
                ),
                key_risks=[
                    f"Support floor near {snapshot.spot_price - snapshot.atr:.0f}",
                    "Short-covering bounce risk if day low holds",
                ],
                risk_warning=f"Support cushion at {snapshot.spot_price - snapshot.atr:.0f}. Exit immediately if SL breached.",
            )
        else:
            return JudgeAgentOutput(
                verdict="NO_TRADE",
                confidence=5,
                recommended_strike=0.0,
                selected_strike=None,
                entry_price=0.0,
                stop_loss=0.0,
                target=0.0,
                risk_reward_ratio="N/A",
                reasoning=(
                    f"CRO Decision: NO TRADE. Market exhibits balanced/conflicting signals "
                    f"(Bull: {bull.confidence}/10, Bear: {bear.confidence}/10). Risk of choppy whip-saw "
                    f"or theta decay inside CPR range is elevated. Capital preservation mandated."
                ),
                key_risks=[
                    "Rangebound sideways chop eroding option premiums",
                    "Conflicting technical indicators lacking directional confluence",
                ],
                risk_warning="Market is rangebound. Wait for a clear directional breakout.",
            )
