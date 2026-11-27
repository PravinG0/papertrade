# TradeLab Cloud V6 — Shadow Trading & Dynamic Risk Report

**Date:** 27 November 2026

## Verification Summary (`test_v6_complete.py`)
1. **Shadow Trading & Champion vs Challenger (`backend/shadow_engine.py`):**
   - `record_debate_opportunity` records both V6-accepted and V6-rejected AI proposals in `app_kv` (`shadow-ledger:<user_id>`).
   - Champion (original AI proposals) and Challenger (V6 quant-validated proposals) track independent virtual ₹10,00,000 research wallets.
   - `update_shadow_positions` settles open shadow positions only on genuine live quotes (never fabricates exits) and deducts statutory charges.
   - Primary `portfolios` and `paper_trades` are never touched by shadow trades.
2. **Dynamic Risk-Based Trade Limits (`backend/adaptive_store.py`):**
   - Configurable per-user settings (`risk-config:<user_id>`) support `max_daily_trades`, `no_count_limit` experimental mode, `max_daily_loss_inr`, `max_concurrent_positions`, `max_consecutive_losses`, and `loss_streak_cooldown_minutes` + `repeat_strike_cooldown_minutes`.
   - Verified `guard_auto_fill` blocks execution when `daily_pnl <= -max_daily_loss_inr`, while `no_count_limit=True` bypasses the 5-trade count cap without weakening loss/cooldown/concurrency checks.
