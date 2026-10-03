"""Route table, request context, authentication and dispatch under the global lock."""
import json
import re

from . import accounts, admin, bookings, catalog, history, policies, replans, series, web
from .errors import ApiError, malformed, not_found, unauthenticated
from .state import LOCK, STORE


class Request:
    def __init__(self, method, path, query, headers, body):
        self.method, self.path, self.query = method, path, query
        self.headers, self.raw, self.user_id = headers, body, None

    def json_object(self):
        try:
            value = json.loads(self.raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise malformed("body is not valid JSON")
        if not isinstance(value, dict):
            raise malformed("body must be a JSON object")
        return value


def _ref(pattern):
    return re.compile("^" + pattern + "$")


# (method, path regex, handler, needs_auth, take_global_lock)
def _screen(route):
    return lambda req: (200, web.page(route))


def _asset(req, name):
    if name not in web.ASSETS:
        raise not_found("no such route")
    return 200, web.asset(name)


ROUTES = [
    *[("GET", _ref(route), _screen(route), False, False) for route in web.PAGES],
    ("GET", _ref("/assets/([a-z.]+)"), _asset, False, False),
    ("GET", _ref("/health"), lambda req: (200, {"status": "ok"}), False, False),
    ("POST", _ref("/_test/reset"), admin.reset, False, False),
    ("GET", _ref("/_test/export"), admin.export, False, True),
    ("POST", _ref("/_test/import"), admin.import_, False, True),
    ("POST", _ref("/auth/signup"), accounts.signup, False, False),
    ("POST", _ref("/auth/login"), accounts.login, False, False),
    ("GET", _ref("/restaurants"), catalog.list_restaurants, False, True),
    ("GET", _ref("/restaurants/([^/]+)"), catalog.get_restaurant, False, True),
    ("GET", _ref("/availability"), catalog.availability, False, True),
    ("POST", _ref("/reservations"), bookings.create, True, True),
    ("GET", _ref("/reservations"), bookings.list_mine, True, True),
    ("GET", _ref("/reservations/([^/]+)"), bookings.get_one, True, True),
    ("POST", _ref("/reservations/([^/]+)/cancel"), bookings.cancel, True, True),
    ("PATCH", _ref("/reservations/([^/]+)"), bookings.amend, True, True),
    ("GET", _ref("/reservations/([^/]+)/history"), history.history, "optional", True),
    ("GET", _ref("/reservations/([^/]+)/decision"), history.decision, "optional", True),
    ("POST", _ref("/reservation-moves"), bookings.moves, True, True),
    ("POST", _ref("/restaurants/([^/]+)/policies"), policies.publish, "after_body", True),
    ("GET", _ref("/restaurants/([^/]+)/policies"), policies.list_policies, False, True),
    ("POST", _ref("/series"), series.create, "after_body", True),
    ("POST", _ref("/series/([^/]+)/amend"), series.amend, "after_body", True),
    ("POST", _ref("/restaurants/([^/]+)/replans"), replans.preview, "after_body", True),
    ("POST", _ref("/restaurants/([^/]+)/replans/([^/]+)/apply"), replans.apply, "after_body", True),
    ("GET", _ref("/series/([^/]+)"), series.get, "optional", True),
]


def _bearer(headers):
    value = headers.get("authorization", "")
    parts = value.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise unauthenticated("a bearer token is required")
    return parts[1]


def dispatch(req):
    """Return (status, payload) or raise ApiError."""
    allowed = []
    for method, pattern, handler, needs_auth, locked in ROUTES:
        m = pattern.match(req.path)
        if not m:
            continue
        if method != req.method:
            allowed.append(method)
            continue
        args = m.groups()
        if not locked:
            if needs_auth:
                raise AssertionError("auth routes are locked")
            return handler(req, *args)
        with LOCK:
            if needs_auth == "after_body":
                req.json_object()  # an unparseable body is reported before a missing token
            if needs_auth == "optional":  # owner-only reads: signed-out callers get the owner 404
                try:
                    req.user_id = STORE.data.tokens.get(_bearer(req.headers))
                except ApiError:
                    req.user_id = None
            elif needs_auth:
                user = STORE.data.tokens.get(_bearer(req.headers))
                if user is None:
                    raise unauthenticated("unknown bearer token")
                req.user_id = user
            return handler(req, *args)
    if allowed:
        raise ApiError(405, "method_not_allowed", "method not allowed")
    raise not_found("no such route")
