# Data Preservation Verification Report

**Date:** 26 November 2026  
**Scope:** Local codebase merge, schema migrations (`migrations.py`), automated regression suites (`conftest.py` isolated temp DB), and read-only inspection of local `backend/papertrade.db`.

## 1. Verification Against Data Preservation Rules

- **Production Supabase Protection:** Production `DATABASE_URL` is hosted on Render and not exposed in local `.env` or Git. No destructive SQL (`DROP`, `TRUNCATE`, `DELETE`), wallet balance modification, or automated test run touched the live Supabase PostgreSQL instance.
- **Test Isolation Confirmed:** [`backend/tests/conftest.py`](file:///home/pravin/Documents/Trading/papertrade/backend/tests/conftest.py) overrides `DATABASE_URL` to an isolated temporary SQLite file and clears external API secrets during automated `pytest` execution.
- **Local Development Database (`backend/papertrade.db`) Read-Only Baseline Check:**
  - Read-only count verified before and after all code changes & tests (`sqlite3` read-only URI `mode=ro`):
    - `users`: 2 rows
    - `portfolios`: 3 rows
    - `paper_trades`: 6 rows
    - `daily_reports`: 1 row
    - `debate_sessions`: 0 rows
    - `debate_records`: 0 rows
    - `app_kv`: 0 rows
  - All local rows, primary keys, timestamps, and wallet balances remained 100% unchanged after running all 237 pytest tests.
- **Legacy Schema Upgrade Data Preservation Test:**
  - Verified in [`test_qa19_non_destructive_migrations_preserve_legacy_data`](file:///home/pravin/Documents/Trading/papertrade/backend/tests/test_qa_hardening.py): existing `users` (1 row), `portfolios` (1 row, `₹987,654.32`), and `paper_trades` (`POS-OLD-1`) retained original IDs, values, and timestamps after running idempotent additive migrations twice.
- **Adaptive Learning & Historical Reports:**
  - `DailyReportModel` prior revisions are archived in `app_kv` (`report-rev:...`) when a report is refreshed rather than discarded.
  - `REPLAY_STOPPED` rows are filtered dynamically in `adaptive_store.py` / `adaptive_memory.py` / `report_agent.py` **without deleting** legacy records from `paper_trades`.
  - Git repository excludes `.env`, `*.db*`, private backups, and session logs via [`.gitignore`](file:///home/pravin/Documents/Trading/papertrade/.gitignore).

## 2. Production Supabase Snapshot Comparison Instruction

Run the following **read-only** command from a private operator shell with production `DATABASE_URL` set (both before and after deployment) to confirm identical historical counts on Supabase:

```bash
PYTHONPATH=backend DATABASE_URL="postgresql://..." python3 backend/migrations.py --dry-run
```
