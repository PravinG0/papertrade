"""Offline memory and guardrail regression tests (no credentials or DB required)."""
from datetime import datetime, timedelta
import json
from adaptive_memory import (IST, HEADER, build_memory, execution_rejection,
                             prompt_with_memory, regime, trend_rejection, session_price_reference)

NOW = datetime(2026, 11, 25, 11, 30, tzinfo=IST)
SNAP = dict(symbol='NIFTY', spot_price=25250, day_open=25000, vwap=25100, session_reference='VWAP')


def report(day, lesson, reason, **extra):
    return dict(date=day, total_trades=2, raw_analysis=json.dumps(dict(
        key_lessons_learned=[lesson], stop_loss_analysis=[dict(symbol='NIFTY25000PE', failure_reasons=reason)])), **extra)


def trade(id, offset=5, **extra):
    return dict(id=id, underlying='NIFTY', option_type='PE', strike=25000, side='BUY',
                created_at=(NOW-timedelta(minutes=45)).isoformat(), closed_at=(NOW-timedelta(minutes=offset)).isoformat(),
                status='CLOSED', exit_reason='STOP_LOSS_HIT', realized_pnl=-200, total_charges=50, **extra)


def test_memory_report_shapes_completion_and_window():
    reports = [report('2026-11-24', 'avoid rapid re-entry', 'weak trend'),
               report('2026-11-23', 'avoid rapid re-entry', ['weak trend']),
               report('2026-11-25', 'TODAY_PARTIAL', 'ignore'),
               report('2026-11-22', 'OPEN_POSITION', 'ignore', open_trades_count=1),
               report('2026-11-21', 'MIDDAY_ONLY', 'ignore', updated_at='2026-11-21 11:00:00'),
               report('2026-11-20', 'OUTSIDE_WINDOW', 'ignore')]
    memory = build_memory(reports, [], SNAP, NOW, short_days=2)
    assert HEADER in memory and 'avoid rapid re-entry" (mentions=2)' in memory
    assert 'weak trend" (mentions=2)' in memory
    assert not any(s in memory for s in ('TODAY_PARTIAL', 'OPEN_POSITION', 'MIDDAY_ONLY', 'OUTSIDE_WINDOW'))
    assert memory in prompt_with_memory('bull rules', memory)
    assert 'untrusted evidence' in prompt_with_memory('judge rules', memory)


def test_memory_uses_net_pnl_and_matching_regime():
    t = trade('1', entry_snapshot=SNAP, judge_confidence=8)
    t.update(closed_at='2026-11-24 14:30:00')
    m = build_memory([], [t], SNAP, NOW)
    assert 'n=1; net P&L INR -200.00' in m
    assert 'BUY PE: n=1' in m and 'Confidence 7-8/10: n=1' in m


def test_no_memory_and_malformed_json():
    m = build_memory([dict(date='2026-11-24', total_trades=2, raw_analysis='broken')], [], SNAP, NOW)
    assert 'No completed prior report lessons yet.' in m
    assert 'n=0 (insufficient evidence)' in m


def test_trend_symmetric_and_unknown():
    assert regime(SNAP) == 'STRONG_BULLISH'
    assert trend_rejection(SNAP, 'PE') and not trend_rejection(SNAP, 'CE')
    down = {**SNAP, 'spot_price': 24750, 'vwap': 24900}
    assert trend_rejection(down, 'CE') and not trend_rejection(down, 'PE')
    assert trend_rejection({**SNAP, 'session_reference': 'UNKNOWN'}, 'CE')


def test_cooldown_exact_strike_option_type_and_boundary():
    stopped = trade('1', 29)
    assert 'cooldown' in execution_rejection([stopped], set(), NOW, 'NIFTY', 25000, 'PE')
    assert execution_rejection([stopped], set(), NOW, 'NIFTY', 25000, 'CE') is None
    assert execution_rejection([stopped], set(), NOW, 'NIFTY', 25050, 'PE') is None
    assert execution_rejection([trade('2', 30)], set(), NOW, 'NIFTY', 25000, 'PE') is None
    assert execution_rejection([stopped], set(), NOW, 'BANKNIFTY', 25000, 'PE') is None


def test_daily_cap_only_auto_fills_all_indices_ist():
    fills = [trade(str(i), 31) for i in range(5)]
    assert 'cap reached' in execution_rejection(fills, {str(i) for i in range(5)}, NOW, 'NIFTY', 25050, 'PE')
    assert execution_rejection(fills, {'0','1','2','3'}, NOW, 'NIFTY', 25050, 'PE') is None
    fills[4]['created_at'] = '2026-11-24T18:00:00Z'  # 23:30 IST yesterday
    assert execution_rejection(fills, {str(i) for i in range(5)}, NOW, 'NIFTY', 25050, 'PE') is None
    fills[4]['created_at'] = '2026-11-24T19:00:00Z'  # 00:30 IST today
    assert 'cap reached' in execution_rejection(fills, {str(i) for i in range(5)}, NOW, 'NIFTY', 25050, 'PE')


def test_session_reference_excludes_previous_days_and_marks_proxy():
    def candle(day, hour, minute, price, volume):
        dt = datetime(2026,11,day,hour,minute,tzinfo=IST)
        return dict(time=dt.timestamp(), open=price, high=price, low=price, close=price, volume=volume)
    rows = [candle(24,15,25,100,5000), candle(25,9,15,200,100), candle(25,11,30,220,300)]
    assert session_price_reference(rows,NOW) == (200,215,'VWAP')
    rows[-1]['volume'] = 0
    assert session_price_reference(rows,NOW) == (200,210,'TYPICAL_PRICE_PROXY')
    assert session_price_reference(rows[:1],NOW) == (None,None,'UNKNOWN')
