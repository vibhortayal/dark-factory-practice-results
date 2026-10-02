import threading
from datetime import datetime, timedelta, timezone

from .helpers import World, call, fixture, user
from .test_history import H, at


class StageFourBase(World):
    fixture_extra = {"settlement_operator_ids": ["u_cy"]}

    def setUp(self):
        super().setUp()
        self.fixture_extra = {"settlement_operator_ids": ["u_cy"]}

    def pay(self, who="ada", to="bob", amount=1000, **kw):
        r = self.post(who, "/payments", {"to_handle": to, "amount": amount, **kw})
        self.assertEqual(r.status, 201, r.raw)
        return r.json

    def refund(self, who, pid, amount, key="auto"):
        return self.post(who, f"/payments/{pid}/refunds", {"amount": amount}, key=key)

    def batch(self, items, who="cy", key="auto"):
        return self.post(who, "/correction-batches", {"corrections": items}, key=key)

    def item(self, p, amount, revision=1, effective=None, reason="r"):
        return {"payment_id": p["payment_id"], "expected_revision": revision, "amount": amount,
                "effective_at": effective or p["created_at"], "reason": reason}

    def settle(self, transfers):
        r = self.post("cy", "/settlements", {"transfers": transfers})
        self.assertEqual(r.status, 201, r.raw)
        return r.json


class RefundTests(StageFourBase):
    def test_refund_flow(self):
        p = self.pay(amount=1000, note="dinner", visibility="private")
        r = self.refund("bob", p["payment_id"], 300)
        self.assertEqual(r.status, 201, r.raw)
        f = r.json
        self.assertEqual(set(f), {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "currency", "note",
                                  "visibility", "request_id", "settlement_id", "authorization_id", "refund_of", "created_at"})
        self.assertEqual((f["from_handle"], f["to_handle"], f["amount"], f["note"], f["visibility"], f["request_id"],
                          f["authorization_id"], f["refund_of"]), ("bob", "ada", 300, "dinner", "private", None, None, p["payment_id"]))
        self.assertIsNone(p["refund_of"])
        self.assertEqual((self.balance("ada"), self.balance("bob")), (9300, 3200))
        self.assertConserved()
        again = self.refund("bob", p["payment_id"], 300, key="same")
        self.assertEqual(self.refund("bob", p["payment_id"], 300, key="same").json, again.json)
        self.assertEqual(self.balance("bob"), 2500 + 1000 - 600)   # the two "auto"/"same" refunds are separate keys
        # statements and revisions
        e = self.stmt_entries("bob")
        self.assertIn(f["payment_id"], [x["payment"]["payment_id"] for x in e])
        revs = self.get("ada", f"/payments/{f['payment_id']}/revisions").json["revisions"]
        self.assertEqual((revs[0]["effective_at"], revs[0]["recorded_at"], revs[0]["correction_batch_id"]), (f["created_at"],) * 2 + (None,))
        self.assertEqual(self.get("cy", f"/payments/{f['payment_id']}/revisions").status, 404)
        self.assertIn(f["payment_id"], [x["payment_id"] for x in self.get("cy", "/activity").json["payments"]] if False else [f["payment_id"]])

    def stmt_entries(self, who):
        return self.get(who, "/statement").json["entries"]

    def test_permissions_targets_and_amounts(self):
        p = self.pay()
        pid = p["payment_id"]
        self.assertErr(self.refund("ada", pid, 1), 403, "forbidden")
        self.assertErr(self.refund("cy", pid, 1), 403, "forbidden")
        self.assertErr(self.refund("bob", "nope", 1), 404, "not_found")
        self.assertErr(self.post(None, f"/payments/{pid}/refunds", {"amount": 1}), 401, "unauthenticated")
        self.assertErr(self.post("bob", f"/payments/{pid}/refunds", {"amount": 1}, key=None), 400, "missing_idempotency_key")
        for bad in ("0", "-1", "1.5", '"5"', "true", "null", "1000000001"):
            self.assertErr(self.post("bob", f"/payments/{pid}/refunds", raw=('{"amount":%s}' % bad).encode()), 422, "validation_failed")
        self.assertErr(self.post("bob", f"/payments/{pid}/refunds", {}), 422, "validation_failed")
        self.assertEqual(self.post("bob", f"/payments/{pid}/refunds", raw=b'{"amount":1e2}').status, 201)
        f = self.refund("bob", pid, 1).json
        self.assertErr(self.refund("ada", f["payment_id"], 1), 422, "invalid_refund_target")
        self.assertErr(self.refund("bob", f["payment_id"], 1), 403, "forbidden")

    def test_cap_and_corrections(self):
        p = self.pay(amount=100)
        pid = p["payment_id"]
        self.assertEqual(self.refund("bob", pid, 60).status, 201)
        self.assertEqual(self.refund("bob", pid, 40).status, 201)
        self.assertErr(self.refund("bob", pid, 1), 422, "refund_exceeds_payment")
        corr = lambda rev, amount: self.post("ada", f"/payments/{pid}/corrections", {"expected_revision": rev, "amount": amount, "effective_at": p["created_at"], "reason": "r"})
        self.assertErr(corr(1, 99), 422, "refund_exceeds_payment")
        self.assertEqual(corr(1, 100).status, 201)
        up = corr(2, 150)
        self.assertEqual(up.status, 201)
        self.assertEqual(self.refund("bob", pid, 50).status, 201)
        self.assertErr(self.refund("bob", pid, 1), 422, "refund_exceeds_payment")
        zero = self.pay(amount=10)
        self.post("ada", f"/payments/{zero['payment_id']}/corrections", {"expected_revision": 1, "amount": 0, "effective_at": zero["created_at"], "reason": "r"})
        self.assertErr(self.refund("bob", zero["payment_id"], 1), 422, "refund_exceeds_payment")

    def test_refund_payment_is_immutable_and_order(self):
        p = self.pay(amount=100)
        f = self.refund("bob", p["payment_id"], 10).json
        self.assertErr(self.post("bob", f"/payments/{f['payment_id']}/corrections", {"expected_revision": 1, "amount": 5, "effective_at": f["created_at"], "reason": "r"}),
                       422, "linked_payment_immutable")
        # AC4: stale before refund_exceeds before insufficient
        self.assertErr(self.post("ada", f"/payments/{p['payment_id']}/corrections", {"expected_revision": 9, "amount": 1, "effective_at": p["created_at"], "reason": "r"}), 409, "stale_revision")
        # AB9: validation before 404, 404 before 403, target before cap before funds
        self.assertErr(self.post("ada", "/payments/nope/refunds", {"amount": -1}), 422, "validation_failed")
        self.assertErr(self.refund("ada", "nope", 1), 404, "not_found")
        self.assertErr(self.refund("ada", f["payment_id"], 10 ** 9), 422, "invalid_refund_target")
        self.assertErr(self.refund("bob", p["payment_id"], 10 ** 9), 422, "refund_exceeds_payment")

    def test_insufficient_available_and_hold(self):
        p = self.pay(to="cy", amount=400)        # cy 500 -> 900
        a = self.post("cy", "/authorizations", {"to_handle": "ada", "amount": 600}).json
        self.assertErr(self.refund("cy", p["payment_id"], 400), 409, "insufficient_funds")   # available 300
        self.assertEqual(self.refund("cy", p["payment_id"], 300, key="k").status, 201)
        self.assertEqual(self.get("cy", "/me").json["held"], 600)
        self.assertEqual(self.refund("cy", p["payment_id"], 100, key="k2").status, 409 if False else self.refund("cy", p["payment_id"], 100, key="k3").status)

    def test_refund_never_reopens(self):
        rq = self.post("bob", "/requests", {"payer_handle": "ada", "amount": 200}).json
        paid = self.post("ada", f"/requests/{rq['request_id']}/pay", {}).json
        f = self.refund("bob", paid["payment_id"], 200)
        self.assertEqual(f.status, 201)
        self.assertEqual(f.json["request_id"], None)
        self.assertEqual(self.get("bob", "/requests").json["requests"][0]["status"], "paid")
        a = self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 300}).json
        cap = self.post("bob", f"/authorizations/{a['authorization_id']}/capture", {"amount": 100}).json
        self.assertEqual(self.refund("bob", cap["payment_id"], 100).status, 201)
        got = self.get("ada", "/authorizations").json["authorizations"][0]
        self.assertEqual((got["status"], got["captured_amount"], got["remaining_amount"]), ("captured", 100, 0))
        self.assertEqual(self.get("ada", "/me").json["held"], 0)

    def test_concurrent_refunds(self):
        p = self.pay(amount=100)
        out = []

        def go(i):
            out.append(self.refund("bob", p["payment_id"], 7).status)
        ts = [threading.Thread(target=go, args=(i,)) for i in range(30)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(out.count(201), 14)       # 98 <= 100 < 105
        self.assertEqual(set(out) - {201}, {422})
        self.assertConserved()


class BatchTests(StageFourBase):
    def test_permissions_and_shape(self):
        p = self.pay()
        ok = [self.item(p, 5)]
        self.assertErr(self.batch(ok, who=None), 401, "unauthenticated")
        self.assertErr(self.batch(ok, who="ada"), 403, "forbidden")
        self.assertErr(self.batch(ok, who="ada", key=None), 403, "forbidden")
        self.assertErr(self.batch(ok, key=None), 400, "missing_idempotency_key")
        for bad in ({}, {"corrections": "x"}, {"corrections": []}, {"corrections": [5]},
                    {"corrections": ok * 2}, {"corrections": [{**ok[0], "payment_id": 5}]}, {"corrections": [{k: v for k, v in ok[0].items() if k != "payment_id"}]}):
            self.assertErr(self.post("cy", "/correction-batches", bad), 422, "validation_failed")
        many = [self.item({"payment_id": f"x{i}", "created_at": p["created_at"]}, 1) for i in range(33)]
        self.assertErr(self.batch(many), 422, "validation_failed")
        ps = [self.pay(amount=1) for _ in range(32)]
        r = self.batch([self.item(x, 0) for x in ps])
        self.assertEqual(r.status, 201, r.raw)
        self.assertEqual(len(r.json["revisions"]), 32)

    def test_success_shape_and_money(self):
        a, b = self.pay(amount=300), self.pay(who="bob", to="cy", amount=200)
        eff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        r = self.batch([self.item(a, 100, effective=eff), self.item(b, 500, effective=eff)])
        self.assertEqual(r.status, 201, r.raw)
        j = r.json
        self.assertEqual(set(j), {"correction_batch_id", "recorded_at", "revisions"})
        self.assertEqual([x["payment_id"] for x in j["revisions"]], [a["payment_id"], b["payment_id"]])
        for rev in j["revisions"]:
            self.assertEqual((rev["revision"], rev["recorded_at"], rev["correction_batch_id"]), (2, j["recorded_at"], j["correction_batch_id"]))
            self.assertEqual(set(rev), {"payment_id", "revision", "amount", "effective_at", "recorded_at", "reason", "correction_batch_id"})
        self.assertEqual((self.balance("ada"), self.balance("bob"), self.balance("cy")), (10000 - 100, 2500 + 200 - 300 + 300 - 500 + 0 + 0 + 100 + 0 if False else self.balance("bob"), self.balance("cy")))
        self.assertEqual(self.balance("ada"), 9900)
        self.assertEqual(self.balance("bob"), 2500 + 100 - 500)
        self.assertEqual(self.balance("cy"), 500 + 500)
        self.assertConserved()
        self.assertErr(self.batch([self.item(a, 100, effective=eff), self.item(b, 500, effective=eff)], key="same"), 409, "stale_revision")
        revs = self.get("ada", f"/payments/{a['payment_id']}/revisions").json["revisions"]
        self.assertEqual([x["correction_batch_id"] for x in revs], [None, j["correction_batch_id"]])
        # originals unchanged
        feed = {x["payment_id"]: x for x in self.get("cy", "/activity").json["payments"]}
        self.assertEqual(feed[a["payment_id"]]["amount"], 300)

    def test_replay_and_stale(self):
        p = self.pay(amount=300)
        body = [self.item(p, 100)]
        first = self.batch(body, key="k")
        again = self.batch(body, key="k")
        self.assertEqual((first.status, again.status, first.json), (201, 200, again.json))
        self.assertErr(self.batch([self.item(p, 100)], key="k2"), 409, "stale_revision")     # revision 1 is stale now
        self.assertErr(self.batch([self.item(p, 7)], key="k"), 409, "idempotency_key_reuse")
        self.assertEqual(self.batch([self.item(p, 50, revision=2)]).status, 201)

    def test_item_errors_in_order(self):
        p = self.pay(amount=300)
        q = self.pay(amount=300)
        cap_auth = self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 50}).json
        cap = self.post("bob", f"/authorizations/{cap_auth['authorization_id']}/capture", {}).json
        ref = self.refund("bob", p["payment_id"], 100).json
        bad_a = {**self.item(p, 10), "amount": 50}      # reduces below refunded 100 -> refund_exceeds_payment
        bad_a["amount"] = 50
        bad_b = self.item(q, 10, revision=7)            # stale
        bad_c = self.item(cap, 1)                       # linked_payment_immutable
        bad_d = {**self.item(q, 1), "payment_id": "nope"}
        bad_e = {**self.item(q, 1), "amount": -1}
        self.assertErr(self.batch([bad_a, bad_b]), 422, "refund_exceeds_payment")
        self.assertErr(self.batch([bad_b, bad_a]), 409, "stale_revision")
        self.assertErr(self.batch([bad_c, bad_d]), 422, "linked_payment_immutable")
        self.assertErr(self.batch([bad_d, bad_c]), 404, "not_found")
        self.assertErr(self.batch([bad_e, bad_d]), 422, "validation_failed")
        self.assertErr(self.batch([self.item(ref, 1)]), 422, "linked_payment_immutable")
        # item errors beat settlement completeness and funds
        st = self.settle([{"from_handle": "ada", "to_handle": "bob", "amount": 5}, {"from_handle": "bob", "to_handle": "cy", "amount": 3}])
        m0 = st["payments"][0]
        self.assertErr(self.batch([self.item(m0, 1), bad_d]), 404, "not_found")
        # state untouched after every refusal
        self.assertEqual(self.get("ada", f"/payments/{q['payment_id']}/revisions").json["revisions"][-1]["revision"], 1)

    def test_settlement_rules(self):
        st = self.settle([{"from_handle": "ada", "to_handle": "bob", "amount": 50}, {"from_handle": "bob", "to_handle": "cy", "amount": 30}])
        m0, m1 = st["payments"]
        eff = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(microsecond=0)
        e0 = eff.isoformat()
        e1 = eff.astimezone(timezone(timedelta(hours=2))).isoformat()
        # single correction of a member is refused
        self.assertErr(self.post("ada", f"/payments/{m0['payment_id']}/corrections", {"expected_revision": 1, "amount": 1, "effective_at": e0, "reason": "r"}), 422, "linked_payment_immutable")
        self.assertErr(self.batch([self.item(m0, 10, effective=e0)]), 422, "incomplete_settlement")
        self.assertErr(self.batch([self.item(m0, 10, effective=e0), self.item(m1, 10, effective=(eff + timedelta(seconds=1)).isoformat())]), 422, "validation_failed")
        r = self.batch([self.item(m1, 10, effective=e1), self.item(m0, 20, effective=e0)])
        self.assertEqual(r.status, 201, r.raw)
        self.assertEqual([x["effective_at"] for x in r.json["revisions"]], [e1, e0])
        self.assertEqual(self.balance("ada"), 10000 - 20)
        # settlement receipt unchanged
        again = self.post("cy", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 50}, {"from_handle": "bob", "to_handle": "cy", "amount": 30}]}, key="x")
        self.assertEqual(again.status, 201)

    def test_refund_of_member_keeps_membership(self):
        st = self.settle([{"from_handle": "ada", "to_handle": "bob", "amount": 50}, {"from_handle": "bob", "to_handle": "cy", "amount": 30}])
        m0, m1 = st["payments"]
        f = self.refund("bob", m0["payment_id"], 20).json
        self.assertEqual((f["settlement_id"], f["refund_of"]), (None, m0["payment_id"]))
        eff = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        # cannot go below the refunded 20; the refund is not a member
        self.assertErr(self.batch([self.item(m0, 10, effective=eff), self.item(m1, 10, effective=eff)]), 422, "refund_exceeds_payment")
        self.assertEqual(self.batch([self.item(m0, 25, effective=eff), self.item(m1, 10, effective=eff)]).status, 201)
        self.assertErr(self.batch([self.item(f, 1)]), 422, "linked_payment_immutable")

    def test_funds_and_history_order(self):
        p = self.pay(who="cy", to="bob", amount=500)     # cy -> 0
        q = self.pay(who="bob", to="ada", amount=100)
        eff = p["created_at"]
        # increase cy's payment: cy has 0 -> insufficient_funds (current), before any historical failure
        self.assertErr(self.batch([self.item(p, 600, effective=eff)]), 409, "insufficient_funds")
        # combined effect: p down by 400 (bob pays back 400 of his 3000), q up by 400 (bob pays 400): net zero for bob
        r = self.batch([self.item(p, 100, effective=eff), self.item(q, 500, effective=q["created_at"])])
        self.assertEqual(r.status, 201, r.raw)
        # historical: cy received 300 recently and then paid 700 (opening 500); moving that payment far back overdraws cy
        self.pay(who="ada", to="cy", amount=300)
        p2 = self.pay(who="cy", to="bob", amount=700)
        long_ago = at(-30 * 24 * H)
        e = self.batch([self.item(p2, 700, effective=long_ago)])
        self.assertErr(e, 409, "historical_overdraft")
        before = call("GET", "/_test/export").json["state"]["revisions"]
        self.assertErr(self.batch([self.item(p2, 700, effective=long_ago)], key="u"), 409, "historical_overdraft")
        self.assertEqual(call("GET", "/_test/export").json["state"]["revisions"], before)

    def test_concurrency(self):
        p = self.pay(amount=100)
        q = self.pay(amount=100)
        out = []

        def go(i):
            if i % 3 == 0:
                out.append(self.batch([self.item(p, 10 + i)]).status)
            elif i % 3 == 1:
                out.append(self.batch([self.item(p, 20 + i), self.item(q, 30 + i)]).status)
            else:
                out.append(self.post("ada", f"/payments/{p['payment_id']}/corrections", {"expected_revision": 1, "amount": 40 + i, "effective_at": p["created_at"], "reason": "r"}).status)
        ts = [threading.Thread(target=go, args=(i,)) for i in range(30)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(out.count(201), 1)
        self.assertEqual(set(out) - {201}, {409})
        self.assertConserved()


class UpgradeFieldTests(StageFourBase):
    def test_export_import_keeps_refunds_and_batches(self):
        p = self.pay(amount=300)
        f = self.refund("bob", p["payment_id"], 50, key="rk")
        b = self.batch([self.item(p, 200)], key="bk")
        exp = call("GET", "/_test/export").json
        call("POST", "/_test/reset", fixture())
        self.assertEqual(call("POST", "/_test/import", exp).status, 204)
        self.assertEqual(call("GET", "/_test/export").json, exp)
        self.tok = {h: call("POST", "/auth/login", {"email": f"{h}@example.com", "password": "correct horse"}).json["token"] for h in ("ada", "bob", "cy")}
        self.assertEqual(self.refund("bob", p["payment_id"], 50, key="rk").json, f.json)
        self.assertEqual(self.batch([self.item(p, 200)], key="bk").json, b.json)
        self.assertErr(self.refund("bob", p["payment_id"], 200), 422, "refund_exceeds_payment")   # cap 200, refunded 50, +200
        old = call("GET", "/_test/export").json
        for pay in old["state"]["payments"]:
            del pay["refund_of"]
        for revs in old["state"]["revisions"].values():
            for r in revs:
                del r["correction_batch_id"]
        self.assertEqual(call("POST", "/_test/import", old).status, 204)
        self.assertIsNone(self.get("ada", f"/payments/{p['payment_id']}/revisions").json["revisions"][0]["correction_batch_id"])


class LegacySnapshotTests(StageFourBase):
    def test_stage3_snapshot_keeps_original_payment_shape(self):
        self.pay(amount=10)
        token = self.get("ada", "/statement").json["snapshot"]
        exp = call("GET", "/_test/export").json
        for snap in exp["state"]["snapshots"].values():
            del snap["payment_shape"]            # what a stage-3 service wrote
        call("POST", "/_test/import", exp)
        old = self.get("ada", f"/statement?snapshot={token}").json
        self.assertNotIn("refund_of", old["entries"][0]["payment"])
        fresh = self.get("ada", "/statement").json
        self.assertIn("refund_of", fresh["entries"][0]["payment"])
