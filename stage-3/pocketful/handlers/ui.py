"""The browser UI: one HTML shell plus static assets, all served from the image.

The shell renders every screen client-side from the JSON API. `/requests` and
`/authorizations` are shared with the API: HTML only for `Accept: text/html`.
"""
import mimetypes
import os

from ..errors import not_found

UI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")
ALWAYS_UI = ("/", "/split", "/signup", "/login")
SHARED_WITH_API = ("/requests", "/authorizations")
CACHE = {}


class Raw:
    """A non-JSON response body."""

    def __init__(self, body, content_type):
        self.body, self.content_type = body, content_type


def wants_ui(req):
    if req.method != "GET":
        return False
    if req.path in ALWAYS_UI or req.path.startswith("/static/"):
        return True
    return req.path in SHARED_WITH_API and "text/html" in (req.header("Accept") or "")


def _read(name):
    if name not in CACHE:
        with open(os.path.join(UI_DIR, name), "rb") as handle:
            CACHE[name] = handle.read()
    return CACHE[name]


def serve(req):
    if not req.path.startswith("/static/"):
        return 200, Raw(_read("index.html"), "text/html; charset=utf-8")
    name = req.path[len("/static/"):]
    full = os.path.normpath(os.path.join(UI_DIR, name))
    if not full.startswith(UI_DIR + os.sep) or not os.path.isfile(full):
        raise not_found("no such asset")
    rel = os.path.relpath(full, UI_DIR)
    kind = mimetypes.guess_type(full)[0] or "application/octet-stream"
    if kind in ("text/javascript", "application/javascript", "text/css"):
        kind += "; charset=utf-8"
    return 200, Raw(_read(rel), kind)
