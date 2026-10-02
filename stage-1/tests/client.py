"""Tiny stdlib HTTP client shared by the tests."""
import http.client
import json
import os
import urllib.parse
import uuid

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080")
_u = urllib.parse.urlsplit(BASE)


def key():
    return uuid.uuid4().hex


def call(method, path, body=None, token=None, idem=None, raw=None, headers=None, timeout=10):
    conn = http.client.HTTPConnection(_u.hostname, _u.port, timeout=timeout)
    h = dict(headers or {})
    if token:
        h["Authorization"] = "Bearer " + token
    if idem is not None:
        h["Idempotency-Key"] = idem
    data = None
    if raw is not None:
        data = raw if isinstance(raw, bytes) else raw.encode()
        h.setdefault("Content-Type", "application/json")
    elif body is not None:
        data = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    conn.request(method, path, body=data, headers=h)
    r = conn.getresponse()
    payload = r.read()
    ctype = r.getheader("Content-Type")
    conn.close()
    js = json.loads(payload) if payload else None
    return r.status, js, ctype


def user(handle, balance=0, **kw):
    u = {"id": "u_" + handle, "email": handle + "@example.com", "password": "correct horse",
         "display_name": handle.title(), "handle": handle, "balance": balance}
    u.update(kw)
    return u


def fixture(users=None, **kw):
    f = {"currency": "EUR", "minor_units": 2,
         "users": users if users is not None else [user("ada", 10000), user("bob", 2500), user("cy", 500)],
         "payments": [], "requests": []}
    f.update(kw)
    return f


def reset(fx):
    s, b, _ = call("POST", "/_test/reset", fx)
    assert s == 204, (s, b)


def login(handle):
    s, b, _ = call("POST", "/auth/login", {"email": handle + "@example.com", "password": "correct horse"})
    assert s == 200, (s, b)
    return b["token"]


def balance(tok):
    return call("GET", "/me", token=tok)[1]["balance"]
