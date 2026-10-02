"""Own tests written from the stage-1 specification. stdlib only.

Run against a started service:  BASE_URL=http://localhost:8080 python3 -m unittest discover -s tests -v
"""
import http.client
import json
import os
import re
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

BASE = urlsplit(os.environ.get("BASE_URL", "http://localhost:8080"))
BASE2 = os.environ.get("BASE_URL2")  # optional second container for import test
TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$")


def call(method, path, body=None, token=None, key=None, raw=None, headers=None, base=BASE):
    c = http.client.HTTPConnection(base.hostname, base.port, timeout=15)
    h = dict(headers or {})
    if token:
        h["Authorization"] = "Bearer " + token
    if key is not None:
        h["Idempotency-Key"] = key
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data is not None:
        h["Content-Type"] = "application/json"
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    txt = r.read()
    ct = r.getheader("Content-Type")
    c.close()
    try:
        js = json.loads(txt) if txt else None
    except ValueError:
        js = None
    return r.status, js, ct, txt


def U(i, handle, bal, email=None):
    return {"id": i, "email": email or handle + "@example.com", "password": "correct horse",
            "display_name": handle.title(), "handle": handle, "balance": bal}


def fixture(**kw):
    f = {"currency": "EUR", "minor_units": 2,
         "users": [U("u_ada", "ada", 10000), U("u_bob", "bob", 2500), U("u_cy", "cy", 500)]}
    f.update(kw)
    return f


def login(email):
    s, b, _, _ = call("POST", "/auth/login", {"email": email, "password": "correct horse"})
    assert s == 200, (s, b)
    return b["token"]


def k():
    return uuid.uuid4().hex


class Base(unittest.TestCase):
    def reset(self, fx=None):
        s, _, _, _ = call("POST", "/_test/reset", fx or fixture())
        self.assertEqual(s, 204)
        hs = {u["handle"] for u in (fx or fixture())["users"]}
        self.ada, self.bob, self.cy = (login(x + "@example.com") if x in hs else None
                                       for x in ("ada", "bob", "cy"))

    def setUp(self):
        self.reset()

    def me(self, t):
        return call("GET", "/me", token=t)[1]

    def err(self, resp, status, code):
        s, b, _, _ = resp
        self.assertEqual(s, status, b)
        self.assertEqual(b["error"]["code"], code)
        self.assertIsInstance(b["error"]["message"], str)

    def pay(self, t=None, **body):
        body.setdefault("to_handle", "bob")
        body.setdefault("amount", 100)
        return call("POST", "/payments", body, t or self.ada, k())


class Basics(Base):
    def test_health_contract_headers(self):
        s, b, ct, _ = call("GET", "/health")
        self.assertEqual((s, b), (200, {"status": "ok"}))
        self.assertEqual(ct, "application/json; charset=utf-8")
        s, _, _, txt = call("POST", "/_test/reset", fixture())
        self.assertEqual((s, txt), (204, b""))

    def test_unknown_route_and_method(self):
        self.err(call("GET", "/nope"), 404, "not_found")
        s, b, _, _ = call("DELETE", "/me", token=self.ada)
        self.assertIn("error", b)
        self.assertEqual(s, 405)

    def test_auth_required_everywhere(self):
        for m, p in [("GET", "/me"), ("POST", "/payments"), ("POST", "/requests"), ("GET", "/requests"),
                     ("POST", "/requests/x/pay"), ("POST", "/requests/x/decline"),
                     ("POST", "/requests/x/cancel"), ("POST", "/splits"), ("GET", "/activity"),
                     ("POST", "/settlements")]:
            self.err(call(m, p, {} if m == "POST" else None), 401, "unauthenticated")
            for h in ("Basic x", "Bearer", "Bearer nope", "bearer"):
                self.err(call(m, p, {} if m == "POST" else None, headers={"Authorization": h}), 401,
                         "unauthenticated")

    def test_reset_clears_everything(self):
        r = self.pay()[1]
        key = k()
        call("POST", "/payments", {"to_handle": "bob", "amount": 1}, self.ada, key)
        old = self.ada
        self.reset()
        self.err(call("GET", "/me", token=old), 401, "unauthenticated") if old == self.ada else None
        self.assertEqual(call("GET", "/activity", token=self.ada)[1]["payments"], [])
        s, _, _, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, self.ada, key)
        self.assertEqual(s, 201)

    def test_old_token_dead_after_reset(self):
        old = self.ada
        call("POST", "/_test/reset", fixture())
        self.err(call("GET", "/me", token=old), 401, "unauthenticated")

    def test_reset_validation(self):
        s, _, _, _ = call("POST", "/_test/reset", fixture(users=[U("u_ada", "ada", -1)]))
        self.assertEqual(s, 422)
        self.assertEqual(self.me(self.ada)["balance"], 10000)
        self.err(call("POST", "/_test/reset", raw=b"{nope"), 400, "malformed_request")
        # optional parts absent
        s, _, _, _ = call("POST", "/_test/reset", {"currency": "JPY", "minor_units": 0,
                                                    "users": [U("u_a", "a", 5)]})
        self.assertEqual(s, 204)
        t = login("a@example.com")
        self.assertEqual(self.me(t)["minor_units"], 0)

    def test_seeded_state_readable(self):
        fx = fixture(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                                "amount": 500, "note": "coffee", "visibility": "private"}],
                     requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
                                "amount": 1200, "note": "taxi", "status": "declined"}])
        self.reset(fx)
        self.assertEqual(self.me(self.ada)["balance"], 10000)
        a = call("GET", "/activity", token=self.ada)[1]["payments"]
        self.assertEqual(a[0]["payment_id"], "p_1")
        self.assertEqual(a[0]["to_handle"], "bob")
        self.assertTrue(TS.match(a[0]["created_at"]))
        self.assertEqual(call("GET", "/activity", token=self.cy)[1]["payments"], [])
        rq = call("GET", "/requests", token=self.bob)[1]["requests"][0]
        self.assertEqual((rq["request_id"], rq["status"], rq["payment_id"]), ("rq_1", "declined", None))


class Auth(Base):
    def test_signup_login(self):
        s, b, _, _ = call("POST", "/auth/signup", {"email": "A.B+c@x.org", "password": "12345678",
                                                    "display_name": "Abc", "handle": "ignored"})
        self.assertEqual(s, 201)
        self.assertEqual(set(b), {"user_id", "display_name", "token"})
        self.assertEqual(self.me(b["token"])["handle"], "a_b_c")
        self.assertEqual(self.me(b["token"])["balance"], 0)
        s, b2, _, _ = call("POST", "/auth/login", {"email": "A.B+c@x.org", "password": "12345678"})
        self.assertEqual(s, 200)
        self.assertNotEqual(b2["token"], b["token"])
        self.assertEqual(self.me(b["token"])["handle"], "a_b_c")  # old token valid
        self.err(call("POST", "/auth/signup", {"email": "A.B+c@x.org", "password": "12345678",
                                                "display_name": "x"}), 409, "email_taken")

    def test_long_local_part_truncated(self):
        s, b, _, _ = call("POST", "/auth/signup", {"email": "abcdefghijklmnopqrstuvwxy@x.org",
                                                    "password": "12345678", "display_name": "L"})
        self.assertEqual(self.me(b["token"])["handle"], "abcdefghijklmnopqrst")

    def test_validation(self):
        base = {"email": "z@x.org", "password": "12345678", "display_name": "Z"}
        for bad in ({"password": "short"}, {"email": "nodomain"}, {"email": "@x"}, {"email": "a@"},
                    {"email": "a b@c"}):
            self.err(call("POST", "/auth/signup", {**base, **bad}), 422, "validation_failed")
        self.err(call("POST", "/auth/signup", {"email": "z@x.org"}), 422, "validation_failed")
        self.err(call("POST", "/auth/signup", {**base, "email": 5}), 400, "malformed_request")
        self.err(call("POST", "/auth/signup", raw=b"[]"), 400, "malformed_request")

    def test_handle_taken(self):
        self.err(call("POST", "/auth/signup", {"email": "ada@other.org", "password": "12345678",
                                                "display_name": "A2"}), 409, "handle_taken")
        self.err(call("POST", "/auth/login", {"email": "ada@other.org", "password": "12345678"}),
                 401, "unauthenticated")
        s, _, _, _ = call("POST", "/auth/signup", {"email": "ada@example.com", "password": "12345678",
                                                    "display_name": "A2"})
        self.assertEqual(s, 409)

    def test_login_failures(self):
        self.err(call("POST", "/auth/login", {"email": "ada@example.com", "password": "bad"}), 401,
                 "unauthenticated")
        self.err(call("POST", "/auth/login", {"email": "zz@example.com", "password": "bad"}), 401,
                 "unauthenticated")


class Payments(Base):
    def test_shape_and_money(self):
        s, b, ct, _ = self.pay(amount=1500, note="dinner", visibility="private")
        self.assertEqual(s, 201)
        self.assertEqual(ct, "application/json; charset=utf-8")
        self.assertEqual(set(b), {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
                                  "amount", "currency", "note", "visibility", "request_id",
                                  "settlement_id", "created_at"})
        self.assertIsNone(b["request_id"])
        self.assertIsNone(b["settlement_id"])
        self.assertTrue(TS.match(b["created_at"]))
        self.assertEqual(self.me(self.ada)["balance"], 8500)
        self.assertEqual(self.me(self.bob)["balance"], 4000)

    def test_defaults_and_float_amounts(self):
        b = self.pay(amount=1000.0)[1]
        self.assertEqual((b["note"], b["visibility"], b["amount"]), ("", "public", 1000))
        self.assertIs(type(b["amount"]), int)
        s, b, _, txt = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1e3}', token=self.ada,
                            key=k())
        self.assertEqual(s, 201)
        self.assertIn(b'"amount": 1000,', txt)

    def test_exact_balance_and_max(self):
        self.assertEqual(self.pay(self.cy, amount=500)[0], 201)
        self.assertEqual(self.me(self.cy)["balance"], 0)
        self.err(self.pay(self.cy, amount=1), 409, "insufficient_funds")
        self.reset(fixture(users=[U("u_ada", "ada", 2 ** 53 - 1000), U("u_bob", "bob", 0)]))
        self.assertEqual(self.pay(amount=1000000000)[0], 201)
        self.assertEqual(self.me(self.ada)["balance"], 2 ** 53 - 1000 - 10 ** 9)
        self.err(self.pay(amount=1000000001), 422, "validation_failed")

    def test_validation(self):
        for amt in (0, -1, 1.5, "100", True, None, [], {}, 10 ** 30, 1e30):
            self.err(self.pay(amount=amt), 422, "validation_failed")
        self.err(call("POST", "/payments", {"to_handle": "bob"}, self.ada, k()), 422, "validation_failed")
        self.err(call("POST", "/payments", {"amount": 5}, self.ada, k()), 422, "validation_failed")
        self.err(self.pay(to_handle=5), 400, "malformed_request")
        self.err(self.pay(to_handle=None), 400, "malformed_request")
        self.err(self.pay(to_handle="ada"), 422, "self_payment")
        self.err(self.pay(to_handle="ghost"), 404, "not_found")
        self.err(self.pay(to_handle="Bob"), 404, "not_found")
        for n in (None, 5, True, [], "x" * 201):
            self.err(self.pay(note=n), 422, "validation_failed")
        for v in ("friends", "", None, 1, True, "PUBLIC"):
            self.err(self.pay(visibility=v), 422, "validation_failed")
        self.err(self.pay(amount="x", to_handle=5), 422, "validation_failed")
        self.err(call("POST", "/payments", raw=b"{bad", token=self.ada, key=k()), 400, "malformed_request")
        self.err(call("POST", "/payments", raw=b"[1]", token=self.ada, key=k()), 400, "malformed_request")
        self.err(call("POST", "/payments", raw=b"", token=self.ada, key=k()), 400, "malformed_request")
        self.err(call("POST", "/payments", raw=b'{"to_handle":"bob","amount":NaN}', token=self.ada,
                      key=k()), 400, "malformed_request")
        self.assertEqual(self.me(self.ada)["balance"], 10000)

    def test_note_boundaries_and_verbatim(self):
        self.assertEqual(self.pay(note="x" * 200)[0], 201)
        e = "\U0001F600" * 200
        self.assertEqual(self.pay(note=e)[0], 201)
        self.err(self.pay(note=e + "\U0001F600"), 422, "validation_failed")
        for n in ("  lead and trail  ", "<b>&amp;</b>", "e\u0301 vs \u00e9", "\u0041\u030a", "a\nb\t\"q\"\\",
                  "\u00a0"):
            b = self.pay(note=n)[1]
            self.assertEqual(b["note"], n)
            got = call("GET", "/activity", token=self.bob)[1]["payments"][0]
            self.assertEqual(got["note"], n)

    def test_unknown_fields_and_query_ignored(self):
        s, _, _, _ = call("POST", "/payments?x=1", {"to_handle": "bob", "amount": 1, "zzz": [1]},
                          self.ada, k())
        self.assertEqual(s, 201)
        self.assertEqual(call("GET", "/me?foo=bar", token=self.ada)[0], 200)

    def test_limits_idem_key(self):
        body = {"to_handle": "bob", "amount": 1}
        self.err(call("POST", "/payments", body, self.ada), 400, "missing_idempotency_key")
        self.err(call("POST", "/payments", body, self.ada, ""), 400, "missing_idempotency_key")
        self.assertEqual(call("POST", "/payments", body, self.ada, "k" * 255)[0], 201)
        self.err(call("POST", "/payments", body, self.ada, "k" * 256), 422, "validation_failed")


class Idempotency(Base):
    def test_replay_all_paths(self):
        self.reset(fixture(settlement_operator_ids=["u_ada"]))
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 50}, self.bob, k())[1]
        ops = {
            "payments": ("/payments", {"to_handle": "bob", "amount": 10}, self.ada),
            "requests": ("/requests", {"payer_handle": "ada", "amount": 10}, self.bob),
            "pay": ("/requests/%s/pay" % rq["request_id"], {"visibility": "private"}, self.ada),
            "splits": ("/splits", {"amount": 100, "participant_handles": ["ada", "bob", "cy"]}, self.ada),
            "settlements": ("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob",
                                                             "amount": 5}]}, self.ada),
        }
        for name, (path, body, tok) in ops.items():
            key = k()
            s1, b1, _, _ = call("POST", path, body, tok, key)
            self.assertEqual(s1, 201, name)
            bal = self.me(self.ada)["balance"]
            reordered = dict(reversed(list(body.items())))
            s2, b2, _, _ = call("POST", path, reordered, tok, key)
            self.assertEqual((s2, b2), (200, b1), name)
            self.assertEqual(self.me(self.ada)["balance"], bal)
            self.err(call("POST", path, {**body, "extra_diff": 1}, tok, key), 409, "idempotency_key_reuse")
            self.err(call("POST", path, {}, tok, key), 409, "idempotency_key_reuse")
            self.err(call("POST", path, body, tok), 400, "missing_idempotency_key")
            self.err(call("POST", path, body, tok, ""), 400, "missing_idempotency_key")
            self.err(call("POST", path, body, tok, "k" * 256), 422, "validation_failed")

    def test_numeric_equality_in_replay(self):
        key = k()
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 10}, self.ada, key)[0], 201)
        s, _, _, _ = call("POST", "/payments", raw=b'{"amount":1e1,"to_handle":"bob"}', token=self.ada,
                          key=key)
        self.assertEqual(s, 200)

    def test_scope_user_and_path(self):
        key = k()
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, self.ada, key)[0], 201)
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, self.cy, key)[0], 201)
        self.assertEqual(call("POST", "/requests", {"payer_handle": "bob", "amount": 1}, self.ada, key)[0], 201)

    def test_failure_does_not_claim_and_precedence(self):
        key = k()
        self.err(call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 6}, self.ada, key), 409,
                 "insufficient_funds")
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, self.ada, key)[0], 201)
        # claimed key beats validation
        self.err(call("POST", "/payments", {"to_handle": "bob", "amount": -5}, self.ada, key), 409,
                 "idempotency_key_reuse")
        self.err(call("POST", "/payments", {"to_handle": 5}, self.ada, key), 409, "idempotency_key_reuse")
        self.err(call("POST", "/payments", raw=b"[]", token=self.ada, key=key), 400, "malformed_request")

    def test_pay_replay_after_paid_and_cancel(self):
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 50}, self.bob, k())[1]
        path = "/requests/%s/pay" % rq["request_id"]
        key = k()
        s, p, _, _ = call("POST", path, {}, self.ada, key)
        self.assertEqual(s, 201)
        self.assertEqual(p["request_id"], rq["request_id"])
        self.assertEqual(call("POST", path, {}, self.ada, key)[:2], (200, p))
        self.err(call("POST", path, {"visibility": "public"}, self.ada, key), 409, "idempotency_key_reuse")
        self.err(call("POST", path, {}, self.ada, k()), 409, "request_not_pending")
        self.assertEqual(self.me(self.ada)["balance"], 9950)
        # empty body equals {}
        rq2 = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, k())[1]
        self.assertEqual(call("POST", "/requests/%s/pay" % rq2["request_id"], token=self.ada, key=k())[0], 201)

    def test_request_replay_after_cancel(self):
        key = k()
        s, r, _, _ = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, key)
        call("POST", "/requests/%s/cancel" % r["request_id"], token=self.bob)
        s2, r2, _, _ = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, key)
        self.assertEqual((s2, r2), (200, r))
        self.assertEqual(r2["status"], "pending")


class Requests(Base):
    def mk(self, amount=100, payer="ada", tok=None, **kw):
        return call("POST", "/requests", {"payer_handle": payer, "amount": amount, **kw}, tok or self.bob, k())

    def test_create_shape_and_errors(self):
        s, r, _, _ = self.mk(1200, note="taxi")
        self.assertEqual(s, 201)
        self.assertEqual(set(r), {"request_id", "requester_id", "requester_handle", "payer_id",
                                  "payer_handle", "amount", "currency", "note", "status", "payment_id",
                                  "created_at"})
        self.assertEqual((r["status"], r["payment_id"], r["requester_handle"], r["payer_handle"]),
                         ("pending", None, "bob", "ada"))
        self.assertEqual(self.mk(10 ** 9)[0], 201)  # exceeds balance, fine
        for a in (0, -1, 1.5, "5", 10 ** 9 + 1):
            self.err(self.mk(a), 422, "validation_failed")
        self.err(self.mk(payer="bob"), 422, "self_request")
        self.err(self.mk(payer="ghost"), 404, "not_found")
        self.err(self.mk(note="x" * 201), 422, "validation_failed")
        self.err(self.mk(payer=7), 400, "malformed_request")

    def test_lifecycle(self):
        r = self.mk(20000)[1]
        rid = r["request_id"]
        pay = lambda t, **b: call("POST", "/requests/%s/pay" % rid, b, t, k())
        self.err(pay(self.ada), 409, "insufficient_funds")
        self.assertEqual(call("GET", "/requests?status=pending", token=self.ada)[1]["requests"][0]["status"],
                         "pending")
        self.err(pay(self.bob), 403, "forbidden")
        self.err(pay(self.cy), 403, "forbidden")
        self.err(call("POST", "/requests/nope/pay", {}, self.ada, k()), 404, "not_found")
        # fund ada, then pay
        self.assertEqual(call("POST", "/payments", {"to_handle": "ada", "amount": 10000}, self.bob and self.bob, k())[0], 409)
        self.reset(fixture(users=[U("u_ada", "ada", 30000), U("u_bob", "bob", 0), U("u_cy", "cy", 0)]))
        rid = self.mk(20000)[1]["request_id"]
        s, p, _, _ = call("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, self.ada, k())
        self.assertEqual((s, p["request_id"], p["visibility"], p["amount"]), (201, rid, "private", 20000))
        rq = call("GET", "/requests", token=self.bob)[1]["requests"][0]
        self.assertEqual((rq["status"], rq["payment_id"]), ("paid", p["payment_id"]))
        self.assertEqual(self.me(self.bob)["balance"], 20000)
        for act, t in (("decline", self.ada), ("cancel", self.bob)):
            self.err(call("POST", "/requests/%s/%s" % (rid, act), token=t), 409, "request_not_pending")

    def test_decline_cancel(self):
        a = self.mk()[1]["request_id"]
        b = self.mk()[1]["request_id"]
        self.err(call("POST", "/requests/%s/decline" % a, token=self.bob), 403, "forbidden")
        self.err(call("POST", "/requests/%s/decline" % a, token=self.cy), 403, "forbidden")
        self.err(call("POST", "/requests/%s/cancel" % a, token=self.ada), 403, "forbidden")
        self.err(call("POST", "/requests/zz/cancel", token=self.ada), 404, "not_found")
        self.err(call("POST", "/requests/zz/decline", token=self.ada), 404, "not_found")
        for _ in range(2):
            s, r, _, _ = call("POST", "/requests/%s/decline" % a, token=self.ada)
            self.assertEqual((s, r["status"]), (200, "declined"))
        self.err(call("POST", "/requests/%s/cancel" % a, token=self.bob), 409, "request_not_pending")
        self.err(call("POST", "/requests/%s/pay" % a, {}, self.ada, k()), 409, "request_not_pending")
        for _ in range(2):
            s, r, _, _ = call("POST", "/requests/%s/cancel" % b, token=self.bob)
            self.assertEqual((s, r["status"]), (200, "cancelled"))
        self.err(call("POST", "/requests/%s/decline" % b, token=self.ada), 409, "request_not_pending")

    def test_list_filters_paging(self):
        ids = [self.mk(i + 1)[1]["request_id"] for i in range(5)]
        call("POST", "/requests", {"payer_handle": "bob", "amount": 7}, self.ada, k())
        self.mk(payer="cy", tok=self.bob)
        self.assertEqual(call("GET", "/requests", token=self.cy)[1]["requests"][0]["payer_handle"], "cy")
        g = lambda q, t=None: call("GET", "/requests" + q, token=t or self.ada)
        allr = g("")[1]["requests"]
        self.assertEqual(len(allr), 6)
        self.assertEqual([r["request_id"] for r in allr[1:]], ids[::-1])
        self.assertEqual(len(g("?direction=incoming")[1]["requests"]), 5)
        self.assertEqual(len(g("?direction=outgoing")[1]["requests"]), 1)
        r = g("?limit=6")[1]
        self.assertFalse(r["has_more"])
        r = g("?limit=5")[1]
        self.assertTrue(r["has_more"])
        self.assertEqual(g("?limit=5&offset=1")[1]["has_more"], False)
        self.assertEqual(g("?offset=6")[1], {"requests": [], "has_more": False})
        call("POST", "/requests/%s/cancel" % ids[0], token=self.bob)
        self.assertEqual(len(g("?status=cancelled")[1]["requests"]), 1)
        for q in ("?limit=0", "?limit=201", "?offset=-1", "?limit=1e1", "?limit=4.0", "?limit=%2B4", "?limit=",
                  "?limit=abc", "?limit=-1", "?offset=1e9", "?direction=x", "?status=x", "?status=", "?limit=%D9%A3"):
            self.err(g(q), 422, "validation_failed")
        self.assertEqual(g("?limit=200")[0], 200)
        self.assertEqual(g("?limit=1&bogus=1")[0], 200)


class Feed(Base):
    def test_visibility_rules(self):
        self.pay(self.ada, to_handle="bob", visibility="private", note="secret")
        self.pay(self.ada, to_handle="bob", visibility="public", note="open")
        notes = lambda t: [p["note"] for p in call("GET", "/activity", token=t)[1]["payments"]]
        self.assertEqual(notes(self.ada), ["open", "secret"])
        self.assertEqual(notes(self.bob), ["open", "secret"])
        self.assertEqual(notes(self.cy), ["open"])
        self.err(call("GET", "/activity?limit=0", token=self.cy), 422, "validation_failed")
        r = call("GET", "/activity?limit=1&offset=1&direction=zzz", token=self.ada)[1]
        self.assertEqual([p["note"] for p in r["payments"]], ["secret"])
        self.assertFalse(r["has_more"])
        self.assertTrue(call("GET", "/activity?limit=1", token=self.ada)[1]["has_more"])

    def test_requests_and_splits_not_in_feed(self):
        call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, k())
        call("POST", "/splits", {"amount": 9, "participant_handles": ["ada", "bob"]}, self.bob, k())
        self.assertEqual(call("GET", "/activity", token=self.ada)[1]["payments"], [])

    def test_pay_visibility_is_payers(self):
        rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, k())[1]["request_id"]
        call("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, self.ada, k())
        self.assertEqual(len(call("GET", "/activity", token=self.bob)[1]["payments"]), 1)
        self.assertEqual(call("GET", "/activity", token=self.cy)[1]["payments"], [])
        self.assertEqual(call("GET", "/activity", token=self.cy)[1]["payments"], [])


class Splits(Base):
    def split(self, amount, hs, t=None, **kw):
        return call("POST", "/splits", {"amount": amount, "participant_handles": hs, **kw}, t or self.ada, k())

    def test_table(self):
        users = [U("u_a", "a", 0), U("u_b", "b", 0), U("u_c", "c", 0), U("u_d", "d", 0), U("u_e", "e", 0)]
        self.reset(fixture(users=users))
        t = login("a@example.com")
        for amount, n, exp in [(1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
                               (999, 3, [333] * 3), (5, 5, [1] * 5)]:
            s, b, _, _ = call("POST", "/splits", {"amount": amount, "participant_handles": list("abcde"[:n])},
                              t, k())
            self.assertEqual(s, 201)
            self.assertEqual([x["amount"] for x in b["shares"]], exp)
            self.assertEqual([x["handle"] for x in b["shares"]], list("abcde"[:n]))
            self.assertEqual([r["amount"] for r in b["requests"]], exp[1:])
            self.assertEqual(sum(exp), amount)
        b = call("POST", "/splits", {"amount": 10, "participant_handles": ["c", "a", "b"]}, t, k())[1]
        self.assertEqual([x["amount"] for x in b["shares"]], [4, 3, 3])
        self.assertEqual([r["payer_handle"] for r in b["requests"]], ["c", "b"])

    def test_shape_caller_omitted_only_caller(self):
        s, b, _, _ = self.split(3000, ["bob", "cy"], note="dinner")
        self.assertEqual(s, 201)
        self.assertEqual(set(b), {"split_id", "amount", "currency", "note", "shares", "requests", "created_at"})
        self.assertEqual([x["amount"] for x in b["shares"]], [1500, 1500])
        self.assertEqual(len(b["requests"]), 2)
        self.assertTrue(all(r["requester_handle"] == "ada" and r["status"] == "pending" for r in b["requests"]))
        s, b, _, _ = self.split(7, ["ada"])
        self.assertEqual((s, b["requests"], b["shares"]), (201, [], [{"handle": "ada", "amount": 7}]))
        b = self.split(1, ["bob", "cy", "ada"])[1]
        self.assertEqual([x["amount"] for x in b["shares"]], [1, 0, 0])
        zero = b["requests"][1]
        self.assertEqual(zero["amount"], 0)
        s, _, _, _ = call("POST", "/requests/%s/pay" % zero["request_id"], {}, self.cy, k())
        self.assertLess(s, 500)
        self.assertEqual(self.me(self.cy)["balance"], 500)

    def test_errors(self):
        for a in (0, -3, 1.5, "9", None, 10 ** 9 + 1):
            self.err(self.split(a, ["bob"]), 422, "validation_failed")
        self.err(self.split(10, []), 422, "validation_failed")
        self.err(self.split(10, ["bob", "bob"]), 422, "validation_failed")
        self.err(self.split(10, ["bob", "ghost"]), 404, "not_found")
        self.err(self.split(10, ["bob"], note="x" * 201), 422, "validation_failed")
        self.err(self.split(10, "bob"), 400, "malformed_request")
        self.err(self.split(10, [1]), 400, "malformed_request")
        self.err(call("POST", "/splits", {"amount": 5}, self.ada, k()), 422, "validation_failed")
        self.assertEqual(call("GET", "/requests", token=self.ada)[1]["requests"], [])

    def test_paid_in_full_conserves(self):
        total = 13000
        for _ in range(6):
            b = self.split(1001, ["ada", "bob", "cy"])[1]
            for r in b["requests"]:
                t = self.bob if r["payer_handle"] == "bob" else self.cy
                call("POST", "/requests/%s/pay" % r["request_id"], {}, t, k())
        bal = sum(self.me(t)["balance"] for t in (self.ada, self.bob, self.cy))
        self.assertEqual(bal, total)


class Settlements(Base):
    def setUp(self):
        self.reset(fixture(settlement_operator_ids=["u_ada"]))

    def st(self, transfers, t=None, key=None):
        return call("POST", "/settlements", {"transfers": transfers}, t or self.ada, key or k())

    def T(self, a, b, amt, **kw):
        return {"from_handle": a, "to_handle": b, "amount": amt, **kw}

    def test_access(self):
        self.err(call("POST", "/settlements", {"transfers": []}), 401, "unauthenticated")
        self.err(self.st([self.T("ada", "bob", 1)], self.bob), 403, "forbidden")
        self.err(call("POST", "/settlements", {"transfers": [self.T("ada", "bob", 1)]}, self.ada),
                 400, "missing_idempotency_key")
        self.err(call("POST", "/settlements", {"transfers": [self.T("ada", "bob", 1)]}, self.ada, ""),
                 400, "missing_idempotency_key")

    def test_success_shape(self):
        s, b, _, _ = self.st([self.T("ada", "bob", 100, note="n", visibility="private"),
                              self.T("bob", "cy", 50)])
        self.assertEqual(s, 201)
        self.assertEqual(set(b), {"settlement_id", "committed_at", "payments"})
        ps = b["payments"]
        self.assertEqual([p["amount"] for p in ps], [100, 50])
        self.assertTrue(all(p["settlement_id"] == b["settlement_id"] and p["request_id"] is None and
                            p["created_at"] == b["committed_at"] for p in ps))
        self.assertEqual((ps[0]["note"], ps[0]["visibility"], ps[1]["note"], ps[1]["visibility"]),
                         ("n", "private", "", "public"))
        self.assertEqual([self.me(t)["balance"] for t in (self.ada, self.bob, self.cy)], [9900, 2550, 550])
        # visibility: private member hidden from cy, operator sees own; cy sees the public one
        self.assertEqual([p["amount"] for p in call("GET", "/activity", token=self.cy)[1]["payments"]], [50])
        self.assertEqual(call("GET", "/activity", token=self.cy)[1]["payments"][0]["settlement_id"],
                         b["settlement_id"])

    def test_operator_no_extra_access(self):
        self.pay(self.bob, to_handle="cy", visibility="private", amount=5)
        self.assertEqual(call("GET", "/activity", token=self.ada)[1]["payments"], [])
        call("POST", "/requests", {"payer_handle": "cy", "amount": 5}, self.bob, k())
        self.assertEqual(call("GET", "/requests", token=self.ada)[1]["requests"], [])

    def test_net_affordability(self):
        self.err(self.st([self.T("bob", "cy", 3000)]), 409, "insufficient_funds")
        s, _, _, _ = self.st([self.T("ada", "bob", 1000), self.T("bob", "cy", 3000)])
        self.assertEqual(s, 201)
        self.assertEqual([self.me(t)["balance"] for t in (self.ada, self.bob, self.cy)], [9000, 500, 3500])
        # order within batch irrelevant
        s, _, _, _ = self.st([self.T("cy", "bob", 3500), self.T("bob", "ada", 4000)])
        self.assertEqual(s, 201)
        self.err(self.st([self.T("cy", "bob", 1), self.T("cy", "ada", 3500)]), 409, "insufficient_funds")

    def test_all_or_nothing_and_key_reuse(self):
        before = [self.me(t)["balance"] for t in (self.ada, self.bob, self.cy)]
        key = k()
        self.err(self.st([self.T("ada", "bob", 1), self.T("cy", "bob", 10 ** 6)], key=key), 409,
                 "insufficient_funds")
        self.err(self.st([self.T("ada", "bob", 1), self.T("ada", "ghost", 1)], key=key), 404, "not_found")
        self.assertEqual([self.me(t)["balance"] for t in (self.ada, self.bob, self.cy)], before)
        self.assertEqual(call("GET", "/activity", token=self.ada)[1]["payments"], [])
        self.assertEqual(self.st([self.T("ada", "bob", 1)], key=key)[0], 201)

    def test_entry_errors_in_order(self):
        big = 10 ** 6
        self.err(self.st([self.T("cy", "bob", big), self.T("ada", "ghost", 1)]), 404, "not_found")
        self.err(self.st([self.T("ada", "bob", 1), self.T("ada", "ada", 1), self.T("x1", "x2", 1)]), 422,
                 "self_payment")
        self.err(self.st([self.T("ada", "ada", 1), self.T("ada", "ghost", 1)]), 422, "self_payment")
        self.err(self.st([self.T("ada", "ghost", 1), self.T("ada", "ada", 1)]), 404, "not_found")
        self.err(self.st([self.T("ada", "bob", 0)]), 422, "validation_failed")
        self.err(self.st([self.T("ada", "bob", 1, note="x" * 201)]), 422, "validation_failed")
        self.err(self.st([self.T("ada", "bob", 1, visibility="x")]), 422, "validation_failed")

    def test_shape_errors(self):
        for tr in (None, "x", {}, [], [1], [None], ["a"], [{}], [{"from_handle": "ada"}],
                   [self.T("ada", "bob", 1)] * 33):
            self.err(call("POST", "/settlements", {"transfers": tr}, self.ada, k()), 422, "validation_failed")
        self.err(call("POST", "/settlements", {}, self.ada, k()), 422, "validation_failed")
        self.err(call("POST", "/settlements", raw=b"[]", token=self.ada, key=k()), 400, "malformed_request")
        self.assertEqual(self.st([self.T("ada", "bob", 1, junk=1)])[0], 201)
        s, b, _, _ = self.st([self.T("ada", "bob", 1)] * 32)
        self.assertEqual((s, len(b["payments"])), (201, 32))

    def test_non_members_null(self):
        p = self.pay(self.ada)[1]
        self.assertIsNone(p["settlement_id"])
        self.assertIsNone(call("GET", "/activity", token=self.ada)[1]["payments"][0]["settlement_id"])


class ExportImport(Base):
    def populate(self):
        self.reset(fixture(settlement_operator_ids=["u_ada"],
                           payments=[{"id": "p_s", "from_user_id": "u_ada", "to_user_id": "u_bob",
                                      "amount": 5, "note": "seed", "visibility": "public"}]))
        self.keys = {}
        self.keys["pay"] = (k(), "/payments", {"to_handle": "bob", "amount": 10, "visibility": "private"},
                            self.ada)
        rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 20}, self.bob, k())[1]["request_id"]
        self.keys["req"] = (k(), "/requests", {"payer_handle": "cy", "amount": 3}, self.bob)
        self.keys["pay_req"] = (k(), "/requests/%s/pay" % rid, {}, self.ada)
        self.keys["split"] = (k(), "/splits", {"amount": 10, "participant_handles": ["ada", "bob"]}, self.ada)
        self.keys["settle"] = (k(), "/settlements",
                               {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 7}]}, self.ada)
        self.orig = {}
        for n, (key, path, body, tok) in self.keys.items():
            s, b, _, _ = call("POST", path, body, tok, key)
            self.assertEqual(s, 201, n)
            self.orig[n] = b
        self.failed_key = k()
        call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 8}, self.cy, self.failed_key)

    def snap(self):
        out = {}
        for n, t in (("ada", self.ada), ("bob", self.bob), ("cy", self.cy)):
            out[n] = (call("GET", "/me", token=t)[1], call("GET", "/activity?limit=200", token=t)[1],
                      call("GET", "/requests?limit=200", token=t)[1])
        return out

    def test_roundtrip_same_service(self):
        self.populate()
        s, exp, _, _ = call("GET", "/_test/export")
        self.assertEqual((s, exp["track"], exp["format_version"]), (200, "pocketful", 1))
        self.assertNotIn("correct horse", json.dumps(exp))
        before = self.snap()
        toks = (self.ada, self.bob, self.cy)
        self.reset()  # replace by different fixture
        self.err(call("GET", "/me", token=toks[0]), 401, "unauthenticated")
        self.assertEqual(call("POST", "/_test/import", exp)[0], 204)
        self.assertEqual(call("POST", "/_test/import", exp)[0], 204)  # repeat: no duplicates
        self.ada, self.bob, self.cy = toks  # tokens issued before export still work
        self.assertEqual(self.snap(), before)
        self.assertEqual(call("GET", "/_test/export")[1], exp)
        self.check_receipts()
        # login with password still works
        self.assertEqual(call("POST", "/auth/login", {"email": "ada@example.com",
                                                      "password": "correct horse"})[0], 200)
        # reset after import clears all
        self.reset()
        self.assertEqual(call("GET", "/activity", token=self.ada)[1]["payments"], [])

    def check_receipts(self, base=BASE):
        for n, (key, path, body, tok) in self.keys.items():
            s, b, _, _ = call("POST", path, body, tok, key, base=base)
            self.assertEqual((s, b), (200, self.orig[n]), n)
            self.err(call("POST", path, {**body, "zz": 1}, tok, key, base=base), 409, "idempotency_key_reuse")
        s, _, _, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, self.cy, self.failed_key, base=base)
        self.assertEqual(s, 201)

    def test_import_errors(self):
        self.populate()
        _, exp, _, _ = call("GET", "/_test/export")
        before = self.snap()
        self.err(call("POST", "/_test/import", raw=b"{x"), 400, "malformed_request")
        bads = [{}, {"track": "pocketful"}, {**exp, "track": "x"}, {**exp, "format_version": 2},
                {**exp, "format_version": "1"}, {**exp, "state": 5}, {**exp, "state": {}},
                {**exp, "state": {**exp["state"], "users": "x"}},
                {**exp, "state": {**exp["state"], "payments": [{"id": "z"}]}}]
        for b in bads:
            self.err(call("POST", "/_test/import", b), 422, "validation_failed")
        self.assertEqual(self.snap(), before)

    def test_export_is_snapshot(self):
        self.populate()
        exp = call("GET", "/_test/export")[1]
        self.pay(self.ada)
        self.assertNotEqual(call("GET", "/_test/export")[1], exp)
        json.dumps(exp)

    @unittest.skipUnless(BASE2, "BASE_URL2 not set")
    def test_import_into_second_container(self):
        self.populate()
        exp = call("GET", "/_test/export")[1]
        before = self.snap()
        call("POST", "/_test/reset", fixture(users=[U("u_z", "z", 1)]), base=urlsplit(BASE2))
        self.assertEqual(call("POST", "/_test/import", exp, base=urlsplit(BASE2))[0], 204)
        for n, t in (("ada", self.ada), ("bob", self.bob), ("cy", self.cy)):
            self.assertEqual(call("GET", "/me", token=t, base=urlsplit(BASE2))[1], before[n][0])
            self.assertEqual(call("GET", "/activity?limit=200", token=t, base=urlsplit(BASE2))[1], before[n][1])
        self.check_receipts(base=urlsplit(BASE2))


class Concurrency(Base):
    def par(self, fns, n=50):
        with ThreadPoolExecutor(n) as ex:
            return list(ex.map(lambda f: f(), fns))

    def total(self):
        return sum(self.me(t)["balance"] for t in (self.ada, self.bob, self.cy))

    def test_drain_never_negative(self):
        stop = threading.Event()
        seen = []

        def watch():
            while not stop.is_set():
                seen.append(self.me(self.cy)["balance"])
        th = threading.Thread(target=watch)
        th.start()
        res = self.par([lambda: call("POST", "/payments", {"to_handle": "bob", "amount": 70}, self.cy, k())
                        for _ in range(50)])
        stop.set()
        th.join()
        ok = [r for r in res if r[0] == 201]
        self.assertEqual(len(ok), 7)
        self.assertTrue(all(r[0] in (201, 409) for r in res))
        self.assertGreaterEqual(min(seen), 0)
        self.assertEqual(self.me(self.cy)["balance"], 500 - 7 * 70)
        self.assertEqual(self.total(), 13000)

    def test_pay_once(self):
        rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, self.bob, k())[1]["request_id"]
        res = self.par([lambda: call("POST", "/requests/%s/pay" % rid, {}, self.ada, k()) for _ in range(30)])
        self.assertEqual(sorted(r[0] for r in res), [201] + [409] * 29)
        self.assertTrue(all(r[1]["error"]["code"] == "request_not_pending" for r in res if r[0] == 409))
        rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, self.bob, k())[1]["request_id"]
        key = k()
        res = self.par([lambda: call("POST", "/requests/%s/pay" % rid, {}, self.ada, key) for _ in range(30)])
        self.assertEqual(sorted(r[0] for r in res), [200] * 29 + [201])
        self.assertEqual(len({json.dumps(r[1], sort_keys=True) for r in res}), 1)
        self.assertEqual(self.me(self.ada)["balance"], 9800)

    def test_same_key_each_path(self):
        self.reset(fixture(settlement_operator_ids=["u_ada"]))
        reqs = [("/payments", {"to_handle": "bob", "amount": 10}, self.ada),
                ("/requests", {"payer_handle": "ada", "amount": 10}, self.bob),
                ("/splits", {"amount": 10, "participant_handles": ["ada", "bob"]}, self.ada),
                ("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]},
                 self.ada)]
        for path, body, tok in reqs:
            key = k()
            res = self.par([lambda: call("POST", path, body, tok, key) for _ in range(20)], 20)
            self.assertEqual(sorted(r[0] for r in res), [200] * 19 + [201], path)
            self.assertEqual(len({json.dumps(r[1], sort_keys=True) for r in res}), 1)
        self.assertEqual(self.me(self.ada)["balance"], 9980)
        self.assertEqual(len(call("GET", "/activity", token=self.ada)[1]["payments"]), 2)

    def test_mixed_burst_conserves(self):
        self.reset(fixture(settlement_operator_ids=["u_ada"]))
        rids = [call("POST", "/requests", {"payer_handle": "ada", "amount": 50}, self.bob, k())[1]["request_id"]
                for _ in range(10)]
        fns = []
        for i in range(50):
            m = i % 5
            if m == 0:
                fns.append(lambda: call("POST", "/payments", {"to_handle": "ada", "amount": 300}, self.cy, k()))
            elif m == 1:
                fns.append(lambda: call("POST", "/payments", {"to_handle": "cy", "amount": 900}, self.bob, k()))
            elif m == 2:
                r = rids[i // 5]
                fns.append(lambda r=r: call("POST", "/requests/%s/pay" % r, {}, self.ada, k()))
            elif m == 3:
                fns.append(lambda: call("POST", "/settlements", {"transfers": [
                    {"from_handle": "cy", "to_handle": "bob", "amount": 400},
                    {"from_handle": "bob", "to_handle": "ada", "amount": 50}]}, self.ada, k()))
            else:
                fns.append(lambda: call("POST", "/splits", {"amount": 100, "participant_handles": ["ada", "bob"]},
                                        self.ada, k()))
        res = self.par(fns)
        self.assertTrue(all(r[0] < 500 for r in res))
        self.assertEqual(self.total(), 13000)
        for t in (self.ada, self.bob, self.cy):
            self.assertGreaterEqual(self.me(t)["balance"], 0)


class Fuzz(Base):
    def test_no_5xx(self):
        self.reset(fixture(settlement_operator_ids=["u_ada"]))
        weird = [None, True, False, 0, -1, 1.5, 1e400 if False else 2 ** 70, "", "x", "\ud800", [], [None], {},
                 {"a": 1}, "😀" * 300, "a\u0000b"]
        endpoints = [("/payments", ["to_handle", "amount", "note", "visibility"]),
                     ("/requests", ["payer_handle", "amount", "note"]),
                     ("/splits", ["amount", "participant_handles", "note"]),
                     ("/settlements", ["transfers"]),
                     ("/requests/rq/pay", ["visibility"]),
                     ("/auth/signup", ["email", "password", "display_name"]),
                     ("/auth/login", ["email", "password"])]
        bodies = []
        for path, fields in endpoints:
            for f in fields:
                for w in weird:
                    bodies.append((path, {f: w}))
            bodies.append((path, {fi: w for fi in fields for w in weird[:1]}))
        def one(a):
            path, body = a
            try:
                data = json.dumps(body)
            except Exception:
                return 200
            s = call("POST", path, raw=data.encode("utf-8", "surrogatepass") if False else data.encode("ascii"),
                     token=self.ada, key=k())[0]
            return s
        with ThreadPoolExecutor(20) as ex:
            res = list(ex.map(one, bodies))
        self.assertTrue(all(s < 500 for s in res), [s for s in res if s >= 500])
        for raw in (b"\xff\xfe", b"{", b'{"a":', b"nul", b'"str"', b"123", b"[" * 5000, b"{" * 100000):
            for path in ("/payments", "/auth/login", "/_test/reset", "/_test/import", "/settlements"):
                s = call("POST", path, raw=raw, token=self.ada, key=k())[0]
                self.assertIn(s, (400, 422), (path, s))


if __name__ == "__main__":
    unittest.main()
