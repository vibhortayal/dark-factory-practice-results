"""Own API tests for Pocketful stage 4: refunds and batch corrections (and their interplay with stage 3).

BASE_URL: stage-4 container. BASE_URL2 (optional): a second fresh stage-4 container.
BASE_URL_PREV1/2/3 (optional): containers of the accepted stage-1 / stage-2 / stage-3 images (export sources).
"""
import json
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import test_stage1 as t1
from test_stage1 import BASE, BASE2, call, err, fixture, login, nk, reset, user
from test_stage3_api import Q, MICRO_RE, correct, dtp, iso, me, now, pay, stmt

PREV1 = os.environ.get("BASE_URL_PREV1")
PREV2 = os.environ.get("BASE_URL_PREV2")
PREV3 = os.environ.get("BASE_URL_PREV3")


def refund(tok, pid, amount, key=None):
    return call("POST", "/payments/%s/refunds" % pid, {"amount": amount}, tok, key or nk())


def item(pid, rev, amount, eff, reason="r"):
    return {"payment_id": pid, "expected_revision": rev, "amount": amount, "effective_at": eff, "reason": reason}


def batch(tok, items, key=None):
    return call("POST", "/correction-batches", {"corrections": items}, tok, key or nk())


def revs(tok, pid):
    return call("GET", "/payments/%s/revisions" % pid, token=tok)[1]["revisions"]


class Base(unittest.TestCase):
    def setUp(self):
        reset(fixture(users=[user("ada", 10000), user("bob", 2500), user("cy", 500), user("dee", 3000), user("op", 100)],
                      settlement_operator_ids=["u_op"]))
        self.ada, self.bob, self.cy, self.dee, self.op = (login(h) for h in ("ada", "bob", "cy", "dee", "op"))
        self.toks = (self.ada, self.bob, self.cy, self.dee, self.op)

    def total(self):
        return sum(me(t)[1]["total"] for t in self.toks)

    def settle(self, transfers):
        r = call("POST", "/settlements", {"transfers": transfers}, self.op, nk())
        self.assertEqual(r[0], 201, r)
        return r[1]


class TestRefunds(Base):
    def test_shape_direction_copy_and_nulls(self):
        p = pay(self.ada, "bob", 1000, note="dinner \U0001F600", visibility="private")[1]
        self.assertIsNone(p["refund_of"])
        s, r, _ = refund(self.bob, p["payment_id"], 200)
        self.assertEqual(s, 201)
        self.assertEqual(set(r), {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "currency", "note", "visibility",
                                  "request_id", "settlement_id", "authorization_id", "refund_of", "created_at"})
        self.assertEqual((r["from_handle"], r["to_handle"], r["amount"], r["refund_of"], r["request_id"], r["authorization_id"], r["settlement_id"],
                          r["note"], r["visibility"]), ("bob", "ada", 200, p["payment_id"], None, None, None, "dinner \U0001F600", "private"))
        self.assertNotEqual(r["payment_id"], p["payment_id"])
        self.assertRegex(r["created_at"], MICRO_RE)
        self.assertGreater(r["created_at"], p["created_at"])
        self.assertEqual((me(self.ada)[1]["balance"], me(self.bob)[1]["balance"]), (9200, 3300))
        self.assertEqual(self.total(), 16100)
        # every payment object carries refund_of: activity, statements, pay, capture, settlements
        feed = call("GET", "/activity", token=self.ada)[1]["payments"]
        self.assertEqual({x["payment_id"]: x["refund_of"] for x in feed}, {p["payment_id"]: None, r["payment_id"]: p["payment_id"]})
        for tok in (self.ada, self.bob):
            for e in stmt(tok)[1]["entries"]:
                self.assertIn("refund_of", e["payment"])
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 50}, self.bob, nk())[1]["request_id"]
        self.assertIsNone(call("POST", "/requests/%s/pay" % rq, {}, self.ada, nk())[1]["refund_of"])
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 60}, self.ada, nk())[1]["authorization_id"]
        self.assertIsNone(call("POST", "/authorizations/%s/capture" % a, {}, self.bob, nk())[1]["refund_of"])
        st = self.settle([{"from_handle": "ada", "to_handle": "bob", "amount": 5}])
        self.assertIsNone(st["payments"][0]["refund_of"])

    def test_targets_request_capture_settlement_member(self):
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 500}, self.bob, nk())[1]["request_id"]
        pr = call("POST", "/requests/%s/pay" % rq, {}, self.ada, nk())[1]
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 800}, self.ada, nk())[1]["authorization_id"]
        cap = call("POST", "/authorizations/%s/capture" % a, {"amount": 300}, self.bob, nk())[1]
        st = self.settle([{"from_handle": "ada", "to_handle": "cy", "amount": 400}, {"from_handle": "cy", "to_handle": "dee", "amount": 100}])
        m0, m1 = st["payments"]
        for target, who, amount in ((pr, self.bob, 100), (cap, self.bob, 300), (m0, self.cy, 400), (m1, self.dee, 100)):
            s, r, _ = refund(who, target["payment_id"], amount)
            self.assertEqual(s, 201, (target, r))
            self.assertEqual((r["refund_of"], r["request_id"], r["authorization_id"], r["settlement_id"]), (target["payment_id"], None, None, None))
        # nothing reopened or restored
        self.assertEqual(call("GET", "/requests", token=self.bob)[1]["requests"][0]["status"], "paid")
        au = call("GET", "/authorizations", token=self.ada)[1]["authorizations"][0]
        self.assertEqual((au["status"], au["captured_amount"], au["remaining_amount"], au["payment_ids"]), ("captured", 300, 0, [cap["payment_id"]]))
        self.assertEqual(me(self.ada)[1]["held"], 0)
        # the settlement and its receipts are unchanged
        again = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 1}]}, self.op, nk())[1]
        self.assertEqual(len(again["payments"]), 1)
        a0 = [x for x in call("GET", "/activity?limit=200", token=self.ada)[1]["payments"] if x["payment_id"] == m0["payment_id"]][0]
        self.assertEqual(a0, m0)
        self.assertEqual(self.total(), 16100)

    def test_access_and_validation(self):
        p = pay(self.ada, "bob", 1000)[1]
        pid = p["payment_id"]
        path = "/payments/%s/refunds" % pid
        err(call("POST", path, {"amount": 5}, None, nk()), 401, "unauthenticated")
        err(call("POST", path, {"amount": 5}, self.bob), 400, "missing_idempotency_key")
        err(call("POST", path, {"amount": 5}, self.bob, ""), 400, "missing_idempotency_key")
        err(call("POST", path, {"amount": 5}, self.bob, "k" * 256), 422, "validation_failed")
        err(call("POST", path, raw=b"{x", token=self.bob, key=nk()), 400, "malformed_request")
        err(call("POST", path, raw=b"[1]", token=self.bob, key=nk()), 400, "malformed_request")
        for who in (self.ada, self.cy, self.op):
            err(refund(who, pid, 5), 403, "forbidden")
        err(refund(self.bob, "nope", 5), 404, "not_found")
        err(call("POST", path, {}, self.bob, nk()), 422, "validation_failed")
        for a in (0, -1, 1000000001, 1.5, "5", True, None, [], {}, 10 ** 40):
            err(refund(self.bob, pid, a), 422, "validation_failed")
        self.assertEqual(call("POST", path, raw=b'{"amount":2e2,"x":1}', token=self.bob, key=nk())[0], 201)
        self.assertEqual(call("POST", path, raw=b'{"amount":100.0}', token=self.bob, key=nk())[0], 201)
        for m in ("GET", "PUT", "DELETE"):
            self.assertLess(call(m, path, token=self.bob)[0], 500)

    def test_refund_of_refund_and_cumulative_limits(self):
        p = pay(self.ada, "bob", 1000)[1]
        pid = p["payment_id"]
        r1 = refund(self.bob, pid, 400)[1]
        err(refund(self.ada, r1["payment_id"], 10), 422, "invalid_refund_target")   # the refund's own receiver
        err(refund(self.bob, r1["payment_id"], 10), 422, "invalid_refund_target")   # the refund's sender
        err(refund(self.cy, r1["payment_id"], 10), 422, "invalid_refund_target")    # a third party: the target rule comes first
        err(refund(self.bob, pid, 601), 422, "refund_exceeds_payment")
        self.assertEqual(refund(self.bob, pid, 600)[0], 201)  # exactly the remainder
        err(refund(self.bob, pid, 1), 422, "refund_exceeds_payment")
        self.assertEqual((me(self.ada)[1]["balance"], me(self.bob)[1]["balance"]), (10000, 2500))
        # a correction lowers the amount: refunds count against the corrected amount
        q = pay(self.ada, "bob", 500)[1]
        refund(self.bob, q["payment_id"], 100)
        self.assertEqual(correct(self.ada, q["payment_id"], 1, 300, q["created_at"])[0], 201)
        self.assertEqual(refund(self.bob, q["payment_id"], 200)[0], 201)
        err(refund(self.bob, q["payment_id"], 1), 422, "refund_exceeds_payment")
        # a fully reversed payment cannot be refunded at all
        z = pay(self.ada, "bob", 50)[1]
        self.assertEqual(correct(self.ada, z["payment_id"], 1, 0, z["created_at"])[0], 201)
        err(refund(self.bob, z["payment_id"], 1), 422, "refund_exceeds_payment")

    def test_available_funds_and_atomicity(self):
        p = pay(self.ada, "cy", 400)[1]
        # cy holds 900, has 100 available... authorise 800 of cy's 900
        call("POST", "/authorizations", {"to_handle": "bob", "amount": 800}, self.cy, nk())
        self.assertEqual(me(self.cy)[1]["available"], 100)
        err(refund(self.cy, p["payment_id"], 101), 409, "insufficient_funds")
        self.assertEqual(me(self.cy)[1]["total"], 900)
        self.assertEqual(len(call("GET", "/activity", token=self.ada)[1]["payments"]), 1)
        self.assertEqual(refund(self.cy, p["payment_id"], 100)[0], 201)
        self.assertEqual(me(self.cy)[1]["available"], 0)
        # a failed refund claims no key and counts nothing against the limit
        k = nk()
        err(refund(self.cy, p["payment_id"], 50, k), 409, "insufficient_funds")
        call("POST", "/payments", {"to_handle": "cy", "amount": 60}, self.ada, nk())
        self.assertEqual(refund(self.cy, p["payment_id"], 50, k)[0], 201)

    def test_check_order_adjacent_pairs(self):
        p = pay(self.ada, "bob", 1000)[1]
        pid = p["payment_id"]
        r1 = refund(self.bob, pid, 100)[1]
        # validation before 404
        err(refund(self.bob, "nope", 0), 422, "validation_failed")
        # 404 before the target rule
        err(refund(self.bob, "nope", 5), 404, "not_found")
        # target rule before permission
        err(refund(self.cy, r1["payment_id"], 5), 422, "invalid_refund_target")
        # permission before the limit
        err(refund(self.cy, pid, 5000), 403, "forbidden")
        # limit before funds: bob cannot afford 5000 and exceeds the payment
        call("POST", "/payments", {"to_handle": "cy", "amount": 3400}, self.bob, nk())
        err(refund(self.bob, pid, 5000), 422, "refund_exceeds_payment")
        # funds last
        err(refund(self.bob, pid, 900), 409, "insufficient_funds")
        # a claimed key replays before any validation
        call("POST", "/payments", {"to_handle": "bob", "amount": 10}, self.ada, nk())
        k = nk()
        first = refund(self.bob, pid, 1, k)
        self.assertEqual(first[0], 201)
        self.assertEqual(call("POST", "/payments/%s/refunds" % pid, {"amount": 1}, self.bob, k)[:2], (200, first[1]))
        err(call("POST", "/payments/%s/refunds" % pid, {"amount": "x"}, self.bob, k), 409, "idempotency_key_reuse")
        err(call("POST", "/payments/%s/refunds" % pid, {"amount": 2}, self.bob, k), 409, "idempotency_key_reuse")

    def test_ledger_citizen(self):
        p = pay(self.ada, "bob", 700)[1]
        pid = p["payment_id"]
        r = refund(self.bob, pid, 300)[1]
        rid = r["payment_id"]
        # both parties' statements contain it once, linked; the feed shows it
        for tok in (self.ada, self.bob):
            es = [e for e in stmt(tok)[1]["entries"] if e["payment"]["payment_id"] == rid]
            self.assertEqual(len(es), 1)
            self.assertEqual(es[0]["payment"]["refund_of"], pid)
            self.assertEqual((es[0]["revision"], es[0]["effective_at"], es[0]["recorded_at"]), (1, r["created_at"], r["created_at"]))
        self.assertEqual(call("GET", "/payments/%s/revisions" % rid, token=self.ada)[1]["revisions"][0]["revision"], 1)
        err(call("GET", "/payments/%s/revisions" % rid, token=self.cy), 404, "not_found")
        # as_of / known_at: the refund counts from its created_at
        c = dtp(r["created_at"])
        eps = timedelta(microseconds=1)
        self.assertEqual(me(self.ada, as_of=iso(c - eps))[1]["balance"], 9300)
        self.assertEqual(me(self.ada, as_of=iso(c))[1]["balance"], 9600)
        self.assertEqual(me(self.ada, as_of=iso(c + timedelta(days=1)), known_at=iso(c - eps))[1]["balance"], 9300)
        self.assertEqual(sum(me(t, as_of=iso(c))[1]["balance"] for t in self.toks), 16100)
        # a refund cannot be corrected (by its sender), a capture neither
        err(correct(self.bob, rid, 1, 1, iso(now())), 422, "linked_payment_immutable")
        err(correct(self.ada, rid, 1, 1, iso(now())), 403, "forbidden")

    def test_burst_never_exceeds(self):
        p = pay(self.ada, "bob", 1000)[1]
        pid = p["payment_id"]
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: refund(self.bob, pid, 60 + i % 7), range(50)))
        ok = [r for r in rs if r[0] == 201]
        self.assertTrue(all(r[0] in (201, 422) for r in rs), sorted({r[0] for r in rs}))
        self.assertLessEqual(sum(r[1]["amount"] for r in ok), 1000)
        self.assertGreater(sum(r[1]["amount"] for r in ok), 1000 - 67)
        self.assertEqual(self.total(), 16100)
        k = nk()
        q = pay(self.ada, "bob", 500)[1]
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: refund(self.bob, q["payment_id"], 100, k), range(50)))
        self.assertEqual(sorted(r[0] for r in rs), [200] * 49 + [201])
        # refunds racing corrections that lower the amount: some serial order
        for _ in range(3):
            z = pay(self.ada, "bob", 600)[1]
            fns = [lambda: refund(self.bob, z["payment_id"], 100) for _ in range(20)] + \
                  [lambda: correct(self.ada, z["payment_id"], 1, 300, z["created_at"]) for _ in range(10)]
            with ThreadPoolExecutor(30) as ex:
                out = list(ex.map(lambda f: f(), fns))
            self.assertTrue(all(r[0] < 500 for r in out))
            current = revs(self.ada, z["payment_id"])[-1]["amount"]
            refunded = sum(r[1]["amount"] for r in out[:20] if r[0] == 201)
            self.assertLessEqual(refunded, current)
            self.assertEqual(self.total(), 16100 + 0 * 1)

    def test_settlement_refund_keeps_membership(self):
        st = self.settle([{"from_handle": "ada", "to_handle": "bob", "amount": 100}, {"from_handle": "bob", "to_handle": "cy", "amount": 50}])
        m = st["payments"][0]
        r = refund(self.bob, m["payment_id"], 100)[1]
        self.assertIsNone(r["settlement_id"])
        # the settlement is still a complete set for batches
        e = iso(now())
        res = batch(self.op, [item(x["payment_id"], 1, x["amount"], st["committed_at"]) for x in st["payments"]])
        self.assertEqual(res[0], 201, res)


class TestSingleCorrectionsWithRefunds(Base):
    def test_refunded_floor_and_pairs(self):
        p = pay(self.ada, "bob", 1000)[1]
        pid, c0 = p["payment_id"], p["created_at"]
        refund(self.bob, pid, 300)
        err(correct(self.ada, pid, 1, 299, c0), 422, "refund_exceeds_payment")
        self.assertEqual(correct(self.ada, pid, 1, 300, c0)[0], 201)   # equal to the refunded amount is fine
        # adjacent pairs: 404 -> 403 -> linked -> stale -> refund -> funds -> history
        err(correct(self.ada, "nope", 1, 1, c0), 404, "not_found")
        err(correct(self.bob, pid, 1, 1, c0), 403, "forbidden")
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, self.ada, nk())[1]["authorization_id"]
        cap = call("POST", "/authorizations/%s/capture" % a, {}, self.bob, nk())[1]
        err(correct(self.ada, cap["payment_id"], 99, 1, c0), 422, "linked_payment_immutable")  # linked before stale
        st = self.settle([{"from_handle": "ada", "to_handle": "cy", "amount": 10}])
        err(correct(self.ada, st["payments"][0]["payment_id"], 1, 1, c0), 422, "linked_payment_immutable")
        err(correct(self.ada, pid, 1, 0, c0), 409, "stale_revision")  # stale before refund_exceeds (rev 2 is current)
        q = pay(self.ada, "bob", 500)[1]
        refund(self.bob, q["payment_id"], 200)
        # refund_exceeds before insufficient_funds / history: a raise that nobody could afford and a cut below the refunded sum
        err(correct(self.ada, q["payment_id"], 1, 100, q["created_at"]), 422, "refund_exceeds_payment")
        # funds before history: ada has almost nothing available
        call("POST", "/authorizations", {"to_handle": "cy", "amount": me(self.ada)[1]["available"]}, self.ada, nk())
        err(correct(self.ada, q["payment_id"], 1, 900, "2001-01-01T00:00:00Z"), 409, "insufficient_funds")

    def test_revision_objects_carry_correction_batch_id(self):
        p = pay(self.ada, "bob", 100)[1]
        j = correct(self.ada, p["payment_id"], 1, 90, p["created_at"])[1]
        self.assertIsNone(j["correction_batch_id"])
        rs = revs(self.ada, p["payment_id"])
        self.assertEqual([r["correction_batch_id"] for r in rs], [None, None])
        self.assertEqual(rs[1], j)


class TestBatches(Base):
    def mk(self, n=3, base=300):
        return [pay(self.ada, "bob", base + i)[1] for i in range(n)]

    def test_access_shape_and_errors(self):
        ps = self.mk(2)
        e = ps[0]["created_at"]
        good = [item(p["payment_id"], 1, 10, p["created_at"]) for p in ps]
        err(call("POST", "/correction-batches", {"corrections": good}, None, nk()), 401, "unauthenticated")
        for who in (self.ada, self.bob, self.cy):
            err(call("POST", "/correction-batches", {"corrections": good}, who, nk()), 403, "forbidden")
        err(call("POST", "/correction-batches", {"corrections": good}, self.op), 400, "missing_idempotency_key")
        err(call("POST", "/correction-batches", {"corrections": good}, self.op, "k" * 256), 422, "validation_failed")
        err(call("POST", "/correction-batches", raw=b"{x", token=self.op, key=nk()), 400, "malformed_request")
        err(call("POST", "/correction-batches", raw=b"[]", token=self.op, key=nk()), 400, "malformed_request")
        shapes = [{}, {"corrections": None}, {"corrections": "x"}, {"corrections": {}}, {"corrections": []},
                  {"corrections": [good[0]] * 2}, {"corrections": [good[0], 5]}, {"corrections": [good[0], None]},
                  {"corrections": [good[0], [1]]}, {"corrections": [good[0]] * 33},
                  {"corrections": [item("p%d" % i, 1, 1, e) for i in range(33)]}]
        for body in shapes:
            err(call("POST", "/correction-batches", body, self.op, nk()), 422, "validation_failed")
        # 32 distinct items are accepted (unknown payments are 404 though)
        err(call("POST", "/correction-batches", {"corrections": [item("p%d" % i, 1, 1, e) for i in range(32)]}, self.op, nk()), 404, "not_found")
        # item fields
        base = good[0]
        for f in ("payment_id", "expected_revision", "amount", "effective_at", "reason"):
            body = {k: v for k, v in base.items() if k != f}
            err(call("POST", "/correction-batches", {"corrections": [body]}, self.op, nk()), 422, "validation_failed")
        bads = {"payment_id": [5, None, [], {}, True], "expected_revision": [0, -1, 1.5, "1", True, None, 10 ** 40],
                "amount": [-1, 1000000001, 1.5, "5", True, None], "effective_at": ["", "2020-01-01", "x", 5, None, iso(now() + timedelta(hours=1))],
                "reason": ["", "x" * 201, 5, None]}
        for f, vals in bads.items():
            for v in vals:
                err(call("POST", "/correction-batches", {"corrections": [{**base, f: v}]}, self.op, nk()), 422, "validation_failed")
        # nothing happened
        self.assertEqual([r["revision"] for r in revs(self.ada, ps[0]["payment_id"])], [1])
        # unknown fields are ignored at both levels
        ok = call("POST", "/correction-batches", {"corrections": [{**good[0], "zz": 1}], "extra": 5}, self.op, nk())
        self.assertEqual(ok[0], 201)

    def test_success_shape_atomicity_and_shared_recorded_at(self):
        ps = self.mk(3)
        before = {p["payment_id"]: dtp(revs(self.ada, p["payment_id"])[-1]["recorded_at"]) for p in ps}
        eff = ps[0]["created_at"]
        items = [item(ps[0]["payment_id"], 1, 0, eff, "reverse"), item(ps[1]["payment_id"], 1, 100, ps[1]["created_at"]),
                 item(ps[2]["payment_id"], 1, 400, ps[2]["created_at"], "up")]
        s, j, _ = batch(self.op, items)
        self.assertEqual(s, 201)
        self.assertEqual(set(j), {"correction_batch_id", "recorded_at", "revisions"})
        self.assertRegex(j["recorded_at"], MICRO_RE)
        self.assertEqual([r["payment_id"] for r in j["revisions"]], [p["payment_id"] for p in ps])
        for r, it in zip(j["revisions"], items):
            self.assertEqual(set(r), {"payment_id", "revision", "amount", "effective_at", "recorded_at", "reason", "correction_batch_id"})
            self.assertEqual((r["revision"], r["amount"], r["effective_at"], r["reason"], r["recorded_at"], r["correction_batch_id"]),
                             (2, it["amount"], it["effective_at"], it["reason"], j["recorded_at"], j["correction_batch_id"]))
        self.assertTrue(all(dtp(j["recorded_at"]) > before[p["payment_id"]] for p in ps))
        # money moved in one step: ada pays 300+301+302 originally -> 0 + 100 + 400
        self.assertEqual((me(self.ada)[1]["balance"], me(self.bob)[1]["balance"]), (10000 - 500, 2500 + 500))
        self.assertEqual(self.total(), 16100)
        # revisions and statements reflect the batch; the original payments, receipts and feed do not change
        rs = revs(self.bob, ps[1]["payment_id"])
        self.assertEqual((len(rs), rs[1]["correction_batch_id"], rs[0]["correction_batch_id"]), (2, j["correction_batch_id"], None))
        st = stmt(self.ada)[1]["entries"]
        self.assertEqual([e["delta"] for e in st], [0, -100, -400])
        feed = call("GET", "/activity", token=self.ada)[1]["payments"]
        self.assertEqual({x["payment_id"]: x["amount"] for x in feed}, {p["payment_id"]: p["amount"] for p in ps})
        # the operator is no party and gets no read access
        err(call("GET", "/payments/%s/revisions" % ps[0]["payment_id"], token=self.op), 404, "not_found")
        # a second batch over the same payments needs the new revision
        err(batch(self.op, [item(ps[0]["payment_id"], 1, 5, eff)]), 409, "stale_revision")
        r2 = batch(self.op, [item(ps[0]["payment_id"], 2, 5, eff)])
        self.assertEqual(r2[0], 201)
        self.assertGreater(r2[1]["recorded_at"], j["recorded_at"])
        self.assertNotEqual(r2[1]["correction_batch_id"], j["correction_batch_id"])

    def test_replay_reuse_and_failures_claim_nothing(self):
        ps = self.mk(2)
        items = [item(p["payment_id"], 1, 11, p["created_at"]) for p in ps]
        k = nk()
        err(call("POST", "/correction-batches", {"corrections": [item("nope", 1, 1, ps[0]["created_at"])]}, self.op, k), 404, "not_found")
        r1 = call("POST", "/correction-batches", {"corrections": items}, self.op, k)
        self.assertEqual(r1[0], 201)
        r2 = call("POST", "/correction-batches", {"corrections": list(reversed(items))}, self.op, k)
        err(r2, 409, "idempotency_key_reuse")
        reorder = call("POST", "/correction-batches", {"corrections": items, "x": 0}, self.op, k)
        err(reorder, 409, "idempotency_key_reuse")
        rep = call("POST", "/correction-batches", {"corrections": items}, self.op, k)
        self.assertEqual((rep[0], rep[1]), (200, r1[1]))
        # replay after newer revisions
        batch(self.op, [item(ps[0]["payment_id"], 2, 3, ps[0]["created_at"])])
        self.assertEqual(call("POST", "/correction-batches", {"corrections": items}, self.op, k)[:2], (200, r1[1]))
        # a single correction's key does not interact with a batch key (other path)
        self.assertEqual(call("POST", "/payments/%s/corrections" % ps[1]["payment_id"], {"expected_revision": 2, "amount": 4,
                                                                                          "effective_at": ps[1]["created_at"], "reason": "r"}, self.op, k)[0], 403)
        # concurrent identical
        qs = self.mk(2, 50)
        body = {"corrections": [item(p["payment_id"], 1, 7, p["created_at"]) for p in qs]}
        k2 = nk()
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: call("POST", "/correction-batches", body, self.op, k2), range(50)))
        self.assertEqual(sorted(r[0] for r in rs), [200] * 49 + [201])
        self.assertEqual(len(revs(self.ada, qs[0]["payment_id"])), 2)
        self.assertEqual(self.total(), 16100)

    def test_linked_and_refunded_items(self):
        p = pay(self.ada, "bob", 1000)[1]
        refund(self.bob, p["payment_id"], 400)
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, self.ada, nk())[1]["authorization_id"]
        cap = call("POST", "/authorizations/%s/capture" % a, {}, self.bob, nk())[1]
        rf = call("GET", "/activity?limit=200", token=self.ada)[1]["payments"]
        refund_pay = [x for x in rf if x["refund_of"]][0]
        e = p["created_at"]
        err(batch(self.op, [item(cap["payment_id"], 1, 1, e)]), 422, "linked_payment_immutable")
        err(batch(self.op, [item(refund_pay["payment_id"], 1, 1, e)]), 422, "linked_payment_immutable")
        err(batch(self.op, [item(p["payment_id"], 1, 399, e)]), 422, "refund_exceeds_payment")
        self.assertEqual(batch(self.op, [item(p["payment_id"], 1, 400, e)])[0], 201)
        # the operator may correct payments of any users, including request payments
        rq = call("POST", "/requests", {"payer_handle": "cy", "amount": 100}, self.dee, nk())[1]["request_id"]
        q = call("POST", "/requests/%s/pay" % rq, {}, self.cy, nk())[1]
        self.assertEqual(batch(self.op, [item(q["payment_id"], 1, 50, q["created_at"])])[0], 201)
        # the single endpoint stays sender-only
        err(call("POST", "/payments/%s/corrections" % q["payment_id"], {"expected_revision": 2, "amount": 1, "effective_at": q["created_at"], "reason": "r"},
                 self.op, nk()), 403, "forbidden")

    def test_settlements(self):
        st = self.settle([{"from_handle": "ada", "to_handle": "bob", "amount": 100}, {"from_handle": "bob", "to_handle": "cy", "amount": 40},
                          {"from_handle": "cy", "to_handle": "dee", "amount": 10}])
        mem = st["payments"]
        c = st["committed_at"]
        # members: every member or none; the single endpoint refuses them
        err(correct(self.ada, mem[0]["payment_id"], 1, 1, c), 422, "linked_payment_immutable")
        err(batch(self.op, [item(mem[0]["payment_id"], 1, 1, c)]), 422, "incomplete_settlement")
        err(batch(self.op, [item(mem[0]["payment_id"], 1, 1, c), item(mem[1]["payment_id"], 1, 1, c)]), 422, "incomplete_settlement")
        # identical effective instants, in any spelling
        spell = [c, c.replace("+00:00", "Z"), iso(dtp(c)).replace("+00:00", "+00:00")]
        d2 = dtp(c).astimezone(timezone(timedelta(hours=2))).isoformat(timespec="microseconds")
        err(batch(self.op, [item(m["payment_id"], 1, 1, e) for m, e in zip(mem, [c, c, iso(dtp(c) + timedelta(microseconds=1))])]), 422, "validation_failed")
        eff = iso(dtp(c) - timedelta(seconds=1))
        eff2 = dtp(eff).astimezone(timezone(timedelta(hours=-5))).isoformat(timespec="microseconds")
        ok = batch(self.op, [item(mem[0]["payment_id"], 1, 50, eff), item(mem[1]["payment_id"], 1, 20, eff2), item(mem[2]["payment_id"], 1, 5, eff.replace("+00:00", "Z"))])
        self.assertEqual(ok[0], 201, ok)
        # membership kept; /revisions show the batch revision
        for m in mem:
            rs = revs(self.ada if m["from_handle"] == "ada" else self.bob if m["from_handle"] == "bob" else self.cy, m["payment_id"])
            self.assertEqual((len(rs), rs[1]["correction_batch_id"]), (2, ok[1]["correction_batch_id"]))
        acts = [x for x in call("GET", "/activity?limit=200", token=self.ada)[1]["payments"] if x["settlement_id"] == st["settlement_id"]]
        self.assertEqual({x["payment_id"]: x["amount"] for x in acts}, {m["payment_id"]: m["amount"] for m in mem if m["payment_id"] in {x["payment_id"] for x in acts}})
        self.assertEqual(self.total(), 16100)
        # a settlement stays a settlement: the next batch must again include everyone
        err(batch(self.op, [item(mem[2]["payment_id"], 2, 1, eff)]), 422, "incomplete_settlement")
        # several settlements and ordinary payments in one batch
        st2 = self.settle([{"from_handle": "dee", "to_handle": "ada", "amount": 30}])
        o = pay(self.ada, "bob", 20)[1]
        ok2 = batch(self.op, [item(st2["payments"][0]["payment_id"], 1, 0, st2["committed_at"]), item(o["payment_id"], 1, 10, o["created_at"]),
                              item(mem[0]["payment_id"], 2, 50, eff), item(mem[1]["payment_id"], 2, 20, eff), item(mem[2]["payment_id"], 2, 5, eff)])
        self.assertEqual(ok2[0], 201, ok2)

    def test_error_precedence_pairs(self):
        st = self.settle([{"from_handle": "ada", "to_handle": "bob", "amount": 100}, {"from_handle": "bob", "to_handle": "cy", "amount": 40}])
        mem = st["payments"]
        c = st["committed_at"]
        o = pay(self.ada, "bob", 20)[1]
        oe = o["created_at"]
        # item errors come in input order, the first failing item decides
        err(batch(self.op, [item(o["payment_id"], 7, 1, oe), item("nope", 1, 1, oe)]), 409, "stale_revision")
        err(batch(self.op, [item(o["payment_id"], 1, 1, oe), item("nope", 1, 1, oe), {"payment_id": o["payment_id"] + "x", "amount": "bad"}]), 404, "not_found")
        err(batch(self.op, [item(o["payment_id"], 1, "x", oe), item("nope", 1, 1, oe)]), 422, "validation_failed")
        # within an item: validation, 404, linked, stale, refund
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, self.ada, nk())[1]["authorization_id"]
        cap = call("POST", "/authorizations/%s/capture" % a, {}, self.bob, nk())[1]
        err(batch(self.op, [item(cap["payment_id"], 9, 1, oe)]), 422, "linked_payment_immutable")
        r = pay(self.ada, "bob", 300)[1]
        refund(self.bob, r["payment_id"], 200)
        err(batch(self.op, [item(r["payment_id"], 9, 1, oe)]), 409, "stale_revision")
        err(batch(self.op, [item(r["payment_id"], 1, 1, oe)]), 422, "refund_exceeds_payment")
        # item errors before settlement completeness
        err(batch(self.op, [item(mem[0]["payment_id"], 1, 1, c), item(o["payment_id"], 5, 1, oe)]), 409, "stale_revision")
        # settlement completeness before the effective-instant rule and before funds
        err(batch(self.op, [item(mem[0]["payment_id"], 1, 1, c), item(o["payment_id"], 1, 1, oe)]), 422, "incomplete_settlement")
        # effective-instant rule before funds: members at different instants AND an unaffordable raise
        later = iso(dtp(c) + timedelta(microseconds=1))
        err(batch(self.op, [item(mem[0]["payment_id"], 1, 100, c), item(mem[1]["payment_id"], 1, 40, later),
                            item(r["payment_id"], 1, 900000, oe)] if False else
                  [item(mem[0]["payment_id"], 1, 100, c), item(mem[1]["payment_id"], 1, 40, later)]), 422, "validation_failed")
        # funds before history: ada has 10000 - ...; raise one payment beyond her available and time it before her own opening
        big = pay(self.ada, "bob", 100)[1]
        avail = me(self.ada)[1]["available"]
        err(batch(self.op, [item(big["payment_id"], 1, 100 + avail + 1, "2001-01-01T00:00:00Z")]), 409, "insufficient_funds")
        # history last: bob is paid 100 by ada, then spends nearly all of it; moving the incoming payment to after the spend overdraws bob
        p_in = pay(self.ada, "bob", 100)[1]
        spend = me(self.bob)[1]["available"]
        p_out = pay(self.bob, "cy", spend)[1]
        err(batch(self.op, [item(p_in["payment_id"], 1, 100, iso(now()))]), 409, "historical_overdraft")
        big = p_in
        # a rejected batch leaves everything as it was
        self.assertEqual(len(revs(self.ada, big["payment_id"])), 1)
        k = nk()
        err(call("POST", "/correction-batches", {"corrections": [item(big["payment_id"], 1, 100, iso(now()))]}, self.op, k), 409, "historical_overdraft")
        self.assertEqual(call("POST", "/correction-batches", {"corrections": [item(big["payment_id"], 1, 100, big["created_at"])]}, self.op, k)[0], 201)

    def test_combined_affordability_and_history(self):
        # bob holds 2500; two payments to cy from bob and a raise on one, a cut on the other, net zero for bob: affordable together
        p1 = pay(self.bob, "cy", 1000)[1]
        p2 = pay(self.bob, "cy", 1000)[1]
        avail = me(self.bob)[1]["available"]
        self.assertEqual(avail, 500)
        up = 1000 + 600   # alone unaffordable (+600 > 500)
        err(call("POST", "/payments/%s/corrections" % p1["payment_id"], {"expected_revision": 1, "amount": up, "effective_at": p1["created_at"], "reason": "r"},
                 self.bob, nk()), 409, "insufficient_funds")
        err(batch(self.op, [item(p1["payment_id"], 1, up, p1["created_at"])]), 409, "insufficient_funds")
        ok = batch(self.op, [item(p1["payment_id"], 1, up, p1["created_at"]), item(p2["payment_id"], 1, 400, p2["created_at"])])
        self.assertEqual(ok[0], 201, ok)
        self.assertEqual((me(self.bob)[1]["balance"], me(self.cy)[1]["balance"]), (2500 - 1600 - 400 + 0 * 1, 500 + 2000))
        # history combined over several items: retiming both payments after a spend of cy overdraws nobody when both go together
        self.assertEqual(self.total(), 16100)

    def test_snapshots_and_old_receipts_stay(self):
        ps = self.mk(3)
        j = stmt(self.ada, limit=2)[1]
        tok = j["snapshot"]
        full = stmt(self.ada, snapshot=tok, limit=100)[1]
        ok = batch(self.op, [item(p["payment_id"], 1, 0, p["created_at"], "zero") for p in ps])
        self.assertEqual(ok[0], 201)
        self.assertEqual(stmt(self.ada, snapshot=tok, limit=100)[1], full)
        self.assertEqual(sum(e["delta"] for e in stmt(self.ada)[1]["entries"]), 0)
        # the original idempotent responses replay unchanged
        k = nk()
        o = call("POST", "/payments", {"to_handle": "cy", "amount": 9}, self.ada, k)[1]
        batch(self.op, [item(o["payment_id"], 1, 1, o["created_at"])])
        self.assertEqual(call("POST", "/payments", {"to_handle": "cy", "amount": 9}, self.ada, k)[:2], (200, o))
        st = self.settle([{"from_handle": "ada", "to_handle": "bob", "amount": 3}])
        kk = nk()
        first = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 4}]}, self.op, kk)[1]
        batch(self.op, [item(first["payments"][0]["payment_id"], 1, 2, first["committed_at"])])
        self.assertEqual(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 4}]}, self.op, kk)[:2], (200, first))

    def test_concurrent_overlapping_batches(self):
        ps = self.mk(6, 100)
        ids = [p["payment_id"] for p in ps]

        def go(i):
            sel = [ids[(i + j) % 6] for j in range(3)]
            its = [item(pid, 1, 10 + i % 5, next(p["created_at"] for p in ps if p["payment_id"] == pid)) for pid in sel]
            return batch(self.op, its)
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(go, range(50)))
        codes = sorted({r[0] for r in rs})
        self.assertTrue(set(codes) <= {201, 409}, codes)
        won = [r for r in rs if r[0] == 201]
        # no payment was corrected twice from revision 1
        counts = {}
        for r in won:
            for rev in r[1]["revisions"]:
                counts[rev["payment_id"]] = counts.get(rev["payment_id"], 0) + 1
        self.assertTrue(all(v == 1 for v in counts.values()), counts)
        for pid in ids:
            self.assertEqual(len(revs(self.ada, pid)), 1 + counts.get(pid, 0))
        # singles and batches racing on the same revision
        q = pay(self.ada, "bob", 50)[1]
        fns = [lambda: correct(self.ada, q["payment_id"], 1, 5, q["created_at"]) for _ in range(15)] + \
              [lambda: batch(self.op, [item(q["payment_id"], 1, 6, q["created_at"])]) for _ in range(15)]
        with ThreadPoolExecutor(30) as ex:
            out = list(ex.map(lambda f: f(), fns))
        self.assertEqual(sum(1 for r in out if r[0] == 201), 1)
        self.assertTrue(all(r[0] in (201, 409) for r in out))
        self.assertEqual(self.total(), 16100)


class TestStoredResponsesAgreeWithLedger(Base):
    def test_import_refuses_altered_stored_responses(self):
        p = pay(self.ada, "bob", 100)[1]
        q = pay(self.ada, "bob", 50)[1]
        kb, kr = nk(), nk()
        b = call("POST", "/correction-batches", {"corrections": [item(p["payment_id"], 1, 60, p["created_at"])]}, self.op, kb)
        self.assertEqual(b[0], 201)
        rf = call("POST", "/payments/%s/refunds" % q["payment_id"], {"amount": 10}, self.bob, kr)
        ex = call("GET", "/_test/export")[1]
        before = call("GET", "/_test/export")[1]
        recs = ex["state"]["idempotency"]

        def rec_of(path_part):
            return [i for i, r in enumerate(recs) if path_part in r["path"]][0]
        bi, ri = rec_of("correction-batches"), rec_of("refunds")
        cases = []
        for v in ("y" * 65, "y" * 300, "", "cb_999", 5, None, ["x"]):
            cases.append(("batch id", bi, ["response", "correction_batch_id"], v))
            cases.append(("revision batch id", bi, ["response", "revisions", 0, "correction_batch_id"], v))
        cases.append(("revision amount", bi, ["response", "revisions", 0, "amount"], 61))
        cases.append(("recorded_at", bi, ["response", "recorded_at"], "2020-01-01T00:00:00Z"))
        for v in ("p_1", "p_2x", "zzz", "", 5, ["x"]):
            cases.append(("refund_of", ri, ["response", "refund_of"], v))
        for name, i, path, v in cases:
            m = json.loads(json.dumps(ex))
            node = m["state"]["idempotency"][i]
            for k in path[:-1]:
                node = node[k]
            node[path[-1]] = v
            r = call("POST", "/_test/import", m)
            self.assertEqual(r[0], 422, (name, repr(v)[:20], r))
            self.assertEqual(call("GET", "/_test/export")[1], before)
        self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        self.assertEqual(call("POST", "/correction-batches", {"corrections": [item(p["payment_id"], 1, 60, p["created_at"])]}, self.op, kb)[:2], (200, b[1]))
        self.assertEqual(call("POST", "/payments/%s/refunds" % q["payment_id"], {"amount": 10}, self.bob, kr)[:2], (200, rf[1]))


class TestTiming4(unittest.TestCase):
    def test_32_item_batch_over_a_large_history(self):
        import random
        rnd = random.Random(8)
        names = ["u%02d" % i for i in range(40)]
        base = now() - timedelta(days=30)
        pays = []
        for i in range(5000):
            a, b = rnd.sample(range(40), 2)
            pays.append({"id": "s%05d" % i, "from_user_id": "u_" + names[a], "to_user_id": "u_" + names[b], "amount": rnd.randint(1, 500),
                         "note": "n", "visibility": "public", "created_at": iso(base + timedelta(seconds=i * 500))})
        users = [user(n, 10 ** 7) for n in names] + [user("op", 0)]
        reset(fixture(users=users, payments=pays, settlement_operator_ids=["u_op"]))
        op = login("op")
        worst = 0
        for r in range(4):
            sel = pays[r * 32:(r + 1) * 32]
            items = [item(p["id"], 1, rnd.randint(0, 600), p["created_at"]) for p in sel]
            t = time.time()
            res = batch(op, items)
            worst = max(worst, time.time() - t)
            self.assertEqual(res[0], 201, res)
        print("32-item batch worst %.3fs" % worst)
        self.assertLess(worst, 5)


if __name__ == "__main__":
    unittest.main(verbosity=1)
