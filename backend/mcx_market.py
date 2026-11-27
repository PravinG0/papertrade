"""MCX Crude Oil research and isolated long-option paper ledger.
Exchange calendar must be operator verified. Never infer the option's underlying
future from nearest expiry; show exact future and option series independently.
"""
from datetime import date, datetime, time, timedelta
import math
from zoneinfo import ZoneInfo
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
from session_calendar import parse_holidays, parse_special_sessions, session_bounds

IST = ZoneInfo('Asia/Kolkata')


def mcx_session_bounds(now, *, opening='09:00', closing='23:55', valid_until='2027-03-12',
                       valid_from='2026-11-02', holidays='', special_sessions=''):
    """Current published winter session only, fail closed outside verified dates."""
    if isinstance(now, datetime):
        if now.tzinfo is None:
            raise ValueError('Timezone-aware session timestamp required')
        day = now.astimezone(IST).date()
    else:
        day = now
    if not date.fromisoformat(valid_from) <= day <= date.fromisoformat(valid_until):
        return None
    st, et = time.fromisoformat(opening), time.fromisoformat(closing)
    if st >= et:
        raise ValueError('Invalid MCX session bounds')
    return session_bounds(day, parse_holidays(holidays), parse_special_sessions(special_sessions), st, et)


def configured_mcx_bounds(now):
    from config import settings
    return mcx_session_bounds(now, opening=settings.MCX_SESSION_OPEN, closing=settings.MCX_SESSION_CLOSE,
        valid_until=settings.MCX_SESSION_VALID_UNTIL, valid_from=settings.MCX_SESSION_VALID_FROM,
        holidays=settings.MCX_HOLIDAYS, special_sessions=settings.MCX_SPECIAL_SESSIONS)


def historical_mcx_bounds(day):
    """Operator-verified historical session ranges, only for indicator warm-up."""
    from config import settings
    current = configured_mcx_bounds(day)
    if current:
        return current
    if date.fromisoformat(settings.MCX_SESSION_VALID_FROM) <= day:
        return None
    for item in settings.MCX_HISTORICAL_SESSIONS.split(','):
        if not item.strip():
            continue
        start, end, opening, closing = item.strip().split('/')
        if date.fromisoformat(start) <= day <= date.fromisoformat(end):
            return mcx_session_bounds(day, opening=opening, closing=closing,
                valid_from=start, valid_until=end, holidays=settings.MCX_HOLIDAYS,
                special_sessions=settings.MCX_SPECIAL_SESSIONS)
    return None


@dataclass(frozen=True)
class CommodityContract:
    name: str
    expiry: str
    strike: int
    option_type: str
    exchange: str
    token: str
    symbol: str
    lot_size: int
    tick_size: float


def parse_contract(row, today):
    """MCX standard CRUDEOIL only; reject mini, NCO, malformed and expired rows."""
    if row.get('name') != 'CRUDEOIL' or row.get('exch_seg') != 'MCX':
        return None
    kind = row.get('instrumenttype')
    symbol = str(row.get('symbol') or '')
    if kind == 'FUTCOM' and symbol.endswith('FUT'):
        opt = 'FUT'
    elif kind == 'OPTFUT' and symbol.endswith(('CE','PE')):
        opt = symbol[-2:]
    else:
        return None
    try:
        expiry = datetime.strptime(row['expiry'], '%d%b%Y').date()
        lot = Decimal(str(row['lotsize']))
        tick = Decimal(str(row['tick_size'])) / 100
        strike = Decimal(str(row['strike'])) / 100 if opt != 'FUT' else Decimal(0)
        token = str(row['token'])
        if (expiry < today or not token.isdigit() or not symbol.startswith('CRUDEOIL') or
            not all(v.is_finite() for v in (lot,tick,strike)) or lot <= 0 or lot != int(lot) or
            tick <= 0 or (opt != 'FUT' and (strike <= 0 or strike != int(strike)))):
            return None
        return CommodityContract('CRUDEOIL', expiry.isoformat(), int(strike), opt, 'MCX', token, symbol, int(lot), float(tick))
    except (KeyError, ValueError, TypeError, InvalidOperation, OverflowError):
        return None


def select_contracts(contracts, today, future_symbol=None, expiry=None):
    """Return exact requested future and option expiry, with no silent substitution."""
    active = [c for c in contracts if c.expiry >= today.isoformat()]
    futures = sorted((c for c in active if c.option_type == 'FUT'), key=lambda c:(c.expiry,c.symbol))
    future = next((c for c in futures if c.symbol == future_symbol), None) if future_symbol else (futures[0] if futures else None)
    if future_symbol and future is None:
        raise ValueError('Requested MCX futures contract unavailable')
    options = [c for c in active if c.option_type in ('CE','PE')]
    expiries = sorted({c.expiry for c in options})
    if expiry and expiry not in expiries:
        raise ValueError('Requested MCX option expiry unavailable')
    selected = expiry or (expiries[0] if expiries else None)
    return futures, future, expiries, selected, [c for c in options if c.expiry == selected]


def quote_view(contract, quote):
    result = asdict(contract)
    quote = quote or {}
    depth = quote.get('depth') or {}
    result.update(ltp=quote.get('ltp'), bid=((depth.get('buy') or [{}])[0]).get('price'),
                  ask=((depth.get('sell') or [{}])[0]).get('price'), oi=quote.get('opnInterest'),
                  volume=quote.get('tradeVolume'), transport=quote.get('_transport'),
                  exchange_timestamp=quote.get('exchFeedTime'), status='live' if quote else 'unavailable')
    return result


def calculate_mcx_charges(buy_value: float, sell_value: float) -> dict[str, float]:
    """Angel One MCX Crude Oil options statutory + brokerage charge breakdown."""
    buy_v = max(0.0, float(buy_value))
    sell_v = max(0.0, float(sell_value))
    turnover = buy_v + sell_v
    brokerage = (20.0 if buy_v > 0 else 0.0) + (20.0 if sell_v > 0 else 0.0)
    ctt = round(sell_v * 0.0005, 2)            # 0.05% CTT on MCX option sell value
    txn = round(turnover * 0.0005, 2)          # 0.05% MCX exchange txn charge
    sebi = round(turnover * 0.000001, 2)       # SEBI turnover fee
    stamp = round(buy_v * 0.00003, 2)          # 0.003% stamp duty on buy
    gst = round((brokerage + txn + sebi) * 0.18, 2)
    total = round(brokerage + ctt + txn + sebi + stamp + gst, 2)
    return {
        "brokerage": brokerage,
        "ctt": ctt,
        "exchange_txn": txn,
        "sebi": sebi,
        "stamp_duty": stamp,
        "gst": gst,
        "total_charges": total,
    }


def mcx_technical_summary(candles: list[dict], spot: float) -> dict:
    """Compute commodity technical indicators from genuine MCX futures candles."""
    if not candles or len(candles) < 20:
        return {"available": False, "reason": "Insufficient MCX historical candles (need >= 20)."}
    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    n = len(closes)

    def _ema(vals: list[float], span: int) -> float:
        if len(vals) < span:
            return sum(vals) / max(1, len(vals))
        a = 2.0 / (span + 1.0)
        v = sum(vals[:span]) / span
        for p in vals[span:]:
            v = p * a + v * (1.0 - a)
        return round(v, 2)

    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    gains = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, n)]
    losses = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, n)]
    ag = sum(gains[:14]) / 14.0 if len(gains) >= 14 else sum(gains) / max(1, len(gains))
    al = sum(losses[:14]) / 14.0 if len(losses) >= 14 else sum(losses) / max(1, len(losses))
    for i in range(14, len(gains)):
        ag = (ag * 13.0 + gains[i]) / 14.0
        al = (al * 13.0 + losses[i]) / 14.0
    rsi = 100.0 if al == 0 and ag > 0 else (50.0 if al == 0 else round(100.0 - (100.0 / (1.0 + ag / al)), 2))
    trs = [highs[0] - lows[0]] + [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, n)
    ]
    atr = round(sum(trs[-14:]) / min(14, len(trs)), 2)
    trend = "BULLISH" if (spot or closes[-1]) >= ema20 and ema20 >= ema50 else (
        "BEARISH" if (spot or closes[-1]) < ema20 and ema20 < ema50 else "NEUTRAL"
    )
    return {
        "available": True,
        "ema_20": ema20,
        "ema_50": ema50,
        "rsi": rsi,
        "atr": atr,
        "trend": trend,
        "candle_count": n,
    }


def _empty_mcx_ledger() -> dict:
    return {"initial_capital": 1000000.0, "cash_balance": 1000000.0, "positions": [], "trades": []}


async def get_mcx_paper_state(user_id: int, *, ledger="paper") -> dict:
    from mcx_storage import read
    data = await read(ledger_key(user_id, ledger), _empty_mcx_ledger)
    now = datetime.now(IST)
    positions = [{**p, 'exit_due':position_due(p,now)} for p in data.get("positions", [])]
    trades = data.get("trades", [])
    realized = round(sum(float(t.get("net_pnl") or 0) for t in trades), 2)
    unrealized = round(sum(float(p.get("unrealized_pnl") or 0) for p in positions), 2)
    margin_used = round(sum(float(p.get("entry_price", 0)) * int(p.get("quantity", 0)) for p in positions), 2)
    return {
        "initial_capital": float(data.get("initial_capital", 1000000.0)),
        "cash_balance": round(float(data.get("cash_balance", 1000000.0)), 2),
        "margin_used": margin_used,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "positions": positions,
        "trades": trades,
    }


async def place_mcx_paper_order(
    user_id: int,
    contract: CommodityContract,
    lots: int,
    entry_price: float,
    stop_loss: float,
    target: float,
    now: datetime,
    *, ledger="paper", debate_id=None, guard=None,
) -> dict:
    """Execute an isolated MCX CRUDEOIL option BUY CE/PE paper trade."""
    import uuid
    from mcx_storage import edit
    if contract.option_type not in ("CE", "PE"):
        raise ValueError("Only MCX CRUDEOIL BUY CE / BUY PE option orders are supported.")
    if contract.expiry <= now.astimezone(IST).date().isoformat():
        raise ValueError("MCX expiry-day or expired contract entries are disabled.")
    bounds = configured_mcx_bounds(now)
    if not bounds or not (bounds[0] <= now.astimezone(IST).time() < bounds[1]):
        raise ValueError("MCX Crude Oil market session is closed.")
    if type(lots) is not int or lots <= 0 or lots > 20:
        raise ValueError("Lots must be between 1 and 20.")
    qty = lots * int(contract.lot_size)
    if not all(math.isfinite(float(v)) for v in (entry_price, stop_loss, target)) or not (0 < stop_loss < entry_price < target):
        raise ValueError("Invalid MCX option SL/target geometry (require 0 < stop_loss < entry < target).")
    entry_price, stop_loss, target = (round(float(v), 2) for v in (entry_price, stop_loss, target))
    if not 0 < stop_loss < entry_price < target or qty <= 0:
        raise ValueError("Invalid rounded price or quantity")
    cost = round(entry_price * qty, 2)

    async with edit(ledger_key(user_id, ledger), _empty_mcx_ledger) as data:
        if debate_id and any(p.get('debate_id') == debate_id for p in data.get('positions', []) + data.get('trades', [])):
            raise ValueError("MCX debate already executed in this wallet")
        if guard:
            guard(data)
        cash = float(data.get("cash_balance", 1000000.0))
        if cost > cash:
            raise ValueError(f"Insufficient MCX paper cash (need ₹{cost:.2f}, available ₹{cash:.2f}).")
        pos = {
            "id": f"MCX-{uuid.uuid4().hex[:8].upper()}",
            "symbol": contract.symbol,
            "token": contract.token,
            "exchange": "MCX",
            "expiry": contract.expiry,
            "strike": contract.strike,
            "option_type": contract.option_type,
            "side": "BUY",
            "lots": lots,
            "lot_size": int(contract.lot_size),
            "quantity": qty,
            "entry_price": round(float(entry_price), 2),
            "ltp": round(float(entry_price), 2),
            "stop_loss": round(float(stop_loss), 2),
            "target": round(float(target), 2),
            "unrealized_pnl": 0.0,
            "entered_at": now.astimezone(IST).isoformat(),
            "status": "OPEN",
            "debate_id": debate_id,
            "source": "AI" if debate_id else "MANUAL",
        }
        data["cash_balance"] = round(cash - cost, 2)
        data.setdefault("positions", []).insert(0, pos)
    return {"status": "FILLED", "position": pos, "cash_balance": data["cash_balance"]}


async def settle_mcx_positions(user_id: int, quotes_by_token: dict[str, float], *, force_squareoff: bool = False, ledger="paper", eligible_ids=None, now=None, due_only=False) -> dict:
    """Update MTM and settle SL/Target/Square-off on genuine MCX quotes only."""
    from mcx_storage import edit
    now = now or datetime.now(IST)
    settled = 0
    async with edit(ledger_key(user_id, ledger), _empty_mcx_ledger) as data:
        remaining = []
        for p in data.get("positions", []):
            ltp = quotes_by_token.get(str(p.get("token")))
            if (eligible_ids is not None and p.get('id') not in eligible_ids) or ltp is None or not math.isfinite(ltp) or ltp <= 0:
                remaining.append(p)
                continue
            p["ltp"] = round(float(ltp), 2)
            p["last_monitored_at"] = now.isoformat()
            qty = int(p["quantity"])
            buy_val = float(p["entry_price"]) * qty
            sell_val = float(ltp) * qty
            p["unrealized_pnl"] = round(sell_val - buy_val, 2)
            reason = None
            if force_squareoff or (due_only and position_due(p, now)):
                reason = "MCX_SESSION_SQUAREOFF"
            elif ltp <= float(p["stop_loss"]):
                reason = "STOP_LOSS_HIT"
            elif ltp >= float(p["target"]):
                reason = "TARGET_HIT"
            if reason:
                chg = calculate_mcx_charges(buy_val, sell_val)["total_charges"]
                net = round((sell_val - buy_val) - chg, 2)
                data["cash_balance"] = round(float(data.get("cash_balance", 0)) + sell_val - chg, 2)
                closed = {**p, "status": "CLOSED", "exit_price": round(float(ltp), 2), "exit_reason": reason,
                          "charges": chg, "net_pnl": net, "closed_at": now.isoformat()}
                data.setdefault("trades", []).insert(0, closed)
                settled += 1
            else:
                remaining.append(p)
        data["positions"] = remaining
    return {"settled": settled, "cash_balance": data["cash_balance"]}


def ledger_key(user_id, ledger):
    if ledger not in ('paper', 'champion', 'challenger'):
        raise ValueError('Invalid MCX ledger')
    return f'mcx-{ledger}:{int(user_id)}'


def position_due(position, now, bounds_fn=configured_mcx_bounds):
    """Square off two minutes before close, or recover on a later session."""
    from adaptive_memory import parse_time
    entered = parse_time(position.get('entered_at'))
    if not entered:
        return False
    bounds = bounds_fn(now)
    return bool(entered.date() < now.astimezone(IST).date() or (bounds and
        now >= datetime.combine(now.astimezone(IST).date(), bounds[1], IST) - timedelta(minutes=2)))
