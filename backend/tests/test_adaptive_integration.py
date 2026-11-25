"""Database and mocked-Gemini integration tests. No live API calls or production DB."""
from datetime import datetime, timedelta
import json
from types import SimpleNamespace
import uuid
import pytest
from adaptive_memory import IST, HEADER
from adaptive_store import retrieve_memory
from agents import BullAgent, BearAgent, JudgeAgent
from database import DailyReportModel, UserModel, AITradeEvidenceModel, async_session_factory, init_db
from debate_schemas import MarketSnapshot
from paper_engine import PaperEngine
from config import settings


def snapshot():
    return MarketSnapshot(symbol='NIFTY', spot_price=25050, day_open=25000,
        ema_20=25000, ema_50=24990, vwap=25000, rsi=55,
        session_reference='VWAP', atm_strike=25050)


async def new_user(db):
    name = 'adaptive-' + uuid.uuid4().hex[:12]
    u = UserModel(username=name, email=name+'@example.invalid', hashed_password='unused-test-hash')
    db.add(u)
    await db.flush()
    return u.id


@pytest.mark.asyncio
async def test_report_account_scope_and_actual_agent_system_prompts():
    await init_db()
    now = datetime.now(IST)
    yesterday = (now.date() - timedelta(days=1)).isoformat()
    async with async_session_factory() as db:
        uid, other = await new_user(db), await new_user(db)
        for user, lesson in [(uid,'account-specific lesson'), (other,'OTHER_ACCOUNT_SECRET')]:
            db.add(DailyReportModel(id='report-'+uuid.uuid4().hex, user_id=user,
                date=yesterday, total_trades=2, raw_analysis=json.dumps({
                    'key_lessons_learned':[lesson], 'stop_loss_analysis':[
                        {'symbol':'NIFTY25000PE','failure_reasons':'repeat strike'}]}),
                updated_at=yesterday+' 15:45:00'))
        await db.commit()
    snap = snapshot()
    memory = await retrieve_memory(uid, snap.model_dump(), now)
    assert HEADER in memory and 'account-specific lesson' in memory and 'repeat strike' in memory
    assert 'OTHER_ACCOUNT_SECRET' not in memory
    assert 'account-specific lesson' not in await retrieve_memory(None, snap.model_dump(), now)
    captured = []
    def fake_client(payload):
        def generate_content(**kwargs):
            captured.append(kwargs['config'].system_instruction)
            return SimpleNamespace(text=json.dumps(payload))
        return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    bull, bear, judge = BullAgent(), BearAgent(), JudgeAgent()
    bull._client = fake_client(dict(confidence=8,strike=25050,thesis='bull',arguments=['test']))
    bear._client = fake_client(dict(confidence=7,strike=25050,thesis='bear',arguments=['test']))
    judge._client = fake_client(dict(verdict='NO_TRADE',confidence=7,reasoning='test'))
    b = await bull.analyze(snap,memory=memory)
    r = await bear.analyze(snap,memory=memory)
    await judge.evaluate(snap,b,r,memory=memory)
    assert len(captured) == 3 and all(memory in p for p in captured)


def order(strike=25050):
    return dict(symbol=f'NIFTY31DEC99{strike}CE',underlying='NIFTY',strike=strike,option_type='CE',
        lots=1,side='BUY',order_type='MARKET',price=100,current_ltp=100,stop_loss=90,target=130)


def evidence(debate_id):
    return dict(debate_id=debate_id,auto_executed=True,snapshot=snapshot().model_dump(),confidence=8)


@pytest.mark.asyncio
async def test_durable_cooldown_cap_and_duplicate_fills(monkeypatch):
    await init_db()
    monkeypatch.setattr(settings,'AUTO_MAX_DAILY_TRADES',2)
    async with async_session_factory() as db:
        uid, other = await new_user(db), await new_user(db)
        await db.commit()
    engine = PaperEngine()
    monkeypatch.setattr(engine,'entry_window_open',lambda: True)
    first_id = 'deb-'+uuid.uuid4().hex
    first = await engine.place_order(order(),user_id=uid,ai_evidence=evidence(first_id))
    assert first['status']=='EXECUTED'
    async with async_session_factory() as db:
        row = await db.get(AITradeEvidenceModel,first_id)
        assert row.position_id == first['position_id'] and row.auto_executed==1
    await engine.update_market_prices({order()['symbol']:75})
    restored = PaperEngine()
    monkeypatch.setattr(restored,'entry_window_open',lambda: True)
    await restored.restore_from_db()
    duplicate = await restored.place_order(order(25100),user_id=uid,ai_evidence=evidence(first_id))
    assert duplicate['status']=='REJECTED' and 'durable fill' in duplicate['reject_reason']
    blocked = await restored.place_order(order(),user_id=uid,ai_evidence=evidence('deb-'+uuid.uuid4().hex))
    assert blocked['status']=='REJECTED' and 'cooldown' in blocked['reject_reason']
    # A different account does not inherit the cooldown.
    separate = await restored.place_order(order(),user_id=other,ai_evidence=evidence('deb-'+uuid.uuid4().hex))
    assert separate['status']=='EXECUTED'
    second = await restored.place_order(order(25100),user_id=uid,ai_evidence=evidence('deb-'+uuid.uuid4().hex))
    assert second['status']=='EXECUTED'
    capped = await restored.place_order(order(25150),user_id=uid,ai_evidence=evidence('deb-'+uuid.uuid4().hex))
    assert capped['status']=='REJECTED' and 'cap reached' in capped['reject_reason']
