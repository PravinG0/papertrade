"""
Angel One Scrip Master loader.

Downloads the public OpenAPIScripMaster.json once a day, keeps only index-option
contracts (NIFTY, BANKNIFTY, FINNIFTY, SENSEX) and exposes fast lookups so the app
can use the *real* exchange trading symbols, expiries, strikes, lot sizes and
instrument tokens instead of synthetic ones.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

from config import settings

logger = logging.getLogger("scrip_master")
IST = ZoneInfo("Asia/Kolkata")

SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)
UNDERLYINGS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX")


@dataclass(frozen=True)
class Contract:
    name: str          # underlying, e.g. NIFTY
    expiry: str        # ISO date, e.g. 2025-12-02
    strike: int
    option_type: str   # CE | PE
    exchange: str      # NFO | BFO
    token: str
    symbol: str        # exchange trading symbol, e.g. NIFTY02DEC2525000CE
    lot_size: int


class ScripMaster:
    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str, int, str], Contract] = {}
        self._by_symbol: dict[str, Contract] = {}
        self._expiries: dict[str, list[str]] = {}
        self._strikes: dict[tuple[str, str], list[int]] = {}
        self._loaded_on: Optional[date] = None
        self._lock = asyncio.Lock()
        self._next_retry: float = 0.0

    # ── State ────────────────────────────────────────────────────────────
    @property
    def is_loaded(self) -> bool:
        return bool(self._by_symbol)

    def _today(self) -> date:
        return datetime.now(tz=IST).date()

    def _cache_path(self) -> Path:
        return Path(settings.SCRIP_CACHE_PATH)

    # ── Loading ──────────────────────────────────────────────────────────
    async def ensure_loaded(self) -> bool:
        """Load (or refresh once per day) the contract table. Never raises."""
        if self._loaded_on == self._today() and self.is_loaded:
            return True
        async with self._lock:
            if self._loaded_on == self._today() and self.is_loaded:
                return True
            if time.time() < self._next_retry:
                return self.is_loaded
            try:
                rows = await asyncio.to_thread(self._read_fresh_cache)
                if rows is None:
                    rows = await self._download()
                    await asyncio.to_thread(self._write_cache, rows)
                self._index(rows)
                self._loaded_on = self._today()
                logger.info("Scrip master ready: %d option contracts", len(self._by_symbol))
                return True
            except Exception as exc:
                logger.warning("Scrip master load failed: %s", exc)
                self._next_retry = time.time() + 600
                # A stale cache is still better than nothing (expiries/strikes rarely change)
                if not self.is_loaded:
                    try:
                        rows = await asyncio.to_thread(self._read_any_cache)
                        if rows:
                            self._index(rows)
                    except Exception:
                        pass
                return self.is_loaded

    def _read_fresh_cache(self) -> Optional[list]:
        p = self._cache_path()
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("date") != self._today().isoformat():
            return None
        return data.get("rows")

    def _read_any_cache(self) -> Optional[list]:
        p = self._cache_path()
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8")).get("rows")

    def _write_cache(self, rows: list) -> None:
        try:
            p = self._cache_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps({"date": self._today().isoformat(), "rows": rows}),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("Could not write scrip cache: %s", exc)

    async def _download(self) -> list:
        logger.info("Downloading Angel One scrip master ...")
        raw = b""
        last_exc: Optional[Exception] = None
        for attempt in range(1, 4):  # Angel's file server truncates connections now and then
            try:
                async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
                    resp = await client.get(SCRIP_MASTER_URL)
                    resp.raise_for_status()
                    raw = resp.content
                if len(raw) < 1_000_000:
                    raise RuntimeError(f"truncated download ({len(raw)} bytes)")
                break
            except Exception as exc:
                last_exc = exc
                logger.warning("Scrip master download attempt %d failed: %s", attempt, exc)
                await asyncio.sleep(3 * attempt)
        else:
            raise RuntimeError(f"scrip master download failed: {last_exc}")
        rows = await asyncio.to_thread(self._filter, raw)
        del raw
        if not rows:
            raise RuntimeError("scrip master contained no index options")
        return rows

    def _filter(self, raw: bytes) -> list:
        today = self._today()
        out: list = []
        for it in json.loads(raw):
            if it.get("instrumenttype") != "OPTIDX":
                continue
            name = it.get("name")
            if name not in UNDERLYINGS:
                continue
            try:
                exp = datetime.strptime(it["expiry"], "%d%b%Y").date()
            except (KeyError, ValueError):
                continue
            if exp < today:
                continue
            sym = str(it.get("symbol", ""))
            opt = sym[-2:]
            if opt not in ("CE", "PE"):
                continue
            try:
                strike = int(round(float(it["strike"]) / 100.0))
                lot = int(float(it.get("lotsize") or 0))
            except (KeyError, ValueError):
                continue
            out.append([name, exp.isoformat(), strike, opt, it.get("exch_seg"), str(it["token"]), sym, lot])
        return out

    def _index(self, rows: list) -> None:
        by_key: dict = {}
        by_symbol: dict = {}
        expiries: dict[str, set[str]] = {}
        strikes: dict[tuple[str, str], set[int]] = {}
        for name, exp, strike, opt, exch, token, sym, lot in rows:
            c = Contract(name, exp, int(strike), opt, exch, token, sym, int(lot))
            by_key[(name, exp, c.strike, opt)] = c
            by_symbol[sym] = c
            expiries.setdefault(name, set()).add(exp)
            strikes.setdefault((name, exp), set()).add(c.strike)
        self._by_key = by_key
        self._by_symbol = by_symbol
        self._expiries = {k: sorted(v) for k, v in expiries.items()}
        self._strikes = {k: sorted(v) for k, v in strikes.items()}

    # ── Lookups ──────────────────────────────────────────────────────────
    def expiries(self, name: str) -> list[str]:
        today = self._today().isoformat()
        return [e for e in self._expiries.get(name, []) if e >= today]

    def strikes(self, name: str, expiry: str) -> list[int]:
        return self._strikes.get((name, expiry), [])

    def contract(self, name: str, expiry: str, strike: int, opt: str) -> Optional[Contract]:
        return self._by_key.get((name, expiry, int(strike), opt))

    def by_symbol(self, symbol: str) -> Optional[Contract]:
        return self._by_symbol.get(symbol)

    def lot_size(self, name: str) -> Optional[int]:
        exps = self.expiries(name)
        if not exps:
            return None
        for c in self._by_key.values():
            if c.name == name and c.expiry == exps[0] and c.lot_size:
                return c.lot_size
        return None

    def resolve(self, symbol: str, underlying: str, strike: float, opt: str) -> Optional[Contract]:
        """Map an order's symbol (real or legacy 'NIFTY24500CE') to a live contract."""
        c = self._by_symbol.get(symbol)
        if c:
            return c if (c.expiry >= self._today().isoformat() and c.name == underlying
                         and c.strike == strike and c.option_type == opt) else None
        # Never roll a dated contract into a different expiry. Only legacy undated symbols may fall back.
        if symbol != f"{underlying}{int(strike)}{opt}":
            return None
        exps = self.expiries(underlying)
        for e in exps:
            c = self._by_key.get((underlying, e, int(strike), opt))
            if c:
                return c
        return None


scrip_master = ScripMaster()
