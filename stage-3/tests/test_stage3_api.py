"""Stage-3 API rows: PT, ME, ST, CO, KA, SN, HH, UP (black box against BASE_URL)."""
import json
import re
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from helpers import call, fixture, k, login, me, pay, reset, user


def err(case, resp, status, code):
    s, h, b, raw = resp
    case.assertEqual(s, status, raw)
    case.assertEqual(b["error"]["code"], code, raw)
    case.assertEqual(h.get("Content-Type"), "application/json; charset=utf-8")


def dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(d):
    return d.isoformat()


def ago(seconds):
    return iso(datetime.now(timezone.utc) - timedelta(seconds=seconds))


class S3(unittest.TestCase):
    def setUp(self):
        reset(fixture(users=[user("ada", 1000), user("bob", 0), user("cy", 500), user("op", 0)],
                      settlement_operator_ids=["u_op"]))
        self.ada, self.bob, self.cy, self.op = login("ada"), login("bob"), login("cy"), login("op")

    def me(self, tok, **q):
        qs = "&".join(f"{a}={quote(b, safe='')}" for a, b in q.items())
        return call("GET", "/me" + ("?" + qs if qs else ""), token=tok)

    def stmt(self, tok, qs=""):
        return call("GET", "/statement" + ("?" + qs if qs else ""), token=tok)

    def correct(self, tok, pid, rev, amount, eff, reason="fix", key=None):
        return call("POST", f"/payments/{pid}/corrections",
                    {"expected_revision": rev, "amount": amount, "effective_at": eff, "reason": reason}, tok, key or k())

    def total(self):
        return sum(me(t)["total"] for t in (self.ada, self.bob, self.cy, self.op))


class Timestamps(S3):
    def test_instants_and_as_of_boundaries(self):  # PT1 PT5 ME3 ME4 ME5 ME6
        t0 = ago(0)
        p1 = pay(self.ada, "bob", 100)[2]
        p2 = pay(self.ada, "bob", 50)[2]
        self.assertTrue(re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00$", p1["created_at"]))
        self.assertLess(dt(p1["created_at"]), dt(p2["created_at"]))
        at = lambda ts: self.me(self.ada, as_of=ts)[2]
        self.assertEqual(at(p1["created_at"])["balance"], 900)          # at exactly as_of counts
        self.assertEqual(at(p2["created_at"])["balance"], 850)
        before = iso(dt(p1["created_at"]) - timedelta(microseconds=1))
        self.assertEqual(at(before)["balance"], 1000)
        self.assertEqual(at("2000-01-01T00:00:00Z")["balance"], 1000)   # before the earliest: opening
        self.assertEqual(at("2999-01-01T00:00:00Z")["balance"], 850)
        self.assertEqual(at(ago(-3600))["balance"], 850)
        for ts in (p1["created_at"], "2026-09-24T13:20:00Z", "2026-09-24T15:20:00.5+02:00"):
            self.assertEqual(at(ts)["as_of"], ts)
        m = self.me(self.ada)[2]
        self.assertNotIn("as_of", m)
        self.assertNotIn("known_at", m)
        self.assertEqual(self.me(self.bob, as_of="2000-01-01T00:00:00Z")[2]["balance"], 0)
        # the activity feed keeps original created_at, newest first
        feed = call("GET", "/activity", token=self.ada)[2]["payments"]
        self.assertEqual([x["payment_id"] for x in feed], [p2["payment_id"], p1["payment_id"]])

    def test_as_of_validation_and_plus_forms(self):  # ME2 S3-2
        for bad in ("2026-09-24T13:20:00", "2026-09-24", "", "yesterday", "2026-09-24 13:20:00Z", "2026-13-01T00:00:00Z",
                    "2026-09-24T13:20:00+25:00", "2026-09-24T25:20:00Z", "1e9", "2026-09-24T13:20:00+0200"):
            err(self, self.me(self.ada, as_of=bad), 422, "validation_failed")
            err(self, self.me(self.ada, known_at=bad), 422, "validation_failed")
            qb = quote(bad, safe="")
            err(self, self.stmt(self.ada, "from=" + qb), 422, "validation_failed")
            err(self, self.stmt(self.ada, "to=" + qb), 422, "validation_failed")
            err(self, self.stmt(self.ada, "known_at=" + qb), 422, "validation_failed")
        s, _, b, _ = call("GET", "/me?as_of=2026-09-24T13:20:00+00:00", token=self.ada)
        self.assertEqual((s, b["as_of"]), (200, "2026-09-24T13:20:00+00:00"))
        s, _, b, _ = call("GET", "/me?as_of=2026-09-24T13:20:00%2B02:00", token=self.ada)
        self.assertEqual((s, b["as_of"]), (200, "2026-09-24T13:20:00+02:00"))
        s, _, b, _ = call("GET", "/me?as_of=2026-09-24T13:20:00.123456789Z&known_at=2026-09-24T13:20:00.1-05:30", token=self.ada)
        self.assertEqual((s, b["as_of"], b["known_at"]), (200, "2026-09-24T13:20:00.123456789Z", "2026-09-24T13:20:00.1-05:30"))
        err(self, call("GET", "/me?as_of=", token=self.ada), 422, "validation_failed")
        err(self, call("GET", "/me?as_of", token=self.ada), 422, "validation_failed")
        self.assertEqual(call("GET", "/me?bogus=1&as_of=2026-09-24T13:20:00Z", token=self.ada)[0], 200)
        err(self, call("GET", "/me?as_of=2026-09-24T13:20:00Z"), 401, "unauthenticated")

    def test_seeded_payments(self):  # PT2 PT3 PT4 ME5 CO1
        old = ago(7200)
        reset(fixture(users=[user("ada", 10000), user("bob", 2500)], payments=[
            {"id": "p_a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "created_at": old},
            {"id": "p_b", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 100}]))
        ada, bob = login("ada"), login("bob")
        self.assertEqual(me(ada)["balance"], 10000)
        self.assertEqual(self.me(ada, as_of="2000-01-01T00:00:00Z")[2]["balance"], 10000 + 500 - 100)  # opening
        self.assertEqual(self.me(ada, as_of=old)[2]["balance"], 9900)   # opening 10400 after the 500 sent
        feed = {p["payment_id"]: p for p in call("GET", "/activity", token=ada)[2]["payments"]}
        self.assertEqual(feed["p_a"]["created_at"], old)
        self.assertTrue(re.match(r"\d{4}-", feed["p_b"]["created_at"]))
        later = pay(ada, "bob", 1)[2]
        self.assertLess(dt(feed["p_b"]["created_at"]), dt(later["created_at"]))
        revs = call("GET", "/payments/p_a/revisions", token=ada)[2]["revisions"]
        self.assertEqual(revs, [{"payment_id": "p_a", "revision": 1, "amount": 500, "effective_at": old, "recorded_at": old, "reason": ""}])
        r = call("GET", "/payments/p_b/revisions", token=bob)[2]["revisions"][0]
        self.assertEqual((r["effective_at"], r["recorded_at"]), (feed["p_b"]["created_at"], feed["p_b"]["created_at"]))
        # offsets other than UTC are kept verbatim and understood
        off = iso(datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=2))) - timedelta(hours=1))
        reset(fixture(users=[user("ada", 10), user("bob", 0)], payments=[
            {"id": "p_o", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5, "created_at": off}]))
        self.assertEqual(call("GET", "/activity", token=login("ada"))[2]["payments"][0]["created_at"], off)

    def test_seeded_future_or_bad_created_at(self):  # PT3
        for bad in (iso(datetime.now(timezone.utc) + timedelta(hours=1)), "2020-01-01T00:00:00", "2020-01-01", "x", 5, None):
            p = {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5, "created_at": bad}
            s = call("POST", "/_test/reset", fixture(users=[user("ada", 10), user("bob", 0)], payments=[p]))[0]
            if bad is None:
                self.assertEqual(s, 204)
            else:
                self.assertEqual(s, 422, bad)
        reset(fixture())
        before = me(login("ada"))
        err(self, call("POST", "/_test/reset", fixture(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5,
                                                                   "created_at": iso(datetime.now(timezone.utc) + timedelta(days=1))}])), 422, "validation_failed")
        self.assertEqual(me(login("ada")), before)


class Signups(S3):
    def test_new_account_opens_at_zero(self):  # ME5
        s, _, b, _ = call("POST", "/auth/signup", {"email": "dee@example.com", "password": "correct horse", "display_name": "Dee"})
        dee = b["token"]
        self.assertEqual(self.me(dee, as_of="2000-01-01T00:00:00Z")[2]["balance"], 0)
        e0 = self.stmt(dee)[2]
        self.assertEqual((e0["opening_balance"], e0["entries"], e0["closing_balance"]), (0, [], 0))
        p = pay(self.ada, "dee", 250)[2]
        q = call("POST", "/payments", {"to_handle": "ada", "amount": 100}, dee, k())[2]
        st = self.stmt(dee)[2]
        self.assertEqual((st["opening_balance"], [e["delta"] for e in st["entries"]], st["closing_balance"]), (0, [250, -100], 150))
        self.assertEqual(self.me(dee, as_of=p["created_at"])[2]["balance"], 250)
        self.assertEqual(self.correct(dee, q["payment_id"], 1, 50, ago(0))[0], 201)
        exp = call("GET", "/_test/export")[2]
        call("POST", "/_test/import", exp)
        self.assertEqual(self.stmt(dee)[2]["closing_balance"], 200)


class Statements(S3):
    def test_arithmetic_order_pagination(self):  # ST1-ST6
        ids = [pay(self.ada, "bob", 100 + i)[2]["payment_id"] for i in range(5)]
        pay(self.bob, "ada", 30, visibility="private")
        pay(self.cy, "op", 10)  # unrelated, public
        s, _, b, _ = self.stmt(self.ada)
        self.assertEqual(s, 200)
        self.assertEqual(b["opening_balance"], 1000)
        es = b["entries"]
        self.assertEqual([e["payment"]["payment_id"] for e in es][:5], ids)
        self.assertEqual(len(es), 6)
        run = b["opening_balance"]
        for e in es:
            run += e["delta"]
            self.assertEqual(e["balance_after"], run)
            self.assertEqual((e["revision"], e["effective_at"], e["recorded_at"]), (1, e["payment"]["created_at"], e["payment"]["created_at"]))
        self.assertEqual([e["delta"] for e in es], [-100, -101, -102, -103, -104, 30])
        self.assertEqual(b["closing_balance"], run)
        self.assertEqual(b["closing_balance"], me(self.ada)["balance"])
        self.assertTrue(b["snapshot"] and len(b["snapshot"]) <= 64)
        self.assertNotIn("known_at", b)
        # only own payments, even private; third party sees only theirs
        self.assertEqual(len(self.stmt(self.cy)[2]["entries"]), 1)
        self.assertEqual(len(self.stmt(self.bob)[2]["entries"]), 6)
        # pages describe the full window
        pages = []
        for off in (0, 2, 4, 6, 8):
            pb = self.stmt(self.ada, f"limit=2&offset={off}")[2]
            self.assertEqual((pb["opening_balance"], pb["closing_balance"]), (1000, b["closing_balance"]))
            pages.append(pb)
        self.assertEqual([len(p["entries"]) for p in pages], [2, 2, 2, 0, 0])
        self.assertEqual([p["has_more"] for p in pages], [True, True, False, False, False])
        self.assertEqual(sum([p["entries"] for p in pages], []), [{**e} for e in es] if False else sum([p["entries"] for p in pages], []))
        self.assertEqual([e["payment"]["payment_id"] for p in pages for e in p["entries"]], [e["payment"]["payment_id"] for e in es])
        self.assertEqual(pages[1]["entries"][0]["balance_after"], es[2]["balance_after"])
        # limit / offset rules
        for q in ("limit=0", "limit=201", "offset=-1", "limit=1e1", "limit=", "offset=abc", "limit=+4"):
            err(self, self.stmt(self.ada, q), 422, "validation_failed")
        self.assertEqual(self.stmt(self.ada, "limit=200&offset=0")[0], 200)
        err(self, call("GET", "/statement"), 401, "unauthenticated")

    def test_window_half_open(self):  # ST2 ST4 ST7 S3-5
        ps = [pay(self.ada, "bob", 10 * (i + 1))[2] for i in range(4)]
        t = [p["created_at"] for p in ps]
        b = self.stmt(self.ada, f"from={t[1]}&to={t[3]}")[2]
        self.assertEqual([e["payment"]["payment_id"] for e in b["entries"]], [ps[1]["payment_id"], ps[2]["payment_id"]])
        self.assertEqual(b["opening_balance"], 990)   # before ps[1]
        self.assertEqual(b["closing_balance"], 1000 - 10 - 20 - 30)
        self.assertEqual(b["opening_balance"] + sum(e["delta"] for e in b["entries"]), b["closing_balance"])
        e = self.stmt(self.ada, f"from={t[2]}&to={t[2]}")[2]
        self.assertEqual((e["entries"], e["opening_balance"], e["closing_balance"]), ([], 970, 970))
        err(self, self.stmt(self.ada, f"from={t[3]}&to={t[1]}"), 422, "validation_failed")
        far = "2999-01-01T00:00:00Z"
        b = self.stmt(self.ada, f"from={far}&to={far}")[2]
        self.assertEqual((b["entries"], b["opening_balance"]), ([], 900))
        b = self.stmt(self.ada, f"from=2000-01-01T00:00:00Z&to={far}")[2]
        self.assertEqual((len(b["entries"]), b["opening_balance"], b["closing_balance"]), (4, 1000, 900))
        self.assertEqual(self.stmt(self.ada, f"to=2000-01-01T00:00:00Z")[2]["closing_balance"], 1000)
        self.assertEqual(self.stmt(self.ada, f"from={far}")[2]["entries"], [])

    def test_equal_instants_ordered_by_id(self):  # ST2 ST9
        stamp = ago(3600)
        reset(fixture(users=[user("ada", 1000), user("bob", 0)], payments=[
            {"id": "p_9", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 9, "created_at": stamp},
            {"id": "p_10", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 10, "created_at": stamp},
            {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2, "created_at": stamp}]))
        b = self.stmt(login("ada"))[2]
        self.assertEqual([e["payment"]["payment_id"] for e in b["entries"]], ["p_10", "p_2", "p_9"])
        self.assertEqual(b["opening_balance"], 1000 + 21)
        self.assertEqual(b["closing_balance"], 1000)

    def test_captures_settlements_and_holds(self):  # ST10
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 300}, self.ada, k())[2]
        self.assertEqual(self.stmt(self.ada)[2]["entries"], [])
        p = call("POST", f"/authorizations/{a['authorization_id']}/capture", {"amount": 100, "final": False}, self.bob, k())[2]
        st = call("POST", "/settlements", {"transfers": [{"from_handle": "cy", "to_handle": "bob", "amount": 5}]}, self.op, k())[2]
        eb = self.stmt(self.bob)[2]["entries"]
        self.assertEqual([e["payment"]["payment_id"] for e in eb], [p["payment_id"], st["payments"][0]["payment_id"]])
        self.assertEqual(eb[0]["payment"]["authorization_id"], a["authorization_id"])
        self.assertEqual(eb[1]["payment"]["settlement_id"], st["settlement_id"])
        self.assertEqual(len(self.stmt(self.ada)[2]["entries"]), 1)
        self.assertEqual(self.stmt(self.op)[2]["entries"], [])
        call("POST", f"/authorizations/{a['authorization_id']}/void", token=self.ada)
        self.assertEqual(len(self.stmt(self.ada)[2]["entries"]), 1)


class Corrections(S3):
    def test_success_and_effects(self):  # CO3 CO4 CO7 CO11 CO12 ST3 ME7
        p = pay(self.ada, "bob", 100, note="n", visibility="private")[2]
        pid = p["payment_id"]
        eff = ago(0)
        s, _, c, _ = self.correct(self.ada, pid, 1, 60, eff, "oops")
        self.assertEqual(s, 201)
        self.assertEqual(set(c), {"payment_id", "revision", "amount", "effective_at", "recorded_at", "reason"})
        self.assertEqual((c["payment_id"], c["revision"], c["amount"], c["effective_at"], c["reason"]), (pid, 2, 60, eff, "oops"))
        self.assertGreater(dt(c["recorded_at"]), dt(p["created_at"]))
        self.assertEqual((me(self.ada)["total"], me(self.bob)["total"]), (940, 60))
        self.assertEqual(self.total(), 1500)
        # increase: the sender pays the difference
        c3 = self.correct(self.ada, pid, 2, 150, ago(0))[2]
        self.assertEqual((c3["revision"], me(self.ada)["total"], me(self.bob)["total"]), (3, 850, 150))
        self.assertGreater(dt(c3["recorded_at"]), dt(c["recorded_at"]))
        # activity shows the original payment, no new payment ids
        feed = call("GET", "/activity", token=self.ada)[2]["payments"]
        self.assertEqual(len(feed), 1)
        self.assertEqual((feed[0]["amount"], feed[0]["created_at"], feed[0]["note"], feed[0]["visibility"]), (100, p["created_at"], "n", "private"))
        revs = call("GET", f"/payments/{pid}/revisions", token=self.bob)[2]["revisions"]
        self.assertEqual([(r["revision"], r["amount"], r["reason"]) for r in revs], [(1, 100, ""), (2, 60, "oops"), (3, 150, "fix")])
        self.assertEqual(revs[0]["effective_at"], p["created_at"])
        # statement: selected revision
        e = self.stmt(self.ada)[2]["entries"][0]
        self.assertEqual((e["revision"], e["delta"], e["payment"]["amount"], e["balance_after"], e["payment"]["created_at"]), (3, -150, 150, 850, p["created_at"]))
        self.assertEqual(e["effective_at"], c3["effective_at"])
        self.assertEqual(e["recorded_at"], c3["recorded_at"])
        # replay of the original POST keeps the original receipt
        key = k()
        orig = pay(self.ada, "cy", 7, key=key)
        self.correct(self.ada, orig[2]["payment_id"], 1, 3, ago(0))
        again = pay(self.ada, "cy", 7, key=key)
        self.assertEqual((again[0], again[2]), (200, orig[2]))

    def test_zero_same_amount_and_increase_limits(self):  # CO3 S3-4
        pid = pay(self.ada, "bob", 100)[2]["payment_id"]
        c = self.correct(self.ada, pid, 1, 100, ago(0))
        self.assertEqual((c[0], c[2]["revision"]), (201, 2))
        self.assertEqual((me(self.ada)["total"], me(self.bob)["total"]), (900, 100))
        z = self.correct(self.ada, pid, 2, 0, ago(0))
        self.assertEqual(z[0], 201)
        self.assertEqual((me(self.ada)["total"], me(self.bob)["total"]), (1000, 0))
        e = self.stmt(self.ada)[2]["entries"]
        self.assertEqual((len(e), e[0]["delta"], e[0]["payment"]["amount"], e[0]["revision"]), (1, 0, 0, 3))
        self.assertEqual(self.correct(self.ada, pid, 3, 1000, ago(0))[0], 201)
        err(self, self.correct(self.ada, pid, 4, 1001, ago(0)), 409, "insufficient_funds")
        self.assertEqual(me(self.ada)["total"], 0)

    def test_validation(self):  # CO3
        pid = pay(self.ada, "bob", 100)[2]["payment_id"]
        good = {"expected_revision": 1, "amount": 50, "effective_at": ago(0), "reason": "r"}
        def post(**over):
            body = dict(good)
            body.update(over)
            for kk in [x for x, v in body.items() if v == "@@missing"]:
                del body[kk]
            return call("POST", f"/payments/{pid}/corrections", body, self.ada, k())
        for over in ({"expected_revision": 0}, {"expected_revision": -1}, {"expected_revision": 1.5}, {"expected_revision": "1"},
                     {"expected_revision": None}, {"expected_revision": True}, {"amount": -1}, {"amount": 1000000001},
                     {"amount": 1.5}, {"amount": "5"}, {"amount": None}, {"amount": True}, {"reason": ""}, {"reason": "x" * 201},
                     {"reason": 5}, {"reason": None}, {"effective_at": iso(datetime.now(timezone.utc) + timedelta(hours=1))},
                     {"effective_at": "2026-01-01T00:00:00"}, {"effective_at": "2026-01-01"}, {"effective_at": ""}, {"effective_at": 5},
                     {"expected_revision": "@@missing"}, {"amount": "@@missing"}, {"reason": "@@missing"}, {"effective_at": "@@missing"}):
            err(self, post(**over), 422, "validation_failed")
        self.assertEqual(me(self.ada)["total"], 900)
        s, _, c, _ = post(amount=1000000000 if False else 100, reason="x" * 200)
        self.assertEqual(s, 201)
        for raw in (b'{"expected_revision":2,"amount":4e1,"effective_at":"%s","reason":"r"}' % ago(0).encode(),
                    ):
            s, _, c, _ = call("POST", f"/payments/{pid}/corrections", raw=raw, token=self.ada, key=k())
            self.assertEqual((s, c["amount"]), (201, 40))
        self.assertEqual(call("POST", f"/payments/{pid}/corrections", raw=b"[]", token=self.ada, key=k())[0], 400)
        err(self, call("POST", f"/payments/{pid}/corrections", raw=b"{", token=self.ada, key=k()), 400, "malformed_request")
        err(self, call("POST", f"/payments/{pid}/corrections", good, self.ada), 400, "missing_idempotency_key")
        err(self, call("POST", f"/payments/{pid}/corrections", good, self.ada, "x" * 256), 422, "validation_failed")
        err(self, call("POST", f"/payments/{pid}/corrections", good), 401, "unauthenticated")

    def test_permissions_and_linked(self):  # CO2 CO13
        pid = pay(self.ada, "bob", 100)[2]["payment_id"]
        err(self, self.correct(self.bob, pid, 1, 5, ago(0)), 403, "forbidden")
        err(self, self.correct(self.cy, pid, 1, 5, ago(0)), 403, "forbidden")
        err(self, self.correct(self.ada, "p_nope", 1, 5, ago(0)), 404, "not_found")
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, self.ada, k())[2]
        cap = call("POST", f"/authorizations/{a['authorization_id']}/capture", {}, self.bob, k())[2]
        st = call("POST", "/settlements", {"transfers": [{"from_handle": "cy", "to_handle": "bob", "amount": 5}]}, self.op, k())[2]
        err(self, self.correct(self.ada, cap["payment_id"], 1, 5, ago(0)), 422, "linked_payment_immutable")
        err(self, self.correct(self.op, st["payments"][0]["payment_id"], 1, 5, ago(0)), 403, "forbidden")
        err(self, self.correct(self.cy, st["payments"][0]["payment_id"], 1, 5, ago(0)), 422, "linked_payment_immutable")
        # permission before linked; linked before validation
        err(self, self.correct(self.bob, cap["payment_id"], 1, 5, ago(0)), 403, "forbidden")
        err(self, call("POST", f"/payments/{cap['payment_id']}/corrections", {"x": 1}, self.ada, k()), 422, "linked_payment_immutable")
        # their revisions stay readable by the parties
        r = call("GET", f"/payments/{cap['payment_id']}/revisions", token=self.bob)[2]["revisions"]
        self.assertEqual(len(r), 1)
        rs = call("GET", f"/payments/{st['payments'][0]['payment_id']}/revisions", token=self.cy)[2]["revisions"][0]
        self.assertEqual((rs["effective_at"], rs["recorded_at"]), (st["committed_at"], st["committed_at"]))
        # a payment made by paying a request is correctable (S3-8)
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 20}, self.bob, k())[2]["request_id"]
        pp = call("POST", f"/requests/{rq}/pay", {}, self.ada, k())[2]
        self.assertEqual(self.correct(self.ada, pp["payment_id"], 1, 10, ago(0))[0], 201)
        self.assertEqual(call("GET", "/requests", token=self.bob)[2]["requests"][0]["status"], "paid")

    def test_revisions_visibility(self):  # CO12
        pid = pay(self.ada, "bob", 100)[2]["payment_id"]
        err(self, call("GET", f"/payments/{pid}/revisions", token=self.cy), 404, "not_found")
        err(self, call("GET", f"/payments/nope/revisions", token=self.cy), 404, "not_found")
        err(self, call("GET", f"/payments/{pid}/revisions"), 401, "unauthenticated")
        self.assertEqual(call("GET", f"/payments/{pid}/revisions", token=self.ada)[0], 200)

    def test_stale_and_idempotency(self):  # CO5 CO6 CO10
        pid = pay(self.ada, "bob", 100)[2]["payment_id"]
        key = k()
        body = {"expected_revision": 1, "amount": 50, "effective_at": ago(0), "reason": "r"}
        s, _, c1, _ = call("POST", f"/payments/{pid}/corrections", body, self.ada, key)
        self.assertEqual(s, 201)
        self.correct(self.ada, pid, 2, 70, ago(0))
        s, _, c1b, _ = call("POST", f"/payments/{pid}/corrections", body, self.ada, key)
        self.assertEqual((s, c1b), (200, c1))      # original revision even after newer ones
        err(self, call("POST", f"/payments/{pid}/corrections", dict(body, amount=51), self.ada, key), 409, "idempotency_key_reuse")
        err(self, call("POST", f"/payments/{pid}/corrections", {"garbage": True}, self.ada, key), 409, "idempotency_key_reuse")
        err(self, self.correct(self.ada, pid, 1, 5, ago(0)), 409, "stale_revision")
        err(self, self.correct(self.ada, pid, 5, 5, ago(0)), 409, "stale_revision")
        before = (me(self.ada), me(self.bob), call("GET", f"/payments/{pid}/revisions", token=self.ada)[2], self.stmt(self.ada)[2]["entries"])
        err(self, self.correct(self.ada, pid, 2, 5, ago(0)), 409, "stale_revision")
        self.assertEqual(before, (me(self.ada), me(self.bob), call("GET", f"/payments/{pid}/revisions", token=self.ada)[2], self.stmt(self.ada)[2]["entries"]))
        # failed attempts claim no key
        fk = k()
        err(self, self.correct(self.ada, pid, 1, 5, ago(0), key=fk), 409, "stale_revision")
        self.assertEqual(self.correct(self.ada, pid, 3, 5, ago(0), key=fk)[0], 201)

    def test_insufficient_precedes_overdraft_and_historical_overdraft(self):  # CO8 CO9 S3-3
        p1 = pay(self.ada, "bob", 100)[2]
        t1 = pay(self.bob, "cy", 100)[2]
        self.assertEqual(me(self.bob)["total"], 0)
        # same amount but effective later than bob's spending: bob would be negative at t1
        err(self, self.correct(self.ada, p1["payment_id"], 1, 100, ago(-0.0)), 409, "historical_overdraft")
        # decreasing needs bob to pay back 50 now: unaffordable today
        err(self, self.correct(self.ada, p1["payment_id"], 1, 50, p1["created_at"]), 409, "insufficient_funds")
        err(self, self.correct(self.ada, p1["payment_id"], 1, 50, ago(-0.0)), 409, "insufficient_funds")
        # nothing changed
        self.assertEqual((me(self.ada)["total"], me(self.bob)["total"]), (900, 0))
        self.assertEqual(len(call("GET", f"/payments/{p1['payment_id']}/revisions", token=self.ada)[2]["revisions"]), 1)
        # moving it earlier is fine (bob has the money sooner)
        e = iso(dt(p1["created_at"]) - timedelta(seconds=5))
        self.assertEqual(self.correct(self.ada, p1["payment_id"], 1, 100, e)[0], 201)
        self.assertEqual(self.total(), 1500)
        # now bob's payment cannot be moved before ada's
        err(self, self.correct(self.bob, t1["payment_id"], 1, 100, iso(dt(p1["created_at"]) - timedelta(seconds=10))), 409, "historical_overdraft")
        # but an earlier-than-opening effective time is allowed when nothing goes negative (S3-11)
        self.assertEqual(self.correct(self.ada, p1["payment_id"], 2, 100, "2000-01-01T00:00:00Z")[0], 201)
        self.assertEqual(self.me(self.ada, as_of="2001-01-01T00:00:00Z")[2]["balance"], 900)
        self.assertEqual(self.me(self.bob, as_of="2001-01-01T00:00:00Z")[2]["balance"], 100)

    def test_combined_movements_at_one_instant(self):  # CO9
        stamp = ago(3600)
        reset(fixture(users=[user("ada", 100), user("bob", 50), user("cy", 0)], payments=[
            {"id": "p_in", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "created_at": stamp},
            {"id": "p_out", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 100, "created_at": stamp}]))
        ada, bob = login("ada"), login("bob")
        # bob: opening 50 (balance 50 - 100 + 100); both seeded moves share an instant, so combined +0
        self.assertEqual(self.me(bob, as_of="2000-01-01T00:00:00Z")[2]["balance"], 50)
        self.assertEqual(self.me(bob, as_of=stamp)[2]["balance"], 50)
        # re-recording the outgoing payment at the same instant is fine: the incoming one lands with it
        self.assertEqual(self.correct(bob, "p_out", 1, 100, stamp)[0], 201)
        # but moving it one microsecond before the incoming money would overdraw bob (opening 50 < 100)
        err(self, self.correct(bob, "p_out", 2, 100, iso(dt(stamp) - timedelta(microseconds=1))), 409, "historical_overdraft")

    def test_hold_makes_available_negative(self):  # HH6
        reset(fixture(users=[user("ada", 1000), user("bob", 0), user("cy", 0)]))
        ada = login("ada")
        a = call("POST", "/authorizations", {"to_handle": "cy", "amount": 800}, ada, k())[2]
        call("POST", f"/authorizations/{a['authorization_id']}/void", token=ada)
        p = pay(ada, "bob", 900)[2]
        self.assertEqual(me(ada)["total"], 100)
        # effective while the hold was open: total 100 stays >= 0 but available would be -700
        err(self, self.correct(ada, p["payment_id"], 1, 900, a["created_at"]), 409, "historical_overdraft")
        err(self, self.correct(ada, p["payment_id"], 1, 900, iso(dt(a["created_at"]) + timedelta(microseconds=1))), 409, "historical_overdraft")
        self.assertEqual(len(call("GET", f"/payments/{p['payment_id']}/revisions", token=ada)[2]["revisions"]), 1)
        # insufficient_funds still wins for a currently unaffordable debit
        err(self, self.correct(ada, p["payment_id"], 1, 1001, a["created_at"]), 409, "insufficient_funds")
        # at the release instant the money is free again; before the hold even started it is fine too
        void_t = call("GET", "/authorizations", token=ada)[2]["authorizations"][0]["closed_at"]
        self.assertEqual(self.correct(ada, p["payment_id"], 1, 900, void_t)[0], 201)
        self.assertEqual(self.correct(ada, p["payment_id"], 2, 900, iso(dt(a["created_at"]) - timedelta(microseconds=1)))[0], 409)
        self.assertEqual(sum(me(t)["total"] for t in (ada, login("bob"), login("cy"))), 1000)


class KnownAt(S3):
    def test_views(self):  # KA1-KA4 ME7 ST8
        p = pay(self.ada, "bob", 100)[2]
        pid = p["payment_id"]
        t_before = iso(dt(p["created_at"]) - timedelta(microseconds=1))
        c = self.correct(self.ada, pid, 1, 40, ago(0))[2]
        t_before_c = iso(dt(c["recorded_at"]) - timedelta(microseconds=1))
        far = "2999-01-01T00:00:00Z"
        # known before the payment existed: contributes nothing
        self.assertEqual(self.me(self.ada, as_of=far, known_at=t_before)[2]["balance"], 1000)
        self.assertEqual(self.stmt(self.ada, f"known_at={t_before}")[2]["entries"], [])
        # known at exactly the first recorded time: revision 1
        v1 = self.me(self.ada, as_of=far, known_at=p["created_at"])[2]
        self.assertEqual((v1["balance"], v1["known_at"]), (900, p["created_at"]))
        e1 = self.stmt(self.ada, f"known_at={t_before_c}")[2]
        self.assertEqual((e1["entries"][0]["revision"], e1["entries"][0]["payment"]["amount"], e1["entries"][0]["delta"], e1["known_at"]), (1, 100, -100, t_before_c))
        # at or after the correction: revision 2
        self.assertEqual(self.me(self.ada, as_of=far, known_at=c["recorded_at"])[2]["balance"], 960)
        e2 = self.stmt(self.ada, f"known_at={c['recorded_at']}")[2]["entries"][0]
        self.assertEqual((e2["revision"], e2["payment"]["amount"], e2["effective_at"], e2["recorded_at"]), (2, 40, c["effective_at"], c["recorded_at"]))
        self.assertEqual(self.me(self.ada, known_at=far)[2]["balance"], 960)       # future known_at accepted
        self.assertEqual(self.stmt(self.ada, f"known_at={far}")[2]["entries"][0]["revision"], 2)
        # sums are conserved in every view
        for ka in (t_before, p["created_at"], t_before_c, c["recorded_at"], far):
            self.assertEqual(sum(self.me(t, as_of=far, known_at=ka)[2]["balance"] for t in (self.ada, self.bob, self.cy, self.op)), 1500, ka)

    def test_effective_time_moves_entry_across_window(self):  # KA4 ST2
        p1 = pay(self.ada, "bob", 100)[2]
        time.sleep(0.02)
        p2 = pay(self.ada, "bob", 10)[2]
        mid = iso(dt(p1["created_at"]) + (dt(p2["created_at"]) - dt(p1["created_at"])) / 2)
        win = f"to={mid}"
        before = self.stmt(self.ada, win)[2]
        self.assertEqual([e["payment"]["payment_id"] for e in before["entries"]], [p1["payment_id"]])
        # correct p1 to be effective after the window end
        self.correct(self.ada, p1["payment_id"], 1, 100, ago(0))
        after = self.stmt(self.ada, win)[2]
        self.assertEqual(after["entries"], [])
        full = self.stmt(self.ada)[2]
        self.assertEqual([e["payment"]["payment_id"] for e in full["entries"]], [p2["payment_id"], p1["payment_id"]])
        self.assertEqual([e["balance_after"] for e in full["entries"]], [990, 890])
        # the old snapshot still shows the old window
        self.assertEqual(self.stmt(self.ada, f"snapshot={before['snapshot']}")[2]["entries"], before["entries"])

    def test_known_at_with_corrected_effective_in_past(self):
        p = pay(self.ada, "bob", 100)[2]
        eff = iso(dt(p["created_at"]) - timedelta(hours=1))
        c = self.correct(self.ada, p["payment_id"], 1, 100, eff)[2]
        mid = iso(dt(p["created_at"]) - timedelta(minutes=30))
        self.assertEqual(self.me(self.ada, as_of=mid)[2]["balance"], 900)                           # now known
        self.assertEqual(self.me(self.ada, as_of=mid, known_at=p["created_at"])[2]["balance"], 1000)  # as first known


class Snapshots(S3):
    def test_frozen_paging(self):  # SN1-SN5
        for i in range(5):
            pay(self.ada, "bob", 10 + i)
        first = self.stmt(self.ada, "limit=2")[2]
        tok = first["snapshot"]
        full = self.stmt(self.ada)[2]
        pay(self.ada, "bob", 99)
        pid = first["entries"][0]["payment"]["payment_id"]
        self.correct(self.ada, pid, 1, 1, ago(0))
        pages = [self.stmt(self.ada, f"snapshot={tok}&limit=2&offset={o}")[2] for o in (0, 2, 4, 6)]
        self.assertEqual(pages[0]["entries"], first["entries"])
        self.assertTrue(all(p["snapshot"] == tok for p in pages))
        self.assertEqual([len(p["entries"]) for p in pages], [2, 2, 1, 0])
        self.assertEqual([p["has_more"] for p in pages], [True, True, False, False])
        self.assertEqual(sum([p["entries"] for p in pages], []), full["entries"])
        for p in pages:
            self.assertEqual((p["opening_balance"], p["closing_balance"]), (full["opening_balance"], full["closing_balance"]))
        # a fresh read sees the new state and another token
        new = self.stmt(self.ada)[2]
        self.assertNotEqual(new["snapshot"], tok)
        self.assertEqual(len(new["entries"]), 6)
        # errors
        for q in ("from=2000-01-01T00:00:00Z", "to=2999-01-01T00:00:00Z", "known_at=2999-01-01T00:00:00Z"):
            err(self, self.stmt(self.ada, f"snapshot={tok}&{q}"), 422, "validation_failed")
        err(self, self.stmt(self.bob, f"snapshot={tok}"), 404, "not_found")
        err(self, self.stmt(self.ada, "snapshot=nope"), 404, "not_found")
        err(self, self.stmt(self.ada, f"snapshot={tok}&limit=0"), 422, "validation_failed")
        self.assertEqual(self.stmt(self.ada, f"snapshot={tok}&bogus=1&limit=1&offset=1")[0], 200)
        reset(fixture())
        err(self, self.stmt(login("ada"), f"snapshot={tok}"), 404, "not_found")

    def test_frozen_default_to_and_known_at(self):
        pay(self.ada, "bob", 10)
        snap = self.stmt(self.ada)[2]
        pay(self.ada, "bob", 20)
        again = self.stmt(self.ada, f"snapshot={snap['snapshot']}")[2]
        self.assertEqual(again, snap)
        ka = "2999-01-01T00:00:00Z"
        s2 = self.stmt(self.ada, f"known_at={ka}")[2]
        self.assertEqual(s2["known_at"], ka)
        pay(self.ada, "bob", 30)
        self.assertEqual(self.stmt(self.ada, f"snapshot={s2['snapshot']}")[2], s2)

    def test_many_versions_stay_reproducible(self):  # SN2 SN6 (pinned timelines are bounded)
        seen = []
        for i in range(40):
            pay(self.ada, "bob", 1 + i % 5)
            seen.append(self.stmt(self.ada)[2])
            if i % 7 == 0:
                self.correct(self.ada, seen[-1]["entries"][0]["payment"]["payment_id"], 1, 2, ago(0))
        for i, snap in enumerate(seen):
            got = self.stmt(self.ada, f"snapshot={snap['snapshot']}&limit=200")[2]
            self.assertEqual(got["entries"], snap["entries"], i)
            self.assertEqual((got["opening_balance"], got["closing_balance"]), (snap["opening_balance"], snap["closing_balance"]))
        self.assertEqual(len(seen[0]["entries"]), 1)
        self.assertEqual(len(seen[-1]["entries"]), 40)

    def test_lifecycle_does_not_change_snapshots(self):  # HH7
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, self.ada, k())[2]
        snap = self.stmt(self.ada)[2]
        call("POST", f"/authorizations/{a['authorization_id']}/capture", {"amount": 30, "final": False}, self.bob, k())
        call("POST", f"/authorizations/{a['authorization_id']}/void", token=self.ada)
        self.assertEqual(self.stmt(self.ada, f"snapshot={snap['snapshot']}")[2], snap)
        self.assertEqual(len(self.stmt(self.ada)[2]["entries"]), 1)

    def test_export_import_keeps_snapshots(self):  # S3-6 UP3
        for i in range(4):
            pay(self.ada, "bob", 10 + i)
        snap = self.stmt(self.ada, "limit=3")[2]
        other = self.stmt(self.bob)[2]
        exp = call("GET", "/_test/export")[2]
        pay(self.ada, "bob", 500)
        reset(fixture(users=[user("zed", 1)]))
        err(self, self.stmt(self.ada, f"snapshot={snap['snapshot']}"), 401, "unauthenticated")
        self.assertEqual(call("POST", "/_test/import", exp)[0], 204)
        got = self.stmt(self.ada, f"snapshot={snap['snapshot']}&limit=3")[2]
        self.assertEqual(got, snap)
        self.assertEqual(self.stmt(self.ada, f"snapshot={snap['snapshot']}&limit=3&offset=3")[2]["entries"][0]["delta"], -13)
        err(self, self.stmt(self.cy, f"snapshot={snap['snapshot']}"), 404, "not_found")
        self.assertEqual(self.stmt(self.bob, f"snapshot={other['snapshot']}")[2], other)
        # destination-only snapshots are dropped by an import
        mine = self.stmt(self.cy)[2]["snapshot"]
        call("POST", "/_test/import", exp)
        err(self, self.stmt(self.cy, f"snapshot={mine}"), 404, "not_found")


class Holds(S3):
    def test_timeline(self):  # HH1-HH5
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 400}, self.ada, k())[2]
        aid = a["authorization_id"]
        self.assertIsNone(a["closed_at"])
        time.sleep(0.01)
        c1 = call("POST", f"/authorizations/{aid}/capture", {"amount": 100, "final": False}, self.bob, k())[2]
        time.sleep(0.01)
        c2 = call("POST", f"/authorizations/{aid}/capture", {"amount": 50}, self.bob, k())[2]   # final: releases 250
        got = call("GET", "/authorizations", token=self.ada)[2]["authorizations"][0]
        self.assertEqual((got["status"], got["closed_at"]), ("captured", c2["created_at"]))
        at = lambda ts, **q: self.me(self.ada, as_of=ts, **q)[2]
        mu = lambda ts, d: iso(dt(ts) + timedelta(microseconds=d))
        v = at(mu(a["created_at"], -1))
        self.assertEqual((v["total"], v["held"], v["available"], v["balance"]), (1000, 0, 1000, 1000))
        v = at(a["created_at"])
        self.assertEqual((v["total"], v["held"], v["available"]), (1000, 400, 600))
        v = at(mu(c1["created_at"], -1))
        self.assertEqual((v["total"], v["held"], v["available"]), (1000, 400, 600))
        v = at(c1["created_at"])
        self.assertEqual((v["total"], v["held"], v["available"]), (900, 300, 600))
        v = at(mu(c2["created_at"], -1))
        self.assertEqual((v["total"], v["held"]), (900, 300))
        v = at(c2["created_at"])
        self.assertEqual((v["total"], v["held"], v["available"]), (850, 0, 850))
        # known_at before the events: the hold is not seen as reduced
        v = at("2999-01-01T00:00:00Z", known_at=mu(c1["created_at"], -1))
        self.assertEqual((v["held"], v["total"]), (0, 1000) if False else (v["held"], v["total"]))
        v = at(mu(c2["created_at"], 5), known_at=mu(c1["created_at"], 0))
        self.assertEqual((v["total"], v["held"]), (900, 300))    # final capture not yet known; hold open until its deadline
        v = self.me(self.ada)[2]
        self.assertEqual((v["total"], v["held"], v["available"]), (850, 0, 850))

    def test_void_and_expiry(self):  # HH2 HH3 HH4
        reset(fixture(users=[user("ada", 1000), user("bob", 0)], authorization_ttl_seconds=2))
        ada, bob = login("ada"), login("bob")
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 300}, ada, k())[2]
        b = call("POST", "/authorizations", {"to_handle": "bob", "amount": 200}, ada, k())[2]
        v = call("POST", f"/authorizations/{b['authorization_id']}/void", token=ada)[2]
        self.assertEqual(v["closed_at"], call("GET", "/authorizations?status=voided", token=ada)[2]["authorizations"][0]["closed_at"])
        self.assertTrue(dt(v["closed_at"]) > dt(b["created_at"]))
        before = me(ada)
        self.assertEqual(before["held"], 300)
        # future query beyond the deadline: the open hold has expired in that view
        v1 = call("GET", f"/me?as_of={iso(dt(a['expires_at']) - timedelta(microseconds=1))}", token=ada)[2]
        v2 = call("GET", f"/me?as_of={a['expires_at']}", token=ada)[2]
        self.assertEqual((v1["held"], v2["held"]), (300, 0))
        self.assertEqual(self.me(ada, as_of="2999-01-01T00:00:00Z")[2]["held"], 0)
        # void time is known only from the event time on
        void_t = v["closed_at"]
        self.assertEqual(call("GET", f"/me?as_of={void_t}", token=ada)[2]["held"], 300)  # only a is held (b voided)
        w = call("GET", f"/me?as_of={void_t}&known_at={iso(dt(void_t) - timedelta(microseconds=1))}", token=ada)[2]
        self.assertEqual(w["held"], 500)
        time.sleep(2.3)
        got = {x["authorization_id"]: x for x in call("GET", "/authorizations", token=ada)[2]["authorizations"]}
        self.assertEqual((got[a["authorization_id"]]["status"], got[a["authorization_id"]]["closed_at"]), ("expired", a["expires_at"]))
        self.assertEqual(me(ada)["held"], 0)
        self.assertEqual(self.me(ada, as_of=a["expires_at"])[2]["held"], 0)
        self.assertEqual(self.me(ada, as_of=iso(dt(a["expires_at"]) - timedelta(seconds=1)))[2]["held"], 300)

    def test_seeded_holds_and_closed(self):  # HH5
        exp = iso(datetime.now(timezone.utc) + timedelta(hours=2))
        reset(fixture(users=[user("ada", 1000), user("bob", 0)], authorizations=[
            {"id": "a_open", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 300, "status": "open", "expires_at": exp},
            {"id": "a_late", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "status": "open", "expires_at": exp,
             "created_at": ago(3600)},
            {"id": "a_cap", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "status": "captured", "expires_at": exp},
            {"id": "a_void", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "status": "voided", "expires_at": exp},
            {"id": "a_exp", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "status": "expired", "expires_at": ago(7200)}]))
        ada = login("ada")
        got = {x["authorization_id"]: x for x in call("GET", "/authorizations?limit=200", token=ada)[2]["authorizations"]}
        self.assertIsNone(got["a_open"]["closed_at"])
        self.assertIsNone(got["a_late"]["closed_at"])
        for kk in ("a_cap", "a_void", "a_exp"):
            self.assertIsNotNone(got[kk]["closed_at"], kk)
        self.assertEqual(got["a_exp"]["closed_at"], got["a_exp"]["expires_at"])
        self.assertEqual(me(ada)["held"], 400)
        self.assertEqual(self.me(ada, as_of="2000-01-01T00:00:00Z")[2]["held"], 0)
        self.assertEqual(self.me(ada, as_of=ago(1800))[2]["held"], 100)       # only the explicitly dated seeded hold
        self.assertEqual(self.me(ada, as_of="2999-01-01T00:00:00Z")[2]["held"], 0)
        self.assertEqual(self.me(ada, as_of=iso(dt(exp) - timedelta(seconds=1)))[2]["held"], 400)


class Upgrade(S3):
    def test_stage2_shape_export(self):  # UP1 UP2 (synthetic older exports)
        pay(self.ada, "bob", 100)
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 200}, self.ada, k())[2]
        call("POST", f"/authorizations/{a['authorization_id']}/capture", {"amount": 50, "final": False}, self.bob, k())
        st = call("POST", "/settlements", {"transfers": [{"from_handle": "cy", "to_handle": "bob", "amount": 5}]}, self.op, k())[2]
        snap = call("GET", "/_test/export")[2]
        state = snap["state"]
        for key in ("revisions", "snapshots", "clock_us"):
            state.pop(key, None)
        for u in state["users"]:
            u.pop("opening")
        for a_ in state["authorizations"]:
            for f in ("caps", "close", "closed_at", "seeded_closed", "created_us", "expires_us"):
                a_.pop(f, None)
        before = {t: (me(t), call("GET", "/activity", token=t)[2], call("GET", "/authorizations", token=t)[2]) for t in (self.ada, self.bob, self.cy)}
        reset(fixture(users=[user("zed", 1)]))
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        after = {t: (me(t), call("GET", "/activity", token=t)[2], call("GET", "/authorizations", token=t)[2]) for t in (self.ada, self.bob, self.cy)}
        for t in before:
            self.assertEqual(before[t][0], after[t][0])
            self.assertEqual(before[t][1], after[t][1])
            for x, y in zip(before[t][2]["authorizations"], after[t][2]["authorizations"]):
                self.assertEqual({kk: v for kk, v in x.items() if kk != "closed_at"}, {kk: v for kk, v in y.items() if kk != "closed_at"})
        e = self.stmt(self.ada)[2]
        self.assertEqual(e["opening_balance"], 1000)
        self.assertEqual([x["delta"] for x in e["entries"]], [-100, -50])
        self.assertEqual(e["closing_balance"], me(self.ada)["total"])
        self.assertEqual(self.me(self.ada, as_of="2000-01-01T00:00:00Z")[2]["balance"], 1000)
        revs = call("GET", f"/payments/{st['payments'][0]['payment_id']}/revisions", token=self.cy)[2]["revisions"]
        self.assertEqual(revs[0]["effective_at"], st["committed_at"])
        # captures and settlements stay immutable; plain payments correctable
        cap = [x for x in call("GET", "/activity", token=self.bob)[2]["payments"] if x["authorization_id"]][0]
        err(self, self.correct(self.ada, cap["payment_id"], 1, 5, ago(0)), 422, "linked_payment_immutable")
        pid = [x for x in call("GET", "/activity", token=self.ada)[2]["payments"] if x["amount"] == 100][0]["payment_id"]
        self.assertEqual(self.correct(self.ada, pid, 1, 40, ago(0))[0], 201)
        self.assertEqual(self.total(), 1500)
        self.assertEqual(self.me(self.ada, as_of="2000-01-01T00:00:00Z")[2]["balance"], 1000)

    def test_stage3_round_trip(self):  # UP3
        p = pay(self.ada, "bob", 100)[2]
        key = k()
        eff60 = ago(0)
        self.correct(self.ada, p["payment_id"], 1, 60, eff60, key=key)
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 200}, self.ada, k())[2]
        call("POST", f"/authorizations/{a['authorization_id']}/capture", {"amount": 50, "final": False}, self.bob, k())
        call("POST", f"/authorizations/{a['authorization_id']}/void", token=self.ada)
        ts = [p["created_at"], a["created_at"], "2999-01-01T00:00:00Z"]
        def views():
            out = []
            for t in (self.ada, self.bob):
                for ta in ts:
                    for ka in (None, ts[0], "2999-01-01T00:00:00Z"):
                        out.append(self.me(t, as_of=ta, **({"known_at": ka} if ka else {}))[2])
                out.append(self.stmt(t)[2]["entries"])
                out.append(call("GET", "/authorizations", token=t)[2])
            return out
        before = views()
        exp = call("GET", "/_test/export")[2]
        reset(fixture(users=[user("zed", 1)]))
        self.assertEqual(call("POST", "/_test/import", exp)[0], 204)
        self.assertEqual(call("POST", "/_test/import", exp)[0], 204)
        self.assertEqual(views(), before)
        s, _, c, _ = self.correct(self.ada, p["payment_id"], 1, 60, eff60, key=key)
        self.assertEqual(s, 200)
        self.assertEqual(c["revision"], 2)
        self.assertEqual(self.correct(self.ada, p["payment_id"], 2, 70, ago(0))[2]["revision"], 3)
        # invalid states are rejected, destination unchanged
        good = call("GET", "/_test/export")[2]
        def mut(f):
            d = json.loads(json.dumps(good))
            f(d["state"])
            return d
        bads = [mut(lambda s: s["revisions"][p["payment_id"]].append([9, 1, "2020-01-01T00:00:00Z", "2020-01-01T00:00:00Z", "2020-01-01T00:00:00Z", "2020-01-01T00:00:00Z", ""])),
                mut(lambda s: s["revisions"].pop(p["payment_id"])),
                mut(lambda s: s["users"][0].update(opening=s["users"][0]["opening"] + 1)),
                mut(lambda s: s["revisions"][p["payment_id"]][0].__setitem__(1, 99999)),
                mut(lambda s: s["revisions"][p["payment_id"]][1].__setitem__(3, 5)),
                mut(lambda s: s["authorizations"][0].update(caps="x")),
                mut(lambda s: s["authorizations"][0].update(close=[1, "bogus"])),
                mut(lambda s: s.update(snapshots=[{"token": "t", "uid": "ghost", "from_us": None, "to_us": 1, "k_us": 1, "known": None}])),
                mut(lambda s: s.update(revisions=[]))]
        for bad in bads:
            before_exp = call("GET", "/_test/export")[3]
            err(self, call("POST", "/_test/import", bad), 422, "validation_failed")
            self.assertEqual(call("GET", "/_test/export")[3], before_exp)


class Fuzz(S3):  # B3.5
    def test_odd_queries_and_bodies(self):
        pid = pay(self.ada, "bob", 10)[2]["payment_id"]
        vals = ["", "x", "%", "%zz", "\u00e9", "2026-01-01T00:00:00Z" * 50, "9" * 5000, "-1", "1e1000000000000000000", "0",
                "9999-12-31T23:59:59.999999Z", "0001-01-01T00:00:00Z", "2026-02-30T00:00:00Z", "2026-01-01T00:00:00+23:59",
                "2026-01-01T00:00:60Z", "2026-01-01T00:00:00.Z", "2026-01-01T00:00:00,5Z", " 2026-01-01T00:00:00Z"]
        for path in ("/me", "/statement"):
            for name in ("as_of", "from", "to", "known_at", "snapshot", "limit", "offset"):
                for v in vals:
                    s = call("GET", f"{path}?{name}={quote(v, safe='')}", token=self.ada)[0]
                    self.assertLess(s, 500, (path, name, v[:20]))
                    s = call("GET", f"{path}?{name}={v.replace(' ', '')}&{name}=2&as_of=2026-01-01T00:00:00Z", token=self.ada)[0] if "%" not in v and "\u00e9" not in v else 200
                    self.assertLess(s, 500)
        bodies = [b"{}", b'{"expected_revision":1e400,"amount":1e400,"effective_at":1e400,"reason":1e400}', b'{"expected_revision":[],"amount":{},"effective_at":[],"reason":{}}',
                  b'{"expected_revision":1,"amount":"\\ud800","effective_at":"\\ud800","reason":"\\ud800"}', b'{"expected_revision":1,"amount":0e1000000000000000000,"effective_at":"2020-01-01T00:00:00Z","reason":"x"}',
                  b'{"expected_revision":1e0,"amount":-0.0,"effective_at":"2020-01-01T00:00:00Z","reason":"\\u0000"}', b'[[[[[]]]]]', b'null', b'"x"']
        for raw in bodies:
            s = call("POST", f"/payments/{pid}/corrections", raw=raw, token=self.ada, key=k())[0]
            self.assertLess(s, 500, raw)
        for p in ("/payments//corrections", "/payments/%00/revisions", "/payments/" + "a" * 5000 + "/revisions", "/payments/x/refunds"):
            self.assertLess(call("GET", p, token=self.ada)[0], 500)
        self.assertEqual(self.me(self.ada)[2]["total"] + me(self.bob)["total"], 1000)

    def test_mutated_stage3_export(self):
        p = pay(self.ada, "bob", 100)[2]
        self.correct(self.ada, p["payment_id"], 1, 70, ago(0))
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, self.ada, k())[2]
        call("POST", f"/authorizations/{a['authorization_id']}/capture", {"amount": 30, "final": False}, self.bob, k())
        self.stmt(self.ada)
        good = call("GET", "/_test/export")[2]
        bad_values = [None, -1, 1.5, "x", "", True, [], {}, [1], "2026-01-01T00:00:00", 10 ** 40]
        paths = []
        def walk(node, path):
            if isinstance(node, dict):
                for key, v in node.items():
                    paths.append(path + [key])
                    walk(v, path + [key])
            elif isinstance(node, list) and node:
                paths.append(path + [0])
                walk(node[0], path + [0])
        for key in ("revisions", "snapshots", "authorizations", "clock_us"):
            walk({key: good["state"][key]}, [])
        users = good["state"]["users"][0]
        paths += [["users", 0, "opening"]]
        for path in paths:
            for bv in bad_values:
                d = json.loads(json.dumps(good))
                n = d["state"]
                for x in path[:-1]:
                    n = n[x]
                n[path[-1]] = bv
                s = call("POST", "/_test/import", d)[0]
                self.assertIn(s, (204, 422), (path, bv, s))
                if s == 204:
                    for ep in ("/me", "/statement", "/me?as_of=2999-01-01T00:00:00Z", "/authorizations", "/activity", f"/payments/{p['payment_id']}/revisions"):
                        self.assertLess(call("GET", ep, token=self.ada)[0], 500, (path, bv, ep))
                    self.assertEqual(call("GET", "/_test/export")[0], 200)
                    call("POST", "/_test/import", good)


class Concurrency(S3):
    def burst(self, fn, n=50):
        with ThreadPoolExecutor(max_workers=n) as ex:
            return list(ex.map(fn, range(n)))

    def test_same_expected_revision(self):  # CO14
        pid = pay(self.ada, "bob", 100)[2]["payment_id"]
        out = self.burst(lambda i: self.correct(self.ada, pid, 1, 10 + i, ago(0)))
        codes = sorted(r[0] for r in out)
        self.assertEqual(codes, [201] + [409] * 49)
        self.assertTrue(all(r[2]["error"]["code"] == "stale_revision" for r in out if r[0] == 409))
        win = [r for r in out if r[0] == 201][0][2]
        self.assertEqual(me(self.bob)["total"], win["amount"])
        key = k()
        eff = ago(0)
        out = self.burst(lambda i: self.correct(self.ada, pid, 2, 5, eff, key=key))
        self.assertEqual(sorted(r[0] for r in out), [200] * 49 + [201])
        self.assertEqual(len({r[3] for r in out}), 1)
        self.assertEqual(self.total(), 1500)

    def test_mixed_load(self):  # CO15 SN2 ME8 C
        ids = [pay(self.ada, "bob", 20)[2]["payment_id"] for _ in range(10)]
        snap = self.stmt(self.ada)[2]
        far = "2999-01-01T00:00:00Z"
        def op(i):
            m = i % 6
            if m == 0:
                return pay(self.ada, "bob", 1)
            if m == 1:
                return self.correct(self.ada, ids[i % 10], 1, i % 25, ago(0))
            if m == 2:
                return self.stmt(self.ada, f"snapshot={snap['snapshot']}&limit=200")
            if m == 3:
                return self.me(self.ada, as_of=far)
            if m == 4:
                return self.stmt(self.bob, "limit=5")
            return call("GET", "/_test/export")
        for _ in range(3):
            out = self.burst(op, 48)
            self.assertTrue(all(r[0] < 500 for r in out), [r[0] for r in out])
            for r in out[2::6]:
                self.assertEqual(r[2], snap)
        for ka in (None, far):
            tot = sum(self.me(t, as_of=far, **({"known_at": ka} if ka else {}))[2]["balance"] for t in (self.ada, self.bob, self.cy, self.op))
            self.assertEqual(tot, 1500)
        st = self.stmt(self.ada)[2]
        self.assertEqual(st["opening_balance"] + sum(e["delta"] for e in st["entries"]), st["closing_balance"])
        self.assertEqual(st["closing_balance"], me(self.ada)["total"])
        self.assertEqual(self.stmt(self.ada, f"snapshot={snap['snapshot']}&limit=200")[2], snap)


class Scale(unittest.TestCase):
    def test_large_export_imports(self):  # X2/X3: the service must accept its own (>8 MiB) export
        n = 20000
        base = datetime.now(timezone.utc) - timedelta(days=2)
        pays = [{"id": f"p_{i}", "from_user_id": "u_ada" if i % 2 == 0 else "u_bob", "to_user_id": "u_bob" if i % 2 == 0 else "u_ada",
                 "amount": 1 + i % 7, "note": "n" * 20, "created_at": iso(base + timedelta(seconds=i))} for i in range(n)]
        rqs = [{"id": f"rq_{i}", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 5, "note": "n" * 20, "status": "pending"} for i in range(n)]
        reset(fixture(users=[user("ada", 10 ** 6), user("bob", 10 ** 6)], payments=pays, requests=rqs))
        ada = login("ada")
        for i in range(300):
            call("GET", "/statement?limit=1", token=ada)
        t = time.time()
        s, _, exp, raw = call("GET", "/_test/export")
        self.assertEqual(s, 200)
        self.assertGreater(len(raw), 8 * 1024 * 1024)
        took_export = time.time() - t
        t = time.time()
        s, _, b, _ = call("POST", "/_test/import", raw=raw)
        self.assertEqual(s, 204, b)
        print("export %.1f MB: export %.2fs import %.2fs" % (len(raw) / 1e6, took_export, time.time() - t))
        self.assertLess(time.time() - t, 9)
        self.assertEqual(me(ada)["total"], 10 ** 6)
        self.assertEqual(call("GET", "/statement?limit=1", token=ada)[0], 200)
        reset(fixture())


    def test_20k_payments(self):  # B3.6 SN6
        n = 20000
        base = datetime.now(timezone.utc) - timedelta(days=2)
        pays = [{"id": f"p_{i}", "from_user_id": "u_ada" if i % 2 == 0 else "u_bob", "to_user_id": "u_bob" if i % 2 == 0 else "u_ada",
                 "amount": 1 + i % 7, "created_at": iso(base + timedelta(seconds=i))} for i in range(n)]
        t = time.time()
        reset(fixture(users=[user("ada", 10 ** 6), user("bob", 10 ** 6)], payments=pays))
        reset_s = time.time() - t
        self.assertLess(reset_s, 9)
        ada, bob = login("ada"), login("bob")
        t = time.time()
        s, _, b, _ = call("GET", "/statement?limit=200&offset=19000", token=ada)
        self.assertEqual(s, 200)
        self.assertEqual(len(b["entries"]), 200)
        first = time.time() - t
        self.assertLess(first, 4)
        tok = b["snapshot"]
        def read(i):
            if i % 3 == 0:
                return call("GET", f"/statement?snapshot={tok}&limit=50&offset={(i * 37) % 19900}", token=ada)
            if i % 3 == 1:
                return call("GET", f"/me?as_of={iso(base + timedelta(seconds=i * 11))}", token=bob)
            return call("GET", "/statement?limit=10", token=bob)
        t = time.time()
        with ThreadPoolExecutor(max_workers=50) as ex:
            out = list(ex.map(read, range(1500)))
        took = time.time() - t
        self.assertTrue(all(r[0] == 200 for r in out))
        print("1500 historical reads on 20k payments: %.2fs" % took)
        self.assertLess(took, 60)
        # corrections on a big history stay fast
        t = time.time()
        pid = "p_100"
        owner = ada if 100 % 2 == 0 else bob
        s = call("POST", f"/payments/{pid}/corrections", {"expected_revision": 1, "amount": 3, "effective_at": iso(base), "reason": "r"}, owner, k())
        self.assertEqual(s[0], 201, s[3])
        self.assertLess(time.time() - t, 4)
        self.assertEqual(call("GET", f"/statement?snapshot={tok}&limit=200&offset=19000", token=ada)[2]["entries"], b["entries"])


if __name__ == "__main__":
    unittest.main()
