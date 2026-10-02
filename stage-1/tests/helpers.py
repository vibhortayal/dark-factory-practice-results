"""Test support: an in-process server and a tiny JSON HTTP client."""
import http.client
import json
import os
import sys
import threading
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pocketful.server import make_server  # noqa: E402

_server = None


def server_port():
    global _server
    if _server is None:
        _server = make_server(0, "127.0.0.1")
        threading.Thread(target=_server.serve_forever, daemon=True).start()
    return _server.server_address[1]


class Resp:
    def __init__(self, status, headers, raw):
        self.status, self.headers, self.raw = status, headers, raw
        self.json = json.loads(raw) if raw else None

    @property
    def code(self):
        return self.json["error"]["code"] if self.json and "error" in self.json else None


def call(method, path, body=None, token=None, key=None, raw=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server_port(), timeout=10)
    hdrs = dict(headers or {})
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if key is not None:
        hdrs["Idempotency-Key"] = key
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    conn.request(method, path, body=data, headers=hdrs)
    r = conn.getresponse()
    resp = Resp(r.status, dict(r.getheaders()), r.read())
    conn.close()
    return resp


def user(uid, handle, balance, **extra):
    return {"id": uid, "email": f"{handle}@example.com", "password": "correct horse",
            "display_name": handle.title(), "handle": handle, "balance": balance, **extra}


def fixture(**extra):
    base = {"currency": "EUR", "minor_units": 2,
            "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500),
                      user("u_cy", "cy", 500)]}
    base.update(extra)
    return base


class World(unittest.TestCase):
    """Resets to the three-user fixture and logs everyone in."""
    fixture_extra = {}

    def setUp(self):
        self.fx = fixture(**self.fixture_extra)
        self.assertEqual(call("POST", "/_test/reset", self.fx).status, 204)
        self.tok = {}
        for u in self.fx["users"]:
            r = call("POST", "/auth/login", {"email": u["email"], "password": "correct horse"})
            self.tok[u["handle"]] = r.json["token"]
        self.total = sum(u["balance"] for u in self.fx["users"])

    def post(self, who, path, body=None, key="auto", **kw):
        if key == "auto":
            key = uuid.uuid4().hex
        return call("POST", path, body, token=self.tok[who] if who else None, key=key, **kw)

    def get(self, who, path):
        return call("GET", path, token=self.tok[who])

    def balance(self, who):
        return self.get(who, "/me").json["balance"]

    def assertErr(self, resp, status, code):
        self.assertEqual((resp.status, resp.code), (status, code), resp.raw)

    def assertConserved(self):
        self.assertEqual(sum(self.balance(h) for h in self.tok), self.total)
