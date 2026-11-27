from datetime import datetime, timedelta, time
import pytest
from quant_engine import (IST, FRAMES, expected_starts, validated_bars, frame_features,
    validate_direction, option_validation, calibration_summary, estimate_option_greeks)
from session_calendar import session_bounds
from research_backtest import run_research, simulate_candidate
from research_ml import temporal_partitions

NOW=datetime(2026,11,25,11,32,tzinfo=IST)
BOUNDS=lambda day: session_bounds(day,set())

def candles(frame='5m', count=100, sign=1):
    keys=expected_starts(NOW,frame,BOUNDS,count)
    result=[]
    for i,k in enumerate(keys):
        t=datetime.combine(k,time(9,15),IST).timestamp() if frame=='1d' else k
        p=25000+sign*i*2
        result.append(dict(time=t,open=p,high=p+2,low=p-2,close=p,volume=0))
    return result

@pytest.mark.parametrize('frame',FRAMES)
def test_completed_session_bars(frame):
    rows=candles(frame)
    assert len(validated_bars(rows,NOW,frame,BOUNDS))==100
    assert frame_features(rows)['direction']=='BULLISH'

@pytest.mark.parametrize('count',[0,1,19,20,49])
def test_ema50_minimum(count):
    with pytest.raises(ValueError,match='minimum 50'): validated_bars(candles(count=count) if count else [],NOW,'5m',BOUNDS)

def test_gap_near_tail():
    rows=candles(); del rows[-10]
    with pytest.raises(ValueError): validated_bars(rows,NOW,'5m',BOUNDS)

def test_duplicate_near_tail():
    rows=candles(); rows.append(rows[-1].copy())
    with pytest.raises(ValueError): validated_bars(rows,NOW,'5m',BOUNDS)

def test_partial_and_future_candles_ignored():
    rows=candles(); partial={**rows[-1],'time':rows[-1]['time']+300,'close':999999}
    assert validated_bars(rows+[partial],NOW,'5m',BOUNDS)[-1]==rows[-1]

def test_stale_data_with_fresh_cache_rejected():
    with pytest.raises(ValueError): validated_bars(candles()[:-1],NOW,'5m',BOUNDS)

def test_malformed_ohlc():
    rows=candles(); rows[-1]['high']=1
    with pytest.raises(ValueError): validated_bars(rows,NOW,'5m',BOUNDS)

def test_holiday_special_session():
    dt=datetime(2026,11,22,19,2,tzinfo=IST)
    bounds=lambda day:session_bounds(day,set(),{dt.date():(time(18,0),time(19,0))})
    assert expected_starts(dt,'1h',bounds,1)==[int(datetime(2026,11,22,18,0,tzinfo=IST).timestamp())]

def test_daily_uses_previous_completed_session():
    assert expected_starts(NOW,'1d',BOUNDS,1)[0]<NOW.date()

def test_bear_and_flat_regime():
    assert frame_features(candles(sign=-1))['direction']=='BEARISH'
    assert frame_features(candles(sign=0))['direction']=='NEUTRAL'

def snapshot(direction='BULLISH'):
    return dict(timeframes={f:{'direction':direction} for f in FRAMES},data_status='cached',spot_fresh=True,session_active=True,
       spot_price=25100 if direction=='BULLISH' else 24900,vwap=25000,session_reference='TYPICAL_PRICE_PROXY',supertrend_direction=direction)

@pytest.mark.parametrize('direction,verdict',[('BULLISH','BUY CE'),('BEARISH','BUY PE')])
def test_direction_pass(direction,verdict):
    assert validate_direction(snapshot(direction),verdict,8)['eligible']

@pytest.mark.parametrize('frame',FRAMES)
def test_missing_frame_blocks(frame):
    snap=snapshot(); del snap['timeframes'][frame]
    assert not validate_direction(snap,'BUY CE',10)['eligible']

@pytest.mark.parametrize('field,value',[('spot_fresh',False),('data_status','simulated'),('session_reference','UNKNOWN'),('supertrend_direction','BEARISH')])
def test_direction_fail_closed(field,value):
    snap=snapshot();snap[field]=value
    assert not validate_direction(snap,'BUY CE',10)['eligible']

def test_low_confidence_and_no_trade():
    assert not validate_direction(snapshot(),'BUY CE',7)['eligible']
    assert not validate_direction(snapshot(),'NO_TRADE',10)['eligible']

def quote(**kw):return dict(bid=99.8,ask=100,ltp=100,exchange_timestamp=NOW.isoformat(),**kw)
def fee(buy,sell):return 40

def test_option_fees_and_spread():
    r=option_validation(quote(),100,95,115,65,NOW,fee)
    assert r['eligible'] and r['metrics']['net_rr']>1.5
    assert not option_validation(quote(),100,95,106,65,NOW,fee)['eligible']

@pytest.mark.parametrize('overrides',[{'bid':0},{'bid':101},{'bid':90},{'exchange_timestamp':None},{'exchange_timestamp':(NOW-timedelta(minutes=1)).isoformat()},{'exchange_timestamp':(NOW+timedelta(seconds=1)).isoformat()}])
def test_option_bad_quotes(overrides):
    assert not option_validation({**quote(),**overrides},100,95,115,65,NOW,fee)['eligible']

@pytest.mark.parametrize('entry,sl,target,qty',[(100,105,120,65),(float('nan'),95,120,65),(100,95,120,0),('bad',95,120,65)])
def test_option_bad_geometry(entry,sl,target,qty):
    assert not option_validation(quote(),entry,sl,target,qty,NOW,fee)['eligible']

def test_confidence_empirical_sample():
    rows=[{'verified':True,'confidence':9,'net_pnl':10}]*20+[{'verified':True,'confidence':9,'net_pnl':-10}]*10
    rows+=[{'verified':False,'confidence':9,'net_pnl':9999}]
    r=calibration_summary(rows)[-1]
    assert r['n']==30 and r['wins']==20 and r['sufficient_sample'] and r['wilson95'][0]<2/3<r['wilson95'][1]
    assert calibration_summary([])[0]['observed_win_rate'] is None

def candidate(**kw):
    c=dict(id='a',decision_at=NOW.isoformat(),available_at=NOW.isoformat(),expiry_at=NOW.replace(hour=15,minute=30).isoformat(),contract='NIFTY-EXACT-CE',verdict='BUY CE',quantity=65,reference_entry=100,stop=95,target=110,max_bars=2,quant_eligible=True)
    c.update(kw);return c

def bar(minutes=3,**kw):
    b=dict(timestamp=(NOW+timedelta(minutes=minutes)).isoformat(),open=100,high=115,low=90,close=100);b.update(kw);return b

def test_backtest_stop_first_and_next_candle():
    r=simulate_candidate(candidate(),[bar(-2),bar(3)],slippage_bps=0)
    assert r['exit_reason']=='STOP' and r['entry_at']==(NOW+timedelta(minutes=3)).isoformat() and r['net_pnl']<0

def test_backtest_no_future_reconstruction_and_gaps():
    assert simulate_candidate(candidate(),[bar(-2)])['status']=='unresolved'
    assert simulate_candidate(candidate(),[bar(3,high=101,low=99),bar(13,high=101,low=99)])['status']=='unresolved'

def test_research_wallets_separate():
    data=dict(provenance='historical_contract_ohlc',candidates=[candidate(quant_eligible=False)],bars_by_contract={'NIFTY-EXACT-CE':[bar(3)]})
    r=run_research(data)
    assert r['champion']['trades']==1 and r['challenger']['trades']==0 and r['resolved_candidates']==1
    assert r['challenger']['ending_capital']==1000000
    with pytest.raises(ValueError):run_research({**data,'provenance':'simulated'})

def test_ml_refuses_small_dataset():
    with pytest.raises(ValueError):temporal_partitions([])

def test_ml_partitions_purge_label_leakage():
    from research_ml import FEATURES
    rows=[]
    for d in range(40):
        for i in range(10):
            dt=NOW+timedelta(days=d,minutes=i)
            end=dt+timedelta(minutes=5)
            rows.append(dict(candidate=dict(decision_at=dt.isoformat(),available_at=dt.isoformat(),features_at=dt.isoformat(),features={k:float(i) for k in FEATURES}),outcome=dict(status='resolved',outcome_at=end.isoformat(),net_pnl=1 if i%2 else -1)))
    train,cal,test=temporal_partitions(rows)
    assert max(r[1] for r in train)<min(r[0] for r in cal)
    assert max(r[1] for r in cal)<min(r[0] for r in test)


def test_full_session_reference_rejects_partial_session():
    from quant_engine import complete_session_reference
    rows=candles(count=100)
    assert complete_session_reference(rows,NOW,BOUNDS)[2]=='TYPICAL_PRICE_PROXY'
    assert complete_session_reference(rows[-10:],NOW,BOUNDS)==(None,None,'UNKNOWN')


def test_market_closed_blocks_candidate():
    snap=snapshot(); snap['session_active']=False
    assert not validate_direction(snap,'BUY CE',10)['eligible']


def test_wallet_fill_bar_boundary():
    from quant_engine import snapshot_frames_current
    snap={'timeframes':{frame:frame_features(candles(frame)) for frame in FRAMES}}
    assert snapshot_frames_current(snap,NOW,BOUNDS)
    assert not snapshot_frames_current(snap,NOW+timedelta(minutes=1),BOUNDS)


def test_ml_research_pipeline_on_synthetic_fixture():
    pytest.importorskip('sklearn')
    from research_ml import FEATURES,evaluate_ml
    rows=[]
    for d in range(40):
        for i in range(10):
            dt=NOW+timedelta(days=d,minutes=i)
            rows.append(dict(candidate=dict(decision_at=dt.isoformat(),available_at=dt.isoformat(),features_at=dt.isoformat(),features={k:float(i) for k in FEATURES}),outcome=dict(status='resolved',outcome_at=(dt+timedelta(minutes=5)).isoformat(),net_pnl=1 if i%2 else -1)))
    metrics=evaluate_ml(rows)
    assert metrics['status']=='research_only' and 0<=metrics['calibrated_metrics']['brier']<=1
    assert metrics['unseen_test']>=30
