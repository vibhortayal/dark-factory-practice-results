"""Restaurant-local time handling, including DST rules."""
import datetime as dt
import re
from functools import lru_cache
from zoneinfo import ZoneInfo

from .errors import invalid

UTC = dt.timezone.utc
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_LOCAL_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2})$")
_DATE_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")
_HHMM_RE = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
MIN_YEAR, MAX_YEAR = 1900, 2200


@lru_cache(maxsize=None)
def zone(name):
    return ZoneInfo(name)


def valid_zone(name):
    if not name or name.startswith("/") or ".." in name:
        return False
    try:
        zone(name)
        return True
    except Exception:
        return False


def parse_date(text):
    m = _DATE_RE.match(text)
    if not m:
        raise invalid("date must be YYYY-MM-DD")
    try:
        d = dt.date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        raise invalid("date is not a real calendar date") from None
    if not MIN_YEAR <= d.year <= MAX_YEAR:
        raise invalid("date out of range")
    return d


def parse_local(text):
    """Bare local 'YYYY-MM-DDTHH:MM' -> naive datetime."""
    m = _LOCAL_RE.match(text)
    if not m:
        raise invalid("starts_at_local must be a bare local YYYY-MM-DDTHH:MM")
    try:
        d = dt.datetime(*(int(g) for g in m.groups()))
    except ValueError:
        raise invalid("starts_at_local is not a real date/time") from None
    if not MIN_YEAR <= d.year <= MAX_YEAR:
        raise invalid("starts_at_local out of range")
    return d


def parse_hhmm(text):
    m = _HHMM_RE.match(text)
    if not m:
        return None
    return int(m[1]) * 60 + int(m[2])


def resolve_local(tz_name, naive):
    """Local wall-clock -> epoch seconds, or None when the time does not exist.

    Repeated (fall-back) times resolve to the first occurrence (fold=0).
    """
    tz = zone(tz_name)
    aware = naive.replace(tzinfo=tz)
    utc = aware.astimezone(UTC)
    if utc.astimezone(tz).replace(tzinfo=None) != naive:
        return None
    return int(utc.timestamp())


def iso_at(tz_name, epoch):
    return dt.datetime.fromtimestamp(epoch, zone(tz_name)).isoformat()


def local_at(tz_name, epoch):
    return dt.datetime.fromtimestamp(epoch, zone(tz_name)).replace(tzinfo=None)


def now_epoch():
    import time
    return time.time()


def utc_stamp(epoch=None):
    d = dt.datetime.now(UTC) if epoch is None else dt.datetime.fromtimestamp(epoch, UTC)
    return d.replace(microsecond=0).isoformat()
