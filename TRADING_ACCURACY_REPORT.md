# TradeLab V5 — Trading Accuracy, Risk & ML Calibration Report

**Date:** 26 November 2026

## 1. Technical Indicator Verification
- **Verified against independent reference implementations (`test_v5_audit_comprehensive.py`):**
  - `EMA 20` & `EMA 50`, `RSI (14)` (Wilder smoothing), `ATR (14)`, `VWAP`, `CPR`, and `Supertrend(10,3)` matched reference calculations within `±0.02`.
  - Black-Scholes midpoint Greeks (`estimate_option_greeks`) and implied volatility (`_implied_volatility`) produced valid ATM call deltas (`0.3 < delta < 0.7`) and IV (`0.05 < iv < 1.0`).
  - `market_regime()` accurately classified `BULL_TREND`, `BEAR_TREND`, and `RANGE_OR_TRANSITION`.

## 2. Quantitative Guardrail & SL/Target Clamping Audit
- **Confirmed Enforced:**
  - Missing/partial/stale timeframe data (`< 50` consecutive completed bars) blocks trades (`NO_TRADE`).
  - Conflicting `1m`/`5m`/`15m`/`1h`/`1d` signals, stale spot/option timestamps (`> 30s`), wide spreads (`> 2.0%`), `net_rr < 1.5`, expired verdicts (`> 180s`), and partial Gemini fallbacks are all rejected before execution.
- **Important Mathematical Conflict Identified:**
  - Existing `compute_clamped_sl_target(..., max_loss_inr=700, max_gain_inr=1000)` clamps NIFTY 1-lot (`qty=65`) trades at ₹80–₹250 to `gross_risk ≈ ₹698.8` and `gross_reward ≈ ₹997.7` (`1.428` gross R:R).
  - After deducting statutory charges (~₹55–₹70) and 1-spread slippage, **`net_rr` is `1.08–1.15`** (and `1.18–1.20` for `BANKNIFTY` `qty=30` at ₹150–₹250) — which is **below `QUANT_MIN_NET_RR = 1.5`**.
  - Only low-premium contracts where `20%` SL is `< ₹700` (e.g., `BANKNIFTY` ₹80 → `net_rr = 1.63`) pass both constraints simultaneously. Neither safety threshold was weakened; operator approval is required if the ₹700/₹1000 clamp should be adjusted (e.g., `max_loss_inr=500` or `max_gain_inr=1250`).

## 3. Machine Learning & Confidence Calibration Status
- **No Unverified Model Deployed:** `research_ml.py` is strictly offline-only; `scikit-learn` is not installed in the production runtime (`test_ml_research_pipeline_on_synthetic_fixture` skipped).
- **Confidence vs Probability:** Gemini confidence (`1–10`) is treated strictly as an ordinal conviction score, not a calibrated win probability. `calibration_summary()` marks bands with `< 30` verified V5 samples as `sufficient: False` with `observed_win_rate: None`.
- **Sufficient Training Data:** Insufficient genuine V5-provenance outcomes currently exist in production; progressive collection of V5-provenance debates (`quant_version="quant-v1"`) is active.
