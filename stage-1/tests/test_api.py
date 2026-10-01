"""Own tests written from the stage-1 specification. Run against a live service:
BASE_URL=http://localhost:8080 python3 -m unittest discover -s tests -v
"""
import json
import os
import re
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.environ.get("BASE_URL", "http://localhost:8080")
TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$")
_n = [0]
_lock = threading.Lock()


def key():
    with _lock:
        _n[0] += 1
        return "k-%d-%d" % (os.getpid(), _n[0])


def call(method, path, body=None, token=None, headers=None, raw=None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            b = r.read()
            return r.status, (json.loads(b) if b else None), r
    except urllib.error.HTTPError as e:
        b = e.read()
        return e.code, (json.loads(b) if b else None), e


def U(i, handle, bal, email=None):
    return {"id": "u_" + i, "email": email or handle + "@example.com",
            "password": "correct horse", "display_name": handle.title(),
            "handle": handle, "balance": bal}


FIX = {"currency": "EUR", "minor_units": 2,
       "users": [U("ada", "ada", 10000), U("bob", "bob", 2500), U("cy", "cy", 0)],
       "payments": [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                     "amount": 500, "note": "coffee", "visibility": "public"},
                    {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_bob",
                     "amount": 100, "note": "secret", "visibility": "private"}],
       "requests": [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
                     "amount": 1200, "note": "taxi", "status": "pending"}],
       "settlement_operator_ids": ["u_cy"]}


def reset(fx=None):
    s, b, _ = call("POST", "/_test/reset", fx or FIX)
    assert s == 204, (s, b)


def login(email):
    s, b, _ = call("POST", "/auth/login", {"email": email, "password": "correct horse"})
    assert s == 200, b
    return b["token"]


class Base(unittest.TestCase):
    def setUp(self):
        reset()
        self.ada, self.bob, self.cy = (login(h + "@example.com") for h in ("ada", "bob", "cy"))

    def err(self, resp, status, code):
        s, b, _ = resp
        self.assertEqual(s, status, b)
        self.assertEqual(b["error"]["code"], code)

    def pay(self, tok, body, k=None, expect=201):
        s, b, _ = call("POST", "/payments", body, tok, {"Idempotency-Key": k or key()})
        self.assertEqual(s, expect, b)
        return b

    def bal(self, tok):
        return call("GET", "/me", token=tok)[1]["balance"]

    def total(self):
        return sum(self.bal(t) for t in (self.ada, self.bob, self.cy))


class Runtime(Base):
    def test_health_and_headers(self):
        s, b, r = call("GET", "/health")
        self.assertEqual((s, b), (200, {"status": "ok"}))
        self.assertEqual(r.headers["Content-Type"], "application/json; charset=utf-8")
        s, b, r = call("GET", "/nope")
        self.assertEqual(s, 404)
        self.assertEqual(b["error"]["code"], "not_found")
        self.assertEqual(r.headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(call("GET", "/")[0], 404)
        self.assertEqual(call("GET", "/authorizations", token=self.ada)[0], 404)
        self.assertIn(call("DELETE", "/me", token=self.ada)[0], (404, 405))

    def test_reset_semantics(self):
        s, b, r = call("POST", "/_test/reset", FIX)
        self.assertEqual((s, b), (204, None))
        self.assertEqual(call("GET", "/me", token=self.ada)[0], 401)
        self.assertEqual(self.bal(login("ada@example.com")), 10000)
        self.err(call("POST", "/_test/reset", raw=b"{nope"), 400, "malformed_request")
        bad = json.loads(json.dumps(FIX))
        bad["users"][0]["balance"] = -1
        self.err(call("POST", "/_test/reset", bad), 422, "validation_failed")
        self.assertEqual(self.bal(login("ada@example.com")), 10000)  # untouched
        for mu, cur in ((0, "JPY"), (3, "BHD")):
            fx = dict(FIX, currency=cur, minor_units=mu)
            reset(fx)
            me = call("GET", "/me", token=login("ada@example.com"))[1]
            self.assertEqual((me["currency"], me["minor_units"]), (cur, mu))
        self.err(call("POST", "/_test/reset", dict(FIX, minor_units=1)), 422, "validation_failed")

    def test_seeded_state(self):
        me = call("GET", "/me", token=self.ada)[1]
        self.assertEqual(me, {"user_id": "u_ada", "display_name": "Ada", "handle": "ada",
                              "balance": 10000, "currency": "EUR", "minor_units": 2})
        feed = call("GET", "/activity", token=self.cy)[1]["payments"]
        self.assertEqual([p["payment_id"] for p in feed], ["p_1"])
        p = feed[0]
        self.assertIsNone(p["request_id"])
        self.assertIsNone(p["settlement_id"])
        self.assertRegex(p["created_at"], TS)
        both = call("GET", "/activity", token=self.bob)[1]["payments"]
        self.assertEqual({p["payment_id"] for p in both}, {"p_1", "p_2"})
        rq = call("GET", "/requests", token=self.ada)[1]["requests"]
        self.assertEqual(rq[0]["request_id"], "rq_1")
        self.assertEqual(call("GET", "/requests", token=self.cy)[1]["requests"], [])
        self.assertEqual(call("POST", "/requests/rq_1/cancel", token=self.bob)[1]["status"], "cancelled")


class Auth(Base):
    def test_signup_login(self):
        s, b, _ = call("POST", "/auth/signup", {"email": "Dee.Ann+tag@x.org",
                                                 "password": "longenough", "display_name": "Dee", "handle": "zzz"})
        self.assertEqual(s, 201)
        self.assertEqual(set(b), {"user_id", "display_name", "token"})
        me = call("GET", "/me", token=b["token"])[1]
        self.assertEqual((me["handle"], me["balance"]), ("dee_ann_tag", 0))
        s, b2, _ = call("POST", "/auth/login", {"email": "Dee.Ann+tag@x.org", "password": "longenough"})
        self.assertEqual(s, 200)
        self.assertNotEqual(b2["token"], b["token"])
        self.assertEqual(call("GET", "/me", token=b["token"])[0], 200)
        self.assertEqual(call("GET", "/me", token=b2["token"])[0], 200)
        self.err(call("POST", "/auth/signup", {"email": "Dee.Ann+tag@x.org", "password": "longenough",
                                               "display_name": "D"}), 409, "email_taken")
        self.err(call("POST", "/auth/signup", {"email": "dee.ann_tag@x.org", "password": "longenough",
                                               "display_name": "D"}), 409, "handle_taken")
        self.err(call("POST", "/auth/login", {"email": "dee.ann_tag@x.org", "password": "longenough"}),
                 401, "unauthenticated")
        long = call("POST", "/auth/signup", {"email": "a" * 30 + "@x.org", "password": "longenough",
                                             "display_name": "L"})[1]
        self.assertEqual(call("GET", "/me", token=long["token"])[1]["handle"], "a" * 20)
        self.err(call("POST", "/auth/signup", {"email": "q@x.org", "password": "short", "display_name": "S"}),
                 422, "validation_failed")
        for e in ("nodomain", "@x.org", "a@", "a@b@c"):
            self.err(call("POST", "/auth/signup", {"email": e, "password": "longenough", "display_name": "S"}),
                     422, "validation_failed")
        self.err(call("POST", "/auth/login", {"email": "ada@example.com", "password": "bad"}), 401, "unauthenticated")
        self.err(call("POST", "/auth/login", {"email": "who@example.com", "password": "correct horse"}),
                 401, "unauthenticated")

    def test_new_user_receives_and_is_requested(self):
        t = call("POST", "/auth/signup", {"email": "new@x.org", "password": "longenough", "display_name": "N"})[1]["token"]
        self.pay(self.ada, {"to_handle": "new", "amount": 7})
        self.assertEqual(self.bal(t), 7)
        s, b, _ = call("POST", "/requests", {"payer_handle": "new", "amount": 5}, self.ada, {"Idempotency-Key": key()})
        self.assertEqual(s, 201)

    def test_401_everywhere(self):
        for m, p in (("GET", "/me"), ("POST", "/payments"), ("POST", "/requests"), ("GET", "/requests"),
                     ("POST", "/requests/rq_1/pay"), ("POST", "/requests/rq_1/decline"),
                     ("POST", "/requests/rq_1/cancel"), ("POST", "/splits"), ("GET", "/activity"),
                     ("POST", "/settlements")):
            for tok in (None, "bogus"):
                self.err(call(m, p, {}, tok, {"Idempotency-Key": key()}), 401, "unauthenticated")
        s, b, _ = call("GET", "/me", headers={"Authorization": "Basic abc"})
        self.assertEqual(s, 401)


class Payments(Base):
    def test_payment(self):
        b = self.pay(self.ada, {"to_handle": "bob", "amount": 1500, "note": "dinner \U0001F600 <b>", "visibility": "private"})
        self.assertEqual(set(b), {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
                                  "amount", "currency", "note", "visibility", "request_id", "settlement_id",
                                  "created_at"})
        self.assertEqual(b["note"], "dinner \U0001F600 <b>")
        self.assertRegex(b["created_at"], TS)
        self.assertEqual(self.bal(self.ada), 8500)
        self.assertEqual(self.bal(self.bob), 4000)
        d = self.pay(self.ada, {"to_handle": "bob", "amount": 1, "extra": [1]})
        self.assertEqual((d["note"], d["visibility"]), ("", "public"))

    def test_amount_forms(self):
        good = ["1000", "1000.0", "1e3", "1E3", "10e2"]
        badv = ["true", '"5"', "null", "1.5", "0", "-1", "1000000001", "1e400", "[]", "{}", "0.0", "1e-3"]
        for lit in good + badv:
            raw = ('{"to_handle":"bob","amount":%s}' % lit).encode()
            s, b, _ = call("POST", "/payments", raw=raw, token=self.ada, headers={"Idempotency-Key": key()})
            if lit in good:
                self.assertEqual(s, 201, (lit, b))
                self.assertEqual(b["amount"], 1000)
                self.assertIsInstance(b["amount"], int)
            else:
                self.assertEqual((s, b["error"]["code"]), (422, "validation_failed"), lit)
        s, b, _ = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1000000000}', token=self.ada,
                       headers={"Idempotency-Key": key()})
        self.assertEqual(s, 409)

    def test_errors(self):
        self.err(call("POST", "/payments", {"to_handle": "ada", "amount": 1}, self.ada, {"Idempotency-Key": key()}),
                 422, "self_payment")
        self.err(call("POST", "/payments", {"to_handle": "zed", "amount": 1}, self.ada, {"Idempotency-Key": key()}),
                 404, "not_found")
        self.err(call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 6}, self.ada, {"Idempotency-Key": key()}),
                 409, "insufficient_funds")
        for bad in ({"to_handle": "bob", "amount": 1, "note": "x" * 201}, {"to_handle": "bob", "amount": 1, "note": None},
                    {"to_handle": "bob", "amount": 1, "note": 5},
                    {"to_handle": "bob", "amount": 1, "visibility": "Public"},
                    {"to_handle": "bob", "amount": 1, "visibility": None}, {"amount": 1}, {"to_handle": "bob"}):
            self.err(call("POST", "/payments", bad, self.ada, {"Idempotency-Key": key()}), 422, "validation_failed")
        self.err(call("POST", "/payments", {"to_handle": 5, "amount": 1}, self.ada, {"Idempotency-Key": key()}),
                 400, "malformed_request")
        self.err(call("POST", "/payments", raw=b"[1]", token=self.ada, headers={"Idempotency-Key": key()}), 400, "malformed_request")
        self.err(call("POST", "/payments", raw=b"{bad", token=self.ada, headers={"Idempotency-Key": key()}), 400, "malformed_request")
        self.err(call("POST", "/payments", raw=b"\xff\xfe", token=self.ada, headers={"Idempotency-Key": key()}), 400, "malformed_request")
        self.assertEqual(self.pay(self.ada, {"to_handle": "bob", "amount": 1, "note": "\U0001F600" * 200})["note"],
                         "\U0001F600" * 200)
        self.err(call("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": "\U0001F600" * 201}, self.ada,
                      {"Idempotency-Key": key()}), 422, "validation_failed")
        self.assertEqual(self.total(), 12500)

    def test_idempotency_key_header(self):
        body = {"to_handle": "bob", "amount": 10}
        self.err(call("POST", "/payments", body, self.ada), 400, "missing_idempotency_key")
        self.err(call("POST", "/payments", body, self.ada, {"Idempotency-Key": ""}), 400, "missing_idempotency_key")
        self.err(call("POST", "/payments", body, self.ada, {"Idempotency-Key": "k" * 256}), 422, "validation_failed")
        self.assertEqual(call("POST", "/payments", body, self.ada, {"Idempotency-Key": "k" * 255})[0], 201)

    def test_replay_rules(self):
        k = key()
        body = {"to_handle": "bob", "amount": 100}
        s1, b1, _ = call("POST", "/payments", body, self.ada, {"Idempotency-Key": k})
        s2, b2, _ = call("POST", "/payments", {"amount": 100.0, "to_handle": "bob"}, self.ada, {"Idempotency-Key": k})
        self.assertEqual((s1, s2, b1), (201, 200, b2))
        self.assertEqual(self.bal(self.ada), 9900)
        self.err(call("POST", "/payments", {"to_handle": "bob", "amount": 101}, self.ada, {"Idempotency-Key": k}),
                 409, "idempotency_key_reuse")
        # invalid body with a claimed key -> reuse conflict, not 422
        self.err(call("POST", "/payments", {"to_handle": "bob", "amount": -1}, self.ada, {"Idempotency-Key": k}),
                 409, "idempotency_key_reuse")
        # other user, same key: independent
        self.assertEqual(call("POST", "/payments", {"to_handle": "ada", "amount": 100}, self.bob, {"Idempotency-Key": k})[0], 201)
        # different path same key/body shape
        self.assertEqual(call("POST", "/requests", {"payer_handle": "bob", "amount": 100}, self.ada, {"Idempotency-Key": k})[0], 201)
        # failed key is reusable
        k2 = key()
        self.err(call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 8}, self.ada, {"Idempotency-Key": k2}), 409, "insufficient_funds")
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 5}, self.ada, {"Idempotency-Key": k2})[0], 201)

    def test_feed(self):
        priv = self.pay(self.ada, {"to_handle": "bob", "amount": 5, "visibility": "private"})
        pub = self.pay(self.bob, {"to_handle": "cy", "amount": 5})
        ids = lambda t: [p["payment_id"] for p in call("GET", "/activity", token=t)[1]["payments"]]
        self.assertNotIn(priv["payment_id"], ids(self.cy))
        self.assertIn(priv["payment_id"], ids(self.bob))
        self.assertIn(priv["payment_id"], ids(self.ada))
        self.assertIn(pub["payment_id"], ids(self.ada))
        self.assertEqual(ids(self.ada)[0], pub["payment_id"])  # newest first
        # requests never in the feed
        call("POST", "/requests", {"payer_handle": "bob", "amount": 5}, self.ada, {"Idempotency-Key": key()})
        self.assertEqual(len(ids(self.cy)), 2)
        s, b, _ = call("GET", "/activity?limit=1&offset=1&direction=zzz", token=self.ada)
        self.assertEqual(s, 200)
        self.assertEqual(len(b["payments"]), 1)
        self.assertTrue(b["has_more"])

    def test_pagination_params(self):
        for q in ("limit=0", "limit=201", "limit=1e2", "limit=4.0", "limit=+4", "limit=abc", "limit=", "limit=-1",
                  "offset=-1", "offset=", "offset=1.0"):
            for p in ("/activity", "/requests"):
                self.err(call("GET", p + "?" + q, token=self.ada), 422, "validation_failed")
        self.assertEqual(call("GET", "/activity?limit=200&offset=0&zzz=1", token=self.ada)[0], 200)
        self.err(call("GET", "/requests?direction=sideways", token=self.ada), 422, "validation_failed")
        self.err(call("GET", "/requests?status=nope", token=self.ada), 422, "validation_failed")


class Requests(Base):
    def mk(self, tok, payer, amount, note="n"):
        s, b, _ = call("POST", "/requests", {"payer_handle": payer, "amount": amount, "note": note}, tok,
                       {"Idempotency-Key": key()})
        self.assertEqual(s, 201, b)
        return b

    def test_lifecycle(self):
        r = self.mk(self.bob, "ada", 300)
        self.assertEqual((r["status"], r["payment_id"], r["requester_handle"], r["payer_handle"]),
                         ("pending", None, "bob", "ada"))
        k = key()
        s, p, _ = call("POST", "/requests/%s/pay" % r["request_id"], {"visibility": "private"}, self.ada, {"Idempotency-Key": k})
        self.assertEqual(s, 201)
        self.assertEqual((p["request_id"], p["visibility"], p["amount"]), (r["request_id"], "private", 300))
        self.assertEqual(self.bal(self.ada), 9700)
        # replay after paid
        s, p2, _ = call("POST", "/requests/%s/pay" % r["request_id"], {"visibility": "private"}, self.ada, {"Idempotency-Key": k})
        self.assertEqual((s, p2), (200, p))
        # {} differs from {"visibility": "public"}
        self.err(call("POST", "/requests/%s/pay" % r["request_id"], {}, self.ada, {"Idempotency-Key": k}), 409, "idempotency_key_reuse")
        self.err(call("POST", "/requests/%s/pay" % r["request_id"], {}, self.ada, {"Idempotency-Key": key()}), 409, "request_not_pending")
        self.err(call("POST", "/requests/%s/pay" % r["request_id"], {}, self.bob, {"Idempotency-Key": key()}), 403, "forbidden")
        self.err(call("POST", "/requests/%s/decline" % r["request_id"], token=self.ada), 409, "request_not_pending")
        self.err(call("POST", "/requests/%s/cancel" % r["request_id"], token=self.bob), 409, "request_not_pending")
        got = call("GET", "/requests?status=paid", token=self.bob)[1]["requests"][0]
        self.assertEqual(got["payment_id"], p["payment_id"])
        self.err(call("POST", "/requests/zzz/pay", {}, self.ada, {"Idempotency-Key": key()}), 404, "not_found")
        self.err(call("POST", "/requests/zzz/decline", token=self.ada), 404, "not_found")

    def test_short_then_funded(self):
        r = self.mk(self.ada, "cy", 500)
        self.err(call("POST", "/requests/%s/pay" % r["request_id"], {}, self.cy, {"Idempotency-Key": key()}), 409, "insufficient_funds")
        self.assertEqual(call("GET", "/requests?status=pending", token=self.cy)[1]["requests"][0]["status"], "pending")
        self.pay(self.ada, {"to_handle": "cy", "amount": 500})
        self.assertEqual(call("POST", "/requests/%s/pay" % r["request_id"], {}, self.cy, {"Idempotency-Key": key()})[0], 201)
        self.assertEqual(self.total(), 12500)

    def test_decline_cancel(self):
        r = self.mk(self.bob, "ada", 5)
        self.err(call("POST", "/requests/%s/decline" % r["request_id"], token=self.bob), 403, "forbidden")
        self.err(call("POST", "/requests/%s/cancel" % r["request_id"], token=self.ada), 403, "forbidden")
        for _ in range(2):
            s, b, _ = call("POST", "/requests/%s/decline" % r["request_id"], token=self.ada)
            self.assertEqual((s, b["status"]), (200, "declined"))
        self.err(call("POST", "/requests/%s/cancel" % r["request_id"], token=self.bob), 409, "request_not_pending")
        self.err(call("POST", "/requests/%s/pay" % r["request_id"], {}, self.ada, {"Idempotency-Key": key()}), 409, "request_not_pending")
        r2 = self.mk(self.bob, "ada", 5)
        for _ in range(2):
            self.assertEqual(call("POST", "/requests/%s/cancel" % r2["request_id"], token=self.bob)[1]["status"], "cancelled")
        self.err(call("POST", "/requests/%s/decline" % r2["request_id"], token=self.ada), 409, "request_not_pending")
        # replay of create after cancel returns original
        k = key()
        s1, a, _ = call("POST", "/requests", {"payer_handle": "ada", "amount": 9}, self.bob, {"Idempotency-Key": k})
        call("POST", "/requests/%s/cancel" % a["request_id"], token=self.bob)
        s2, b, _ = call("POST", "/requests", {"payer_handle": "ada", "amount": 9}, self.bob, {"Idempotency-Key": k})
        self.assertEqual((s1, s2, a), (201, 200, b))

    def test_errors_and_listing(self):
        h = {"Idempotency-Key": key()}
        self.err(call("POST", "/requests", {"payer_handle": "bob", "amount": 5}, self.bob, h), 422, "self_request")
        self.err(call("POST", "/requests", {"payer_handle": "zed", "amount": 5}, self.bob, {"Idempotency-Key": key()}), 404, "not_found")
        self.err(call("POST", "/requests", {"payer_handle": "ada", "amount": 0}, self.bob, {"Idempotency-Key": key()}), 422, "validation_failed")
        self.err(call("POST", "/requests", {"payer_handle": "ada", "amount": 5, "note": "x" * 201}, self.bob, {"Idempotency-Key": key()}), 422, "validation_failed")
        self.mk(self.bob, "ada", 1)
        self.mk(self.ada, "bob", 2)
        self.mk(self.cy, "bob", 3)
        l = lambda q, t: call("GET", "/requests" + q, token=t)[1]
        self.assertEqual(len(l("", self.bob)["requests"]), 4)
        self.assertEqual(len(l("?direction=incoming", self.bob)["requests"]), 2)
        self.assertEqual(len(l("?direction=outgoing", self.bob)["requests"]), 2)
        self.assertEqual(l("", self.cy)["requests"][0]["amount"], 3)
        self.assertEqual([r["amount"] for r in l("", self.bob)["requests"]], [3, 2, 1, 1200])
        pg = l("?limit=2", self.bob)
        self.assertTrue(pg["has_more"])
        self.assertFalse(l("?limit=2&offset=2", self.bob)["has_more"])
        self.assertEqual(l("?status=paid", self.bob)["requests"], [])


class Splits(Base):
    def split(self, tok, amount, handles, **kw):
        body = dict({"amount": amount, "participant_handles": handles}, **kw)
        return call("POST", "/splits", body, tok, {"Idempotency-Key": key()})

    def test_rounding_table(self):
        for amt, n, exp in ((1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
                            (999, 3, [333, 333, 333]), (5, 5, [1] * 5)):
            hs = ["ada", "bob", "cy", "u4", "u5"][:n]
            if n == 5:
                for h in ("u4", "u5"):
                    call("POST", "/auth/signup", {"email": h + "@x.org", "password": "longenough", "display_name": h})
            s, b, _ = self.split(self.ada, amt, hs, note="d")
            self.assertEqual(s, 201, b)
            self.assertEqual([x["amount"] for x in b["shares"]], exp)
            self.assertEqual([x["handle"] for x in b["shares"]], hs)
            self.assertEqual([r["amount"] for r in b["requests"]], exp[1:])
            self.assertEqual([r["payer_handle"] for r in b["requests"]], hs[1:])
            self.assertTrue(all(r["requester_handle"] == "ada" and r["status"] == "pending" for r in b["requests"]))
        b = self.split(self.ada, 1000, ["cy", "bob", "ada"])[1]
        self.assertEqual([x["amount"] for x in b["shares"]], [334, 333, 333])
        self.assertEqual([r["payer_handle"] for r in b["requests"]], ["cy", "bob"])

    def test_edges(self):
        s, b, _ = self.split(self.ada, 100, ["ada"])
        self.assertEqual((s, b["requests"], b["shares"]), (201, [], [{"handle": "ada", "amount": 100}]))
        s, b, _ = self.split(self.bob, 1, ["ada", "cy"])  # caller omitted; zero share still a request
        self.assertEqual([r["amount"] for r in b["requests"]], [1, 0])
        self.err(self.split(self.ada, 100, []), 422, "validation_failed")
        self.err(self.split(self.ada, 100, ["bob", "bob"]), 422, "validation_failed")
        self.err(self.split(self.ada, 100, ["bob", "zed"]), 404, "not_found")
        self.err(self.split(self.ada, 0, ["bob"]), 422, "validation_failed")
        self.err(self.split(self.ada, 5, ["bob"], note="x" * 201), 422, "validation_failed")
        self.err(self.split(self.ada, 5, "bob"), 400, "malformed_request")
        s, b, _ = self.split(self.ada, 5, ["h%d" % i for i in range(1000)])
        self.assertIn(s, (404, 422))
        self.assertEqual(self.total(), 12500)
        self.assertEqual(call("GET", "/activity", token=self.cy)[1]["payments"][0]["payment_id"], "p_1")

    def test_paid_splits_conserve(self):
        b = self.split(self.ada, 3000, ["ada", "bob", "cy"])[1]
        self.pay(self.bob, {"to_handle": "cy", "amount": 1000})
        for r in b["requests"]:
            tok = self.bob if r["payer_handle"] == "bob" else self.cy
            call("POST", "/requests/%s/pay" % r["request_id"], {}, tok, {"Idempotency-Key": key()})
        self.assertEqual(self.total(), 12500)


class Settlements(Base):
    def st(self, tok, transfers, k=None, extra=None):
        return call("POST", "/settlements", dict({"transfers": transfers}, **(extra or {})), tok,
                    {"Idempotency-Key": k or key()})

    def t(self, f, to, a, **kw):
        return dict({"from_handle": f, "to_handle": to, "amount": a}, **kw)

    def test_auth(self):
        self.err(self.st(None, [self.t("ada", "bob", 1)]), 401, "unauthenticated")
        self.err(self.st(self.ada, [self.t("ada", "bob", 1)]), 403, "forbidden")
        self.err(call("POST", "/settlements", {"transfers": [self.t("ada", "bob", 1)]}, self.cy), 400, "missing_idempotency_key")

    def test_commit_and_net(self):
        # cy holds 0 but passes money through
        s, b, _ = self.st(self.cy, [self.t("ada", "cy", 100), self.t("cy", "bob", 100, visibility="private", note="n")])
        self.assertEqual(s, 201, b)
        self.assertEqual(len(b["payments"]), 2)
        self.assertEqual({p["created_at"] for p in b["payments"]}, {b["committed_at"]})
        self.assertTrue(all(p["settlement_id"] == b["settlement_id"] and p["request_id"] is None for p in b["payments"]))
        self.assertEqual((self.bal(self.ada), self.bal(self.bob), self.bal(self.cy)), (9900, 2600, 0))
        feed = [p["payment_id"] for p in call("GET", "/activity", token=self.cy)[1]["payments"]]
        self.assertIn(b["payments"][1]["payment_id"], feed)  # cy is the sender
        # operator sees nothing extra: the private one is hidden from a stranger
        sg = call("POST", "/auth/signup", {"email": "z@x.org", "password": "longenough", "display_name": "Z"})[1]["token"]
        feed = [p["payment_id"] for p in call("GET", "/activity", token=sg)[1]["payments"]]
        self.assertNotIn(b["payments"][1]["payment_id"], feed)
        self.assertIn(b["payments"][0]["payment_id"], feed)
        self.assertEqual(call("GET", "/requests", token=self.cy)[1]["requests"], [])
        self.err(call("POST", "/requests/rq_1/cancel", token=self.cy), 403, "forbidden")
        self.assertIsNone(self.pay(self.ada, {"to_handle": "bob", "amount": 1})["settlement_id"])

    def test_failures_leave_nothing(self):
        k = key()
        self.err(self.st(self.cy, [self.t("bob", "ada", 2000), self.t("bob", "cy", 1000)], k), 409, "insufficient_funds")
        self.assertEqual(self.total(), 12500)
        self.assertEqual(self.bal(self.bob), 2500)
        self.assertEqual(self.st(self.cy, [self.t("bob", "ada", 1)], k)[0], 201)  # key not claimed
        self.err(self.st(self.cy, [self.t("bob", "ada", 1), self.t("ada", "ada", 1), self.t("x", "ada", 1)]), 422, "self_payment")
        self.err(self.st(self.cy, [self.t("bob", "ada", 1), self.t("zed", "ada", 1), self.t("ada", "ada", 1)]), 404, "not_found")
        self.err(self.st(self.cy, [self.t("zed", "ada", 10 ** 8)]), 404, "not_found")  # before funds
        for bad in ([], [self.t("bob", "ada", 1)] * 33, "x", [1], [self.t("bob", "ada", 0)],
                    [self.t("bob", "ada", 1, visibility="x")], [self.t("bob", "ada", 1, note=None)]):
            self.err(self.st(self.cy, bad), 422, "validation_failed")
        self.err(call("POST", "/settlements", {}, self.cy, {"Idempotency-Key": key()}), 422, "validation_failed")
        self.assertEqual(self.st(self.cy, [self.t("bob", "ada", 1)] * 32)[0], 201)

    def test_replay(self):
        k = key()
        s1, a, _ = self.st(self.cy, [self.t("ada", "bob", 10)], k)
        s2, b, _ = self.st(self.cy, [self.t("ada", "bob", 10)], k)
        self.assertEqual((s1, s2, a), (201, 200, b))
        self.err(self.st(self.cy, [self.t("ada", "bob", 11)], k), 409, "idempotency_key_reuse")
        self.assertEqual(self.bal(self.ada), 9990)


class ExportImport(Base):
    def test_roundtrip(self):
        k = key()
        p = self.pay(self.ada, {"to_handle": "bob", "amount": 100, "visibility": "private"}, k)
        call("POST", "/requests", {"payer_handle": "bob", "amount": 9}, self.ada, {"Idempotency-Key": "fail-me"})
        self.err(call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 9}, self.ada, {"Idempotency-Key": "failed"}), 409, "insufficient_funds")
        st = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 3}]}, self.cy,
                  {"Idempotency-Key": "sk"})[1]
        s, exp, _ = call("GET", "/_test/export")
        self.assertEqual((s, exp["track"], exp["format_version"]), (200, "pocketful", 1))
        self.assertNotIn("correct horse", json.dumps(exp))
        before = (call("GET", "/activity", token=self.bob)[1], self.bal(self.ada))
        self.pay(self.ada, {"to_handle": "bob", "amount": 1})  # after export: must vanish
        reset({"currency": "JPY", "minor_units": 0, "users": [U("zz", "zz", 5)]})
        for _ in range(2):
            self.assertEqual(call("POST", "/_test/import", exp)[0], 204)
        self.assertEqual(call("GET", "/me", token=self.ada)[0], 200)  # token preserved
        after = (call("GET", "/activity", token=self.bob)[1], self.bal(self.ada))
        self.assertEqual(before, after)
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 100, "visibility": "private"}, self.ada,
                              {"Idempotency-Key": k})[:2], (200, p))
        self.err(call("POST", "/payments", {"to_handle": "bob", "amount": 101}, self.ada, {"Idempotency-Key": k}), 409, "idempotency_key_reuse")
        self.assertEqual(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 3}]},
                              self.cy, {"Idempotency-Key": "sk"})[:2], (200, st))
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 5}, self.ada, {"Idempotency-Key": "failed"})[0], 201)
        self.assertEqual(call("GET", "/requests", token=self.ada)[1]["requests"][0]["request_id"] is not None, True)
        self.err(call("GET", "/me", token=None), 401, "unauthenticated")
        self.assertEqual(call("GET", "/_test/export")[1]["state"]["currency"], "EUR")
        # invalid imports leave state alone
        self.err(call("POST", "/_test/import", raw=b"{"), 400, "malformed_request")
        for bad in ({}, [], {"track": "x", "format_version": 1, "state": exp["state"]},
                    {"track": "pocketful", "format_version": 2, "state": exp["state"]},
                    {"track": "pocketful", "format_version": 1}, {"track": "pocketful", "format_version": 1, "state": {}},
                    {"track": "pocketful", "format_version": 1, "state": []}):
            self.err(call("POST", "/_test/import", bad), 422, "validation_failed")
        self.assertEqual(call("GET", "/me", token=self.ada)[0], 200)
        reset()
        self.assertEqual(call("GET", "/me", token=self.ada)[0], 401)


class Concurrency(Base):
    def test_drain_and_conservation(self):
        def one(i):
            return call("POST", "/payments", {"to_handle": "bob" if i % 2 else "cy", "amount": 300}, self.ada,
                        {"Idempotency-Key": key()})[0]
        with ThreadPoolExecutor(50) as ex:
            codes = list(ex.map(one, range(100)))
        self.assertEqual(set(codes) <= {201, 409}, True)
        self.assertEqual(codes.count(201), 33)
        self.assertEqual(self.bal(self.ada), 10000 - 33 * 300)
        self.assertEqual(self.total(), 12500)

    def test_idempotent_burst_and_pay_once(self):
        k = key()
        with ThreadPoolExecutor(50) as ex:
            res = list(ex.map(lambda _: call("POST", "/payments", {"to_handle": "bob", "amount": 10}, self.ada,
                                            {"Idempotency-Key": k}), range(50)))
        self.assertEqual(sorted(r[0] for r in res).count(201), 1)
        self.assertEqual(len({json.dumps(r[1], sort_keys=True) for r in res}), 1)
        self.assertEqual(self.bal(self.ada), 9990)
        with ThreadPoolExecutor(50) as ex:
            res = list(ex.map(lambda _: call("POST", "/requests/rq_1/pay", {}, self.ada, {"Idempotency-Key": key()})[0],
                              range(50)))
        self.assertEqual((res.count(201), res.count(409)), (1, 49))
        self.assertEqual(self.bal(self.ada), 9990 - 1200)
        self.assertEqual(self.total(), 12500)

    def test_settlement_burst(self):
        def one(i):
            return call("POST", "/settlements", {"transfers": [{"from_handle": "bob", "to_handle": "ada", "amount": 1000}]},
                        self.cy, {"Idempotency-Key": key()})[0]
        with ThreadPoolExecutor(30) as ex:
            codes = list(ex.map(one, range(30)))
        self.assertEqual(codes.count(201), 2)
        self.assertEqual(self.total(), 12500)
        self.assertGreaterEqual(self.bal(self.bob), 0)


class Hostile(Base):
    def test_no_5xx(self):
        h = {"Idempotency-Key": key()}
        cases = [b"1" * 5000, b'{"amount":' + b"9" * 5000 + b',"to_handle":"bob"}', b"[" * 5000, b'{"a":' * 2000,
                 b'{"to_handle":"bob","amount":NaN}', b'{"to_handle":"bob","amount":1e999999999999}',
                 b'{"to_handle":"bob","amount":-0.0}', b"\xff", b"", b'"s"', b"null"]
        for path in ("/payments", "/requests", "/splits", "/settlements", "/requests/rq_1/pay", "/auth/login",
                     "/auth/signup", "/_test/import", "/_test/reset"):
            for c in cases:
                tok = self.cy if path == "/settlements" else self.ada
                s, b, _ = call("POST", path, raw=c, token=tok, headers={"Idempotency-Key": key()})
                self.assertLess(s, 500, (path, c[:20], b))
                self.assertGreaterEqual(s, 200)
        reset()
        s, b, _ = call("GET", "/activity?limit=%s" % ("9" * 5000), token=login("ada@example.com"))
        self.assertEqual(s, 422)
        self.assertEqual(call("POST", "/payments", {"to_handle": "x" * 10000, "amount": 1}, login("ada@example.com"),
                              {"Idempotency-Key": "k" * 10000})[0], 422)


class Regressions(Base):
    def test_import_keeps_ids_unique(self):
        exp = call("GET", "/_test/export")[1]
        self.assertEqual(call("POST", "/_test/import", exp)[0], 204)
        ids = {self.pay(self.ada, {"to_handle": "bob", "amount": 1})["payment_id"] for _ in range(3)}
        self.assertEqual(len(ids), 3)
        self.assertFalse(ids & {"p_1", "p_2"})

    def test_huge_exponents(self):
        for lit in ("1e9999999999999999999999", "1e-9999999999999999999999", "-1e99999999999999999999",
                    "0e99999999999999999999", "1E+1000000000000000000"):
            raw = ('{"to_handle":"bob","amount":%s}' % lit).encode()
            self.err(call("POST", "/payments", raw=raw, token=self.ada, headers={"Idempotency-Key": key()}),
                     422, "validation_failed")
            raw = ('{"to_handle":"bob","amount":5,"zz":%s}' % lit).encode()
            self.assertEqual(call("POST", "/payments", raw=raw, token=self.ada,
                                  headers={"Idempotency-Key": key()})[0], 201)
            fx = json.loads(json.dumps(FIX))
            fx["users"][0]["balance"] = 0
            raw = json.dumps(fx).replace('"balance": 0', '"balance": ' + lit, 1).encode()
            self.assertIn(call("POST", "/_test/reset", raw=raw)[0], (204, 422))
            reset()
            self.ada = login("ada@example.com")

    def test_bad_party_ids(self):
        for k, v in (("from_user_id", []), ("to_user_id", {})):
            fx = json.loads(json.dumps(FIX))
            fx["payments"][0][k] = v
            self.err(call("POST", "/_test/reset", fx), 422, "validation_failed")
        for k, v in (("requester_id", []), ("payer_id", {"a": 1})):
            fx = json.loads(json.dumps(FIX))
            fx["requests"][0][k] = v
            self.err(call("POST", "/_test/reset", fx), 422, "validation_failed")

    def test_import_float_state(self):
        exp = call("GET", "/_test/export")[1]
        txt = json.dumps(exp).replace('"minor_units": 2', '"minor_units": 2.0', 1)
        self.err(call("POST", "/_test/import", raw=txt.encode()), 422, "validation_failed")
        self.assertEqual(call("GET", "/me", token=self.ada)[0], 200)

    def test_offset_and_limit_digits(self):
        for off in ("1000000000000", "9" * 100):
            s, b, _ = call("GET", "/activity?offset=" + off, token=self.ada)
            self.assertEqual((s, b["payments"]), (200, []))
        self.assertEqual(call("GET", "/activity?limit=0000000000050", token=self.ada)[0], 200)

    def test_replay_distinguishes_string_from_number(self):
        k = key()
        a = {"to_handle": "bob", "amount": 5, "x": "D1.5"}
        self.assertEqual(call("POST", "/payments", a, self.ada, {"Idempotency-Key": k})[0], 201)
        self.err(call("POST", "/payments", raw=b'{"to_handle":"bob","amount":5,"x":1.5}', token=self.ada,
                      headers={"Idempotency-Key": k}), 409, "idempotency_key_reuse")
        self.assertEqual(call("POST", "/payments", raw=b'{"x":"D1.5","amount":5.0,"to_handle":"bob"}', token=self.ada,
                              headers={"Idempotency-Key": k})[0], 200)

    def test_import_ids_unique_all_kinds(self):
        h = lambda: {"Idempotency-Key": key()}
        for _ in range(2):
            call("POST", "/requests", {"payer_handle": "bob", "amount": 1}, self.ada, h())
            call("POST", "/splits", {"amount": 3, "participant_handles": ["bob"]}, self.ada, h())
            call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}, self.cy, h())
            call("POST", "/auth/signup", {"email": "n%d@x.org" % _, "password": "longenough", "display_name": "n"})
        exp = call("GET", "/_test/export")[1]
        seen = {"rq": set(), "sp": set(), "st": set(), "u": set(), "p": set()}
        def collect(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    for pre, name in (("rq", "request_id"), ("sp", "split_id"), ("st", "settlement_id"), ("p", "payment_id"), ("u", "user_id")):
                        if k == name and isinstance(v, str):
                            seen[pre].add(v)
                    collect(v)
            elif isinstance(o, list):
                for v in o:
                    collect(v)
        collect(exp["state"])
        self.assertEqual(call("POST", "/_test/import", exp)[0], 204)
        ada = login("ada@example.com")
        new = {k: set() for k in seen}
        b = call("POST", "/requests", {"payer_handle": "bob", "amount": 1}, ada, h())[1]
        new["rq"].add(b["request_id"])
        new["sp"].add(call("POST", "/splits", {"amount": 3, "participant_handles": ["bob"]}, ada, h())[1]["split_id"])
        s = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}, login("cy@example.com"), h())[1]
        new["st"].add(s["settlement_id"]); new["p"].add(s["payments"][0]["payment_id"])
        new["u"].add(call("POST", "/auth/signup", {"email": "after@x.org", "password": "longenough", "display_name": "n"})[1]["user_id"])
        for k in seen:
            self.assertFalse(seen[k] & new[k], k)

    def test_fixture_created_at_is_ignored_when_bad(self):
        for v in (5, "yesterday", "2026-01-01T00:00:00", None, [], "2026-09-24T19:00:00+02:00"):
            fx = json.loads(json.dumps(FIX))
            fx["payments"][0]["created_at"] = v
            fx["requests"][0]["created_at"] = v
            reset(fx)
            self.assertEqual(call("GET", "/activity", token=login("ada@example.com"))[0], 200)

    def test_huge_body_gets_4xx(self):
        s, b, _ = call("POST", "/payments", raw=b" " * (17 * 1024 * 1024), token=self.ada,
                       headers={"Idempotency-Key": key()})
        self.assertEqual((s, b["error"]["code"]), (400, "malformed_request"))

    def test_bad_target(self):
        import socket
        host, port = BASE.split("//")[1].split(":")
        c = socket.create_connection((host, int(port)), timeout=5)
        c.sendall(b"GET http://[x/me HTTP/1.1\r\nHost: x\r\n\r\n")
        self.assertRegex(c.recv(200), rb"^HTTP/1.1 4\d\d")
        c.close()


if __name__ == "__main__":
    unittest.main()
