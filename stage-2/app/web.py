"""Serving the browser UI: page shells (content negotiation) and static assets."""
import os

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
PAGES = {"/", "/requests", "/split", "/signup", "/login", "/authorizations"}
SHARED_WITH_API = {"/requests", "/authorizations"}   # HTML only when the client asks for it
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}


class Raw:
    """A pre-encoded, non-JSON response body."""

    def __init__(self, body: bytes, content_type: str):
        self.body, self.content_type = body, content_type


def wants_html(accept) -> bool:
    return "text/html" in (accept or "").lower()


def _read(relative: str):
    path = os.path.realpath(os.path.join(UI_DIR, relative))
    if not path.startswith(UI_DIR + os.sep) or not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1]
    if ext not in CONTENT_TYPES:
        return None
    with open(path, "rb") as handle:
        return Raw(handle.read(), CONTENT_TYPES[ext])


def page(path: str, accept):
    """The HTML shell for a screen route, or None when the API should answer instead."""
    if path not in PAGES or (path in SHARED_WITH_API and not wants_html(accept)):
        return None
    return _read("index.html")


def asset(path: str):
    if not path.startswith("/ui/"):
        return None
    return _read(path[len("/ui/"):])
