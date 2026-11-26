# TradeLab V5 — Hybrid Quantitative AI Trading Engine (development candidate)

Base: the exact user-supplied `papertrade(4).zip`, including the historical candle resilience changes from Antigravity. This is a source merge candidate, not a verified production release. No production service, account, database, wallet or Git repository was accessed or changed. Do not deploy until the blocking integration checks below pass.

## Implemented application changes

1. `backend/quant_engine.py`: independent deterministic evaluation of completed 1m/5m/15m/1h/daily candles using session-aligned expected start timestamps, 50 consecutive valid candles minimum, up to 200 for warm-up, gap/duplicate/invalid-OHLC detection, EMA20/50 separation normalized by ATR, regime labels, directional agreement, session reference and Supertrend confirmation. Current session reference requires the entire completed session tail; zero-volume index data is identified as a typical-price proxy rather than VWAP. Calendar is the existing operator-configured calendar, not an official live holiday feed. Assumes broker candles are start-labelled and intraday bars align to session open; verify 1h/shortened session/daily timestamps with live broker responses. Strict checks can deliberately block at a bar boundary when a new completed bar has not arrived. 
2. `backend/angel_service.py`: require broker-backed cache provenance, recheck cache freshness, stop putting generated fallback candles in the real cache, reject impossible OHLC instead of repairing it, and expose actual exchange quote timestamps on spot quotes. The older general chart freshness classifier is still permissive; the new strict completed-bar validation is at the debate/automatic-fill boundary. Historical API retry, token renewal, singleflight and cooldown code retained. Rate limiting remains process-local.
3. `backend/debate_engine.py`: build five-timeframe snapshots (`5m/5d`, `1d/1y`, `1h/30d`, `15m/15d`, `1m/5d`), revalidate after collection, refresh spot, require a timestamp for eligibility, reject missing timeframes, preserve original Judge proposal and timestamp before deterministic filtering, downgrade rejected proposals to `NO_TRADE`. No automatic trade on partial Gemini fallback. One-lot exact-expiry preview checks a two-sided market quote and estimated net reward/risk using existing charge function, actual lot size, and assumed one-spread exit slippage. Option Greeks are separately labelled Black–Scholes midpoint estimates, not broker-supplied or a probability. The option preview does not prove market depth or execution availability. Auto execution re-fetches data, pins expiry, disallows overrides, enforces snapshot age, estimates fill at ask rather than LTP, rechecks actual total quantity and fees, stores execution validation. `paper_engine.py` checks quote/spot exchange timestamps and completed timeframe freshness under the wallet lock for V5 evidence before debiting. Existing entry, trend, cooldown, cap, duplicate, and wallet checks remain. Manual order flow and manual overrides remain distinct from automatic execution; historical archived manual execution behavior is not newly certified.
4. `backend/debate_schemas.py`: optional fields for timeframes, regime, active session, exchange timestamp, option expiry, original proposal, validation results. Old debate payloads continue to deserialize with defaults; old debates cannot automatically execute without new validation. New metadata uses existing `debate_records.payload` and `ai_trade_evidence.snapshot` JSON fields. No V5 database table/column migration required. Existing production initialization/migrations still need normal backup/test verification.
5. Bull/Bear/Judge prompts receive actual timeframe direction and data availability. Old prompts and 5/30-day memory retained. `adaptive_store.py` adds up to 90 **observed prior trading dates** for provenance-backed V5 automatic fills (bounded 2,000-record query). Historical records without V5 provenance remain in old memory; not silently relabelled as verified. It reports observed win rates by confidence band, counts and Wilson intervals, marking <30 samples insufficient. This is descriptive calibration evidence, not a deployed probability model. Report explanations remain hypotheses. Existing legacy report/replay provenance limitations remain.
6. `frontend/src/components/DebateArena.jsx`: responsive current-debate validation panel, original AI proposal, five timeframe labels, regime, spot freshness, blocking reasons, option preview spread/net R:R/model delta, execution recheck, explicit disclaimer. Existing Terminal, History, wallet and mobile styles retained; browser layout needs verification. No separate advanced performance dashboard has been built.

## Optional offline research tools (NOT used by production auto execution)

- `backend/research_backtest.py`: reads an operator-supplied JSON of exact historical option OHLC and point-in-time candidate proposals. Evaluates hypothetical rejected as well as accepted BUY candidates. Entry is on the next strictly subsequent bar; stops take precedence when both stop/target occur in same bar; gap-through-stop uses open; horizon limited to entry date and expiry. Models explicit approximate fees/slippage, reports unresolved missing data, net P&L, win rate, profit factor, expectancy, fees, realized-equity max drawdown. Champion = original AI BUY proposals; challenger = recorded `quant_eligible=true`. Both have separate offline simulated balances, one non-overlapping position each. Does not start competing live schedulers, write any production records, automatically promote strategies or reconstruct historical Gemini calls. Not the existing app's historical replay module (that remains playback-only until isolated). Input provenance is operator-supplied, not independently authenticated. Real option data and correctly recorded point-in-time proposals are required. No real backtest results were produced.
- `backend/research_ml.py`: optional research-only logistic baseline with separate chronological training, calibration and unseen test partitions; purges labels that extend into next partition; minimum 300 completed, feature-complete outcomes over at least 20 dates and sufficient two-class samples in each partition. Uses fixed input features, not exits or P&L as predictors; calibrated metrics and constant baseline. Optional `--model xgboost` / `lightgbm` require separate install. No model files are loaded or deployed; no production probability gating; no automatic training on real data. One chronological holdout is not full walk-forward testing, and the ML sample count is a minimum gate, not proof of reliability. Test on multiple market regimes and prospective paper trading. Synthetic test validates pipeline execution only.

### Research input schema

Create a private JSON dataset from genuine licensed historical option data and point-in-time captured proposals. Do not use generated option premiums or today's indicators to reconstruct past decisions. Keep the file outside Git. Structure:

```json
{
  "provenance": "historical_contract_ohlc",
  "initial_capital": 1000000,
  "assumptions": {"interval_minutes": 5, "slippage_bps": 10, "fixed_fee": 40, "turnover_fee_bps": 5},
  "candidates": [
    {
      "id": "recorded-proposal-id", "decision_at": "2026-11-25T10:01:00+05:30",
      "available_at": "2026-11-25T10:01:05+05:30", "features_at": "2026-11-25T10:01:00+05:30",
      "expiry_at": "2026-11-26T15:30:00+05:30", "contract": "EXACT-OPTION-SYMBOL",
      "verdict": "BUY CE", "quantity": 65, "reference_entry": 100, "stop": 95, "target": 115,
      "max_bars": 12, "quant_eligible": false,
      "features": {"confidence": 9, "rsi": 58, "atr_pct": 0.2, "spread_pct": 0.4, "net_rr": 1.7, "ema_separation_atr": 1.2}
    }
  ],
  "bars_by_contract": {"EXACT-OPTION-SYMBOL": [
    {"timestamp": "2026-11-25T10:05:00+05:30", "open": 100, "high": 110, "low": 98, "close": 105}
  ]}
}
```

Illustrative schema only; values above are not trading data. The operator must map exact expiry/contract, timestamps and features from recorded debates, and provide sufficient later bars for the full holding horizon. Feature timestamp must reflect latest information used at the decision (including option preview), and `quant_eligible` must be recorded then, not reconstructed with future outcomes. Some rejected proposals may lack quote/feature metadata; keep them unresolved or exclude them from ML rather than fabricate values. No automated production export or historical options downloader yet. Verify fee schedules for the historical period; defaults are research assumptions, not statutory rate assertions. 

```bash
cd backend
python research_backtest.py /private/dataset.json --output /private/comparison.json
python -m pip install -r requirements-research.txt
python research_ml.py /private/comparison.json --model logistic --output /private/ml_metrics.json
```

## Configuration

New default values (see `.env.example`, preserve existing actual `.env`):

- `MEMORY_EXTENDED_DAYS=90`
- `QUANT_MIN_CONFIDENCE=8` (conviction 1–10, not an 80% success probability)
- `QUANT_MIN_NET_RR=1.5` (estimated fee/spread-adjusted ratio)
- `QUANT_MAX_SPREAD_PCT=2.0`
- `QUANT_MAX_VERDICT_AGE_SECONDS=180` (age since data snapshot, not end of AI response)

The rule-based filter is deliberately conservative: daily direction must not oppose the proposed trade; 1m/5m/15m/1h must align, session reference and Supertrend must agree, required Gemini analyses must succeed. Quote/spot time age max 30s. Five daily automatic trades remains a cap, not a target. The existing ₹700 gross loss / ₹1000 gross target clamps can make the net R:R threshold difficult to meet. It is valid to make no trades for an entire session. Do not loosen constraints simply to generate more orders; evaluate them on held-out data. Fees/gaps/slippage mean realized risk can exceed a planned stop distance. 

## Verification performed in this environment

- Python dependency-light suite: **233 passed**, 0 failed (182 pre-existing offline cases and 51 new parametrized cases; includes one synthetic logistic research pipeline exercise). Commands: `cd backend && PYTHONPATH=. python -m pytest -q tests/test_quant_v5.py tests/test_adaptive_memory.py tests/test_audit_offline.py tests/test_offline_core.py tests/test_qa_repairs_offline.py tests/test_wallet_accounting.py`.
- Python syntax: compileall passed.
- Frontend JS: **28 passed**, 0 failed (`node --test tests/*.test.js`).
- Frontend production build: passed, 1,598 modules, main JS 414.44 kB, chart JS 173.56 kB, no oversized chunk warning. Built from dependency files included in user ZIP; permissions restored on esbuild in the disposable workspace. No browser test performed.
- Full backend collection: blocked by missing dependencies (`aiosqlite`, etc.; 10 test module collection errors, including new mocked integration test). `pip install -r backend/requirements-dev.txt` failed because pyotp package could not be obtained. Do not treat prior Antigravity's 248-pass baseline as proof of this revision. New integration test `test_v5_debate_integration.py` written but not executed.
- Live SmartAPI/Gemini, PostgreSQL concurrency, production data audit, broker candle alignment, and mobile/browser verification: not executed. No credentials used.

## Required Antigravity checks before any production push

1. Merge into existing production main, do not replace it; preserve uncommitted changes and current credentials. Git checkpoint and verified Supabase backup, no original financial edits or destructive migration. No V5 schema change needed. Keep one backend worker/service until shared rate limiting/leader lease is verified.
2. Install required dependencies and run **all** backend tests (`python -m pytest -q`) including mocked candidate rejection/persistence. Verify actual async paths, prompt injection, exact expiry, fees, old payload loading, legacy wallet behavior, no real orders, market-session filtering, and stale quote/fill rejection. Add integration tests for successful V5 quote preview/auto-fill, scheduler `NO_TRADE`, one lot vs multi-lot, missing 1h bars, crossing a bar boundary, and restart/multiple workers. Check current code/API contracts instead of relying solely on docs.
3. Read-only live validation during actual market session: 5 intervals for both NIFTY and BANKNIFTY; confirm candle timestamps (start-labelled vs end-labelled, 1h alignment and final shortened bars, daily timestamp normalization), expected completed bars, calendar/holiday handling, API limits and request latency, exact exchange quote timestamps. Test warm cache and expired cache. Configure official exchange closure/special dates. A provider publishing slowly can cause strict NO TRADE / 503; diagnose rather than bypass. Evaluate rate and latency with extra timeframes and repeated execution snapshots; optimize with shared broker-backed incremental data only if required.
4. Verify bid/ask/quote timestamp, liquidity depth/volume and Greek estimates; actual option-chain OI coverage/freshness is still a limitation (broker may provide incomplete chain). VWAP on cash index may be unavailable; proxy remains explicit. FII/DII/global breadth, official exchange calendar auto-sync, short margin, distributed scheduler, and prior replay provenance remain unresolved as in earlier handoff. No need to purchase extra APIs without approval.
5. Use isolated DB to run PostgreSQL concurrency and data-preservation tests; verify existing histories remain unchanged. Test mobile at common viewports, actual Chart/Chat/History flow and error status. Confirm quantitative panel shows reasons for blocked trades.
6. Collect real point-in-time proposals and historical option premiums. Build validated private dataset/export, resolve rejected proposals offline, and verify research metrics. Compare strategies using multiple chronological walk-forward windows and forward paper trials; do not promote ML or live champion/challenger without independent evidence and user approval. Research needs live shadow scheduler, durable research records, export/data ingestion, full dashboard, model governance, and automated evaluation as future work.
7. Update AI_HANDOFF.md and report actual test results. Only push verified changes to `origin/main` if essential tests pass; no force push, no automatic historical wallet correction, no production migrations without approval. Production and original ZIP unchanged by this development task.
