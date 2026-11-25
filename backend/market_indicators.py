"""Pure indicator computations for ordered OHLC candles."""
from datetime import datetime, time
from zoneinfo import ZoneInfo
import math
IST = ZoneInfo('Asia/Kolkata')


def prior_session_cpr(candles, now):
    days = {}
    for c in candles:
        try:
            t = datetime.fromtimestamp(float(c['time']), IST)
            h, l, close = map(float, (c['high'], c['low'], c['close']))
            if not all(math.isfinite(x) and x > 0 for x in (h, l, close)) or not l <= close <= h:
                continue
            if t.date() < now.astimezone(IST).date() and time(9,15) <= t.time() < time(15,30):
                days.setdefault(t.date(), {})[t] = (h,l,close)
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            continue
    if not days:
        return None
    day = days[max(days)]
    times = sorted(day)
    # Require full 5-minute session before calling this previous-day OHLC.
    if len(times) != 75 or times[0].time() != time(9,15) or times[-1].time() != time(15,25):
        return None
    if any((b-a).total_seconds() != 300 for a,b in zip(times,times[1:])):
        return None
    high = max(v[0] for v in day.values()); low = min(v[1] for v in day.values()); close = day[times[-1]][2]
    pivot = (high + low + close) / 3
    a = (high + low)/2; b = 2*pivot - a
    bottom, top = sorted((a,b))
    return dict(cpr_pivot=round(pivot,2), cpr_bc=round(bottom,2), cpr_tc=round(top,2),
                cpr_width_type='NARROW_TRENDING' if (top-bottom)/close*100 < .35 else 'WIDE_RANGEBOUND')


def supertrend(candles, period=10, multiplier=3.0):
    if len(candles) < period + 1:
        return None
    try:
        rows = [tuple(float(c[k]) for k in ('high','low','close')) for c in candles]
    except (KeyError, ValueError, TypeError):
        return None
    if not all(math.isfinite(x) and x > 0 for row in rows for x in row) or any(not l <= c <= h for h,l,c in rows):
        return None
    tr = [rows[0][0] - rows[0][1]]
    for i, (h,l,c) in enumerate(rows[1:], 1):
        pc = rows[i-1][2]; tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    atr = sum(tr[:period])/period
    upper = lower = None
    bullish = False
    for i in range(period-1, len(rows)):
        h,l,c = rows[i]
        if i >= period: atr = (atr*(period-1)+tr[i])/period
        mid=(h+l)/2; u=mid+multiplier*atr; d=mid-multiplier*atr
        if upper is None:
            upper, lower = u,d
        else:
            pc=rows[i-1][2]
            upper = u if u < upper or pc > upper else upper
            lower = d if d > lower or pc < lower else lower
            bullish = c >= lower if bullish else c > upper
    return dict(supertrend_direction='BULLISH' if bullish else 'BEARISH', supertrend_value=round(lower if bullish else upper,2))
