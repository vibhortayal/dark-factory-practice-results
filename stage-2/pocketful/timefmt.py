"""RFC 3339 timestamps with an explicit numeric offset."""
from datetime import datetime, timezone


def fmt(instant):
    """Fixed-width RFC 3339: UTC, always six fractional digits, numeric offset.

    Strings of server-assigned timestamps therefore sort in time order.
    """
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def parse_iso(value):
    """Parse an RFC 3339 string with an offset; return an aware datetime or None."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def normalise_iso(value):
    """Return the value with a numeric offset, or None when it is not valid."""
    parsed = parse_iso(value)
    if parsed is None:
        return None
    return parsed.isoformat(timespec="seconds") if parsed.microsecond == 0 else parsed.isoformat()
