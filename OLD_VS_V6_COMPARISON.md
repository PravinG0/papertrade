# TradeLab Cloud V6 — Old vs V6 Comparison

**Date:** 27 November 2026

| Capability / Metric | Previous Production (`308e7aa`) | TradeLab Cloud V6 |
| --- | --- | --- |
| Live Quote Transport | REST polling only (`~250–600ms`) | Angel One WebSocket 2.0 streaming (`BrokerStream`) + REST fallback |
| Live MCX Crude Oil | Not supported | `1,100` CRUDEOIL contracts, live WS + REST, seasonal session (`09:00–23:55 IST`), isolated MCX paper wallet & AI analysis |
| Multi-Timeframe Quantitative Gate | Single `5m` snapshot | `1m`, `5m`, `15m`, `1h`, `1d` completed bars (50+ min) + `41e2e67` prior-day gap tolerance + bid/ask & net R:R validation |
| Shadow Trading & Champion/Challenger | Offline script only | Live per-user Shadow Engine tracking accepted & rejected proposals in isolated Champion/Challenger wallets |
| Daily Risk Limits | Fixed `AUTO_MAX_DAILY_TRADES=5` | Configurable UI/API risk limits (`max_daily_trades`, `no_count_limit`, `max_daily_loss_inr`, `max_concurrent_positions`, loss-streak cooldown) |
| Header Feed Status | Basic live/closed pill | Explicit `LIVE · WS (<age>s)`, `LIVE · REST`, `STALE`, `DISCONNECTED · UNAVAILABLE`, `MARKET CLOSED`, `SIMULATED` |
| Historical Candle Resilience | `1.2s` pacing, `60s` 5m TTL, `403` retry, `401`/`AG8001` renewal | Preserved in full |

*Note: Real-world out-of-sample P&L superiority of V6 over Old cannot be claimed until sufficient live Shadow / Challenger trades accumulate with genuine option prices.*
