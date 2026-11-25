"""Operator-supplied exchange closure dates and optional special sessions; no implied official calendar feed."""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')


def parse_holidays(value):
    dates = set()
    for raw in str(value or '').split(','):
        raw = raw.strip()
        if raw:
            d = date.fromisoformat(raw)
            if d.isoformat() != raw:
                raise ValueError('Use YYYY-MM-DD exchange closure dates')
            dates.add(d)
    return dates


def parse_special_sessions(value):
    """Parse 'YYYY-MM-DD=HH:MM-HH:MM,...' optional special sessions (e.g., Muhurat)."""
    sessions = {}
    for raw in str(value or '').split(','):
        raw = raw.strip()
        if not raw:
            continue
        if '=' not in raw or '-' not in raw.split('=', 1)[1]:
            raise ValueError('Use YYYY-MM-DD=HH:MM-HH:MM format for special sessions')
        day_s, span = raw.split('=', 1)
        start_s, end_s = span.split('-', 1)
        d = date.fromisoformat(day_s.strip())
        if d.isoformat() != day_s.strip():
            raise ValueError('Use YYYY-MM-DD date in special sessions')
        st = time.fromisoformat(start_s.strip())
        et = time.fromisoformat(end_s.strip())
        if not st < et:
            raise ValueError('Special session start must precede end')
        sessions[d] = (st, et)
    return sessions


def trading_day(now, holidays, special_sessions=None):
    day = now.astimezone(IST).date() if isinstance(now, datetime) else now
    if day in holidays:
        return False
    if special_sessions and day in special_sessions:
        return True
    return day.weekday() < 5


def session_bounds(now, holidays, special_sessions=None, default_open=time(9, 15), default_close=time(15, 30)):
    day = now.astimezone(IST).date() if isinstance(now, datetime) else now
    if day in holidays:
        return None
    if special_sessions and day in special_sessions:
        return special_sessions[day]
    if day.weekday() >= 5:
        return None
    return default_open, default_close
