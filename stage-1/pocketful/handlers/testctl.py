"""Unauthenticated test endpoints: reset, export, import (spec §3.3, §10)."""
from ..errors import invalid
from ..statecodec import build_state, check_export
from ..store import store
from ..timefmt import now_iso


def reset(req):
    fixture = req.json_body()
    state = build_state(fixture, now_iso())  # hashing happens before the lock
    store.load(state)
    return 204, None


def export_state(req):
    return 200, {"track": "pocketful", "format_version": 1, "state": store.dump()}


def import_state(req):
    document = req.json_body()
    state = check_export(document)
    store.load(state)
    return 204, None
