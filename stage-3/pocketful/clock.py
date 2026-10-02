"""The service clock: one monotonic source of "now" for server-assigned instants.

`tick()` never returns an instant earlier than or equal to the previous one, even
if the wall clock steps backwards, so a later write never carries an earlier
timestamp.
"""
import threading
from datetime import datetime, timedelta, timezone

_lock = threading.Lock()
_last = None


def tick():
    global _last
    with _lock:
        now = datetime.now(timezone.utc)
        if _last is not None and now <= _last:
            now = _last + timedelta(microseconds=1)
        _last = now
        return now
