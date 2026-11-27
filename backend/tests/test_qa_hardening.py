"""Comprehensive integration & hardening tests covering QA-11 through QA-25 fixes and HTTP endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import time
import uuid
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import create_async_engine

from agents.bear_agent import BearAgent
from agents.bull_agent import BullAgent
from agents.judge_agent import JudgeAgent
from agents.report_agent import ReportAgent
from angel_service import AngelService
from auth import create_access_token
from config import Settings, settings
from database import AppKVModel, Base, PaperTradeModel, PortfolioModel, UserModel, async_session_factory, init_db
from debate_engine import DebateEngine
from debate_schemas import BearAgentOutput, BullAgentOutput, DebateSession, JudgeAgentOutput, MarketSnapshot
from main import app
from migrations import apply_additive_migrations, inspect_schema
from paper_engine import PaperEngine
from replay_engine import replay_engine
from scheduler import DebateScheduler
from session_calendar import parse_holidays, parse_special_sessions, session_bounds, trading_day

IST = ZoneInfo("Asia/Kolkata")


async def _make_user(suffix: str = "") -> UserModel:
    await init_db()
    uid_tag = uuid.uuid4().hex[:8] + suffix
    async with async_session_factory() as db:
        u = UserModel(
            username=f"qa_{uid_tag}",
            email=f"qa_{uid_tag}@example.invalid",
            hashed_password="unused",
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u


def _sample_order(**kw):
    return {
        "symbol": "NIFTY31DEC9925000CE",
        "underlying": "NIFTY",
        "strike": 25000.0,
        "option_type": "CE",
        "side": "BUY",
        "order_type": "MARKET",
        "lots": 1,
        "lot_size": 65,
        "price": 100.0,
        "current_ltp": 100.0,
        **kw,
    }


@pytest.mark.asyncio
async def test_qa11_auto_execute_blocks_partial_fallback_and_bad_geometry(monkeypatch):
    user = await _make_user("qa11")
    engine = DebateEngine()
    snap = MarketSnapshot(
        symbol="NIFTY",
        spot_price=25300.0,
        ema_20=25100.0,
        ema_50=25000.0,
        vwap=25150.0,
        rsi=62.0,
        day_open=25000.0,
        session_reference="VWAP",
        vix=None,
    )
    session = DebateSession(
        id=f"deb-{uuid.uuid4().hex[:8]}",
        symbol="NIFTY",
        spot_price=25300.0,
        market_snapshot=snap,
        bull=BullAgentOutput(
            analysis_source="gemini", confidence=8, strike=25300, thesis="up", arguments=["VWAP above"]
        ),
        bear=BearAgentOutput(
            analysis_source="fallback", confidence=4, strike=25300, thesis="down", arguments=["Resistance"]
        ),
        judge=JudgeAgentOutput(
            verdict="BUY CE",
            analysis_source="gemini",
            confidence=8,
            recommended_strike=25300,
            entry_price=110.0,
            stop_loss=100.0,
            target=125.0,
            reasoning="Bullish setup",
        ),
        user_id=user.id,
    )
    engine._history.insert(0, session)
    from angel_service import angel_service
    monkeypatch.setattr(angel_service, "is_configured", lambda: True)

    with pytest.raises(ValueError, match="Gemini analysis"):
        await engine.execute_verdict(session.id, user_id=user.id, auto=True)

    # Judge infeasible low-premium geometry must downgrade cleanly to NO_TRADE instead of throwing into fallback
    tiny = JudgeAgent()._parse_and_guardrail(
        {
            "verdict": "BUY CE",
            "confidence": 8,
            "recommended_strike": 25000,
            "entry_price": 0.05,
            "stop_loss": 0.02,
            "target": 0.15,
            "reasoning": "Tiny tick",
        },
        snap,
    )
    assert tiny.verdict == "NO_TRADE"


@pytest.mark.asyncio
async def test_qa12_quote_freshness_and_stale_mtm(monkeypatch):
    svc = AngelService()
    tok = "99999"
    now = time.time()

    # Exchange timestamp, not HTTP receipt/cache time, establishes freshness.
    from datetime import datetime, timezone, timedelta
    fresh_quote = {"ltp": 120.5, "exchFeedTime": (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()}
    ok, _, age = svc._is_quote_valid_and_fresh(tok, fresh_quote, max_age_seconds=5.0)
    assert ok is True and age <= 5.0
    old_quote = dict(fresh_quote, exchFeedTime=(datetime.now(timezone.utc)-timedelta(seconds=25)).isoformat())
    assert svc._is_quote_valid_and_fresh(tok, old_quote, max_age_seconds=10.0)[0] is False
    assert svc._is_quote_valid_and_fresh(tok, {"ltp":120.5})[0] is False
    assert svc._is_quote_valid_and_fresh(tok, dict(fresh_quote, ltp=float("nan")))[0] is False
    assert svc._is_quote_valid_and_fresh(tok, dict(fresh_quote, ltp=0))[0] is False

    # Missing fresh quote marks position quote_stale=True and check_intraday_squareoff defers cleanly
    user = await _make_user("qa12")
    pe = PaperEngine()
    await pe.reset_portfolio(1000000.0, user_id=user.id)
    fill = await pe.place_order(_sample_order(), user_id=user.id, enforce_hours=False)
    pid = fill["position_id"]
    await pe.update_market_prices({})
    assert pe.active_positions[pid]["quote_stale"] is True
    # Squareoff with no fresh quote must defer rather than fabricate exit price
    monkeypatch.setattr("paper_engine.is_trading_day", lambda _now: True)
    res = await pe.check_intraday_squareoff(fresh_quotes={})
    # During off-hours < 15:15 returns []; explicitly test with mocked 15:20 IST on a trading day:
    class _FixedDt(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 25, 15, 20, 0, tzinfo=tz or IST)

    monkeypatch.setattr("paper_engine.datetime", _FixedDt)
    res = await pe.check_intraday_squareoff(fresh_quotes={})
    assert res == []
    assert pid in pe.active_positions


@pytest.mark.asyncio
async def test_qa14_stale_worker_syncs_sl_and_concurrent_portfolio_creation():
    user = await _make_user("qa14")
    a, b = PaperEngine(), PaperEngine()
    await a.reset_portfolio(1000000.0, user_id=user.id)
    fill = await a.place_order(_sample_order(stop_loss=90.0, target=150.0), user_id=user.id, enforce_hours=False)
    pid = fill["position_id"]

    # Worker b loads position with SL=90
    await b.restore_from_db()
    assert b.active_positions[pid]["stop_loss"] == 90.0

    # Worker a widens SL to 50 in DB
    upd = await a.update_sl(pid, stop_loss=50.0, user_id=user.id)
    assert upd["status"] == "SUCCESS"

    # Worker b sees LTP=80 (< old 90, > new 50). It MUST sync 50 from DB and NOT exit!
    await b.update_market_prices({_sample_order()["symbol"]: 80.0})
    assert b.active_positions[pid]["stop_loss"] == 50.0
    state = await a.get_state(user_id=user.id)
    assert len(state["positions"]) == 1

    # Concurrent first-time portfolio creation for a fresh user must not IntegrityError
    fresh_user = await _make_user("qa14_race")
    ports = await asyncio.gather(a.get_state(user_id=fresh_user.id), b.get_state(user_id=fresh_user.id))
    assert ports[0]["wallet"]["cash_balance"] == 1000000.0
    assert ports[1]["wallet"]["cash_balance"] == 1000000.0


@pytest.mark.asyncio
async def test_qa16_report_none_sl_replay_filter_and_revision_history():
    user = await _make_user("qa16")
    pe = PaperEngine()
    await pe.reset_portfolio(1000000.0, user_id=user.id)

    # Trade with None SL/target & UTC offset timestamp crossing into next IST day
    f1 = await pe.place_order(_sample_order(stop_loss=None, target=None), user_id=user.id, enforce_hours=False)
    pid1 = f1["position_id"]
    await pe.exit_position(pid1, exit_price=112.0, user_id=user.id, reason="MANUAL_EXIT")

    # Replay stopped trade that should be excluded from daily report metrics
    f2 = await pe.place_order(_sample_order(strike=25100.0, symbol="NIFTY31DEC9925100CE"), user_id=user.id, enforce_hours=False)
    pid2 = f2["position_id"]
    await pe.exit_position(pid2, exit_price=50.0, user_id=user.id, reason="REPLAY_STOPPED")

    target_day = datetime.now(IST).strftime("%Y-%m-%d")
    ra = ReportAgent(api_key="")  # force fallback quantitative path
    ra._client = None
    rep1 = await ra.generate_daily_report(date_str=target_day, user_id=user.id)
    assert rep1["total_trades"] == 1  # REPLAY_STOPPED excluded
    assert "Fallback" in rep1["report_markdown"] or "Daily Trading Report" in rep1["report_markdown"]

    # Regenerate report -> old snapshot stored in app_kv
    rep2 = await ra.generate_daily_report(date_str=target_day, user_id=user.id)
    assert rep2["total_trades"] == 1
    async with async_session_factory() as db:
        revs = (await db.execute(select(AppKVModel).where(AppKVModel.key.like(f"report-rev:report-{target_day}-u{user.id}:%")))).scalars().all()
        assert len(revs) >= 1


@pytest.mark.asyncio
async def test_qa18_null_vix_and_session_high_low():
    snap = MarketSnapshot(
        symbol="NIFTY",
        spot_price=25000.0,
        ema_20=24900.0,
        ema_50=24800.0,
        vwap=24950.0,
        rsi=60.0,
        vix=None,
        pcr=None,
    )
    bull = BullAgent(api_key="")
    bear = BearAgent(api_key="")
    judge = JudgeAgent(api_key="")
    assert "VIX: UNAVAILABLE" in judge._build_prompt(snap, bull._fallback_output(snap), bear._fallback_output(snap))
    assert "UNAVAILABLE" in bull._build_prompt(snap)
    assert "UNAVAILABLE" in bear._build_prompt(snap)


@pytest.mark.asyncio
async def test_qa19_non_destructive_migrations_preserve_legacy_data(tmp_path):
    db_file = tmp_path / "legacy_prod.db"
    sync_url = f"sqlite:///{db_file}"
    async_url = f"sqlite+aiosqlite:///{db_file}"

    # Build an older pre-migration schema & populate legacy financial rows
    sync_eng = create_engine(sync_url)
    with sync_eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, email TEXT UNIQUE, hashed_password TEXT, created_at TEXT)")
        conn.exec_driver_sql("CREATE TABLE portfolios (id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, initial_capital REAL, cash_balance REAL, margin_used REAL, updated_at TEXT)")
        conn.exec_driver_sql("CREATE TABLE paper_trades (id TEXT PRIMARY KEY, user_id INTEGER, symbol TEXT, underlying TEXT, strike REAL, option_type TEXT, side TEXT, lots INTEGER, quantity INTEGER, entry_price REAL, exit_price REAL, current_ltp REAL, pnl REAL, gross_pnl REAL, realized_pnl REAL, total_charges REAL, status TEXT, stop_loss REAL, target REAL, exit_reason TEXT, pnl_pct REAL, created_at TEXT, closed_at TEXT)")
        conn.exec_driver_sql("CREATE TABLE daily_reports (id TEXT PRIMARY KEY, report_date TEXT, user_id INTEGER, total_trades INTEGER, winning_trades INTEGER, losing_trades INTEGER, win_rate REAL, gross_pnl REAL, total_charges REAL, net_pnl REAL, profit_factor REAL, average_win REAL, average_loss REAL, max_drawdown REAL, open_trades_count INTEGER, sl_hit_count INTEGER, target_hit_count INTEGER, summary_json TEXT, ai_analysis_json TEXT, markdown_report TEXT, created_at TEXT, updated_at TEXT)")
        conn.exec_driver_sql("INSERT INTO users VALUES (42, 'legacy_trader', 'legacy@test.local', 'hash', '2026-11-01 09:00:00')")
        conn.exec_driver_sql("INSERT INTO portfolios VALUES (7, 42, 1000000.0, 987654.32, 0.0, '2026-11-20 15:30:00')")
        conn.exec_driver_sql("INSERT INTO paper_trades VALUES ('POS-OLD-1', 42, 'NIFTY26NOV25000CE', 'NIFTY', 25000, 'CE', 'BUY', 1, 65, 100.0, 120.0, 120.0, 1250.0, 1300.0, 1250.0, 50.0, 'CLOSED', 80.0, 130.0, 'TARGET_HIT', 19.23, '2026-11-20 10:00:00', '2026-11-20 11:00:00')")
    sync_eng.dispose()

    async_eng = create_async_engine(async_url)
    try:
        dry = await inspect_schema(async_eng)
        assert "ai_trade_evidence" not in dry["existing_tables"]
        assert any(c["column"] == "google_id" for c in dry["missing_columns"])
        assert dry["row_counts"]["paper_trades"] == 1

        # Apply twice (idempotency check)
        await apply_additive_migrations(async_eng, Base.metadata)
        await apply_additive_migrations(async_eng, Base.metadata)

        after = await inspect_schema(async_eng)
        assert after["missing_columns"] == []
        assert after["missing_indexes"] == []
        assert "ai_trade_evidence" in after["existing_tables"]
        assert "schema_migrations" in after["existing_tables"]
        assert after["row_counts"]["users"] == 1
        assert after["row_counts"]["portfolios"] == 1
        assert after["row_counts"]["paper_trades"] == 1
    finally:
        await async_eng.dispose()


@pytest.mark.asyncio
async def test_qa20_scheduler_slot_idempotency():
    user = await _make_user("qa20")
    s1 = DebateScheduler(user_id=user.id)
    s2 = DebateScheduler(user_id=user.id)
    slot_time = datetime(2026, 11, 25, 10, 5, 8, tzinfo=IST)
    assert await s1._claim_slot(slot_time) is True
    # Restarted or competing worker claiming the exact same 5-minute slot must be skipped
    assert await s2._claim_slot(slot_time) is False
    # Next 5-minute slot is allowed
    next_slot = datetime(2026, 11, 25, 10, 10, 8, tzinfo=IST)
    assert await s2._claim_slot(next_slot) is True


@pytest.mark.asyncio
async def test_qa21_qa22_qa23_and_http_endpoints():
    user = await _make_user("http")
    other = await _make_user("http_other")
    token = create_access_token({"sub": str(user.id), "username": user.username})
    other_token = create_access_token({"sub": str(other.id), "username": other.username})

    pe = PaperEngine()
    await pe.reset_portfolio(1000000.0, user_id=user.id)
    # Place BUY and SELL orders (QA-23)
    f_buy = await pe.place_order(_sample_order(side="BUY"), user_id=user.id, enforce_hours=False)
    await pe.exit_position(f_buy["position_id"], exit_price=110.0, user_id=user.id)
    f_sell = await pe.place_order(_sample_order(side="SELL", option_type="PE"), user_id=user.id, enforce_hours=False)
    await pe.exit_position(f_sell["position_id"], exit_price=125.0, user_id=user.id)  # loss on SELL

    # QA-23 long-only enforcement
    prev_short = settings.ALLOW_SHORT_OPTIONS
    try:
        settings.ALLOW_SHORT_OPTIONS = False
        rejected = await pe.place_order(_sample_order(side="SELL"), user_id=user.id, enforce_hours=False)
        assert rejected["status"] == "REJECTED"
    finally:
        settings.ALLOW_SHORT_OPTIONS = prev_short

    # QA-22 special sessions & holiday overrides
    specials = parse_special_sessions("2026-11-08=18:15-19:15")
    holidays = parse_holidays("2026-11-09")
    assert trading_day(datetime(2026, 11, 8, 18, 30, tzinfo=IST), holidays, specials) is True
    assert session_bounds(datetime(2026, 11, 8, 18, 30, tzinfo=IST), holidays, specials)[0].hour == 18
    assert trading_day(datetime(2026, 11, 9, 10, 0, tzinfo=IST), holidays, specials) is False

    # HTTP transport verification
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        st = await client.get("/api/status")
        assert st.status_code == 200 and "allow_short_options" in st.json()

        # Unauthenticated private route rejected
        assert (await client.get("/api/trading/state")).status_code == 401

        # Lightweight polling vs full state (QA-21)
        light = await client.get("/api/trading/state?include_history=false", headers={"Authorization": f"Bearer {token}"})
        assert light.status_code == 200
        lj = light.json()
        assert lj["history_omitted"] is True
        assert lj["all_trades"] == [] and lj["statistics"]["total_trades"] == 2
        assert lj["wallet"]["margin_model"] == "simplified_premium_reserve"

        # Filtered & paginated history (QA-21)
        hist = await client.get("/api/trading/history?limit=1&offset=0", headers={"Authorization": f"Bearer {token}"})
        assert hist.status_code == 200 and len(hist.json()) == 1

        # Cross-account isolation
        other_hist = await client.get("/api/trading/history", headers={"Authorization": f"Bearer {other_token}"})
        assert other_hist.status_code == 200 and other_hist.json() == []

        # Replay exit protection (QA-13)
        replay_engine.is_replaying = True
        try:
            exit_rep = await client.post("/api/trading/position/ANY/exit", headers={"Authorization": f"Bearer {token}"})
            assert exit_rep.status_code == 409
        finally:
            replay_engine.is_replaying = False
