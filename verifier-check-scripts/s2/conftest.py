"""Browser fixtures for the stage-2 UI checks (Playwright / Chromium from the kickoff virtualenv)."""
import os
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from lib import BASE, PW, VOUT, violation

VIEWPORTS = {"narrow": {"width": 375, "height": 740}, "wide": {"width": 1280, "height": 800}}
expect.set_options(timeout=6000)


class UI:
    """One browser context with one page, plus a log of what the page did on the network."""

    def __init__(self, browser, viewport="wide", base=BASE):
        self.base = base
        self.origin = "{0.scheme}://{0.netloc}".format(urlsplit(base))
        size = VIEWPORTS[viewport] if isinstance(viewport, str) else viewport
        self.context = browser.new_context(viewport=size, base_url=base)
        self.context.set_default_timeout(8000)
        self.page = self.context.new_page()
        self.requests = []
        self.errors = []
        self.page.on("request", self._on_request)
        self.page.on("response", self._on_response)
        self.page.on("pageerror", self._on_pageerror)

    # ---- recording
    def _on_request(self, req):
        u = urlsplit(req.url)
        if u.scheme in ("data", "blob", "about"):
            return
        origin = f"{u.scheme}://{u.netloc}"
        if origin != self.origin and not getattr(self, "allow_origin", None) == origin:
            violation("external-request", method=req.method, path=req.url[:200], status=0)
        self.requests.append(req)

    def _on_response(self, resp):
        if resp.status >= 500 and not getattr(self, "expect_5xx", False):
            violation("ui-5xx", method=resp.request.method, path=resp.url[:200], status=resp.status)

    def _on_pageerror(self, exc):
        if getattr(self, "ignore_errors", False):
            return
        self.errors.append(str(exc))
        violation("pageerror", method="PAGE", path=self.page.url[:200], status=0, body=str(exc)[:300])

    def sent(self, method, path_suffix):
        """Requests the page sent with this method to a path (query ignored)."""
        return [r for r in self.requests if r.method == method and urlsplit(r.url).path == path_suffix]

    def sent_like(self, method, fragment):
        return [r for r in self.requests if r.method == method and fragment in urlsplit(r.url).path]

    # ---- locating
    def t(self, testid):
        return self.page.get_by_test_id(testid)

    def has(self, testid) -> bool:
        return self.t(testid).count() > 0

    def goto(self, path):
        self.page.goto(path, wait_until="load")
        return self

    # ---- flows
    def login(self, handle, password=PW, email=None):
        self.goto("/login")
        self.t("login-email").fill(email or f"{handle}@example.com")
        self.t("login-password").fill(password)
        self.t("login-submit").click()
        expect(self.t("current-user")).to_be_visible()
        return self

    def home(self):
        self.goto("/")
        expect(self.t("wallet-balance")).to_be_visible()
        return self

    def amount(self, testid) -> int:
        return int(self.t(testid).get_attribute("data-amount"))

    def fill_pay(self, handle, amount, note="", visibility=None, prefix="pay"):
        self.t(f"{prefix}-handle").fill(handle)
        self.t(f"{prefix}-amount").fill(amount)
        if self.has(f"{prefix}-note"):
            self.t(f"{prefix}-note").fill(note)
        if visibility:
            self.t(f"{prefix}-visibility").select_option(visibility)

    def shot(self, name):
        d = os.path.join(VOUT, "shots")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name + ".png")
        self.page.screenshot(path=path, full_page=True)
        return path

    def close(self):
        self.context.close()


@pytest.fixture(scope="session")
def pw_browser():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture()
def ui(pw_browser):
    made = []

    def factory(viewport="wide", base=BASE):
        u = UI(pw_browser, viewport, base)
        made.append(u)
        return u

    yield factory
    for u in made:
        u.close()


@pytest.fixture(params=["narrow", "wide"])
def vp(request):
    return request.param
