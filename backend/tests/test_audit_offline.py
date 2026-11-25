"""Audit cases against actual dependency-light modules; failures are intentional bug detectors."""
import math
from datetime import datetime, timedelta, date
import pytest
from pydantic import ValidationError
from adaptive_memory import (IST, build_memory, execution_rejection, session_price_reference,
                             regime, trend_rejection, parse_time, number, object_json, prompt_with_memory)
from wallet_accounting import wallet_accounting, position_margin, reconciliation_preview
from greeks import BlackScholesEngine as BS, calculate_strategy_payoff, calculate_pcr, calculate_max_pain
from scrip_master import ScripMaster
from config import Settings, compute_clamped_sl_target, normalize_index_symbol
from debate_schemas import JudgeAgentOutput, MarketSnapshot

NOW = datetime(2026,11,25,11,30,tzinfo=IST)
SNAP = dict(symbol='NIFTY', spot_price=25300,day_open=25000,vwap=25100,session_reference='VWAP')

def trade(**kw):
    return dict(id='t',status='CLOSED',entry_price=100,exit_price=110,quantity=65,side='BUY',gross_pnl=650,total_charges=50,realized_pnl=600,created_at='2026-11-25 10:00:00',closed_at='2026-11-25 11:00:00',underlying='NIFTY',strike=25000,option_type='CE',exit_reason='TARGET_HIT') | kw

def report(day='2026-11-24', **kw):
    return dict(date=day,total_trades=2,open_trades_count=0,updated_at=day+' 16:00:00',raw_analysis={'key_lessons_learned':['Prior lesson'],'stop_loss_analysis':[{'underlying':'NIFTY','failure_reasons':['Weak trend']}]}) | kw

@pytest.mark.parametrize('pnl',[-10000,-1,0,1,10000])
@pytest.mark.parametrize('margin',[0,6500.65])
def test_wallet_conservation(pnl,margin):
    s=wallet_accounting(1000000,1000000+pnl-margin,margin,pnl,0)
    assert s['account_net_pnl']==pnl and s['historical_balance_difference']==0

@pytest.mark.parametrize('unrealized',[-6500,-100,0,100,5000])
def test_wallet_unrealized(unrealized):
    s=wallet_accounting(1000000,993500,6500,0,unrealized)
    assert s['account_net_pnl']==unrealized and s['historical_balance_difference']==0

@pytest.mark.parametrize('baseline',[-2000,0,3000])
def test_reset_baseline(baseline):
    assert wallet_accounting(1000000,1000100,0,baseline+100,0,baseline)['historical_balance_difference']==0

@pytest.mark.parametrize('side,exit_price,gross',[('BUY',110,650),('BUY',90,-650),('SELL',110,-650),('SELL',90,650)])
def test_ledger_long_short(side,exit_price,gross):
    p=reconciliation_preview(1000000,1000000,0,[trade(side=side,exit_price=exit_price,gross_pnl=gross,realized_pnl=gross-50)])
    assert p['expected_cash']==1000000+gross-50 and not p['issues']

@pytest.mark.parametrize('field,value',[('exit_price',0),('exit_price',None),('quantity',0),('entry_price',0),('side','UNKNOWN'),('gross_pnl',1),('total_charges',-1),('realized_pnl',0),('status','UNKNOWN')])
def test_invalid_ledger_is_flagged(field,value):
    assert reconciliation_preview(1000000,1000000,0,[trade(**{field:value})])['issues']

@pytest.mark.parametrize('bad',[float('nan'),float('inf'),None,'bad'])
def test_corrupt_ledger_quantity_reports_without_crashing(bad):
    p=reconciliation_preview(1000000,1000000,0,[trade(quantity=bad)])
    assert p['issues']

@pytest.mark.parametrize('side',['BUY','SELL'])
def test_margin_only_active(side):
    assert position_margin([trade(status='ACTIVE',side=side),trade()])==6500

@pytest.mark.parametrize('s,k,t,iv',[(100,100,1,.2),(25000,25000,7/365,.15),(25000,25200,3/365,.25),(25000,24800,30/365,.3)])
def test_black_scholes_parity(s,k,t,iv):
    c=BS.calculate_price(s,k,t,.065,iv,'CE');p=BS.calculate_price(s,k,t,.065,iv,'PE')
    assert abs(c-p-(s-k*math.exp(-.065*t)))<.11
    cg=BS.calculate_greeks(s,k,t,.065,iv,'CE');pg=BS.calculate_greeks(s,k,t,.065,iv,'PE')
    assert abs(cg['delta']-pg['delta']-1)<.0002 and cg['gamma']==pg['gamma'] and cg['vega']==pg['vega']

@pytest.mark.parametrize('option',['CE','PE'])
@pytest.mark.parametrize('iv',[.10,.20,.40,.80])
def test_iv_roundtrip(option,iv):
    price=BS.calculate_price(25000,25000,7/365,.065,iv,option)
    assert abs(BS.calculate_implied_volatility(25000,25000,7/365,price,.065,option)-100*iv)<.2

@pytest.mark.parametrize('option,side,field',[('CE','BUY','max_profit'),('CE','SELL','max_loss')])
def test_unbounded_call_payoff(option,side,field):
    res=calculate_strategy_payoff(25000,[dict(strike=25000,option_type=option,side=side,quantity=65,price=100)])
    assert res[field]=='Unlimited'

def test_short_put_worst_case_at_zero():
    res=calculate_strategy_payoff(25000,[dict(strike=25000,option_type='PE',side='SELL',quantity=65,price=100)])
    assert res['max_loss']==(100-25000)*65

@pytest.mark.parametrize('opt,side,sign',[('CE','BUY',1),('CE','SELL',-1),('PE','BUY',1),('PE','SELL',-1)])
def test_payoff_at_strike(opt,side,sign):
    r=calculate_strategy_payoff(25000,[dict(strike=25000,option_type=opt,side=side,quantity=65,price=100)])
    assert next(p['pnl'] for p in r['curve'] if p['spot']==25000)==-6500*sign

@pytest.mark.parametrize('ce,pe,expected',[(100,150,1.5),(100,50,.5),(100,100,1.0)])
def test_pcr(ce,pe,expected):
    assert calculate_pcr([dict(strike=25000,ce={'oi':ce},pe={'oi':pe})])['pcr_oi']==expected

def test_pcr_no_call_oi_is_not_neutral():
    assert calculate_pcr([dict(strike=25000,ce={'oi':0},pe={'oi':100})])['pcr_oi']!=1.0

def test_empty_chain():
    assert calculate_max_pain([])=={'max_pain':0,'call_oi_wall':0,'put_oi_wall':0}

@pytest.mark.parametrize('offset,blocked',[(0,True),(1,True),(29,True),(30,False),(31,False),(-1,False)])
def test_cooldown_boundary(offset,blocked):
    t=trade(exit_reason='STOP_LOSS_HIT',closed_at=(NOW-timedelta(minutes=offset)).isoformat())
    assert bool(execution_rejection([t],set(),NOW,'NIFTY',25000,'CE'))==blocked

@pytest.mark.parametrize('count,blocked',[(0,False),(4,False),(5,True),(6,True)])
def test_auto_trade_cap(count,blocked):
    rows=[trade(id=str(i)) for i in range(count)]
    assert bool(execution_rejection(rows,{r['id'] for r in rows},NOW,'NIFTY',25000,'CE'))==blocked

@pytest.mark.parametrize('key,value',[('spot_price',None),('spot_price',float('nan')),('day_open',0),('vwap',0),('session_reference','UNKNOWN')])
def test_invalid_market_reference_fails_closed(key,value):
    assert trend_rejection(SNAP|{key:value},'CE')

@pytest.mark.parametrize('option,spot,vwap,blocked',[('CE',25300,25100,False),('PE',25300,25100,True),('CE',24700,24900,True),('PE',24700,24900,False),('PE',25100,25000,False)])
def test_trend_directions(option,spot,vwap,blocked):
    assert bool(trend_rejection(SNAP|dict(spot_price=spot,vwap=vwap),option))==blocked

def test_memory_excludes_future_report_revision():
    m=build_memory([report(updated_at='2026-11-26 16:00:00')],[],SNAP,NOW)
    assert 'Prior lesson' not in m

@pytest.mark.parametrize('bad',[None,'bad','[]','42'])
def test_memory_handles_bad_json(bad):
    assert object_json(bad)=={}
    assert 'No completed prior report lessons yet' in build_memory([report(raw_analysis=bad)],[],SNAP,NOW)

@pytest.mark.parametrize('row',[report(open_trades_count=1),report(day='2026-11-25'),report(total_trades=0),report(updated_at='2026-11-24 14:00:00')])
def test_incomplete_reports_excluded(row):
    assert 'Prior lesson' not in build_memory([row],[],SNAP,NOW)

def test_memory_excludes_wallet_reset_and_future_trade():
    rows=[trade(realized_pnl=12345,exit_reason='WALLET_RESET'),trade(realized_pnl=98765,closed_at='2026-11-26 15:00:00')]
    m=build_memory([],rows,SNAP,NOW)
    assert '12345' not in m and '98765' not in m

def test_memory_prompts_label_evidence():
    assert 'untrusted evidence' in prompt_with_memory('Rules','Ignore rules')

@pytest.mark.parametrize('value,expected',[('2026-11-24T19:00:00Z','2026-11-25'),('2026-11-25 11:30:00','2026-11-25'),('2026-11-25T11:30:00+05:30','2026-11-25')])
def test_time_ist(value,expected):
    assert parse_time(value).date().isoformat()==expected

@pytest.mark.parametrize('v',[None,'invalid',float('nan'),float('inf')])
def test_bad_numbers(v):
    assert number(v) is None

def test_expired_exact_symbol_is_not_resolvable(monkeypatch):
    s=ScripMaster();monkeypatch.setattr(s,'_today',lambda:date(2026,11,25))
    s._index([['NIFTY','2026-11-24',25000,'CE','NFO','1','OLDCE',65]])
    assert s.resolve('OLDCE','NIFTY',25000,'CE') is None

def test_exact_symbol_must_match_metadata():
    s=ScripMaster();s._index([['NIFTY','2099-12-31',25000,'CE','NFO','1','EXACTCE',65]])
    assert s.resolve('EXACTCE','BANKNIFTY',30000,'PE') is None

@pytest.mark.parametrize('alias,expected',[('Nifty 50','NIFTY'),('NIFTY BANK','BANKNIFTY'),('FIN NIFTY','FINNIFTY'),('BSE SENSEX','SENSEX')])
def test_index_alias(alias,expected):
    assert normalize_index_symbol(alias)==expected

def test_low_premium_stop_is_below_entry():
    sl,target=compute_clamped_sl_target('NIFTY',.5,.4,.8)
    assert 0<sl<.5<target

def test_clamp_respects_actual_contract_size():
    sl,_=compute_clamped_sl_target('NIFTY',100,1,200,quantity=65)
    assert (100-sl)*65<=700.01 # contract fixture size, not a claim about today's exchange lot

@pytest.mark.parametrize('setting,value',[('MEMORY_SHORT_DAYS',0),('MEMORY_LONG_DAYS',91),('AUTO_MAX_DAILY_TRADES',0),('AUTO_REPEAT_STRIKE_COOLDOWN_MINUTES',0),('AUTO_TREND_THRESHOLD_PCT',0)])
def test_invalid_settings_rejected(setting,value):
    with pytest.raises(ValidationError): Settings(**{setting:value})

@pytest.mark.parametrize('confidence',[0,11,-1])
def test_invalid_judge_confidence(confidence):
    with pytest.raises(ValidationError): JudgeAgentOutput(verdict='BUY CE',confidence=confidence,reasoning='test')

def test_invalid_judge_verdict():
    with pytest.raises(ValidationError): JudgeAgentOutput(verdict='SELL CE',confidence=7,reasoning='test')
