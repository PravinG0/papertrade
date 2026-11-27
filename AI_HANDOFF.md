# TradeLab Cloud V6 — AI Developer Handoff

**Current Revision:** TradeLab Cloud V6 (`TradeLab_Cloud_V6` merged onto `main` `308e7aa`, backup tag `backup-pre-v6-308e7aa`), 27 November 2026.  
**Read alongside:** `V6_IMPLEMENTATION.md`, `CLOUD_V6_IMPLEMENTATION.md`, `WEBSOCKET_TEST_REPORT.md`, `MCX_TEST_REPORT.md`, `SHADOW_TRADING_TEST_REPORT.md`, `DATABASE_MIGRATION_REPORT.md`, `DATA_PRESERVATION_REPORT.md`, `OLD_VS_V6_COMPARISON.md`, `FINAL_QA_REPORT.md`, `DEPLOYMENT_REPORT.md`.

---

## 1. Cloud V6 Architecture
- **Frontend (React 18 + Vite 5.4 + TailwindCSS on Vercel):**
  - [`Header.jsx`](file:///home/pravin/Documents/Trading/papertrade/frontend/src/components/Header.jsx): Market Feed Status (`LIVE · WS (<age>s)`, `LIVE · REST`, `STALE`, `DISCONNECTED · UNAVAILABLE`, `DELAYED / UNAVAILABLE`, `MARKET CLOSED`, `SIMULATED`) with WebSocket/REST transport, reconnects, and exchange timestamp tooltip.
  - [`DebateArena.jsx`](file:///home/pravin/Documents/Trading/papertrade/frontend/src/components/DebateArena.jsx): Quantitative Validation panel (5-timeframe direction & bar count grid, regime, spot freshness, option preview spread/net R:R/model delta), Dynamic Risk Limits panel, and Shadow Research (Champion vs Challenger) panel.
  - [`McxResearch.jsx`](file:///home/pravin/Documents/Trading/papertrade/frontend/src/components/McxResearch.jsx): MCX CRUDEOIL futures & options viewer, seasonal session status, MCX AI Technical Analysis (`/api/mcx/debate/run`), and isolated MCX Paper Trading wallet (`/api/mcx/paper/*`).
- **Backend (Python + FastAPI + Supabase PostgreSQL on Render Free):**
  - [`broker_stream.py`](file:///home/pravin/Documents/Trading/papertrade/backend/broker_stream.py) & [`angel_service.py`](file:///home/pravin/Documents/Trading/papertrade/backend/angel_service.py): Outbound Angel One WebSocket 2.0 (`wss://smartapisocket.angelone.in/smart-stream`) for `NSE`/`NFO`/`BSE`/`BFO`/`MCX` + bounded REST fallback + `1.2s` historical candle pacing, `60s` 5m cache TTL, `HTTP 403` retry backoff, and `401`/`AG8001` token renewal.
  - [`quant_engine.py`](file:///home/pravin/Documents/Trading/papertrade/backend/quant_engine.py): Restored V5 5-timeframe completed-bar validation (`1m`, `5m`, `15m`, `1h`, `1d`) with `41e2e67` isolated prior-day gap tolerance.
  - [`mcx_market.py`](file:///home/pravin/Documents/Trading/papertrade/backend/mcx_market.py): `CRUDEOIL` contract parser (`lot_size=100`), seasonal session bounds (`09:00–23:55 IST` winter `2026-11-02..2027-03-12`), MCX charges (`calculate_mcx_charges`), technical summary, and isolated MCX paper wallet (`mcx-paper:<uid>` in `app_kv`).
  - [`shadow_engine.py`](file:///home/pravin/Documents/Trading/papertrade/backend/shadow_engine.py) & [`adaptive_store.py`](file:///home/pravin/Documents/Trading/papertrade/backend/adaptive_store.py): Live Shadow Trading (`shadow-ledger:<uid>`), Champion vs Challenger virtual wallets, and Dynamic Risk Limits (`risk-config:<uid>`).

## 2. Database Preservation & Zero-Migration Rollout
- **Zero schema migrations required:** Shadow ledger, MCX paper wallet, and dynamic risk config use existing `app_kv` (`AppKVModel`), and V5 metadata uses existing JSON columns (`debate_records.payload`, `ai_trade_evidence.snapshot`).
- **`pravin_g` (`user_id=1`, `portfolio_id=10`) Preserved:** Reconciled cash `₹9,91,609.77`, `90` closed `paper_trades`, all AI debates, daily reports, and adaptive learning memory remain 100% intact.

## 3. Environment Variables & Safety Gates
- Keep `V6_AUTO_EXECUTION_ENABLED=false` and `ALLOW_SIMULATED_TRADING=false` until live NSE session validation is completed with `EXCHANGE_HOLIDAYS` and `MCX_HOLIDAYS` configured.
- Keep `BROKER_STREAM_ENABLED=true`, `BROKER_REST_FALLBACK=true`, `MCX_RESEARCH_ENABLED=true`, and 1 Render worker.
- Rollback: `git checkout backup-pre-v6-308e7aa` (no DB rollback needed).
