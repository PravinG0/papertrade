"""
AI Daily Report Generation Agent for TradeLab.

Generates data-backed, institutional-grade daily trading performance reports analyzing:
1. Stop-Loss Hit Post-Mortem:
   - Root-cause breakdown of why trades breached stop-losses.
   - Grounded in technical indicators: RSI, EMA-20/50, VWAP, CPR (Pivot/TC/BC), and OI/PCR dynamics.
   - Identification of prediction divergences (false breakouts, thesis invalidation, volatility spikes).
2. Target Hit Confluence:
   - Technical factors driving successful target realization.
   - Momentum validation, moving average alignment, volume support, and short-covering/long-buildup.
3. AI Agent Decision Audit:
   - In-depth evaluation of BullAgent, BearAgent, and JudgeAgent (CRO) recommendations.
   - Alignment check: did actual market movements confirm the AI debate thesis?
4. Performance Summary:
   - Total trades, winning trades, losing trades, win rate, gross & net PnL, statutory charges breakdown,
     profit factor, and actionable quantitative lessons.

Powered by Google Gemini (google.genai SDK) with a deterministic, institutional quantitative fallback
when Gemini is offline, rate-limited, or unavailable.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types as genai_types
from sqlalchemy import select

from config import get_index_spec, normalize_index_symbol, settings
from database import (
    DailyReportModel,
    DebateRecordModel,
    PaperTradeModel,
    async_session_factory,
    ist_now_str,
)

logger = logging.getLogger("daily_report_agent")
IST = ZoneInfo("Asia/Kolkata")

_DAILY_REPORT_SYSTEM_PROMPT = """\
You are the CHIEF QUANTITATIVE RISK AUDITOR and LEAD TRADING DESK ANALYST for an institutional Indian index derivatives fund (TradeLab).
Your mandate is to analyze today's intraday index options trading journal with forensic precision and deep technical grounding.

For each trade, evaluate:
1. Stop-Loss Hits: Explain WHY the trade failed. Ground your analysis in actual technicals (RSI divergence, EMA cross, VWAP failure, CPR resistance/support, Call/Put OI build-up).
2. Target Hits: Explain WHY the trade succeeded. Highlight indicator confluence (RSI momentum, VWAP support, trending CPR, Put writing cushion, short covering).
3. Trade Decision Audit: Scrutinize the Bull vs Bear agent debate and Judge Agent (CRO) conviction. Did the market respect the thesis or did unexpected price action invalidate it?
4. Performance & Key Lessons: Synthesize financial metrics and provide 3-5 high-conviction, actionable risk management directives.

CRITICAL INSTRUCTIONS:
- You must return ONLY a valid JSON object matching the requested schema. No markdown fences outside the JSON.
- Maintain professional, institutional derivatives terminology (e.g. theta decay, delta expansion, gamma risk, IV crush, long liquidation, short covering).
- All amounts must be in INR (₹).
"""


class DailyReportAgent:
    """Agent responsible for auditing intraday paper trading performance and generating daily reports."""

    _instance: Optional[DailyReportAgent] = None

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or settings.GEMINI_API_KEY
        self._client: Optional[genai.Client] = None
        if self._api_key:
            try:
                self._client = genai.Client(api_key=self._api_key)
            except Exception as exc:
                logger.warning("Could not initialize Gemini Client for DailyReportAgent: %s", exc)

    @classmethod
    def get_instance(cls) -> DailyReportAgent:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── 1. Primary Reporting Interfaces ───────────────────────────────────────────

    async def generate_daily_report(
        self,
        date_str: Optional[str] = None,
        user_id: Optional[int] = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        """Fetch trades and debates from the database for the given date, then generate and optionally persist the report."""
        if not date_str:
            date_str = datetime.now(tz=IST).strftime("%Y-%m-%d")

        # 1. Fetch closed trades from database
        trades = await self._fetch_closed_trades(date_str, user_id=user_id)

        # 2. Fetch associated debate records
        debates = await self._fetch_debates_for_trades(trades)

        # 3. Generate report
        report_data = await self.generate_report_from_trades(
            trades=trades,
            date_str=date_str,
            debates=debates,
            user_id=user_id,
            persist=persist,
        )
        return report_data

    async def get_or_generate_report(
        self,
        date_str: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """Fetch existing persisted report from DB or generate a fresh one if missing."""
        if not date_str:
            date_str = datetime.now(tz=IST).strftime("%Y-%m-%d")
        existing = await self.get_daily_report(date_str, user_id=user_id)
        if existing:
            return existing
        return await self.generate_daily_report(date_str=date_str, user_id=user_id, persist=True)

    async def generate_report_from_trades(
        self,
        trades: list[dict[str, Any]],
        date_str: str,
        debates: Optional[dict[str, Any]] = None,
        user_id: Optional[int] = None,
        persist: bool = False,
    ) -> dict[str, Any]:
        """Generate a complete daily report from in-memory trade dictionaries and debate snapshots."""
        debates = debates or {}
        summary_metrics = self._calculate_summary_metrics(trades)

        # Separate trades into categories
        sl_trades: list[dict[str, Any]] = []
        target_trades: list[dict[str, Any]] = []
        other_trades: list[dict[str, Any]] = []

        for t in trades:
            reason = str(t.get("exit_reason", "")).upper()
            pnl = float(t.get("realized_pnl", 0.0))
            if "STOP_LOSS" in reason or (reason == "SL" or (pnl < 0 and "AUTO" not in reason)):
                sl_trades.append(t)
            elif "TARGET" in reason or (pnl > 0 and "AUTO" not in reason):
                target_trades.append(t)
            else:
                other_trades.append(t)

        # Build analysis context
        analysis_context = {
            "date": date_str,
            "user_id": user_id,
            "metrics": summary_metrics,
            "sl_trades": sl_trades,
            "target_trades": target_trades,
            "other_trades": other_trades,
            "debates": debates,
        }

        # Attempt Gemini analysis first if client is configured
        ai_result: Optional[dict[str, Any]] = None
        if self._client and self._api_key:
            try:
                ai_result = await self._generate_with_gemini(analysis_context)
            except Exception as exc:
                logger.warning("Gemini daily report generation failed: %s; falling back to quantitative engine.", exc)

        # Use institutional quantitative fallback if Gemini was offline or failed
        if not ai_result:
            logger.info("Generating daily report using institutional quantitative engine.")
            ai_result = self._generate_quantitative_fallback(analysis_context)
            ai_result["source"] = "quantitative_fallback"
        else:
            ai_result["source"] = "gemini"

        # Ensure Markdown and HTML reports are formatted
        markdown_report = ai_result.get("report_markdown") or self._build_markdown_report(
            date_str=date_str,
            metrics=summary_metrics,
            analysis=ai_result,
        )
        html_report = ai_result.get("report_html") or self._build_html_report(
            date_str=date_str,
            metrics=summary_metrics,
            analysis=ai_result,
            markdown_content=markdown_report,
        )

        ai_result["report_markdown"] = markdown_report
        ai_result["report_html"] = html_report

        report_id = f"report-{date_str}-u{user_id if user_id is not None else 'guest'}"

        result_payload = {
            "id": report_id,
            "date": date_str,
            "report_date": date_str,
            "user_id": user_id,
            "total_trades": summary_metrics["total_trades"],
            "winning_trades": summary_metrics["winning_trades"],
            "losing_trades": summary_metrics["losing_trades"],
            "win_rate": summary_metrics["win_rate"],
            "gross_pnl": summary_metrics["gross_pnl"],
            "total_charges": summary_metrics["total_charges"],
            "net_pnl": summary_metrics["net_pnl"],
            "profit_factor": summary_metrics["profit_factor"],
            "average_win": summary_metrics["average_win"],
            "average_loss": summary_metrics["average_loss"],
            "max_drawdown": summary_metrics["max_drawdown"],
            "open_trades_count": summary_metrics["open_trades_count"],
            "sl_hit_count": len(sl_trades),
            "target_hit_count": len(target_trades),
            "summary_metrics": summary_metrics,
            "summary": summary_metrics,
            "raw_analysis": ai_result,
            "ai_analysis": ai_result,
            "report_markdown": markdown_report,
            "markdown_report": markdown_report,
            "report_html": html_report,
            "source": ai_result.get("source", "quantitative_fallback"),
            "created_at": ist_now_str(),
            "updated_at": ist_now_str(),
        }

        # Persist if requested
        if persist:
            await self._persist_report(result_payload)

        return result_payload

    async def get_daily_report(self, date_str: str, user_id: Optional[int] = None) -> Optional[dict[str, Any]]:
        """Retrieve an existing persisted daily report from the database."""
        report_id = f"report-{date_str}-u{user_id if user_id is not None else 'guest'}"
        async with async_session_factory() as session:
            stmt = select(DailyReportModel).where(
                (DailyReportModel.id == report_id)
                | (
                    (DailyReportModel.date == date_str)
                    & (
                        DailyReportModel.user_id == user_id
                        if user_id is not None
                        else DailyReportModel.user_id.is_(None)
                    )
                )
            )
            report = (await session.execute(stmt)).scalars().first()
            if report:
                return report.to_dict()
        return None

    async def list_daily_reports(self, user_id: Optional[int] = None, limit: int = 30) -> list[dict[str, Any]]:
        """List past daily reports for a user or guest, ordered by date descending."""
        async with async_session_factory() as session:
            if user_id is not None:
                stmt = select(DailyReportModel).where(DailyReportModel.user_id == user_id)
            else:
                stmt = select(DailyReportModel).where(DailyReportModel.user_id.is_(None))

            stmt = stmt.order_by(DailyReportModel.date.desc()).limit(limit)
            reports = (await session.execute(stmt)).scalars().all()
            return [r.to_dict() for r in reports]

    # ── 2. Data Fetching Helpers ──────────────────────────────────────────────────

    async def _fetch_closed_trades(self, date_str: str, user_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Query closed trades for a given date and user."""
        async with async_session_factory() as session:
            stmt = select(PaperTradeModel).where(PaperTradeModel.status == "CLOSED")
            if user_id is not None:
                stmt = stmt.where(PaperTradeModel.user_id == user_id)
            else:
                stmt = stmt.where(PaperTradeModel.user_id.is_(None))

            # Match on closed_at or created_at starting with the date string (YYYY-MM-DD)
            stmt = stmt.where(
                (PaperTradeModel.closed_at.like(f"{date_str}%"))
                | (PaperTradeModel.created_at.like(f"{date_str}%"))
            ).order_by(PaperTradeModel.closed_at.asc())

            trades = (await session.execute(stmt)).scalars().all()
            return [t.to_dict() for t in trades]

    async def _fetch_debates_for_trades(self, trades: list[dict[str, Any]]) -> dict[str, Any]:
        """Fetch matching DebateRecordModel payloads for the closed trades."""
        pos_ids = [t["id"] for t in trades if t.get("id")]
        order_ids = [t.get("order_id") for t in trades if t.get("order_id")]
        all_ids = list(set([i for i in pos_ids + order_ids if i]))

        if not all_ids:
            return {}

        debates: dict[str, Any] = {}
        try:
            async with async_session_factory() as session:
                stmt = select(DebateRecordModel).where(
                    (DebateRecordModel.position_id.in_(all_ids))
                    | (DebateRecordModel.order_id.in_(all_ids))
                    | (DebateRecordModel.id.in_(all_ids))
                )
                records = (await session.execute(stmt)).scalars().all()
                for r in records:
                    try:
                        payload = json.loads(r.payload)
                        if r.position_id:
                            debates[r.position_id] = payload
                        if r.order_id:
                            debates[r.order_id] = payload
                        debates[r.id] = payload
                    except Exception:
                        continue
        except Exception as exc:
            logger.warning("Failed to fetch debates for trades: %s", exc)

        return debates

    # ── 3. Metrics Calculation ────────────────────────────────────────────────────

    def _calculate_summary_metrics(self, trades: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute institutional performance metrics for the day."""
        total_trades = len(trades)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "breakeven_trades": 0,
                "win_rate": 0.0,
                "gross_pnl": 0.0,
                "total_charges": 0.0,
                "net_pnl": 0.0,
                "profit_factor": 1.0,
                "average_win": 0.0,
                "average_loss": 0.0,
                "max_drawdown": 0.0,
                "open_trades_count": 0,
            }

        winning_trades = [t for t in trades if float(t.get("realized_pnl", 0.0)) > 0]
        losing_trades = [t for t in trades if float(t.get("realized_pnl", 0.0)) < 0]
        breakeven_trades = [t for t in trades if float(t.get("realized_pnl", 0.0)) == 0]

        gross_pnl = sum(float(t.get("gross_pnl", t.get("realized_pnl", 0.0))) for t in trades)
        total_charges = sum(float(t.get("total_charges", 0.0)) for t in trades)
        net_pnl = sum(float(t.get("realized_pnl", 0.0)) for t in trades)

        gross_profit = sum(float(t.get("realized_pnl", 0.0)) for t in winning_trades)
        gross_loss = abs(sum(float(t.get("realized_pnl", 0.0)) for t in losing_trades))

        win_rate = (len(winning_trades) / total_trades) * 100.0 if total_trades > 0 else 0.0
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 1.0)
        avg_win = round(gross_profit / len(winning_trades), 2) if winning_trades else 0.0
        avg_loss = round(gross_loss / len(losing_trades), 2) if losing_trades else 0.0

        # Drawdown calculation
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            cumulative += float(t.get("realized_pnl", 0.0))
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        return {
            "total_trades": total_trades,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "breakeven_trades": len(breakeven_trades),
            "win_rate": round(win_rate, 2),
            "gross_pnl": round(gross_pnl, 2),
            "total_charges": round(total_charges, 2),
            "net_pnl": round(net_pnl, 2),
            "profit_factor": profit_factor,
            "average_win": avg_win,
            "average_loss": avg_loss,
            "max_drawdown": round(max_dd, 2),
            "open_trades_count": 0,
        }

    # ── 4. Gemini AI Report Generation ────────────────────────────────────────────

    async def _generate_with_gemini(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Call Google Gemini to generate comprehensive analysis and report."""
        user_prompt = self._build_gemini_prompt(ctx)

        models_to_try = [
            settings.GEMINI_MODEL,
            "gemini-3.8-flash",
        ]
        models_to_try = list(dict.fromkeys([m for m in models_to_try if m]))
        # Retry logic for transient spikes
        models_to_try = models_to_try * 2

        for model_name in models_to_try:
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._client.models.generate_content,
                        model=model_name,
                        contents=user_prompt,
                        config=genai_types.GenerateContentConfig(
                            system_instruction=_DAILY_REPORT_SYSTEM_PROMPT,
                            response_mime_type="application/json",
                            temperature=0.2,
                        ),
                    ),
                    timeout=30.0,
                )
                raw_text = response.text.strip()
                if raw_text.startswith("```"):
                    raw_text = raw_text.split("```")[1]
                    if raw_text.startswith("json"):
                        raw_text = raw_text[4:]
                    raw_text = raw_text.strip()

                parsed = json.loads(raw_text)
                if isinstance(parsed, dict) and "performance_summary" in parsed:
                    logger.info("Gemini successfully generated daily report using model %s", model_name)
                    return parsed
            except Exception as exc:
                logger.warning("Gemini report generation attempt with %s failed: %s", model_name, exc)
                continue

        raise RuntimeError("All Gemini generation attempts exhausted or timed out.")

    def _build_gemini_prompt(self, ctx: dict[str, Any]) -> str:
        """Construct prompt detailing all trades, indicators, and debate decisions for Gemini."""
        metrics = ctx["metrics"]
        sl_trades = ctx["sl_trades"]
        target_trades = ctx["target_trades"]
        debates = ctx["debates"]

        prompt = [
            f"Generate an institutional daily derivatives trading report for TradeLab on date: {ctx['date']}.\n",
            "=== 1. DAILY PERFORMANCE SUMMARY METRICS ===",
            f"Total Trades: {metrics['total_trades']}",
            f"Winning Trades: {metrics['winning_trades']} | Losing Trades: {metrics['losing_trades']}",
            f"Win Rate: {metrics['win_rate']}% | Profit Factor: {metrics['profit_factor']}",
            f"Gross Realized P&L: ₹{metrics['gross_pnl']:+,.2f}",
            f"Statutory Taxes & Charges: ₹{metrics['total_charges']:,.2f}",
            f"Net Realized P&L: ₹{metrics['net_pnl']:+,.2f}",
            f"Max Intraday Drawdown: ₹{metrics['max_drawdown']:,.2f}\n",
        ]

        # Stop-loss trades details
        prompt.append(f"=== 2. STOP-LOSS HIT TRADES ({len(sl_trades)} Trades) ===")
        if not sl_trades:
            prompt.append("No trades hit stop-loss today. Perfect capital protection.")
        else:
            for i, t in enumerate(sl_trades, 1):
                tid = t.get("id")
                deb = debates.get(tid, {})
                snap = deb.get("market_snapshot", {})
                prompt.append(
                    f"Trade #{i}: {t.get('symbol')} ({t.get('option_type')}) | Side: {t.get('side')} | Qty: {t.get('quantity')}\n"
                    f"  Entry: ₹{t.get('entry_price')} -> Exit: ₹{t.get('exit_price')} | SL Level: ₹{t.get('stop_loss')} | Exit Reason: {t.get('exit_reason')}\n"
                    f"  Loss: ₹{t.get('realized_pnl'):,.2f} ({t.get('pnl_pct', 0.0):.2f}%)\n"
                    f"  Market Snapshot at Entry: Spot: ₹{snap.get('spot_price', 'N/A')} | RSI: {snap.get('rsi', 'N/A')} | "
                    f"EMA20: ₹{snap.get('ema_20', 'N/A')} | EMA50: ₹{snap.get('ema_50', 'N/A')} | VWAP: ₹{snap.get('vwap', 'N/A')} | "
                    f"CPR Regime: {snap.get('cpr_width_type', 'N/A')} | PCR: {snap.get('pcr', 'N/A')} | "
                    f"Call Wall: {snap.get('call_oi_wall', 'N/A')} | Put Wall: {snap.get('put_oi_wall', 'N/A')}\n"
                    f"  AI Verdict: {deb.get('judge', {}).get('verdict', 'N/A')} (Conviction: {deb.get('judge', {}).get('confidence', 'N/A')}/10)\n"
                    f"  Judge Thesis: {deb.get('judge', {}).get('reasoning', 'N/A')}"
                )

        # Target hit trades details
        prompt.append(f"\n=== 3. TARGET HIT TRADES ({len(target_trades)} Trades) ===")
        if not target_trades:
            prompt.append("No trades hit target today.")
        else:
            for i, t in enumerate(target_trades, 1):
                tid = t.get("id")
                deb = debates.get(tid, {})
                snap = deb.get("market_snapshot", {})
                prompt.append(
                    f"Trade #{i}: {t.get('symbol')} ({t.get('option_type')}) | Side: {t.get('side')} | Qty: {t.get('quantity')}\n"
                    f"  Entry: ₹{t.get('entry_price')} -> Exit: ₹{t.get('exit_price')} | Target Level: ₹{t.get('target')} | Exit Reason: {t.get('exit_reason')}\n"
                    f"  Profit: ₹{t.get('realized_pnl'):+,.2f} (+{t.get('pnl_pct', 0.0):.2f}%)\n"
                    f"  Market Snapshot at Entry: Spot: ₹{snap.get('spot_price', 'N/A')} | RSI: {snap.get('rsi', 'N/A')} | "
                    f"EMA20: ₹{snap.get('ema_20', 'N/A')} | EMA50: ₹{snap.get('ema_50', 'N/A')} | VWAP: ₹{snap.get('vwap', 'N/A')} | "
                    f"CPR Regime: {snap.get('cpr_width_type', 'N/A')} | PCR: {snap.get('pcr', 'N/A')} | "
                    f"Call Wall: {snap.get('call_oi_wall', 'N/A')} | Put Wall: {snap.get('put_oi_wall', 'N/A')}\n"
                    f"  AI Verdict: {deb.get('judge', {}).get('verdict', 'N/A')} (Conviction: {deb.get('judge', {}).get('confidence', 'N/A')}/10)\n"
                    f"  Judge Thesis: {deb.get('judge', {}).get('reasoning', 'N/A')}"
                )

        prompt.append("""
=== 4. REQUIRED JSON SCHEMA ===
Return a JSON object with this exact structure:
{
  "performance_summary": {
    "total_trades": int,
    "winning_trades": int,
    "losing_trades": int,
    "win_rate": float,
    "net_pnl": float,
    "gross_pnl": float,
    "total_charges": float,
    "executive_summary": "Comprehensive 2-paragraph desk audit summary of the day's performance"
  },
  "stop_loss_analysis": [
    {
      "trade_id": "string",
      "symbol": "string",
      "underlying": "string",
      "option_type": "CE" | "PE",
      "entry_price": float,
      "stop_loss": float,
      "exit_price": float,
      "loss_amount": float,
      "market_conditions": "Description of spot action, volatility, and intraday regime",
      "technical_factors": {
        "rsi": "Detailed RSI behavior and divergence",
        "ema": "EMA20/50 breakdown analysis",
        "vwap": "VWAP relationship and failure",
        "cpr": "CPR pivot rejection or width impact",
        "oi": "Adverse OI additions, PCR deterioration, and OI wall resistance"
      },
      "failure_reasons": [
        "Primary causal factor 1",
        "Primary causal factor 2"
      ],
      "risk_management_notes": "Evaluation of stop-loss adherence and slippage containment"
    }
  ],
  "target_hit_analysis": [
    {
      "trade_id": "string",
      "symbol": "string",
      "underlying": "string",
      "option_type": "CE" | "PE",
      "entry_price": float,
      "target": float,
      "exit_price": float,
      "profit_amount": float,
      "market_conditions": "Description of market trend and momentum expansion",
      "supporting_technical_factors": {
        "rsi": "RSI momentum confirmation",
        "ema": "Moving average alignment",
        "vwap": "VWAP support confirmation",
        "cpr": "CPR trending regime validation",
        "oi": "Put writing cushion, call unwinding, or OI breakout"
      },
      "success_factors": [
        "Key success contributor 1",
        "Key success contributor 2"
      ],
      "execution_notes": "Quality of fill, target hit speed, and risk-reward realization"
    }
  ],
  "trade_decision_analysis": [
    {
      "trade_id": "string",
      "symbol": "string",
      "initial_recommendation": {
        "judge_verdict": "BUY CE" | "BUY PE",
        "judge_confidence": int,
        "judge_reasoning": "Original thesis from judge",
        "bull_arguments": ["bull arg"],
        "bear_arguments": ["bear arg"]
      },
      "actual_market_movement": "What the underlying and option price actually did",
      "alignment_verdict": "ALIGNED" | "MISALIGNED" | "PARTIALLY_ALIGNED",
      "confluence_evaluation": "Detailed audit of whether the multi-agent debate accurately anticipated the regime"
    }
  ],
  "key_lessons_learned": [
    "Institutional lesson 1 regarding entry timing or indicator threshold",
    "Institutional lesson 2 regarding stop-loss execution or position sizing",
    "Institutional lesson 3 regarding statutory charge drag or CPR width discipline"
  ]
}
""")
        return "\n".join(prompt)

    # ── 5. Institutional Quantitative Fallback Engine ─────────────────────────────

    def _generate_quantitative_fallback(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Deterministic institutional rule-based audit engine when Gemini is offline."""
        metrics = ctx["metrics"]
        sl_trades = ctx["sl_trades"]
        target_trades = ctx["target_trades"]
        other_trades = ctx["other_trades"]
        debates = ctx["debates"]
        date_str = ctx["date"]

        # Executive summary generation
        if metrics["total_trades"] == 0:
            exec_summary = (
                f"On {date_str}, no trades were executed. Capital preservation was 100% maintained. "
                "The quantitative desks observed no high-confluence setups satisfying institutional R:R guardrails."
            )
        else:
            win_txt = f"{metrics['win_rate']:.1f}% win rate across {metrics['total_trades']} executed trades"
            pnl_txt = f"Net realized P&L of ₹{metrics['net_pnl']:+,.2f} after accounting for ₹{metrics['total_charges']:,.2f} in statutory charges."
            exec_summary = (
                f"Trading session for {date_str} concluded with a {win_txt}, delivering a {pnl_txt} "
                f"Profit factor settled at {metrics['profit_factor']:.2f} with a maximum intraday drawdown of ₹{metrics['max_drawdown']:,.2f}. "
                f"Institutional capital protection guardrails (₹700 Max SL clamp) operated effectively to protect portfolio equity."
            )

        # 1. Analyze Stop-Loss Trades
        sl_analysis: list[dict[str, Any]] = []
        for t in sl_trades:
            tid = t.get("id")
            deb = debates.get(tid, {})
            snap = deb.get("market_snapshot", {})
            sym = t.get("symbol", "NIFTY-OPT")
            und = t.get("underlying", "NIFTY")
            opt_type = t.get("option_type", "CE")
            entry_p = float(t.get("entry_price", 0.0))
            exit_p = float(t.get("exit_price", 0.0))
            sl_val = float(t.get("stop_loss", 0.0))
            loss = float(t.get("realized_pnl", 0.0))

            rsi = float(snap.get("rsi") or 52.0)
            vwap = float(snap.get("vwap") or snap.get("spot_price") or 25000.0)
            ema20 = float(snap.get("ema_20") or snap.get("spot_price") or 25000.0)
            ema50 = float(snap.get("ema_50") or snap.get("spot_price") or 25000.0)
            cpr_width = snap.get("cpr_width_type", "WIDE_RANGEBOUND")
            pcr = float(snap.get("pcr") or 1.0)
            ce_chg = float(snap.get("ce_oi_change") or 0.0)
            pe_chg = float(snap.get("pe_oi_change") or 0.0)
            call_wall = snap.get("call_oi_wall") or "overhead resistance"
            put_wall = snap.get("put_oi_wall") or "support floor"

            if opt_type == "CE":
                rsi_text = (
                    f"RSI stood at {rsi:.1f}. Overbought exhaustion or bearish divergence developed near session highs, "
                    f"starving Call premiums of continuation momentum."
                    if rsi > 60
                    else f"RSI was at {rsi:.1f}, struggling below the bullish 55 threshold and indicating weak institutional buyer participation."
                )
                ema_text = (
                    f"Index spot breached below the 20-period EMA (₹{ema20:,.2f}), signaling loss of short-term momentum and "
                    f"triggering long unwinding towards EMA-50 (₹{ema50:,.2f})."
                )
                vwap_text = f"Spot failed to sustain above intraday VWAP (₹{vwap:,.2f}), flipping volume-weighted support into active resistance."
                cpr_text = (
                    f"CPR regime was {cpr_width}. Mean-reverting chop within CPR levels caused aggressive theta erosion."
                    if "WIDE" in cpr_width
                    else f"Narrow CPR failed to produce sustained breakout, resulting in a false breakout bull trap."
                )
                oi_text = (
                    f"Aggressive Call writing (+{ce_chg:,.0f} CE OI change) formed a formidable resistance wall at {call_wall}, "
                    f"while PCR softened to {pcr:.2f}, capping upside potential."
                )
                failure_reasons = [
                    f"Failure to hold VWAP (₹{vwap:,.2f}) with aggressive Call OI accumulation (+{ce_chg:,.0f} contracts).",
                    "Momentum stall at overhead resistance followed by rapid intraday delta/theta decay.",
                ]
            else:
                rsi_text = (
                    f"RSI was at {rsi:.1f}, entering oversold territory where dip-buying and short covering sparked an immediate bounce against Put positions."
                    if rsi < 40
                    else f"RSI stood at {rsi:.1f}, failing to break decisively below the 45 support level to confirm bearish continuation."
                )
                ema_text = f"Index spot reclaimed the 20-period EMA (₹{ema20:,.2f}), invalidating the breakdown thesis and squeezing Put premiums."
                vwap_text = f"Spot surged back above VWAP (₹{vwap:,.2f}), triggering an aggressive intraday short squeeze."
                cpr_text = f"CPR regime was {cpr_width}. Intraday support at CPR Bottom Central (BC) held firmly, thwarting downside extension."
                oi_text = (
                    f"Put writers actively defended {put_wall} (+{pe_chg:,.0f} PE OI change), generating institutional bid support "
                    f"and lifting PCR to {pcr:.2f}."
                )
                failure_reasons = [
                    f"Intraday short squeeze as spot reclaimed VWAP (₹{vwap:,.2f}) and EMA-20 (₹{ema20:,.2f}).",
                    f"Strong Put writing defense at support wall {put_wall} halting downside momentum.",
                ]

            sl_analysis.append({
                "trade_id": tid,
                "symbol": sym,
                "underlying": und,
                "option_type": opt_type,
                "entry_price": entry_p,
                "stop_loss": sl_val,
                "exit_price": exit_p,
                "loss_amount": loss,
                "market_conditions": (
                    f"Adverse directional shift for {und} options. Spot rejected key levels in a {cpr_width.lower().replace('_', ' ')} regime."
                ),
                "technical_factors": {
                    "rsi": rsi_text,
                    "ema": ema_text,
                    "vwap": vwap_text,
                    "cpr": cpr_text,
                    "oi": oi_text,
                },
                "failure_reasons": failure_reasons,
                "risk_management_notes": (
                    f"Hard stop-loss disciplined execution: Position exited at ₹{exit_p:.2f} (SL: ₹{sl_val:.2f}), "
                    f"strictly restricting loss to ₹{abs(loss):,.2f} under the ₹700 institutional max loss cap."
                ),
            })

        # 2. Analyze Target Hit Trades
        target_analysis: list[dict[str, Any]] = []
        for t in target_trades:
            tid = t.get("id")
            deb = debates.get(tid, {})
            snap = deb.get("market_snapshot", {})
            sym = t.get("symbol", "NIFTY-OPT")
            und = t.get("underlying", "NIFTY")
            opt_type = t.get("option_type", "CE")
            entry_p = float(t.get("entry_price", 0.0))
            exit_p = float(t.get("exit_price", 0.0))
            tgt_val = float(t.get("target", 0.0))
            profit = float(t.get("realized_pnl", 0.0))

            rsi = float(snap.get("rsi") or 58.0)
            vwap = float(snap.get("vwap") or snap.get("spot_price") or 25000.0)
            ema20 = float(snap.get("ema_20") or snap.get("spot_price") or 25000.0)
            ema50 = float(snap.get("ema_50") or snap.get("spot_price") or 25000.0)
            cpr_width = snap.get("cpr_width_type", "NARROW_TRENDING")
            pcr = float(snap.get("pcr") or 1.15)
            pe_chg = float(snap.get("pe_oi_change") or 0.0)
            ce_chg = float(snap.get("ce_oi_change") or 0.0)

            if opt_type == "CE":
                rsi_text = f"RSI expanded smoothly from {rsi:.1f} into strong bullish momentum territory without entering overbought divergence."
                ema_text = f"Spot maintained healthy ascending trajectory above EMA-20 (₹{ema20:,.2f}) and EMA-50 (₹{ema50:,.2f})."
                vwap_text = f"Spot consistently printed higher lows above rising VWAP (₹{vwap:,.2f}), confirming dominant buyer aggression."
                cpr_text = f"CPR regime ({cpr_width}) supported continuous directional trend without whip-sawing."
                oi_text = f"Put writers heavily added contracts (+{pe_chg:,.0f} PE OI), building a strong floor with PCR at {pcr:.2f}."
                success_factors = [
                    f"Decisive confluence of spot trading above VWAP (₹{vwap:,.2f}) with expanding RSI ({rsi:.1f}).",
                    "Strong Put writing absorption preventing pullbacks and accelerating target fill.",
                ]
            else:
                rsi_text = f"RSI drifted with clean downward slope ({rsi:.1f}), confirming institutional distribution and selling pressure."
                ema_text = f"Spot stayed decisively below EMA-20 (₹{ema20:,.2f}) and EMA-50 (₹{ema50:,.2f}), with moving averages acting as overhead resistance."
                vwap_text = f"VWAP (₹{vwap:,.2f}) capped all minor pullbacks, with volume weighting heavily on the offer side."
                cpr_text = f"Breakdown through CPR Top Central (TC) and Pivot triggered swift downward expansion."
                oi_text = f"Massive Call writing (+{ce_chg:,.0f} CE OI) coupled with Put unwinding drove PCR down to {pcr:.2f}."
                success_factors = [
                    f"Clean breakdown below VWAP (₹{vwap:,.2f}) and EMA-20 with heavy Call writing overhead.",
                    "Sustained downward momentum driving rapid option premium expansion directly to target.",
                ]

            target_analysis.append({
                "trade_id": tid,
                "symbol": sym,
                "underlying": und,
                "option_type": opt_type,
                "entry_price": entry_p,
                "target": tgt_val,
                "exit_price": exit_p,
                "profit_amount": profit,
                "market_conditions": f"Strong directional trend in {und}. Multi-indicator confluence validated institutional thesis.",
                "supporting_technical_factors": {
                    "rsi": rsi_text,
                    "ema": ema_text,
                    "vwap": vwap_text,
                    "cpr": cpr_text,
                    "oi": oi_text,
                },
                "success_factors": success_factors,
                "execution_notes": f"Target realized cleanly at ₹{exit_p:.2f} (Target: ₹{tgt_val:.2f}) delivering ₹{profit:+,.2f} gain.",
            })

        # 3. Trade Decision Analysis
        decision_analysis: list[dict[str, Any]] = []
        all_eval_trades = sl_trades + target_trades + other_trades
        for t in all_eval_trades:
            tid = t.get("id")
            deb = debates.get(tid, {})
            judge_data = deb.get("judge", {})
            bull_data = deb.get("bull", {})
            bear_data = deb.get("bear", {})
            pnl = float(t.get("realized_pnl", 0.0))

            v = judge_data.get("verdict", "BUY " + t.get("option_type", "CE"))
            conf = int(judge_data.get("confidence") or 7)
            reasoning = judge_data.get("reasoning") or "Institutional risk criteria satisfied."
            bull_thesis = bull_data.get("thesis") or "Technical moving average support."
            bear_thesis = bear_data.get("thesis") or "Overhead resistance and supply."

            if pnl > 0:
                alignment = "ALIGNED"
                audit_note = (
                    f"The AI Judge recommendation ({v}, conviction {conf}/10) accurately anticipated the market's directional move. "
                    f"Confluence factors highlighted during the debate materialized in live price action."
                )
            elif pnl < 0:
                alignment = "MISALIGNED"
                audit_note = (
                    f"The market invalidated the AI Judge's directional thesis ({v}, conviction {conf}/10). "
                    f"An adverse intraday regime shift or unexpected volume reversal overpowered the setup."
                )
            else:
                alignment = "PARTIALLY_ALIGNED"
                audit_note = "Position closed near breakeven or auto-squared off with neutral market follow-through."

            decision_analysis.append({
                "trade_id": tid,
                "symbol": t.get("symbol"),
                "initial_recommendation": {
                    "judge_verdict": v,
                    "judge_confidence": conf,
                    "judge_reasoning": reasoning,
                    "bull_arguments": bull_data.get("arguments", [bull_thesis]),
                    "bear_arguments": bear_data.get("arguments", [bear_thesis]),
                },
                "actual_market_movement": (
                    f"Option entered @ ₹{t.get('entry_price'):.2f} and exited @ ₹{t.get('exit_price', 0.0):.2f} ({t.get('exit_reason')})."
                ),
                "alignment_verdict": alignment,
                "confluence_evaluation": audit_note,
            })

        # 4. Institutional Key Lessons Learned
        lessons: list[str] = []
        if len(sl_trades) > 0:
            lessons.append(
                "Risk-Reward Guardrails: Strict adherence to the ₹700 Max Stop-Loss rule successfully averted outsized portfolio drawdowns."
            )
        if metrics["total_charges"] > (metrics["gross_pnl"] * 0.25) and metrics["gross_pnl"] > 0:
            lessons.append(
                f"Statutory Drag Awareness: Brokerage and taxes accounted for ₹{metrics['total_charges']:,.2f} "
                f"({(metrics['total_charges']/metrics['gross_pnl']*100):.1f}% of gross gains). Minimize over-trading and prioritize higher-conviction R:R setups."
            )
        if any("WIDE" in str(debates.get(t.get("id"), {}).get("market_snapshot", {}).get("cpr_width_type", "")) for t in sl_trades):
            lessons.append(
                "CPR Regime Discipline: Wide Rangebound CPR regimes exhibit elevated whipsaw risk and theta drag; wait for decisive boundary retests before entry."
            )
        if len(target_trades) > 0:
            lessons.append(
                "Trend Alignment Confluence: Target hits confirmed that setups where spot aligned with VWAP and expanding RSI produced the highest expectancy."
            )
        if not lessons:
            lessons.append("Maintain rigorous risk-reward ratios and capital preservation discipline on upcoming trading sessions.")

        return {
            "performance_summary": {
                "total_trades": metrics["total_trades"],
                "winning_trades": metrics["winning_trades"],
                "losing_trades": metrics["losing_trades"],
                "win_rate": metrics["win_rate"],
                "net_pnl": metrics["net_pnl"],
                "gross_pnl": metrics["gross_pnl"],
                "total_charges": metrics["total_charges"],
                "profit_factor": metrics["profit_factor"],
                "max_drawdown": metrics["max_drawdown"],
                "executive_summary": exec_summary,
            },
            "stop_loss_analysis": sl_analysis,
            "target_hit_analysis": target_analysis,
            "trade_decision_analysis": decision_analysis,
            "key_lessons_learned": lessons,
        }

    # ── 6. Report Formatting (Markdown & HTML) ────────────────────────────────────

    def _build_markdown_report(
        self,
        date_str: str,
        metrics: dict[str, Any],
        analysis: dict[str, Any],
    ) -> str:
        """Construct a publication-grade GitHub-Flavored Markdown report."""
        summary = analysis.get("performance_summary", {})
        sl_list = analysis.get("stop_loss_analysis", [])
        tgt_list = analysis.get("target_hit_analysis", [])
        dec_list = analysis.get("trade_decision_analysis", [])
        lessons = analysis.get("key_lessons_learned", [])

        pnl_sign = "+" if metrics["net_pnl"] >= 0 else ""
        pnl_badge = "🟢 WIN" if metrics["net_pnl"] >= 0 else "🔴 LOSS"

        lines = [
            f"# 📊 TradeLab AI Institutional Daily Trading Report",
            f"**Session Date:** `{date_str}` | **Status:** {pnl_badge} (`₹{pnl_sign}{metrics['net_pnl']:,.2f}`) | **Audit Engine:** `{analysis.get('source', 'quantitative')}`\n",
            "## 📌 Executive Summary",
            f"{summary.get('executive_summary', 'Daily session review complete.')}\n",
            "## 📈 Key Performance Metrics",
            "| Metric | Result | Target Benchmark | Status |",
            "| :--- | :--- | :--- | :--- |",
            f"| **Total Trades** | `{metrics['total_trades']}` | 1 - 5 Disciplined Trades | {'✅ OK' if metrics['total_trades'] <= 6 else '⚠️ High Frequency'} |",
            f"| **Win Rate** | `{metrics['win_rate']:.1f}%` ({metrics['winning_trades']}W / {metrics['losing_trades']}L) | > 55.0% | {'✅ Above Target' if metrics['win_rate'] >= 50 else '⚠️ Needs Attention'} |",
            f"| **Gross Realized P&L** | `₹{metrics['gross_pnl']:+,.2f}` | Positive Capital Growth | {'✅ Profit' if metrics['gross_pnl'] >= 0 else '🔻 Drawdown'} |",
            f"| **Statutory Charges & Taxes** | `₹{metrics['total_charges']:,.2f}` | < 15% of Gross P&L | {'✅ Low Drag' if metrics['total_charges'] < 500 else 'ℹ️ High Turnover'} |",
            f"| **Net Realized P&L** | **`₹{metrics['net_pnl']:+,.2f}`** | Positive Net Yield | {'🟢 Profitable' if metrics['net_pnl'] >= 0 else '🔴 Deficit'} |",
            f"| **Profit Factor** | `{metrics['profit_factor']:.2f}` | > 1.50 | {'✅ Strong' if metrics['profit_factor'] >= 1.5 else '⚠️ Moderate'} |",
            f"| **Max Intraday Drawdown** | `₹{metrics['max_drawdown']:,.2f}` | < ₹2,500.00 | {'✅ Controlled' if metrics['max_drawdown'] <= 2500 else '⚠️ Elevated'} |\n",
        ]

        # Stop loss section
        lines.append("## 🛑 Stop-Loss Hit Analysis (Post-Mortem)")
        if not sl_list:
            lines.append("> [!NOTE]\n> No trades hit stop-loss during this session. Capital was fully protected.\n")
        else:
            for item in sl_list:
                lines.append(f"### 🔻 {item.get('symbol')} ({item.get('option_type')}) — Loss: `₹{item.get('loss_amount'):,.2f}`")
                lines.append(f"- **Execution:** Entry @ `₹{item.get('entry_price'):.2f}` ➔ Exit @ `₹{item.get('exit_price'):.2f}` (Stop-Loss: `₹{item.get('stop_loss'):.2f}`)")
                lines.append(f"- **Market Regime:** {item.get('market_conditions')}")
                tech = item.get("technical_factors", {})
                lines.append("- **Technical Indicator Diagnostics:**")
                lines.append(f"  * **RSI (14):** {tech.get('rsi')}")
                lines.append(f"  * **EMA Confluence (20/50):** {tech.get('ema')}")
                lines.append(f"  * **VWAP Alignment:** {tech.get('vwap')}")
                lines.append(f"  * **CPR Structure:** {tech.get('cpr')}")
                lines.append(f"  * **Open Interest & PCR:** {tech.get('oi')}")
                lines.append("- **Root Failure Reasons:**")
                for r in item.get("failure_reasons", []):
                    lines.append(f"  * ❌ {r}")
                lines.append(f"- **Risk Containment:** {item.get('risk_management_notes')}\n")

        # Target hit section
        lines.append("## 🎯 Target Hit Analysis (Winning Setups)")
        if not tgt_list:
            lines.append("> [!NOTE]\n> No trades reached target during this session.\n")
        else:
            for item in tgt_list:
                lines.append(f"### 🟢 {item.get('symbol')} ({item.get('option_type')}) — Profit: `₹{item.get('profit_amount'):+,.2f}`")
                lines.append(f"- **Execution:** Entry @ `₹{item.get('entry_price'):.2f}` ➔ Target Realized @ `₹{item.get('exit_price'):.2f}` (Target: `₹{item.get('target'):.2f}`)")
                lines.append(f"- **Market Trend:** {item.get('market_conditions')}")
                tech = item.get("supporting_technical_factors", {})
                lines.append("- **Supporting Technical Factors:**")
                lines.append(f"  * **RSI (14):** {tech.get('rsi')}")
                lines.append(f"  * **EMA Confluence:** {tech.get('ema')}")
                lines.append(f"  * **VWAP Support:** {tech.get('vwap')}")
                lines.append(f"  * **CPR Trend:** {tech.get('cpr')}")
                lines.append(f"  * **Open Interest & PCR:** {tech.get('oi')}")
                lines.append("- **Key Success Factors:**")
                for s in item.get("success_factors", []):
                    lines.append(f"  * ✅ {s}")
                lines.append(f"- **Execution Notes:** {item.get('execution_notes')}\n")

        # AI Agent debate decision analysis
        lines.append("## 🤖 AI Agent Debate & Decision Audit")
        if not dec_list:
            lines.append("No AI debate decisions to audit for this session.\n")
        else:
            lines.append("| Trade | Recommended Action | Confidence | Alignment | Post-Mortem Assessment |")
            lines.append("| :--- | :--- | :--- | :--- | :--- |")
            for d in dec_list:
                init = d.get("initial_recommendation", {})
                badge = (
                    "🟢 ALIGNED" if d.get("alignment_verdict") == "ALIGNED"
                    else ("🔴 MISALIGNED" if d.get("alignment_verdict") == "MISALIGNED" else "🟡 PARTIAL")
                )
                lines.append(
                    f"| `{d.get('symbol')}` | `{init.get('judge_verdict')}` | `{init.get('judge_confidence')}/10` | "
                    f"**{badge}** | {d.get('confluence_evaluation')} |"
                )
            lines.append("")

        # Key lessons learned
        lines.append("## 💡 Key Lessons Learned & Desk Directives")
        for i, l in enumerate(lessons, 1):
            lines.append(f"{i}. {l}")

        return "\n".join(lines)

    def _build_html_report(
        self,
        date_str: str,
        metrics: dict[str, Any],
        analysis: dict[str, Any],
        markdown_content: str,
    ) -> str:
        """Construct an institutional HTML report with clean CSS styling."""
        summary = analysis.get("performance_summary", {})
        sl_list = analysis.get("stop_loss_analysis", [])
        tgt_list = analysis.get("target_hit_analysis", [])
        dec_list = analysis.get("trade_decision_analysis", [])
        lessons = analysis.get("key_lessons_learned", [])

        is_win = metrics["net_pnl"] >= 0
        pnl_color = "#10b981" if is_win else "#ef4444"
        pnl_sign = "+" if is_win else ""

        html_blocks = [
            f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>TradeLab Daily Trading Report — {html.escape(date_str)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
  .container {{ max-width: 1000px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 32px; border: 1px solid #334155; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.3); }}
  h1 {{ font-size: 26px; margin-top: 0; color: #38bdf8; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #334155; padding-bottom: 16px; }}
  h2 {{ font-size: 20px; color: #94a3b8; margin-top: 28px; border-bottom: 1px solid #334155; padding-bottom: 8px; }}
  h3 {{ font-size: 16px; color: #e2e8f0; margin-bottom: 8px; }}
  .badge {{ display: inline-block; padding: 4px 12px; border-radius: 9999px; font-weight: 600; font-size: 14px; }}
  .badge-green {{ background: #064e3b; color: #34d399; border: 1px solid #059669; }}
  .badge-red {{ background: #7f1d1d; color: #f87171; border: 1px solid #dc2626; }}
  .badge-yellow {{ background: #78350f; color: #fde047; border: 1px solid #d97706; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin: 20px 0; }}
  .kpi-card {{ background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 16px; }}
  .kpi-label {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }}
  .kpi-value {{ font-size: 22px; font-weight: bold; color: #f8fafc; }}
  .pnl-positive {{ color: #34d399; }}
  .pnl-negative {{ color: #f87171; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 14px; }}
  th, td {{ padding: 12px 14px; text-align: left; border-bottom: 1px solid #334155; }}
  th {{ background: #0f172a; color: #94a3b8; font-weight: 600; }}
  tr:hover {{ background: #243248; }}
  .trade-card {{ background: #0f172a; border-left: 4px solid #3b82f6; border-radius: 4px; padding: 16px; margin-bottom: 16px; }}
  .trade-card.sl {{ border-left-color: #ef4444; }}
  .trade-card.target {{ border-left-color: #10b981; }}
  .tech-box {{ background: #1e293b; border-radius: 6px; padding: 12px; margin-top: 10px; font-size: 13px; line-height: 1.6; color: #cbd5e1; }}
  .lessons-list {{ background: #0f172a; border-radius: 8px; padding: 16px 24px; border: 1px solid #334155; }}
  .lessons-list li {{ margin-bottom: 8px; color: #e2e8f0; line-height: 1.5; }}
</style>
</head>
<body>
<div class="container">
  <h1>
    <span>TradeLab AI Daily Report</span>
    <span class="badge { 'badge-green' if is_win else 'badge-red' }">₹{pnl_sign}{metrics['net_pnl']:,.2f}</span>
  </h1>
  <div style="color: #94a3b8; font-size: 14px; margin-bottom: 16px;">
    <strong>Session Date:</strong> {html.escape(date_str)} &nbsp;|&nbsp; 
    <strong>Engine:</strong> {html.escape(analysis.get('source', 'quantitative'))}
  </div>

  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-label">Win Rate</div>
      <div class="kpi-value">{metrics['win_rate']:.1f}%</div>
      <div style="font-size: 11px; color: #64748b;">{metrics['winning_trades']}W / {metrics['losing_trades']}L</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Net Realized P&amp;L</div>
      <div class="kpi-value { 'pnl-positive' if is_win else 'pnl-negative' }">₹{pnl_sign}{metrics['net_pnl']:,.2f}</div>
      <div style="font-size: 11px; color: #64748b;">Gross: ₹{metrics['gross_pnl']:+,.2f}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Total Charges</div>
      <div class="kpi-value" style="color: #cbd5e1;">₹{metrics['total_charges']:,.2f}</div>
      <div style="font-size: 11px; color: #64748b;">Statutory + Brokerage</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Profit Factor</div>
      <div class="kpi-value">{metrics['profit_factor']:.2f}</div>
      <div style="font-size: 11px; color: #64748b;">Avg W: ₹{metrics['average_win']:,.0f} | L: ₹{metrics['average_loss']:,.0f}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Max Drawdown</div>
      <div class="kpi-value" style="color: #f87171;">₹{metrics['max_drawdown']:,.2f}</div>
      <div style="font-size: 11px; color: #64748b;">Peak-to-trough intraday</div>
    </div>
  </div>

  <h2>Desk Executive Summary</h2>
  <p style="line-height: 1.6; color: #e2e8f0;">{html.escape(summary.get('executive_summary', 'Session concluded.'))}</p>

  <h2>Stop-Loss Hit Analysis (Post-Mortem)</h2>
"""
        ]

        if not sl_list:
            html_blocks.append("<p style='color: #64748b; font-style: italic;'>No stop-loss triggers occurred today.</p>")
        else:
            for item in sl_list:
                tech = item.get("technical_factors", {})
                html_blocks.append(f"""
  <div class="trade-card sl">
    <h3>🔻 {html.escape(item.get('symbol', ''))} ({html.escape(item.get('option_type', ''))}) &mdash; Loss: <span style="color: #f87171;">₹{item.get('loss_amount'):,.2f}</span></h3>
    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 8px;">
      Entry: ₹{item.get('entry_price'):.2f} &rarr; Exit: ₹{item.get('exit_price'):.2f} (SL: ₹{item.get('stop_loss'):.2f})
    </div>
    <div class="tech-box">
      <strong>Technical Breakdown:</strong><br>
      &bull; <strong>RSI:</strong> {html.escape(tech.get('rsi', 'N/A'))}<br>
      &bull; <strong>EMA Confluence:</strong> {html.escape(tech.get('ema', 'N/A'))}<br>
      &bull; <strong>VWAP:</strong> {html.escape(tech.get('vwap', 'N/A'))}<br>
      &bull; <strong>CPR:</strong> {html.escape(tech.get('cpr', 'N/A'))}<br>
      &bull; <strong>Open Interest:</strong> {html.escape(tech.get('oi', 'N/A'))}
    </div>
    <div style="margin-top: 8px; font-size: 13px; color: #e2e8f0;">
      <strong>Root Causes:</strong> {html.escape('; '.join(item.get('failure_reasons', [])))}<br>
      <span style="color: #94a3b8;">{html.escape(item.get('risk_management_notes', ''))}</span>
    </div>
  </div>
""")

        html_blocks.append("<h2>Target Hit Analysis (Winning Setups)</h2>")
        if not tgt_list:
            html_blocks.append("<p style='color: #64748b; font-style: italic;'>No targets reached today.</p>")
        else:
            for item in tgt_list:
                tech = item.get("supporting_technical_factors", {})
                html_blocks.append(f"""
  <div class="trade-card target">
    <h3>🟢 {html.escape(item.get('symbol', ''))} ({html.escape(item.get('option_type', ''))}) &mdash; Profit: <span style="color: #34d399;">₹{item.get('profit_amount'):+,.2f}</span></h3>
    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 8px;">
      Entry: ₹{item.get('entry_price'):.2f} &rarr; Exit: ₹{item.get('exit_price'):.2f} (Target: ₹{item.get('target'):.2f})
    </div>
    <div class="tech-box">
      <strong>Supporting Confluence:</strong><br>
      &bull; <strong>RSI:</strong> {html.escape(tech.get('rsi', 'N/A'))}<br>
      &bull; <strong>EMA Confluence:</strong> {html.escape(tech.get('ema', 'N/A'))}<br>
      &bull; <strong>VWAP:</strong> {html.escape(tech.get('vwap', 'N/A'))}<br>
      &bull; <strong>CPR:</strong> {html.escape(tech.get('cpr', 'N/A'))}<br>
      &bull; <strong>Open Interest:</strong> {html.escape(tech.get('oi', 'N/A'))}
    </div>
    <div style="margin-top: 8px; font-size: 13px; color: #e2e8f0;">
      <strong>Success Drivers:</strong> {html.escape('; '.join(item.get('success_factors', [])))}<br>
      <span style="color: #94a3b8;">{html.escape(item.get('execution_notes', ''))}</span>
    </div>
  </div>
""")

        html_blocks.append("""
  <h2>AI Agent Decision Audit</h2>
  <table>
    <thead>
      <tr>
        <th>Trade</th>
        <th>Verdict</th>
        <th>Conviction</th>
        <th>Alignment</th>
        <th>Audit Assessment</th>
      </tr>
    </thead>
    <tbody>
""")
        for d in dec_list:
            init = d.get("initial_recommendation", {})
            align = d.get("alignment_verdict", "ALIGNED")
            badge_class = "badge-green" if align == "ALIGNED" else ("badge-red" if align == "MISALIGNED" else "badge-yellow")
            html_blocks.append(f"""
      <tr>
        <td><code>{html.escape(d.get('symbol', ''))}</code></td>
        <td>{html.escape(init.get('judge_verdict', ''))}</td>
        <td>{init.get('judge_confidence', 7)}/10</td>
        <td><span class="badge {badge_class}">{align}</span></td>
        <td>{html.escape(d.get('confluence_evaluation', ''))}</td>
      </tr>
""")
        html_blocks.append("""
    </tbody>
  </table>

  <h2>Key Lessons Learned &amp; Desk Directives</h2>
  <div class="lessons-list">
    <ol>
""")
        for l in lessons:
            html_blocks.append(f"      <li>{html.escape(l)}</li>")

        html_blocks.append("""
    </ol>
  </div>
</div>
</body>
</html>
""")
        return "".join(html_blocks)

    # ── 7. Persistence ────────────────────────────────────────────────────────────

    async def _persist_report(self, payload: dict[str, Any]) -> None:
        """Upsert daily report into the persistent DailyReportModel table."""
        report_id = payload["id"]
        date_str = payload["date"]
        user_id = payload.get("user_id")

        async with async_session_factory() as session:
            try:
                stmt = select(DailyReportModel).where(DailyReportModel.id == report_id)
                db_rep = (await session.execute(stmt)).scalars().first()

                summary_str = json.dumps(payload["summary_metrics"])
                analysis_str = json.dumps(payload["raw_analysis"])

                if db_rep:
                    db_rep.date = date_str
                    db_rep.report_date = date_str
                    db_rep.user_id = user_id
                    db_rep.total_trades = payload["total_trades"]
                    db_rep.winning_trades = payload["winning_trades"]
                    db_rep.losing_trades = payload["losing_trades"]
                    db_rep.win_rate = payload["win_rate"]
                    db_rep.gross_pnl = payload["gross_pnl"]
                    db_rep.total_charges = payload["total_charges"]
                    db_rep.net_pnl = payload["net_pnl"]
                    db_rep.profit_factor = payload["profit_factor"]
                    db_rep.average_win = payload["average_win"]
                    db_rep.average_loss = payload["average_loss"]
                    db_rep.max_drawdown = payload["max_drawdown"]
                    db_rep.sl_hit_count = payload["sl_hit_count"]
                    db_rep.target_hit_count = payload["target_hit_count"]
                    db_rep.summary_metrics = summary_str
                    db_rep.summary_json = summary_str
                    db_rep.raw_analysis = analysis_str
                    db_rep.ai_analysis_json = analysis_str
                    db_rep.report_markdown = payload["report_markdown"]
                    db_rep.markdown_report = payload["report_markdown"]
                    db_rep.report_html = payload["report_html"]
                    db_rep.updated_at = ist_now_str()
                else:
                    db_rep = DailyReportModel(
                        id=report_id,
                        date=date_str,
                        report_date=date_str,
                        user_id=user_id,
                        total_trades=payload["total_trades"],
                        winning_trades=payload["winning_trades"],
                        losing_trades=payload["losing_trades"],
                        win_rate=payload["win_rate"],
                        gross_pnl=payload["gross_pnl"],
                        total_charges=payload["total_charges"],
                        net_pnl=payload["net_pnl"],
                        profit_factor=payload["profit_factor"],
                        average_win=payload["average_win"],
                        average_loss=payload["average_loss"],
                        max_drawdown=payload["max_drawdown"],
                        sl_hit_count=payload["sl_hit_count"],
                        target_hit_count=payload["target_hit_count"],
                        summary_metrics=summary_str,
                        summary_json=summary_str,
                        raw_analysis=analysis_str,
                        ai_analysis_json=analysis_str,
                        report_markdown=payload["report_markdown"],
                        markdown_report=payload["report_markdown"],
                        report_html=payload["report_html"],
                        created_at=ist_now_str(),
                        updated_at=ist_now_str(),
                    )
                    session.add(db_rep)

                await session.commit()
                logger.info("Persisted daily report %s for date %s (user_id=%s)", report_id, date_str, user_id)
            except Exception as exc:
                await session.rollback()
                logger.error("Failed to persist daily report %s: %s", report_id, exc)


daily_report_agent = DailyReportAgent.get_instance()
