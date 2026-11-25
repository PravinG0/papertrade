# Wallet and Trade History update

- Header shows equity (`cash + used margin + unrealized P&L`), account P&L (`equity - initial capital`), available cash, margin used, and net trade P&L for the current wallet cycle.
- A historical difference between the stored wallet and trade ledger is shown explicitly rather than overwriting the wallet or fabricating a trade. The exact cause of existing discrepancies requires an audit of the deployed database.
- Future wallet resets store a per-portfolio realized-P&L baseline in the existing app_kv table; trade history is retained. All-time reporting fields retain their original meaning. Account state reads are serialized with order mutations for consistency (database latency may affect snapshot throughput).
- Trade History supports inclusive From/To dates, entry/exit selector, Today and Clear filters; full date/time in IST, filtered realized P&L, and improved text contrast. CSV export remains the full closed-trade export. Debate history is unchanged.
- Zero available balance no longer falls back to initial capital in order dialogs.

Verification: Vite build passed (1597 modules; existing bundle-size warning); Python compile passed; 8 offline Python tests and 3 Node timestamp tests passed. Database-backed regression suite blocked by missing aiosqlite. No live database, API, browser, or deployment validation performed. No existing balance or trade history was edited.
