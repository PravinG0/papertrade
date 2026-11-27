from datetime import datetime, timedelta
from unittest.mock import AsyncMock
import pytest
from debate_engine import DebateEngine
from debate_schemas import MarketSnapshot, BullAgentOutput, BearAgentOutput, JudgeAgentOutput
from quant_engine import IST, FRAMES
from config import settings


@pytest.mark.asyncio
async def test_quant_rejection_persists_original_ai_proposal(monkeypatch):
    engine=DebateEngine()
    snapshot=MarketSnapshot(symbol='NIFTY',spot_price=25000,ema_20=24990,ema_50=24900,vwap=24980,rsi=60,
        data_status='live',spot_fresh=True,session_active=True,session_reference='VWAP',supertrend_direction='BULLISH',
        timeframes={f:{'direction':'BULLISH'} for f in FRAMES})
    snapshot.timeframes['15m']={'direction':'BEARISH'}
    monkeypatch.setattr(engine,'build_snapshot',AsyncMock(return_value=snapshot))
    monkeypatch.setattr('debate_engine.retrieve_memory',AsyncMock(return_value='test evidence'))
    bull=BullAgentOutput(analysis_source='gemini',confidence=9,strike=25000,thesis='up',arguments=['up'])
    bear=BearAgentOutput(analysis_source='gemini',confidence=4,strike=25000,thesis='down',arguments=['down'])
    judge=JudgeAgentOutput(analysis_source='gemini',verdict='BUY CE',confidence=9,recommended_strike=25000,entry_price=100,stop_loss=95,target=115,reasoning='up')
    monkeypatch.setattr(engine.bull_agent,'analyze',AsyncMock(return_value=bull))
    monkeypatch.setattr(engine.bear_agent,'analyze',AsyncMock(return_value=bear))
    monkeypatch.setattr(engine.judge_agent,'evaluate',AsyncMock(return_value=judge))
    persist=AsyncMock(); monkeypatch.setattr(engine,'_persist',persist)
    result=await engine.run_debate('NIFTY',user_id=42)
    assert result.original_judge_verdict=='BUY CE' and result.judge.verdict=='NO_TRADE'
    assert result.original_judge_proposal['recommended_strike']==25000
    assert not result.quantitative_validation['eligible'] and '15m' in ' '.join(result.quantitative_validation['reasons'])
    persist.assert_awaited_once_with(result)
    engine.bull_agent.analyze.assert_awaited_once_with(snapshot,memory='test evidence')
    engine.bear_agent.analyze.assert_awaited_once_with(snapshot,memory='test evidence')
    engine.judge_agent.evaluate.assert_awaited_once_with(snapshot,bull,bear,memory='test evidence')
