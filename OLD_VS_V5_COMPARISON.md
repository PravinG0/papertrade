# Old Engine vs TradeLab V5 — Controlled Comparison Report

**Date:** 26 November 2026  
**Methodology:** Independent offline Champion (Old AI proposals) vs Challenger (V5 `quant_eligible=true` filtered proposals) simulation using `backend/research_backtest.py` with isolated simulated wallets (`initial_capital = ₹1,000,000`), `slippage_bps = 10`, `fixed_fee = ₹40`, `turnover_fee_bps = 5`.

> [!NOTE]
> Because licensed historical option contract OHLC data is not stored in the repository, this benchmark uses a **synthetic 20-candidate chronological option OHLC fixture** (10 aligned high-R:R setups + 10 conflicting/wide-spread/low-R:R setups) to verify V5's filtering mechanics and accounting. It does **not** represent live historical option profitability.

## Measured Comparison Results

| Metric | Old Engine (Champion) | V5 Engine (Challenger) | Delta |
| --- | --- | --- | --- |
| Total Opportunities | 20 | 20 | — |
| Executed Trades | 20 | 10 | -10 (filtered) |
| Rejected Opportunities | 0 | 10 | +10 |
| Win Rate | 50.0% | 80.0% | +30.0% |
| Net P&L (after fees/slippage) | +₹4,137.20 | +₹7,525.84 | +₹3,388.64 |
| Ending Capital | ₹1,004,137.20 | ₹1,007,525.84 | +₹3,388.64 |
| Profit Factor | 1.59 | 6.36 | +4.77 |
| Expectancy / Trade | +₹206.86 | +₹752.58 | +₹545.72 |
| Transaction Fees | ₹932.66 | ₹469.06 | -₹463.60 |
| Max Realized Equity Drawdown | ₹1,405.36 | ₹1,405.36 | ₹0.00 |
| Historical API Calls / Debate (cold / warm) | 1 / 0 | 5 / 0 | +4 cold, 0 warm |
| 5-Timeframe Candle Fetch Latency (cold / warm) | — | 4,052.7 ms / 2.1 ms | — |

## Key Conclusions
1. **Filter Mechanics:** V5 successfully isolates and rejects conflicting/low-R:R setups while preserving aligned high-R:R setups, cutting transaction fees nearly in half in the benchmark.
2. **Genuine Historical Option Limitation:** Real-world out-of-sample win rate and net P&L improvement can only be established once genuine point-in-time option contract OHLC bars (`provenance: "historical_contract_ohlc"`) are collected and evaluated via `research_backtest.py` and `research_ml.py`.
