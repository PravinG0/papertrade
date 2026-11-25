# Final QA Status & Test Report (QA-01 through QA-25)

**Verification Date:** 26 November 2026  
**Environment:** Local Python 3.12 (`aiosqlite`, `asyncpg`, `sqlalchemy`, `fastapi`, `httpx`), Node.js v20+, Vite 5.4.21, isolated temp SQLite test DB (`conftest.py`).

## 1. Test Execution Results (Post-Final Edit)

| Check | Command | Outcome | Notes |
|---|---|---|---|
| Python Syntax | `python3 -m py_compile backend/*.py backend/agents/*.py backend/tests/*.py` | **PASS** (0 errors) | All backend source & test modules |
| Full Backend Pytest | `cd backend && PYTHONPATH=. python3 -m pytest -v` | **237 PASSED, 0 FAILED** (34.04s) | Includes all integration, concurrency, settlement, adaptive, offline & audit suites |
| Frontend JS Unit Tests | `cd frontend && node --test tests/*.test.js` | **28 PASSED, 0 FAILED** (209ms) | Covers `tradeDates.test.js` + `auditDates.test.js` |
| Vite Production Build | `cd frontend && npm run build` | **PASS** (8.06s, 1,598 modules) | Main JS `409.25 kB`, `charts` `173.56 kB`, lazy components split |
| Live Read-Only Angel One Check | Controlled `angel_service.authenticate()` + `get_spot_indices()` | **PASS** | HTTP 200 login & quotes (`NIFTY: live`, `VIX: 17.67`) |
| Live Read-Only Gemini Check | Controlled `generate_content` probe | **PARTIAL / QUOTA** | `gemini-3.8-flash` hit Free Tier `429` (`20/day` exhausted); `gemini-2.5-flash` returned `404`; `gemini-3.5-flash-lite` succeeded (`OK`) and was added as secondary candidate |

## 2. QA Issue Status Matrix (QA-01 to QA-25)

| ID | Status | Summary & Verification Evidence |
|---|---|---|
| QA-01 | **FIXED AND VERIFIED** | Decimal `0.05`-tick `compute_clamped_sl_target(..., quantity=...)` uses live broker `lots * lot_size`; verified across offline & debate execution tests. |
| QA-02 | **FIXED AND VERIFIED** | Rejects non-finite/infeasible SL/target bounds; enforces `0 < SL < entry < target`; verified in `test_qa_repairs_offline.py` & `test_qa_hardening.py`. |
| QA-03 | **FIXED AND VERIFIED** | Analytical tail slope & domain breakpoints in `greeks.calculate_strategy_payoff`; `Unlimited` max profit/loss explicit; verified in tests. |
| QA-04 | **FIXED AND VERIFIED** | Spot `0.0` bound included in option payoff evaluation; short put max loss verified exact at `spot=0`. |
| QA-05 | **FIXED AND VERIFIED** | `ScripMaster.resolve` verifies expiry `>= today`, underlying, strike, option type without silent substitution; verified offline & in `test_offline_core.py`. |
| QA-06 | **FIXED AND VERIFIED** | `build_memory` filters future report revisions (`updated > now`) and incomplete intraday reports; report revision snapshots archived in `app_kv`. |
| QA-07 | **FIXED AND VERIFIED** | Zero Call OI returns `pcr_oi=None` and `sentiment='UNAVAILABLE'`; JSON-safe (`allow_nan=False`) and UI `PcrOiPanel` updated. |
| QA-08 | **FIXED AND VERIFIED** | `reconciliation_preview` flags invalid types, NaN/Inf, missing exits cleanly and refuses approval token. |
| QA-09 | **FIXED AND VERIFIED** | `istParts` validates calendar bounds (including leap years) and time components for naive & offset strings; 28/28 JS tests pass. |
| QA-10 | **FIXED AND VERIFIED** | Strict `validated_verdict` + exact frontend `=== 'BUY CE'` / `=== 'BUY PE'` equality; invalid verdicts become `NO_TRADE`. |
| QA-11 | **FIXED AND VERIFIED** | `analysis_source` on Bull/Bear/Judge outputs; `auto=True` requires all 3 `'gemini'` + live feed; infeasible Judge tick downgrades to `NO_TRADE`; UI badges + fallback warning shown; verified in `test_qa_hardening.py`. |
| QA-12 | **PARTIALLY FIXED** | Quote freshness (`_is_quote_valid_and_fresh`, exchange timestamp + cache age) & fresh-quote gating on square-off implemented & unit-tested; deferred missing-quote exits & `stale_prior_day`/`quote_stale` UI badges added. **Remaining blocker:** live market-hours open-market end-to-end observation & multi-worker external PostgreSQL test. |
| QA-13 | **PARTIALLY FIXED** | **Playback-only safeguard**: replay fills & replay synthetic exits blocked (`400`/`409`) at API & engine; `REPLAY_STOPPED` excluded from live memory & daily reports. **Remaining work:** dedicated isolated replay wallet/tables if interactive replay trading is to be re-enabled safely. |
| QA-14 | **PARTIALLY FIXED** | Portfolio row locking (`_lock_portfolio`), single settlement path (`_settle_position`), `require_pending`, owner checks, race-safe portfolio creation, and DB SL/target resync in `update_market_prices` implemented & verified in SQLite asyncio concurrency tests. **Remaining blocker:** isolated multi-process PostgreSQL concurrency test (no local Postgres instance available). |
| QA-15 | **PARTIALLY FIXED** | Account ownership checked under `replay_engine._lock` & `paper_engine._lock`; live fills blocked during replay; verified in `test_audit_integration.py`. **Remaining caveat:** single backend worker model remains global display across viewers. |
| QA-16 | **FIXED AND VERIFIED** | Cross-day trades report realized P&L only on IST closing day; earlier-day attribution resets status/prices without future leakage; prior report revisions preserved in `app_kv`; `REPLAY_STOPPED` excluded. |
| QA-17 | **FIXED AND VERIFIED** | Removed fake random prices in `App.jsx` header/ticker, `PcrOiPanel.jsx`, and `OptionChain.jsx` on API error; stale/offline indicators surfaced cleanly; option chain backend endpoint tags `data_source`. |
| QA-18 | **PARTIALLY FIXED** | Real prior-session 5m CPR, Wilder ATR Supertrend(10,3), nullable VIX & PCR, full-session `day_high`/`day_low`, `UNAVAILABLE` for absent FII/global/breadth/heavyweights, fallback report hypotheses marked unverified. **Remaining blocker:** no authorized external institutional/breadth feed integrated yet. |
| QA-19 | **PARTIALLY FIXED** | Created versioned, strictly additive `backend/migrations.py` (`--dry-run` / `--apply`, `schema_migrations`, columns & indexes) verified on legacy SQLite schema copy with 100% row preservation. **Remaining blocker:** operator run on a cloned Supabase PostgreSQL instance & backup confirmation before applying production DDL. |
| QA-20 | **PARTIALLY FIXED** | Per-account `SchedulerRegistry` (`scheduler:<uid>` in `app_kv`), same-index DB active guard, and atomic slot-claim idempotency (`_claim_slot`) verified in tests. **Remaining blocker:** cross-worker distributed leader lease across multiple Render instances (keep 1 worker active; note duplicate Render service observed). |
| QA-21 | **FIXED IN CODE — VERIFICATION PENDING** | Added lightweight `GET /api/trading/state?include_history=false` polling in `App.jsx`, server-side filtered/paginated `GET /api/trading/history` (`limit`, `offset`, `from_date`, `to_date`, `status`, `underlying`, `search`), and DB composite indexes. **Pending:** load benchmarking in browser with 10k+ rows. |
| QA-22 | **PARTIALLY FIXED** | Unified `EXCHANGE_HOLIDAYS` + `EXCHANGE_SPECIAL_SESSIONS` calendar bounds across status/entry/squareoff/scheduler, surfaced `exchange_holidays_configured` in `/api/status`. **Remaining blocker:** no automated official NSE/BSE holiday feed; operator must keep `EXCHANGE_HOLIDAYS` populated. |
| QA-23 | **PARTIALLY FIXED** | Disclosed simplified premium-reserve model in UI (`OrderModal`, `wallet.margin_model`) and added `ALLOW_SHORT_OPTIONS` long-only safety switch tested for BUY & SELL paths. **Remaining blocker:** Angel One SPAN/clearing margin calculator integration. |
| QA-24 | **PARTIALLY FIXED** | Safe `reconcile_wallet.py` dry-run & missing-table resilience implemented; local dev SQLite preview audited (`WALLET_RECONCILIATION_PREVIEW.md`). **Remaining blocker:** live Supabase `DATABASE_URL` not present in local `.env`; run operator preview against Supabase backup before any `--apply`. |
| QA-25 | **FIXED IN CODE — VERIFICATION PENDING** | Vite manual `charts` chunk split + lazy `PcrOiPanel`, `PnlHeatmap`, `StrategyPayoff`, `DailyReportModal` verified in production build (`409.25 kB` main bundle, zero oversized chunk warnings). **Pending:** headless Playwright multi-viewport layout measurements (Playwright/Chrome not installed locally). |
