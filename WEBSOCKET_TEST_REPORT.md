# TradeLab Cloud V6 — Live WebSocket Test Report

**Date:** 27 November 2026 (21:51 IST, live MCX session)

## 1. Live Angel One WebSocket 2.0 Verification
- **Endpoint:** `wss://smartapisocket.angelone.in/smart-stream`
- **Auth & Feed Token:** `angel_service.authenticate()` succeeded; `jwtToken` & `feedToken` generated.
- **Connection & Subscription (`MCX` `576264` `CRUDEOIL18DEC26FUT`, `MCX` `586071` `CRUDEOIL16DEC267800PE`, `NSE` `99926000`):**
  - `WS connected = True`, `error = None`, `reconnects = 0`.
  - **MCX Futures Binary Packet (`576264`):** `ltp = 7783.0` (`÷100` paise scaling matched REST `7785.0`), `open = 7951.0`, `high = 8060.0`, `low = 7755.0`, `close = 7872.0`, `tradeVolume = 28748`, `opnInterest = 855800`, `bid = 7782.0`, `ask = 7784.0`, `exchFeedTime = 2026-11-27T16:21:55+00:00` (`21:51:55 IST`).
  - **MCX Option Binary Packet (`586071`):** `ltp = 347.5`, `bid = 346.7`, `ask = 347.5` (`0.23%` spread), `tradeVolume = 49384`, `opnInterest = 338500`, `exchFeedTime = 2026-11-27T16:21:54+00:00`.
  - **Note on Depth Quantity Units:** WebSocket depth `quantity` for MCX is reported in lots (`1` lot = `100` bbl), whereas REST FULL depth `quantity` is reported in units (`100` per lot). Price scaling (`÷ 100`) is identical.
  - **NSE `99926000`:** `None` at `21:51 IST` because NSE cash/index session was closed (`15:30 IST`), confirming no fabricated after-hours ticks.

## 2. Offline Unit Coverage (`test_cloud_v6_offline.py` & `test_candle_resilience.py`)
- Binary mode 2/3 packet decoding, crossed depth rejection, invalid token/price/timestamp rejection, duplicate/out-of-order sequence handling, stale exchange timestamp rejection (`> 10s`), capped dynamic subscription prioritization, REST fallback, and token renewal (`401`/`AG8001`/`AG8002`/`AG8003`).
