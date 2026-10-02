"""Own tests for stage 1, stdlib only. Run against a live service: BASE_URL=http://localhost:8080 python3 tests/test_stage1.py"""
import http.client
import json
import os
import re
import threading
import time
import unittest
import uuid
from urllib.parse import urlparse

U = urlparse(os.environ.get("BASE_URL", "http://localhost:8080"))


def call(method, path, body=None, token=None, key=None, raw=None, headers=None):
    c = http.client.HTTPConnection(U.hostname, U.port, timeout=15)
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
    c.close()
    try:
        js = json.loads(txt) if txt else None
    except ValueError:
        js = None
    return r.status, js, r


def user(i, h, bal, **kw):
    d = {"id": "u_" + i, "email": i + "@example.com", "password": "correct horse",
         "display_name": i.title(), "handle": h, "balance": bal}
    d.update(kw)
    return d


def fixture(**kw):
    f = {"currency": "EUR", "minor_units": 2,
         "users": [user("ada", "ada", 10000), user("bob", "bob", 2500), user("cy", "cy", 500)]}
    f.update(kw)
    return f


def reset(f=None):
    s, _, _ = call("POST", "/_test/reset", f or fixture())
    assert s == 204, s


def login(email):
    s, b, _ = call("POST", "/auth/login", {"email": email, "password": "correct horse"})
    assert s == 200, (s, b)
    return b["token"]


def k():
    return uuid.uuid4().hex


class Base(unittest.TestCase):
    def setUp(self):
        reset(fixture(settlement_operator_ids=["u_cy"]))
        self.ada, self.bob, self.cy = (login(x + "@example.com") for x in ("ada", "bob", "cy"))

    def bal(self, t):
        return call("GET", "/me", token=t)[1]["balance"]

    def err(self, resp, status, code):
        s, b, _ = resp
        self.assertEqual((s, b and b.get("error", {}).get("code")), (status, code), b)


class TestBasics(Base):
    def test_health_headers_shapes(self):
        s, b, r = call("GET", "/health")
        self.assertEqual((s, b), (200, {"status": "ok"}))
        self.assertEqual(r.getheader("Content-Type"), "application/json; charset=utf-8")
        s, b, _ = call("GET", "/me", token=self.ada)
        self.assertEqual(b, {"user_id": "u_ada", "display_name": "Ada", "handle": "ada",
                             "balance": 10000, "currency": "EUR", "minor_units": 2})

    def test_unknown_route_and_auth(self):
        self.err(call("GET", "/nope"), 404, "not_found")
        self.err(call("GET", "/"), 404, "not_found")
        self.err(call("POST", "/me"), 405, "method_not_allowed")
        for m, p in (("GET", "/me"), ("GET", "/activity"), ("GET", "/requests"), ("POST", "/payments"),
                     ("POST", "/requests/x/decline"), ("POST", "/settlements"), ("POST", "/splits")):
            self.err(call(m, p, {}), 401, "unauthenticated")
        self.err(call("GET", "/me", headers={"Authorization": "Bearer nope"}), 401, "unauthenticated")
        self.err(call("GET", "/me", headers={"Authorization": "Bearer "}), 401, "unauthenticated")
        self.err(call("GET", "/me", headers={"Authorization": self.ada}), 401, "unauthenticated")

    def test_reset_semantics(self):
        reset(fixture(currency="JPY", minor_units=0))
        self.err(call("GET", "/me", token=self.ada), 401, "unauthenticated")
        t = login("ada@example.com")
        self.assertEqual(call("GET", "/me", token=t)[1]["currency"], "JPY")
        bad = fixture()
        bad["users"][0]["balance"] = -1
        self.err(call("POST", "/_test/reset", bad), 422, "validation_failed")
        self.assertEqual(self.bal(t), 10000)  # unchanged
        for mutate in (lambda f: f.update(minor_units=1),
                       lambda f: f["users"].append(dict(f["users"][0])),
                       lambda f: f["users"][0].update(handle="BAD"),
                       lambda f: f.update(payments=[{"id": "p", "from_user_id": "zz", "to_user_id": "u_bob",
                                                     "amount": 1}]),
                       lambda f: f.update(requests=[{"id": "r", "requester_id": "u_ada", "payer_id": "u_bob",
                                                     "amount": 1, "status": "weird"}]),
                       lambda f: f.update(settlement_operator_ids=["nobody"])):
            f = fixture()
            mutate(f)
            self.err(call("POST", "/_test/reset", f), 422, "validation_failed")
        self.err(call("POST", "/_test/reset", raw=b"{nope"), 400, "malformed_request")
        self.assertEqual(self.bal(t), 10000)

    def test_seeded_state(self):
        f = fixture(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
                               "note": "coffee", "visibility": "private"}],
                    requests=[{"id": "rq_%s" % s, "requester_id": "u_bob", "payer_id": "u_ada", "amount": 100,
                               "note": "n", "status": s} for s in ("pending", "paid", "declined", "cancelled")])
        reset(f)
        t = login("ada@example.com")
        self.assertEqual(self.bal(t), 10000)
        s, b, _ = call("GET", "/activity", token=t)
        p = b["payments"][0]
        self.assertEqual((p["payment_id"], p["request_id"], p["settlement_id"], p["from_handle"]),
                         ("p_1", None, None, "ada"))
        self.assertEqual(len(call("GET", "/requests", token=t)[1]["requests"]), 4)
        self.err(call("POST", "/requests/rq_paid/pay", {}, t, k()), 409, "request_not_pending")
        self.assertEqual(call("POST", "/requests/rq_pending/pay", {}, t, k())[0], 201)
        # private seeded payment hidden from third party; the later public payment is visible to all
        cy = login("cy@example.com")
        self.assertEqual([x["payment_id"] for x in call("GET", "/activity", token=cy)[1]["payments"]], ["p_2"])


class TestPayments(Base):
    def pay(self, t, body, key=None):
        return call("POST", "/payments", body, t, key or k())

    def test_happy_and_shape(self):
        s, b, _ = self.pay(self.ada, {"to_handle": "bob", "amount": 1500, "note": "dinner"})
        self.assertEqual(s, 201)
        self.assertEqual(set(b), {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
                                  "amount", "currency", "note", "visibility", "request_id", "settlement_id",
                                  "created_at"})
        self.assertEqual((b["visibility"], b["request_id"]), ("public", None))
        self.assertTrue(re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$", b["created_at"]))
        self.assertEqual((self.bal(self.ada), self.bal(self.bob)), (8500, 4000))

    def test_amounts(self):
        for a in (1.5, "100", True, None, 0, -1, 1000000001, [], {}):
            self.err(self.pay(self.ada, {"to_handle": "bob", "amount": a}), 422, "validation_failed")
        self.err(self.pay(self.ada, {"to_handle": "bob"}), 422, "validation_failed")
        self.assertEqual(self.pay(self.ada, {"to_handle": "bob", "amount": 1}, None)[0], 201)
        for raw in (b'{"to_handle":"bob","amount":1e3}', b'{"to_handle":"bob","amount":1000.0}'):
            s, b, _ = call("POST", "/payments", raw=raw, token=self.ada, key=k())
            self.assertEqual((s, b["amount"], type(b["amount"])), (201, 1000, int))
        self.err(call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1e9}', token=self.ada, key=k()),
                 409, "insufficient_funds")
        self.err(call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1e10}', token=self.ada, key=k()),
                 422, "validation_failed")

    def test_errors(self):
        self.err(self.pay(self.ada, {"to_handle": "ada", "amount": 1}), 422, "self_payment")
        self.err(self.pay(self.ada, {"to_handle": "zed", "amount": 1}), 404, "not_found")
        for h in ("", "ADA", "@ada"):
            self.err(self.pay(self.ada, {"to_handle": h, "amount": 1}), 404, "not_found")
        self.err(self.pay(self.ada, {"to_handle": 5, "amount": 1}), 400, "malformed_request")
        self.err(self.pay(self.ada, {"amount": 1}), 422, "validation_failed")
        self.err(self.pay(self.ada, {"to_handle": "bob", "amount": 1, "note": None}), 422, "validation_failed")
        self.err(self.pay(self.ada, {"to_handle": "bob", "amount": 1, "note": 5}), 422, "validation_failed")
        for v in ("PUBLIC", "", None, 1, "friends"):
            self.err(self.pay(self.ada, {"to_handle": "bob", "amount": 1, "visibility": v}), 422,
                     "validation_failed")
        self.err(call("POST", "/payments", raw=b"{bad", token=self.ada, key=k()), 400, "malformed_request")
        self.err(call("POST", "/payments", raw=b"[]", token=self.ada, key=k()), 400, "malformed_request")
        self.err(call("POST", "/payments", raw=b"\xff\xfe", token=self.ada, key=k()), 400, "malformed_request")
        self.err(call("POST", "/payments", raw=b"", token=self.ada, key=k()), 400, "malformed_request")
        self.err(self.pay(self.cy, {"to_handle": "bob", "amount": 501}), 409, "insufficient_funds")
        self.assertEqual(self.pay(self.cy, {"to_handle": "bob", "amount": 500})[0], 201)
        self.assertEqual(self.bal(self.cy), 0)
        self.assertEqual(len(call("GET", "/activity", token=self.cy)[1]["payments"]), 1)

    def test_note(self):
        self.assertEqual(self.pay(self.ada, {"to_handle": "bob", "amount": 1, "note": "x" * 200})[0], 201)
        self.err(self.pay(self.ada, {"to_handle": "bob", "amount": 1, "note": "x" * 201}), 422, "validation_failed")
        self.assertEqual(self.pay(self.ada, {"to_handle": "bob", "amount": 1, "note": "😀" * 200})[0], 201)
        self.err(self.pay(self.ada, {"to_handle": "bob", "amount": 1, "note": "😀" * 201}), 422, "validation_failed")
        n = '  <script>"é' + "e\u0301" + "\u00a0 "
        s, b, _ = self.pay(self.ada, {"to_handle": "bob", "amount": 1, "note": n})
        self.assertEqual(b["note"], n)
        self.assertEqual(call("GET", "/activity", token=self.bob)[1]["payments"][0]["note"], n)

    def test_idempotency(self):
        key = k()
        body = {"to_handle": "bob", "amount": 100}
        s1, b1, _ = self.pay(self.ada, body, key)
        s2, b2, _ = self.pay(self.ada, {"amount": 100.0, "to_handle": "bob"}, key)
        self.assertEqual((s1, s2, b1), (201, 200, b2))
        self.assertEqual(self.bal(self.ada), 9900)
        self.err(self.pay(self.ada, {"to_handle": "bob", "amount": 101}, key), 409, "idempotency_key_reuse")
        self.err(self.pay(self.ada, {"to_handle": "bob", "amount": -5}, key), 409, "idempotency_key_reuse")
        # other user, same key
        self.assertEqual(self.pay(self.bob, body | {"to_handle": "ada"}, key)[0], 201)
        # different path same key
        self.assertEqual(call("POST", "/requests", {"payer_handle": "bob", "amount": 100}, self.ada, key)[0], 201)
        # missing / empty / long key
        self.err(call("POST", "/payments", body, self.ada), 400, "missing_idempotency_key")
        self.err(call("POST", "/payments", body, self.ada, ""), 400, "missing_idempotency_key")
        self.err(self.pay(self.ada, body, "x" * 256), 422, "validation_failed")
        self.assertEqual(self.pay(self.ada, body, "x" * 255)[0], 201)
        # failure doesn't claim key
        k2 = k()
        self.err(self.pay(self.cy, {"to_handle": "bob", "amount": 600}, k2), 409, "insufficient_funds")
        self.pay(self.ada, {"to_handle": "cy", "amount": 200})
        self.assertEqual(self.pay(self.cy, {"to_handle": "bob", "amount": 600}, k2)[0], 201)
        # replay after state change
        self.assertEqual(self.pay(self.cy, {"to_handle": "bob", "amount": 600}, k2)[0], 200)

    def test_concurrent_overdraft_and_replay(self):
        res = []

        def go(key):
            res.append(self.pay(self.cy, {"to_handle": "bob", "amount": 500}, key)[0])
        ts = [threading.Thread(target=go, args=(k(),)) for _ in range(50)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual((res.count(201), res.count(409)), (1, 49))
        key = k()
        res.clear()
        ts = [threading.Thread(target=go, args=(key,)) for _ in range(1)]
        res2 = []

        def go2():
            res2.append(self.pay(self.ada, {"to_handle": "bob", "amount": 7}, key)[0])
        ts = [threading.Thread(target=go2) for _ in range(50)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual((res2.count(201), res2.count(200)), (1, 49))
        self.assertEqual(self.bal(self.ada) + self.bal(self.bob) + self.bal(self.cy), 13000)


class TestRequests(Base):
    def ask(self, t, body, key=None):
        return call("POST", "/requests", body, t, key or k())

    def test_lifecycle(self):
        s, r, _ = self.ask(self.bob, {"payer_handle": "ada", "amount": 1200, "note": "taxi"})
        self.assertEqual(s, 201)
        self.assertEqual((r["status"], r["payment_id"], r["requester_handle"], r["payer_handle"]),
                         ("pending", None, "bob", "ada"))
        rid = r["request_id"]
        self.err(call("POST", "/requests/%s/pay" % rid, {}, self.bob, k()), 403, "forbidden")
        self.err(call("POST", "/requests/%s/pay" % rid, {}, self.cy, k()), 403, "forbidden")
        self.err(call("POST", "/requests/nope/pay", {}, self.ada, k()), 404, "not_found")
        self.err(call("POST", "/requests/%s/cancel" % rid, None, self.ada), 403, "forbidden")
        self.err(call("POST", "/requests/%s/decline" % rid, None, self.bob), 403, "forbidden")
        self.err(call("POST", "/requests/%s/pay" % rid, {"visibility": "x"}, self.ada, k()), 422, "validation_failed")
        key = k()
        s, p, _ = call("POST", "/requests/%s/pay" % rid, raw=b"", token=self.ada, key=key)
        self.assertEqual((s, p["request_id"], p["amount"], p["visibility"]), (201, rid, 1200, "public"))
        self.assertEqual(call("POST", "/requests/%s/pay" % rid, {}, self.ada, key)[0], 200)
        self.err(call("POST", "/requests/%s/pay" % rid, {"visibility": "public"}, self.ada, key), 409,
                 "idempotency_key_reuse")
        self.err(call("POST", "/requests/%s/pay" % rid, {}, self.ada, k()), 409, "request_not_pending")
        self.err(call("POST", "/requests/%s/cancel" % rid, None, self.bob), 409, "request_not_pending")
        self.err(call("POST", "/requests/%s/decline" % rid, None, self.ada), 409, "request_not_pending")
        got = call("GET", "/requests", token=self.bob)[1]["requests"][0]
        self.assertEqual((got["status"], got["payment_id"]), ("paid", p["payment_id"]))

    def test_short_then_funded_decline_cancel(self):
        rid = self.ask(self.ada, {"payer_handle": "cy", "amount": 900})[1]["request_id"]
        self.err(call("POST", "/requests/%s/pay" % rid, {}, self.cy, k()), 409, "insufficient_funds")
        self.assertEqual(self.bal(self.cy), 500)
        call("POST", "/payments", {"to_handle": "cy", "amount": 400}, self.ada, k())
        self.assertEqual(call("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, self.cy, k())[0], 201)
        r2 = self.ask(self.ada, {"payer_handle": "cy", "amount": 5})[1]["request_id"]
        self.assertEqual(call("POST", "/requests/%s/decline" % r2, None, self.cy)[1]["status"], "declined")
        self.assertEqual(call("POST", "/requests/%s/decline" % r2, None, self.cy)[0], 200)
        self.err(call("POST", "/requests/%s/cancel" % r2, None, self.ada), 409, "request_not_pending")
        r3 = self.ask(self.ada, {"payer_handle": "cy", "amount": 5})[1]["request_id"]
        self.assertEqual(call("POST", "/requests/%s/cancel" % r3, None, self.ada)[1]["status"], "cancelled")
        self.assertEqual(call("POST", "/requests/%s/cancel" % r3, None, self.ada)[0], 200)

    def test_create_errors(self):
        self.err(self.ask(self.ada, {"payer_handle": "ada", "amount": 5}), 422, "self_request")
        self.err(self.ask(self.ada, {"payer_handle": "zz", "amount": 5}), 404, "not_found")
        self.err(self.ask(self.ada, {"payer_handle": "bob", "amount": 0}), 422, "validation_failed")
        self.err(self.ask(self.ada, {"payer_handle": "bob", "amount": 5, "note": "x" * 201}), 422, "validation_failed")
        self.err(self.ask(self.ada, {"payer_handle": 3, "amount": 5}), 400, "malformed_request")
        self.assertEqual(self.ask(self.ada, {"payer_handle": "cy", "amount": 99999999})[0], 201)

    def test_race(self):
        rid = self.ask(self.bob, {"payer_handle": "ada", "amount": 1000})[1]["request_id"]
        out = []

        def pay():
            out.append(("pay", call("POST", "/requests/%s/pay" % rid, {}, self.ada, k())[0]))

        def can():
            out.append(("can", call("POST", "/requests/%s/cancel" % rid, None, self.bob)[0]))

        def dec():
            out.append(("dec", call("POST", "/requests/%s/decline" % rid, None, self.ada)[0]))
        ts = [threading.Thread(target=f) for f in [pay, can, dec] * 10]
        [t.start() for t in ts]
        [t.join() for t in ts]
        status = call("GET", "/requests", token=self.bob)[1]["requests"][0]["status"]
        moved = self.bal(self.bob) - 2500
        self.assertEqual(moved, 1000 if status == "paid" else 0)
        wins = {n for n, s in out if s in (200, 201)}
        self.assertEqual(len(wins), 1, out)

    def test_list(self):
        for i in range(5):
            self.ask(self.bob, {"payer_handle": "ada", "amount": 10 + i})
        self.ask(self.ada, {"payer_handle": "cy", "amount": 3})
        s, b, _ = call("GET", "/requests?limit=2", token=self.ada)
        self.assertEqual((len(b["requests"]), b["has_more"]), (2, True))
        s, b, _ = call("GET", "/requests?direction=incoming", token=self.ada)
        self.assertEqual([r["amount"] for r in b["requests"]], [14, 13, 12, 11, 10])
        s, b, _ = call("GET", "/requests?direction=outgoing&limit=1&unknown=1", token=self.ada)
        self.assertEqual(b["requests"][0]["amount"], 3)
        s, b, _ = call("GET", "/requests?limit=3&offset=3", token=self.ada)
        self.assertEqual((len(b["requests"]), b["has_more"]), (3, False))
        s, b, _ = call("GET", "/requests?limit=6", token=self.ada)
        self.assertEqual((len(b["requests"]), b["has_more"]), (6, False))
        s, b, _ = call("GET", "/requests?offset=99", token=self.ada)
        self.assertEqual((b["requests"], b["has_more"]), ([], False))
        self.assertEqual(call("GET", "/requests", token=self.cy)[1]["requests"][0]["amount"], 3)
        for q in ("limit=0", "limit=201", "limit=1e2", "limit=4.0", "limit=+4", "limit=-1", "limit=abc",
                  "limit=", "offset=-1", "offset=1.0", "direction=x", "status=nope"):
            self.err(call("GET", "/requests?" + q, token=self.ada), 422, "validation_failed")
        for q in ("limit=1", "limit=200", "status=pending", "status=cancelled", "offset=0"):
            self.assertEqual(call("GET", "/requests?" + q, token=self.ada)[0], 200)
        # operator isolation
        self.assertEqual(call("GET", "/requests", token=self.cy)[1]["requests"][0]["amount"], 3)
        self.assertEqual(len(call("GET", "/requests", token=self.cy)[1]["requests"]), 1)


class TestSplits(Base):
    def split(self, t, body, key=None):
        return call("POST", "/splits", body, t, key or k())

    def test_rounding_table(self):
        reset(fixture(users=[user("u%d" % i, "u%d" % i, 0) for i in range(5)] + [user("ada", "ada", 10)]))
        t = login("ada@example.com")
        for amount, n, exp in ((1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
                               (999, 3, [333, 333, 333]), (5, 5, [1] * 5)):
            hs = ["u%d" % i for i in range(n)]
            s, b, _ = self.split(t, {"amount": amount, "participant_handles": hs})
            self.assertEqual((s, [x["amount"] for x in b["shares"]]), (201, exp))
            self.assertEqual([r["amount"] for r in b["requests"]], exp)
        s, b, _ = self.split(t, {"amount": 10, "participant_handles": ["u2", "u1", "u0"]})
        self.assertEqual([(x["handle"], x["amount"]) for x in b["shares"]], [("u2", 4), ("u1", 3), ("u0", 3)])

    def test_shape_and_caller(self):
        s, b, _ = self.split(self.ada, {"amount": 3000, "participant_handles": ["ada", "bob", "cy"], "note": "d"})
        self.assertEqual(s, 201)
        self.assertEqual([x["handle"] for x in b["shares"]], ["ada", "bob", "cy"])
        self.assertEqual([r["payer_handle"] for r in b["requests"]], ["bob", "cy"])
        self.assertTrue(all(r["requester_handle"] == "ada" and r["status"] == "pending" and r["note"] == "d"
                            for r in b["requests"]))
        s, b, _ = self.split(self.ada, {"amount": 10, "participant_handles": ["bob", "cy"]})
        self.assertEqual([x["amount"] for x in b["shares"]], [5, 5])
        s, b, _ = self.split(self.ada, {"amount": 10, "participant_handles": ["ada"]})
        self.assertEqual((s, b["requests"], b["shares"]), (201, [], [{"handle": "ada", "amount": 10}]))
        s, b, _ = self.split(self.ada, {"amount": 1, "participant_handles": ["bob", "cy"]})
        self.assertEqual([r["amount"] for r in b["requests"]], [1, 0])
        zero = b["requests"][1]["request_id"]
        self.assertEqual(call("POST", "/requests/%s/pay" % zero, {}, self.cy, k())[1]["amount"], 0)
        self.assertEqual(len(call("GET", "/activity", token=self.bob)[1]["payments"]), 1)

    def test_errors(self):
        for body, st, code in (
                ({"amount": 0, "participant_handles": ["bob"]}, 422, "validation_failed"),
                ({"amount": 5, "participant_handles": []}, 422, "validation_failed"),
                ({"amount": 5}, 422, "validation_failed"),
                ({"amount": 5, "participant_handles": ["bob", "bob"]}, 422, "validation_failed"),
                ({"amount": 5, "participant_handles": ["bob"], "note": "x" * 201}, 422, "validation_failed"),
                ({"amount": 5, "participant_handles": ["bob", "zz"]}, 404, "not_found"),
                ({"amount": 5, "participant_handles": "bob"}, 400, "malformed_request"),
                ({"amount": 5, "participant_handles": [1]}, 400, "malformed_request"),
                ({"amount": 5, "participant_handles": ["zz", "bob", "bob"]}, 422, "validation_failed")):
            self.err(self.split(self.ada, body), st, code)
        self.assertEqual(call("GET", "/requests", token=self.bob)[1]["requests"], [])

    def test_idem(self):
        key = k()
        body = {"amount": 10, "participant_handles": ["bob", "cy"]}
        a = self.split(self.ada, body, key)
        b = self.split(self.ada, body, key)
        self.assertEqual((a[0], b[0], a[1]), (201, 200, b[1]))
        self.assertEqual(len(call("GET", "/requests", token=self.bob)[1]["requests"]), 1)
        self.err(self.split(self.ada, {"amount": 11, "participant_handles": ["bob"]}, key), 409,
                 "idempotency_key_reuse")


class TestFeed(Base):
    def test_visibility(self):
        call("POST", "/payments", {"to_handle": "bob", "amount": 1, "visibility": "private"}, self.ada, k())
        call("POST", "/payments", {"to_handle": "bob", "amount": 2}, self.ada, k())
        n = lambda t: [p["amount"] for p in call("GET", "/activity", token=t)[1]["payments"]]
        self.assertEqual((n(self.ada), n(self.bob), n(self.cy)), ([2, 1], [2, 1], [2]))
        s, b, _ = call("GET", "/activity?limit=1&offset=1", token=self.ada)
        self.assertEqual(([p["amount"] for p in b["payments"]], b["has_more"]), ([1], False))
        self.err(call("GET", "/activity?limit=0", token=self.ada), 422, "validation_failed")
        self.err(call("GET", "/activity?offset=x", token=self.ada), 422, "validation_failed")


class TestAuth(Base):
    def signup(self, **kw):
        b = {"email": "new@example.com", "password": "correct horse", "display_name": "New"}
        b.update(kw)
        return call("POST", "/auth/signup", b)

    def test_signup_login(self):
        s, b, _ = self.signup(email="Jo.Anne+x@ex.com")
        self.assertEqual((s, set(b)), (201, {"user_id", "display_name", "token"}))
        me = call("GET", "/me", token=b["token"])[1]
        self.assertEqual((me["handle"], me["balance"]), ("jo_anne_x", 0))
        s, b2, _ = self.signup(email="a" * 30 + "@ex.com")
        self.assertEqual(call("GET", "/me", token=b2["token"])[1]["handle"], "a" * 20)
        self.err(self.signup(email="jo.anne+x@ex.com"), 409, "email_taken")
        self.err(self.signup(email="jo_anne_x@other.com"), 409, "handle_taken")
        self.err(call("POST", "/auth/login", {"email": "jo_anne_x@other.com", "password": "correct horse"}),
                 401, "unauthenticated")
        self.assertEqual(self.signup(email="jo_anne_x@other.com", display_name="z")[0], 409)
        self.err(self.signup(email="ada@other.com"), 409, "handle_taken")
        self.err(self.signup(password="1234567"), 422, "validation_failed")
        self.assertEqual(self.signup(email="p8@e.com", password="12345678")[0], 201)
        for e in ("nope", "@x.com", "a@", ""):
            self.err(self.signup(email=e), 422, "validation_failed")
        self.err(call("POST", "/auth/signup", {"email": "q@e.com", "password": "12345678"}), 422, "validation_failed")
        self.err(self.signup(email=5), 400, "malformed_request")
        # new user receives money and requests immediately
        t = call("POST", "/auth/login", {"email": "p8@e.com", "password": "12345678"})[1]["token"]
        self.assertEqual(call("POST", "/payments", {"to_handle": "p8", "amount": 5}, self.ada, k())[0], 201)
        self.assertEqual(call("POST", "/requests", {"payer_handle": "p8", "amount": 5}, self.ada, k())[0], 201)
        self.assertEqual(call("GET", "/me", token=t)[1]["balance"], 5)

    def test_login(self):
        a = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
        b = call("POST", "/auth/login", {"email": "ADA@example.com", "password": "correct horse"})
        self.assertEqual((a[0], b[0]), (200, 200))
        self.assertNotEqual(a[1]["token"], b[1]["token"])
        self.assertEqual(call("GET", "/me", token=a[1]["token"])[0], 200)
        self.assertEqual(call("GET", "/me", token=self.ada)[0], 200)
        self.err(call("POST", "/auth/login", {"email": "ada@example.com", "password": "wrong"}), 401, "unauthenticated")
        self.err(call("POST", "/auth/login", {"email": "x@example.com", "password": "correct horse"}), 401,
                 "unauthenticated")

    def test_perf_many_users(self):
        reset(fixture(users=[user("m%d" % i, "m%d" % i, 10) for i in range(300)]))
        res, t0 = [], time.time()

        def go(i):
            res.append(call("POST", "/auth/login", {"email": "m%d@example.com" % i, "password": "correct horse"})[0])
        ts = [threading.Thread(target=go, args=(i,)) for i in range(50)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(res, [200] * 50)
        self.assertLess(time.time() - t0, 5)

    def test_export_has_no_plaintext(self):
        s, b, r = call("GET", "/_test/export")
        self.assertNotIn("correct horse", json.dumps(b))


class TestSettlements(Base):
    def st(self, t, transfers, key=None, **kw):
        return call("POST", "/settlements", dict(transfers=transfers, **kw), t, key or k())

    def tr(self, f, t, a, **kw):
        return dict(from_handle=f, to_handle=t, amount=a, **kw)

    def test_auth_and_shape(self):
        self.err(call("POST", "/settlements", {"transfers": []}), 401, "unauthenticated")
        self.err(self.st(self.ada, [self.tr("ada", "bob", 1)]), 403, "forbidden")
        self.err(call("POST", "/settlements", {"transfers": [self.tr("ada", "bob", 1)]}, self.cy),
                 400, "missing_idempotency_key")
        for tr in ([], [self.tr("ada", "bob", 1)] * 33, "x", None, [1], [{"from_handle": "ada"}]):
            self.err(self.st(self.cy, tr), 422, "validation_failed")
        self.assertEqual(self.st(self.cy, [self.tr("ada", "bob", 1)] * 32)[0], 201)
        self.err(self.st(self.cy, [self.tr("ada", "ada", 1)]), 422, "self_payment")
        self.err(self.st(self.cy, [self.tr("ada", "zz", 1)]), 404, "not_found")
        # entry errors in input order, before insufficient funds
        self.err(self.st(self.cy, [self.tr("ada", "bob", 10 ** 9), self.tr("ada", "ada", 1), self.tr("a", "zz", 1)]),
                 422, "self_payment")
        self.err(self.st(self.cy, [self.tr("ada", "bob", 10 ** 9), self.tr("ada", "zz", 1), self.tr("ada", "ada", 1)]),
                 404, "not_found")
        self.err(self.st(self.cy, [self.tr("ada", "bob", 0)]), 422, "validation_failed")

    def test_net_and_atomic(self):
        reset(fixture(users=[user("ada", "ada", 100), user("bob", "bob", 0), user("cy", "cy", 0)],
                      settlement_operator_ids=["u_cy"]))
        ada, bob, cy = (login(x + "@example.com") for x in ("ada", "bob", "cy"))
        key = k()
        s, b, _ = self.st(cy, [self.tr("ada", "bob", 100), self.tr("bob", "cy", 100, visibility="private", note="n")], key)
        self.assertEqual(s, 201)
        self.assertEqual([self.bal(t) for t in (ada, bob, cy)], [0, 0, 100])
        self.assertEqual(set(b), {"settlement_id", "committed_at", "payments"})
        ps = b["payments"]
        self.assertEqual([p["amount"] for p in ps], [100, 100])
        self.assertTrue(all(p["settlement_id"] == b["settlement_id"] and p["request_id"] is None and
                            p["created_at"] == b["committed_at"] for p in ps))
        self.assertEqual(ps[1]["visibility"], "private")
        self.assertEqual(self.st(cy, [self.tr("ada", "bob", 100), self.tr("bob", "cy", 100, visibility="private",
                                                                      note="n")], key)[1], b)
        # operator doesn't see private payment unless party; here cy is receiver
        # unaffordable: nothing happens, key reusable
        k3 = k()
        self.err(self.st(cy, [self.tr("bob", "ada", 11), self.tr("cy", "bob", 10)], k3), 409, "insufficient_funds")
        self.assertEqual([self.bal(t) for t in (ada, bob, cy)], [0, 0, 100])
        self.assertEqual(len(call("GET", "/activity", token=ada)[1]["payments"]), 1)
        self.assertEqual(self.st(cy, [self.tr("cy", "bob", 10)], k3)[0], 201)
        # ordinary payments expose settlement_id null
        p = call("POST", "/payments", {"to_handle": "ada", "amount": 1}, bob, k())[1]
        self.assertIsNone(p["settlement_id"])

    def test_operator_isolation(self):
        self.st(self.cy, [self.tr("ada", "bob", 5, visibility="private")])
        feed = call("GET", "/activity", token=self.cy)[1]["payments"]
        self.assertEqual(feed, [])
        call("POST", "/requests", {"payer_handle": "bob", "amount": 1}, self.ada, k())
        self.assertEqual(call("GET", "/requests", token=self.cy)[1]["requests"], [])
        rid = call("GET", "/requests", token=self.ada)[1]["requests"][0]["request_id"]
        self.err(call("POST", "/requests/%s/cancel" % rid, None, self.cy), 403, "forbidden")

    def test_concurrent(self):
        out = []

        def go():
            out.append(self.st(self.cy, [self.tr("cy", "bob", 300)])[0])
        ts = [threading.Thread(target=go) for _ in range(20)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual((out.count(201), out.count(409)), (1, 19))
        self.assertEqual(sum(self.bal(t) for t in (self.ada, self.bob, self.cy)), 13000)


class TestExportImport(Base):
    def test_roundtrip(self):
        call("POST", "/payments", {"to_handle": "bob", "amount": 5, "note": "é😀 "}, self.ada, "kk1")
        rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 9}, self.bob, "kk2")[1]["request_id"]
        call("POST", "/splits", {"amount": 5, "participant_handles": ["bob", "cy"]}, self.ada, "kk3")
        call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]},
             self.cy, "kk4")
        call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 9}, self.ada, "failed")
        reads = lambda: [call("GET", p, token=t)[1] for t in (self.ada, self.bob, self.cy)
                         for p in ("/me", "/activity", "/requests")]
        before = reads()
        s, exp, _ = call("GET", "/_test/export")
        self.assertEqual((s, exp["track"], exp["format_version"]), (200, "pocketful", 1))
        call("POST", "/payments", {"to_handle": "bob", "amount": 7}, self.ada, k())
        self.assertEqual(call("POST", "/_test/import", exp)[0], 204)
        self.assertEqual(call("POST", "/_test/import", exp)[0], 204)
        self.assertEqual(reads(), before)
        s, b, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 5, "note": "é😀 "}, self.ada, "kk1")
        self.assertEqual(s, 200)
        self.err(call("POST", "/payments", {"to_handle": "bob", "amount": 6}, self.ada, "kk1"), 409,
                 "idempotency_key_reuse")
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, self.ada, "failed")[0], 201)
        self.assertEqual(call("POST", "/requests/%s/pay" % rid, {}, self.ada, k())[0], 201)
        self.assertEqual(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob",
                                                                      "amount": 1}]}, self.cy, "kk4")[0], 200)
        self.assertEqual(login("ada@example.com") is not None, True)
        # fresh import replaces everything
        reset(fixture(currency="JPY", minor_units=0))
        self.err(call("GET", "/me", token=self.ada), 401, "unauthenticated")
        call("POST", "/_test/import", exp)
        self.assertEqual(call("GET", "/me", token=self.ada)[1]["currency"], "EUR")
        reset()
        self.err(call("GET", "/me", token=self.ada), 401, "unauthenticated")

    def test_import_errors(self):
        exp = call("GET", "/_test/export")[1]
        self.err(call("POST", "/_test/import", raw=b"{x"), 400, "malformed_request")
        bads = [{}, {k_: v for k_, v in exp.items() if k_ != "state"}, dict(exp, track="x"),
                dict(exp, format_version=2), dict(exp, state={}), dict(exp, state=[]),
                dict(exp, state=dict(exp["state"], users="x")),
                dict(exp, state=dict(exp["state"], tokens={"t": "nobody"}))]
        for b in bads:
            self.err(call("POST", "/_test/import", b), 422, "validation_failed")
        self.assertEqual(call("GET", "/me", token=self.ada)[0], 200)


class TestHostile(Base):
    def test_no_5xx(self):
        cases = [("POST", "/payments", b"[" * 100000), ("POST", "/payments", b'{"a":' * 5000),
                 ("POST", "/payments", b'{"to_handle":"bob","amount":1e999}'),
                 ("POST", "/payments", b'{"to_handle":"bob","amount":' + b"9" * 6000 + b"}"),
                 ("POST", "/payments", b'{"to_handle":"bob","amount":NaN}'),
                 ("POST", "/splits", json.dumps({"amount": 5, "participant_handles": ["h%d" % i for i in range(1000)]}).encode()),
                 ("POST", "/payments", b'{"to_handle":"\\ud800","amount":1}'),
                 ("POST", "/payments", b'{"to_handle":"bob","amount":1,"note":"\\ud800"}')]
        for m, p, raw in cases:
            s, b, _ = call(m, p, raw=raw, token=self.ada, key=k())
            self.assertLess(s, 500, (p, raw[:30], s))
        s, _, _ = call("GET", "/requests?limit=" + "9" * 5000, token=self.ada)
        self.assertEqual(s, 422)
        s, _, _ = call("GET", "/activity?offset=" + "9" * 5000, token=self.ada)
        self.assertLess(s, 500)
        s, b, _ = call("GET", "/me", token=self.ada, headers={"Idempotency-Key": "é"})
        self.assertEqual(s, 200)


class TestExactNumbers(Base):
    def test_literals(self):
        for lit in ("1.0000000000000001", "100.00000000000000001", "0.99999999999999999",
                    "999999999.99999999", "1000000000.00000001", "1e309", "1e400", "-1e400", "9" * 5000):
            for path, body in (("/payments", '{"to_handle":"bob","amount":%s}'),
                               ("/requests", '{"payer_handle":"bob","amount":%s}'),
                               ("/splits", '{"participant_handles":["bob"],"amount":%s}'),
                               ("/settlements", '{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":%s}]}')):
                t = self.cy if path == "/settlements" else self.ada
                self.err(call("POST", path, raw=(body % lit).encode(), token=t, key=k()), 422, "validation_failed")
        self.assertEqual(self.bal(self.ada), 10000)
        s, b, _ = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":5,"zzz":1e400}', token=self.ada, key=k())
        self.assertEqual(s, 201)
        s, b, _ = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1.000,"note":"x"}', token=self.ada, key=k())
        self.assertEqual((s, b["amount"]), (201, 1))

    def test_replay_equivalence_and_import(self):
        key = k()
        a = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":100,"x":1e400}', token=self.ada, key=key)
        b = call("POST", "/payments", raw=b'{"x":1E+400,"amount":1e2,"to_handle":"bob"}', token=self.ada, key=key)
        self.assertEqual((a[0], b[0], a[1]), (201, 200, b[1]))
        exp = call("GET", "/_test/export")[1]
        call("POST", "/_test/import", exp)
        c = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":100.0,"x":1e400}', token=self.ada, key=key)
        self.assertEqual((c[0], c[1]), (200, a[1]))
        self.err(call("POST", "/payments", raw=b'{"to_handle":"bob","amount":101,"x":1e400}', token=self.ada, key=key),
                 409, "idempotency_key_reuse")

    def test_deep_and_key_chars(self):
        key = k()
        call("POST", "/payments", {"to_handle": "bob", "amount": 1}, self.ada, key)
        deep = b'{"to_handle":"bob","amount":1,"z":' + b"[" * 600 + b"]" * 600 + b"}"
        s = call("POST", "/payments", raw=deep, token=self.ada, key=key)[0]
        self.assertLess(s, 500)
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, self.ada, "é" * 128)[0], 201)
        self.assertEqual(call("GET", "/activity?offset=" + "9" * 30, token=self.ada)[0], 200)


class TestBigNumbers(Base):
    def test_near_2_53(self):
        big = 2 ** 53 - 1
        reset(fixture(users=[user("ada", "ada", big), user("bob", "bob", 0)]))
        ada = login("ada@example.com")
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 9}, ada, k())[0], 201)
        self.assertEqual(call("GET", "/me", token=ada)[1]["balance"], big - 10 ** 9)


if __name__ == "__main__":
    unittest.main(verbosity=1)
