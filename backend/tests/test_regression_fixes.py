"""Runtime regression tests; run after installing backend requirements."""
import pytest
from paper_engine import PaperEngine
from database import init_db
from main import ConnectionManager


def order(**overrides):
    base = dict(symbol='NIFTY31DEC9925000CE', underlying='NIFTY', strike=25000,
                option_type='CE', side='BUY', order_type='MARKET', lots=1,
                price=100, current_ltp=100)
    return {**base, **overrides}


@pytest.mark.asyncio
async def test_websocket_account_isolation():
    class Socket:
        def __init__(self): self.messages = []
        async def accept(self): pass
        async def send_json(self, data): self.messages.append(data)
    manager = ConnectionManager()
    a, b, guest = Socket(), Socket(), Socket()
    for sock, uid in [(a, 1), (b, 2), (guest, None)]:
        await manager.connect(sock, uid)
    await manager.broadcast({'type': 'ORDER_UPDATE', 'user_id': 1})
    assert len(a.messages) == 1 and not b.messages and not guest.messages
    await manager.broadcast({'type': 'TICK'})
    assert all(x.messages[-1]['type'] == 'TICK' for x in [a, b, guest])


@pytest.mark.asyncio
async def test_market_hours_reject_pending(monkeypatch):
    engine = PaperEngine()
    monkeypatch.setattr(engine, 'entry_window_open', lambda: False)
    assert (await engine.place_order(order(order_type='LIMIT')))['status'] == 'REJECTED'


@pytest.mark.asyncio
async def test_invalid_market_price_rejected():
    engine = PaperEngine()
    assert (await engine.place_order(order(price=0, current_ltp=0), enforce_hours=False))['status'] == 'REJECTED'
    assert (await engine.place_order(order(side='INVALID'), enforce_hours=False))['status'] == 'REJECTED'


@pytest.mark.asyncio
async def test_gap_stop_uses_observed_ltp():
    await init_db()
    engine = PaperEngine()
    await engine.reset_portfolio(1000000)
    placed = await engine.place_order(order(stop_loss=90), enforce_hours=False)
    await engine.update_market_prices({order()['symbol']: 75})
    history = await engine.get_history()
    trade = next(t for t in history if t['id'] == placed['position_id'])
    assert trade['exit_reason'] == 'STOP_LOSS_HIT' and trade['exit_price'] == 75


@pytest.mark.asyncio
async def test_pending_fill_rechecks_balance_and_restores():
    await init_db()
    engine = PaperEngine()
    await engine.reset_portfolio(100)
    pending = await engine.place_order(order(order_type='LIMIT'), enforce_hours=False)
    assert pending['status'] == 'PENDING'
    restored = PaperEngine()
    await restored.restore_from_db()
    assert pending['order_id'] in restored.active_orders
    await restored.update_market_prices({order()['symbol']: 99})
    assert pending['order_id'] not in restored.active_orders
    state = await restored.get_state()
    assert state['portfolio']['available_margin'] == 100
    assert not state['positions']
