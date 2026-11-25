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


from wallet_accounting import position_margin, reconciliation_preview


def sample_trade(**overrides):
    return dict(id='test', status='CLOSED', entry_price=200, exit_price=100,
                quantity=97, side='BUY', gross_pnl=-9700, total_charges=48.44,
                realized_pnl=-9748.44, **overrides) if not overrides else {
                    **sample_trade(), **overrides}


def test_screenshot_repair_preview():
    preview = reconciliation_preview(1000000, 953687.19, 44534.75, [sample_trade()])
    assert preview['expected_cash'] == 990251.56
    assert preview['expected_margin'] == 0
    assert preview['cash_adjustment'] == 36564.37
    assert preview['margin_adjustment'] == -44534.75
    assert preview['issues'] == []


def test_reserve_only_counts_active_rows():
    trades = [sample_trade(), sample_trade(id='open', status='ACTIVE', entry_price=100.01,
                                          quantity=65, exit_price=None, gross_pnl=0,
                                          total_charges=0, realized_pnl=0)]
    assert position_margin(trades) == 6500.65
    preview = reconciliation_preview(1000000, 990000, 50000, trades, baseline=-9748.44)
    assert preview['expected_cash'] == 993499.35
    assert preview['cycle_realized_pnl'] == 0


def test_repair_refuses_inconsistent_trade_arithmetic():
    preview = reconciliation_preview(1000000, 990000, 0, [sample_trade(realized_pnl=0)])
    assert preview['issues']


def test_repair_checks_missing_exit():
    preview = reconciliation_preview(1000000, 990000, 0, [sample_trade(exit_price=None)])
    assert preview['issues']
