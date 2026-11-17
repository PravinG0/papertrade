"""
Render Keep-Alive & Self-Ping Service for TradeLab Backend.

Prevents Render Free Tier services from spinning down after 15 minutes of inactivity.
Automatically detects the Render external service URL (via RENDER_EXTERNAL_URL)
and sends an HTTP heartbeat every 10 minutes to reset the inactivity timer.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
from typing import Any, Optional

import httpx

from config import settings

logger = logging.getLogger("tradelab_keep_alive")


class KeepAliveManager:
    """Manages periodic keep-alive pings to keep cloud hosting active 24/7."""

    def __init__(
        self,
        interval_seconds: int = 600,  # 10 minutes (under Render's 15-minute sleep threshold)
    ) -> None:
        self.interval_seconds = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False
        self.last_ping_time: Optional[datetime] = None
        self.last_status_code: Optional[int] = None
        self.total_pings: int = 0
        self.target_url: str = ""

    def _resolve_target_url(self) -> str:
        """Resolve the public URL to ping."""
        # 1. Check Render's auto-injected environment variable
        render_url = os.getenv("RENDER_EXTERNAL_URL") or getattr(settings, "RENDER_EXTERNAL_URL", "")
        if render_url and render_url.strip():
            url = render_url.strip().rstrip("/")
            return f"{url}/api/health"

        # 2. Check explicit KEEP_ALIVE_URL override
        custom_url = os.getenv("KEEP_ALIVE_URL", "")
        if custom_url and custom_url.strip():
            return custom_url.strip()

        # 3. Fallback to local endpoint for local testing
        port = getattr(settings, "PORT", 8000)
        return f"http://127.0.0.1:{port}/api/health"

    async def ping_once(self) -> dict[str, Any]:
        """Perform a single keep-alive ping."""
        target = self._resolve_target_url()
        self.target_url = target
        now_utc = datetime.now(timezone.utc)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(
                    target,
                    headers={"User-Agent": "TradeLab-KeepAlive/2.0 (Render Always-On)"},
                )
                self.last_status_code = res.status_code
                self.last_ping_time = now_utc
                self.total_pings += 1

                logger.info(
                    "[KeepAlive] Heartbeat ping -> %s [Status %d] (Ping #%d)",
                    target,
                    res.status_code,
                    self.total_pings,
                )
                return {
                    "success": True,
                    "target": target,
                    "status_code": res.status_code,
                    "timestamp": now_utc.isoformat(),
                    "total_pings": self.total_pings,
                }
        except Exception as exc:
            self.last_ping_time = now_utc
            logger.warning("[KeepAlive] Heartbeat ping to %s failed: %s", target, exc)
            return {
                "success": False,
                "target": target,
                "error": str(exc),
                "timestamp": now_utc.isoformat(),
            }

    async def _loop(self) -> None:
        """Background loop running every 10 minutes."""
        # Wait 30 seconds after startup before the initial ping
        await asyncio.sleep(30)
        logger.info(
            "[KeepAlive] Service active. Target: %s (Interval: %ds / %dm)",
            self._resolve_target_url(),
            self.interval_seconds,
            self.interval_seconds // 60,
        )

        while self._running:
            try:
                await self.ping_once()
            except Exception as exc:
                logger.error("[KeepAlive] Unexpected error in loop: %s", exc)

            try:
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        """Start the background keep-alive ping loop."""
        if self._running:
            return
        self._running = True
        self.target_url = self._resolve_target_url()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop the background loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("[KeepAlive] Service stopped.")

    def get_status(self) -> dict[str, Any]:
        """Return diagnostic status of the keep-alive monitor."""
        return {
            "enabled": getattr(settings, "ENABLE_KEEP_ALIVE", True),
            "running": self._running,
            "target_url": self._resolve_target_url(),
            "interval_seconds": self.interval_seconds,
            "interval_minutes": self.interval_seconds // 60,
            "last_ping": self.last_ping_time.isoformat() if self.last_ping_time else None,
            "last_status_code": self.last_status_code,
            "total_pings": self.total_pings,
        }


# Global singleton instance
keep_alive_manager = KeepAliveManager(
    interval_seconds=getattr(settings, "KEEP_ALIVE_INTERVAL_SECONDS", 600)
)
