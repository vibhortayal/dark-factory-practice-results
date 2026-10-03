"""Test-control endpoints: reset, export, import (spec §3.3, §10). Unauthenticated."""
from . import snapshot
from .errors import ApiError, invalid
from .state import LOCK, STORE

TRACK, FORMAT_VERSION = "tablekeeper", 1


def reset(req):
    data = snapshot.from_fixture(req.json_object())  # hashing happens outside the lock
    with LOCK:
        STORE.data = data
    return 204, None


def export(req):
    return 200, {"track": TRACK, "format_version": FORMAT_VERSION,
                 "state": snapshot.export_state(STORE.data)}


def import_(req):
    body = req.json_object()
    if body.get("track") != TRACK or body.get("format_version") != FORMAT_VERSION \
            or type(body.get("format_version")) is not int or "state" not in body:
        raise invalid("expected track 'tablekeeper', format_version 1 and a state")
    try:
        data = snapshot.from_state(body["state"])
    except (ApiError, KeyError, TypeError, ValueError, AttributeError):
        raise invalid("state is not a valid export")
    STORE.data = data
    return 204, None
