# TradeLab / PaperTrade — AI Developer Handoff

**Current Revision:** QA Remediation, Merge & Hardening (`tradelab_qa_repaired` + post-merge QA hardening), 26 November 2026.  
**Base:** Production `main` (`52a8419`, tag `backup-pre-qa-repaired-52a8419`) merged with `tradelab_qa_repaired.zip`.  
**Read alongside:** `PRODUCTION_MERGE_REPORT.md`, `FINAL_QA_REPORT.md`, `DATABASE_MIGRATION_REPORT.md`, `DATA_PRESERVATION_REPORT.md`, `WALLET_RECONCILIATION_PREVIEW.md`, `DEPLOYMENT_REPORT.md`, `ADAPTIVE_LEARNING_CHANGES.md`, `WALLET_RECONCILIATION.md`.

---

## 1. Architecture & Technology Stack

- **Frontend:** React 18, Vite 5.4, TailwindCSS, Axios, `lightweight-charts` (split into `charts` chunk; `PcrOiPanel`, `PnlHeatmap`, `StrategyPayoff`, `DailyReportModal` lazy-loaded via `Suspense`).
- **Backend:** FastAPI, SQLAlchemy 2.0 AsyncIO (`aiosqlite` for local/tests, `asyncpg` + Supabase pooler port `6543` for production), Pydantic v2, Google `genai` SDK, Angel One SmartAPI REST + `pyotp` (paper-trading only; zero broker order routing).
- **Primary Endpoints:**
  - Health & Status: `/api/health`, `/api/status` (includes `exchange_holidays_configured`, `allow_short_options`, `data_source`)
  - Market Data: `/api/indices`, `/api/candles`, `/api/expiries`, `/api/option-chain`, `/api/analytics/pcr-oi`, `/api/analytics/payoff`
  - Paper Trading: `/api/trading/state` (`?include_history=true|false`), `/api/trading/order`, `/api/trading/order/{id}/cancel`, `/api/trading/position/{id}/exit`, `/api/trading/position/{id}/stoploss`, `/api/trading/exit-all`, `/api/trading/reset`, `/api/trading/history` (paginated & server-filtered), `/api/trading/all-trades`, `/api/trading/export`
  - AI & Scheduler: `/api/debate/run`, `/api/debate/latest`, `/api/debate/history`, `/api/debate/{id}/execute`, `/api/scheduler/start`, `/api/scheduler/stop`, `/api/scheduler/status`
  - Reports & Replay: `/api/reports/daily`, `/api/reports/daily/generate`, `/api/reports/dates`, `/api/reports/daily/export`, `/api/replay/start`, `/api/replay/control`, `/api/replay/state`
  - Auth & WS: `/api/auth/*`, `/ws/terminal` (owner-scoped `ORDER_UPDATE`)

## 2. Database Schema & Non-Destructive Migrations

- Tables in [`backend/database.py`](file:///home/pravin/Documents/Trading/papertrade/backend/database.py):
  - `users`, `portfolios`, `paper_trades`, `pending_paper_orders`, `debate_sessions`, `debate_records`, `ai_trade_evidence`, `daily_reports`, `app_kv`, plus `schema_migrations` added by [`backend/migrations.py`](file:///home/pravin/Documents/Trading/papertrade/backend/migrations.py).
- **Migrations:** `init_db()` invokes `apply_additive_migrations()` using SQLAlchemy `inspect()` for both SQLite and PostgreSQL (only additive `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN`, and `CREATE INDEX IF NOT EXISTS`). Supports `SKIP_DB_INIT=true` and CLI `--dry-run` / `--apply`.

## 3. Trading, Risk, AI Agents & Memory Workflows

1. **Adaptive Learning Loop** (`adaptive_memory.py`, `adaptive_store.py`):
   - Retrieves intraday closed P&L, 5-day completed DailyReport lessons (with future revision protection `updated > now` and intraday `<15:30` exclusion), 30-day statistics, and comparable market regime win/loss stats strictly scoped by `user_id` and excluding `WALLET_RESET` and `REPLAY_STOPPED`.
   - Injected into Bull, Bear, Judge prompts via `prompt_with_memory()` (marking reports untrusted evidence).
2. **Deterministic Backend Guardrails**:
   - Decimal `0.05`-tick clamping via `compute_clamped_sl_target(..., quantity=lots * lot_size)`.
   - Strict verdict parser (`verdict_validation.py`): only `BUY CE`, `BUY PE`, `NO_TRADE` with finite positive prices & integer confidence `1..10`; infeasible tick geometry downgrades to `NO_TRADE`.
   - `analysis_source` tracking (`gemini`, `fallback`, `unknown`): `auto_execute` fails closed if any of Bull/Bear/Judge is non-Gemini or Angel feed is unconfigured. UI shows badges & fallback warning notice.
   - `guard_auto_fill`: max daily auto fills (`AUTO_MAX_DAILY_TRADES=5`), repeat-strike SL cooldown (`AUTO_REPEAT_STRIKE_COOLDOWN_MINUTES=30`), single active position per index, atomic `ai_trade_evidence` per debate ID, symmetric `trend_rejection` (`AUTO_TREND_THRESHOLD_PCT=0.75`).
   - `DebateScheduler._claim_slot` records durable slot claims in `app_kv` (`scheduler-slot:<uid>:<sym>`) to block duplicate runs across restarts.
3. **Wallet Settlement & Concurrency** (`paper_engine.py`, `wallet_accounting.py`):
   - Single transactional `_settle_position` under `_lock_portfolio` row update lock; `reset_portfolio` uses `_lock_portfolio`; `_get_or_create_portfolio` handles `IntegrityError` races.
   - `update_market_prices` syncs DB `stop_loss` & `target` from persisted row before trigger evaluation (prevents stale worker trigger).
   - `check_intraday_squareoff` requires `is_trading_day(now)` and current-cycle fresh quotes; defers unpriced contracts cleanly; `get_state` surfaces `stale_prior_day` & `quote_stale`.
   - `ALLOW_SHORT_OPTIONS` allows toggling off short SELL options when broker clearing/SPAN margin API is unavailable.
4. **Exchange Calendar & Replay Isolation**:
   - `session_calendar.py` supports `EXCHANGE_HOLIDAYS` and `EXCHANGE_SPECIAL_SESSIONS` across status, entry window, square-off, and scheduler.
   - Historical Replay is strictly **playback-only**: orders and exits during replay return HTTP 409 / `REJECTED` so live capital and learning memory stay isolated.

## 4. Environment Variables

Preserve `.env` privately (never commit). Optional new keys in `.env.example`:
- `EXCHANGE_HOLIDAYS`, `EXCHANGE_SPECIAL_SESSIONS`, `ALLOW_SHORT_OPTIONS`, `SKIP_DB_INIT`.
- Gemini failover order (`gemini_candidate_models()` in `config.py`): `[settings.GEMINI_MODEL, "gemini-3.8-flash", "gemini-3.5-flash-lite"]`.

## 5. Verification Baseline (26 November 2026)

- Python syntax check (`py_compile` all source & test files): **PASS**
- Full backend `pytest`: **237 passed, 0 failed** (34.04s) using isolated temp SQLite DB
- Frontend `node --test tests/*.test.js`: **28 passed, 0 failed** (209ms)
- Frontend `npm run build`: **PASS** (1,598 modules, 8.06s, main `409.25 kB`, charts `173.56 kB`, zero oversized chunk warnings)
- Controlled read-only live checks: Angel One SmartAPI login & spot/VIX (`live`, `VIX=17.67`) **PASS**; Gemini `gemini-3.8-flash` hit daily Free Tier `429` (`20/day`), `gemini-3.5-flash-lite` responded `OK`.

## 6. Known Limitations & Operator Actions Remaining

1. **Duplicate Render Instance**: Both `papertrade-1-uv24.onrender.com` and `papertrade-s9fq.onrender.com` were active against Supabase PostgreSQL. Keep only one backend service & single worker active until distributed leader leasing is implemented.
2. **Supabase Production DB Audit / Reconciliation**: Production `DATABASE_URL` lives on Render. Take a Supabase backup, run `migrations.py --dry-run` and `reconcile_wallet.py --user-id <ID>` read-only first, and approve any wallet correction explicitly.
3. **Browser E2E Layout Verification**: Playwright/Chrome not installed locally; test desktop/tablet/mobile viewports (320px–1440px) in browser after Vercel deploy.
4. **External Feeds**: FII/DII, global sentiment, breadth, official NSE holiday auto-sync, and broker SPAN short-margin APIs remain unintegrated (marked `UNAVAILABLE` / disclosed clearly).
