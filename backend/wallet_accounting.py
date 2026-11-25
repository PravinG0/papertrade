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
