import asyncio
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from src.shinban_sync.core.logger import logger


def _get_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default

    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning(f"环境变量 {name}={raw!r} 不是有效数字，使用默认值 {default}")
        return default


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default

    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(f"环境变量 {name}={raw!r} 不是有效整数，使用默认值 {default}")
        return default


class AsyncRateLimiter:
    def __init__(self, min_interval_seconds: float):
        self._min_interval_seconds = max(0.0, min_interval_seconds)
        self._lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def wait(self):
        loop = asyncio.get_running_loop()
        async with self._lock:
            now = loop.time()
            delay = self._next_request_at - now
            if delay > 0:
                await asyncio.sleep(delay)
                now = loop.time()

            if self._min_interval_seconds > 0:
                self._next_request_at = max(now, self._next_request_at) + self._min_interval_seconds

    async def defer(self, seconds: float):
        if seconds <= 0:
            return

        loop = asyncio.get_running_loop()
        async with self._lock:
            self._next_request_at = max(self._next_request_at, loop.time() + seconds)


ACG_RIP_MIN_INTERVAL_SECONDS = _get_float_env("ACG_RIP_MIN_INTERVAL_SECONDS", 2.0)
ACG_RIP_RETRY_AFTER_SECONDS = _get_float_env("ACG_RIP_RETRY_AFTER_SECONDS", 30.0)
ACG_RIP_MAX_ATTEMPTS = _get_int_env("ACG_RIP_MAX_ATTEMPTS", 3)

_ACG_RIP_HOSTS = {"acg.rip", "www.acg.rip"}
_ACG_RIP_RATE_LIMITER = AsyncRateLimiter(ACG_RIP_MIN_INTERVAL_SECONDS)
_ACG_RIP_REQUEST_LOCK = asyncio.Lock()


def is_acg_rip_url(url: str) -> bool:
    return urlparse(url).hostname in _ACG_RIP_HOSTS


def _retry_after_seconds(response: httpx.Response) -> float:
    value = response.headers.get("Retry-After")
    if not value:
        return ACG_RIP_RETRY_AFTER_SECONDS

    try:
        return max(0.0, float(value))
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return ACG_RIP_RETRY_AFTER_SECONDS

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo = timezone.utc)

    return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())


async def request_acg_rip(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        max_attempts: int = ACG_RIP_MAX_ATTEMPTS,
        **kwargs
) -> httpx.Response:
    attempts = max(1, max_attempts)

    async with _ACG_RIP_REQUEST_LOCK:
        for attempt in range(1, attempts + 1):
            await _ACG_RIP_RATE_LIMITER.wait()
            response = await client.request(method, url, **kwargs)

            if response.status_code != 429 or attempt >= attempts:
                return response

            wait_seconds = _retry_after_seconds(response)
            logger.warning(
                f"AcgRip 返回 429，等待 {wait_seconds:.1f} 秒后重试 ({attempt}/{attempts}): {url}")
            await response.aclose()
            await _ACG_RIP_RATE_LIMITER.defer(wait_seconds)

    raise RuntimeError("unreachable")
