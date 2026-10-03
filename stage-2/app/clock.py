"""Timestamps: RFC 3339 text with explicit offset plus a sortable microsecond value."""
from datetime import datetime, timezone
from typing import NamedTuple


class Stamp(NamedTuple):
    ts: int
    text: str


def now() -> Stamp:
    moment = datetime.now(timezone.utc)
    return Stamp(int(moment.timestamp() * 1_000_000), moment.isoformat(timespec="seconds"))


def from_ts(ts: int) -> Stamp:
    """A Stamp for a microsecond timestamp, with sub-second precision in the text."""
    moment = datetime.fromtimestamp(ts / 1_000_000, timezone.utc)
    return Stamp(ts, moment.isoformat())


def parse(text) -> "Stamp | None":
    """Parse a fixture-provided timestamp; None if it is not usable."""
    if not isinstance(text, str):
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return Stamp(int(moment.timestamp() * 1_000_000), moment.isoformat(timespec="seconds"))
