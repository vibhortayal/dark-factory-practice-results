"""Own API tests for Pocketful stage 3 (timestamps, as_of/known_at, statements, snapshots, corrections, holds, upgrade).

BASE_URL: stage-3 container. BASE_URL2 (optional): a second fresh stage-3 container.
BASE_URL_PREV1 / BASE_URL_PREV2 (optional): containers of the accepted stage-1 / stage-2 images (export sources).
"""
import json
import os
import re
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import test_stage1 as t1
from test_stage1 import BASE, BASE2, call, err, fixture, login, nk, reset, user

PREV1 = os.environ.get("BASE_URL_PREV1")
PREV2 = os.environ.get("BASE_URL_PREV2")
MICRO_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00$")


def Q(path, **params):
    parts = ["%s=%s" % (k, quote(str(v), safe="")) for k, v in params.items() if v is not None]
    return path + ("?" + "&".join(parts) if parts else "")


def iso(d):
    return d.astimezone(timezone.utc).isoformat(timespec="microseconds")


def now():
    return datetime.now(timezone.utc)


def dtp(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))


def me(tok, **p):
    return call("GET", Q("/me", **p), token=tok)


def pay(tok, to, amount, **kw):
    return call("POST", "/payments", {"to_handle": to, "amount": amount, **kw}, tok, nk())


def correct(tok, pid, rev, amount, eff, reason="why", key=None):
    return call("POST", "/payments/%s/corrections" % pid,
                {"expected_revision": rev, "amount": amount, "effective_at": eff, "reason": reason}, tok, key or nk())


def stmt(tok, **p):
    return call("GET", Q("/statement", **p), token=tok)


class Base(unittest.TestCase):
    def setUp(self):
        reset(fixture(users=[user("ada", 10000), user("bob", 2500), user("cy", 500), user("op", 0)], settlement_operator_ids=["u_op"]))
        self.ada, self.bob, self.cy, self.op = (login(h) for h in ("ada", "bob", "cy", "op"))


class TestTimestamps(Base):
    def test_created_at_microseconds_strictly_increasing(self):
        seen = []
        for i in range(30):
            seen.append(pay(self.ada, "bob", 1)[1]["created_at"])
        for x in seen:
            self.assertRegex(x, MICRO_RE)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(len(set(seen)), len(seen))
        # concurrent payments never tie either
        with ThreadPoolExecutor(30) as ex:
            rs = list(ex.map(lambda i: pay(self.ada, "bob", 1)[1]["created_at"], range(60)))
        self.assertEqual(len(set(rs)), 60)

    def test_activity_order_and_every_payment_endpoint_has_created_at(self):
        p = pay(self.ada, "bob", 5)[1]
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 6}, self.bob, nk())[1]["request_id"]
        q2 = call("POST", "/requests/%s/pay" % rq, {}, self.ada, nk())[1]
        s = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}, self.op, nk())[1]
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 50}, self.ada, nk())[1]
        c = call("POST", "/authorizations/%s/capture" % a["authorization_id"], {}, self.bob, nk())[1]
        for x in (p, q2, s["payments"][0], c):
            self.assertRegex(x["created_at"], MICRO_RE)
        self.assertEqual(s["payments"][0]["created_at"], s["committed_at"])
        feed = call("GET", "/activity", token=self.ada)[1]["payments"]
        self.assertEqual([x["created_at"] for x in feed], sorted((x["created_at"] for x in feed), reverse=True))
        st = stmt(self.ada)[1]["entries"]
        for e in st:
            self.assertRegex(e["payment"]["created_at"], MICRO_RE)

    def test_seeded_created_at(self):
        past = "2020-01-01T00:00:00+00:00"
        mid = "2021-06-01T12:00:00.5+02:00"
        pays = [{"id": "p_b", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "b", "visibility": "public", "created_at": mid},
                {"id": "p_a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 300, "note": "a", "visibility": "public", "created_at": past},
                {"id": "p_n1", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 100, "note": "n", "visibility": "public"},
                {"id": "p_n2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 50, "note": "n", "visibility": "private"}]
        reset(fixture(users=[user("ada", 10000), user("bob", 2500), user("cy", 500)], payments=pays))
        ada, bob, cy = login("ada"), login("bob"), login("cy")
        self.assertEqual(me(ada)[1]["balance"], 10000)  # seeded balances are final
        feed = call("GET", "/activity", token=bob)[1]["payments"]
        by = {x["payment_id"]: x for x in feed}
        self.assertEqual(by["p_a"]["created_at"], past)
        self.assertEqual(by["p_b"]["created_at"], mid)
        self.assertEqual(by["p_n1"]["created_at"], by["p_n2"]["created_at"])
        self.assertRegex(by["p_n1"]["created_at"], MICRO_RE)
        # ordered by created_at, newest first; the unsupplied ones (reset time) are newest, fixture order oldest -> newest
        self.assertEqual([x["payment_id"] for x in feed], ["p_n2", "p_n1", "p_b", "p_a"])
        later = pay(ada, "bob", 1)[1]
        self.assertGreater(later["created_at"], by["p_n1"]["created_at"])
        self.assertEqual(call("GET", "/activity", token=bob)[1]["payments"][0]["payment_id"], later["payment_id"])
        # opening balances: balance minus the net effect of the seeded payments
        self.assertEqual(me(ada, as_of="2019-01-01T00:00:00Z")[1]["balance"], 10000 + 800)
        self.assertEqual(me(ada, as_of=past)[1]["balance"], 10000 + 500)  # a payment AT as_of counts
        self.assertEqual(me(bob, as_of="2019-01-01T00:00:00Z")[1]["balance"], 2500 - 800 + 150)
        self.assertEqual(me(cy, as_of="2019-01-01T00:00:00Z")[1]["balance"], 500 - 150)
        # 21:... in UTC: 2021-06-01T10:00:00.5Z
        self.assertEqual(me(ada, as_of="2021-06-01T10:00:00.499999Z")[1]["balance"], 10000 + 500)
        self.assertEqual(me(ada, as_of="2021-06-01T10:00:00.5Z")[1]["balance"], 10000)
        self.assertEqual(me(ada, as_of="2021-06-01T12:00:00.500000+02:00")[1]["balance"], 10000)

    def test_bad_seeded_created_at(self):
        fut = iso(now() + timedelta(days=2))
        base_p = {"id": "p", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5, "note": "", "visibility": "public"}
        reset(fixture())
        a = login("ada")
        for bad in (fut, "2020-01-01", "2020-01-01 00:00:00Z", "2020-01-01T00:00:00", "nope", 5, None, "", ["x"], "2020-13-01T00:00:00Z",
                    "0000-01-01T00:00:00Z", "2020-01-01T24:00:00Z", "2020-01-01T00:00:60Z"):
            err(call("POST", "/_test/reset", fixture(payments=[{**base_p, "created_at": bad}])), 422, "validation_failed")
        self.assertEqual(me(a)[1]["balance"], 10000)  # nothing changed
        self.assertEqual(call("POST", "/_test/reset", fixture(payments=[{**base_p, "created_at": "2020-01-01T00:00:00z"}]))[0], 204)
        # an instant a moment before now is fine
        self.assertEqual(call("POST", "/_test/reset", fixture(payments=[{**base_p, "created_at": iso(now() - timedelta(seconds=1))}]))[0], 204)


class TestAsOf(Base):
    def test_grammar(self):
        ok = ["2026-09-24T13:20:00+00:00", "2026-09-24T13:20:00Z", "2026-09-24t13:20:00z", "2026-09-24T13:20:00.123456789012345+05:30",
              "2026-09-24T13:20:00-23:59", "2999-01-01T00:00:00Z", "0001-01-01T00:00:00Z", "9999-12-31T23:59:59.999999999999Z",
              "2026-09-24T13:20:00." + "0" * 3000 + "1Z", "2026-02-28T23:59:59+23:59"]
        bad = ["", "2026-09-24", "2026-09-24T13:20:00", "2026-09-24 13:20:00Z", "2026-09-24T13:20Z", "2026-09-24T13:20:00 00:00",
               "2026-09-24T24:00:00Z", "2026-09-24T13:60:00Z", "2026-09-24T13:20:60Z", "2026-13-24T13:20:00Z", "2026-02-30T13:20:00Z",
               "2025-02-29T00:00:00Z", "2026-09-24T13:20:00+24:00", "2026-09-24T13:20:00+00:60", "2026-09-24T13:20:00+0000", "2026-W39-4T00:00:00Z",
               "0000-01-01T00:00:00Z", "10000-01-01T00:00:00Z", "0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00",
               "2026-09-24T13:20:00.Z", "٢٠٢٦-09-24T13:20:00Z", "1e9", "now", "2026-09-24T13:20:00+00:00 ", " 2026-09-24T13:20:00Z"]
        for v in ok:
            for name in ("as_of", "known_at"):
                r = me(self.ada, **{name: v})
                self.assertEqual(r[0], 200, (name, v[:40], r))
                self.assertEqual(r[1][name], v)
        for v in bad:
            for name in ("as_of", "known_at"):
                err(me(self.ada, **{name: v}), 422, "validation_failed")
        # a raw plus in the query is a space, so it is invalid; %2B works
        err(call("GET", "/me?as_of=2026-09-24T13:20:00+00:00", token=self.ada), 422, "validation_failed")
        self.assertEqual(call("GET", "/me?as_of=2026-09-24T13:20:00%2B00:00", token=self.ada)[0], 200)
        err(call("GET", "/me?as_of=", token=self.ada), 422, "validation_failed")
        err(call("GET", "/me?known_at=", token=self.ada), 422, "validation_failed")
        for ep in ("/statement",):
            for name in ("from", "to", "known_at"):
                err(call("GET", Q(ep, **{name: "garbage"}), token=self.ada), 422, "validation_failed")
                err(call("GET", ep + "?" + name + "=", token=self.ada), 422, "validation_failed")

    def test_without_params_unchanged(self):
        j = me(self.ada)[1]
        self.assertNotIn("as_of", j)
        self.assertNotIn("known_at", j)
        self.assertEqual(set(j), {"user_id", "display_name", "handle", "balance", "total", "available", "held", "currency", "minor_units"})
        j = me(self.ada, known_at="2999-01-01T00:00:00Z")[1]
        self.assertNotIn("as_of", j)
        self.assertEqual(j["known_at"], "2999-01-01T00:00:00Z")

    def test_semantics_on_a_small_history(self):
        t0 = now()
        p1 = pay(self.ada, "bob", 300)[1]
        p2 = pay(self.bob, "ada", 100)[1]
        p3 = pay(self.ada, "cy", 50)[1]
        c1, c2, c3 = (dtp(p["created_at"]) for p in (p1, p2, p3))
        eps = timedelta(microseconds=1)
        v = lambda who, t: me(who, as_of=iso(t))[1]["balance"]
        self.assertEqual(v(self.ada, c1 - eps), 10000)   # opening
        self.assertEqual(v(self.ada, t0 - timedelta(days=1)), 10000)
        self.assertEqual(v(self.ada, c1), 9700)          # at the instant: counts
        self.assertEqual(v(self.ada, c2 - eps), 9700)
        self.assertEqual(v(self.ada, c2), 9800)
        self.assertEqual(v(self.ada, c3), 9750)
        self.assertEqual(v(self.ada, c3 + timedelta(days=1)), 9750)
        self.assertEqual(me(self.ada)[1]["balance"], 9750)
        self.assertEqual(v(self.cy, c3 - eps), 500)
        self.assertEqual(v(self.cy, c3), 550)
        # the same instant in another offset
        local = c2.astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat(timespec="microseconds")
        self.assertEqual(me(self.ada, as_of=local)[1]["balance"], 9800)
        # all wallets sum to the seeded total at every boundary
        for t in (c1 - eps, c1, c2, c3, c3 + eps):
            self.assertEqual(sum(me(tok, as_of=iso(t))[1]["balance"] for tok in (self.ada, self.bob, self.cy, self.op)), 13000)


class TestStatement(Base):
    def test_window_order_and_arithmetic(self):
        ps = [pay(self.ada, "bob", 300)[1], pay(self.bob, "ada", 120)[1], pay(self.ada, "cy", 40, visibility="private")[1],
              pay(self.bob, "cy", 10)[1]]  # the last one is not ada's: public, between two others
        s, j, _ = stmt(self.ada)
        self.assertEqual(s, 200)
        self.assertEqual(set(j), {"opening_balance", "entries", "closing_balance", "has_more", "snapshot"})
        self.assertEqual([e["payment"]["payment_id"] for e in j["entries"]], [p["payment_id"] for p in ps[:3]])
        self.assertEqual([e["delta"] for e in j["entries"]], [-300, 120, -40])
        self.assertEqual([e["balance_after"] for e in j["entries"]], [9700, 9820, 9780])
        self.assertEqual((j["opening_balance"], j["closing_balance"], j["has_more"]), (10000, 9780, False))
        for e in j["entries"]:
            self.assertEqual(set(e), {"payment", "delta", "balance_after", "revision", "effective_at", "recorded_at"})
            self.assertEqual((e["revision"], e["effective_at"], e["recorded_at"]), (1, e["payment"]["created_at"], e["payment"]["created_at"]))
        self.assertEqual(j["closing_balance"], me(self.ada)[1]["balance"])
        # bob sees the public one too only as far as it is his
        jb = stmt(self.bob)[1]
        self.assertEqual([e["delta"] for e in jb["entries"]], [300, -120, -10])
        # window: [from, to) half open
        c = [dtp(p["created_at"]) for p in ps]
        w = stmt(self.ada, **{"from": iso(c[1]), "to": iso(c[2])})[1]
        self.assertEqual([e["payment"]["payment_id"] for e in w["entries"]], [ps[1]["payment_id"]])
        self.assertEqual((w["opening_balance"], w["closing_balance"]), (9700, 9820))
        w = stmt(self.ada, **{"from": iso(c[1]), "to": iso(c[2] + timedelta(microseconds=1))})[1]
        self.assertEqual(len(w["entries"]), 2)
        w = stmt(self.ada, **{"from": iso(c[2] + timedelta(microseconds=1))})[1]
        self.assertEqual((w["entries"], w["opening_balance"], w["closing_balance"]), ([], 9780, 9780))
        w = stmt(self.ada, **{"from": iso(c[1]), "to": iso(c[1])})[1]
        self.assertEqual((w["entries"], w["opening_balance"], w["closing_balance"]), ([], 9700, 9700))
        w = stmt(self.ada, to=iso(c[0]))[1]
        self.assertEqual((w["entries"], w["opening_balance"], w["closing_balance"]), ([], 10000, 10000))
        err(stmt(self.ada, **{"from": iso(c[2]), "to": iso(c[1])}), 422, "validation_failed")

    def test_pagination_keeps_balances(self):
        for i in range(12):
            pay(self.ada, "bob", 10 + i)
        full = stmt(self.ada)[1]
        for limit in (1, 3, 5, 12, 50):
            seen, off = [], 0
            while True:
                j = stmt(self.ada, limit=limit, offset=off)[1]
                self.assertEqual((j["opening_balance"], j["closing_balance"]), (full["opening_balance"], full["closing_balance"]))
                seen += j["entries"]
                self.assertEqual(j["has_more"], off + limit < 12)
                if not j["has_more"]:
                    break
                off += limit
            self.assertEqual([(e["payment"]["payment_id"], e["balance_after"]) for e in seen],
                            [(e["payment"]["payment_id"], e["balance_after"]) for e in full["entries"]])
        for off in (12, 13, 1000, 10 ** 40):
            j = stmt(self.ada, offset=off)[1]
            self.assertEqual((j["entries"], j["has_more"], j["opening_balance"], j["closing_balance"]), ([], False, 10000, full["closing_balance"]))
        for bad in ("limit=0", "limit=201", "offset=-1", "limit=1e2", "offset=1.0", "limit=", "offset=abc", "limit=+4"):
            err(call("GET", "/statement?" + bad, token=self.ada), 422, "validation_failed")
        self.assertEqual(call("GET", "/statement?limit=0050&offset=000&zzz=1&as_of=junk", token=self.ada)[0], 200)

    def test_snapshots(self):
        for i in range(8):
            pay(self.ada, "bob", 5 + i)
        j = stmt(self.ada, limit=3)[1]
        tok = j["snapshot"]
        self.assertTrue(isinstance(tok, str) and 0 < len(tok) <= 200)
        first = stmt(self.ada, snapshot=tok, limit=100)[1]
        self.assertEqual(len(first["entries"]), 8)
        self.assertEqual(first["snapshot"], tok)
        # change everything: payments, corrections
        later = pay(self.ada, "bob", 1)[1]
        pid = first["entries"][0]["payment"]["payment_id"]
        c = correct(self.ada, pid, 1, 777, iso(now()))
        self.assertEqual(c[0], 201)
        again = stmt(self.ada, snapshot=tok, limit=100)[1]
        self.assertEqual(again, first)
        live = stmt(self.ada, limit=100)[1]
        self.assertNotEqual(live["closing_balance"], first["closing_balance"])
        self.assertEqual(len(live["entries"]), 9)
        # pages of the snapshot are consistent
        parts = []
        for off in (0, 3, 6, 9):
            parts += stmt(self.ada, snapshot=tok, limit=3, offset=off)[1]["entries"]
        self.assertEqual(parts, first["entries"])
        self.assertEqual(stmt(self.ada, snapshot=tok, limit=3, offset=5)[1]["has_more"], False)
        self.assertEqual(stmt(self.ada, snapshot=tok, limit=3, offset=4)[1]["has_more"], True)
        self.assertEqual(stmt(self.ada, snapshot=tok, offset=99)[1]["entries"], [])
        # forbidden companions, unknown / other user's / empty tokens
        for extra in ({"from": "2020-01-01T00:00:00Z"}, {"to": "2999-01-01T00:00:00Z"}, {"known_at": "2999-01-01T00:00:00Z"}, {"from": "junk"}):
            err(stmt(self.ada, snapshot=tok, **extra), 422, "validation_failed")
            err(stmt(self.ada, snapshot="unknown-token", **extra), 422, "validation_failed")
        err(stmt(self.ada, snapshot="unknown-token"), 404, "not_found")
        err(stmt(self.ada, snapshot=tok + "x"), 404, "not_found")
        err(stmt(self.ada, snapshot=tok[:-2]), 404, "not_found")
        err(call("GET", "/statement?snapshot=", token=self.ada), 404, "not_found")
        err(stmt(self.bob, snapshot=tok), 404, "not_found")
        err(call("GET", Q("/statement", snapshot=tok), token=None), 401, "unauthenticated")
        self.assertEqual(stmt(self.ada, snapshot=tok, limit=2, zzz=5)[0], 200)
        # a snapshot with a known_at cut keeps the cut
        cut = iso(dtp(first["entries"][3]["payment"]["created_at"]))
        j2 = stmt(self.ada, known_at=cut)[1]
        self.assertEqual(len(j2["entries"]), 4)
        pay(self.ada, "cy", 3)
        self.assertEqual(len(stmt(self.ada, snapshot=j2["snapshot"], limit=100)[1]["entries"]), 4)
        # tokens of the previous state are gone after a reset
        reset(fixture(users=[user("ada", 10000), user("bob", 2500), user("cy", 500), user("op", 0)]))
        self.ada = login("ada")
        err(stmt(self.ada, snapshot=tok), 404, "not_found")
        # snapshot tokens are many but cheap: a memory-flat read path
        toks = {stmt(self.ada)[1]["snapshot"] for _ in range(50)}
        self.assertEqual(len(toks), 50)

    def test_snapshot_survives_own_export_import_and_dies_with_other_state(self):
        pay(self.ada, "bob", 10)
        j = stmt(self.ada)[1]
        tok = j["snapshot"]
        ex = call("GET", "/_test/export")[1]
        pay(self.ada, "bob", 20)
        reset(fixture(users=[user("ada", 10000), user("bob", 2500), user("cy", 500), user("op", 0)]))
        ada = login("ada")
        err(stmt(ada, snapshot=tok), 404, "not_found")
        self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        self.assertEqual(stmt(self.ada, snapshot=tok, limit=100)[1]["entries"], j["entries"])
        # importing another state replaces the secret: the token is dead there
        other = {"track": "pocketful", "format_version": 1, "state": ex["state"]}
        reset(fixture())
        ex2 = call("GET", "/_test/export")[1]
        self.assertEqual(call("POST", "/_test/import", ex2)[0], 204)
        err(stmt(login("ada"), snapshot=tok), 404, "not_found")


class TestCorrections(Base):
    def test_validation_auth_and_errors(self):
        p = pay(self.ada, "bob", 300)[1]
        pid = p["payment_id"]
        eff = iso(now())
        path = "/payments/%s/corrections" % pid
        good = {"expected_revision": 1, "amount": 200, "effective_at": eff, "reason": "r"}
        err(call("POST", path, good, None, nk()), 401, "unauthenticated")
        err(call("POST", path, good, self.ada), 400, "missing_idempotency_key")
        err(call("POST", path, good, self.ada, "k" * 256), 422, "validation_failed")
        err(call("POST", path, raw=b"{x", token=self.ada, key=nk()), 400, "malformed_request")
        err(call("POST", path, raw=b"[1]", token=self.ada, key=nk()), 400, "malformed_request")
        err(call("POST", path, good, self.bob, nk()), 403, "forbidden")
        err(call("POST", path, good, self.cy, nk()), 403, "forbidden")
        err(call("POST", "/payments/nope/corrections", good, self.ada, nk()), 404, "not_found")
        for f in good:
            body = dict(good)
            del body[f]
            err(call("POST", path, body, self.ada, nk()), 422, "validation_failed")
        bads = {"expected_revision": [0, -1, 1.5, "1", True, None, [], {}, 10 ** 40], "amount": [-1, 1000000001, 1.5, "5", True, None, [], 10 ** 40],
                "effective_at": ["", "2020-01-01", "2020-01-01T00:00:00", 5, None, True, "2999-01-01T00:00:00Z", iso(now() + timedelta(hours=1)), [], "x"],
                "reason": ["", "x" * 201, 5, None, True, [], {}]}
        for f, vals in bads.items():
            for v in vals:
                err(call("POST", path, {**good, f: v}, self.ada, nk()), 422, "validation_failed")
        self.assertEqual(me(self.ada)[1]["balance"], 9700)
        for amount, reason in ((0, "r"), (1000000000, "x" * 200), (1.0, "é" * 200), (1e2, "r")):
            pass
        # boundary values accepted: reason 200 characters (code points), amount 0 .. 1e9 (unaffordable ones are refused later)
        r = call("POST", path, {**good, "amount": 300, "reason": "é" * 200}, self.ada, nk())
        self.assertEqual(r[0], 201)
        err(call("POST", path, {**good, "expected_revision": 2, "amount": 1000000000}, self.ada, nk()), 409, "insufficient_funds")
        self.assertEqual(call("POST", path, {**good, "expected_revision": 2, "amount": 1e2}, self.ada, nk())[0], 201)

    def test_success_shape_conservation_and_original_untouched(self):
        p = pay(self.ada, "bob", 300, note="n", visibility="private")[1]
        pid = p["payment_id"]
        key = nk()
        eff = "2020-01-01T00:00:00+00:00"
        s, j, _ = call("POST", "/payments/%s/corrections" % pid, {"expected_revision": 1, "amount": 100, "effective_at": eff, "reason": "less"}, self.ada, key)
        self.assertEqual(s, 201)
        self.assertEqual(set(j), {"payment_id", "revision", "amount", "effective_at", "recorded_at", "reason"})
        self.assertEqual((j["payment_id"], j["revision"], j["amount"], j["effective_at"], j["reason"]), (pid, 2, 100, eff, "less"))
        self.assertRegex(j["recorded_at"], MICRO_RE)
        self.assertGreater(j["recorded_at"], p["created_at"])
        self.assertEqual((me(self.ada)[1]["balance"], me(self.bob)[1]["balance"]), (9900, 2600))
        self.assertEqual(sum(me(t)[1]["balance"] for t in (self.ada, self.bob, self.cy, self.op)), 13000)
        # replay after newer revisions
        j3 = correct(self.ada, pid, 2, 150, iso(now()))[1]
        self.assertEqual(j3["revision"], 3)
        s, rj, _ = call("POST", "/payments/%s/corrections" % pid, {"expected_revision": 1, "amount": 100, "effective_at": eff, "reason": "less"}, self.ada, key)
        self.assertEqual((s, rj), (200, j))
        err(call("POST", "/payments/%s/corrections" % pid, {"expected_revision": 1, "amount": 101, "effective_at": eff, "reason": "less"}, self.ada, key), 409, "idempotency_key_reuse")
        err(call("POST", "/payments/%s/corrections" % pid, {"expected_revision": 1, "amount": 100, "effective_at": eff, "reason": "less", "x": 1}, self.ada, key), 409, "idempotency_key_reuse")
        # stale
        err(correct(self.ada, pid, 2, 10, iso(now())), 409, "stale_revision")
        err(correct(self.ada, pid, 9, 10, iso(now())), 409, "stale_revision")
        self.assertEqual(call("POST", "/payments/%s/corrections" % pid, {"expected_revision": 3, "amount": 150, "effective_at": eff, "reason": "same amount"}, self.ada, nk())[0], 201)
        # the original payment and the feed are untouched, corrections are no feed items
        feed = call("GET", "/activity", token=self.bob)[1]["payments"]
        self.assertEqual(feed, [p])
        self.assertEqual(pay(self.ada, "bob", 300, note="n", visibility="private")[0], 201)
        # the original idempotent response replays unchanged
        k = nk()
        o = call("POST", "/payments", {"to_handle": "cy", "amount": 40}, self.ada, k)[1]
        correct(self.ada, o["payment_id"], 1, 0, iso(now()))
        self.assertEqual(call("POST", "/payments", {"to_handle": "cy", "amount": 40}, self.ada, k)[:2], (200, o))
        # revisions endpoint
        revs = call("GET", "/payments/%s/revisions" % pid, token=self.ada)[1]["revisions"]
        self.assertEqual([r["revision"] for r in revs], [1, 2, 3, 4])
        self.assertEqual(revs[0], {"payment_id": pid, "revision": 1, "amount": 300, "effective_at": p["created_at"], "recorded_at": p["created_at"], "reason": ""})
        self.assertEqual(revs[1], j)
        self.assertEqual(call("GET", "/payments/%s/revisions" % pid, token=self.bob)[1]["revisions"], revs)
        err(call("GET", "/payments/%s/revisions" % pid, token=self.cy), 404, "not_found")
        err(call("GET", "/payments/%s/revisions" % pid, token=self.op), 404, "not_found")
        err(call("GET", "/payments/nope/revisions", token=self.ada), 404, "not_found")
        err(call("GET", "/payments/%s/revisions" % pid, token=None), 401, "unauthenticated")
        rec = [r["recorded_at"] for r in revs]
        self.assertEqual(rec, sorted(rec))
        self.assertEqual(len(set(rec)), len(rec))

    def test_increase_decrease_directions_and_precedence(self):
        p = pay(self.ada, "bob", 2000)[1]
        pid, c0 = p["payment_id"], p["created_at"]
        # decrease debits the receiver (same effective time: only the amount changes)
        self.assertEqual(correct(self.ada, pid, 1, 1500, c0)[0], 201)
        self.assertEqual((me(self.ada)[1]["balance"], me(self.bob)[1]["balance"]), (8500, 4000))
        # bob spends almost everything, then a decrease by 600 cannot be afforded by bob
        pay(self.bob, "cy", 3900)
        err(correct(self.ada, pid, 2, 900, c0), 409, "insufficient_funds")
        self.assertEqual((me(self.ada)[1]["balance"], me(self.bob)[1]["balance"]), (8500, 100))
        # increase debits the sender: ada holds nearly all of her money
        call("POST", "/authorizations", {"to_handle": "cy", "amount": 8400}, self.ada, nk())
        err(correct(self.ada, pid, 2, 1700, c0), 409, "insufficient_funds")  # 200 > available 100
        self.assertEqual(correct(self.ada, pid, 2, 1600, c0)[0], 201)  # exactly the available 100
        self.assertEqual(me(self.ada)[1]["available"], 0)
        revs = call("GET", "/payments/%s/revisions" % pid, token=self.ada)[1]["revisions"]
        self.assertEqual([r["amount"] for r in revs], [2000, 1500, 1600])

    def test_historical_overdraft(self):
        # ada is paid 1000 by cy at T1, spends 900 to bob at T2; re-timing cy's payment after T2 overdraws ada at T2
        reset(fixture(users=[user("ada", 100), user("bob", 2500), user("cy", 5000)],
                      payments=[{"id": "p_in", "from_user_id": "u_cy", "to_user_id": "u_ada", "amount": 1000, "note": "", "visibility": "public",
                                 "created_at": "2021-01-01T00:00:00Z"},
                                {"id": "p_out", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 900, "note": "", "visibility": "public",
                                 "created_at": "2021-01-02T00:00:00Z"}]))
        ada, bob, cy = login("ada"), login("bob"), login("cy")
        self.assertEqual(me(ada, as_of="2020-01-01T00:00:00Z")[1]["balance"], 0)
        # moving p_in after p_out: ada would be at -900 at 2021-01-02
        err(correct(cy, "p_in", 1, 1000, "2021-01-03T00:00:00Z"), 409, "historical_overdraft")
        # same instant: movements at one boundary are combined
        self.assertEqual(correct(cy, "p_in", 1, 1000, "2021-01-02T00:00:00Z")[0], 201)
        # reducing p_in below p_out overdraws ada (and receiver cannot be debited: ada has 100 now -> insufficient first)
        err(correct(cy, "p_in", 2, 0, "2021-01-01T00:00:00Z"), 409, "insufficient_funds")
        # nothing changed by the refusals
        self.assertEqual(me(ada)[1]["balance"], 100)
        self.assertEqual([r["revision"] for r in call("GET", "/payments/p_in/revisions", token=cy)[1]["revisions"]], [1, 2])
        # a re-timing to before an account existed is judged against opening 0: ada's opening is 0
        e = correct(cy, "p_in", 2, 1000, "2000-01-01T00:00:00Z")
        self.assertEqual(e[0], 201)
        # equal amount, only re-timing, is valid (G-7); here it fails the history check
        err(correct(cy, "p_in", 3, 1000, "2021-01-03T00:00:00Z"), 409, "historical_overdraft")
        # zero reversal: ada's later payment would overdraw
        self.assertEqual(me(ada, as_of="2021-01-01T12:00:00Z")[1]["balance"], 1000)

    def test_known_at_semantics(self):
        p = pay(self.ada, "bob", 300)[1]
        pid = p["payment_id"]
        c0 = dtp(p["created_at"])
        r2 = correct(self.ada, pid, 1, 100, iso(c0 - timedelta(seconds=5)))[1]
        r3 = correct(self.ada, pid, 2, 0, iso(c0 - timedelta(seconds=2)))[1]
        t2, t3 = dtp(r2["recorded_at"]), dtp(r3["recorded_at"])
        eps = timedelta(microseconds=1)
        bal = lambda **kw: me(self.ada, **kw)[1]["balance"]
        far = iso(c0 + timedelta(days=1))
        # K before the payment was known: contributes nothing
        self.assertEqual(bal(as_of=far, known_at=iso(c0 - eps)), 10000)
        self.assertEqual(bal(as_of=far, known_at=iso(c0)), 9700)
        self.assertEqual(bal(as_of=far, known_at=iso(t2 - eps)), 9700)
        self.assertEqual(bal(as_of=far, known_at=iso(t2)), 9900)
        self.assertEqual(bal(as_of=far, known_at=iso(t3)), 10000)
        self.assertEqual(bal(as_of=far, known_at="2999-01-01T00:00:00Z"), 10000)
        # effective times: revision 2 is effective 5 s before the creation
        self.assertEqual(bal(as_of=iso(c0 - timedelta(seconds=6)), known_at=iso(t2)), 10000)
        self.assertEqual(bal(as_of=iso(c0 - timedelta(seconds=5)), known_at=iso(t2)), 9900)
        self.assertEqual(bal(as_of=iso(c0 - timedelta(seconds=3)), known_at=iso(t3 - eps)), 9900)
        self.assertEqual(bal(as_of=iso(c0 - timedelta(seconds=2)), known_at=iso(t3)), 10000)
        # statements by known_at: the payment appears once, with the selected revision
        s0 = stmt(self.ada, known_at=iso(c0))[1]
        self.assertEqual([(e["revision"], e["delta"], e["payment"]["amount"]) for e in s0["entries"]], [(1, -300, 300)])
        s2 = stmt(self.ada, known_at=iso(t2))[1]
        self.assertEqual([(e["revision"], e["delta"], e["payment"]["amount"], e["effective_at"]) for e in s2["entries"]],
                         [(2, -100, 100, iso(c0 - timedelta(seconds=5)))])
        s3 = stmt(self.ada)[1]
        self.assertEqual([(e["revision"], e["delta"]) for e in s3["entries"]], [(3, 0)])  # zero revisions still appear
        self.assertEqual((s3["opening_balance"], s3["closing_balance"]), (10000, 10000))
        self.assertEqual(stmt(self.ada, known_at=iso(c0 - eps))[1]["entries"], [])
        # the correction moves the payment out of a window
        w = stmt(self.ada, **{"from": iso(c0 - timedelta(seconds=1)), "known_at": iso(c0)})[1]
        self.assertEqual(len(w["entries"]), 1)
        w = stmt(self.ada, **{"from": iso(c0 - timedelta(seconds=1))})[1]
        self.assertEqual(w["entries"], [])
        w = stmt(self.ada, **{"to": iso(c0 - timedelta(seconds=4)), "known_at": iso(t2)})[1]
        self.assertEqual([e["revision"] for e in w["entries"]], [2])
        self.assertEqual((w["opening_balance"], w["closing_balance"]), (10000, 9900))

    def test_linked_payments_are_immutable(self):
        s = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 50}]}, self.op, nk())[1]
        m = s["payments"][0]
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 60}, self.ada, nk())[1]
        c = call("POST", "/authorizations/%s/capture" % a["authorization_id"], {"amount": 40}, self.bob, nk())[1]
        for p in (m, c):
            err(correct(self.ada, p["payment_id"], 1, 1, iso(now())), 422, "linked_payment_immutable")
            err(correct(self.cy, p["payment_id"], 1, 1, iso(now())), 403, "forbidden")  # permission first
            revs = call("GET", "/payments/%s/revisions" % p["payment_id"], token=self.ada)[1]["revisions"]
            self.assertEqual(len(revs), 1)
        # revision 1 of a settlement member: effective = recorded = committed_at
        revs = call("GET", "/payments/%s/revisions" % m["payment_id"], token=self.ada)[1]["revisions"]
        self.assertEqual((revs[0]["effective_at"], revs[0]["recorded_at"]), (s["committed_at"], s["committed_at"]))
        err(call("GET", "/payments/%s/revisions" % m["payment_id"], token=self.op), 404, "not_found")
        # paying a request makes an ordinary payment: correctable
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 70}, self.bob, nk())[1]["request_id"]
        pp = call("POST", "/requests/%s/pay" % rq, {}, self.ada, nk())[1]
        self.assertEqual(correct(self.ada, pp["payment_id"], 1, 30, iso(now()))[0], 201)
        # a capture keeps appearing exactly once, with its links
        st = stmt(self.bob)[1]["entries"]
        caps = [e for e in st if e["payment"]["authorization_id"] == a["authorization_id"]]
        self.assertEqual(len(caps), 1)
        mem = [e for e in st if e["payment"]["settlement_id"] == s["settlement_id"]]
        self.assertEqual(len(mem), 1)
        # authorisation, release, expiry are not statement entries
        self.assertEqual(len({e["payment"]["payment_id"] for e in st}), len(st))

    def test_concurrent_corrections_same_revision(self):
        p = pay(self.ada, "bob", 300)[1]
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: correct(self.ada, p["payment_id"], 1, 10 + i, iso(now())), range(50)))
        self.assertEqual(sorted(r[0] for r in rs).count(201), 1)
        self.assertTrue(all(r[0] in (201, 409) for r in rs))
        self.assertEqual(len(call("GET", "/payments/%s/revisions" % p["payment_id"], token=self.ada)[1]["revisions"]), 2)
        k = nk()
        body = {"expected_revision": 2, "amount": 5, "effective_at": iso(now()), "reason": "same key"}
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: call("POST", "/payments/%s/corrections" % p["payment_id"], body, self.ada, k), range(50)))
        self.assertEqual(sorted(r[0] for r in rs), [200] * 49 + [201])
        self.assertEqual(len({json.dumps(r[1], sort_keys=True) for r in rs}), 1)
        self.assertEqual(sum(me(t)[1]["balance"] for t in (self.ada, self.bob, self.cy, self.op)), 13000)


class TestHoldsHistory(Base):
    def test_closed_at_and_hold_views(self):
        t0 = now()
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, self.ada, nk())[1]
        self.assertIsNone(a["closed_at"])
        aid = a["authorization_id"]
        c0, ex = dtp(a["created_at"]), dtp(a["expires_at"])
        eps = timedelta(microseconds=1)
        v = lambda t, **kw: me(self.ada, as_of=iso(t), **kw)[1]
        self.assertEqual(v(c0 - eps)["held"], 0)
        self.assertEqual(v(c0)["held"], 1000)
        self.assertEqual(v(c0)["available"], 9000)
        p1 = call("POST", "/authorizations/%s/capture" % aid, {"amount": 300, "final": False}, self.bob, nk())[1]
        tp1 = dtp(p1["created_at"])
        self.assertEqual(v(tp1 - eps), {**v(tp1 - eps)})
        self.assertEqual((v(tp1 - eps)["total"], v(tp1 - eps)["held"]), (10000, 1000))
        self.assertEqual((v(tp1)["total"], v(tp1)["held"], v(tp1)["available"]), (9700, 700, 9000))
        x = call("POST", "/authorizations/%s/void" % aid, None, self.ada)[1]
        self.assertEqual(x["status"], "voided")
        tv = dtp(x["closed_at"])
        self.assertRegex(x["closed_at"], MICRO_RE)
        self.assertEqual(v(tv - eps)["held"], 700)
        self.assertEqual(v(tv)["held"], 0)
        self.assertEqual(v(tv)["available"], 9700)
        # known_at before the void: the void is not known, the hold stays until the deadline
        self.assertEqual(me(self.ada, as_of=iso(tv + timedelta(seconds=1)), known_at=iso(tv - eps))[1]["held"], 700)
        self.assertEqual(me(self.ada, as_of=iso(ex - eps), known_at=iso(tv - eps))[1]["held"], 700)
        self.assertEqual(me(self.ada, as_of=iso(ex), known_at=iso(tv - eps))[1]["held"], 0)  # deadline known once creation is known
        # a known_at before creation: nothing
        self.assertEqual(me(self.ada, as_of=iso(tv), known_at=iso(c0 - eps))[1]["held"], 0)
        # beyond now: an open hold expires at its deadline
        b = call("POST", "/authorizations", {"to_handle": "bob", "amount": 500}, self.ada, nk())[1]
        eb = dtp(b["expires_at"])
        self.assertEqual(me(self.ada, as_of=iso(eb - eps))[1]["held"], 500)
        self.assertEqual(me(self.ada, as_of=iso(eb))[1]["held"], 0)
        self.assertEqual(me(self.ada, as_of=iso(eb + timedelta(days=9)))[1]["available"], me(self.ada, as_of=iso(eb))[1]["total"])
        # default as_of is the request instant
        self.assertEqual(me(self.ada, known_at="2999-01-01T00:00:00Z")[1]["held"], 500)
        # final capture closes at the capture time
        d = call("POST", "/authorizations", {"to_handle": "cy", "amount": 200}, self.ada, nk())[1]
        pf = call("POST", "/authorizations/%s/capture" % d["authorization_id"], {"amount": 50}, self.cy, nk())[1]
        got = [x for x in call("GET", "/authorizations", token=self.ada)[1]["authorizations"] if x["authorization_id"] == d["authorization_id"]][0]
        self.assertEqual((got["status"], got["closed_at"]), ("captured", pf["created_at"]))
        self.assertEqual(me(self.ada, as_of=pf["created_at"])[1]["held"], 500)

    def test_overdraft_by_holds(self):
        # holds count: re-timing a received payment after a hold was placed makes available negative then
        reset(fixture(users=[user("ada", 100), user("bob", 0), user("cy", 5000)], payments=[
            {"id": "p_in", "from_user_id": "u_cy", "to_user_id": "u_ada", "amount": 50, "note": "", "visibility": "public",
             "created_at": iso(now() - timedelta(hours=1))}]))
        ada, cy = login("ada"), login("cy")
        self.assertEqual(me(ada, as_of=iso(now() - timedelta(hours=2)))[1]["balance"], 50)
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, ada, nk())
        self.assertEqual(a[0], 201)
        # re-timing p_in to now is fine for total (the hold needs 100, total at hold creation would be 50) -> overdraft
        err(correct(cy, "p_in", 1, 50, iso(now())), 409, "historical_overdraft")
        self.assertEqual(correct(cy, "p_in", 1, 50, iso(now() - timedelta(minutes=30)))[0], 201)


class TestExpiryHistory(unittest.TestCase):
    def test_expired_hold_closed_at_and_history(self):
        reset(fixture(users=[user("ada", 1000), user("bob", 0)], authorization_ttl_seconds=1))
        ada = login("ada")
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 400}, ada, nk())[1]
        time.sleep(1.3)
        got = call("GET", "/authorizations", token=ada)[1]["authorizations"][0]
        self.assertEqual((got["status"], got["closed_at"]), ("expired", a["expires_at"]))
        ex = dtp(a["expires_at"])
        self.assertEqual(me(ada, as_of=iso(ex - timedelta(microseconds=1)))[1]["held"], 400)
        self.assertEqual(me(ada, as_of=iso(ex))[1]["held"], 0)
        self.assertEqual(me(ada)[1]["held"], 0)


class TestSeededHolds(unittest.TestCase):
    def test_seeded_holds_history(self):
        future = iso(now() + timedelta(days=1))
        reset(fixture(users=[user("ada", 1000), user("bob", 0)], authorizations=[
            {"id": "a_open", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 300, "status": "open", "expires_at": future},
            {"id": "a_cap", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "status": "captured", "expires_at": future},
            {"id": "a_void", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "status": "voided", "expires_at": future},
            {"id": "a_exp", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "status": "expired", "expires_at": "2020-01-01T00:00:00Z"},
            {"id": "a_exp2", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "status": "expired", "expires_at": future},
            {"id": "a_ct", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 50, "status": "open", "expires_at": future,
             "created_at": "2021-01-01T00:00:00Z"}]))
        ada = login("ada")
        auth = {x["authorization_id"]: x for x in call("GET", "/authorizations", token=ada)[1]["authorizations"]}
        self.assertIsNone(auth["a_open"]["closed_at"])
        self.assertEqual(auth["a_exp"]["closed_at"], "2020-01-01T00:00:00Z")
        for k in ("a_cap", "a_void", "a_exp2"):
            self.assertRegex(auth[k]["closed_at"], MICRO_RE)
        self.assertEqual(auth["a_ct"]["created_at"], "2021-01-01T00:00:00Z")
        self.assertEqual(me(ada)[1]["held"], 350)
        self.assertEqual(me(ada, as_of="2021-06-01T00:00:00Z")[1]["held"], 50)  # a_open starts at reset, a_ct earlier
        self.assertEqual(me(ada, as_of="2020-06-01T00:00:00Z")[1]["held"], 0)
        self.assertEqual(me(ada, as_of=iso(now() + timedelta(hours=1)))[1]["held"], 350)
        self.assertEqual(me(ada, as_of=iso(now() + timedelta(days=3)))[1]["held"], 0)
        err(call("POST", "/_test/reset", fixture(users=[user("ada", 1000), user("bob", 0)], authorizations=[
            {"id": "a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 3, "status": "open", "expires_at": future,
             "created_at": iso(now() + timedelta(hours=1))}])), 422, "validation_failed")
        err(call("POST", "/_test/reset", fixture(users=[user("ada", 1000), user("bob", 0)], authorizations=[
            {"id": "a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 3, "status": "open", "expires_at": future,
             "created_at": "2021-01-01"}])), 422, "validation_failed")


class TestCorrectionIdempotency(Base):
    def test_rows_f(self):
        p = pay(self.ada, "bob", 300)[1]
        pid = p["payment_id"]
        path = "/payments/%s/corrections" % pid
        body = {"expected_revision": 1, "amount": 200, "effective_at": p["created_at"], "reason": "r"}
        # a failed request claims nothing: a 422 and a 409 leave the key reusable
        k = nk()
        err(call("POST", path, {**body, "amount": -1}, self.ada, k), 422, "validation_failed")
        err(call("POST", path, {**body, "expected_revision": 7}, self.ada, k), 409, "stale_revision")
        err(call("POST", path, body, self.bob, k), 403, "forbidden")
        r1 = call("POST", path, body, self.ada, k)
        self.assertEqual(r1[0], 201)
        # once claimed: replay 200; a different (even invalid) body is a reuse conflict before any validation
        self.assertEqual(call("POST", path, {"reason": "r", "effective_at": p["created_at"], "amount": 200.0, "expected_revision": 1}, self.ada, k)[:2], (200, r1[1]))
        err(call("POST", path, {**body, "amount": -1}, self.ada, k), 409, "idempotency_key_reuse")
        err(call("POST", path, {}, self.ada, k), 409, "idempotency_key_reuse")
        # scoped to the user; the same key and body on another path is a first use
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, self.ada, k)[0], 201)
        p2 = pay(self.bob, "ada", 50)[1]
        self.assertEqual(call("POST", "/payments/%s/corrections" % p2["payment_id"], body, self.bob, k)[0], 201)
        # a different payment id with the same key and body is a different request
        p3 = pay(self.ada, "bob", 20)[1]
        self.assertEqual(call("POST", "/payments/%s/corrections" % p3["payment_id"], {**body, "amount": 10}, self.ada, k)[0], 201)
        # percent-encoded spellings of the path are the same request
        enc = pid.replace("_", "%5F")
        self.assertEqual(call("POST", "/payments/%s/corrections" % enc, body, self.ada, k)[:2], (200, r1[1]))
        # burst of identical requests
        k2 = nk()
        b2 = {"expected_revision": 2, "amount": 150, "effective_at": p["created_at"], "reason": "burst"}
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: call("POST", path, b2, self.ada, k2), range(50)))
        self.assertEqual(sorted(r[0] for r in rs), [200] * 49 + [201])
        # missing key / long key
        err(call("POST", path, b2, self.ada), 400, "missing_idempotency_key")
        err(call("POST", path, b2, self.ada, "k" * 256), 422, "validation_failed")
        self.assertEqual(call("POST", path, {**b2, "expected_revision": 3, "amount": 100}, self.ada, "k" * 255)[0], 201)


class TestStage1ListUnderStage3(Base):
    def test_unchanged_without_temporal_parameters(self):
        p = pay(self.ada, "bob", 10)[1]
        j = call("GET", "/activity", token=self.ada)[1]
        self.assertEqual(j["payments"][0], p)
        self.assertEqual(set(p), {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "currency", "note", "visibility",
                                  "request_id", "settlement_id", "authorization_id", "created_at"})


if __name__ == "__main__":
    unittest.main(verbosity=1)
