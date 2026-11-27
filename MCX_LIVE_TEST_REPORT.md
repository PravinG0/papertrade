# TradeLab Cloud V6.1 — Live MCX Test Report

**Date:** 27 November 2026 (`22:50 – 22:53 IST`, live MCX evening session after NSE close)

## 1. Live MCX Contract & Option-to-Future Mapping Verification
- **Scrip Master (`scrip_master.mcx_contracts()`):** `1,100` active `CRUDEOIL` contracts (`lot_size=100`, `tick_size=1.0` futures / `0.1` options).
- **Verified Futures & Option Expiries:**
  - `2026-12-16` options → `CRUDEOIL18DEC26FUT` (`2026-12-18`)
  - `2027-01-15` options → `CRUDEOIL19JAN27FUT` (`2027-01-19`)
  - `2027-02-17` options → `CRUDEOIL19FEB27FUT` (`2027-02-19`)

## 2. Live 5-Timeframe MCX Historical Candles (`CRUDEOIL18DEC26FUT`)
- `1m` (`5d`): `source=live`, `3912` raw → `200` valid completed bars
- `5m` (`5d`): `source=live`, `786` raw → `200` valid completed bars
- `15m` (`15d`): `source=live`, `684` raw → `200` valid completed bars
- `1h` (`30d`): `source=live`, `330` raw → `50` valid completed bars
- `1d` (`1y`): `source=live`, `259` raw → **`83` valid completed bars** with `MCX_HISTORICAL_SESSIONS=2026-08-01/2026-11-01/09:00/23:30`

## 3. Live MCX Gemini 3-Agent Debate (`mcx_ai.run` in isolated temp DB)
- `gemini-3.8-flash` hit `503`/`429`; `mcx_ai.gemini_json` automatically failed over to `gemini-3.5-flash-lite` (`200 OK`) for all 3 agents (**Bull** `conf=3`, **Bear** `conf=8`, **Judge** `conf=8`, `NO_TRADE` under `RANGE_OR_TRANSITION`).
- Verified zero NIFTY/India VIX contamination and fail-closed `NO_TRADE` filtering.
