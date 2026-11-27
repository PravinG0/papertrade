"""Account-scoped SQLAlchemy persistence for adaptive memory and automatic trade guards."""
from datetime import datetime, timedelta
from sqlalchemy import select, func, or_
from adaptive_memory import IST, build_memory, execution_rejection, object_json, trend_rejection
from config import settings
from quant_engine import calibration_summary
from database import (AppKVModel, DailyReportModel, PaperTradeModel, DebateRecordModel,
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
                t['verified_quant'] = bool(evidence.auto_executed and t['entry_snapshot'].get('quant_version') == 'quant-v1')
            trades.append(t)
    from adaptive_memory import parse_time, summarize_trades
    eligible = [t for t in trades if t.get('verified_quant') and t.get('exit_reason') not in ('WALLET_RESET','REPLAY_STOPPED') and (end := parse_time(t.get('closed_at'))) and end <= now]
    days = sorted({parse_time(t['closed_at']).date() for t in eligible if parse_time(t['closed_at']).date()<now.date()}, reverse=True)[:settings.MEMORY_EXTENDED_DAYS]
    extended = [t for t in eligible if parse_time(t['closed_at']).date() in days]
    calibration = calibration_summary([dict(verified=True, confidence=t.get('judge_confidence'), net_pnl=t.get('realized_pnl')) for t in extended])
    return build_memory(report_data, trades, snapshot, now, settings.MEMORY_SHORT_DAYS,
                        settings.MEMORY_LONG_DAYS, settings.AUTO_TREND_THRESHOLD_PCT) + (
        '\nExtended verified quantitative-fill memory (up to 90 observed prior trading dates; bounded database sample): '
        + summarize_trades(extended) + '\nObserved confidence bands (not predicted probabilities): ' + str(calibration))


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
    from shadow_engine import DEFAULT_RISK_CONFIG
    risk_row = await db.get(AppKVModel, f'risk-config:{user_id}')
    user_risk = object_json(risk_row.value) if risk_row else {}
    risk_cfg = {**DEFAULT_RISK_CONFIG, **user_risk}
    max_trades = 0 if risk_cfg.get('no_count_limit') else int(
        user_risk['max_daily_trades'] if 'max_daily_trades' in user_risk else settings.AUTO_MAX_DAILY_TRADES
    )
    strike_cd = int(
        user_risk['repeat_strike_cooldown_minutes']
        if 'repeat_strike_cooldown_minutes' in user_risk
        else settings.AUTO_REPEAT_STRIKE_COOLDOWN_MINUTES
    )

    # execution_rejection uses <=0 cap? If max_trades == 0 (no_count_limit), pass large cap so count-limit is bypassed while strike cooldown stays active.
    effective_cap = 999999 if max_trades <= 0 else max_trades
    trade_dicts = [r.to_dict() for r in rows]
    rejection = execution_rejection(trade_dicts, auto_ids, now,
        order['underlying'], order['strike'], order['option_type'], effective_cap, strike_cd)
    if rejection:
        return rejection
    if existing is not None:
        return 'A position in this index is already open.'

    # Dynamic risk-budget checks (daily loss limit, concurrent positions, consecutive loss cooldown)
    today_iso = now.date().isoformat()
    today_closed = [t for t in trade_dicts if t.get('status') == 'CLOSED' and str(t.get('closed_at') or t.get('exit_time') or '').startswith(today_iso)]
    daily_pnl = sum(float(t.get('realized_pnl') or 0) for t in today_closed)
    max_daily_loss = float(risk_cfg.get('max_daily_loss_inr', 0) or 0)
    if max_daily_loss > 0 and daily_pnl <= -max_daily_loss:
        return f'Daily loss limit reached (₹{abs(daily_pnl):.2f} >= ₹{max_daily_loss:.2f}).'

    active_count = (await db.execute(select(func.count(PaperTradeModel.id)).where(
        PaperTradeModel.user_id == user_id, PaperTradeModel.status == 'ACTIVE'))).scalar_one() or 0
    max_conc = int(risk_cfg.get('max_concurrent_positions', 0) or 0)
    if max_conc > 0 and active_count >= max_conc:
        return f'Max concurrent positions ({max_conc}) reached.'

    streak_limit = int(risk_cfg.get('max_consecutive_losses', 0) or 0)
    streak_cd = int(risk_cfg.get('loss_streak_cooldown_minutes', 45) or 0)
    if streak_limit > 0 and streak_cd > 0 and len(today_closed) >= streak_limit:
        ordered = sorted(today_closed, key=lambda t: str(t.get('closed_at') or t.get('exit_time') or ''))
        recent = ordered[-streak_limit:]
        if all(float(t.get('realized_pnl') or 0) < 0 for t in recent):
            last_closed = parse_time(recent[-1].get('closed_at') or recent[-1].get('exit_time'))
            if last_closed and (now - last_closed).total_seconds() < streak_cd * 60:
                return f'Consecutive stop-loss cooldown active ({streak_limit} losses; wait {streak_cd}m).'
    return None
