"""Stage-4 service as the destination of exports of the accepted stage-1, stage-2 and stage-3 services, and of its own."""
import json
import os
import time
import unittest
from datetime import timedelta

import test_stage1 as t1
from test_stage1 import BASE, BASE2, call, err, fixture, login, nk, reset, user
from test_stage3_api import Q, correct, dtp, iso, me, now, pay, stmt
from test_stage3_upgrade import views
from test_stage4_api import batch, item, refund, revs

PREV1 = os.environ.get("BASE_URL_PREV1")
PREV2 = os.environ.get("BASE_URL_PREV2")
PREV3 = os.environ.get("BASE_URL_PREV3")


def login_on(base, name):
    return call("POST", "/auth/login", {"email": name + "@example.com", "password": "correct horse"}, base=base)[1]["token"]


class TestFromEarlierStages(unittest.TestCase):
    def fx(self):
        return fixture(users=[user("ada", 10000), user("bob", 2500), user("cy", 500), user("op", 100)], settlement_operator_ids=["u_op"],
                       payments=[{"id": "p_s", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 300, "note": "seed", "visibility": "public"}])

    @unittest.skipUnless(PREV1, "BASE_URL_PREV1 not set")
    def test_stage1_export(self):
        call("POST", "/_test/reset", self.fx(), base=PREV1)
        tk = {n: login_on(PREV1, n) for n in ("ada", "bob", "cy", "op")}
        k = nk()
        p = call("POST", "/payments", {"to_handle": "bob", "amount": 400}, tk["ada"], k, base=PREV1)
        k2 = nk()
        s = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 50}, {"from_handle": "bob", "to_handle": "cy", "amount": 20}]},
                 tk["op"], k2, base=PREV1)
        ex = call("GET", "/_test/export", base=PREV1)[1]
        self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        # retries replay exactly as stored (no member is invented)
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 400}, tk["ada"], k)[:2], (200, p[1]))
        self.assertEqual(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 50}, {"from_handle": "bob", "to_handle": "cy", "amount": 20}]},
                              tk["op"], k2)[:2], (200, s[1]))
        # the imported payments can be refunded; the imported settlement is a complete set for a batch
        r = refund(tk["bob"], p[1]["payment_id"], 100)
        self.assertEqual(r[0], 201)
        mem = s[1]["payments"]
        b = batch(tk["op"], [item(m["payment_id"], 1, m["amount"] - 5, s[1]["committed_at"]) for m in mem])
        self.assertEqual(b[0], 201, b)
        self.assertEqual(b[1]["revisions"][0]["effective_at"], s[1]["committed_at"])
        err(batch(tk["op"], [item(mem[0]["payment_id"], 2, 1, s[1]["committed_at"])]), 422, "incomplete_settlement")
        self.assertEqual(sum(me(tk[n])[1]["total"] for n in tk), 13100)
        self.assertEqual(call("GET", "/_test/export")[0], 200)

    @unittest.skipUnless(PREV2, "BASE_URL_PREV2 not set")
    def test_stage2_export(self):
        call("POST", "/_test/reset", self.fx(), base=PREV2)
        tk = {n: login_on(PREV2, n) for n in ("ada", "bob", "cy", "op")}
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 900}, tk["ada"], nk(), base=PREV2)[1]["authorization_id"]
        time.sleep(1.1)
        cap = call("POST", "/authorizations/%s/capture" % a, {"amount": 300}, tk["bob"], nk(), base=PREV2)[1]
        p = call("POST", "/payments", {"to_handle": "cy", "amount": 200}, tk["ada"], nk(), base=PREV2)[1]
        ex = call("GET", "/_test/export", base=PREV2)[1]
        self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        # a capture can be refunded but never corrected, singly or in a batch
        self.assertEqual(refund(tk["bob"], cap["payment_id"], 100)[0], 201)
        err(batch(tk["op"], [item(cap["payment_id"], 1, 1, cap["created_at"])]), 422, "linked_payment_immutable")
        err(correct(tk["ada"], cap["payment_id"], 1, 1, iso(now())), 422, "linked_payment_immutable")
        self.assertEqual(batch(tk["op"], [item(p["payment_id"], 1, 150, p["created_at"])])[0], 201)
        self.assertEqual(sum(me(tk[n])[1]["total"] for n in tk), 13100)

    @unittest.skipUnless(PREV3, "BASE_URL_PREV3 not set")
    def test_stage3_export_with_corrections_snapshots_and_settlement(self):
        fx = self.fx()
        call("POST", "/_test/reset", fx, base=PREV3)
        tk = {n: login_on(PREV3, n) for n in ("ada", "bob", "cy", "op")}
        pays = [call("POST", "/payments", {"to_handle": "bob", "amount": 100 + i}, tk["ada"], nk(), base=PREV3)[1] for i in range(4)]
        k = nk()
        body = {"expected_revision": 1, "amount": 60, "effective_at": pays[0]["created_at"], "reason": "less"}
        c1 = call("POST", "/payments/%s/corrections" % pays[0]["payment_id"], body, tk["ada"], k, base=PREV3)
        self.assertEqual(c1[0], 201)
        st = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 30}, {"from_handle": "cy", "to_handle": "bob", "amount": 10}]},
                  tk["op"], nk(), base=PREV3)[1]
        snaps = {n: call("GET", "/statement?limit=2", token=tk[n], base=PREV3)[1] for n in ("ada", "bob")}
        full = {n: call("GET", "/statement?snapshot=%s&limit=100" % snaps[n]["snapshot"], token=tk[n], base=PREV3)[1] for n in snaps}
        ex = call("GET", "/_test/export", base=PREV3)[1]
        # mutate the source afterwards: the snapshots stay what they were
        call("POST", "/payments", {"to_handle": "bob", "amount": 7}, tk["ada"], nk(), base=PREV3)
        self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        for n in snaps:
            got = call("GET", "/statement?snapshot=%s&limit=100" % snaps[n]["snapshot"], token=tk[n])
            self.assertEqual((got[0], got[1]), (200, full[n]))
            pages = []
            for off in (0, 2, 4):
                pages += call("GET", "/statement?snapshot=%s&limit=2&offset=%d" % (snaps[n]["snapshot"], off), token=tk[n])[1]["entries"]
            self.assertEqual(pages, full[n]["entries"])
        # correction retries replay exactly as stored; old revisions have no batch id key in the stored response
        r = call("POST", "/payments/%s/corrections" % pays[0]["payment_id"], body, tk["ada"], k)
        self.assertEqual((r[0], r[1]), (200, c1[1]))
        rs = revs(tk["ada"], pays[0]["payment_id"])
        self.assertEqual([x["correction_batch_id"] for x in rs], [None, None])
        # settlement membership retained: an incomplete set is refused, the complete set works
        mem = st["payments"]
        err(batch(tk["op"], [item(mem[0]["payment_id"], 1, 1, st["committed_at"])]), 422, "incomplete_settlement")
        ok = batch(tk["op"], [item(m["payment_id"], 1, m["amount"], st["committed_at"], "same amount") for m in mem])
        self.assertEqual(ok[0], 201, ok)
        # a refund on a corrected payment honours the corrected amount
        err(refund(tk["bob"], pays[0]["payment_id"], 61), 422, "refund_exceeds_payment")
        self.assertEqual(refund(tk["bob"], pays[0]["payment_id"], 60)[0], 201)
        err(correct(tk["ada"], pays[0]["payment_id"], 2, 59, iso(now())), 422, "refund_exceeds_payment")
        # the new snapshots keep working after another export/import
        ex2 = call("GET", "/_test/export")[1]
        self.assertEqual(call("POST", "/_test/import", ex2)[0], 204)
        got = call("GET", "/statement?snapshot=%s&limit=100" % snaps["ada"]["snapshot"], token=tk["ada"])
        self.assertEqual((got[0], got[1]), (200, full["ada"]))


class TestOwnRoundTrip(unittest.TestCase):
    def build(self):
        reset(fixture(users=[user("ada", 9000), user("bob", 2500), user("cy", 1500), user("op", 100)], settlement_operator_ids=["u_op"]))
        tk = {n: login(n) for n in ("ada", "bob", "cy", "op")}
        ps = [pay(tk["ada"], "bob", 400 + i)[1] for i in range(3)]
        keys = []
        r = refund(tk["bob"], ps[0]["payment_id"], 100)
        keys.append(("/payments/%s/refunds" % ps[0]["payment_id"], {"amount": 100}, tk["bob"], None))
        k = nk()
        rf = call("POST", "/payments/%s/refunds" % ps[1]["payment_id"], {"amount": 50}, tk["bob"], k)
        keys.append(("/payments/%s/refunds" % ps[1]["payment_id"], {"amount": 50}, tk["bob"], k, rf[1]))
        st = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 70}, {"from_handle": "bob", "to_handle": "cy", "amount": 30}]},
                  tk["op"], nk())[1]
        kb = nk()
        items = [item(m["payment_id"], 1, m["amount"] - 10, st["committed_at"], "batch") for m in st["payments"]] + \
                [item(ps[2]["payment_id"], 1, 450, ps[2]["created_at"])]
        b = call("POST", "/correction-batches", {"corrections": items}, tk["op"], kb)
        self.assertEqual(b[0], 201, b)
        keys.append(("/correction-batches", {"corrections": items}, tk["op"], kb, b[1]))
        snaps = {n: stmt(tk[n], limit=2)[1]["snapshot"] for n in tk}
        return tk, keys, snaps, ps, st, b[1]

    def test_roundtrip(self):
        tk, keys, snaps, ps, st, b = self.build()
        instants = ["2000-01-01T00:00:00Z", ps[0]["created_at"], st["committed_at"], b["recorded_at"], iso(now() + timedelta(days=1))]
        before = views(None, tk, instants)
        ex = call("GET", "/_test/export")[1]
        full = {n: call("GET", "/statement?snapshot=%s&limit=100" % snaps[n], token=tk[n])[1] for n in tk}
        for base in [None] + ([BASE2] if BASE2 else []):
            if base is None:
                reset(fixture())
            self.assertEqual(call("POST", "/_test/import", ex, base=base)[0], 204)
            self.assertEqual(views(base, tk, instants), before)
            for n in tk:
                self.assertEqual(call("GET", "/statement?snapshot=%s&limit=100" % snaps[n], token=tk[n], base=base)[1], full[n])
            for path, body, tok, k, *resp in keys:
                if k is None:
                    continue
                r = call("POST", path, body, tok, k, base=base)
                self.assertEqual((r[0], r[1]), (200, resp[0]), path)
            for m in st["payments"]:
                rs = call("GET", "/payments/%s/revisions" % m["payment_id"], token=tk["ada"] if m["from_handle"] == "ada" else tk["bob"], base=base)[1]["revisions"]
                self.assertEqual([x["correction_batch_id"] for x in rs], [None, b["correction_batch_id"]])
            ex2 = call("GET", "/_test/export", base=base)[1]
            self.assertEqual(ex2["state"], ex["state"])
            # refunds on the imported payments still respect the derived refunded sums
            err(refund(tk["bob"], ps[0]["payment_id"], 301), 422, "refund_exceeds_payment") if base is None else None
        newp = pay(tk["ada"], "bob", 1)[1]
        self.assertGreater(newp["created_at"], max(x["created_at"] for x in ex["state"]["payments"]))


if __name__ == "__main__":
    unittest.main(verbosity=1)
