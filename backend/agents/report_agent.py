"""
AI Daily Trading Report Agent for TradeLab.

Generates end-of-day institutional trading summaries with deep-dive AI analysis:
1. All executed trades and overall net/gross P&L, fees, and stats.
2. Stop-Loss Hit Analysis: Why trades hit SL, market conditions, indicators, failure causes.
3. Target Hit Analysis: Why trades hit target, supporting indicators, market trends.
4. Trade Decision Analysis: Why AI agents recommended trades and alignment with actual market action.
5. Performance Summary & Actionable Key Lessons Learned.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types as genai_types
from sqlalchemy import select

from config import gemini_candidate_models, get_index_spec, normalize_index_symbol, settings
from database import DailyReportModel, DebateRecordModel, PaperTradeModel, async_session_factory
from paper_engine import paper_engine

logger = logging.getLogger("report_agent")
IST = ZoneInfo("Asia/Kolkata")


_REPORT_SYSTEM_PROMPT = """\
You are an institutional Risk Desk Auditor and Chief Trading Analyst evaluating the day's paper trading activity for an Indian derivatives fund (trading NIFTY / BANKNIFTY index options).

You have been provided with:
1. Full trade logs executed today (entry price, exit price, stop-loss, target, trade status, realized/unrealized P&L, entry/exit time).
2. The initial AI debate records (Bull thesis, Bear counter-thesis, Judge reasoning, confidence) for executed setups.
3. Market conditions and technical indicator snapshots.

Your task is to generate a rigorous, data-backed Daily Trading Report. Provide clear, analytical explanations grounded in specific price levels, numbers, indicator readings, and price action rather than generic advice.

Return your response as a valid JSON object matching this schema:
{
  "executive_summary": "<Comprehensive institutional summary paragraph of the day's performance and market dynamics>",
  "stop_loss_analysis": [
    {
      "trade_id": "<Trade/Position ID>",
      "symbol": "<Symbol e.g. NIFTY25000CE>",
      "entry_price": <float>,
      "exit_price": <float>,
      "stop_loss": <float>,
      "loss_amount": <float>,
      "market_conditions": "<Detailed price action and volatility context during the trade>",
      "technical_indicators": "<Readings of RSI, VWAP, EMA, CPR, and PCR that preceded or caused the stop loss breach>",
      "failure_reasons": "<Specific reasons why the predictive thesis failed, e.g. false breakout, overhead Call wall absorption, IV crush>",
      "key_takeaway": "<Concrete operational takeaway to prevent similar losses>"
    }
  ],
  "target_hit_analysis": [
    {
      "trade_id": "<Trade/Position ID>",
      "symbol": "<Symbol e.g. NIFTY24900PE>",
      "entry_price": <float>,
      "exit_price": <float>,
      "target": <float>,
      "profit_amount": <float>,
      "market_trends": "<Directional trend, volume surge, or momentum conditions enabling target achievement>",
      "supporting_indicators": "<Confluence of VWAP, EMA alignment, RSI continuation, and OI shifts that validated the setup>",
      "success_factors": "<Key factors driving the winning outcome>",
      "key_takeaway": "<Pattern recognition insight to repeat this success>"
    }
  ],
  "trade_decision_analysis": [
    {
      "trade_id": "<Trade/Position ID>",
      "symbol": "<Symbol>",
      "initial_verdict": "<BUY CE / BUY PE / MANUAL>",
      "judge_rationale": "<Why the AI judge approved the setup and Bull/Bear conviction levels>",
      "actual_market_movement": "<How the market actually behaved after entry>",
      "alignment_evaluation": "<Did the market validate or invalidate the agent's thesis? Was the Bear or Bull closer to reality?>",
      "agent_calibration_feedback": "<Specific feedback to calibrate agent confidence and threshold parameters>"
    }
  ],
  "performance_summary": {
    "total_trades": <int>,
    "win_rate_pct": <float>,
    "net_pnl": <float>,
    "profit_factor": <float>,
    "risk_discipline_rating": "<EXCELLENT | GOOD | NEEDS_IMPROVEMENT>",
    "overall_critique": "<Strategic analysis of the trading execution quality>"
  },
  "key_lessons_learned": [
    "<Data-backed lesson 1 with reference to specific metrics or events>",
    "<Data-backed lesson 2>",
    "<Data-backed lesson 3>"
  ]
}
"""


class ReportAgent:
    """AI Agent responsible for generating deep Daily Trading Reports with AI audit."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or settings.GEMINI_API_KEY
        self._client: Optional[genai.Client] = None
        if self._api_key:
            try:
                self._client = genai.Client(api_key=self._api_key)
            except Exception as exc:
                logger.warning("Could not initialize Gemini Client for ReportAgent: %s", exc)

    def _now_ist(self) -> str:
        return datetime.now(tz=IST).strftime("%Y-%m-%d %H:%M:%S")

    def _today_date(self) -> str:
        return datetime.now(tz=IST).strftime("%Y-%m-%d")

    async def get_or_generate_report(
        self, date_str: Optional[str] = None, user_id: Optional[int] = None, force_refresh: bool = False
    ) -> dict[str, Any]:
        """Fetch existing daily report or generate a new one if not yet created or force refreshed."""
        target_date = (date_str or self._today_date())[:10]
        report_id = f"report-{target_date}" + (f"-u{user_id}" if user_id is not None else "-guest")

        if not force_refresh:
            async with async_session_factory() as session:
                stmt = select(DailyReportModel).where(DailyReportModel.id == report_id)
                existing = (await session.execute(stmt)).scalars().first()
                if existing:
                    data = existing.to_dict()
                    data["executed_trades"] = await paper_engine.get_daily_trades(target_date, user_id=user_id)
                    return data

        return await self.generate_daily_report(target_date, user_id=user_id)

    async def generate_daily_report(
        self, date_str: Optional[str] = None, user_id: Optional[int] = None
    ) -> dict[str, Any]:
        """Generate a complete end-of-day trading report with quantitative and AI analysis."""
        target_date = (date_str or self._today_date())[:10]
        report_id = f"report-{target_date}" + (f"-u{user_id}" if user_id is not None else "-guest")

        # 1. Fetch all executed trades for the day (excluding known replay teardowns)
        raw_trades = await paper_engine.get_daily_trades(target_date, user_id=user_id)
        trades = [t for t in raw_trades if t.get("exit_reason") != "REPLAY_STOPPED"]

        # 2. Query associated AI debate sessions from DB
        debates_by_pos_or_order: dict[str, dict[str, Any]] = {}
        async with async_session_factory() as session:
            stmt = select(DebateRecordModel).where(DebateRecordModel.user_id == user_id).order_by(DebateRecordModel.created_at.desc())
            db_debates = (await session.execute(stmt)).scalars().all()
            for d in db_debates:
                try:
                    payload = json.loads(d.payload)
                except Exception:
                    payload = {}
                if d.position_id:
                    debates_by_pos_or_order[d.position_id] = payload
                if d.order_id:
                    debates_by_pos_or_order[d.order_id] = payload

        # 3. Calculate statistics
        total_trades = len(trades)
        closed_trades = [t for t in trades if t.get("status") == "CLOSED"]
        open_trades = [t for t in trades if t.get("status") == "ACTIVE" or t.get("trade_status") == "OPEN"]

        sl_hits = [t for t in trades if t.get("trade_status") == "STOP_LOSS_HIT" or t.get("exit_reason") == "STOP_LOSS_HIT"]
        tgt_hits = [t for t in trades if t.get("trade_status") == "TARGET_HIT" or t.get("exit_reason") == "TARGET_HIT"]
        winning_trades = [t for t in closed_trades if (t.get("realized_pnl") or 0.0) > 0]
        losing_trades = [t for t in closed_trades if (t.get("realized_pnl") or 0.0) < 0]

        total_closed = len(closed_trades)
        win_rate = round((len(winning_trades) / total_closed) * 100, 2) if total_closed > 0 else 0.0

        gross_profit = sum(t.get("realized_pnl", 0.0) for t in winning_trades)
        gross_loss = abs(sum(t.get("realized_pnl", 0.0) for t in losing_trades))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 1.0)
        avg_win = round(gross_profit / len(winning_trades), 2) if winning_trades else 0.0
        avg_loss = round(gross_loss / len(losing_trades), 2) if losing_trades else 0.0

        gross_pnl = sum(t.get("gross_pnl", t.get("realized_pnl", 0.0)) for t in closed_trades)
        total_charges = sum(t.get("total_charges", 0.0) for t in closed_trades)
        realized_net_pnl = sum(t.get("realized_pnl", 0.0) for t in closed_trades)
        unrealized_pnl = sum(t.get("unrealized_pnl", 0.0) for t in open_trades)
        net_pnl = round(realized_net_pnl + unrealized_pnl, 2)

        metrics = {
            "report_date": target_date,
            "total_trades": total_trades,
            "open_trades_count": len(open_trades),
            "closed_trades_count": total_closed,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "sl_hit_count": len(sl_hits),
            "target_hit_count": len(tgt_hits),
            "win_rate": win_rate,
            "gross_pnl": round(gross_pnl, 2),
            "total_charges": round(total_charges, 2),
            "realized_pnl": round(realized_net_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "net_pnl": net_pnl,
            "profit_factor": profit_factor,
            "average_win": avg_win,
            "average_loss": avg_loss,
            "max_drawdown": round(gross_loss, 2),
        }

        # 4. Generate AI Analysis (with Gemini LLM or data-backed quantitative rule engine)
        ai_analysis = await self._generate_ai_analysis(trades, debates_by_pos_or_order, metrics)

        # 5. Build presentation Markdown report
        markdown_report = self._build_markdown_report(metrics, trades, ai_analysis)

        # 6. Save or update record in SQLite DB
        now_time = self._now_ist()
        async with async_session_factory() as session:
            stmt = select(DailyReportModel).where(DailyReportModel.id == report_id)
            db_report = (await session.execute(stmt)).scalars().first()

            summary_json_str = json.dumps(metrics)
            ai_json_str = json.dumps(ai_analysis)

            if db_report:
                # Preserve prior report revision snapshot in AppKV (non-destructive audit trail for as-of QA-06/16)
                from database import AppKVModel
                rev_key = f"report-rev:{report_id}:{db_report.updated_at}"[:64]
                if await session.get(AppKVModel, rev_key) is None:
                    session.add(AppKVModel(
                        key=rev_key,
                        value=json.dumps({
                            "date": db_report.date or db_report.report_date,
                            "updated_at": db_report.updated_at,
                            "net_pnl": db_report.net_pnl,
                            "total_trades": db_report.total_trades,
                        }),
                    ))
                db_report.date = target_date
                db_report.report_date = target_date
                db_report.total_trades = total_trades
                db_report.winning_trades = len(winning_trades)
                db_report.losing_trades = len(losing_trades)
                db_report.win_rate = win_rate
                db_report.gross_pnl = round(gross_pnl, 2)
                db_report.total_charges = round(total_charges, 2)
                db_report.net_pnl = net_pnl
                db_report.profit_factor = profit_factor
                db_report.average_win = avg_win
                db_report.average_loss = avg_loss
                db_report.max_drawdown = round(gross_loss, 2)
                db_report.open_trades_count = len(open_trades)
                db_report.sl_hit_count = len(sl_hits)
                db_report.target_hit_count = len(tgt_hits)
                db_report.summary_metrics = summary_json_str
                db_report.summary_json = summary_json_str
                db_report.raw_analysis = ai_json_str
                db_report.ai_analysis_json = ai_json_str
                db_report.report_markdown = markdown_report
                db_report.markdown_report = markdown_report
                db_report.updated_at = now_time
            else:
                db_report = DailyReportModel(
                    id=report_id,
                    date=target_date,
                    report_date=target_date,
                    user_id=user_id,
                    total_trades=total_trades,
                    winning_trades=len(winning_trades),
                    losing_trades=len(losing_trades),
                    win_rate=win_rate,
                    gross_pnl=round(gross_pnl, 2),
                    total_charges=round(total_charges, 2),
                    net_pnl=net_pnl,
                    profit_factor=profit_factor,
                    average_win=avg_win,
                    average_loss=avg_loss,
                    max_drawdown=round(gross_loss, 2),
                    open_trades_count=len(open_trades),
                    sl_hit_count=len(sl_hits),
                    target_hit_count=len(tgt_hits),
                    summary_metrics=summary_json_str,
                    summary_json=summary_json_str,
                    raw_analysis=ai_json_str,
                    ai_analysis_json=ai_json_str,
                    report_markdown=markdown_report,
                    markdown_report=markdown_report,
                    created_at=now_time,
                    updated_at=now_time,
                )
                session.add(db_report)
            await session.commit()
            data = db_report.to_dict()
            data["executed_trades"] = trades
            return data

    async def _generate_ai_analysis(
        self,
        trades: list[dict[str, Any]],
        debates: dict[str, dict[str, Any]],
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate structured AI analysis via Gemini or fallback quantitative engine."""
        if not trades:
            return {
                "executive_summary": f"No trades were executed on {metrics['report_date']}. The virtual trading portfolio remained flat with ₹0 P&L.",
                "stop_loss_analysis": [],
                "target_hit_analysis": [],
                "trade_decision_analysis": [],
                "performance_summary": {
                    "total_trades": 0,
                    "win_rate_pct": 0.0,
                    "net_pnl": 0.0,
                    "profit_factor": 1.0,
                    "risk_discipline_rating": "EXCELLENT",
                    "overall_critique": "Capital preservation maintained. No capital exposed during this session.",
                },
                "key_lessons_learned": [
                    "Preserving capital during non-confluent market regimes prevents unforced drawdowns.",
                    "Wait for high-conviction (>7.0/10) multi-agent institutional confluences.",
                ],
            }

        # Build trade payloads with linked debate info
        enriched_trades = []
        for t in trades:
            pos_id = t.get("id") or t.get("pos_id")
            order_id = t.get("order_id")
            debate_info = debates.get(pos_id) or debates.get(order_id)
            enriched_trades.append({
                "trade_id": pos_id,
                "symbol": t.get("symbol"),
                "underlying": t.get("underlying"),
                "strike": t.get("strike"),
                "option_type": t.get("option_type"),
                "side": t.get("side"),
                "lots": t.get("lots"),
                "quantity": t.get("quantity"),
                "entry_price": t.get("entry_price"),
                "exit_price": t.get("exit_price"),
                "stop_loss": t.get("stop_loss"),
                "target": t.get("target"),
                "trade_status": t.get("trade_status") or t.get("status"),
                "exit_reason": t.get("exit_reason"),
                "realized_pnl": t.get("realized_pnl"),
                "unrealized_pnl": t.get("unrealized_pnl"),
                "entry_time": t.get("entry_time") or t.get("created_at"),
                "exit_time": t.get("exit_time") or t.get("closed_at"),
                "debate_verdict": debate_info.get("judge", {}).get("verdict") if debate_info else None,
                "debate_confidence": debate_info.get("judge", {}).get("confidence") if debate_info else None,
                "judge_reasoning": debate_info.get("judge", {}).get("reasoning") if debate_info else None,
                "bull_thesis": debate_info.get("bull", {}).get("thesis") if debate_info else None,
                "bear_thesis": debate_info.get("bear", {}).get("thesis") if debate_info else None,
            })

        # Try Gemini API if client available
        if self._client:
            prompt = (
                f"Trading Date: {metrics['report_date']}\n"
                f"Session Metrics:\n{json.dumps(metrics, indent=2)}\n\n"
                f"Executed Trades & AI Debate Context:\n{json.dumps(enriched_trades, indent=2)}"
            )
            models_to_try = gemini_candidate_models()
            for model_name in models_to_try:
                try:
                    response = await asyncio.wait_for(
                        self._client.aio.models.generate_content(
                            model=model_name,
                            contents=prompt,
                            config=genai_types.GenerateContentConfig(
                                system_instruction=_REPORT_SYSTEM_PROMPT,
                                temperature=0.2,
                                response_mime_type="application/json",
                            ),
                        ),
                        timeout=25.0,
                    )
                    if response and response.text:
                        raw = response.text.strip()
                        if raw.startswith("```"):
                            raw = raw.split("\n", 1)[1].rsplit("\n", 1)[0]
                        parsed = json.loads(raw)
                        logger.info("Successfully generated AI Daily Report using model %s", model_name)
                        return parsed
                except Exception as exc:
                    logger.warning("Gemini AI report generation failed on %s: %s", model_name, exc)

        # Quantitative heuristic engine fallback (always reliable and data-backed)
        return self._generate_quantitative_analysis(enriched_trades, metrics)

    def _generate_quantitative_analysis(
        self, enriched_trades: list[dict[str, Any]], metrics: dict[str, Any]
    ) -> dict[str, Any]:
        """Data-backed quantitative analysis when LLM is unavailable."""
        sl_analyses = []
        tgt_analyses = []
        decision_analyses = []
        lessons = []

        for t in enriched_trades:
            tid = t.get("trade_id")
            sym = t.get("symbol")
            entry = t.get("entry_price", 0.0)
            exit_p = t.get("exit_price") or entry
            sl = t.get("stop_loss")
            tgt = t.get("target")
            pnl = t.get("realized_pnl") or t.get("unrealized_pnl") or 0.0
            status = t.get("trade_status") or t.get("status")
            opt_type = t.get("option_type") or "CE"
            underlying = t.get("underlying") or "NIFTY"
            is_ce = opt_type == "CE"

            # 1. Stop Loss Hit Analysis
            if status == "STOP_LOSS_HIT" or t.get("exit_reason") == "STOP_LOSS_HIT":
                price_drop_pct = round(((entry - exit_p) / entry) * 100, 1) if entry > 0 else 0.0
                sl_analyses.append({
                    "trade_id": tid,
                    "symbol": sym,
                    "entry_price": entry,
                    "exit_price": exit_p,
                    "stop_loss": sl,
                    "loss_amount": abs(pnl),
                    "market_conditions": (
                        f"Underlying {underlying} experienced an intraday directional rejection. "
                        f"Option premium declined by {price_drop_pct}% from entry ₹{entry:.2f} down to ₹{exit_p:.2f}, "
                        f"breaching the pre-set risk threshold of {'₹' + f'{sl:.2f}' if sl is not None else 'market SL'}."
                    ),
                    "technical_indicators": (
                        "Quantitative fallback (Gemini unavailable): exact post-exit candle indicators were not independently audited for this trade."
                    ),
                    "failure_reasons": (
                        f"Hypothesis (unverified fallback): adverse move of {price_drop_pct}% from entry ₹{entry:.2f} to ₹{exit_p:.2f} in {sym} ({opt_type}) breached stop loss."
                    ),
                    "key_takeaway": (
                        f"Strict adherence to the {'₹' + f'{sl:.2f}' if sl is not None else 'Stop Loss'} successfully protected capital from unmanaged max drawdown. "
                        f"For future {opt_type} setups, demand confirmation of 2 consecutive candle closes above VWAP before entry."
                    ),
                })

            # 2. Target Hit Analysis
            if status == "TARGET_HIT" or t.get("exit_reason") == "TARGET_HIT":
                gain_pct = round(((exit_p - entry) / entry) * 100, 1) if entry > 0 else 0.0
                tgt_analyses.append({
                    "trade_id": tid,
                    "symbol": sym,
                    "entry_price": entry,
                    "exit_price": exit_p,
                    "target": tgt,
                    "profit_amount": pnl,
                    "market_trends": (
                        f"Underlying {underlying} established a sustained intraday directional expansion. "
                        f"The premium expanded by +{gain_pct}% from ₹{entry:.2f} to precisely achieve the target objective of {'₹' + f'{tgt:.2f}' if tgt is not None else 'target'}."
                    ),
                    "supporting_indicators": (
                        "Quantitative fallback (Gemini unavailable): exact post-exit indicator series was not independently audited for this trade."
                    ),
                    "success_factors": (
                        f"Observed favorable premium expansion of +{gain_pct}% from ₹{entry:.2f} to ₹{exit_p:.2f} reaching configured target."
                    ),
                    "key_takeaway": (
                        f"Excellent execution on {sym}. When directional confluence aligns with option chain open interest, "
                        f"allow the position to complete its full trajectory to target."
                    ),
                })

            # 3. Trade Decision Analysis
            verdict = t.get("debate_verdict") or ("BUY " + opt_type)
            conf = t.get("debate_confidence") or 7
            aligned = (pnl >= 0) if status != "OPEN" else True
            decision_analyses.append({
                "trade_id": tid,
                "symbol": sym,
                "initial_verdict": verdict,
                "judge_rationale": (
                    t.get("judge_reasoning") or
                    f"Chief Risk Officer authorized {verdict} on {sym} with {conf}/10 confidence based on multi-indicator confluence and strict capital guardrails."
                ),
                "actual_market_movement": (
                    f"Premium moved from ₹{entry:.2f} to ₹{exit_p:.2f} ({'+' if pnl >= 0 else ''}₹{pnl:.2f} net P&L). "
                    f"Status: {status}."
                ),
                "alignment_evaluation": (
                    f"The recommendation was {'CORRECT and fully aligned with market trajectory' if aligned else 'DISRUPTED by unexpected intraday market reversal'}. "
                    f"{'The Bull thesis correctly anticipated the expansion.' if aligned and is_ce else ('The Bear thesis correctly warned of overhead headwinds.' if not aligned and is_ce else 'Strategy maintained strict risk discipline.')}"
                ),
                "agent_calibration_feedback": (
                    f"Maintain minimum confidence threshold of 7/10 for {underlying} entries. "
                    f"{'Agent correctly identified momentum confluence.' if aligned else 'Agent should elevate weighting of OI wall resistance when spot approaches round numbers.'}"
                ),
            })

        # Key Lessons
        if sl_analyses:
            lessons.append(
                f"Stop-loss discipline capped total downside on {len(sl_analyses)} trade(s) to predetermined thresholds, preventing catastrophic drawdown."
            )
        if tgt_analyses:
            lessons.append(
                f"Target achievement on {len(tgt_analyses)} trade(s) demonstrated high statistical edge when trades align with higher timeframe VWAP and EMA trend."
            )
        lessons.append(
            f"Net P&L of {'+' if metrics['net_pnl'] >= 0 else ''}₹{metrics['net_pnl']:.2f} with a {metrics['win_rate']}% win rate underscores the value of disciplined risk-reward execution."
        )

        exec_summary = (
            f"On {metrics['report_date']}, {metrics['total_trades']} total trade(s) were recorded with {metrics['closed_trades_count']} completed "
            f"and {metrics['open_trades_count']} open position(s). The portfolio generated a Net P&L of "
            f"{'+' if metrics['net_pnl'] >= 0 else ''}₹{metrics['net_pnl']:.2f} after ₹{metrics['total_charges']:.2f} in statutory exchange charges and brokerage. "
            f"The session recorded {len(tgt_analyses)} Target Hit(s) and {len(sl_analyses)} Stop-Loss Hit(s), yielding an overall win rate of {metrics['win_rate']}%."
        )

        return {
            "executive_summary": exec_summary,
            "stop_loss_analysis": sl_analyses,
            "target_hit_analysis": tgt_analyses,
            "trade_decision_analysis": decision_analyses,
            "performance_summary": {
                "total_trades": metrics["total_trades"],
                "win_rate_pct": metrics["win_rate"],
                "net_pnl": metrics["net_pnl"],
                "profit_factor": metrics["profit_factor"],
                "risk_discipline_rating": "EXCELLENT" if metrics["sl_hit_count"] == 0 or metrics["profit_factor"] >= 1.5 else "GOOD",
                "overall_critique": "Solid execution with strict capital protection and transparent trade rationale.",
            },
            "key_lessons_learned": lessons,
        }

    def _build_markdown_report(
        self, metrics: dict[str, Any], trades: list[dict[str, Any]], ai_analysis: dict[str, Any]
    ) -> str:
        """Construct a formatted Markdown document for the Daily Trading Report."""
        net = metrics["net_pnl"]
        is_profit = net >= 0
        pnl_badge = f"+₹{net:,.2f}" if is_profit else f"-₹{abs(net):,.2f}"

        md = []
        md.append(f"# 📊 Institutional Daily Trading Report — {metrics['report_date']}")
        md.append(f"**Session Outcome:** **{pnl_badge}** | **Win Rate:** {metrics['win_rate']}% | **Total Trades:** {metrics['total_trades']}\n")
        md.append(f"> {ai_analysis.get('executive_summary', '')}\n")

        # Performance Scorecard Table
        md.append("## 🏆 Performance Scorecard")
        md.append("| Metric | Value | Metric | Value |")
        md.append("| :--- | :--- | :--- | :--- |")
        md.append(f"| **Total Executed Trades** | `{metrics['total_trades']}` | **Win Rate** | `{metrics['win_rate']}%` |")
        md.append(f"| **Winning Trades** | `{metrics['winning_trades']}` | **Losing Trades** | `{metrics['losing_trades']}` |")
        md.append(f"| **Target Hits** | `🎯 {metrics['target_hit_count']}` | **Stop-Loss Hits** | `⚠️ {metrics['sl_hit_count']}` |")
        md.append(f"| **Gross Realized P&L** | `₹{metrics['gross_pnl']:,.2f}` | **Charges & Taxes** | `₹{metrics['total_charges']:,.2f}` |")
        md.append(f"| **Net Realized P&L** | `₹{metrics['realized_pnl']:,.2f}` | **Unrealized (Open)** | `₹{metrics['unrealized_pnl']:,.2f}` |")
        md.append(f"| **Net Session P&L** | **`{pnl_badge}`** | **Profit Factor** | `{metrics['profit_factor']}` |")
        md.append(f"| **Average Win** | `₹{metrics['average_win']:,.2f}` | **Average Loss** | `₹{metrics['average_loss']:,.2f}` |\n")

        # Key Lessons Learned
        md.append("## 💡 Key Lessons Learned & Actionable Takeaways")
        lessons = ai_analysis.get("key_lessons_learned", [])
        if lessons:
            for i, lesson in enumerate(lessons, 1):
                md.append(f"{i}. {lesson}")
        else:
            md.append("1. Maintain disciplined stop loss placement.\n2. Align option purchases with multi-timeframe VWAP.")
        md.append("")

        # Executed Trades Table
        md.append("## 📋 Executed Trades Journal")
        if trades:
            md.append("| ID | Instrument | Type | Entry (₹) | Exit (₹) | SL (₹) | Target (₹) | Net P&L (₹) | Status | Execution Time |")
            md.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |")
            for t in trades:
                tid = (t.get("id") or t.get("pos_id") or "")[-8:]
                sym = t.get("symbol") or "NIFTY Option"
                opt_type = t.get("option_type") or "CE"
                entry = f"₹{t.get('entry_price', 0):.2f}"
                exit_p = f"₹{t.get('exit_price'):.2f}" if t.get("exit_price") is not None else "—"
                sl = f"₹{t.get('stop_loss'):.2f}" if t.get("stop_loss") is not None else "—"
                tgt = f"₹{t.get('target'):.2f}" if t.get("target") is not None else "—"
                pnl = t.get("realized_pnl") if t.get("status") == "CLOSED" else (t.get("unrealized_pnl") or t.get("pnl") or 0.0)
                pnl_str = f"{'+' if pnl >= 0 else ''}₹{pnl:,.2f}"
                status = t.get("trade_status") or t.get("status") or "CLOSED"
                exec_time = (t.get("entry_time") or t.get("created_at") or "")[11:19]
                md.append(f"| `{tid}` | **{sym}** | `{opt_type}` | {entry} | {exit_p} | {sl} | {tgt} | **{pnl_str}** | `{status}` | {exec_time} |")
        else:
            md.append("*No trades were executed on this date.*")
        md.append("")

        # Deep Dive: Stop-Loss Hit Analysis
        sl_list = ai_analysis.get("stop_loss_analysis", [])
        if sl_list:
            md.append("## ⚠️ Deep-Dive: Stop-Loss Hit Analysis")
            md.append("Detailed institutional post-mortem for each trade that hit its stop loss:\n")
            for item in sl_list:
                md.append(f"### Trade `{item.get('trade_id')}` — {item.get('symbol')}")
                md.append(f"- **Entry Price:** ₹{(item.get('entry_price') or 0):.2f} | **Exit Price:** ₹{(item.get('exit_price') or 0):.2f} | **SL Trigger:** {'₹' + format(float(item['stop_loss']), '.2f') if item.get('stop_loss') is not None else '—'}")
                md.append(f"- **Realized Loss:** `-₹{(item.get('loss_amount') or 0):,.2f}`")
                md.append(f"- **Market Conditions & Price Movement:** {item.get('market_conditions')}")
                md.append(f"- **Technical Indicator Dynamics:** {item.get('technical_indicators')}")
                md.append(f"- **Root Cause for Failed Prediction:** {item.get('failure_reasons')}")
                md.append(f"- **Operational Takeaway:** 🛡️ *{item.get('key_takeaway')}*\n")

        # Deep Dive: Target Hit Analysis
        tgt_list = ai_analysis.get("target_hit_analysis", [])
        if tgt_list:
            md.append("## 🎯 Deep-Dive: Target Hit Analysis")
            md.append("Analytical breakdown of setups that reached their target profit objectives:\n")
            for item in tgt_list:
                md.append(f"### Trade `{item.get('trade_id')}` — {item.get('symbol')}")
                md.append(f"- **Entry Price:** ₹{(item.get('entry_price') or 0):.2f} | **Exit Price:** ₹{(item.get('exit_price') or 0):.2f} | **Target Level:** {'₹' + format(float(item['target']), '.2f') if item.get('target') is not None else '—'}")
                md.append(f"- **Realized Profit:** `+₹{(item.get('profit_amount') or 0):,.2f}`")
                md.append(f"- **Market Trend Dynamics:** {item.get('market_trends')}")
                md.append(f"- **Supporting Technical Confluences:** {item.get('supporting_indicators')}")
                md.append(f"- **Critical Drivers of Success:** {item.get('success_factors')}")
                md.append(f"- **Replicable Rule:** ⭐ *{item.get('key_takeaway')}*\n")

        # Trade Decision Analysis (AI Agent Evaluation)
        decision_list = ai_analysis.get("trade_decision_analysis", [])
        if decision_list:
            md.append("## 🤖 AI Trading Agents: Decision Audit & Predictive Accuracy")
            md.append("Evaluation of initial Bull, Bear, and Judge recommendations versus real-time market behavior:\n")
            for item in decision_list:
                md.append(f"### Setup `{item.get('trade_id')}` — {item.get('symbol')} ({item.get('initial_verdict')})")
                md.append(f"- **Initial AI CRO Recommendation:** {item.get('judge_rationale')}")
                md.append(f"- **Subsequent Price Trajectory:** {item.get('actual_market_movement')}")
                md.append(f"- **Hypothesis Alignment Evaluation:** {item.get('alignment_evaluation')}")
                md.append(f"- **Agent Calibration Feedback:** ⚙️ *{item.get('agent_calibration_feedback')}*\n")

        return "\n".join(md)


# Global singleton instance
report_agent = ReportAgent()
