"""Operator-only wallet repair; dry run by default. Stop all trading workers first."""
import argparse
import asyncio
import hashlib
import json
import os
import uuid
from sqlalchemy import inspect, select, update
from database import async_session_factory, engine, PortfolioModel, PaperTradeModel, PendingOrderModel, AppKVModel, ist_now_str
from wallet_accounting import reconciliation_preview

async def run(args):
    if not os.environ.get('DATABASE_URL'):
        raise SystemExit('Set DATABASE_URL explicitly in your private shell; refusing implicit database.')
    async with async_session_factory() as session:
        # Lock before reading on apply. Preview never updates any row.
        if args.apply:
            await session.execute(update(PortfolioModel).where(PortfolioModel.user_id == args.user_id)
                                  .values(updated_at=PortfolioModel.updated_at))
        port = (await session.execute(select(PortfolioModel).where(PortfolioModel.user_id == args.user_id))).scalar_one_or_none()
        if port is None:
            raise SystemExit('No portfolio for this user ID.')
        trades = (await session.execute(select(PaperTradeModel).where(PaperTradeModel.user_id == args.user_id).order_by(PaperTradeModel.id))).scalars().all()
        baseline_row = await session.get(AppKVModel, f'wallet-reset-baseline:{port.id}')
        baseline = baseline_row.value if baseline_row else 0.0
        rows = [t.to_dict() for t in trades]
        preview = reconciliation_preview(port.initial_capital, port.cash_balance, port.margin_used, rows, baseline)
        preview.update(user_id=args.user_id, portfolio_id=port.id, reset_baseline_present=baseline_row is not None)
        conn = await session.connection()
        has_pending_table = await conn.run_sync(lambda c: inspect(c).has_table('pending_paper_orders'))
        pending = (await session.execute(select(PendingOrderModel.id).where(PendingOrderModel.user_id == args.user_id))).scalars().all() if has_pending_table else []
        preview["pending_count"] = len(pending)
        if preview['issues']:
            print(json.dumps(preview, indent=2, allow_nan=False))
            raise SystemExit('Repair refused: invalid ledger or wallet values.')
        # Hash exact inputs, not just totals; changes invalidate approval.
        try:
            payload = json.dumps({'preview': preview, 'trades': rows, 'updated_at': port.updated_at}, sort_keys=True, allow_nan=False)
        except (ValueError, TypeError):
            raise SystemExit('Repair refused: raw ledger contains non-serializable or non-finite values.')
        token = hashlib.sha256(payload.encode()).hexdigest()
        print(json.dumps({**preview, 'confirmation_token': token}, indent=2, allow_nan=False))
        if not args.apply:
            print('Preview only. No balance changed. Verify complete ledger, reset history and starting capital.')
            return
        if args.confirm != token or not args.verified_ledger or preview['issues'] or preview['active_count'] or preview['pending_count']:
            raise SystemExit('Repair refused: token mismatch, unverified ledger, inconsistent records, open positions or pending orders.')
        if not preview['cash_adjustment'] and not preview['margin_adjustment']:
            print('Already reconciled; no changes.'); return
        # Keep before/after evidence in an existing table, atomically with repair.
        audit_key = f'wallet-repair:{uuid.uuid4().hex}'
        session.add(AppKVModel(key=audit_key, value=json.dumps({**preview, 'confirmation_token': token, 'timestamp': ist_now_str()})))
        port.cash_balance = preview['expected_cash']
        port.margin_used = preview['expected_margin']
        port.updated_at = ist_now_str()
        await session.commit()
        print(f'Repair committed. Audit record: {audit_key}')

async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--user-id', type=int, required=True)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--confirm')
    p.add_argument('--verified-ledger', action='store_true', help='Confirm complete ledger, starting capital, reset baseline and no other cash adjustments.')
    try:
        await run(p.parse_args())
    finally:
        await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
