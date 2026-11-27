"""
Configuration module for TradeLab Paper Trading Backend.

Loads environment variables from /home/pravin/Documents/Trading/papertrade/.env
and exposes application-wide settings and index metadata.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings

# Locate .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)


class Settings(BaseSettings):
    """Application-wide settings sourced from environment variables."""

    model_config = ConfigDict(
        env_file=str(_env_path),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Angel One SmartAPI Credentials ────────────────────────────────────
    ANGEL_API_KEY: str = Field(default="")
    ANGEL_CLIENT_CODE: str = Field(default="")
    ANGEL_PIN: str = Field(default="")
    ANGEL_TOTP_SECRET: str = Field(default="")

    # Cloud V6: one broker stream per process; turn off for REST-only rollback.
    BROKER_STREAM_ENABLED: bool = Field(default=True)
    BROKER_REST_FALLBACK: bool = Field(default=True)
    BROKER_STREAM_MAX_SUBSCRIPTIONS: int = Field(default=300, ge=10, le=1000)
    BROKER_QUOTE_MAX_AGE_SECONDS: float = Field(default=10.0, gt=0, le=30)
    V6_AUTO_EXECUTION_ENABLED: bool = Field(default=False)
    MCX_RESEARCH_ENABLED: bool = Field(default=True)
    # Confirm this date and exchange session before enabling any MCX execution.
    MCX_SESSION_OPEN: str = Field(default="09:00")
    MCX_SESSION_CLOSE: str = Field(default="23:55")
    MCX_SESSION_VALID_FROM: str = Field(default="2026-11-02")
    MCX_SESSION_VALID_UNTIL: str = Field(default="2027-03-12")
    MCX_HOLIDAYS: str = Field(default="")
    MCX_SPECIAL_SESSIONS: str = Field(default="")

    # ── Paper Trading Wallet Defaults ─────────────────────────────────────
    VIRTUAL_STARTING_CAPITAL: float = Field(default=1000000.0)  # Default 10,00,000 INR (10 Lakhs)
    DEFAULT_STRIKES: int = Field(default=10)                    # ATM ± 10 strikes (21 total)

    # ── Server & Market Configuration ─────────────────────────────────────
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)
    DEBUG: bool = Field(default=False)
    TIMEZONE: str = Field(default="Asia/Kolkata")
    MARKET_OPEN: str = Field(default="09:15")
    MARKET_CLOSE: str = Field(default="15:30")
    EXCHANGE_HOLIDAYS: str = Field(default="")
    EXCHANGE_SPECIAL_SESSIONS: str = Field(default="")

    @field_validator('EXCHANGE_HOLIDAYS')
    @classmethod
    def validate_exchange_holidays(cls, value):
        from session_calendar import parse_holidays
        parse_holidays(value)
        return value

    @field_validator('EXCHANGE_SPECIAL_SESSIONS')
    @classmethod
    def validate_exchange_special_sessions(cls, value):
        from session_calendar import parse_special_sessions
        parse_special_sessions(value)
        return value

    # ── Database & Auth Configuration ────────────────────────────────────
    DATABASE_URL: str = Field(
        default=f"sqlite+aiosqlite:///{Path(__file__).resolve().parent / 'papertrade.db'}"
    )
    JWT_SECRET_KEY: str = Field(
        default="tradelab_papertrade_jwt_secret_key_super_secure_99182"
    )
    JWT_ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 24 * 7)

    # ── Google OAuth Configuration ───────────────────────────────────────
    GOOGLE_CLIENT_ID: str = Field(
        default="518222337987-4gkeuho6suld8hbtml9hk4jopofurn35.apps.googleusercontent.com"
    )
    GOOGLE_CLIENT_SECRET: str = Field(default="")

    # ── Gemini AI Configuration ──────────────────────────────────────────
    GEMINI_API_KEY: str = Field(default="")
    GEMINI_MODEL: str = Field(default="gemini-3.8-flash")

    # Adaptive paper-trading memory and hard risk rules
    MEMORY_SHORT_DAYS: int = Field(default=5, ge=1, le=30)
    MEMORY_LONG_DAYS: int = Field(default=30, ge=5, le=90)
    MEMORY_EXTENDED_DAYS: int = Field(default=90, ge=30, le=90)
    QUANT_MIN_CONFIDENCE: int = Field(default=8, ge=1, le=10)
    QUANT_MIN_NET_RR: float = Field(default=1.5, gt=0, le=10)
    QUANT_MAX_SPREAD_PCT: float = Field(default=2.0, gt=0, le=20)
    QUANT_MAX_VERDICT_AGE_SECONDS: int = Field(default=180, ge=30, le=600)
    AUTO_MAX_DAILY_TRADES: int = Field(default=5, ge=1, le=100)
    AUTO_REPEAT_STRIKE_COOLDOWN_MINUTES: int = Field(default=30, ge=1, le=1440)
    AUTO_TREND_THRESHOLD_PCT: float = Field(default=0.75, gt=0, le=10)

    # ── Keep-Alive / Render Self-Ping Configuration ────────────────────────
    RENDER_EXTERNAL_URL: str = Field(default="")
    KEEP_ALIVE_INTERVAL_SECONDS: int = Field(default=600)  # 10 minutes (prevents Render 15-min idle sleep)
    ENABLE_KEEP_ALIVE: bool = Field(default=True)

    # ── Testing switch: allow opening trades outside 09:15-15:15 IST (disables auto square-off) ──
    ALLOW_OFFHOURS_TRADING: bool = Field(default=False)
    ALLOW_SIMULATED_TRADING: bool = Field(default=False)
    ALLOW_SHORT_OPTIONS: bool = Field(default=True)

    # ── Scrip Master Cache Path ───────────────────────────────────────────
    SCRIP_CACHE_PATH: str = Field(
        default=str(Path(__file__).resolve().parent / "scrip_master_cache.json")
    )


settings = Settings()

# The repo is public, so the built-in default JWT secret is public too: anyone could forge a login
# token for any user. If JWT_SECRET_KEY was not set to something private, derive a stable secret
# from private values already in the environment (so sessions survive restarts) and warn.
_DEFAULT_JWT = "tradelab_papertrade_jwt_secret_key_super_secure_99182"
if not settings.JWT_SECRET_KEY or settings.JWT_SECRET_KEY == _DEFAULT_JWT:
    import hashlib
    import logging as _logging

    _private = [
        settings.ANGEL_TOTP_SECRET, settings.ANGEL_API_KEY, settings.GEMINI_API_KEY,
        settings.GOOGLE_CLIENT_SECRET,
        settings.DATABASE_URL if "@" in settings.DATABASE_URL else "",
    ]
    _private = [p for p in _private if p]
    if _private:
        settings.JWT_SECRET_KEY = hashlib.sha256(("tradelab-jwt-v1|" + "|".join(_private)).encode()).hexdigest()
        _logging.getLogger("tradelab.config").warning(
            "JWT_SECRET_KEY is not set; using a secret derived from private environment values. "
            "Set JWT_SECRET_KEY to a long random string in your host's environment."
        )
    else:
        import secrets
        settings.JWT_SECRET_KEY = secrets.token_urlsafe(48)
        _logging.getLogger("tradelab.config").warning(
            "Using an ephemeral JWT secret; sessions reset on restart. Set a private JWT_SECRET_KEY."
        )

# ── Index Configurations & Constants ─────────────────────────────────────────
INDEX_CONFIG: dict[str, dict[str, Any]] = {
    "NIFTY": {
        "symbol": "NIFTY",
        "name": "NIFTY 50",
        "exchange": "NSE",
        "token": "99926000",
        "trading_symbol": "Nifty 50",
        "lot_size": 25,
        "strike_step": 50,
        "default_spot": 24980.0,
        "tick_size": 0.05,
    },
    "BANKNIFTY": {
        "symbol": "BANKNIFTY",
        "name": "NIFTY BANK",
        "exchange": "NSE",
        "token": "99926009",
        "trading_symbol": "Nifty Bank",
        "lot_size": 15,
        "strike_step": 100,
        "default_spot": 52140.0,
        "tick_size": 0.05,
    },
    "FINNIFTY": {
        "symbol": "FINNIFTY",
        "name": "NIFTY FIN SERVICE",
        "exchange": "NSE",
        "token": "99926037",
        "trading_symbol": "Nifty Fin Service",
        "lot_size": 25,
        "strike_step": 50,
        "default_spot": 24450.0,
        "tick_size": 0.05,
    },
    "SENSEX": {
        "symbol": "SENSEX",
        "name": "BSE SENSEX",
        "exchange": "BSE",
        "token": "99919000",
        "trading_symbol": "Sensex",
        "lot_size": 10,
        "strike_step": 100,
        "default_spot": 81650.0,
        "tick_size": 0.05,
    },
}

# Alias resolution mapping
SYMBOL_ALIASES: dict[str, str] = {
    "NIFTY 50": "NIFTY",
    "NIFTY50": "NIFTY",
    "^NSEI": "NIFTY",
    "%5ENSEI": "NIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "BANK NIFTY": "BANKNIFTY",
    "^NSEBANK": "BANKNIFTY",
    "%5ENSEBANK": "BANKNIFTY",
    "NIFTY FIN SERVICE": "FINNIFTY",
    "FIN NIFTY": "FINNIFTY",
    "BSE SENSEX": "SENSEX",
    "BSESENSEX": "SENSEX",
    "^BSESN": "SENSEX",
}


def normalize_index_symbol(symbol: str) -> str:
    """Normalize input symbol to primary index symbol key (e.g. 'Nifty 50' -> 'NIFTY')."""
    if not symbol:
        return "NIFTY"
    clean = symbol.strip().upper()
    if clean.startswith(('MCX', 'CRUDEOIL', 'CRUDE OIL')):
        raise ValueError('MCX uses the dedicated research market endpoint; index trading is not supported.')
    if clean in INDEX_CONFIG:
        return clean
    if clean in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[clean]
    # Remove whitespace and special chars
    stripped = clean.replace(" ", "").replace("^", "").replace("-", "")
    if stripped in INDEX_CONFIG:
        return stripped
    if stripped in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[stripped]
    return "NIFTY"


def get_index_spec(symbol: str) -> dict[str, Any]:
    """Retrieve index specifications for a given symbol."""
    norm = normalize_index_symbol(symbol)
    return INDEX_CONFIG.get(norm, INDEX_CONFIG["NIFTY"]).copy()


def compute_clamped_sl_target(
    symbol: str,
    entry_price: float,
    stop_loss: float,
    target: float,
    max_loss_inr: float = 700.0,
    max_gain_inr: float = 1000.0,
    *, quantity: int | None = None,
) -> tuple[float, float]:
    """Clamp premium distances; actual total units mandatory at execution.

    Preview callers may use configured lot size. Gross risk excludes fees/slippage.
    """
    from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
    import math
    qty = quantity if quantity is not None else get_index_spec(symbol)["lot_size"]
    if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
        raise ValueError("Positive integer quantity required")
    if not all(math.isfinite(v) for v in (entry_price, stop_loss, target, max_loss_inr, max_gain_inr)) or min(entry_price, max_loss_inr, max_gain_inr) <= 0:
        raise ValueError("Invalid risk inputs")
    entry, sl, tgt, loss, gain = map(lambda v: Decimal(str(v)), (entry_price, stop_loss, target, max_loss_inr, max_gain_inr))
    tick = Decimal('0.05')
    ceil = lambda v: (v / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    floor = lambda v: (v / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
    lower = ceil(max(tick, entry - loss / qty))
    upper = floor(entry + gain / qty)
    sl = ceil(max(lower, sl)) if 0 < sl < entry else lower
    tgt = floor(min(upper, tgt)) if tgt > entry else upper
    if not 0 < sl < entry < tgt:
        raise ValueError("Risk limits cannot accommodate a valid price tick")
    return float(sl), float(tgt)


def is_trading_day(now):
    from session_calendar import parse_holidays, parse_special_sessions, trading_day
    return trading_day(now, parse_holidays(settings.EXCHANGE_HOLIDAYS), parse_special_sessions(settings.EXCHANGE_SPECIAL_SESSIONS))


def get_session_bounds(now):
    from session_calendar import parse_holidays, parse_special_sessions, session_bounds
    return session_bounds(now, parse_holidays(settings.EXCHANGE_HOLIDAYS), parse_special_sessions(settings.EXCHANGE_SPECIAL_SESSIONS))


def gemini_candidate_models() -> list[str]:
    """Ordered Gemini models with one primary retry plus active free-tier failover."""
    primary = settings.GEMINI_MODEL or "gemini-3.8-flash"
    unique = list(dict.fromkeys([m for m in (primary, "gemini-3.8-flash", "gemini-3.5-flash-lite") if m]))
    return [unique[0]] + unique
