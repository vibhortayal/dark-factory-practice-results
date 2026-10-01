"""Stage-2 API rows: W, Z, X2, G1/G5/G6, U2, C2 (black box against BASE_URL)."""
import json
import re
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from helpers import call, fixture, k, login, me, pay, reset, user


def err(case, resp, status, code):
    s, h, b, raw = resp
    case.assertEqual(s, status, raw)
    case.assertEqual(b["error"]["code"], code, raw)
    case.assertEqual(h.get("Content-Type"), "application/json; charset=utf-8")


def iso(dt):
    return dt.isoformat(timespec="seconds")


def in_(seconds):
    return iso(datetime.now(timezone.utc) + timedelta(seconds=seconds))


class S2(unittest.TestCase):
    def setUp(self):
        reset(fixture())
        self.ada, self.bob, self.cy = login("ada"), login("bob"), login("cy")

    def auth(self, tok, to, amount, key=None, **extra):
        body = {"to_handle": to, "amount": amount}
        body.update(extra)
        return call("POST", "/authorizations", body, tok, key or k())

    def cap(self, tok, aid, body=None, key=None):
        return call("POST", f"/authorizations/{aid}/capture", {} if body is None else body, tok, key or k())

    def void(self, tok, aid):
        return call("POST", f"/authorizations/{aid}/void", token=tok)

    def total(self):
        return sum(me(t)["total"] for t in (self.ada, self.bob, self.cy))


class Wallet(S2):
    def test_me_fields_and_hold(self):  # W1 Z4
        m = me(self.ada)
        self.assertEqual((m["balance"], m["total"], m["available"], m["held"]), (10000, 10000, 10000, 0))
        s, _, a, _ = self.auth(self.ada, "bob", 2000, note="deposit", visibility="private")
        self.assertEqual(s, 201)
        self.assertEqual(set(a), {"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
                                  "captured_amount", "remaining_amount", "currency", "note", "visibility", "status",
                                  "expires_at", "payment_id", "payment_ids", "created_at"})
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_id"], a["payment_ids"]),
                         ("open", 0, 2000, None, []))
        c = datetime.fromisoformat(a["created_at"])
        e = datetime.fromisoformat(a["expires_at"])
        self.assertEqual((e - c).total_seconds(), 600)
        m = me(self.ada)
        self.assertEqual((m["balance"], m["total"], m["available"], m["held"]), (10000, 10000, 8000, 2000))
        self.assertEqual(call("GET", "/activity", token=self.ada)[2]["payments"], [])
        self.assertEqual(call("GET", "/activity", token=self.bob)[2]["payments"], [])

    def test_funds_use_available(self):  # W4 W5
        self.auth(self.cy, "bob", 400)
        err(self, pay(self.cy, "bob", 101), 409, "insufficient_funds")
        self.assertEqual(pay(self.cy, "bob", 100)[0], 201)
        err(self, self.auth(self.cy, "bob", 1), 409, "insufficient_funds")
        rq = call("POST", "/requests", {"payer_handle": "cy", "amount": 1}, self.bob, k())[2]["request_id"]
        err(self, call("POST", f"/requests/{rq}/pay", {}, self.cy, k()), 409, "insufficient_funds")
        self.assertEqual(self.total(), 13000)

    def test_settlement_net_debits_respect_holds(self):  # W5
        reset(fixture(users=[user("ada", 1000), user("bob", 0), user("op", 0)], settlement_operator_ids=["u_op"]))
        ada, op = login("ada"), login("op")
        self.auth(ada, "bob", 600)
        body = lambda a: {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": a}]}
        err(self, call("POST", "/settlements", body(401), op, k()), 409, "insufficient_funds")
        self.assertEqual(call("POST", "/settlements", body(400), op, k())[0], 201)
        b = {"transfers": [{"from_handle": "ada", "to_handle": "op", "amount": 50}, {"from_handle": "op", "to_handle": "bob", "amount": 50}]}
        err(self, call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "op", "amount": 1}]}, op, k()), 409, "insufficient_funds")

    def test_payment_authorization_id_everywhere(self):  # W7
        s, _, p, _ = pay(self.ada, "bob", 5)
        self.assertIn("authorization_id", p)
        self.assertIsNone(p["authorization_id"])
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, self.bob, k())[2]["request_id"]
        self.assertIsNone(call("POST", f"/requests/{rq}/pay", {}, self.ada, k())[2]["authorization_id"])
        for p in call("GET", "/activity", token=self.ada)[2]["payments"]:
            self.assertIsNone(p["authorization_id"])

    def test_create_errors(self):  # Z3
        for a in (0, -1, 1.5, "5", None, True, 1000000001):
            err(self, self.auth(self.ada, "bob", a), 422, "validation_failed")
        err(self, self.auth(self.ada, "ada", 5), 422, "self_payment")
        err(self, self.auth(self.ada, "nobody", 5), 404, "not_found")
        err(self, self.auth(self.ada, "bob", 5, note="x" * 201), 422, "validation_failed")
        err(self, self.auth(self.ada, "bob", 5, visibility="friends"), 422, "validation_failed")
        err(self, self.auth(self.ada, 7, 5), 400, "malformed_request")
        err(self, self.auth(self.ada, "bob", 10001), 409, "insufficient_funds")
        self.assertEqual(self.auth(self.ada, "bob", 10000)[0], 201)
        a = self.auth(self.bob, "ada", 5)[2]
        self.assertEqual((a["note"], a["visibility"]), ("", "public"))
        err(self, call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, self.ada), 400, "missing_idempotency_key")
        err(self, call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}), 401, "unauthenticated")


class Capture(S2):
    def test_default_final_capture_releases_remainder(self):  # Z5 Z6 Z7 Z9 Z13
        a = self.auth(self.ada, "bob", 2000, note="deposit", visibility="private")[2]
        aid = a["authorization_id"]
        s, _, p, _ = self.cap(self.bob, aid, {"amount": 1500})
        self.assertEqual(s, 201)
        self.assertEqual((p["amount"], p["authorization_id"], p["request_id"], p["note"], p["visibility"], p["from_handle"], p["to_handle"]),
                         (1500, aid, None, "deposit", "private", "ada", "bob"))
        m = me(self.ada)
        self.assertEqual((m["total"], m["held"], m["available"]), (8500, 0, 8500))
        self.assertEqual(me(self.bob)["total"], 4000)
        got = call("GET", "/authorizations", token=self.ada)[2]["authorizations"][0]
        self.assertEqual((got["status"], got["captured_amount"], got["payment_id"], got["payment_ids"], got["remaining_amount"]),
                         ("captured", 1500, p["payment_id"], [p["payment_id"]], 0))
        err(self, self.cap(self.bob, aid, {"amount": 1}), 409, "authorization_not_open")
        err(self, self.cap(self.bob, aid), 409, "authorization_not_open")
        feed = call("GET", "/activity", token=self.bob)[2]["payments"]
        self.assertEqual([x["payment_id"] for x in feed], [p["payment_id"]])
        self.assertEqual(call("GET", "/activity", token=self.cy)[2]["payments"], [])  # private

    def test_default_amount_is_remaining(self):
        aid = self.auth(self.ada, "bob", 700)[2]["authorization_id"]
        s, _, p, _ = self.cap(self.bob, aid)
        self.assertEqual((s, p["amount"]), (201, 700))
        self.assertEqual(self.total(), 13000)

    def test_extended_mode(self):  # Z8 Z9
        aid = self.auth(self.ada, "bob", 2000)[2]["authorization_id"]
        s, _, p1, _ = self.cap(self.bob, aid, {"amount": 700, "final": False})
        self.assertEqual(s, 201)
        a = call("GET", "/authorizations?status=open", token=self.bob)[2]["authorizations"][0]
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_id"]), ("open", 700, 1300, p1["payment_id"]))
        m = me(self.ada)
        self.assertEqual((m["total"], m["held"], m["available"]), (9300, 1300, 8000))
        err(self, self.cap(self.bob, aid, {"amount": 1301, "final": False}), 422, "capture_exceeds_authorization")
        s, _, p2, _ = self.cap(self.bob, aid, {"amount": 300, "final": False})
        a = call("GET", "/authorizations", token=self.bob)[2]["authorizations"][0]
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_ids"]), ("open", 1000, 1000, [p1["payment_id"], p2["payment_id"]]))
        s, _, p3, _ = self.cap(self.bob, aid, {"amount": 400})  # final: releases 600
        a = call("GET", "/authorizations", token=self.bob)[2]["authorizations"][0]
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_id"], len(a["payment_ids"])), ("captured", 1400, 0, p3["payment_id"], 3))
        self.assertEqual(me(self.ada)["held"], 0)
        self.assertEqual(me(self.ada)["total"], 8600)
        # capturing the whole remainder closes it even with final: false
        aid = self.auth(self.ada, "bob", 100)[2]["authorization_id"]
        self.cap(self.bob, aid, {"amount": 100, "final": False})
        err(self, self.cap(self.bob, aid, {"amount": 1, "final": False}), 409, "authorization_not_open")
        self.assertEqual(call("GET", "/authorizations?status=captured", token=self.bob)[2]["authorizations"][0]["status"], "captured")

    def test_capture_spends_reserved_money_with_zero_available(self):  # Z13
        aid = self.auth(self.cy, "bob", 500)[2]["authorization_id"]
        self.assertEqual(me(self.cy)["available"], 0)
        self.assertEqual(self.cap(self.bob, aid)[0], 201)
        self.assertEqual(me(self.cy)["total"], 0)

    def test_errors_and_precedence(self):  # Z10 S2-1
        aid = self.auth(self.ada, "bob", 1000)[2]["authorization_id"]
        err(self, self.cap(self.ada, aid), 403, "forbidden")
        err(self, self.cap(self.cy, aid), 403, "forbidden")
        err(self, self.cap(self.bob, "nope"), 404, "not_found")
        for a in (0, -1, 1.5, "5", None, True):
            err(self, self.cap(self.bob, aid, {"amount": a}), 422, "validation_failed")
        err(self, self.cap(self.bob, aid, {"amount": 5, "final": "yes"}), 400, "malformed_request")
        err(self, self.cap(self.bob, aid, {"amount": 5, "final": None}), 400, "malformed_request")
        err(self, self.cap(self.bob, aid, {"amount": 1001}), 422, "capture_exceeds_authorization")
        err(self, call("POST", f"/authorizations/{aid}/capture", {}, self.bob), 400, "missing_idempotency_key")
        err(self, call("POST", f"/authorizations/{aid}/capture", raw=b"[]", token=self.bob, key=k()), 400, "malformed_request")
        self.assertEqual(self.cap(self.bob, aid, {"amount": 1000})[0], 201)
        err(self, self.cap(self.ada, aid), 403, "forbidden")  # permission before state

    def test_idempotency(self):  # Z11 Z18
        aid = self.auth(self.ada, "bob", 2000)[2]["authorization_id"]
        key = k()
        s, _, p, _ = self.cap(self.bob, aid, {"amount": 700, "final": False}, key)
        self.assertEqual(s, 201)
        s, _, p2, _ = self.cap(self.bob, aid, {"final": False, "amount": 700}, key)
        self.assertEqual((s, p2), (200, p))
        err(self, self.cap(self.bob, aid, {"amount": 700}, key), 409, "idempotency_key_reuse")
        err(self, self.cap(self.bob, aid, {"amount": 700, "final": True}, key), 409, "idempotency_key_reuse")
        err(self, self.cap(self.bob, aid, {}, key), 409, "idempotency_key_reuse")
        self.assertEqual(me(self.bob)["total"], 3200)
        # replay after closed
        key2 = k()
        self.cap(self.bob, aid, {"amount": 1300}, key2)
        self.assertEqual(self.cap(self.bob, aid, {"amount": 1300}, key2)[0], 200)
        # {} vs {"amount": 2000}
        aid2 = self.auth(self.ada, "bob", 20)[2]["authorization_id"]
        key3 = k()
        self.assertEqual(self.cap(self.bob, aid2, {}, key3)[0], 201)
        err(self, self.cap(self.bob, aid2, {"amount": 20}, key3), 409, "idempotency_key_reuse")
        # failed attempt claims no key
        aid3 = self.auth(self.ada, "bob", 20)[2]["authorization_id"]
        key4 = k()
        err(self, self.cap(self.cy, aid3, {}, key4), 403, "forbidden")
        self.assertEqual(self.cap(self.bob, aid3, {}, key4)[0], 201)
        # authorization create replay
        key5 = k()
        s, _, a1, _ = self.auth(self.ada, "bob", 10, key5)
        s2, _, a2, _ = self.auth(self.ada, "bob", 10, key5)
        self.assertEqual((s, s2, a1 == a2), (201, 200, True))
        err(self, self.auth(self.ada, "bob", 11, key5), 409, "idempotency_key_reuse")
        self.assertEqual(me(self.ada)["held"], 10)

    def test_void(self):  # Z14 Z15
        aid = self.auth(self.ada, "bob", 1000)[2]["authorization_id"]
        err(self, self.void(self.bob, aid), 403, "forbidden")
        err(self, self.void(self.cy, aid), 403, "forbidden")
        err(self, self.void(self.ada, "nope"), 404, "not_found")
        s, _, v, _ = self.void(self.ada, aid)
        self.assertEqual((s, v["status"], v["remaining_amount"]), (200, "voided", 0))
        self.assertEqual(self.void(self.ada, aid)[2]["status"], "voided")
        self.assertEqual(me(self.ada)["held"], 0)
        err(self, self.cap(self.bob, aid), 409, "authorization_not_open")
        # partial then void
        aid = self.auth(self.ada, "bob", 1000)[2]["authorization_id"]
        p = self.cap(self.bob, aid, {"amount": 400, "final": False})[2]
        v = self.void(self.ada, aid)[2]
        self.assertEqual((v["status"], v["captured_amount"], v["remaining_amount"], v["payment_ids"]), ("voided", 400, 0, [p["payment_id"]]))
        self.assertEqual((me(self.ada)["total"], me(self.ada)["held"]), (9600, 0))
        # captured one cannot be voided
        aid = self.auth(self.ada, "bob", 10)[2]["authorization_id"]
        self.cap(self.bob, aid)
        err(self, self.void(self.ada, aid), 409, "authorization_not_open")

    def test_list(self):  # Z17
        ids = [self.auth(self.ada, "bob", 10 + i)[2]["authorization_id"] for i in range(3)]
        self.auth(self.bob, "ada", 5)
        self.cap(self.bob, ids[0])
        self.void(self.ada, ids[1])
        g = lambda q, t=self.ada: call("GET", "/authorizations" + q, token=t)
        self.assertEqual(len(g("")[2]["authorizations"]), 4)
        self.assertEqual(len(g("?direction=outgoing")[2]["authorizations"]), 3)
        self.assertEqual(len(g("?direction=incoming")[2]["authorizations"]), 1)
        self.assertEqual(len(g("?status=open")[2]["authorizations"]), 2)
        self.assertEqual(len(g("?status=captured")[2]["authorizations"]), 1)
        self.assertEqual(len(g("?status=voided&direction=outgoing")[2]["authorizations"]), 1)
        self.assertEqual(g("", self.cy)[2], {"authorizations": [], "has_more": False})
        b = g("?limit=2")[2]
        self.assertEqual((len(b["authorizations"]), b["has_more"]), (2, True))
        b = g("?limit=2&offset=2")[2]
        self.assertEqual((len(b["authorizations"]), b["has_more"]), (2, False))
        for q in ("?limit=0", "?limit=201", "?offset=-1", "?limit=1e1", "?limit=", "?status=paid", "?direction=x", "?status=pending"):
            err(self, g(q), 422, "validation_failed")
        err(self, call("GET", "/authorizations"), 401, "unauthenticated")

    def test_expiry(self):  # Z16 Z10
        reset(fixture(authorization_ttl_seconds=2))
        ada, bob = login("ada"), login("bob")
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 3000}, ada, k())[2]
        self.assertEqual((datetime.fromisoformat(a["expires_at"]) - datetime.fromisoformat(a["created_at"])).total_seconds(), 2)
        self.assertEqual(me(ada)["held"], 3000)
        self.assertEqual(call("GET", "/authorizations?status=open", token=ada)[2]["authorizations"][0]["authorization_id"], a["authorization_id"])
        time.sleep(2.3)
        m = me(ada)
        self.assertEqual((m["held"], m["available"]), (0, 10000))
        got = call("GET", "/authorizations", token=bob)[2]["authorizations"][0]
        self.assertEqual((got["status"], got["remaining_amount"]), ("expired", 0))
        self.assertEqual(call("GET", "/authorizations?status=open", token=bob)[2]["authorizations"], [])
        self.assertEqual(len(call("GET", "/authorizations?status=expired", token=bob)[2]["authorizations"]), 1)
        err(self, call("POST", f"/authorizations/{a['authorization_id']}/capture", {}, bob, k()), 409, "authorization_expired")
        err(self, call("POST", f"/authorizations/{a['authorization_id']}/void", token=ada), 409, "authorization_not_open")
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 10000}, ada, k())[0], 201)

    def test_partial_then_expiry_preserves_captures(self):  # Z15
        reset(fixture(authorization_ttl_seconds=2))
        ada, bob = login("ada"), login("bob")
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, ada, k())[2]
        p = call("POST", f"/authorizations/{a['authorization_id']}/capture", {"amount": 400, "final": False}, bob, k())[2]
        time.sleep(2.3)
        got = call("GET", "/authorizations", token=ada)[2]["authorizations"][0]
        self.assertEqual((got["status"], got["captured_amount"], got["remaining_amount"], got["payment_ids"]), ("expired", 400, 0, [p["payment_id"]]))
        self.assertEqual((me(ada)["total"], me(ada)["held"]), (9600, 0))


class Fixtures(S2):
    def auths(self, *items, **extra):
        return fixture(authorizations=list(items), **extra)

    def seeded(self, **o):
        d = {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit",
             "visibility": "public", "status": "open", "expires_at": in_(7200)}
        d.update(o)
        return d

    def test_seeded_open_hold(self):  # X2.2 X2.3 X2.6 S2-3
        reset(self.auths(self.seeded()))
        ada, bob, cy = login("ada"), login("bob"), login("cy")
        m = me(ada)
        self.assertEqual((m["total"], m["held"], m["available"]), (10000, 2000, 8000))
        a = call("GET", "/authorizations", token=bob)[2]["authorizations"][0]
        self.assertEqual((a["authorization_id"], a["status"], a["captured_amount"], a["remaining_amount"], a["payment_id"], a["payment_ids"], a["note"]),
                         ("a_1", "open", 0, 2000, None, [], "deposit"))
        self.assertTrue(re.match(r"\d{4}-", a["created_at"]))
        self.assertEqual(call("GET", "/authorizations", token=cy)[2]["authorizations"], [])
        self.assertEqual(self.cap(bob, "a_1", {"amount": 500})[0], 201)
        self.assertEqual((me(ada)["total"], me(ada)["held"]), (9500, 0))

    def test_seeded_statuses(self):  # X2.2 X2.5 S2-2 S2-3
        reset(self.auths(self.seeded(id="a_cap", status="captured", amount=500),
                         self.seeded(id="a_void", status="voided"),
                         self.seeded(id="a_exp", status="expired"),
                         self.seeded(id="a_old", status="open", expires_at=in_(-7200), amount=999999),
                         self.seeded(id="a_part", status="open", captured_amount=300, payment_id="px", amount=1000)))
        ada, bob = login("ada"), login("bob")
        got = {a["authorization_id"]: a for a in call("GET", "/authorizations?limit=200", token=ada)[2]["authorizations"]}
        self.assertEqual((got["a_cap"]["status"], got["a_cap"]["captured_amount"], got["a_cap"]["remaining_amount"]), ("captured", 500, 0))
        self.assertEqual(got["a_void"]["status"], "voided")
        self.assertEqual((got["a_exp"]["status"], got["a_exp"]["remaining_amount"]), ("expired", 0))
        self.assertEqual((got["a_old"]["status"], got["a_old"]["remaining_amount"]), ("expired", 0))
        self.assertEqual((got["a_part"]["status"], got["a_part"]["remaining_amount"], got["a_part"]["payment_id"], got["a_part"]["payment_ids"]), ("open", 700, "px", ["px"]))
        self.assertEqual((me(ada)["held"], me(ada)["available"]), (700, 9300))
        err(self, self.cap(bob, "a_exp"), 409, "authorization_expired")
        err(self, self.cap(bob, "a_old"), 409, "authorization_expired")
        err(self, self.cap(bob, "a_cap"), 409, "authorization_not_open")
        err(self, self.cap(bob, "a_void"), 409, "authorization_not_open")
        err(self, self.void(ada, "a_exp"), 409, "authorization_not_open")

    def test_holds_exceeding_balance(self):  # X2.4
        err(self, call("POST", "/_test/reset", self.auths(self.seeded(amount=10001))), 422, "validation_failed")
        err(self, call("POST", "/_test/reset", self.auths(self.seeded(amount=6000), self.seeded(id="a_2", amount=4001))), 422, "validation_failed")
        self.assertEqual(call("POST", "/_test/reset", self.auths(self.seeded(amount=6000), self.seeded(id="a_2", amount=4000)))[0], 204)
        # expired ones do not count
        self.assertEqual(call("POST", "/_test/reset", self.auths(self.seeded(amount=999999, expires_at=in_(-7200))))[0], 204)
        self.assertEqual(call("POST", "/_test/reset", self.auths(self.seeded(amount=999999, status="expired")))[0], 204)
        reset(fixture())
        err(self, call("POST", "/_test/reset", self.auths(self.seeded(amount=10001))), 422, "validation_failed")
        self.assertEqual(me(login("ada"))["held"], 0)  # nothing changed

    def test_ttl(self):  # X2.1
        for bad in (0, -5, 1.5, "60", None, True, [], "x"):
            err(self, call("POST", "/_test/reset", fixture(authorization_ttl_seconds=bad)), 422, "validation_failed")
        reset(fixture())
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, login("ada"), k())[2]
        self.assertEqual((datetime.fromisoformat(a["expires_at"]) - datetime.fromisoformat(a["created_at"])).total_seconds(), 600)
        reset(fixture(authorization_ttl_seconds=90))
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, login("ada"), k())[2]
        self.assertEqual((datetime.fromisoformat(a["expires_at"]) - datetime.fromisoformat(a["created_at"])).total_seconds(), 90)

    def test_bad_seeded_authorizations(self):
        for bad in (self.seeded(from_user_id="u_zed"), self.seeded(status="weird"), self.seeded(expires_at="soon"),
                    self.seeded(expires_at="2026-01-01T00:00:00"), self.seeded(amount=0), self.seeded(visibility="x"),
                    self.seeded(amount="5"), {"id": "a_9"}):
            self.assertEqual(call("POST", "/_test/reset", self.auths(bad))[0], 422, bad)
        self.assertEqual(call("POST", "/_test/reset", fixture(authorizations="x"))[0], 422)

    def test_reset_5000_users_within_limit(self):  # S2-6 (stage-1 D5: reset < 10 s)
        users = [user("u%d" % i, 10, pw="pw%06d-secret" % i) for i in range(5000)]
        t = time.time()
        reset(fixture(users=users))
        took = time.time() - t
        self.assertLess(took, 8, took)
        self.assertEqual(me(login("u4999", "pw004999-secret"))["total"], 10)
        err(self, call("POST", "/auth/login", {"email": "u4999@example.com", "password": "wrong password"}), 401, "unauthenticated")
        print("reset of 5000 users: %.2fs" % took)

    def test_seeded_hold_blocks_payments(self):
        reset(self.auths(self.seeded(amount=9500)))
        ada = login("ada")
        err(self, pay(ada, "bob", 501), 409, "insufficient_funds")
        self.assertEqual(pay(ada, "bob", 500)[0], 201)


class UiRouting(S2):
    def test_accept_negotiation(self):  # U2
        for p in ("/requests", "/authorizations"):
            s, h, b, raw = call("GET", p, headers={"Accept": "text/html,application/xhtml+xml"})
            self.assertEqual(s, 200)
            self.assertTrue(h["Content-Type"].startswith("text/html"))
            self.assertIn(b"<html", raw)
            s, h, b, raw = call("GET", p, headers={"Accept": "text/html"}, token=self.ada)
            self.assertEqual(s, 200)
            s, h, b, _ = call("GET", p)
            self.assertEqual(s, 401)
            self.assertEqual(h["Content-Type"], "application/json; charset=utf-8")
            s, h, b, _ = call("GET", p, token=self.ada, headers={"Accept": "application/json"})
            self.assertEqual(s, 200)
            self.assertIsInstance(b, dict)
            s, h, b, _ = call("GET", p, token=self.ada, headers={"Accept": "*/*"})
            self.assertEqual(s, 200)
            self.assertIsInstance(b, dict)
        for p in ("/", "/split", "/signup", "/login"):
            s, h, _, raw = call("GET", p, headers={"Accept": "text/html"})
            self.assertEqual(s, 200)
            self.assertIn(b"/static/app.js", raw)
        for m in ("POST", "PUT", "DELETE"):
            self.assertEqual(call(m, "/split")[0], 404)
        for p in ("/static/app.js", "/static/app.css"):
            self.assertEqual(call("GET", p)[0], 200)
        self.assertEqual(call("GET", "/static/nope.js")[0], 404)
        self.assertEqual(call("GET", "/static/../app.py")[0], 404)
        self.assertEqual(call("GET", "/static/%2e%2e/app.py")[0], 404)

    def test_odd_accept_headers_never_5xx(self):  # B2.6
        for acc in ("", "text/html;q=0", "*/*;q=0.1", "é", "x" * 5000, "text/html," * 500):
            for p in ("/requests", "/authorizations", "/", "/me"):
                try:
                    s = call("GET", p, token=self.ada, headers={"Accept": acc})[0]
                except UnicodeError:
                    continue
                self.assertLess(s, 500, (acc[:20], p))

    def test_no_stage3_surface(self):  # B2.4
        for m, p in (("GET", "/statement"), ("GET", "/me?as_of=2026-01-01T00:00:00Z"), ("POST", "/payments/p_1/refund"),
                     ("POST", "/corrections"), ("POST", "/payments/p_1/correct")):
            s = call(m, p, token=self.ada)[0]
            self.assertIn(s, (200, 404))
        m = call("GET", "/me?as_of=2000-01-01T00:00:00Z", token=self.ada)[2]
        self.assertEqual(m["total"], 10000)
        self.assertNotIn("as_of", m)


class RoundTrip(S2):
    def test_stage2_export_import(self):  # G5 G6
        a = self.auth(self.ada, "bob", 2000, note="d", visibility="private")[2]
        akey, ckey = k(), k()
        a2 = self.auth(self.ada, "cy", 100, key=akey)[2]
        cap = self.cap(self.bob, a["authorization_id"], {"amount": 300, "final": False}, ckey)[2]
        self.void(self.ada, a2["authorization_id"])
        before = {t: (me(t), call("GET", "/authorizations", token=t)[2], call("GET", "/activity", token=t)[2])
                  for t in (self.ada, self.bob, self.cy)}
        snap = call("GET", "/_test/export")[2]
        self.assertEqual((snap["track"], snap["format_version"]), ("pocketful", 1))
        reset(fixture(users=[user("zed", 1)], authorization_ttl_seconds=5))
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        after = {t: (me(t), call("GET", "/authorizations", token=t)[2], call("GET", "/activity", token=t)[2])
                 for t in (self.ada, self.bob, self.cy)}
        self.assertEqual(before, after)
        s, _, b, _ = self.cap(self.bob, a["authorization_id"], {"amount": 300, "final": False}, ckey)
        self.assertEqual((s, b), (200, cap))
        s, _, b, _ = self.auth(self.ada, "cy", 100, key=akey)
        self.assertEqual((s, b), (200, a2))
        err(self, self.auth(self.ada, "cy", 101, key=akey), 409, "idempotency_key_reuse")
        # ttl preserved
        n = self.auth(self.ada, "bob", 1)[2]
        self.assertEqual((datetime.fromisoformat(n["expires_at"]) - datetime.fromisoformat(n["created_at"])).total_seconds(), 600)
        ids = [x["authorization_id"] for x in call("GET", "/authorizations", token=self.ada)[2]["authorizations"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(me(self.ada)["total"] + me(self.bob)["total"] + me(self.cy)["total"], 13000)

    def test_stage1_export_accepted(self):  # G1 (synthetic stage-1 shape)
        pay(self.ada, "bob", 100)
        call("POST", "/requests", {"payer_handle": "ada", "amount": 50}, self.bob, k())
        snap = call("GET", "/_test/export")[2]
        st = snap["state"]
        for key in ("authorizations", "authorization_ttl_seconds"):
            st.pop(key)
        st["counters"].pop("a")
        for p in st["payments"]:
            p.pop("authorization_id")
        for e in st["idempotency"]:
            e["response"].pop("authorization_id", None)
        for u in st["users"]:  # stage-1 hash parameters
            pass
        reset(fixture(users=[user("zed", 1)]))
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        m = me(self.ada)
        self.assertEqual((m["total"], m["held"], m["available"]), (9900, 0, 9900))
        self.assertEqual(login("ada") is not None, True)
        rq = call("GET", "/requests", token=self.ada)[2]["requests"][0]["request_id"]
        self.assertEqual(call("POST", f"/requests/{rq}/pay", {}, self.ada, k())[0], 201)
        p = call("GET", "/activity", token=self.ada)[2]["payments"]
        self.assertTrue(all(x["authorization_id"] is None for x in p))
        self.assertEqual(self.auth(self.ada, "bob", 10)[0], 201)

    def test_invalid_authorization_state_rejected(self):  # G6
        self.auth(self.ada, "bob", 2000)
        good = call("GET", "/_test/export")[2]
        def mut(f):
            d = json.loads(json.dumps(good))
            f(d["state"])
            return d
        bads = [mut(lambda s: s["authorizations"][0].update(amount=-1)),
                mut(lambda s: s["authorizations"][0].update(status="weird")),
                mut(lambda s: s["authorizations"][0].update(expires_at="2026-01-01T00:00:00")),
                mut(lambda s: s["authorizations"][0].update(from_user_id="ghost")),
                mut(lambda s: s["authorizations"][0].update(captured_amount=99999)),
                mut(lambda s: s["authorizations"][0].update(payment_ids="x")),
                mut(lambda s: s["authorizations"][0].update(amount=10 ** 9)),   # hold above balance
                mut(lambda s: s.update(authorization_ttl_seconds=0)),
                mut(lambda s: s.update(authorizations="x"))]
        for bad in bads:
            before = call("GET", "/_test/export")[3]
            err(self, call("POST", "/_test/import", bad), 422, "validation_failed")
            self.assertEqual(call("GET", "/_test/export")[3], before)
        self.assertEqual(call("GET", "/authorizations", token=self.ada)[0], 200)

    def test_mutated_export_fuzz(self):
        self.auth(self.ada, "bob", 2000)
        cp = self.cap(self.bob, self.auth(self.ada, "bob", 100)[2]["authorization_id"], {"amount": 5, "final": False})
        good = call("GET", "/_test/export")[2]
        bad_values = [None, -1, 1.5, "x", "", True, [], {}, "2026-01-01T00:00:00", 10 ** 40]
        for key in ("authorizations", "authorization_ttl_seconds"):
            node = good["state"][key]
            paths = [[key]]
            if isinstance(node, list) and node:
                paths += [[key, 0, f] for f in node[0]]
            for path in paths:
                for bv in bad_values:
                    d = json.loads(json.dumps(good))
                    n = d["state"]
                    for p in path[:-1]:
                        n = n[p]
                    n[path[-1]] = bv
                    s = call("POST", "/_test/import", d)[0]
                    self.assertIn(s, (204, 422), (path, bv))
                    if s == 204:
                        for ep in ("/authorizations", "/me", "/activity"):
                            self.assertLess(call("GET", ep, token=self.ada)[0], 500, (path, bv, ep))
                        self.assertEqual(call("GET", "/_test/export")[0], 200)
                        call("POST", "/_test/import", good)


class Concurrent(S2):
    def burst(self, fn, n=50):
        with ThreadPoolExecutor(max_workers=n) as ex:
            return list(ex.map(fn, range(n)))

    def test_capture_races_never_overcapture(self):  # Z12 C2.2
        aid = self.auth(self.ada, "bob", 1000)[2]["authorization_id"]
        out = self.burst(lambda i: self.cap(self.bob, aid, {"amount": 100, "final": False}))
        ok = [r for r in out if r[0] == 201]
        self.assertEqual(len(ok), 10)
        self.assertTrue(all(r[0] in (201, 409) for r in out))
        self.assertTrue(all(r[2]["error"]["code"] == "authorization_not_open" for r in out if r[0] == 409))
        self.assertEqual(me(self.bob)["total"], 3500)
        self.assertEqual(me(self.ada)["total"], 9000)
        self.assertEqual(self.total(), 13000)

    def test_capture_vs_void_vs_final(self):  # C2.2
        for _ in range(5):
            aid = self.auth(self.ada, "bob", 100)[2]["authorization_id"]
            def act(i):
                if i % 3 == 0:
                    return ("c", self.cap(self.bob, aid, {"amount": 60, "final": False}))
                if i % 3 == 1:
                    return ("v", self.void(self.ada, aid))
                return ("f", self.cap(self.bob, aid, {"amount": 100}))
            out = self.burst(act, 30)
            self.assertTrue(all(r[1][0] < 500 for r in out))
            a = call("GET", "/authorizations?limit=1", token=self.ada)[2]["authorizations"][0]
            self.assertLessEqual(a["captured_amount"], 100)
            self.assertEqual(a["captured_amount"], sum(p["amount"] for p in
                             [x for x in call("GET", "/activity?limit=200", token=self.ada)[2]["payments"] if x["authorization_id"] == aid]))
            self.assertNotEqual(a["status"], "open")
            self.assertEqual(me(self.ada)["held"], 0)
        self.assertEqual(self.total(), 13000)

    def test_holds_never_overspend(self):  # W4 C2.1
        def op(i):
            m = i % 5
            if m == 0:
                return pay(self.cy, "bob", 100)
            if m == 1:
                return self.auth(self.cy, "bob", 150)
            if m == 2:
                return call("GET", "/me", token=self.cy)
            if m == 3:
                return call("GET", "/_test/export")
            return pay(self.ada, "cy", 10)
        for _ in range(3):
            out = self.burst(op, 50)
            self.assertTrue(all(r[0] < 500 for r in out))
            for r in out:
                if r[0] == 200 and r[2] and "available" in r[2]:
                    self.assertGreaterEqual(r[2]["available"], 0)
                    self.assertEqual(r[2]["available"], r[2]["total"] - r[2]["held"])
            m = me(self.cy)
            self.assertGreaterEqual(m["available"], 0)
        self.assertEqual(self.total(), 13000)

    def test_same_key_concurrent(self):  # Z18
        key = k()
        out = self.burst(lambda i: self.auth(self.ada, "bob", 100, key))
        self.assertEqual(sorted(r[0] for r in out), [200] * 49 + [201])
        self.assertEqual(len({r[3] for r in out}), 1)
        self.assertEqual(me(self.ada)["held"], 100)
        aid = out[0][2]["authorization_id"]
        key = k()
        out = self.burst(lambda i: self.cap(self.bob, aid, {"amount": 30, "final": False}, key))
        self.assertEqual(sorted(r[0] for r in out), [200] * 49 + [201])
        self.assertEqual(me(self.bob)["total"], 2530)

    def test_expiry_under_load(self):  # C2.1
        reset(fixture(authorization_ttl_seconds=1))
        ada, bob, cy = login("ada"), login("bob"), login("cy")
        def op(i):
            if i % 4 == 0:
                return call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, ada, k())
            if i % 4 == 1:
                return call("GET", "/me", token=ada)
            if i % 4 == 2:
                return call("POST", "/payments", {"to_handle": "cy", "amount": 100}, ada, k())
            return call("GET", "/authorizations?limit=200", token=bob)
        for _ in range(4):
            out = self.burst(op, 40)
            self.assertTrue(all(r[0] < 500 for r in out))
            for r in out:
                if r[0] == 200 and r[2] and "available" in r[2]:
                    self.assertGreaterEqual(r[2]["available"], 0)
            time.sleep(0.6)
        time.sleep(1.2)
        m = me(ada)
        self.assertEqual((m["held"], m["available"]), (0, m["total"]))
        self.assertEqual(sum(me(t)["total"] for t in (ada, bob, cy)), 13000)


if __name__ == "__main__":
    unittest.main()
