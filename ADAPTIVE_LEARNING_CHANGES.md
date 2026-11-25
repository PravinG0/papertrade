# TradeLab — Dynamic Daily Learning & Memory Loop

## Revision and scope

Base: user-uploaded `papertrade(2).zip`, 25 November 2026. Preserve previous wallet, date filtering, three-tab Terminal and mobile work. This is paper trading only. The update implements retrieval-based adaptation, not Gemini fine-tuning, model training, automatic parameter optimization or a profitability claim.

## Runtime architecture

1. `DebateEngine.run_debate` gets a market snapshot; retrieves this account's completed prior daily reports and observed closed trade results from SQLAlchemy; builds a bounded Markdown memory block.
2. Pass the same immutable per-request memory string to `BullAgent.analyze`, `BearAgent.analyze`, and `JudgeAgent.evaluate`. Each appends it to the Gemini system instruction. The quantitative fallback remains unchanged and does not use textual lessons.
3. A symmetric trend guard converts a counter-trend Judge recommendation into `NO_TRADE` when valid session context indicates a strong trend. The snapshot now uses today's opening candle or broker open, and a current-session price reference rather than cross-day VWAP. When volume is missing the reference is labelled `TYPICAL_PRICE_PROXY`, not true VWAP. Missing/stale (>15 min) current-session candles fail closed for automatic trading.
4. Before an automatic execution, rebuild market context. Before the paper engine commits a fill, apply trend, repeated-strike stop-loss cooldown, market entry window and daily automatic fill count guards inside its process-local lock. Read the DB at fill time, not only when the debate was generated. Rejected orders leave wallet/trades unchanged; scheduler's existing `mark_skipped` persists rejection text. Manual order entry is not subject to auto-only rules. Judge `NO_TRADE` remains non-executable.
5. Atomic new provenance table `ai_trade_evidence` stores position ID, debate ID (unique primary key), owner, auto flag, entry context and Judge confidence in the same DB transaction as the trade and wallet update. For manual execution of a Judge verdict, context is the debate snapshot; automatic execution stores refreshed context. Duplicate fills are rejected even after process restart. Older auto-debate fills with reliable `DebateRecordModel` links are counted too.
6. The existing EOD report job remains the source of the next day's lessons. No new scheduled job or external API required. In Chat, a collapsible saved memory panel and risk/skip notices make decisions inspectable, including archived debates.

## Memory layers

- Intraday: today's closed paper-trade net P&L, win rate, average loss, fees and sample size.
- Short-term: last 5 distinct eligible report dates by default. Earlier dates only; skip reports with open positions, known intraday-only generation and empty analyses. No explicit report completion flag exists in the existing schema, so prior-date completion is inferred. Both active ReportAgent string and DailyReportAgent list forms of `stop_loss_analysis.failure_reasons` are supported. Extract top five lessons and top five failure hypotheses by exact-text recurrence; lessons may be account-wide, failure reasons scoped to current index when identifiable.
- Long-term: up to 30 observed historical trading dates of actual closed trade data, and a comparison of BUY CE/PE under the current regime for AI fills with valid recorded entry context. Include sample size, net P&L, win rate, average loss, fees. Judge confidence buckets are descriptive, not calibrated probabilities.
- Strategic: retained-history CE/PE aggregates, bounded by newest 2,000 closed rows for the selected index. The 30-day and strategic windows may be incomplete for very large histories. Up to 60 report rows are considered. Legacy trade rows lacking valid snapshots contribute only to general results; old fabricated day-open snapshots are not treated as reliable regime evidence. Historical replay trades in legacy data cannot always be distinguished from ordinary trades.
- Report explanations are unverified hypotheses. Quoted, length-bounded text is identified as untrusted data, not instructions. No persistent agent prompt mutation, cross-account retrieval, extra vector database, or embedding service. A database read failure gives a neutral missing-memory prompt; automatic risk-history DB failures prevent a fill. Stored debate memory remains a point-in-time audit trail.

## Configuration (backend environment variables)

| Name | Default | Meaning |
|---|---:|---|
| `MEMORY_SHORT_DAYS` | 5 | Prior distinct eligible report dates |
| `MEMORY_LONG_DAYS` | 30 | Observed past trading dates |
| `AUTO_MAX_DAILY_TRADES` | 5 | Successful auto fills per user across indices per IST date; includes open and closed |
| `AUTO_REPEAT_STRIKE_COOLDOWN_MINUTES` | 30 | Block the same index/strike/CE-PE after an actual stop-loss, including manually opened trades; deliberately applies across expiry to reduce churn |
| `AUTO_TREND_THRESHOLD_PCT` | 0.75 | Change from session open plus above/below session VWAP or labelled proxy; hard block in opposite direction |

These are unvalidated starting settings for paper trading, not optimal parameters. Existing scheduler confidence threshold (70%) and one-position-per-index rules remain. No mandatory daily loss limit, consecutive-loss pause, new RR floor or automatic threshold optimization is introduced in this revision. Caps persist across wallet resets because trade history is retained. The scheduler is still process-local/global; run a single backend worker. The new table's unique debate key prevents duplicate durable fills, but multi-worker cap/cooldown concurrency is not guaranteed.

## Files changed

| File | Responsibility |
|---|---|
| `backend/adaptive_memory.py` | Pure report and trade statistics, session VWAP/proxy calculation, deterministic rules |
| `backend/adaptive_store.py` | Account-specific SQLAlchemy memory and cap/cooldown retrieval |
| `backend/database.py` | Additive `AITradeEvidenceModel`; existing `init_db()` creates table |
| `backend/config.py`, `.env.example` | Configurable defaults |
| `backend/debate_schemas.py` | Backwards-compatible `session_reference` and `episodic_memory` fields |
| `backend/debate_engine.py` | Memory orchestration, session open fix, trend veto, fresh context, fill provenance |
| `backend/agents/{bull,bear,judge}_agent.py` | Request-local Gemini system prompt injection and session-reference labels |
| `backend/agents/report_agent.py` | Scope report debate lookup to account |
| `backend/paper_engine.py` | Lock-protected final auto checks and atomic durable fill evidence |
| `frontend/src/components/DebateArena.jsx` | Collapsible memory and risk notice (responsive, no new endpoint) |
| `backend/tests/test_adaptive_memory.py` | Seven offline regression tests |
| `backend/tests/test_adaptive_integration.py` | Two integration tests: actual Gemini system instructions with fake clients, account-scoped DB retrieval, persisted duplicate/cooldown/cap checks |
| `AI_HANDOFF.md`, this file | Current handoff and revision details |

## Database / deployment

Uses portable SQLAlchemy ORM, ordinary text JSON, integer flags, foreign keys and SQL `substr`/`coalesce`, no PostgreSQL-only JSON or SQLite-only statement for the feature. `init_db()` calls `Base.metadata.create_all`; it should create `ai_trade_evidence` on SQLite or Supabase if the connection role has CREATE TABLE permission. No destructive schema migration or backfill. Back up database; confirm table exists and permission is correct in staging. Do not expose database credentials or replace existing DB with an empty file. Deploy backend on Render and frontend on Vercel; leave credentials in host settings. Source-only ZIP omits `.env`, SQLite DB, cached sessions, node_modules, dist, and Git metadata.

## Verification actually run for this revision

- `cd backend && python -m pytest -q tests/test_adaptive_memory.py tests/test_offline_core.py tests/test_wallet_accounting.py`: **15 passed** (7 new + 8 existing dependency-light tests).
- `cd backend && python -m compileall -q .`: passed.
- `cd frontend && node --test tests/*.test.js`: **3 passed**.
- `cd frontend && npm run build`: passed, 1,597 modules; existing >500 kB JS chunk warning (approximately 645 kB).
- Full `python -m pytest -q`: **blocked during collection**, missing `aiosqlite`; package installation failed. New DB/mocked-Gemini tests have not run. Supabase, live Gemini/Angel One, browser/mobile and live deployment not verified here. Historical test/deployment claims in older handoff are from the supplied ZIP, not reverified.

Before production deployment: install `backend/requirements-dev.txt`, run full suite against isolated test DB; confirm `ai_trade_evidence` creation on staging PostgreSQL; use mock quote and fake Gemini for tests; verify six consecutive eligible auto attempts yield five fills then one rejection; simulate SL and confirm same strike blocks for 30 min but another strike may proceed; restart process and repeat; verify two accounts' histories never leak; verify Chat UI desktop/mobile. Do not use live broker execution or actual credentials in testing. Compare baseline against enhanced system using held-out market replay and forward paper testing; do not infer improvement without data.

## Remaining development

Separate historical replay provenance, persistent per-user scheduler, additional configurable loss/fee/risk-reward rules, market-regime sophistication beyond simple open/VWAP reference, structured exit-time market snapshot, calibrated confidence and champion/challenger evaluation are future work. Strategic statistics are calculated on read rather than a trained/optimized model. Missing daily reports (backend downtime) are not automatically backfilled by this revision. DB query latency and the extra fresh snapshot may affect existing execution timeout; verify on Render. Do not silently change accounting, real trade safety or manual order semantics.
