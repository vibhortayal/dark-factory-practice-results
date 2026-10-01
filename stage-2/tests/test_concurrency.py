"""Concurrency rows: I1-I5, K9, M14, N11, N12, X6, D5."""
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from helpers import call, fixture, k, login, me, pay, reset, user


def burst(fn, n=50):
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=n) as ex:
        out = list(ex.map(fn, range(n)))
    return out, time.time() - t0


def codes(out):
    d = {}
    for r in out:
        d[r[0]] = d.get(r[0], 0) + 1
    return d


class Concurrency(unittest.TestCase):
    def setUp(self):
        reset(fixture(users=[user("ada", 1000), user("bob", 0), user("cy", 500), user("dan", 0)],
                      settlement_operator_ids=["u_dan"]))
        self.t = {h: login(h) for h in ("ada", "bob", "cy", "dan")}

    def total(self):
        return sum(me(t)["balance"] for t in self.t.values())

    def test_drain_one_wallet(self):  # I2 D5
        out, took = burst(lambda i: pay(self.t["ada"], "bob", 100))
        self.assertEqual(codes(out), {201: 10, 409: 40})
        self.assertEqual((me(self.t["ada"])["balance"], me(self.t["bob"])["balance"]), (0, 1000))
        self.assertLess(took, 5)

    def test_all_in_one_exactly_one_wins(self):
        out, _ = burst(lambda i: pay(self.t["ada"], "bob", 1000))
        self.assertEqual(codes(out), {201: 1, 409: 49})

    def test_cycle_conservation(self):  # I1
        names = ["ada", "bob", "cy"]
        out, _ = burst(lambda i: pay(self.t[names[i % 3]], names[(i + 1) % 3], 7 + i % 5))
        self.assertTrue(all(r[0] in (201, 409) for r in out))
        self.assertEqual(self.total(), 1500)
        for h in self.t:
            self.assertGreaterEqual(me(self.t[h])["balance"], 0)

    def test_same_key_once(self):  # K9
        key = k()
        out, _ = burst(lambda i: pay(self.t["ada"], "bob", 100, key=key))
        self.assertEqual(codes(out), {201: 1, 200: 49})
        self.assertEqual(len({r[3] for r in out}), 1)
        self.assertEqual(me(self.t["ada"])["balance"], 900)
        for path, tok, body in (("/requests", "bob", {"payer_handle": "ada", "amount": 5}),
                                ("/splits", "ada", {"amount": 9, "participant_handles": ["bob", "cy"]})):
            key = k()
            out, _ = burst(lambda i: call("POST", path, body, self.t[tok], key))
            self.assertEqual(codes(out), {201: 1, 200: 49})
            self.assertEqual(len({r[3] for r in out}), 1)
        self.assertEqual(len(call("GET", "/requests", token=self.t["cy"])[2]["requests"]), 1)
        self.assertEqual(len(call("GET", "/requests?direction=outgoing", token=self.t["ada"])[2]["requests"]), 2)

    def test_settlement_same_key(self):  # N11
        key = k()
        body = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]}
        out, _ = burst(lambda i: call("POST", "/settlements", body, self.t["dan"], key))
        self.assertEqual(codes(out), {201: 1, 200: 49})
        self.assertEqual(len({r[3] for r in out}), 1)
        self.assertEqual(me(self.t["bob"])["balance"], 10)

    def test_pay_race(self):  # I3 M14
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, self.t["bob"], k())[2]["request_id"]
        out, _ = burst(lambda i: call("POST", f"/requests/{rq}/pay", {}, self.t["ada"], k()))
        self.assertEqual(codes(out), {201: 1, 409: 49})
        self.assertTrue(all(r[2]["error"]["code"] == "request_not_pending" for r in out if r[0] == 409))
        self.assertEqual(me(self.t["ada"])["balance"], 900)

    def test_pay_vs_decline_vs_cancel(self):  # I3 M14
        for _ in range(5):
            rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 10}, self.t["bob"], k())[2]["request_id"]
            def act(i):
                if i % 3 == 0:
                    return call("POST", f"/requests/{rq}/pay", {}, self.t["ada"], k())
                if i % 3 == 1:
                    return call("POST", f"/requests/{rq}/decline", token=self.t["ada"])
                return call("POST", f"/requests/{rq}/cancel", token=self.t["bob"])
            out, _ = burst(act, 30)
            final = call("GET", "/requests?limit=200", token=self.t["bob"])[2]["requests"]
            r = next(x for x in final if x["request_id"] == rq)
            wins = {"paid": [x for x in out[0::3] if x[0] == 201],
                    "declined": [x for x in out[1::3] if x[0] == 200],
                    "cancelled": [x for x in out[2::3] if x[0] == 200]}
            self.assertTrue(wins[r["status"]])
            for st, w in wins.items():
                if st != r["status"]:
                    self.assertEqual(w, [])
            self.assertEqual(len(wins["paid"]) <= 1, True)
            self.assertTrue(all(x[0] in (200, 201, 409) for x in out))
        self.assertEqual(self.total(), 1500)

    def test_mixed_load_with_settlements_and_export(self):  # N12 X6 I5 D5
        def op(i):
            m = i % 6
            if m == 0:
                return pay(self.t["ada"], "bob", 30)
            if m == 1:
                return pay(self.t["bob"], "cy", 20)
            if m == 2:
                return call("POST", "/settlements", {"transfers": [
                    {"from_handle": "ada", "to_handle": "bob", "amount": 50},
                    {"from_handle": "bob", "to_handle": "cy", "amount": 60},
                    {"from_handle": "cy", "to_handle": "ada", "amount": 40}]}, self.t["dan"], k())
            if m == 3:
                s, _, b, raw = call("GET", "/_test/export")
                bal = sum(u["balance"] for u in b["state"]["users"])
                return (200 if bal == 1500 else 599, None, None, raw)
            if m == 4:
                return call("POST", "/signup-nope")
            return call("GET", "/activity", token=self.t["cy"])
        out, took = burst(op, 50)
        self.assertTrue(all(r[0] < 500 for r in out), codes(out))
        self.assertLess(took, 5)
        self.assertEqual(self.total(), 1500)
        for h in self.t:
            self.assertGreaterEqual(me(self.t[h])["balance"], 0)

    def test_failed_settlements_leave_nothing(self):  # N6
        body = {"transfers": [{"from_handle": "cy", "to_handle": "bob", "amount": 400},
                              {"from_handle": "cy", "to_handle": "ada", "amount": 400}]}
        out, _ = burst(lambda i: call("POST", "/settlements", body, self.t["dan"], k()), 20)
        self.assertEqual(codes(out), {409: 20})
        self.assertEqual(self.total(), 1500)
        self.assertEqual(call("GET", "/activity", token=self.t["cy"])[2]["payments"], [])


if __name__ == "__main__":
    unittest.main()
