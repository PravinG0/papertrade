"""Live Shadow Trading, Champion vs Challenger comparison, and Dynamic Risk Settings.

All state is stored per-user in existing `app_kv` rows (`shadow-ledger:<uid>`, `risk-config:<uid>`).
Never modifies primary `portfolios` or `paper_trades` tables and requires no schema migration.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from database import AppKVModel, async_session_factory
from paper_engine import calculate_trade_charges

logger = logging.getLogger("shadow_engine")
IST = ZoneInfo("Asia/Kolkata")

DEFAULT_RISK_CONFIG: dict[str, Any] = {
    "max_daily_trades": 5,           # 0 => no-count-limit experimental mode
    "no_count_limit": False,
    "max_daily_loss_inr": 3500.0,
    "max_risk_per_trade_inr": 1000.0,
    "max_open_risk_inr": 2500.0,
    "max_concurrent_positions": 3,
    "max_consecutive_losses": 3,
    "loss_streak_cooldown_minutes": 45,
    "repeat_strike_cooldown_minutes": 30,
    "min_net_rr": 1.5,
    "min_confidence": 8,
}

_locks: dict[int, asyncio.Lock] = {}


def _user_lock(user_id: int) -> asyncio.Lock:
    lock = _locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[user_id] = lock
    return lock


def _empty_ledger() -> dict[str, Any]:
    return {
        "champion_capital": 1000000.0,
        "challenger_capital": 1000000.0,
        "opportunities": [],   # bounded latest 250 recorded proposals (accepted + rejected)
        "champion_trades": [], # bounded latest 250
        "challenger_trades": [],
    }


async def _load_kv(session, key: str, default: dict[str, Any]) -> dict[str, Any]:
    row = await session.get(AppKVModel, key)
    if not row or not row.value:
        return json.loads(json.dumps(default))
    try:
        data = json.loads(row.value)
        if isinstance(data, dict):
            return data
    except (ValueError, TypeError):
        pass
    return json.loads(json.dumps(default))


async def _save_kv(session, key: str, data: dict[str, Any]) -> None:
    payload = json.dumps(data, default=str)
    row = await session.get(AppKVModel, key)
    if row is None:
        session.add(AppKVModel(key=key, value=payload))
    else:
        row.value = payload


async def get_risk_settings(user_id: Optional[int]) -> dict[str, Any]:
    if user_id is None:
        return dict(DEFAULT_RISK_CONFIG)
    async with async_session_factory() as session:
        stored = await _load_kv(session, f"risk-config:{user_id}", DEFAULT_RISK_CONFIG)
    merged = {**DEFAULT_RISK_CONFIG, **stored}
    return merged


async def update_risk_settings(user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    async with _user_lock(user_id):
        async with async_session_factory() as session:
            cur = await _load_kv(session, f"risk-config:{user_id}", DEFAULT_RISK_CONFIG)
            for k, default_v in DEFAULT_RISK_CONFIG.items():
                if k not in patch or patch[k] is None:
                    continue
                if isinstance(default_v, bool):
                    cur[k] = bool(patch[k])
                elif isinstance(default_v, int):
                    cur[k] = max(0, int(patch[k]))
                elif isinstance(default_v, float):
                    cur[k] = max(0.0, float(patch[k]))
            if cur.get("no_count_limit"):
                cur["max_daily_trades"] = 0
            await _save_kv(session, f"risk-config:{user_id}", cur)
            await session.commit()
            return {**DEFAULT_RISK_CONFIG, **cur}


def _wallet_stats(trades: list[dict[str, Any]], initial_capital: float = 1000000.0) -> dict[str, Any]:
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    open_trades = [t for t in trades if t.get("status") == "OPEN"]
    wins = [t for t in closed if float(t.get("net_pnl") or 0) > 0]
    losses = [t for t in closed if float(t.get("net_pnl") or 0) <= 0]
    target_hits = sum(1 for t in closed if t.get("exit_reason") == "TARGET_HIT")
    sl_hits = sum(1 for t in closed if t.get("exit_reason") == "STOP_LOSS_HIT")
    net_pnl = round(sum(float(t.get("net_pnl") or 0) for t in closed), 2)
    fees = round(sum(float(t.get("charges") or 0) for t in closed), 2)
    gross_wins = sum(float(t.get("net_pnl") or 0) for t in wins)
    gross_losses = abs(sum(float(t.get("net_pnl") or 0) for t in losses))
    pf = round(gross_wins / gross_losses, 2) if gross_losses > 0 else (99.0 if gross_wins > 0 else 0.0)

    # Max realized equity drawdown
    eq = initial_capital
    peak = initial_capital
    max_dd = 0.0
    for t in closed:
        eq += float(t.get("net_pnl") or 0)
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)

    n = len(closed)
    return {
        "open_count": len(open_trades),
        "closed_count": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round((len(wins) / n) * 100.0, 1) if n else 0.0,
        "target_hit_rate": round((target_hits / n) * 100.0, 1) if n else 0.0,
        "stop_loss_rate": round((sl_hits / n) * 100.0, 1) if n else 0.0,
        "net_pnl": net_pnl,
        "fees": fees,
        "profit_factor": pf,
        "max_drawdown": round(max_dd, 2),
        "expectancy": round(net_pnl / n, 2) if n else 0.0,
        "ending_capital": round(initial_capital + net_pnl, 2),
    }


async def record_debate_opportunity(user_id: Optional[int], session_obj: Any) -> None:
    """Record accepted & rejected AI debate proposals for Shadow / Champion-vs-Challenger tracking."""
    if user_id is None:
        return
    try:
        orig_verdict = str(
            getattr(session_obj, "original_judge_verdict", None) or session_obj.judge.verdict or "NO_TRADE"
        ).upper()
        qv = getattr(session_obj, "quantitative_validation", None) or {}
        chall_ok = bool(qv.get("eligible")) and orig_verdict in ("BUY CE", "BUY PE")
        reasons = list(qv.get("reasons") or [])
        opt_info = qv.get("option") or {}
        entry = float(opt_info.get("entry_price") or session_obj.judge.entry_price or 0.0)
        sl = float(session_obj.judge.stop_loss or 0.0)
        tgt = float(session_obj.judge.target or 0.0)
        qty = int(opt_info.get("quantity") or 65)
        contract_sym = opt_info.get("symbol") or f"{session_obj.symbol}{int(session_obj.judge.recommended_strike or 0)}{orig_verdict[-2:] if orig_verdict in ('BUY CE', 'BUY PE') else ''}"

        opp = {
            "id": f"opp-{uuid.uuid4().hex[:10]}",
            "debate_id": session_obj.id,
            "timestamp": session_obj.timestamp,
            "symbol": session_obj.symbol,
            "original_verdict": orig_verdict,
            "final_verdict": session_obj.judge.verdict,
            "challenger_eligible": chall_ok,
            "reasons": reasons[:6],
            "contract": contract_sym,
            "entry_price": round(entry, 2),
            "stop_loss": round(sl, 2),
            "target": round(tgt, 2),
            "quantity": qty,
            "confidence": int(session_obj.judge.confidence or 0),
            "regime": getattr(session_obj.market_snapshot, "market_regime", "UNKNOWN"),
        }

        async with _user_lock(user_id):
            async with async_session_factory() as db:
                ledger = await _load_kv(db, f"shadow-ledger:{user_id}", _empty_ledger())
                ledger["opportunities"] = ([opp] + ledger.get("opportunities", []))[:250]

                if orig_verdict in ("BUY CE", "BUY PE") and 0 < sl < entry < tgt and qty > 0:
                    base_trade = {
                        "id": f"shd-{uuid.uuid4().hex[:10]}",
                        "debate_id": session_obj.id,
                        "symbol": contract_sym,
                        "underlying": session_obj.symbol,
                        "option_type": orig_verdict[-2:],
                        "quantity": qty,
                        "entry_price": round(entry, 2),
                        "stop_loss": round(sl, 2),
                        "target": round(tgt, 2),
                        "status": "OPEN",
                        "entered_at": datetime.now(IST).isoformat(),
                        "net_pnl": 0.0,
                        "charges": 0.0,
                        "exit_reason": None,
                        "exit_price": None,
                    }
                    # Champion tracks original AI BUY proposals (max 10 open)
                    champ_open = sum(1 for t in ledger["champion_trades"] if t.get("status") == "OPEN")
                    if champ_open < 10:
                        ledger["champion_trades"] = ([dict(base_trade, engine="champion")] + ledger["champion_trades"])[:250]

                    # Challenger tracks V6 quant-approved proposals only
                    if chall_ok:
                        chall_open = sum(1 for t in ledger["challenger_trades"] if t.get("status") == "OPEN")
                        if chall_open < 10:
                            ledger["challenger_trades"] = ([dict(base_trade, id=f"shd-{uuid.uuid4().hex[:10]}", engine="challenger")] + ledger["challenger_trades"])[:250]

                await _save_kv(db, f"shadow-ledger:{user_id}", ledger)
                await db.commit()
    except Exception as exc:
        logger.debug("Shadow opportunity record skipped: %s", exc)


async def update_shadow_positions(user_id: int, quotes_by_symbol: dict[str, float]) -> int:
    """Settle open shadow trades against genuine live quotes (never fabricated prices)."""
    if not quotes_by_symbol:
        return 0
    settled = 0
    async with _user_lock(user_id):
        async with async_session_factory() as db:
            ledger = await _load_kv(db, f"shadow-ledger:{user_id}", _empty_ledger())
            now_str = datetime.now(IST).isoformat()
            for bucket in ("champion_trades", "challenger_trades"):
                for t in ledger.get(bucket, []):
                    if t.get("status") != "OPEN":
                        continue
                    ltp = quotes_by_symbol.get(t.get("symbol"))
                    if ltp is None or ltp <= 0:
                        continue
                    reason = None
                    if ltp <= float(t["stop_loss"]):
                        reason = "STOP_LOSS_HIT"
                    elif ltp >= float(t["target"]):
                        reason = "TARGET_HIT"
                    if reason:
                        qty = int(t["quantity"])
                        buy_val = float(t["entry_price"]) * qty
                        sell_val = float(ltp) * qty
                        chg = float(calculate_trade_charges(buy_val, sell_val)["total_charges"])
                        net = round((sell_val - buy_val) - chg, 2)
                        t["status"] = "CLOSED"
                        t["exit_price"] = round(float(ltp), 2)
                        t["exit_reason"] = reason
                        t["closed_at"] = now_str
                        t["charges"] = round(chg, 2)
                        t["net_pnl"] = net
                        settled += 1
            if settled:
                await _save_kv(db, f"shadow-ledger:{user_id}", ledger)
                await db.commit()
    return settled


async def get_shadow_summary(user_id: Optional[int]) -> dict[str, Any]:
    if user_id is None:
        return {
            "opportunities_total": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "champion": _wallet_stats([]),
            "challenger": _wallet_stats([]),
            "recent_opportunities": [],
            "recent_trades": [],
            "shared_debate_note": "Shared AI debate with independent Champion (original AI) and Challenger (V6 quant-validated) virtual research wallets. Isolated from primary paper wallet.",
        }
    async with async_session_factory() as db:
        ledger = await _load_kv(db, f"shadow-ledger:{user_id}", _empty_ledger())
    opps = ledger.get("opportunities", [])
    champ_trades = ledger.get("champion_trades", [])
    chall_trades = ledger.get("challenger_trades", [])
    accepted = sum(1 for o in opps if o.get("challenger_eligible"))
    rejected = sum(1 for o in opps if o.get("original_verdict") in ("BUY CE", "BUY PE") and not o.get("challenger_eligible"))
    return {
        "opportunities_total": len(opps),
        "accepted_count": accepted,
        "rejected_count": rejected,
        "champion": _wallet_stats(champ_trades, float(ledger.get("champion_capital", 1000000.0))),
        "challenger": _wallet_stats(chall_trades, float(ledger.get("challenger_capital", 1000000.0))),
        "recent_opportunities": opps[:20],
        "recent_trades": (chall_trades[:10] + champ_trades[:10])[:20],
        "shared_debate_note": "Shared AI debate with independent Champion (original AI) and Challenger (V6 quant-validated) virtual research wallets. Isolated from primary paper wallet.",
    }
