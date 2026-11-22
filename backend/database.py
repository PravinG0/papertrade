"""
Database models and async SQLAlchemy 2.0 engine setup for TradeLab Paper Trading.

Provides:
- Persistent SQLite storage with aiosqlite, WAL mode, foreign keys, and busy timeout.
- Relational ORM models:
  * UserModel: User authentication, credentials, timestamps.
  * PaperTradeModel: Live positions and historical executed trades linked to user accounts.
  * PortfolioModel: Virtual cash balances and used margins per user.
  * DebateSessionModel: AI debate sessions, strikes, reasoning, and verdicts.
- DB initialization helper `init_db()` and FastAPI `get_session()` dependency.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    event,
    func,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.pool import NullPool

from config import settings

logger = logging.getLogger("tradelab.database")
IST = ZoneInfo("Asia/Kolkata")


def ist_now() -> datetime:
    """Current timestamp localized to Asia/Kolkata."""
    return datetime.now(tz=IST)


def ist_now_str() -> str:
    """Current timestamp string formatted as 'YYYY-MM-DD HH:MM:SS'."""
    return ist_now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_database_url(url: str) -> str:
    """Ensure database connection string uses async driver (aiosqlite or asyncpg) and auto-encodes password characters."""
    raw_url = str(url).strip()
    if raw_url.startswith("sqlite:///"):
        # Make sure directory exists for sqlite file
        db_path = raw_url.replace("sqlite:///", "")
        try:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return raw_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    elif raw_url.startswith("sqlite+aiosqlite:///"):
        db_path = raw_url.replace("sqlite+aiosqlite:///", "")
        try:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return raw_url

    # Check for unencoded '@' in password (e.g. postgresql://user:pass@word@host:port/db)
    if "://" in raw_url:
        proto, rest = raw_url.split("://", 1)
        if rest.count("@") > 1:
            userinfo, hostinfo = rest.rsplit("@", 1)
            if ":" in userinfo:
                user, password = userinfo.split(":", 1)
                password = password.replace("@", "%40")
                userinfo = f"{user}:{password}"
            rest = f"{userinfo}@{hostinfo}"
            raw_url = f"{proto}://{rest}"

    # Auto-switch Supabase session pooler (port 5432) to transaction pooler (port 6543)
    # Supabase session mode is strictly limited to 15 clients (EMAXCONNSESSION);
    # transaction mode on port 6543 supports thousands of concurrent connections.
    if ".pooler.supabase.com:5432" in raw_url:
        raw_url = raw_url.replace(".pooler.supabase.com:5432", ".pooler.supabase.com:6543")

    if raw_url.startswith("postgres://"):
        return raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw_url


DATABASE_URL_NORMALIZED = normalize_database_url(settings.DATABASE_URL)
is_sqlite = DATABASE_URL_NORMALIZED.startswith("sqlite")

engine_kwargs: dict[str, Any] = {
    "echo": False,
    "future": True,
}

if is_sqlite:
    engine_kwargs["poolclass"] = NullPool
    engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
else:
    # PostgreSQL (Supabase Transaction Pooler / Neon / Render Postgres)
    # A NullPool opened a brand-new TLS connection for EVERY query (seconds each from Render),
    # which made order placement time out. A tiny pool reuses connections; the transaction
    # pooler (port 6543) multiplexes server-side so this stays well under its client limit.
    engine_kwargs["pool_size"] = 3
    engine_kwargs["max_overflow"] = 2
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 240
    engine_kwargs["pool_timeout"] = 15
    engine_kwargs["connect_args"] = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    }

engine: AsyncEngine = create_async_engine(DATABASE_URL_NORMALIZED, **engine_kwargs)

if is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        """Enable WAL mode, foreign keys, and busy timeout on SQLite connection."""
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
        except Exception as exc:
            logger.warning("Could not set SQLite pragmas: %s", exc)


async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


# ── ORM Models ───────────────────────────────────────────────────────────────

class UserModel(Base):
    """User account entity for authentication and user-scoped data."""

    __tablename__ = "users"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    username: str = Column(String(64), unique=True, index=True, nullable=False)
    email: str = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password: str = Column(String(255), nullable=False)
    google_id: str | None = Column(String(128), unique=True, index=True, nullable=True)
    avatar_url: str | None = Column(String(512), nullable=True)
    created_at: datetime = Column(DateTime(timezone=True), default=ist_now, nullable=False)

    # Relationships
    trades = relationship("PaperTradeModel", back_populates="user", cascade="all, delete-orphan")
    portfolio = relationship("PortfolioModel", back_populates="user", uselist=False, cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username} email={self.email}>"

    def to_dict(self) -> dict[str, Any]:
        """Convert UserModel to client-compatible dictionary format."""
        created_at_str = (
            self.created_at.strftime("%Y-%m-%d %H:%M:%S")
            if hasattr(self.created_at, "strftime")
            else str(self.created_at)
        )
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "google_id": self.google_id,
            "avatar_url": self.avatar_url,
            "created_at": created_at_str,
        }


class PaperTradeModel(Base):
    """Paper trade order/position record stored persistently."""

    __tablename__ = "paper_trades"

    id: str = Column(String(64), primary_key=True)  # e.g. ORD-xxx or POS-xxx
    user_id: int | None = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    symbol: str = Column(String(64), nullable=False)
    underlying: str = Column(String(32), default="NIFTY", nullable=False)
    strike: float = Column(Float, nullable=False)
    option_type: str = Column(String(8), nullable=False)  # CE or PE
    side: str = Column(String(8), nullable=False)         # BUY or SELL
    lots: int = Column(Integer, nullable=False, default=1)
    quantity: int = Column(Integer, nullable=False)
    entry_price: float = Column(Float, nullable=False)
    exit_price: float | None = Column(Float, nullable=True)
    current_ltp: float = Column(Float, nullable=False, default=0.0)
    pnl: float = Column(Float, nullable=False, default=0.0)
    gross_pnl: float = Column(Float, nullable=False, default=0.0)
    realized_pnl: float = Column(Float, nullable=False, default=0.0)
    total_charges: float = Column(Float, nullable=False, default=0.0)
    status: str = Column(String(32), nullable=False, default="ACTIVE")  # ACTIVE, CLOSED, PENDING, CANCELLED
    stop_loss: float | None = Column(Float, nullable=True)
    target: float | None = Column(Float, nullable=True)
    exit_reason: str | None = Column(String(64), nullable=True)
    pnl_pct: float = Column(Float, nullable=False, default=0.0)
    created_at: str = Column(String(32), nullable=False, default=ist_now_str)
    closed_at: str | None = Column(String(32), nullable=True)

    # Relationships
    user = relationship("UserModel", back_populates="trades")

    def __repr__(self) -> str:
        return f"<PaperTrade id={self.id} symbol={self.symbol} status={self.status} pnl={self.realized_pnl}>"

    def to_dict(self) -> dict[str, Any]:
        """Convert ORM record to client-compatible dictionary format."""
        return {
            "id": self.id,
            "pos_id": self.id,
            "order_id": self.id,
            "user_id": self.user_id,
            "symbol": self.symbol,
            "underlying": self.underlying,
            "strike": self.strike,
            "option_type": self.option_type,
            "side": self.side,
            "lots": self.lots,
            "quantity": self.quantity,
            "entry_price": round(self.entry_price, 2),
            "exit_price": round(self.exit_price, 2) if self.exit_price is not None else None,
            "current_ltp": round(self.current_ltp, 2),
            "ltp": round(self.current_ltp, 2),
            "live_price": round(self.current_ltp, 2),
            "pnl": round(self.pnl, 2),
            "unrealized_pnl": round(self.pnl, 2) if self.status == "ACTIVE" else 0.0,
            "gross_pnl": round(self.gross_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "total_charges": round(self.total_charges, 2),
            "status": self.status,
            "stop_loss": round(self.stop_loss, 2) if self.stop_loss is not None else None,
            "target": round(self.target, 2) if self.target is not None else None,
            "exit_reason": self.exit_reason,
            "pnl_pct": round(self.pnl_pct, 2),
            "created_at": self.created_at,
            "entry_time": self.created_at,
            "closed_at": self.closed_at,
            "exit_time": self.closed_at or "",
        }


class PortfolioModel(Base):
    """Persistent virtual portfolio / wallet record per user."""

    __tablename__ = "portfolios"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int | None = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=True, index=True)
    initial_capital: float = Column(Float, nullable=False, default=1000000.0)
    cash_balance: float = Column(Float, nullable=False, default=1000000.0)
    margin_used: float = Column(Float, nullable=False, default=0.0)
    updated_at: str = Column(String(32), nullable=False, default=ist_now_str)

    # Relationships
    user = relationship("UserModel", back_populates="portfolio")

    def __repr__(self) -> str:
        return f"<Portfolio user_id={self.user_id} cash={self.cash_balance}>"


class DebateSessionModel(Base):
    """Persistent AI debate session record."""

    __tablename__ = "debate_sessions"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    symbol: str = Column(String(32), nullable=False, default="NIFTY")
    spot_price: float = Column(Float, nullable=False)
    verdict: str = Column(String(32), nullable=False)  # BULLISH / BEARISH / NEUTRAL
    recommended_strike: int | None = Column(Integer, nullable=True)
    stop_loss: float | None = Column(Float, nullable=True)
    target: float | None = Column(Float, nullable=True)
    bull_arguments: str | None = Column(Text, nullable=True)
    bear_arguments: str | None = Column(Text, nullable=True)
    judge_reasoning: str | None = Column(Text, nullable=True)
    created_at: str = Column(String(32), nullable=False, default=ist_now_str)

    def __repr__(self) -> str:
        return f"<DebateSession id={self.id} symbol={self.symbol} verdict={self.verdict}>"


class DebateRecordModel(Base):
    """Full AI-debate session (JSON payload) so history survives restarts/redeploys."""

    __tablename__ = "debate_records"

    id: str = Column(String(64), primary_key=True)          # deb-<epoch_ms>
    symbol: str = Column(String(32), nullable=False, default="NIFTY", index=True)
    user_id: int | None = Column(Integer, nullable=True, index=True)
    executed: int = Column(Integer, nullable=False, default=0)
    order_id: str | None = Column(String(64), nullable=True)
    position_id: str | None = Column(String(64), nullable=True, index=True)
    created_at: str = Column(String(32), nullable=False, default=ist_now_str, index=True)
    payload: str = Column(Text, nullable=False)


class AppKVModel(Base):
    """Tiny key/value store (e.g. auto-debate scheduler config so it resumes after restart)."""

    __tablename__ = "app_kv"

    key: str = Column(String(64), primary_key=True)
    value: str = Column(Text, nullable=False, default="")


# ── Database Initialization & Session Dependency ──────────────────────────────

async def init_db() -> None:
    """Create all database tables if they do not exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # SQLite schema migration for newly added columns
        if engine.dialect.name == "sqlite":
            def _check_sqlite_columns(connection):
                try:
                    res = connection.exec_driver_sql("PRAGMA table_info(users)").fetchall()
                    col_names = [col[1] for col in res]
                    if "google_id" not in col_names:
                        connection.exec_driver_sql("ALTER TABLE users ADD COLUMN google_id VARCHAR(128)")
                        connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_id ON users (google_id)")
                    if "avatar_url" not in col_names:
                        connection.exec_driver_sql("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(512)")
                except Exception as e:
                    logger.warning("Notice on SQLite table migration: %s", e)

            await conn.run_sync(_check_sqlite_columns)
    logger.info("Database initialized successfully at %s", DATABASE_URL_NORMALIZED)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
