from __future__ import annotations

import asyncio
import logging
import random
from email.utils import parsedate_to_datetime
from time import time
from typing import Mapping

import httpx

from .settings import ScraperSettings
from .types import ScrapeRequest

logger = logging.getLogger(__name__)


class ScraperHTTPError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class SharedScraperHTTPClient:
    def __init__(
        self,
        settings: ScraperSettings,
        client: httpx.AsyncClient | None = None,
        provider_headers: Mapping[str, str] | None = None,
    ):
        self.settings = settings
        self._external_client = client
        self._client = client
        self._semaphore = asyncio.Semaphore(max(1, settings.concurrency_per_source))
        self._provider_headers = dict(provider_headers or {})

    async def __aenter__(self) -> "SharedScraperHTTPClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.timeout_seconds),
                follow_redirects=True,
                headers=self._base_headers(),
            )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None and self._external_client is None:
            await self._client.aclose()
        self._client = None

    def _base_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.7,en;q=0.6",
            **self._provider_headers,
        }

    async def fetch_text(self, request: ScrapeRequest) -> str:
        response = await self.request(request)
        return response.text

    async def request(self, request: ScrapeRequest) -> httpx.Response:
        if self._client is None:
            raise RuntimeError("SharedScraperHTTPClient must be used as an async context manager")

        async with self._semaphore:
            await self._delay()
            return await self._request_with_retries(request)

    async def _request_with_retries(self, request: ScrapeRequest) -> httpx.Response:
        attempts = max(1, self.settings.max_retries + 1)
        last_exc: Exception | None = None

        for attempt in range(attempts):
            try:
                assert self._client is not None
                response = await self._client.request(
                    request.method,
                    request.url,
                    params=request.params,
                    headers=request.headers or None,
                )
                if response.status_code in {403, 404}:
                    raise ScraperHTTPError(
                        f"non-retryable HTTP {response.status_code}",
                        status_code=response.status_code,
                        url=str(response.url),
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < attempts - 1:
                        await self._backoff(attempt, response)
                        continue
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, ScraperHTTPError) as exc:
                last_exc = exc
                status_code = getattr(exc, "status_code", None)
                if isinstance(exc, httpx.HTTPStatusError):
                    status_code = exc.response.status_code
                if status_code in {403, 404} or attempt >= attempts - 1:
                    logger.warning("scraper request failed url=%s status=%s", request.url, status_code)
                    raise
                await self._backoff(attempt)

        raise ScraperHTTPError(f"request failed after {attempts} attempts: {last_exc}", url=request.url)

    async def _delay(self) -> None:
        min_ms = max(0, self.settings.request_delay_min_ms)
        max_ms = max(min_ms, self.settings.request_delay_max_ms)
        if max_ms <= 0:
            return
        await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)

    async def _backoff(self, attempt: int, response: httpx.Response | None = None) -> None:
        retry_after = self._retry_after_seconds(response)
        if retry_after is not None:
            await asyncio.sleep(retry_after)
            return
        base = min(30.0, 0.5 * (2**attempt))
        await asyncio.sleep(base + random.uniform(0, 0.3))

    def _retry_after_seconds(self, response: httpx.Response | None) -> float | None:
        if response is None:
            return None
        value = response.headers.get("Retry-After")
        if not value:
            return None
        if value.isdigit():
            return float(value)
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, retry_at.timestamp() - time())
