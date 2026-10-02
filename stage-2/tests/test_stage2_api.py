"""Own API tests for Pocketful stage 2 (authorizations, captures, holds, upgrade, content negotiation).

BASE_URL: stage-2 container. BASE_URL2 (optional): a second fresh stage-2 container.
BASE_URL_PREV (optional): a stage-1 container, the export source of the upgrade test.
"""
import json
import os
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

import test_stage1 as t1
from test_stage1 import BASE, BASE2, TS_RE, call, err, fixture, login, nk, reset, user, bal

PREV = os.environ.get("BASE_URL_PREV")


def me(tok):
    return call("GET", "/me", token=tok)[1]


def seeded(**kw):
    users = [user("ada", 10000), user("bob", 2500), user("cy", 500), user("op", 0)]
    fx = fixture(users=users, settlement_operator_ids=["u_op"])
    fx.update(kw)
    return fx


class Base(unittest.TestCase):
    def setUp(self):
        reset(seeded())
        self.ada, self.bob, self.cy, self.op = (login(h) for h in ("ada", "bob", "cy", "op"))

    def auth(self, tok, to, amount, key=None, **kw):
        return call("POST", "/authorizations", {"to_handle": to, "amount": amount, **kw}, tok, key or nk())

    def cap(self, tok, aid, body=None, key=None):
        return call("POST", "/authorizations/%s/capture" % aid, body if body is not None else {}, tok, key or nk())

    def total(self):
        return sum(me(t)["total"] for t in (self.ada, self.bob, self.cy, self.op))


class TestHolds(Base):
    def test_me_fields(self):
        j = me(self.ada)
        self.assertEqual((j["balance"], j["total"], j["available"], j["held"]), (10000, 10000, 10000, 0))
        s, a, _ = self.auth(self.ada, "bob", 2000, note="deposit", visibility="private")
        self.assertEqual(s, 201)
        self.assertEqual(set(a), {"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
                                  "captured_amount", "remaining_amount", "currency", "note", "visibility", "status",
                                  "expires_at", "payment_id", "payment_ids", "created_at"})
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_id"], a["payment_ids"],
                          a["visibility"], a["note"]), ("open", 0, 2000, None, [], "private", "deposit"))
        from datetime import datetime
        d = datetime.fromisoformat(a["expires_at"]) - datetime.fromisoformat(a["created_at"])
        self.assertEqual(d.total_seconds(), 600)
        self.assertRegex(a["created_at"], TS_RE)
        j = me(self.ada)
        self.assertEqual((j["balance"], j["total"], j["available"], j["held"]), (10000, 10000, 8000, 2000))
        self.assertEqual(me(self.bob)["available"], 2500)
        self.assertEqual(call("GET", "/activity", token=self.ada)[1]["payments"], [])

    def test_held_cannot_be_spent(self):
        self.auth(self.ada, "bob", 9000)
        t = lambda r, c: err(r, 409, c)
        t(call("POST", "/payments", {"to_handle": "bob", "amount": 1001}, self.ada, nk()), "insufficient_funds")
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 1000}, self.ada, nk())[0], 201)
        self.assertEqual(me(self.ada)["available"], 0)
        t(self.auth(self.ada, "bob", 1), "insufficient_funds")
        rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 1}, self.bob, nk())[1]["request_id"]
        t(call("POST", "/requests/%s/pay" % rid, {}, self.ada, nk()), "insufficient_funds")
        # settlement: net debit must not touch held money
        reset(seeded())
        self.ada, self.bob, self.cy, self.op = (login(h) for h in ("ada", "bob", "cy", "op"))
        self.auth(self.ada, "bob", 9000)
        s = lambda a: call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": a}]}, self.op, nk())
        t(s(1001), "insufficient_funds")
        self.assertEqual(s(1000)[0], 201)

    def test_authorize_errors(self):
        for a in (0, -1, 1000000001, 1.5, "5", True, None):
            err(self.auth(self.ada, "bob", a), 422, "validation_failed")
        err(self.auth(self.ada, "ada", 5), 422, "self_payment")
        err(self.auth(self.ada, "zz", 5), 404, "not_found")
        err(self.auth(self.ada, "bob", 5, note="x" * 201), 422, "validation_failed")
        err(self.auth(self.ada, "bob", 5, visibility="friends"), 422, "validation_failed")
        err(self.auth(self.ada, "bob", 10001), 409, "insufficient_funds")
        self.assertEqual(self.auth(self.ada, "bob", 10000)[0], 201)
        err(call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, self.ada), 400, "missing_idempotency_key")
        err(call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, None, nk()), 401, "unauthenticated")

    def test_capture_final_default(self):
        a = self.auth(self.ada, "bob", 2000, note="dep", visibility="private")[1]
        s, p, _ = self.cap(self.bob, a["authorization_id"], {"amount": 1500})
        self.assertEqual(s, 201)
        self.assertEqual((p["amount"], p["authorization_id"], p["request_id"], p["settlement_id"], p["note"], p["visibility"],
                          p["from_handle"], p["to_handle"]), (1500, a["authorization_id"], None, None, "dep", "private", "ada", "bob"))
        j = me(self.ada)
        self.assertEqual((j["total"], j["available"], j["held"]), (8500, 8500, 0))
        self.assertEqual(me(self.bob)["total"], 4000)
        got = call("GET", "/authorizations", token=self.ada)[1]["authorizations"][0]
        self.assertEqual((got["status"], got["captured_amount"], got["remaining_amount"], got["payment_id"], got["payment_ids"]),
                         ("captured", 1500, 0, p["payment_id"], [p["payment_id"]]))
        err(self.cap(self.bob, a["authorization_id"], {"amount": 1}), 409, "authorization_not_open")
        err(self.cap(self.bob, a["authorization_id"]), 409, "authorization_not_open")
        feed = call("GET", "/activity", token=self.bob)[1]["payments"]
        self.assertEqual([x["payment_id"] for x in feed], [p["payment_id"]])
        self.assertEqual(call("GET", "/activity", token=self.cy)[1]["payments"], [])  # private
        # plain payments carry null
        q = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, self.ada, nk())[1]
        self.assertIsNone(q["authorization_id"])

    def test_capture_default_amount_is_remainder(self):
        a = self.auth(self.ada, "bob", 2000)[1]
        s, p, _ = self.cap(self.bob, a["authorization_id"])
        self.assertEqual((s, p["amount"]), (201, 2000))
        self.assertEqual(me(self.ada)["available"], 8000)

    def test_extended_mode(self):
        aid = self.auth(self.ada, "bob", 2000)[1]["authorization_id"]
        s, p1, _ = self.cap(self.bob, aid, {"amount": 700, "final": False})
        self.assertEqual(s, 201)
        j = me(self.ada)
        self.assertEqual((j["total"], j["held"], j["available"]), (9300, 1300, 8000))
        a = call("GET", "/authorizations?status=open", token=self.bob)[1]["authorizations"][0]
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_id"]), ("open", 700, 1300, p1["payment_id"]))
        err(self.cap(self.bob, aid, {"amount": 1301, "final": False}), 422, "capture_exceeds_authorization")
        err(self.cap(self.bob, aid, {"amount": 10 ** 40}), 422, "capture_exceeds_authorization")
        s, p2, _ = self.cap(self.bob, aid, {"amount": 300, "final": False})
        self.assertEqual(s, 201)
        self.assertEqual(me(self.ada)["held"], 1000)
        # whole remainder closes even with final:false
        s, p3, _ = self.cap(self.bob, aid, {"amount": 1000, "final": False})
        a = call("GET", "/authorizations?status=captured", token=self.bob)[1]["authorizations"][0]
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_id"], a["payment_ids"]),
                         ("captured", 2000, 0, p3["payment_id"], [p1["payment_id"], p2["payment_id"], p3["payment_id"]]))
        self.assertEqual(me(self.ada)["held"], 0)
        # final capture releases the rest
        aid = self.auth(self.ada, "bob", 2000)[1]["authorization_id"]
        self.cap(self.bob, aid, {"amount": 500, "final": False})
        s, p, _ = self.cap(self.bob, aid, {"amount": 100})
        self.assertEqual(s, 201)
        j = me(self.ada)
        self.assertEqual((j["held"], j["total"], j["available"]), (0, 10000 - 2000 - 600 + 2000 - 2000 + 0 if False else 10000 - 2000 - 600, 10000 - 2000 - 600))
        self.assertEqual(self.total(), 13000)

    def test_capture_errors(self):
        aid = self.auth(self.ada, "bob", 2000)[1]["authorization_id"]
        err(self.cap(self.ada, aid), 403, "forbidden")
        err(self.cap(self.cy, aid), 403, "forbidden")
        err(self.cap(self.bob, "nope"), 404, "not_found")
        err(self.cap(self.bob, aid, {"amount": 2001}), 422, "capture_exceeds_authorization")
        for a in (0, -1, 1.5, "5", True, None):
            err(self.cap(self.bob, aid, {"amount": a}), 422, "validation_failed")
        err(self.cap(self.bob, aid, {"amount": 5, "final": "yes"}), 400, "malformed_request")
        err(self.cap(self.bob, aid, {"amount": 5, "final": None}), 400, "malformed_request")
        err(call("POST", "/authorizations/%s/capture" % aid, {}, self.bob), 400, "missing_idempotency_key")
        err(call("POST", "/authorizations/%s/capture" % aid, {}, self.bob, "k" * 256), 422, "validation_failed")
        # failed attempts left the hold alone
        self.assertEqual(me(self.ada)["held"], 2000)
        self.assertEqual(self.cap(self.bob, aid, {"amount": 2000.0})[0], 201)

    def test_void(self):
        aid = self.auth(self.ada, "bob", 2000)[1]["authorization_id"]
        err(call("POST", "/authorizations/%s/void" % aid, None, self.bob), 403, "forbidden")
        err(call("POST", "/authorizations/%s/void" % aid, None, self.cy), 403, "forbidden")
        err(call("POST", "/authorizations/nope/void", None, self.ada), 404, "not_found")
        s, j, _ = call("POST", "/authorizations/%s/void" % aid, None, self.ada)
        self.assertEqual((s, j["status"], j["remaining_amount"]), (200, "voided", 0))
        self.assertEqual(me(self.ada)["available"], 10000)
        self.assertEqual(call("POST", "/authorizations/%s/void" % aid, None, self.ada)[0], 200)
        err(self.cap(self.bob, aid), 409, "authorization_not_open")
        # partially captured then void keeps captures
        aid = self.auth(self.ada, "bob", 2000)[1]["authorization_id"]
        p = self.cap(self.bob, aid, {"amount": 600, "final": False})[1]
        s, j, _ = call("POST", "/authorizations/%s/void" % aid, None, self.ada)
        self.assertEqual((j["status"], j["captured_amount"], j["payment_id"], j["payment_ids"], j["remaining_amount"]),
                         ("voided", 600, p["payment_id"], [p["payment_id"]], 0))
        self.assertEqual(me(self.ada)["held"], 0)
        # captured -> 409
        aid = self.auth(self.ada, "bob", 100)[1]["authorization_id"]
        self.cap(self.bob, aid)
        err(call("POST", "/authorizations/%s/void" % aid, None, self.ada), 409, "authorization_not_open")
        self.assertEqual(self.total(), 13000)

    def test_idempotency(self):
        aid = self.auth(self.ada, "bob", 2000)[1]["authorization_id"]
        k = nk()
        r1 = self.cap(self.bob, aid, {"amount": 1500}, k)
        r2 = self.cap(self.bob, aid, {"amount": 1500.0}, k)
        self.assertEqual((r1[0], r2[0], r1[1]), (201, 200, r2[1]))
        err(self.cap(self.bob, aid, {}, k), 409, "idempotency_key_reuse")
        err(self.cap(self.bob, aid, {"amount": 1500, "final": True}, k), 409, "idempotency_key_reuse")
        err(self.cap(self.bob, aid, {"amount": 1499}, k), 409, "idempotency_key_reuse")
        self.assertEqual(me(self.bob)["total"], 4000)
        # create replay, after the authorization changed
        k2 = nk()
        b = {"to_handle": "bob", "amount": 100}
        a1 = call("POST", "/authorizations", b, self.ada, k2)
        call("POST", "/authorizations/%s/void" % a1[1]["authorization_id"], None, self.ada)
        a2 = call("POST", "/authorizations", b, self.ada, k2)
        self.assertEqual((a1[0], a2[0], a1[1]), (201, 200, a2[1]))
        self.assertEqual(a2[1]["status"], "open")  # original response
        err(call("POST", "/authorizations", {**b, "amount": 101}, self.ada, k2), 409, "idempotency_key_reuse")
        # other path with the same key and body is a first use
        self.assertEqual(call("POST", "/payments", b, self.ada, k2)[0], 201)
        # failed capture claims nothing
        k3 = nk()
        err(self.cap(self.bob, aid, {"amount": 1}, k3), 409, "authorization_not_open")
        a3 = self.auth(self.ada, "bob", 50)[1]["authorization_id"]
        self.assertEqual(self.cap(self.bob, a3, {"amount": 1}, k3)[0], 201)

    def test_concurrent_captures(self):
        aid = self.auth(self.ada, "bob", 1000)[1]["authorization_id"]
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: self.cap(self.bob, aid, {"amount": 20, "final": False}), range(50)))
        self.assertEqual([r[0] for r in rs].count(201), 50)
        self.assertEqual(me(self.ada)["held"], 0)
        aid = self.auth(self.ada, "bob", 1000)[1]["authorization_id"]
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: self.cap(self.bob, aid, {"amount": 300, "final": False}), range(50)))
        self.assertEqual(sorted(r[0] for r in rs).count(201), 3)
        self.assertTrue(all(r[0] in (201, 422, 409) for r in rs))
        self.assertEqual(me(self.ada)["held"], 100)
        k = nk()
        aid = self.auth(self.ada, "bob", 100)[1]["authorization_id"]
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: self.cap(self.bob, aid, {"amount": 60}, k), range(50)))
        self.assertEqual(sorted(r[0] for r in rs), [200] * 49 + [201])
        self.assertEqual(self.total(), 13000)

    def test_races(self):
        for _ in range(4):
            aid = self.auth(self.ada, "bob", 500)[1]["authorization_id"]
            fns = [lambda: self.cap(self.bob, aid, {"amount": 100}) for _ in range(15)] + \
                  [lambda: call("POST", "/authorizations/%s/void" % aid, None, self.ada) for _ in range(15)]
            with ThreadPoolExecutor(30) as ex:
                rs = list(ex.map(lambda f: f(), fns))
            self.assertTrue(all(r[0] < 500 for r in rs))
            a = [x for x in call("GET", "/authorizations", token=self.ada)[1]["authorizations"] if x["authorization_id"] == aid][0]
            captures = sum(1 for r in rs[:15] if r[0] == 201)
            self.assertEqual(captures, len(a["payment_ids"]))
            self.assertEqual(me(self.ada)["held"], 0)
            self.assertEqual(a["captured_amount"], 100 * captures)
            self.assertEqual(self.total(), 13000)

    def test_mixed_burst_invariants(self):
        stop = threading.Event()
        bad = []

        def watch():
            while not stop.is_set():
                for t in (self.ada, self.bob):
                    j = me(t)
                    if j["available"] < 0 or j["balance"] != j["total"] or j["held"] < 0 or j["available"] != j["total"] - j["held"]:
                        bad.append(j)
        w = threading.Thread(target=watch)
        w.start()

        def go(i):
            k = i % 5
            if k == 0:
                return call("POST", "/payments", {"to_handle": "bob", "amount": 400}, self.ada, nk())[0]
            if k == 1:
                r = self.auth(self.ada, "bob", 300)
                return r[0]
            if k == 2:
                lst = call("GET", "/authorizations?direction=incoming&status=open", token=self.bob)[1]["authorizations"]
                if lst:
                    return self.cap(self.bob, lst[0]["authorization_id"], {"amount": 100, "final": i % 2 == 0})[0]
                return 200
            if k == 3:
                lst = call("GET", "/authorizations?direction=outgoing&status=open", token=self.ada)[1]["authorizations"]
                if lst:
                    return call("POST", "/authorizations/%s/void" % lst[-1]["authorization_id"], None, self.ada)[0]
                return 200
            return call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 200}]}, self.op, nk())[0]
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(go, range(250)))
        stop.set()
        w.join()
        self.assertTrue(all(s < 500 for s in rs), sorted(set(rs)))
        self.assertEqual(bad, [])
        self.assertEqual(self.total(), 13000)

    def test_list_filters(self):
        a1 = self.auth(self.ada, "bob", 10)[1]["authorization_id"]
        a2 = self.auth(self.bob, "ada", 10)[1]["authorization_id"]
        self.auth(self.bob, "cy", 10)
        self.cap(self.bob, a1)
        ids = lambda q, t: [x["authorization_id"] for x in call("GET", "/authorizations" + q, token=t)[1]["authorizations"]]
        self.assertEqual(len(ids("", self.ada)), 2)
        self.assertEqual(ids("?direction=outgoing", self.ada), [a1])
        self.assertEqual(ids("?direction=incoming", self.ada), [a2])
        self.assertEqual(ids("?status=captured", self.ada), [a1])
        self.assertEqual(ids("?status=open", self.ada), [a2])
        self.assertEqual(ids("", self.op), [])
        j = call("GET", "/authorizations?limit=1&offset=1", token=self.ada)[1]
        self.assertEqual((len(j["authorizations"]), j["has_more"]), (1, False))
        j = call("GET", "/authorizations?limit=1", token=self.ada)[1]
        self.assertEqual((len(j["authorizations"]), j["has_more"]), (1, True))
        for q in ("direction=x", "status=x", "limit=0", "limit=201", "offset=-1", "limit=1e2", "offset=1.0"):
            err(call("GET", "/authorizations?" + q, token=self.ada), 422, "validation_failed")
        err(call("GET", "/authorizations", token=None), 401, "unauthenticated")
        for q in ("?limit=50&zzz=1",):
            self.assertEqual(call("GET", "/authorizations" + q, token=self.ada)[0], 200)

    def test_import_export(self):
        a = self.auth(self.ada, "bob", 2000, note="x")[1]["authorization_id"]
        k = nk()
        p = self.cap(self.bob, a, {"amount": 500, "final": False}, k)
        key = nk()
        b = {"to_handle": "cy", "amount": 70}
        a2 = call("POST", "/authorizations", b, self.ada, key)
        ex = call("GET", "/_test/export")[1]
        snap = lambda base: {h: [call("GET", "/me", token=t, base=base)[1], call("GET", "/authorizations", token=t, base=base)[1],
                                 call("GET", "/activity", token=t, base=base)[1]] for h, t in
                             (("ada", self.ada), ("bob", self.bob), ("cy", self.cy))}
        before = snap(None)
        for base in [None] + ([BASE2] if BASE2 else []):
            if base is None:
                reset(seeded())
            self.assertEqual(call("POST", "/_test/import", ex, base=base)[0], 204)
            self.assertEqual(snap(base), before)
            self.assertEqual(call("POST", "/authorizations/%s/capture" % a, {"amount": 500, "final": False}, self.bob, k, base=base)[:2], (200, p[1]))
            self.assertEqual(call("POST", "/authorizations", b, self.ada, key, base=base)[:2], (200, a2[1]))
            self.assertEqual(snap(base), before)
        reset(seeded())
        err(call("GET", "/me", token=self.ada), 401, "unauthenticated")
        self.ada = login("ada")
        self.assertEqual(call("GET", "/authorizations", token=self.ada)[1]["authorizations"], [])


class TestExpiry(unittest.TestCase):
    def test_clock_expiry(self):
        reset(seeded(authorization_ttl_seconds=2))
        ada, bob = login("ada"), login("bob")
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 3000}, ada, nk())[1]
        from datetime import datetime
        self.assertEqual((datetime.fromisoformat(a["expires_at"]) - datetime.fromisoformat(a["created_at"])).total_seconds(), 2)
        self.assertEqual(me(ada)["available"], 7000)
        p = call("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, ada, nk())[1]["authorization_id"]
        call("POST", "/authorizations/%s/capture" % p, {"amount": 100, "final": False}, bob, nk())
        time.sleep(2.4)
        got = call("GET", "/authorizations?status=expired", token=ada)[1]["authorizations"]
        self.assertEqual({x["authorization_id"] for x in got}, {a["authorization_id"], p})
        self.assertEqual(call("GET", "/authorizations?status=open", token=ada)[1]["authorizations"], [])
        part = [x for x in got if x["authorization_id"] == p][0]
        self.assertEqual((part["captured_amount"], part["remaining_amount"], len(part["payment_ids"])), (100, 0, 1))
        j = me(ada)
        self.assertEqual((j["available"], j["held"], j["total"]), (9900, 0, 9900))
        err(call("POST", "/authorizations/%s/capture" % a["authorization_id"], {}, bob, nk()), 409, "authorization_expired")
        err(call("POST", "/authorizations/%s/void" % a["authorization_id"], None, ada), 409, "authorization_not_open")
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 9900}, ada, nk())[0], 201)

    def test_expiry_visible_to_export_and_writes(self):
        reset(seeded(authorization_ttl_seconds=1))
        ada = login("ada")
        call("POST", "/authorizations", {"to_handle": "bob", "amount": 10000}, ada, nk())
        time.sleep(1.3)
        st = call("GET", "/_test/export")[1]["state"]
        self.assertEqual(st["authorizations"][0]["status"], "expired")
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 10000}, ada, nk())[0], 201)

    def test_ttl_validation(self):
        for ttl in (0, -1, 1.5, "5", True, None, [], 10 ** 29, 10 ** 12):
            r = call("POST", "/_test/reset", {**seeded(), "authorization_ttl_seconds": ttl})
            self.assertEqual(r[0], 422, ttl)
        self.assertEqual(call("POST", "/_test/reset", {**seeded(), "authorization_ttl_seconds": 1e3})[0], 204)
        self.assertEqual(call("POST", "/_test/reset", seeded())[0], 204)
        ada = login("ada")
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 1}, ada, nk())[1]
        from datetime import datetime
        self.assertEqual((datetime.fromisoformat(a["expires_at"]) - datetime.fromisoformat(a["created_at"])).total_seconds(), 600)


class TestSeeded(unittest.TestCase):
    def fx(self, auths, **kw):
        return seeded(authorizations=auths, **kw)

    def a(self, i, frm="u_ada", to="u_bob", amount=2000, status="open", exp="2099-01-01T00:00:00+00:00", **kw):
        return {"id": i, "from_user_id": frm, "to_user_id": to, "amount": amount, "note": "n", "visibility": "public",
                "status": status, "expires_at": exp, **kw}

    def test_seed(self):
        past = "2020-01-01T00:00:00Z"
        reset(self.fx([self.a("a_1"), self.a("a_2", amount=7000, exp=past), self.a("a_3", status="captured", amount=500),
                       self.a("a_4", status="voided"), self.a("a_5", status="expired", amount=9999999)]))
        ada, bob = login("ada"), login("bob")
        j = me(ada)
        self.assertEqual((j["total"], j["available"], j["held"]), (10000, 8000, 2000))
        lst = call("GET", "/authorizations", token=ada)[1]["authorizations"]
        by = {x["authorization_id"]: x for x in lst}
        self.assertEqual([x["authorization_id"] for x in lst], ["a_5", "a_4", "a_3", "a_2", "a_1"])
        self.assertEqual((by["a_2"]["status"], by["a_2"]["remaining_amount"], by["a_2"]["expires_at"]), ("expired", 0, past))
        self.assertEqual((by["a_3"]["status"], by["a_3"]["captured_amount"], by["a_3"]["payment_id"], by["a_3"]["payment_ids"]),
                         ("captured", 500, None, []))
        self.assertEqual((by["a_1"]["status"], by["a_1"]["remaining_amount"], by["a_1"]["note"]), ("open", 2000, "n"))
        err(call("POST", "/authorizations/a_2/capture", {}, bob, nk()), 409, "authorization_expired")
        err(call("POST", "/authorizations/a_3/capture", {}, bob, nk()), 409, "authorization_not_open")
        s, p, _ = call("POST", "/authorizations/a_1/capture", {"amount": 1500}, bob, nk())
        self.assertEqual((s, p["amount"]), (201, 1500))
        self.assertEqual(me(ada)["available"], 8500)
        self.assertEqual(call("POST", "/authorizations/a_4/void", None, ada)[1]["status"], "voided")
        self.assertEqual(call("POST", "/authorizations/a_2/void", None, ada)[0], 409)

    def test_bad_seeds(self):
        reset(seeded())
        ada = login("ada")
        bad = [
            self.fx([self.a("a_1", amount=10001)]),
            self.fx([self.a("a_1", amount=6000), self.a("a_2", amount=4001)]),
            self.fx([self.a("a_1"), self.a("a_1")]),
            self.fx([self.a("a_1", frm="nobody")]), self.fx([self.a("a_1", to="nobody")]),
            self.fx([self.a("a_1", to="u_ada")]), self.fx([self.a("a_1", status="weird")]),
            self.fx([self.a("a_1", exp="tomorrow")]), self.fx([self.a("a_1", exp="2099-01-01T00:00:00")]),
            self.fx([self.a("a_1", exp=5)]), self.fx([self.a("a_1", amount=0)]), self.fx([self.a("a_1", amount=1.5)]),
            self.fx([self.a("a_1", amount=10 ** 9 + 1)]), self.fx([self.a("a_1", visibility="x")]),
            self.fx([self.a("a_1", note="x" * 201)]), self.fx("nope"), self.fx(["x"]),
            self.fx([{k: v for k, v in self.a("a_1").items() if k != "id"}]),
        ]
        for fx in bad:
            err(call("POST", "/_test/reset", fx), 422, "validation_failed")
        self.assertEqual(me(ada)["balance"], 10000)
        # exactly the balance is fine; expired and non-open do not count
        self.assertEqual(call("POST", "/_test/reset", self.fx([self.a("a_1", amount=10000)]))[0], 204)
        self.assertEqual(call("POST", "/_test/reset", self.fx([self.a("a_1", amount=10000, exp="2020-01-01T00:00:00+00:00"),
                                                              self.a("a_2", amount=10000)]))[0], 204)
        self.assertEqual(call("POST", "/_test/reset", self.fx([self.a("a_1", amount=10 ** 9, status="voided")]))[0], 204)
        self.assertEqual(call("POST", "/_test/reset", {**seeded(), "authorizations": []})[0], 204)


class TestUpgrade(unittest.TestCase):
    @unittest.skipUnless(PREV, "BASE_URL_PREV not set")
    def test_stage1_export_into_stage2(self):
        call("POST", "/_test/reset", seeded(requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
                                                       "amount": 1200, "note": "taxi", "status": "pending"}]), base=PREV)
        tok = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}, base=PREV)[1]["token"]
        key = nk()
        body = {"to_handle": "bob", "amount": 300, "note": "x"}
        p1 = call("POST", "/payments", body, tok, key, base=PREV)
        key2 = nk()
        s1 = call("POST", "/splits", {"amount": 9, "participant_handles": ["ada", "bob"]}, tok, key2, base=PREV)
        ex = call("GET", "/_test/export", base=PREV)[1]
        self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        j = call("GET", "/me", token=tok)[1]
        self.assertEqual((j["balance"], j["total"], j["available"], j["held"]), (9700, 9700, 9700, 0))
        r = call("POST", "/payments", body, tok, key)
        self.assertEqual(r[0], 200)
        self.assertEqual({k: v for k, v in r[1].items() if k != "authorization_id"}, p1[1])
        self.assertIsNone(r[1]["authorization_id"])
        self.assertEqual(call("POST", "/splits", {"amount": 9, "participant_handles": ["ada", "bob"]}, tok, key2)[:2], (200, s1[1]))
        err(call("POST", "/payments", {**body, "amount": 301}, tok, key), 409, "idempotency_key_reuse")
        self.assertEqual(call("POST", "/requests/rq_1/pay", {}, tok, nk())[0], 201)
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, tok, nk())
        self.assertEqual(a[0], 201)
        self.assertEqual(call("GET", "/_test/export")[0], 200)
        # re-export / re-import of the stage-2 state
        ex2 = call("GET", "/_test/export")[1]
        self.assertEqual(call("POST", "/_test/import", ex2)[0], 204)
        self.assertEqual(call("GET", "/me", token=tok)[1]["held"], 100)


class TestNegotiation(Base):
    def test_accept(self):
        html = "text/html; charset=utf-8"
        for p in ("/", "/requests", "/split", "/signup", "/login", "/authorizations"):
            r = call("GET", p, headers={"Accept": "text/html,application/xhtml+xml"})
            self.assertEqual((r[0], r[2]), (200, html), p)
        for p in ("/", "/split", "/signup", "/login"):
            for acc in (None, "*/*", "application/json"):
                r = call("GET", p, headers={"Accept": acc} if acc else None)
                self.assertEqual((r[0], r[2]), (200, html), (p, acc))
        for p in ("/requests", "/authorizations"):
            for acc in (None, "*/*", "application/json"):
                r = call("GET", p, headers={"Accept": acc} if acc else None)
                self.assertEqual(r[0], 401, (p, acc))
                self.assertEqual(r[2], "application/json; charset=utf-8")
                r = call("GET", p, token=self.ada, headers={"Accept": acc} if acc else None)
                self.assertEqual(r[0], 200, (p, acc))
            r = call("GET", p, token=self.ada, headers={"Accept": "text/html"})
            self.assertEqual(r[2], html)
        for p, c in (("/static/app.js", "text/javascript; charset=utf-8"), ("/static/app.css", "text/css; charset=utf-8")):
            r = call("GET", p)
            self.assertEqual((r[0], r[2]), (200, c))
        err(call("GET", "/static/nope.js"), 404, "not_found")
        err(call("GET", "/static/../app.py"), 404, "not_found")
        for m in ("POST", "PUT", "DELETE"):
            for p in ("/", "/login", "/static/app.js"):
                self.assertLess(call(m, p, {})[0], 500)
        self.assertEqual(call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, nk(),
                              headers={"Accept": "text/html"})[0], 201)


class TestMutationAuth(unittest.TestCase):
    """The stage-1 mutation sweep, extended over authorizations, captures and the new fixture members."""

    def rich(self):
        reset(seeded(authorizations=[TestSeeded.a(None, "a_s1"), TestSeeded.a(None, "a_s2", status="captured", amount=5)]))
        t = {h: login(h) for h in ("ada", "bob", "cy", "op")}
        self.t = t
        self.calls = []

        def do(path, body, tok):
            k = nk()
            r = call("POST", path, body, tok, k)
            self.assertEqual(r[0], 201, r)
            self.calls.append((path, body, tok, k))
            return r[1]
        a = do("/authorizations", {"to_handle": "bob", "amount": 900, "note": "n", "visibility": "private"}, t["ada"])
        do("/authorizations/%s/capture" % a["authorization_id"], {"amount": 100, "final": False}, t["bob"])
        b = do("/authorizations", {"to_handle": "cy", "amount": 50}, t["ada"])
        do("/authorizations/%s/capture" % b["authorization_id"], {}, t["cy"])
        do("/authorizations", {"to_handle": "ada", "amount": 20}, t["bob"])
        do("/payments", {"to_handle": "cy", "amount": 3}, t["ada"])
        return call("GET", "/_test/export")[1]

    def test_import_mutants(self):
        ex = self.rich()
        sub = t1.SUBST
        members, containers = t1.locations(ex["state"])
        members = [m for m in members if m[0] in ("authorizations", "idempotency", "ttl", "payments")]
        containers = [c for c in containers if c and c[0] in ("authorizations", "idempotency")]
        n = 0
        for kind, paths in (("set", members), ("add", containers)):
            for path in paths:
                for v in sub:
                    m = json.loads(json.dumps(ex))
                    if kind == "set":
                        t1.put(m["state"], path, v)
                    else:
                        t1.get(m["state"], path)["zz_extra"] = v
                    self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
                    before = call("GET", "/_test/export")[1]
                    r = call("POST", "/_test/import", raw=json.dumps(m).encode())
                    n += 1
                    label = (kind, path, repr(v)[:20])
                    self.assertIn(r[0], (204, 422), (label, r))
                    if r[0] == 422:
                        self.assertEqual(call("GET", "/_test/export")[1], before, label)
                    else:
                        s, ex2, _ = call("GET", "/_test/export")
                        self.assertEqual(s, 200, label)
                        self.assertEqual(call("POST", "/_test/import", ex2)[0], 204, label)
                        for h, tok in self.t.items():
                            for p in ("/me", "/activity", "/requests", "/authorizations"):
                                self.assertLess(call("GET", p, token=tok)[0], 500, (label, p))
                        for path2, body, tok, k in self.calls:
                            self.assertLess(call("POST", path2, body, tok, k)[0], 500, (label, path2))
        print("stage-2 import mutants:", n)

    def test_reset_mutants(self):
        fx = seeded(authorizations=[TestSeeded.a(None, "a_1"), TestSeeded.a(None, "a_2", status="expired")],
                    authorization_ttl_seconds=30)
        members, containers = t1.locations(fx)
        n = 0
        for kind, paths in (("set", [m for m in members if m[0] in ("authorizations", "authorization_ttl_seconds")]),
                            ("add", [c for c in containers if c and c[0] == "authorizations"] + [[]])):
            for path in paths:
                for v in t1.SUBST:
                    m = json.loads(json.dumps(fx))
                    if kind == "set":
                        t1.put(m, path, v)
                    else:
                        t1.get(m, path)["zz_extra"] = v
                    reset(fx)
                    r = call("POST", "/_test/reset", raw=json.dumps(m).encode())
                    n += 1
                    self.assertIn(r[0], (204, 422), (kind, path, v, r))
                    if r[0] == 204:
                        ex = call("GET", "/_test/export")
                        self.assertEqual(ex[0], 200, (kind, path, v))
                        self.assertEqual(call("POST", "/_test/import", ex[1])[0], 204, (kind, path, v))
        print("stage-2 reset mutants:", n)


class TestNumberFuzzAuth(Base):
    def test_amounts(self):
        reset(seeded(users=[user("ada", 10 ** 15), user("bob", 0), user("op", 0)]) if False else seeded())
        self.ada, self.bob = login("ada"), login("bob")
        for lit in t1.number_literals()[:60]:
            ok = t1.expected_valid_int(lit, 1, 10 ** 9)
            r = call("POST", "/authorizations", raw=('{"to_handle":"bob","amount":%s}' % lit).encode(), token=self.ada, key=nk())
            self.assertIn(r[0], ((201, 409) if ok else (422,)), lit[:40])
            aid = self.auth(self.ada, "bob", 1)[1]["authorization_id"]
            r = call("POST", "/authorizations/%s/capture" % aid, raw=('{"amount":%s}' % lit).encode(), token=self.bob, key=nk())
            valid_cap = t1.expected_valid_int(lit, 1, 1)
            self.assertLess(r[0], 500, lit[:40])
            if valid_cap:
                self.assertEqual(r[0], 201, lit[:40])
            else:
                try:
                    positive_int = t1.expected_valid_int(lit, 2, 10 ** 400)
                except Exception:
                    positive_int = False
                self.assertEqual(r[0], 422, lit[:40])
            r = call("POST", "/authorizations", raw=('{"to_handle":"bob","amount":1,"x":%s}' % lit).encode(), token=self.ada, key=nk())
            self.assertEqual(r[0], 201, lit[:40])


if __name__ == "__main__":
    unittest.main(verbosity=1)
