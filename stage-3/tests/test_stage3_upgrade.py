"""Stage-3 service as the destination of exports of the accepted stage-1 and stage-2 services, and of its own."""
import json
import os
import time
import unittest
from datetime import datetime, timedelta, timezone

import test_stage1 as t1
from test_stage1 import BASE, BASE2, call, err, fixture, login, nk, reset, user
from test_stage3_api import Q, correct, dtp, iso, me, now, pay, stmt, MICRO_RE

PREV1 = os.environ.get("BASE_URL_PREV1")
PREV2 = os.environ.get("BASE_URL_PREV2")


def views(base, toks, instants):
    """Everything a client can read about the history, as plain data (snapshot tokens excluded)."""
    out = {}
    for name, tok in toks.items():
        o = {"me": call("GET", "/me", token=tok, base=base)[1]}
        for i, t in enumerate(instants):
            o["asof%d" % i] = call("GET", Q("/me", as_of=t), token=tok, base=base)[1]
            o["known%d" % i] = call("GET", Q("/me", as_of=instants[-1], known_at=t), token=tok, base=base)[1]
        for i, (f, t) in enumerate([(None, None), (instants[1], None), (None, instants[2]), (instants[1], instants[3])]):
            j = call("GET", Q("/statement", **{"from": f, "to": t, "limit": 200}), token=tok, base=base)[1]
            j.pop("snapshot", None)
            o["stmt%d" % i] = j
        o["activity"] = call("GET", "/activity?limit=200", token=tok, base=base)[1]
        o["requests"] = call("GET", "/requests?limit=200", token=tok, base=base)[1]
        o["auths"] = call("GET", "/authorizations?limit=200", token=tok, base=base)[1]
        out[name] = o
    return out


class TestFromStage1(unittest.TestCase):
    @unittest.skipUnless(PREV1, "BASE_URL_PREV1 not set")
    def test_stage1_export(self):
        fx = fixture(users=[user("ada", 10000), user("bob", 2500), user("cy", 500), user("op", 0)], settlement_operator_ids=["u_op"],
                     payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
                               {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 200, "note": "", "visibility": "private"}],
                     requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}])
        call("POST", "/_test/reset", fx, base=PREV1)
        tk = {n: call("POST", "/auth/login", {"email": n + "@example.com", "password": "correct horse"}, base=PREV1)[1]["token"] for n in ("ada", "bob", "cy", "op")}
        k1 = nk()
        a = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, tk["ada"], k1, base=PREV1)
        k2 = nk()
        s = call("POST", "/settlements", {"transfers": [{"from_handle": "bob", "to_handle": "cy", "amount": 30}]}, tk["op"], k2, base=PREV1)
        ex = call("GET", "/_test/export", base=PREV1)[1]
        self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        # every payment has revision 1; opening balances = imported balance minus net effect of all imported payments
        ids = [x["payment_id"] for x in call("GET", "/activity?limit=200", token=tk["ada"])[1]["payments"]]
        self.assertEqual(set(ids), {"p_1", a[1]["payment_id"], s[1]["payments"][0]["payment_id"]} - {s[1]["payments"][0]["payment_id"]} | {"p_1", a[1]["payment_id"]} | ({s[1]["payments"][0]["payment_id"]}))
        for pid in ("p_1", a[1]["payment_id"]):
            revs = call("GET", "/payments/%s/revisions" % pid, token=tk["ada"])[1]["revisions"]
            self.assertEqual([r["revision"] for r in revs], [1])
            self.assertEqual(revs[0]["effective_at"], revs[0]["recorded_at"])
        early = "2000-01-01T00:00:00Z"
        # ada: 10000 balance; sent 500 (p_1) and 100 -> opening 10600; bob: 2500 + 500 - 200 + 100 - 30 -> opening 2500 - 500 + 200 - 100 + 30
        self.assertEqual(me(tk["ada"], as_of=early)[1]["balance"], call("GET", "/me", token=tk["ada"])[1]["balance"] + 500 + 100)
        self.assertEqual(me(tk["bob"], as_of=early)[1]["balance"], call("GET", "/me", token=tk["bob"])[1]["balance"] - 500 + 200 - 100 + 30)
        self.assertEqual(sum(me(tk[n], as_of=early)[1]["balance"] for n in tk), 13000)
        for n in tk:
            j = call("GET", "/statement", token=tk[n])[1]
            self.assertEqual(j["opening_balance"] + sum(e["delta"] for e in j["entries"]), j["closing_balance"])
            self.assertEqual(j["closing_balance"], call("GET", "/me", token=tk[n])[1]["balance"])
        # tokens and retries still valid; corrections work on imported payments
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 100}, tk["ada"], k1)[:2], (200, a[1] | {"authorization_id": None}))
        r = call("POST", "/settlements", {"transfers": [{"from_handle": "bob", "to_handle": "cy", "amount": 30}]}, tk["op"], k2)
        self.assertEqual(r[0], 200)
        self.assertEqual(correct(tk["ada"], "p_1", 1, 400, iso(now()))[0], 201)
        err(correct(tk["op"], s[1]["payments"][0]["payment_id"], 1, 5, iso(now())), 403, "forbidden")
        err(correct(tk["bob"], s[1]["payments"][0]["payment_id"], 1, 5, iso(now())), 422, "linked_payment_immutable")
        # the clock continues after imported state
        newp = pay(tk["ada"], "bob", 1)[1]
        self.assertGreater(newp["created_at"], max(x["created_at"] for x in ex["state"]["payments"]))
        self.assertEqual(call("GET", "/_test/export")[0], 200)


class TestFromStage2(unittest.TestCase):
    @unittest.skipUnless(PREV2, "BASE_URL_PREV2 not set")
    def test_stage2_export_with_holds(self):
        future = iso(now() + timedelta(days=1))
        fx = fixture(users=[user("ada", 10000), user("bob", 2500), user("cy", 500)],
                     authorizations=[{"id": "a_seed", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 700, "status": "open", "expires_at": future},
                                     {"id": "a_seed_cap", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "status": "captured", "expires_at": future},
                                     {"id": "a_seed_void", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "status": "voided", "expires_at": future}],
                     authorization_ttl_seconds=600)
        call("POST", "/_test/reset", fx, base=PREV2)
        tk = {n: call("POST", "/auth/login", {"email": n + "@example.com", "password": "correct horse"}, base=PREV2)[1]["token"] for n in ("ada", "bob", "cy")}
        p1 = call("POST", "/payments", {"to_handle": "cy", "amount": 100}, tk["ada"], nk(), base=PREV2)[1]
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, tk["ada"], nk(), base=PREV2)[1]["authorization_id"]
        time.sleep(1.1)  # stage-2 payments carry whole seconds: keep the capture clearly after the creation
        c1 = call("POST", "/authorizations/%s/capture" % a, {"amount": 300, "final": False}, tk["bob"], nk(), base=PREV2)[1]
        v = call("POST", "/authorizations/%s/void" % a, None, tk["ada"], base=PREV2)[1]
        b = call("POST", "/authorizations", {"to_handle": "cy", "amount": 400}, tk["ada"], nk(), base=PREV2)[1]["authorization_id"]
        time.sleep(1.1)
        c2 = call("POST", "/authorizations/%s/capture" % b, {"amount": 150}, tk["cy"], nk(), base=PREV2)[1]
        d = call("POST", "/authorizations", {"to_handle": "cy", "amount": 80}, tk["ada"], nk(), base=PREV2)[1]
        ex = call("GET", "/_test/export", base=PREV2)[1]
        self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        auths = {x["authorization_id"]: x for x in call("GET", "/authorizations?limit=200", token=tk["ada"])[1]["authorizations"]}
        # decision G-12: derived closed_at
        self.assertEqual(auths[a]["closed_at"], c1["created_at"])        # voided in stage 2: released at its last capture
        self.assertEqual(auths[b]["closed_at"], c2["created_at"])        # final capture
        self.assertIsNone(auths[d["authorization_id"]]["closed_at"])
        self.assertEqual(me(tk["ada"])[1]["held"], 700 + 80)
        # historical holds: before the capture the 1000 was held; the stage-2 void never overdraws
        cc = dtp(c1["created_at"])
        self.assertEqual(me(tk["ada"], as_of=iso(cc - timedelta(microseconds=1)))[1]["held"], 700 + 1000)
        self.assertEqual(me(tk["ada"], as_of=iso(cc))[1]["held"], 700)
        # captures appear once in statements with their links; they are immutable
        st = call("GET", "/statement?limit=200", token=tk["ada"])[1]["entries"]
        self.assertEqual(sum(1 for e in st if e["payment"]["authorization_id"] == a), 1)
        err(correct(tk["ada"], c1["payment_id"], 1, 5, iso(now())), 422, "linked_payment_immutable")
        # the ordinary payment can be corrected and the history stays consistent
        self.assertEqual(correct(tk["ada"], p1["payment_id"], 1, 50, p1["created_at"])[0], 201)
        self.assertEqual(sum(me(tk[n])[1]["balance"] for n in tk), 13000)
        j = call("GET", "/statement", token=tk["ada"])[1]
        self.assertEqual(j["closing_balance"], me(tk["ada"])[1]["balance"])
        # the pending retries
        self.assertEqual(call("POST", "/payments", {"to_handle": "cy", "amount": 100}, tk["ada"], nk())[0], 201)


class TestOwnRoundTrip(unittest.TestCase):
    def build(self):
        reset(fixture(users=[user("ada", 8000), user("bob", 2500), user("cy", 1500), user("op", 0)], settlement_operator_ids=["u_op"],
                      payments=[{"id": "p_s", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 400, "note": "s", "visibility": "public",
                                 "created_at": "2021-03-01T10:00:00.123456789+01:00"}],
                      authorizations=[{"id": "a_s", "from_user_id": "u_cy", "to_user_id": "u_ada", "amount": 200, "status": "open",
                                       "expires_at": iso(now() + timedelta(days=2)), "created_at": "2021-04-01T00:00:00Z"}]))
        tk = {n: login(n) for n in ("ada", "bob", "cy", "op")}
        keys = []
        p = pay(tk["ada"], "bob", 500)[1]
        p2 = pay(tk["bob"], "cy", 300)[1]
        for i, amount in enumerate((450, 0, 520)):
            k = nk()
            body = {"expected_revision": i + 1, "amount": amount, "effective_at": p["created_at"], "reason": "c%d" % i}
            r = call("POST", "/payments/%s/corrections" % p["payment_id"], body, tk["ada"], k)
            self.assertEqual(r[0], 201, r)
            keys.append((p["payment_id"], body, k, r[1]))
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 900}, tk["cy"], nk())[1]["authorization_id"]
        call("POST", "/authorizations/%s/capture" % a, {"amount": 100, "final": False}, tk["bob"], nk())
        call("POST", "/authorizations/%s/void" % a, None, tk["cy"])
        call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 25}]}, tk["op"], nk())
        snaps = {n: call("GET", "/statement?limit=2", token=tk[n])[1]["snapshot"] for n in tk}
        return tk, keys, snaps, p

    def test_roundtrip_same_and_other_container(self):
        tk, keys, snaps, p = self.build()
        instants = ["2000-01-01T00:00:00Z", "2021-03-01T09:00:00.123456789Z", p["created_at"], iso(now()), iso(now() + timedelta(days=1))]
        before = views(None, tk, instants)
        ex = call("GET", "/_test/export")[1]
        before_snap = {n: call("GET", "/statement?snapshot=%s&limit=100" % snaps[n], token=tk[n])[1] for n in tk}
        for base in [None] + ([BASE2] if BASE2 else []):
            if base is None:
                reset(fixture())
            self.assertEqual(call("POST", "/_test/import", ex, base=base)[0], 204)
            after = views(base, tk, instants)
            self.assertEqual(after, before)
            for n in tk:
                got = call("GET", "/statement?snapshot=%s&limit=100" % snaps[n], token=tk[n], base=base)
                self.assertEqual(got[0], 200)
                self.assertEqual(got[1], before_snap[n])
            for pid, body, k, resp in keys:
                r = call("POST", "/payments/%s/corrections" % pid, body, tk["ada"], k, base=base)
                self.assertEqual((r[0], r[1]), (200, resp))
            revs = call("GET", "/payments/%s/revisions" % p["payment_id"], token=tk["ada"], base=base)[1]["revisions"]
            self.assertEqual([r["revision"] for r in revs], [1, 2, 3, 4])
            # a re-export is identical up to nothing: same state
            ex2 = call("GET", "/_test/export", base=base)[1]
            self.assertEqual(ex2["state"], ex["state"])
        # the clock continues: nothing created later is older than imported instants
        newp = pay(tk["ada"], "bob", 1)[1]
        self.assertGreater(newp["created_at"], max(x["created_at"] for x in ex["state"]["payments"] if x["created_at"].startswith("20")))

    def test_clock_continues_after_a_future_instant_in_imported_state(self):
        reset(fixture())
        ada = login("ada")
        pay(ada, "bob", 5)
        ex = call("GET", "/_test/export")[1]
        future = iso(now() + timedelta(seconds=30))
        ex["state"]["payments"][0]["created_at"] = future
        self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        p = pay(ada, "bob", 1)[1]
        self.assertGreater(dtp(p["created_at"]), dtp(future))
        c = correct(ada, p["payment_id"], 1, 2, p["created_at"])
        self.assertEqual(c[0], 201)
        self.assertGreater(c[1]["recorded_at"], p["created_at"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
