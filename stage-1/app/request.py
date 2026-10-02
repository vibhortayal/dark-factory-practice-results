"""Parsed HTTP request handed to route handlers, plus bearer authentication."""
from .errors import ApiError


class Request:
    def __init__(self, method, path, query, headers, raw_body, params=None):
        self.method = method
        self.path = path
        self.query = query
        self.headers = headers
        self.raw_body = raw_body
        self.params = params or {}

    def header(self, name):
        return self.headers.get(name)


def authenticate(req, store):
    """Return the authenticated user dict or raise 401 unauthenticated."""
    header = req.header("Authorization") or ""
    parts = header.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        uid = store.tokens.get(parts[1].strip())
        if uid in store.users:
            return store.users[uid]
    raise ApiError(401, "unauthenticated", "missing or invalid bearer token")
