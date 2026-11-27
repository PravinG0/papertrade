# TradeLab Cloud V6 — Final QA Report

**Date:** 27 November 2026  
**Commit Base:** `308e7aa` (Backup tag: `backup-pre-v6-308e7aa`)

## 1. Automated Test & Build Results
- **Python Compilation (`py_compile`):** **PASSED** across all backend modules, agents, and tests.
- **Full Backend `pytest` (`python3 -m pytest -q tests`):** **349 passed, 1 skipped, 0 failed** (`100.89s` on isolated temporary SQLite DBs; `test_ml_research_pipeline_on_synthetic_fixture` skipped because optional `scikit-learn` is not installed in runtime environment).
  - Includes `test_cloud_v6_offline.py` (`47` V6 WebSocket/MCX/stream cases), `test_v6_complete.py` (Shadow Trading, Champion vs Challenger, Dynamic Risk Limits, MCX charges & isolated MCX paper trading), `test_quant_v5.py`, `test_v5_debate_integration.py`, `test_candle_resilience.py`, `test_adaptive_integration.py`, and all existing accounting/settlement/concurrency tests.
- **Frontend Unit Tests (`node --test tests/*.test.js`):** **28 passed, 0 failed**.
- **Frontend Production Build (`npm run build`):** **PASSED** (`1,599` modules, main `420.32 kB`, charts `173.56 kB`, `McxResearch` `12.77 kB`).

## 2. Live Integration Results (27 Nov 2026, 21:51 IST)
- **Angel One WebSocket 2.0 (`wss://smartapisocket.angelone.in/smart-stream`):** **PASSED** (`connected=True`, `error=None`, `reconnects=0`; live binary ticks decoded for `MCX` `CRUDEOIL18DEC26FUT` `576264` and `CRUDEOIL16DEC267800PE` `586071` matching REST `÷100` price scaling).
- **MCX Crude Oil Contract & Candle Verification:** **PASSED** (`1,100` CRUDEOIL contracts parsed, `775` live 5m candles, `09:00–23:55 IST` winter session bounds).
- **Live NSE Session Testing:** **PENDING** next NSE market open (`09:15–15:30 IST`); keep `V6_AUTO_EXECUTION_ENABLED=false` until verified live.
