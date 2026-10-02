"""RFC 3339 timestamps with an explicit numeric offset."""
import re
from datetime import datetime, timedelta, timezone


def fmt(instant):
    """Fixed-width RFC 3339: UTC, always six fractional digits, numeric offset.

    Strings of server-assigned timestamps therefore sort in time order.
    """
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def parse_iso(value):
    """Parse an RFC 3339 string with an offset; return an aware datetime or None."""
    if not isinstance(value, str):
        return None
    strict = parse_rfc3339(value)
    if strict is not None:
        return strict
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


_RFC3339 = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?([Zz]|[+-]\d{2}:\d{2})")


def parse_rfc3339(value):
    """A strictly RFC 3339 instant with an offset -> aware datetime, else None.

    Naive times, bare dates, empty text and impossible dates are all None.
    Fractional seconds beyond microseconds are truncated.
    """
    if not isinstance(value, str):
        return None
    match = _RFC3339.fullmatch(value)
    if match is None:
        return None
    year, month, day, hour, minute, second, fraction, offset = match.groups()
    try:
        if offset in ("Z", "z"):
            zone = timezone.utc
        else:
            sign = -1 if offset[0] == "-" else 1
            hours, minutes = int(offset[1:3]), int(offset[4:6])
            if hours > 23 or minutes > 59:
                return None
            zone = timezone(sign * timedelta(hours=hours, minutes=minutes))
        micro = int((fraction or "0")[:6].ljust(6, "0"))
        return datetime(int(year), int(month), int(day), int(hour), int(minute), int(second), micro, zone)
    except ValueError:
        return None
