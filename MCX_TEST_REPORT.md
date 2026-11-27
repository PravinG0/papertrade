# TradeLab Cloud V6 — MCX Crude Oil Test Report

**Date:** 27 November 2026 (21:51 IST, live MCX session)

## 1. Live MCX Contract & Market Data Verification
- **Session Bounds (`configured_mcx_bounds`):** `09:00 – 23:55 IST` (winter schedule `2026-11-02` to `2027-03-12`).
- **Scrip Master Contracts (`scrip_master.mcx_contracts()`):** `1,100` `CRUDEOIL` contracts parsed (`10` futures, `392` options in `2026-12-16` expiry).
- **Nearest Future:** `CRUDEOIL18DEC26FUT` (`token=576264`, `expiry=2026-12-18`, `lot_size=100`, `tick_size=1.0`).
- **Historical 5m Candles:** `source=live`, `775` candles, latest `close=7785.0`, `volume=72`.
- **REST FULL Quote:** `ltp=7785.0`, `bid=7783.0`, `ask=7785.0`, `opnInterest=855800`, `tradeVolume=28746`.
- **Sample Option (`CRUDEOIL16DEC267800PE`, `token=586071`):** `lot_size=100`, `tick_size=0.1`, live WS `ltp=347.5`, `bid=346.7`, `ask=347.5`.

## 2. Isolated MCX Paper Trading & AI Analysis (`test_v6_complete.py`)
- Verified `place_mcx_paper_order` (`BUY CE` / `BUY PE`), `lot_size=100` multiplier, MCX session & expiry validation, `calculate_mcx_charges` (brokerage, CTT, MCX txn, SEBI, stamp, GST), `settle_mcx_positions`, and `mcx_technical_summary`.
- Index `paper_engine.place_order` continues to reject `CRUDEOIL` so commodity trades stay 100% isolated in `mcx-paper:<user_id>`.
