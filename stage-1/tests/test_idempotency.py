"""Rows F: idempotency on all five write paths, plus settlements (I) and ordering (F10)."""
import threading

from .base import ApiTestCase
from .support import fixture, user

PATHS = {
    "payments": ("/payments", {"to_handle": "bob", "amount": 10}, "ada"),
    "requests": ("/requests", {"payer_handle": "ada", "amount": 10}, "bob"),
    "splits": ("/splits", {"amount": 10, "participant_handles": ["ada", "cy"]}, "bob"),
    "settlements": ("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]}, "ada"),
}


class IdempotencyTests(ApiTestCase):
    def setUp(self):
        self.reset(fixture(settlement_operator_ids=["u_ada"]))

    def test_replay_and_reuse_on_each_path(self):
        for name, (path, body, who) in PATHS.items():
            s1, b1, _ = self.call("POST", path, body, who=who, key="K-" + name)
            self.assertEqual(s1, 201, (name, b1))
            s2, b2, _ = self.call("POST", path, dict(reversed(list(body.items()))), who=who, key="K-" + name)
            self.assertEqual((s2, b2), (200, b1), name)
            other = dict(body, amount=11)
            self.expect(409, "idempotency_key_reuse", self.call("POST", path, other, who=who, key="K-" + name))
            self.expect(400, "missing_idempotency_key", self.call("POST", path, body, who=who))
            self.expect(400, "missing_idempotency_key", self.call("POST", path, body, who=who, key=""))
            self.expect(422, "validation_failed", self.call("POST", path, body, who=who, key="x" * 256))
            self.assertEqual(self.call("POST", path, body, who=who, key="x" * 255)[0], 201)
        self.assertEqual(self.balance("ada"), 10000 - 40)  # two payments and two settlement transfers out

    def test_pay_path_missing_and_length(self):
        rid = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, who="bob", key="r")[1]["request_id"]
        p = "/requests/%s/pay" % rid
        self.expect(400, "missing_idempotency_key", self.call("POST", p, {}, who="ada"))
        self.expect(422, "validation_failed", self.call("POST", p, {}, who="ada", key="y" * 256))
        self.assertEqual(self.call("POST", p, {}, who="ada", key="y" * 255)[0], 201)

    def test_pay_body_identity_and_other_path(self):
        r1 = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, who="bob", key="r1")[1]["request_id"]
        r2 = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 6}, who="bob", key="r2")[1]["request_id"]
        self.assertEqual(self.call("POST", "/requests/%s/pay" % r1, {}, who="ada", key="same")[0], 201)
        self.expect(409, "idempotency_key_reuse",
                    self.call("POST", "/requests/%s/pay" % r1, {"visibility": "public"}, who="ada", key="same"))
        s, b, _ = self.call("POST", "/requests/%s/pay" % r2, {}, who="ada", key="same")
        self.assertEqual((s, b["amount"]), (201, 6))

    def test_same_key_other_path_same_body(self):
        self.assertEqual(self.call("POST", "/payments", {"to_handle": "bob", "amount": 3}, who="ada", key="K")[0], 201)
        self.assertEqual(self.call("POST", "/requests", {"payer_handle": "bob", "amount": 3}, who="ada", key="K")[0], 201)

    def test_key_scoped_per_user(self):
        a = self.call("POST", "/payments", {"to_handle": "cy", "amount": 3}, who="ada", key="K")
        b = self.call("POST", "/payments", {"to_handle": "cy", "amount": 3}, who="bob", key="K")
        self.assertEqual((a[0], b[0]), (201, 201))
        self.assertNotEqual(a[1]["payment_id"], b[1]["payment_id"])

    def test_failed_key_reusable(self):
        self.expect(409, "insufficient_funds", self.pay("cy", "ada", 501, "K"))
        self.expect(422, "validation_failed", self.pay("cy", "ada", 0, "K"))
        self.api.call("POST", "/payments", {"to_handle": "cy", "amount": 100}, token=self.tok["bob"], key="topup")
        self.assertEqual(self.pay("cy", "ada", 501, "K")[0], 201)

    def test_replay_after_resource_changed(self):
        s, req, _ = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, who="bob", key="K")
        self.call("POST", "/requests/%s/cancel" % req["request_id"], who="bob")
        s, again, _ = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, who="bob", key="K")
        self.assertEqual((s, again["status"]), (200, "pending"))

    def test_claimed_key_precedes_validation_and_order(self):
        self.pay("ada", "bob", 5, "K")
        self.expect(409, "idempotency_key_reuse", self.pay("ada", "bob", "bad", "K"))
        self.expect(409, "idempotency_key_reuse", self.call("POST", "/payments", {"nonsense": 1}, who="ada", key="K"))
        # 401 before 400 body, body 400 before key 400, key 422 before validation
        self.expect(401, "unauthenticated", self.api.call("POST", "/payments", raw=b"{", key="K"))
        self.expect(400, "malformed_request", self.call("POST", "/payments", who="ada", raw=b"{"))
        self.expect(422, "validation_failed", self.call("POST", "/payments", {"amount": 0}, who="ada", key="k" * 300))

    def test_concurrent_identical_exactly_one_201(self):
        for name, (path, body, who) in PATHS.items():
            results = []

            def go():
                results.append(self.call("POST", path, body, who=who, key="C-" + name))
            threads = [threading.Thread(target=go) for _ in range(20)]
            [t.start() for t in threads]
            [t.join() for t in threads]
            self.assertEqual(sorted(r[0] for r in results), [200] * 19 + [201], name)
            self.assertEqual(len({str(r[1]) for r in results}), 1, name)
        self.assertEqual(self.balance("ada") + self.balance("bob") + self.balance("cy"), 13000)


class SettlementTests(ApiTestCase):
    def setUp(self):
        self.reset(fixture(users=[user("ada", 1000), user("bob", 0), user("cy", 0), user("dee", 50)],
                           settlement_operator_ids=["u_dee"]))
        self.tok["dee"] = self.api.login("dee@example.com")

    def settle(self, transfers, who="dee", key="s"):
        return self.call("POST", "/settlements", {"transfers": transfers}, who=who, key=key)

    def t(self, f, to, amount, **extra):
        return dict(from_handle=f, to_handle=to, amount=amount, **extra)

    def test_permissions(self):
        self.expect(401, "unauthenticated", self.api.call("POST", "/settlements", {"transfers": []}, key="k"))
        self.expect(403, "forbidden", self.settle([self.t("ada", "bob", 1)], who="ada"))
        s, b, _ = self.settle([self.t("ada", "bob", 100, visibility="private")])
        self.assertEqual(s, 201)
        self.assertEqual(self.call("GET", "/activity", who="dee")[1]["payments"], [])
        self.assertEqual(self.call("GET", "/requests", who="dee")[1]["requests"], [])
        self.assertEqual(len(self.call("GET", "/activity", who="bob")[1]["payments"]), 1)
        self.assertEqual(self.call("GET", "/activity", who="cy")[1]["payments"], [])

    def test_net_affordability_and_shape(self):
        s, b, _ = self.settle([self.t("ada", "bob", 100), self.t("bob", "cy", 50, note="n")])
        self.assertEqual(s, 201, b)
        self.assertEqual(set(b), {"settlement_id", "committed_at", "payments"})
        self.assertEqual([p["amount"] for p in b["payments"]], [100, 50])
        for p in b["payments"]:
            self.assertEqual((p["settlement_id"], p["request_id"], p["created_at"]),
                             (b["settlement_id"], None, b["committed_at"]))
            self.assertEqual(p["visibility"], "public")
        self.assertEqual([self.balance(h) for h in ("ada", "bob", "cy")], [900, 50, 50])
        self.assertEqual(self.settle([self.t("ada", "bob", 100), self.t("bob", "cy", 50, note="n")])[0], 200)
        feed = self.call("GET", "/activity", who="cy")[1]["payments"]
        self.assertEqual({p["settlement_id"] for p in feed}, {b["settlement_id"]})
        self.assertIsNone(self.pay("ada", "bob", 1, "plain")[1]["settlement_id"])

    def test_all_or_nothing(self):
        self.expect(409, "insufficient_funds", self.settle([self.t("ada", "bob", 100), self.t("cy", "bob", 1)], key="x"))
        self.assertEqual([self.balance(h) for h in ("ada", "bob", "cy")], [1000, 0, 0])
        self.assertEqual(self.call("GET", "/activity", who="ada")[1]["payments"], [])
        self.assertEqual(self.settle([self.t("ada", "bob", 100)], key="x")[0], 201)  # key not claimed

    def test_entry_errors_precedence(self):
        self.expect(422, "self_payment", self.settle([self.t("ada", "ada", 5), self.t("ada", "ghost", 5)]))
        self.expect(404, "not_found", self.settle([self.t("ada", "ghost", 5), self.t("ada", "ada", 5)]))
        self.expect(404, "not_found", self.settle([self.t("cy", "ada", 5000), self.t("cy", "ghost", 5)]))
        self.expect(422, "validation_failed", self.settle([self.t("cy", "ada", 5000, note=None)]))
        self.expect(422, "validation_failed", self.settle([self.t("ada", "bob", 0)]))
        self.expect(422, "validation_failed", self.settle([self.t("ada", "bob", 1, visibility="x")]))

    def test_shape_and_counts(self):
        for bad in ([], [self.t("ada", "bob", 1)] * 33, ["x"], [1], {}, "nope", None):
            self.expect(422, "validation_failed", self.call("POST", "/settlements", {"transfers": bad}, who="dee", key="b"))
        self.expect(422, "validation_failed", self.call("POST", "/settlements", {}, who="dee", key="b"))
        self.expect(422, "validation_failed", self.call("POST", "/settlements", {"transfers": [{"to_handle": "a", "amount": 1}]}, who="dee", key="b"))
        self.expect(400, "malformed_request", self.call("POST", "/settlements", raw=b"[]", who="dee", key="b"))
        self.assertEqual(self.settle([self.t("ada", "bob", 1)] * 32, key="c32")[0], 201)
        self.assertEqual(self.settle([self.t("ada", "bob", 1, junk=1)], key="c1")[0], 201)
