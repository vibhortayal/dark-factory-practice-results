"""Route table and request dispatch (independent of the HTTP transport)."""
import re

from . import accounts, bookings, catalog, fixture, idempotency, moves, snapshot
from .errors import ApiError, not_found
from .jsonutil import parse_json, parse_object
from .timeutil import now_epoch


class Request:
    def __init__(self, method, path, query, headers, raw):
        self.method, self.path, self.query, self.headers, self.raw = method, path, query, headers, raw

    def body(self):
        return parse_object(self.raw)


def _reset(store, req, _m):
    state = fixture.build_state(req.body())
    store.replace(state)
    return 204, None


def _export(store, req, _m):
    return 200, snapshot.export_state(store)


def _import(store, req, _m):
    snapshot.import_state(store, req.body())
    return 204, None


def _signup(store, req, _m):
    return 201, accounts.signup(store, req.body())


def _login(store, req, _m):
    return 200, accounts.login(store, req.body())


def _list_restaurants(store, req, _m):
    return 200, catalog.list_restaurants(store)


def _get_restaurant(store, req, m):
    return 200, catalog.get_restaurant(store, m[0])


def _availability(store, req, _m):
    return 200, catalog.availability(store, req.query)


def _create(store, req, _m):
    uid = accounts.authenticate(store, req.headers)
    key = idempotency.read_key(req.headers)
    return bookings.create(store, uid, key, req.body())


def _list(store, req, _m):
    uid = accounts.authenticate(store, req.headers)
    return 200, bookings.list_for(store, uid)


def _get(store, req, m):
    uid = accounts.authenticate(store, req.headers)
    return 200, bookings.get(store, uid, m[0])


def _cancel(store, req, m):
    uid = accounts.authenticate(store, req.headers)
    return 200, bookings.cancel(store, uid, m[0], now_epoch())


def _patch(store, req, m):
    uid = accounts.authenticate(store, req.headers)
    return 200, bookings.amend(store, uid, m[0], req.body(), now_epoch())


def _moves(store, req, _m):
    uid = accounts.authenticate(store, req.headers)
    key = idempotency.read_key(req.headers)
    return moves.move(store, uid, key, req.body(), now_epoch())


def _health(store, req, _m):
    return 200, {"status": "ok"}


SEG = r"([^/]+)"
ROUTES = [
    (r"/health", {"GET": _health}),
    (r"/_test/reset", {"POST": _reset}),
    (r"/_test/export", {"GET": _export}),
    (r"/_test/import", {"POST": _import}),
    (r"/auth/signup", {"POST": _signup}),
    (r"/auth/login", {"POST": _login}),
    (r"/restaurants", {"GET": _list_restaurants}),
    (r"/restaurants/" + SEG, {"GET": _get_restaurant}),
    (r"/availability", {"GET": _availability}),
    (r"/reservations", {"POST": _create, "GET": _list}),
    (r"/reservations/" + SEG, {"GET": _get, "PATCH": _patch}),
    (r"/reservations/" + SEG + r"/cancel", {"POST": _cancel}),
    (r"/reservation-moves", {"POST": _moves}),
]
_COMPILED = [(re.compile("^" + p + "$"), h) for p, h in ROUTES]


def dispatch(store, req):
    """Return (status, json-able body or None). Raises ApiError for failures."""
    for pattern, handlers in _COMPILED:
        m = pattern.match(req.path)
        if not m:
            continue
        handler = handlers.get(req.method)
        if handler is None:
            raise ApiError("method not allowed", "method_not_allowed", 405)
        return handler(store, req, m.groups())
    raise not_found("no such route")
