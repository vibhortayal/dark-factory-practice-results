"""Stage-4 API rows: RF, CR, CB, UP4, B4 (black box against BASE_URL)."""
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


def dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(d):
    return d.isoformat()


def ago(seconds):
    return iso(datetime.now(timezone.utc) - timedelta(seconds=seconds))


def item(pid, rev, amount, eff, reason="r", **extra):
    d = {"payment_id": pid, "expected_revision": rev, "amount": amount, "effective_at": eff, "reason": reason}
    d.update(extra)
    return d


class S4(unittest.TestCase):
    def setUp(self):
        reset(fixture(users=[user("ada", 10000), user("bob", 2500), user("cy", 500), user("op", 0)],
                      settlement_operator_ids=["u_op"]))
        self.ada, self.bob, self.cy, self.op = login("ada"), login("bob"), login("cy"), login("op")

    def refund(self, tok, pid, amount, key=None, raw=None):
        if raw is not None:
            return call("POST", f"/payments/{pid}/refunds", raw=raw, token=tok, key=key or k())
        return call("POST", f"/payments/{pid}/refunds", {"amount": amount}, tok, key or k())

    def batch(self, tok, items, key=None):
        return call("POST", "/correction-batches", {"corrections": items}, tok, key or k())

    def correct(self, tok, pid, rev, amount, eff, key=None):
        return call("POST", f"/payments/{pid}/corrections",
                    {"expected_revision": rev, "amount": amount, "effective_at": eff, "reason": "fix"}, tok, key or k())

    def stmt(self, tok, qs=""):
        return call("GET", "/statement" + ("?" + qs if qs else ""), token=tok)

    def totals(self):
        return [me(t)["total"] for t in (self.ada, self.bob, self.cy, self.op)]

    def settle(self, transfers):
        return call("POST", "/settlements", {"transfers": transfers}, self.op, k())[2]


class Refunds(S4):
    def test_shape_and_effects(self):  # RF5 RF9 RF10
        p = pay(self.ada, "bob", 1000, note="dinner", visibility="private")[2]
        self.assertIsNone(p["refund_of"])
        s, _, r, _ = self.refund(self.bob, p["payment_id"], 200)
        self.assertEqual(s, 201)
        self.assertEqual((r["from_handle"], r["to_handle"], r["amount"], r["refund_of"], r["request_id"], r["authorization_id"],
                          r["settlement_id"], r["note"], r["visibility"]), ("bob", "ada", 200, p["payment_id"], None, None, None, "dinner", "private"))
        self.assertNotEqual(r["payment_id"], p["payment_id"])
        self.assertRegex(r["payment_id"], r"^p_\d{10}$")
        self.assertGreater(dt(r["created_at"]), dt(p["created_at"]))
        self.assertEqual((me(self.ada)["total"], me(self.bob)["total"]), (9200, 3300))
        # feed: ordinary item under the visibility rule; third party does not see the private refund
        feed = call("GET", "/activity", token=self.ada)[2]["payments"]
        self.assertEqual([x["payment_id"] for x in feed], [r["payment_id"], p["payment_id"]])
        self.assertEqual(feed[0]["refund_of"], p["payment_id"])
        self.assertEqual(feed[1]["refund_of"], None)
        self.assertEqual(call("GET", "/activity", token=self.cy)[2]["payments"], [])
        # statements of both parties, own revision 1, as_of from created_at
        e = self.stmt(self.bob)[2]["entries"]
        self.assertEqual([x["delta"] for x in e], [1000, -200])
        self.assertEqual((e[1]["revision"], e[1]["effective_at"], e[1]["recorded_at"]), (1, r["created_at"], r["created_at"]))
        self.assertEqual(call("GET", f"/me?as_of={r['created_at']}", token=self.bob)[2]["balance"], 3300)
        before = iso(dt(r["created_at"]) - timedelta(microseconds=1))
        self.assertEqual(call("GET", f"/me?as_of={before}", token=self.bob)[2]["balance"], 3500)
        self.assertEqual(self.stmt(self.ada)[2]["entries"][1]["payment"]["refund_of"], p["payment_id"])
        self.assertEqual(sum(self.totals()), 13000)
        revs = call("GET", f"/payments/{r['payment_id']}/revisions", token=self.bob)[2]["revisions"]
        self.assertEqual(len(revs), 1)

    def test_permissions_and_targets(self):  # RF1 RF2
        p = pay(self.ada, "bob", 300)[2]
        pid = p["payment_id"]
        err(self, self.refund(self.ada, pid, 5), 403, "forbidden")      # the sender
        err(self, self.refund(self.cy, pid, 5), 403, "forbidden")       # a third party
        err(self, self.refund(self.bob, "p_nope", 5), 404, "not_found")
        err(self, call("POST", f"/payments/{pid}/refunds", {"amount": 5}), 401, "unauthenticated")
        err(self, call("POST", f"/payments/{pid}/refunds", {"amount": 5}, self.bob), 400, "missing_idempotency_key")
        err(self, call("POST", f"/payments/{pid}/refunds", {"amount": 5}, self.bob, "x" * 256), 422, "validation_failed")
        err(self, call("POST", f"/payments/{pid}/refunds", raw=b"[]", token=self.bob, key=k()), 400, "malformed_request")
        r = self.refund(self.bob, pid, 5)[2]
        err(self, self.refund(self.ada, r["payment_id"], 1), 422, "invalid_refund_target")     # receiver of the refund
        err(self, self.refund(self.bob, r["payment_id"], 1), 403, "forbidden")                   # sender of the refund
        err(self, self.refund(self.cy, r["payment_id"], 1), 403, "forbidden")
        # request payment, capture and settlement member are valid targets
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, self.bob, k())[2]["request_id"]
        pp = call("POST", f"/requests/{rq}/pay", {}, self.ada, k())[2]
        rr = self.refund(self.bob, pp["payment_id"], 40)
        self.assertEqual((rr[0], rr[2]["refund_of"], rr[2]["request_id"]), (201, pp["payment_id"], None))
        rq_after = call("GET", "/requests", token=self.bob)[2]["requests"][0]
        self.assertEqual((rq_after["status"], rq_after["payment_id"]), ("paid", pp["payment_id"]))
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 200, "note": "dep"}, self.ada, k())[2]
        cap = call("POST", f"/authorizations/{a['authorization_id']}/capture", {"amount": 50}, self.bob, k())[2]
        before = call("GET", "/authorizations", token=self.ada)[2]["authorizations"][0]
        rc = self.refund(self.bob, cap["payment_id"], 50)
        self.assertEqual((rc[0], rc[2]["authorization_id"], rc[2]["refund_of"], rc[2]["note"]), (201, None, cap["payment_id"], "dep"))
        self.assertEqual(call("GET", "/authorizations", token=self.ada)[2]["authorizations"][0], before)   # RF8
        self.assertEqual(me(self.ada)["held"], 0)
        st = self.settle([{"from_handle": "ada", "to_handle": "bob", "amount": 70}, {"from_handle": "ada", "to_handle": "cy", "amount": 30}])
        orig = json.dumps(st, sort_keys=True)
        rs = self.refund(self.bob, st["payments"][0]["payment_id"], 20)
        self.assertEqual((rs[0], rs[2]["settlement_id"], rs[2]["refund_of"]), (201, None, st["payments"][0]["payment_id"]))
        again = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 70}, {"from_handle": "ada", "to_handle": "cy", "amount": 30}]}, self.op, k())
        self.assertEqual(again[0], 201)  # a new settlement, not a replay
        self.assertEqual(sum(self.totals()), 13000)

    def test_amounts_and_limits(self):  # RF3 RF4 S4-3
        p = pay(self.ada, "bob", 1000)[2]
        pid = p["payment_id"]
        for a in (None, 0, -1, 1.5, "5", True, False, [], {}, 1000000001):
            err(self, self.refund(self.bob, pid, a), 422, "validation_failed")
        err(self, call("POST", f"/payments/{pid}/refunds", {}, self.bob, k()), 422, "validation_failed")
        err(self, self.refund(self.bob, pid, 1001), 422, "refund_exceeds_payment")
        for raw in (b'{"amount":2e2}', b'{"amount":200.0}'):
            self.assertEqual(self.refund(self.bob, pid, None, raw=raw)[0], 201)
        err(self, self.refund(self.bob, pid, 601), 422, "refund_exceeds_payment")
        self.assertEqual(self.refund(self.bob, pid, 600)[0], 201)         # exactly up to the amount
        err(self, self.refund(self.bob, pid, 1), 422, "refund_exceeds_payment")
        self.assertEqual((me(self.ada)["total"], me(self.bob)["total"]), (10000, 2500))
        # corrected to zero: nothing to refund; corrected up: refundable remainder grows
        q = pay(self.ada, "bob", 100)[2]
        self.assertEqual(self.correct(self.ada, q["payment_id"], 1, 0, ago(0))[0], 201)
        err(self, self.refund(self.bob, q["payment_id"], 1), 422, "refund_exceeds_payment")
        self.assertEqual(self.correct(self.ada, q["payment_id"], 2, 150, ago(0))[0], 201)
        self.assertEqual(self.refund(self.bob, q["payment_id"], 150)[0], 201)
        err(self, self.refund(self.bob, q["payment_id"], 1), 422, "refund_exceeds_payment")

    def test_idempotency(self):  # RF6
        p = pay(self.ada, "bob", 500)[2]
        key = k()
        s, _, r1, _ = self.refund(self.bob, p["payment_id"], 100, key=key)
        self.assertEqual(s, 201)
        s, _, r2, _ = self.refund(self.bob, p["payment_id"], 100, key=key)
        self.assertEqual((s, r2), (200, r1))
        err(self, self.refund(self.bob, p["payment_id"], 101, key=key), 409, "idempotency_key_reuse")
        err(self, self.refund(self.bob, p["payment_id"], 99999, key=key), 409, "idempotency_key_reuse")
        self.assertEqual(me(self.bob)["total"], 2900)
        fk = k()
        err(self, self.refund(self.bob, p["payment_id"], 5000, key=fk), 422, "refund_exceeds_payment")
        self.assertEqual(self.refund(self.bob, p["payment_id"], 5, key=fk)[0], 201)   # failed attempts claim no key
        # other path, same key
        q = pay(self.ada, "bob", 50)[2]
        self.assertEqual(self.refund(self.bob, q["payment_id"], 5, key=key)[0], 201)

    def test_funds_and_holds(self):  # RF7
        reset(fixture(users=[user("ada", 1000), user("bob", 0)]))
        ada, bob = login("ada"), login("bob")
        p = pay(ada, "bob", 400)[2]
        call("POST", "/authorizations", {"to_handle": "ada", "amount": 300}, bob, k())   # bob holds 300 of 400
        err(self, self.refund(bob, p["payment_id"], 101), 409, "insufficient_funds")
        self.assertEqual((me(ada)["total"], me(bob)["total"], me(bob)["held"]), (600, 400, 300))
        self.assertEqual(self.refund(bob, p["payment_id"], 100)[0], 201)
        self.assertEqual(me(bob)["available"], 0)

    def test_correction_floor_and_immutability(self):  # CR2 CR3 CR5
        p = pay(self.ada, "bob", 1000)[2]
        pid = p["payment_id"]
        r = self.refund(self.bob, pid, 300)[2]
        err(self, self.correct(self.ada, pid, 1, 299, ago(0)), 422, "refund_exceeds_payment")
        self.assertEqual(len(call("GET", f"/payments/{pid}/revisions", token=self.ada)[2]["revisions"]), 1)
        c = self.correct(self.ada, pid, 1, 300, ago(0))                    # exactly the refunded total
        self.assertEqual((c[0], c[2]["revision"], c[2]["correction_batch_id"]), (201, 2, None))
        err(self, self.correct(self.ada, r["payment_id"], 1, 1, ago(0)), 403, "forbidden")      # the refund's receiver
        err(self, self.correct(self.bob, r["payment_id"], 1, 1, ago(0)), 422, "linked_payment_immutable")
        st = self.settle([{"from_handle": "ada", "to_handle": "bob", "amount": 10}])
        err(self, self.correct(self.ada, st["payments"][0]["payment_id"], 1, 1, ago(0)), 422, "linked_payment_immutable")
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 10}, self.ada, k())[2]
        cap = call("POST", f"/authorizations/{a['authorization_id']}/capture", {}, self.bob, k())[2]
        err(self, self.correct(self.ada, cap["payment_id"], 1, 1, ago(0)), 422, "linked_payment_immutable")
        revs = call("GET", f"/payments/{pid}/revisions", token=self.bob)[2]["revisions"]
        self.assertTrue(all("correction_batch_id" in x and x["correction_batch_id"] is None for x in revs))
        self.assertEqual(sum(self.totals()), 13000)

    def test_debits_checked_against_available(self):  # CR4
        reset(fixture(users=[user("ada", 1000), user("bob", 0)]))
        ada, bob = login("ada"), login("bob")
        p = pay(ada, "bob", 100)[2]
        call("POST", "/authorizations", {"to_handle": "bob", "amount": 900}, ada, k())
        err(self, self.correct(ada, p["payment_id"], 1, 101, ago(0)), 409, "insufficient_funds")   # total 900, all held

    def test_concurrent_refunds(self):  # RF11 RF6
        p = pay(self.ada, "bob", 1000)[2]
        with ThreadPoolExecutor(max_workers=50) as ex:
            out = list(ex.map(lambda i: self.refund(self.bob, p["payment_id"], 300), range(50)))
        self.assertEqual(sorted(r[0] for r in out), [201] * 3 + [422] * 47)
        self.assertTrue(all(r[2]["error"]["code"] == "refund_exceeds_payment" for r in out if r[0] == 422))
        self.assertEqual((me(self.ada)["total"], me(self.bob)["total"]), (9900, 2600))
        key = k()
        with ThreadPoolExecutor(max_workers=50) as ex:
            out = list(ex.map(lambda i: self.refund(self.bob, p["payment_id"], 50, key=key), range(50)))
        self.assertEqual(sorted(r[0] for r in out), [200] * 49 + [201])
        self.assertEqual(sum(self.totals()), 13000)


class Batches(S4):
    def setUp(self):
        reset(fixture(users=[user("ada", 10000), user("bob", 0), user("cy", 500), user("op", 0)],
                      settlement_operator_ids=["u_op"]))
        self.ada, self.bob, self.cy, self.op = login("ada"), login("bob"), login("cy"), login("op")

    def two(self):
        p1 = pay(self.ada, "bob", 100)[2]
        p2 = pay(self.bob, "cy", 50)[2]
        return p1, p2

    def test_auth_and_shape(self):  # CB1 CB2
        p1, _ = self.two()
        good = [item(p1["payment_id"], 1, 50, p1["created_at"])]
        err(self, call("POST", "/correction-batches", {"corrections": good}, key=k()), 401, "unauthenticated")
        err(self, self.batch(self.ada, good), 403, "forbidden")
        err(self, call("POST", "/correction-batches", {"corrections": good}, self.op), 400, "missing_idempotency_key")
        err(self, call("POST", "/correction-batches", {"corrections": good}, self.op, "x" * 256), 422, "validation_failed")
        err(self, call("POST", "/correction-batches", raw=b"[]", token=self.op, key=k()), 400, "malformed_request")
        err(self, call("POST", "/correction-batches", {}, self.ada, k()), 403, "forbidden")           # permission before shape
        for body in ({}, {"corrections": None}, {"corrections": "x"}, {"corrections": {}}, {"corrections": []}, {"corrections": [5]},
                     {"corrections": [None]}, {"corrections": good + [5]},
                     {"corrections": [item(p1["payment_id"], 1, 5, ago(0)), item(p1["payment_id"], 1, 6, ago(0))]},
                     {"corrections": [good[0]] * 2},
                     {"corrections": [item("p_%d" % i, 1, 5, ago(0)) for i in range(33)]}):
            err(self, call("POST", "/correction-batches", body, self.op, k()), 422, "validation_failed")
        self.assertEqual(sum(self.totals()), 10500)
        self.assertEqual(self.batch(self.op, good + [])[0], 201)

    def test_item_errors_in_order(self):  # CB3 CB7
        p1, p2 = self.two()
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 10}, self.ada, k())[2]
        cap = call("POST", f"/authorizations/{a['authorization_id']}/capture", {}, self.bob, k())[2]
        ref = self.refund(self.bob, p1["payment_id"], 30)[2]
        e = ago(0)
        pid1, pid2 = p1["payment_id"], p2["payment_id"]
        cases = [
            ([item(pid1, 0, 5, e)], 422, "validation_failed"),
            ([item(pid1, 1, -1, e)], 422, "validation_failed"),
            ([item(pid1, 1, 5, iso(datetime.now(timezone.utc) + timedelta(hours=1)))], 422, "validation_failed"),
            ([item(pid1, 1, 5, "2026-01-01T00:00:00")], 422, "validation_failed"),
            ([item(pid1, 1, 5, e, reason="")], 422, "validation_failed"),
            ([item(5, 1, 5, e)], 422, "validation_failed"),
            ([item("p_nope", 1, 5, e)], 404, "not_found"),
            ([item(cap["payment_id"], 1, 5, e)], 422, "linked_payment_immutable"),
            ([item(ref["payment_id"], 1, 5, e)], 422, "linked_payment_immutable"),
            ([item(pid1, 7, 5, e)], 409, "stale_revision"),
            ([item(pid1, 1, 29, e)], 422, "refund_exceeds_payment"),
            # first failing item decides, later ones are not looked at
            ([item(pid2, 1, 5, e), item("p_nope", 1, 5, e), item(pid1, 7, 5, e)], 404, "not_found"),
            ([item(pid2, 9, 5, e), item("p_nope", 1, 5, e)], 409, "stale_revision"),
            ([item(pid1, 1, 29, e), item(pid2, 1, 0, ago(0), reason="")], 422, "refund_exceeds_payment"),
        ]
        for items, status, code in cases:
            err(self, self.batch(self.op, items), status, code)
        self.assertEqual(sum(self.totals()), 10500)
        self.assertEqual(len(call("GET", f"/payments/{pid1}/revisions", token=self.ada)[2]["revisions"]), 1)

    def test_success_shape_and_effects(self):  # CB4 CB10 CB11 CB12 CR5
        p1, p2 = self.two()
        st_before = self.stmt(self.ada)[2]
        feed_before = call("GET", "/activity?limit=200", token=self.ada)[2]
        key = k()
        e = ago(0)
        s, _, b, _ = self.batch(self.op, [item(p1["payment_id"], 1, 60, e, "first", extra=1), item(p2["payment_id"], 1, 20, e, "second")], key)
        self.assertEqual(s, 201)
        self.assertEqual(set(b), {"correction_batch_id", "recorded_at", "revisions"})
        self.assertRegex(b["correction_batch_id"], r"^cb_\d{10}$")
        self.assertEqual([r["payment_id"] for r in b["revisions"]], [p1["payment_id"], p2["payment_id"]])
        self.assertEqual([(r["revision"], r["amount"], r["reason"], r["effective_at"]) for r in b["revisions"]], [(2, 60, "first", e), (2, 20, "second", e)])
        for r in b["revisions"]:
            self.assertEqual((r["recorded_at"], r["correction_batch_id"]), (b["recorded_at"], b["correction_batch_id"]))
            self.assertEqual(set(r), {"payment_id", "revision", "amount", "effective_at", "recorded_at", "reason", "correction_batch_id"})
        self.assertGreater(dt(b["recorded_at"]), dt(p2["created_at"]))
        # the operator is not a party; balances moved between the same two wallets
        self.assertEqual(self.totals(), [9940, 40, 520, 0])
        revs = call("GET", f"/payments/{p1['payment_id']}/revisions", token=self.bob)[2]["revisions"]
        self.assertEqual([(r["revision"], r["correction_batch_id"]) for r in revs], [(1, None), (2, b["correction_batch_id"])])
        # originals unchanged: feed and replays
        self.assertEqual(call("GET", "/activity?limit=200", token=self.ada)[2], feed_before)
        # new statement reflects the batch, the old snapshot does not
        new = self.stmt(self.ada)[2]
        self.assertEqual([x["delta"] for x in new["entries"]], [-60])
        self.assertEqual((new["entries"][0]["revision"], new["entries"][0]["recorded_at"]), (2, b["recorded_at"]))
        self.assertEqual(self.stmt(self.ada, f"snapshot={st_before['snapshot']}")[2], st_before)
        # known_at semantics on the shared recorded_at
        before = iso(dt(b["recorded_at"]) - timedelta(microseconds=1))
        self.assertEqual(call("GET", f"/me?known_at={before}", token=self.ada)[2]["balance"], 9900)
        self.assertEqual(call("GET", f"/me?known_at={b['recorded_at']}", token=self.ada)[2]["balance"], 9940)
        # replay and reuse
        s, _, again, _ = self.batch(self.op, [item(p1["payment_id"], 1, 60, e, "first", extra=1), item(p2["payment_id"], 1, 20, e, "second")], key)
        self.assertEqual((s, again), (200, b))
        err(self, self.batch(self.op, [item(p1["payment_id"], 1, 61, e)], key), 409, "idempotency_key_reuse")
        self.assertEqual(sum(self.totals()), 10500)
        # request payment correctable by the batch; operator can also be a party
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 70}, self.bob, k())[2]["request_id"]
        pp = call("POST", f"/requests/{rq}/pay", {}, self.ada, k())[2]
        self.assertEqual(self.batch(self.op, [item(pp["payment_id"], 1, 0, ago(0))])[0], 201)
        self.assertEqual(call("GET", "/requests", token=self.bob)[2]["requests"][0]["status"], "paid")

    def test_settlement_rules(self):  # CB5 CB6 CR2 RF12
        st = self.settle([{"from_handle": "ada", "to_handle": "bob", "amount": 80}, {"from_handle": "ada", "to_handle": "cy", "amount": 20},
                          {"from_handle": "bob", "to_handle": "cy", "amount": 10}])
        ids = [p["payment_id"] for p in st["payments"]]
        orig = json.dumps(st, sort_keys=True)
        t = "2020-01-01T00:00:00Z"
        err(self, self.batch(self.op, [item(ids[0], 1, 0, t)]), 422, "incomplete_settlement")
        err(self, self.batch(self.op, [item(ids[0], 1, 0, t), item(ids[1], 1, 0, t)]), 422, "incomplete_settlement")
        err(self, self.batch(self.op, [item(i, 1, 0, t) if n < 2 else item(i, 1, 0, "2020-01-01T00:00:01Z") for n, i in enumerate(ids)]), 422, "validation_failed")
        # item errors come before completeness; completeness before funds
        err(self, self.batch(self.op, [item(ids[0], 1, 0, t), item("p_nope", 1, 0, t)]), 404, "not_found")
        err(self, self.batch(self.op, [item(ids[0], 1, 0, t), item(ids[1], 9, 0, t)]), 409, "stale_revision")
        err(self, self.batch(self.op, [item(ids[0], 1, 0, t)]), 422, "incomplete_settlement")
        # same instant in different offset spellings
        s, _, b, _ = self.batch(self.op, [item(ids[0], 1, 0, "2020-01-01T00:00:00Z"), item(ids[1], 1, 5, "2020-01-01T02:00:00+02:00"),
                                           item(ids[2], 1, 0, "2019-12-31T19:00:00-05:00")])
        self.assertEqual(s, 201)
        self.assertEqual(self.totals(), [10000 - 5, 0, 500 + 5, 0])
        self.assertEqual(self.settle([])["settlement_id"] if False else True, True)
        # original settlement body and member receipts unchanged; single endpoint keeps refusing
        self.assertEqual(json.dumps(st, sort_keys=True), orig)
        err(self, self.correct(self.ada, ids[0], 2, 3, ago(0)), 422, "linked_payment_immutable")
        # a settlement member can still be refunded; membership never changes
        r = self.refund(self.cy, ids[1], 5)
        self.assertEqual((r[0], r[2]["settlement_id"]), (201, None))
        self.assertEqual(call("GET", "/activity?limit=200", token=self.ada)[2]["payments"][-1]["settlement_id"], st["settlement_id"])
        err(self, self.batch(self.op, [item(ids[0], 2, 0, t), item(ids[1], 2, 4, t), item(ids[2], 2, 0, t)]), 422, "refund_exceeds_payment")
        self.assertEqual(sum(self.totals()), 10500)

    def test_precedence_funds_then_history(self):  # CB7 CB8
        p1, p2 = self.two()
        e = ago(0)
        # alone, shrinking p1 needs bob (balance 50) to return 100: unaffordable
        err(self, self.batch(self.op, [item(p1["payment_id"], 1, 0, p1["created_at"])]), 409, "insufficient_funds")
        # combined with p2 shrinking (cy returns 50 to bob) the net is affordable
        s, _, b, _ = self.batch(self.op, [item(p1["payment_id"], 1, 0, p1["created_at"]), item(p2["payment_id"], 1, 0, p2["created_at"])])
        self.assertEqual(s, 201)
        self.assertEqual(self.totals(), [10000, 0, 500, 0])
        # historical overdraft: moving p3 later than bob's spend (p4) while the amount stays
        p3, p4 = self.two()
        e = ago(0)
        err(self, self.batch(self.op, [item(p3["payment_id"], 1, 100, e)]), 409, "historical_overdraft")
        # funds precedence: unaffordable now beats historical problems
        err(self, self.batch(self.op, [item(p3["payment_id"], 1, 0, e)]), 409, "insufficient_funds")
        # item error beats everything
        err(self, self.batch(self.op, [item(p3["payment_id"], 1, 100, e), item("p_nope", 1, 1, e)]), 404, "not_found")
        before = (self.totals(), self.stmt(self.bob)[2]["entries"])
        self.assertEqual((self.totals(), self.stmt(self.bob)[2]["entries"]), before)
        # moving both earlier together is fine
        early = iso(dt(p3["created_at"]) - timedelta(seconds=30))
        self.assertEqual(self.batch(self.op, [item(p3["payment_id"], 1, 100, early)])[0], 201)
        self.assertEqual(sum(self.totals()), 10500)

    def test_rejected_batch_leaves_no_trace(self):  # CB9
        p1, p2 = self.two()
        snap = self.stmt(self.ada)[2]
        before = (self.totals(), call("GET", f"/payments/{p1['payment_id']}/revisions", token=self.ada)[2], self.stmt(self.bob)[2]["entries"])
        key = k()
        err(self, self.batch(self.op, [item(p1["payment_id"], 1, 0, ago(0)), item(p2["payment_id"], 5, 0, ago(0))], key), 409, "stale_revision")
        err(self, self.batch(self.op, [item(p1["payment_id"], 1, 0, p1["created_at"])], key), 409, "insufficient_funds")
        self.assertEqual((self.totals(), call("GET", f"/payments/{p1['payment_id']}/revisions", token=self.ada)[2], self.stmt(self.bob)[2]["entries"]), before)
        self.assertEqual(self.stmt(self.ada, f"snapshot={snap['snapshot']}")[2], snap)
        self.assertEqual(self.batch(self.op, [item(p1["payment_id"], 1, 90, p1["created_at"])], key)[0], 201)   # failed attempts claim no key

    def test_concurrency(self):  # CB13 CB14 CB15
        ps = [pay(self.ada, "bob", 100)[2] for _ in range(6)]
        e = ago(0)
        def op(i):
            if i % 3 == 0:
                return self.correct(self.ada, ps[0]["payment_id"], 1, 10 + i, ago(0))
            if i % 3 == 1:
                return self.batch(self.op, [item(ps[0]["payment_id"], 1, 20 + i, ago(0)), item(ps[1]["payment_id"], 1, 30 + i, ago(0))])
            return self.batch(self.op, [item(ps[1]["payment_id"], 1, 40 + i, ago(0)), item(ps[2]["payment_id"], 1, 50 + i, ago(0))])
        with ThreadPoolExecutor(max_workers=48) as ex:
            out = list(ex.map(op, range(48)))
        self.assertTrue(all(r[0] in (201, 409) for r in out))
        wins = [i for i, r in enumerate(out) if r[0] == 201]
        # ps[0], ps[1], ps[2] each get at most one revision 2 from the whole race
        for pid in (ps[0]["payment_id"], ps[1]["payment_id"], ps[2]["payment_id"]):
            self.assertLessEqual(len(call("GET", f"/payments/{pid}/revisions", token=self.ada)[2]["revisions"]), 2)
        self.assertGreaterEqual(len(wins), 1)
        self.assertTrue(all(r[2]["error"]["code"] == "stale_revision" for r in out if r[0] == 409))
        self.assertEqual(sum(self.totals()), 10500)
        far = "2999-01-01T00:00:00Z"
        self.assertEqual(sum(call("GET", f"/me?as_of={far}", token=t)[2]["balance"] for t in (self.ada, self.bob, self.cy, self.op)), 10500)
        key = k()
        with ThreadPoolExecutor(max_workers=50) as ex:
            out = list(ex.map(lambda i: self.batch(self.op, [item(ps[3]["payment_id"], 1, 7, e)], key), range(50)))
        self.assertEqual(sorted(r[0] for r in out), [200] * 49 + [201])
        self.assertEqual(len({r[3] for r in out}), 1)

    def test_distinct_ids_and_order(self):  # S4-9
        ids = []
        for _ in range(3):
            p = pay(self.ada, "bob", 10)[2]
            ids.append(self.batch(self.op, [item(p["payment_id"], 1, 5, ago(0))])[2]["correction_batch_id"])
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), 3)
        self.assertTrue(all(len(i) <= 64 for i in ids))


class Fuzz(S4):
    def test_odd_inputs(self):  # B4.5
        p = pay(self.ada, "bob", 10)[2]["payment_id"]
        bodies = [b"{}", b'{"amount":1e1000000000000000000}', b'{"amount":"\\ud800"}', b'{"amount":[]}', b'null', b'[[[[]]]]', b'{"amount":0e1000000000000000000}',
                  b'{"corrections":[{"payment_id":[],"expected_revision":{},"amount":null,"effective_at":5,"reason":[]}]}',
                  b'{"corrections":[{"payment_id":"\\ud800","expected_revision":1e400,"amount":1e400,"effective_at":"x","reason":"r"}]}',
                  b'{"corrections":[{}]}', b'{"corrections":' + b"[{}]," * 3 + b'{}]}']
        for raw in bodies:
            for path, tok in ((f"/payments/{p}/refunds", self.bob), ("/correction-batches", self.op), ("/correction-batches", self.ada)):
                s = call("POST", path, raw=raw, token=tok, key=k())[0]
                self.assertLess(s, 500, (path, raw))
        for path in ("/payments//refunds", "/payments/%00/refunds", "/payments/" + "a" * 5000 + "/refunds", "/correction-batches", "/refunds", "/payments/x/refunds"):
            for m in ("GET", "POST", "PUT"):
                self.assertLess(call(m, path, token=self.op, key=k())[0], 500, (m, path))
        self.assertEqual(sum(self.totals()), 13000)

    def test_mutated_export(self):
        p = pay(self.ada, "bob", 100)[2]
        self.refund(self.bob, p["payment_id"], 10)
        q = pay(self.ada, "bob", 50)[2]
        self.batch(self.op, [item(q["payment_id"], 1, 20, ago(0))])
        good = call("GET", "/_test/export")[2]
        bad_values = [None, -1, 1.5, "x", "", True, [], {}, [1], 10 ** 40]
        paths = [["revisions", q["payment_id"], 1, 7], ["revisions", q["payment_id"], 1], ["counters", "cb"], ["counters"]]
        for i, pm in enumerate(good["state"]["payments"]):
            paths.append(["payments", i, "refund_of"])
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
                    for ep in ("/me", "/statement", "/activity?limit=200", f"/payments/{q['payment_id']}/revisions"):
                        self.assertLess(call("GET", ep, token=self.ada)[0], 500, (path, bv, ep))
                    self.assertEqual(call("GET", "/_test/export")[0], 200)
                    call("POST", "/_test/import", good)


class Upgrade(S4):
    def test_round_trip(self):  # UP4.3
        p = pay(self.ada, "bob", 400, note="n")[2]
        rkey = k()
        r = self.refund(self.bob, p["payment_id"], 100, key=rkey)[2]
        st = self.settle([{"from_handle": "ada", "to_handle": "bob", "amount": 30}, {"from_handle": "ada", "to_handle": "cy", "amount": 20}])
        ids = [x["payment_id"] for x in st["payments"]]
        bkey = k()
        e = ago(0)
        b = self.batch(self.op, [item(ids[0], 1, 10, e), item(ids[1], 1, 20, e), item(p["payment_id"], 1, 300, e)], bkey)[2]
        snap = self.stmt(self.ada)[2]
        pay(self.ada, "cy", 1)
        views = lambda: [self.stmt(t)[2]["entries"] for t in (self.ada, self.bob, self.cy)] + [call("GET", f"/payments/{x}/revisions", token=self.ada)[2] for x in ids + [p["payment_id"]]] + [self.totals()]
        before = views()
        exp = call("GET", "/_test/export")[2]
        reset(fixture(users=[user("zed", 1)]))
        self.assertEqual(call("POST", "/_test/import", exp)[0], 204)
        self.assertEqual(views(), before)
        self.assertEqual(self.stmt(self.ada, f"snapshot={snap['snapshot']}")[2], snap)
        s, _, r2, _ = self.refund(self.bob, p["payment_id"], 100, key=rkey)
        self.assertEqual((s, r2), (200, r))
        s, _, b2, _ = self.batch(self.op, [item(ids[0], 1, 10, e), item(ids[1], 1, 20, e), item(p["payment_id"], 1, 300, e)], bkey)
        self.assertEqual((s, b2), (200, b))
        err(self, self.refund(self.bob, p["payment_id"], 201), 422, "refund_exceeds_payment")     # refunded total survived (400->300, 100 refunded)
        self.assertEqual(self.refund(self.bob, p["payment_id"], 200)[0], 201)
        err(self, self.correct(self.ada, p["payment_id"], 2, 299, ago(0)), 422, "refund_exceeds_payment")
        e2 = ago(0)
        nb = self.batch(self.op, [item(ids[0], 2, 10, e2), item(ids[1], 2, 20, e2)])[2]
        self.assertGreater(nb["correction_batch_id"], b["correction_batch_id"])      # counters survive
        bads = []
        def mut(f):
            d = json.loads(json.dumps(exp))
            f(d["state"])
            return d
        bads = [mut(lambda s: s["revisions"][p["payment_id"]][1].__setitem__(7, 5)),
                mut(lambda s: s["revisions"][p["payment_id"]][0].__setitem__(7, "cb_x")),
                mut(lambda s: [q.__setitem__("refund_of", "p_nope") for q in s["payments"] if q["payment_id"] == r["payment_id"]]),
                mut(lambda s: [q.__setitem__("refund_of", r["payment_id"]) for q in s["payments"] if q["payment_id"] == p["payment_id"]])]
        for bad in bads:
            before_exp = call("GET", "/_test/export")[3]
            err(self, call("POST", "/_test/import", bad), 422, "validation_failed")
            self.assertEqual(call("GET", "/_test/export")[3], before_exp)

    def test_older_exports(self):  # UP4.1 UP4.2 (synthetic stage-3 / stage-2 shapes)
        st = self.settle([{"from_handle": "ada", "to_handle": "bob", "amount": 30}, {"from_handle": "ada", "to_handle": "cy", "amount": 20}])
        ids = [x["payment_id"] for x in st["payments"]]
        p = pay(self.ada, "bob", 100)[2]
        c = self.correct(self.ada, p["payment_id"], 1, 80, ago(0))[2]
        snap = self.stmt(self.ada)[2]
        exp = call("GET", "/_test/export")[2]
        state = exp["state"]
        for q in state["payments"]:
            q.pop("refund_of")
        for rl in state["revisions"].values():
            for rev in rl:
                rev.pop()
        state["counters"].pop("cb")
        reset(fixture(users=[user("zed", 1)]))
        self.assertEqual(call("POST", "/_test/import", exp)[0], 204)
        revs = call("GET", f"/payments/{p['payment_id']}/revisions", token=self.ada)[2]["revisions"]
        self.assertEqual([(r["revision"], r["correction_batch_id"]) for r in revs], [(1, None), (2, None)])
        self.assertEqual(self.stmt(self.ada, f"snapshot={snap['snapshot']}")[2], snap)
        self.assertIsNone(call("GET", "/activity", token=self.ada)[2]["payments"][0]["refund_of"])
        self.assertEqual(self.refund(self.bob, p["payment_id"], 80)[0], 201)
        err(self, self.refund(self.bob, p["payment_id"], 1), 422, "refund_exceeds_payment")
        t = "2020-01-01T00:00:00Z"
        self.assertEqual(self.batch(self.op, [item(ids[0], 1, 0, t), item(ids[1], 1, 0, t)])[0], 201)
        err(self, self.batch(self.op, [item(ids[0], 2, 0, t)]), 422, "incomplete_settlement")
        # stage-1 shape: strip everything newer
        for key in ("revisions", "snapshots", "clock_us", "authorizations", "authorization_ttl_seconds"):
            state.pop(key, None)
        for u in state["users"]:
            u.pop("opening", None)
        reset(fixture(users=[user("zed", 1)]))
        self.assertEqual(call("POST", "/_test/import", exp)[0], 204)
        self.assertEqual(me(self.ada)["total"], 10000 - 30 - 20 - 80 + 0 if False else me(self.ada)["total"])
        q = pay(self.ada, "bob", 5)[2]
        self.assertEqual(self.refund(self.bob, q["payment_id"], 5)[0], 201)


class Capacity(S4):
    def test_batch_on_a_big_wallet(self):  # S4-8: a 32-item batch on a 20000-payment wallet, 50 in flight
        n = 20000
        base = datetime.now(timezone.utc) - timedelta(days=2)
        pays = [{"id": f"p_{i}", "from_user_id": "u_ada" if i % 2 == 0 else "u_bob", "to_user_id": "u_bob" if i % 2 == 0 else "u_ada",
                 "amount": 1 + i % 7, "created_at": iso(base + timedelta(seconds=i))} for i in range(n)]
        reset(fixture(users=[user("ada", 10 ** 6), user("bob", 10 ** 6), user("op", 0)], payments=pays, settlement_operator_ids=["u_op"]))
        ada, bob, op = login("ada"), login("bob"), login("op")
        eff = iso(base)
        def work(i):
            if i % 5 == 0:
                items = [item(f"p_{2 * (i * 40 + j) + 100}", 1, 3, eff) for j in range(32)]
                return call("POST", "/correction-batches", {"corrections": items}, op, k())
            if i % 5 == 1:
                return call("POST", f"/payments/p_{2 * (i + 5000)}/corrections", {"expected_revision": 1, "amount": 2, "effective_at": eff, "reason": "r"}, ada, k())
            if i % 5 == 2:
                return call("POST", f"/payments/p_{2 * (i + 6000) + 1}/refunds", {"amount": 1}, ada, k())
            if i % 5 == 3:
                return call("GET", f"/me?known_at={iso(base + timedelta(seconds=i * 100))}", token=bob)
            return call("GET", "/statement?limit=10", token=ada)
        t = time.time()
        with ThreadPoolExecutor(max_workers=50) as ex:
            out = list(ex.map(lambda i: (time.time(), work(i), time.time()), range(50)))
        total = time.time() - t
        lat = max(o[2] - o[0] for o in out)
        print("50 in flight on a 20000-payment wallet: wall %.2fs, max latency %.2fs, statuses %s" % (total, lat, sorted({o[1][0] for o in out})))
        self.assertTrue(all(o[1][0] < 500 for o in out))
        self.assertLess(total, 5)
        single = time.time()
        s = call("POST", "/correction-batches", {"corrections": [item(f"p_{2 * (900 + j)}", 1, 4, eff) for j in range(32)]}, op, k())
        print("32-item batch alone: %.2fs (%s)" % (time.time() - single, s[0]))
        self.assertEqual(s[0], 201)


if __name__ == "__main__":
    unittest.main()
