"""Own tests, written from the specification. Run against a live service:
    BASE_URL=http://127.0.0.1:8080 python3 tests/test_service.py
"""
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from client import call, fixture, key, user, reset, login, balance  # noqa: E402

TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$")


def err(test, resp, status, code):
    s, b, _ = resp
    test.assertEqual(s, status, b)
    test.assertEqual(b["error"]["code"], code, b)
    test.assertIsInstance(b["error"]["message"], str)


def pay(tok, to="bob", amount=100, k=None, **extra):
    body = {"to_handle": to, "amount": amount}
    body.update(extra)
    return call("POST", "/payments", body, tok, k or key())


def ask(tok, payer="ada", amount=1200, k=None, **extra):
    body = {"payer_handle": payer, "amount": amount}
    body.update(extra)
    return call("POST", "/requests", body, tok, k or key())


class Base(unittest.TestCase):
    def setUp(self):
        reset(fixture())
        self.ada, self.bob, self.cy = login("ada"), login("bob"), login("cy")


class Runtime(Base):
    def test_health_and_headers(self):
        s, b, ct = call("GET", "/health")
        self.assertEqual((s, b, ct), (200, {"status": "ok"}, "application/json; charset=utf-8"))
        s, b, ct = call("GET", "/me", token=self.ada)
        self.assertEqual(ct, "application/json; charset=utf-8")

    def test_unknown_route_and_method_envelopes(self):
        err(self, call("GET", "/nope"), 404, "not_found")
        err(self, call("GET", "/authorizations", token=self.ada), 404, "not_found")
        s, b, _ = call("DELETE", "/me", token=self.ada)
        self.assertEqual(s, 405)
        self.assertIn("error", b)

    def test_reset_twice_clears_everything(self):
        pay(self.ada)
        reset(fixture(users=[user("zed", 5)]))
        err(self, call("GET", "/me", token=self.ada), 401, "unauthenticated")
        err(self, call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}),
            401, "unauthenticated")
        z = login("zed")
        self.assertEqual(call("GET", "/activity", token=z)[1]["payments"], [])
        reset(fixture())
        self.assertEqual(balance(login("ada")), 10000)

    def test_unknown_fields_and_query_ignored(self):
        s, b, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 5, "zzz": [1]}, self.ada, key())
        self.assertEqual(s, 201)
        self.assertEqual(call("GET", "/me?foo=bar", token=self.ada)[0], 200)

    def test_timestamps_and_ids(self):
        p = pay(self.ada)[1]
        r = ask(self.bob)[1]
        self.assertRegex(p["created_at"], TS)
        self.assertRegex(r["created_at"], TS)
        for v in (p["payment_id"], r["request_id"], p["from_user_id"]):
            self.assertLessEqual(len(v), 64)

    def test_all_endpoints_require_auth(self):
        for m, path in [("GET", "/me"), ("POST", "/payments"), ("POST", "/requests"),
                        ("GET", "/requests"), ("POST", "/splits"), ("POST", "/settlements"),
                        ("GET", "/activity"), ("POST", "/requests/x/pay"),
                        ("POST", "/requests/x/decline"), ("POST", "/requests/x/cancel")]:
            for tok in (None, "garbage"):
                err(self, call(m, path, {} if m == "POST" else None, tok, key()), 401, "unauthenticated")
        s, b, _ = call("GET", "/me", headers={"Authorization": "Basic abc"})
        self.assertEqual(s, 401)

    def test_malformed_bodies(self):
        for raw in ["{", "[1]", "null", "\"x\"", "", "\xff"]:
            err(self, call("POST", "/payments", token=self.ada, idem=key(), raw=raw), 400, "malformed_request")
        err(self, call("POST", "/auth/login", raw="{bad"), 400, "malformed_request")
        err(self, call("POST", "/_test/reset", raw="{bad"), 400, "malformed_request")
        err(self, call("POST", "/payments", {"to_handle": 5, "amount": 1}, self.ada, key()), 400, "malformed_request")

    def test_no_5xx_on_hostile_input(self):
        weird = [{}, {"to_handle": None}, {"to_handle": ["x"], "amount": {}}, {"amount": 1e999},
                 {"to_handle": "bob", "amount": "1e3"},
                 {"to_handle": "bob", "amount": 1, "note": {"a": 1}}, {"to_handle": "\ud800", "amount": 1}]
        for w in weird:
            for path in ("/payments", "/requests", "/splits", "/settlements", "/auth/signup", "/auth/login"):
                s, b, _ = call("POST", path, w, self.ada, key())
                self.assertLess(s, 500, (path, w, s, b))
        s, _, _ = call("POST", "/payments", token=self.ada, idem=key(),
                       raw='{"to_handle":"bob","amount":1e999999999}')
        self.assertEqual(s, 422)
        s, _, _ = call("POST", "/payments", token=self.ada, idem=key(),
                       raw='{"to_handle":"bob","amount":' + "9" * 6000 + '}')
        self.assertEqual(s, 422)
        s, _, _ = call("POST", "/payments", token=self.ada, idem=key(), raw='{"amount": NaN}')
        self.assertEqual(s, 400)


class Fixtures(unittest.TestCase):
    def test_negative_balance_changes_nothing(self):
        reset(fixture())
        tok = login("ada")
        err(self, call("POST", "/_test/reset", fixture(users=[user("ada", -1)])), 422, "validation_failed")
        self.assertEqual(balance(tok), 10000)

    def test_invalid_fixtures_422_state_intact(self):
        reset(fixture())
        tok = login("ada")
        bads = [fixture(users=[user("ada", 1), user("ada", 2, id="u_x", email="x@e.com")]),
                fixture(users=[user("Bad!", 1)]), fixture(minor_units=5), {"users": "x"},
                fixture(users=[user("ada", 1.5)]), fixture(users=[user("ada", "1")]),
                fixture(payments=[{"id": "p", "from_user_id": "nobody", "to_user_id": "u_ada", "amount": 1}]),
                fixture(requests=[{"id": "r", "requester_id": ["x"], "payer_id": "u_ada", "amount": 1}]),
                fixture(settlement_operator_ids=["ghost"])]
        for b in bads:
            err(self, call("POST", "/_test/reset", b), 422, "validation_failed")
        self.assertEqual(balance(tok), 10000)

    def test_optional_sections_and_currencies(self):
        for cur, mu in (("JPY", 0), ("BHD", 3), ("EUR", 2)):
            reset({"currency": cur, "minor_units": mu, "users": [user("ada", 7)]})
            me = call("GET", "/me", token=login("ada"))[1]
            self.assertEqual((me["currency"], me["minor_units"], me["balance"]), (cur, mu, 7))

    def test_seeded_payments_requests_served(self):
        reset(fixture(payments=[
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee",
             "visibility": "private"}],
            requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200,
                       "note": "taxi", "status": "pending"},
                      {"id": "rq_2", "requester_id": "u_bob", "payer_id": "u_cy", "amount": 5,
                       "status": "cancelled"}]))
        ada, bob, cy = login("ada"), login("bob"), login("cy")
        self.assertEqual(balance(ada), 10000)  # seeded balance is final
        a = call("GET", "/activity", token=ada)[1]["payments"]
        self.assertEqual([(p["payment_id"], p["visibility"], p["note"]) for p in a], [("p_1", "private", "coffee")])
        self.assertEqual(call("GET", "/activity", token=cy)[1]["payments"], [])
        rq = {r["request_id"]: r for r in call("GET", "/requests", token=bob)[1]["requests"]}
        self.assertEqual(set(rq), {"rq_1", "rq_2"})
        self.assertEqual(rq["rq_2"]["status"], "cancelled")
        err(self, call("POST", "/requests/rq_2/pay", {}, cy, key()), 409, "request_not_pending")
        self.assertEqual(call("POST", "/requests/rq_1/pay", {}, ada, key())[0], 201)

    def test_generated_ids_do_not_collide_with_seeded(self):
        reset(fixture(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1}]))
        ada = login("ada")
        p = pay(ada)[1]
        self.assertNotEqual(p["payment_id"], "p_1")


class Auth(Base):
    def test_signup_login(self):
        s, b, _ = call("POST", "/auth/signup", {"email": "Jo.Ann+x@Example.com", "password": "12345678",
                                                "display_name": "Jo"})
        self.assertEqual(s, 201)
        self.assertEqual(set(b), {"user_id", "display_name", "token"})
        me = call("GET", "/me", token=b["token"])[1]
        self.assertEqual((me["handle"], me["balance"]), ("jo_ann_x", 0))
        s2, b2, _ = call("POST", "/auth/login", {"email": "Jo.Ann+x@Example.com", "password": "12345678"})
        self.assertEqual(s2, 200)
        self.assertEqual(b2["user_id"], b["user_id"])
        self.assertNotEqual(b2["token"], b["token"])
        self.assertEqual(call("GET", "/me", token=b["token"])[0], 200)
        self.assertEqual(call("GET", "/me", token=b2["token"])[0], 200)
        self.assertEqual(pay(self.ada, to="jo_ann_x", amount=5)[0], 201)

    def test_long_local_part(self):
        s, b, _ = call("POST", "/auth/signup", {"email": "a" * 25 + "@e.com", "password": "12345678", "display_name": "L"})
        self.assertEqual(call("GET", "/me", token=b["token"])[1]["handle"], "a" * 20)

    def test_rejections(self):
        base = {"email": "n@e.com", "password": "12345678", "display_name": "N"}
        err(self, call("POST", "/auth/signup", dict(base, email="ada@example.com")), 409, "email_taken")
        err(self, call("POST", "/auth/signup", dict(base, password="1234567")), 422, "validation_failed")
        self.assertEqual(call("POST", "/auth/signup", dict(base, password="12345678"))[0], 201)
        for bad in ("nodomain", "@e.com", "a@", "a b@c", "a@@b"):
            err(self, call("POST", "/auth/signup", dict(base, email=bad)), 422, "validation_failed")
        err(self, call("POST", "/auth/signup", {"email": "q@e.com", "password": "12345678"}), 422, "validation_failed")
        err(self, call("POST", "/auth/signup", dict(base, email=5)), 400, "malformed_request")
        err(self, call("POST", "/auth/login", {"email": "ada@example.com", "password": "nope"}), 401, "unauthenticated")
        err(self, call("POST", "/auth/login", {"email": "who@example.com", "password": "nope"}), 401, "unauthenticated")

    def test_handle_taken_creates_nothing(self):
        e = "ada@other.com"  # derives "ada", taken by seeded Ada
        err(self, call("POST", "/auth/signup", {"email": e, "password": "12345678", "display_name": "X"}),
            409, "handle_taken")
        err(self, call("POST", "/auth/login", {"email": e, "password": "12345678"}), 401, "unauthenticated")
        # email still free: retry yields the same handle error, not email_taken
        err(self, call("POST", "/auth/signup", {"email": e, "password": "12345678", "display_name": "X"}),
            409, "handle_taken")

    def test_password_not_plaintext_in_export(self):
        s, b, _ = call("GET", "/_test/export")
        self.assertNotIn("correct horse", json.dumps(b))


class Payments(Base):
    def test_shape_defaults_and_funds(self):
        s, p, _ = pay(self.ada, amount=1500)
        self.assertEqual(s, 201)
        self.assertEqual(set(p), {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
                                  "currency", "note", "visibility", "request_id", "settlement_id", "created_at"})
        self.assertEqual((p["note"], p["visibility"], p["request_id"], p["settlement_id"]), ("", "public", None, None))
        self.assertEqual((balance(self.ada), balance(self.bob)), (8500, 4000))
        err(self, pay(self.cy, amount=501), 409, "insufficient_funds")
        self.assertEqual(balance(self.cy), 500)
        self.assertEqual(pay(self.cy, amount=500)[0], 201)
        self.assertEqual(balance(self.cy), 0)

    def test_amount_validation(self):
        for a in (0, -1, 1_000_000_001, "5", True, None, 1.5, [1], 10 ** 30, 1e30):
            err(self, pay(self.ada, amount=a), 422, "validation_failed")
        err(self, call("POST", "/payments", token=self.ada, idem=key(), raw='{"to_handle":"bob"}'), 422, "validation_failed")
        for raw in ("1e2", "100.0", "1E2", "100.00"):
            s, p, _ = call("POST", "/payments", token=self.ada, idem=key(), raw='{"to_handle":"bob","amount":%s}' % raw)
            self.assertEqual((s, p["amount"]), (201, 100))
        self.assertIsInstance(p["amount"], int)
        self.assertEqual(call("POST", "/payments", token=self.ada, idem=key(),
                              raw='{"to_handle":"bob","amount":1000000000}')[0], 409)
        err(self, call("POST", "/payments", token=self.ada, idem=key(),
                       raw='{"to_handle":"bob","amount":1000000001}'), 422, "validation_failed")

    def test_other_rejections(self):
        err(self, pay(self.ada, to="ada"), 422, "self_payment")
        err(self, pay(self.ada, to="nobody"), 404, "not_found")
        for h in ("ADA", "@ada", "", "x" * 40):
            err(self, pay(self.ada, to=h), 404, "not_found")
        err(self, pay(self.ada, note="x" * 201), 422, "validation_failed")
        err(self, pay(self.ada, note=None), 422, "validation_failed")
        err(self, pay(self.ada, note=5), 422, "validation_failed")
        for v in ("Public", "", None, 1, "friends"):
            err(self, pay(self.ada, visibility=v), 422, "validation_failed")
        self.assertEqual(pay(self.ada, note="x" * 200)[0], 201)
        self.assertEqual(pay(self.ada, note="\U0001F600" * 200)[0], 201)
        err(self, pay(self.ada, note="\U0001F600" * 201), 422, "validation_failed")

    def test_note_verbatim(self):
        for n in ["  padded  ", "<b>&amp;</b>", "caf\u00e9 e\u0301", "\U0001F600\u200d\U0001F468", "line\nbreak\t", "\u0000x", "\"q\\"]:
            s, p, _ = pay(self.ada, amount=1, note=n)
            self.assertEqual(p["note"], n)
            self.assertEqual(call("GET", "/activity", token=self.ada)[1]["payments"][0]["note"], n)

    def test_large_balances(self):
        big = 2 ** 53 - 10
        reset(fixture(users=[user("ada", big), user("bob", 5)]))
        ada = login("ada")
        self.assertEqual(balance(ada), big)
        self.assertEqual(pay(ada, amount=1_000_000_000)[0], 201)
        self.assertEqual(balance(ada), big - 1_000_000_000)
        self.assertEqual(balance(login("bob")), 1_000_000_005)

    def test_idempotency_matrix(self):
        k = key()
        s1, b1, _ = pay(self.ada, amount=300, k=k)
        s2, b2, _ = pay(self.ada, amount=300, k=k)
        self.assertEqual((s1, s2, b1 == b2), (201, 200, True))
        self.assertEqual(balance(self.ada), 9700)
        # key order / whitespace / number spelling
        s3, b3, _ = call("POST", "/payments", token=self.ada, idem=k, raw=' { "amount" : 3e2 , "to_handle":"bob" } ')
        self.assertEqual((s3, b3), (200, b1))
        err(self, pay(self.ada, amount=301, k=k), 409, "idempotency_key_reuse")
        err(self, pay(self.ada, amount="junk", k=k), 409, "idempotency_key_reuse")  # claimed key before validation
        err(self, call("POST", "/payments", {"to_handle": "bob", "amount": 300, "note": ""}, self.ada, k), 409,
            "idempotency_key_reuse")
        # per-user scope
        self.assertEqual(pay(self.bob, to="ada", amount=300, k=k)[0], 201)
        # different path same key succeeds
        self.assertEqual(ask(self.bob, k=k)[0], 201)
        # failed first use does not claim
        k2 = key()
        err(self, pay(self.cy, amount=10 ** 6, k=k2), 409, "insufficient_funds")
        self.assertEqual(pay(self.cy, amount=5, k=k2)[0], 201)
        err(self, call("POST", "/payments", {"to_handle": "bob", "amount": 1}, self.ada), 400, "missing_idempotency_key")
        err(self, call("POST", "/payments", {"to_handle": "bob", "amount": 1}, self.ada, ""), 400, "missing_idempotency_key")
        self.assertEqual(pay(self.ada, amount=1, k="k" * 255)[0], 201)
        err(self, pay(self.ada, amount=1, k="k" * 256), 422, "validation_failed")
        err(self, pay(self.ada, amount=1, k="k" * 10000), 422, "validation_failed")
        # 400 for missing key precedes body validation; 401 precedes both
        err(self, call("POST", "/payments", {}, self.ada), 400, "missing_idempotency_key")


class Requests(Base):
    def test_create_and_rules(self):
        s, r, _ = ask(self.bob, amount=999999)  # exceeds payer balance: legal
        self.assertEqual(s, 201)
        self.assertEqual(set(r), {"request_id", "requester_id", "requester_handle", "payer_id", "payer_handle",
                                  "amount", "currency", "note", "status", "payment_id", "created_at"})
        self.assertEqual((r["status"], r["payment_id"], r["requester_handle"], r["payer_handle"]),
                         ("pending", None, "bob", "ada"))
        err(self, ask(self.bob, payer="bob"), 422, "self_request")
        err(self, ask(self.bob, payer="zzz"), 404, "not_found")
        err(self, ask(self.bob, amount=0), 422, "validation_failed")
        err(self, ask(self.bob, amount="5"), 422, "validation_failed")
        err(self, ask(self.bob, note="x" * 201), 422, "validation_failed")
        err(self, ask(self.bob, note=None), 422, "validation_failed")

    def test_pay_flow_and_short(self):
        r = ask(self.ada, payer="cy", amount=800)[1]["request_id"]
        k = key()
        err(self, call("POST", f"/requests/{r}/pay", {}, self.cy, k), 409, "insufficient_funds")
        self.assertEqual(call("GET", "/requests?status=pending", token=self.cy)[1]["requests"][0]["status"], "pending")
        err(self, call("POST", f"/requests/{r}/pay", {}, self.ada, key()), 403, "forbidden")
        err(self, call("POST", f"/requests/{r}/pay", {}, self.cy, ""), 400, "missing_idempotency_key")
        pay(self.ada, to="cy", amount=400)
        s, p, _ = call("POST", f"/requests/{r}/pay", {"visibility": "private"}, self.cy, k)
        self.assertEqual(s, 201)
        self.assertEqual((p["request_id"], p["visibility"], p["amount"], p["from_handle"]), (r, "private", 800, "cy"))
        self.assertEqual(balance(self.cy), 100)
        # replay: 200, same body, no more money, even though request is now paid
        s2, p2, _ = call("POST", f"/requests/{r}/pay", {"visibility": "private"}, self.cy, k)
        self.assertEqual((s2, p2), (200, p))
        self.assertEqual(balance(self.cy), 100)
        # different key: not pending
        err(self, call("POST", f"/requests/{r}/pay", {"visibility": "private"}, self.cy, key()), 409, "request_not_pending")
        # {} vs visibility on same key
        err(self, call("POST", f"/requests/{r}/pay", {}, self.cy, k), 409, "idempotency_key_reuse")
        paid = call("GET", "/requests?direction=outgoing", token=self.ada)[1]["requests"][0]
        self.assertEqual((paid["status"], paid["payment_id"]), ("paid", p["payment_id"]))
        err(self, call("POST", "/requests/nope/pay", {}, self.cy, key()), 404, "not_found")
        err(self, call("POST", f"/requests/{r}/pay", {"visibility": "x"}, self.cy, key()), 422, "validation_failed")

    def test_pay_with_no_body(self):
        r = ask(self.bob, amount=10)[1]["request_id"]
        s, p, _ = call("POST", f"/requests/{r}/pay", token=self.ada, idem=key())
        self.assertEqual((s, p["visibility"]), (201, "public"))

    def test_decline_cancel(self):
        r = ask(self.bob, amount=10)[1]["request_id"]
        err(self, call("POST", f"/requests/{r}/cancel", None, self.ada), 403, "forbidden")
        err(self, call("POST", f"/requests/{r}/decline", None, self.bob), 403, "forbidden")
        err(self, call("POST", f"/requests/{r}/decline", None, self.cy), 403, "forbidden")
        for _ in range(2):
            s, b, _ = call("POST", f"/requests/{r}/decline", None, self.ada)
            self.assertEqual((s, b["status"]), (200, "declined"))
        err(self, call("POST", f"/requests/{r}/cancel", None, self.bob), 409, "request_not_pending")
        err(self, call("POST", f"/requests/{r}/pay", {}, self.ada, key()), 409, "request_not_pending")
        r2 = ask(self.bob, amount=10)[1]["request_id"]
        for _ in range(2):
            s, b, _ = call("POST", f"/requests/{r2}/cancel", None, self.bob)
            self.assertEqual((s, b["status"]), (200, "cancelled"))
        err(self, call("POST", f"/requests/{r2}/decline", None, self.ada), 409, "request_not_pending")
        err(self, call("POST", f"/requests/{r2}/pay", {}, self.ada, key()), 409, "request_not_pending")
        err(self, call("POST", "/requests/zzz/cancel", None, self.bob), 404, "not_found")
        err(self, call("POST", "/requests/zzz/decline", None, self.bob), 404, "not_found")
        # paid cannot be declined/cancelled
        r3 = ask(self.bob, amount=10)[1]["request_id"]
        call("POST", f"/requests/{r3}/pay", {}, self.ada, key())
        err(self, call("POST", f"/requests/{r3}/decline", None, self.ada), 409, "request_not_pending")
        err(self, call("POST", f"/requests/{r3}/cancel", None, self.bob), 409, "request_not_pending")

    def test_replay_after_cancel_returns_original(self):
        k = key()
        s, r, _ = ask(self.bob, k=k)
        call("POST", f"/requests/{r['request_id']}/cancel", None, self.bob)
        s2, r2, _ = ask(self.bob, k=k)
        self.assertEqual((s2, r2), (200, r))
        self.assertEqual(r2["status"], "pending")

    def test_list_filters_and_paging(self):
        ids = [ask(self.bob, amount=i + 1)[1]["request_id"] for i in range(5)]
        ask(self.cy, payer="bob", amount=7)
        ask(self.ada, payer="cy", amount=8)
        out = call("GET", "/requests", token=self.bob)[1]
        self.assertEqual([r["amount"] for r in out["requests"]], [7, 5, 4, 3, 2, 1])
        self.assertFalse(out["has_more"])
        self.assertEqual([r["amount"] for r in call("GET", "/requests?direction=incoming", token=self.bob)[1]["requests"]], [7])
        self.assertEqual(len(call("GET", "/requests?direction=outgoing", token=self.bob)[1]["requests"]), 5)
        self.assertEqual(call("GET", "/requests", token=self.cy)[1]["requests"].__len__(), 2)
        s, b, _ = call("GET", "/requests?limit=2&offset=0", token=self.bob)
        self.assertEqual((len(b["requests"]), b["has_more"]), (2, True))
        s, b, _ = call("GET", "/requests?limit=3&offset=3", token=self.bob)
        self.assertEqual((len(b["requests"]), b["has_more"]), (3, False))
        s, b, _ = call("GET", "/requests?limit=6", token=self.bob)
        self.assertEqual((len(b["requests"]), b["has_more"]), (6, False))
        s, b, _ = call("GET", "/requests?limit=5", token=self.bob)
        self.assertEqual((len(b["requests"]), b["has_more"]), (5, True))
        s, b, _ = call("GET", "/requests?offset=100", token=self.bob)
        self.assertEqual((b["requests"], b["has_more"]), ([], False))
        call("POST", f"/requests/{ids[0]}/decline", None, self.ada)
        self.assertEqual(len(call("GET", "/requests?status=declined", token=self.bob)[1]["requests"]), 1)
        self.assertEqual(call("GET", "/requests?limit=200&offset=0&status=paid", token=self.bob)[1]["requests"], [])

    def test_bad_query_params(self):
        for qs in ("limit=0", "limit=201", "limit=-1", "limit=1e2", "limit=4.0", "limit=%2B4", "limit=", "limit=abc",
                   "offset=-1", "offset=1e9", "offset=", "offset=%EF%BC%91", "direction=both", "status=open",
                   "direction=", "status=PENDING"):
            err(self, call("GET", "/requests?" + qs, token=self.ada), 422, "validation_failed")
        for qs in ("limit=0", "limit=201", "offset=-1", "limit=1e1", "offset=+4", "offset=4.0"):
            err(self, call("GET", "/activity?" + qs, token=self.ada), 422, "validation_failed")
        self.assertEqual(call("GET", "/requests?limit=200&offset=0", token=self.ada)[0], 200)
        self.assertEqual(call("GET", "/requests?limit=1&limit=2", token=self.ada)[0], 200)


class Splits(Base):
    def split(self, tok, amount, handles, **kw):
        body = {"amount": amount, "participant_handles": handles}
        body.update(kw)
        return call("POST", "/splits", body, tok, key())

    def test_rounding_table(self):
        names = ["ada", "bob", "cy"]
        for amount, n, exp in [(1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
                               (999, 3, [333, 333, 333])]:
            s, b, _ = self.split(self.ada, amount, names[:n])
            self.assertEqual([x["amount"] for x in b["shares"]], exp)
        reset(fixture(users=[user(h, 100) for h in "abcde"]))
        a = login("a")
        s, b, _ = self.split(a, 5, list("abcde"))
        self.assertEqual([x["amount"] for x in b["shares"]], [1] * 5)
        s, b, _ = self.split(a, 7, list("edcba"))
        self.assertEqual([(x["handle"], x["amount"]) for x in b["shares"]],
                         [("e", 2), ("d", 2), ("c", 1), ("b", 1), ("a", 1)])

    def test_shape_and_requests(self):
        s, b, _ = self.split(self.ada, 3000, ["ada", "bob", "cy"], note="dinner")
        self.assertEqual(s, 201)
        self.assertEqual(set(b), {"split_id", "amount", "currency", "note", "shares", "requests", "created_at"})
        self.assertEqual([r["payer_handle"] for r in b["requests"]], ["bob", "cy"])
        self.assertTrue(all(r["requester_handle"] == "ada" and r["status"] == "pending" and r["amount"] == 1000
                            and r["note"] == "dinner" for r in b["requests"]))
        self.assertEqual(call("GET", "/activity", token=self.ada)[1]["payments"], [])
        # caller omitted
        s, b, _ = self.split(self.ada, 11, ["cy", "bob"])
        self.assertEqual([x["amount"] for x in b["shares"]], [6, 5])
        self.assertEqual([r["amount"] for r in b["requests"]], [6, 5])
        # caller only
        s, b, _ = self.split(self.ada, 11, ["ada"])
        self.assertEqual((s, b["shares"], b["requests"]), (201, [{"handle": "ada", "amount": 11}], []))
        # zero share request created and payable
        s, b, _ = self.split(self.ada, 1, ["ada", "bob", "cy"])
        self.assertEqual([r["amount"] for r in b["requests"]], [0, 0])
        rid = b["requests"][0]["request_id"]
        s, p, _ = call("POST", f"/requests/{rid}/pay", {}, self.bob, key())
        self.assertEqual((s, p["amount"]), (201, 0))
        # no balance check
        self.assertEqual(self.split(self.cy, 10 ** 9, ["bob", "ada"])[0], 201)

    def test_rejections(self):
        for a in (0, -3, 10 ** 9 + 1, "5", 2.5, None, True):
            err(self, self.split(self.ada, a, ["bob"]), 422, "validation_failed")
        err(self, self.split(self.ada, 5, []), 422, "validation_failed")
        err(self, self.split(self.ada, 5, ["bob", "bob"]), 422, "validation_failed")
        err(self, self.split(self.ada, 5, ["bob", "ghost"]), 404, "not_found")
        err(self, self.split(self.ada, 5, ["bob"], note="x" * 201), 422, "validation_failed")
        err(self, self.split(self.ada, 5, "bob"), 400, "malformed_request")
        err(self, self.split(self.ada, 5, [1]), 400, "malformed_request")
        err(self, call("POST", "/splits", {"amount": 5}, self.ada, key()), 422, "validation_failed")
        self.assertEqual(call("GET", "/requests", token=self.ada)[1]["requests"], [])  # nothing created by failures

    def test_split_idempotent_and_conservation(self):
        k = key()
        body = {"amount": 1000, "participant_handles": ["ada", "bob", "cy"]}
        s1, b1, _ = call("POST", "/splits", body, self.ada, k)
        s2, b2, _ = call("POST", "/splits", body, self.ada, k)
        self.assertEqual((s1, s2, b1 == b2), (201, 200, True))
        self.assertEqual(len(call("GET", "/requests", token=self.ada)[1]["requests"]), 2)
        for r in b1["requests"]:
            tok = self.bob if r["payer_handle"] == "bob" else self.cy
            call("POST", f"/requests/{r['request_id']}/pay", {}, tok, key())
        self.assertEqual(balance(self.ada) + balance(self.bob) + balance(self.cy), 13000)


class Feed(Base):
    def test_visibility(self):
        pay(self.ada, to="bob", amount=1, visibility="private")
        pay(self.ada, to="bob", amount=2, visibility="public")
        pay(self.bob, to="cy", amount=3, visibility="private")
        ask(self.bob, amount=4)
        feed = lambda t: [p["amount"] for p in call("GET", "/activity", token=t)[1]["payments"]]
        self.assertEqual(feed(self.ada), [2, 1])
        self.assertEqual(feed(self.bob), [3, 2, 1])
        self.assertEqual(feed(self.cy), [3, 2])
        # same visibility value for both parties
        self.assertEqual(call("GET", "/activity", token=self.bob)[1]["payments"][2]["visibility"], "private")

    def test_paging(self):
        for i in range(5):
            pay(self.ada, amount=i + 1)
        s, b, _ = call("GET", "/activity?limit=2&offset=1", token=self.cy)
        self.assertEqual(([p["amount"] for p in b["payments"]], b["has_more"]), ([4, 3], True))
        s, b, _ = call("GET", "/activity?limit=2&offset=3", token=self.cy)
        self.assertEqual(([p["amount"] for p in b["payments"]], b["has_more"]), ([2, 1], False))
        self.assertEqual(call("GET", "/activity?direction=zzz&status=nope", token=self.cy)[0], 200)


class Settlements(unittest.TestCase):
    def setUp(self):
        reset(fixture(users=[user("ada", 1000), user("bob", 0), user("cy", 0), user("dee", 50)],
                      settlement_operator_ids=["u_dee"]))
        self.ada, self.bob, self.cy, self.dee = (login(h) for h in ("ada", "bob", "cy", "dee"))

    def settle(self, transfers, tok=None, k=None):
        return call("POST", "/settlements", {"transfers": transfers}, tok or self.dee, k or key())

    def t(self, f, t, a, **kw):
        d = {"from_handle": f, "to_handle": t, "amount": a}
        d.update(kw)
        return d

    def test_auth(self):
        err(self, call("POST", "/settlements", {"transfers": []}, None, key()), 401, "unauthenticated")
        err(self, self.settle([self.t("ada", "bob", 1)], self.ada), 403, "forbidden")
        err(self, call("POST", "/settlements", {"transfers": [self.t("ada", "bob", 1)]}, self.dee), 400,
            "missing_idempotency_key")

    def test_net_and_shape(self):
        s, b, _ = self.settle([self.t("ada", "bob", 100), self.t("bob", "cy", 50, note="n", visibility="private")])
        self.assertEqual(s, 201)
        self.assertEqual(set(b), {"settlement_id", "committed_at", "payments"})
        self.assertRegex(b["committed_at"], TS)
        p1, p2 = b["payments"]
        self.assertEqual((p1["from_handle"], p1["to_handle"], p2["note"], p2["visibility"]), ("ada", "bob", "n", "private"))
        for p in b["payments"]:
            self.assertEqual((p["settlement_id"], p["request_id"], p["created_at"]), (b["settlement_id"], None, b["committed_at"]))
        self.assertEqual([balance(t) for t in (self.ada, self.bob, self.cy, self.dee)], [900, 50, 50, 50])
        # visibility: operator sees only public one; parties see theirs
        self.assertEqual([p["amount"] for p in call("GET", "/activity", token=self.dee)[1]["payments"]], [100])
        self.assertEqual(len(call("GET", "/activity", token=self.cy)[1]["payments"]), 2)
        self.assertEqual(call("GET", "/activity", token=self.cy)[1]["payments"][0]["settlement_id"], b["settlement_id"])
        # ordinary payments have null settlement id
        self.assertIsNone(pay(self.ada, amount=1)[1]["settlement_id"])

    def test_insufficient_and_atomic(self):
        err(self, self.settle([self.t("ada", "bob", 600), self.t("ada", "cy", 401)]), 409, "insufficient_funds")
        err(self, self.settle([self.t("ada", "bob", 100), self.t("bob", "cy", 101)]), 409, "insufficient_funds")
        self.assertEqual([balance(t) for t in (self.ada, self.bob, self.cy)], [1000, 0, 0])
        self.assertEqual(call("GET", "/activity", token=self.ada)[1]["payments"], [])
        # key unclaimed after failure
        k = key()
        err(self, self.settle([self.t("bob", "cy", 5)], k=k), 409, "insufficient_funds")
        self.assertEqual(self.settle([self.t("ada", "cy", 5)], k=k)[0], 201)
        # cycle needs nothing
        self.assertEqual(self.settle([self.t("bob", "cy", 9), self.t("cy", "bob", 9)])[0], 201)

    def test_entry_errors_precedence(self):
        big = 10 ** 6
        err(self, self.settle([self.t("ada", "bob", big), self.t("ada", "ghost", 1)]), 404, "not_found")
        err(self, self.settle([self.t("ada", "bob", big), self.t("bob", "bob", 1)]), 422, "self_payment")
        err(self, self.settle([self.t("ada", "ghost", 1), self.t("bob", "bob", 1)]), 404, "not_found")
        err(self, self.settle([self.t("bob", "bob", 1), self.t("ada", "ghost", 1)]), 422, "self_payment")
        err(self, self.settle([self.t("ada", "bob", 0)]), 422, "validation_failed")
        err(self, self.settle([self.t("ada", "bob", 1, note="x" * 201)]), 422, "validation_failed")
        err(self, self.settle([self.t("ada", "bob", 1, visibility="nope")]), 422, "validation_failed")
        err(self, self.settle([self.t("ada", "bob", 1, note=None)]), 422, "validation_failed")

    def test_batch_shape(self):
        for tr in ([], [1], "x", None, {}, [self.t("ada", "bob", 1)] * 33, [[]]):
            err(self, self.settle(tr), 422, "validation_failed")
        err(self, call("POST", "/settlements", {}, self.dee, key()), 422, "validation_failed")
        self.assertEqual(self.settle([self.t("ada", "bob", 1, extra=1)] * 32)[0], 201)
        err(self, call("POST", "/settlements", raw="[", token=self.dee, idem=key()), 400, "malformed_request")

    def test_replay(self):
        k = key()
        tr = [self.t("ada", "bob", 100), self.t("bob", "cy", 50)]
        s1, b1, _ = self.settle(tr, k=k)
        s2, b2, _ = self.settle(tr, k=k)
        self.assertEqual((s1, s2, b1 == b2), (201, 200, True))
        self.assertEqual(balance(self.ada), 900)
        err(self, self.settle([self.t("ada", "bob", 101)], k=k), 409, "idempotency_key_reuse")
        err(self, self.settle([], k=k), 409, "idempotency_key_reuse")

    def test_operator_no_extra_access(self):
        rq = ask(self.bob, payer="ada", amount=5)[1]["request_id"]
        self.assertEqual(call("GET", "/requests", token=self.dee)[1]["requests"], [])
        err(self, call("POST", f"/requests/{rq}/cancel", None, self.dee), 403, "forbidden")
        err(self, call("POST", f"/requests/{rq}/pay", {}, self.dee, key()), 403, "forbidden")


class ExportImport(unittest.TestCase):
    def test_roundtrip(self):
        reset(fixture(settlement_operator_ids=["u_ada"]))
        ada, bob, cy = login("ada"), login("bob"), login("cy")
        kp, kr, ks, kst = key(), key(), key(), key()
        p = call("POST", "/payments", {"to_handle": "bob", "amount": 300, "note": "é", "visibility": "private"}, ada, kp)[1]
        r = call("POST", "/requests", {"payer_handle": "ada", "amount": 77}, bob, kr)[1]
        sp = call("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "bob", "cy"]}, ada, ks)[1]
        st = call("POST", "/settlements", {"transfers": [{"from_handle": "cy", "to_handle": "bob", "amount": 9}]}, ada, kst)[1]
        failed = key()
        call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 8}, cy, failed)
        snap_s, snap, _ = call("GET", "/_test/export")
        self.assertEqual((snap_s, snap["track"], snap["format_version"]), (200, "pocketful", 1))
        before = {t: (call("GET", "/me", token=t)[1], call("GET", "/activity", token=t)[1],
                      call("GET", "/requests", token=t)[1]) for t in (ada, bob, cy)}
        pay(ada, amount=1)  # later write must not change the snapshot
        self.assertNotEqual(balance(ada), before[ada][0]["balance"])
        reset(fixture(users=[user("zed", 1)]))
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)  # repeat: no duplication
        err(self, call("GET", "/me", token=login("ada") + "x"), 401, "unauthenticated")
        for t in (ada, bob, cy):  # existing bearer tokens still work
            now = (call("GET", "/me", token=t)[1], call("GET", "/activity", token=t)[1], call("GET", "/requests", token=t)[1])
            self.assertEqual(now, before[t])
        # idempotent replays
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 300, "note": "é", "visibility": "private"}, ada, kp), (200, p, "application/json; charset=utf-8"))
        self.assertEqual(call("POST", "/requests", {"payer_handle": "ada", "amount": 77}, bob, kr)[:2], (200, r))
        self.assertEqual(call("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "bob", "cy"]}, ada, ks)[:2], (200, sp))
        self.assertEqual(call("POST", "/settlements", {"transfers": [{"from_handle": "cy", "to_handle": "bob", "amount": 9}]}, ada, kst)[:2], (200, st))
        err(self, call("POST", "/payments", {"to_handle": "bob", "amount": 301}, ada, kp), 409, "idempotency_key_reuse")
        # failed key reusable, operators preserved, ids continue without collision
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, cy, failed)[0], 201)
        p2 = pay(ada)[1]
        self.assertNotIn(p2["payment_id"], (p["payment_id"], st["payments"][0]["payment_id"]))
        self.assertEqual(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}, ada, key())[0], 201)
        # hashed-password login preserved; zed gone
        self.assertEqual(call("POST", "/auth/login", {"email": "bob@example.com", "password": "correct horse"})[0], 200)
        err(self, call("POST", "/auth/login", {"email": "zed@example.com", "password": "correct horse"}), 401, "unauthenticated")
        # replay of a pay for a request after import still 200
        rk = key()
        rid = call("POST", "/requests", {"payer_handle": "cy", "amount": 1}, bob, key())[1]["request_id"]
        pr = call("POST", f"/requests/{rid}/pay", {}, cy, rk)
        call("GET", "/_test/export")
        s, snap2, _ = call("GET", "/_test/export")
        reset(fixture())
        call("POST", "/_test/import", snap2)
        self.assertEqual(call("POST", f"/requests/{rid}/pay", {}, cy, rk)[:2], (200, pr[1]))
        # reset clears imported
        reset(fixture())
        err(self, call("GET", "/me", token=cy), 401, "unauthenticated")

    def test_invalid_imports(self):
        reset(fixture())
        ada = login("ada")
        snap = call("GET", "/_test/export")[1]
        err(self, call("POST", "/_test/import", raw="{"), 400, "malformed_request")
        bad = [{}, {"track": "pocketful"}, dict(snap, track="x"), dict(snap, format_version=2),
               dict(snap, format_version="1"), dict(snap, format_version=True), dict(snap, state=None),
               dict(snap, state={}), dict(snap, state=dict(snap["state"], users=[{"id": "x"}])),
               dict(snap, state=dict(snap["state"], users=5)),
               dict(snap, state=dict(snap["state"], tokens={"t": "ghost"}))]
        for b in bad:
            err(self, call("POST", "/_test/import", b), 422, "validation_failed")
        self.assertEqual(balance(ada), 10000)


if __name__ == "__main__":
    unittest.main(verbosity=1)
