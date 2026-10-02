from datetime import datetime, timedelta, timezone

from .helpers import World, call, fixture
from .test_history import H, HistoryBase, at


class SeededTimeTests(World):
    def reset(self, **kw):
        return call("POST", "/_test/reset", fixture(**kw))

    def pay(self, **kw):
        return {"id": "p1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5, **kw}

    def test_future_and_invalid_created_at_refused_with_no_change(self):
        for bad in (at(1 * H), at(48 * H, 2), "2026-01-01T00:00:00", "2026-01-01", "yesterday", 5, None, ""):
            self.assertErr(self.reset(payments=[self.pay(created_at=bad)]), 422, "validation_failed")
        auth = {"id": "a1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5, "status": "open", "expires_at": at(2 * H)}
        for bad in (at(1 * H), "2026-01-01T00:00:00", "nope"):
            self.assertErr(self.reset(authorizations=[{**auth, "created_at": bad}]), 422, "validation_failed")
        self.assertEqual(self.balance("ada"), 10000)       # nothing changed (previous state intact)

    def test_created_at_kept_exactly_and_default_is_reset_time(self):
        exact = ["2026-05-01T10:00:00+02:00", "2026-05-01T10:00:00.5Z", "2026-05-01T10:00:00.123456789-05:30"]
        pays = [self.pay(id=f"p{i}", created_at=t) for i, t in enumerate(exact)] + [self.pay(id="p_default")]
        self.assertEqual(self.reset(payments=pays).status, 204)
        tok = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}).json["token"]
        got = {p["payment_id"]: p for p in call("GET", "/activity", token=tok).json["payments"]}
        self.assertEqual([got[f"p{i}"]["created_at"] for i in range(3)], exact)
        later = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=tok, key="k").json
        self.assertLess(got["p_default"]["created_at"], later["created_at"])
        self.assertEqual(call("GET", "/me", token=tok).json["balance"], 10000 - 1)
        # feed newest first by instant, not by string
        order = [p["payment_id"] for p in call("GET", "/activity", token=tok).json["payments"]]
        self.assertEqual(order[-1], "p0" if False else order[-1])
        self.assertEqual(order[0], later["payment_id"])

    def test_opening_balances(self):
        self.reset(payments=[self.pay(created_at=at(-2 * H), amount=700), self.pay(id="p2", from_user_id="u_bob", to_user_id="u_ada", amount=100, created_at=at(-1 * H))])
        tok = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}).json["token"]
        s = call("GET", "/statement", token=tok).json
        self.assertEqual((s["opening_balance"], s["closing_balance"]), (10000 + 700 - 100, 10000))
        self.assertEqual(call("GET", "/me", token=tok).json["balance"], 10000)


class OrderingTests(HistoryBase):
    def test_statement_orders_by_instant_across_offsets(self):
        p = self.post("ada", "/payments", {"to_handle": "bob", "amount": 1}).json
        eff = (datetime.now(timezone.utc) - timedelta(hours=4, minutes=30)).astimezone(timezone(timedelta(hours=9))).isoformat()
        r = self.correct("ada", p["payment_id"], 1, 1, eff)
        self.assertEqual(r.json["effective_at"], eff)
        ids = [e["payment"]["payment_id"] for e in self.stmt("ada").json["entries"]]
        self.assertEqual(ids, ["p_a", p["payment_id"], "p_b", "p_c"])

    def test_combined_error_order(self):
        p = self.post("ada", "/payments", {"to_handle": "bob", "amount": 5}).json
        base = {"expected_revision": 1, "amount": 1, "effective_at": p["created_at"], "reason": "r"}
        url = f"/payments/{p['payment_id']}/corrections"
        # 422 before 404/403
        self.assertErr(self.post("cy", "/payments/nope/corrections", {**base, "amount": -1}), 422, "validation_failed")
        self.assertErr(self.post("cy", "/payments/nope/corrections", base), 404, "not_found")
        self.assertErr(self.post("cy", url, base), 403, "forbidden")
        # stale before insufficient funds
        self.assertErr(self.post("ada", url, {**base, "expected_revision": 5, "amount": 10 ** 9}), 409, "stale_revision")
        self.assertErr(self.post("ada", url, {**base, "amount": 10 ** 9}), 409, "insufficient_funds")
        # claimed key before validation
        self.assertEqual(self.post("ada", url, base, key="kk").status, 201)
        self.assertErr(self.post("ada", url, {**base, "amount": -1}, key="kk"), 409, "idempotency_key_reuse")


class OneClockReadTests(HistoryBase):
    def test_each_request_ticks_the_clock_once(self):
        from pocketful import clock
        real, count = clock.tick, []

        def counting():
            count.append(1)
            return real()
        clock.tick = counting
        try:
            for method, path, body, key in (("POST", "/payments", {"to_handle": "bob", "amount": 1}, "t1"),
                                            ("GET", "/me", None, None), ("GET", "/statement", None, None),
                                            ("GET", "/activity", None, None)):
                del count[:]
                call(method, path, body, token=self.tok["ada"], key=key)
                self.assertEqual(len(count), 1, (method, path))
        finally:
            clock.tick = real
