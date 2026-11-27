# TradeLab Cloud V6.1 — AI Developer Handoff

**Current Revision:** TradeLab Cloud V6.1 (`TradeLab_Cloud_V6_1_MCX` merged onto `ec9dcc0`, backup tag `backup-pre-v6_1-ec9dcc0`), 27 November 2026.  
**Read alongside:** `MCX_V61_IMPLEMENTATION.md`, `FINAL_QA_REPORT.md`, `MCX_LIVE_TEST_REPORT.md`, `WEBSOCKET_TEST_REPORT.md`, `DATA_PRESERVATION_REPORT.md`, `DEPLOYMENT_REPORT.md`.

---

## 1. Cloud V6.1 Architecture & New Modules
- **MCX AI Debate & Independent Scheduler ([`backend/mcx_ai.py`](file:///home/pravin/Documents/Trading/papertrade/backend/mcx_ai.py)):**
  - Dedicated Bull/Bear/Judge Gemini prompts for `CRUDEOIL` futures options (no NIFTY/VIX assumptions, no heuristic fallback when Gemini fails).
  - Fixed `gemini_json` to try `gemini_candidate_models()[:3]`, strip optional markdown fences, and log model/exception details (verified live at `22:52 IST` failing over from `gemini-3.8-flash` `503`/`429` to `gemini-3.5-flash-lite` `200 OK`).
  - Independent `scheduler_loop` and `monitor_loop` running in FastAPI lifespan without interrupting or depending on NSE scheduler state.
  - Risk guardrails: configurable `max_daily_trades` (`0` = no count limit), max 1 open primary MCX position, stop risk `<= 0.25%` cash, daily realized loss limit `<= 1%`, 30m repeat-contract SL cooldown, 1h pause after 3 consecutive SL exits, 5m no-entry before close, expiry-day entry block.
- **MCX Transactional Storage ([`backend/mcx_storage.py`](file:///home/pravin/Documents/Trading/papertrade/backend/mcx_storage.py)):**
  - Uses existing `app_kv` (`AppKVModel`) with transaction-scoped PostgreSQL advisory locks (`pg_advisory_xact_lock`) and SQLite `BEGIN IMMEDIATE` for tests — zero DB schema migrations required.
- **MCX Market, Research & Isolated Paper Wallets ([`backend/mcx_market.py`](file:///home/pravin/Documents/Trading/papertrade/backend/mcx_market.py)):**
  - Primary MCX ledger (`mcx-paper:<uid>`), Champion research wallet (`mcx-champion:<uid>`), Challenger research wallet (`mcx-challenger:<uid>`), no 100-trade truncation, fresh ask for manual entry and fresh bid for square-off.
- **MCX 3-Tab UI ([`frontend/src/components/McxResearch.jsx`](file:///home/pravin/Documents/Trading/papertrade/frontend/src/components/McxResearch.jsx), [`frontend/src/components/McxDebatePanel.jsx`](file:///home/pravin/Documents/Trading/papertrade/frontend/src/components/McxDebatePanel.jsx)):**
  - Tabs: `Option Buy/Sell`, `Chat` (manual debate + persistent MCX Auto-Debate scheduler + Auto-Execute gate + Bull/Bear/Judge + Quant + memory/dates/reports), `History` (paged debate history + Champion/Challenger comparison).

## 2. Verification & Environment Configuration
- **Verified Safe Defaults:** Keep `MCX_AUTO_EXECUTION_ENABLED=false` and `V6_AUTO_EXECUTION_ENABLED=false` until live primary auto-fill tests pass.
- **Verified Live Render Config Values (ready for operator to set on Render when enabling MCX Auto-Debate / Shadow):**
  - `MCX_HISTORICAL_SESSIONS=2026-08-01/2026-11-01/09:00/23:30`
  - `MCX_OPTION_FUTURE_MAP={"2026-12-16":"CRUDEOIL18DEC26FUT","2027-01-15":"CRUDEOIL19JAN27FUT","2027-02-17":"CRUDEOIL19FEB27FUT"}`
  - `MCX_SPECIFICATIONS_VERIFIED=true`, `MCX_CALENDAR_VERIFIED=true`, `MCX_SHADOW_ENABLED=true` (while keeping `MCX_AUTO_EXECUTION_ENABLED=false`).
- **Remaining Limitations:** Render Free can sleep on HTTP inactivity (outbound WS does not prevent spin-down); `scikit-learn` optional for offline `research_ml.py`; live NSE session auto-execution validation pending next NSE open (`09:15–15:30 IST`).
