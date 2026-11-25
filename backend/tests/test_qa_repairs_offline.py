"""Pure regression tests for QA repair boundaries; no live connections."""
import json
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import pytest
from config import compute_clamped_sl_target, Settings
from greeks import calculate_pcr, calculate_strategy_payoff
from market_indicators import prior_session_cpr, supertrend
from session_calendar import parse_holidays, trading_day
from verdict_validation import validated_verdict
from wallet_accounting import reconciliation_preview
from adaptive_memory import build_memory

IST=ZoneInfo('Asia/Kolkata')
GOOD=dict(verdict='BUY CE',confidence=8,recommended_strike=25000,entry_price=100,stop_loss=90,target=120)

@pytest.mark.parametrize('verdict',['SELL CE','DO NOT BUY PE','NO TRADE: avoid CALL','INVALID CALL','BUY_CE','NO_TRADE','BUY CE and PE',None])
def test_bad_verdict(verdict):
    assert validated_verdict(GOOD|{'verdict':verdict})[0]=='NO_TRADE'

@pytest.mark.parametrize('changes',[{'confidence':'8'},{'confidence':True},{'confidence':11},{'entry_price':float('nan')},{'entry_price':True},{'stop_loss':100},{'target':99},{'recommended_strike':0},{'entry_price':'bad'},{'stop_loss':None}])
def test_malformed_verdict(changes):
    assert validated_verdict(GOOD|changes)[0]=='NO_TRADE'

@pytest.mark.parametrize('v',['BUY CE','BUY PE'])
def test_valid_verdict(v):
    assert validated_verdict(GOOD|{'verdict':v})==(v,8,25000.,100.,90.,120.)

@pytest.mark.parametrize('qty',[15,25,65,130,325])
def test_actual_quantity_clamp(qty):
    sl,tgt=compute_clamped_sl_target('NIFTY',100,1,500,quantity=qty)
    assert 0<sl<100<tgt
    assert (100-sl)*qty<=700.000001 and (tgt-100)*qty<=1000.000001
    assert abs(sl*20-round(sl*20))<1e-8
    assert abs(tgt*20-round(tgt*20))<1e-8

@pytest.mark.parametrize('entry,qty',[(.05,65),(100,1000000),(100,0),(100,-1),(float('inf'),65)])
def test_infeasible_stop_rejected(entry,qty):
    with pytest.raises(ValueError): compute_clamped_sl_target('NIFTY',entry,1,500,quantity=qty)

def test_spread_payoff_uses_full_domain():
    legs=[dict(strike=25000,option_type='CE',side='BUY',quantity=65,price=100),dict(strike=25100,option_type='CE',side='SELL',quantity=65,price=40)]
    res=calculate_strategy_payoff(25000,legs)
    assert res['max_profit']==2600 and res['max_loss']==-3900 and res['breakevens']==[25060]

def test_zero_oi_unavailable_json_safe():
    r=calculate_pcr([dict(ce={'oi':0},pe={'oi':100})]);assert r['pcr_oi'] is None and r['sentiment']=='UNAVAILABLE'
    json.dumps(r,allow_nan=False)

@pytest.mark.parametrize('bad',[None,'bad',float('nan'),float('inf'),-1,0,1.2])
def test_invalid_quantity_refuses_repair(bad):
    t=dict(id='a',status='ACTIVE',side='BUY',entry_price=100,quantity=bad,gross_pnl=0,realized_pnl=0,total_charges=0)
    p=reconciliation_preview(1000000,1000000,0,[t]);assert p['issues'] and p['expected_cash'] is None
    json.dumps(p,allow_nan=False)

@pytest.mark.parametrize('raw',['bad','2026-02-30','20261125'])
def test_invalid_holiday(raw):
    with pytest.raises(ValueError): Settings(EXCHANGE_HOLIDAYS=raw)

def test_calendar_closures_and_weekends():
    h=parse_holidays('2026-11-25, 2026-11-26');assert not trading_day(date(2026,11,25),h)
    assert not trading_day(date(2026,11,28),h) and trading_day(date(2026,11,27),h)


def test_prior_session_cpr_requires_full_day_and_excludes_today():
    start=datetime(2026,11,24,9,15,tzinfo=IST)
    rows=[dict(time=(start+timedelta(minutes=5*i)).timestamp(),high=110,low=90,close=106) for i in range(75)]
    now=datetime(2026,11,25,10,0,tzinfo=IST)
    rows.append(dict(time=now.timestamp(),high=200,low=150,close=175))
    r=prior_session_cpr(rows,now);assert (r['cpr_pivot'],r['cpr_bc'],r['cpr_tc'])==(102,100,104)
    assert prior_session_cpr(rows[1:],now) is None

@pytest.mark.parametrize('direction,sign',[('BULLISH',1),('BEARISH',-1)])
def test_supertrend_direction(direction,sign):
    rows=[dict(high=200+sign*i+1,low=200+sign*i-1,close=200+sign*i) for i in range(80)]
    st=supertrend(rows);assert st['supertrend_direction']==direction
    assert (rows[-1]['close']-st['supertrend_value'])*sign>=0
    assert supertrend(rows[:5]) is None


def test_known_replay_exit_excluded_from_memory():
    now=datetime(2026,11,25,12,0,tzinfo=IST)
    row=dict(status='CLOSED',exit_reason='REPLAY_STOPPED',closed_at='2026-11-25 11:00:00',underlying='NIFTY',realized_pnl=123456,side='BUY',option_type='CE')
    assert '123456' not in build_memory([], [row], {'symbol':'NIFTY'}, now)
