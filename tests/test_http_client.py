import asyncio

import httpx

from scrapers.core.http import ScraperHTTPError, SharedScraperHTTPClient
from scrapers.core.settings import ScraperSettings
from scrapers.core.types import ScrapeRequest


def _settings(**overrides):
    values = {
        "timeout_seconds": 5,
        "max_retries": 1,
        "concurrency_per_source": 1,
        "request_delay_min_ms": 0,
        "request_delay_max_ms": 0,
    }
    values.update(overrides)
    return ScraperSettings(**values)


def test_http_client_retries_transient_errors(monkeypatch):
    calls = 0

    async def no_sleep(_seconds):
        return None

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, request=request)
        return httpx.Response(200, text="ok", request=request)

    monkeypatch.setattr("scrapers.core.http.asyncio.sleep", no_sleep)

    async def run():
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        async with SharedScraperHTTPClient(_settings(), client=async_client) as client:
            response = await client.fetch_text(ScrapeRequest(url="https://example.test"))
        await async_client.aclose()
        return response

    assert asyncio.run(run()) == "ok"
    assert calls == 2


def test_http_client_does_not_retry_404():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(404, request=request)

    async def run():
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            async with SharedScraperHTTPClient(_settings(max_retries=3), client=async_client) as client:
                await client.fetch_text(ScrapeRequest(url="https://example.test/missing"))
        finally:
            await async_client.aclose()

    try:
        asyncio.run(run())
    except ScraperHTTPError as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("expected ScraperHTTPError")
    assert calls == 1


def test_http_client_wraps_final_5xx_as_scraper_error(monkeypatch):
    async def no_sleep(_seconds):
        return None

    def handler(request):
        return httpx.Response(503, request=request)

    monkeypatch.setattr("scrapers.core.http.asyncio.sleep", no_sleep)

    async def run():
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            async with SharedScraperHTTPClient(_settings(max_retries=1), client=async_client) as client:
                await client.fetch_text(ScrapeRequest(url="https://example.test/down"))
        finally:
            await async_client.aclose()

    try:
        asyncio.run(run())
    except ScraperHTTPError as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("expected ScraperHTTPError")
