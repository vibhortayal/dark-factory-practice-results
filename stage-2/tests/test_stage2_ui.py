"""Own browser tests for the Pocketful stage-2 UI (real Chromium through Playwright).

Run with the Python that has Playwright, e.g. the kickoff checkout's .venv:
  BASE_URL=http://127.0.0.1:8080 BASE_URL_PREV=http://127.0.0.1:8081 SHOTS=/some/dir  python tests/test_stage2_ui.py
BASE_URL_PREV (optional) is a stage-1 container used by the upgrade test.
Elements are found by data-testid only.
"""
import json
import os
import re
import time
import unittest
from urllib.parse import urlsplit

from playwright import sync_api as pw

import test_stage1 as t1
from test_stage1 import call, fixture, nk, reset, user

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080")
PREV = os.environ.get("BASE_URL_PREV")
SHOTS = os.environ.get("SHOTS", "/tmp/pocketful-shots")


def sel(name):
    return "[data-testid='%s']" % name


def money(minor, mu=2, cur="EUR"):
    if mu == 0:
        return "%d %s" % (minor, cur)
    t = str(minor).rjust(mu + 1, "0")
    return "%s.%s %s" % (t[:-mu], t[-mu:], cur)


def seed(**kw):
    fx = fixture(users=[user("ada", 10000, display_name="Ada"), user("bob", 2500, display_name="Bob"),
                        user("cy", 500, display_name="Cy")])
    fx.update(kw)
    return fx


class UI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pwx = pw.sync_playwright().start()
        cls.browser = cls.pwx.chromium.launch(channel="chromium")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pwx.stop()

    def setUp(self):
        self.ctx = self.browser.new_context(base_url=BASE, viewport={"width": 1280, "height": 900})
        self.page = self.ctx.new_page()
        self.requests = []
        self.ctx.on("request", lambda r: self.requests.append(r))
        self.fixture = seed()
        reset(self.fixture)

    def tearDown(self):
        self.ctx.close()

    # helpers
    def login(self, who="ada", page=None, password="correct horse"):
        p = page or self.page
        p.goto("/login")
        p.fill(sel("login-email"), who + "@example.com")
        p.fill(sel("login-password"), password)
        p.click(sel("login-submit"))
        p.wait_for_function("h => { const e = document.querySelector(\"[data-testid='current-handle']\"); return e && e.textContent.trim() === h && location.pathname === '/'; }", arg=who)

    def token(self, who="ada", base=None):
        return call("POST", "/auth/login", {"email": who + "@example.com", "password": "correct horse"}, base=base)[1]["token"]

    def text(self, tid, page=None):
        return (page or self.page).text_content(sel(tid)).strip()

    def amount_attr(self, tid):
        return self.page.get_attribute(sel(tid), "data-amount")

    def posts(self, path):
        return [r for r in self.requests if r.method == "POST" and urlsplit(r.url).path == path]

    # ------------------------------------------------------------ routes / shell
    def test_all_routes_and_layout(self):
        os.makedirs(SHOTS, exist_ok=True)
        long_note = "A very long note with an_unbroken_token_" + "x" * 100 + " and more words to wrap onto lines"
        reset(seed(
            users=[user("ada", 10 ** 12, display_name="Ada Lovelace"), user("bob", 2500, display_name="Bob"),
                   user("a_very_long_handle_1", 500, display_name="Long Name " + "N" * 60)],
            payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": long_note, "visibility": "public"},
                      {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1234, "note": "lunch", "visibility": "private"},
                      {"id": "p_3", "from_user_id": "u_bob", "to_user_id": "u_a_very_long_handle_1", "amount": 99, "note": "", "visibility": "public"}],
            requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": long_note, "status": "pending"},
                      {"id": "rq_2", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 300, "note": "tickets", "status": "pending"},
                      {"id": "rq_3", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 50, "note": "", "status": "paid"}],
            authorizations=[
                {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit " + long_note, "visibility": "public",
                 "status": "open", "expires_at": "2099-01-01T00:00:00+00:00"},
                {"id": "a_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 750, "note": "hotel", "visibility": "private",
                 "status": "open", "expires_at": "2099-01-01T00:00:00+00:00"},
                {"id": "a_3", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "note": "done", "visibility": "public",
                 "status": "captured", "expires_at": "2099-01-01T00:00:00+00:00"},
                {"id": "a_4", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "note": "late", "visibility": "public",
                 "status": "open", "expires_at": "2020-01-01T00:00:00+00:00"}]))
        for width, height in ((375, 800), (768, 900), (1280, 900), (1920, 1000)):
            ctx = self.browser.new_context(base_url=BASE, viewport={"width": width, "height": height})
            page = ctx.new_page()
            self.login("ada", page)
            for route, anchor in (("/", "pay-submit"), ("/requests", "incoming-list"), ("/split", "split-submit"),
                                  ("/authorizations", "authorization-list"), ("/login", "login-submit"),
                                  ("/signup", "signup-submit")):
                page.goto(route)
                page.wait_for_selector(sel(anchor))
                page.wait_for_timeout(200)
                for tid in ("current-user", "current-handle", "logout-button"):
                    self.assertTrue(page.is_visible(sel(tid)), (route, tid))
                self.assertEqual(page.text_content(sel("current-handle")).strip(), "ada")
                self.assertIn("Ada", page.text_content(sel("current-user")))
                sw = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
                self.assertLessEqual(sw[0], sw[1], (route, width, sw))
                if width in (375, 1280):
                    page.screenshot(path="%s/%s-%d.png" % (SHOTS, route.strip("/") or "home", width), full_page=True)
            ctx.close()
        # signed-out shots
        for route in ("/login", "/signup"):
            ctx = self.browser.new_context(base_url=BASE, viewport={"width": 375, "height": 800})
            page = ctx.new_page()
            page.goto(route)
            page.wait_for_selector(sel(route.strip("/") + "-submit"))
            page.screenshot(path="%s/%s-signedout-375.png" % (SHOTS, route.strip("/")), full_page=True)
            ctx.close()

    def test_no_external_requests_and_no_console_errors(self):
        errors = []
        self.page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        self.page.on("pageerror", lambda e: errors.append(str(e)))
        self.login()
        for route in ("/", "/requests", "/split", "/authorizations", "/signup", "/login"):
            self.page.goto(route)
            self.page.wait_for_load_state("networkidle")
        origin = urlsplit(BASE)
        for r in self.requests:
            u = urlsplit(r.url)
            self.assertEqual((u.scheme, u.netloc), (origin.scheme, origin.netloc), r.url)
        self.assertEqual(errors, [])

    def test_signed_out_redirect_and_auth_flows(self):
        for route in ("/", "/requests", "/split", "/authorizations"):
            self.page.goto(route)
            self.page.wait_for_selector(sel("login-submit"))
            self.assertEqual(urlsplit(self.page.url).path, "/login")
            self.assertIsNone(self.page.query_selector(sel("current-user")))
        self.assertIsNone(self.page.query_selector(sel("auth-error")))
        self.page.fill(sel("login-email"), "ada@example.com")
        self.page.fill(sel("login-password"), "wrong wrong")
        self.page.click(sel("login-submit"))
        self.page.wait_for_selector(sel("auth-error"))
        self.page.fill(sel("login-password"), "correct horse")
        self.page.click(sel("login-submit"))
        self.page.wait_for_selector(sel("current-user"))
        self.assertIsNone(self.page.query_selector(sel("auth-error")))
        for route in ("/requests", "/split", "/authorizations", "/"):
            self.page.goto(route)
            self.page.wait_for_selector(sel("current-user"))
        self.page.click(sel("logout-button"))
        self.page.wait_for_selector(sel("current-user"), state="detached")
        self.page.goto("/requests")
        self.page.wait_for_selector(sel("login-submit"))
        # signup errors and success
        self.page.goto("/signup")
        for email, pw_, code in (("ada@example.com", "longenough1", "taken"), ("ADA@other.example.com", "longenough1", "handle"),
                                 ("new@example.com", "short", "short"), ("nodomain", "longenough1", "email")):
            self.page.fill(sel("signup-email"), email)
            self.page.fill(sel("signup-password"), pw_)
            self.page.fill(sel("signup-display-name"), "N")
            self.page.click(sel("signup-submit"))
            self.page.wait_for_selector(sel("auth-error"))
        self.page.fill(sel("signup-email"), "Dee.Ann+x@example.com")
        self.page.fill(sel("signup-password"), "longenough1")
        self.page.fill(sel("signup-display-name"), "Dee")
        self.page.click(sel("signup-submit"))
        self.page.wait_for_selector(sel("current-user"))
        self.assertEqual(self.text("current-handle"), "dee_ann_x")
        self.page.goto("/login")  # forms render when signed in too
        self.page.wait_for_selector(sel("login-submit"))
        self.assertTrue(self.page.is_visible(sel("current-user")))

    # --------------------------------------------------------------- pay form
    def pay(self, handle="bob", amount="15.00", note=None, vis=None):
        self.page.goto("/")
        self.page.wait_for_selector(sel("pay-submit"))
        self.page.fill(sel("pay-handle"), handle)
        self.page.fill(sel("pay-amount"), amount)
        if note is not None:
            self.page.fill(sel("pay-note"), note)
        if vis:
            self.page.select_option(sel("pay-visibility"), vis)
        self.page.click(sel("pay-submit"))

    def test_decimal_rule_and_request_log(self):
        self.login()
        self.pay(amount="15.005")
        self.page.wait_for_selector(sel("pay-error"))
        for bad in ("abc", "", "1.", ".5", "-5", "1e3", "1,5", "15.123", "+5", "1 5"):
            self.page.fill(sel("pay-amount"), bad)
            self.page.click(sel("pay-submit"))
            self.page.wait_for_selector(sel("pay-error"))
        self.assertEqual(self.posts("/payments"), [])
        for typed, minor in (("15", 1500), ("15.5", 1550), ("0.29", 29), ("  7.07 ", 707), ("1234567.89", 123456789)):
            before = self.amount_attr("wallet-balance")
            self.page.fill(sel("pay-amount"), typed)
            self.page.click(sel("pay-submit"))
            if typed == "1234567.89":  # more than the wallet holds: the server refuses; the body is still exact
                self.page.wait_for_selector(sel("pay-error"))
                break
            self.page.wait_for_function("n => document.querySelector(\"[data-testid='wallet-balance']\").getAttribute('data-amount') !== n", arg=before)
            body = json.loads(self.posts("/payments")[-1].post_data)
            self.assertEqual(body["amount"], minor, typed) if typed != "1234567.89" else None
            if typed == "1234567.89":
                break
        self.assertEqual(json.loads(self.posts("/payments")[-1].post_data)["amount"], 123456789)

    def test_minor_units_zero_and_three(self):
        for cur, mu, bal, typed, expect in (("JPY", 0, 1200, "15", 15), ("BHD", 3, 1234, "1.234", 1234)):
            reset(seed(currency=cur, minor_units=mu, users=[user("ada", bal, display_name="Ada"), user("bob", 5, display_name="Bob")]))
            self.login()
            self.page.goto("/")
            self.page.wait_for_selector(sel("wallet-balance"))
            self.assertEqual(self.text("wallet-balance"), money(bal, mu, cur))
            self.assertEqual(self.text("wallet-available"), money(bal, mu, cur))
            self.pay(amount="1.5" if mu == 0 else "1.2345")
            self.page.wait_for_selector(sel("pay-error"))
            self.pay(amount=typed)
            self.page.wait_for_selector("%s[data-amount='%d']" % (sel("wallet-balance"), bal - expect))
            self.assertEqual(self.text("wallet-balance"), money(bal - expect, mu, cur))
            self.page.click(sel("logout-button"))

    def test_big_values_exact(self):
        big = 2 ** 53 - 1
        reset(seed(users=[user("ada", big, display_name="Ada"), user("bob", 0, display_name="Bob")]))
        self.login()
        self.page.goto("/")
        self.page.wait_for_selector(sel("wallet-balance"))
        self.assertEqual(self.text("wallet-balance"), money(big))
        self.assertEqual(self.amount_attr("wallet-balance"), str(big))

    def test_double_submit_is_replay(self):
        self.login()
        self.pay(amount="15.00", note="dinner", vis="private")
        self.page.wait_for_selector("%s[data-amount='8500']" % sel("wallet-balance"))
        self.page.click(sel("pay-submit"))
        self.page.dblclick(sel("pay-submit"))
        for _ in range(3):
            self.page.click(sel("pay-submit"))
        self.page.wait_for_timeout(600)
        self.assertIsNone(self.page.query_selector(sel("pay-error")))
        self.assertEqual(self.amount_attr("wallet-balance"), "8500")
        ps = self.posts("/payments")
        self.assertGreaterEqual(len(ps), 2)
        self.assertEqual({r.headers["idempotency-key"] for r in ps}, {ps[0].headers["idempotency-key"]})
        self.assertEqual({r.post_data for r in ps}, {ps[0].post_data})
        items = self.page.query_selector_all("[data-testid^='activity-item-']")
        self.assertEqual(len(items), 1)
        self.assertEqual(self.page.get_attribute("[data-testid^='activity-item-']", "data-visibility"), "private")
        # form kept its values
        self.assertEqual(self.page.input_value(sel("pay-amount")), "15.00")
        self.assertEqual(self.page.input_value(sel("pay-handle")), "bob")
        # changing a field mints a new key; edit away and back counts as a change
        self.page.fill(sel("pay-amount"), "20.00")
        self.page.fill(sel("pay-amount"), "15.00")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector("%s[data-amount='7000']" % sel("wallet-balance"))
        keys = {r.headers["idempotency-key"] for r in self.posts("/payments")}
        self.assertEqual(len(keys), 2)

    def test_refused_payment_preserves_inputs_and_refreshes(self):
        self.login()
        self.page.goto("/")
        self.page.wait_for_selector(sel("pay-submit"))
        # another client spends the balance
        ada = self.token("ada")
        call("POST", "/payments", {"to_handle": "cy", "amount": 9900}, ada, nk())
        self.page.fill(sel("pay-handle"), "bob")
        self.page.fill(sel("pay-amount"), "50.00")
        self.page.fill(sel("pay-note"), "keep me")
        self.page.select_option(sel("pay-visibility"), "private")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-error"))
        self.page.wait_for_selector("%s[data-amount='100']" % sel("wallet-balance"))
        self.assertEqual([self.page.input_value(sel(x)) for x in ("pay-handle", "pay-amount", "pay-note", "pay-visibility")],
                         ["bob", "50.00", "keep me", "private"])
        self.assertTrue(self.page.query_selector("[data-testid^='activity-item-']"))
        self.assertIsNone(self.page.query_selector(sel("pay-uncertain")))
        # unknown handle and self payment are refusals too
        for handle in ("nobody", "ada"):
            self.page.fill(sel("pay-handle"), handle)
            self.page.fill(sel("pay-amount"), "0.01")
            self.page.click(sel("pay-submit"))
            self.page.wait_for_selector(sel("pay-error"))

    def test_latest_refresh_wins(self):
        self.login()
        self.page.goto("/")
        self.page.wait_for_selector(sel("wallet-balance"))
        count = {"n": 0}

        def handler(route):
            path = urlsplit(route.request.url).path
            if path in ("/me", "/activity"):
                count["n"] += 1
                n = count["n"]
                resp = route.fetch()
                if n <= 2:  # the first refresh (both reads) is delayed
                    time.sleep(1.6)
                route.fulfill(response=resp)
            else:
                route.continue_()
        self.page.route("**/*", lambda r: handler(r) if r.request.resource_type in ("fetch", "xhr") else r.continue_())
        self.page.click(sel("wallet-refresh"))  # slow, sees 10000
        self.page.wait_for_timeout(200)
        call("POST", "/payments", {"to_handle": "bob", "amount": 700}, self.token("ada"), nk())
        self.page.click(sel("wallet-refresh"))  # fast, sees 9300
        self.page.wait_for_selector("%s[data-amount='9300']" % sel("wallet-balance"))
        self.page.wait_for_timeout(2500)
        self.assertEqual(self.amount_attr("wallet-balance"), "9300")
        self.assertEqual(self.amount_attr("wallet-available"), "9300")

    def test_refresh_keeps_form(self):
        self.login()
        self.page.goto("/")
        self.page.fill(sel("pay-handle"), "bob")
        self.page.fill(sel("pay-amount"), "3.00")
        call("POST", "/payments", {"to_handle": "cy", "amount": 100}, self.token("ada"), nk())
        self.page.click(sel("wallet-refresh"))
        self.page.wait_for_selector("%s[data-amount='9900']" % sel("wallet-balance"))
        self.assertEqual(self.page.input_value(sel("pay-amount")), "3.00")

    def test_lost_response_is_uncertain_and_retry_is_exactly_once(self):
        self.login()
        self.page.goto("/")
        self.page.wait_for_selector(sel("pay-submit"))
        mode = {"lose": True}

        def handler(route):
            if route.request.method == "POST" and urlsplit(route.request.url).path == "/payments" and mode["lose"]:
                route.fetch()  # forwarded: the payment commits
                route.abort()
            else:
                route.continue_()
        self.page.route("**/payments", handler)
        self.pay(amount="15.00", note="lost")
        self.page.wait_for_selector(sel("pay-uncertain"))
        self.assertTrue(self.text("pay-uncertain"))
        self.assertIsNone(self.page.query_selector(sel("pay-error")))
        self.assertEqual(self.page.input_value(sel("pay-amount")), "15.00")
        mode["lose"] = False
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-uncertain"), state="detached")
        self.page.wait_for_selector("%s[data-amount='8500']" % sel("wallet-balance"))
        self.assertIsNone(self.page.query_selector(sel("pay-error")))
        ps = self.posts("/payments")
        self.assertEqual(len(ps), 2)
        self.assertEqual(ps[0].headers["idempotency-key"], ps[1].headers["idempotency-key"])
        self.assertEqual(ps[0].post_data, ps[1].post_data)
        self.assertEqual(len(self.page.query_selector_all("[data-testid^='activity-item-']")), 1)
        # also: a lost response before commit; a 500; an unreadable body
        for kind in ("abort", "500", "garbage"):
            self.page.unroute("**/payments")

            def h2(route, kind=kind):
                if route.request.method != "POST":
                    return route.continue_()
                if kind == "abort":
                    return route.abort()
                if kind == "500":
                    return route.fulfill(status=500, body="boom")
                return route.fulfill(status=201, body="not json", content_type="application/json")
            self.page.route("**/payments", h2)
            self.page.fill(sel("pay-amount"), "1.00" if kind == "abort" else ("2.00" if kind == "500" else "3.00"))
            self.page.click(sel("pay-submit"))
            self.page.wait_for_selector(sel("pay-uncertain"))
            self.assertIsNone(self.page.query_selector(sel("pay-error")))

    # ---------------------------------------------------------------- feed
    def test_feed_text_and_markup_safety(self):
        evil = "<img src=x onerror=\"window.__pwned=1\"> <b>bold</b> & \"q\" 'a'\n  spaced  \U0001F600"
        weird_id = "p'\"<x> y"
        reset(seed(payments=[{"id": weird_id, "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 5, "note": evil, "visibility": "public"}]))
        self.login()
        self.page.goto("/")
        el = "[data-testid=\"activity-note-%s\"]" % weird_id.replace("\\", "\\\\").replace('"', '\\"')
        self.page.wait_for_selector(el)
        self.assertEqual(self.page.text_content(el), evil)
        self.assertIsNone(self.page.evaluate("window.__pwned"))
        self.assertEqual(self.page.query_selector_all("img"), [])
        item = self.page.get_attribute("[data-testid^='activity-item-']", "data-testid")
        self.assertEqual(item, "activity-item-" + weird_id)
        self.assertIn("bob", self.page.text_content("[data-testid^='activity-parties-']"))
        self.assertIn("ada", self.page.text_content("[data-testid^='activity-parties-']"))
        self.assertEqual(self.page.text_content("[data-testid^='activity-amount-']").strip(), money(5))

    def test_feed_order_visibility_and_empty(self):
        self.login("cy")
        self.page.goto("/")
        self.page.wait_for_selector(sel("empty-activity"))
        self.assertIsNone(self.page.query_selector(sel("activity-list")))
        ada, bob = self.token("ada"), self.token("bob")
        ids = [call("POST", "/payments", {"to_handle": "bob", "amount": 10 + i, "visibility": "public" if i % 2 else "private"}, ada, nk())[1]["payment_id"]
               for i in range(5)]
        self.login("ada")
        self.page.goto("/")
        self.page.wait_for_selector(sel("activity-list"))
        order = self.page.eval_on_selector_all("[data-testid='activity-list'] > *", "els => els.map(e => e.getAttribute('data-testid'))")
        self.assertEqual(sorted(order), sorted("activity-item-" + i for i in ids))
        self.assertEqual(order, ["activity-item-" + i for i in reversed(ids)])
        vis = self.page.eval_on_selector_all("[data-testid^='activity-item-']", "els => els.map(e => e.getAttribute('data-visibility'))")
        self.assertEqual(vis, ["private", "public", "private", "public", "private"])
        # opens an empty note
        call("POST", "/payments", {"to_handle": "bob", "amount": 1}, ada, nk())
        self.page.click(sel("wallet-refresh"))
        self.page.wait_for_function("document.querySelectorAll(\"[data-testid^='activity-item-']\").length === 6")
        notes = self.page.eval_on_selector_all("[data-testid^='activity-note-']", "els => els.map(e => e.textContent)")
        self.assertEqual(notes, [""] * 6)

    def test_many_payments_all_pages(self):
        ada = self.token("ada")
        reset(seed(users=[user("ada", 10 ** 6, display_name="Ada"), user("bob", 0, display_name="Bob")],
                   payments=[{"id": "s%d" % i, "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1, "note": "n", "visibility": "public"}
                             for i in range(450)]))
        self.login()
        self.page.goto("/")
        self.page.wait_for_function("document.querySelectorAll(\"[data-testid^='activity-item-']\").length === 450")

    # ------------------------------------------------------------- requests
    def test_requests_screen(self):
        ada, bob, cy = self.token("ada"), self.token("bob"), self.token("cy")
        r_in = call("POST", "/requests", {"payer_handle": "ada", "amount": 1200, "note": "taxi"}, bob, nk())[1]["request_id"]
        r_in2 = call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, bob, nk())[1]["request_id"]
        r_in3 = call("POST", "/requests", {"payer_handle": "ada", "amount": 77}, bob, nk())[1]["request_id"]
        r_out = call("POST", "/requests", {"payer_handle": "bob", "amount": 300}, ada, nk())[1]["request_id"]
        sp = call("POST", "/splits", {"amount": 1, "participant_handles": ["bob", "ada", "cy"]}, bob, nk())[1]
        zero = [r for r in sp["requests"] if r["payer_handle"] == "ada"][0]
        self.login()
        self.page.goto("/requests")
        self.page.wait_for_selector(sel("request-item-" + r_in))
        self.assertIsNone(self.page.query_selector(sel("empty-requests")))
        self.assertEqual(self.text("request-amount-" + zero["request_id"]), "0.00 EUR")
        self.assertEqual(self.page.get_attribute(sel("request-item-" + r_in), "data-status"), "pending")
        self.assertIsNone(self.page.query_selector(sel("request-cancel-" + r_in)))
        self.assertIsNone(self.page.query_selector(sel("request-pay-" + r_out)))
        self.assertIsNone(self.page.query_selector(sel("request-decline-" + r_out)))
        # items sit in the right list
        inc = self.page.eval_on_selector_all("[data-testid='incoming-list'] > *", "els => els.map(e => e.getAttribute('data-testid'))")
        out = self.page.eval_on_selector_all("[data-testid='outgoing-list'] > *", "els => els.map(e => e.getAttribute('data-testid'))")
        self.assertIn("request-item-" + r_in, inc)
        self.assertIn("request-item-" + r_out, out)
        self.page.click(sel("request-pay-" + r_in))
        self.page.wait_for_selector("%s[data-status='paid']" % sel("request-item-" + r_in))
        self.assertIsNone(self.page.query_selector(sel("request-pay-" + r_in)))
        self.assertEqual(call("GET", "/me", token=ada)[1]["balance"], 8800)
        self.page.click(sel("request-decline-" + r_in2))
        self.page.wait_for_selector("%s[data-status='declined']" % sel("request-item-" + r_in2))
        self.page.click(sel("request-cancel-" + r_out))
        self.page.wait_for_selector("%s[data-status='cancelled']" % sel("request-item-" + r_out))
        self.assertIsNone(self.page.query_selector(sel("request-error")))
        # cancelled elsewhere while the pay button is visible
        call("POST", "/requests/%s/cancel" % r_in3, None, bob)
        self.page.click(sel("request-pay-" + r_in3))
        self.page.wait_for_selector(sel("request-error"))
        self.page.wait_for_selector("%s[data-status='cancelled']" % sel("request-item-" + r_in3))
        self.assertIsNone(self.page.query_selector(sel("request-pay-" + r_in3)))
        # insufficient funds
        big = call("POST", "/requests", {"payer_handle": "cy", "amount": 90000}, ada, nk())[1]["request_id"]
        self.login("cy")
        self.page.goto("/requests")
        self.page.click(sel("request-pay-" + big))
        self.page.wait_for_selector(sel("request-error"))
        self.assertEqual(self.page.get_attribute(sel("request-item-" + big), "data-status"), "pending")

    def test_empty_requests(self):
        self.login()
        self.page.goto("/requests")
        self.page.wait_for_selector(sel("empty-requests"))
        self.assertTrue(self.page.query_selector(sel("incoming-list")) is not None)

    def test_request_form_on_home(self):
        self.login()
        self.page.goto("/")
        self.page.wait_for_selector(sel("request-submit"))
        for h, a in (("nobody", "5"), ("ada", "5"), ("bob", "x"), ("bob", "0")):
            self.page.fill(sel("request-handle"), h)
            self.page.fill(sel("request-amount"), a)
            self.page.click(sel("request-submit"))
            self.page.wait_for_selector(sel("request-error"))
        self.page.fill(sel("request-handle"), "bob")
        self.page.fill(sel("request-amount"), "2.50")
        self.page.fill(sel("request-note"), "snacks")
        self.page.click(sel("request-submit"))
        self.page.wait_for_selector(sel("request-error"), state="detached")
        bob = self.token("bob")
        rs = call("GET", "/requests", token=bob)[1]["requests"]
        self.assertEqual([(r["amount"], r["note"], r["payer_handle"]) for r in rs], [(250, "snacks", "bob")])

    # --------------------------------------------------------------- split
    def test_split_preview_and_submit(self):
        self.login()
        self.page.goto("/split")
        self.page.fill(sel("split-amount"), "10.00")
        self.page.fill(sel("split-handles"), " ada , bob,cy ")
        self.page.wait_for_selector(sel("split-preview"))
        shares = [self.text("split-share-" + h) for h in ("ada", "bob", "cy")]
        self.assertEqual(shares, [money(334), money(333), money(333)])
        self.page.fill(sel("split-handles"), "cy,bob,ada")
        self.assertEqual(self.text("split-share-cy"), money(334))
        self.assertEqual(self.text("split-share-ada"), money(333))
        self.page.fill(sel("split-amount"), "0.01")
        self.assertEqual([self.text("split-share-" + h) for h in ("cy", "bob", "ada")], [money(1), money(0), money(0)])
        self.page.fill(sel("split-amount"), "x")
        self.assertIsNone(self.page.query_selector(sel("split-preview")))
        self.page.fill(sel("split-amount"), "10.00")
        self.page.fill(sel("split-handles"), "bob,cy")
        self.assertEqual([self.text("split-share-" + h) for h in ("bob", "cy")], [money(500), money(500)])
        self.page.fill(sel("split-note"), "dinner")
        self.page.click(sel("split-submit"))
        self.page.wait_for_selector(sel("split-success"))
        bob = self.token("bob")
        rs = call("GET", "/requests", token=bob)[1]["requests"]
        self.assertEqual([(r["amount"], r["note"]) for r in rs], [(500, "dinner")])
        # double click replays
        self.page.click(sel("split-submit"))
        self.page.wait_for_timeout(400)
        self.assertEqual(len(call("GET", "/requests", token=bob)[1]["requests"]), 1)
        self.assertEqual(len({r.headers["idempotency-key"] for r in self.posts("/splits")}), 1)
        # preview equals the server's answer
        body = json.loads(self.posts("/splits")[-1].post_data)
        self.assertEqual(body["participant_handles"], ["bob", "cy"])

    def test_split_errors(self):
        self.login()
        self.page.goto("/split")
        for amount, hs in (("10.00", "ada,nobody"), ("10.00", "bob,bob"), ("10.00", ""), ("0", "bob"), ("10.00", "ada")):
            self.page.fill(sel("split-amount"), amount)
            self.page.fill(sel("split-handles"), hs)
            self.page.click(sel("split-submit"))
            if amount == "10.00" and hs == "ada":
                self.page.wait_for_selector(sel("split-success"))
            else:
                self.page.wait_for_selector(sel("split-error"))
        self.page.fill(sel("split-amount"), "10.005")
        self.page.fill(sel("split-handles"), "bob")
        n = len(self.posts("/splits"))
        self.page.click(sel("split-submit"))
        self.page.wait_for_selector(sel("split-error"))
        self.assertEqual(len(self.posts("/splits")), n)

    # ------------------------------------------------------ authorizations
    def test_wallet_numbers_and_seeded_holds(self):
        reset(seed(authorizations=[
            {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit", "visibility": "public",
             "status": "open", "expires_at": "2099-01-01T00:00:00+00:00"}]))
        self.login()
        self.page.goto("/")
        self.page.wait_for_selector(sel("wallet-available"))
        self.assertEqual(self.text("wallet-available"), "80.00 EUR")
        self.assertEqual(self.amount_attr("wallet-available"), "8000")
        self.assertEqual(self.text("wallet-balance"), "100.00 EUR")
        self.assertEqual(self.amount_attr("wallet-balance"), "10000")
        self.assertEqual(self.text("wallet-held"), "20.00 EUR")
        self.assertEqual(self.amount_attr("wallet-held"), "2000")
        # headline: available is the largest text
        sizes = self.page.evaluate("""() => ['wallet-available','wallet-balance','wallet-held'].map(t =>
            parseFloat(getComputedStyle(document.querySelector("[data-testid='" + t + "']")).fontSize))""")
        self.assertGreater(sizes[0], sizes[1])
        self.assertGreater(sizes[0], sizes[2])
        # a pay above available is refused
        self.pay(amount="90.00")
        self.page.wait_for_selector(sel("pay-error"))
        self.pay(amount="80.00")
        self.page.wait_for_selector("%s[data-amount='0']" % sel("wallet-available"))
        # no hold -> no wallet-held
        self.login("cy")
        self.page.goto("/")
        self.page.wait_for_selector(sel("wallet-available"))
        self.assertIsNone(self.page.query_selector(sel("wallet-held")))
        self.assertEqual(self.text("wallet-available"), self.text("wallet-balance"))

    def test_authorize_form_and_list(self):
        self.login()
        self.page.goto("/")
        self.page.wait_for_selector(sel("authorize-submit"))
        for h, a in (("nobody", "5"), ("ada", "5"), ("bob", "abc"), ("bob", "999.00"), ("bob", "5.005")):
            self.page.fill(sel("authorize-handle"), h)
            self.page.fill(sel("authorize-amount"), a)
            self.page.click(sel("authorize-submit"))
            self.page.wait_for_selector(sel("authorize-error"))
        self.assertEqual(len(self.posts("/authorizations")), 3)
        self.page.fill(sel("authorize-handle"), "bob")
        self.page.fill(sel("authorize-amount"), "20.00")
        self.page.fill(sel("authorize-note"), "deposit")
        self.page.select_option(sel("authorize-visibility"), "private")
        self.page.click(sel("authorize-submit"))
        self.page.wait_for_selector("%s[data-amount='2000']" % sel("wallet-held"))
        self.assertEqual(self.amount_attr("wallet-available"), "8000")
        self.assertIsNone(self.page.query_selector(sel("authorize-error")))
        self.page.click(sel("authorize-submit"))  # replay
        self.page.wait_for_timeout(400)
        self.assertEqual(self.amount_attr("wallet-held"), "2000")
        self.assertEqual(len({r.headers["idempotency-key"] for r in self.posts("/authorizations")[-2:]}), 1)
        self.page.goto("/authorizations")
        self.page.wait_for_selector(sel("authorization-list"))
        item = self.page.query_selector("[data-testid^='authorization-item-']")
        aid = item.get_attribute("data-testid")[len("authorization-item-"):]
        self.assertEqual(item.get_attribute("data-status"), "open")
        self.assertEqual(self.text("authorization-amount-" + aid), "20.00 EUR")
        self.assertRegex(self.text("authorization-expires-" + aid), r"^\d{4}-\d\d-\d\dT.*[+-]\d\d:\d\d$")
        self.assertIsNone(self.page.query_selector(sel("authorization-captured-" + aid)))
        self.assertIsNone(self.page.query_selector(sel("authorization-capture-" + aid)))
        self.assertTrue(self.page.query_selector(sel("authorization-void-" + aid)))
        self.assertEqual(self.text("wallet-held"), "20.00 EUR")
        self.page.click(sel("authorization-void-" + aid))
        self.page.wait_for_selector("%s[data-status='voided']" % sel("authorization-item-" + aid))
        self.assertIsNone(self.page.query_selector(sel("wallet-held")))
        self.assertIsNone(self.page.query_selector(sel("authorization-void-" + aid)))
        self.assertEqual(self.text("wallet-available"), "100.00 EUR")

    def test_capture_flow(self):
        ada, bob = self.token("ada"), self.token("bob")
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 2000, "note": "dep"}, ada, nk())[1]["authorization_id"]
        b = call("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, ada, nk())[1]["authorization_id"]
        self.login("bob")
        self.page.goto("/authorizations")
        self.page.wait_for_selector(sel("authorization-item-" + a))
        self.assertEqual(self.page.input_value(sel("authorization-capture-amount-" + a)), "20.00")
        self.assertIsNone(self.page.query_selector(sel("authorization-void-" + a)))
        self.page.fill(sel("authorization-capture-amount-" + a), "15.00")
        self.page.click(sel("authorization-capture-" + a))
        self.page.wait_for_selector("%s[data-status='captured']" % sel("authorization-item-" + a))
        self.assertEqual(self.text("authorization-captured-" + a), "15.00 EUR")
        self.assertEqual(self.text("authorization-amount-" + a), "20.00 EUR")
        self.assertIsNone(self.page.query_selector(sel("authorization-capture-" + a)))
        self.assertIsNone(self.page.query_selector(sel("authorization-capture-amount-" + a)))
        self.assertEqual(call("GET", "/me", token=ada)[1]["available"], 10000 - 1500 - 1000)
        # extended capture via the checkbox; over-capture is refused
        self.page.fill(sel("authorization-capture-amount-" + b), "20.00")
        self.page.click(sel("authorization-capture-" + b))
        self.page.wait_for_selector(sel("authorization-error"))
        self.assertEqual(self.page.get_attribute(sel("authorization-item-" + b), "data-status"), "open")
        self.page.fill(sel("authorization-capture-amount-" + b), "3.00")
        self.page.check("#keep-" + b)
        self.page.click(sel("authorization-capture-" + b))
        self.page.wait_for_function("document.querySelector(\"[data-testid='authorization-capture-amount-%s']\").value === '7.00'" % b)
        self.assertEqual(self.page.get_attribute(sel("authorization-item-" + b), "data-status"), "open")
        self.assertIsNone(self.page.query_selector(sel("authorization-error")))
        self.assertEqual(self.amount_attr("wallet-balance"), "%d" % (2500 + 1500 + 300))
        # voided elsewhere while collectable
        call("POST", "/authorizations/%s/void" % b, None, ada)
        self.page.click(sel("authorization-capture-" + b))
        self.page.wait_for_selector(sel("authorization-error"))
        self.page.wait_for_selector("%s[data-status='voided']" % sel("authorization-item-" + b))
        # payments created by captures show up in the feed
        self.page.goto("/")
        self.page.wait_for_function("document.querySelectorAll(\"[data-testid^='activity-item-']\").length === 2")
        amounts = sorted(self.page.eval_on_selector_all("[data-testid^='activity-amount-']", "els => els.map(e => e.textContent)"))
        self.assertEqual(amounts, ["15.00 EUR", "3.00 EUR"])

    def test_expiry_by_clock_in_ui(self):
        reset(seed(authorization_ttl_seconds=2))
        ada = self.token("ada")
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 4000}, ada, nk())[1]["authorization_id"]
        self.login()
        self.page.goto("/authorizations")
        self.page.wait_for_selector("%s[data-status='open']" % sel("authorization-item-" + a))
        self.assertEqual(self.text("wallet-held"), "40.00 EUR")
        self.page.wait_for_selector("%s[data-status='expired']" % sel("authorization-item-" + a), timeout=8000)
        self.assertIsNone(self.page.query_selector(sel("wallet-held")))
        self.assertEqual(self.text("wallet-available"), "100.00 EUR")
        self.page.goto("/authorizations")
        self.page.wait_for_selector("%s[data-status='expired']" % sel("authorization-item-" + a))
        self.assertIsNone(self.page.query_selector(sel("authorization-void-" + a)))

    def test_empty_authorizations(self):
        self.login()
        self.page.goto("/authorizations")
        self.page.wait_for_selector(sel("empty-authorizations"))
        self.assertIsNone(self.page.query_selector(sel("authorization-list")))

    # --------------------------------------------------------- upgrade (M2-M4)
    @unittest.skipUnless(PREV, "BASE_URL_PREV not set")
    def test_upgrade_keeps_session_form_and_retry(self):
        call("POST", "/_test/reset", seed(requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200,
                                                      "note": "taxi", "status": "pending"}]), base=PREV)
        mode = {"upstream": PREV, "lose": False}

        def handler(route):
            req = route.request
            u = urlsplit(req.url)
            if req.resource_type not in ("fetch", "xhr"):
                return route.continue_()
            if mode["upstream"] is None:
                return route.continue_()
            resp = route.fetch(url=mode["upstream"] + u.path + ("?" + u.query if u.query else ""))
            if mode["lose"] and req.method == "POST" and u.path == "/payments":
                return route.abort()
            route.fulfill(response=resp)
        self.page.route("**/*", handler)
        self.login()
        self.page.goto("/")
        self.page.wait_for_selector(sel("pay-submit"))
        mode["lose"] = True
        self.page.fill(sel("pay-handle"), "bob")
        self.page.fill(sel("pay-amount"), "15.00")
        self.page.fill(sel("pay-note"), "lost before the upgrade")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-uncertain"))
        mode["lose"] = False
        # the export taken while the response was lost, imported into the new service
        ex = call("GET", "/_test/export", base=PREV)[1]
        self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        mode["upstream"] = None
        self.page.click(sel("pay-submit"))  # same key and body, no reload
        self.page.wait_for_selector(sel("pay-uncertain"), state="detached")
        self.page.wait_for_selector("%s[data-amount='8500']" % sel("wallet-balance"))
        self.assertEqual(self.amount_attr("wallet-available"), "8500")
        self.assertIsNone(self.page.query_selector(sel("pay-error")))
        self.assertEqual(len(self.page.query_selector_all("[data-testid^='activity-item-']")), 1)
        tok = self.token("ada")
        self.assertEqual(call("GET", "/me", token=tok)[1]["balance"], 8500)
        self.assertEqual(self.page.input_value(sel("pay-note")), "lost before the upgrade")
        # still signed in on another screen; the pending request is payable
        self.page.goto("/requests")
        self.page.wait_for_selector(sel("request-pay-rq_1"))
        self.page.click(sel("request-pay-rq_1"))
        self.page.wait_for_selector("%s[data-status='paid']" % sel("request-item-rq_1"))
        self.assertEqual(call("GET", "/me", token=tok)[1]["balance"], 7300)

    # ----------------------------------------------------------- a11y / look
    def test_labels_focus_and_contrast(self):
        reset(seed(authorizations=[{"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "d",
                                    "visibility": "public", "status": "open", "expires_at": "2099-01-01T00:00:00+00:00"},
                                   {"id": "a_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 2000, "note": "d",
                                    "visibility": "public", "status": "open", "expires_at": "2099-01-01T00:00:00+00:00"}]))
        self.login()
        for route, anchor in (("/", "pay-submit"), ("/split", "split-submit"), ("/authorizations", "authorization-list"),
                              ("/requests", "incoming-list"), ("/login", "login-submit"), ("/signup", "signup-submit")):
            self.page.goto(route)
            self.page.wait_for_selector(sel(anchor))
            self.page.wait_for_timeout(150)
            bad = self.page.evaluate("""() => [...document.querySelectorAll('input:not([type=checkbox]),select')].filter(e =>
                !(e.id && document.querySelector('label[for="' + e.id + '"]')) && !e.getAttribute('aria-label')).map(e => e.outerHTML)""")
            self.assertEqual(bad, [], route)
            low = self.page.evaluate("""() => {
              const lum = c => { const [r,g,b] = c.map(v => { v/=255; return v<=0.03928? v/12.92 : Math.pow((v+0.055)/1.055,2.4)}); return 0.2126*r+0.7152*g+0.0722*b; };
              const parse = s => { const m = s.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(',').map(Number); return {c: p.slice(0,3), a: p.length>3? p[3]:1}; };
              const bg = el => { for (let e = el; e; e = e.parentElement) { const p = parse(getComputedStyle(e).backgroundColor); if (p && p.a > 0.5) return p.c; const bi = getComputedStyle(e).backgroundImage; if (bi && bi !== 'none') return [15,118,110]; } return [255,255,255]; };
              const out = [];
              document.querySelectorAll('body *').forEach(el => {
                if (!el.childNodes.length || ![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) return;
                const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.display === 'none') return;
                const fg = parse(cs.color); if (!fg) return;
                const a = lum(fg.c), b = lum(bg(el)); const ratio = (Math.max(a,b)+0.05)/(Math.min(a,b)+0.05);
                const large = parseFloat(cs.fontSize) >= 24 || (parseFloat(cs.fontSize) >= 18.66 && parseInt(cs.fontWeight) >= 700);
                if (ratio < (large ? 3 : 4.5)) out.push([el.tagName, el.textContent.trim().slice(0, 30), ratio.toFixed(2)]);
              });
              return out; }""")
            self.assertEqual(low, [], route)
        # focus is visible on a control
        self.page.goto("/")
        self.page.wait_for_selector(sel("pay-submit"))
        self.page.focus(sel("pay-amount"))
        self.page.keyboard.press("Tab")
        outline = self.page.evaluate("getComputedStyle(document.activeElement).outlineStyle + ' ' + getComputedStyle(document.activeElement).outlineWidth")
        self.assertNotIn("none", outline.split()[0])

    def test_keyboard_only_pay(self):
        self.login()
        self.page.goto("/")
        self.page.wait_for_selector(sel("pay-handle"))
        self.page.focus(sel("pay-handle"))
        self.page.keyboard.type("bob")
        self.page.keyboard.press("Tab")
        self.page.keyboard.type("5.00")
        self.page.keyboard.press("Enter")
        self.page.wait_for_selector("%s[data-amount='9500']" % sel("wallet-balance"))

    def test_loading_and_error_states(self):
        self.login()
        # slow API: a loading indicator shows, then content
        def slow(route):
            if urlsplit(route.request.url).path == "/activity":
                time.sleep(1.0)
            route.continue_()
        self.page.route("**/activity*", slow)
        self.page.goto("/")
        self.page.wait_for_selector(".state.loading")
        self.page.wait_for_selector(sel("empty-activity"))
        # failing API: an error state with a retry control
        self.page.unroute("**/activity*")
        self.page.route("**/activity*", lambda r: r.fulfill(status=500, body="x"))
        self.page.goto("/")
        self.page.wait_for_selector(".msg.error")
        self.page.unroute("**/activity*")
        self.page.click(".msg.error button")
        self.page.wait_for_selector(sel("empty-activity"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
