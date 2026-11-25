"""Additional runtime tests. Install requirements-dev.txt first. No live services.
Some are regression specifications expected to fail until the audited bugs are fixed.
"""
import asyncio
from datetime import datetime
from types import SimpleNamespace
import uuid
import pytest
from database import init_db, async_session_factory, UserModel, PaperTradeModel
from paper_engine import PaperEngine, calculate_trade_charges
from config import settings
from adaptive_memory import IST
from agents.judge_agent import JudgeAgent
from debate_schemas import MarketSnapshot

async def create_user():
    await init_db()
    name='audit-'+uuid.uuid4().hex
    async with async_session_factory() as db:
        u=UserModel(username=name,email=name+'@example.invalid',hashed_password='unused')
        db.add(u);await db.flush();uid=u.id;await db.commit()
    return uid

def order(**kw):
    return dict(symbol='NIFTY31DEC9925000CE',underlying='NIFTY',strike=25000,option_type='CE',side='BUY',order_type='MARKET',lots=1,lot_size=65,price=100,current_ltp=100)|kw

@pytest.mark.asyncio
@pytest.mark.parametrize('side,exit_price',[('BUY',90),('BUY',110),('SELL',90),('SELL',110)])
async def test_net_cash_conservation_after_exit(side,exit_price):
    uid=await create_user();e=PaperEngine();await e.reset_portfolio(user_id=uid)
    f=await e.place_order(order(side=side),uid,enforce_hours=False)
    assert f['status']=='EXECUTED'
    r=await e.exit_position(f['position_id'],exit_price,user_id=uid)
    assert r['status']=='SUCCESS'
    w=(await e.get_state(uid))['wallet']
    assert w['cash_balance']==round(1000000+r['realized_pnl'],2)
    assert w['used_margin']==0 and w['historical_balance_difference']==0

@pytest.mark.asyncio
async def test_other_user_cannot_close_or_edit():
    a,b=await create_user(),await create_user();e=PaperEngine()
    f=await e.place_order(order(),a,enforce_hours=False);pid=f['position_id']
    assert (await e.exit_position(pid,90,user_id=b))['status']=='ERROR'
    assert (await e.update_sl(pid,90,user_id=b))['status']=='ERROR'
    assert not (await e.get_state(b))['positions']
    assert len((await e.get_state(a))['positions'])==1

@pytest.mark.asyncio
async def test_concurrent_fills_cannot_overspend():
    uid=await create_user();a,b=PaperEngine(),PaperEngine();await a.reset_portfolio(10000,uid)
    result=await asyncio.gather(a.place_order(order(),uid,enforce_hours=False),b.place_order(order(),uid,enforce_hours=False))
    assert sum(x['status']=='EXECUTED' for x in result)==1
    assert (await a.get_state(uid))['wallet']['cash_balance']==3500

@pytest.mark.asyncio
async def test_cancel_already_filled_from_stale_worker_is_not_success():
    uid=await create_user();a,b=PaperEngine(),PaperEngine()
    f=await a.place_order(order(order_type='LIMIT'),uid,enforce_hours=False)
    await b.restore_from_db();await a.update_market_prices({order()['symbol']:99})
    assert (await b.cancel_order(f['order_id'],uid))['status']!='SUCCESS'

@pytest.mark.asyncio
async def test_stale_worker_cannot_modify_closed_trade():
    uid=await create_user();a,b=PaperEngine(),PaperEngine()
    f=await a.place_order(order(stop_loss=90),uid,enforce_hours=False);pid=f['position_id']
    await b.restore_from_db();await a.exit_position(pid,110,user_id=uid)
    assert (await b.update_sl(pid,80,user_id=uid))['status']!='SUCCESS'
    async with async_session_factory() as db:
        row=await db.get(PaperTradeModel,pid);assert row.stop_loss==90

@pytest.mark.asyncio
async def test_restart_does_not_erase_last_observed_price():
    uid=await create_user();a,b=PaperEngine(),PaperEngine()
    f=await a.place_order(order(),uid,enforce_hours=False)
    await a.update_market_prices({order()['symbol']:112})
    await b.restore_from_db()
    pos=next(p for p in (await b.get_state(uid))['positions'] if p['id']==f['position_id'])
    assert pos['current_ltp']==112

@pytest.mark.asyncio
async def test_cross_day_trade_not_counted_as_closed_before_exit():
    uid=await create_user();e=PaperEngine()
    f=await e.place_order(order(),uid,enforce_hours=False)
    await e.exit_position(f['position_id'],110,user_id=uid)
    async with async_session_factory() as db:
        t=await db.get(PaperTradeModel,f['position_id']);t.created_at='2026-11-23 14:00:00';t.closed_at='2026-11-24 10:00:00';await db.commit()
    rows=await e.get_daily_trades('2026-11-23',uid)
    assert all(t['status']!='CLOSED' for t in rows)

@pytest.mark.asyncio
async def test_replay_fills_do_not_change_live_wallet():
    uid=await create_user();e=PaperEngine();before=(await e.get_state(uid))['wallet']['cash_balance']
    f=await e.place_order(order(replay=True),uid,enforce_hours=False)
    if f['status']=='EXECUTED':
        assert (await e.get_state(uid))['wallet']['cash_balance']==before

@pytest.mark.parametrize('verdict',['SELL CE','DO NOT BUY PE','NO TRADE: avoid CALL','INVALID CALL'])
def test_judge_rejects_ambiguous_verdict(verdict):
    snap=MarketSnapshot(spot_price=25000,ema_20=25000,ema_50=25000,vwap=25000,rsi=50)
    out=JudgeAgent()._parse_and_guardrail(dict(verdict=verdict,confidence=8,reasoning='test'),snap)
    assert out.verdict=='NO_TRADE'

@pytest.mark.parametrize('buy,sell',[(0,0),(6500,6500),(6500,7800),(6500,5200)])
def test_trade_charges_sum(buy,sell):
    c=calculate_trade_charges(buy,sell)
    assert c['total_charges']==round(sum(v for k,v in c.items() if k!='total_charges'),2)

@pytest.mark.asyncio
async def test_replay_start_and_controls_are_account_owned(monkeypatch):
    from replay_engine import ReplayEngine
    from angel_service import angel_service
    async def candles(*args):
        return [{'time': 1700000000, 'close': 25000}]
    monkeypatch.setattr(angel_service, 'get_replay_candles', candles)
    r=ReplayEngine()
    try:
        result=await r.start_replay('2026-11-24', owner_id=1)
        assert result['status']=='SUCCESS'
        assert (await r.start_replay('2026-11-24', owner_id=2))['status']=='ERROR'
        assert (await r.pause(owner_id=2))['status']=='ERROR'
        assert (await r.stop_replay(owner_id=2))['status']=='ERROR'
        assert r.owner_id==1
    finally:
        await r.stop_replay()

@pytest.mark.asyncio
async def test_account_schedulers_have_separate_status_and_state(monkeypatch):
    from scheduler import SchedulerRegistry, DebateScheduler
    async def idle(self):
        await asyncio.sleep(60)
    monkeypatch.setattr(DebateScheduler,'_run_loop',idle)
    a,b=await create_user(),await create_user()
    registry=SchedulerRegistry()
    try:
        await registry.start(user_id=a,symbol='NIFTY',immediate=False)
        await registry.start(user_id=b,symbol='BANKNIFTY',immediate=False)
        assert registry.get_status(a)['symbol']=='NIFTY'
        assert registry.get_status(b)['symbol']=='BANKNIFTY'
        assert not registry.get_status(None)['is_running']
        await registry.stop(a)
        assert not registry.get_status(a)['is_running'] and registry.get_status(b)['is_running']
    finally:
        await registry.stop(b)
        await registry.shutdown()
