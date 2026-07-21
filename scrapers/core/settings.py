from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _int_list_env(name: str, default: list[int]) -> list[int]:
    value = os.getenv(name)
    if not value:
        return list(default)
    values: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(int(part))
        except ValueError:
            return list(default)
    return values or list(default)


@dataclass(frozen=True)
class ScraperSettings:
    user_agent: str = os.getenv("SCRAPER_USER_AGENT", "ImobHubBot/1.0 (+https://example.com)")
    timeout_seconds: float = _float_env("SCRAPER_TIMEOUT_SECONDS", 20.0)
    max_retries: int = _int_env("SCRAPER_MAX_RETRIES", 3)
    concurrency_per_source: int = _int_env("SCRAPER_CONCURRENCY_PER_SOURCE", 2)
    request_delay_min_ms: int = _int_env("SCRAPER_REQUEST_DELAY_MIN_MS", 350)
    request_delay_max_ms: int = _int_env("SCRAPER_REQUEST_DELAY_MAX_MS", 1200)
    missing_threshold: int = _int_env("SCRAPER_MISSING_THRESHOLD", 2)
    removal_after_hours: int = _int_env("SCRAPER_REMOVAL_AFTER_HOURS", 72)
    detail_ttl_hours: int = _int_env("SCRAPER_DETAIL_TTL_HOURS", 24)
    delta_stale_pages: int = _int_env("SCRAPER_DELTA_STALE_PAGES", 3)
    max_invalid_card_rate: float = _float_env("SCRAPER_MAX_INVALID_CARD_RATE", 0.25)
    full_min_listing_ratio: float = _float_env("SCRAPER_FULL_MIN_LISTING_RATIO", 0.50)
    max_pages: int = _int_env("SCRAPER_MAX_PAGES", 0)
    dry_run: bool = _bool_env("SCRAPER_DRY_RUN", False)


@dataclass(frozen=True)
class SaleSchedulerSettings:
    enabled: bool = _bool_env("SALE_SCRAPING_ENABLED", True)
    timezone: str = os.getenv("SALE_SCRAPING_TIMEZONE", "America/Sao_Paulo")
    full_crawl_enabled: bool = _bool_env("SALE_FULL_CRAWL_ENABLED", True)
    full_crawl_hour: int = _int_env("SALE_FULL_CRAWL_HOUR", 3)
    full_crawl_source_offset_minutes: int = _int_env("SALE_FULL_CRAWL_SOURCE_OFFSET_MINUTES", 15)
    full_crawl_jitter_minutes: int = _int_env("SALE_FULL_CRAWL_JITTER_MINUTES", 10)
    priority_crawl_enabled: bool = _bool_env("SALE_PRIORITY_CRAWL_ENABLED", True)
    priority_crawl_hours: list[int] = field(
        default_factory=lambda: _int_list_env("SALE_PRIORITY_CRAWL_HOURS", [2, 6, 10, 14, 18, 22])
    )
    priority_source_offset_minutes: int = _int_env("SALE_PRIORITY_SOURCE_OFFSET_MINUTES", 10)
    priority_jitter_minutes: int = _int_env("SALE_PRIORITY_JITTER_MINUTES", 10)
    health_check_enabled: bool = _bool_env("SALE_HEALTH_CHECK_ENABLED", True)
    health_check_interval_minutes: int = _int_env("SALE_HEALTH_CHECK_INTERVAL_MINUTES", 60)
    health_check_source_offset_minutes: int = _int_env("SALE_HEALTH_CHECK_SOURCE_OFFSET_MINUTES", 5)
    health_check_jitter_minutes: int = _int_env("SALE_HEALTH_CHECK_JITTER_MINUTES", 5)
    detail_refresh_days: int = _int_env("SALE_DETAIL_REFRESH_DAYS", 7)
    missing_runs_before_removal: int = _int_env("SALE_MISSING_RUNS_BEFORE_REMOVAL", 2)
    minimum_inventory_ratio: float = _float_env("SALE_MINIMUM_INVENTORY_RATIO", 0.70)
    max_pages: int = _int_env("SALE_MAX_PAGES", 0)
    max_details: int = _int_env("SALE_MAX_DETAILS", 0)
    dry_run: bool = _bool_env("SALE_DRY_RUN", False)
    loop_poll_seconds: int = _int_env("SALE_SCHEDULER_POLL_SECONDS", 60)
    misfire_grace_minutes: int = _int_env("SALE_SCHEDULER_MISFIRE_GRACE_MINUTES", 30)
    alert_cooldown_minutes: int = _int_env("SALE_ALERT_COOLDOWN_MINUTES", 180)


def load_scraper_settings() -> ScraperSettings:
    return ScraperSettings()


def load_sale_scheduler_settings() -> SaleSchedulerSettings:
    return SaleSchedulerSettings()
