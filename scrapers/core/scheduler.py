from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from backend.app.db.models import JobLog, Source
from backend.app.db.session import AsyncSessionLocal
from scrapers.core.engine import SyncEngine
from scrapers.core.http import ScraperHTTPError, SharedScraperHTTPClient
from scrapers.core.persistence import PropertyRepository
from scrapers.core.providers import RealEstateProvider
from scrapers.core.registry import load_provider, registered_provider_keys
from scrapers.core.sale_scope import SALE_PRIORITY_NEIGHBORHOODS, SaleScrapeScope
from scrapers.core.settings import SaleSchedulerSettings, ScraperSettings, load_sale_scheduler_settings, load_scraper_settings
from scrapers.core.types import SyncStats

logger = logging.getLogger(__name__)


ScheduleJobType = Literal["sale_health_check", "sale_priority_crawl", "sale_full_crawl"]
HealthStatus = Literal["HEALTHY", "DEGRADED", "FAILED", "BLOCKED", "STRUCTURE_CHANGED"]
PRIORITY_NEIGHBORHOOD_OFFSET_MINUTES = 2


@dataclass
class ScheduleJob:
    id: str
    job_type: ScheduleJobType
    source_key: str
    purpose: Literal["sale"]
    scope: dict[str, Any]
    timezone: str
    next_run_at: datetime | None
    enabled: bool = True
    status: str = "scheduled"
    last_run_at: datetime | None = None
    last_result: dict[str, Any] | None = None
    dedupe_occurrence: bool = False

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.next_run_at:
            data["next_run_at"] = self.next_run_at.isoformat()
        if self.last_run_at:
            data["last_run_at"] = self.last_run_at.isoformat()
        return data


@dataclass
class HealthCheckResult:
    status: HealthStatus
    provider_key: str
    url: str
    final_url: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    cards: int = 0
    invalid_cards: int = 0
    response_time_ms: int | None = None
    canonical_url: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class InMemoryLockManager:
    def __init__(self):
        self._locks: set[str] = set()

    async def acquire(self, _session, key: str) -> bool:
        if key in self._locks:
            return False
        self._locks.add(key)
        return True

    async def release(self, _session, key: str) -> None:
        self._locks.discard(key)

    async def is_locked(self, _session, key: str) -> bool:
        return key in self._locks


class PostgresAdvisoryLockManager:
    async def acquire(self, session, key: str) -> bool:
        result = await session.execute(text("SELECT pg_try_advisory_lock(hashtext(:key), 0)"), {"key": key})
        return bool(result.scalar())

    async def release(self, session, key: str) -> None:
        await session.execute(text("SELECT pg_advisory_unlock(hashtext(:key), 0)"), {"key": key})

    async def is_locked(self, session, key: str) -> bool:
        acquired = await self.acquire(session, key)
        if acquired:
            await self.release(session, key)
            return False
        return True


class StructuredAlertSink:
    def __init__(self, cooldown_minutes: int):
        self.cooldown = timedelta(minutes=max(0, cooldown_minutes))
        self._last_alert_at: dict[str, datetime] = {}

    def emit(self, key: str, event: str, payload: dict[str, Any], now: datetime) -> bool:
        previous = self._last_alert_at.get(key)
        if previous and now - previous < self.cooldown:
            return False
        self._last_alert_at[key] = now
        logger.warning("scraper_alert", extra={"event": event, **payload})
        return True


def _aware_now(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def _jitter(job_id: str, max_minutes: int) -> int:
    max_minutes = max(0, max_minutes)
    if max_minutes <= 0:
        return 0
    digest = hashlib.sha256(job_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % (max_minutes + 1)


def _next_daily(now: datetime, hour: int, offset_minutes: int, jitter_minutes: int) -> datetime:
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    candidate += timedelta(minutes=offset_minutes + jitter_minutes)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _previous_daily(now: datetime, hour: int, offset_minutes: int, jitter_minutes: int) -> datetime:
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    candidate += timedelta(minutes=offset_minutes + jitter_minutes)
    if candidate > now:
        candidate -= timedelta(days=1)
    return candidate


def _next_from_hours(now: datetime, hours: list[int], offset_minutes: int, jitter_minutes: int) -> datetime:
    if not hours:
        return _next_daily(now, 2, offset_minutes, jitter_minutes)
    for day_offset in (0, 1):
        for hour in sorted({hour % 24 for hour in hours}):
            candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            candidate += timedelta(days=day_offset, minutes=offset_minutes + jitter_minutes)
            if candidate > now:
                return candidate
    return now + timedelta(hours=4, minutes=offset_minutes + jitter_minutes)


def _previous_from_hours(now: datetime, hours: list[int], offset_minutes: int, jitter_minutes: int) -> datetime:
    normalized_hours = sorted({hour % 24 for hour in hours}) or [2]
    candidates = []
    for day_offset in (0, -1):
        for hour in normalized_hours:
            candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            candidate += timedelta(days=day_offset, minutes=offset_minutes + jitter_minutes)
            if candidate <= now:
                candidates.append(candidate)
    return max(candidates) if candidates else now - timedelta(days=1)


def _next_interval(now: datetime, interval_minutes: int, offset_minutes: int, jitter_minutes: int) -> datetime:
    interval = max(1, interval_minutes)
    anchor = now.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=offset_minutes)
    while anchor <= now:
        anchor += timedelta(minutes=interval)
    return anchor + timedelta(minutes=jitter_minutes)


def _previous_interval(now: datetime, interval_minutes: int, offset_minutes: int, jitter_minutes: int) -> datetime:
    interval = max(1, interval_minutes)
    anchor = now.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=offset_minutes + jitter_minutes)
    while anchor > now:
        anchor -= timedelta(minutes=interval)
    while anchor + timedelta(minutes=interval) <= now:
        anchor += timedelta(minutes=interval)
    return anchor


def _source_lock_key(source_key: str) -> str:
    return f"{source_key}:sale:any:sao-paulo"


def _scope_lock_key(source_key: str, scope_type: str) -> str:
    return f"{source_key}:sale:{scope_type}:sao-paulo"


def sale_scraper_settings(base: ScraperSettings, sale: SaleSchedulerSettings) -> ScraperSettings:
    return ScraperSettings(
        user_agent=base.user_agent,
        timeout_seconds=base.timeout_seconds,
        max_retries=base.max_retries,
        concurrency_per_source=min(max(1, base.concurrency_per_source), 2),
        request_delay_min_ms=base.request_delay_min_ms,
        request_delay_max_ms=base.request_delay_max_ms,
        missing_threshold=sale.missing_runs_before_removal,
        removal_after_hours=base.removal_after_hours,
        detail_ttl_hours=sale.detail_refresh_days * 24,
        delta_stale_pages=base.delta_stale_pages,
        max_invalid_card_rate=base.max_invalid_card_rate,
        full_min_listing_ratio=sale.minimum_inventory_ratio,
        max_pages=base.max_pages,
        dry_run=base.dry_run,
    )


async def load_enabled_sale_providers(session) -> list[RealEstateProvider]:
    result = await session.execute(select(Source).where(Source.enabled.is_(True)))
    providers: list[RealEstateProvider] = []
    for source in sorted(result.scalars().all(), key=lambda item: item.key or ""):
        if not source.key or source.key not in registered_provider_keys():
            continue
        provider = load_provider(source.key)
        if provider and provider.capabilities.supports_sale:
            providers.append(provider)
    return providers


async def run_health_check(
    provider: RealEstateProvider,
    settings: ScraperSettings,
    scope: dict[str, Any],
    http_client: SharedScraperHTTPClient | None = None,
) -> HealthCheckResult:
    search_scope = provider.search_scope_for_sale_scope(scope)
    request = provider.build_search_request(page=1, search_scope=search_scope)
    started = datetime.now(timezone.utc)
    try:
        client_context = http_client if http_client is not None else SharedScraperHTTPClient(settings, provider_headers=provider.headers)
        async with client_context as client:
            response = await client.request(request)
        elapsed = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        content_type = response.headers.get("content-type", "")
        html = response.text
        blocked = _looks_blocked(response.status_code, html)
        listing = provider.parse_listing_page(html, page=1, search_scope=search_scope)
        if blocked:
            status: HealthStatus = "BLOCKED"
        elif "html" not in content_type.lower() and content_type:
            status = "DEGRADED"
        elif listing.raw_cards_count <= 0 and not listing.candidates:
            status = "STRUCTURE_CHANGED"
        elif listing.invalid_cards_count > max(0, listing.raw_cards_count // 2):
            status = "DEGRADED"
        else:
            status = "HEALTHY"
        return HealthCheckResult(
            status=status,
            provider_key=provider.source_key,
            url=request.url,
            final_url=str(response.url),
            http_status=response.status_code,
            content_type=content_type or None,
            cards=len(listing.candidates),
            invalid_cards=listing.invalid_cards_count,
            response_time_ms=elapsed,
            canonical_url=listing.canonical_url,
        )
    except ScraperHTTPError as exc:
        status = "BLOCKED" if exc.status_code in {403, 429} else "FAILED"
        return HealthCheckResult(status=status, provider_key=provider.source_key, url=request.url, http_status=exc.status_code, error=str(exc))
    except Exception as exc:
        return HealthCheckResult(status="STRUCTURE_CHANGED", provider_key=provider.source_key, url=request.url, error=str(exc)[:500])


def _looks_blocked(status_code: int, text_value: str) -> bool:
    if status_code in {403, 429}:
        return True
    haystack = text_value[:5000].lower()
    return any(term in haystack for term in ("captcha", "cloudflare", "access denied", "too many requests"))


class SaleScheduler:
    def __init__(
        self,
        providers: list[RealEstateProvider],
        settings: SaleSchedulerSettings | None = None,
        scraper_settings: ScraperSettings | None = None,
        session_factory: Callable[[], Any] = AsyncSessionLocal,
        lock_manager: Any | None = None,
        jitter_func: Callable[[str, int], int] | None = None,
        alert_sink: StructuredAlertSink | None = None,
    ):
        self.providers = sorted(providers, key=lambda provider: provider.source_key)
        self.settings = settings or load_sale_scheduler_settings()
        base_scraper_settings = scraper_settings or load_scraper_settings()
        self.scraper_settings = sale_scraper_settings(base_scraper_settings, self.settings)
        self.session_factory = session_factory
        self.lock_manager = lock_manager or PostgresAdvisoryLockManager()
        self.jitter_func = jitter_func or _jitter
        self.alert_sink = alert_sink or StructuredAlertSink(self.settings.alert_cooldown_minutes)
        self.schedules: dict[str, ScheduleJob] = {}

    def register_schedules(self, now: datetime | None = None, due_window: bool = False) -> list[ScheduleJob]:
        now = self._normalize_now(now)
        if not self.settings.enabled:
            self.schedules = {}
            return []
        schedules: dict[str, ScheduleJob] = {}
        for index, provider in enumerate(self.providers):
            if not provider.capabilities.supports_sale:
                continue
            schedules.update(self._provider_schedules(provider, index, now, due_window=due_window))
        self.schedules = schedules
        logger.info("schedules_registered", extra={"jobs": len(schedules), "timezone": self.settings.timezone})
        return list(schedules.values())

    def _provider_schedules(
        self,
        provider: RealEstateProvider,
        index: int,
        now: datetime,
        due_window: bool,
    ) -> dict[str, ScheduleJob]:
        jobs: dict[str, ScheduleJob] = {}
        full_scope = provider.search_scope_for_sale_scope(SaleScrapeScope.full_city().as_dict())
        if self.settings.full_crawl_enabled and provider.supports_scope(SaleScrapeScope.full_city().as_dict()):
            job_id = f"sale_full_crawl:{provider.source_key}"
            offset = index * self.settings.full_crawl_source_offset_minutes
            jitter = self.jitter_func(job_id, self.settings.full_crawl_jitter_minutes)
            next_run_at = self._scheduled_daily(now, self.settings.full_crawl_hour, offset, jitter, due_window)
            jobs[job_id] = ScheduleJob(
                id=job_id,
                job_type="sale_full_crawl",
                source_key=provider.source_key,
                purpose="sale",
                scope=full_scope,
                timezone=self.settings.timezone,
                next_run_at=next_run_at,
                dedupe_occurrence=due_window,
            )

        priority_job_id = f"sale_priority_crawl:{provider.source_key}"
        if self.settings.priority_crawl_enabled and provider.supports_scope(SaleScrapeScope.priority_neighborhoods().as_dict()):
            for neighborhood_index, neighborhood in enumerate(SALE_PRIORITY_NEIGHBORHOODS):
                priority_scope = provider.search_scope_for_sale_scope(
                    SaleScrapeScope.priority_neighborhood(neighborhood).as_dict()
                )
                neighborhood_job_id = f"{priority_job_id}:{neighborhood.slug}"
                offset = (
                    index * self.settings.priority_source_offset_minutes
                    + neighborhood_index * PRIORITY_NEIGHBORHOOD_OFFSET_MINUTES
                )
                jitter = self.jitter_func(neighborhood_job_id, self.settings.priority_jitter_minutes)
                jobs[neighborhood_job_id] = ScheduleJob(
                    id=neighborhood_job_id,
                    job_type="sale_priority_crawl",
                    source_key=provider.source_key,
                    purpose="sale",
                    scope=priority_scope,
                    timezone=self.settings.timezone,
                    next_run_at=self._scheduled_from_hours(
                        now,
                        self.settings.priority_crawl_hours,
                        offset,
                        jitter,
                        due_window,
                    ),
                    dedupe_occurrence=due_window,
                )
        elif self.settings.priority_crawl_enabled:
            priority_scope = provider.search_scope_for_sale_scope(SaleScrapeScope.priority_neighborhoods().as_dict())
            jobs[priority_job_id] = ScheduleJob(
                id=priority_job_id,
                job_type="sale_priority_crawl",
                source_key=provider.source_key,
                purpose="sale",
                scope=priority_scope,
                timezone=self.settings.timezone,
                next_run_at=None,
                enabled=False,
                status="skipped",
                last_result={"result": "skipped", "reason": "neighborhood_scope_not_supported"},
            )

        if self.settings.health_check_enabled:
            job_id = f"sale_health_check:{provider.source_key}"
            offset = index * self.settings.health_check_source_offset_minutes
            jitter = self.jitter_func(job_id, self.settings.health_check_jitter_minutes)
            jobs[job_id] = ScheduleJob(
                id=job_id,
                job_type="sale_health_check",
                source_key=provider.source_key,
                purpose="sale",
                scope=full_scope,
                timezone=self.settings.timezone,
                next_run_at=self._scheduled_interval(
                    now,
                    self.settings.health_check_interval_minutes,
                    offset,
                    jitter,
                    due_window,
                ),
                dedupe_occurrence=due_window,
            )
        return jobs

    async def run_due_once(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = self._normalize_now(now)
        if not self.schedules:
            self.register_schedules(now, due_window=True)
        results = []
        for job in list(self.schedules.values()):
            if not job.enabled or job.next_run_at is None or job.next_run_at > now:
                continue
            if now - job.next_run_at > timedelta(minutes=self.settings.misfire_grace_minutes):
                job.last_result = {"result": "skipped", "reason": "misfire_grace_exceeded"}
                job.next_run_at = self._next_for_job(job, now)
                results.append(job.last_result)
                continue
            result = await self.run_job(job)
            job.last_run_at = now
            job.last_result = result
            job.next_run_at = self._next_for_job(job, now)
            results.append(result)
        return results

    async def run_job(self, job: ScheduleJob) -> dict[str, Any]:
        provider = self._provider(job.source_key)
        if provider is None:
            return {"result": "skipped", "reason": "provider_not_registered", "job_id": job.id}
        if not job.enabled:
            return {"result": "skipped", "reason": "job_disabled", "job_id": job.id}
        if job.job_type == "sale_priority_crawl" and not provider.supports_scope(SaleScrapeScope.priority_neighborhoods().as_dict()):
            result = {"result": "skipped", "reason": "neighborhood_scope_not_supported", "job_id": job.id}
            logger.info("job_skipped", extra={**result, "provider": provider.source_key})
            return result

        async with self.session_factory() as session:
            if job.dedupe_occurrence and job.next_run_at is not None and job.next_run_at <= self._normalize_now(None):
                if await self._already_started_for_occurrence(session, job, job.next_run_at):
                    result = {"result": "skipped", "reason": "schedule_occurrence_already_started", "job_id": job.id}
                    logger.info("job_skipped", extra={**result, "provider": provider.source_key})
                    return result
            if job.job_type == "sale_health_check":
                if await self.lock_manager.is_locked(session, _source_lock_key(provider.source_key)):
                    return {"result": "skipped", "reason": "crawl_active_for_source", "job_id": job.id}
                return await self._run_health_job(session, provider, job)
            return await self._run_crawl_job(session, provider, job)

    async def _run_health_job(self, session, provider: RealEstateProvider, job: ScheduleJob) -> dict[str, Any]:
        result = await run_health_check(provider, self.scraper_settings, job.scope)
        status = "success" if result.status == "HEALTHY" else "partial"
        run = await self._create_scheduler_run(session, provider, job, mode="health")
        run.status = status
        run.finished_at = datetime.utcnow()
        run.summary = {
            "triggered_by": "scheduler",
            "schedule_job_id": job.id,
            "job_type": job.job_type,
            "scheduled_for": job.next_run_at.isoformat() if job.next_run_at else None,
            "purpose": "SALE",
            "scope_type": job.scope.get("scope_type"),
            "health": result.as_dict(),
            "reconciliation_allowed": False,
            "reconciliation_skipped_reason": "health_check",
        }
        session.add(run)
        await session.commit()
        if result.status != "HEALTHY":
            self.alert_sink.emit(
                key=f"{provider.source_key}:{result.status}",
                event="health_check_failed",
                payload={"provider": provider.source_key, "status": result.status, "job_id": job.id},
                now=self._normalize_now(None),
            )
        logger.info("health_check_completed", extra={"provider": provider.source_key, "status": result.status, "job_id": job.id})
        return {"result": result.status, "job_id": job.id, "run_id": str(run.id), "summary": result.as_dict()}

    async def _run_crawl_job(self, session, provider: RealEstateProvider, job: ScheduleJob) -> dict[str, Any]:
        scope_type = str(job.scope.get("scope_type") or "full_city")
        full_lock_key = _scope_lock_key(provider.source_key, "full_city")
        scope_lock_key = _scope_lock_key(provider.source_key, scope_type)
        source_lock_key = _source_lock_key(provider.source_key)
        if scope_type == "priority_neighborhoods" and await self.lock_manager.is_locked(session, full_lock_key):
            result = {"result": "skipped", "reason": "full_city_job_already_running", "job_id": job.id}
            logger.info("job_skipped", extra={**result, "provider": provider.source_key})
            return result
        acquired: list[str] = []
        for key in (source_lock_key, scope_lock_key):
            if not await self.lock_manager.acquire(session, key):
                for acquired_key in reversed(acquired):
                    await self.lock_manager.release(session, acquired_key)
                result = {"result": "skipped", "reason": "equivalent_job_already_running", "job_id": job.id}
                logger.info("lock_unavailable", extra={**result, "provider": provider.source_key, "lock_key": key})
                return result
            acquired.append(key)
        logger.info("lock_acquired", extra={"provider": provider.source_key, "job_id": job.id, "scope_type": scope_type})
        try:
            mode = "full" if job.job_type == "sale_full_crawl" else "delta"
            if self.settings.dry_run:
                stats = await SyncEngine(provider=provider, settings=self.scraper_settings).run(
                    mode=mode,
                    search_scope=job.scope,
                    dry_run=True,
                    max_pages=None if self.settings.max_pages <= 0 else self.settings.max_pages,
                    max_details=None if self.settings.max_details <= 0 else self.settings.max_details,
                )
            else:
                run = await self._create_scheduler_run(session, provider, job, mode=mode)
                await session.commit()
                stats = await SyncEngine(provider=provider, settings=self.scraper_settings, session=session).run(
                    mode=mode,
                    search_scope=job.scope,
                    dry_run=False,
                    max_pages=None if self.settings.max_pages <= 0 else self.settings.max_pages,
                    max_details=None if self.settings.max_details <= 0 else self.settings.max_details,
                    run_id=run.id,
                )
                run = await PropertyRepository(session).get_run(run.id)
                if run:
                    run.job_name = job.job_type
                    summary = dict(run.summary or stats.as_summary())
                    summary.update(
                        {
                            "triggered_by": "scheduler",
                            "schedule_job_id": job.id,
                            "job_type": job.job_type,
                            "scheduled_for": job.next_run_at.isoformat() if job.next_run_at else None,
                            "purpose": "SALE",
                            "scope_type": scope_type,
                            "lock_acquired": True,
                            "reconciliation_allowed": mode == "full" and run.status == "success",
                            "reconciliation_skipped_reason": None if mode == "full" and run.status == "success" else stats.stopped_reason,
                        }
                    )
                    run.summary = summary
                    session.add(run)
                    await session.commit()
            result = {
                "result": "success" if stats.completed and not stats.http_errors and not stats.parse_errors else "partial",
                "job_id": job.id,
                "provider": provider.source_key,
                "stats": stats.as_summary(),
            }
            logger.info("crawl_completed", extra={"provider": provider.source_key, "job_id": job.id, "result": result["result"]})
            if result["result"] != "success":
                self.alert_sink.emit(
                    key=f"{provider.source_key}:{job.job_type}:{stats.stopped_reason}",
                    event="crawl_partial",
                    payload={"provider": provider.source_key, "job_id": job.id, "reason": stats.stopped_reason},
                    now=self._normalize_now(None),
                )
            return result
        except Exception as exc:
            logger.exception("crawl_failed", extra={"provider": provider.source_key, "job_id": job.id})
            self.alert_sink.emit(
                key=f"{provider.source_key}:{job.job_type}:failed",
                event="crawl_failed",
                payload={"provider": provider.source_key, "job_id": job.id, "error": str(exc)[:300]},
                now=self._normalize_now(None),
            )
            return {"result": "failed", "job_id": job.id, "provider": provider.source_key, "error": str(exc)[:500]}
        finally:
            for key in reversed(acquired):
                await self.lock_manager.release(session, key)

    async def _create_scheduler_run(self, session, provider: RealEstateProvider, job: ScheduleJob, mode: str):
        repo = PropertyRepository(session)
        source = await repo.ensure_source(provider)
        run = repo.build_run(provider, source, mode, job.scope)
        run.job_name = job.job_type
        run.status = "pending"
        run.summary = {
            "triggered_by": "scheduler",
            "schedule_job_id": job.id,
            "job_type": job.job_type,
            "scheduled_for": job.next_run_at.isoformat() if job.next_run_at else None,
            "purpose": "SALE",
            "scope_type": job.scope.get("scope_type"),
            "neighborhoods": job.scope.get("neighborhoods"),
            "lock_acquired": False,
        }
        session.add(run)
        await session.flush()
        return run

    async def run_forever(self) -> None:
        self.register_schedules(due_window=True)
        logger.info("scheduler_started", extra={"timezone": self.settings.timezone, "jobs": len(self.schedules)})
        while True:
            try:
                await self.run_due_once()
            except Exception:
                logger.exception("scheduler_tick_failed")
            await asyncio.sleep(max(1, self.settings.loop_poll_seconds))

    def _next_for_job(self, job: ScheduleJob, now: datetime) -> datetime | None:
        provider_index = next((idx for idx, provider in enumerate(self.providers) if provider.source_key == job.source_key), 0)
        if job.job_type == "sale_full_crawl":
            jitter = self.jitter_func(job.id, self.settings.full_crawl_jitter_minutes)
            return _next_daily(now, self.settings.full_crawl_hour, provider_index * self.settings.full_crawl_source_offset_minutes, jitter)
        if job.job_type == "sale_priority_crawl":
            if not job.enabled:
                return None
            jitter = self.jitter_func(job.id, self.settings.priority_jitter_minutes)
            return _next_from_hours(now, self.settings.priority_crawl_hours, provider_index * self.settings.priority_source_offset_minutes, jitter)
        jitter = self.jitter_func(job.id, self.settings.health_check_jitter_minutes)
        return _next_interval(now, self.settings.health_check_interval_minutes, provider_index * self.settings.health_check_source_offset_minutes, jitter)

    def _scheduled_daily(self, now: datetime, hour: int, offset: int, jitter: int, due_window: bool) -> datetime:
        if due_window:
            previous = _previous_daily(now, hour, offset, jitter)
            if now - previous <= timedelta(minutes=self.settings.misfire_grace_minutes):
                return previous
        return _next_daily(now, hour, offset, jitter)

    def _scheduled_from_hours(self, now: datetime, hours: list[int], offset: int, jitter: int, due_window: bool) -> datetime:
        if due_window:
            previous = _previous_from_hours(now, hours, offset, jitter)
            if now - previous <= timedelta(minutes=self.settings.misfire_grace_minutes):
                return previous
        return _next_from_hours(now, hours, offset, jitter)

    def _scheduled_interval(self, now: datetime, interval_minutes: int, offset: int, jitter: int, due_window: bool) -> datetime:
        if due_window:
            previous = _previous_interval(now, interval_minutes, offset, jitter)
            if now - previous <= timedelta(minutes=self.settings.misfire_grace_minutes):
                return previous
        return _next_interval(now, interval_minutes, offset, jitter)

    async def _already_started_for_occurrence(self, session, job: ScheduleJob, scheduled_at: datetime) -> bool:
        scheduled_utc = scheduled_at.astimezone(timezone.utc).replace(tzinfo=None)
        window_end = scheduled_utc + timedelta(minutes=self.settings.misfire_grace_minutes + 2)
        result = await session.execute(
            select(JobLog.summary).where(
                JobLog.provider_key == job.source_key,
                JobLog.job_name == job.job_type,
                JobLog.created_at >= scheduled_utc,
                JobLog.created_at <= window_end,
            )
        )
        for row in result:
            summary = row[0] or {}
            if isinstance(summary, dict) and summary.get("schedule_job_id") == job.id:
                return True
        return False

    def _provider(self, source_key: str) -> RealEstateProvider | None:
        for provider in self.providers:
            if provider.source_key == source_key:
                return provider
        return None

    def _normalize_now(self, now: datetime | None) -> datetime:
        tz = ZoneInfo(self.settings.timezone)
        if now is None:
            return _aware_now(self.settings.timezone)
        if now.tzinfo is None:
            return now.replace(tzinfo=tz)
        return now.astimezone(tz)


async def build_scheduler_from_db() -> SaleScheduler:
    async with AsyncSessionLocal() as session:
        providers = await load_enabled_sale_providers(session)
    return SaleScheduler(providers=providers)


async def run_scheduler_forever() -> None:
    scheduler = await build_scheduler_from_db()
    await scheduler.run_forever()


async def list_schedules() -> list[dict[str, Any]]:
    scheduler = await build_scheduler_from_db()
    return [job.as_dict() for job in scheduler.register_schedules()]


async def run_due_once() -> list[dict[str, Any]]:
    scheduler = await build_scheduler_from_db()
    scheduler.register_schedules(due_window=True)
    return await scheduler.run_due_once()


async def run_manual_job(
    provider_key: str,
    job_type: ScheduleJobType,
    dry_run: bool = False,
    max_pages: int | None = None,
    max_details: int | None = None,
) -> dict[str, Any]:
    provider = load_provider(provider_key)
    if provider is None:
        raise RuntimeError(f"provider not registered: {provider_key}")
    settings = load_sale_scheduler_settings()
    settings = SaleSchedulerSettings(
        enabled=settings.enabled,
        timezone=settings.timezone,
        full_crawl_enabled=settings.full_crawl_enabled,
        full_crawl_hour=settings.full_crawl_hour,
        full_crawl_source_offset_minutes=settings.full_crawl_source_offset_minutes,
        full_crawl_jitter_minutes=settings.full_crawl_jitter_minutes,
        priority_crawl_enabled=settings.priority_crawl_enabled,
        priority_crawl_hours=settings.priority_crawl_hours,
        priority_source_offset_minutes=settings.priority_source_offset_minutes,
        priority_jitter_minutes=settings.priority_jitter_minutes,
        health_check_enabled=settings.health_check_enabled,
        health_check_interval_minutes=settings.health_check_interval_minutes,
        health_check_source_offset_minutes=settings.health_check_source_offset_minutes,
        health_check_jitter_minutes=settings.health_check_jitter_minutes,
        detail_refresh_days=settings.detail_refresh_days,
        missing_runs_before_removal=settings.missing_runs_before_removal,
        minimum_inventory_ratio=settings.minimum_inventory_ratio,
        max_pages=0 if max_pages is None else max_pages,
        max_details=0 if max_details is None else max_details,
        dry_run=dry_run,
        loop_poll_seconds=settings.loop_poll_seconds,
        misfire_grace_minutes=settings.misfire_grace_minutes,
        alert_cooldown_minutes=settings.alert_cooldown_minutes,
    )
    scheduler = SaleScheduler([provider], settings=settings)
    registered_jobs = scheduler.register_schedules()
    matching_jobs = [job for job in registered_jobs if job.job_type == job_type]
    if job_type == "sale_priority_crawl" and matching_jobs:
        results = []
        for job in matching_jobs:
            results.append(await scheduler.run_job(job))
        return {
            "result": "success" if all(result.get("result") in {"success", "skipped"} for result in results) else "partial",
            "provider": provider.source_key,
            "job_type": job_type,
            "jobs": results,
        }
    jobs = {job.job_type: job for job in registered_jobs}
    job = jobs.get(job_type)
    if job is None:
        scope = (
            SaleScrapeScope.priority_neighborhoods().as_dict()
            if job_type == "sale_priority_crawl"
            else SaleScrapeScope.full_city().as_dict()
        )
        job = ScheduleJob(
            id=f"{job_type}:{provider.source_key}",
            job_type=job_type,
            source_key=provider.source_key,
            purpose="sale",
            scope=provider.search_scope_for_sale_scope(scope),
            timezone=settings.timezone,
            next_run_at=None,
            enabled=settings.enabled,
        )
    return await scheduler.run_job(job)
