from __future__ import annotations

import os
from dataclasses import dataclass


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
    max_pages: int = _int_env("SCRAPER_MAX_PAGES", 0)
    dry_run: bool = _bool_env("SCRAPER_DRY_RUN", False)


def load_scraper_settings() -> ScraperSettings:
    return ScraperSettings()

