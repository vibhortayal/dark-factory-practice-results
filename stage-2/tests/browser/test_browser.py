"""Own browser checks (rows L-U). Needs Playwright; run with the kickoff checkout's interpreter:

    <kickoff>/.venv/bin/python -m unittest discover -s tests/browser -t . -v

Screenshots of every route at 375 px and 1280 px are written to $SHOT_DIR (default /tmp/pf-shots).
"""
import os
import unittest
from datetime import datetime, timedelta, timezone

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # run with the kickoff checkout's interpreter
    raise unittest.SkipTest('playwright is not installed')

from tests.support import Api, fixture, user

SHOTS = os.environ.get("SHOT_DIR", "/tmp/pf-shots")


def sel(name):
    return "[data-testid='%s']" % name


def money(minor, units=2, cur="EUR"):
    if units == 0:
        return "%d %s" % (minor, cur)
    text = str(minor).rjust(units + 1, "0")
    return "%s.%s %s" % (text[:-units], text[-units:], cur)


class BrowserCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = Api()
        cls.base = "http://127.0.0.1:%d" % cls.api.port
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.api.close()

    def setUp(self):
        self.api.reset(fixture())
        self.ctx = self.browser.new_context(base_url=self.base, viewport={"width": 1280, "height": 900})
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(8000)
        self.posts = []
        self.signed_in = False
        self.page.on("request", lambda r: self.posts.append(r) if r.method == "POST" else None)

    def tearDown(self):
        result = getattr(self._outcome, "result", None)
        if result is not None and any(t is self for t, _ in result.errors + result.failures):
            os.makedirs(SHOTS, exist_ok=True)
            self.page.screenshot(path="%s/FAIL-%s.png" % (SHOTS, self._testMethodName), full_page=True)
            print("PAGE TEXT:", self.page.inner_text("body")[:800])
        self.ctx.close()

    def login(self, who="ada"):
        self.page.goto("/login")
        self.page.fill(sel("login-email"), who + "@example.com")
        self.page.fill(sel("login-password"), "correct horse")
        self.page.click(sel("login-submit"))
        self.page.wait_for_selector(sel("current-user"))
        self.signed_in = True

    def token(self, who="ada"):
        return self.api.login(who + "@example.com")

    def side(self, method, path, body=None, who="ada", key=None):
        return self.api.call(method, path, body, token=self.token(who), key=key)

    def amount(self, name="wallet-balance"):
        return self.page.get_attribute(sel(name), "data-amount")

    def pay(self, handle="bob", amount="15.00", **kw):
        if not self.signed_in:
            self.login()
        self.page.goto("/")
        self.page.wait_for_selector(sel("pay-submit"))
        self.page.fill(sel("pay-handle"), handle)
        self.page.fill(sel("pay-amount"), amount)
        self.page.click(sel("pay-submit"))

    def payments_posted(self):
        return [r for r in self.posts if r.url.endswith("/payments")]


class LayoutTests(BrowserCase):
    def test_no_horizontal_scroll_and_screenshots(self):
        os.makedirs(SHOTS, exist_ok=True)
        long_note = "w" * 150 + " ünïcödé 😀 " + "long words " * 20
        self.api.reset(fixture(users=[user("ada", 10000), user("a_very_long_handle_x", 5000), user("bob", 0)],
                               payments=[{"id": "p1", "from_user_id": "u_ada", "to_user_id": "u_a_very_long_handle_x",
                                          "amount": 1234, "note": long_note, "visibility": "private"}],
                               requests=[{"id": "r1", "requester_id": "u_a_very_long_handle_x", "payer_id": "u_ada",
                                          "amount": 99, "note": long_note, "status": "pending"}],
                               authorizations=[{"id": "a1", "from_user_id": "u_ada", "to_user_id": "u_a_very_long_handle_x",
                                                "amount": 2000, "note": long_note, "visibility": "private", "status": "open",
                                                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()}]))
        for width, height in ((375, 800), (1280, 900)):
            self.page.set_viewport_size({"width": width, "height": height})
            self.login()
            for route in ("/", "/requests", "/split", "/authorizations"):
                self.page.goto(route)
                self.page.wait_for_selector(sel("current-user"))
                self.page.wait_for_timeout(300)
                over = self.page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                self.assertLessEqual(over, 0, (route, width))
                self.page.screenshot(path="%s/%s-%d.png" % (SHOTS, route.strip("/") or "home", width), full_page=True)
            self.ctx.clear_cookies()
            self.page.evaluate("localStorage.clear()")
            for route in ("/login", "/signup"):
                self.page.goto(route)
                self.page.wait_for_selector("form")
                self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"), 0)
                self.page.screenshot(path="%s/%s-%d.png" % (SHOTS, route.strip("/"), width))

    def test_labels_and_focus(self):
        self.login()
        self.page.goto("/")
        self.page.wait_for_selector(sel("pay-submit"))
        unlabeled = self.page.evaluate("""() => [...document.querySelectorAll('input,select')].filter(
            el => !(el.id && document.querySelector('label[for="' + el.id + '"]'))).map(el => el.outerHTML)""")
        self.assertEqual(unlabeled, [])
        self.page.focus(sel("pay-handle"))
        outline = self.page.evaluate("getComputedStyle(document.querySelector(\"[data-testid='pay-handle']\")).outlineStyle")
        self.assertEqual(outline, "solid")
        self.page.keyboard.press("Tab")
        self.assertEqual(self.page.evaluate("getComputedStyle(document.activeElement).outlineStyle"), "solid")

    def test_signed_out_goes_to_login_and_routes(self):
        for route in ("/", "/requests", "/split", "/authorizations"):
            self.page.goto(route)
            self.page.wait_for_selector(sel("login-submit"))
        for route in ("/signup", "/login"):
            self.page.goto(route)
            self.assertEqual(self.page.query_selector(sel("current-user")), None)


class AuthUiTests(BrowserCase):
    def test_signup_login_errors_logout(self):
        p = self.page
        p.goto("/signup")
        p.fill(sel("signup-email"), "dee.ann@example.com")
        p.fill(sel("signup-password"), "short")
        p.fill(sel("signup-display-name"), "Dee")
        p.click(sel("signup-submit"))
        p.wait_for_selector(sel("auth-error"))
        p.fill(sel("signup-password"), "correct horse")
        p.click(sel("signup-submit"))
        p.wait_for_selector(sel("current-user"))
        self.assertIn("Dee", p.text_content(sel("current-user")))
        self.assertEqual(p.text_content(sel("current-handle")), "dee_ann")
        for route in ("/requests", "/split", "/authorizations", "/"):
            p.goto(route)
            p.wait_for_selector(sel("current-user"))
            self.assertEqual(p.text_content(sel("current-handle")), "dee_ann")
        p.click(sel("logout-button"))
        p.wait_for_selector(sel("current-user"), state="detached")
        p.goto("/signup")
        p.fill(sel("signup-email"), "ada@example.com")
        p.fill(sel("signup-password"), "correct horse")
        p.fill(sel("signup-display-name"), "X")
        p.click(sel("signup-submit"))
        p.wait_for_selector(sel("auth-error"))
        p.goto("/login")
        self.assertEqual(p.query_selector(sel("auth-error")), None)
        p.fill(sel("login-email"), "ada@example.com")
        p.fill(sel("login-password"), "bad password")
        p.click(sel("login-submit"))
        p.wait_for_selector(sel("auth-error"))


class WalletUiTests(BrowserCase):
    def test_formats_by_currency(self):
        for cur, units, text in (("JPY", 0, "10000 JPY"), ("BHD", 3, "10.000 BHD"), ("EUR", 2, "100.00 EUR")):
            self.api.reset(fixture(currency=cur, minor_units=units))
            self.login()
            self.page.goto("/")
            self.page.wait_for_selector(sel("wallet-balance"))
            self.assertEqual(self.page.text_content(sel("wallet-balance")), text)
            self.assertEqual(self.page.text_content(sel("wallet-available")), text)
            self.assertEqual(self.page.query_selector(sel("wallet-held")), None)
            self.page.evaluate("localStorage.clear()")

    def test_decimal_parsing_sends_nothing_when_invalid(self):
        self.login()
        self.page.goto("/")
        for bad in ("15.005", "abc", "", "1e3", "-5", "15.", "0", "1,000"):
            self.page.fill(sel("pay-handle"), "bob")
            self.page.fill(sel("pay-amount"), bad)
            self.page.click(sel("pay-submit"))
            self.page.wait_for_selector(sel("pay-error"))
        self.assertEqual(self.payments_posted(), [])
        for text, minor in (("15", 1500), ("15.5", 1550), ("15.00", 1500), ("0.01", 1)):
            self.page.fill(sel("pay-amount"), text)
            self.page.click(sel("pay-submit"))
            self.page.wait_for_selector("%s[data-amount='%d']" % (sel("wallet-balance"), 10000 - self._spent(minor)))
        self.api.reset(fixture(currency="JPY", minor_units=0))
        self.login()
        self.page.goto("/")
        for bad in ("15.0", "15.5"):
            self.page.fill(sel("pay-handle"), "bob")
            self.page.fill(sel("pay-amount"), bad)
            self.page.click(sel("pay-submit"))
            self.page.wait_for_selector(sel("pay-error"))

    _total = 0

    def _spent(self, minor):
        self._total += minor
        return self._total

    def test_double_submit_and_change(self):
        self.pay(amount="15.00")
        self.page.wait_for_selector("%s[data-amount='8500']" % sel("wallet-balance"))
        self.assertEqual(self.page.input_value(sel("pay-amount")), "15.00")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_timeout(500)
        self.assertEqual(self.page.query_selector(sel("pay-error")), None)
        self.assertEqual(self.amount(), "8500")
        self.assertEqual(len(self.payments_posted()), 1)
        self.assertEqual(len(self.page.query_selector_all("[data-testid^='activity-item-']")), 1)
        self.page.fill(sel("pay-amount"), "20.00")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector("%s[data-amount='6500']" % sel("wallet-balance"))
        keys = {r.headers["idempotency-key"] for r in self.payments_posted()}
        self.assertEqual(len(keys), 2)

    def test_errors_and_visibility(self):
        self.pay(handle="nobody")
        self.page.wait_for_selector(sel("pay-error"))
        self.pay(handle="ada")
        self.page.wait_for_selector(sel("pay-error"))
        self.pay(handle="bob", amount="9999.00")
        self.page.wait_for_selector(sel("pay-error"))
        self.assertEqual(self.page.input_value(sel("pay-amount")), "9999.00")
        self.page.fill(sel("pay-amount"), "1.00")
        self.page.fill(sel("pay-note"), "<b>hi</b> 😀 ")
        self.page.select_option(sel("pay-visibility"), "private")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector("[data-testid^='activity-item-'][data-visibility='private']")
        note = self.page.text_content("[data-testid^='activity-note-']")
        self.assertEqual(note, "<b>hi</b> 😀 ")
        self.assertEqual(self.page.query_selector(sel("pay-error")), None)
        self.assertEqual(self.page.eval_on_selector_all(sel("pay-visibility") + " option", "els => els.map(e => e.value)"),
                         ["public", "private"])

    def test_empty_note_and_empty_feed(self):
        self.login("cy")
        self.page.goto("/")
        self.page.wait_for_selector(sel("empty-activity"))
        self.assertEqual(self.page.query_selector(sel("activity-list")), None)

    def test_request_form(self):
        self.login()
        self.page.goto("/")
        self.page.fill(sel("request-handle"), "bob")
        self.page.fill(sel("request-amount"), "12.00")
        self.page.click(sel("request-submit"))
        self.page.wait_for_selector(sel("request-success")) if self.page.query_selector(sel("request-success")) else None
        self.page.fill(sel("request-handle"), "ada")
        self.page.click(sel("request-submit"))
        self.page.wait_for_selector(sel("request-error"))
        outgoing = self.side("GET", "/requests?direction=outgoing")[1]["requests"]
        self.assertEqual([r["amount"] for r in outgoing], [1200])

    def test_refresh_keeps_form_and_sees_other_clients(self):
        self.login()
        self.page.goto("/")
        self.page.wait_for_selector(sel("wallet-balance"))
        self.page.fill(sel("pay-handle"), "bob")
        self.page.fill(sel("pay-amount"), "3.00")
        s, p, _ = self.side("POST", "/payments", {"to_handle": "cy", "amount": 300}, key="x")
        self.page.click(sel("wallet-refresh"))
        self.page.wait_for_selector("%s[data-amount='9700']" % sel("wallet-balance"))
        self.page.wait_for_selector(sel("activity-item-" + p["payment_id"]))
        self.assertEqual(self.page.input_value(sel("pay-handle")), "bob")
        self.assertEqual(self.page.input_value(sel("pay-amount")), "3.00")

    def test_latest_refresh_wins(self):
        self.login()
        held = []

        seen = []

        def delay_first(route):
            seen.append(1)
            if len(seen) == 2:          # 1st /me is the page boot; the 2nd is the wallet's first read
                held.append(route)      # hold it until we release it
            else:
                route.continue_()
        self.page.route("**/me", delay_first)
        self.page.goto("/")
        self.page.wait_for_function("1")
        self.page.wait_for_timeout(300)
        self.assertEqual(len(held), 1)
        self.side("POST", "/payments", {"to_handle": "cy", "amount": 400}, key="x")
        self.page.click(sel("wallet-refresh"))
        self.page.wait_for_selector("%s[data-amount='9600']" % sel("wallet-balance"))
        held[0].continue_()              # stale response (balance 10000) arrives late
        self.page.wait_for_timeout(600)
        self.assertEqual(self.amount(), "9600")

    def test_refused_because_spent_elsewhere(self):
        self.login("cy")
        self.page.goto("/")
        self.page.wait_for_selector("%s[data-amount='500']" % sel("wallet-balance"))
        self.side("POST", "/payments", {"to_handle": "ada", "amount": 400}, who="cy", key="spent")
        self.page.fill(sel("pay-handle"), "bob")
        self.page.fill(sel("pay-amount"), "3.00")
        self.page.fill(sel("pay-note"), "keep me")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-error"))
        self.page.wait_for_selector("%s[data-amount='100']" % sel("wallet-balance"))
        self.assertEqual((self.page.input_value(sel("pay-handle")), self.page.input_value(sel("pay-amount")),
                          self.page.input_value(sel("pay-note"))), ("bob", "3.00", "keep me"))

    def test_lost_response_is_uncertain_and_retry_pays_once(self):
        self.login()
        self.page.goto("/")
        state = {"lost": True}

        def lose(route):
            if route.request.method == "POST" and state["lost"]:
                route.fetch()           # the server commits...
                state["lost"] = False
                route.abort()           # ...but the browser never sees the answer
            else:
                route.continue_()
        self.page.route("**/payments", lose)
        self.page.fill(sel("pay-handle"), "bob")
        self.page.fill(sel("pay-amount"), "15.00")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-uncertain"))
        self.assertTrue(self.page.text_content(sel("pay-uncertain")).strip())
        self.assertEqual(self.page.query_selector(sel("pay-error")), None)
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-uncertain"), state="detached")
        self.page.wait_for_selector("%s[data-amount='8500']" % sel("wallet-balance"))
        self.assertEqual(self.page.query_selector(sel("pay-error")), None)
        posts = self.payments_posted()
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0].headers["idempotency-key"], posts[1].headers["idempotency-key"])
        self.assertEqual(posts[0].post_data, posts[1].post_data)
        self.assertEqual(len(self.page.query_selector_all("[data-testid^='activity-item-']")), 1)
        self.assertEqual(self.side("GET", "/me")[1]["balance"], 8500)

    def test_upgrade_keeps_session_requests_and_retry(self):
        rid = self.side("POST", "/requests", {"payer_handle": "ada", "amount": 1000}, who="bob", key="rq")[1]["request_id"]
        self.login()
        self.page.goto("/")
        state = {"lost": True}

        def lose(route):
            if route.request.method == "POST" and state["lost"]:
                route.fetch()
                state["lost"] = False
                route.abort()
            else:
                route.continue_()
        self.page.route("**/payments", lose)
        self.page.fill(sel("pay-handle"), "bob")
        self.page.fill(sel("pay-amount"), "15.00")
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-uncertain"))
        doc = self.api.call("GET", "/_test/export")[1]
        self.api.reset(fixture(users=[user("zed", 1)]))
        self.assertEqual(self.api.call("POST", "/_test/import", doc)[0], 204)
        self.page.click(sel("pay-submit"))
        self.page.wait_for_selector(sel("pay-uncertain"), state="detached")
        self.page.wait_for_selector("%s[data-amount='8500']" % sel("wallet-balance"))
        self.assertEqual(self.page.input_value(sel("pay-amount")), "15.00")
        self.page.goto("/requests")
        self.page.click(sel("request-pay-" + rid))
        self.page.wait_for_selector("%s[data-status='paid']" % sel("request-item-" + rid))
        self.assertEqual(self.side("GET", "/me")[1]["balance"], 7500)


class RequestsUiTests(BrowserCase):
    def mk(self, who="bob", payer="ada", amount=1200):
        return self.side("POST", "/requests", {"payer_handle": payer, "amount": amount, "note": "taxi"}, who=who, key="k-%s-%s-%d" % (who, payer, amount))[1]["request_id"]

    def test_lists_and_actions(self):
        inc, out, dec = self.mk(), self.mk("ada", "bob", 300), self.mk("cy", "ada", 50)
        self.login()
        self.page.goto("/requests")
        self.page.wait_for_selector(sel("request-item-" + inc))
        self.assertEqual(self.page.query_selector(sel("empty-requests")).is_hidden(), True)
        self.assertEqual(self.page.text_content(sel("request-amount-" + inc)), "12.00 EUR")
        self.assertIsNotNone(self.page.query_selector("%s %s" % (sel("incoming-list"), sel("request-item-" + inc))))
        self.assertIsNotNone(self.page.query_selector("%s %s" % (sel("outgoing-list"), sel("request-item-" + out))))
        self.assertIsNone(self.page.query_selector(sel("request-pay-" + out)))
        self.assertIsNone(self.page.query_selector(sel("request-cancel-" + inc)))
        self.page.click(sel("request-decline-" + dec))
        self.page.wait_for_selector("%s[data-status='declined']" % sel("request-item-" + dec))
        self.assertIsNone(self.page.query_selector(sel("request-decline-" + dec)))
        self.page.click(sel("request-cancel-" + out))
        self.page.wait_for_selector("%s[data-status='cancelled']" % sel("request-item-" + out))
        self.page.click(sel("request-pay-" + inc))
        self.page.wait_for_selector("%s[data-status='paid']" % sel("request-item-" + inc))
        self.page.wait_for_selector("%s[data-amount='8800']" % sel("wallet-balance"))

    def test_cancelled_elsewhere_and_insufficient(self):
        rid = self.mk()
        big = self.mk("ada", "cy", 90000)
        self.login()
        self.page.goto("/requests")
        self.page.wait_for_selector(sel("request-pay-" + rid))
        self.side("POST", "/requests/%s/cancel" % rid, who="bob")
        self.page.click(sel("request-pay-" + rid))
        self.page.wait_for_selector(sel("request-error"))
        self.page.wait_for_selector(sel("request-pay-" + rid), state="detached")
        self.page.evaluate("localStorage.clear()")
        self.login("cy")
        self.page.goto("/requests")
        self.page.click(sel("request-pay-" + big))
        self.page.wait_for_selector(sel("request-error"))

    def test_empty(self):
        self.login()
        self.page.goto("/requests")
        self.page.wait_for_selector(sel("empty-requests"))
        self.assertIsNotNone(self.page.query_selector(sel("incoming-list")))


class SplitUiTests(BrowserCase):
    def test_preview_matches_server(self):
        self.login()
        self.page.goto("/split")
        self.page.fill(sel("split-amount"), "10.00")
        self.page.fill(sel("split-handles"), "ada, bob ,cy")
        shares = [self.page.text_content(sel("split-share-" + h)) for h in ("ada", "bob", "cy")]
        self.assertEqual(shares, ["3.34 EUR", "3.33 EUR", "3.33 EUR"])
        self.page.fill(sel("split-handles"), "cy,bob,ada")
        self.assertEqual(self.page.text_content(sel("split-share-cy")), "3.34 EUR")
        self.page.fill(sel("split-amount"), "0.01")
        self.assertEqual([self.page.text_content(sel("split-share-" + h)) for h in ("cy", "bob", "ada")],
                         ["0.01 EUR", "0.00 EUR", "0.00 EUR"])
        self.page.fill(sel("split-amount"), "10.00")
        self.page.fill(sel("split-handles"), "ada,bob,cy")
        self.assertEqual([p for p in self.posts if p.url.endswith("/splits")], [])  # preview posts nothing
        self.page.click(sel("split-submit"))
        self.page.wait_for_selector(sel("split-success"))
        reqs = self.side("GET", "/requests", who="bob")[1]["requests"]
        self.assertEqual([r["amount"] for r in reqs], [333])
        self.page.click(sel("split-submit"))
        self.assertEqual(len(self.side("GET", "/requests", who="bob")[1]["requests"]), 1)

    def test_errors(self):
        self.login()
        self.page.goto("/split")
        for amount, handles in (("10.00", "ada,ghost"), ("10.00", ""), ("abc", "ada"), ("10.00", "bob,bob")):
            self.page.fill(sel("split-amount"), amount)
            self.page.fill(sel("split-handles"), handles)
            self.page.click(sel("split-submit"))
            self.page.wait_for_selector(sel("split-error"))


class AuthorizationUiTests(BrowserCase):
    def seeded(self):
        soon = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(timespec="seconds")
        self.api.reset(fixture(authorizations=[
            {"id": "a_out", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit",
             "visibility": "private", "status": "open", "expires_at": soon},
            {"id": "a_in", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 500, "visibility": "public",
             "status": "open", "expires_at": soon},
            {"id": "a_cap", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 700, "visibility": "public",
             "status": "captured", "captured_amount": 650, "expires_at": soon}]))
        return soon

    def test_wallet_shows_available_headline_and_held(self):
        self.seeded()
        self.login()
        self.page.goto("/")
        self.page.wait_for_selector(sel("wallet-held"))
        self.assertEqual(self.page.text_content(sel("wallet-available")), "80.00 EUR")
        self.assertEqual(self.page.text_content(sel("wallet-balance")), "100.00 EUR")
        self.assertEqual(self.page.text_content(sel("wallet-held")), "20.00 EUR")
        sizes = self.page.evaluate("""() => ['wallet-available','wallet-balance','wallet-held'].map(
            t => parseFloat(getComputedStyle(document.querySelector("[data-testid='" + t + "']")).fontSize))""")
        self.assertGreater(sizes[0], sizes[1])
        self.assertGreater(sizes[0], sizes[2])

    def test_list_capture_void(self):
        soon = self.seeded()
        self.login()
        self.page.goto("/authorizations")
        self.page.wait_for_selector(sel("authorization-item-a_out"))
        order = self.page.eval_on_selector_all(sel("authorization-list") + " > *", "els => els.map(e => e.dataset.testid)")
        self.assertEqual(set(order), {"authorization-item-a_out", "authorization-item-a_in", "authorization-item-a_cap"})
        self.assertEqual(self.page.text_content(sel("authorization-amount-a_out")), "20.00 EUR")
        self.assertEqual(self.page.text_content(sel("authorization-expires-a_out")), soon)
        self.assertEqual(self.page.text_content(sel("authorization-captured-a_cap")), "6.50 EUR")
        self.assertIsNone(self.page.query_selector(sel("authorization-captured-a_out")))
        self.assertIsNone(self.page.query_selector(sel("authorization-capture-a_out")))
        self.assertIsNone(self.page.query_selector(sel("authorization-void-a_in")))
        self.assertIsNone(self.page.query_selector(sel("authorization-capture-a_cap")))
        self.assertEqual(self.page.input_value(sel("authorization-capture-amount-a_in")), "5.00")
        self.page.fill(sel("authorization-capture-amount-a_in"), "5.005")
        self.page.click(sel("authorization-capture-a_in"))
        self.page.wait_for_selector(sel("authorization-error"))
        self.page.fill(sel("authorization-capture-amount-a_in"), "6.00")
        self.page.click(sel("authorization-capture-a_in"))
        self.page.wait_for_selector(sel("authorization-error"))
        self.page.fill(sel("authorization-capture-amount-a_in"), "2.50")
        self.page.click(sel("authorization-capture-a_in"))
        self.page.wait_for_selector("%s[data-status='captured']" % sel("authorization-item-a_in"))
        self.page.wait_for_selector("%s[data-amount='10250']" % sel("wallet-balance"))
        self.page.click(sel("authorization-void-a_out"))
        self.page.wait_for_selector("%s[data-status='voided']" % sel("authorization-item-a_out"))
        self.page.wait_for_selector(sel("wallet-held"), state="detached")
        self.assertEqual(self.page.get_attribute(sel("wallet-available"), "data-amount"), "10250")

    def test_authorize_form_on_both_pages_and_empty(self):
        self.login()
        self.page.goto("/authorizations")
        self.page.wait_for_selector(sel("empty-authorizations"))
        self.page.fill(sel("authorize-handle"), "bob")
        self.page.fill(sel("authorize-amount"), "30.00")
        self.page.select_option(sel("authorize-visibility"), "private")
        self.page.click(sel("authorize-submit"))
        self.page.wait_for_selector("%s[data-amount='7000']" % sel("wallet-available"))
        self.page.wait_for_selector("[data-testid^='authorization-item-']")
        self.page.fill(sel("authorize-amount"), "999.00")
        self.page.click(sel("authorize-submit"))
        self.page.wait_for_selector(sel("authorize-error"))
        self.page.goto("/")
        self.page.wait_for_selector(sel("wallet-held"))
        self.page.fill(sel("authorize-handle"), "bob")
        self.page.fill(sel("authorize-amount"), "71.00")
        self.page.click(sel("authorize-submit"))
        self.page.wait_for_selector(sel("authorize-error"))
        self.assertEqual(self.page.query_selector("[data-testid^='activity-item-']"), None)


if __name__ == "__main__":
    unittest.main()
