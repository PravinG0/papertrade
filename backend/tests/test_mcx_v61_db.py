"""Real database integration. conftest points at disposable SQLite; also run against isolated PostgreSQL in CI."""
import asyncio
from datetime import datetime
import pytest
from database import init_db
from mcx_market import IST, CommodityContract, place_mcx_paper_order, settle_mcx_positions, get_mcx_paper_state

@pytest.mark.asyncio
async def test_mcx_database_duplicate_settlement_and_research_isolation():
    await init_db()
    now=datetime(2026,11,27,21,0,tzinfo=IST)
    c=CommodityContract('CRUDEOIL','2026-12-16',7800,'PE','MCX','123','CRUDEOIL16DEC267800PE',100,.1)
    uid=98621
    await place_mcx_paper_order(uid,c,1,100,90,130,now,debate_id='test-v61')
    await place_mcx_paper_order(uid,c,1,100,90,130,now,ledger='champion',debate_id='test-v61')
    results=await asyncio.gather(settle_mcx_positions(uid,{'123':140},now=now),settle_mcx_positions(uid,{'123':140},now=now))
    assert sum(r['settled'] for r in results)==1
    primary=await get_mcx_paper_state(uid);research=await get_mcx_paper_state(uid,ledger='champion')
    assert len(primary['trades'])==1 and not primary['positions']
    assert len(research['positions'])==1 and not research['trades']
    assert abs(primary['cash_balance']-primary['initial_capital']-primary['realized_pnl'])<.02
