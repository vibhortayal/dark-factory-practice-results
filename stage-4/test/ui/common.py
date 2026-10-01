"""Shared helpers for the browser tests (Python Playwright, sync API).

Run against a container you started yourself: BASE_URL=http://127.0.0.1:18080
"""
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080")


def api(method, path, body=None, token=None, key=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if key:
        req.add_header("Idempotency-Key", key)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as r:
            text = r.read().decode()
            return r.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        return e.code, (json.loads(text) if text else None)


def user(uid, handle, balance=10000, name=None):
    return {"id": uid, "email": f"{handle}@example.com", "password": "correct horse",
            "display_name": name or handle.title(), "handle": handle, "balance": balance}


def fixture(**extra):
    fx = {"currency": "EUR", "minor_units": 2,
          "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500), user("u_cy", "cy", 0)]}
    fx.update(extra)
    return fx


def reset(fx=None):
    status, body = api("POST", "/_test/reset", fx or fixture())
    assert status == 204, (status, body)


def iso(delta_seconds):
    t = datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    return t.isoformat(timespec="microseconds")


def token_for(handle):
    status, body = api("POST", "/auth/login", {"email": f"{handle}@example.com", "password": "correct horse"})
    assert status == 200, body
    return body["token"]


def ui_login(page, handle):
    page.goto(BASE + "/login")
    page.get_by_test_id("login-email").fill(f"{handle}@example.com")
    page.get_by_test_id("login-password").fill("correct horse")
    page.get_by_test_id("login-submit").click()
    page.get_by_test_id("wallet-balance").wait_for()


def with_session(page, handle):
    """Sign in by planting the token the way the app stores it (fast path for tests)."""
    token = token_for(handle)
    page.goto(BASE + "/login")
    page.evaluate("t => localStorage.setItem('pocketful.session', JSON.stringify({token: t}))", token)
    return token
