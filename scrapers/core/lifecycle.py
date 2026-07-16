from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .types import PropertyStatus


@dataclass(frozen=True)
class MissingPolicy:
    missing_threshold: int = 2
    removal_after_hours: int = 72


def status_when_seen(previous_status: str | None) -> tuple[PropertyStatus, bool]:
    if previous_status in {"MISSING", "REMOVED", "missing", "removed"}:
        return "ACTIVE", True
    return "ACTIVE", False


def status_when_not_seen(
    current_status: str | None,
    missing_since: datetime | None,
    now: datetime,
    valid_full_run: bool,
    policy: MissingPolicy,
) -> tuple[PropertyStatus | None, bool]:
    if not valid_full_run:
        return None, False

    normalized_status = (current_status or "ACTIVE").upper()
    if normalized_status == "REMOVED":
        return None, False

    if normalized_status == "ACTIVE":
        return "MISSING", True

    if normalized_status == "MISSING":
        if missing_since and now - missing_since >= timedelta(hours=policy.removal_after_hours):
            return "REMOVED", True
        return None, False

    return None, False

