# TradeLab QA audit — wallet-reconciled release

## Scope and result
Base: `tradelab_wallet_reconciled.zip` (the most recent corrected source, not a fresh download of production). This is a test-and-audit revision only. Application source is unchanged. No production DB, credentials, network trading APIs, or real broker order endpoints were used. The offline suite imports the actual pure modules; no dependency shims were used. Runtime paths were inspected selectively, not every branch executed. Fees were not checked against current broker/exchange schedules.

| Run | Passed | Failed | Notes |
|---|---:|---:|---|
| Python offline | 124 | 11 | 135 total; 19 existing + 116 new |
| Node date helpers | 19 | 4 | 23 total; 3 existing + 20 new |
| Combined | 143 | 15 | 158 executed cases |
| New integration specifications | 0 verified | Not run | 19 parameter-expanded cases, require dependencies |
| Full original backend suite | Not run | 6 collection errors | Missing aiosqlite; no package candidate available |
| Python syntax | 35 files parsed | 0 | Includes test files |
| Frontend production build | Passed | 0 | 1,597 modules; JS 645.32 kB / gzip 186.56 kB; existing size warning |

155 new test cases (116 Python offline, 20 Node, 19 Python integration) added. The 15 test failures are deliberately left as failing regression cases to guide fixes, not suppressed or changed to xfail. 22 pre-existing offline cases pass. Runtime test specifications are unexecuted and may themselves require adjustment after a full environment run.

## Reproduced defects

| ID | Priority | Actual behavior / evidence | Expected behavior | Location |
|---|---|---|---|---|
| QA-01 | High | Fixture with 65-unit contract and ₹100 premium clamps SL to ₹72 using configured 25-unit lot. Gross loss at SL ₹1,820, before charges and gaps. | Risk cap uses actual quantity, including number of lots; disclose slippage and fees. | `config.py:212`, `debate_engine.py:546` |
| QA-02 | High | ₹0.50 entry with ₹0.40 requested SL returns ₹1.00 SL. | Valid BUY SL below entry or reject infeasible risk. | `config.py:226-235` |
| QA-03 | High | Long call maximum profit and naked short call maximum loss both shown as finite ₹123,500 in fixture. | Determine unbounded tail analytically, not by chart range. | `greeks.py:259-369` |
| QA-04 | High | Short 25,000 put, ₹100 premium, 65 qty shows ₹123,500 max loss magnitude; expiry at zero yields ₹1,618,500 loss before costs. | Include zero and all strike breakpoints when computing true payoff bounds. | `greeks.py:285-369` |
| QA-05 | High | Exact-symbol lookup can return expired cached contract and ignores mismatched underlying/strike/type. Two separate tests fail. Normal manual quote lookup already validates the requested expiry; this defect concerns direct resolution/MTM with stale or inconsistent contract metadata. | Validate date and metadata before returning exact match; do not roll into another expiry. | `scrip_master.py:217-229` |
| QA-06 | Medium | Report dated 24 Nov but revised 26 Nov is included in memory evaluated 25 Nov. | Exclude future revisions; keep versioned historical evidence when doing as-of evaluation. | `adaptive_memory.py:116-139` |
| QA-07 | Medium | PCR returns 1.0 / neutral when call OI is zero and put OI positive. | Represent undefined ratio explicitly and avoid treating absent denominator as balanced OI. | `greeks.py:223-252` |
| QA-08 | Medium | Null/non-numeric quantity raises TypeError/ValueError rather than returning an invalid-ledger preview. Such values are constrained by current DB schema, but helper should handle malformed imported/legacy records. | Return structured validation issues and refuse apply. | `wallet_accounting.py:22-52` |
| QA-09 | Medium | Four impossible naive IST timestamps accepted (Feb 30, month 13, hour 25, minute 65). | Validate calendar/time components and display invalid timestamp as unavailable. | `frontend/src/utils/tradeDates.js:3-6` |

## Additional source findings (not runtime reproduced)

| ID | Priority | Finding / risk | Suggested acceptance criterion |
|---|---|---|---|
| QA-10 | High | `agents/judge_agent.py:160-167` uses substring matching. `SELL CE`, `DO NOT BUY PE`, and `NO TRADE: avoid CALL` can be converted to BUY instead of NO_TRADE. | Strict allowlist and schema validation; malformed model response must fail closed. New mocked-runtime tests cover this. |
| QA-11 | High | `agents/judge_agent.py:132-133` returns heuristic fallback after Gemini failure; scheduler can auto-execute it with qualifying confidence. Memory prompts do not influence deterministic fallback. | Mark source and block auto execution on AI failure unless user explicitly enables a separately validated heuristic strategy. |
| QA-12 | High | `main.py:124` square-off runs before fresh quote refresh; `paper_engine.py:893+` writes ordinary MTM into memory only. Restart can restore entry-price LTP, and square-off may settle using stale cached price. | Fetch/validate fresh exact-contract quote before settlement; mark unpriced positions; persist last trusted price/time. |
| QA-13 | High | Replay orders share live paper wallet and trade table. `PaperTradeModel` has no replay provenance and `adaptive_store.py` can include replay trades in statistical memory. Crash can leave replay positions active. | Separate replay ledger and provenance; exclude replay from live learning and reconcile on restart. This is a design change, not an assertion that user wanted separate wallet originally. |
| QA-14 | High | `paper_engine.py:595+` cancel returns SUCCESS for stale cached pending order even if DB row is gone. `:722+` update_sl can mutate CLOSED database record using stale active cache. | Re-read owner and current status under wallet lock; no modification after closure. |
| QA-15 | High | `main.py:803+` replay eligibility is checked outside replay engine lock. Concurrent request can pass before another user starts replay; process-local state also makes multi-worker behavior fragile. | Atomic ownership acquisition and durable lifecycle; stress test across workers. |
| QA-16 | Medium | `paper_engine.py:879-891` daily trades select entry OR close date; `agents/report_agent.py:164-185` uses current CLOSED status and realized P&L. Cross-day position can be attributed to both days or use future outcome when regenerating an older report. | Explicit report as-of semantics; realized P&L allocated to closing date only. |
| QA-17 | Medium | `frontend/src/App.jsx:184-205` generates random market index prices when request fails without updating source to offline/stale. OptionChain separately labels its simulated data, but header can mislead. | Freeze last known value and label stale/error; disable trading if data unreliable. Configured backend candle fetch returns empty on failure, not a simulated candle series. |
| QA-18 | Medium | `debate_engine.py:48-153` labels EMA-based direction and price±ATR as Supertrend; CPR uses last 60 candles/spot rather than prior session OHLC; FII/global sentiment inferred. | Implement real indicators or label as approximations; independent indicator fixtures. |
| QA-19 | Medium | `database.py:473-507` schema alteration only for SQLite, while create_all does not migrate existing PostgreSQL tables. | Versioned migrations and disposable PostgreSQL upgrade tests. May not affect DB that already has all columns. |
| QA-20 | Medium | `scheduler.py:154+` only one global account scheduler; duplicate active position guard relies on in-memory positions. | One scheduler per account, durable job lock, DB-level position constraints if required. |
| QA-21 | Medium | `paper_engine.py:214+`, `App.jsx:401+`: entire trade history read/serialized on 4-second polling; duplicated history in response and WebSocket on changes. | Paginated history, incremental events, portfolio summary endpoint; measure with large dataset. |
| QA-22 | Medium | Entry time/day cap/market hours use weekdays without exchange holiday calendar; actual order quote validation helps but does not fully prove open exchange. | Calendar or authoritative trading-session state; test holidays, exceptional sessions, stale quotes. |
| QA-23 | Medium | Short option trades reserve premium rather than exchange short margin. No mark-to-market margin call; short loss can exceed wallet. | Model margin explicitly or restrict simulator to long options; never market as actual broker-equivalent margin. |
| QA-24 | Medium | `reconcile_wallet.py` assumes complete history and known reset baseline. Arithmetic alone cannot prove no missing fills/adjustments. Non-finite values can fail JSON serialization. | Never repair production automatically; verify full ledger and preview, reject invalid inputs gracefully. |
| QA-25 | Low | Build warning for 645.32 kB minified JS. | Route-based splitting, measure load on mobile. |

## Wallet assessment
Pure arithmetic passed for cash/margin/equity, realized/unrealized P&L, reset baselines, long/short arithmetic and screenshot repair preview. This does not certify the database settlement implementation or the historical production wallet. No actual Supabase ledger was provided or modified. Do not run repair apply until ledger completeness, reset history and account ownership are checked against an isolated copy. Margin calculations reflect the simulator's premium-reserve model only.

## How to run
From project root, create a virtual environment and install `python -m pip install -r backend/requirements-dev.txt`. Then:

```bash
cd backend
python -m pytest -q
# Offline subset only:
python -m pytest -q tests/test_offline_core.py tests/test_adaptive_memory.py tests/test_wallet_accounting.py tests/test_audit_offline.py
```

Frontend (new terminal):

```bash
cd frontend
npm ci
node --test tests/*.test.js
npm run build
```

The existing conftest uses a temporary SQLite database, disables keep-alive, and clears API credentials. Run the full suite without production `.env` or environment secrets and with outbound network disabled where possible; all external integrations must use fixtures/mocks. A separate disposable PostgreSQL instance is needed for real transaction concurrency and migration tests because the existing conftest forces SQLite. No live integration test results are claimed. See `QA_RESULTS/` for raw logs. Production source unchanged.

## Remaining test plan / release gate
- SQLite and PostgreSQL: two workers place/close/cancel/reset concurrently; simultaneous reset vs fill; balance conservation under 1000 sequential and concurrent orders; restart with pending/live orders; injected commit failure and rollback; duplicate debate ID; repair preview/apply idempotency and stale token rejection; database migration from old schemas.
- Market data: mocked 401/403/429/500 and timeout, stale quote timestamps, malformed broker payloads, partial quote batches, token collision, exact option expiry, holiday, opening/closing boundaries, gaps, price zero, NaN/Inf, throttling and reconnect.
- AI: captured system prompts for all 3 agents; malformed and ambiguous JSON; unavailable Gemini; account-specific memory; same strike cooldown across restart; five-fill cap across workers and days; historical replay segregation; no future information; memory token budget; sample-size effects and forward-only paper-trading validation.
- Security: invalid/expired JWT, reconnect after logout, user switching, cross-account order/read/export/reports/WebSocket/scheduler access, Google token claims, injection-safe CSV and rendered reports, rate limiting and abuse resistance. Test only local fixtures and disposable accounts.
- Browser: Playwright/Chromium at 360/390/768/1024/1440 widths; tabs, charts, date range and IST, order dialog, daily report, theme contrast, logout, mobile touch/overflow, long history, fallback badges, network slow/offline, no duplicate fills from retries. No browser test executed here.
- Deploy preview: Render backend health, Vercel preview, disposable Supabase, secrets and migrations, staged end-to-end paper trades, reconciliation dry-run, rollback drill. No production deployment.

**Release verdict:** offline tests expose real defects; full backend and browser verification remain blocked/unperformed. Do not classify this release as bug-free or production-ready based on a successful build. Fix QA-01 to QA-14 first, then re-run tests. No trading profitability claim is supported.
