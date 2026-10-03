"""Rows AD-AH: refunds, correction batches, and import across stages."""
import json
import threading
from datetime import datetime, timedelta, timezone

from .base import ApiTestCase
from .support import Api, fixture, user

PAST = "2026-01-01T10:00:00+00:00"


def world(**extra):
    return fixture(users=[user("ada", 10000), user("bob", 2500), user("cy", 500), user("dee", 5000)],
                   settlement_operator_ids=["u_cy"], **extra)


class Base(ApiTestCase):
    def setUp(self):
        self.reset(world())

    def reset(self, fx):
        self.api.reset(fx)
        self.tok = {u["handle"]: self.api.login(u["email"]) for u in fx["users"]}

    def pay(self, who="ada", to="bob", amount=1000, key=None, **extra):
        s, b, _ = self.call("POST", "/payments", dict(to_handle=to, amount=amount, **extra), who=who,
                            key=key or "p-%s-%s-%d-%s" % (who, to, amount, len(self.api.call("GET", "/_test/export")[1]["state"]["payments"])))
        self.assertEqual(s, 201, b)
        return b

    def refund(self, pid, amount, who="bob", key=None):
        return self.call("POST", "/payments/%s/refunds" % pid, {"amount": amount}, who=who,
                         key=key or "r-%s-%s-%s" % (pid, amount, who))

    def corr(self, pid, rev, amount, eff=None, reason="fix", **extra):
        item = dict(payment_id=pid, expected_revision=rev, amount=amount, effective_at=eff or PAST, reason=reason)
        item.update(extra)
        return item

    def batch(self, items, who="cy", key=None, **extra):
        return self.call("POST", "/correction-batches", dict(corrections=items, **extra), who=who,
                         key=key or "b-%d" % len(json.dumps(items)) + str(hash(json.dumps(items, sort_keys=True))))

    def me(self, who, **q):
        qs = "&".join("%s=%s" % kv for kv in q.items())
        return self.api.call("GET", "/me" + ("?" + qs if qs else ""), token=self.tok[who])[1]

    def balances(self):
        return tuple(self.balance(w) for w in ("ada", "bob", "cy", "dee"))

    def settle(self, transfers, key="st"):
        s, b, _ = self.call("POST", "/settlements", {"transfers": transfers}, who="cy", key=key)
        self.assertEqual(s, 201, b)
        return b

    def revisions(self, pid, who="ada"):
        return self.call("GET", "/payments/%s/revisions" % pid, who=who)[1]["revisions"]


class RefundTests(Base):
    def test_basic_refund(self):
        p = self.pay()
        self.assertIsNone(p["refund_of"])
        s, r, _ = self.refund(p["payment_id"], 200)
        self.assertEqual(s, 201)
        self.assertEqual((r["refund_of"], r["from_handle"], r["to_handle"], r["amount"], r["request_id"],
                          r["authorization_id"], r["settlement_id"], r["note"], r["visibility"]),
                         (p["payment_id"], "bob", "ada", 200, None, None, None, "", "public"))
        self.assertNotEqual(r["payment_id"], p["payment_id"])
        self.assertEqual(self.balances(), (9200, 3300, 500, 5000))
        s, again, _ = self.refund(p["payment_id"], 200)
        self.assertEqual((s, again), (200, r))
        self.assertEqual(self.balances(), (9200, 3300, 500, 5000))

    def test_note_and_visibility_copied_and_feed(self):
        p = self.pay(note="dinner 😀", visibility="private")
        r = self.refund(p["payment_id"], 50)[1]
        self.assertEqual((r["note"], r["visibility"]), ("dinner 😀", "private"))
        feed = {x["payment_id"]: x for x in self.call("GET", "/activity", who="ada")[1]["payments"]}
        self.assertEqual(feed[r["payment_id"]]["refund_of"], p["payment_id"])
        self.assertEqual(self.call("GET", "/activity", who="dee")[1]["payments"], [])
        st = self.api.call("GET", "/statement", token=self.tok["ada"])[1]
        self.assertEqual([(e["payment"]["payment_id"], e["delta"], e["revision"]) for e in st["entries"]],
                         [(p["payment_id"], -1000, 1), (r["payment_id"], 50, 1)])
        self.assertEqual(st["entries"][1]["effective_at"], r["created_at"])
        self.assertEqual(st["closing_balance"], 9050)
        self.assertEqual(self.api.call("GET", "/statement", token=self.tok["bob"])[1]["entries"][1]["delta"], -50)

    def test_auth_and_targets(self):
        p = self.pay()
        self.assertEqual(self.api.call("POST", "/payments/%s/refunds" % p["payment_id"], {"amount": 1}, key="k")[0], 401)
        self.expect(404, "not_found", self.refund("nope", 1))
        self.expect(403, "forbidden", self.refund(p["payment_id"], 1, who="ada"))
        self.expect(403, "forbidden", self.refund(p["payment_id"], 1, who="cy"))
        r = self.refund(p["payment_id"], 100)[1]
        self.expect(422, "invalid_refund_target", self.refund(r["payment_id"], 1, who="ada"))
        self.expect(403, "forbidden", self.refund(r["payment_id"], 1, who="bob"))
        self.expect(400, "missing_idempotency_key", self.call("POST", "/payments/%s/refunds" % p["payment_id"], {"amount": 1}, who="bob"))

    def test_amount_matrix(self):
        p = self.pay(amount=1000)
        pid = p["payment_id"]
        for i, bad in enumerate((None, 0, -1, 1.5, "5", True, [], 1000000001)):
            body = {} if bad is None else {"amount": bad}
            self.expect(422, "validation_failed", self.call("POST", "/payments/%s/refunds" % pid, body, who="bob", key="bad%d" % i))
        self.expect(422, "validation_failed", self.call("POST", "/payments/%s/refunds" % pid, {"amount": None}, who="bob", key="n"))
        self.expect(400, "malformed_request", self.call("POST", "/payments/%s/refunds" % pid, who="bob", key="m", raw=b"[]"))
        for raw, key in ((b'{"amount":1}', "a"), (b'{"amount":200.0}', "b"), (b'{"amount":2e2}', "c")):
            self.assertEqual(self.call("POST", "/payments/%s/refunds" % pid, who="bob", key=key, raw=raw)[0], 201)
        self.assertEqual(self.balance("ada"), 10000 - 1000 + 401)

    def test_cumulative_limit_and_correction(self):
        p = self.pay(amount=1000)
        pid = p["payment_id"]
        self.assertEqual(self.refund(pid, 400)[0], 201)
        self.assertEqual(self.refund(pid, 599)[0], 201)
        self.expect(422, "refund_exceeds_payment", self.refund(pid, 2))
        self.assertEqual(self.refund(pid, 1)[0], 201)
        self.expect(422, "refund_exceeds_payment", self.refund(pid, 1, key="again"))
        # a correction cannot go below the refunded total (1000); any reduction fails
        s, b, _ = self.call("POST", "/payments/%s/corrections" % pid, dict(expected_revision=1, amount=999, effective_at=PAST, reason="x"), who="ada", key="c1")
        self.assertEqual((s, b["error"]["code"]), (422, "refund_exceeds_payment"))
        self.assertEqual(self.call("POST", "/payments/%s/corrections" % pid, dict(expected_revision=1, amount=1000, effective_at=PAST, reason="x"), who="ada", key="c2")[0], 201)
        self.assertEqual(self.call("POST", "/payments/%s/corrections" % pid, dict(expected_revision=2, amount=1200, effective_at=PAST, reason="up"), who="ada", key="c3")[0], 201)
        self.assertEqual(self.refund(pid, 200)[0], 201)       # the corrected amount is the limit
        self.expect(422, "refund_exceeds_payment", self.refund(pid, 1, key="z"))

    def test_correction_floor_exact(self):
        p = self.pay(amount=1000)
        pid = p["payment_id"]
        self.refund(pid, 300)
        c = lambda amount, key: self.call("POST", "/payments/%s/corrections" % pid, dict(expected_revision=1, amount=amount, effective_at=PAST, reason="x"), who="ada", key=key)
        self.assertEqual(c(299, "a")[0], 422)
        self.assertEqual(c(300, "b")[0], 201)
        # batch floor
        s, b, _ = self.batch([self.corr(pid, 2, 299)])
        self.assertEqual((s, b["error"]["code"]), (422, "refund_exceeds_payment"))

    def test_insufficient_and_holds(self):
        p = self.pay(amount=1000)                      # bob 3500
        self.call("POST", "/authorizations", {"to_handle": "cy", "amount": 3400}, who="bob", key="h")
        self.assertEqual(self.balances(), (9000, 3500, 500, 5000))
        before = self.me("bob")
        self.expect(409, "insufficient_funds", self.refund(p["payment_id"], 101))
        self.assertEqual(self.me("bob"), before)
        self.assertEqual(self.refund(p["payment_id"], 100)[0], 201)
        self.assertEqual(self.me("bob")["available"], 0)

    def test_all_payment_kinds_and_non_effects(self):
        rid = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, who="bob", key="rq")[1]["request_id"]
        rp = self.call("POST", "/requests/%s/pay" % rid, {}, who="ada", key="rqp")[1]
        r1 = self.refund(rp["payment_id"], 40)[1]
        self.assertEqual(r1["request_id"], None)
        self.assertEqual(self.call("GET", "/requests", who="ada")[1]["requests"][0]["status"], "paid")
        aid = self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 500}, who="ada", key="au")[1]["authorization_id"]
        cap = self.call("POST", "/authorizations/%s/capture" % aid, {"amount": 200}, who="bob", key="cp")[1]
        r2 = self.refund(cap["payment_id"], 50)[1]
        self.assertIsNone(r2["authorization_id"])
        a = self.call("GET", "/authorizations", who="ada")[1]["authorizations"][0]
        self.assertEqual((a["status"], a["remaining_amount"]), ("captured", 0))
        self.assertEqual(self.me("ada")["held"], 0)
        st = self.settle([{"from_handle": "dee", "to_handle": "ada", "amount": 300}])
        member = st["payments"][0]
        r3 = self.refund(member["payment_id"], 100, who="ada")[1]
        self.assertIsNone(r3["settlement_id"])
        again = self.call("POST", "/settlements", {"transfers": [{"from_handle": "dee", "to_handle": "ada", "amount": 300}]}, who="cy", key="st")
        self.assertEqual((again[0], again[1]), (200, st))
        self.assertEqual(len(self.db_settlement_members(st["settlement_id"])), 1)

    def db_settlement_members(self, sid):
        doc = self.api.call("GET", "/_test/export")[1]
        return [s for s in doc["state"]["settlements"] if s["settlement_id"] == sid][0]["payment_ids"]

    def test_refund_payments_are_immutable_for_corrections(self):
        p = self.pay()
        r = self.refund(p["payment_id"], 100)[1]
        s, b, _ = self.call("POST", "/payments/%s/corrections" % r["payment_id"], dict(expected_revision=1, amount=50, effective_at=PAST, reason="x"), who="bob", key="k")
        self.assertEqual((s, b["error"]["code"]), (422, "linked_payment_immutable"))
        s, b, _ = self.batch([self.corr(r["payment_id"], 1, 50)])
        self.assertEqual((s, b["error"]["code"]), (422, "linked_payment_immutable"))
        aid = self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 50}, who="ada", key="au")[1]["authorization_id"]
        cap = self.call("POST", "/authorizations/%s/capture" % aid, {}, who="bob", key="cp")[1]
        s, b, _ = self.batch([self.corr(cap["payment_id"], 1, 10)], key="cb2")
        self.assertEqual((s, b["error"]["code"]), (422, "linked_payment_immutable"))

    def test_concurrent_refunds_never_exceed(self):
        p = self.pay(amount=1000)
        res = []
        threads = [threading.Thread(target=lambda i=i: res.append(self.refund(p["payment_id"], 100, key="r%d" % i))) for i in range(20)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(r[0] for r in res), [201] * 10 + [422] * 10)
        self.assertEqual(self.balance("ada"), 10000)
        self.assertEqual(sum(self.balances()), 18000)

    def test_refund_vs_correction_race(self):
        for round_ in range(5):
            p = self.pay(amount=100 + round_)
            pid = p["payment_id"]
            out = {}
            t1 = threading.Thread(target=lambda: out.update(r=self.refund(pid, 60, key="rr")))
            t2 = threading.Thread(target=lambda: out.update(c=self.call("POST", "/payments/%s/corrections" % pid, dict(expected_revision=1, amount=30, effective_at=PAST, reason="x"), who="ada", key="cc")))
            t1.start(); t2.start(); t1.join(); t2.join()
            refunded = 60 if out["r"][0] == 201 else 0
            current = 30 if out["c"][0] == 201 else 100 + round_
            self.assertLessEqual(refunded, current)

    def test_idempotency_paths(self):
        p = self.pay()
        pid = p["payment_id"]
        self.assertEqual(self.refund(pid, 10, key="K")[0], 201)
        self.expect(409, "idempotency_key_reuse", self.refund(pid, 11, key="K"))
        self.expect(422, "validation_failed", self.refund(pid, 1, key="x" * 256))
        self.assertEqual(self.refund(pid, 1, key="x" * 255)[0], 201)
        self.expect(422, "validation_failed", self.refund(pid, 0, key="F"))
        self.assertEqual(self.refund(pid, 5, key="F")[0], 201)       # failed key reusable
        self.expect(409, "idempotency_key_reuse", self.refund(pid, 6, key="F"))
        p2 = self.pay(amount=300)
        self.assertEqual(self.refund(p2["payment_id"], 10, key="K")[0], 201)   # same key, other path
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.refund(pid, 7, key="conc"))) for _ in range(20)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(r[0] for r in results), [200] * 19 + [201])


class BatchBase(Base):
    def two_payments(self):
        return self.pay(amount=300), self.pay(amount=400, to="cy")


class BatchTests(BatchBase):
    def test_access_and_shape(self):
        p = self.pay()
        item = self.corr(p["payment_id"], 1, 900)
        self.assertEqual(self.api.call("POST", "/correction-batches", {"corrections": [item]}, key="k")[0], 401)
        self.expect(403, "forbidden", self.batch([item], who="ada"))
        self.expect(400, "missing_idempotency_key", self.call("POST", "/correction-batches", {"corrections": [item]}, who="cy"))
        self.expect(422, "validation_failed", self.call("POST", "/correction-batches", {"corrections": [item]}, who="cy", key="x" * 256))
        self.expect(400, "malformed_request", self.call("POST", "/correction-batches", who="cy", key="m", raw=b"[1]"))
        for i, bad in enumerate(({}, {"corrections": "x"}, {"corrections": []}, {"corrections": [1]}, {"corrections": {}},
                                 {"corrections": [item, item]}, {"corrections": [item] * 33})):
            self.expect(422, "validation_failed", self.call("POST", "/correction-batches", bad, who="cy", key="s%d" % i))
        s, b, _ = self.batch([dict(item, extra=1)], key="ok1", unknown=True)
        self.assertEqual(s, 201)

    def test_thirty_two_items(self):
        pays = [self.pay(amount=10 + i, key="m%d" % i) for i in range(32)]
        items = [self.corr(p["payment_id"], 1, 5) for p in pays]
        s, b, _ = self.batch(items, key="b32")
        self.assertEqual((s, len(b["revisions"])), (201, 32))
        self.assertEqual([r["payment_id"] for r in b["revisions"]], [p["payment_id"] for p in pays])
        self.expect(422, "validation_failed", self.batch(items + [self.corr(self.pay()["payment_id"], 1, 1)], key="b33"))

    def test_item_validation_and_lookup(self):
        p = self.pay()
        pid = p["payment_id"]
        base = self.corr(pid, 1, 900)
        bad = [{"payment_id": None}, {"payment_id": 5}, {"expected_revision": 0}, {"expected_revision": "1"}, {"amount": -1},
               {"amount": 1000000001}, {"amount": 1.5}, {"effective_at": "2026-01-01"}, {"reason": ""}, {"reason": "r" * 201},
               {"effective_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}]
        for i, change in enumerate(bad):
            self.expect(422, "validation_failed", self.batch([dict(base, **change)], key="v%d" % i))
        for name in ("payment_id", "expected_revision", "amount", "effective_at", "reason"):
            self.expect(422, "validation_failed", self.batch([{k: v for k, v in base.items() if k != name}], key="m" + name))
        self.expect(404, "not_found", self.batch([self.corr("ghost", 1, 5)], key="u"))
        self.expect(409, "stale_revision", self.batch([self.corr(pid, 2, 5)], key="st"))
        self.assertEqual(self.batch([self.corr(pid, 1, 1000000000 if False else 900)], key="fine")[0], 201)

    def test_success_shape_and_effects(self):
        a, b = self.two_payments()
        before = self.balances()
        s, body, _ = self.batch([self.corr(a["payment_id"], 1, 100), self.corr(b["payment_id"], 1, 0, "2026-01-01T12:00:00+02:00")], key="K")
        self.assertEqual(s, 201)
        self.assertEqual(set(body), {"correction_batch_id", "recorded_at", "revisions"})
        r1, r2 = body["revisions"]
        self.assertEqual((r1["payment_id"], r1["revision"], r1["amount"], r1["reason"], r1["correction_batch_id"]),
                         (a["payment_id"], 2, 100, "fix", body["correction_batch_id"]))
        self.assertEqual((r2["effective_at"], r2["amount"]), ("2026-01-01T12:00:00+02:00", 0))
        self.assertEqual({r1["recorded_at"], r2["recorded_at"]}, {body["recorded_at"]})
        for p in (a, b):
            prev = datetime.fromisoformat(self.revisions(p["payment_id"])[0]["recorded_at"])
            self.assertGreater(datetime.fromisoformat(body["recorded_at"]), prev)
        self.assertEqual(self.balances(), (before[0] + 200 + 400, before[1] - 200, before[2] - 400, before[3]))
        revs = self.revisions(a["payment_id"])
        self.assertEqual([(r["revision"], r["correction_batch_id"]) for r in revs], [(1, None), (2, body["correction_batch_id"])])
        s, again, _ = self.batch([self.corr(a["payment_id"], 1, 100), self.corr(b["payment_id"], 1, 0, "2026-01-01T12:00:00+02:00")], key="K")
        self.assertEqual((s, again), (200, body))
        single = self.call("POST", "/payments/%s/corrections" % a["payment_id"], dict(expected_revision=2, amount=50, effective_at=PAST, reason="s"), who="ada", key="s")[1]
        self.assertIsNone(single["correction_batch_id"])
        self.assertEqual(self.batch([self.corr(a["payment_id"], 1, 100), self.corr(b["payment_id"], 1, 0, "2026-01-01T12:00:00+02:00")], key="K")[:2], (200, body))
        self.expect(409, "idempotency_key_reuse", self.batch([self.corr(a["payment_id"], 1, 101)], key="K"))
        self.assertEqual(sum(self.balances()), 17500 + 500 + 0)

    def test_originals_unchanged_and_snapshots_frozen(self):
        a, b = self.two_payments()
        snap = self.api.call("GET", "/statement", token=self.tok["ada"])[1]
        s, replay, _ = self.call("POST", "/payments", {"to_handle": "bob", "amount": 300}, who="ada", key="p-ada-bob-300-0")
        self.batch([self.corr(a["payment_id"], 1, 100)], key="b1")
        feed = {x["payment_id"]: x["amount"] for x in self.call("GET", "/activity", who="ada")[1]["payments"]}
        self.assertEqual(feed[a["payment_id"]], 300)
        page = self.api.call("GET", "/statement?snapshot=" + snap["snapshot"], token=self.tok["ada"])[1]
        self.assertEqual(page["entries"], snap["entries"])
        new = self.api.call("GET", "/statement", token=self.tok["ada"])[1]
        self.assertEqual([(e["payment"]["amount"], e["revision"]) for e in new["entries"]], [(100, 2), (400, 1)])

    def test_operator_is_not_a_party_and_kinds(self):
        rid = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, who="bob", key="rq")[1]["request_id"]
        rp = self.call("POST", "/requests/%s/pay" % rid, {}, who="ada", key="rqp")[1]
        d = self.pay(amount=50)
        st = self.settle([{"from_handle": "dee", "to_handle": "ada", "amount": 70}])
        s, b, _ = self.batch([self.corr(rp["payment_id"], 1, 60), self.corr(d["payment_id"], 1, 40),
                              self.corr(st["payments"][0]["payment_id"], 1, 20)], key="all")
        self.assertEqual(s, 201, b)
        self.assertEqual(self.balance("dee"), 5000 - 20)

    def test_settlement_completeness_and_instants(self):
        st = self.settle([{"from_handle": "dee", "to_handle": "ada", "amount": 100}, {"from_handle": "ada", "to_handle": "bob", "amount": 30}])
        m1, m2 = [p["payment_id"] for p in st["payments"]]
        e = "2026-01-02T10:00:00+00:00"
        for items, key in (([self.corr(m1, 1, 50, e)], "i1"),):
            s, b, _ = self.batch(items, key=key)
            self.assertEqual((s, b["error"]["code"]), (422, "incomplete_settlement"))
        s, b, _ = self.batch([self.corr(m1, 1, 50, e), self.corr(m2, 1, 10, "2026-01-02T10:00:01+00:00")], key="i2")
        self.assertEqual((s, b["error"]["code"]), (422, "validation_failed"))
        s, b, _ = self.call("POST", "/payments/%s/corrections" % m1, dict(expected_revision=1, amount=50, effective_at=e, reason="x"), who="dee", key="single")
        self.assertEqual((s, b["error"]["code"]), (422, "linked_payment_immutable"))
        s, b, _ = self.batch([self.corr(m1, 1, 50, e), self.corr(m2, 1, 10, "2026-01-02T12:00:00+02:00")], key="i3")
        self.assertEqual(s, 201, b)
        self.assertEqual(self.balance("dee"), 5000 - 50)
        self.assertEqual(self.balance("bob"), 2500 + 10)
        replay = self.call("POST", "/settlements", {"transfers": [{"from_handle": "dee", "to_handle": "ada", "amount": 100}, {"from_handle": "ada", "to_handle": "bob", "amount": 30}]}, who="cy", key="st")
        self.assertEqual((replay[0], replay[1]), (200, st))

    def test_precedence(self):
        st = self.settle([{"from_handle": "dee", "to_handle": "ada", "amount": 100}, {"from_handle": "ada", "to_handle": "bob", "amount": 30}])
        m1 = st["payments"][0]["payment_id"]
        p = self.pay(amount=100)
        pid = p["payment_id"]
        # item errors (in input order) come before settlement completeness
        s, b, _ = self.batch([self.corr(m1, 1, 5), self.corr(pid, 7, 5)], key="a")
        self.assertEqual((s, b["error"]["code"]), (409, "stale_revision"))
        s, b, _ = self.batch([self.corr(pid, 7, 5), self.corr("ghost", 1, 5)], key="b")
        self.assertEqual((s, b["error"]["code"]), (409, "stale_revision"))
        s, b, _ = self.batch([self.corr("ghost", 1, 5), self.corr(pid, 7, 5)], key="c")
        self.assertEqual((s, b["error"]["code"]), (404, "not_found"))
        s, b, _ = self.batch([self.corr(pid, 1, 5, reason=""), self.corr("ghost", 1, 5)], key="d")
        self.assertEqual((s, b["error"]["code"]), (422, "validation_failed"))
        # settlement completeness before affordability
        s, b, _ = self.batch([self.corr(m1, 1, 100000)], key="e")
        self.assertEqual((s, b["error"]["code"]), (422, "incomplete_settlement"))

    def test_affordability_is_combined(self):
        a = self.pay(who="cy", to="bob", amount=100, key="c1")
        b2 = self.pay(who="cy", to="dee", amount=300, key="c2")      # cy 500 -> 100
        e = PAST
        s, body, _ = self.batch([self.corr(a["payment_id"], 1, 300, e)], key="x")   # cy would pay 200 more: has 100
        self.assertEqual((s, body["error"]["code"]), (409, "insufficient_funds"))
        s, body, _ = self.batch([self.corr(a["payment_id"], 1, 300, e), self.corr(b2["payment_id"], 1, 0, e)], key="y")   # offsetting
        self.assertEqual(s, 201, body)
        self.assertEqual(self.balance("cy"), 100 - 200 + 300)
        # and the reverse: each item affordable alone, the pair is not
        c = self.pay(who="cy", to="bob", amount=150, key="c3")
        d = self.pay(who="cy", to="dee", amount=30, key="c4")        # cy 200 -> 20
        s, body, _ = self.batch([self.corr(c["payment_id"], 1, 160, e), self.corr(d["payment_id"], 1, 40, e)], key="z")   # 10 + 10 > ... 20 ok? 
        self.assertEqual(s, 201, body)
        s, body, _ = self.batch([self.corr(c["payment_id"], 2, 170, e), self.corr(d["payment_id"], 2, 50, e)], key="w")   # 10 + 10 = 20 > 0 left
        self.assertEqual((s, body["error"]["code"]), (409, "insufficient_funds"))

    def test_historical_overdraft_and_rollback(self):
        self.reset(fixture(users=[user("ada", 1100), user("bob", 1500), user("cy", 400)], settlement_operator_ids=["u_cy"], payments=[
            {"id": "q0", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 500, "created_at": "2025-12-31T10:00:00+00:00"},
            {"id": "q1", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 400, "created_at": "2026-01-01T10:00:00+00:00"},
            {"id": "q2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1000, "created_at": "2026-01-02T10:00:00+00:00"}]))
        self.tok = {h: self.api.login(h + "@example.com") for h in ("ada", "bob", "cy")}
        before = self.api.call("GET", "/_test/export")[1]["state"]
        s, b, _ = self.batch([self.corr("q0", 1, 300, "2025-12-31T10:00:00+00:00")], key="H")
        self.assertEqual((s, b["error"]["code"]), (409, "historical_overdraft"))
        after = self.api.call("GET", "/_test/export")[1]["state"]
        self.assertEqual((before["payments"], before["users"]), (after["payments"], after["users"]))
        self.assertEqual(self.batch([self.corr("q0", 1, 900, "2025-12-31T10:00:00+00:00")], key="H")[0], 201)   # key reusable
        # current shortfall wins over history
        s, b, _ = self.batch([self.corr("q1", 1, 9000, "2026-01-01T10:00:00+00:00")], key="I")
        self.assertEqual((s, b["error"]["code"]), (409, "insufficient_funds"))

    def test_concurrent_batches_and_singles(self):
        p = self.pay(amount=500)
        pid = p["payment_id"]
        q = self.pay(amount=600, to="dee")
        res = []
        def go(i):
            if i % 2:
                res.append(self.batch([self.corr(pid, 1, 100 + i)], key="rb%d" % i))
            else:
                res.append(self.call("POST", "/payments/%s/corrections" % pid, dict(expected_revision=1, amount=200 + i, effective_at=PAST, reason="s"), who="ada", key="rs%d" % i))
        threads = [threading.Thread(target=go, args=(i,)) for i in range(16)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(r[0] for r in res).count(201), 1)
        self.assertEqual(len(self.revisions(pid)), 2)
        res.clear()
        threads = [threading.Thread(target=lambda i=i: res.append(self.batch([self.corr(pid, 2, 50 + i), self.corr(q["payment_id"], 1, 10 + i)], key="bb%d" % i))) for i in range(10)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(r[0] for r in res).count(201), 1)
        self.assertEqual(sum(self.balances()), 18000)
        for t in ("2025-01-01T00:00:00Z", "2030-01-01T00:00:00Z"):
            self.assertEqual(sum(self.me(w, as_of=t.replace("+", "%2B"))["balance"] for w in ("ada", "bob", "cy", "dee")), 18000)

    def test_refund_then_batch_floor(self):
        d = self.pay(amount=100)
        self.refund(d["payment_id"], 70)
        s, b, _ = self.batch([self.corr(d["payment_id"], 1, 69)], key="f")
        self.assertEqual((s, b["error"]["code"]), (422, "refund_exceeds_payment"))
        self.assertEqual(self.batch([self.corr(d["payment_id"], 1, 70)], key="g")[0], 201)


class ImportTests(BatchBase):
    def strip_to_stage3(self, doc):
        doc = json.loads(json.dumps(doc))
        for rec in doc["state"]["payments"]:
            rec["data"].pop("refund_of", None)
            for rev in rec["revs"]:
                rev.pop("correction_batch_id", None)
        return doc

    def test_stage3_export_imports(self):
        d = self.pay(amount=300)
        st = self.settle([{"from_handle": "dee", "to_handle": "ada", "amount": 100}, {"from_handle": "ada", "to_handle": "bob", "amount": 30}])
        self.call("POST", "/payments/%s/corrections" % d["payment_id"], dict(expected_revision=1, amount=250, effective_at=PAST, reason="s"), who="ada", key="c")
        snap = self.api.call("GET", "/statement", token=self.tok["ada"])[1]
        doc = self.strip_to_stage3(self.api.call("GET", "/_test/export")[1])
        other = Api()
        try:
            self.assertEqual(other.call("POST", "/_test/import", doc)[0], 204)
            t = self.tok["ada"]
            self.assertEqual(other.call("GET", "/statement?snapshot=" + snap["snapshot"], token=t)[1]["entries"][0]["delta"], snap["entries"][0]["delta"])
            payments = other.call("GET", "/activity", token=t)[1]["payments"]
            self.assertTrue(all(p["refund_of"] is None for p in payments))
            revs = other.call("GET", "/payments/%s/revisions" % d["payment_id"], token=t)[1]["revisions"]
            self.assertEqual([r["correction_batch_id"] for r in revs], [None, None])
            self.assertEqual(other.call("POST", "/payments/%s/refunds" % d["payment_id"], {"amount": 250}, token=self.tok["bob"], key="r")[0], 201)
            m1, m2 = [p["payment_id"] for p in st["payments"]]
            e = "2026-01-02T10:00:00+00:00"
            cy = self.tok["cy"]
            s, b, _ = other.call("POST", "/correction-batches", {"corrections": [self.corr(m1, 1, 50, e)]}, token=cy, key="x")
            self.assertEqual((s, b["error"]["code"]), (422, "incomplete_settlement"))
            s, b, _ = other.call("POST", "/correction-batches", {"corrections": [self.corr(m1, 1, 50, e), self.corr(m2, 1, 20, e)]}, token=cy, key="y")
            self.assertEqual(s, 201, b)
            self.assertEqual(other.call("POST", "/settlements", {"transfers": [{"from_handle": "dee", "to_handle": "ada", "amount": 100}, {"from_handle": "ada", "to_handle": "bob", "amount": 30}]}, token=cy, key="st")[1], st)
        finally:
            other.close()

    def test_stage4_round_trip(self):
        d = self.pay(amount=300)
        r = self.refund(d["payment_id"], 100)[1]
        s, b, _ = self.batch([self.corr(d["payment_id"], 1, 200)], key="bk")
        self.assertEqual(s, 201)
        snap = self.api.call("GET", "/statement", token=self.tok["ada"])[1]
        doc = self.api.call("GET", "/_test/export")[1]
        other = Api()
        try:
            self.assertEqual(other.call("POST", "/_test/import", doc)[0], 204)
            self.assertEqual(other.call("POST", "/correction-batches", {"corrections": [self.corr(d["payment_id"], 1, 200)]}, token=self.tok["cy"], key="bk")[:2], (200, b))
            self.assertEqual(other.call("POST", "/payments/%s/refunds" % d["payment_id"], {"amount": 100}, token=self.tok["bob"], key="r-%s-100-bob" % d["payment_id"])[:2], (200, r))
            self.assertEqual(other.call("POST", "/payments/%s/refunds" % d["payment_id"], {"amount": 101}, token=self.tok["bob"], key="over")[1]["error"]["code"], "refund_exceeds_payment")
            self.assertEqual(other.call("GET", "/statement?snapshot=" + snap["snapshot"], token=self.tok["ada"])[1]["entries"], snap["entries"])
            self.assertEqual(other.call("POST", "/payments/%s/corrections" % d["payment_id"], dict(expected_revision=2, amount=99, effective_at=PAST, reason="x"), token=self.tok["ada"], key="lo")[1]["error"]["code"], "refund_exceeds_payment")
            bad = json.loads(json.dumps(doc))
            bad["state"]["payments"][0]["data"]["refund_of"] = "no_such"
            self.assertEqual(other.call("POST", "/_test/import", bad)[0], 422)
        finally:
            other.close()
