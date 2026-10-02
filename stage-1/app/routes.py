"""Route table and dispatch. Unknown paths and unsupported methods are 404."""
import re

from . import (handlers_auth, handlers_payments, handlers_requests, handlers_settlements,
               handlers_splits, handlers_testctl)
from .errors import not_found


def _health(req):
    return 200, {"status": "ok"}


_ROUTES = [
    ("GET", "/health", _health),
    ("POST", "/_test/reset", handlers_testctl.reset),
    ("GET", "/_test/export", handlers_testctl.export),
    ("POST", "/_test/import", handlers_testctl.import_state),
    ("POST", "/auth/signup", handlers_auth.signup),
    ("POST", "/auth/login", handlers_auth.login),
    ("GET", "/me", handlers_payments.me),
    ("POST", "/payments", handlers_payments.create_payment),
    ("GET", "/activity", handlers_payments.activity),
    ("POST", "/requests", handlers_requests.create_request),
    ("GET", "/requests", handlers_requests.list_requests),
    ("POST", "/requests/{id}/pay", handlers_requests.pay),
    ("POST", "/requests/{id}/decline", handlers_requests.decline),
    ("POST", "/requests/{id}/cancel", handlers_requests.cancel),
    ("POST", "/splits", handlers_splits.create_split),
    ("POST", "/settlements", handlers_settlements.create_settlement),
]

ROUTES = [(m, re.compile(re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", p)), fn) for m, p, fn in _ROUTES]


def dispatch(req):
    for method, pattern, handler in ROUTES:
        match = pattern.fullmatch(req.path)
        if match and method == req.method:
            req.params = match.groupdict()
            return handler(req)
    raise not_found("no such route")
