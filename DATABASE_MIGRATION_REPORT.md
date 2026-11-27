# TradeLab Cloud V6 — Database Migration & Data Preservation Report

**Date:** 27 November 2026

## Schema & Migration Status
- **Zero Production Schema Migrations Required:** All new V6 features (Shadow Trading ledger, Champion vs Challenger wallets, Dynamic Risk settings, and isolated MCX Paper Trading ledger) use the existing `app_kv` table (`AppKVModel`) keyed per `user_id` (`shadow-ledger:<uid>`, `risk-config:<uid>`, `mcx-paper:<uid>`), and V5 metadata uses existing `debate_records.payload` and `ai_trade_evidence.snapshot` JSON columns.
- **No Destructive Operations:** Zero `DROP`, `TRUNCATE`, `DELETE`, or schema-breaking alterations were introduced or executed.
- **Existing `pravin_g` (`user_id=1`, `portfolio_id=10`) Data Preserved:**
  - Reconciled `cash_balance = ₹9,91,609.77` (`wallet-repair:ff25b0058a164aa1ad9cd06f97bd06f2`), `90` closed `paper_trades`, all AI debates, daily reports, and adaptive learning memory remain 100% intact.
