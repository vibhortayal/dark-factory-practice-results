"""Test client: boots the real server in-process on a free port and talks plain HTTP."""
import http.client
import json
import threading
import unittest
import uuid

from app.server import Handler, Server

_server = Server(("127.0.0.1", 0), Handler)
threading.Thread(target=_server.serve_forever, daemon=True).start()
PORT = _server.server_address[1]


def call(method, path, body=None, token=None, key=None, raw=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    hdrs = dict(headers or {})
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if key is not None:
        hdrs["Idempotency-Key"] = key
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    text = resp.read()
    conn.close()
    parsed = json.loads(text) if text else None
    return resp.status, parsed, resp


def user(uid, handle, balance, email=None):
    return {"id": uid, "email": email or f"{handle}@example.com", "password": "correct horse",
            "display_name": handle.title(), "handle": handle, "balance": balance}


def fixture(**extra):
    base = {"currency": "EUR", "minor_units": 2,
            "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500),
                      user("u_cy", "cy", 0)]}
    base.update(extra)
    return base


class Api(unittest.TestCase):
    def reset(self, fx=None):
        status, _, _ = call("POST", "/_test/reset", fx or fixture())
        self.assertEqual(status, 204)
        self.tok = {}
        for u in (fx or fixture())["users"]:
            self.tok[u["handle"]] = self.login(u["email"])

    def login(self, email, password="correct horse"):
        status, body, _ = call("POST", "/auth/login", {"email": email, "password": password})
        self.assertEqual(status, 200, body)
        return body["token"]

    def setUp(self):
        self.reset()

    def req(self, who, method, path, body=None, key="auto", **kw):
        if key == "auto":
            key = uuid.uuid4().hex if method == "POST" else None
        return call(method, path, body, token=self.tok.get(who, who), key=key, **kw)

    def ok(self, who, method, path, body=None, status=201, **kw):
        s, b, _ = self.req(who, method, path, body, **kw)
        self.assertEqual(s, status, b)
        return b

    def err(self, who, method, path, body, status, code, **kw):
        s, b, resp = self.req(who, method, path, body, **kw)
        self.assertEqual((s, b["error"]["code"]), (status, code), b)
        self.assertEqual(resp.getheader("Content-Type"), "application/json; charset=utf-8")

    def balance(self, who):
        return self.ok(who, "GET", "/me", status=200)["balance"]

    def total(self):
        return sum(self.balance(h) for h in self.tok)
