from wallet_accounting import wallet_accounting


def test_open_margin_is_not_a_loss():
    state = wallet_accounting(1000000, 990000, 10000, 0, 250)
    assert state['net_liquidation_value'] == 1000250
    assert state['account_net_pnl'] == 250
    assert state['historical_balance_difference'] == 0


def test_closed_trade_and_reset_baseline():
    assert wallet_accounting(1000000, 999500, 0, -500, 0)['account_net_pnl'] == -500
    reset = wallet_accounting(1000000, 1000000, 0, -500, 0, -500)
    assert reset['current_cycle_trade_pnl'] == reset['account_net_pnl'] == 0
    later = wallet_accounting(1000000, 1000250, 0, -250, 0, -500)
    assert later['account_net_pnl'] == later['current_cycle_trade_pnl'] == 250


def test_legacy_difference_is_reported_not_hidden():
    state = wallet_accounting(1000000, 953687.19, 0, -9748.44, 0)
    assert state['account_net_pnl'] == -46312.81
    assert state['current_cycle_trade_pnl'] == -9748.44
    assert state['historical_balance_difference'] == -36564.37
