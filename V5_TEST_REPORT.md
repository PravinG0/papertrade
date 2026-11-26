# TradeLab V5 — Comprehensive Test Report

**Date:** 26 November 2026  
**Scope:** Automated backend/frontend suites, live Angel One 5-interval SmartAPI checks, technical indicator reference checks, quantitative validation & clamping audit, AI agent & memory checks, and Old vs V5 research benchmark.

## 1. Test Execution Summary

| Suite / Check | Result | Details |
| --- | --- | --- |
| Python syntax (`py_compile`) | **PASSED** | All backend modules, agents, and test files compiled cleanly |
| Backend `pytest` (`tests/`) | **PASSED (with 1 skip)** | Full suite run on isolated temporary SQLite DBs; `test_ml_research_pipeline_on_synthetic_fixture` skipped (optional `scikit-learn` not installed in runtime environment) |
| Frontend JS (`node --test tests/*.test.js`) | **PASSED** | `28 passed, 0 failed` |
| Frontend Vite build (`npm run build`) | **PASSED** | `1,598` modules, `414.49 kB` main JS, `173.56 kB` charts JS |
| Live SmartAPI 5-Interval Check (`NIFTY`, `BANKNIFTY`) | **PASSED** | All 10 calls (`1m`, `5m`, `15m`, `1h`, `1d`) returned `HTTP 200`, `source=live`, zero `403` errors at `0.65s` min pacing |
| Live Market-Hours Option Spread & Auto-Fill | **PENDING** | Requires active NSE session (`09:15–15:30 IST`); market closed at audit time (`23:50 IST`) |
| Browser E2E Viewport Automation | **BLOCKED (local)** | Playwright/Chrome not installed locally; responsive CSS & production build verified |

## 2. Bugs Discovered & Fixed During Audit

1. **SmartAPI 5-Interval Rate-Limit Burst (`HTTP 403` on `BANKNIFTY`):**
   - *Cause:* `_candle_min_interval = 0.45s` allowed >2 req/sec across 5 consecutive timeframe requests, triggering SmartAPI `HTTP 403` on the 6th request.
   - *Fix:* Tuned `_candle_min_interval` to `0.65s` in `backend/angel_service.py`; verified all 10 `NIFTY` + `BANKNIFTY` interval calls pass with `HTTP 200`.
2. **Low-Contrast Light-Theme Text in Quantitative Validation Panel:**
   - *Cause:* `DebateArena.jsx` used `text-slate-600` on `bg-white`, which maps to light grey (`#94a3b8`) under `tailwind.config.js`'s inverted slate scale.
   - *Fix:* Updated to `text-ink` / `text-slate-300` / `text-slate-400` (`#0f172a` / `#334155` / `#475569`).
3. **SL/Target Clamping vs `QUANT_MIN_NET_RR = 1.5` Mathematical Conflict (Documented):**
   - *Finding:* `compute_clamped_sl_target(..., max_loss_inr=700, max_gain_inr=1000)` caps gross R:R at `1.428` for NIFTY 1-lot (`qty=65`) trades at ₹80–₹250 and BANKNIFTY (`qty=30`) at ₹150–₹250. After brokerage/statutory fees and 1-spread slippage, `net_rr` drops to `1.08–1.20 < 1.5`, making clamped trades fail `option_validation`. Left `700/1000` and `1.5` untouched per safety policy; requires operator decision if wider target / tighter SL clamp is desired.
