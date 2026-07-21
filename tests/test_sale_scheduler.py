import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from scrapers.core.http import SharedScraperHTTPClient
from scrapers.core.providers import ProviderCapabilities, RealEstateProvider
from scrapers.core.sale_scope import SaleScrapeScope
from scrapers.core.scheduler import InMemoryLockManager, SaleScheduler, run_health_check
from scrapers.core.settings import SaleSchedulerSettings, ScraperSettings
from scrapers.core.types import ListingPage, PropertyCandidate, ScrapeRequest


class FakeProvider(RealEstateProvider):
    source_name = "Fake"
    base_url = "https://fake.test"
    default_search_scope = {"purpose": "sale"}

    def __init__(self, key: str, capabilities: ProviderCapabilities | None = None):
        self.source_key = key
        self.capabilities = capabilities or ProviderCapabilities(supports_neighborhood_scope=False)

    def build_search_request(self, page: int, search_scope: dict | None = None) -> ScrapeRequest:
        return ScrapeRequest(url=f"{self.base_url}/{self.source_key}/sale/page/{page}")

    def parse_listing_page(self, html: str, page: int, search_scope: dict | None = None) -> ListingPage:
        if "card" not in html:
            return ListingPage(candidates=[], raw_cards_count=0)
        return ListingPage(
            candidates=[
                PropertyCandidate(
                    source_key=self.source_key,
                    external_id=f"{self.source_key}-1",
                    source_url=f"{self.base_url}/{self.source_key}-1",
                )
            ],
            raw_cards_count=1,
            invalid_cards_count=0,
            canonical_url=f"{self.base_url}/{self.source_key}/sale",
        )


class DummySessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return None


def dummy_session_factory():
    return DummySessionContext()


def scheduler_settings(**overrides):
    values = {
        "timezone": "America/Sao_Paulo",
        "full_crawl_hour": 3,
        "full_crawl_source_offset_minutes": 15,
        "full_crawl_jitter_minutes": 0,
        "priority_crawl_hours": [2, 6, 10, 14, 18, 22],
        "priority_source_offset_minutes": 10,
        "priority_jitter_minutes": 0,
        "health_check_interval_minutes": 60,
        "health_check_source_offset_minutes": 5,
        "health_check_jitter_minutes": 0,
        "loop_poll_seconds": 1,
        "alert_cooldown_minutes": 60,
    }
    values.update(overrides)
    return SaleSchedulerSettings(**values)


def scraper_settings():
    return ScraperSettings(
        timeout_seconds=5,
        max_retries=0,
        concurrency_per_source=1,
        request_delay_min_ms=0,
        request_delay_max_ms=0,
    )


def test_sale_scheduler_uses_sao_paulo_timezone_and_full_offsets():
    now = datetime(2026, 7, 21, 1, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
    providers = [FakeProvider("zimoveis"), FakeProvider("localimoveis"), FakeProvider("pacheco")]
    scheduler = SaleScheduler(providers, settings=scheduler_settings(), scraper_settings=scraper_settings())

    jobs = {job.id: job for job in scheduler.register_schedules(now)}

    assert jobs["sale_full_crawl:localimoveis"].next_run_at.isoformat() == "2026-07-21T03:00:00-03:00"
    assert jobs["sale_full_crawl:pacheco"].next_run_at.isoformat() == "2026-07-21T03:15:00-03:00"
    assert jobs["sale_full_crawl:zimoveis"].next_run_at.isoformat() == "2026-07-21T03:30:00-03:00"
    assert jobs["sale_full_crawl:pacheco"].timezone == "America/Sao_Paulo"


def test_priority_schedule_only_runs_for_neighborhood_capable_providers():
    now = datetime(2026, 7, 21, 1, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
    regional = FakeProvider("regional", ProviderCapabilities(supports_neighborhood_scope=True))
    city_only = FakeProvider("cityonly", ProviderCapabilities(supports_neighborhood_scope=False))
    scheduler = SaleScheduler([regional, city_only], settings=scheduler_settings(), scraper_settings=scraper_settings())

    jobs = {job.id: job for job in scheduler.register_schedules(now)}

    regional_priority_jobs = [
        job for job in jobs.values() if job.id.startswith("sale_priority_crawl:regional:")
    ]
    assert len(regional_priority_jobs) == 6
    assert jobs["sale_priority_crawl:regional:pinheiros"].enabled is True
    assert jobs["sale_priority_crawl:regional:pinheiros"].next_run_at.isoformat() == "2026-07-21T02:10:00-03:00"
    assert jobs["sale_priority_crawl:regional:vila-madalena"].scope["neighborhoods"] == [
        {"name": "Vila Madalena", "slug": "vila-madalena"}
    ]
    assert jobs["sale_priority_crawl:cityonly"].enabled is False
    assert jobs["sale_priority_crawl:cityonly"].last_result["reason"] == "neighborhood_scope_not_supported"


def test_health_check_is_hourly_with_source_offsets():
    now = datetime(2026, 7, 21, 1, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
    scheduler = SaleScheduler(
        [FakeProvider("a"), FakeProvider("b")],
        settings=scheduler_settings(),
        scraper_settings=scraper_settings(),
    )

    jobs = {job.id: job for job in scheduler.register_schedules(now)}

    assert jobs["sale_health_check:a"].next_run_at.isoformat() == "2026-07-21T02:00:00-03:00"
    assert jobs["sale_health_check:b"].next_run_at.isoformat() == "2026-07-21T01:05:00-03:00"


def test_jitter_is_within_configured_limit():
    now = datetime(2026, 7, 21, 1, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
    seen_limits = []

    def jitter(_job_id, max_minutes):
        seen_limits.append(max_minutes)
        return max_minutes

    scheduler = SaleScheduler(
        [FakeProvider("a")],
        settings=scheduler_settings(full_crawl_jitter_minutes=7),
        scraper_settings=scraper_settings(),
        jitter_func=jitter,
    )

    jobs = {job.id: job for job in scheduler.register_schedules(now)}

    assert jobs["sale_full_crawl:a"].next_run_at.isoformat() == "2026-07-21T03:07:00-03:00"
    assert 7 in seen_limits


def test_restart_recalculates_same_schedule_ids_without_duplicates():
    now = datetime(2026, 7, 21, 1, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
    scheduler = SaleScheduler([FakeProvider("a")], settings=scheduler_settings(), scraper_settings=scraper_settings())

    first = [job.id for job in scheduler.register_schedules(now)]
    second = [job.id for job in scheduler.register_schedules(now)]

    assert first == second
    assert len(second) == len(set(second))


def test_due_window_uses_recent_scheduled_occurrence_for_stateless_cron():
    now = datetime(2026, 7, 21, 3, 5, tzinfo=ZoneInfo("America/Sao_Paulo"))
    scheduler = SaleScheduler(
        [FakeProvider("a")],
        settings=scheduler_settings(full_crawl_jitter_minutes=0),
        scraper_settings=scraper_settings(),
    )

    jobs = {job.id: job for job in scheduler.register_schedules(now, due_window=True)}

    assert jobs["sale_full_crawl:a"].next_run_at.isoformat() == "2026-07-21T03:00:00-03:00"


def test_due_window_moves_to_next_run_after_misfire_grace():
    now = datetime(2026, 7, 21, 3, 45, tzinfo=ZoneInfo("America/Sao_Paulo"))
    scheduler = SaleScheduler(
        [FakeProvider("a")],
        settings=scheduler_settings(full_crawl_jitter_minutes=0, misfire_grace_minutes=30),
        scraper_settings=scraper_settings(),
    )

    jobs = {job.id: job for job in scheduler.register_schedules(now, due_window=True)}

    assert jobs["sale_full_crawl:a"].next_run_at.isoformat() == "2026-07-22T03:00:00-03:00"


def test_full_lock_blocks_priority_job():
    provider = FakeProvider("regional", ProviderCapabilities(supports_neighborhood_scope=True))
    scheduler = SaleScheduler(
        [provider],
        settings=scheduler_settings(),
        scraper_settings=scraper_settings(),
        session_factory=dummy_session_factory,
        lock_manager=InMemoryLockManager(),
    )
    job = [item for item in scheduler.register_schedules() if item.id == "sale_priority_crawl:regional:pinheiros"][0]

    async def run():
        await scheduler.lock_manager.acquire(None, "regional:sale:full_city:sao-paulo")
        return await scheduler.run_job(job)

    result = asyncio.run(run())

    assert result["result"] == "skipped"
    assert result["reason"] == "full_city_job_already_running"


def test_equivalent_lock_blocks_duplicate_job():
    provider = FakeProvider("regional", ProviderCapabilities(supports_neighborhood_scope=True))
    scheduler = SaleScheduler(
        [provider],
        settings=scheduler_settings(),
        scraper_settings=scraper_settings(),
        session_factory=dummy_session_factory,
        lock_manager=InMemoryLockManager(),
    )
    job = [item for item in scheduler.register_schedules() if item.id == "sale_full_crawl:regional"][0]

    async def run():
        await scheduler.lock_manager.acquire(None, "regional:sale:any:sao-paulo")
        return await scheduler.run_job(job)

    result = asyncio.run(run())

    assert result["result"] == "skipped"
    assert result["reason"] == "equivalent_job_already_running"


def test_health_check_parses_first_page_without_persisting_properties():
    provider = FakeProvider("health")

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html; charset=UTF-8"}, text="<html>card</html>", request=request)

    async def run():
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            client = SharedScraperHTTPClient(scraper_settings(), client=async_client)
            return await run_health_check(provider, scraper_settings(), SaleScrapeScope.full_city().as_dict(), client)
        finally:
            await async_client.aclose()

    result = asyncio.run(run())

    assert result.status == "HEALTHY"
    assert result.cards == 1
    assert result.http_status == 200


def test_health_check_detects_blocking_status():
    provider = FakeProvider("blocked")

    def handler(request):
        return httpx.Response(403, text="Access denied", request=request)

    async def run():
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            client = SharedScraperHTTPClient(scraper_settings(), client=async_client)
            return await run_health_check(provider, scraper_settings(), SaleScrapeScope.full_city().as_dict(), client)
        finally:
            await async_client.aclose()

    result = asyncio.run(run())

    assert result.status == "BLOCKED"
    assert result.http_status == 403
