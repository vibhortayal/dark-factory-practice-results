"""Test helpers: an in-process server on a free port and a tiny JSON client."""
import http.client
import json
import threading

from app.server import make_server


class Api:
    def __init__(self, base=None):
        if base is None:
            self.server = make_server(0, "127.0.0.1")
            self.port = self.server.server_address[1]
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
        else:
            self.port = base
            self.server = None

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def call(self, method, path, body=None, token=None, key=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        hdrs = dict(headers or {})
        if token:
            hdrs["Authorization"] = "Bearer " + token
        if key is not None:
            hdrs["Idempotency-Key"] = key
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        text = resp.read()
        conn.close()
        parsed = json.loads(text) if text else None
        return resp.status, parsed, resp

    def reset(self, fixture):
        status, body, _ = self.call("POST", "/_test/reset", fixture)
        assert status == 204, (status, body)

    def login(self, email, password="correct horse"):
        status, body, _ = self.call("POST", "/auth/login", {"email": email, "password": password})
        assert status == 200, (status, body)
        return body["token"]


def user(handle, balance, uid=None):
    return {"id": uid or "u_" + handle, "email": handle + "@example.com",
            "password": "correct horse", "display_name": handle.title(),
            "handle": handle, "balance": balance}


def fixture(users=None, currency="EUR", minor_units=2, **extra):
    fx = {"currency": currency, "minor_units": minor_units,
          "users": users if users is not None else
          [user("ada", 10000), user("bob", 2500), user("cy", 500)]}
    fx.update(extra)
    return fx
