"""Route table and dispatch: (method, path pattern) -> handler, auth on or off."""
import re

from .errors import ApiError
from . import holds
from .handlers import (activity, auth, authorizations, me, payments, requests, settlements,
                       splits, testctl, ui)
from .store import store

# (method, pattern, handler, requires_auth)
ROUTES = [
    ("GET", r"/health", lambda req: (200, {"status": "ok"}), False),
    ("POST", r"/_test/reset", testctl.reset, False),
    ("GET", r"/_test/export", testctl.export_state, False),
    ("POST", r"/_test/import", testctl.import_state, False),
    ("POST", r"/auth/signup", auth.signup, False),
    ("POST", r"/auth/login", auth.login, False),
    ("GET", r"/me", me.get_me, True),
    ("POST", r"/payments", payments.create_payment, True),
    ("POST", r"/requests", requests.create_request, True),
    ("GET", r"/requests", requests.list_requests, True),
    ("POST", r"/requests/([^/]+)/pay", requests.pay_request, True),
    ("POST", r"/requests/([^/]+)/decline", requests.decline_request, True),
    ("POST", r"/requests/([^/]+)/cancel", requests.cancel_request, True),
    ("POST", r"/splits", splits.create_split, True),
    ("POST", r"/settlements", settlements.create_settlement, True),
    ("GET", r"/activity", activity.get_activity, True),
    ("POST", r"/authorizations", authorizations.create_authorization, True),
    ("GET", r"/authorizations", authorizations.list_authorizations, True),
    ("POST", r"/authorizations/([^/]+)/capture", authorizations.capture_authorization, True),
    ("POST", r"/authorizations/([^/]+)/void", authorizations.void_authorization, True),
]
COMPILED = [(m, re.compile(p), h, a) for m, p, h, a in ROUTES]


def dispatch(req):
    """Return (status, body). Raises ApiError for every expected failure."""
    if ui.wants_ui(req):
        return ui.serve(req)
    with store.lock:
        holds.sweep()  # every request sees clock expiry, even with no request at the deadline
    path_matched = False
    for method, pattern, handler, needs_auth in COMPILED:
        found = pattern.fullmatch(req.path)
        if not found:
            continue
        path_matched = True
        if method != req.method:
            continue
        req.params = found.groups()
        if needs_auth:
            req.user_id = auth.authenticate(req)
        return handler(req)
    if path_matched:
        raise ApiError(405, "method_not_allowed", "method not allowed on this path")
    raise ApiError(404, "not_found", "no such route")
