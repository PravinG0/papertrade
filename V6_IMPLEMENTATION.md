# TradeLab Cloud V6 — Architecture & Implementation

**Date:** 27 November 2026  
**Base Production Commit:** `308e7aa` (Backup tag: `backup-pre-v6-308e7aa`)  

## Implemented Architecture
1. **Restored V5 Quantitative Validation Engine ([`backend/quant_engine.py`](file:///home/pravin/Documents/Trading/papertrade/backend/quant_engine.py)):**
   - 5-timeframe completed-bar validation (`1m`, `5m`, `15m`, `1h`, `1d`; 50 valid candles minimum, up to 200 warm-up) with `41e2e67` isolated prior-day gap tolerance when today's live session tail is strictly contiguous.
   - Market regime detection (`BULL_TREND`, `BEAR_TREND`, `RANGE_OR_TRANSITION`), directional alignment, two-sided bid/ask spread & fee-adjusted net R:R (`QUANT_MIN_NET_RR=1.5`), Black-Scholes midpoint Greeks estimate, 90-day provenance-backed memory, and offline Champion/Challenger (`research_backtest.py`) + ML calibration (`research_ml.py`).
2. **Angel One WebSocket Streaming 2.0 ([`backend/broker_stream.py`](file:///home/pravin/Documents/Trading/papertrade/backend/broker_stream.py), [`backend/angel_service.py`](file:///home/pravin/Documents/Trading/papertrade/backend/angel_service.py)):**
   - Outbound `wss://smartapisocket.angelone.in/smart-stream` connection for `NSE`, `NFO`, `BSE`, `BFO`, `MCX`.
   - Binary quote/snapquote packet decoding (`decode_packet`), exchange+token keys, duplicate/out-of-order sequence checks, exchange timestamp freshness (`fresh`), dynamic capped subscriptions (`BROKER_STREAM_MAX_SUBSCRIPTIONS=300`), heartbeat, reconnect/resubscribe, and bounded REST fallback.
   - Preserves `1.2s` historical candle spacing, `60s` 5m cache TTL (`1m`: `55s`, `15m`: `300s`, `1h`: `600s`, `1d`: `1800s`), `HTTP 403` retry backoff, `401`/`AG8001`/`AG8002`/`AG8003` token renewal, and incremental tail merging.
3. **MCX Crude Oil Research, AI Analysis & Isolated Paper Trading ([`backend/mcx_market.py`](file:///home/pravin/Documents/Trading/papertrade/backend/mcx_market.py), [`frontend/src/components/McxResearch.jsx`](file:///home/pravin/Documents/Trading/papertrade/frontend/src/components/McxResearch.jsx)):**
   - Real `CRUDEOIL` futures & options from `scrip_master` (`1,100` contracts: `lot_size=100`, `tick_size=1.0` FUT / `0.1` OPT).
   - Seasonal MCX calendar (`configured_mcx_bounds`, winter `09:00–23:55 IST` for `2026-11-02..2027-03-12` + `MCX_HOLIDAYS`/`MCX_SPECIAL_SESSIONS`).
   - MCX AI Technical Analysis (`/api/mcx/debate/run`) and isolated MCX `BUY CE`/`BUY PE` paper wallet (`/api/mcx/paper/state`, `/api/mcx/paper/order`, `/api/mcx/paper/squareoff`) using `calculate_mcx_charges` (brokerage, CTT, MCX txn, SEBI, stamp, GST). Completely isolated from NSE index `portfolios`/`paper_trades`.
4. **Live Shadow Trading, Champion vs Challenger & Dynamic Risk Limits ([`backend/shadow_engine.py`](file:///home/pravin/Documents/Trading/papertrade/backend/shadow_engine.py), [`backend/adaptive_store.py`](file:///home/pravin/Documents/Trading/papertrade/backend/adaptive_store.py)):**
   - Per-user isolated shadow ledger (`app_kv` key `shadow-ledger:<uid>`) tracking all accepted & rejected AI debates in independent Champion (original AI) and Challenger (V6 quant-validated) research wallets, settled only against genuine live quotes.
   - Per-user dynamic risk config (`app_kv` key `risk-config:<uid>`): configurable `max_daily_trades` + `no_count_limit` mode, `max_daily_loss_inr`, `max_concurrent_positions`, `max_consecutive_losses`, and `loss_streak_cooldown_minutes`, enforced inside `guard_auto_fill`.
5. **Market Feed Status & UI ([`frontend/src/components/Header.jsx`](file:///home/pravin/Documents/Trading/papertrade/frontend/src/components/Header.jsx), [`frontend/src/components/DebateArena.jsx`](file:///home/pravin/Documents/Trading/papertrade/frontend/src/components/DebateArena.jsx)):**
   - Header displays `LIVE · WS (<age>s)`, `LIVE · REST`, `STALE`, `DISCONNECTED · UNAVAILABLE`, `DELAYED / UNAVAILABLE`, `MARKET CLOSED`, or `SIMULATED`, with WebSocket/REST transport, reconnects, and exchange timestamp tooltip.
   - DebateArena includes Quantitative Validation, Dynamic Risk Limits, and Shadow Research panels.
