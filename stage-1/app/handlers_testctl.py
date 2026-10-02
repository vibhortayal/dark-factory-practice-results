"""Unauthenticated test endpoints: reset, export, import."""
from . import fixture, store as store_mod
from .errors import invalid, malformed
from .jsonutil import parse
from .store import LOCK, StateError


def reset(req):
    new_store = fixture.build(parse(req.raw_body))  # hashing happens outside the lock
    with LOCK:
        store_mod.replace(new_store)
    return 204, None


def export(req):
    with LOCK:
        state = store_mod.current().dump()
    return 200, {"track": "pocketful", "format_version": 1, "state": state}


def import_state(req):
    body = parse(req.raw_body)
    if not isinstance(body, dict):
        raise malformed("body must be a JSON object")
    version = body.get("format_version")
    if (body.get("track") != "pocketful" or type(version) is not int or version != 1
            or not isinstance(body.get("state"), dict)):
        raise invalid("expected track pocketful, format_version 1 and a state object")
    try:
        new_store = store_mod.load(body["state"])
    except StateError:
        raise invalid("state is not a valid pocketful state") from None
    with LOCK:
        store_mod.replace(new_store)
    return 204, None
