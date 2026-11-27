"""Deterministic, point-in-time research filters. Scores are rules, not probabilities."""
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import math
from adaptive_memory import number, parse_time
from market_indicators import supertrend

IST = ZoneInfo('Asia/Kolkata')
FRAMES = {'1m': 1, '5m': 5, '15m': 15, '1h': 60, '1d': 1440}
VERSION = 'quant-v1'


def expected_starts(now, frame, bounds, count=50):
    """Broker candles assumed start-labelled, aligned to exchange session open.
    Daily bars are keyed by local date. Only completed bars are included.
    The last shortened intraday bar is complete at session close.
    """
    now = now.astimezone(IST)
    step = timedelta(minutes=FRAMES[frame]); result = []
    for offset in range(400):
        day = now.date() - timedelta(days=offset)
        span = bounds(day)
        if not span:
            continue
        start, end = (datetime.combine(day, t, IST) for t in span)
        if frame == '1d':
            if end <= now:
                result.append(day)
        else:
            rows = []
            while start < end and min(start + step, end) <= now:
                rows.append(int(start.timestamp()))
                start += step
            result.extend(reversed(rows))
        if len(result) >= count:
            break
    return list(reversed(result[:count]))


def validated_bars(rows, now, frame, bounds, minimum=50):
    """Return a contiguous tail, rejecting gaps, future/partial and malformed bars."""
    expected = expected_starts(now, frame, bounds, max(200, minimum))
    keys = set(expected); actual = {}; duplicates = set()
    for row in rows or []:
        try:
            dt = datetime.fromtimestamp(float(row['time']), IST)
            k = dt.date() if frame == '1d' else int(dt.timestamp())
            if k not in keys or dt > now:
                continue
            o,h,l,c = (number(row.get(x)) for x in ('open','high','low','close'))
            v = number(row.get('volume', 0))
            if any(x is None or x <= 0 for x in (o,h,l,c)) or v is None or v < 0 or l > min(o,c) or h < max(o,c):
                continue
            if k in actual:
                duplicates.add(k)
            actual[k] = dict(row, open=o, high=h, low=l, close=c, volume=v)
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            continue
    tail = []
    for k in reversed(expected):
        if k not in actual or k in duplicates:
            break
        tail.append(actual[k])
    tail.reverse()
    if len(tail) >= minimum:
        return tail

    # Allow isolated prior-day broker gaps / unlisted past holidays ONLY when the recent
    # live tail is strictly contiguous (all of today's session or >=12 bars intraday, >=5 for 1d)
    # and >=85% of expected history is intact with at least `minimum` valid bars.
    min_contiguous = 5 if frame == '1d' else 12
    today = now.astimezone(IST).date()
    today_expected_count = sum(
        1 for k in expected
        if (k == today if frame == '1d' else datetime.fromtimestamp(k, IST).date() == today)
    )
    required_contiguous = max(min_contiguous, today_expected_count)
    if len(tail) >= min(len(expected), required_contiguous):
        clean = [actual[k] for k in expected if k in actual and k not in duplicates]
        if len(clean) >= minimum and len(clean) >= int(0.85 * len(expected)):
            return clean

    raise ValueError(f'{frame}: only {len(tail)} consecutive completed candles; minimum {minimum} required (stale, gaps or insufficient warm-up).')


def ema(values, n):
    if len(values) < n:
        raise ValueError('Insufficient EMA warm-up')
    value = sum(values[:n])/n
    alpha = 2/(n+1)
    for x in values[n:]: value += alpha*(x-value)
    return value


def frame_features(rows):
    c = [r['close'] for r in rows]; e20 = ema(c,20); e50 = ema(c,50)
    tr = [rows[0]['high']-rows[0]['low']] + [max(r['high']-r['low'], abs(r['high']-p['close']), abs(r['low']-p['close'])) for p,r in zip(rows, rows[1:])]
    atr = sum(tr[:14])/14
    for x in tr[14:]: atr = (atr*13+x)/14
    spread = (e20-e50)/atr if atr>0 else 0
    direction = 'BULLISH' if c[-1]>e20>e50 and spread>=.15 else 'BEARISH' if c[-1]<e20<e50 and spread<=-.15 else 'NEUTRAL'
    st = supertrend(rows) or {}
    return {'direction':direction,'ema20':round(e20,4),'ema50':round(e50,4),'close':c[-1], 'atr_pct':round(100*atr/c[-1],4),'separation_atr':round(spread,4),'supertrend':st.get('supertrend_direction','UNKNOWN'),'count':len(rows),'last_start':rows[-1]['time']}


def market_regime(frames):
    directions = [frames.get(k,{}).get('direction','UNKNOWN') for k in ('1h','15m','5m')]
    if 'UNKNOWN' in directions: return 'UNKNOWN'
    if all(d=='BULLISH' for d in directions): return 'BULL_TREND'
    if all(d=='BEARISH' for d in directions): return 'BEAR_TREND'
    return 'RANGE_OR_TRANSITION'


def validate_direction(snapshot, verdict, confidence, min_confidence=8):
    frames = snapshot.get('timeframes') or {}; reasons=[]; checks={}
    if verdict not in ('BUY CE','BUY PE'):
        return {'version':VERSION,'eligible':False,'reasons':['Judge returned NO TRADE or invalid verdict.'],'checks':{},'regime':market_regime(frames)}
    desired = 'BULLISH' if verdict=='BUY CE' else 'BEARISH'
    opposite = 'BEARISH' if desired=='BULLISH' else 'BULLISH'
    for frame in FRAMES:
        direction = frames.get(frame,{}).get('direction','UNKNOWN')
        # Daily can be neutral, but not directly opposing. Intraday alignment mandatory.
        passed = direction in ((desired,'NEUTRAL') if frame=='1d' else (desired,))
        checks[frame]=passed
        if not passed: reasons.append(f'{frame} direction {direction} does not support {verdict}.')
    score = number(confidence)
    checks['conviction'] = score is not None and min_confidence <= score <= 10
    if not checks['conviction']: reasons.append('Judge conviction below configured minimum (not a probability).')
    checks['data'] = snapshot.get('data_status') in ('live','cached') and snapshot.get('spot_fresh') is True and snapshot.get('session_active') is True
    if not checks['data']: reasons.append('Validated live spot/candle data and an active exchange session required.')
    spot, ref = number(snapshot.get('spot_price')), number(snapshot.get('vwap'))
    checks['session_reference'] = bool(spot and ref and snapshot.get('session_reference') in ('VWAP','TYPICAL_PRICE_PROXY') and (spot>ref if desired=='BULLISH' else spot<ref))
    if not checks['session_reference']: reasons.append('Session price reference does not confirm direction.')
    checks['supertrend'] = snapshot.get('supertrend_direction')==desired
    if not checks['supertrend']: reasons.append('5m Supertrend does not confirm direction.')
    return {'version':VERSION,'eligible':not reasons,'reasons':reasons,'checks':checks,'regime':market_regime(frames)}


def option_validation(quote, entry, stop, target, quantity, now, fee_fn, min_rr=1.5, max_spread_pct=2., max_age=30.):
    """Check executable spread, exchange time and fee-adjusted payoff; not a fill guarantee."""
    bid,ask,ltp = (number(quote.get(k)) for k in ('bid','ask','ltp'))
    entry,stop,target,quantity = (number(v) for v in (entry,stop,target,quantity))
    stamp = parse_time(quote.get('exchange_timestamp'))
    reasons=[]; metrics={}
    if stamp is None or not 0 <= (now-stamp).total_seconds() <= max_age: reasons.append('Missing/stale exchange option quote timestamp.')
    if not all(v is not None and v>0 for v in (bid,ask,ltp)) or ask<bid:
        reasons.append('Valid two-sided option quote required.')
    else:
        spread=100*(ask-bid)/((ask+bid)/2); metrics['spread_pct']=round(spread,3)
        if spread>max_spread_pct: reasons.append('Option bid/ask spread above configured maximum.')
    if not all(v is not None for v in (entry,stop,target,quantity)) or not 0<stop<entry<target or quantity<=0:
        reasons.append('Invalid option risk geometry.')
    elif bid is not None and ask is not None and 0<bid<=ask:
        # Approximate one spread of slippage for exits; fees use existing round-trip model.
        loss_exit=max(.05,stop-(ask-bid)); win_exit=max(.05,target-(ask-bid))
        loss=(entry-loss_exit)*quantity+fee_fn(entry*quantity,loss_exit*quantity)
        gain=(win_exit-entry)*quantity-fee_fn(entry*quantity,win_exit*quantity)
        ratio=gain/loss if loss>0 else 0
        metrics.update(net_target=round(gain,2),net_risk=round(loss,2),net_rr=round(ratio,4))
        if ratio<min_rr: reasons.append('Estimated reward/risk after spread and fees below threshold.')
    return {'eligible':not reasons,'reasons':reasons,'metrics':metrics}


def calibration_summary(rows, min_samples=30):
    """Descriptive observed win rates for completed, provenance-backed fills only.
    Wilson interval expresses sampling uncertainty, not prospective probability.
    """
    out=[]
    for low,high in ((1,6),(7,8),(9,10)):
        cohort=[r for r in rows if r.get('verified') is True and number(r.get('net_pnl')) is not None and low <= (number(r.get('confidence')) or 0) <= high]
        n=len(cohort); wins=sum(number(r['net_pnl'])>0 for r in cohort); p=wins/n if n else None
        interval=None
        if n:
            z=1.96; den=1+z*z/n; center=(p+z*z/(2*n))/den; half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
            interval=[round(max(0,center-half),4),round(min(1,center+half),4)]
        out.append({'band':f'{low}-{high}','n':n,'wins':wins,'observed_win_rate':round(p,4) if p is not None else None,'wilson95':interval,'sufficient_sample':n>=min_samples})
    return out


def estimate_option_greeks(spot, strike, option_type, expiry, quote, now):
    """Model estimates from a fresh two-sided mid; refuse impossible premiums, no default IV."""
    from greeks import BlackScholesEngine
    try:
        end = datetime.combine(datetime.fromisoformat(expiry).date(), time(15,30), IST)
        t = (end-now).total_seconds()/(365*86400)
        bid, ask = number(quote.get('bid')), number(quote.get('ask'))
        if t<.0001 or not bid or not ask or ask<bid or spot<=0 or strike<=0 or option_type not in ('CE','PE'):
            return {'status':'unavailable'}
        mid = (bid+ask)/2
        lo,hi=.01,3.
        def price(s): return BlackScholesEngine.calculate_price(spot,strike,t,.065,s,option_type)
        if not price(lo)<mid<price(hi): return {'status':'unavailable','reason':'Premium outside model IV bounds'}
        for _ in range(48):
            m=(lo+hi)/2
            if price(m)<mid: lo=m
            else: hi=m
        iv=(lo+hi)/2
        g=BlackScholesEngine.calculate_greeks(spot,strike,t,iv=iv,option_type=option_type)
        return {'status':'estimated','basis':'Black-Scholes midpoint, fixed 6.5% assumed risk-free rate',**g}
    except (ValueError,TypeError,OverflowError,ZeroDivisionError):
        return {'status':'unavailable'}


def complete_session_reference(rows, now, bounds):
    """A partial session is never reported as full-session VWAP or opening price."""
    session=bounds(now.date())
    if not session: return None,None,'UNKNOWN'
    start,end=(datetime.combine(now.date(),t,IST) for t in session)
    if not start<=now<=end: return None,None,'UNKNOWN'
    expected={k for k in expected_starts(now,'5m',bounds,200) if datetime.fromtimestamp(k,IST).date()==now.date()}
    current=[r for r in rows if datetime.fromtimestamp(r['time'],IST).date()==now.date()]
    if not expected or {r['time'] for r in current} != expected: return None,None,'UNKNOWN'
    # Existing session_price_reference uses the normal 09:15 session. Explicitly support special sessions here.
    current.sort(key=lambda r:r['time'])
    typical=[(r['high']+r['low']+r['close'])/3 for r in current]; volumes=[r['volume'] for r in current]
    if all(v>0 for v in volumes): return current[0]['open'],sum(p*v for p,v in zip(typical,volumes))/sum(volumes),'VWAP'
    return current[0]['open'],sum(typical)/len(typical),'TYPICAL_PRICE_PROXY'


def snapshot_frames_current(snapshot, now, bounds):
    """Recheck timestamps under the wallet lock without network access."""
    for frame in FRAMES:
        start=(snapshot.get('timeframes') or {}).get(frame,{}).get('last_start')
        expected=expected_starts(now,frame,bounds,1)
        if start is None or not expected: return False
        try:
            key=datetime.fromtimestamp(float(start),IST).date() if frame=='1d' else int(start)
        except (ValueError,TypeError,OverflowError,OSError): return False
        if key!=expected[0]: return False
    return True
