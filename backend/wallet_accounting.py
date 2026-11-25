"""Separate account equity from trading performance without rewriting historical balances."""

def wallet_accounting(initial, cash, margin, realized, unrealized, reset_baseline=0.0):
    equity = round(cash + margin + unrealized, 2)
    trade_pnl = round(realized - reset_baseline + unrealized, 2)
    account_pnl = round(equity - initial, 2)
    return {
        'net_liquidation_value': equity,
        'account_net_pnl': account_pnl,
        'current_cycle_trade_pnl': trade_pnl,
        'historical_balance_difference': round(account_pnl - trade_pnl, 2),
        'reset_realized_baseline': round(reset_baseline, 2),
    }


def position_margin(positions):
    """The simulator reserves rounded entry premium for both BUY and SELL."""
    return round(sum(round(float(p['entry_price']) * int(p['quantity']), 2)
                     for p in positions if p['status'] == 'ACTIVE'), 2)


def reconciliation_preview(initial, cash, stored_margin, trades, baseline=0.0):
    """Reconstruct cash from recorded net P&L, not from a stale reserve.

    Only valid when the ledger is complete and baseline/starting capital are verified.
    This function never writes anything and does not include unrealized P&L in cash.
    """
    import math
    issues = []
    def finite(value):
        try:
            v = float(value)
            return v if math.isfinite(v) else None
        except (TypeError, ValueError, OverflowError):
            return None
    initial, cash, stored_margin, baseline = map(finite, (initial, cash, stored_margin, baseline))
    if None in (initial, cash, stored_margin, baseline):
        issues.append('Invalid wallet values.')
    closed_count = active_count = 0
    margin = net = 0.0
    for p in trades:
        ident = p.get('id', '?')
        status = p.get('status')
        if status not in ('ACTIVE', 'CLOSED'):
            issues.append(f'Invalid status: {ident}'); continue
        closed_count += status == 'CLOSED'
        active_count += status == 'ACTIVE'
        entry, qty, realized, gross, charges = (finite(p.get(k)) for k in ('entry_price', 'quantity', 'realized_pnl', 'gross_pnl', 'total_charges'))
        if None in (entry, qty, realized, gross, charges) or entry <= 0 or qty <= 0 or not qty.is_integer() or charges < 0 or p.get('side') not in ('BUY', 'SELL'):
            issues.append(f'Invalid trade values: {ident}'); continue
        if status == 'ACTIVE':
            margin += round(entry * qty, 2); continue
        exit_p = finite(p.get('exit_price'))
        if exit_p is None or exit_p <= 0:
            issues.append(f'Missing/invalid exit price: {ident}'); continue
        expected_gross = round((exit_p - entry) * qty * (1 if p['side'] == 'BUY' else -1), 2)
        if abs(expected_gross - gross) > .011 or abs(round(gross - charges, 2) - realized) > .011:
            issues.append(f'Trade P&L inconsistent: {ident}')
        net += realized
    if not issues:
        margin, net = round(margin, 2), round(net - baseline, 2)
        expected = round(initial + net - margin, 2)
        if not all(math.isfinite(x) for x in (margin, net, expected, expected - cash, margin - stored_margin)):
            issues.append('Non-finite computed wallet values.')
    return {'initial_capital': initial, 'baseline': baseline, 'closed_count': closed_count,
            'active_count': active_count, 'cycle_realized_pnl': None if issues else net,
            'stored_cash': cash, 'stored_margin': stored_margin, 'expected_cash': None if issues else expected,
            'expected_margin': None if issues else margin, 'cash_adjustment': None if issues else round(expected - cash, 2),
            'margin_adjustment': None if issues else round(margin - stored_margin, 2), 'issues': issues}
