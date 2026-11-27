"""Account-scoped SQLAlchemy persistence for adaptive memory and automatic trade guards."""
from datetime import datetime, timedelta
from sqlalchemy import select, func, or_
from adaptive_memory import IST, build_memory, execution_rejection, object_json, trend_rejection
from config import settings
from database import (DailyReportModel, PaperTradeModel, DebateRecordModel,
                      AITradeEvidenceModel, async_session_factory)


async def retrieve_memory(user_id, snapshot, now=None):
    now = (now or datetime.now(IST)).astimezone(IST)
    if user_id is None:
        return build_memory([], [], snapshot, now)
    async with async_session_factory() as db:
        date = func.coalesce(func.nullif(DailyReportModel.date, ''), DailyReportModel.report_date)
        reports = (await db.execute(select(DailyReportModel).where(
            DailyReportModel.user_id == user_id, date < now.date().isoformat(),
            DailyReportModel.total_trades > 0).order_by(date.desc(), DailyReportModel.updated_at.desc()).limit(60))).scalars().all()
        known_replay = (await db.execute(select(PaperTradeModel.created_at, PaperTradeModel.closed_at).where(
            PaperTradeModel.user_id == user_id, PaperTradeModel.exit_reason == 'REPLAY_STOPPED'))).all()
        known_replay_days = {str(t)[:10] for row in known_replay for t in row if t}
        report_data = [dict(date=r.date or r.report_date, total_trades=r.total_trades,
                            raw_analysis=r.raw_analysis, ai_analysis_json=r.ai_analysis_json,
                            updated_at=r.updated_at, open_trades_count=r.open_trades_count) for r in reports
                       if (r.date or r.report_date) not in known_replay_days]
        rows = (await db.execute(select(PaperTradeModel, AITradeEvidenceModel).outerjoin(
            AITradeEvidenceModel, AITradeEvidenceModel.position_id == PaperTradeModel.id).where(
            PaperTradeModel.user_id == user_id, PaperTradeModel.underlying == snapshot['symbol'],
            PaperTradeModel.status == 'CLOSED', PaperTradeModel.closed_at.is_not(None),
            or_(PaperTradeModel.exit_reason.is_(None), PaperTradeModel.exit_reason != 'WALLET_RESET')).order_by(PaperTradeModel.closed_at.desc()).limit(2000))).all()
        trades = []
        for row, evidence in rows:
            t = row.to_dict()
            if evidence and evidence.user_id == user_id:
                t['entry_snapshot'] = object_json(evidence.snapshot)
                t['judge_confidence'] = evidence.confidence
            trades.append(t)
    return build_memory(report_data, trades, snapshot, now, settings.MEMORY_SHORT_DAYS,
                        settings.MEMORY_LONG_DAYS, settings.AUTO_TREND_THRESHOLD_PCT)


async def guard_auto_fill(db, user_id, order, now=None):
    """Called inside the paper engine's fill lock, before any wallet changes.

    Counts new durable provenance and older executed debates by their actual fill date.
    SQL errors deliberately propagate: don't auto-fill with unverified risk history.
    """
    if user_id is None:
        return 'Automatic trades require a signed-in account.'
    now = (now or datetime.now(IST)).astimezone(IST)
    # Stored timestamps are canonical naive IST, with a one-day cushion for legacy offsets.
    first_date = (now.date() - timedelta(days=1)).isoformat()
    last_date = (now.date() + timedelta(days=1)).isoformat()
    cutoff = (now - timedelta(minutes=settings.AUTO_REPEAT_STRIKE_COOLDOWN_MINUTES, days=1)).date().isoformat()
    rows = (await db.execute(select(PaperTradeModel).where(
        PaperTradeModel.user_id == user_id, or_(func.substr(PaperTradeModel.created_at, 1, 10).between(first_date, last_date),
        func.substr(PaperTradeModel.closed_at, 1, 10) >= cutoff)))).scalars().all()
    existing = (await db.execute(select(PaperTradeModel.id).where(
        PaperTradeModel.user_id == user_id, PaperTradeModel.underlying == order['underlying'],
        PaperTradeModel.status == 'ACTIVE').limit(1))).scalar_one_or_none()
    ids = [r.id for r in rows]
    auto_ids = set()
    # Join rather than an unbounded IN list, for SQLite and PostgreSQL compatibility.
    if ids:
        new = (await db.execute(select(AITradeEvidenceModel.position_id).join(PaperTradeModel,
            PaperTradeModel.id == AITradeEvidenceModel.position_id).where(
            AITradeEvidenceModel.user_id == user_id, PaperTradeModel.user_id == user_id,
            AITradeEvidenceModel.auto_executed == 1,
            func.substr(PaperTradeModel.created_at, 1, 10).between(first_date, last_date)))).scalars().all()
        auto_ids.update(new)
        legacy = (await db.execute(select(DebateRecordModel).join(PaperTradeModel,
            PaperTradeModel.id == DebateRecordModel.position_id).where(
            DebateRecordModel.user_id == user_id, PaperTradeModel.user_id == user_id,
            DebateRecordModel.executed == 1, func.substr(PaperTradeModel.created_at, 1, 10).between(first_date, last_date)))).scalars().all()
        auto_ids.update(r.position_id for r in legacy if object_json(r.payload).get('auto_executed') is True)
    rejection = execution_rejection([r.to_dict() for r in rows], auto_ids, now,
        order['underlying'], order['strike'], order['option_type'], settings.AUTO_MAX_DAILY_TRADES,
        settings.AUTO_REPEAT_STRIKE_COOLDOWN_MINUTES)
    return rejection or ('A position in this index is already open.' if existing is not None else None)
