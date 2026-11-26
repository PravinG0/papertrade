# TradeLab V5 Hybrid — Production Merge Report

**Date:** 26 November 2026  
**Base Production Commit:** `56ddbfb` (Backup tag: `backup-pre-v5-hybrid-56ddbfb`)  
**Merged Candidate:** `tradelab_v5_hybrid.zip` (`V5_HYBRID_ENGINE.md`)

## Summary of Merge

`tradelab_v5_hybrid` was merged selectively into the production `main` codebase while preserving all existing production features, `.env` credentials, Supabase schema compatibility, and the Angel One historical candle resilience layer (`56ddbfb`).

### Newly Added Files
- `backend/quant_engine.py`: Deterministic 5-timeframe completed-candle validation, regime detection, directional gating, two-sided option spread/fee-adjusted net R:R validation, Black-Scholes Greeks estimate, and calibration band summaries.
- `backend/research_backtest.py`: Offline Champion vs Challenger backtest simulator (isolated research wallets).
- `backend/research_ml.py` & `backend/requirements-research.txt`: Offline purged-label chronological ML calibration pipeline.
- `backend/tests/test_quant_v5.py` & `backend/tests/test_v5_debate_integration.py`: Unit & integration tests for V5 validation, option gates, stale fill protection, and research isolation.
- `V5_HYBRID_ENGINE.md`: V5 architecture and verification specification.

### Modified Files
- `backend/angel_service.py`: Preserved `56ddbfb` candle rate limiting, singleflight deduplication, interval TTLs, token renewal (`401`/`AG8001`/`AG8002`/`AG8003`), `Retry-After` cooldowns, and incremental merging; added `exchange_timestamp` on spot quotes, strict OHLC rejection (`h < max(o,c)` or `l > min(o,c)`), removed fallback candles from real cache, and tuned `_candle_min_interval` to `0.65s` after live 5-interval testing caught an HTTP `403` burst on `BANKNIFTY`.
- `backend/debate_engine.py` & `backend/debate_schemas.py`: Integrated 5-timeframe validation (`1m`, `5m`, `15m`, `1h`, `1d`), spot/quote exchange timestamp checks, 1-lot option preview, original Judge proposal preservation, and V5 execution rechecks.
- `backend/paper_engine.py`: Added V5 `quant-v1` quote/spot timestamp (<= 30s) and completed-frame freshness recheck under the wallet lock before debiting.
- `backend/adaptive_memory.py`, `backend/adaptive_store.py`, `backend/agents/{bull,bear,judge}_agent.py`, `backend/config.py`, `.env.example`: Added 90-day provenance-backed V5 memory (`MEMORY_EXTENDED_DAYS=90`), calibration band reporting, and timeframe context injection.
- `frontend/src/components/DebateArena.jsx`: Added the Quantitative Validation panel with light-theme contrast fixes (`text-ink`, `text-slate-300`, `text-slate-400` on `bg-white`), while keeping the `56ddbfb` Market Matrix data-status bar, IST timestamp, and controlled Retry with 4s cooldown.
