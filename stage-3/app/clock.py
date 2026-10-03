"""Instants: exact integer-microsecond timestamps, RFC 3339 text, strict parsing.

`now()` is strictly increasing across calls (a microsecond is added when the wall clock has not
advanced), so recorded times of one payment always increase and ties are rare.
"""
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MICRO = timedelta(microseconds=1)
_lock = threading.Lock()
_last = 0

_RFC3339 = re.compile(r"^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(?:\.(\d+))?([Zz]|[+-]\d{2}:\d{2})$")
_SPACE_OFFSET = re.compile(r"^(.*\d) (\d{2}:\d{2})$")  # a "+" in a raw query string decodes to a space


class Stamp(NamedTuple):
    ts: int      # microseconds since the epoch
    text: str    # RFC 3339 with an explicit offset


def to_ts(moment: datetime) -> int:
    return (moment - EPOCH) // _MICRO


def from_ts(ts: int) -> Stamp:
    return Stamp(ts, (EPOCH + timedelta(microseconds=ts)).isoformat())


def now() -> Stamp:
    global _last
    wall = to_ts(datetime.now(timezone.utc))
    with _lock:
        _last = max(wall, _last + 1)
        return from_ts(_last)


def parse(text) -> "Stamp | None":
    """A strict RFC 3339 instant with an offset, or None. The text is kept as supplied."""
    if not isinstance(text, str):
        return None
    match = _RFC3339.match(text)
    if not match:
        return None
    date, clock, fraction, offset = match.groups()
    offset = "+00:00" if offset in ("Z", "z") else offset
    micro = (fraction or "")[:6].ljust(6, "0")
    try:
        moment = datetime.fromisoformat("%sT%s.%s%s" % (date, clock, micro, offset))
    except ValueError:
        return None
    if int(offset[1:3]) > 23 or int(offset[4:6]) > 59:
        return None
    return Stamp(to_ts(moment), text)


def parse_query(text) -> "Stamp | None":
    """Like `parse`, but repairs an unescaped "+" offset that the query decoder turned into a space."""
    stamp = parse(text)
    if stamp is None and isinstance(text, str):
        match = _SPACE_OFFSET.match(text)
        if match:
            stamp = parse("%s+%s" % match.groups())
    return stamp
