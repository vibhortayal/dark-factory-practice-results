"""Restaurant-local time handling, DST rules (spec §9).

Skipped local times do not exist; repeated local times resolve to the first
occurrence; durations are absolute time. All arithmetic on instants is done on
aware datetimes, so overlap is computed on absolute instants.
"""
import datetime as dt
import re
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
LOCAL_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2})$")
DATE_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")
HHMM_RE = re.compile(r"^([0-9]{2}):([0-9]{2})$")


def zone(name):
    return ZoneInfo(name)


def now_utc():
    return dt.datetime.now(UTC).replace(microsecond=0)


def iso(moment):
    """RFC 3339 with an explicit numeric offset."""
    return moment.replace(microsecond=0).isoformat()


def parse_local(text):
    """Parse a bare YYYY-MM-DDTHH:MM into a naive datetime, or None if invalid."""
    m = LOCAL_RE.match(text)
    if not m:
        return None
    try:
        return dt.datetime(*(int(g) for g in m.groups()))
    except ValueError:
        return None


def parse_date(text):
    m = DATE_RE.match(text)
    if not m:
        return None
    try:
        return dt.date(*(int(g) for g in m.groups()))
    except ValueError:
        return None


def parse_hhmm(text):
    """Minutes since local midnight for a 24-hour HH:MM, or None."""
    m = HHMM_RE.match(text)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return h * 60 + mi


def resolve_local(tz, naive):
    """UTC instant for a local wall time, first occurrence if repeated.

    Returns None when the wall time falls in a spring-forward gap. Instants are kept
    in UTC because arithmetic and comparison on same-zone datetimes ignore the
    offset (wall-clock semantics); convert with `.astimezone(tz)` only to display.
    """
    instant = naive.replace(tzinfo=tz, fold=0).astimezone(UTC)
    return instant if instant.astimezone(tz).replace(tzinfo=None) == naive else None


def instant_of_wall(tz, naive):
    """Instant for a wall time that need not exist (used for closing time)."""
    return naive.replace(tzinfo=tz, fold=0).astimezone(UTC)


def local_text(moment):
    return moment.strftime("%Y-%m-%dT%H:%M")


def weekday_key(date):
    return WEEKDAYS[date.weekday()]
