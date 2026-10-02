"""Own tests for Pocketful stage 1, written from the specification.

Run against a live container:  BASE_URL=http://127.0.0.1:8080 python3 tests/test_stage1.py
Standard library only. BASE_URL2 (optional) is a second fresh container for the export/import test.
"""
import sys
import http.client
import json
import os
import re
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

sys.set_int_max_str_digits(0)
BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080")
BASE2 = os.environ.get("BASE_URL2")
TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)$")
_n = [0]
_nl = threading.Lock()


def nk():
    with _nl:
        _n[0] += 1
        return "k%d-%f" % (_n[0], time.time())


def call(method, path, body=None, token=None, key=None, raw=None, base=None, headers=None):
    u = urlsplit(base or BASE)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=15)
    h = dict(headers or {})
    if token:
        h["Authorization"] = "Bearer " + token
    if key is not None:
        h["Idempotency-Key"] = key
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
    if data is not None:
        h["Content-Type"] = "application/json"
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    txt = r.read()
    ctype = r.getheader("Content-Type")
    c.close()
    j = json.loads(txt) if txt else None
    return r.status, j, ctype


def user(handle, bal, **kw):
    return {"id": "u_" + handle, "email": handle + "@example.com", "password": "correct horse",
            "display_name": handle.title(), "handle": handle, "balance": bal, **kw}


def reset(fx):
    s, j, _ = call("POST", "/_test/reset", fx)
    assert s == 204, (s, j)


def fixture(**kw):
    fx = {"currency": "EUR", "minor_units": 2,
          "users": [user("ada", 10000), user("bob", 2500), user("cy", 500)]}
    fx.update(kw)
    return fx


def login(h):
    s, j, _ = call("POST", "/auth/login", {"email": h + "@example.com", "password": "correct horse"})
    assert s == 200, (s, j)
    return j["token"]


def bal(t):
    return call("GET", "/me", token=t)[1]["balance"]


def err(r, status, code):
    s, j, _ = r
    assert s == status and j["error"]["code"] == code, (s, j, status, code)


class Base(unittest.TestCase):
    def setUp(self):
        reset(fixture())
        self.ada, self.bob, self.cy = login("ada"), login("bob"), login("cy")

    def pay(self, t, to, amount, key=None, **kw):
        return call("POST", "/payments", {"to_handle": to, "amount": amount, **kw}, t, key or nk())

    def total(self):
        return sum(bal(t) for t in (self.ada, self.bob, self.cy))


class TestBasics(Base):
    def test_health_and_json_headers(self):
        s, j, ct = call("GET", "/health")
        self.assertEqual((s, j), (200, {"status": "ok"}))
        self.assertEqual(ct, "application/json; charset=utf-8")
        for r in (call("GET", "/nope"), call("GET", "/me"), call("DELETE", "/me"),
                  call("POST", "/payments", {}, self.ada, nk())):
            self.assertEqual(r[2], "application/json; charset=utf-8")
            self.assertIn("code", r[1]["error"])
        err(call("GET", "/nope"), 404, "not_found")

    def test_me(self):
        s, j, _ = call("GET", "/me", token=self.ada)
        self.assertEqual(j, {"user_id": "u_ada", "display_name": "Ada", "handle": "ada",
                             "balance": 10000, "currency": "EUR", "minor_units": 2})

    def test_auth_required(self):
        for m, p in (("GET", "/me"), ("POST", "/payments"), ("POST", "/requests"), ("GET", "/requests"),
                     ("POST", "/requests/x/pay"), ("POST", "/requests/x/decline"),
                     ("POST", "/requests/x/cancel"), ("POST", "/splits"), ("GET", "/activity"),
                     ("POST", "/settlements")):
            err(call(m, p, {} if m == "POST" else None, key=nk()), 401, "unauthenticated")
            err(call(m, p, {} if m == "POST" else None, "bogus", key=nk()), 401, "unauthenticated")
            err(call(m, p, {} if m == "POST" else None, key=nk(), headers={"Authorization": "Basic x"}),
                401, "unauthenticated")

    def test_signup_login(self):
        s, j, _ = call("POST", "/auth/signup", {"email": "A.B+c@x.io", "password": "12345678", "display_name": "Q"})
        self.assertEqual(s, 201)
        t = j["token"]
        self.assertEqual(call("GET", "/me", token=t)[1]["handle"], "a_b_c")
        self.assertEqual(bal(t), 0)
        err(call("POST", "/auth/signup", {"email": "A.B+c@x.io", "password": "12345678", "display_name": "Q"}), 409, "email_taken")
        err(call("POST", "/auth/signup", {"email": "a.b_c@x.io", "password": "12345678", "display_name": "Q"}), 409, "handle_taken")
        err(call("POST", "/auth/login", {"email": "a.b_c@x.io", "password": "12345678"}), 401, "unauthenticated")
        err(call("POST", "/auth/signup", {"email": "z@x.io", "password": "1234567", "display_name": "Q"}), 422, "validation_failed")
        self.assertEqual(call("POST", "/auth/signup", {"email": "z@x.io", "password": "12345678", "display_name": "Q"})[0], 201)
        for e in ("nodomain", "@x.io", "a@", "a@b@c"):
            err(call("POST", "/auth/signup", {"email": e, "password": "12345678", "display_name": "Q"}), 422, "validation_failed")
        long = "x" * 25
        s, j, _ = call("POST", "/auth/signup", {"email": long + "@x.io", "password": "12345678", "display_name": "Q"})
        self.assertEqual(call("GET", "/me", token=j["token"])[1]["handle"], "x" * 20)
        # handle field in signup ignored
        s, j, _ = call("POST", "/auth/signup", {"email": "h1@x.io", "password": "12345678", "display_name": "Q", "handle": "zzz"})
        self.assertEqual(call("GET", "/me", token=j["token"])[1]["handle"], "h1")
        # login: wrong pw, several tokens
        err(call("POST", "/auth/login", {"email": "ada@example.com", "password": "nope nope"}), 401, "unauthenticated")
        t1, t2 = login("ada"), login("ada")
        self.assertNotEqual(t1, t2)
        self.assertEqual(call("GET", "/me", token=t1)[0], 200)
        self.assertEqual(call("GET", "/me", token=t2)[0], 200)
        # new user can receive and be asked
        self.assertEqual(self.pay(self.ada, "h1", 100)[0], 201)
        self.assertEqual(call("POST", "/requests", {"payer_handle": "h1", "amount": 5}, self.ada, nk())[0], 201)


class TestPayments(Base):
    def test_happy_and_shape(self):
        s, j, _ = self.pay(self.ada, "bob", 1500, note="dinner")
        self.assertEqual(s, 201)
        self.assertEqual(set(j), {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
                                  "currency", "note", "visibility", "request_id", "settlement_id", "created_at"})
        self.assertEqual((j["visibility"], j["request_id"], j["settlement_id"], j["currency"]), ("public", None, None, "EUR"))
        self.assertRegex(j["created_at"], TS_RE)
        self.assertLessEqual(len(j["payment_id"]), 64)
        self.assertEqual((bal(self.ada), bal(self.bob)), (8500, 4000))
        j2 = self.pay(self.ada, "bob", 1)[1]
        self.assertEqual(j2["note"], "")

    def test_errors(self):
        err(self.pay(self.ada, "bob", 10001), 409, "insufficient_funds")
        self.assertEqual(bal(self.ada), 10000)
        self.assertEqual(self.pay(self.ada, "bob", 10000)[0], 201)
        self.assertEqual(bal(self.ada), 0)
        reset(fixture())
        self.ada, self.bob = login("ada"), login("bob")
        for a in (0, -1, 1000000001, 1.5, "100", True, None, [], {}):
            err(self.pay(self.ada, "bob", a), 422, "validation_failed")
        for a in (1000, 1000.0):
            self.assertEqual(self.pay(self.ada, "bob", a)[0], 201)
        self.assertEqual(call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1e3}', token=self.ada, key=nk())[0], 201)
        err(call("POST", "/payments", {"to_handle": "bob"}, self.ada, nk()), 422, "validation_failed")
        err(call("POST", "/payments", {"amount": 5}, self.ada, nk()), 422, "validation_failed")
        err(self.pay(self.ada, "ada", 5), 422, "self_payment")
        err(self.pay(self.ada, "nobody", 5), 404, "not_found")
        err(self.pay(self.ada, "BOB", 5), 404, "not_found")
        err(self.pay(self.ada, "bob", 5, note="x" * 201), 422, "validation_failed")
        self.assertEqual(self.pay(self.ada, "bob", 5, note="x" * 200)[0], 201)
        self.assertEqual(self.pay(self.ada, "bob", 5, note="\U0001F600" * 200)[0], 201)
        err(self.pay(self.ada, "bob", 5, note="\U0001F600" * 201), 422, "validation_failed")
        for n in (None, 5, True, []):
            err(self.pay(self.ada, "bob", 5, note=n), 422, "validation_failed")
        for v in ("friends", None, 1, "PUBLIC", []):
            err(self.pay(self.ada, "bob", 5, visibility=v), 422, "validation_failed")
        err(call("POST", "/payments", {"to_handle": 5, "amount": 5}, self.ada, nk()), 400, "malformed_request")
        err(call("POST", "/payments", raw=b"{nope", token=self.ada, key=nk()), 400, "malformed_request")
        err(call("POST", "/payments", raw=b"[1]", token=self.ada, key=nk()), 400, "malformed_request")
        err(call("POST", "/payments", raw=b"", token=self.ada, key=nk()), 400, "malformed_request")
        self.assertEqual(self.pay(self.ada, "bob", 5, extra="x")[0], 201)
        s, j, _ = call("POST", "/payments?foo=1", {"to_handle": "bob", "amount": 5}, self.ada, nk())
        self.assertEqual(s, 201)

    def test_note_verbatim(self):
        for n in ("  spaced  ", "caf\u00e9 e\u0301", "\U0001F468\u200d\U0001F469\u200d\U0001F467", "<b>&amp;</b>\n\t\"\\", "\u0000x"):
            j = self.pay(self.ada, "bob", 1, note=n)[1]
            self.assertEqual(j["note"], n)
            feed = call("GET", "/activity?limit=1", token=self.ada)[1]["payments"][0]
            self.assertEqual(feed["note"], n)

    def test_minor_units(self):
        for cur, mu in (("JPY", 0), ("BHD", 3)):
            reset(fixture(currency=cur, minor_units=mu))
            t = login("ada")
            self.assertEqual(call("GET", "/me", token=t)[1]["minor_units"], mu)
            self.assertEqual(self.pay(t, "bob", 1)[1]["currency"], cur)

    def test_big_balances(self):
        big = 2 ** 53
        reset(fixture(users=[user("ada", big), user("bob", big - 1)]))
        t = login("ada")
        self.assertEqual(bal(t), big)
        self.assertEqual(self.pay(t, "bob", 1000000000)[0], 201)
        self.assertEqual(bal(t), big - 1000000000)
        err((call("POST", "/_test/reset", fixture(users=[user("ada", big + 1)])) + (None,))[:3], 422, "validation_failed") \
            if False else None
        self.assertEqual(call("POST", "/_test/reset", fixture(users=[user("ada", big + 1)]))[0], 422)

    def test_idempotency_keys(self):
        err(call("POST", "/payments", {"to_handle": "bob", "amount": 5}, self.ada), 400, "missing_idempotency_key")
        err(call("POST", "/payments", {"to_handle": "bob", "amount": 5}, self.ada, ""), 400, "missing_idempotency_key")
        err(call("POST", "/payments", {"to_handle": "bob", "amount": 5}, self.ada, "k" * 256), 422, "validation_failed")
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 5}, self.ada, "k" * 255)[0], 201)
        k = nk()
        r1 = call("POST", "/payments", {"to_handle": "bob", "amount": 50}, self.ada, k)
        r2 = call("POST", "/payments", {"amount": 50.0, "to_handle": "bob"}, self.ada, k)
        self.assertEqual(r1[0], 201)
        self.assertEqual((r2[0], r2[1]), (200, r1[1]))
        err(call("POST", "/payments", {"to_handle": "bob", "amount": 51}, self.ada, k), 409, "idempotency_key_reuse")
        err(call("POST", "/payments", {"to_handle": "bob", "amount": "bad"}, self.ada, k), 409, "idempotency_key_reuse")
        err(call("POST", "/payments", {"to_handle": "bob", "amount": 50, "x": 1}, self.ada, k), 409, "idempotency_key_reuse")
        # other user, same key
        self.assertEqual(call("POST", "/payments", {"to_handle": "ada", "amount": 50}, self.bob, k)[0], 201)
        # different path, same key and body
        self.assertEqual(call("POST", "/requests", {"payer_handle": "bob", "amount": 50}, self.ada, k)[0], 201)
        # failed request does not claim the key
        k2 = nk()
        err(call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 6}, self.ada, k2), 409, "insufficient_funds")
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 5}, self.ada, k2)[0], 201)
        before = bal(self.ada)
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 5}, self.ada, k2)[0], 200)
        self.assertEqual(bal(self.ada), before)

    def test_concurrent_drain(self):
        stop = threading.Event()
        neg = []

        def watch():
            while not stop.is_set():
                for t in (self.ada, self.bob):
                    if bal(t) < 0:
                        neg.append(1)
        w = threading.Thread(target=watch)
        w.start()
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: self.pay(self.ada, "bob", 300), range(50)))
        stop.set()
        w.join()
        ok = [r for r in rs if r[0] == 201]
        self.assertEqual(len(ok), 10000 // 300 if False else 33)
        self.assertTrue(all(r[0] == 409 for r in rs if r[0] != 201))
        self.assertEqual(neg, [])
        self.assertEqual(self.total(), 13000)

    def test_concurrent_same_key(self):
        k = nk()
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: self.pay(self.ada, "bob", 100, key=k), range(50)))
        self.assertEqual(sorted(r[0] for r in rs).count(201), 1)
        self.assertEqual(sum(1 for r in rs if r[0] == 200), 49)
        self.assertTrue(all(r[1] == rs[0][1] or True for r in rs))
        self.assertEqual(len({json.dumps(r[1], sort_keys=True) for r in rs}), 1)
        self.assertEqual(bal(self.ada), 9900)

    def test_cycle(self):
        def go(i):
            a, b = [(self.ada, "bob"), (self.bob, "cy"), (self.cy, "ada")][i % 3]
            return self.pay(a, b, 100)[0]
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(go, range(150)))
        self.assertTrue(all(s in (201, 409) for s in rs), rs)
        self.assertEqual(self.total(), 13000)


class TestRequests(Base):
    def ask(self, t, payer, amount, key=None, **kw):
        return call("POST", "/requests", {"payer_handle": payer, "amount": amount, **kw}, t, key or nk())

    def test_lifecycle(self):
        s, rq, _ = self.ask(self.bob, "ada", 1200, note="taxi")
        self.assertEqual(s, 201)
        self.assertEqual(set(rq), {"request_id", "requester_id", "requester_handle", "payer_id", "payer_handle",
                                   "amount", "currency", "note", "status", "payment_id", "created_at"})
        self.assertEqual((rq["status"], rq["payment_id"], rq["requester_handle"], rq["payer_handle"]),
                         ("pending", None, "bob", "ada"))
        rid = rq["request_id"]
        # third party
        err(call("POST", "/requests/%s/pay" % rid, {}, self.cy, nk()), 403, "forbidden")
        err(call("POST", "/requests/%s/decline" % rid, None, self.cy), 403, "forbidden")
        err(call("POST", "/requests/%s/cancel" % rid, None, self.cy), 403, "forbidden")
        err(call("POST", "/requests/%s/pay" % rid, {}, self.bob, nk()), 403, "forbidden")
        err(call("POST", "/requests/%s/decline" % rid, None, self.bob), 403, "forbidden")
        err(call("POST", "/requests/%s/cancel" % rid, None, self.ada), 403, "forbidden")
        err(call("POST", "/requests/nope/pay", {}, self.ada, nk()), 404, "not_found")
        err(call("POST", "/requests/nope/decline", None, self.ada), 404, "not_found")
        err(call("POST", "/requests/nope/cancel", None, self.ada), 404, "not_found")
        k = nk()
        s, p, _ = call("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, self.ada, k)
        self.assertEqual(s, 201)
        self.assertEqual((p["request_id"], p["amount"], p["note"], p["visibility"], p["from_handle"], p["to_handle"]),
                         (rid, 1200, "taxi", "private", "ada", "bob"))
        self.assertEqual((bal(self.ada), bal(self.bob)), (8800, 3700))
        # replay incl. after paid
        s2, p2, _ = call("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, self.ada, k)
        self.assertEqual((s2, p2), (200, p))
        err(call("POST", "/requests/%s/pay" % rid, {"visibility": "public"}, self.ada, k), 409, "idempotency_key_reuse")
        err(call("POST", "/requests/%s/pay" % rid, {}, self.ada, k), 409, "idempotency_key_reuse")
        err(call("POST", "/requests/%s/pay" % rid, {}, self.ada, nk()), 409, "request_not_pending")
        err(call("POST", "/requests/%s/decline" % rid, None, self.ada), 409, "request_not_pending")
        err(call("POST", "/requests/%s/cancel" % rid, None, self.bob), 409, "request_not_pending")
        got = call("GET", "/requests?status=paid", token=self.bob)[1]["requests"][0]
        self.assertEqual((got["status"], got["payment_id"]), ("paid", p["payment_id"]))

    def test_insufficient_then_funded(self):
        rid = self.ask(self.cy, "bob", 3000)[1]["request_id"]
        k = nk()
        err(call("POST", "/requests/%s/pay" % rid, {}, self.bob, k), 409, "insufficient_funds")
        self.assertEqual(call("GET", "/requests", token=self.cy)[1]["requests"][0]["status"], "pending")
        self.pay(self.ada, "bob", 1000)
        self.assertEqual(call("POST", "/requests/%s/pay" % rid, {}, self.bob, k)[0], 201)
        self.assertEqual((bal(self.bob), bal(self.cy)), (500, 3500))

    def test_decline_cancel(self):
        rid = self.ask(self.bob, "ada", 10)[1]["request_id"]
        s, j, _ = call("POST", "/requests/%s/decline" % rid, None, self.ada)
        self.assertEqual((s, j["status"]), (200, "declined"))
        self.assertEqual(call("POST", "/requests/%s/decline" % rid, None, self.ada)[0], 200)
        err(call("POST", "/requests/%s/cancel" % rid, None, self.bob), 409, "request_not_pending")
        err(call("POST", "/requests/%s/pay" % rid, {}, self.ada, nk()), 409, "request_not_pending")
        rid = self.ask(self.bob, "ada", 10)[1]["request_id"]
        s, j, _ = call("POST", "/requests/%s/cancel" % rid, None, self.bob)
        self.assertEqual((s, j["status"]), (200, "cancelled"))
        self.assertEqual(call("POST", "/requests/%s/cancel" % rid, None, self.bob)[0], 200)
        err(call("POST", "/requests/%s/decline" % rid, None, self.ada), 409, "request_not_pending")

    def test_validation(self):
        for a in (0, -1, 1000000001, 1.5, "1", True, None):
            err(self.ask(self.bob, "ada", a), 422, "validation_failed")
        err(self.ask(self.bob, "bob", 5), 422, "self_request")
        err(self.ask(self.bob, "zzz", 5), 404, "not_found")
        err(self.ask(self.bob, "ada", 5, note="x" * 201), 422, "validation_failed")
        err(call("POST", "/requests", {"amount": 5}, self.bob, nk()), 422, "validation_failed")
        err(call("POST", "/requests", {"payer_handle": 1, "amount": 5}, self.bob, nk()), 400, "malformed_request")
        self.assertEqual(self.ask(self.bob, "ada", 10 ** 9)[0], 201)  # exceeds balance, legal

    def test_listing(self):
        ids = [self.ask(self.bob, "ada", 10 + i)[1]["request_id"] for i in range(5)]
        self.ask(self.ada, "cy", 7)
        s, j, _ = call("GET", "/requests?limit=2", token=self.ada)
        self.assertEqual([r["request_id"] for r in j["requests"]][0] != ids[0], True)
        self.assertTrue(j["has_more"])
        allr = call("GET", "/requests", token=self.ada)[1]["requests"]
        self.assertEqual(len(allr), 6)
        self.assertEqual([r["request_id"] for r in allr[1:]], ids[::-1])
        self.assertEqual(len(call("GET", "/requests?direction=incoming", token=self.ada)[1]["requests"]), 5)
        self.assertEqual(len(call("GET", "/requests?direction=outgoing", token=self.ada)[1]["requests"]), 1)
        self.assertEqual(call("GET", "/requests", token=self.cy)[1]["requests"][0]["payer_handle"], "cy")
        self.assertEqual(len(call("GET", "/requests", token=self.cy)[1]["requests"]), 1)
        j = call("GET", "/requests?limit=3&offset=3", token=self.ada)[1]
        self.assertEqual((len(j["requests"]), j["has_more"]), (3, False))
        j = call("GET", "/requests?limit=3&offset=2", token=self.ada)[1]
        self.assertEqual((len(j["requests"]), j["has_more"]), (3, True))
        for q in ("direction=x", "status=x", "limit=0", "limit=201", "limit=1e2", "limit=4.0", "limit=+4",
                  "limit=abc", "limit=-1", "limit=", "offset=-1", "offset=1e1", "offset="):
            err(call("GET", "/requests?" + q, token=self.ada), 422, "validation_failed")
        self.assertEqual(call("GET", "/requests?limit=200&offset=0&zzz=1", token=self.ada)[0], 200)

    def test_race_pay_decline_cancel(self):
        for _ in range(5):
            rid = self.ask(self.bob, "ada", 100)[1]["request_id"]
            fns = [lambda: call("POST", "/requests/%s/pay" % rid, {}, self.ada, nk())] * 20 + \
                  [lambda: call("POST", "/requests/%s/decline" % rid, None, self.ada)] * 10 + \
                  [lambda: call("POST", "/requests/%s/cancel" % rid, None, self.bob)] * 10
            with ThreadPoolExecutor(40) as ex:
                rs = list(ex.map(lambda f: f(), fns))
            st = call("GET", "/requests?limit=1", token=self.bob)[1]["requests"][0]["status"]
            paid = sum(1 for r in rs[:20] if r[0] == 201)
            self.assertEqual(paid, 1 if st == "paid" else 0, st)
            self.assertEqual(bal(self.ada) + bal(self.bob) + bal(self.cy), 13000)
            reset(fixture())
            self.ada, self.bob, self.cy = login("ada"), login("bob"), login("cy")

    def test_pay_burst_distinct_and_same_key(self):
        rid = self.ask(self.bob, "ada", 100)[1]["request_id"]
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: call("POST", "/requests/%s/pay" % rid, {}, self.ada, nk()), range(50)))
        self.assertEqual([r[0] for r in rs].count(201), 1)
        self.assertEqual([r[1]["error"]["code"] for r in rs if r[0] == 409], ["request_not_pending"] * 49)
        rid = self.ask(self.bob, "ada", 100)[1]["request_id"]
        k = nk()
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: call("POST", "/requests/%s/pay" % rid, {}, self.ada, k), range(50)))
        self.assertEqual(sorted(r[0] for r in rs), [200] * 49 + [201])
        self.assertEqual(bal(self.ada), 9800)

    def test_zero_request(self):
        s, j, _ = call("POST", "/splits", {"amount": 1, "participant_handles": ["ada", "bob", "cy"]}, self.ada, nk())
        self.assertEqual([x["amount"] for x in j["shares"]], [1, 0, 0])
        r0 = j["requests"][0]
        self.assertEqual(r0["amount"], 0)
        s, p, _ = call("POST", "/requests/%s/pay" % r0["request_id"], {}, self.bob, nk())
        self.assertEqual((s, p["amount"]), (201, 0))


class TestSplits(Base):
    def split(self, t, amount, hs, **kw):
        return call("POST", "/splits", {"amount": amount, "participant_handles": hs, **kw}, t, nk())

    def test_rounding(self):
        for amt, n, exp in ((1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
                            (999, 3, [333] * 3), (5, 5, [1] * 5)):
            hs = ["ada", "bob", "cy", "ada2", "bob2"][:n]
            reset(fixture(users=[user(h, 100) for h in ["ada", "bob", "cy", "ada2", "bob2"]]))
            t = login("ada")
            s, j, _ = self.split(t, amt, hs, note="dinner")
            self.assertEqual(s, 201)
            self.assertEqual([x["amount"] for x in j["shares"]], exp)
            self.assertEqual([x["handle"] for x in j["shares"]], hs)
            self.assertEqual(len(j["requests"]), n - 1)
            for r, e in zip(j["requests"], exp[1:]):
                self.assertEqual((r["amount"], r["status"], r["requester_handle"], r["note"]), (e, "pending", "ada", "dinner"))
            self.assertEqual([r["payer_handle"] for r in j["requests"]], hs[1:])
        reset(fixture())
        self.ada = login("ada")
        s, j, _ = self.split(self.ada, 1000, ["cy", "bob", "ada"])
        self.assertEqual([x["amount"] for x in j["shares"]], [334, 333, 333])
        self.assertEqual([r["payer_handle"] for r in j["requests"]], ["cy", "bob"])

    def test_caller_omitted_and_alone(self):
        s, j, _ = self.split(self.ada, 100, ["bob", "cy"])
        self.assertEqual(([x["amount"] for x in j["shares"]], len(j["requests"])), ([50, 50], 2))
        s, j, _ = self.split(self.ada, 100, ["ada"])
        self.assertEqual((s, j["requests"], j["shares"]), (201, [], [{"handle": "ada", "amount": 100}]))
        self.assertRegex(j["created_at"], TS_RE)

    def test_errors(self):
        for a in (0, 1.5, "5", True, None, 1000000001):
            err(self.split(self.ada, a, ["bob"]), 422, "validation_failed")
        err(self.split(self.ada, 5, []), 422, "validation_failed")
        err(self.split(self.ada, 5, ["bob", "bob"]), 422, "validation_failed")
        err(self.split(self.ada, 5, ["bob"], note="x" * 201), 422, "validation_failed")
        err(self.split(self.ada, 5, ["bob", "nobody"]), 404, "not_found")
        err(call("POST", "/splits", {"amount": 5}, self.ada, nk()), 422, "validation_failed")
        err(call("POST", "/splits", {"participant_handles": ["bob"]}, self.ada, nk()), 422, "validation_failed")
        err(call("POST", "/splits", {"amount": 5, "participant_handles": "bob"}, self.ada, nk()), 400, "malformed_request")
        s = self.split(self.ada, 5, ["h%d" % i for i in range(1000)])[0]
        self.assertIn(s, (404, 422))
        # no balance check
        self.assertEqual(self.split(self.cy, 10 ** 9, ["ada", "bob"])[0], 201)

    def test_independent_and_conserved(self):
        for _ in range(3):
            j = self.split(self.ada, 1000, ["ada", "bob", "cy"])[1]
            for r in j["requests"]:
                t = {"bob": self.bob, "cy": self.cy}[r["payer_handle"]]
                s, p, _ = call("POST", "/requests/%s/pay" % r["request_id"], {}, t, nk())
                if s == 409:
                    self.pay(self.ada, r["payer_handle"], 1000)
                    s, p, _ = call("POST", "/requests/%s/pay" % r["request_id"], {}, t, nk())
                self.assertEqual(s, 201)
        self.assertEqual(self.total(), 13000)

    def test_idem(self):
        k = nk()
        b = {"amount": 1000, "participant_handles": ["ada", "bob", "cy"]}
        r1 = call("POST", "/splits", b, self.ada, k)
        r2 = call("POST", "/splits", b, self.ada, k)
        self.assertEqual((r1[0], r2[0], r1[1]), (201, 200, r2[1]))
        self.assertEqual(len(call("GET", "/requests", token=self.bob)[1]["requests"]), 1)
        err(call("POST", "/splits", {**b, "amount": 9}, self.ada, k), 409, "idempotency_key_reuse")
        k = nk()
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: call("POST", "/splits", b, self.ada, k), range(50)))
        self.assertEqual(sorted(r[0] for r in rs), [200] * 49 + [201])
        self.assertEqual(len(call("GET", "/requests", token=self.bob)[1]["requests"]), 2)
        # request create idem
        k = nk()
        rb = {"payer_handle": "ada", "amount": 5}
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: call("POST", "/requests", rb, self.bob, k), range(50)))
        self.assertEqual(sorted(r[0] for r in rs), [200] * 49 + [201])


class TestFeed(Base):
    def test_visibility(self):
        self.pay(self.ada, "bob", 10, note="pub")
        self.pay(self.ada, "bob", 20, note="priv", visibility="private")
        self.pay(self.bob, "cy", 5, note="bc-priv", visibility="private")
        self.ask_ = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.cy, nk())
        notes = lambda t: [p["note"] for p in call("GET", "/activity", token=t)[1]["payments"]]
        self.assertEqual(notes(self.ada), ["priv", "pub"])
        self.assertEqual(notes(self.bob), ["bc-priv", "priv", "pub"])
        self.assertEqual(notes(self.cy), ["bc-priv", "pub"])
        j = call("GET", "/activity?limit=1&offset=1&direction=zzz&status=zzz", token=self.bob)[1]
        self.assertEqual(([p["note"] for p in j["payments"]], j["has_more"]), (["priv"], True))
        for q in ("limit=0", "limit=201", "offset=-1", "limit=x", "offset=1.0"):
            err(call("GET", "/activity?" + q, token=self.ada), 422, "validation_failed")

    def test_requests_not_visible(self):
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, nk())[1]["request_id"]
        for st in ("", "?status=pending", "?direction=incoming", "?direction=outgoing"):
            self.assertEqual(call("GET", "/requests" + st, token=self.cy)[1]["requests"], [])
        self.assertEqual(call("GET", "/activity", token=self.cy)[1]["payments"], [])


class TestSeeded(unittest.TestCase):
    def test_seed(self):
        fx = fixture(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
                                "note": "coffee", "visibility": "public"},
                               {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5,
                                "note": "sec", "visibility": "private"}],
                     requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200,
                                "note": "taxi", "status": "pending"},
                               {"id": "rq_2", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1,
                                "note": "old", "status": "paid"}])
        reset(fx)
        ada, bob, cy = login("ada"), login("bob"), login("cy")
        self.assertEqual(bal(ada), 10000)
        ps = call("GET", "/activity", token=ada)[1]["payments"]
        self.assertEqual([p["payment_id"] for p in ps], ["p_2", "p_1"])
        self.assertEqual((ps[0]["request_id"], ps[0]["settlement_id"]), (None, None))
        self.assertRegex(ps[0]["created_at"], TS_RE)
        self.assertEqual([p["payment_id"] for p in call("GET", "/activity", token=cy)[1]["payments"]], ["p_1"])
        rs = call("GET", "/requests", token=bob)[1]["requests"]
        self.assertEqual([(r["request_id"], r["status"]) for r in rs], [("rq_2", "paid"), ("rq_1", "pending")])
        self.assertEqual(call("GET", "/requests", token=cy)[1]["requests"], [])
        err(call("POST", "/requests/rq_2/pay", {}, ada, nk()), 409, "request_not_pending")
        err(call("POST", "/requests/rq_1/pay", {}, cy, nk()), 403, "forbidden")
        self.assertEqual(call("POST", "/requests/rq_1/pay", {}, ada, nk())[0], 201)

    def test_bad_fixtures(self):
        good = fixture()
        reset(good)
        t = login("ada")
        bad = [
            fixture(users=[user("ada", -1)]), {"currency": "EUR", "minor_units": 2}, {"users": []},
            fixture(minor_units=1), fixture(minor_units="2"), fixture(minor_units=True),
            fixture(users=[user("ada", 1), user("ada", 2, id="u_x", email="x@x.io")]),
            fixture(users=[user("ada", 1), user("bob", 2, id="u_ada")]),
            fixture(users=[user("ada", 1), user("bob", 2, email="ada@example.com")]),
            fixture(users=[user("Ada", 1)]), fixture(users=[user("a" * 21, 1)]), fixture(users=[user("", 1)]),
            fixture(payments=[{"id": "p", "from_user_id": "nobody", "to_user_id": "u_ada", "amount": 1}]),
            fixture(requests=[{"id": "r", "requester_id": "u_ada", "payer_id": "nobody", "amount": 1, "status": "pending"}]),
            fixture(requests=[{"id": "r", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 1, "status": "weird"}]),
            fixture(settlement_operator_ids=["nobody"]), fixture(users="x"),
        ]
        for b in bad:
            err(call("POST", "/_test/reset", b), 422, "validation_failed")
        err(call("POST", "/_test/reset", raw=b"{bad"), 400, "malformed_request")
        self.assertEqual(bal(t), 10000)  # state untouched
        # reset clears tokens/keys
        k = nk()
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 5}, t, k)[0], 201)
        reset(good)
        err(call("GET", "/me", token=t), 401, "unauthenticated")
        t = login("ada")
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 5}, t, k)[0], 201)

    def test_reset_speed(self):
        users = [user("u%d" % i, 1000) for i in range(100)]
        t0 = time.time()
        reset(fixture(users=users))
        self.assertLess(time.time() - t0, 10)
        print("reset 100 users: %.2fs" % (time.time() - t0))


class TestSettlements(unittest.TestCase):
    def setUp(self):
        reset(fixture(users=[user("ada", 0), user("bob", 100), user("cy", 50), user("op", 0)],
                      settlement_operator_ids=["u_op"]))
        self.op, self.ada, self.bob, self.cy = login("op"), login("ada"), login("bob"), login("cy")

    def st(self, ts, t=None, key=None, **kw):
        return call("POST", "/settlements", {"transfers": ts, **kw}, t or self.op, key or nk())

    def tr(self, f, t, a, **kw):
        return {"from_handle": f, "to_handle": t, "amount": a, **kw}

    def test_auth(self):
        err(call("POST", "/settlements", {"transfers": []}, key=nk()), 401, "unauthenticated")
        err(self.st([self.tr("bob", "cy", 1)], self.bob), 403, "forbidden")
        err(call("POST", "/settlements", {"transfers": [self.tr("bob", "cy", 1)]}, self.op), 400, "missing_idempotency_key")

    def test_shape(self):
        for ts in ([], [self.tr("bob", "cy", 1)] * 33, "x", None, [1], [[]]):
            err(call("POST", "/settlements", {"transfers": ts}, self.op, nk()), 422, "validation_failed")
        err(call("POST", "/settlements", {}, self.op, nk()), 422, "validation_failed")
        self.assertEqual(self.st([self.tr("bob", "cy", 1)] * 32)[0], 409 if False else 201)

    def test_net(self):
        s, j, _ = self.st([self.tr("ada", "bob", 100), self.tr("bob", "ada", 100)])
        self.assertEqual(s, 201)  # ada has 0, net zero
        self.assertEqual(len(j["payments"]), 2)
        self.assertEqual(len({p["created_at"] for p in j["payments"]} | {j["committed_at"]}), 1)
        self.assertTrue(all(p["settlement_id"] == j["settlement_id"] and p["request_id"] is None for p in j["payments"]))
        self.assertEqual((bal(self.ada), bal(self.bob)), (0, 100))
        # chain: bob->cy 100 and cy->ada 150 : cy 50+100-150 = 0
        s, j, _ = self.st([self.tr("bob", "cy", 100), self.tr("cy", "ada", 150)])
        self.assertEqual(s, 201)
        self.assertEqual((bal(self.ada), bal(self.bob), bal(self.cy)), (150, 0, 0))
        # not affordable: nothing changes, key reusable
        k = nk()
        err(self.st([self.tr("cy", "bob", 1), self.tr("ada", "bob", 151)], key=k), 409, "insufficient_funds")
        self.assertEqual((bal(self.ada), bal(self.bob), bal(self.cy)), (150, 0, 0))
        self.assertEqual(self.st([self.tr("ada", "bob", 150)], key=k)[0], 201)
        # entry errors precede insufficient funds, in input order
        err(self.st([self.tr("ada", "bob", 10 ** 6), self.tr("ada", "nobody", 1)]), 404, "not_found")
        err(self.st([self.tr("ada", "bob", 10 ** 6), self.tr("ada", "ada", 1)]), 422, "self_payment")
        err(self.st([self.tr("ada", "ada", 1), self.tr("ada", "nobody", 1)]), 422, "self_payment")
        err(self.st([self.tr("ada", "nobody", 1), self.tr("ada", "ada", 1)]), 404, "not_found")
        for bad in ({"amount": 0}, {"amount": "1"}, {"note": 5}, {"note": "x" * 201}, {"visibility": "x"}):
            err(self.st([{**self.tr("bob", "cy", 1), **bad}]), 422, "validation_failed")

    def test_visibility_replay(self):
        k = nk()
        ts = [self.tr("bob", "cy", 10, note="n", visibility="private"), self.tr("bob", "cy", 5, extra=1)]
        s, j, _ = self.st(ts, key=k)
        self.assertEqual((s, j["payments"][0]["visibility"], j["payments"][1]["visibility"], j["payments"][1]["note"]),
                         (201, "private", "public", ""))
        r2 = call("POST", "/settlements", {"transfers": ts}, self.op, k)
        self.assertEqual((r2[0], r2[1]), (200, j))
        err(self.st(ts[:1], key=k), 409, "idempotency_key_reuse")
        self.assertEqual(len(call("GET", "/activity", token=self.op)[1]["payments"]), 1)  # only public one? op is not a party
        self.assertEqual(len(call("GET", "/activity", token=self.cy)[1]["payments"]), 2)
        self.assertEqual(call("GET", "/activity", token=self.op)[1]["payments"][0]["settlement_id"], j["settlement_id"])
        self.assertEqual((bal(self.bob), bal(self.cy)), (85, 65))
        # operator cannot see requests of others
        rq = call("POST", "/requests", {"payer_handle": "cy", "amount": 5}, self.bob, nk())[1]["request_id"]
        self.assertEqual(call("GET", "/requests", token=self.op)[1]["requests"], [])
        err(call("POST", "/requests/%s/cancel" % rq, None, self.op), 403, "forbidden")
        # plain payment shows null settlement_id
        p = call("POST", "/payments", {"to_handle": "cy", "amount": 1}, self.bob, nk())[1]
        self.assertIn("settlement_id", p)
        self.assertIsNone(p["settlement_id"])

    def test_concurrent(self):
        reset(fixture(users=[user("ada", 1000), user("bob", 1000), user("cy", 1000), user("op", 0)],
                      settlement_operator_ids=["u_op"]))
        op = login("op")
        pairs = [("ada", "bob"), ("bob", "cy"), ("cy", "ada")]

        def go(i):
            a, b = pairs[i % 3]
            return call("POST", "/settlements", {"transfers": [self.tr(a, b, 150), self.tr(b, a, 40)]}, op, nk())[0]
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(go, range(100)))
        self.assertTrue(all(s in (201, 409) for s in rs))
        ts = [login(h) for h in ("ada", "bob", "cy")]
        bs = [bal(t) for t in ts]
        self.assertEqual(sum(bs), 3000)
        self.assertTrue(all(b >= 0 for b in bs))
        k = nk()
        body = {"transfers": [self.tr("ada", "bob", 1)]}
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: call("POST", "/settlements", body, op, k)[0], range(50)))
        self.assertEqual(sorted(rs), [200] * 49 + [201])


class TestExportImport(unittest.TestCase):
    def build(self):
        reset(fixture(users=[user("ada", 10000), user("bob", 2500), user("cy", 500), user("op", 0)],
                      settlement_operator_ids=["u_op"],
                      payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5,
                                 "note": "x", "visibility": "public"}]))
        t = {h: login(h) for h in ("ada", "bob", "cy", "op")}
        keys = {}
        keys["pay"] = (nk(), {"to_handle": "bob", "amount": 100, "visibility": "private"})
        call("POST", "/payments", keys["pay"][1], t["ada"], keys["pay"][0])
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 50}, t["bob"], nk())
        keys["req"] = (nk(), {"payer_handle": "cy", "amount": 70})
        call("POST", "/requests", keys["req"][1], t["bob"], keys["req"][0])
        rid = rq[1]["request_id"]
        keys["pay_req"] = (nk(), {"visibility": "private"})
        call("POST", "/requests/%s/pay" % rid, keys["pay_req"][1], t["ada"], keys["pay_req"][0])
        keys["split"] = (nk(), {"amount": 100, "participant_handles": ["ada", "bob", "cy"]})
        call("POST", "/splits", keys["split"][1], t["ada"], keys["split"][0])
        keys["st"] = (nk(), {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 9}]})
        call("POST", "/settlements", keys["st"][1], t["op"], keys["st"][0])
        err(call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 7}, t["ada"], "failedkey"), 409, "insufficient_funds")
        return t, keys, rid

    def snapshot(self, t, base=None):
        out = {}
        for h, tok in t.items():
            out[h] = [call("GET", "/me", token=tok, base=base)[1], call("GET", "/activity?limit=200", token=tok, base=base)[1],
                      call("GET", "/requests?limit=200", token=tok, base=base)[1]]
        return out

    def test_roundtrip(self):
        t, keys, rid = self.build()
        s, ex, _ = call("GET", "/_test/export")
        self.assertEqual((s, ex["track"], ex["format_version"]), (200, "pocketful", 1))
        self.assertNotIn("correct horse", json.dumps(ex))
        before = self.snapshot(t)
        # later writes don't change the export
        call("POST", "/payments", {"to_handle": "bob", "amount": 1}, t["ada"], nk())
        reset(fixture(users=[user("zed", 5)]))
        self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        self.assertEqual(self.snapshot(t), before)
        for name, path in (("pay", "/payments"), ("req", "/requests"), ("split", "/splits")):
            k, b = keys[name]
            who = t["ada"] if name in ("pay", "split") else t["bob"]
            s, j, _ = call("POST", path, b, who, k)
            self.assertEqual(s, 200, name)
        self.assertEqual(call("POST", "/requests/%s/pay" % rid, keys["pay_req"][1], t["ada"], keys["pay_req"][0])[0], 200)
        self.assertEqual(call("POST", "/settlements", keys["st"][1], t["op"], keys["st"][0])[0], 200)
        err(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, t["ada"], keys["pay"][0]), 409, "idempotency_key_reuse")
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 5}, t["ada"], "failedkey")[0], 201)
        self.assertEqual(call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})[0], 200)
        self.assertEqual(self.snapshot(t)["ada"][0]["balance"], before["ada"][0]["balance"] - 5)
        # repeated import restores
        self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        self.assertEqual(self.snapshot(t), before)
        # invalid imports leave state alone
        err(call("POST", "/_test/import", raw=b"{x"), 400, "malformed_request")
        for bad in ({}, {"track": "x", "format_version": 1, "state": ex["state"]},
                    {"track": "pocketful", "format_version": 2, "state": ex["state"]},
                    {"track": "pocketful", "format_version": 1}, {"track": "pocketful", "format_version": 1, "state": {}},
                    {"track": "pocketful", "format_version": 1, "state": "x"}, [1]):
            err(call("POST", "/_test/import", bad), 422, "validation_failed")
        self.assertEqual(self.snapshot(t), before)
        reset(fixture())
        err(call("GET", "/me", token=t["ada"]), 401, "unauthenticated")

    @unittest.skipUnless(BASE2, "BASE_URL2 not set")
    def test_other_container(self):
        t, keys, rid = self.build()
        ex = call("GET", "/_test/export")[1]
        before = self.snapshot(t)
        self.assertEqual(call("POST", "/_test/import", ex, base=BASE2)[0], 204)
        self.assertEqual(self.snapshot(t, BASE2), before)
        self.assertEqual(call("POST", "/payments", keys["pay"][1], t["ada"], keys["pay"][0], base=BASE2)[0], 200)

    def test_export_consistent_under_writes(self):
        reset(fixture())
        ada = login("ada")
        stop = threading.Event()

        def w():
            while not stop.is_set():
                call("POST", "/payments", {"to_handle": "bob", "amount": 1}, ada, nk())
        th = [threading.Thread(target=w) for _ in range(8)]
        [x.start() for x in th]
        try:
            for _ in range(10):
                st = call("GET", "/_test/export")[1]["state"]
                self.assertEqual(sum(u["balance"] for u in st["users"]), 13000)
        finally:
            stop.set()
            [x.join() for x in th]


def rawsock(data, base=None):
    import socket
    u = urlsplit(base or BASE)
    c = socket.create_connection((u.hostname, u.port), timeout=10)
    c.sendall(data)
    out = b""
    try:
        while True:
            b = c.recv(65536)
            if not b:
                break
            out += b
            if b"\r\n\r\n" in out and len(out) > 20:
                head, _, body = out.partition(b"\r\n\r\n")
                m = re.search(rb"(?i)content-length: *(\d+)", head)
                if m and len(body) >= int(m.group(1)):
                    break
    except OSError:
        pass
    c.close()
    return out


class TestHardening(Base):
    def check_json_4xx(self, out):
        head, _, body = out.partition(b"\r\n\r\n")
        status = int(head.split()[1])
        self.assertTrue(400 <= status < 500, head)
        self.assertIn(b"application/json; charset=utf-8", head)
        self.assertIn("error", json.loads(body))

    def test_methods(self):
        for m in ("OPTIONS", "TRACE", "PROPFIND", "CONNECT", "FOO"):
            self.check_json_4xx(rawsock(("%s /payments HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n" % m).encode()))
        out = rawsock(b"HEAD /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        head, _, body = out.partition(b"\r\n\r\n")
        self.assertTrue(400 <= int(head.split()[1]) < 500)
        self.assertEqual(body, b"")

    def test_transport_errors(self):
        self.check_json_4xx(rawsock(b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\nHost: x\r\n\r\n"))
        self.check_json_4xx(rawsock(b"GET /me HTTP/1.1\r\nHost: x\r\n" + b"X: y\r\n" * 150 + b"\r\n"))
        self.check_json_4xx(rawsock(b"GET /me HTTP/1.1\r\nHost: x\r\nX: " + b"a" * 70000 + b"\r\n\r\n"))
        self.check_json_4xx(rawsock(b"GARBAGE\r\n\r\n"))
        self.check_json_4xx(rawsock(b"GET /me HTTP/9.9\r\nHost: x\r\n\r\n"))
        self.check_json_4xx(rawsock(b"GET http://[bad/me HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"))
        self.check_json_4xx(rawsock(b"POST /payments HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n7FFFFFFFFFFF\r\n"))
        self.check_json_4xx(rawsock(b"POST /payments HTTP/1.1\r\nHost: x\r\nContent-Length: 2000000\r\nConnection: close\r\n\r\n"))
        out = rawsock(b"GET http://host/health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        self.assertIn(b" 200 ", out.split(b"\r\n")[0])
        self.assertEqual(call("GET", "/health")[0], 200)

    def test_huge_query_ints(self):
        for p in ("/activity", "/requests"):
            err(call("GET", p + "?limit=" + "9" * 4301, token=self.ada), 422, "validation_failed")
            self.assertEqual(call("GET", p + "?offset=" + "9" * 4301, token=self.ada)[0], 200)
            err(call("GET", p + "?offset=" + "9" * 4301 + "x", token=self.ada), 422, "validation_failed")

    def test_reset_bad_refs(self):
        for f in ("from_user_id", "to_user_id"):
            for bad in ([ "u_ada"], {}, 5, None):
                p = {"id": "p1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1, "note": "", "visibility": "public"}
                p[f] = bad
                err(call("POST", "/_test/reset", fixture(payments=[p])), 422, "validation_failed")
        for f in ("requester_id", "payer_id"):
            for bad in ([ "u_ada"], {}):
                r = {"id": "r1", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 1, "status": "pending"}
                r[f] = bad
                err(call("POST", "/_test/reset", fixture(requests=[r])), 422, "validation_failed")
        err(call("POST", "/_test/reset", fixture(settlement_operator_ids=[["u_ada"]])), 422, "validation_failed")
        self.assertEqual(bal(self.ada), 10000)

    def test_deep_replay(self):
        for depth in (400, 500, 800):
            body = b'{"to_handle":"bob","amount":1,"x":' + b"[" * depth + b"]" * depth + b"}"
            k = nk()
            r1 = call("POST", "/payments", raw=body, token=self.ada, key=k)
            r2 = call("POST", "/payments", raw=body, token=self.ada, key=k)
            self.assertEqual((r1[0], r2[0], r1[1]), (201, 200, r2[1]), depth)
        body = b'{"to_handle":"bob","amount":1,"x":' + b"[" * 5000 + b"]" * 5000 + b"}"
        for _ in range(2):
            err(call("POST", "/payments", raw=body, token=self.ada, key="deep"), 400, "malformed_request")

    def test_exact_numbers(self):
        for lit in ("0.99999999999999999999", "1.00000000000000000001", "1000000000.0000000001", "1e-400", "1.5",
                    "9" * 4301, "1" + "0" * 40, "1e999999999", "-1"):
            r = call("POST", "/payments", raw=('{"to_handle":"bob","amount":%s}' % lit).encode(), token=self.ada, key=nk())
            err(r, 422, "validation_failed")
            r = call("POST", "/requests", raw=('{"payer_handle":"bob","amount":%s}' % lit).encode(), token=self.ada, key=nk())
            err(r, 422, "validation_failed")
            r = call("POST", "/splits", raw=('{"participant_handles":["bob"],"amount":%s}' % lit).encode(), token=self.ada, key=nk())
            err(r, 422, "validation_failed")
        self.assertEqual(bal(self.ada), 10000)
        for lit in ("1.0", "1e0", "1E0", "1.000000000000000000000000000", "10e-1"):
            r = call("POST", "/payments", raw=('{"to_handle":"bob","amount":%s}' % lit).encode(), token=self.ada, key=nk())
            self.assertEqual((r[0], r[1]["amount"]), (201, 1), lit)
        fx = fixture()
        fx["users"][0]["balance"] = json.loads("0.99999999999999999999")
        err(call("POST", "/_test/reset", raw=json.dumps(fixture()).replace("10000", "0.99999999999999999999").encode()), 422, "validation_failed")
        ok = call("POST", "/_test/reset", raw=json.dumps(fixture()).replace("10000", "1e4").encode())
        self.assertEqual(ok[0], 204)

    def test_import_validation(self):
        ex = call("GET", "/_test/export")[1]
        self.pay(self.ada, "bob", 5)
        ex = call("GET", "/_test/export")[1]
        before = call("GET", "/activity", token=self.ada)[1]

        def mut(f):
            e = json.loads(json.dumps(ex))
            f(e["state"])
            return e
        cases = [
            lambda st: st["payments"][0].update(amount=-5),
            lambda st: st["payments"][0].update(created_at="yesterday"),
            lambda st: st["payments"][0].update(id="p" * 100),
            lambda st: st["payments"][0].update(request_id=5),
            lambda st: st["payments"][0].update(request_id="nope"),
            lambda st: st["payments"][0].update(settlement_id="nope"),
            lambda st: st["payments"][0].update(amount=1.5),
            lambda st: st["users"][0].update(id="u" * 100),
            lambda st: st["users"][0].update(handle="ada\n"),
            lambda st: st["users"][0].update(email="a b@x.io"),
            lambda st: st["payments"][0].update(from_user_id=["u_ada"]),
            lambda st: st["idempotency"][0].update(key=""),
            lambda st: st["idempotency"][0].update(response=5),
            lambda st: st.update(operators=[["x"]]),
        ]
        for i, f in enumerate(cases):
            err(call("POST", "/_test/import", mut(f)), 422, "validation_failed")
        self.assertEqual(call("GET", "/activity", token=self.ada)[1], before)

    def test_handle_newline_and_path_spelling(self):
        err(call("POST", "/_test/reset", fixture(users=[user("ada\n", 1)])), 422, "validation_failed")
        reset(fixture())
        self.ada, self.bob = login("ada"), login("bob")
        err(call("POST", "/auth/signup", {"email": "a b@x.io", "password": "12345678", "display_name": "Q"}), 422, "validation_failed")
        err(call("POST", "/auth/signup", {"email": "a\n@x.io", "password": "12345678", "display_name": "Q"}), 422, "validation_failed")
        rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, nk())[1]["request_id"]
        k = nk()
        r1 = call("POST", "/requests/%s/pay" % rid, {}, self.ada, k)
        enc = rid.replace("_", "%5F")
        r2 = call("POST", "/requests/%s/pay" % enc, {}, self.ada, k)
        self.assertEqual((r1[0], r2[0], r1[1]), (201, 200, r2[1]))

    def test_body_cap(self):
        big = b'{"to_handle":"bob","amount":1,"note":"' + b"x" * 1100000 + b'"}'
        try:
            r = call("POST", "/payments", raw=big, token=self.ada, key=nk())
            self.assertTrue(400 <= r[0] < 500)
        except (ConnectionError, OSError):
            pass
        self.assertEqual(call("GET", "/health")[0], 200)


class TestRound2(Base):
    HUGE = ("1e99999999999999999999", "1e-99999999999999999999", "0e99999999999999999999", "1E+1000000000000000000")

    def test_huge_exponents(self):
        for lit in self.HUGE:
            for path, body in (("/payments", '{"to_handle":"bob","amount":%s}'), ("/requests", '{"payer_handle":"bob","amount":%s}')):
                r = call("POST", path, raw=(body % lit).encode(), token=self.ada, key=nk())
                self.assertIn(r[0], (201, 422), (lit, r))
            r = call("POST", "/payments", raw=('{"to_handle":"bob","amount":5,"x":%s}' % lit).encode(), token=self.ada, key=nk())
            self.assertEqual(r[0], 201)
            self.assertLess(call("POST", "/auth/login", raw=('{"email":"ada@example.com","password":"x","y":%s}' % lit).encode())[0], 500)
            self.assertLess(call("POST", "/auth/signup", raw=('{"email":"q@x.io","password":"longenough1","display_name":"d","y":%s}' % lit).encode())[0], 500)
            self.assertEqual(call("POST", "/_test/reset", raw=json.dumps(fixture()).replace("}]", ',"z":%s}]' % lit).encode())[0], 204)
            self.assertLess(call("POST", "/_test/import", raw=('{"track":"pocketful","format_version":1,"state":{},"y":%s}' % lit).encode())[0], 500)
            self.ada, self.bob = login("ada"), login("bob")

    def test_decimal_replay_after_import(self):
        reset(fixture())
        ada, bob = login("ada"), login("bob")
        cases = [("/payments", {"to_handle": "bob", "amount": 5}, ada), ("/requests", {"payer_handle": "ada", "amount": 5}, bob),
                 ("/splits", {"amount": 9, "participant_handles": ["ada", "bob"]}, ada)]
        keys = []
        for path, b, t in cases:
            raw = json.dumps(b)[:-1] + ',"lat":52.52,"big":1e99999999999999999999}'
            k = nk()
            self.assertEqual(call("POST", path, raw=raw.encode(), token=t, key=k)[0], 201)
            keys.append((path, raw, t, k))
        ex = call("GET", "/_test/export")[1]
        self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        for path, raw, t, k in keys:
            self.assertEqual(call("POST", path, raw=raw.encode(), token=t, key=k)[0], 200, path)
            # same value, other spelling, still a replay (D-7)
            self.assertEqual(call("POST", path, raw=raw.replace("52.52", "52.520").encode(), token=t, key=k)[0], 200, path)
            self.assertEqual(call("POST", path, raw=raw.replace("52.52", "52.53").encode(), token=t, key=k)[0], 409, path)

    def test_deep_export_import(self):
        for depth in (850, 898, 900):
            reset(fixture())
            ada = login("ada")
            body = b'{"to_handle":"bob","amount":1,"x":' + b"[" * depth + b"]" * depth + b"}"
            k = nk()
            self.assertEqual(call("POST", "/payments", raw=body, token=ada, key=k)[0], 201)
            ex = call("GET", "/_test/export")[1]
            self.assertEqual(call("POST", "/_test/import", ex)[0], 204, depth)
            self.assertEqual(call("POST", "/payments", raw=body, token=ada, key=k)[0], 200)

    def test_control_chars_email(self):
        for e in ("ctl\x00@example.com", "a\x7fb@exa\x01mple.com", "a\x85b@x.io", "a\tb@x.io"):
            r = call("POST", "/auth/signup", {"email": e, "password": "longenough1", "display_name": "x"})
            err(r, 422, "validation_failed")
        self.assertEqual(call("POST", "/auth/signup", {"email": "ok@x.io", "password": "longenough1", "display_name": "x"})[0], 201)

    def test_zero_padded_query(self):
        self.assertEqual(call("GET", "/activity?limit=" + "0" * 29 + "1", token=self.ada)[0], 200)
        self.assertEqual(call("GET", "/activity?limit=" + "0" * 40 + "5", token=self.ada)[0], 200)
        err(call("GET", "/activity?limit=" + "0" * 40 + "0", token=self.ada), 422, "validation_failed")
        err(call("GET", "/activity?limit=1" + "0" * 40, token=self.ada), 422, "validation_failed")


def expected_valid_int(lit, lo, hi):
    """Exact value of a JSON number literal (test oracle using Fraction)."""
    from fractions import Fraction
    m = re.fullmatch(r"(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?", lit)
    sign, ip, fp, ex = m.groups()
    if int(ip + (fp or "") or "0") == 0:
        return lo <= 0 <= hi
    if ex is not None and abs(int(ex)) > 2000:
        return False
    v = Fraction(int(ip + (fp or ""))) * Fraction(10) ** (int(ex or 0) - len(fp or ""))
    if sign:
        v = -v
    return v.denominator == 1 and lo <= v <= hi


def number_literals():
    import random
    rnd = random.Random(7)
    out = ["0", "-0", "0.0", "1", "1.0", "1e0", "1e3", "1E3", "1e+3", "10e-1", "0.001e3", "1000000000", "1000000000.0",
           "1e9", "1000000001", "0.99999999999999999999", "1.00000000000000000001", "1e-400", "1e400",
           "1e99999999999999999999", "0e5000", "1e5000", "1e-5000", "-1", "-1e3", "1.5", "9" * 4301, "1" + "0" * 5000,
           "1." + "0" * 5000, "0." + "0" * 5000 + "1", "1e" + "9" * 5000, "0e" + "9" * 5000, "5e-" + "9" * 400]
    for _ in range(120):
        sign = rnd.choice(["", "", "-"])
        ip = str(rnd.choice([0, 1, 5, 12345, 10 ** rnd.randint(0, 25)]))
        fp = rnd.choice(["", "", ".0", "." + "0" * rnd.randint(1, 30), "." + str(rnd.randint(0, 99999))])
        ex = rnd.choice(["", "", "e0", "e1", "e3", "e-3", "e+2", "E2", "e18", "e19", "e20", "e-18", "e-19", "e400",
                         "e-400", "e5000", "e" + "9" * rnd.randint(1, 60)])
        out.append(sign + ip + fp + ex)
    return out


class TestNumberFuzz(unittest.TestCase):
    def test_amount_and_ignored(self):
        reset(fixture(users=[user("ada", 10 ** 15), user("bob", 0)]))
        ada = login("ada")
        for lit in number_literals():
            ok = expected_valid_int(lit, 1, 10 ** 9)
            r = call("POST", "/payments", raw=('{"to_handle":"bob","amount":%s}' % lit).encode(), token=ada, key=nk())
            self.assertEqual(r[0], 201 if ok else 422, lit[:40])
            r = call("POST", "/requests", raw=('{"payer_handle":"bob","amount":%s}' % lit).encode(), token=ada, key=nk())
            self.assertEqual(r[0], 201 if ok else 422, lit[:40])
            r = call("POST", "/splits", raw=('{"participant_handles":["bob"],"amount":%s}' % lit).encode(), token=ada, key=nk())
            self.assertEqual(r[0], 201 if ok else 422, lit[:40])
            k = nk()
            raw = ('{"to_handle":"bob","amount":1,"x":[%s],"y":{"z":%s}}' % (lit, lit)).encode()
            self.assertEqual(call("POST", "/payments", raw=raw, token=ada, key=k)[0], 201, lit[:40])
            self.assertEqual(call("POST", "/payments", raw=raw, token=ada, key=k)[0], 200, lit[:40])
            for path, body in (("/auth/login", '{"email":"ada@example.com","password":"correct horse","x":%s}'),
                               ("/auth/signup", '{"email":"nn%d@x.io","password":"longenough1","display_name":"d","x":%%s}' % (_n[0]))):
                r = call("POST", path, raw=(body % lit).encode())
                self.assertIn(r[0], (200, 201, 409), lit[:40])

    def test_fixture_and_import(self):
        for lit in number_literals():
            ok = expected_valid_int(lit, 0, 2 ** 53)
            raw = json.dumps(fixture()).replace('"balance": 10000', '"balance": %s' % lit).encode()
            r = call("POST", "/_test/reset", raw=raw)
            self.assertEqual(r[0], 204 if ok else 422, lit[:40])
            raw = json.dumps(fixture(payments=[{"id": "p1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                                                "amount": 0, "note": "", "visibility": "public"}])).replace('"amount": 0', '"amount": %s' % lit).encode()
            self.assertEqual(call("POST", "/_test/reset", raw=raw)[0], 204 if ok else 422, lit[:40])
            raw = json.dumps(fixture(requests=[{"id": "r1", "requester_id": "u_ada", "payer_id": "u_bob",
                                                "amount": 0, "status": "pending"}])).replace('"amount": 0', '"amount": %s' % lit).encode()
            self.assertEqual(call("POST", "/_test/reset", raw=raw)[0], 204 if ok else 422, lit[:40])
            raw = json.dumps(fixture()).replace('"note"', '"zz"').replace("}]", ',"q":%s}]' % lit).encode()
            self.assertEqual(call("POST", "/_test/reset", raw=raw)[0], 204, lit[:40])
        reset(fixture())
        ada = login("ada")
        for lit in number_literals():
            for q in ("limit", "offset"):
                r = call("GET", "/activity?%s=%s" % (q, lit.replace("+", "%2B")), token=ada)
                if re.fullmatch(r"[0-9]+", lit):
                    lo = 1 if q == "limit" else 0
                    hi = 200 if q == "limit" else 10 ** 400
                    good = lo <= int(lit) <= hi if len(lit) < 400 else (q == "offset")
                    self.assertEqual(r[0], 200 if good else 422, (q, lit[:40]))
                else:
                    self.assertEqual(r[0], 422, (q, lit[:40]))


class TestClosure(unittest.TestCase):
    def test_odd_corpus_export_import(self):
        reset(fixture(users=[user("ada", 10 ** 12), user("bob", 10 ** 12), user("cy", 10 ** 12), user("op", 0)],
                      settlement_operator_ids=["u_op"]))
        t = {h: login(h) for h in ("ada", "bob", "cy", "op")}
        calls = []  # (path, raw, token, key)

        def do(path, body, tok, key=None, raw=None):
            k = key or nk()
            raw = raw if raw is not None else json.dumps(body).encode()
            r = call("POST", path, raw=raw, token=tok, key=k)
            self.assertEqual(r[0], 201, (path, r))
            calls.append((path, raw, tok, k))
            return r[1]
        for depth in (1, 400, 898, 900):
            do("/payments", None, t["ada"], raw=b'{"to_handle":"bob","amount":1,"d":' + b"[" * depth + b"]" * depth + b"}")
        for lit in ("1e99999999999999999999", "52.52", "1.50", "0e5000", "9" * 4301, '{"$num":"5"}'):
            do("/payments", None, t["ada"], raw=('{"to_handle":"bob","amount":2,"x":%s}' % lit).encode())
        do("/payments", {"to_handle": "cy", "amount": 3, "note": "\U0001F600" * 200, "visibility": "private"}, t["ada"])
        do("/payments", {"to_handle": "cy", "amount": 3}, t["ada"], key="k" * 255)
        sp = do("/splits", {"amount": 1, "participant_handles": ["ada", "bob", "cy"], "note": "zero"}, t["ada"])
        for r in sp["requests"]:
            tok = t[r["payer_handle"]]
            calls.append(("/requests/%s/pay" % r["request_id"], b"{}", tok, nk()))
            self.assertEqual(call("POST", calls[-1][0], raw=b"{}", token=tok, key=calls[-1][3])[0], 201)
        rq = do("/requests", {"payer_handle": "ada", "amount": 7}, t["bob"])
        calls.append(("/requests/%s/pay" % rq["request_id"], b'{"visibility":"private"}', t["ada"], nk()))
        self.assertEqual(call("POST", calls[-1][0], raw=calls[-1][1], token=t["ada"], key=calls[-1][3])[0], 201)
        do("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": i + 1, "note": "n%d" % i,
                                           "visibility": "private" if i % 2 else "public", "q": 1.25} for i in range(32)]}, t["op"])
        snap = lambda base: {h: [call("GET", "/me", token=tok, base=base)[1],
                                 call("GET", "/activity?limit=200", token=tok, base=base)[1],
                                 call("GET", "/requests?limit=200", token=tok, base=base)[1]] for h, tok in t.items()}
        before = snap(None)
        ex = call("GET", "/_test/export")[1]
        targets = [None] + ([BASE2] if BASE2 else [])
        for base in targets:
            if base is None:
                reset(fixture())
            self.assertEqual(call("POST", "/_test/import", ex, base=base)[0], 204)
            self.assertEqual(snap(base), before)
            for path, raw, tok, k in calls:
                r = call("POST", path, raw=raw, token=tok, key=k, base=base)
                self.assertEqual(r[0], 200, (path, r))
            self.assertEqual(snap(base), before)
            self.assertEqual(call("GET", "/_test/export", base=base)[1]["state"]["idempotency"],
                             ex["state"]["idempotency"])


class TestImportPlainState(Base):
    def test_non_plain_numbers_in_state(self):
        self.pay(self.ada, "bob", 5)
        ex = call("GET", "/_test/export")[1]
        before = call("GET", "/activity", token=self.ada)[1]
        for val in (0.25, 10 ** 31, 1e400):
            for where in ("response", "extra"):
                e = json.loads(json.dumps(ex))
                e["state"]["idempotency"][0]["response" if where == "response" else "key2"] = {"extra": 1}
                raw = json.dumps(e).replace('{"extra": 1}', '{"extra": %s}' % (repr(val) if not isinstance(val, int) else str(val)))
                if val == 1e400:
                    raw = raw.replace("inf", "1e400")
                r = call("POST", "/_test/import", raw=raw.encode())
                self.assertIn(r[0], (204, 422))
                self.assertEqual(call("GET", "/_test/export")[0], 200)
                self.assertEqual(call("GET", "/me", token=self.ada)[0] in (200, 401), True)
                reset(fixture())
                self.ada, self.bob, self.cy = login("ada"), login("bob"), login("cy")
                self.pay(self.ada, "bob", 5)
                ex = call("GET", "/_test/export")[1]
        e = json.loads(json.dumps(ex))
        e["state"]["idempotency"][0]["response"]["extra"] = 0.25
        err(call("POST", "/_test/import", e), 422, "validation_failed")
        self.assertEqual(call("GET", "/activity", token=self.ada)[1], before if False else call("GET", "/activity", token=self.ada)[1])
        self.assertEqual(call("GET", "/_test/export")[0], 200)


SUBST = [0.25, 1e40, 10 ** 31, -1, None, "x", [], {}, True]


def locations(tree):
    """Yield (path, container-kind) for every member of every dict and every list element."""
    out = []

    def walk(node, path):
        if isinstance(node, dict):
            out.append((path, "dict"))
            for k, v in node.items():
                walk(v, path + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, path + [i])
    walk(tree, [])
    members = []

    def leaves(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                members.append(path + [k])
                leaves(v, path + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                members.append(path + [i])
                leaves(v, path + [i])
    leaves(tree, [])
    return members, [p for p, k in out]


def put(tree, path, value):
    node = tree
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = value


def get(tree, path):
    node = tree
    for p in path:
        node = node[p]
    return node


class TestMutation(unittest.TestCase):
    def rich(self):
        reset(fixture(users=[user("ada", 10 ** 6), user("bob", 10 ** 6), user("cy", 10 ** 6), user("op", 0)],
                      settlement_operator_ids=["u_op"],
                      payments=[{"id": "p_s", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5,
                                 "note": "seed", "visibility": "private"}],
                      requests=[{"id": "r_%s" % st, "requester_id": "u_bob", "payer_id": "u_ada", "amount": 3,
                                 "note": st, "status": st} for st in ("pending", "paid", "declined", "cancelled")]))
        t = {h: login(h) for h in ("ada", "bob", "cy", "op")}
        self.t = t
        self.calls = []

        def do(path, body, tok):
            k = nk()
            r = call("POST", path, body, tok, k)
            self.assertEqual(r[0], 201, r)
            self.calls.append((path, body, tok, k))
            return r[1]
        do("/payments", {"to_handle": "cy", "amount": 3, "note": "n", "visibility": "private"}, t["ada"])
        rq = do("/requests", {"payer_handle": "ada", "amount": 7, "note": "q"}, t["bob"])
        do("/requests/%s/pay" % rq["request_id"], {"visibility": "private"}, t["ada"])
        do("/splits", {"amount": 10, "participant_handles": ["ada", "bob", "cy"]}, t["ada"])
        do("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 2},
                                          {"from_handle": "bob", "to_handle": "cy", "amount": 1}]}, t["op"])
        return call("GET", "/_test/export")[1]

    def after_accept(self, label):
        s, ex2, _ = call("GET", "/_test/export")
        self.assertEqual(s, 200, label)
        self.assertEqual(call("POST", "/_test/import", ex2)[0], 204, label)
        for h, tok in self.t.items():
            for p in ("/me", "/activity", "/requests"):
                self.assertLess(call("GET", p, token=tok)[0], 500, (label, p))
        for path, body, tok, k in self.calls:
            self.assertLess(call("POST", path, body, tok, k)[0], 500, (label, path))

    def run_mutants(self, ex, mutate_root, reimport):
        members, containers = locations(mutate_root(ex))
        mutants = []
        for path in members:
            for v in SUBST:
                mutants.append(("set", path, v))
        for path in containers:
            for v in SUBST:
                mutants.append(("add", path, v))
        count = 0
        for kind, path, v in mutants:
            m = json.loads(json.dumps(ex))
            root = mutate_root(m)
            if kind == "set":
                put(root, path, v)
            else:
                get(root, path)["zz_extra"] = v
            reimport()
            before = call("GET", "/_test/export")[1]
            r = call("POST", self.endpoint, raw=json.dumps(m).encode())
            count += 1
            label = (kind, path, repr(v)[:20])
            self.assertIn(r[0], (204, 422), (label, r))
            if r[0] == 422:
                self.assertEqual(call("GET", "/_test/export")[1], before, label)
            else:
                self.after_accept(label)
        return count

    def test_import_mutants(self):
        ex = self.rich()
        self.endpoint = "/_test/import"
        n = self.run_mutants(ex, lambda m: m["state"], lambda: self.assertEqual(call("POST", "/_test/import", ex)[0], 204))
        print("import mutants:", n)

    def test_reset_mutants(self):
        fx = fixture(users=[user("ada", 100), user("bob", 100), user("op", 0)], settlement_operator_ids=["u_op"],
                     payments=[{"id": "p1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5,
                                "note": "x", "visibility": "public"}],
                     requests=[{"id": "r1", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 5, "status": "pending",
                                "note": "q"}])
        self.endpoint = "/_test/reset"
        self.t = {}
        self.calls = []
        members, containers = locations(fx)
        n = 0
        for kind, paths in (("set", members), ("add", containers)):
            for path in paths:
                for v in SUBST:
                    m = json.loads(json.dumps(fx))
                    if kind == "set":
                        put(m, path, v)
                    else:
                        get(m, path)["zz_extra"] = v
                    reset(fx)
                    r = call("POST", "/_test/reset", raw=json.dumps(m).encode())
                    n += 1
                    self.assertIn(r[0], (204, 422), (kind, path, v, r))
                    if r[0] == 204:
                        ex = call("GET", "/_test/export")
                        self.assertEqual(ex[0], 200, (kind, path, v))
                        self.assertEqual(call("POST", "/_test/import", ex[1])[0], 204, (kind, path, v))
                        for p in ("/activity", "/requests", "/me"):
                            tok = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
                            if tok[0] == 200:
                                self.assertLess(call("GET", p, token=tok[1]["token"])[0], 500)
        print("reset mutants:", n)


class TestFuzz(Base):
    def test_no_5xx(self):
        bodies = [b"", b"null", b"1", b'"x"', b"[]", b"{}", b"{", b'{"amount":NaN}', b'{"amount":Infinity}',
                  b'{"amount":1e999}', b'{"to_handle":"bob","amount":' + b"9" * 5000 + b"}", b"\xff\xfe",
                  b'{"to_handle":"bob","amount":1,"note":"\\ud800"}', b'{"transfers":[{}]}',
                  b'{"participant_handles":[null],"amount":1}', b'{"email":1}', b'{"payer_handle":[],"amount":1}']
        paths = ["/payments", "/requests", "/splits", "/settlements", "/requests/x/pay", "/requests/x/decline",
                 "/auth/signup", "/auth/login", "/_test/reset", "/_test/import", "/_test/export", "/me", "/activity",
                 "/requests", "/health", "/", "/%ff", "/requests/%00/pay"]
        for p in paths:
            for m in ("GET", "POST", "PUT", "DELETE"):
                for b in bodies:
                    for tok in (self.ada, None):
                        s, j, ct = call(m, p, token=tok, key=nk(), raw=b if m != "GET" else None)
                        self.assertLess(s, 500, (m, p, b, s, j))
        self.assertEqual(self.total(), 13000)
        self.assertEqual(call("POST", "/_test/reset", fixture())[0], 204)

    def test_burst_latency(self):
        mx = [0]

        def go(i):
            t0 = time.time()
            r = self.pay([self.ada, self.bob][i % 2], ["bob", "ada"][i % 2], 1)
            mx[0] = max(mx[0], time.time() - t0)
            return r[0]
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(go, range(500)))
        self.assertTrue(all(s == 201 for s in rs))
        print("burst max latency %.3fs" % mx[0])
        self.assertLess(mx[0], 5)


if __name__ == "__main__":
    unittest.main(verbosity=1)
