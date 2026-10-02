"""RFC 3339 timestamps with an explicit numeric offset."""
from datetime import datetime, timedelta, timezone


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def now_dt():
    return datetime.now(timezone.utc)


def created_and_expiry(ttl_seconds):
    """(created_at, expires_at) from ONE clock read.

    created_at is now rounded up to a whole second so the lifetime is never
    shorter than the ttl; expires_at is exactly created_at + ttl.
    """
    now = now_dt()
    whole = now.replace(microsecond=0) + (timedelta(seconds=1) if now.microsecond else timedelta())
    return (whole.isoformat(timespec="seconds"),
            (whole + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds"))
