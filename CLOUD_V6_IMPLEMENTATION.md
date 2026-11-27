# TradeLab Cloud V6 — implementation and verification

## Release scope (27 November 2026)
Base: `papertrade(5).zip`, the supplied cloud source, not a local application. The base's documentation described V5 but its executable code was missing the quantitative and research modules. Recovered the V5 changes using `papertrade(4).zip` as the common base; reconciled overlaps in `angel_service.py`, `test_candle_resilience.py` and `DebateArena.jsx` instead of replacing newer production fixes. Existing Render/Vercel deployment configuration, authentication and database/migration modules are retained. No live data or database credentials were used and no deployment was performed.

## Implemented
- Restored V5 five-timeframe snapshot validation (1m, 5m, 15m, 1h, 1d; 50 completed valid candles, up to 200 warm-up), directional checks, exact option contract, ask-side entry, depth/spread and fee-adjusted risk/reward validation, 90-day verified-evidence memory, original proposal/rejection evidence, and quantitative panel. Restored offline Champion/Challenger and ML research modules; neither represents an active trained model or an independent live shadow trader.
- `backend/broker_stream.py`: direct outbound Angel One WebSocket 2.0, NSE/NFO/BSE/BFO/MCX subscriptions, binary quote/snapquote decoding, exchange+token keys, timestamp and sequence checks, capped dynamic subscriptions, heartbeat, reconnect and resubscribe, safe shutdown, latency telemetry. Provisional observed OHLC aggregation is internal only; historical chart/AI candles still come from REST. It is not a lossless tick store.
- `backend/angel_service.py`: shared streaming-first quote cache; bounded, paced REST recovery with per-token retry spacing, broker cooldown and validation; no fabricated live prices when credentials/data unavailable. Reject missing or aged exchange timestamps rather than treating HTTP receipt as fresh. Retain newer historical 1.2-second spacing, retry, auth recovery, incremental cache and singleflight behavior. Avoid relabelling simulated/stale candles as cached-live. Option LTP settlement still uses the existing sampled monitor, not every streamed tick. Full broker payload, depth orientation, timestamps and runtime behavior need live verification.
- `backend/mcx_market.py`, `scrip_master.py`, `main.py`: read-only standard CRUDEOIL futures and option-series research; use actual MCX instrument master metadata, separate future and option expiry selectors, futures historical candles and deterministic timeframe trend, LTP, bid/ask, OI, volume, lot and tick metadata. Authenticated `/api/mcx/market` and `/api/mcx/candles`. Do not infer which futures month underlies a particular option. Explicitly reject commodity orders through the index order path. No MCX wallet changes or commodity-specific AI execution yet.
- `frontend/src/components/McxResearch.jsx`, `App.jsx`, `DebateArena.jsx`: separate responsive MCX screen, source and session status, stream diagnostics, restored quantitative panel, and visible automatic-execution pause. Existing browser-to-backend WebSocket remains distinct from the new broker-to-backend WebSocket.
- `backend/config.py`, `.env.example`, `requirements.txt`: stream controls and WebSocket dependency, MCX-specific seasonal session config, explicit pre-verification automatic execution gate. Keep one backend worker for now. No new database schema for V6.

## Settings and rollout
Defaults: BROKER_STREAM_ENABLED=true, BROKER_REST_FALLBACK=true, BROKER_STREAM_MAX_SUBSCRIPTIONS=300, BROKER_QUOTE_MAX_AGE_SECONDS=10, V6_AUTO_EXECUTION_ENABLED=false, MCX_RESEARCH_ENABLED=true. Existing AUTO_MAX_DAILY_TRADES remains configurable (default 5); dynamic risk-budget limits are not implemented. Keep ALLOW_SIMULATED_TRADING=false and existing private DATABASE_URL/JWT/Google/broker/AI configuration. No private credentials or database files are included. Existing manual paper trading and settlement monitoring remain available; the automatic AI execution gate stays closed until verified. Do not reset the wallet.

MCX standard non-agricultural winter hours are 09:00–23:55 IST for 2026-11-02 through 2027-03-12, subject to holidays and special sessions. Config expires after this period instead of assuming permanent timings. Populate MCX_HOLIDAYS and MCX_SPECIAL_SESSIONS from official circulars. The schedule is not an official calendar feed and no guarantee is made about any specific holiday. Verify standard CRUDEOIL contract master price scaling, lot metadata, exact underlying future, expiry/devolvement, settlement, tick size, fees and margin separately before allowing commodity trades. Browse-only strike windows are centered on the selected future; this is not an option-underlying mapping.

References for operator verification: MCX Circular MCX/TRD/550/2026, MCX Market Operations FAQ (https://www.mcxindia.com/faq/market-operations); Angel One SmartAPI WebSocket Streaming 2.0 (https://smartapi.angelone.in/docs/WebSocket2) and official SmartAPI Python SDK. Verify latest broker protocol and exchange specifications at rollout.

## Actual tests
- Python offline selection: 280 passed (includes 47 new V6 cases).
- JavaScript date/time suite: 28 passed.
- Python compileall: passed.
- Vite production build: passed, 1,599 modules transformed.
- Full pytest: attempted, stopped during collection with 10 errors; missing aiosqlite/pyotp and other required runtime libraries. Dependency install unavailable in build environment. No claim of full backend pass.
- New offline coverage: binary frames, exchange keys, invalid and stale data, duplicate/out-of-order checks, subscriptions, MCX session bounds and holidays, contract parsing/selection and configuration. These are unit fixtures, not actual broker feed traffic.
- Not tested: live WebSocket, broker authentication, depth parity, live REST fallback, production PostgreSQL, full restart/reconnection integration, browser responsiveness and settlement timing. No trade accuracy or profitability claims.

Reproduce (from backend, isolated database via tests/conftest.py):
```
python -m pip install -r requirements-dev.txt
PYTHONPATH=. python -m pytest -q
PYTHONPATH=. python -m pytest -q tests/test_offline_core.py tests/test_adaptive_memory.py tests/test_audit_offline.py tests/test_qa_repairs_offline.py tests/test_wallet_accounting.py tests/test_quant_v5.py tests/test_cloud_v6_offline.py
```
Frontend: `npm ci`, `node --test tests/*.test.js`, `npm run build`.

## Remaining release blockers
1. Full runtime suite and live data checks, especially exchange timestamps, snapshot depth/price scaling, REST fallback, actual WebSocket heartbeat, reconnect, session renewal, subscription limits and sampled settlement. Test with one worker, profile request and memory usage.
2. Test V5 live integration, data availability, old record compatibility, wallet consistency and risk gate. The supplied older wallet reconciliation preview is historical, not a new correction.
3. MCX paper execution, AI debate, independent instrument-specific adaptive memory, verified fee/multiplier and margin accounting, exchange-specific exit scheduler, option-to-futures link, expiry/devolvement handling. All pending. The read-only MCX screen is useful for late-session feed testing, not yet late-session automatic learning/trading.
4. Live shadow trading and dynamic risk-budget limits remain pending. Offline research modules need real labelled data, separate provenance and out-of-sample evaluation.
5. Render Free can suspend or restart. Outbound broker ticks alone are not a guarantee of availability. Verify extended-hour operation, recovery and no duplicate settlements. Do not claim 24/7 monitoring. Existing keep-alive configuration retained, not a new uptime guarantee.
6. Tick-to-chart integration and lossless tick-driven settlement require further work. Historical bars currently remain REST-derived; internal provisional bars are not authoritative AI inputs. No distributed stream/rate-limit coordination.

## Rollback and data protection
Set V6_AUTO_EXECUTION_ENABLED=false while validating. BROKER_STREAM_ENABLED=false restores REST-only quote acquisition with strict freshness checks. MCX_RESEARCH_ENABLED=false disables MCX endpoints. Do not roll back database schema destructively or reset any wallet. Preserve existing database and deployment environment, test migration compatibility on a disposable copy and use Git checkpoint/revert rather than force-push. No live deployment has been performed.
