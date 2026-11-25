"""Non-destructive, versioned database migrations for SQLite and Supabase PostgreSQL.

Strict safety guarantees:
- Additive only (CREATE TABLE IF NOT EXISTS, ADD COLUMN nullable/default, CREATE INDEX IF NOT EXISTS).
- Never drops tables/columns, never truncates, never deletes or overwrites historical rows.
- Can inspect live schema read-only or preview pending statements via --dry-run before applying.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
from typing import Any
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("tradelab.migrations")
IST = ZoneInfo("Asia/Kolkata")


MIGRATIONS: list[dict[str, Any]] = [
    {
        "version": "2026_11_26_001_core_tables",
        "description": "Ensure baseline ORM tables (including ai_trade_evidence, pending_paper_orders) exist additively",
        "kind": "orm_create_all",
    },
    {
        "version": "2026_11_26_002_additive_columns_and_indexes",
        "description": "Add missing backward-compatible columns and query performance indexes",
        "kind": "columns_and_indexes",
    },
]

_ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "users": [
        ("google_id", "VARCHAR(128)"),
        ("avatar_url", "VARCHAR(512)"),
    ],
    "daily_reports": [
        ("date", "VARCHAR(16) DEFAULT ''"),
        ("report_date", "VARCHAR(16) DEFAULT ''"),
        ("summary_metrics", "TEXT DEFAULT '{}'"),
        ("summary_json", "TEXT DEFAULT '{}'"),
        ("raw_analysis", "TEXT DEFAULT '{}'"),
        ("ai_analysis_json", "TEXT DEFAULT '{}'"),
        ("report_markdown", "TEXT DEFAULT ''"),
        ("markdown_report", "TEXT DEFAULT ''"),
        ("report_html", "TEXT"),
    ],
}

_ADDITIVE_INDEXES: list[tuple[str, str, str, bool]] = [
    # (index_name, table_name, columns_sql, unique)
    ("ix_users_google_id", "users", "google_id", True),
    ("ix_paper_trades_user_status", "paper_trades", "user_id, status", False),
    ("ix_paper_trades_user_closed", "paper_trades", "user_id, closed_at", False),
    ("ix_daily_reports_user_date", "daily_reports", "user_id, date", False),
]


def _ensure_migrations_table_sync(conn) -> None:
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(64) PRIMARY KEY,
            description TEXT NOT NULL DEFAULT '',
            checksum VARCHAR(64) NOT NULL DEFAULT '',
            applied_at VARCHAR(32) NOT NULL DEFAULT ''
        )
        """
    )


def _compute_plan_sync(conn) -> dict[str, Any]:
    insp = inspect(conn)
    existing_tables = set(insp.get_table_names())
    missing_columns: list[dict[str, str]] = []
    missing_indexes: list[dict[str, Any]] = []

    for table_name, col_defs in _ADDITIVE_COLUMNS.items():
        if table_name not in existing_tables:
            continue
        cols = {c["name"] for c in insp.get_columns(table_name)}
        for col_name, col_type in col_defs:
            if col_name not in cols:
                missing_columns.append({
                    "table": table_name,
                    "column": col_name,
                    "ddl": f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}",
                })

    for idx_name, table_name, cols_sql, unique in _ADDITIVE_INDEXES:
        if table_name not in existing_tables:
            continue
        existing_idx = {idx["name"] for idx in insp.get_indexes(table_name) if idx.get("name")}
        if idx_name not in existing_idx:
            uniq = "UNIQUE " if unique else ""
            missing_indexes.append({
                "table": table_name,
                "index": idx_name,
                "ddl": f"CREATE {uniq}INDEX IF NOT EXISTS {idx_name} ON {table_name} ({cols_sql})",
            })

    applied: list[dict[str, str]] = []
    if "schema_migrations" in existing_tables:
        rows = conn.exec_driver_sql(
            "SELECT version, description, checksum, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        applied = [
            {"version": r[0], "description": r[1], "checksum": r[2], "applied_at": r[3]}
            for r in rows
        ]

    return {
        "dialect": conn.dialect.name,
        "existing_tables": sorted(existing_tables),
        "missing_columns": missing_columns,
        "missing_indexes": missing_indexes,
        "applied_migrations": applied,
    }


def _apply_sync(conn, base_metadata) -> dict[str, Any]:
    # 1. Create any newly added ORM tables additively (never drops existing tables)
    base_metadata.create_all(conn)
    _ensure_migrations_table_sync(conn)

    plan = _compute_plan_sync(conn)
    applied_ddl: list[str] = []

    for item in plan["missing_columns"]:
        conn.exec_driver_sql(item["ddl"])
        applied_ddl.append(item["ddl"])

    for item in plan["missing_indexes"]:
        conn.exec_driver_sql(item["ddl"])
        applied_ddl.append(item["ddl"])

    now_str = datetime.now(tz=IST).strftime("%Y-%m-%d %H:%M:%S")
    existing_versions = {m["version"] for m in plan["applied_migrations"]}
    for mig in MIGRATIONS:
        ver = mig["version"]
        if ver in existing_versions:
            continue
        checksum = hashlib.sha256(f"{ver}:{mig['description']}".encode()).hexdigest()[:16]
        conn.execute(
            text(
                "INSERT INTO schema_migrations (version, description, checksum, applied_at) "
                "VALUES (:v, :d, :c, :a)"
            ),
            {"v": ver, "d": mig["description"], "c": checksum, "a": now_str},
        )

    return {
        "dialect": conn.dialect.name,
        "applied_ddl": applied_ddl,
        "tables_after": sorted(inspect(conn).get_table_names()),
    }


async def inspect_schema(async_engine: AsyncEngine) -> dict[str, Any]:
    """Read-only inspection of current schema and pending additive migrations."""
    async with async_engine.connect() as conn:
        plan = await conn.run_sync(_compute_plan_sync)
        row_counts: dict[str, int] = {}
        for t in plan["existing_tables"]:
            try:
                cnt = (await conn.execute(text(f'SELECT COUNT(*) FROM "{t}"'))).scalar_one()
                row_counts[t] = int(cnt)
            except Exception as exc:
                logger.warning("Could not count rows in %s: %s", t, exc)
        plan["row_counts"] = row_counts
        return plan


async def apply_additive_migrations(async_engine: AsyncEngine, base_metadata, conn=None) -> dict[str, Any]:
    """Apply idempotent, non-destructive additive migrations inside a transaction."""
    if conn is not None:
        return await conn.run_sync(lambda sync_conn: _apply_sync(sync_conn, base_metadata))
    async with async_engine.begin() as owned_conn:
        return await owned_conn.run_sync(lambda sync_conn: _apply_sync(sync_conn, base_metadata))


async def _cli() -> None:
    import json
    from database import Base, engine

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Inspect schema and print pending additive DDL without modifying DB")
    parser.add_argument("--apply", action="store_true", help="Apply non-destructive additive migrations")
    args = parser.parse_args()

    try:
        if args.apply and not args.dry_run:
            res = await apply_additive_migrations(engine, Base.metadata)
            print(json.dumps(res, indent=2))
        else:
            res = await inspect_schema(engine)
            print(json.dumps(res, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_cli())
