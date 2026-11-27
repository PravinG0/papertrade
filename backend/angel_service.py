"""
Angel One SmartAPI Client and Market Data Service.

Provides:
- Native SmartAPI authentication with dynamic TOTP login (`pyotp`).
- Real-time batch quote fetching (/market/v1/quote/ with mode FULL).
- Historical candlestick fetching (/historical/v1/getCandleData) for 1m, 5m, 15m, 1D.
- Full TradeLab option chain generator with Black-Scholes Greeks, PCR, and Max Pain.
- Asynchronous Scrip Master resolution and high-fidelity fallback generators.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import random
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
import pyotp

from config import INDEX_CONFIG, normalize_index_symbol, settings
from greeks import BlackScholesEngine, calculate_max_pain, calculate_pcr
from scrip_master import Contract, scrip_master

logger = logging.getLogger("angel_service")
logging.basicConfig(level=logging.INFO)

IST = ZoneInfo("Asia/Kolkata")

# Angel One Interval translation
INTERVAL_MAP: dict[str, str] = {
    "1m": "ONE_MINUTE",
    "3m": "THREE_MINUTE",
    "5m": "FIVE_MINUTE",
    "10m": "TEN_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "30m": "THIRTY_MINUTE",
    "1h": "ONE_HOUR",
    "60m": "ONE_HOUR",
    "1d": "ONE_DAY",
    "1D": "ONE_DAY",
}


class AngelService:
    """Service interfacing with Angel One SmartAPI with fallback and caching."""

    _instance: Optional[AngelService] = None

    def __init__(self) -> None:
        self.api_key = settings.ANGEL_API_KEY
        self.client_code = settings.ANGEL_CLIENT_CODE
        self.pin = settings.ANGEL_PIN
        self.totp_secret = settings.ANGEL_TOTP_SECRET

        self._jwt_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._feed_token: Optional[str] = None
        self._token_expiry_epoch: float = 0.0
        self._auth_lock = asyncio.Lock()
        self._last_auth_attempt: float = 0.0
        self._auth_cooldown: float = 5.0

        self._client: Optional[httpx.AsyncClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # In-memory caches
        self._candle_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._last_valid_candles: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._quote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._spot_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._scrip_master: dict[str, Any] = {}
        self._scrip_download_task: Optional[asyncio.Task] = None

        # Historical candle rate-limiting, deduplication, and cooldown state
        self._candle_lock = asyncio.Lock()
        self._last_candle_ts: float = 0.0
        self._candle_min_interval: float = 1.2
        self._candle_cooldown_until: float = 0.0
        self._candle_inflight: dict[str, asyncio.Task] = {}

        # Live-quote plumbing (SmartAPI allows ~1 quote request / second)
        self._quote_lock = asyncio.Lock()
        self._last_quote_ts: float = 0.0
        self._tok_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._last_live_ok: float = 0.0
        self._oi_baseline: dict[str, tuple[str, float]] = {}
        self.vix: Optional[float] = None
        # tokens somebody asked for recently: token -> (exchange, last_requested_epoch)
        self._watch: dict[str, tuple[str, float]] = {}
        self._refresher: Optional[asyncio.Task] = None

    @classmethod
    def get_instance(cls) -> AngelService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def is_configured(self) -> bool:
        """Verify whether all required credentials are present."""
        return bool(
            self.api_key
            and self.client_code
            and self.pin
            and self.totp_secret
        )

    def _ensure_loop(self) -> None:
        """Bind HTTP client to active running event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._loop != loop:
            self._loop = loop
            self._auth_lock = asyncio.Lock()
            self._candle_lock = asyncio.Lock()
            self._candle_inflight = {}
            if self._client is not None and not self._client.is_closed:
                self._client = None

    async def get_http_client(self) -> httpx.AsyncClient:
        """Acquire an active AsyncClient."""
        self._ensure_loop()
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self) -> None:
        """Cleanly close underlying HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _base_headers(self) -> dict[str, str]:
        """Generate base SmartAPI request headers."""
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "157.51.15.74",
            "X-MACAddress": "fe80::216e:6507:4b83:3797",
            "X-PrivateKey": self.api_key,
        }

    async def authenticate(self, force_refresh: bool = False) -> bool:
        """Authenticate with Angel One SmartAPI using TOTP."""
        if not self.is_configured():
            logger.warning("Angel One credentials are missing or incomplete in config.")
            return False

        self._ensure_loop()
        async with self._auth_lock:
            now = time.time()
            if not force_refresh and self._jwt_token and now < self._token_expiry_epoch:
                return True

            if not force_refresh and now - self._last_auth_attempt < self._auth_cooldown:
                logger.debug("Authentication cooldown active, skipping attempt.")
                return bool(self._jwt_token and now < self._token_expiry_epoch)

            self._last_auth_attempt = now

            try:
                totp_code = pyotp.TOTP(self.totp_secret).now()
                payload = {
                    "clientcode": self.client_code,
                    "password": self.pin,
                    "totp": totp_code,
                }
                client = await self.get_http_client()
                resp = await client.post(
                    "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword",
                    json=payload,
                    headers=self._base_headers(),
                )

                if resp.status_code != 200:
                    logger.warning("Angel One login returned HTTP %s: %s", resp.status_code, resp.text[:150])
                    return False

                data = resp.json()
                if data.get("status") is True:
                    token_data = data.get("data", {})
                    self._jwt_token = token_data.get("jwtToken")
                    self._refresh_token = token_data.get("refreshToken")
                    self._feed_token = token_data.get("feedToken")
                    # Tokens valid for ~24 hours; refresh after 12h
                    self._token_expiry_epoch = now + (12 * 3600)
                    logger.info("Angel One SmartAPI login successful for user %s", self.client_code)
                    return True
                else:
                    logger.warning("Angel One login failed: %s - %s", data.get("errorcode"), data.get("message"))
                    return False
            except Exception as exc:
                logger.error("Exception during Angel One authentication: %s", exc)
                return False

    # ── Live quote plumbing ──────────────────────────────────────────────────

    @property
    def data_source(self) -> str:
        """'live' when Angel One quotes were fetched in the last 30s, else 'simulated'."""
        return "live" if (time.time() - self._last_live_ok) < 30.0 else "simulated"

    async def fetch_quotes(self, exchange_tokens: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
        """Throttled SmartAPI FULL-mode quote call. Returns {symbolToken: item}. Never raises."""
        exchange_tokens = {k: v for k, v in exchange_tokens.items() if v}
        if not exchange_tokens or not await self.authenticate():
            return {}
        async with self._quote_lock:
            wait = self._last_quote_ts + 1.05 - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
            headers = self._base_headers()
            headers["Authorization"] = f"Bearer {self._jwt_token}"
            try:
                client = await self.get_http_client()
                resp = await client.post(
                    "https://apiconnect.angelone.in/rest/secure/angelbroking/market/v1/quote/",
                    json={"mode": "FULL", "exchangeTokens": exchange_tokens},
                    headers=headers,
                )
                self._last_quote_ts = time.time()
                if resp.status_code != 200:
                    logger.warning("Quote API HTTP %s: %s", resp.status_code, resp.text[:120])
                    return {}
                data = resp.json()
                if data.get("status") is not True:
                    code = str(data.get("errorcode") or "")
                    logger.warning("Quote API error %s: %s", code, data.get("message"))
                    if code in ("AG8001", "AG8002", "AG8003"):  # token invalid / expired
                        self._token_expiry_epoch = 0.0
                    return {}
                out: dict[str, dict[str, Any]] = {}
                now = time.time()
                for item in (data.get("data") or {}).get("fetched") or []:
                    tok = str(item.get("symbolToken", ""))
                    if tok:
                        out[tok] = item
                        self._tok_cache[tok] = (now, item)
                if out:
                    self._last_live_ok = now
                return out
            except Exception as exc:
                self._last_quote_ts = time.time()
                logger.warning("Quote fetch failed: %s", exc)
                return {}

    def _ensure_refresher(self) -> None:
        if not self.is_configured():
            return
        if self._refresher is None or self._refresher.done():
            self._refresher = asyncio.create_task(self._refresh_loop())

    async def _refresh_loop(self) -> None:
        """Keep recently-requested quotes warm in ONE paced stream.

        Angel allows ~1 quote request/second. Without this, the index poll, option-chain poll,
        position tracker and every browser tab queued behind that limit (chain calls took 10-15s).
        Now API calls read the warm cache; this loop is the only steady caller.
        """
        idle_since = time.time()
        while True:
            try:
                now = time.time()
                self._watch = {t: v for t, v in self._watch.items() if now - v[1] < 30.0}
                if not self._watch:
                    if now - idle_since > 60.0:
                        return  # nobody is looking; restarts on the next request
                    await asyncio.sleep(1.0)
                    continue
                idle_since = now

                stalest_first = sorted(
                    self._watch.items(), key=lambda kv: self._tok_cache.get(kv[0], (0.0, None))[0]
                )
                batch = stalest_first[:50]
                age = now - self._tok_cache.get(batch[0][0], (0.0, None))[0]
                if age < 1.0:
                    await asyncio.sleep(0.4)
                    continue
                by_exch: dict[str, list[str]] = {}
                for tok, (exch, _) in batch:
                    by_exch.setdefault(exch, []).append(tok)
                got = await self.fetch_quotes(by_exch)
                if not got:
                    await asyncio.sleep(2.0)  # API error / rate-limited: back off
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("quote refresher error: %s", exc)
                await asyncio.sleep(2.0)

    async def get_token_quotes(
        self, items: list[tuple[str, str]], ttl: float = 4.0
    ) -> dict[str, dict[str, Any]]:
        """Quotes for [(exchange, token), ...]: warm cache first, direct fetch only for misses."""
        now = time.time()
        for exch, tok in items:
            self._watch[tok] = (exch, now)
        self._ensure_refresher()
        result: dict[str, dict[str, Any]] = {}
        missing: dict[str, list[str]] = {}
        for exch, tok in items:
            hit = self._tok_cache.get(tok)
            if hit and now - hit[0] < ttl:
                result[tok] = hit[1]
            else:
                missing.setdefault(exch, []).append(tok)
        for exch, toks in missing.items():
            for i in range(0, len(toks), 50):
                got = await self.fetch_quotes({exch: toks[i:i + 50]})
                result.update(got)
        return result

    # ── Spot Indices ─────────────────────────────────────────────────────────

    async def get_spot_indices(self) -> list[dict[str, Any]]:
        """Fetch real-time spot indices quotes for NIFTY, BANKNIFTY, FINNIFTY, SENSEX (+ India VIX)."""
        now = time.time()
        exchange_tokens: dict[str, list[str]] = {"NSE": ["99926017"], "BSE": []}  # 99926017 = India VIX
        token_to_sym: dict[str, str] = {}
        for sym_key, spec in INDEX_CONFIG.items():
            exchange_tokens[spec["exchange"]].append(spec["token"])
            token_to_sym[spec["token"]] = sym_key

        quotes_by_sym: dict[str, dict[str, Any]] = {}
        fetched = await self.get_token_quotes(
            [(e, t) for e, toks in exchange_tokens.items() for t in toks], ttl=4.0
        )
        vix_item = fetched.get("99926017")
        if vix_item and float(vix_item.get("ltp") or 0) > 0:
            self.vix = round(float(vix_item["ltp"]), 2)

        for tok, item in fetched.items():
            sym_key = token_to_sym.get(tok)
            if not sym_key:
                continue
            ltp = float(item.get("ltp") or 0.0)
            if ltp <= 0:
                continue
            close_val = float(item.get("close") or ltp)
            net_chg = float(item.get("netChange") or round(ltp - close_val, 2))
            pct_chg = float(
                item.get("percentChange")
                or (round((net_chg / close_val) * 100, 2) if close_val > 0 else 0.0)
            )
            entry = {
                "symbol": sym_key,
                "name": INDEX_CONFIG[sym_key]["name"],
                "trading_symbol": item.get("tradingSymbol", INDEX_CONFIG[sym_key]["trading_symbol"]),
                "token": tok,
                "exchange": INDEX_CONFIG[sym_key]["exchange"],
                "ltp": round(ltp, 2),
                "open": round(float(item.get("open") or ltp), 2),
                "high": round(float(item.get("high") or ltp), 2),
                "low": round(float(item.get("low") or ltp), 2),
                "close": round(close_val, 2),
                "net_change": round(net_chg, 2),
                "percent_change": round(pct_chg, 2),
                "timestamp": datetime.now(tz=IST).isoformat(),
                "source": "live",
            }
            quotes_by_sym[sym_key] = entry
            self._spot_cache[sym_key] = (now, entry)

        result = []
        for sym_key in INDEX_CONFIG:
            if sym_key in quotes_by_sym:
                result.append(quotes_by_sym[sym_key])
                continue
            cached = self._spot_cache.get(sym_key)
            if cached and cached[1].get("source") in ("live", "stale"):
                # Keep the last REAL price (flagged stale) rather than inventing one.
                stale = cached[1].copy()
                stale["source"] = "stale" if now - cached[0] > 10.0 else "live"
                result.append(stale)
            elif cached and now - cached[0] < 30.0:
                result.append(cached[1].copy())
            else:
                fallback = self._generate_fallback_spot(sym_key)
                self._spot_cache[sym_key] = (now, fallback)
                result.append(fallback)
        return result

    def _generate_fallback_spot(self, symbol: str) -> dict[str, Any]:
        """Generate realistic synthetic spot data when offline or markets closed."""
        spec = INDEX_CONFIG.get(symbol, INDEX_CONFIG["NIFTY"])
        base = spec["default_spot"]
        # Micro variation
        jitter = random.uniform(-0.15, 0.25)
        ltp = round(base * (1.0 + jitter / 100.0), 2)
        net_chg = round(ltp - base, 2)
        pct_chg = round((net_chg / base) * 100, 2)

        return {
            "symbol": spec["symbol"],
            "name": spec["name"],
            "trading_symbol": spec["trading_symbol"],
            "token": spec["token"],
            "exchange": spec["exchange"],
            "ltp": ltp,
            "open": round(base - 15.0, 2),
            "high": round(max(ltp, base + 45.0), 2),
            "low": round(min(ltp, base - 35.0), 2),
            "close": base,
            "net_change": net_chg,
            "percent_change": pct_chg,
            "timestamp": datetime.now(tz=IST).isoformat(),
            "source": "simulated",
        }

    async def get_spot_price(self, symbol: str = "NIFTY") -> float:
        """Fetch spot price for a given index symbol."""
        sym_norm = normalize_index_symbol(symbol)
        spots = await self.get_spot_indices()
        for s in spots:
            if s["symbol"] == sym_norm:
                return float(s["ltp"])
        return INDEX_CONFIG.get(sym_norm, INDEX_CONFIG["NIFTY"])["default_spot"]

    # ── Historical Candles ───────────────────────────────────────────────────

    @staticmethod
    def _candle_ttl(angel_interval: str) -> float:
        """Interval-aware cache TTL (seconds) to avoid redundant SmartAPI historical calls."""
        return {
            "ONE_MINUTE": 55.0,
            "THREE_MINUTE": 60.0,
            "FIVE_MINUTE": 60.0,
            "TEN_MINUTE": 180.0,
            "FIFTEEN_MINUTE": 300.0,
            "THIRTY_MINUTE": 450.0,
            "ONE_HOUR": 600.0,
            "ONE_DAY": 1800.0,
        }.get(angel_interval, 60.0)

    @staticmethod
    def _parse_retry_after(resp: httpx.Response, default_sec: float = 10.0) -> float:
        """Parse Retry-After header safely, bounded between 1s and 60s."""
        raw = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
        if raw:
            try:
                val = float(str(raw).strip())
                return max(1.0, min(60.0, val))
            except ValueError:
                pass
        return default_sec

    @staticmethod
    def _parse_and_validate_candles(
        raw: Any,
        one_day: bool = False,
        angel_interval: str = "FIVE_MINUTE",
    ) -> list[dict[str, Any]]:
        """Validate timestamps, OHLC bounds, finite values, and monotonic ordering."""
        if not isinstance(raw, list):
            return []
        parsed: list[dict[str, Any]] = []
        for row in raw:
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                continue
            ts_str, o, h, l, c = row[0], row[1], row[2], row[3], row[4]
            vol = row[5] if len(row) > 5 else 0
            try:
                dt = datetime.fromisoformat(str(ts_str))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=IST)
                t = int(dt.timestamp())
                o_f, h_f, l_f, c_f, v_f = float(o), float(h), float(l), float(c), float(vol or 0)
            except (ValueError, TypeError):
                continue

            if not (
                math.isfinite(o_f)
                and math.isfinite(h_f)
                and math.isfinite(l_f)
                and math.isfinite(c_f)
                and math.isfinite(v_f)
            ):
                continue
            if o_f <= 0 or h_f <= 0 or l_f <= 0 or c_f <= 0 or v_f < 0:
                continue
            if h_f < l_f:
                continue

            parsed.append({
                "time": t,
                "open": round(o_f, 2),
                "high": round(max(h_f, o_f, c_f), 2),
                "low": round(min(l_f, o_f, c_f), 2),
                "close": round(c_f, 2),
                "volume": int(v_f),
            })

        if not parsed:
            return []

        # Enforce strictly ascending unique timestamps
        parsed.sort(key=lambda item: item["time"])
        deduped: list[dict[str, Any]] = []
        last_time = -1
        for item in parsed:
            if item["time"] > last_time:
                deduped.append(item)
                last_time = item["time"]

        if deduped and one_day and angel_interval != "ONE_DAY":
            last_day = datetime.fromtimestamp(deduped[-1]["time"], tz=IST).date()
            deduped = [
                c for c in deduped
                if datetime.fromtimestamp(c["time"], tz=IST).date() == last_day
            ]
        return deduped

    @staticmethod
    def _merge_candles(
        existing: list[dict[str, Any]],
        incoming: list[dict[str, Any]],
        one_day: bool = False,
        angel_interval: str = "FIVE_MINUTE",
    ) -> list[dict[str, Any]]:
        """Merge incremental tail candles onto existing validated history without duplicates."""
        by_time: dict[int, dict[str, Any]] = {int(c["time"]): c.copy() for c in existing if c.get("time") is not None}
        for c in incoming:
            if c.get("time") is not None:
                by_time[int(c["time"])] = c.copy()
        merged = [by_time[k] for k in sorted(by_time)]
        if merged and one_day and angel_interval != "ONE_DAY":
            last_day = datetime.fromtimestamp(merged[-1]["time"], tz=IST).date()
            merged = [
                c for c in merged
                if datetime.fromtimestamp(c["time"], tz=IST).date() == last_day
            ]
        return merged[-500:] if len(merged) > 500 else merged

    @staticmethod
    def _assess_candle_freshness(
        candles: list[dict[str, Any]],
        angel_interval: str = "FIVE_MINUTE",
    ) -> tuple[bool, Optional[int], Optional[str], Optional[str]]:
        """Return (is_fresh, last_epoch, last_candle_ist, stale_reason)."""
        if not candles:
            return False, None, None, "No candles returned."
        last_epoch = int(candles[-1]["time"])
        last_dt = datetime.fromtimestamp(last_epoch, tz=IST)
        last_ist = last_dt.strftime("%Y-%m-%d %H:%M IST")
        now_dt = datetime.now(tz=IST)
        age_sec = max(0.0, now_dt.timestamp() - last_epoch)

        # If market is currently open (Mon-Fri 09:20..15:30 IST), intraday candles should be recent
        in_session = (
            now_dt.weekday() < 5
            and (now_dt.hour, now_dt.minute) >= (9, 20)
            and (now_dt.hour, now_dt.minute) <= (15, 30)
        )
        if in_session and angel_interval != "ONE_DAY":
            max_live_age = 1800.0 if angel_interval in ("ONE_MINUTE", "THREE_MINUTE", "FIVE_MINUTE") else 3600.0
            if age_sec > max_live_age:
                return False, last_epoch, last_ist, f"Latest intraday candle is {int(age_sec // 60)}m old ({last_ist})."
        elif age_sec > 5 * 86400:
            return False, last_epoch, last_ist, f"Latest candle is stale ({last_ist})."

        return True, last_epoch, last_ist, None

    async def get_candles_with_meta(
        self,
        symbol: str = "NIFTY",
        interval: str = "5m",
        range_period: str = "5d",
        contract: Optional[Contract] = None,
    ) -> dict[str, Any]:
        """Fetch historical candles with rate-limiting, deduplication, retries, and freshness metadata."""
        sym_norm = normalize_index_symbol(symbol)
        spec = dict(INDEX_CONFIG.get(sym_norm, INDEX_CONFIG["NIFTY"]))
        if contract is not None:
            spec["exchange"] = contract.exchange
            spec["token"] = contract.token

        angel_interval = INTERVAL_MAP.get(interval.lower(), INTERVAL_MAP.get(interval, "FIVE_MINUTE"))
        cache_key = f"{spec['exchange']}_{spec['token']}_{angel_interval}_{range_period.lower()}"
        ttl = self._candle_ttl(angel_interval)
        now = time.time()

        if cache_key in self._candle_cache:
            c_time, c_candles = self._candle_cache[cache_key]
            age = max(0.0, now - c_time)
            if age < ttl and c_candles:
                _, _, last_ist, _ = self._assess_candle_freshness(c_candles, angel_interval)
                return {
                    "candles": [c.copy() for c in c_candles],
                    "source": "cached",
                    "last_candle_ist": last_ist,
                    "cached_age_seconds": round(age, 1),
                    "error": None,
                    "error_code": None,
                    "reason": None,
                }

        self._ensure_loop()
        inflight = self._candle_inflight.get(cache_key)
        if inflight is not None and not inflight.done():
            res = await inflight
            return {**res, "candles": [c.copy() for c in res.get("candles", [])]}

        task = asyncio.create_task(
            self._fetch_candles_singleflight(
                sym_norm=sym_norm,
                spec=spec,
                interval=interval,
                angel_interval=angel_interval,
                range_period=range_period,
                cache_key=cache_key,
                contract=contract,
            )
        )
        self._candle_inflight[cache_key] = task
        try:
            res = await task
            return {**res, "candles": [c.copy() for c in res.get("candles", [])]}
        finally:
            if self._candle_inflight.get(cache_key) is task:
                self._candle_inflight.pop(cache_key, None)

    async def _fetch_candles_singleflight(
        self,
        sym_norm: str,
        spec: dict[str, Any],
        interval: str,
        angel_interval: str,
        range_period: str,
        cache_key: str,
        contract: Optional[Contract],
    ) -> dict[str, Any]:
        """Singleflight worker for historical candles with rate limiting, retries, and stale fallback."""
        one_day = range_period.lower() in ("1d", "today")

        def _stale_or_unavailable(reason: str, error_code: Optional[str] = None) -> dict[str, Any]:
            if cache_key in self._last_valid_candles:
                c_time, prev_candles = self._last_valid_candles[cache_key]
                if prev_candles:
                    _, _, last_ist, _ = self._assess_candle_freshness(prev_candles, angel_interval)
                    return {
                        "candles": [c.copy() for c in prev_candles],
                        "source": "stale",
                        "last_candle_ist": last_ist,
                        "cached_age_seconds": round(max(0.0, time.time() - c_time), 1),
                        "error": reason,
                        "error_code": error_code,
                        "reason": reason,
                    }
            return {
                "candles": [],
                "source": "unavailable",
                "last_candle_ist": None,
                "cached_age_seconds": None,
                "error": reason,
                "error_code": error_code,
                "reason": reason,
            }

        if not self.is_configured():
            if contract is not None:
                return _stale_or_unavailable("Angel One credentials are not configured for option candles.")
            fallback = self._generate_fallback_candles(sym_norm, interval=interval, count=80)
            self._candle_cache[cache_key] = (time.time(), fallback)
            _, _, last_ist, _ = self._assess_candle_freshness(fallback, angel_interval)
            return {
                "candles": fallback,
                "source": "simulated",
                "last_candle_ist": last_ist,
                "cached_age_seconds": 0.0,
                "error": None,
                "error_code": None,
                "reason": None,
            }

        # Respect active broker rate-limit cooldown
        cooldown_rem = self._candle_cooldown_until - time.time()
        if cooldown_rem > 0:
            return _stale_or_unavailable(
                f"Angel One historical API cooldown active ({int(math.ceil(cooldown_rem))}s remaining).",
                error_code="RATE_LIMIT_COOLDOWN",
            )

        if not await self.authenticate():
            return _stale_or_unavailable("Angel One authentication failed; unable to fetch historical candles.", error_code="AUTH_FAILED")

        now_dt = datetime.now(tz=IST)
        days = 5
        if one_day:
            days = 5
        elif range_period.lower() in ("5d",):
            days = 5
        elif range_period.lower() in ("10d", "15d"):
            days = 15
        elif range_period.lower() in ("1mo", "30d"):
            days = 30
        elif range_period.lower() in ("1y", "1year"):
            days = 365

        if angel_interval == "ONE_DAY" and days < 30:
            days = 60

        full_from_date = (now_dt - timedelta(days=days)).strftime("%Y-%m-%d 09:15")
        to_date = min(now_dt, now_dt.replace(hour=15, minute=30)).strftime("%Y-%m-%d %H:%M")

        # Incremental tail fetch when we already have validated candles >= 20
        prev_entry = self._last_valid_candles.get(cache_key)
        incremental_from: Optional[str] = None
        if prev_entry and len(prev_entry[1]) >= 20 and angel_interval != "ONE_DAY" and not one_day:
            last_candle_dt = datetime.fromtimestamp(prev_entry[1][-1]["time"], tz=IST)
            overlap_dt = last_candle_dt - timedelta(hours=2)
            if overlap_dt < now_dt:
                incremental_from = overlap_dt.strftime("%Y-%m-%d %H:%M")

        from_date = incremental_from or full_from_date
        last_reason = f"Historical candle data for {sym_norm} is unavailable."
        last_code: Optional[str] = None
        max_attempts = 3

        for attempt in range(max_attempts):
            headers = self._base_headers()
            headers["Authorization"] = f"Bearer {self._jwt_token}"
            payload = {
                "exchange": spec["exchange"],
                "symboltoken": spec["token"],
                "interval": angel_interval,
                "fromdate": from_date,
                "todate": to_date,
            }

            try:
                async with self._candle_lock:
                    wait = self._candle_min_interval - (time.time() - self._last_candle_ts)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    self._last_candle_ts = time.time()
                    client = await self.get_http_client()
                    resp = await client.post(
                        "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData",
                        json=payload,
                        headers=headers,
                    )

                if resp.status_code == 401:
                    last_code = "HTTP_401"
                    last_reason = "Angel One historical session expired (HTTP 401); renewing token."
                    logger.warning("Historical candles 401 for %s; forcing token refresh", sym_norm)
                    self._token_expiry_epoch = 0.0
                    self._jwt_token = None
                    if await self.authenticate(force_refresh=True) and attempt < max_attempts - 1:
                        continue
                    break

                if resp.status_code in (429, 403):
                    has_retry_hdr = bool(resp.headers.get("Retry-After") or resp.headers.get("retry-after"))
                    retry_after = self._parse_retry_after(resp, default_sec=12.0 if resp.status_code == 429 else 8.0)
                    last_code = f"HTTP_{resp.status_code}"
                    last_reason = f"Angel One historical API rate-limited/rejected (HTTP {resp.status_code}); retry in {int(retry_after)}s."
                    logger.warning("Historical candles HTTP %s for %s (attempt %d/%d)", resp.status_code, sym_norm, attempt + 1, max_attempts)
                    if resp.status_code == 403 and attempt < max_attempts - 1 and not has_retry_hdr:
                        await asyncio.sleep((1.5 * (attempt + 1)) + random.uniform(0.1, 0.3))
                        continue
                    if attempt < max_attempts - 1 and retry_after <= 3.0:
                        await asyncio.sleep(retry_after + random.uniform(0.05, 0.25))
                        continue
                    self._candle_cooldown_until = max(self._candle_cooldown_until, time.time() + retry_after)
                    break

                if resp.status_code >= 500:
                    last_code = f"HTTP_{resp.status_code}"
                    last_reason = f"Angel One historical API server error (HTTP {resp.status_code})."
                    logger.warning("Historical candles HTTP %s for %s (attempt %d/%d)", resp.status_code, sym_norm, attempt + 1, max_attempts)
                    if attempt < max_attempts - 1:
                        await asyncio.sleep((0.4 * (2 ** attempt)) + random.uniform(0.05, 0.25))
                        continue
                    break

                if resp.status_code != 200:
                    last_code = f"HTTP_{resp.status_code}"
                    last_reason = f"Angel One historical API returned HTTP {resp.status_code}."
                    logger.warning("Historical candles unexpected HTTP %s for %s", resp.status_code, sym_norm)
                    break

                data = resp.json()
                if data.get("status") is not True:
                    err_code = str(data.get("errorcode") or "").strip().upper()
                    err_msg = str(data.get("message") or "Unknown broker error").strip()
                    last_code = err_code or "BROKER_ERROR"
                    last_reason = f"Angel One historical error ({last_code}): {err_msg}"
                    logger.warning("SmartAPI historical rejected for %s: code=%s msg=%s", sym_norm, last_code, err_msg)

                    if err_code in ("AG8001", "AG8002", "AG8003"):
                        self._token_expiry_epoch = 0.0
                        self._jwt_token = None
                        if await self.authenticate(force_refresh=True) and attempt < max_attempts - 1:
                            continue
                        break

                    if err_code in ("AB1004", "AB1010", "AG8004") or "rate" in err_msg.lower() or "exceed" in err_msg.lower():
                        self._candle_cooldown_until = max(self._candle_cooldown_until, time.time() + 10.0)
                        if attempt < max_attempts - 1:
                            await asyncio.sleep((0.5 * (2 ** attempt)) + random.uniform(0.05, 0.25))
                            continue
                    break

                parsed = self._parse_and_validate_candles(data.get("data"), one_day=one_day, angel_interval=angel_interval)
                if not parsed and incremental_from is not None:
                    # Incremental tail returned empty; fall back to full range once
                    incremental_from = None
                    from_date = full_from_date
                    if attempt < max_attempts - 1:
                        continue

                if not parsed:
                    last_code = "EMPTY_CANDLES"
                    last_reason = f"Angel One returned empty or invalid historical candles for {sym_norm}."
                    break

                if incremental_from is not None and prev_entry:
                    candles = self._merge_candles(prev_entry[1], parsed, one_day=one_day, angel_interval=angel_interval)
                else:
                    candles = parsed

                is_fresh, _, last_ist, stale_note = self._assess_candle_freshness(candles, angel_interval)
                now_ts = time.time()
                self._last_valid_candles[cache_key] = (now_ts, candles)
                if is_fresh:
                    self._candle_cache[cache_key] = (now_ts, candles)
                    return {
                        "candles": candles,
                        "source": "live",
                        "last_candle_ist": last_ist,
                        "cached_age_seconds": 0.0,
                        "error": None,
                        "error_code": None,
                        "reason": None,
                    }
                return {
                    "candles": candles,
                    "source": "stale",
                    "last_candle_ist": last_ist,
                    "cached_age_seconds": 0.0,
                    "error": stale_note,
                    "error_code": "STALE_CANDLES",
                    "reason": stale_note,
                }

            except (httpx.TimeoutException, httpx.RequestError) as exc:
                last_code = type(exc).__name__
                last_reason = f"Network timeout/error fetching historical candles for {sym_norm}: {type(exc).__name__}"
                logger.warning("Historical candles network error for %s (attempt %d/%d): %s", sym_norm, attempt + 1, max_attempts, exc)
                if attempt < max_attempts - 1:
                    await asyncio.sleep((0.4 * (2 ** attempt)) + random.uniform(0.05, 0.25))
                    continue
            except Exception as exc:
                last_code = type(exc).__name__
                last_reason = f"Unexpected error fetching historical candles for {sym_norm}: {exc}"
                logger.warning("Error fetching historical candles for %s: %s", sym_norm, exc)
                break

        return _stale_or_unavailable(last_reason, error_code=last_code)

    async def get_candles(
        self,
        symbol: str = "NIFTY",
        interval: str = "5m",
        range_period: str = "5d",
        contract: Optional[Contract] = None,
    ) -> list[dict[str, Any]]:
        """Fetch historical candlestick data from Angel One SmartAPI.

        With `contract` set, returns that option's REAL candles (empty list if unavailable -
        never synthetic), otherwise the index candles.
        """
        meta = await self.get_candles_with_meta(
            symbol=symbol,
            interval=interval,
            range_period=range_period,
            contract=contract,
        )
        return meta.get("candles") or []

    def _generate_fallback_candles(
        self,
        symbol: str,
        interval: str = "5m",
        count: int = 80,
    ) -> list[dict[str, Any]]:
        """Generate realistic synthetic OHLCV candles."""
        spec = INDEX_CONFIG.get(symbol, INDEX_CONFIG["NIFTY"])
        base_price = spec["default_spot"]

        step_seconds = 300
        if "1m" in interval.lower():
            step_seconds = 60
        elif "15m" in interval.lower():
            step_seconds = 900
        elif "1h" in interval.lower() or "60m" in interval.lower():
            step_seconds = 3600
        elif "1d" in interval.lower():
            step_seconds = 86400

        now_sec = int(time.time())
        end_time = (now_sec // step_seconds) * step_seconds
        start_time = end_time - (count * step_seconds)

        candles: list[dict[str, Any]] = []
        cur_price = base_price

        for i in range(count):
            t = start_time + (i * step_seconds)
            drift = math.sin(i * 0.18) * (base_price * 0.0008)
            o = round(cur_price, 2)
            noise = ((i % 5 - 2) * (base_price * 0.0004))
            c = round(cur_price + drift + noise, 2)
            spread = abs(o - c) + (base_price * 0.0005)
            h = round(max(o, c) + spread * 0.6, 2)
            l = round(min(o, c) - spread * 0.6, 2)
            vol = int(random.randint(25000, 150000))

            candles.append({
                "time": t,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
            })
            cur_price = c

        return candles

    async def get_replay_candles(self, symbol: str, date_str: str) -> list[dict[str, Any]]:
        """Fetch full day 1-minute candles for the replay engine (09:15 to 15:30 IST)."""
        sym_norm = normalize_index_symbol(symbol)
        spec = INDEX_CONFIG.get(sym_norm, INDEX_CONFIG["NIFTY"])

        if await self.authenticate():
            headers = self._base_headers()
            headers["Authorization"] = f"Bearer {self._jwt_token}"

            payload = {
                "exchange": spec["exchange"],
                "symboltoken": spec["token"],
                "interval": "ONE_MINUTE",
                "fromdate": f"{date_str} 09:15",
                "todate": f"{date_str} 15:30",
            }

            try:
                client = await self.get_http_client()
                resp = await client.post(
                    "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    raw = data.get("data") or []
                    if raw and len(raw) > 20:
                        candles = []
                        last_t = -1
                        for row in raw:
                            dt = datetime.fromisoformat(row[0])
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=IST)
                            t = int(dt.timestamp())
                            if t <= last_t:
                                continue
                            candles.append({
                                "time": t,
                                "timestamp": row[0],
                                "open": float(row[1]),
                                "high": float(row[2]),
                                "low": float(row[3]),
                                "close": float(row[4]),
                                "volume": int(row[5]) if len(row) > 5 else 0,
                            })
                            last_t = t
                        return candles
            except Exception as exc:
                logger.warning("Replay candles fetch error for %s on %s: %s", sym_norm, date_str, exc)

        # Do not label generated prices as real historical data.
        if self.is_configured() or not settings.ALLOW_SIMULATED_TRADING:
            return []
        return self._generate_simulated_day_candles(sym_norm, date_str)

    def _generate_simulated_day_candles(self, symbol: str, date_str: str) -> list[dict[str, Any]]:
        """Generate high-fidelity 375 one-minute candles for a specific market day (09:15 to 15:30)."""
        spec = INDEX_CONFIG.get(symbol, INDEX_CONFIG["NIFTY"])
        base_spot = spec["default_spot"]

        # Parse date
        try:
            day_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=IST)
        except ValueError:
            day_dt = datetime.now(tz=IST).replace(hour=0, minute=0, second=0, microsecond=0)

        start_dt = day_dt.replace(hour=9, minute=15, second=0)
        start_ts = int(start_dt.timestamp())

        candles: list[dict[str, Any]] = []
        cur_price = base_spot

        for i in range(375):
            t = start_ts + (i * 60)
            candle_dt = datetime.fromtimestamp(t, tz=IST)
            ts_str = candle_dt.isoformat()

            # Subtle wave + random walk
            step_drift = math.sin(i * 0.05) * 4.0
            noise = random.gauss(0.0, base_spot * 0.0003)
            o = round(cur_price, 2)
            c = round(cur_price + step_drift * 0.1 + noise, 2)
            h = round(max(o, c) + abs(noise) * 0.5 + 1.5, 2)
            l = round(min(o, c) - abs(noise) * 0.5 - 1.5, 2)
            vol = int(random.randint(1500, 20000))

            candles.append({
                "time": t,
                "timestamp": ts_str,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
            })
            cur_price = c

        return candles

    # ── Expiries ─────────────────────────────────────────────────────────────

    # ── Expiries ─────────────────────────────────────────────────────────────

    async def ensure_contracts(self) -> bool:
        """Make sure the real contract table is loaded, and sync lot sizes into INDEX_CONFIG."""
        ok = await scrip_master.ensure_loaded()
        if ok:
            for name, spec in INDEX_CONFIG.items():
                lot = scrip_master.lot_size(name)
                if lot and lot != spec.get("lot_size"):
                    logger.info("Lot size for %s updated from scrip master: %s -> %s", name, spec.get("lot_size"), lot)
                    spec["lot_size"] = lot
        return ok

    def _rule_based_expiries(self, sym_norm: str) -> list[dict[str, Any]]:
        """Fallback only (used when the scrip master is unavailable): weekday-rule expiries."""
        today = datetime.now(tz=IST).date()
        weekday = {"BANKNIFTY": 1, "FINNIFTY": 1, "SENSEX": 3}.get(sym_norm, 1)  # Tue; SENSEX Thu
        expiries: list[dict[str, Any]] = []
        d = today
        while len(expiries) < 6:
            if d.weekday() == weekday:
                is_monthly = (d + timedelta(days=7)).month != d.month
                expiries.append({
                    "date": d.strftime("%Y-%m-%d"),
                    "label": d.strftime("%d-%b-%Y"),
                    "is_nearest": len(expiries) == 0,
                    "type": "Monthly" if is_monthly else "Weekly",
                })
            d += timedelta(days=1)
        return expiries

    def get_expiries(self, symbol: str = "NIFTY") -> list[dict[str, Any]]:
        """Upcoming expiries - the real exchange list when the scrip master is loaded."""
        sym_norm = normalize_index_symbol(symbol)
        real = scrip_master.expiries(sym_norm)[:6]
        if not real:
            return self._rule_based_expiries(sym_norm)
        out: list[dict[str, Any]] = []
        all_exp = scrip_master.expiries(sym_norm)
        for i, iso in enumerate(real):
            d = datetime.strptime(iso, "%Y-%m-%d").date()
            later_same_month = any(e[:7] == iso[:7] and e > iso for e in all_exp)
            out.append({
                "date": iso,
                "label": d.strftime("%d-%b-%Y"),
                "is_nearest": i == 0,
                "type": "Weekly" if later_same_month else "Monthly",
            })
        return out

    # ── Real option quotes ───────────────────────────────────────────────────

    def _pick_contract(self, symbol: str, underlying: str, strike: float, opt: str) -> Optional[Contract]:
        return scrip_master.resolve(symbol, normalize_index_symbol(underlying), strike, opt.upper())

    @staticmethod
    def _parse_exchange_quote_time(item: dict[str, Any]) -> Optional[datetime]:
        """Parse SmartAPI FULL quote exchange feed/trade timestamp if present."""
        raw = item.get("exchFeedTime") or item.get("exchTradeTime")
        if not raw or not isinstance(raw, str):
            return None
        s = raw.strip()
        for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=IST)
            except ValueError:
                continue
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)
        except ValueError:
            return None

    def _is_quote_valid_and_fresh(
        self, token: str, item: Optional[dict[str, Any]], max_age_seconds: float = 15.0
    ) -> tuple[bool, Optional[datetime], Optional[float]]:
        """Validate finite positive LTP, local cache age, and exchange timestamp when present."""
        if not item:
            return False, None, None
        try:
            ltp = float(item.get("ltp") or 0)
        except (TypeError, ValueError):
            return False, None, None
        if not math.isfinite(ltp) or ltp <= 0:
            return False, None, None
        hit = self._tok_cache.get(token)
        age_sec: Optional[float] = round(max(0.0, time.time() - hit[0]), 2) if hit else None
        if age_sec is not None and age_sec > max_age_seconds:
            return False, None, age_sec
        exch_dt = self._parse_exchange_quote_time(item)
        if exch_dt is not None:
            now_ist = datetime.now(tz=IST)
            from config import is_trading_day
            # Only reject stale exchange timestamps when exchange session is currently active (09:16-15:30 IST).
            if is_trading_day(now_ist) and (9, 16) <= (now_ist.hour, now_ist.minute) < (15, 30):
                exch_age = (now_ist - exch_dt).total_seconds()
                if exch_age > max(60.0, max_age_seconds * 4.0) or exch_age < -60.0:
                    return False, exch_dt, age_sec
        return True, exch_dt, age_sec

    async def get_option_ltps(self, legs: list[dict[str, Any]]) -> dict[str, float]:
        """Live LTP for open positions/orders. Returns {leg['symbol']: ltp}; unresolved legs are omitted."""
        if not legs or not scrip_master.is_loaded:
            return {}
        pairs: dict[str, Contract] = {}
        for leg in legs:
            c = self._pick_contract(leg["symbol"], leg["underlying"], leg["strike"], leg["option_type"])
            if c:
                pairs[leg["symbol"]] = c
        if not pairs:
            return {}
        quotes = await self.get_token_quotes(
            list({(c.exchange, c.token) for c in pairs.values()}), ttl=3.0
        )
        out: dict[str, float] = {}
        for sym, c in pairs.items():
            q = quotes.get(c.token)
            ok, _, _ = self._is_quote_valid_and_fresh(c.token, q, max_age_seconds=10.0)
            if ok and q:
                out[sym] = round(float(q["ltp"]), 2)
        return out

    async def get_option_quote(
        self, underlying: str, strike: float, option_type: str, expiry: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """Fresh live quote (symbol, ltp, bid, ask, lot size) for one contract; None if unavailable/stale."""
        await self.ensure_contracts()
        name = normalize_index_symbol(underlying)
        exps = scrip_master.expiries(name)
        if not exps:
            return None
        if expiry is not None and expiry not in exps:
            return None
        iso = expiry if expiry is not None else exps[0]
        c = scrip_master.contract(name, iso, int(strike), option_type.upper())
        if not c:
            return None
        q = (await self.get_token_quotes([(c.exchange, c.token)], ttl=1.0)).get(c.token)
        ok, exch_dt, age_sec = self._is_quote_valid_and_fresh(c.token, q, max_age_seconds=10.0)
        if not ok or not q:
            return None
        depth = q.get("depth") or {}
        bid = float(((depth.get("buy") or [{}])[0]).get("price") or 0)
        ask = float(((depth.get("sell") or [{}])[0]).get("price") or 0)
        return {
            "symbol": c.symbol,
            "expiry": c.expiry,
            "ltp": round(float(q["ltp"]), 2),
            "bid": round(bid, 2),
            "ask": round(ask, 2),
            "lot_size": c.lot_size,
            "exchange_timestamp": exch_dt.isoformat() if exch_dt else None,
            "quote_age_seconds": age_sec,
        }

    def _oi_change(self, token: str, oi: float) -> float:
        """OI change versus the first OI this server saw today (Angel's quote API has no day-change)."""
        today = datetime.now(tz=IST).date().isoformat()
        base = self._oi_baseline.get(token)
        if not base or base[0] != today:
            self._oi_baseline[token] = (today, oi)
            return 0.0
        return oi - base[1]

    async def _live_chain_rows(
        self,
        sym_norm: str,
        expiry_iso: str,
        spot: float,
        strikes_count: int,
        lot_size: int,
        t_years: float,
    ) -> Optional[list[dict[str, Any]]]:
        """Build option-chain rows from real Angel One quotes. None => fall back to simulation."""
        all_strikes = scrip_master.strikes(sym_norm, expiry_iso)
        if not all_strikes:
            return None
        atm_idx = min(range(len(all_strikes)), key=lambda i: abs(all_strikes[i] - spot))
        lo = max(0, atm_idx - strikes_count)
        hi = min(len(all_strikes), atm_idx + strikes_count + 1)
        wanted = all_strikes[lo:hi]
        atm_strike = all_strikes[atm_idx]

        contracts: dict[tuple[int, str], Contract] = {}
        for k in wanted:
            for ot in ("CE", "PE"):
                c = scrip_master.contract(sym_norm, expiry_iso, k, ot)
                if c:
                    contracts[(k, ot)] = c
        if not contracts:
            return None

        quotes = await self.get_token_quotes(
            [(c.exchange, c.token) for c in contracts.values()], ttl=4.0
        )
        if not quotes:
            return None

        def side(strike: int, ot: str) -> dict[str, Any]:
            c = contracts.get((strike, ot))
            q = quotes.get(c.token) if c else None
            ltp = round(float(q.get("ltp") or 0.0), 2) if q else 0.0
            depth = (q or {}).get("depth") or {}
            bid = float(((depth.get("buy") or [{}])[0]).get("price") or 0.0)
            ask = float(((depth.get("sell") or [{}])[0]).get("price") or 0.0)
            oi = float((q or {}).get("opnInterest") or 0.0)
            vol = int(float((q or {}).get("tradeVolume") or 0))
            net = round(float((q or {}).get("netChange") or 0.0), 2)
            pct = round(float((q or {}).get("percentChange") or 0.0), 2)
            iv = BlackScholesEngine.calculate_implied_volatility(
                spot, strike, t_years, ltp, option_type=ot
            ) if ltp > 0.05 else 0.0
            greeks = BlackScholesEngine.calculate_greeks(
                spot=spot, strike=strike, time_to_expiry_years=t_years,
                iv=max(0.01, iv / 100.0), option_type=ot,
            )
            greeks["price"] = ltp
            greeks["iv"] = round(iv, 2)
            return {
                "symbol": c.symbol if c else f"{sym_norm}{strike}{ot}",
                "token": c.token if c else None,
                "strike": strike,
                "option_type": ot,
                "ltp": ltp,
                "bid": round(bid, 2),
                "ask": round(ask, 2),
                "net_change": net,
                "percent_change": pct,
                "oi": int(oi),
                "oi_change": int(self._oi_change(c.token, oi)) if c else 0,
                "volume": vol,
                "lot_amount": round(ltp * lot_size, 2),
                "greeks": greeks,
            }

        rows = []
        for k in wanted:
            rows.append({
                "strike": k,
                "is_atm": k == atm_strike,
                "lot_size": lot_size,
                "ce": side(k, "CE"),
                "pe": side(k, "PE"),
            })
        # If almost nothing priced, the market feed is not usable
        priced = sum(1 for r in rows if r["ce"]["ltp"] > 0 or r["pe"]["ltp"] > 0)
        return rows if priced >= max(1, len(rows) // 3) else None

    # ── Option Chain ─────────────────────────────────────────────────────────

    def _simulated_rows(
        self, sym_norm: str, spec: dict[str, Any], spot: float, atm_strike: int,
        strikes_count: int, t_years: float, exp_suffix: str,
    ) -> list[dict[str, Any]]:
        """Synthetic Black-Scholes chain used ONLY when live data is unavailable (offline/dev)."""
        step = spec["strike_step"]
        lot_size = spec["lot_size"]
        rows = []
        base_vix = self.vix or 14.5
        for offset in range(-strikes_count, strikes_count + 1):
            strike = atm_strike + (offset * step)
            dist_ratio = abs(spot - strike) / spot
            smile_iv = (base_vix / 100.0) * (1.0 + 0.12 * dist_ratio)
            ce_greeks = BlackScholesEngine.calculate_greeks(
                spot=spot, strike=strike, time_to_expiry_years=t_years, iv=smile_iv, option_type="CE")
            pe_greeks = BlackScholesEngine.calculate_greeks(
                spot=spot, strike=strike, time_to_expiry_years=t_years, iv=smile_iv, option_type="PE")
            ce_ltp, pe_ltp = ce_greeks["price"], pe_greeks["price"]
            tick = spec["tick_size"]
            ce_dist = abs(strike - (spot + step * 2))
            pe_dist = abs(strike - (spot - step * 2))
            ce_oi = int(max(25000, 3500000 - int(ce_dist * 450)))
            pe_oi = int(max(25000, 3200000 - int(pe_dist * 450)))
            ce_vol = int(max(5000, ce_oi * random.uniform(0.35, 0.75)))
            pe_vol = int(max(5000, pe_oi * random.uniform(0.35, 0.75)))
            ce_chg = round((spot - strike) * 0.04 + random.uniform(1.0, 5.0), 2)
            pe_chg = round((strike - spot) * 0.04 - random.uniform(1.0, 5.0), 2)
            rows.append({
                "strike": strike,
                "is_atm": strike == atm_strike,
                "lot_size": lot_size,
                "ce": {
                    "symbol": f"{sym_norm}{exp_suffix}{strike}CE", "strike": strike, "option_type": "CE",
                    "ltp": ce_ltp, "bid": max(0.05, round(ce_ltp - tick, 2)), "ask": round(ce_ltp + tick, 2),
                    "net_change": ce_chg, "percent_change": round((ce_chg / max(ce_ltp, 1.0)) * 100, 2),
                    "oi": ce_oi, "oi_change": int(ce_oi * 0.06), "volume": ce_vol,
                    "lot_amount": round(ce_ltp * lot_size, 2), "greeks": ce_greeks,
                },
                "pe": {
                    "symbol": f"{sym_norm}{exp_suffix}{strike}PE", "strike": strike, "option_type": "PE",
                    "ltp": pe_ltp, "bid": max(0.05, round(pe_ltp - tick, 2)), "ask": round(pe_ltp + tick, 2),
                    "net_change": pe_chg, "percent_change": round((pe_chg / max(pe_ltp, 1.0)) * 100, 2),
                    "oi": pe_oi, "oi_change": int(pe_oi * 0.05), "volume": pe_vol,
                    "lot_amount": round(pe_ltp * lot_size, 2), "greeks": pe_greeks,
                },
            })
        return rows

    async def get_option_chain(
        self,
        symbol: str = "NIFTY",
        strikes_count: int = 10,
        expiry: Optional[str] = None,
        override_spot: Optional[float] = None,
    ) -> dict[str, Any]:
        """Option chain with real Angel One prices/OI when live, Black-Scholes simulation otherwise."""
        sym_norm = normalize_index_symbol(symbol)
        spec = INDEX_CONFIG.get(sym_norm, INDEX_CONFIG["NIFTY"])
        step = spec["strike_step"]

        await self.ensure_contracts()
        lot_size = scrip_master.lot_size(sym_norm) or spec["lot_size"]

        replaying = override_spot is not None and override_spot > 0
        spot = float(override_spot) if replaying else await self.get_spot_price(sym_norm)

        avail_expiries = self.get_expiries(sym_norm)
        selected_expiry = None
        if expiry:
            for exp in avail_expiries:
                if exp["date"] == expiry or exp["label"].lower() == expiry.lower():
                    selected_expiry = exp
                    break
        if expiry and not selected_expiry:
            raise ValueError("Requested expiry is unavailable.")
        if not selected_expiry and avail_expiries:
            selected_expiry = avail_expiries[0]

        # Time to expiry (expiry settles 15:30 IST)
        now_dt = datetime.now(tz=IST)
        t_years = 3.0 / 365.0
        if selected_expiry:
            try:
                exp_dt = datetime.strptime(selected_expiry["date"], "%Y-%m-%d").replace(
                    hour=15, minute=30, tzinfo=IST)
                t_years = max((exp_dt - now_dt).total_seconds(), 3600.0) / (365.0 * 86400.0)
            except ValueError:
                pass

        data_source = "simulated"
        chain_rows: Optional[list[dict[str, Any]]] = None
        atm_strike = int(round(spot / step) * step)

        if not replaying and selected_expiry and scrip_master.is_loaded:
            chain_rows = await self._live_chain_rows(
                sym_norm, selected_expiry["date"], spot, strikes_count, lot_size, t_years)
            if chain_rows:
                data_source = "live"
                atm_strike = next((r["strike"] for r in chain_rows if r["is_atm"]), atm_strike)

        if not chain_rows:
            exp_suffix = selected_expiry["date"].replace("-", "")[2:] if selected_expiry else "261120"
            chain_rows = self._simulated_rows(
                sym_norm, spec, spot, atm_strike, strikes_count, t_years, exp_suffix)

        max_pain_info = calculate_max_pain(chain_rows)
        pcr_info = calculate_pcr(chain_rows)

        return {
            "symbol": sym_norm,
            "name": spec["name"],
            "data_source": data_source,
            "vix": self.vix,
            "spot_price": spot,
            "atm_strike": atm_strike,
            "lot_size": lot_size,
            "strike_step": step,
            "expiry": selected_expiry,
            "available_expiries": avail_expiries,
            "max_pain": max_pain_info["max_pain"],
            "call_oi_wall": max_pain_info["call_oi_wall"],
            "put_oi_wall": max_pain_info["put_oi_wall"],
            "pcr": pcr_info["pcr_oi"],
            "pcr_volume": pcr_info["pcr_vol"],
            "sentiment": pcr_info["sentiment"],
            "total_ce_oi": pcr_info["total_ce_oi"],
            "total_pe_oi": pcr_info["total_pe_oi"],
            "chain": chain_rows,
            "timestamp": now_dt.isoformat(),
        }


# Singleton accessor
angel_service = AngelService.get_instance()
