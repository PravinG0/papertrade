# PaperTrade — source audit and corrective patch

## Verification status
- Frontend: `npm run build` passed, 1,596 modules transformed. Vite warned that the JS bundle is larger than 500 kB (632.59 kB minified).
- Python: compilation of backend source passed.
- Offline core: 5 tests passed (Black–Scholes parity, delta, implied volatility, strategy payoff, exact-contract resolution).
- Full backend suite: blocked at test collection by missing `aiosqlite`. Dependency installation also failed because the environment cannot resolve the package repository; `pyotp` was the first missing download. No live broker, Gemini, Google OAuth, external PostgreSQL or browser E2E test was performed.

## Implemented source corrections
| Area | Changes |
|---|---|
| Authentication and privacy | Private REST endpoints require sign-in; invalid tokens are rejected; authenticated sockets are associated with a verified account; private ORDER_UPDATE messages are delivered only to their owner, not guest or other accounts. |
| Order validation | Reject invalid/zero/non-finite prices, invalid sides and order types; require positive limit/trigger prices; market-hours rules apply to pending entries and fills. |
| Wallet and pending orders | Recheck available cash in the actual fill transaction. Introduce pending_paper_orders table; pending orders persist across restarts, are removed in the fill/cancel/reset transaction and expired prior-day orders are discarded. Replay pending orders are discarded at restart. |
| Fill prices | SL and target exits record observed LTP rather than trigger price; limit orders use observed qualifying LTP; position removal occurs after DB commit. This is a simplified LTP simulation, not an exchange execution model. |
| Exact contracts | Reject invalid selected expiries instead of silently falling back to the nearest; do not remap missing dated symbols to another expiry; avoid ambiguous strike-only keys in MTM. Live entry quantity uses the broker contract lot size. |
| AI | Skip live debates when selected index spot or option chain is unavailable or simulated. Serialise verdict execution; prevent executing a verdict twice or executing NO_TRADE through an override; UUID debate IDs; latest-by-index must match that index. |
| Replay | Associate owner before initial tick, scope simulated MTM to owner, block new live orders/AI execution during replay, prevent replay start when there are active positions or pending orders, cancel replay pending orders and close replay positions on stop, reject new replay orders after 15:15. Historical feed failure no longer silently becomes simulated data by default. |
| Reports | EOD report generation iterates owners of trades opened or closed that day and refreshes existing report; fixes guest-only automatic generation. |
| Frontend | Require login to open the order modal; clear stale portfolio data on account change; correct replay visibility flag; report actual wallet-reset failure instead of clearing the UI and showing fake success. |
| Configuration | Portable default SQLite location and startup script; replace predictable default JWT with private-derived or ephemeral secret; offline trading is disabled by default; cleaned example config. |
| Testing | Added dependency-light and backend regression tests; test configuration isolates a temporary DB and blanks API credentials. |

## Setup and testing
Use your original environment locally or set environment variables in your deployment platform; **do not put real secrets into Git**. Rotate exposed credentials and use a strong random JWT secret. Keep your existing database separately and make a backup before running the patched application. Database initialization adds the pending_paper_orders table automatically. Run one backend worker (global scheduler and in-memory position state are process-local).

1. Create/activate a Python virtual environment, preferably with the project Python version.
2. From the project root, `python -m pip install -r backend/requirements-dev.txt`.
3. Copy `.env.example` to `.env` and configure credentials and database. Do not copy placeholders as secrets. Offline mode is intentionally disabled unless `ALLOW_SIMULATED_TRADING=true` is explicitly selected (with broker credentials unset).
4. Run tests from backend: `python -m pytest -q`.
5. From backend: `python -m uvicorn main:app --host 127.0.0.1 --port 8000`.
6. From frontend: `npm ci`, then `npm run dev`.

## Remaining risks and deployment gates
- Runtime regression tests, live API credentials and exact quotes, report generation, database schema creation/migration and browser chart behavior must be tested with dependencies installed. No assertion of production readiness.
- Angel market data remains REST polling; browser WebSocket is backend-to-frontend. No broker order placement was introduced.
- Scheduler and replay are global single-instance features; replay market display remains shared; simultaneous replay/live requests and crash recovery of open replay positions require further integration hardening. The pending-order persistence changes have not been exercised against a real database here.
- Simulated fills are based on LTP, not actual bid/ask, depth, liquidity, real margin rules or exchange fills. Square-off and manual exits may use last observed prices; no exchange holiday calendar integration was added. Statutory fee rates and broker API/model availability were not independently verified.
- No migration of existing historical trades was performed; reset retains closed history as in the original implementation. AI reports remain inferred explanations, not verified causes. Large frontend bundle remains a warning.
- Original `.env`, local DB, debate session data, Git history, dependencies and generated build output are intentionally excluded from the source ZIP. Your uploaded original is unchanged.
