import threading

from .helpers import World


class RequestTests(World):
    def ask(self, who="bob", payer="ada", amount=1200, **kw):
        return self.post(who, "/requests", {"payer_handle": payer, "amount": amount, **kw})

    def test_create_and_shape(self):
        r = self.ask(note="taxi")
        self.assertEqual(r.status, 201)
        self.assertEqual(set(r.json), {"request_id", "requester_id", "requester_handle", "payer_id",
                                       "payer_handle", "amount", "currency", "note", "status",
                                       "payment_id", "created_at"})
        self.assertEqual((r.json["status"], r.json["requester_handle"], r.json["payer_handle"]),
                         ("pending", "bob", "ada"))
        self.assertErr(self.ask(payer="bob"), 422, "self_request")
        self.assertErr(self.ask(payer="nobody"), 404, "not_found")
        self.assertErr(self.ask(amount=0), 422, "validation_failed")

    def test_over_balance_request_then_pay(self):
        rq = self.ask(who="ada", payer="cy", amount=900).json
        rid = rq["request_id"]
        self.assertErr(self.post("cy", f"/requests/{rid}/pay", {}), 409, "insufficient_funds")
        self.assertEqual(self.get("cy", "/requests?status=pending").json["requests"][0]["status"], "pending")
        self.post("bob", "/payments", {"to_handle": "cy", "amount": 500})
        r = self.post("cy", f"/requests/{rid}/pay", {"visibility": "private"})
        self.assertEqual(r.status, 201)
        self.assertEqual((r.json["request_id"], r.json["visibility"], r.json["amount"]), (rid, "private", 900))
        self.assertEqual(self.balance("ada"), 10900)
        self.assertErr(self.post("cy", f"/requests/{rid}/pay", {}), 409, "request_not_pending")
        self.assertConserved()

    def test_pay_permissions_and_empty_body(self):
        rid = self.ask().json["request_id"]
        self.assertErr(self.post("bob", f"/requests/{rid}/pay", {}), 403, "forbidden")
        self.assertErr(self.post("cy", f"/requests/{rid}/pay", {}), 403, "forbidden")
        self.assertErr(self.post("ada", "/requests/nope/pay", {}), 404, "not_found")
        self.assertErr(self.post("ada", f"/requests/{rid}/pay", {"visibility": "x"}), 422, "validation_failed")
        self.assertEqual(self.post("ada", f"/requests/{rid}/pay", raw=b"").status, 201)

    def test_pay_replay_after_paid(self):
        rid = self.ask().json["request_id"]
        a = self.post("ada", f"/requests/{rid}/pay", {}, key="pk")
        b = self.post("ada", f"/requests/{rid}/pay", {}, key="pk")
        self.assertEqual((a.status, b.status, a.json), (201, 200, b.json))
        self.assertErr(self.post("ada", f"/requests/{rid}/pay", {"visibility": "public"}, key="pk"), 409, "idempotency_key_reuse")
        self.assertEqual(self.balance("ada"), 8800)

    def test_concurrent_pay_once(self):
        rid = self.ask().json["request_id"]
        out = []

        def go():
            out.append(self.post("ada", f"/requests/{rid}/pay", {}).status)
        ts = [threading.Thread(target=go) for _ in range(20)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(out), [201] + [409] * 19)
        self.assertEqual(self.balance("ada"), 8800)

    def test_decline_cancel_matrix(self):
        rid = self.ask().json["request_id"]
        self.assertErr(self.post("bob", f"/requests/{rid}/decline", None, key=None), 403, "forbidden")
        self.assertErr(self.post("ada", f"/requests/{rid}/cancel", None, key=None), 403, "forbidden")
        self.assertEqual(self.post("ada", f"/requests/{rid}/decline", None, key=None).json["status"], "declined")
        self.assertEqual(self.post("ada", f"/requests/{rid}/decline", None, key=None).status, 200)
        self.assertErr(self.post("bob", f"/requests/{rid}/cancel", None, key=None), 409, "request_not_pending")
        self.assertErr(self.post("ada", f"/requests/{rid}/pay", {}), 409, "request_not_pending")
        rid2 = self.ask().json["request_id"]
        self.assertEqual(self.post("bob", f"/requests/{rid2}/cancel", None, key=None).json["status"], "cancelled")
        self.assertEqual(self.post("bob", f"/requests/{rid2}/cancel", None, key=None).status, 200)
        self.assertErr(self.post("ada", f"/requests/{rid2}/decline", None, key=None), 409, "request_not_pending")
        self.assertErr(self.post("ada", "/requests/zzz/decline", None, key=None), 404, "not_found")

    def test_list_filters_and_paging(self):
        for i in range(5):
            self.ask(amount=10 + i)
        self.ask(who="ada", payer="cy")
        self.assertEqual(len(self.get("bob", "/requests").json["requests"]), 5)
        self.assertEqual(len(self.get("cy", "/requests").json["requests"]), 1)
        page = self.get("bob", "/requests?limit=5").json
        self.assertFalse(page["has_more"])
        page = self.get("bob", "/requests?limit=2&offset=0").json
        self.assertTrue(page["has_more"])
        self.assertEqual([r["amount"] for r in page["requests"]], [14, 13])
        self.assertEqual(len(self.get("ada", "/requests?direction=incoming").json["requests"]), 5)
        self.assertEqual(len(self.get("ada", "/requests?direction=outgoing").json["requests"]), 1)
        for q in ("limit=0", "limit=201", "limit=1e1", "limit=+4", "limit=", "offset=-1",
                  "direction=sideways", "status=nope", "limit=4.0"):
            self.assertErr(self.get("bob", "/requests?" + q), 422, "validation_failed")
        self.assertEqual(self.get("bob", "/requests?limit=200&zzz=1").status, 200)


class SplitTests(World):
    def split(self, amount, handles, who="ada", **kw):
        return self.post(who, "/splits", {"amount": amount, "participant_handles": handles, **kw})

    def test_share_table(self):
        for amount, n, want in ((1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
                                (999, 3, [333] * 3), (5, 5, [1] * 5)):
            handles = ["ada", "bob", "cy", "ada2", "bob2"][:n]
            from .helpers import call
            for h in handles[3:]:
                call("POST", "/auth/signup", {"email": f"{h}@x.io", "password": "longenough", "display_name": h})
            r = self.split(amount, handles)
            self.assertEqual(r.status, 201, r.raw)
            self.assertEqual([s["amount"] for s in r.json["shares"]], want)
            self.assertEqual(len(r.json["requests"]), n - 1)
            self.assertEqual([q["amount"] for q in r.json["requests"]], want[1:])

    def test_caller_only_and_omitted(self):
        r = self.split(30, ["ada"])
        self.assertEqual((r.status, r.json["requests"]), (201, []))
        r = self.split(30, ["bob", "cy"], note="n")
        self.assertEqual([s["amount"] for s in r.json["shares"]], [15, 15])
        self.assertEqual(len(r.json["requests"]), 2)
        self.assertEqual(r.json["requests"][0]["requester_handle"], "ada")
        self.assertEqual(self.get("ada", "/activity").json["payments"], [])

    def test_rejections(self):
        self.assertErr(self.split(10, []), 422, "validation_failed")
        self.assertErr(self.split(10, ["bob", "bob"]), 422, "validation_failed")
        self.assertErr(self.split(10, ["bob", "ghost"]), 404, "not_found")
        self.assertErr(self.split(10, ["ghost"] * 1), 404, "not_found")
        self.assertErr(self.post("ada", "/splits", {"amount": 10, "participant_handles": "bob"}), 400, "malformed_request")
        self.assertErr(self.post("ada", "/splits", {"amount": 10, "participant_handles": ["bob", 3]}), 400, "malformed_request")
        self.assertErr(self.post("ada", "/splits", {"amount": 10}), 422, "validation_failed")
        self.assertErr(self.split(10, [f"g{i}" for i in range(1000)]), 404, "not_found")
        self.assertEqual(self.get("bob", "/requests").json["requests"], [])  # atomic: none created

    def test_split_all_paid_conserves(self):
        r = self.split(1000, ["ada", "bob", "cy"])
        for q in r.json["requests"]:
            payer = q["payer_handle"]
            pay = self.post(payer, f"/requests/{q['request_id']}/pay", {})
            self.assertIn(pay.status, (201, 409))
        self.assertConserved()
