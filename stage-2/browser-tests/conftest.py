"""Browser tests for stage 2. They run against a running service (default http://localhost:8080,
override with POCKETFUL_URL) using Playwright's Chromium:

    <kickoff>/.venv/bin/python -m pytest stage-2/browser-tests
"""
import json
import os
import urllib.request

import pytest
from playwright.sync_api import sync_playwright

BASE = os.environ.get("POCKETFUL_URL", "http://localhost:8080")


def call(method, path, body=None, token=None, key=None):
    req = urllib.request.Request(BASE + path, method=method, data=None if body is None else json.dumps(body).encode())
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if key:
        req.add_header("Idempotency-Key", key)
    try:
        with urllib.request.urlopen(req) as res:
            text = res.read().decode()
            return res.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as err:
        text = err.read().decode()
        return err.code, (json.loads(text) if text else None)


def user(uid, handle, name, balance):
    return {"id": f"u_{uid}", "email": f"{uid}@example.com", "password": "correct horse",
            "display_name": name, "handle": handle, "balance": balance}


def fixture(**extra):
    base = {"currency": "EUR", "minor_units": 2,
            "users": [user("ada", "ada", "Ada", 10000), user("bob", "bob", "Bob", 2500), user("cy", "cy", "Cy", 500)]}
    base.update(extra)
    return base


def reset(fx=None):
    status, _ = call("POST", "/_test/reset", fx or fixture())
    assert status == 204


def login_token(uid):
    return call("POST", "/auth/login", {"email": f"{uid}@example.com", "password": "correct horse"})[1]["token"]


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(base_url=BASE, viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    yield pg
    ctx.close()


def sel(name):
    return f"[data-testid='{name}']"


def log_in(page, uid="ada"):
    page.goto("/login")
    page.fill(sel("login-email"), f"{uid}@example.com")
    page.fill(sel("login-password"), "correct horse")
    page.click(sel("login-submit"))
    page.wait_for_selector(sel("current-user"))
