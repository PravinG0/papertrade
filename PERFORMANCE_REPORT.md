# TradeLab V5 — Performance & Load Report

**Date:** 26 November 2026

## Measured Backend & API Metrics

| Metric | Measured Value | Notes |
| --- | --- | --- |
| Historical API Calls / Debate (cold cache) | **5** (`1m`, `5m`, `15m`, `1h`, `1d`) | Serialized via `_candle_lock` (`0.65s` min spacing) |
| Historical API Calls / Debate (warm cache) | **0** | Interval TTLs: `30s` (1m), `45s` (5m), `120s` (15m), `180s` (1h), `300s` (1D) |
| Cold 5-Timeframe Fetch Latency (`NIFTY`) | **4,052.7 ms** (~4.05s) | Well within `QUANT_MAX_VERDICT_AGE_SECONDS=180` |
| Warm Cached 5-Timeframe Fetch Latency | **2.1 ms** | ~1,930x faster than cold fetch |
| Concurrent 10× Identical Candle Requests | **383.2 ms** total | Singleflight `_candle_inflight` deduplicates to **1** SmartAPI HTTP call |
| Python Process Peak RSS Memory | **49.5 MB** | Measured during live candle + backtest benchmark |
| Frontend Production Bundle (`vite build`) | **414.49 kB** main / **173.56 kB** charts | 1,598 modules, built in `6.50s` |

## Compatibility & Recommendations
- **Render / Supabase / Angel One:** Single-worker Render deployment handles 5-timeframe fetches cleanly at `0.65s` pacing without triggering SmartAPI `HTTP 403` rate-limit rejections.
- **Database Concurrency:** Wallet lock (`_lock_portfolio`) and `ai_trade_evidence` unique constraint prevent duplicate fills and concurrent overspending.
