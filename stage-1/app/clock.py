"""RFC 3339 timestamps with an explicit offset."""
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
