import json
import re
import unittest

from helpers import call, fixture, k, login, me, pay, reset, user

TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?([+-]\d\d:\d\d|Z)$")


def err(case, resp, status, code):
    s, h, b, raw = resp
    case.assertEqual(s, status, raw)
    case.assertEqual(b["error"]["code"], code, raw)
    case.assertIsInstance(b["error"]["message"], str)
    case.assertEqual(h.get("Content-Type"), "application/json; charset=utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        reset(fixture())
        self.ada, self.bob, self.cy = login("ada"), login("bob"), login("cy")

    def total(self):
        return sum(me(t)["balance"] for t in (self.ada, self.bob, self.cy))


class Runtime(Base):
    def test_health_and_headers(self):  # R2 R5
        s, h, b, _ = call("GET", "/health")
        self.assertEqual((s, b), (200, {"status": "ok"}))
        self.assertEqual(h["Content-Type"], "application/json; charset=utf-8")
        for path in ("/me", "/activity", "/requests"):
            self.assertEqual(call("GET", path, token=self.ada)[1]["Content-Type"],
                             "application/json; charset=utf-8")

    def test_unknown_route(self):  # R10 D8 M15
        for m, p in (("GET", "/nope"), ("DELETE", "/me"), ("GET", "/refunds"), ("POST", "/refunds"), ("GET", "/users"),
                     ("POST", "/deposits"), ("POST", "/admin/balance"), ("GET", "/refunds?x=1")):
            err(self, call(m, p, token=self.ada), 404, "not_found")

    def test_reset_clears_everything_and_changes_currency(self):  # R3 R4 M1
        old = self.ada
        pay(self.ada, "bob", 10)
        reset(fixture(currency="JPY", minor_units=0, users=[user("zed", 5)]))
        err(self, call("GET", "/me", token=old), 401, "unauthenticated")
        z = login("zed")
        m = me(z)
        self.assertEqual((m["currency"], m["minor_units"], m["balance"]), ("JPY", 0, 5))
        self.assertEqual(call("GET", "/activity", token=z)[2]["payments"], [])
        reset(fixture(currency="BHD", minor_units=3))
        self.assertEqual(me(login("ada"))["minor_units"], 3)

    def test_reset_negative_balance_changes_nothing(self):  # M10
        err(self, call("POST", "/_test/reset", fixture(users=[user("ada", -1)])), 422,
            "validation_failed")
        self.assertEqual(me(self.ada)["balance"], 10000)

    def test_reset_malformed(self):
        err(self, call("POST", "/_test/reset", raw=b"{nope"), 400, "malformed_request")

    def test_unknown_fields_and_query_ignored(self):  # R7 R8
        s, _, b, _ = pay(self.ada, "bob", 5, extra="x", nested={"a": 1})
        self.assertEqual(s, 201)
        self.assertEqual(call("GET", "/me?zzz=1", token=self.ada)[0], 200)
        self.assertEqual(call("GET", "/activity?foo=bar&limit=5", token=self.ada)[0], 200)

    def test_fixture_values(self):  # M7 M8 M9
        fx = fixture(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                                "amount": 500, "note": "coffee", "visibility": "private"},
                               {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_cy",
                                "amount": 5, "note": "x", "visibility": "public"}],
                     requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
                                "amount": 1200, "note": "taxi", "status": "pending"}])
        reset(fx)
        ada, cy = login("ada"), login("cy")
        self.assertEqual(me(ada)["balance"], 10000)
        feed = call("GET", "/activity", token=ada)[2]["payments"]
        self.assertEqual([p["payment_id"] for p in feed], ["p_2", "p_1"])
        self.assertEqual(feed[1]["note"], "coffee")
        self.assertIsNone(feed[1]["settlement_id"])
        self.assertTrue(TS.match(feed[1]["created_at"]))
        self.assertEqual([p["payment_id"] for p in call("GET", "/activity", token=cy)[2]["payments"]], ["p_2"])
        rq = call("GET", "/requests", token=ada)[2]["requests"]
        self.assertEqual(rq[0]["request_id"], "rq_1")
        # decline works on a seeded pending request
        self.assertEqual(call("POST", "/requests/rq_1/decline", token=ada)[2]["status"], "declined")


class Auth(Base):
    def test_signup_login(self):  # A1 A2 A3 A9 M4 M5
        s, _, b, _ = call("POST", "/auth/signup", {"email": "Jo.Ann+x@ex.com",
                                                    "password": "12345678", "display_name": "Jo"})
        self.assertEqual(s, 201)
        self.assertEqual(set(b), {"user_id", "display_name", "token"})
        m = me(b["token"])
        self.assertEqual((m["handle"], m["balance"]), ("jo_ann_x", 0))
        err(self, call("POST", "/auth/signup", {"email": "jo.ann+x@ex.com", "password": "12345678",
                                                 "display_name": "J"}), 409, "email_taken")
        t1 = call("POST", "/auth/login", {"email": "Jo.Ann+x@ex.com", "password": "12345678"})[2]["token"]
        t2 = call("POST", "/auth/login", {"email": "Jo.Ann+x@ex.com", "password": "12345678"})[2]["token"]
        self.assertNotEqual(t1, t2)
        self.assertEqual(call("GET", "/me", token=t1)[0], 200)
        self.assertEqual(call("GET", "/me", token=t2)[0], 200)
        self.assertEqual(call("GET", "/me", token=b["token"])[0], 200)
        self.assertEqual(pay(self.ada, "jo_ann_x", 100)[0], 201)

    def test_long_handle_truncated(self):  # M4
        s, _, b, _ = call("POST", "/auth/signup", {"email": "a" * 25 + "@x.io", "password": "12345678",
                                                    "display_name": "L"})
        self.assertEqual(me(b["token"])["handle"], "a" * 20)

    def test_validation(self):  # A4 A5 A6 A11
        def su(**o):
            d = {"email": "q@x.io", "password": "12345678", "display_name": "Q"}
            d.update(o)
            return call("POST", "/auth/signup", d)
        err(self, su(password="1234567"), 422, "validation_failed")
        self.assertEqual(su(password="12345678")[0], 201)
        for bad in ("nodomain", "@x.io", "a@", "a b@x.io", "a@@x.io", ""):
            err(self, su(email=bad), 422, "validation_failed")
        err(self, su(email=1), 400, "malformed_request")
        err(self, call("POST", "/auth/signup", {"email": "z@x.io", "password": "12345678"}), 422,
            "validation_failed")
        err(self, call("POST", "/auth/signup", [1]), 400, "malformed_request")
        err(self, call("POST", "/auth/signup", raw=b"{"), 400, "malformed_request")
        err(self, call("POST", "/auth/login", {"email": "ada@example.com", "password": "bad"}), 401,
            "unauthenticated")
        err(self, call("POST", "/auth/login", {"email": "no@example.com", "password": "bad"}), 401,
            "unauthenticated")
        err(self, call("POST", "/auth/login", {"email": "ada@example.com"}), 422, "validation_failed")
        err(self, call("POST", "/auth/login", {"email": "ada@example.com", "password": 5}), 400,
            "malformed_request")

    def test_handle_taken(self):  # A7
        for email in ("ada@other.org", "ADA@third.org"):
            err(self, call("POST", "/auth/signup", {"email": email, "password": "12345678",
                                                     "display_name": "X"}), 409, "handle_taken")
        err(self, call("POST", "/auth/login", {"email": "ada@other.org", "password": "12345678"}), 401,
            "unauthenticated")
        long1 = "b" * 20 + "x@a.io"
        self.assertEqual(call("POST", "/auth/signup", {"email": long1, "password": "12345678",
                                                        "display_name": "X"})[0], 201)
        err(self, call("POST", "/auth/signup", {"email": "b" * 20 + "y@a.io", "password": "12345678",
                                                 "display_name": "X"}), 409, "handle_taken")
        # the email stays free
        self.assertEqual(call("POST", "/auth/signup", {"email": "free@a.io", "password": "12345678",
                                                        "display_name": "X"})[0], 201)

    def test_auth_required_everywhere(self):  # E4 A8
        for m, p in (("GET", "/me"), ("GET", "/activity"), ("GET", "/requests"),
                     ("POST", "/payments"), ("POST", "/requests"), ("POST", "/splits"),
                     ("POST", "/settlements"), ("POST", "/requests/x/pay"),
                     ("POST", "/requests/x/decline"), ("POST", "/requests/x/cancel")):
            err(self, call(m, p, {}, key=k()), 401, "unauthenticated")
            err(self, call(m, p, {}, key=k(), headers={"Authorization": "Bearer nope"}), 401, "unauthenticated")
            err(self, call(m, p, {}, key=k(), headers={"Authorization": "Basic abc"}), 401, "unauthenticated")
            err(self, call(m, p, {}, key=k(), headers={"Authorization": "Bearer"}), 401, "unauthenticated")

    def test_password_not_plaintext_in_export(self):  # A10
        raw = call("GET", "/_test/export")[3].decode()
        self.assertNotIn("correct horse", raw)


class Payments(Base):
    def test_shape_and_money(self):  # P2 P3 R6 R9
        s, _, b, _ = pay(self.ada, "bob", 1500, note="dinner", visibility="private")
        self.assertEqual(s, 201)
        self.assertEqual(set(b), {"payment_id", "from_user_id", "from_handle", "to_user_id",
                                  "to_handle", "amount", "currency", "note", "visibility",
                                  "request_id", "settlement_id", "authorization_id", "created_at"})
        self.assertEqual((b["from_handle"], b["to_handle"], b["amount"], b["currency"]),
                         ("ada", "bob", 1500, "EUR"))
        self.assertIsNone(b["request_id"])
        self.assertIsNone(b["settlement_id"])
        self.assertTrue(TS.match(b["created_at"]))
        self.assertLessEqual(len(b["payment_id"]), 64)
        self.assertEqual((me(self.ada)["balance"], me(self.bob)["balance"]), (8500, 4000))
        d = pay(self.ada, "bob", 1)[2]
        self.assertEqual((d["note"], d["visibility"]), ("", "public"))

    def test_amounts(self):  # M2 P5 E10
        for a in (1, 1000000000, 1000.0):
            self.assertEqual(pay(self.ada, "bob", 1 if a == 1 else 1000, key=k())[0], 201)
        s, _, b, raw = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1e3}',
                            token=self.ada, key=k())
        self.assertEqual(s, 201)
        self.assertEqual(b["amount"], 1000)
        self.assertIn(b'"amount":1000,', raw)
        s, _, b, raw = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1000.0}',
                            token=self.ada, key=k())
        self.assertEqual(s, 201)
        self.assertIn(b'"amount":1000,', raw)
        for a in (0, -1, 1.5, 1000000001, "10", True, False, None, [1], {}, 10 ** 40):
            err(self, pay(self.ada, "bob", a), 422, "validation_failed")
        for raw in (b'{"to_handle":"bob","amount":1e400}', b'{"to_handle":"bob","amount":1E+9}',
                    b'{"to_handle":"bob","amount":1e30000000000}'):
            s = call("POST", "/payments", raw=raw, token=self.ada, key=k())[0]
            self.assertIn(s, (201, 409, 422))
        err(self, call("POST", "/payments", {"to_handle": "bob"}, self.ada, k()), 422, "validation_failed")
        err(self, pay(self.bob, "cy", 1000000000), 409, "insufficient_funds")

    def test_exact_balance_and_funds(self):  # P4 I4
        err(self, pay(self.cy, "bob", 501), 409, "insufficient_funds")
        self.assertEqual(me(self.cy)["balance"], 500)
        self.assertEqual(pay(self.cy, "bob", 500)[0], 201)
        self.assertEqual(me(self.cy)["balance"], 0)
        self.assertEqual(self.total(), 13000)
        self.assertEqual(call("GET", "/activity", token=self.cy)[2]["payments"][0]["amount"], 500)

    def test_big_balances_exact(self):  # M12
        big = 2 ** 53
        reset(fixture(users=[user("ada", big), user("bob", 0)]))
        ada, bob = login("ada"), login("bob")
        for _ in range(3):
            self.assertEqual(pay(ada, "bob", 999999999)[0], 201)
        self.assertEqual(me(ada)["balance"], big - 3 * 999999999)
        self.assertEqual(me(bob)["balance"], 3 * 999999999)

    def test_errors(self):  # P6 P7 P8 P9 E2
        err(self, pay(self.ada, "ada", 5), 422, "self_payment")
        err(self, pay(self.ada, "nobody", 5), 404, "not_found")
        err(self, pay(self.ada, "", 5), 404, "not_found")
        err(self, pay(self.ada, "ADA", 5), 404, "not_found")
        err(self, pay(self.ada, 5, 5), 400, "malformed_request")
        err(self, pay(self.ada, None, 5), 400, "malformed_request")
        err(self, call("POST", "/payments", {"amount": 5}, self.ada, k()), 422, "validation_failed")
        self.assertEqual(pay(self.ada, "bob", 1, note="x" * 200)[0], 201)
        err(self, pay(self.ada, "bob", 1, note="x" * 201), 422, "validation_failed")
        self.assertEqual(pay(self.ada, "bob", 1, note="\U0001F600" * 200)[0], 201)
        err(self, pay(self.ada, "bob", 1, note="\U0001F600" * 201), 422, "validation_failed")
        for note in (None, 5, [], {}, True):
            err(self, pay(self.ada, "bob", 1, note=note), 422, "validation_failed")
        for vis in ("friends", "", None, 5, True, "PUBLIC", []):
            err(self, pay(self.ada, "bob", 1, visibility=vis), 422, "validation_failed")
        # precedence: bad amount before unknown handle, unknown handle before funds
        err(self, pay(self.ada, "nobody", 0), 422, "validation_failed")
        err(self, pay(self.cy, "nobody", 10 ** 9), 404, "not_found")
        err(self, pay(self.cy, "cy", 10 ** 9), 422, "self_payment")
        for raw in (b"", b"[]", b"5", b"null", b"{", b'"s"', b"\xff\xfe", b"NaN", b'{"a":Infinity}'):
            err(self, call("POST", "/payments", raw=raw, token=self.ada, key=k()), 400, "malformed_request")

    def test_note_roundtrip(self):  # P10
        notes = ["  lead and trail  ", "<b>&amp;</b>", "e\u0301 vs \u00e9", "caf\u00e9 \U0001F469\u200d\U0001F4BB",
                 "line\nbreak\ttab", "\"quoted\" \\ back", "\u0000nul", "\ufffd", ""]
        for n in notes:
            s, _, b, _ = pay(self.ada, "bob", 1, note=n)
            self.assertEqual(s, 201)
            self.assertEqual(b["note"], n)
        feed = call("GET", "/activity", token=self.bob, ) [2]["payments"]
        self.assertEqual([p["note"] for p in reversed(feed)][-len(notes):], notes)
        # lone surrogate must not crash
        s = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1,"note":"\\ud800"}',
                 token=self.ada, key=k())[0]
        self.assertEqual(s, 201)

    def test_max_balance_not_5xx_fuzz(self):  # I5
        bodies = [b'{"to_handle":"bob","amount":' + b"9" * 5000 + b"}",
                  b"[" * 5000 + b"]" * 5000, b'{"to_handle":"bob","amount":-0.0}',
                  b'{"to_handle":{"a":1},"amount":1}', b'{"amount":1,"amount":2,"to_handle":"bob"}']
        for raw in bodies:
            s = call("POST", "/payments", raw=raw, token=self.ada, key=k())[0]
            self.assertLess(s, 500)
        for path in ("/requests?limit=" + "9" * 5000, "/activity?offset=" + "9" * 5000, "/requests?status=%ff"):
            self.assertLess(call("GET", path, token=self.ada)[0], 500)


class Requests(Base):
    def rq(self, tok, payer, amount, key=None, **extra):
        body = {"payer_handle": payer, "amount": amount}
        body.update(extra)
        return call("POST", "/requests", body, tok, key or k())

    def test_create_shape(self):  # P11 M13
        s, _, b, _ = self.rq(self.bob, "ada", 1200, note="taxi")
        self.assertEqual(s, 201)
        self.assertEqual(set(b), {"request_id", "requester_id", "requester_handle", "payer_id",
                                  "payer_handle", "amount", "currency", "note", "status",
                                  "payment_id", "created_at"})
        self.assertEqual((b["requester_handle"], b["payer_handle"], b["status"], b["payment_id"]),
                         ("bob", "ada", "pending", None))
        s, _, b, _ = self.rq(self.bob, "cy", 10 ** 9)  # more than cy holds
        self.assertEqual((s, b["status"]), (201, "pending"))

    def test_create_errors(self):  # P12
        for a in (0, -1, 1.5, "5", 1000000001, None, True):
            err(self, self.rq(self.bob, "ada", a), 422, "validation_failed")
        err(self, self.rq(self.bob, "bob", 5), 422, "self_request")
        err(self, self.rq(self.bob, "ghost", 5), 404, "not_found")
        err(self, self.rq(self.bob, "ada", 5, note="x" * 201), 422, "validation_failed")
        err(self, self.rq(self.bob, 3, 5), 400, "malformed_request")
        err(self, call("POST", "/requests", {"amount": 5}, self.bob, k()), 422, "validation_failed")

    def test_pay_flow(self):  # P13 P15 M14
        rq = self.rq(self.bob, "ada", 1200, note="taxi")[2]["request_id"]
        key = k()
        s, _, p, _ = call("POST", f"/requests/{rq}/pay", {"visibility": "private"}, self.ada, key)
        self.assertEqual(s, 201)
        self.assertEqual((p["request_id"], p["amount"], p["note"], p["visibility"],
                          p["from_handle"], p["to_handle"]), (rq, 1200, "taxi", "private", "ada", "bob"))
        self.assertEqual((me(self.ada)["balance"], me(self.bob)["balance"]), (8800, 3700))
        r = call("GET", "/requests", token=self.ada)[2]["requests"][0]
        self.assertEqual((r["status"], r["payment_id"]), ("paid", p["payment_id"]))
        s, _, p2, _ = call("POST", f"/requests/{rq}/pay", {"visibility": "private"}, self.ada, key)
        self.assertEqual((s, p2), (200, p))
        self.assertEqual(me(self.ada)["balance"], 8800)
        err(self, call("POST", f"/requests/{rq}/pay", {}, self.ada, k()), 409, "request_not_pending")
        err(self, call("POST", f"/requests/{rq}/pay", {"visibility": "private"}, self.ada, k()), 409,
            "request_not_pending")
        err(self, call("POST", f"/requests/{rq}/pay", {"visibility": "public"}, self.ada, key), 409,
            "idempotency_key_reuse")
        err(self, call("POST", f"/requests/{rq}/decline", token=self.ada), 409, "request_not_pending")
        err(self, call("POST", f"/requests/{rq}/cancel", token=self.bob), 409, "request_not_pending")

    def test_pay_errors(self):  # P14
        rq = self.rq(self.bob, "cy", 600)[2]["request_id"]
        err(self, call("POST", f"/requests/{rq}/pay", {}, self.cy, k()), 409, "insufficient_funds")
        self.assertEqual(call("GET", "/requests", token=self.cy)[2]["requests"][0]["status"], "pending")
        err(self, call("POST", f"/requests/{rq}/pay", {}, self.bob, k()), 403, "forbidden")
        err(self, call("POST", f"/requests/{rq}/pay", {}, self.ada, k()), 403, "forbidden")
        err(self, call("POST", "/requests/nope/pay", {}, self.cy, k()), 404, "not_found")
        err(self, call("POST", f"/requests/{rq}/pay", {"visibility": "x"}, self.cy, k()), 422, "validation_failed")
        self.assertEqual(pay(self.ada, "cy", 100)[0], 201)  # now payable
        self.assertEqual(call("POST", f"/requests/{rq}/pay", {}, self.cy, k())[0], 201)
        self.assertEqual(self.total(), 13000)

    def test_pay_empty_body_defaults(self):
        rq = self.rq(self.bob, "ada", 5)[2]["request_id"]
        s, _, p, _ = call("POST", f"/requests/{rq}/pay", token=self.ada, key=k())
        self.assertEqual((s, p["visibility"]), (201, "public"))

    def test_decline_cancel(self):  # P16 P17 Q6
        r1 = self.rq(self.bob, "ada", 5)[2]["request_id"]
        self.assertEqual(call("POST", f"/requests/{r1}/decline", token=self.ada)[2]["status"], "declined")
        self.assertEqual(call("POST", f"/requests/{r1}/decline", token=self.ada)[2]["status"], "declined")
        err(self, call("POST", f"/requests/{r1}/cancel", token=self.bob), 409, "request_not_pending")
        err(self, call("POST", f"/requests/{r1}/pay", {}, self.ada, k()), 409, "request_not_pending")
        err(self, call("POST", f"/requests/{r1}/decline", token=self.bob), 403, "forbidden")
        err(self, call("POST", f"/requests/{r1}/cancel", token=self.ada), 403, "forbidden")
        err(self, call("POST", f"/requests/{r1}/cancel", token=self.cy), 403, "forbidden")
        r2 = self.rq(self.bob, "ada", 5)[2]["request_id"]
        err(self, call("POST", f"/requests/{r2}/cancel", token=self.ada), 403, "forbidden")
        err(self, call("POST", f"/requests/{r2}/decline", token=self.bob), 403, "forbidden")
        self.assertEqual(call("POST", f"/requests/{r2}/cancel", token=self.bob)[2]["status"], "cancelled")
        self.assertEqual(call("POST", f"/requests/{r2}/cancel", token=self.bob)[2]["status"], "cancelled")
        err(self, call("POST", f"/requests/{r2}/decline", token=self.ada), 409, "request_not_pending")
        err(self, call("POST", "/requests/zz/decline", token=self.ada), 404, "not_found")
        err(self, call("POST", "/requests/zz/cancel", token=self.ada), 404, "not_found")

    def test_list_filters_paging(self):  # P18-P21 E11 E13
        ids = [self.rq(self.bob, "ada", 10 + i)[2]["request_id"] for i in range(5)]
        self.rq(self.ada, "bob", 7)
        call("POST", f"/requests/{ids[0]}/decline", token=self.ada)
        g = lambda q, t=self.ada: call("GET", "/requests" + q, token=t)
        self.assertEqual(len(g("")[2]["requests"]), 6)
        self.assertEqual(len(g("?direction=incoming")[2]["requests"]), 5)
        self.assertEqual(len(g("?direction=outgoing")[2]["requests"]), 1)
        self.assertEqual(len(g("?status=declined")[2]["requests"]), 1)
        self.assertEqual(len(g("?status=pending&direction=incoming")[2]["requests"]), 4)
        self.assertEqual(g("", self.cy)[2], {"requests": [], "has_more": False})
        full = [r["request_id"] for r in g("")[2]["requests"]]
        self.assertEqual(full[1:], list(reversed(ids)))  # newest first (within a second: by order)
        b = g("?limit=2&offset=0")[2]
        self.assertEqual((len(b["requests"]), b["has_more"]), (2, True))
        b = g("?limit=2&offset=4")[2]
        self.assertEqual((len(b["requests"]), b["has_more"]), (2, False))
        b = g("?limit=3&offset=3")[2]
        self.assertEqual((len(b["requests"]), b["has_more"]), (3, False))
        b = g("?offset=100")[2]
        self.assertEqual((b["requests"], b["has_more"]), ([], False))
        for q in ("?limit=0", "?limit=201", "?limit=-1", "?limit=1e2", "?limit=4.0", "?limit=+4",
                  "?limit=", "?limit=abc", "?offset=-1", "?offset=1e1", "?offset=", "?direction=sideways",
                  "?status=open", "?direction=", "?limit=%EF%BC%91"):
            err(self, g(q), 422, "validation_failed")
        for q in ("?limit=1", "?limit=200", "?offset=0", "?direction=incoming&status=paid&x=1"):
            self.assertEqual(g(q)[0], 200)

    def test_not_visible_to_third_party(self):  # P28
        rq = self.rq(self.bob, "ada", 5)[2]["request_id"]
        self.assertEqual(call("GET", "/requests", token=self.cy)[2]["requests"], [])
        self.assertEqual(call("GET", "/activity", token=self.cy)[2]["payments"], [])
        for act in ("decline", "cancel"):
            err(self, call("POST", f"/requests/{rq}/{act}", token=self.cy), 403, "forbidden")


class Feed(Base):
    def test_visibility(self):  # P27 P29
        pay(self.ada, "bob", 10, visibility="private")
        pay(self.ada, "bob", 20, visibility="public")
        pay(self.bob, "cy", 5, visibility="private")
        amt = lambda t: [p["amount"] for p in call("GET", "/activity", token=t)[2]["payments"]]
        self.assertEqual(amt(self.ada), [20, 10])
        self.assertEqual(amt(self.bob), [5, 20, 10])
        self.assertEqual(amt(self.cy), [5, 20])
        b = call("GET", "/activity?limit=1&offset=1", token=self.bob)[2]
        self.assertEqual((b["payments"][0]["amount"], b["has_more"]), (20, True))
        for q in ("?limit=0", "?limit=201", "?offset=-1", "?limit=1e1"):
            err(self, call("GET", "/activity" + q, token=self.bob), 422, "validation_failed")


class Splits(Base):
    def sp(self, tok, amount, handles, key=None, **extra):
        body = {"amount": amount, "participant_handles": handles}
        body.update(extra)
        return call("POST", "/splits", body, tok, key or k())

    def test_rounding_table(self):  # S1 S2
        for amount, n, exp in ((1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
                               (999, 3, [333, 333, 333]), (5, 5, [1] * 5)):
            reset(fixture(users=[user(h, 0) for h in "abcde"]))
            t = login("a")
            s, _, b, _ = self.sp(t, amount, list("abcde")[:n])
            self.assertEqual(s, 201)
            self.assertEqual([x["amount"] for x in b["shares"]], exp)
            self.assertEqual([x["amount"] for x in b["requests"]], exp[1:])
        reset(fixture())
        ada = login("ada")
        s, _, b, _ = self.sp(ada, 1000, ["cy", "bob", "ada"])
        self.assertEqual([(x["handle"], x["amount"]) for x in b["shares"]],
                         [("cy", 334), ("bob", 333), ("ada", 333)])

    def test_shape(self):  # P22 P23 S3
        s, _, b, _ = self.sp(self.ada, 3000, ["ada", "bob", "cy"], note="dinner")
        self.assertEqual(set(b), {"split_id", "amount", "currency", "note", "shares", "requests", "created_at"})
        self.assertEqual([r["payer_handle"] for r in b["requests"]], ["bob", "cy"])
        for r in b["requests"]:
            self.assertEqual((r["requester_handle"], r["status"], r["amount"], r["note"]),
                             ("ada", "pending", 1000, "dinner"))
        s, _, b, _ = self.sp(self.ada, 100, ["bob", "cy"])
        self.assertEqual([x["amount"] for x in b["shares"]], [50, 50])
        self.assertEqual(len(b["requests"]), 2)
        s, _, b, _ = self.sp(self.ada, 1, ["bob", "cy", "ada"])
        self.assertEqual([r["amount"] for r in b["requests"]], [1, 0])
        self.assertEqual(call("GET", "/requests", token=self.cy)[2]["requests"][0]["amount"], 0)
        self.assertEqual(call("GET", "/activity", token=self.cy)[2]["payments"], [])

    def test_zero_share_payable(self):  # S3 Q4
        b = self.sp(self.ada, 1, ["bob", "cy", "ada"])[2]
        zero = b["requests"][1]["request_id"]
        s, _, p, _ = call("POST", f"/requests/{zero}/pay", {}, self.cy, k())
        self.assertEqual((s, p["amount"]), (201, 0))
        self.assertEqual(self.total(), 13000)

    def test_only_caller(self):  # P25
        s, _, b, _ = self.sp(self.ada, 77, ["ada"])
        self.assertEqual((s, b["requests"], b["shares"]), (201, [], [{"handle": "ada", "amount": 77}]))
        self.assertEqual(me(self.ada)["balance"], 10000)
        # no balance check anywhere
        self.assertEqual(self.sp(self.cy, 10 ** 9, ["ada", "bob"])[0], 201)

    def test_errors(self):  # P24
        for a in (0, -5, 1.5, "5", None, 1000000001):
            err(self, self.sp(self.ada, a, ["bob"]), 422, "validation_failed")
        err(self, self.sp(self.ada, 5, []), 422, "validation_failed")
        err(self, self.sp(self.ada, 5, ["bob", "bob"]), 422, "validation_failed")
        err(self, self.sp(self.ada, 5, ["bob"], note="x" * 201), 422, "validation_failed")
        err(self, self.sp(self.ada, 5, ["bob", "ghost"]), 404, "not_found")
        err(self, self.sp(self.ada, 5, "bob"), 400, "malformed_request")
        err(self, self.sp(self.ada, 5, [1]), 400, "malformed_request")
        err(self, call("POST", "/splits", {"amount": 5}, self.ada, k()), 422, "validation_failed")
        self.assertEqual(call("GET", "/requests", token=self.bob)[2]["requests"], [])  # nothing created

    def test_paid_in_full_conserves(self):  # S4
        for n in range(3):
            b = self.sp(self.ada, 1000 + n, ["ada", "bob", "cy"])[2]
            for r in b["requests"]:
                tok = {"bob": self.bob, "cy": self.cy}[r["payer_handle"]]
                s = call("POST", f"/requests/{r['request_id']}/pay", {}, tok, k())[0]
                self.assertIn(s, (201, 409))
        self.assertEqual(self.total(), 13000)


class Idempotency(Base):
    def endpoints(self):
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, k())[2]["request_id"]
        rq2 = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, k())[2]["request_id"]
        reset_ops = None
        return [
            ("/payments", self.ada, {"to_handle": "bob", "amount": 5}, {"to_handle": "bob", "amount": 6}),
            ("/requests", self.bob, {"payer_handle": "ada", "amount": 5}, {"payer_handle": "ada", "amount": 6}),
            (f"/requests/{rq}/pay", self.ada, {}, {"visibility": "private"}),
            ("/splits", self.ada, {"amount": 5, "participant_handles": ["bob"]},
             {"amount": 6, "participant_handles": ["bob"]}),
        ]

    def test_all_four(self):  # K1-K8 K10 K11
        for path, tok, body, other in self.endpoints():
            err(self, call("POST", path, body, tok), 400, "missing_idempotency_key")
            err(self, call("POST", path, body, tok, key=""), 400, "missing_idempotency_key")
            key = k()
            s1, _, b1, _ = call("POST", path, body, tok, key)
            self.assertEqual(s1, 201, path)
            s2, _, b2, _ = call("POST", path, body, tok, key)
            self.assertEqual((s2, b2), (200, b1), path)
            # key order / whitespace irrelevant
            raw = json.dumps(dict(reversed(list(body.items()))), indent=3).encode()
            s3, _, b3, _ = call("POST", path, raw=raw, token=tok, key=key)
            self.assertEqual((s3, b3), (200, b1), path)
            err(self, call("POST", path, other, tok, key), 409, "idempotency_key_reuse")
            # K11: invalid body with claimed key is still reuse
            err(self, call("POST", path, {"amount": "bad", "payer_handle": 1}, tok, key), 409,
                "idempotency_key_reuse")
            # non-object body: 400 before key resolution
            err(self, call("POST", path, raw=b"[1]", token=tok, key=key), 400, "malformed_request")
            err(self, call("POST", path, body, tok, key="x" * 256), 422, "validation_failed")

    def test_effect_once(self):
        key = k()
        for _ in range(3):
            pay(self.ada, "bob", 100, key=key)
        self.assertEqual(me(self.ada)["balance"], 9900)

    def test_key_length(self):  # E12
        self.assertEqual(pay(self.ada, "bob", 1, key="x" * 255)[0], 201)
        err(self, pay(self.ada, "bob", 1, key="x" * 256), 422, "validation_failed")
        self.assertEqual(pay(self.ada, "bob", 1, key="y")[0], 201)

    def test_failed_key_reusable(self):  # K5
        key = k()
        err(self, pay(self.cy, "bob", 5000, key=key), 409, "insufficient_funds")
        err(self, pay(self.cy, "nobody", 5, key=key), 404, "not_found")
        s, _, b, _ = pay(self.cy, "bob", 5, key=key)
        self.assertEqual(s, 201)
        self.assertEqual(pay(self.cy, "bob", 5, key=key)[:1], (200,))

    def test_user_scope_and_path_scope(self):  # K6 K7
        key = k()
        self.assertEqual(pay(self.ada, "bob", 5, key=key)[0], 201)
        self.assertEqual(pay(self.bob, "ada", 5, key=key)[0], 201)
        self.assertEqual(pay(self.cy, "ada", 5, key=key)[0], 201)
        body = {"payer_handle": "bob", "amount": 5, "to_handle": "bob"}
        s = call("POST", "/requests", body, self.ada, key)[0]
        self.assertEqual(s, 201)
        r1 = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, k())[2]["request_id"]
        r2 = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, k())[2]["request_id"]
        key = k()
        self.assertEqual(call("POST", f"/requests/{r1}/pay", {}, self.ada, key)[0], 201)
        self.assertEqual(call("POST", f"/requests/{r2}/pay", {}, self.ada, key)[0], 201)

    def test_k8_empty_vs_explicit(self):
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, k())[2]["request_id"]
        key = k()
        self.assertEqual(call("POST", f"/requests/{rq}/pay", {}, self.ada, key)[0], 201)
        err(self, call("POST", f"/requests/{rq}/pay", {"visibility": "public"}, self.ada, key), 409,
            "idempotency_key_reuse")

    def test_replay_after_cancel(self):  # K10
        key = k()
        s, _, b, _ = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, key)
        call("POST", f"/requests/{b['request_id']}/cancel", token=self.bob)
        s2, _, b2, _ = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, key)
        self.assertEqual((s2, b2), (200, b))
        self.assertEqual(b2["status"], "pending")

    def test_number_equality(self):
        key = k()
        s = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1000}', token=self.ada, key=key)[0]
        s2 = call("POST", "/payments", raw=b'{"amount":1e3,"to_handle":"bob"}', token=self.ada, key=key)[0]
        self.assertEqual((s, s2), (201, 200))


class Settlements(Base):
    def setUp(self):
        reset(fixture(users=[user("ada", 10000), user("bob", 0), user("cy", 500), user("dan", 0)],
                      settlement_operator_ids=["u_dan"]))
        self.ada, self.bob, self.cy, self.dan = login("ada"), login("bob"), login("cy"), login("dan")

    def st(self, tok, transfers, key=None):
        return call("POST", "/settlements", {"transfers": transfers}, tok, key or k())

    def T(self, f, t, a, **x):
        d = {"from_handle": f, "to_handle": t, "amount": a}
        d.update(x)
        return d

    def test_auth(self):  # N1
        err(self, call("POST", "/settlements", {"transfers": []}, key=k()), 401, "unauthenticated")
        err(self, self.st(self.ada, [self.T("ada", "bob", 1)]), 403, "forbidden")
        err(self, call("POST", "/settlements", {}, self.ada, k()), 403, "forbidden")
        err(self, call("POST", "/settlements", {}, self.dan), 400, "missing_idempotency_key")

    def test_net_success(self):  # N5 N7 N8
        s, _, b, _ = self.st(self.dan, [self.T("ada", "bob", 100), self.T("bob", "cy", 50, note="n",
                                                                           visibility="private", junk=1)])
        self.assertEqual(s, 201)
        self.assertEqual(set(b), {"settlement_id", "committed_at", "payments"})
        self.assertEqual([p["amount"] for p in b["payments"]], [100, 50])
        for p in b["payments"]:
            self.assertEqual(p["settlement_id"], b["settlement_id"])
            self.assertIsNone(p["request_id"])
            self.assertEqual(p["created_at"], b["committed_at"])
        self.assertEqual((b["payments"][1]["note"], b["payments"][1]["visibility"]), ("n", "private"))
        self.assertEqual((me(self.ada)["balance"], me(self.bob)["balance"], me(self.cy)["balance"]),
                         (9900, 50, 550))
        pub = call("GET", "/activity", token=self.dan)[2]["payments"]  # operator not a party
        self.assertEqual([p["amount"] for p in pub], [100])
        self.assertEqual(pub[0]["settlement_id"], b["settlement_id"])
        self.assertEqual(len(call("GET", "/activity", token=self.cy)[2]["payments"]), 2)
        self.assertEqual(pay(self.ada, "bob", 1)[2]["settlement_id"], None)

    def test_not_affordable_and_atomic(self):  # N5 N6
        key = k()
        err(self, self.st(self.dan, [self.T("ada", "bob", 100), self.T("bob", "cy", 101)], key), 409,
            "insufficient_funds")
        err(self, self.st(self.dan, [self.T("cy", "bob", 600)], key), 409, "insufficient_funds")
        self.assertEqual((me(self.ada)["balance"], me(self.bob)["balance"]), (10000, 0))
        self.assertEqual(call("GET", "/activity", token=self.dan)[2]["payments"], [])
        self.assertEqual(self.st(self.dan, [self.T("ada", "bob", 1)], key)[0], 201)  # key unclaimed

    def test_shape_and_precedence(self):  # N2 N3 N4
        ok = self.T("ada", "bob", 1)
        for tr in (None, "x", {}, [], [1], [ok, "s"], [ok] * 33, [None]):
            body = {} if tr is None else {"transfers": tr}
            err(self, call("POST", "/settlements", body, self.dan, k()), 422, "validation_failed")
        self.assertEqual(self.st(self.dan, [ok] * 32)[0], 201)
        self.assertEqual(self.st(self.dan, [ok])[0], 201)
        err(self, self.st(self.dan, [self.T("ada", "ada", 5)]), 422, "self_payment")
        err(self, self.st(self.dan, [self.T("ada", "ghost", 5)]), 404, "not_found")
        err(self, self.st(self.dan, [self.T("ghost", "ada", 5)]), 404, "not_found")
        for a in (0, 1.5, "5", None, 10 ** 9 + 1, True):
            err(self, self.st(self.dan, [self.T("ada", "bob", a)]), 422, "validation_failed")
        err(self, self.st(self.dan, [self.T("ada", "bob", 5, note=3)]), 422, "validation_failed")
        err(self, self.st(self.dan, [self.T("ada", "bob", 5, visibility="x")]), 422, "validation_failed")
        err(self, self.st(self.dan, [self.T("ada", "bob", 5, note="x" * 201)]), 422, "validation_failed")
        # first failing entry decides, and entry errors beat insufficient funds
        err(self, self.st(self.dan, [ok, self.T("ada", "bob", 0), self.T("ada", "ghost", 5)]), 422,
            "validation_failed")
        err(self, self.st(self.dan, [ok, self.T("ada", "ghost", 5), self.T("ada", "ada", 5)]), 404, "not_found")
        err(self, self.st(self.dan, [self.T("cy", "bob", 10 ** 9), self.T("ada", "ada", 5)]), 422, "self_payment")

    def test_replay_and_reuse(self):  # N11
        key = k()
        s, _, b, _ = self.st(self.dan, [self.T("ada", "bob", 7)], key)
        s2, _, b2, _ = self.st(self.dan, [self.T("ada", "bob", 7)], key)
        self.assertEqual((s, s2, b2), (201, 200, b))
        err(self, self.st(self.dan, [self.T("ada", "bob", 8)], key), 409, "idempotency_key_reuse")
        self.assertEqual(me(self.bob)["balance"], 7)

    def test_operator_nothing_else(self):  # N10 N13
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, k())[2]["request_id"]
        pay(self.ada, "bob", 3, visibility="private")
        self.assertEqual(call("GET", "/requests", token=self.dan)[2]["requests"], [])
        self.assertEqual(call("GET", "/activity", token=self.dan)[2]["payments"], [])
        err(self, call("POST", f"/requests/{rq}/decline", token=self.dan), 403, "forbidden")
        err(self, call("POST", f"/requests/{rq}/pay", {}, self.dan, k()), 403, "forbidden")
        # operator may be a party, or move others' money
        self.assertEqual(self.st(self.dan, [self.T("dan", "ada", 0 + 1)])[0], 409)
        self.assertEqual(self.st(self.dan, [self.T("ada", "dan", 10)])[0], 201)
        reset(fixture())
        ada = login("ada")
        err(self, call("POST", "/settlements", {"transfers": [self.T("ada", "bob", 1)]}, ada, k()), 403, "forbidden")


class ExportImport(Base):
    def test_roundtrip(self):  # X1-X8 X11
        reset(fixture(settlement_operator_ids=["u_ada"]))
        ada, bob = login("ada"), login("bob")
        k1, k2, k3 = k(), k(), k()
        p = pay(ada, "bob", 100, key=k1, note="héllo")[2]
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 9}, bob, k2)[2]
        sp = call("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "bob", "cy"]}, ada, k3)[2]
        stk = k()
        st = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 3}]}, ada, stk)[2]
        err(self, pay(ada, "bob", 10 ** 9, key=k()), 409, "insufficient_funds")
        before = {t: (me(t), call("GET", "/activity", token=t)[2], call("GET", "/requests", token=t)[2])
                  for t in (ada, bob)}
        s, h, snap, raw = call("GET", "/_test/export")
        self.assertEqual(s, 200)
        self.assertEqual((snap["track"], snap["format_version"]), ("pocketful", 1))
        self.assertIsInstance(snap["state"], dict)
        self.assertEqual(call("GET", "/_test/export")[3], raw)  # read-only
        pay(ada, "bob", 1)  # later writes do not affect the snapshot
        reset(fixture(users=[user("zed", 1)]))
        err(self, call("GET", "/me", token=ada), 401, "unauthenticated")
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)  # repeat: no duplication
        after = {t: (me(t), call("GET", "/activity", token=t)[2], call("GET", "/requests", token=t)[2])
                 for t in (ada, bob)}
        self.assertEqual(before, after)
        self.assertEqual(login("ada") is not None, True)
        s, _, b, _ = pay(ada, "bob", 100, key=k1, note="héllo")
        self.assertEqual((s, b), (200, p))
        err(self, pay(ada, "bob", 101, key=k1), 409, "idempotency_key_reuse")
        self.assertEqual(call("POST", "/requests", {"payer_handle": "ada", "amount": 9}, bob, k2)[:1], (200,))
        self.assertEqual(call("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "bob", "cy"]}, ada, k3)[2], sp)
        s, _, b, _ = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 3}]}, ada, stk)
        self.assertEqual((s, b), (200, st))
        self.assertEqual(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}, ada, k())[0], 201)
        self.assertEqual(pay(ada, "bob", 1, key=k())[0], 201)  # ids/seq continue without clash
        ids = [x["payment_id"] for x in call("GET", "/activity?limit=200", token=ada)[2]["payments"]]
        self.assertEqual(len(ids), len(set(ids)))
        reset(fixture())  # X9
        err(self, call("GET", "/me", token=bob), 401, "unauthenticated")
        self.assertEqual(call("GET", "/activity", token=login("ada"))[2]["payments"], [])

    def test_invalid(self):  # X5
        pay(self.ada, "bob", 5)
        good = call("GET", "/_test/export")[2]
        err(self, call("POST", "/_test/import", raw=b"{"), 400, "malformed_request")
        bads = [{}, {"track": "pocketful"}, {**good, "track": "x"}, {**good, "format_version": 2},
                {**good, "state": None}, {**good, "state": {}}, {**good, "state": []}, [], 5,
                {**good, "state": {**good["state"], "users": "x"}},
                {**good, "state": {**good["state"], "tokens": {"a": "nouser"}}}]
        users = json.loads(json.dumps(good["state"]["users"]))
        users[0]["balance"] = -5
        bads.append({**good, "state": {**good["state"], "users": users}})
        for bad in bads:
            err(self, call("POST", "/_test/import", bad), 422, "validation_failed")
        self.assertEqual(me(self.ada)["balance"], 9995)

    def test_import_in_fresh_state_replaces(self):  # X4
        snap = call("GET", "/_test/export")[2]
        reset(fixture(users=[user("zed", 1)]))
        call("POST", "/_test/import", snap)
        err(self, call("POST", "/auth/login", {"email": "zed@example.com", "password": "correct horse"}), 401,
            "unauthenticated")


class Hardening(Base):
    """Verifier findings F1/F2: never 5xx, fixture amounts in integral forms."""

    def test_huge_exponents(self):
        for raw, path in ((b'{"to_handle":"bob","amount":1e1000000000000000000}', "/payments"),
                          (b'{"to_handle":"bob","amount":5,"note":1e1000000000000000000}', "/payments")):
            err(self, call("POST", path, raw=raw, token=self.ada, key=k()), 422, "validation_failed")
        err(self, call("POST", "/auth/login", raw=b'{"email":"a@b.c","password":"x","z":1e999999999999999999999}'),
            401, "unauthenticated")
        s = call("POST", "/_test/reset", raw=b'{"x":1e-999999999999999999999}')[0]
        self.assertLess(s, 500)
        reset(fixture())
        s = call("POST", "/_test/import", raw=b'{"x":1E+9223372036854775808}')[0]
        self.assertEqual(s, 422)

    def test_odd_methods_and_targets(self):
        for m in ("TRACE", "PROPFIND", "get", "CONNECT"):
            s, _, b, _ = call(m, "/health")
            self.assertEqual(s // 100, 4, m)
        import socket
        from helpers import HOST, PORT
        for line in (b"GET http://[bad/health HTTP/1.1", b"GET /health HTTP/3.0", b"GARBAGE",
                     b"GET /health HTTP/1.1 extra junk", b"get /health HTTP/1.1"):
            c = socket.create_connection((HOST, PORT), timeout=5)
            c.sendall(line + b"\r\nHost: x\r\nConnection: close\r\n\r\n")
            data = b""
            while True:
                chunk = c.recv(4096)
                if not chunk:
                    break
                data += chunk
            c.close()
            status = int(data.split(b" ")[1])
            self.assertIn(status // 100, (2, 4), (line, data[:80]))
            if status >= 400:
                self.assertIn(b'"error"', data, line)

    def test_surrogate_password(self):
        s = call("POST", "/auth/signup", raw=b'{"email":"sur@example.com","password":"\\ud800aaaaaaaa","display_name":"x"}')[0]
        self.assertEqual(s, 201)
        s = call("POST", "/_test/reset", raw=json.dumps(fixture(users=[user("ada", 1, pw="\ud800aaaaaaaa")])).encode())[0]
        self.assertEqual(s, 204)

    def test_invalid_import_states(self):
        pay(self.ada, "bob", 5)
        call("POST", "/splits", {"amount": 9, "participant_handles": ["bob"]}, self.ada, k())
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 2}, self.bob, k())
        good = call("GET", "/_test/export")[2]
        def mut(f):
            d = json.loads(json.dumps(good))
            f(d["state"])
            return d
        bads = [mut(lambda st: st["payments"][0].update(created_at="2026-01-01T00:00:00")),
                mut(lambda st: st["requests"][0].update(created_at="2026-01-01T00:00:00")),
                mut(lambda st: st["splits"][0].update(response=-1.5)),
                mut(lambda st: st["payments"][0].update(amount=1.5))]
        for bad in bads:
            err(self, call("POST", "/_test/import", bad), 422, "validation_failed")
        self.assertEqual(call("GET", "/activity", token=self.ada)[0], 200)
        self.assertEqual(call("GET", "/_test/export")[0], 200)

    def test_mutated_exports_fuzz(self):
        pay(self.ada, "bob", 5)
        call("POST", "/splits", {"amount": 9, "participant_handles": ["bob"]}, self.ada, k())
        call("POST", "/requests", {"payer_handle": "ada", "amount": 2}, self.bob, k())
        call("POST", "/settlements", {"transfers": []}, self.ada, k())
        good = call("GET", "/_test/export")[2]
        bad_values = [None, -1, 1.5, "x", "", True, [], {}, "2026-01-01T00:00:00", 10 ** 40, "\ud800"]
        paths = []
        def walk(node, path):
            if isinstance(node, dict):
                for key, v in node.items():
                    paths.append(path + [key])
                    walk(v, path + [key])
            elif isinstance(node, list) and node:
                paths.append(path + [0])
                walk(node[0], path + [0])
        walk(good["state"], [])
        for path in paths:
            for bv in bad_values:
                d = json.loads(json.dumps(good))
                node = d["state"]
                for p in path[:-1]:
                    node = node[p]
                node[path[-1]] = bv
                before = call("GET", "/_test/export")[3]
                s = call("POST", "/_test/import", d)[0]
                self.assertIn(s, (204, 422), (path, bv, s))
                if s == 422:
                    self.assertEqual(call("GET", "/_test/export")[3], before, (path, bv))
                else:
                    reset(fixture())
                    call("POST", "/_test/import", good)
                    continue
                for ep in ("/activity", "/requests"):
                    self.assertLess(call("GET", ep, token=self.ada)[0], 500, (path, bv))

    def test_body_fuzz_never_5xx(self):
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 2}, self.bob, k())[2]["request_id"]
        vals = [None, True, -1, 0, 1.5, 10 ** 40, "", "\ud800", "a\u0000b", "\u202e", "x" * 5000, [], {}, [[]],
                [{"from_handle": "ada"}], {"a": {"b": [1, {}]}}, "ada", "bob", 5, 1e308]
        eps = [("/payments", self.ada, ["to_handle", "amount", "note", "visibility"]),
               ("/requests", self.bob, ["payer_handle", "amount", "note"]),
               ("/splits", self.ada, ["amount", "participant_handles", "note"]),
               ("/settlements", self.ada, ["transfers"]),
               (f"/requests/{rq}/pay", self.ada, ["visibility"]),
               ("/auth/signup", None, ["email", "password", "display_name"]),
               ("/auth/login", None, ["email", "password"])]
        base = {"to_handle": "bob", "amount": 5, "note": "n", "visibility": "public", "payer_handle": "ada",
                "participant_handles": ["bob"], "transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}],
                "email": "fz@x.io", "password": "12345678", "display_name": "F"}
        for path, tok, fields in eps:
            for f in fields:
                for v in vals:
                    body = {x: base[x] for x in fields}
                    body[f] = v
                    for key in (k(), "\u00e9" * 200, "\ud800"):
                        try:
                            s = call("POST", path, body, tok, key)[0]
                        except UnicodeError:
                            continue
                        self.assertLess(s, 500, (path, f, v))
        for h in ({"Authorization": "Bearer \u00e9"}, {"Idempotency-Key": "\u00e9" * 300}):
            try:
                self.assertLess(call("POST", "/payments", {}, self.ada, None, headers=h)[0], 500)
            except UnicodeError:
                pass

    def test_fixture_integral_forms(self):
        fx = fixture()
        raw = json.dumps(fx).replace('"balance": 10000', '"balance": 10000.0').replace('"balance": 2500', '"balance": 1e4')
        s = call("POST", "/_test/reset", raw=raw.encode())[0]
        self.assertEqual(s, 204)
        self.assertEqual(me(login("ada"))["balance"], 10000)
        self.assertEqual(me(login("bob"))["balance"], 10000)
        raw = b'{"currency":"EUR","minor_units":2,"users":[{"id":"u_a","email":"a@x.io","password":"correct horse","display_name":"A","handle":"a","balance":1e2},{"id":"u_b","email":"b@x.io","password":"correct horse","display_name":"B","handle":"b","balance":0}],"payments":[{"id":"p_1","from_user_id":"u_a","to_user_id":"u_b","amount":500.0}]}'
        self.assertEqual(call("POST", "/_test/reset", raw=raw)[0], 204)
        err(self, call("POST", "/_test/reset", raw=raw.replace(b'"balance":0', b'"balance":-0.5')), 422, "validation_failed")

    def test_many_users_reset_fast(self):
        users = [user("u%d" % i, 1, pw="pw%06d" % i) for i in range(300)]
        t = __import__("time").time()
        reset(fixture(users=users))
        self.assertLess(__import__("time").time() - t, 8)


if __name__ == "__main__":
    unittest.main()
