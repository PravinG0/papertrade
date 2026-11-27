# TradeLab Cloud V6.1 — Data Preservation Report

**Date:** 27 November 2026

## Production Data Safety Verification
1. **Zero Destructive SQL or Migrations:** Zero `DROP`, `TRUNCATE`, `DELETE`, or schema migrations were added or run.
2. **Existing `app_kv` Keys Retained:** `mcx-paper:<uid>` is preserved; V6.1 adds separate `mcx-champion:<uid>`, `mcx-challenger:<uid>`, `ai_config`, and `debates` keys using transactional advisory locks (`mcx_storage.py`).
3. **Existing `pravin_g` (`user_id=1`, `portfolio_id=10`) Account:** Reconciled cash `₹9,91,609.77`, `90` closed `paper_trades`, all AI debates, daily reports, and adaptive learning memory remain 100% intact.
4. **Isolated Test Execution:** All `pytest` runs (`conftest.py`) and live `22:52 IST` MCX Gemini debate tests used isolated temporary SQLite databases.
