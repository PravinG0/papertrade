# Database Migration Report (`QA-19`)

**Date:** 26 November 2026  
**Migration Module:** [`backend/migrations.py`](file:///home/pravin/Documents/Trading/papertrade/backend/migrations.py)  
**Integration Point:** [`backend/database.py`](file:///home/pravin/Documents/Trading/papertrade/backend/database.py) (`init_db`)

## 1. Non-Destructive Design & Safeguards

All schema management in [`backend/migrations.py`](file:///home/pravin/Documents/Trading/papertrade/backend/migrations.py) is **strictly additive and non-destructive**:

- Never runs `DROP TABLE`, `DROP COLUMN`, `TRUNCATE`, `DELETE`, or destructive `ALTER COLUMN TYPE`.
- `init_db()` skips DDL completely when `SKIP_DB_INIT=true` is set in environment variables.
- Supports read-only inspection (`python migrations.py --dry-run`) returning dialect, existing tables, row counts, pending additive columns/indexes, and applied migration history without modifying any data.
- Supports PostgreSQL (`asyncpg` / Supabase Transaction Pooler port `6543`) and SQLite (`aiosqlite`) cleanly via SQLAlchemy `inspect()`.

## 2. Versioned Additive Migrations

| Version | Purpose | DDL Operations |
|---|---|---|
| `2026_11_26_001_core_tables` | Ensure baseline ORM tables exist additively (`users`, `paper_trades`, `portfolios`, `debate_sessions`, `debate_records`, `pending_paper_orders`, `app_kv`, `daily_reports`, `ai_trade_evidence`) | `Base.metadata.create_all` (`CREATE TABLE IF NOT EXISTS`) |
| `2026_11_26_002_additive_columns_and_indexes` | Ensure nullable/default columns on `users` (`google_id`, `avatar_url`) and `daily_reports` (`date`, `report_date`, `summary_metrics`, `summary_json`, `raw_analysis`, `ai_analysis_json`, `report_markdown`, `markdown_report`, `report_html`) plus query indexes (`ix_users_google_id`, `ix_paper_trades_user_status`, `ix_paper_trades_user_closed`, `ix_daily_reports_user_date`) | Conditional `ALTER TABLE ... ADD COLUMN` & `CREATE [UNIQUE] INDEX IF NOT EXISTS` |
| Tracking table | Record applied migration versions, checksums, descriptions & IST timestamps | `CREATE TABLE IF NOT EXISTS schema_migrations` |

## 3. Isolated Verification Results

- Verified against a legacy pre-upgrade SQLite database fixture in [`test_qa19_non_destructive_migrations_preserve_legacy_data`](file:///home/pravin/Documents/Trading/papertrade/backend/tests/test_qa_hardening.py):
  - Pre-populated `users`, `portfolios`, `paper_trades`, and `daily_reports` without `google_id`, `pending_paper_orders`, `ai_trade_evidence`, or indexes.
  - Verified `--dry-run` / `inspect_schema()` detected exact missing columns/indexes and counted legacy rows without mutating data.
  - Executed `apply_additive_migrations()` **twice** (idempotency check) and verified 0 remaining pending migrations and 100% row retention.
- Verified read-only against local `backend/papertrade.db` (`--dry-run` completed cleanly without writes).
- **External Dependency Note:** Production Supabase `DATABASE_URL` resides in Render environment variables rather than local `.env`. Before applying any future manual migrations or index creation on Supabase, take a Supabase snapshot backup and run `DATABASE_URL=... python backend/migrations.py --dry-run` in a private shell.

## 4. Rollback Procedure

1. Code rollback: `git checkout backup-pre-qa-repaired-52a8419` (or `git revert <commit>`).
2. Because all added columns/indexes/tables (`schema_migrations`, `ix_paper_trades_user_*`) are additive and backward-compatible, previous application code continues running cleanly without requiring destructive DDL rollback.
3. If an additive index needs removal on PostgreSQL: `DROP INDEX IF EXISTS ix_paper_trades_user_status;` etc., never dropping core financial tables.
