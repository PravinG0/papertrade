"""Isolated database tests; require backend requirements, no live API calls."""
import asyncio
import pytest
from sqlalchemy import select
from database import init_db, async_session_factory, PortfolioModel
from paper_engine import PaperEngine


def order(**kw):
    return dict(symbol='NIFTY31DEC9925000CE', underlying='NIFTY', strike=25000,
                option_type='CE', side='BUY', order_type='MARKET', lots=1,
                price=100, current_ltp=100, **kw)


@pytest.mark.asyncio
async def test_two_engines_cannot_settle_same_trade_twice():
    await init_db()
    a, b = PaperEngine(), PaperEngine()
    await a.reset_portfolio(1000000)
    fill = await a.place_order(order(stop_loss=90), enforce_hours=False)
    pid = fill['position_id']
    await b.restore_from_db()
    results = await asyncio.gather(a.exit_position(pid, exit_price=80), b.exit_position(pid, exit_price=80))
    assert sum(r['status'] == 'SUCCESS' for r in results) == 1
    state = await a.get_state()
    assert state['wallet']['used_margin'] == 0
    assert state['wallet']['historical_balance_difference'] == 0
    assert not state['positions']


@pytest.mark.asyncio
async def test_stale_automatic_exit_after_manual_close():
    await init_db()
    a, b = PaperEngine(), PaperEngine()
    await a.reset_portfolio(1000000)
    fill = await a.place_order(order(stop_loss=90), enforce_hours=False)
    await b.restore_from_db()
    await a.exit_position(fill['position_id'], exit_price=80)
    before = (await a.get_state())['wallet']
    await b.update_market_prices({order()['symbol']: 75})
    after = (await b.get_state())['wallet']
    assert before == after
    assert after['historical_balance_difference'] == 0


@pytest.mark.asyncio
async def test_stored_orphan_margin_is_reported_not_counted():
    await init_db()
    a = PaperEngine()
    await a.reset_portfolio(1000000)
    async with async_session_factory() as s:
        port = (await s.execute(select(PortfolioModel).where(PortfolioModel.user_id.is_(None)))).scalars().first()
        port.margin_used = 44534.75
        await s.commit()
    state = await a.get_state()
    assert state['wallet']['used_margin'] == 0
    assert state['wallet']['stored_margin'] == 44534.75
    assert state['wallet']['margin_discrepancy'] == 44534.75
    assert state['wallet']['net_liquidation_value'] == 1000000


@pytest.mark.asyncio
async def test_stale_pending_order_cannot_fill_twice():
    await init_db()
    a, b = PaperEngine(), PaperEngine()
    await a.reset_portfolio(1000000)
    req = {**order(), 'order_type': 'LIMIT'}
    pending = await a.place_order(req, enforce_hours=False)
    assert pending['status'] == 'PENDING'
    await b.restore_from_db()
    await asyncio.gather(a.update_market_prices({req['symbol']: 99}), b.update_market_prices({req['symbol']: 99}))
    state = await a.get_state()
    assert len(state['positions']) == 1
    assert state['wallet']['historical_balance_difference'] == 0
