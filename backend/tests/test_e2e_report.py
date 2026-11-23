import pytest
import asyncio
from datetime import datetime
from sqlalchemy import delete
from database import init_db, async_session_factory, DailyReportModel, PaperTradeModel
from paper_engine import paper_engine
from agents.report_agent import report_agent
from main import app
from httpx import AsyncClient, ASGITransport

@pytest.mark.asyncio
async def test_end_to_end_positions_and_reports():
    await init_db()
    async with async_session_factory() as session:
        await session.execute(delete(DailyReportModel))
        await session.execute(delete(PaperTradeModel))
        await session.commit()
    await paper_engine.reset_portfolio(1000000.0)
    
    # 1. Place a BUY trade with SL and Target
    order1 = await paper_engine.place_order(
        {
            "symbol": "NIFTY24900CE",
            "underlying": "NIFTY",
            "strike": 24900,
            "option_type": "CE",
            "side": "BUY",
            "order_type": "MARKET",
            "quantity": 50,
            "price": 120.0,
            "stop_loss": 90.0,
            "target": 160.0
        },
        enforce_hours=False
    )
    assert order1.get("status") in ["SUCCESS", "EXECUTED"] or order1.get("position_id")
    
    # Check open state
    state = await paper_engine.get_state()
    assert len(state["positions"]) == 1
    assert state["positions"][0]["trade_status"] == "OPEN"
    assert state["positions"][0]["stop_loss"] == 90.0
    assert state["positions"][0]["target"] == 160.0
    
    # 2. Simulate price movement hitting Target (LTP moves to 165.0)
    await paper_engine.update_market_prices({"NIFTY24900CE": 165.0})
    
    # Verify it hit target and moved to closed trades
    state = await paper_engine.get_state()
    assert len(state["positions"]) == 0
    assert len(state["closed_positions"]) == 1
    assert state["closed_positions"][0]["trade_status"] == "TARGET_HIT"
    assert state["closed_positions"][0]["exit_reason"] == "TARGET_HIT"
    assert state["closed_positions"][0]["realized_pnl"] > 0
    assert state["closed_positions"][0]["target"] == 160.0
    assert state["statistics"]["target_hit_count"] == 1
    
    # 3. Place a 2nd trade hitting Stop-Loss
    order2 = await paper_engine.place_order(
        {
            "symbol": "BANKNIFTY52000PE",
            "underlying": "BANKNIFTY",
            "strike": 52000,
            "option_type": "PE",
            "side": "BUY",
            "order_type": "MARKET",
            "quantity": 30,
            "price": 200.0,
            "stop_loss": 170.0,
            "target": 260.0
        },
        enforce_hours=False
    )
    
    # Simulate price movement hitting SL (LTP drops to 165.0)
    await paper_engine.update_market_prices({"BANKNIFTY52000PE": 165.0})
    
    state = await paper_engine.get_state()
    assert len(state["positions"]) == 0
    assert len(state["closed_positions"]) == 2
    assert state["statistics"]["sl_hit_count"] == 1
    assert state["statistics"]["target_hit_count"] == 1
    assert len(state["all_trades"]) == 2
    
    # 4. Test API Endpoints via ASGI test client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # GET /api/trading/state
        resp = await ac.get("/api/trading/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "all_trades" in data
        assert len(data["all_trades"]) == 2
        statuses = [t["trade_status"] for t in data["all_trades"]]
        assert "TARGET_HIT" in statuses
        assert "STOP_LOSS_HIT" in statuses
        
        # POST /api/reports/daily/generate
        today_str = datetime.now().strftime("%Y-%m-%d")
        gen_resp = await ac.post("/api/reports/daily/generate", json={"date": today_str})
        assert gen_resp.status_code == 200
        report = gen_resp.json()
        assert report["date"] == today_str
        assert report["total_trades"] == 2
        assert report["winning_trades"] == 1
        assert report["losing_trades"] == 1
        assert report["win_rate"] == 50.0
        
        # Check structured analysis sections
        raw_analysis = report["raw_analysis"]
        assert "target_hit_analysis" in raw_analysis
        assert len(raw_analysis["target_hit_analysis"]) >= 1
        sl_key = "stop_loss_analysis" if "stop_loss_analysis" in raw_analysis else "stop_loss_hit_analysis"
        assert sl_key in raw_analysis
        assert len(raw_analysis[sl_key]) >= 1
        assert "trade_decision_analysis" in raw_analysis
        assert "performance_summary" in raw_analysis
        lessons = raw_analysis.get("key_lessons_learned") or raw_analysis.get("performance_summary", {}).get("key_lessons", [])
        assert len(lessons) >= 1
        
        # Check Markdown export
        assert "report_markdown" in report
        assert "Daily Trading Report" in report["report_markdown"]
        assert "Target" in report["report_markdown"]
        assert "Stop-Loss" in report["report_markdown"]
        
        # GET /api/reports/daily
        get_rep = await ac.get(f"/api/reports/daily?date={today_str}")
        assert get_rep.status_code == 200
        assert get_rep.json()["total_trades"] == 2
        
        # GET /api/reports/dates
        dates_resp = await ac.get("/api/reports/dates")
        assert dates_resp.status_code == 200
        assert today_str in dates_resp.json()
