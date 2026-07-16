from datetime import datetime, timedelta

from scrapers.core.lifecycle import MissingPolicy, status_when_not_seen, status_when_seen


def test_active_to_missing_on_valid_full_run():
    now = datetime(2026, 1, 10, 12)
    next_status, changed = status_when_not_seen("ACTIVE", None, now, True, MissingPolicy())
    assert next_status == "MISSING"
    assert changed is True


def test_missing_to_removed_after_configured_window():
    now = datetime(2026, 1, 10, 12)
    missing_since = now - timedelta(hours=73)
    next_status, changed = status_when_not_seen(
        "MISSING",
        missing_since,
        now,
        True,
        MissingPolicy(removal_after_hours=72),
    )
    assert next_status == "REMOVED"
    assert changed is True


def test_removed_to_active_is_reactivation():
    next_status, reactivated = status_when_seen("REMOVED")
    assert next_status == "ACTIVE"
    assert reactivated is True


def test_failed_execution_does_not_mark_missing_or_removed():
    now = datetime(2026, 1, 10, 12)
    next_status, changed = status_when_not_seen(
        "ACTIVE",
        None,
        now,
        False,
        MissingPolicy(removal_after_hours=1),
    )
    assert next_status is None
    assert changed is False


def test_delta_execution_does_not_reconcile_global_absences():
    now = datetime(2026, 1, 10, 12)
    next_status, changed = status_when_not_seen("MISSING", now - timedelta(days=30), now, False, MissingPolicy())
    assert next_status is None
    assert changed is False
