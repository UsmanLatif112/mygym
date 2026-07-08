from datetime import datetime, timedelta, timezone


def parse_check_in_at(value):
    """Parse incoming datetime and normalize to naive UTC for DB storage."""
    if not value:
        return None

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)

    return dt


def should_skip_duplicate(last_log, incoming_time, dedup_seconds=60):
    """Return True if incoming event is inside deduplication window."""
    if not last_log or not incoming_time:
        return False

    last_time = getattr(last_log, "check_in_at", None)
    if not last_time:
        return False

    delta = abs((incoming_time - last_time).total_seconds())
    return delta <= dedup_seconds
