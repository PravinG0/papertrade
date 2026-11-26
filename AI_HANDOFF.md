# TradeLab / PaperTrade — AI Developer Handoff

**Current Revision:** TradeLab V5 Hybrid Quantitative AI Engine (`tradelab_v5_hybrid` merged onto production `56ddbfb`, Git backup tag `backup-pre-v5-hybrid-56ddbfb`), 26 November 2026.  
**Read alongside:** `V5_HYBRID_ENGINE.md`, `PRODUCTION_MERGE_REPORT.md`, `FINAL_QA_REPORT.md`, `DATA_PRESERVATION_REPORT.md`, `DEPLOYMENT_REPORT.md`, `DATABASE_MIGRATION_REPORT.md`, `WALLET_RECONCILIATION.md`.

---

## 1. Architecture & V5 Hybrid Stack

- **Frontend:** React 18, Vite 5.4, TailwindCSS (inverted light palette; dark text uses `text-ink` / `text-slate-300`), Axios, `lightweight-charts`. [`DebateArena.jsx`](file:///home/pravin/Documents/Trading/papertrade/frontend/src/components/DebateArena.jsx) includes the **Quantitative Validation** panel (original AI proposal vs deterministic filter verdict, 5-timeframe status grid, regime, spot freshness, option preview spread/net R:R/model delta, execution recheck), Market Matrix data-status/IST timestamp bar, controlled Retry with 4s cooldown, and Adaptive Learning Memory panel.
- **Backend:** FastAPI, SQLAlchemy 2.0 AsyncIO (`aiosqlite` for local/tests, `asyncpg` + Supabase PostgreSQL pooler for production), Pydantic v2, Google `genai` SDK, Angel One SmartAPI REST + `pyotp` (paper-trading only; zero broker order routing).
- **V5 Quantitative & Research Modules:**
  - [`backend/quant_engine.py`](file:///home/pravin/Documents/Trading/papertrade/backend/quant_engine.py): deterministic completed-bar validation (`expected_starts`, `validated_bars` requiring 50 consecutive valid candles, up to 200 warm-up), EMA20/50ATR separation, regime detection (`market_regime`), directional alignment (`validate_direction`), two-sided option spread/fee-adjusted net R:R (`option_validation`), Black-Scholes midpoint Greeks estimate (`estimate_option_greeks`), full-session reference check (`complete_session_reference`), and empirical confidence band summary (`calibration_summary`).
  - [`backend/research_backtest.py`](file:///home/pravin/Documents/Trading/papertrade/backend/research_backtest.py) & [`backend/research_ml.py`](file:///home/pravin/Documents/Trading/papertrade/backend/research_ml.py): offline-only Champion vs Challenger backtester and chronological purged-label ML calibration pipeline (`requirements-research.txt`). Never used by live or automatic trading.

## 2. Database Schema & Existing Data Preservation

- **No V5 schema/column migration required:** V5 metadata (`timeframes`, `market_regime`, `quantitative_validation`, `execution_validation`, `original_judge_verdict`, `quant_version: "quant-v1"`) is stored inside existing `debate_records.payload` and `ai_trade_evidence.snapshot` JSON fields.
- **Backward Compatibility & Preservation:** Legacy debate payloads deserialize cleanly with defaults; pre-V5 trades remain untouched and are **never** relabeled as `verified_quant`; existing user accounts, wallet balances, open/closed trades, pending orders, daily reports, and adaptive memory are 100% preserved.

## 3. Environment Variables

Preserve production `.env` privately (never commit). Optional V5 config defaults in `.env.example`:
- `MEMORY_EXTENDED_DAYS=90`
- `QUANT_MIN_CONFIDENCE=8`
- `QUANT_MIN_NET_RR=1.5`
- `QUANT_MAX_SPREAD_PCT=2.0`
- `QUANT_MAX_VERDICT_AGE_SECONDS=180`

## 4. Verification Results (26 November 2026)

- **Python syntax (`py_compile`):** **PASS** across all backend modules, agents, and tests.
- **Backend `pytest`:** **299 passed, 1 skipped** (`test_ml_research_pipeline_on_synthetic_fixture` skipped because optional `scikit-learn` research dependency is not installed in runtime environment) using isolated temporary SQLite DBs.
- **Frontend JS (`node --test tests/*.test.js`):** **28 passed, 0 failed**.
- **Frontend Production Build (`npm run build`):** **PASS** (`1,598` modules, main `414.49 kB`, charts `173.56 kB`).
- **Live SmartAPI 5-Interval Verification (read-only after market close, `_candle_min_interval = 0.65s`):**
  - `NIFTY` & `BANKNIFTY` across `1m` (`1092`), `5m` (`220`), `15m` (`275`), `1h` (`149`), `1d` (`247`) all returned `HTTP 200`, `source=live`, zero `403` rate-limit errors.
  - Note on `quant_engine.validated_bars()` strictness: during post-close testing on `2026-11-26`, `15m` passed (`50` bars, `BULLISH`), while `1m`/`5m` reflected a real SmartAPI 5-minute feed gap at `15:15–15:19 IST` and `1h`/`1d` reflected `2026-11-24` (Guru Nanak Jayanti) not being configured in `EXCHANGE_HOLIDAYS`. Keeping strict validation intact ensures the engine fails closed (`NO_TRADE`) when broker bars or holiday calendars are incomplete.

## 5. Known Limitations & Remaining Operator/Future Work

1. **Exchange Holiday Configuration:** Configure `EXCHANGE_HOLIDAYS` in Render env vars so `quant_engine.expected_starts()` does not expect bars on NSE holidays.
2. **Live Market Session Testing:** Live bid/ask spread validation, bar-boundary transitions, and auto-execution during active market hours (`09:15–15:30 IST`) remain pending until the next live market session. Keep `auto_execute` disabled until live-session validation passes.
3. **Single Backend Worker:** Historical candle rate limiting (`_candle_lock`) and scheduler slots are process-local; keep a single Render worker active.
4. **Offline Research Only:** `research_backtest.py` and `research_ml.py` require an operator-supplied historical options JSON dataset (`provenance: "historical_contract_ohlc"`) and `requirements-research.txt`; no ML model is deployed in production.

## 6. Deployment & Rollback

- **Deploy:** Push verified changes directly to `origin/main` (Render auto-deploys backend; Vercel auto-deploys frontend).
- **Rollback:** `git checkout backup-pre-v5-hybrid-56ddbfb` (or `git revert <commit>`) and push to `main`. No database rollback needed since no schema migration was added.
