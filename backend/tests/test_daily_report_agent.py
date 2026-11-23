"""
Automated unit tests for TradeLab DailyReportAgent and DailyReportModel.

Covers:
1. DailyReportModel schema attributes, properties, and dictionary serialization.
2. Summary metrics calculation (win rate, gross/net PnL, statutory charges, drawdown).
3. Stop-Loss Hit post-mortem analysis (RSI, EMA-20/50, VWAP, CPR, OI).
4. Target Hit confluence analysis (momentum, trend alignment, Put writing support).
5. AI Trade Decision audit (Bull vs Bear vs Judge verdict alignment).
6. Institutional quantitative fallback execution (offline simulation).
7. Publication-grade Markdown and HTML generation.
8. End-to-end database persistence and retrieval.
"""

import json
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select

from database import (
    DailyReportModel,
    PaperTradeModel,
    DebateRecordModel,
    init_db,
    async_session_factory,
)
from agents.daily_report_agent import DailyReportAgent, daily_report_agent

IST = ZoneInfo("Asia/Kolkata")


@pytest.mark.asyncio
async def test_daily_report_model_schema():
    """Verify DailyReportModel schema fields and serialization."""
    await init_db()

    test_date = "2026-11-23"
    test_id = f"test-report-{test_date}"

    metrics = {
        "total_trades": 3,
        "winning_trades": 2,
        "losing_trades": 1,
        "win_rate": 66.7,
        "net_pnl": 1250.0,
        "gross_pnl": 1450.0,
        "total_charges": 200.0,
    }
    raw_analysis = {
        "executive_summary": "Test executive summary",
        "key_lessons": ["Lesson 1", "Lesson 2"],
    }

    async with async_session_factory() as session:
        # Clean up existing test entry
        existing = await session.get(DailyReportModel, test_id)
        if existing:
            await session.delete(existing)
            await session.commit()

        report = DailyReportModel(
            id=test_id,
            date=test_date,
            user_id=None,
            total_trades=3,
            winning_trades=2,
            losing_trades=1,
            win_rate=66.7,
            gross_pnl=1450.0,
            total_charges=200.0,
            net_pnl=1250.0,
            summary_metrics=json.dumps(metrics),
            raw_analysis=json.dumps(raw_analysis),
            report_markdown="# Test Report",
            report_html="<h1>Test Report</h1>",
        )
        session.add(report)
        await session.commit()

    async with async_session_factory() as session:
        fetched = await session.get(DailyReportModel, test_id)
        assert fetched is not None
        assert fetched.date == test_date
        assert fetched.report_date == test_date
        assert fetched.win_rate == 66.7
        assert fetched.net_pnl == 1250.0

        d = fetched.to_dict()
        assert d["id"] == test_id
        assert d["date"] == test_date
        assert d["summary_metrics"]["total_trades"] == 3
        assert d["raw_analysis"]["executive_summary"] == "Test executive summary"
        assert d["report_markdown"] == "# Test Report"
        assert d["report_html"] == "<h1>Test Report</h1>"

        # Cleanup
        await session.delete(fetched)
        await session.commit()


@pytest.mark.asyncio
async def test_daily_report_agent_quantitative_fallback():
    """Verify the institutional quantitative fallback engine without Gemini API."""
    agent = DailyReportAgent(api_key="")  # Empty API key forces quantitative fallback

    test_date = "2026-11-23"
    trades = [
        # Trade 1: Stop-Loss Hit on Long Call
        {
            "id": "POS-TEST-SL-1",
            "pos_id": "POS-TEST-SL-1",
            "order_id": "ORD-TEST-SL-1",
            "symbol": "NIFTY24500CE",
            "underlying": "NIFTY",
            "strike": 24500.0,
            "option_type": "CE",
            "side": "BUY",
            "quantity": 25,
            "entry_price": 120.0,
            "exit_price": 92.0,
            "stop_loss": 92.0,
            "target": 160.0,
            "gross_pnl": -700.0,
            "realized_pnl": -755.0,
            "total_charges": 55.0,
            "exit_reason": "STOP_LOSS_HIT",
            "status": "CLOSED",
            "pnl_pct": -25.17,
        },
        # Trade 2: Target Hit on Long Call
        {
            "id": "POS-TEST-TGT-1",
            "pos_id": "POS-TEST-TGT-1",
            "order_id": "ORD-TEST-TGT-1",
            "symbol": "NIFTY24600CE",
            "underlying": "NIFTY",
            "strike": 24600.0,
            "option_type": "CE",
            "side": "BUY",
            "quantity": 25,
            "entry_price": 110.0,
            "exit_price": 150.0,
            "stop_loss": 85.0,
            "target": 150.0,
            "gross_pnl": 1000.0,
            "realized_pnl": 942.0,
            "total_charges": 58.0,
            "exit_reason": "TARGET_HIT",
            "status": "CLOSED",
            "pnl_pct": 34.25,
        },
    ]

    debates = {
        "POS-TEST-SL-1": {
            "market_snapshot": {
                "spot_price": 24520.0,
                "rsi": 62.5,
                "vwap": 24540.0,
                "ema_20": 24535.0,
                "ema_50": 24510.0,
                "cpr_width_type": "WIDE_RANGEBOUND",
                "pcr": 0.88,
                "ce_oi_change": 4500000.0,
                "pe_oi_change": -1200000.0,
                "call_oi_wall": 24600.0,
                "put_oi_wall": 24400.0,
            },
            "judge": {
                "verdict": "BUY CE",
                "confidence": 7,
                "reasoning": "Bullish breakout above day opening range.",
            },
            "bull": {
                "thesis": "Ascending triangle breakout.",
                "arguments": ["EMA-20 support held on 5m candle"],
            },
            "bear": {
                "thesis": "Overhead Call wall at 24600.",
                "arguments": ["Call writers aggressively building supply"],
            },
        },
        "POS-TEST-TGT-1": {
            "market_snapshot": {
                "spot_price": 24610.0,
                "rsi": 58.0,
                "vwap": 24580.0,
                "ema_20": 24575.0,
                "ema_50": 24550.0,
                "cpr_width_type": "NARROW_TRENDING",
                "pcr": 1.25,
                "ce_oi_change": -800000.0,
                "pe_oi_change": 3500000.0,
                "call_oi_wall": 24800.0,
                "put_oi_wall": 24500.0,
            },
            "judge": {
                "verdict": "BUY CE",
                "confidence": 8,
                "reasoning": "Momentum expansion with heavy Put writing.",
            },
            "bull": {
                "thesis": "Spot trending above VWAP and EMA-20.",
                "arguments": ["PCR expanded from 1.05 to 1.25"],
            },
            "bear": {
                "thesis": "Approaching minor resistance.",
                "arguments": ["Stochastic oscillator high"],
            },
        },
    }

    report = await agent.generate_report_from_trades(
        trades=trades,
        date_str=test_date,
        debates=debates,
        user_id=None,
        persist=False,
    )

    assert report is not None
    assert report["date"] == test_date
    assert report["total_trades"] == 2
    assert report["winning_trades"] == 1
    assert report["losing_trades"] == 1
    assert report["win_rate"] == 50.0
    assert report["net_pnl"] == round(942.0 - 755.0, 2)
    assert report["total_charges"] == round(55.0 + 58.0, 2)
    assert report["sl_hit_count"] == 1
    assert report["target_hit_count"] == 1

    raw = report["raw_analysis"]

    # 1. Verify Stop-Loss Hit Analysis
    sl_analysis = raw["stop_loss_analysis"]
    assert len(sl_analysis) == 1
    sl_item = sl_analysis[0]
    assert sl_item["symbol"] == "NIFTY24500CE"
    assert "VWAP" in sl_item["technical_factors"]["vwap"]
    assert "EMA" in sl_item["technical_factors"]["ema"]
    assert "CPR" in sl_item["technical_factors"]["cpr"]
    assert "OI" in sl_item["technical_factors"]["oi"] or "Call writing" in sl_item["technical_factors"]["oi"]
    assert len(sl_item["failure_reasons"]) >= 1

    # 2. Verify Target Hit Analysis
    tgt_analysis = raw["target_hit_analysis"]
    assert len(tgt_analysis) == 1
    tgt_item = tgt_analysis[0]
    assert tgt_item["symbol"] == "NIFTY24600CE"
    assert "VWAP" in tgt_item["supporting_technical_factors"]["vwap"]
    assert "RSI" in tgt_item["supporting_technical_factors"]["rsi"]
    assert len(tgt_item["success_factors"]) >= 1

    # 3. Verify Trade Decision Audit
    dec_analysis = raw["trade_decision_analysis"]
    assert len(dec_analysis) == 2
    assert dec_analysis[0]["alignment_verdict"] == "MISALIGNED"
    assert dec_analysis[1]["alignment_verdict"] == "ALIGNED"

    # 4. Verify Key Lessons Learned
    lessons = raw["key_lessons_learned"]
    assert len(lessons) >= 2

    # 5. Verify Markdown and HTML output
    md = report["report_markdown"]
    assert "# 📊 TradeLab AI Institutional Daily Trading Report" in md
    assert "Stop-Loss Hit Analysis" in md
    assert "Target Hit Analysis" in md
    assert "AI Agent Debate & Decision Audit" in md

    html_content = report["report_html"]
    assert "<!DOCTYPE html>" in html_content
    assert "TradeLab Daily Trading Report" in html_content
    assert "NIFTY24500CE" in html_content
    assert "NIFTY24600CE" in html_content


@pytest.mark.asyncio
async def test_daily_report_agent_empty_day():
    """Verify handling when no trades occurred on a given day."""
    agent = DailyReportAgent(api_key="")
    test_date = "2026-11-23"

    report = await agent.generate_report_from_trades(
        trades=[],
        date_str=test_date,
        debates={},
        user_id=None,
        persist=False,
    )

    assert report["total_trades"] == 0
    assert report["win_rate"] == 0.0
    assert report["net_pnl"] == 0.0
    assert report["total_charges"] == 0.0
    assert "Capital preservation" in report["raw_analysis"]["performance_summary"]["executive_summary"]
