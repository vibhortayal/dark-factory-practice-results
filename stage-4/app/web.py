"""The browser UI: four HTML screens plus their CSS and JS, all served from the image.

Pages are composed from web/layout.html and web/<page>.html; there are no external
resources. Assets live under /assets/.
"""
from pathlib import Path

ROOT = Path(__file__).parent / "web"
PAGES = {  # route -> (page file, title, page script)
    "/": ("index", "Find a table", "search"),
    "/signup": ("signup", "Create your account", "auth"),
    "/login": ("login", "Log in", "auth"),
    "/lookup": ("lookup", "Look up a booking", "lookup"),
}
JS = "text/javascript; charset=utf-8"
ASSETS = {"app.css": "text/css; charset=utf-8", "common.js": JS, "search.js": JS,
          "auth.js": JS, "lookup.js": JS}


class Raw:
    """A non-JSON response body."""

    def __init__(self, content_type, body):
        self.content_type, self.body = content_type, body


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def _render(route):
    page, title, script = PAGES[route]
    html = _read("layout.html")
    for key, value in (("{{title}}", title), ("{{page}}", page), ("{{script}}", script),
                       ("{{body}}", _read(page + ".html"))):
        html = html.replace(key, value)
    return Raw("text/html; charset=utf-8", html.encode("utf-8"))


_CACHE = {}


def page(route):
    if route not in _CACHE:
        _CACHE[route] = _render(route)
    return _CACHE[route]


def asset(name):
    if name not in _CACHE:
        _CACHE[name] = Raw(ASSETS[name], _read(name).encode("utf-8"))
    return _CACHE[name]
