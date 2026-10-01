"""Browser rows (U, L, Y, F, Q, T, R2, G, A2, V) with Playwright/Chromium against BASE_URL.

Run with the Playwright-enabled interpreter, e.g.
  BASE_URL=http://localhost:8080 SHOTS=/tmp/shots <venv>/bin/python -m unittest test_browser -v
"""
import json
import os
import re
import time
import unittest

from playwright.sync_api import sync_playwright, expect

from helpers import BASE, call, fixture, k, login, me, pay, reset, user

SHOTS = os.environ.get("SHOTS")
PW = None
BROWSER = None


def setUpModule():
    global PW, BROWSER
    PW = sync_playwright().start()
    BROWSER = PW.chromium.launch(args=["--no-sandbox"])


def tearDownModule():
    BROWSER.close()
    PW.stop()


def sel(n):
    return f"[data-testid='{n}']"


def money(minor, mu=2, cur="EUR"):
    if mu == 0:
        return f"{minor} {cur}"
    t = str(minor).rjust(mu + 1, "0")
    return f"{t[:-mu]}.{t[-mu:]} {cur}"


class B(unittest.TestCase):
    width = 1280

    def setUp(self):
        reset(fixture())
        self.ctx = BROWSER.new_context(base_url=BASE, viewport={"width": self.width, "height": 900})
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(8000)
        self.posts = []
        self.page.on("request", lambda r: self.posts.append((r.method, r.url, r.post_data)) if r.method == "POST" else None)
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" and "401" not in m.text else None)

    def tearDown(self):
        self.ctx.close()
        self.assertEqual([e for e in self.errors if "Failed to load resource" not in e], [])

    def log_in(self, handle="ada"):
        p = self.page
        p.goto("/login")
        p.fill(sel("login-email"), f"{handle}@example.com")
        p.fill(sel("login-password"), "correct horse")
        p.click(sel("login-submit"))
        p.wait_for_selector(sel("current-user"))
        return p

    def pay_form(self, handle="bob", amount="15.00", note="", vis=None):
        p = self.page
        p.goto("/")
        p.wait_for_selector(sel("pay-submit"))
        p.fill(sel("pay-handle"), handle)
        p.fill(sel("pay-amount"), amount)
        if note:
            p.fill(sel("pay-note"), note)
        if vis:
            p.select_option(sel("pay-visibility"), vis)

    def bal(self, name="wallet-balance"):
        return int(self.page.get_attribute(sel(name), "data-amount"))

    def shot(self, name):
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            self.page.screenshot(path=f"{SHOTS}/{name}-{self.width}.png", full_page=True)

    def no_hscroll(self):
        ok = self.page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        self.assertTrue(ok, "horizontal scroll at " + self.page.url)


class Screens(B):
    def test_routes_signed_out_and_in(self):  # U1 U4 L
        p = self.page
        for r in ("/signup", "/login"):
            p.goto(r)
            p.wait_for_selector(sel(r[1:] + "-submit"))
            self.assertEqual(p.query_selector(sel("current-user")), None)
            self.assertEqual(p.query_selector(sel("auth-error")), None)
        p.goto("/")
        p.wait_for_url("**/login")
        p.goto("/requests")
        p.wait_for_url("**/login")
        self.log_in()
        for route, anchor in (("/", "pay-submit"), ("/requests", "incoming-list"), ("/split", "split-submit"), ("/authorizations", "authorize-submit")):
            p.goto(route)
            p.wait_for_selector(sel(anchor), state="attached")
            self.assertEqual(p.text_content(sel("current-handle")), "ada")
            self.assertIn("Ada", p.text_content(sel("current-user")))
            p.reload()
            p.wait_for_selector(sel("current-user"))
        p.click(sel("logout-button"))
        p.wait_for_selector(sel("current-user"), state="detached")
        p.goto("/")
        p.wait_for_url("**/login")

    def test_signup_login_errors(self):  # L1-L3
        p = self.page
        p.goto("/signup")
        p.fill(sel("signup-email"), "ada@elsewhere.org")
        p.fill(sel("signup-password"), "correct horse")
        p.fill(sel("signup-display-name"), "Other Ada")
        p.click(sel("signup-submit"))
        p.wait_for_selector(sel("auth-error"))
        p.fill(sel("signup-email"), "new.person@example.com")
        p.fill(sel("signup-password"), "short")
        p.click(sel("signup-submit"))
        p.wait_for_selector(sel("auth-error"))
        p.fill(sel("signup-password"), "long enough pw")
        p.click(sel("signup-submit"))
        p.wait_for_selector(sel("current-user"))
        self.assertEqual(p.text_content(sel("current-handle")), "new_person")
        self.assertEqual(self.bal("wallet-balance"), 0)
        self.assertEqual(self.bal("wallet-available"), 0)
        self.assertEqual(p.query_selector(sel("wallet-held")), None)
        p.wait_for_selector(sel("empty-activity"))

    def test_formats_and_headline(self):  # Y1 Y2 A2.1 A2.2
        for cur, mu, exp in (("JPY", 0, "10000 JPY"), ("BHD", 3, "10.000 BHD"), ("EUR", 2, "100.00 EUR")):
            reset(fixture(currency=cur, minor_units=mu))
            self.ctx.clear_cookies()
            self.page.goto("/login")
            self.page.evaluate("localStorage.clear()")
            self.log_in()
            self.page.goto("/")
            self.page.wait_for_selector(sel("wallet-balance"))
            self.assertEqual(self.page.text_content(sel("wallet-balance")).strip(), exp)
            self.assertEqual(self.page.text_content(sel("wallet-available")).strip(), exp)
            self.assertEqual(money(10000, mu, cur), exp)
        # headline: available is the largest monetary text once holds exist
        reset(fixture(authorizations=[{"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000,
                                       "status": "open", "expires_at": "2099-01-01T00:00:00+00:00"}]))
        self.page.evaluate("localStorage.clear()")
        self.log_in()
        self.page.goto("/")
        self.page.wait_for_selector(sel("wallet-held"))
        self.assertEqual(self.page.text_content(sel("wallet-available")).strip(), "80.00 EUR")
        self.assertEqual(self.page.text_content(sel("wallet-balance")).strip(), "100.00 EUR")
        self.assertEqual(self.page.text_content(sel("wallet-held")).strip(), "20.00 EUR")
        self.assertEqual(self.bal("wallet-held"), 2000)
        size = lambda n: float(self.page.eval_on_selector(sel(n), "e => parseFloat(getComputedStyle(e).fontSize)"))
        self.assertGreater(size("wallet-available"), size("wallet-balance") * 1.8)
        self.assertGreater(size("wallet-available"), size("wallet-held") * 1.8)
        self.shot("home-held")


class Pay(B):
    def test_decimals_and_no_request_on_error(self):  # Y4 Y5
        self.log_in()
        self.pay_form(amount="15.5")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='8450']")
        self.assertEqual(self.bal("wallet-available"), 8450)
        n = len(self.posts)
        for bad in ("15.005", "abc", "", "1e3", "-5", "1,5", ".", "15.", "1 5"):
            self.page.fill(sel("pay-amount"), bad)
            self.page.click(sel("pay-submit"))
            self.page.wait_for_selector(sel("pay-error"))
            self.assertEqual(len(self.posts), n, bad)
        self.page.fill(sel("pay-amount"), "15")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='6950']")
        self.assertEqual(self.page.query_selector(sel("pay-error")), None)

    def test_jpy_rejects_decimal_point(self):  # Y4
        reset(fixture(currency="JPY", minor_units=0))
        self.log_in()
        self.pay_form(amount="15.0")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-error"))
        self.assertEqual([p for p in self.posts if "/payments" in p[1]], [])
        self.page.fill(sel("pay-amount"), "15")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='9985']")

    def test_double_submit_once_and_new_payment_on_change(self):  # Y6 Y7
        self.log_in()
        self.pay_form(note="dinner <b>x</b> ", vis="private")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='8500']")
        self.page.click(sel("pay-submit"))
        self.page.click(sel("pay-submit"))
        self.page.wait_for_timeout(500)
        self.assertEqual(self.bal(), 8500)
        self.assertEqual(self.page.query_selector(sel("pay-error")), None)
        self.assertEqual(len(call("GET", "/activity", token=login("ada"))[2]["payments"]), 1)
        self.assertEqual(self.page.input_value(sel("pay-amount")), "15.00")
        self.assertEqual(self.page.input_value(sel("pay-note")), "dinner <b>x</b> ")
        self.page.fill(sel("pay-amount"), "20.00")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='6500']")
        keys = [json.loads(p[2])["amount"] for p in self.posts if p[1].endswith("/payments")]
        self.assertEqual(keys[-1], 2000)
        self.assertTrue(all(x == 1500 for x in keys[:-1]) and len(keys) >= 2, keys)

    def test_rapid_double_click(self):  # Y6
        self.log_in()
        self.pay_form()
        self.page.dblclick(sel("pay-submit"))
        self.page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='8500']")
        self.page.wait_for_timeout(400)
        self.assertEqual(self.bal(), 8500)

    def test_feed_rows(self):  # F1-F7
        a = login("ada")
        notes = ["  spaced  ", "<b>bold</b>", "é café \U0001F600", ""]
        ids = [pay(a, "bob", 100 + i, note=n, visibility="private" if i == 1 else "public")[2]["payment_id"] for i, n in enumerate(notes)]
        pay(login("bob"), "cy", 5, visibility="private")
        pay(login("bob"), "cy", 6, visibility="public")
        self.log_in()
        self.page.goto("/")
        self.page.wait_for_selector(sel("activity-list"))
        for i, pid in enumerate(ids):
            self.assertEqual(self.page.text_content(sel(f"activity-note-{pid}")), notes[i])
            self.assertEqual(self.page.text_content(sel(f"activity-amount-{pid}")).strip(), money(100 + i))
            self.assertEqual(self.page.get_attribute(sel(f"activity-item-{pid}"), "data-visibility"), "private" if i == 1 else "public")
            t = self.page.text_content(sel(f"activity-parties-{pid}"))
            self.assertIn("ada", t)
            self.assertIn("bob", t)
        order = self.page.eval_on_selector_all(f"{sel('activity-list')} > *", "els => els.map(e => e.getAttribute('data-testid'))")
        self.assertEqual(len(order), 5)  # ada's 4 + bob->cy public; bob->cy private hidden
        self.assertEqual(order[0].replace("activity-item-", ""), call("GET", "/activity", token=a)[2]["payments"][0]["payment_id"])
        self.assertEqual(self.page.eval_on_selector(sel("activity-note-" + ids[0]), "e => e.innerHTML"), "  spaced  ")
        self.assertEqual(self.page.eval_on_selector(sel("activity-note-" + ids[1]), "e => e.querySelector('b')"), None)
        self.shot("home-feed")

    def test_refresh_keeps_form_and_unknown_handle_error(self):  # R2.1 Y5
        self.log_in()
        self.pay_form(handle="nobody", amount="1.00", note="hello")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-error"))
        self.shot("pay-error")
        self.page.click(sel("wallet-refresh"))
        self.page.wait_for_timeout(300)
        self.assertEqual(self.page.input_value(sel("pay-note")), "hello")
        self.assertEqual(self.page.input_value(sel("pay-handle")), "nobody")
        pay(login("ada"), "cy", 700)
        self.page.click(sel("wallet-refresh"))
        self.page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='9300']")
        self.assertEqual(self.page.input_value(sel("pay-handle")), "nobody")

    def test_request_form(self):  # Y8
        self.log_in()
        p = self.page
        p.wait_for_selector(sel("request-submit"))
        p.fill(sel("request-handle"), "bob")
        p.fill(sel("request-amount"), "0.005")
        p.click(sel("request-submit"))
        p.wait_for_selector(sel("request-error"))
        p.fill(sel("request-amount"), "12.00")
        p.fill(sel("request-note"), "taxi")
        p.click(sel("request-submit"))
        p.wait_for_selector(sel("request-success"))
        self.assertEqual(p.query_selector(sel("request-error")), None)
        self.assertEqual(call("GET", "/requests?direction=outgoing", token=login("ada"))[2]["requests"][0]["note"], "taxi")
        p.fill(sel("request-handle"), "ada")
        p.click(sel("request-submit"))
        p.wait_for_selector(sel("request-error"))
        p.fill(sel("request-handle"), "ghost")
        p.click(sel("request-submit"))
        p.wait_for_selector(sel("request-error"))


class Competing(B):
    def test_latest_refresh_wins(self):  # R2.2
        self.log_in()
        self.pay_form()
        self.page.wait_for_selector(sel("wallet-balance"))
        state = {"n": 0}
        def handler(route):
            if route.request.url.endswith("/me"):
                state["n"] += 1
                if state["n"] == 1:
                    resp = route.fetch()  # fetch now: stale data, deliver late
                    time.sleep(0)
                    self.page.wait_for_timeout(0)
                    stale = resp.body()
                    def late():
                        route.fulfill(response=resp, body=stale)
                    delayed.append(late)
                    return
            route.continue_()
        delayed = []
        self.page.route("**/me", handler)
        self.page.click(sel("wallet-refresh"))   # first refresh: held back
        self.page.wait_for_timeout(300)
        pay(login("ada"), "cy", 700)
        self.page.click(sel("wallet-refresh"))   # second refresh: fresh
        self.page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='9300']")
        self.assertEqual(len(delayed), 1)
        delayed[0]()                              # now the stale answer arrives
        self.page.wait_for_timeout(500)
        self.assertEqual(self.bal(), 9300)
        self.assertEqual(self.bal("wallet-available"), 9300)

    def test_refused_after_competing_spend(self):  # R2.3
        self.log_in("cy")
        self.pay_form(handle="bob", amount="4.00", note="keep me")
        self.page.wait_for_selector(sel("wallet-balance"))
        pay(login("cy"), "ada", 450)   # another client spends it
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-error"))
        self.page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='50']")
        self.assertEqual(self.page.input_value(sel("pay-note")), "keep me")
        self.assertEqual(self.page.input_value(sel("pay-amount")), "4.00")
        self.assertEqual(self.page.input_value(sel("pay-handle")), "bob")
        self.assertEqual(self.page.query_selector(sel("pay-uncertain")), None)

    def test_stale_request_pay_button(self):  # R2.4 Q-5 Q-6
        rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, login("bob"), k())[2]["request_id"]
        self.log_in()
        self.page.goto("/requests")
        self.page.wait_for_selector(sel(f"request-pay-{rid}"))
        call("POST", f"/requests/{rid}/cancel", token=login("bob"))
        self.assertEqual(self.page.eval_on_selector(f"#rv-{rid}", "e => e.labels.length"), 1)  # V5: visible label
        self.assertTrue(self.page.is_visible(f"label[for='rv-{rid}']"))
        self.page.click(sel(f"request-pay-{rid}"))
        self.page.wait_for_selector(sel("request-error"))
        self.page.wait_for_selector(sel(f"request-pay-{rid}"), state="detached")
        self.assertEqual(self.page.get_attribute(sel(f"request-item-{rid}"), "data-status"), "cancelled")
        self.assertEqual(me(login("ada"))["total"], 10000)

    def test_lost_response_then_same_key_retry(self):  # R2.5 R2.6
        self.log_in()
        self.pay_form(amount="15.00", note="n")
        self.page.wait_for_selector(sel("wallet-balance"))
        calls = []
        def handler(route):
            if route.request.method == "POST" and route.request.url.endswith("/payments"):
                calls.append((route.request.headers.get("idempotency-key"), route.request.post_data))
                if len(calls) == 1:
                    route.fetch()        # the server commits...
                    route.abort()        # ...and the response is lost
                    return
            route.continue_()
        self.page.route("**/*", handler)
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-uncertain"))
        self.assertTrue(self.page.text_content(sel("pay-uncertain")).strip())
        self.assertEqual(self.page.query_selector(sel("pay-error")), None)
        self.shot("pay-uncertain")
        self.assertEqual(me(login("ada"))["total"], 8500)  # it did commit
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-uncertain"), state="detached")
        self.page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='8500']")
        self.assertEqual(self.page.query_selector(sel("pay-error")), None)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(len(call("GET", "/activity", token=login("ada"))[2]["payments"]), 1)
        self.assertEqual(self.page.locator(f"{sel('activity-list')} > *").count(), 1)

    def test_lost_response_before_commit_then_retry(self):  # R2.5
        self.log_in()
        self.pay_form(amount="15.00")
        self.page.wait_for_selector(sel("wallet-balance"))
        n = {"c": 0}
        def handler(route):
            if route.request.method == "POST" and route.request.url.endswith("/payments"):
                n["c"] += 1
                if n["c"] == 1:
                    route.abort()
                    return
            route.continue_()
        self.page.route("**/*", handler)
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-uncertain"))
        self.assertEqual(me(login("ada"))["total"], 10000)
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='8500']")
        self.assertEqual(self.page.query_selector(sel("pay-uncertain")), None)

    def test_upgrade_between_requests(self):  # G2 G3 G4
        rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 250}, login("bob"), k())[2]["request_id"]
        self.log_in()
        self.pay_form(handle="cy", amount="10.00", note="lost")
        self.page.wait_for_selector(sel("wallet-balance"))
        calls = []
        def handler(route):
            if route.request.method == "POST" and route.request.url.endswith("/payments"):
                calls.append(route.request.headers.get("idempotency-key"))
                if len(calls) == 1:
                    route.fetch()
                    route.abort()
                    return
            route.continue_()
        self.page.route("**/*", handler)
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-uncertain"))
        snap = call("GET", "/_test/export")[2]               # export taken after the lost response
        reset(fixture(users=[user("zed", 1)]))              # destination had other data
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        # same page, no reload: still signed in, retry recovers the original payment
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-uncertain"), state="detached")
        self.page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='9000']")
        self.assertEqual(self.page.input_value(sel("pay-note")), "lost")
        self.assertEqual(len(call("GET", "/activity", token=login("ada"))[2]["payments"]), 1)
        self.assertEqual(calls[0], calls[1])
        self.page.goto("/requests")
        self.page.wait_for_selector(sel(f"request-pay-{rid}"))
        self.page.click(sel(f"request-pay-{rid}"))
        self.page.wait_for_selector(f"{sel('request-item-' + rid)}[data-status='paid']")
        self.assertEqual(me(login("ada"))["total"], 8750)


class Requests(B):
    def test_lists_and_actions(self):  # Q
        bob, ada = login("bob"), login("ada")
        r1 = call("POST", "/requests", {"payer_handle": "ada", "amount": 1200, "note": "taxi"}, bob, k())[2]["request_id"]
        r2 = call("POST", "/requests", {"payer_handle": "ada", "amount": 300}, bob, k())[2]["request_id"]
        r3 = call("POST", "/requests", {"payer_handle": "bob", "amount": 50, "note": "out"}, ada, k())[2]["request_id"]
        self.log_in()
        p = self.page
        p.goto("/requests")
        p.wait_for_selector(sel(f"request-item-{r1}"))
        self.assertEqual(p.query_selector(sel("empty-requests")), None)
        inc = p.eval_on_selector_all(f"{sel('incoming-list')} > *", "els => els.map(e => e.getAttribute('data-testid'))")
        out = p.eval_on_selector_all(f"{sel('outgoing-list')} > *", "els => els.map(e => e.getAttribute('data-testid'))")
        self.assertEqual(inc, [f"request-item-{r2}", f"request-item-{r1}"])
        self.assertEqual(out, [f"request-item-{r3}"])
        self.assertEqual(p.text_content(sel(f"request-amount-{r1}")).strip(), "12.00 EUR")
        self.assertIsNone(p.query_selector(sel(f"request-cancel-{r1}")))
        self.assertIsNone(p.query_selector(sel(f"request-pay-{r3}")))
        self.assertIsNone(p.query_selector(sel(f"request-decline-{r3}")))
        self.shot("requests")
        p.click(sel(f"request-decline-{r2}"))
        p.wait_for_selector(f"{sel('request-item-' + r2)}[data-status='declined']")
        self.assertIsNone(p.query_selector(sel(f"request-pay-{r2}")))
        p.click(sel(f"request-cancel-{r3}"))
        p.wait_for_selector(f"{sel('request-item-' + r3)}[data-status='cancelled']")
        p.click(sel(f"request-pay-{r1}"))
        p.wait_for_selector(f"{sel('request-item-' + r1)}[data-status='paid']")
        self.assertEqual(p.get_attribute(sel("wallet-balance"), "data-amount"), "8800")

    def test_empty_and_insufficient(self):  # Q-6 Q-7
        self.log_in()
        self.page.goto("/requests")
        self.page.wait_for_selector(sel("empty-requests"))
        self.assertEqual(self.page.query_selector(sel("request-error")), None)
        rid = call("POST", "/requests", {"payer_handle": "cy", "amount": 900000}, login("ada"), k())[2]["request_id"]
        self.page.evaluate("localStorage.clear()")
        self.log_in("cy")
        self.page.goto("/requests")
        self.page.click(sel(f"request-pay-{rid}"))
        self.page.wait_for_selector(sel("request-error"))
        self.assertEqual(self.page.get_attribute(sel(f"request-item-{rid}"), "data-status"), "pending")


class Split(B):
    def test_preview_and_submit(self):  # T
        self.log_in()
        p = self.page
        p.goto("/split")
        p.fill(sel("split-amount"), "10.00")
        p.fill(sel("split-handles"), "ada, bob,cy")
        shares = [p.text_content(sel(f"split-share-{h}")).strip() for h in ("ada", "bob", "cy")]
        self.assertEqual(shares, [money(334), money(333), money(333)])
        p.fill(sel("split-handles"), "cy,bob,ada")
        self.assertEqual(p.text_content(sel("split-share-cy")).strip(), money(334))
        self.assertEqual(p.text_content(sel("split-share-ada")).strip(), money(333))
        p.fill(sel("split-amount"), "0.01")
        self.assertEqual(p.text_content(sel("split-share-cy")).strip(), money(1))
        self.assertEqual(p.text_content(sel("split-share-bob")).strip(), money(0))
        p.fill(sel("split-amount"), "10.00")
        p.fill(sel("split-handles"), "ada,bob,cy")
        self.assertEqual([x for x in self.posts if 'auth' not in x[1]], [])
        p.fill(sel("split-note"), "dinner")
        p.click(sel("split-submit"))
        p.wait_for_selector(sel("split-success"))
        self.assertEqual([r["amount"] for r in call("GET", "/requests", token=login("bob"))[2]["requests"]], [333])
        self.assertEqual([r["amount"] for r in call("GET", "/requests", token=login("cy"))[2]["requests"]], [333])
        self.shot("split")
        p.fill(sel("split-handles"), "ada,ghost")
        p.click(sel("split-submit"))
        p.wait_for_selector(sel("split-error"))
        p.fill(sel("split-amount"), "10.005")
        p.click(sel("split-submit"))
        p.wait_for_selector(sel("split-error"))
        p.fill(sel("split-amount"), "10.00")
        p.fill(sel("split-handles"), "bob,bob")
        p.click(sel("split-submit"))
        p.wait_for_selector(sel("split-error"))


class Authorizations(B):
    def test_flow(self):  # A2.3-A2.9
        self.log_in()
        p = self.page
        p.goto("/authorizations")
        p.wait_for_selector(sel("empty-authorizations"))
        p.fill(sel("authorize-handle"), "bob")
        p.fill(sel("authorize-amount"), "20.00")
        p.fill(sel("authorize-note"), "deposit")
        p.select_option(sel("authorize-visibility"), "private")
        p.click(sel("authorize-submit"))
        p.wait_for_selector(f"{sel('wallet-held')}[data-amount='2000']")
        self.assertEqual(self.bal("wallet-available"), 8000)
        self.assertEqual(self.bal("wallet-balance"), 10000)
        item = p.locator("[data-testid^='authorization-item-']")
        item.first.wait_for()
        aid = item.first.get_attribute("data-testid").replace("authorization-item-", "")
        self.assertEqual(item.first.get_attribute("data-status"), "open")
        self.assertEqual(p.text_content(sel(f"authorization-amount-{aid}")).strip(), "20.00 EUR")
        exp = p.text_content(sel(f"authorization-expires-{aid}")).strip()
        self.assertEqual(exp, call("GET", "/authorizations", token=login("ada"))[2]["authorizations"][0]["expires_at"])
        self.assertIsNotNone(p.query_selector(sel(f"authorization-void-{aid}")))
        self.assertIsNone(p.query_selector(sel(f"authorization-capture-{aid}")))
        self.assertIsNone(p.query_selector(sel(f"authorization-captured-{aid}")))
        self.assertIsNone(p.query_selector(sel("empty-authorizations")))
        self.shot("auth-ada")
        p.fill(sel("authorize-amount"), "100.01")
        p.click(sel("authorize-submit"))
        p.wait_for_selector(sel("authorize-error"))
        p.fill(sel("authorize-amount"), "1.001")
        p.click(sel("authorize-submit"))
        p.wait_for_selector(sel("authorize-error"))
        # bob captures part, keeping the rest on hold, then the rest
        self.page.evaluate("localStorage.clear()")
        self.log_in("bob")
        p.goto("/authorizations")
        p.wait_for_selector(sel(f"authorization-capture-{aid}"))
        self.assertEqual(p.input_value(sel(f"authorization-capture-amount-{aid}")), "20.00")
        self.assertIsNone(p.query_selector(sel(f"authorization-void-{aid}")))
        self.shot("auth-bob")
        p.fill(sel(f"authorization-capture-amount-{aid}"), "7.00")
        p.check(f"#keep-{aid}")
        p.click(sel(f"authorization-capture-{aid}"))
        p.wait_for_selector(f"{sel('authorization-amount-' + aid)}")
        p.wait_for_function(f"document.querySelector(\"[data-testid='authorization-capture-amount-{aid}']\").value === '13.00'")
        self.assertEqual(p.get_attribute(sel(f"authorization-item-{aid}"), "data-status"), "open")
        p.fill(sel(f"authorization-capture-amount-{aid}"), "99.00")
        p.click(sel(f"authorization-capture-{aid}"))
        p.wait_for_selector(sel("authorization-error"))
        p.fill(sel(f"authorization-capture-amount-{aid}"), "13.00")
        p.click(sel(f"authorization-capture-{aid}"))
        p.wait_for_selector(f"{sel('authorization-item-' + aid)}[data-status='captured']")
        self.assertEqual(p.text_content(sel(f"authorization-captured-{aid}")).strip(), "20.00 EUR")
        self.assertIsNone(p.query_selector(sel(f"authorization-capture-{aid}")))
        self.assertEqual(self.bal("wallet-balance"), 4500)
        self.assertEqual(self.bal("wallet-available"), 4500)
        self.assertIsNone(p.query_selector(sel("wallet-held")))

    def test_void_and_expiry_in_ui(self):  # A2.8 Z16
        reset(fixture(authorization_ttl_seconds=2))
        self.log_in()
        p = self.page
        p.goto("/authorizations")
        for amt in ("10.00", "5.00"):
            p.fill(sel("authorize-handle"), "bob")
            p.fill(sel("authorize-amount"), amt)
            p.click(sel("authorize-submit"))
            p.wait_for_selector(sel("authorize-success"))
            p.fill(sel("authorize-amount"), "6.00" if amt == "10.00" else amt)
        p.wait_for_selector(f"{sel('wallet-held')}[data-amount='1500']") if False else None
        p.wait_for_timeout(2600)
        p.reload()
        p.wait_for_selector("[data-testid^='authorization-item-']")
        statuses = p.eval_on_selector_all("[data-testid^='authorization-item-']", "els => els.map(e => e.getAttribute('data-status'))")
        self.assertEqual(set(statuses), {"expired"})
        self.assertEqual(self.bal("wallet-available"), 10000)
        self.assertIsNone(p.query_selector(sel("wallet-held")))
        # void path
        reset(fixture())
        p.evaluate("localStorage.clear()")
        self.log_in()
        p.goto("/authorizations")
        p.fill(sel("authorize-handle"), "bob")
        p.fill(sel("authorize-amount"), "3.00")
        p.click(sel("authorize-submit"))
        btn = p.locator("[data-testid^='authorization-void-']")
        btn.wait_for()
        btn.click()
        p.wait_for_selector("[data-status='voided']")
        self.assertIsNone(p.query_selector(sel("wallet-held")))
        self.assertEqual(self.bal("wallet-available"), 10000)

    def test_capture_refused_shows_error(self):  # A2.8
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 500}, login("ada"), k())[2]
        aid = a["authorization_id"]
        self.log_in("bob")
        self.page.goto("/authorizations")
        self.page.wait_for_selector(sel(f"authorization-capture-{aid}"))
        call("POST", f"/authorizations/{aid}/void", token=login("ada"))
        self.page.click(sel(f"authorization-capture-{aid}"))
        self.page.wait_for_selector(sel("authorization-error"))
        self.page.wait_for_selector(f"{sel('authorization-item-' + aid)}[data-status='voided']")
        self.assertIsNone(self.page.query_selector(sel(f"authorization-capture-{aid}")))

    def test_seeded_hold_shown_after_reset(self):  # A2.10
        reset(fixture(authorizations=[{"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit",
                                       "status": "open", "expires_at": "2099-01-01T00:00:00+00:00"}]))
        self.log_in()
        self.page.goto("/")
        self.page.wait_for_selector(sel("wallet-held"))
        self.assertEqual(self.bal("wallet-available"), 8000)
        self.page.goto("/authorizations")
        self.page.wait_for_selector(sel("authorization-item-a_1"))
        self.assertEqual(self.page.text_content(sel("authorization-expires-a_1")).strip(), "2099-01-01T00:00:00+00:00")


class AuthorizeFormOnBothRoutes(B):  # S2-8 / A2.3
    def test_home_and_authorizations(self):
        for route in ("/", "/authorizations"):
            reset(fixture())
            self.page.evaluate("localStorage.clear()") if self.page.url != "about:blank" else None
            self.log_in()
            p = self.page
            p.goto(route)
            p.wait_for_selector(sel("authorize-submit"))
            for t in ("authorize-handle", "authorize-amount", "authorize-note", "authorize-visibility", "authorize-submit"):
                self.assertEqual(p.locator(sel(t)).count(), 1, (route, t))
            self.assertEqual(p.locator(sel("authorize-error")).count(), 0)
            p.fill(sel("authorize-handle"), "bob")
            p.fill(sel("authorize-amount"), "100.01")
            p.click(sel("authorize-submit"))
            p.wait_for_selector(sel("authorize-error"))      # more than available
            p.fill(sel("authorize-amount"), "1.001")
            p.click(sel("authorize-submit"))
            p.wait_for_selector(sel("authorize-error"))
            p.fill(sel("authorize-amount"), "20.00")
            p.fill(sel("authorize-note"), "deposit")
            p.select_option(sel("authorize-visibility"), "private")
            if route == "/":
                p.fill(sel("pay-handle"), "cy")
                p.fill(sel("pay-amount"), "1.00")
            p.click(sel("authorize-submit"))
            p.wait_for_selector(f"{sel('wallet-held')}[data-amount='2000']")
            self.assertEqual(self.bal("wallet-available"), 8000)
            self.assertEqual(self.bal("wallet-balance"), 10000)
            if route == "/":
                self.assertEqual(p.input_value(sel("pay-handle")), "cy")
                self.assertEqual(p.input_value(sel("pay-amount")), "1.00")
                self.assertEqual(p.query_selector(sel("activity-list")), None)  # holds are not feed items
            else:
                p.wait_for_selector("[data-testid^='authorization-item-']")
            a = call("GET", "/authorizations", token=login("ada"))[2]["authorizations"]
            self.assertEqual((len(a), a[0]["note"], a[0]["visibility"], a[0]["amount"]), (1, "deposit", "private", 2000))
            self.shot("home-with-authorize" if route == "/" else "auth-page")


class Narrow(B):
    width = 375

    def test_no_horizontal_scroll_and_shots(self):  # V4
        long = "w" * 20
        a = login("ada")
        for i in range(4):
            pay(a, "bob", 100, note="a very long note " + "x" * 190)
        call("POST", "/requests", {"payer_handle": "bob", "amount": 100, "note": "y" * 200}, a, k())
        call("POST", "/authorizations", {"to_handle": "bob", "amount": 100, "note": "z" * 200}, a, k())
        for r in ("/login", "/signup"):
            self.page.goto(r)
            self.page.wait_for_selector("form")
            self.no_hscroll()
            self.shot("route" + r.replace("/", "-"))
        self.log_in()
        for r in ("/", "/requests", "/split", "/authorizations"):
            self.page.goto(r)
            self.page.wait_for_selector(sel("current-user"))
            self.page.wait_for_timeout(500)
            self.no_hscroll()
            self.shot("route" + (r.replace("/", "-") if r != "/" else "-home"))
        self.page.goto("/split")
        self.page.fill(sel("split-amount"), "1.00")
        self.page.fill(sel("split-handles"), "ada,bob,cy")
        self.no_hscroll()


class Wide(Narrow):
    width = 1280


class Accessibility(B):
    def test_labels_focus_and_keyboard(self):  # V5
        self.page.goto("/login")
        self.page.wait_for_selector(sel("login-email"))
        for t in ("login-email", "login-password"):
            lbl = self.page.eval_on_selector(sel(t), "e => e.labels.length")
            self.assertEqual(lbl, 1, t)
        # keyboard-only login
        self.page.focus(sel("login-email"))
        self.page.keyboard.type("ada@example.com")
        self.page.keyboard.press("Tab")
        self.page.keyboard.type("correct horse")
        self.page.keyboard.press("Enter")
        self.page.wait_for_selector(sel("current-user"))
        self.page.wait_for_selector(sel("pay-submit"))
        for t in ("pay-handle", "pay-amount", "pay-note", "pay-visibility", "request-handle", "request-amount", "request-note"):
            self.assertEqual(self.page.eval_on_selector(sel(t), "e => e.labels.length"), 1, t)
        self.page.focus(sel("pay-handle"))
        outline = self.page.eval_on_selector(sel("pay-handle"), "e => getComputedStyle(e).outlineStyle + ' ' + getComputedStyle(e).outlineWidth")
        self.assertIn("solid", outline)
        self.page.focus(sel("pay-submit"))
        outline = self.page.eval_on_selector(sel("pay-submit"), "e => getComputedStyle(e).outlineStyle + ' ' + getComputedStyle(e).outlineWidth")
        self.assertIn("solid", outline)

    def test_contrast(self):  # V5 (computed)
        reset(fixture(authorizations=[{"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000,
                                       "status": "open", "expires_at": "2099-01-01T00:00:00+00:00"}]))
        pay(login("ada"), "bob", 5, note="n", visibility="private")
        call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, login("bob"), k())
        self.log_in()
        script = """
        () => {
          function lum(c){ const m=c.match(/[\\d.]+/g).map(Number); const a=m.slice(0,3).map(v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)}); return 0.2126*a[0]+0.7152*a[1]+0.0722*a[2]; }
          function bg(e){ while(e){ const c=getComputedStyle(e).backgroundColor; const m=c.match(/[\\d.]+/g); if(m && (m.length<4 || parseFloat(m[3])>0.99)) return c; if(getComputedStyle(e).backgroundImage!=='none') return 'IMG'; e=e.parentElement;} return 'rgb(255,255,255)'; }
          const bad=[]; const seen=new Set();
          document.querySelectorAll('body *').forEach(e=>{
            if(!e.childNodes.length) return;
            const own=[...e.childNodes].filter(n=>n.nodeType===3 && n.textContent.trim()).length; if(!own) return;
            const cs=getComputedStyle(e); if(cs.visibility==='hidden'||cs.display==='none') return;
            const b=bg(e); if(b==='IMG') return;
            const l1=lum(cs.color), l2=lum(b); const r=(Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05);
            const size=parseFloat(cs.fontSize), bold=parseInt(cs.fontWeight)>=700;
            const need=(size>=24||(size>=18.66&&bold))?3:4.5;
            if(r<need){ const k=e.tagName+e.className+r.toFixed(2); if(!seen.has(k)){seen.add(k); bad.push([e.tagName,e.className,e.textContent.trim().slice(0,30),r.toFixed(2),cs.color,b]);} }
          });
          return bad;
        }
        """
        for route in ("/", "/requests", "/authorizations", "/split"):
            self.page.goto(route)
            self.page.wait_for_selector(sel("current-user"))
            self.page.wait_for_timeout(400)
            bad = self.page.evaluate(script)
            self.assertEqual(bad, [], route)


if __name__ == "__main__":
    unittest.main()
