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


def iso_at_or_after_now(plus_seconds=0):
    """Now rounded up to a whole second, plus an offset, as an RFC 3339 string.

    Used for authorizations so `created_at + ttl` never expires earlier than the
    ttl promises, however the sub-second part falls.
    """
    now = now_dt()
    whole = now.replace(microsecond=0) + (timedelta(seconds=1) if now.microsecond else timedelta())
    return (whole + timedelta(seconds=plus_seconds)).isoformat(timespec="seconds")
