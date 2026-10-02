"""Unauthenticated test endpoints: reset, export, import (spec §3.3, §10)."""
from .. import clock, operation
from ..errors import invalid
from ..fixture import build_state
from ..statecheck import check_export
from ..store import store
from ..timefmt import fmt


def reset(req):
    fixture = req.json_body()
    state = build_state(fixture, fmt(clock.tick()))  # hashing happens before the lock
    with store.lock:
        store.load(state)
        operation.begin()
    return 204, None


def export_state(req):
    with store.lock:
        operation.begin()
        return 200, {"track": "pocketful", "format_version": 1, "state": store.dump()}


def import_state(req):
    document = req.json_body()
    state = check_export(document)
    with store.lock:
        store.load(state)
        operation.begin()
    return 204, None
