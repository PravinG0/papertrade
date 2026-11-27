"""Comprehensive tests for AngelService historical candle resilience and DebateEngine gating."""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from angel_service import AngelService
from debate_engine import DebateEngine

IST = ZoneInfo("Asia/Kolkata")


def _make_smartapi_rows(count: int = 30, base_price: float = 25000.0, step_min: int = 5) -> list[list]:
    """Generate recent valid SmartAPI candle rows ending at the latest 5m bar."""
    now = datetime.now(tz=IST).replace(second=0, microsecond=0)
    # If outside market hours, anchor at 15:25 IST today (or previous weekday) so candles are valid session bars
    if now.weekday() >= 5 or (now.hour, now.minute) > (15, 30) or (now.hour, now.minute) < (9, 20):
        anchor = now.replace(hour=15, minute=25)
        while anchor.weekday() >= 5:
            anchor -= timedelta(days=1)
    else:
        anchor = now

    rows = []
    for i in range(count):
        dt = anchor - timedelta(minutes=step_min * (count - 1 - i))
        o = base_price + i * 2.0
        h = o + 10.0
        l = o - 8.0
        c = o + 4.0
        rows.append([dt.strftime("%Y-%m-%dT%H:%M:%S+05:30"), o, h, l, c, 1000 + i * 10])
    return rows


def _configured_service() -> AngelService:
    svc = AngelService()
    svc.api_key = "test-api-key"
    svc.client_code = "TEST123"
    svc.pin = "1234"
    svc.totp_secret = "JBSWY3DPEHPK3PXP"
    svc._jwt_token = "valid-jwt"
    svc._token_expiry_epoch = time.time() + 3600
    svc._candle_min_interval = 0.0  # keep unit tests fast
    return svc


def _mock_response(status_code: int, json_body: dict, headers: dict | None = None) -> httpx.Response:
    req = httpx.Request("POST", "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData")
    return httpx.Response(status_code=status_code, json=json_body, headers=headers or {}, request=req)


@pytest.mark.asyncio
async def test_successful_nifty_and_banknifty_retrieval():
    svc = _configured_service()
    nifty_rows = _make_smartapi_rows(30, 25000.0)
    bnf_rows = _make_smartapi_rows(30, 53000.0)

    async def fake_post(url, json=None, headers=None):
        token = (json or {}).get("symboltoken")
        rows = bnf_rows if token == "99926009" else nifty_rows
        return _mock_response(200, {"status": True, "message": "SUCCESS", "errorcode": "", "data": rows})

    fake_client = SimpleNamespace(post=AsyncMock(side_effect=fake_post))
    with patch.object(svc, "get_http_client", AsyncMock(return_value=fake_client)):
        n_meta = await svc.get_candles_with_meta("NIFTY", "5m", "5d")
        b_meta = await svc.get_candles_with_meta("BANKNIFTY", "5m", "5d")

    assert n_meta["source"] == "live"
    assert len(n_meta["candles"]) == 30
    assert n_meta["last_candle_ist"] is not None
    assert b_meta["source"] == "live"
    assert len(b_meta["candles"]) == 30
    assert b_meta["candles"][-1]["close"] > 50000.0


@pytest.mark.asyncio
@pytest.mark.parametrize("err_code", ["AG8001", "AG8002", "AG8003"])
async def test_token_renewal_on_ag_auth_errors(err_code: str):
    svc = _configured_service()
    rows = _make_smartapi_rows(25, 25100.0)
    calls = {"count": 0}

    async def fake_post(url, json=None, headers=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return _mock_response(200, {"status": False, "errorcode": err_code, "message": "Invalid Token"})
        return _mock_response(200, {"status": True, "message": "SUCCESS", "data": rows})

    fake_client = SimpleNamespace(post=AsyncMock(side_effect=fake_post))
    renew_mock = AsyncMock(side_effect=lambda force_refresh=False: setattr(svc, "_jwt_token", "renewed-jwt") or True)

    with (
        patch.object(svc, "get_http_client", AsyncMock(return_value=fake_client)),
        patch.object(svc, "authenticate", renew_mock),
    ):
        meta = await svc.get_candles_with_meta("NIFTY", "5m", "5d")

    assert meta["source"] == "live"
    assert len(meta["candles"]) == 25
    assert renew_mock.await_count >= 1
    assert any(kwargs.get("force_refresh") is True for _, kwargs in renew_mock.await_args_list)


@pytest.mark.asyncio
async def test_http_401_triggers_automatic_token_renewal():
    svc = _configured_service()
    rows = _make_smartapi_rows(25, 25200.0)
    calls = {"count": 0}

    async def fake_post(url, json=None, headers=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return _mock_response(401, {"status": False, "message": "Unauthorized"})
        return _mock_response(200, {"status": True, "message": "SUCCESS", "data": rows})

    fake_client = SimpleNamespace(post=AsyncMock(side_effect=fake_post))
    renew_mock = AsyncMock(side_effect=lambda force_refresh=False: setattr(svc, "_jwt_token", "fresh-jwt") or True)

    with (
        patch.object(svc, "get_http_client", AsyncMock(return_value=fake_client)),
        patch.object(svc, "authenticate", renew_mock),
    ):
        meta = await svc.get_candles_with_meta("NIFTY", "5m", "5d")

    assert meta["source"] == "live"
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_http_403_and_429_retry_after_cooldown():
    svc = _configured_service()
    fake_client_429 = SimpleNamespace(
        post=AsyncMock(return_value=_mock_response(429, {"status": False, "message": "Too Many Requests"}, {"Retry-After": "15"}))
    )

    with patch.object(svc, "get_http_client", AsyncMock(return_value=fake_client_429)):
        meta = await svc.get_candles_with_meta("NIFTY", "5m", "5d")

    assert meta["source"] == "unavailable"
    assert meta["candles"] == []
    assert meta["error_code"] == "HTTP_429"
    assert svc._candle_cooldown_until > time.time() + 10.0

    # Subsequent call during cooldown should NOT hit broker HTTP client
    fake_client_429.post.reset_mock()
    with patch.object(svc, "get_http_client", AsyncMock(return_value=fake_client_429)):
        meta2 = await svc.get_candles_with_meta("NIFTY", "5m", "5d")

    assert meta2["error_code"] == "RATE_LIMIT_COOLDOWN"
    assert fake_client_429.post.await_count == 0

    # Reset and test HTTP 403
    svc._candle_cooldown_until = 0.0
    fake_client_403 = SimpleNamespace(
        post=AsyncMock(return_value=_mock_response(403, {"status": False, "message": "Access denied / rate limit"}))
    )
    with patch.object(svc, "get_http_client", AsyncMock(return_value=fake_client_403)):
        meta403 = await svc.get_candles_with_meta("BANKNIFTY", "5m", "5d")

    assert meta403["source"] == "unavailable"
    assert meta403["error_code"] == "HTTP_403"


@pytest.mark.asyncio
async def test_network_timeout_retries_and_fails_gracefully():
    svc = _configured_service()
    fake_client = SimpleNamespace(post=AsyncMock(side_effect=httpx.ReadTimeout("timed out")))

    with (
        patch.object(svc, "get_http_client", AsyncMock(return_value=fake_client)),
        patch("angel_service.asyncio.sleep", AsyncMock()),
    ):
        meta = await svc.get_candles_with_meta("NIFTY", "5m", "5d")

    assert fake_client.post.await_count == 3
    assert meta["source"] == "unavailable"
    assert "ReadTimeout" in (meta["error_code"] or "")
    assert "timeout" in (meta["reason"] or "").lower()


@pytest.mark.asyncio
async def test_empty_and_invalid_candle_validation():
    svc = _configured_service()

    # Empty data
    empty_client = SimpleNamespace(post=AsyncMock(return_value=_mock_response(200, {"status": True, "data": []})))
    with patch.object(svc, "get_http_client", AsyncMock(return_value=empty_client)):
        empty_meta = await svc.get_candles_with_meta("NIFTY", "5m", "5d")
    assert empty_meta["source"] == "unavailable"
    assert empty_meta["error_code"] == "EMPTY_CANDLES"

    # Mixed invalid + out-of-order + duplicate rows
    valid_rows = _make_smartapi_rows(22, 25000.0)
    bad_and_mixed = [
        valid_rows[5],  # out of order
        ["bad-ts", 100, 110, 90, 105, 10],
        [valid_rows[0][0], -5, 10, 1, 5, 10],  # negative open
        [valid_rows[1][0], 100, 90, 110, 105, 10],  # high < low
        valid_rows[5],  # duplicate timestamp
    ] + valid_rows
    parsed = svc._parse_and_validate_candles(bad_and_mixed)
    assert len(parsed) == 22
    times = [c["time"] for c in parsed]
    assert times == sorted(set(times))


@pytest.mark.asyncio
async def test_concurrent_identical_requests_deduplicated():
    svc = _configured_service()
    rows = _make_smartapi_rows(25, 25000.0)

    async def slow_post(url, json=None, headers=None):
        await asyncio.sleep(0.05)
        return _mock_response(200, {"status": True, "data": rows})

    fake_client = SimpleNamespace(post=AsyncMock(side_effect=slow_post))
    with patch.object(svc, "get_http_client", AsyncMock(return_value=fake_client)):
        results = await asyncio.gather(
            svc.get_candles_with_meta("NIFTY", "5m", "5d"),
            svc.get_candles_with_meta("NIFTY", "5m", "5d"),
            svc.get_candles_with_meta("NIFTY", "5m", "5d"),
        )

    assert fake_client.post.await_count == 1
    assert all(len(r["candles"]) == 25 for r in results)


@pytest.mark.asyncio
async def test_cache_expiration_and_incremental_merge():
    svc = _configured_service()
    assert svc._candle_ttl("FIVE_MINUTE") == 60.0
    assert svc._candle_ttl("FIFTEEN_MINUTE") == 300.0
    assert svc._candle_ttl("ONE_DAY") == 1800.0

    rows = _make_smartapi_rows(25, 25000.0)
    fake_client = SimpleNamespace(post=AsyncMock(return_value=_mock_response(200, {"status": True, "data": rows})))

    with patch.object(svc, "get_http_client", AsyncMock(return_value=fake_client)):
        first = await svc.get_candles_with_meta("NIFTY", "5m", "5d")
        second = await svc.get_candles_with_meta("NIFTY", "5m", "5d")

    assert first["source"] == "live"
    assert second["source"] == "cached"
    assert fake_client.post.await_count == 1

    # Expire cache and verify incremental merge adds new bar without duplicating prior bars
    cache_key = "NSE_99926000_FIVE_MINUTE_5d"
    svc._candle_cache[cache_key] = (time.time() - 120.0, svc._candle_cache[cache_key][1])
    next_dt = datetime.fromtimestamp(svc._last_valid_candles[cache_key][1][-1]["time"], tz=IST) + timedelta(minutes=5)
    new_tail = [rows[-1], [next_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30"), 25100, 25120, 25090, 25115, 1500]]
    fake_client.post.return_value = _mock_response(200, {"status": True, "data": new_tail})

    with patch.object(svc, "get_http_client", AsyncMock(return_value=fake_client)):
        third = await svc.get_candles_with_meta("NIFTY", "5m", "5d")

    assert third["source"] == "live"
    assert len(third["candles"]) == 26
    assert third["candles"][-1]["close"] == 25115.0


@pytest.mark.asyncio
async def test_debate_engine_blocks_stale_and_insufficient_candles():
    engine = DebateEngine()

    stale_meta = {
        "candles": [{"time": int(time.time()) - 7200, "open": 25000, "high": 25010, "low": 24990, "close": 25005, "volume": 100}] * 25,
        "source": "stale",
        "last_candle_ist": "2026-11-26 11:00 IST",
        "reason": "Angel One historical API cooldown active (12s remaining).",
    }
    with (
        patch("debate_engine.angel_service.get_spot_indices", AsyncMock(return_value=[{"symbol": "NIFTY", "ltp": 25005.0, "source": "live"}])),
        patch("debate_engine.angel_service.is_configured", return_value=True),
        patch("debate_engine.angel_service.get_candles_with_meta", AsyncMock(return_value=stale_meta)),
    ):
        with pytest.raises(ValueError, match="cooldown active"):
            await engine.build_snapshot("NIFTY")

    # Fewer than 50 candles must be rejected cleanly
    short_meta = {
        "candles": [{"time": int(time.time()) - 300 * i, "open": 25000, "high": 25010, "low": 24990, "close": 25005, "volume": 100} for i in range(10, 0, -1)],
        "source": "live",
        "last_candle_ist": "2026-11-26 15:25 IST",
        "reason": None,
    }
    with (
        patch("debate_engine.angel_service.get_spot_indices", AsyncMock(return_value=[{"symbol": "NIFTY", "ltp": 25005.0, "source": "live"}])),
        patch("debate_engine.angel_service.is_configured", return_value=True),
        patch("debate_engine.angel_service.get_candles_with_meta", AsyncMock(return_value=short_meta)),
    ):
        with pytest.raises(ValueError, match="minimum 50 required"):
            await engine.build_snapshot("NIFTY")
