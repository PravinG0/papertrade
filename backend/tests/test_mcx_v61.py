from datetime import datetime,timedelta,date,time
from types import SimpleNamespace
from contextlib import asynccontextmanager
import asyncio
import pytest
from mcx_market import IST, _empty_mcx_ledger, position_due, ledger_key, CommodityContract, place_mcx_paper_order, settle_mcx_positions, historical_mcx_bounds
from mcx_ai import memory_summary, risk_guard, configure, claim, session_reference, session_active, near_close, default_config
from config import settings
import mcx_storage

NOW=datetime(2026,11,27,21,0,tzinfo=IST)
CONTRACT=CommodityContract('CRUDEOIL','2026-12-16',7800,'PE','MCX','123','CRUDEOIL16DEC267800PE',100,.1)

@pytest.fixture
def storage(monkeypatch):
    import copy
    data={};lock=asyncio.Lock()
    @asynccontextmanager
    async def edit(key,default):
        async with lock:
            value=copy.deepcopy(data.get(key,default()))
            yield value
            data[key]=value
    async def read(key,default): return copy.deepcopy(data.get(key,default()))
    monkeypatch.setattr(mcx_storage,'edit',edit)
    monkeypatch.setattr(mcx_storage,'read',read)
    monkeypatch.setattr('mcx_ai.edit',edit)
    monkeypatch.setattr('mcx_ai.read',read)
    return data

@pytest.mark.parametrize('hour,minute,active',[(8,59,False),(9,0,True),(15,31,True),(21,0,True),(23,54,True),(23,55,False)])
def test_evening_session(hour,minute,active):
    assert session_active(NOW.replace(hour=hour,minute=minute))==active

@pytest.mark.parametrize('minute,expected',[(49,False),(50,True),(54,True),(55,True)])
def test_close_buffer(minute,expected):
    assert near_close(NOW.replace(hour=23,minute=minute))==expected

@pytest.mark.parametrize('delta,expected',[(0,False),(1,True)])
def test_recovery_next_session(delta,expected):
    p={'entered_at':(NOW-timedelta(days=delta)).isoformat()}
    assert position_due(p,NOW)==expected

@pytest.mark.parametrize('minute,expected',[(52,False),(53,True),(54,True)])
def test_squareoff_buffer(minute,expected):
    assert position_due({'entered_at':NOW.isoformat()},NOW.replace(hour=23,minute=minute))==expected

@pytest.mark.parametrize('ledger',['paper','champion','challenger'])
def test_distinct_ledger(ledger):
    assert ledger_key(1,ledger)==f'mcx-{ledger}:1'
    assert ledger_key(1,ledger)!=ledger_key(2,ledger)


def test_memory_excludes_future():
    rows=[{'closed_at':(NOW-timedelta(days=i)).isoformat(),'net_pnl':-100 if i%2 else 200,'exit_reason':'STOP_LOSS_HIT','source':'AI'} for i in range(100)]
    rows.append({'closed_at':(NOW+timedelta(days=1)).isoformat(),'net_pnl':99999})
    m=memory_summary(rows,NOW)
    assert [m[x]['sample_size'] for x in ('intraday','5_days','30_days','90_days')]==[1,5,30,90]
    assert m['intraday']['net_pnl']==200


def test_reference_requires_session_open():
    assert session_reference([{'time':NOW.timestamp(),'high':100,'low':90,'close':95,'volume':1}],NOW)==(None,'UNKNOWN')

@pytest.mark.parametrize('volume,kind',[(10,'VWAP'),(0,'TYPICAL_PRICE_PROXY')])
def test_session_reference(volume,kind):
    rows=[{'time':NOW.replace(hour=9,minute=0).timestamp(),'high':100,'low':90,'close':95,'volume':volume}]
    assert session_reference(rows,NOW)==(95,kind)


def ledger():
    d=_empty_mcx_ledger();d['ai_config']={'enabled':True,'auto_execute':True,'generation':'g'};return d


def guard(d, risk=100, cap=5):
    risk_guard(d,CONTRACT,NOW,risk,max_trades=cap,max_risk_pct=.25,max_loss_pct=1,generation='g')


def test_risk_accept(): guard(ledger())

@pytest.mark.parametrize('case,match',[('stopped','stopped'),('generation','stopped'),('position','open primary'),('risk','per-trade'),('loss','daily loss'),('cap','daily automatic'),('cooldown','cooldown'),('consecutive','consecutive')])
def test_risk_rejections(case,match):
    d=ledger();r=100
    t={'entered_at':NOW.isoformat(),'closed_at':(NOW-timedelta(minutes=5)).isoformat(),'net_pnl':-50,'source':'AI','exit_reason':'STOP_LOSS_HIT','symbol':CONTRACT.symbol}
    if case=='stopped':d['ai_config']['enabled']=False
    if case=='generation':d['ai_config']['generation']='new'
    if case=='position':d['positions']=[{}]
    if case=='risk':r=3000
    if case=='loss':d['trades']=[{**t,'net_pnl':-20000}]
    if case=='cap':d['trades']=[{**t,'symbol':'OTHER'}]*5
    if case=='cooldown':d['trades']=[t]
    if case=='consecutive':d['trades']=[{**t,'symbol':'OTHER'}]*3
    with pytest.raises(ValueError,match=match):guard(d,r)


def test_no_count_mode_retains_other_risk():
    d=ledger();d['trades']=[{'entered_at':NOW.isoformat(),'closed_at':NOW.isoformat(),'net_pnl':50,'source':'AI'}]*100
    guard(d,cap=0)
    with pytest.raises(ValueError,match='per-trade'):guard(d,risk=3000,cap=0)

@pytest.mark.asyncio
async def test_storage_concurrent_settlement_and_research_isolation(storage):
    r=await place_mcx_paper_order(1,CONTRACT,1,100,90,130,NOW,debate_id='d')
    await place_mcx_paper_order(1,CONTRACT,1,100,90,130,NOW,ledger='champion',debate_id='d')
    with pytest.raises(ValueError,match='already executed'):await place_mcx_paper_order(1,CONTRACT,1,100,90,130,NOW,debate_id='d')
    results=await asyncio.gather(settle_mcx_positions(1,{'123':140},now=NOW),settle_mcx_positions(1,{'123':140},now=NOW))
    assert sum(x['settled'] for x in results)==1
    assert len(storage['mcx-paper:1']['trades'])==1
    assert len(storage['mcx-champion:1']['positions'])==1
    assert storage['mcx-paper:1']['cash_balance']>1000000

@pytest.mark.asyncio
async def test_no_history_truncation(storage):
    storage['mcx-paper:1']={**_empty_mcx_ledger(),'trades':[{'id':str(i)} for i in range(120)]}
    await place_mcx_paper_order(1,CONTRACT,1,100,90,130,NOW)
    await settle_mcx_positions(1,{'123':140},now=NOW)
    assert len(storage['mcx-paper:1']['trades'])==121

@pytest.mark.asyncio
@pytest.mark.parametrize('bad',[0,21,True,1.5])
async def test_invalid_lots(storage,bad):
    with pytest.raises(ValueError,match='Lots'): await place_mcx_paper_order(1,CONTRACT,bad,100,90,130,NOW)

@pytest.mark.asyncio
async def test_stale_position_snapshot_not_closed(storage):
    a=await place_mcx_paper_order(1,CONTRACT,1,100,90,130,NOW)
    await place_mcx_paper_order(1,CONTRACT,1,100,90,130,NOW)
    await settle_mcx_positions(1,{'123':140},eligible_ids={a['position']['id']},now=NOW)
    assert len(storage['mcx-paper:1']['positions'])==1

@pytest.mark.asyncio
async def test_persistent_scheduler_lease_and_stop(storage,monkeypatch):
    monkeypatch.setattr(settings,'MCX_AUTO_EXECUTION_ENABLED',False)
    s=await configure(1,{'enabled':True,'future':CONTRACT.symbol,'expiry':CONTRACT.expiry,'interval':5})
    assert s['enabled']
    c=await claim(1,False);assert c
    assert await claim(1,False) is None
    await configure(1,{'enabled':False})
    assert not storage['mcx-paper:1']['ai_config']['enabled']
    assert storage['mcx-paper:1']['ai_config']['generation']!=c['generation']
    with pytest.raises(ValueError,match='disabled'):await configure(1,{'auto_execute':True})

@pytest.mark.asyncio
@pytest.mark.parametrize('payload',[{'enabled':'true'},{'interval':0},{'lots':True},{'max_trades':101},{'enabled':True}])
async def test_scheduler_input_validation(storage,payload):
    with pytest.raises(ValueError): await configure(1,payload)


def test_historical_calendar_explicit(monkeypatch):
    monkeypatch.setattr(settings,'MCX_HISTORICAL_SESSIONS','2026-09-01/2026-10-30/09:00/23:30')
    assert historical_mcx_bounds(date(2026,10,1))==(time(9),time(23,30))
    assert historical_mcx_bounds(date(2026,8,1)) is None
    assert historical_mcx_bounds(date(2026,11,27))==(time(9),time(23,55))

@pytest.mark.asyncio
async def test_three_agent_flow_and_memory(storage,monkeypatch):
    import sys
    from unittest.mock import AsyncMock
    from quant_engine import expected_starts
    import mcx_ai
    fut=CommodityContract('CRUDEOIL','2026-12-20',0,'FUT','MCX','567','CRUDEOIL20DEC26FUT',100,.1)
    # Freeze clock for deterministic completed-bar boundaries.
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return NOW if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(mcx_ai,'datetime',Clock)
    monkeypatch.setattr(settings,'MCX_HISTORICAL_SESSIONS','2026-01-01/2026-10-30/09:00/23:30')
    monkeypatch.setattr(settings,'MCX_OPTION_FUTURE_MAP','{"2026-12-16":"CRUDEOIL20DEC26FUT"}')
    async def candles(sym,frame,span,contract):
        assert contract==fut
        rows=[]
        for i,k in enumerate(expected_starts(NOW,frame,historical_mcx_bounds,200)):
            timestamp=datetime.combine(k,time(9),IST).timestamp() if frame=='1d' else k
            px=7200+i*2
            rows.append({'time':timestamp,'open':px,'high':px+1,'low':px-1,'close':px,'volume':100})
        return {'source':'live','candles':rows}
    q={'ltp':8000,'depth':{'buy':[{'price':99.9}],'sell':[{'price':100}]},'exchFeedTime':NOW.isoformat()}
    service=SimpleNamespace(ensure_contracts=AsyncMock(),get_candles_with_meta=candles,get_token_quotes=AsyncMock(return_value={'567':q,'123':q}),_quote_is_current=lambda *_:True)
    monkeypatch.setitem(sys.modules,'angel_service',SimpleNamespace(angel_service=service))
    monkeypatch.setitem(sys.modules,'scrip_master',SimpleNamespace(scrip_master=SimpleNamespace(mcx_contracts=lambda:[fut,CONTRACT])))
    storage['mcx-paper:1']={**_empty_mcx_ledger(),'trades':[{'closed_at':(NOW-timedelta(days=1)).isoformat(),'net_pnl':-100,'exit_reason':'STOP_LOSS_HIT'}]}
    calls=[]
    async def agent(role,context,memory):
        calls.append((role,context,memory))
        if role=='Judge': return {'verdict':'BUY PE','confidence':9,'recommended_strike':7800,'entry_price':100,'stop_loss':90,'target':130,'reasoning':'test'}
        return {'confidence':8,'thesis':'test','arguments':['test']}
    result=await mcx_ai.build_debate(1,fut.symbol,CONTRACT.expiry,agent=agent)
    assert {r for r,_,_ in calls}=={'Bull','Bear','Judge'}
    assert all('STOP_LOSS_HIT' in m for _,_,m in calls)
    assert all('MCX EPISODIC MEMORY' in m for _,_,m in calls)
    assert len(result['market_snapshot']['timeframes'])==5
    assert result['judge']['verdict']=='BUY PE'
    assert result['verdict']=='NO_TRADE' # Bullish completed bars independently reject PE
    assert result['market_snapshot']['option_mapping_verified']

@pytest.mark.asyncio
async def test_manual_debate_persists_without_auto_fill(storage,monkeypatch):
    import mcx_ai
    from unittest.mock import AsyncMock
    monkeypatch.setattr(settings,'MCX_SHADOW_ENABLED',False)
    monkeypatch.setattr(settings,'MCX_AUTO_EXECUTION_ENABLED',True)
    fake={'id':'debate-1','verdict':'BUY CE','quantitative_validation':{'eligible':True}}
    monkeypatch.setattr(mcx_ai,'build_debate',AsyncMock(return_value=fake))
    fill=AsyncMock();monkeypatch.setattr(mcx_ai,'place_mcx_paper_order',fill)
    result=await mcx_ai.run(1,future='FUT',expiry='2026-12-16')
    assert result['execution']['status']=='NOT_EXECUTED'
    fill.assert_not_awaited()
    assert storage['mcx-paper:1']['debates'][0]['id']=='debate-1'
    assert storage['mcx-paper:1']['ai_config']['lease_until'] is None

@pytest.mark.asyncio
async def test_agent_failure_releases_lease(storage,monkeypatch):
    import mcx_ai
    from unittest.mock import AsyncMock
    monkeypatch.setattr(mcx_ai,'build_debate',AsyncMock(side_effect=ValueError('Gemini unavailable')))
    with pytest.raises(ValueError,match='Gemini'):await mcx_ai.run(1)
    assert storage['mcx-paper:1']['ai_config']['lease_until'] is None
    assert storage['mcx-paper:1']['ai_config']['last_error']=='Gemini unavailable'


def test_daily_reports_use_exit_date_and_fees():
    from mcx_ai import daily_summaries
    rows=[{'entered_at':(NOW-timedelta(days=1)).isoformat(),'closed_at':NOW.isoformat(),'net_pnl':100,'charges':20,'exit_reason':'TARGET_HIT'}, {'closed_at':NOW.isoformat(),'net_pnl':-40,'charges':5,'exit_reason':'STOP_LOSS_HIT'}]
    assert daily_summaries(rows)==[{'date':'2026-11-27','trades':2,'wins':1,'losses':1,'net_pnl':60.,'estimated_charges':25.,'exit_reasons':{'TARGET_HIT':1,'STOP_LOSS_HIT':1}}]
