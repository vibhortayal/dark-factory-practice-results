"""Timestamps: RFC 3339 text with explicit offset plus a sortable microsecond value."""
from datetime import datetime, timezone
from typing import NamedTuple


class Stamp(NamedTuple):
    ts: int
    text: str


def now() -> Stamp:
    moment = datetime.now(timezone.utc)
    return Stamp(int(moment.timestamp() * 1_000_000), moment.isoformat(timespec="seconds"))


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
