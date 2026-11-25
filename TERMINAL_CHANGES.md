# Terminal navigation update

Based on papertrade(1).zip. Existing backend files and previous fixes are unchanged.

- Option Buy/Sell: existing option chain, chart, order entry, open positions, pending orders and quick trade. Closed trades move to the History ledger. Chart remains mounted across tabs.
- Chat: existing Bull/Bear/Judge debate and scheduler controls. The old separate AI Debate navigation is removed. Archived debates open in Chat read-only; scheduler status and latest session refresh continue in the background.
- History: trade ledger (open and closed positions), entry date/index/status/search filters, daily report, authenticated CSV export of closed trades; debate history (up to the API maximum of 100 sessions) with existing outcome badges. Direct manual-versus-AI trade provenance is not consistently stored in the original ledger, so no inferred labels or source filter were added.
- Desktop and mobile navigation, keyboard arrow navigation for terminal tabs, and existing analysis/journal/strategy pages retained.

## Verification
- Vite production build: passed (1,596 modules); existing bundle size warning remains.
- Backend Python syntax compilation: passed.
- Browser smoke test attempted; Chromium navigation blocked by environment administrator policy. No browser runtime or live broker/Gemini/database verification claimed.
- Source-only archive excludes .env, private databases, debate sessions, Git metadata, node_modules, generated dist and Python caches. Keep your local .env and database; back them up and do not overwrite them.
