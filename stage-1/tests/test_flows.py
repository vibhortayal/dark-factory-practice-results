"""Spec-derived tests: idempotency, splits, feed, settlements, export/import (rows F, G, H, I, K)."""
import copy
import threading
import unittest

from app.money import equal_shares
from helpers import Api, call, fixture, user


class Idempotency(Api):
    """Each case runs against all five write paths."""

    def setUp(self):
        super().setUp()
        self.reset(fixture(settlement_operator_ids=["u_ada"]))
        self.rid = [self.ok("bob", "POST", "/requests", {"payer_handle": "ada", "amount": 10})["request_id"]
                    for _ in range(3)]
        self.paths = {
            "payments": ("/payments", {"to_handle": "bob", "amount": 10}, {"to_handle": "bob", "amount": 11}),
            "requests": ("/requests", {"payer_handle": "bob", "amount": 10}, {"payer_handle": "bob", "amount": 11}),
            "pay": (f"/requests/{self.rid[0]}/pay", {}, {"visibility": "public"}),
            "splits": ("/splits", {"amount": 9, "participant_handles": ["bob", "cy"]},
                       {"amount": 8, "participant_handles": ["bob", "cy"]}),
            "settlements": ("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]},
                            {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 2}]}),
        }

    def each(self, fn):
        for name, (path, good, other) in self.paths.items():
            with self.subTest(name):
                fn(path, good, other)

    def test_missing_and_long_key(self):
        def check(path, good, other):
            self.err("ada", "POST", path, good, 400, "missing_idempotency_key", key=None)
            self.err("ada", "POST", path, good, 400, "missing_idempotency_key", key="")
            self.err("ada", "POST", path, good, 422, "validation_failed", key="k" * 256)
            self.assertEqual(self.req("ada", "POST", path, good, key="é" * 255)[0], 201)
        self.each(check)

    def test_replay_conflict_and_scope(self):
        def check(path, good, other):
            s1, b1, _ = self.req("ada", "POST", path, good, key="K-" + path)
            self.assertEqual(s1, 201, b1)
            bal = self.total(), self.balance("ada")
            s2, b2, _ = self.req("ada", "POST", path, dict(reversed(list(good.items()))), key="K-" + path)
            self.assertEqual((s2, b2), (200, b1))
            self.assertEqual((self.total(), self.balance("ada")), bal)
            self.err("ada", "POST", path, other, 409, "idempotency_key_reuse", key="K-" + path)
            self.err("ada", "POST", path, {**good, "extra": 1}, 409, "idempotency_key_reuse", key="K-" + path)
            self.err("ada", "POST", path, {"amount": "bad", "participant_handles": 5, "transfers": 1},
                     409, "idempotency_key_reuse", key="K-" + path)
        self.each(check)

    def test_replay_raw_whitespace_and_number_forms(self):
        s, b, _ = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1000}', token=self.tok["ada"], key="n")
        self.assertEqual(s, 201)
        s, b2, _ = call("POST", "/payments", raw=b'{ "amount" : 1e3 , "to_handle":"bob" }',
                        token=self.tok["ada"], key="n")
        self.assertEqual((s, b2), (200, b))

    def test_other_user_same_key_and_other_path(self):
        self.assertEqual(self.req("ada", "POST", "/payments", {"to_handle": "cy", "amount": 1}, key="s")[0], 201)
        self.assertEqual(self.req("bob", "POST", "/payments", {"to_handle": "cy", "amount": 1}, key="s")[0], 201)
        self.assertEqual(self.req("ada", "POST", "/requests", {"payer_handle": "cy", "amount": 1}, key="s")[0], 201)
        for rid in self.rid[1:]:
            self.assertEqual(self.req("ada", "POST", f"/requests/{rid}/pay", {}, key="shared")[0], 201)

    def test_failed_key_reusable(self):
        self.err("ada", "POST", "/payments", {"to_handle": "nobody", "amount": 1}, 404, "not_found", key="f")
        self.err("ada", "POST", "/payments", {"to_handle": "bob", "amount": 0}, 422, "validation_failed", key="f")
        self.err("cy", "POST", "/payments", {"to_handle": "bob", "amount": 50}, 409, "insufficient_funds", key="f")
        self.assertEqual(self.req("cy", "POST", "/requests", {"payer_handle": "bob", "amount": 50}, key="f")[0], 201)
        self.ok("ada", "POST", "/payments", {"to_handle": "cy", "amount": 100})
        self.assertEqual(self.req("cy", "POST", "/payments", {"to_handle": "bob", "amount": 50}, key="f")[0], 201)

    def test_replay_after_resource_changed(self):
        s, created, _ = self.req("bob", "POST", "/requests", {"payer_handle": "ada", "amount": 4}, key="c")
        self.ok("bob", "POST", f"/requests/{created['request_id']}/cancel", status=200, key=None)
        s, b, _ = self.req("bob", "POST", "/requests", {"payer_handle": "ada", "amount": 4}, key="c")
        self.assertEqual((s, b["status"]), (200, "pending"))
        s, pay, _ = self.req("ada", "POST", f"/requests/{self.rid[0]}/pay", {}, key="p")
        s, again, _ = self.req("ada", "POST", f"/requests/{self.rid[0]}/pay", {}, key="p")
        self.assertEqual((s, again), (200, pay))
        self.assertEqual(self.balance("ada"), 9990)

    def test_concurrent_identical(self):
        def check(path, good, other):
            out = []

            def go():
                out.append(call("POST", path, good, token=self.tok["ada"], key="conc-" + path)[:2])
            ts = [threading.Thread(target=go) for _ in range(30)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            self.assertEqual(sorted(s for s, _ in out).count(201), 1)
            self.assertEqual({str(b) for _, b in out}, {str(out[0][1])})
            self.assertEqual({s for s, _ in out}, {200, 201})
        self.each(check)
        self.assertEqual(self.total(), 12500)


class Splits(Api):
    def test_share_table(self):
        for amount, n, want in ((1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
                                (999, 3, [333] * 3), (5, 5, [1] * 5)):
            self.assertEqual(equal_shares(amount, n), want)
        for amount in range(0, 120):
            for n in range(1, 12):
                shares = equal_shares(amount, n)
                self.assertEqual((sum(shares), max(shares) - min(shares) <= 1,
                                  shares == sorted(shares, reverse=True)), (amount, True, True))

    def test_split_shapes(self):
        s = self.ok("ada", "POST", "/splits", {"amount": 1000, "participant_handles": ["ada", "bob", "cy"], "note": "d"})
        self.assertEqual([x["amount"] for x in s["shares"]], [334, 333, 333])
        self.assertEqual([r["payer_handle"] for r in s["requests"]], ["bob", "cy"])
        self.assertEqual([r["amount"] for r in s["requests"]], [333, 333])
        self.assertTrue(all(r["status"] == "pending" and r["requester_handle"] == "ada" and r["note"] == "d"
                            for r in s["requests"]))
        s = self.ok("ada", "POST", "/splits", {"amount": 10, "participant_handles": ["cy", "bob"]})
        self.assertEqual([x["amount"] for x in s["shares"]], [5, 5])
        self.assertEqual(len(s["requests"]), 2)
        s = self.ok("ada", "POST", "/splits", {"amount": 10, "participant_handles": ["cy", "bob", "ada"]})
        self.assertEqual([x["amount"] for x in s["shares"]], [4, 3, 3])
        s = self.ok("ada", "POST", "/splits", {"amount": 5, "participant_handles": ["ada"]})
        self.assertEqual((len(s["shares"]), s["requests"]), (1, []))
        self.assertEqual(self.balance("ada"), 10000)

    def test_zero_share_requests(self):
        s = self.ok("ada", "POST", "/splits", {"amount": 1, "participant_handles": ["ada", "bob", "cy"]})
        self.assertEqual([r["amount"] for r in s["requests"]], [0, 0])
        rid = s["requests"][0]["request_id"]
        self.assertEqual(self.ok("bob", "POST", f"/requests/{rid}/pay", {})["amount"], 0)
        self.ok("cy", "POST", f"/requests/{s['requests'][1]['request_id']}/decline", status=200, key=None)

    def test_split_errors_create_nothing(self):
        bad = [({"amount": 0, "participant_handles": ["bob"]}, 422), ({"amount": 5, "participant_handles": []}, 422),
               ({"amount": 5, "participant_handles": ["bob", "bob"]}, 422),
               ({"amount": 5, "participant_handles": ["bob", "zed"]}, 404),
               ({"amount": 5, "participant_handles": "bob"}, 400), ({"amount": 5, "participant_handles": [1]}, 400),
               ({"amount": 5}, 422), ({"participant_handles": ["bob"]}, 422),
               ({"amount": 5, "participant_handles": ["bob"], "note": "x" * 201}, 422)]
        for body, status in bad:
            self.assertEqual(self.req("ada", "POST", "/splits", body)[0], status, body)
        self.assertEqual(self.ok("bob", "GET", "/requests", status=200)["requests"], [])

    def test_paid_splits_conserve_money(self):
        for amount in (1000, 7, 1, 999):
            s = self.ok("ada", "POST", "/splits", {"amount": amount, "participant_handles": ["bob", "cy", "ada"]})
            for r in s["requests"]:
                who = r["payer_handle"]
                if r["amount"]:
                    self.ok("ada", "POST", "/payments", {"to_handle": who, "amount": r["amount"]})
                self.ok(who, "POST", f"/requests/{r['request_id']}/pay", {})
        self.assertEqual(self.total(), 12500)


class Feed(Api):
    def test_visibility_rule(self):
        self.reset(fixture(settlement_operator_ids=["u_cy"]))
        pub = self.ok("ada", "POST", "/payments", {"to_handle": "bob", "amount": 1})
        prv = self.ok("ada", "POST", "/payments", {"to_handle": "bob", "amount": 2, "visibility": "private"})
        self.ok("ada", "POST", "/requests", {"payer_handle": "bob", "amount": 3})
        self.ok("ada", "POST", "/splits", {"amount": 3, "participant_handles": ["bob"]})
        feed = lambda who: [p["payment_id"] for p in self.ok(who, "GET", "/activity", status=200)["payments"]]
        self.assertEqual(feed("ada"), [prv["payment_id"], pub["payment_id"]])
        self.assertEqual(feed("bob"), [prv["payment_id"], pub["payment_id"]])
        self.assertEqual(feed("cy"), [pub["payment_id"]])
        s, b, _ = call("POST", "/auth/signup", {"email": "new@x.com", "password": "12345678", "display_name": "N"})
        self.assertEqual(feed(b["token"]), [pub["payment_id"]])
        self.assertEqual(self.ok("cy", "GET", "/requests", status=200)["requests"], [])


class Settlements(Api):
    def setUp(self):
        super().setUp()
        self.reset(fixture(settlement_operator_ids=["u_cy"]))

    def t(self, f, to, amount, **kw):
        return {"from_handle": f, "to_handle": to, "amount": amount, **kw}

    def test_permissions(self):
        body = {"transfers": [self.t("ada", "bob", 1)]}
        self.err("ada", "POST", "/settlements", body, 403, "forbidden")
        self.err("ada", "POST", "/settlements", body, 403, "forbidden", key=None)
        self.err("cy", "POST", "/settlements", body, 400, "missing_idempotency_key", key=None)
        rid = self.ok("bob", "POST", "/requests", {"payer_handle": "ada", "amount": 1})["request_id"]
        self.err("cy", "POST", f"/requests/{rid}/pay", {}, 403, "forbidden")
        self.err("cy", "POST", f"/requests/{rid}/cancel", None, 403, "forbidden", key=None)
        self.assertEqual(self.ok("cy", "GET", "/requests", status=200)["requests"], [])

    def test_net_chain_and_shape(self):
        r = self.ok("cy", "POST", "/settlements", {"transfers": [
            self.t("ada", "bob", 100, note="n", visibility="private", junk=1), self.t("bob", "cy", 2600)]})
        self.assertEqual([p["amount"] for p in r["payments"]], [100, 2600])
        self.assertTrue(all(p["settlement_id"] == r["settlement_id"] and p["request_id"] is None
                            and p["created_at"] == r["committed_at"] for p in r["payments"]))
        self.assertEqual((self.balance("ada"), self.balance("bob"), self.balance("cy")), (9900, 0, 2600))
        feed_ada = self.ok("ada", "GET", "/activity", status=200)["payments"]
        self.assertEqual(len(feed_ada), 2)  # private ada->bob as sender + public bob->cy
        self.assertEqual(len(self.ok("cy", "GET", "/activity", status=200)["payments"]), 1)  # only public cy member
        plain = self.ok("ada", "POST", "/payments", {"to_handle": "bob", "amount": 1})
        self.assertIsNone(plain["settlement_id"])

    def test_cycle_and_unaffordable_leave_no_trace(self):
        self.ok("cy", "POST", "/settlements", {"transfers": [self.t("ada", "bob", 9), self.t("bob", "cy", 9),
                                                             self.t("cy", "ada", 9)]})
        self.assertEqual(self.balance("cy"), 0)
        before = [self.balance(h) for h in ("ada", "bob", "cy")]
        self.err("cy", "POST", "/settlements", {"transfers": [self.t("bob", "ada", 2501)]}, 409,
                 "insufficient_funds", key="again")
        self.err("cy", "POST", "/settlements", {"transfers": [self.t("cy", "ada", 1)]}, 409,
                 "insufficient_funds", key="again")
        self.assertEqual([self.balance(h) for h in ("ada", "bob", "cy")], before)
        self.assertEqual(self.req("cy", "POST", "/settlements", {"transfers": [self.t("ada", "cy", 1)]},
                                  key="again")[0], 201)

    def test_validation_and_precedence(self):
        post = lambda transfers, key=None: self.req("cy", "POST", "/settlements", {"transfers": transfers})
        ok = self.t("ada", "bob", 1)
        for bad in ([], [ok] * 33, "x", None, [5], [ok, []]):
            self.assertEqual(post(bad)[0], 422, bad)
        self.assertEqual(self.req("cy", "POST", "/settlements", {})[0], 422)
        self.assertEqual(post([ok] * 32)[0], 201)
        self.assertEqual(post([self.t("zed", "bob", 1), self.t("ada", "bob", 0)])[0], 404)
        self.assertEqual(post([self.t("ada", "bob", 0), self.t("zed", "bob", 1)])[0], 422)
        self.assertEqual(post([self.t("ada", "bob", 10 ** 9 + 1)])[0], 422)
        self.assertEqual(post([self.t("ada", "bob", 10 ** 8 * 5), self.t("ada", "ada", 1)])[1]["error"]["code"],
                         "self_payment")
        self.assertEqual(post([self.t("ada", "nobody", 1)])[0], 404)
        self.assertEqual(post([{"to_handle": "bob", "amount": 1}])[0], 422)
        self.assertEqual(post([self.t(5, "bob", 1)])[0], 400)
        self.assertEqual(post([self.t("ada", "bob", 1, note=None)])[0], 422)
        self.assertEqual(post([self.t("ada", "bob", 1, visibility="x")])[0], 422)

    def test_concurrent_settlements_and_payments_conserve(self):
        out = []

        def go(i):
            body = {"transfers": [self.t("ada", "bob", 1000), self.t("bob", "ada", 500)]}
            out.append(call("POST", "/settlements", body, token=self.tok["cy"], key=f"s{i}")[0])
            call("POST", "/payments", {"to_handle": "ada", "amount": 1}, token=self.tok["bob"], key=f"p{i}")
        ts = [threading.Thread(target=go, args=(i,)) for i in range(30)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertTrue(set(out) <= {201, 409})
        self.assertEqual(self.total(), 12500)
        self.assertTrue(all(self.balance(h) >= 0 for h in self.tok))


class ExportImport(Api):
    def snapshot(self):
        return {h: (self.ok(h, "GET", "/me", status=200), self.ok(h, "GET", "/activity", status=200),
                    self.ok(h, "GET", "/requests", status=200)) for h in self.tok}

    def test_roundtrip_and_replacement(self):
        self.reset(fixture(settlement_operator_ids=["u_cy"]))
        self.ok("ada", "POST", "/payments", {"to_handle": "bob", "amount": 7, "note": "é́ 🍝 "}, key="pk")
        rid = self.ok("bob", "POST", "/requests", {"payer_handle": "ada", "amount": 9})["request_id"]
        sp = self.ok("ada", "POST", "/splits", {"amount": 5, "participant_handles": ["bob", "cy"]}, key="sk")
        st = self.ok("cy", "POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 3}]}, key="stk")
        self.err("cy", "POST", "/payments", {"to_handle": "ada", "amount": 99}, 409, "insufficient_funds", key="failed")
        s, export, _ = call("GET", "/_test/export")
        self.assertEqual((s, export["track"], export["format_version"]), (200, "pocketful", 1))
        self.assertNotIn("correct horse", str(export))
        before = self.snapshot()
        self.ok("ada", "POST", "/payments", {"to_handle": "bob", "amount": 1000})
        self.ok("ada", "POST", f"/requests/{rid}/pay", {})
        fresh = call("POST", "/auth/signup", {"email": "z@z.com", "password": "12345678", "display_name": "Z"})[1]["token"]
        for _ in range(2):
            self.assertEqual(call("POST", "/_test/import", export)[0], 204)
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(call("GET", "/me", token=fresh)[0], 401)  # destination data removed
        s, b, _ = self.req("ada", "POST", "/payments", {"to_handle": "bob", "amount": 7, "note": "é́ 🍝 "}, key="pk")
        self.assertEqual(s, 200)
        self.assertEqual(self.req("ada", "POST", "/payments", {"to_handle": "bob", "amount": 8}, key="pk")[0], 409)
        self.assertEqual(self.req("ada", "POST", "/splits", {"amount": 5, "participant_handles": ["bob", "cy"]}, key="sk")[1], sp)
        self.assertEqual(self.req("cy", "POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 3}]}, key="stk")[1], st)
        self.assertEqual(self.req("cy", "POST", "/payments", {"to_handle": "ada", "amount": 1}, key="failed")[0], 409)
        self.assertEqual(self.req("cy", "POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]})[0], 201)
        new_ids = [self.ok("ada", "POST", "/payments", {"to_handle": "bob", "amount": 1})["payment_id"] for _ in range(3)]
        known = {p["payment_id"] for p in export["state"]["payments"]}
        self.assertFalse(known & set(new_ids))
        self.assertEqual(self.total(), 12500)

    def test_import_rejections_leave_state(self):
        _, export, _ = call("GET", "/_test/export")
        self.ok("ada", "POST", "/payments", {"to_handle": "bob", "amount": 1})
        bad = [{}, {"track": "pocketful", "format_version": 1}, {**export, "track": "x"},
               {**export, "format_version": 2}, {**export, "format_version": True}, {**export, "state": []},
               {**export, "state": {}}, {**export, "state": {**export["state"], "users": "x"}}, []]
        corrupt = copy.deepcopy(export)
        corrupt["state"]["payments"] = [{"payment_id": "p", "from_user_id": "ghost"}]
        bad.append(corrupt)
        for payload in bad:
            s, b, _ = call("POST", "/_test/import", payload)
            self.assertIn(s, (400, 422), payload)
            self.assertEqual(b["error"]["code"], "validation_failed" if s == 422 else "malformed_request")
        self.assertEqual(call("POST", "/_test/import", raw=b"{nope")[0], 400)
        self.assertEqual(self.balance("ada"), 9999)


if __name__ == "__main__":
    unittest.main()
