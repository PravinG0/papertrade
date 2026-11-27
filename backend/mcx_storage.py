"""Serialize MCX JSON-ledger changes without changing the existing DB schema."""
import asyncio
import json
from contextlib import asynccontextmanager

_lock = asyncio.Lock()

@asynccontextmanager
async def edit(key, default):
    from sqlalchemy import text
    from database import AppKVModel, async_session_factory, is_sqlite
    # SQLite tests use a process lock + BEGIN IMMEDIATE; PostgreSQL uses a
    # transaction-scoped advisory lock, including when the row does not exist.
    async with _lock:
        async with async_session_factory() as db:
            if is_sqlite:
                await db.execute(text('BEGIN IMMEDIATE'))
            else:
                await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'), {'key':key})
            row = await db.get(AppKVModel, key)
            data = json.loads(row.value) if row and row.value else default()
            yield data
            value = json.dumps(data, allow_nan=False)
            if row is None:
                db.add(AppKVModel(key=key,value=value))
            else:
                row.value = value
            await db.commit()

async def read(key, default):
    from database import AppKVModel, async_session_factory
    async with async_session_factory() as db:
        row = await db.get(AppKVModel,key)
        return json.loads(row.value) if row and row.value else default()

async def keys(prefix):
    from database import AppKVModel, async_session_factory
    from sqlalchemy import select
    async with async_session_factory() as db:
        return list((await db.scalars(select(AppKVModel.key).where(AppKVModel.key.startswith(prefix)))).all())
