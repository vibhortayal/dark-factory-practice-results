"""Spec-derived tests: runtime contract, auth, payments, requests, errors (rows B-E, G)."""
import re
import threading
import unittest

from helpers import Api, call, fixture, user

RFC3339 = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")


class Contract(Api):
    def test_health_and_unknown_route(self):
        s, b, r = call("GET", "/health")
        self.assertEqual((s, b), (200, {"status": "ok"}))
        for method, path in (("GET", "/authorizations"), ("POST", "/health"), ("GET", "/statement")):
            s, b, _ = call(method, path)
            self.assertEqual((s, b["error"]["code"]), (404, "not_found"))

    def test_reset_replaces_everything_and_bad_fixture_changes_nothing(self):
        old = self.tok["ada"]
        k = "same-key"
        self.ok("ada", "POST", "/payments", {"to_handle": "bob", "amount": 5}, key=k)
        bad = fixture()
        bad["users"][0]["balance"] = -1
        s, b, _ = call("POST", "/_test/reset", bad)
        self.assertEqual((s, b["error"]["code"]), (422, "validation_failed"))
        self.assertEqual(self.balance("ada"), 9995)
        for payload, status in (([], 400), ({}, 422), ({"currency": "EUR", "minor_units": 2}, 422)):
            self.assertEqual(call("POST", "/_test/reset", payload)[0], status)
        self.assertEqual(call("POST", "/_test/reset", raw=b"{bad")[0], 400)
        dup = fixture()
        dup["users"].append(user("u_x", "ada", 1, "x@example.com"))
        self.assertEqual(call("POST", "/_test/reset", dup)[0], 422)
        self.assertEqual(self.balance("ada"), 9995)
        self.reset()
        s, _, _ = call("GET", "/me", token=old)
        self.assertEqual(s, 401)
        self.ok("ada", "POST", "/payments", {"to_handle": "bob", "amount": 5}, key=k)

    def test_currencies_and_seeded_ids_do_not_collide(self):
        for cur, mu in (("JPY", 0), ("BHD", 3)):
            fx = fixture(currency=cur, minor_units=mu, payments=[
                {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5}])
            self.reset(fx)
            me = self.ok("ada", "GET", "/me", status=200)
            self.assertEqual((me["currency"], me["minor_units"]), (cur, mu))
            p = self.ok("ada", "POST", "/payments", {"to_handle": "bob", "amount": 1})
            self.assertEqual(p["currency"], cur)
            self.assertNotEqual(p["payment_id"], "p_1")
            self.assertLessEqual(len(p["payment_id"]), 64)

    def test_unknown_fields_and_query_ignored(self):
        p = self.ok("ada", "POST", "/payments", {"to_handle": "bob", "amount": 5, "zzz": [1]})
        self.assertTrue(RFC3339.match(p["created_at"]))
        self.ok("ada", "GET", "/activity?foo=1&limit=5", status=200)
        self.ok("ada", "GET", "/me?z=1", status=200)

    def test_non_json_content_type_still_parsed(self):
        s, _, _ = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1}',
                       token=self.tok["ada"], key="k1", headers={"Content-Type": "text/plain"})
        self.assertEqual(s, 201)

    def test_seeded_balance_is_final_and_login_works(self):
        fx = fixture(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                                "amount": 500, "visibility": "private"}])
        self.reset(fx)
        self.assertEqual(self.balance("ada"), 10000)
        self.assertEqual(len(self.ok("cy", "GET", "/activity", status=200)["payments"]), 0)
        self.assertEqual(len(self.ok("bob", "GET", "/activity", status=200)["payments"]), 1)


class Auth(Api):
    def test_signup_login(self):
        s, b, _ = call("POST", "/auth/signup", {"email": "Ada.Lovelace+x@example.com",
                                                "password": "12345678", "display_name": "L"})
        self.assertEqual(s, 201)
        me = self.ok(b["token"], "GET", "/me", status=200)
        self.assertEqual((me["handle"], me["balance"]), ("ada_lovelace_x", 0))
        s, b2, _ = call("POST", "/auth/login", {"email": "Ada.Lovelace+x@example.com",
                                                "password": "12345678"})
        self.assertEqual(s, 200)
        self.assertNotEqual(b["token"], b2["token"])
        self.assertEqual(self.balance(b["token"]), 0)
        self.assertEqual(self.balance(b2["token"]), 0)

    def test_signup_errors(self):
        post = lambda body: call("POST", "/auth/signup", body)
        good = {"email": "n@x.com", "password": "12345678", "display_name": "N"}
        self.assertEqual(post({**good, "password": "1234567"})[0], 422)
        for email in ("nodomain", "@x.com", "a@", "", "a@@b"):
            self.assertEqual(post({**good, "email": email})[0], 422, email)
        self.assertEqual(post({**good, "email": 1})[0], 400)
        self.assertEqual(post({"email": "a@b.c"})[0], 422)
        self.assertEqual(call("POST", "/auth/signup", raw=b"[]")[0], 400)
        s, b, _ = post({**good, "email": "ada@other.com"})
        self.assertEqual((s, b["error"]["code"]), (409, "handle_taken"))
        self.assertEqual(call("POST", "/auth/login", {"email": "ada@other.com",
                                                      "password": "12345678"})[0], 401)
        s, b, _ = post({**good, "email": "ada@example.com"})
        self.assertEqual((s, b["error"]["code"]), (409, "email_taken"))
        self.assertEqual(post({**good, "email": "a.b@x.com"})[0], 201)
        s, b, _ = post({**good, "email": "a_b@x.com"})
        self.assertEqual((s, b["error"]["code"]), (409, "handle_taken"))
        s, b, _ = post({**good, "email": "x" * 25 + "@y.com"})
        self.assertEqual(self.balance(b["token"]), 0)
        self.assertEqual(self.ok(b["token"], "GET", "/me", status=200)["handle"], "x" * 20)

    def test_login_failures_and_missing_auth(self):
        for body in ({"email": "ada@example.com", "password": "nope"},
                     {"email": "no@example.com", "password": "correct horse"}):
            self.assertEqual(call("POST", "/auth/login", body)[0], 401)
        self.assertEqual(call("POST", "/auth/login", {"email": 1, "password": "x"})[0], 400)
        self.assertEqual(call("POST", "/auth/login", {"email": "a@b.c"})[0], 422)
        for method, path in (("GET", "/me"), ("POST", "/payments"), ("GET", "/activity"),
                             ("GET", "/requests"), ("POST", "/splits"), ("POST", "/settlements"),
                             ("POST", "/requests/x/pay"), ("POST", "/requests/x/decline"),
                             ("POST", "/requests/x/cancel"), ("POST", "/requests")):
            for hdr in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "},
                        {"Authorization": "Bearer nope"}):
                s, b, _ = call(method, path, {}, key="k", headers=hdr)
                self.assertEqual((s, b["error"]["code"]), (401, "unauthenticated"), path)


class Payments(Api):
    def test_payment_shape_and_balances(self):
        p = self.ok("ada", "POST", "/payments",
                    {"to_handle": "bob", "amount": 1500, "note": "  dîner 🍝<script> ",
                     "visibility": "private"})
        self.assertEqual(set(p), {"payment_id", "from_user_id", "from_handle", "to_user_id",
                                  "to_handle", "amount", "currency", "note", "visibility",
                                  "request_id", "settlement_id", "created_at"})
        self.assertEqual(p["note"], "  dîner 🍝<script> ")
        self.assertEqual((p["request_id"], p["settlement_id"]), (None, None))
        self.assertEqual((self.balance("ada"), self.balance("bob")), (8500, 4000))
        self.assertEqual(self.ok("ada", "POST", "/payments",
                                 {"to_handle": "bob", "amount": 1})["visibility"], "public")

    def test_amount_forms_and_boundaries(self):
        s, b, _ = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1e3}',
                       token=self.tok["ada"], key="a")
        self.assertEqual((s, b["amount"]), (201, 1000))
        s, b, _ = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1000.0}',
                       token=self.tok["ada"], key="b")
        self.assertEqual((s, b["amount"]), (201, 1000))
        for bad in (0, -1, 1000000001, 1.5, "10", True, None, [], {}, 10 ** 30):
            self.err("ada", "POST", "/payments", {"to_handle": "bob", "amount": bad},
                     422, "validation_failed")
        s, _, _ = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1e400}',
                       token=self.tok["ada"], key="c")
        self.assertEqual(s, 422)
        self.err("ada", "POST", "/payments", {"to_handle": "bob"}, 422, "validation_failed")
        self.err("ada", "POST", "/payments", {"amount": 1}, 422, "validation_failed")
        self.err("ada", "POST", "/payments", {"to_handle": 5, "amount": 1}, 400, "malformed_request")
        self.err("ada", "POST", "/payments", None, 400, "malformed_request", raw=b"{bad")
        self.err("ada", "POST", "/payments", None, 400, "malformed_request", raw=b'"x"')

    def test_funds_boundary(self):
        self.err("cy", "POST", "/payments", {"to_handle": "bob", "amount": 1}, 409, "insufficient_funds")
        self.err("bob", "POST", "/payments", {"to_handle": "ada", "amount": 2501}, 409, "insufficient_funds")
        self.ok("bob", "POST", "/payments", {"to_handle": "ada", "amount": 2500})
        self.assertEqual(self.balance("bob"), 0)
        self.assertEqual(self.ok("bob", "GET", "/activity", status=200)["payments"][0]["amount"], 2500)

    def test_field_rules(self):
        self.err("ada", "POST", "/payments", {"to_handle": "ada", "amount": 1}, 422, "self_payment")
        self.err("ada", "POST", "/payments", {"to_handle": "nobody", "amount": 1}, 404, "not_found")
        self.err("ada", "POST", "/payments", {"to_handle": "BOB", "amount": 1}, 404, "not_found")
        self.err("ada", "POST", "/payments", {"to_handle": "", "amount": 1}, 404, "not_found")
        self.ok("ada", "POST", "/payments", {"to_handle": "bob", "amount": 1, "note": "é" * 200})
        for note in ("x" * 201, None, 5, ["a"]):
            self.err("ada", "POST", "/payments", {"to_handle": "bob", "amount": 1, "note": note},
                     422, "validation_failed")
        for vis in ("friends", None, 1, "PUBLIC"):
            self.err("ada", "POST", "/payments", {"to_handle": "bob", "amount": 1, "visibility": vis},
                     422, "validation_failed")
        self.assertEqual(self.total(), 12500)

    def test_failed_payment_leaves_no_trace(self):
        self.err("cy", "POST", "/payments", {"to_handle": "bob", "amount": 5}, 409, "insufficient_funds")
        self.assertEqual(self.ok("bob", "GET", "/activity", status=200)["payments"], [])

    def test_overdraft_race(self):
        results = []

        def go(i):
            s, _, _ = call("POST", "/payments", {"to_handle": "ada", "amount": 1000},
                           token=self.tok["bob"], key=f"race-{i}")
            results.append(s)
        threads = [threading.Thread(target=go, args=(i,)) for i in range(40)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual((results.count(201), results.count(409)), (2, 38))
        self.assertEqual((self.balance("bob"), self.total()), (500, 12500))


class Requests(Api):
    def make(self, requester="bob", payer="ada", amount=1200, **kw):
        return self.ok(requester, "POST", "/requests",
                       {"payer_handle": payer, "amount": amount, "note": "taxi", **kw})

    def test_lifecycle_and_roles(self):
        r = self.make()
        self.assertEqual(set(r), {"request_id", "requester_id", "requester_handle", "payer_id",
                                  "payer_handle", "amount", "currency", "note", "status",
                                  "payment_id", "created_at"})
        rid = r["request_id"]
        for who in ("bob", "cy"):
            self.err(who, "POST", f"/requests/{rid}/pay", {}, 403, "forbidden")
        self.err("ada", "POST", f"/requests/{rid}/cancel", None, 403, "forbidden", key=None)
        self.err("cy", "POST", f"/requests/{rid}/decline", None, 403, "forbidden", key=None)
        self.err("ada", "POST", "/requests/nope/pay", {}, 404, "not_found")
        pay = self.ok("ada", "POST", f"/requests/{rid}/pay", {"visibility": "private"})
        self.assertEqual((pay["request_id"], pay["visibility"], pay["amount"]), (rid, "private", 1200))
        self.assertEqual((self.balance("ada"), self.balance("bob")), (8800, 3700))
        got = self.ok("bob", "GET", "/requests", status=200)["requests"][0]
        self.assertEqual((got["status"], got["payment_id"]), ("paid", pay["payment_id"]))
        self.err("ada", "POST", f"/requests/{rid}/pay", {}, 409, "request_not_pending")
        self.err("ada", "POST", f"/requests/{rid}/decline", None, 409, "request_not_pending", key=None)
        self.err("bob", "POST", f"/requests/{rid}/cancel", None, 409, "request_not_pending", key=None)
        self.assertEqual(len(self.ok("cy", "GET", "/activity", status=200)["payments"]), 0)

    def test_decline_cancel_idempotent_states(self):
        r1, r2 = self.make()["request_id"], self.make()["request_id"]
        for _ in range(2):
            self.assertEqual(self.ok("ada", "POST", f"/requests/{r1}/decline", status=200,
                                     key=None)["status"], "declined")
            self.assertEqual(self.ok("bob", "POST", f"/requests/{r2}/cancel", status=200,
                                     key=None)["status"], "cancelled")
        self.err("bob", "POST", f"/requests/{r1}/cancel", None, 409, "request_not_pending", key=None)
        self.err("ada", "POST", f"/requests/{r2}/decline", None, 409, "request_not_pending", key=None)
        self.err("ada", "POST", f"/requests/{r1}/pay", {}, 409, "request_not_pending")

    def test_oversized_request_payable_later(self):
        rid = self.make("ada", "cy", 5000)["request_id"]
        self.err("cy", "POST", f"/requests/{rid}/pay", {}, 409, "insufficient_funds")
        self.assertEqual(self.ok("ada", "GET", "/requests", status=200)["requests"][0]["status"], "pending")
        self.ok("ada", "POST", "/payments", {"to_handle": "cy", "amount": 5000})
        self.ok("cy", "POST", f"/requests/{rid}/pay", {})
        self.assertEqual(self.total(), 12500)

    def test_request_errors(self):
        self.err("bob", "POST", "/requests", {"payer_handle": "bob", "amount": 1}, 422, "self_request")
        self.err("bob", "POST", "/requests", {"payer_handle": "zed", "amount": 1}, 404, "not_found")
        self.err("bob", "POST", "/requests", {"payer_handle": "ada", "amount": 0}, 422, "validation_failed")
        self.err("bob", "POST", "/requests", {"payer_handle": "ada", "amount": 1, "note": "x" * 201},
                 422, "validation_failed")
        self.err("bob", "POST", "/requests", {"payer_handle": ["ada"], "amount": 1}, 400, "malformed_request")
        self.err("bob", "POST", "/requests", {"amount": 1}, 422, "validation_failed")
        rid = self.make()["request_id"]
        for vis in ("x", None, 3):
            self.err("ada", "POST", f"/requests/{rid}/pay", {"visibility": vis}, 422, "validation_failed")

    def test_zero_length_pay_body_is_empty_object(self):
        rid = self.make()["request_id"]
        s, b, _ = call("POST", f"/requests/{rid}/pay", raw=b"", token=self.tok["ada"], key="z")
        self.assertEqual((s, b["visibility"]), (201, "public"))

    def test_list_filters_and_pagination(self):
        ids = [self.make(amount=i + 1)["request_id"] for i in range(5)]
        self.make("cy", "ada", 7)
        got = self.ok("ada", "GET", "/requests?direction=incoming&limit=3", status=200)
        self.assertEqual((len(got["requests"]), got["has_more"]), (3, True))
        self.assertEqual(got["requests"][0]["amount"], 7)
        self.assertEqual(self.ok("ada", "GET", "/requests?limit=6", status=200)["has_more"], False)
        self.assertEqual(self.ok("ada", "GET", "/requests?limit=5", status=200)["has_more"], True)
        self.assertEqual(self.ok("ada", "GET", "/requests?offset=9", status=200),
                         {"requests": [], "has_more": False})
        self.assertEqual(len(self.ok("bob", "GET", "/requests?direction=outgoing", status=200)["requests"]), 5)
        self.assertEqual(len(self.ok("ada", "GET", "/requests?direction=outgoing", status=200)["requests"]), 0)
        self.assertEqual(len(self.ok("cy", "GET", "/requests?status=pending", status=200)["requests"]), 1)
        self.assertEqual(self.ok("cy", "GET", "/requests?status=paid", status=200)["requests"], [])
        for q in ("limit=0", "limit=201", "limit=1e2", "limit=4.0", "limit=+4", "limit=-1", "limit=",
                  "limit=abc", "offset=-1", "offset=1e1", "direction=x", "status=x"):
            for path in ("/requests", "/activity"):
                if q.startswith(("direction", "status")) and path == "/activity":
                    continue
                self.err("ada", "GET", f"{path}?{q}", None, 422, "validation_failed")
        self.ok("ada", "GET", "/activity?limit=200&offset=0", status=200)
        self.assertEqual(ids[-1], self.ok("ada", "GET", "/requests?direction=incoming&offset=1",
                                          status=200)["requests"][0]["request_id"])

    def test_pay_race_moves_money_once(self):
        rid = self.make()["request_id"]
        out = []

        def go(i):
            out.append(call("POST", f"/requests/{rid}/pay", {}, token=self.tok["ada"], key=f"k{i}")[0])
        ts = [threading.Thread(target=go, args=(i,)) for i in range(20)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual((out.count(201), out.count(409)), (1, 19))
        self.assertEqual(self.balance("ada"), 8800)

    def test_pay_decline_cancel_race(self):
        rid = self.make()["request_id"]
        out = []
        ops = [("ada", "pay"), ("ada", "decline"), ("bob", "cancel")] * 5

        def go(i, who, op):
            out.append((op, call("POST", f"/requests/{rid}/{op}", {}, token=self.tok[who], key=f"r{i}")[0]))
        ts = [threading.Thread(target=go, args=(i, w, o)) for i, (w, o) in enumerate(ops)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        final = self.ok("ada", "GET", "/requests", status=200)["requests"][0]["status"]
        winners = {op for op, s in out if s in (200, 201)}
        self.assertEqual(winners, {{"paid": "pay", "declined": "decline", "cancelled": "cancel"}[final]})
        self.assertEqual(self.total(), 12500)


if __name__ == "__main__":
    unittest.main()
