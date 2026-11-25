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
from pydantic import ConfigDict, Field
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
) -> tuple[float, float]:
    """Clamp stop loss and profit target to institutional risk guardrails (₹700 SL, ₹1000 Tgt)."""
    spec = get_index_spec(symbol)
    lot_size = spec.get("lot_size", 25)

    max_sl_pts = max_loss_inr / lot_size
    max_tgt_pts = max_gain_inr / lot_size

    # Clamped SL
    min_allowed_sl = round(max(1.0, entry_price - max_sl_pts), 2)
    clamped_sl = round(max(min_allowed_sl, stop_loss), 2)
    if clamped_sl >= entry_price:
        clamped_sl = round(max(1.0, entry_price - min(max_sl_pts, 20.0)), 2)

    # Clamped Target
    max_allowed_target = round(entry_price + max_tgt_pts, 2)
    clamped_target = round(min(max_allowed_target, target), 2)
    if clamped_target <= entry_price:
        clamped_target = round(entry_price + min(max_tgt_pts, 35.0), 2)

    return clamped_sl, clamped_target
