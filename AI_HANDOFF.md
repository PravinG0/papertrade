# TradeLab / PaperTrade — AI developer handoff

**Revision:** Mobile responsiveness update, 25 November 2026.  
**Base:** `papertrade_wallet_history_fixed.zip` (includes earlier audit, terminal navigation, wallet and history fixes).  
**Current scope:** Frontend layout and developer documentation only. Backend source, database schema, API contracts and trading rules are unchanged in this revision.

## 1. Project overview

TradeLab is a virtual options paper-trading application for NIFTY, BANKNIFTY, FINNIFTY and SENSEX. It uses Angel One SmartAPI for market data and an internal Python paper engine for simulated orders; no real broker order placement was introduced. The AI debate currently offers NIFTY and BANKNIFTY selection. Bull and Bear agents analyse market data and the Judge agent produces a verdict (BUY CE, BUY PE or NO TRADE). Manual and AI trades share the paper engine and account. Auto-debate is scheduled on the backend. AI reports provide inferred explanations of trading outcomes, not verified market causes.

### Architecture and ownership

| Component | File / location | Responsibility |
|---|---|---|
| Frontend shell | `frontend/src/App.jsx` | Terminal tabs, account state, data refresh, WebSocket, orders, modal visibility |
| API client | `frontend/src/api.js` | Axios, JWT, REST endpoint wrappers, backend URL |
| Auth | `frontend/src/context/AuthContext.jsx`, `backend/auth.py` | Account login and session handling |
| Header / wallet | `frontend/src/components/Header.jsx` | Equity, cash, margin, account and trade P&L, market status |
| Trading UI | `OptionChain.jsx`, `TradingChart.jsx`, `OrderModal.jsx`, `PositionsPanel.jsx`, `OrdersPanel.jsx`, `QuickScalperBar.jsx` in components | Exact contract selection, chart, order entry, open positions and historical ledger |
| AI UI | `DebateArena.jsx`, `DailyReportModal.jsx` | Debate and scheduler controls, archive, daily reports |
| Other UI | `PcrOiPanel.jsx`, `PnlHeatmap.jsx`, `StrategyPayoff.jsx`, `ReplayControls.jsx` | OI analysis, journal, payoff, historical replay |
| Responsive design | `frontend/src/index.css`, `frontend/tailwind.config.js`, component JSX | Tailwind light theme, mobile breakpoints and layout |
| Timestamp helper | `frontend/src/utils/tradeDates.js` | IST parsing, formatting and inclusive date comparisons |
| Backend API | `backend/main.py` | FastAPI REST and `/ws/terminal` |
| Data feed | `backend/angel_service.py`, `backend/scrip_master.py` | Angel One REST polling, scrip resolution, option chain and candles |
| Trading | `backend/paper_engine.py`, `backend/wallet_accounting.py` | Paper orders, fills, MTM, wallet, position lifecycle |
| Persistence | `backend/database.py` | SQLite or configured PostgreSQL |
| AI | `backend/debate_engine.py`, `backend/agents/`, `backend/scheduler.py` | Gemini debate, verdicts, reports and scheduling |
| Replay | `backend/replay_engine.py` | Historical market replay |
| Hosting | `render.yaml`, `vercel.json`, `frontend/vercel.json` | Render backend, Vercel frontend |

Market flow: Angel One REST polling → FastAPI backend → browser REST and WebSocket updates → React. Do not confuse the backend-to-browser WebSocket with a direct Angel One SmartAPI streaming connection.

Key API routes: `/api/status`, `/api/indices`, `/api/candles`, `/api/expiries`, `/api/option-chain`, `/api/trading/state`, `/api/trading/order`, `/api/trading/reset`, `/api/trading/history`, `/api/trading/all-trades`, `/api/trading/export`, `/api/debate/run`, `/api/debate/latest`, `/api/debate/history`, `/api/debate/{debate_id}/execute`, `/api/scheduler/start`, `/api/scheduler/stop`, `/api/scheduler/status`, `/api/reports/daily`. Read the actual endpoint definitions before changing payloads.

## 2. Latest changes — mobile and tablet responsiveness

The existing desktop table and trading logic are retained. Mobile presentation uses the same data and event handlers, not a second trading engine or duplicate table.

- Header: compact, wrapping brand and status; responsive wallet/actions layout, separate cash/margin/P&L details, swipeable market ticker, larger action buttons, profile menu retained. Header scrolls with content below 1024px to free vertical screen space.
- Main layout: single-column terminal on tablets/phones, min-width constraints, chart/option chain panel heights adjusted, independently scrolling market tables. Desktop grid remains at `lg` (1024px and above).
- Terminal tabs: Option Buy/Sell, Chat, History retained; sticky on phones, larger touch controls, mobile tab changes return to the top of main content when scrolled deep. Existing mounted chart/debate components are retained.
- Mobile Trade History and Open Positions: same desktop table rows displayed as labelled two-column cards below 768px, with full-width instrument, timestamp and action fields; status, entry/exit, SL, target, P&L and exit controls retained. Table headers remain in the accessibility tree and roles explicitly supplied. No duplicate trade data requests added.
- Date filters: responsive two-column layout (single column below 360px), full-width search, enlarged inputs/buttons, horizontal status-filter ribbon, stacked history toolbar. Entry/exit date range semantics unchanged.
- Charts and option chain: control groups wrap, larger buttons, option tables scroll inside their own panel. Simple chain may still scroll on very narrow phones; Advanced intentionally scrolls to preserve analytics columns. Compare chart sheet uses dynamic viewport height.
- AI chat: wrap market metric strip and controls; larger debate action targets. Existing scheduler and archived debate restrictions unchanged.
- Quick Scalper: CE and PE controls stack on phones, preset groups wrap. No execution behavior changed.
- Other pages: OI distribution bars flex to available width, journal table has a minimum width with internal scrolling, replay controls wrap.
- Dialogs: login, order, report, risk calculator, shortcuts and comparison dialogs have mobile viewport height bounds, safe-area space and scrolling.
- Navigation: bottom nav reserves safe-area space; selected marker anchored to its own item. Main padding prevents bottom nav from covering content.
- Contrast: corrected inactive terminal/history labels against the light theme. Important: `tailwind.config.js` intentionally inverts the slate palette; `text-slate-600` is a light grey here. Use `text-ink` or deliberate hex colours for dark text.
- Breakpoints: <360px narrow-phone adjustments; <768px mobile cards, bottom nav and filter grid; <1024px stacked terminal. `viewport-fit=cover` enabled. No device-specific UA detection.

## 3. Cumulative changes from earlier revisions

### Initial audit and bug fixes

- Private REST routes require authentication; invalid/expired JWT rejected instead of guest fallback; private order WebSocket updates scoped to owner; portfolio cleared on account change.
- Validated side, order type, positive finite prices, limit/trigger values and market hours. Balance rechecked at actual pending-order fill. Pending orders persist using `pending_paper_orders`; removed transactionally at fill/cancel/reset; expired prior-day and restart replay orders discarded.
- SL/target fill at observed LTP, limit fills at qualifying observed LTP; commit before removing positions. This remains a simplified simulation.
- Reject unknown/expired dated contracts instead of substituting another expiry; prevent ambiguous strike-only MTM mappings; live entries use broker contract lot sizes.
- Live-data guard on AI debates; no simulated chain or spot fallback for live AI decisions. Verdict execution locked against duplicates; NO_TRADE blocked; unique debate IDs; latest debate scoped to index.
- Replay owner isolation for MTM; block new live/AI orders during replay; require no open positions/pending orders before starting; stop cancels replay orders and closes replay positions. Replay data failure does not silently become simulated data by default.
- End-of-day report generation scoped to trade owners; report refresh; frontend wallet-reset error feedback; portable startup/database paths; stronger JWT fallback; offline simulation opt-in. Tests isolated from actual database.

### Terminal restructure

- Three tabs within Terminal: Option Buy/Sell (option chain, charts, orders, open positions and quick trade), Chat (Bull/Bear/Judge, scheduler, verdict execution), History (open/closed ledger and debate archive).
- Old separate debate navigation removed; existing AI component stays mounted, archive opens in read-only mode, chart stays mounted across tab switches.
- Retained OI & Greeks, P&L Journal, Strategy Payoff, historical replay, Daily Report and authenticated closed-trade CSV export.
- Do not infer manual vs AI source: existing trades do not consistently store that provenance. Debate archive uses existing API maximum of 100 sessions.

### Wallet and history correction

- Equity = available cash + used margin + unrealized P&L. Account P&L = equity − initial capital. Distinguish account P&L from current wallet-cycle trade P&L and all-time reporting fields.
- Per-account reset realized-P&L baseline stored in existing `app_kv` table. Historical ledger preserved. Account snapshots serialized with mutations. Zero cash does not fall back to starting capital.
- Historical unreconciled differences displayed, not silently rewritten. Earlier screenshot implied ₹36,564.37 unexplained difference assuming ₹10 lakh starting capital and no margin; exact cause needs deployed database audit. Do not manufacture adjustment trades.
- History inclusive From/To filters by entry or exit date; same day possible by equal dates; Today/Clear filters, index/status/search, filtered realized P&L and count. Full timestamps `DD/MM/YYYY HH:mm:ss` in IST. Existing naive backend timestamps treated as IST; explicit offsets converted. CSV remains full closed-trade export, not filtered export. Debate history dates/filtering were not altered.

Original detailed reports retained: `FIX_REPORT.md`, `TERMINAL_CHANGES.md`, `WALLET_HISTORY_CHANGES.md`.

## 4. Setup, tests and deployment

1. Back up the existing database. Preserve environment configuration separately. Copy `.env.example` to `.env` only for a fresh environment and supply real settings securely. Never commit `.env` or share API secrets.
2. Create a Python virtual environment. From root: `python -m pip install -r backend/requirements-dev.txt`.
3. From `backend/`: `python -m pytest -q`, then `python -m uvicorn main:app --host 127.0.0.1 --port 8000`.
4. From `frontend/`: `npm ci`, `npm run dev` (port 5173), `npm run build`, `node --test tests/*.test.js`.
5. Render backend configuration is in `render.yaml`. Use persistent PostgreSQL via `DATABASE_URL` in hosted environments; Render ephemeral SQLite is unsafe for durable trading records. Keep one backend worker while scheduler/replay/position state remain process-local.
6. Vercel frontend: use existing frontend root and build settings. Set `VITE_API_URL` to the intended backend if needed; api.js contains an existing production fallback. Check WebSocket URL in App.jsx too. For this revision only, if the wallet/history backend revision is already deployed, only redeploy frontend. If not, deploy the accumulated backend updates as well after backup and tests.

### Verification of this revision

- Vite production build: PASS (1,597 modules transformed, ~644 kB minified JS in 8.18s).
- Python compileall: PASS.
- Full backend pytest suite: PASS (28/28 passed in 8.51s, including `test_wallet_accounting.py`, `test_regression_fixes.py`, `test_offline_core.py`, `test_e2e_report.py`, `test_daily_report_agent.py`, `test_engine.py`).
- Node timestamp tests: PASS (3/3 passed in `frontend/tests/tradeDates.test.js`).
- Database compatibility: Verified with Supabase PostgreSQL cloud transaction pooler (port 6543) and local SQLite.
- Live deployment health check: Render backend active (`is_postgres: true`, 200 OK), Vercel frontend active (200 OK).

### Mobile acceptance checklist for next AI/developer

Test at 320×568, 360×800, 390×844, 430×932, 768×1024, 1024×768 and desktop 1440×900. Include portrait/landscape and iOS keyboard/safe areas.

- Check no horizontal page overflow; intentional sideways scroll limited to data panels/tickers.
- Test all three Terminal tabs and bottom navigation; tab switch should preserve chart DOM and not stop auto-debate or monitoring.
- Check both CE/PE orders, all order modal fields, pending-order cancel, SL edit and position exit using mock/sandbox data only. Verify no duplicate requests or unintended trades.
- Check wallet numbers, sign-in/profile dropdown, reset confirmation, calculator, report and replay dialogs; all controls reachable above bottom bar and keyboard.
- Test History with empty, open, closed, long symbols and large counts; inclusive date filters, invalid date order, Today, clear, IST entry/exit display, filtered P&L and CSV behavior.
- Check archive opens read-only, AI scheduler and countdown survive tab changes; no API requests to production credentials during tests.
- Check chart resize and compare mode, option chain Simple/Advanced, OI, Journal and Strategy; verify desktop tables and controls have not regressed.

## 5. Remaining limitations / rules for future changes

- No production-readiness claim until browser/runtime, DB integration and live quote tests pass. Never execute real broker trades; keep the application paper-only.
- Direct Angel One WebSocket streaming has not been implemented. Scheduler remains global; replay market display is shared and crash recovery needs hardening.
- Paper fills are LTP-based, not actual bid/ask, liquidity, margin rules or exchange fills. Holiday calendar and statutory fees require separate verification. AI reports are inferred.
- Existing data mismatch requires deployed DB audit; don't change historical wallet values based on a screenshot.
- Manual/AI trade provenance, filtered CSV export and debate date filters remain possible enhancements, not completed features.
- Bundle size warning remains; mobile cards may be tall for large histories. Consider pagination/virtualization after browser verification, preserving exports and filter totals.
- Source-only package excludes real secrets, local database, private sessions, Git metadata, node_modules, dist and caches. Keep these separately.
- When another AI modifies this project: read this file and the exact source, keep previous regression fixes, avoid rewriting unrelated logic, update this handoff and report tests actually executed.
