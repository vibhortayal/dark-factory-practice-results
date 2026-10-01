import http.client
import json
import os
import urllib.parse
import uuid

BASE = os.environ.get("BASE_URL", "http://localhost:8080")
_u = urllib.parse.urlsplit(BASE)
HOST, PORT = _u.hostname, _u.port or 80


def call(method, path, body=None, token=None, key=None, raw=None, headers=None):
    """Returns (status, response headers, parsed JSON or None, raw bytes)."""
    h = dict(headers or {})
    if token:
        h["Authorization"] = "Bearer " + token
    if key is not None:
        h["Idempotency-Key"] = key
    data = raw
    if raw is None and body is not None:
        data = json.dumps(body).encode()
    if data is not None:
        h["Content-Type"] = "application/json"
    conn = http.client.HTTPConnection(HOST, PORT, timeout=10)
    try:
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        payload = r.read()
        try:
            parsed = json.loads(payload) if payload else None
        except ValueError:
            parsed = None  # HTML or other non-JSON body
        return r.status, dict(r.getheaders()), parsed, payload
    finally:
        conn.close()


def k():
    return uuid.uuid4().hex


def user(handle, balance, uid=None, pw="correct horse"):
    return {"id": uid or "u_" + handle, "email": handle + "@example.com", "password": pw,
            "display_name": handle.title(), "handle": handle, "balance": balance}


def fixture(users=None, currency="EUR", minor_units=2, **extra):
    d = {"currency": currency, "minor_units": minor_units,
         "users": users if users is not None else [user("ada", 10000), user("bob", 2500),
                                                   user("cy", 500)],
         "payments": [], "requests": []}
    d.update(extra)
    return d


def reset(fx):
    s, _, b, _ = call("POST", "/_test/reset", fx)
    assert s == 204, (s, b)


def login(handle, pw="correct horse"):
    s, _, b, _ = call("POST", "/auth/login", {"email": handle + "@example.com", "password": pw})
    assert s == 200, (s, b)
    return b["token"]


def me(tok):
    return call("GET", "/me", token=tok)[2]


def pay(tok, to, amount, key=None, **extra):
    body = {"to_handle": to, "amount": amount}
    body.update(extra)
    return call("POST", "/payments", body, tok, key or k())
