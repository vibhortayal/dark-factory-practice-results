"""Unauthenticated test endpoints: reset, export, import (spec §3.3, §10)."""
from .. import holds
from ..fixture import build_state, precompute_hashes
from ..statecheck import check_export
from ..store import store


def reset(req):
    fixture = req.json_body()
    hashes = precompute_hashes(fixture)   # slow hashing happens before the lock
    with store.locked():
        state = build_state(fixture, store.now, hashes)
        store.load(state)
        holds.sweep()
    return 204, None


def export_state(req):
    with store.locked():
        return 200, {"track": "pocketful", "format_version": 1, "state": store.dump()}


def import_state(req):
    document = req.json_body()
    with store.locked():
        state = check_export(document, store.now)
        store.load(state)
        holds.sweep()
    return 204, None
