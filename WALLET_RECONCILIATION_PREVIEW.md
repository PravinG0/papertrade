# Historical Wallet Reconciliation Preview (`QA-24`)

**Date:** 26 November 2026  
**Policy:** Read-only preview ONLY. Zero balances, trade records, or baselines were modified automatically.

## 1. Local Development Database (`backend/papertrade.db`) Read-Only Preview

Executed read-only audit against local SQLite portfolios (`mode=ro`, no writes):

| Portfolio ID | User ID | Initial Capital (₹) | Baseline (₹) | Closed Trades | Active Trades | Cycle Net P&L (₹) | Stored Cash (₹) | Stored Margin (₹) | Expected Cash (₹) | Expected Margin (₹) | Cash Adjustment (₹) | Margin Adjustment (₹) | Issues |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | `NULL` (Guest) | 1,000,000.00 | 0.00 | 6 | 0 | +1,153.05 | 1,000,000.00 | 0.00 | 1,001,153.05 | 0.00 | +1,153.05 | 0.00 | `[]` |
| 2 | `1` | 1,000,000.00 | 0.00 | 0 | 0 | 0.00 | 1,000,000.00 | 0.00 | 1,000,000.00 | 0.00 | 0.00 | 0.00 | `[]` |
| 3 | `2` | 1,000,000.00 | 0.00 | 0 | 0 | 0.00 | 1,000,000.00 | 0.00 | 1,000,000.00 | 0.00 | 0.00 | 0.00 | `[]` |

- **Guest (`portfolio_id=1`) Root Cause:** Contains 6 historical closed dev trades (`+445.92` manual exit, `-1,181.58` SL hits, `+1,888.71` target hits, `0.00` wallet reset = `+1,153.05` total) while a prior reset restored `cash_balance` to `1,000,000.00` before `wallet-reset-baseline:1` tracking existed in `app_kv`. No repair was applied.

## 2. Production Screenshot Reference Example (Conditional — Not a Live Supabase Query)

Per `WALLET_RECONCILIATION.md` arithmetic check against the user-provided screenshot (`initial=1,000,000.00`, `cash=953,687.19`, `stored_margin=44,534.75`, `trade_pnl=-9,748.44`, assuming `0` open trades & `0.00` baseline):
- Expected active reserve: `₹0.00` (`margin_adjustment: -₹44,534.75`, which matches displayed `stored_margin - used_margin` without overwriting cash).
- Conditional expected cash: `1,000,000.00 - 9,748.44 = ₹990,251.56` (`cash_adjustment: +₹36,564.37`).
- **Important:** Do NOT apply these figures blindly. First verify complete Supabase trade history, reset baselines, prior duplicate settlements, or replay provenance using the operator CLI below.

## 3. Live Supabase Preview Procedure (Operator Action Required)

Because live Supabase PostgreSQL credentials are stored only on Render (not local `.env`), execute the read-only preview safely from a private shell after stopping trading workers:

```bash
cd backend
DATABASE_URL="postgresql://..." python3 reconcile_wallet.py --user-id <YOUR_NUMERIC_USER_ID>
```

Note that `reconcile_wallet.py` was hardened to gracefully inspect whether optional tables (like `pending_paper_orders`) exist before querying, prints a SHA-256 fingerprint token covering the exact ledger snapshot, and refuses `--apply` unless `--verified-ledger`, matching `--confirm <TOKEN>`, `active_count == 0`, and `pending_count == 0` all hold.
