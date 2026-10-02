import threading

from .helpers import World, call, fixture, user


class SettlementTests(World):
    fixture_extra = {"settlement_operator_ids": ["u_cy"]}

    def settle(self, transfers, who="cy", **kw):
        return self.post(who, "/settlements", {"transfers": transfers}, **kw)

    def test_permissions(self):
        t = [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]
        self.assertErr(self.settle(t, who="ada"), 403, "forbidden")
        self.assertErr(self.settle(t, who=None), 401, "unauthenticated")
        self.assertErr(self.settle(t, key=None), 400, "missing_idempotency_key")
        r = self.settle(t)
        self.assertEqual(r.status, 201)
        self.assertEqual(self.get("cy", "/activity").json["payments"][0]["settlement_id"], r.json["settlement_id"])

    def test_chain_net_and_shape(self):
        r = self.settle([{"from_handle": "cy", "to_handle": "ada", "amount": 500},
                         {"from_handle": "ada", "to_handle": "bob", "amount": 10500, "visibility": "private"},
                         {"from_handle": "bob", "to_handle": "cy", "amount": 1, "note": "n"}])
        self.assertEqual(r.status, 201, r.raw)
        pays = r.json["payments"]
        self.assertEqual([p["amount"] for p in pays], [500, 10500, 1])
        self.assertEqual({p["created_at"] for p in pays}, {r.json["committed_at"]})
        self.assertTrue(all(p["settlement_id"] == r.json["settlement_id"] and p["request_id"] is None for p in pays))
        self.assertEqual((self.balance("ada"), self.balance("bob"), self.balance("cy")), (0, 12999, 1))
        # private member hidden from the operator when not a party
        self.assertEqual(len(self.get("cy", "/activity").json["payments"]), 2)
        self.assertConserved()
        again = self.settle([], key="x")
        self.assertErr(again, 422, "validation_failed")

    def test_unaffordable_and_error_precedence(self):
        big = {"from_handle": "cy", "to_handle": "ada", "amount": 501}
        self.assertErr(self.settle([big], key="u"), 409, "insufficient_funds")
        self.assertEqual(self.balance("cy"), 500)
        bad404 = {"from_handle": "cy", "to_handle": "ghost", "amount": 1}
        bad_self = {"from_handle": "cy", "to_handle": "cy", "amount": 1}
        self.assertErr(self.settle([big, bad404]), 404, "not_found")
        self.assertErr(self.settle([bad_self, bad404]), 422, "self_payment")
        self.assertErr(self.settle([bad404, bad_self]), 404, "not_found")
        ok = {"from_handle": "cy", "to_handle": "ada", "amount": 5}
        self.assertErr(self.settle([ok, {**ok, "amount": 0}]), 422, "validation_failed")
        self.assertEqual(self.settle([ok], key="u").status, 201)  # key still free after failures

    def test_batch_shape(self):
        ok = {"from_handle": "cy", "to_handle": "ada", "amount": 1}
        self.assertErr(self.post("cy", "/settlements", {}), 422, "validation_failed")
        self.assertErr(self.post("cy", "/settlements", {"transfers": "x"}), 422, "validation_failed")
        self.assertErr(self.settle([5]), 422, "validation_failed")
        self.assertErr(self.settle([ok] * 33), 422, "validation_failed")
        self.assertEqual(self.settle([{**ok, "amount": 1}] * 32).status, 201)
        self.assertErr(self.settle([{**ok, "from_handle": 3}]), 400, "malformed_request")

    def test_replay_and_concurrency(self):
        t = [{"from_handle": "ada", "to_handle": "bob", "amount": 100}]
        out = []

        def go():
            out.append(self.settle(t, key="same"))
        ts = [threading.Thread(target=go) for _ in range(20)]
        [x.start() for x in ts]
        [x.join() for x in ts]
        self.assertEqual(sorted(r.status for r in out), [200] * 19 + [201])
        self.assertEqual(len({r.raw for r in out}), 1)
        self.assertEqual(self.balance("ada"), 9900)


class ExportImportTests(World):
    fixture_extra = {"settlement_operator_ids": ["u_ada"]}

    def test_roundtrip_preserves_everything(self):
        self.post("ada", "/payments", {"to_handle": "bob", "amount": 100, "visibility": "private"}, key="pk")
        rq = self.post("bob", "/requests", {"payer_handle": "cy", "amount": 40}, key="rk").json
        st = self.post("ada", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 7}]}, key="sk")
        exp = call("GET", "/_test/export")
        self.assertEqual(exp.status, 200)
        self.assertNotIn("correct horse", exp.raw.decode())
        self.assertEqual((exp.json["track"], exp.json["format_version"]), ("pocketful", 1))
        self.post("ada", "/payments", {"to_handle": "bob", "amount": 1})  # later write
        self.assertEqual(call("POST", "/_test/import", exp.json).status, 204)
        self.assertEqual(call("GET", "/_test/export").json, exp.json)
        self.assertEqual(call("POST", "/_test/import", exp.json).status, 204)
        self.assertEqual(call("GET", "/_test/export").json, exp.json)
        self.assertEqual(self.balance("ada"), 10000 - 100 - 7)
        again = self.post("bob", "/requests", {"payer_handle": "cy", "amount": 40}, key="rk")
        self.assertEqual((again.status, again.json), (200, rq))
        s2 = self.post("ada", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 7}]}, key="sk")
        self.assertEqual((s2.status, s2.json), (200, st.json))
        self.assertErr(self.post("ada", "/payments", {"to_handle": "bob", "amount": 5}, key="pk"), 409, "idempotency_key_reuse")
        self.assertEqual(call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}).status, 200)
        self.assertEqual(len(self.get("bob", "/activity").json["payments"]), 2)
        self.assertConserved()

    def test_import_replaces_and_rejects(self):
        exp = call("GET", "/_test/export").json
        call("POST", "/auth/signup", {"email": "new@x.io", "password": "12345678", "display_name": "N"})
        call("POST", "/_test/import", exp)
        self.assertEqual(call("POST", "/auth/login", {"email": "new@x.io", "password": "12345678"}).status, 401)
        for bad in ({}, {"track": "x", "format_version": 1, "state": exp["state"]},
                    {"track": "pocketful", "format_version": 2, "state": exp["state"]},
                    {"track": "pocketful", "format_version": 1},
                    {"track": "pocketful", "format_version": 1, "state": {"users": 1}},
                    {"track": "pocketful", "format_version": 1, "state": []}):
            self.assertErr(call("POST", "/_test/import", bad), 422, "validation_failed")
        self.assertErr(call("POST", "/_test/import", raw=b"{"), 400, "malformed_request")
        self.assertEqual(self.balance("ada"), 10000)
