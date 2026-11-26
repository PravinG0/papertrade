# TradeLab V5 Hybrid — Final QA Report

**Date:** 26 November 2026

## Test & Verification Summary

1. **Python Compilation:** `python3 -m py_compile backend/*.py backend/agents/*.py backend/tests/*.py` — **PASS**.
2. **Backend Automated Suite (`python3 -m pytest -v tests`):** **303 passed, 1 skipped** (isolated temp SQLite DBs; `test_ml_research_pipeline_on_synthetic_fixture` skipped due to optional `scikit-learn` not installed in runtime environment).
   - Covers `test_quant_v5.py`, `test_v5_debate_integration.py`, `test_candle_resilience.py`, `test_adaptive_integration.py`, `test_adaptive_memory.py`, `test_audit_integration.py`, `test_audit_offline.py`, `test_engine.py`, `test_offline_core.py`, `test_qa_hardening.py`, `test_qa_repairs_offline.py`, `test_regression_fixes.py`, `test_wallet_accounting.py`, `test_wallet_settlement.py`.
3. **Frontend Unit Tests (`node --test tests/*.test.js`):** **28 passed, 0 failed**.
4. **Frontend Production Build (`npm run build`):** **PASS** (1,598 modules, `414.49 kB` main bundle).
5. **Live Angel One SmartAPI 5-Interval Check (`NIFTY` & `BANKNIFTY`):**
   - Initially tripped `HTTP 403` on the 6th back-to-back historical call (`BANKNIFTY 1m`) at `0.45s` pacing.
   - Tuned `_candle_min_interval` to `0.65s` in `angel_service.py`; re-test across all 10 calls (`1m`, `5m`, `15m`, `1h`, `1d` for `NIFTY` and `BANKNIFTY`) returned `HTTP 200`, `source=live`, `err=None`.
   - Observed that `quant_engine.validated_bars()` strictly blocks when an exchange holiday (`2026-11-24`) is absent from `EXCHANGE_HOLIDAYS` or when SmartAPI has a feed gap (`15:15–15:19 IST` on `2026-11-26`), confirming fail-closed safety.

## Pending Live-Market Checks
- Active market-session (`09:15–15:30 IST`) validation of live bid/ask option spreads, bar-boundary transitions, and automatic execution remains pending until market open. Keep `auto_execute` disabled until verified live.
