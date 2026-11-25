# TradeLab QA remediation — latest revision

Base: `tradelab_qa_audit.zip`. This is a source-code revision, not a production deployment. Earlier audit documents and logs are retained as historical evidence; **this document supersedes their status**. No production Supabase database, Angel One account, or Gemini credentials were used. No production balance was changed.

## Results and scope

- Offline Python: **182 passed** (135 existing QA-suite cases, 47 new cases).
- Node date/time: **28 passed** (23 existing QA-suite cases, 5 new cases).
- Total executed offline: **210 passed, 0 failed**. All 15 previously failing offline cases are now passing. The lot-size test was corrected to explicitly pass its fixture's 65 units; the actual execution path supplies broker lot size multiplied by lots. The authenticated replay test was updated to provide an owner.
- Full backend: **NOT run to completion**. Seven collection errors due to unavailable `aiosqlite`; existing and newly added integration tests remain unverified. No dependency shims used. Do not equate offline success with a successful full backend run.
- Syntax: 39 Python files parsed. Vite production build: 1,598 modules, successful without the previous >500 kB chunk warning. Main bundle 408.74 kB; chart vendor 173.56 kB. Some of these are loaded together; this is code splitting, not a claim that total initial download is 408.74 kB. Browser and mobile performance not measured.
- No new package dependency or DB schema added by this revision. New optional `EXCHANGE_HOLIDAYS` configuration, see below. Existing database schemas may still require migrations.

## QA issue-by-issue handoff

| ID | Status | Implemented changes and outstanding acceptance criteria |
|---|---|---|
| QA-01 | Offline verified; execution integration pending | `compute_clamped_sl_target` takes total actual quantity; debate execution passes live contract lot size × lots, also clamps overrides. 0.05 premium tick assumption; validate per-contract tick size and fill path. Gross cap excludes fees and gaps. |
| QA-02 | Offline verified | Reject infeasible SL/target, ensure `0 < SL < entry < target`; round conservatively. |
| QA-03 | Offline verified | Compute payoff limits from domain breakpoints and net call tail slope; unlimited risk/profit explicit. |
| QA-04 | Offline verified | Include zero in true expiry payoff bounds; short put max loss no longer limited to chart range. |
| QA-05 | Offline verified | Reject expired or metadata-mismatched exact symbols. Verify broker resolution, expired settlement and legacy undated contracts in live tests. |
| QA-06 | Offline verified for reproduced defect; versioning remains | Ignore reports updated after as-of time. True historical reconstruction still requires versioned reports; unknown legacy revision times cannot be reconstructed. |
| QA-07 | Offline verified; API/UI runtime pending | Undefined PCR returns null, unavailable sentiment, updated agent prompts, OI view and report formatting. Removed fake fallback OI values. Validate partial/live chain quality and PCR UI. |
| QA-08 | Offline verified | Invalid ledger data produces issues, JSON-safe null values and no approval token. |
| QA-09 | Offline verified | Validate calendar and time parts, including offset timestamps. |
| QA-10 | Offline verified parser; actual agent runtime pending | Strict `validated_verdict` accepts only BUY CE, BUY PE, NO_TRADE; requires finite positive strike/entry/SL/target and integer confidence. No permissive substring matching. Verify actual Gemini parser end-to-end. |
| QA-11 | Source fix; runtime pending | Analysis provenance (`gemini`, `fallback`, `unknown`) on all three outputs; auto execution requires all three successful Gemini responses and configured live feed. Unknown legacy verdicts and fallback auto-execution blocked. Manual fallback display remains; ensure UI distinguishes it. Test each agent timeout, malformed response and API failure, and no wallet mutations. |
| QA-12 | Partial, external verification pending | Automatic square-off now runs after quote refresh, requires a current-cycle exact-contract quote and only runs during normal 15:15–15:30 window; durable last observed MTM in active DB record. Missing quotes defer rather than fabricate fills. Broker cache age (3 sec) is not exchange tick freshness. Need exchange timestamp/quote age validation, explicit stale/unpriced UI, missed/expired-session recovery policy and live tests. Measure extra MTM database writes. |
| QA-13 | Safeguard, incomplete | **Replay is playback-only**. New replay fills rejected at API and engine; playback/stop no longer writes/settles the live wallet. Known REPLAY_STOPPED rows excluded from memory, their days' reports skipped. Legacy SL/target replay fills lack reliable provenance; do not guess. Implement separate replay wallet, positions, orders and report/memory scope, migration/quarantine for verified replay history, and restore replay trading only after tests. |
| QA-14 | Source fix; concurrency pending | Cancel and SL update verify owner and active row under portfolio lock; stale pending/closed records cannot be changed by these paths. Persisted MTM checks active owner/status. Verify PostgreSQL locking, stale cached SL trigger after another worker edit, all concurrent paths; no multi-worker certification. |
| QA-15 | Source fix, single-process only | Replay ownership checked under replay lock; start takes paper-engine lock before activating; controls re-check owner. Live fills blocked during playback. Test concurrent start/control/order, restart, and multi-worker ownership. Shared market display remains global. |
| QA-16 | Source fix; report integration pending | Realized results attributed to closing day; entry-day reconstruction for later exits clears closed status/reason, aliases and realized P&L. Past unrealized value is unavailable, represented as zero/entry price rather than future MTM. Need full as-of handling for multi-day positions, earlier cached reports, true historical MTM and offset timestamps. |
| QA-17 | Source fix; browser pending | Remove random index ticks and header mock defaults; feed source from REST/WS; OI panel no fabricated fallback. Backend explicit simulation still possible for development; verify all chart/option data paths label source. |
| QA-18 | Partial; external data needed | Added prior-full-5m-session CPR and Wilder ATR Supertrend(10,3), with unavailable when insufficient evidence. FII/global/heavyweight/breadth inputs no longer inferred as verified facts; mark unavailable. Verify independently against indicator fixtures/reference and reliable volume/VIX/OI data. Other agent fallback causal narratives remain hypotheses; verify/rework before using as evidence. Need actual institutional/global/breadth feed, not fabricated estimates. |
| QA-19 | **Open** | Versioned non-destructive PostgreSQL migrations and schema diff against disposable copy of actual Supabase required. create_all does not upgrade existing tables. No production DDL applied. |
| QA-20 | Source fix, single process; runtime pending | Account-specific scheduler registry and `app_kv` keys `scheduler:<uid>`, legacy global config fallback. DB same-index active-position guard under wallet lock. Test save/restore, two accounts, resource/API limits, start/stop, process restarts. Multi-worker leader election/leases not implemented. Run exactly one backend worker until verified. |
| QA-21 | **Open** | Four-second portfolio polling and full history DB read remain; don't reduce MTM accuracy to hide load. Implement aggregate lightweight snapshot, paginated/date-scoped history, incremental WS updates and measure large-history performance. Preserve date filters and full CSV exports. |
| QA-22 | Partial; official calendar required | `EXCHANGE_HOLIDAYS` comma-separated closure dates validated; shared normal weekday checks in scheduler/entry/status/EOD/squareoff. Empty default means no holidays configured, not complete exchange calendar. Obtain/maintain official NSE/BSE holidays and special sessions (including Muhurat), per exchange where needed. Verify fail-closed availability before unattended operation. |
| QA-23 | **Open** | UI disclosure added for simplified premium reserve on SELL. Not broker/clearing margin; loss can exceed wallet. Need real broker/clearing margin and margin call rules or user-approved restriction on opening shorts. Do not falsely claim margin accuracy. |
| QA-24 | Partial; production ledger needed | Invalid baseline, non-finite/malformed ledger and JSON serialization refusal improved. Full historical cash reconciliation still requires complete production ledger, reset baselines, known adjustments and prior replay provenance; dry-run on backup, explicitly approve only after verifying completeness. |
| QA-25 | Build verified; browser metrics pending | Lazy-load OI, Journal, Payoff, Daily Report and split chart vendor. Previous oversized chunk warning gone. Validate desktop/mobile load and caching. |

## Deployment safety and configuration

- Do not merge directly into main or deploy yet. Work on a branch, compare production-specific changes, run a full isolated integration suite first. Keep existing `.env`, JWT secret and production DB; do not print secrets.
- New optional `.env` key `EXCHANGE_HOLIDAYS=YYYY-MM-DD,YYYY-MM-DD` (replace with actual officially verified closure dates). No example dates are actual exchange holidays. Existing risk settings remain unchanged. Both Render and Vercel need redeploy after approval. Do not enable simulation/off-hours trading on production.
- A single backend worker is required until scheduler/replay coordination and concurrent settlement are independently tested. SQL row locking alone does not provide a cross-worker scheduler lease.
- **Replay behavior changed intentionally**: playback, pause, speed and stepping remain, new replay orders blocked to protect the live wallet and memory. Do not restore replay trading against live records. Existing untagged legacy records need classification; do not delete or rewrite them automatically.
- Wallet reconciliation requires dry-run and verified ledger; no automatic production repair. Read `WALLET_RECONCILIATION.md`. Historical report versioning and previous-day snapshots require additional storage or migrations.
- Agent estimate SL/target is indicative; final fill re-clamps using actual total units. ₹700 is gross stop risk at trigger price, not guaranteed maximum loss. Gap execution and fees may exceed that amount.

## Reproduce tests

```bash
# From papertrade root; use isolated Python environment, private credentials absent
python -m pip install -r backend/requirements-dev.txt
cd backend
python -m pytest -q
# Offline subset used here:
python -m pytest -q tests/test_offline_core.py tests/test_adaptive_memory.py tests/test_wallet_accounting.py tests/test_audit_offline.py tests/test_qa_repairs_offline.py
cd ../frontend
npm ci
node --test tests/*.test.js
npm run build
```

Existing `conftest.py` forces temporary SQLite and clears API credentials. PostgreSQL concurrency and migration tests must use a separate disposable PostgreSQL database and an explicit test-only fixture, never bypass isolation to access production. Add mocked HTTP and browser tests for every affected frontend/backend path. Raw logs are in `QA_REPAIR_RESULTS/`; old `QA_RESULTS/` is the pre-fix audit.
