"""Route table and the request pipeline.

Pipeline for authenticated routes (spec section 7, F10):
401 -> body parse (400) -> idempotency key (400/422) -> claimed key -> handler.
"""
import re
from urllib.parse import unquote

from . import clock, holds, idempotency, web
from .errors import ApiError, forbidden, not_found, unauthenticated
from .handlers import (activity, auth, authorizations, batches, corrections, me, payments,
                       refunds, requests, settlements, splits, statement, testctl)
from .jsonutil import parse_json, parse_object


class Request:
    def __init__(self, method, path, query, headers, body):
        self.method, self.path, self.query = method, path, query
        self.headers, self.body = headers, body


class Ctx:
    """What an authenticated handler sees; the global lock is held."""

    def __init__(self, state, user, request, body, params):
        self.state, self.user, self.query = state, user, request.query
        self.body, self.params = body, params


class Route:
    def __init__(self, method, pattern, handler, kind="authed", body="none", idempotent=False,
                 operator=False):
        self.method, self.handler = method, handler
        self.regex = re.compile("^" + pattern + "$")
        self.kind, self.body, self.idempotent = kind, body, idempotent
        self.operator = operator


ROUTES = [
    Route("POST", "/auth/signup", auth.signup, "open"),
    Route("POST", "/auth/login", auth.login, "open"),
    Route("POST", "/_test/reset", testctl.reset, "open"),
    Route("GET", "/_test/export", testctl.export, "open"),
    Route("POST", "/_test/import", testctl.import_, "open"),
    Route("GET", "/me", me.get_me),
    Route("POST", "/payments", payments.create, body="object", idempotent=True),
    Route("POST", "/payments/([^/]+)/corrections", corrections.correct, body="object", idempotent=True),
    Route("GET", "/payments/([^/]+)/revisions", corrections.revisions),
    Route("POST", "/payments/([^/]+)/refunds", refunds.refund, body="object", idempotent=True),
    Route("POST", "/correction-batches", batches.create, body="object", idempotent=True,
          operator=True),
    Route("GET", "/statement", statement.get_statement),
    Route("POST", "/requests", requests.create, body="object", idempotent=True),
    Route("GET", "/requests", requests.list_requests),
    Route("POST", "/requests/([^/]+)/pay", requests.pay, body="optional", idempotent=True),
    Route("POST", "/requests/([^/]+)/decline", requests.decline),
    Route("POST", "/requests/([^/]+)/cancel", requests.cancel),
    Route("POST", "/splits", splits.create, body="object", idempotent=True),
    Route("GET", "/activity", activity.feed),
    Route("POST", "/authorizations", authorizations.create, body="object", idempotent=True),
    Route("GET", "/authorizations", authorizations.list_authorizations),
    Route("POST", "/authorizations/([^/]+)/capture", authorizations.capture, body="optional",
          idempotent=True),
    Route("POST", "/authorizations/([^/]+)/void", authorizations.void),
    Route("POST", "/settlements", settlements.create, body="object", idempotent=True,
          operator=True),
]


def _bearer(headers):
    value = headers.get("Authorization") or ""
    parts = value.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise unauthenticated()
    return parts[1]


def _body(route, raw):
    if route.body == "object":
        return parse_object(raw)
    if route.body == "optional":
        return parse_object(raw) if raw.strip() else {}
    return {}


def _run_authed(holder, route, request, params):
    with holder.lock:
        state = holder.state
        uid = state.tokens.get(_bearer(request.headers))
        user = state.users.get(uid) if uid else None
        if user is None:
            raise unauthenticated()
        if route.operator and uid not in state.operators:
            raise forbidden("settlements require an operator")
        holds.expire_due(state, clock.now().ts)
        body = _body(route, request.body)
        ctx = Ctx(state, user, request, body, params)
        if route.idempotent:
            key = idempotency.read_key(request.headers)
            return idempotency.run(ctx, request, key, route.handler)
        return route.handler(ctx)


def dispatch(holder, request):
    """Returns (status, payload) where payload is a dict, pre-encoded bytes or None."""
    path = request.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    if request.method == "GET":
        served = web.page(path, request.headers.get("Accept")) or web.asset(path)
        if served is not None:
            return 200, served
    path_known = False
    for route in ROUTES:
        match = route.regex.match(path)
        if not match:
            continue
        path_known = True
        if route.method != request.method:
            continue
        params = [unquote(g) for g in match.groups()]
        if route.kind == "open":
            return route.handler(holder, request)
        return _run_authed(holder, route, request, params)
    if path_known:
        raise ApiError(405, "method_not_allowed", "method not allowed")
    if path == "/health" and request.method == "GET":
        return 200, {"status": "ok"}
    raise not_found("no such route")
