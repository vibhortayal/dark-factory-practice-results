"""Rows A5, A6, B: invariants under concurrency, and no 5xx on malformed input."""
import itertools
import threading

from .base import ApiTestCase
from .support import fixture, user


def run_parallel(fns):
    out = [None] * len(fns)

    def wrap(i, fn):
        out[i] = fn()
    threads = [threading.Thread(target=wrap, args=(i, f)) for i, f in enumerate(fns)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return out


class ConcurrencyTests(ApiTestCase):
    def test_overspend_exactly_k_succeed(self):
        self.reset(fixture(users=[user("ada", 1000), user("bob", 0), user("cy", 0)]))
        res = run_parallel([lambda i=i: self.pay("ada", "bob", 100, "k%d" % i) for i in range(40)])
        codes = sorted(r[0] for r in res)
        self.assertEqual(codes, [201] * 10 + [409] * 30)
        self.assertEqual((self.balance("ada"), self.balance("bob")), (0, 1000))

    def test_pay_request_once(self):
        rid = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 50}, who="bob", key="r")[1]["request_id"]
        res = run_parallel([lambda i=i: self.call("POST", "/requests/%s/pay" % rid, {}, who="ada", key="p%d" % i)
                            for i in range(20)])
        self.assertEqual(sorted(r[0] for r in res), [201] + [409] * 19)
        self.assertEqual({r[1]["error"]["code"] for r in res if r[0] == 409}, {"request_not_pending"})
        self.assertEqual(self.balance("ada"), 9950)

    def test_pay_same_key_concurrent(self):
        rid = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 50}, who="bob", key="r")[1]["request_id"]
        res = run_parallel([lambda: self.call("POST", "/requests/%s/pay" % rid, {}, who="ada", key="same")
                            for _ in range(20)])
        self.assertEqual(sorted(r[0] for r in res), [200] * 19 + [201])
        self.assertEqual(len({str(r[1]) for r in res}), 1)
        self.assertEqual(self.balance("ada"), 9950)

    def test_pay_decline_cancel_race(self):
        rid = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 50}, who="bob", key="r")[1]["request_id"]
        fns = [lambda: self.call("POST", "/requests/%s/pay" % rid, {}, who="ada", key="p"),
               lambda: self.call("POST", "/requests/%s/decline" % rid, who="ada"),
               lambda: self.call("POST", "/requests/%s/cancel" % rid, who="bob")] * 5
        run_parallel(fns)
        final = self.call("GET", "/requests", who="ada")[1]["requests"][0]["status"]
        self.assertIn(final, ("paid", "declined", "cancelled"))
        self.assertEqual(self.balance("ada"), 9950 if final == "paid" else 10000)

    def test_storm_conserves_total(self):
        self.reset(fixture(users=[user("ada", 300), user("bob", 300), user("cy", 300)],
                           settlement_operator_ids=["u_ada"]))
        names = ["ada", "bob", "cy"]
        counter = itertools.count()

        def job(i):
            a, b = names[i % 3], names[(i + 1) % 3]
            if i % 4 == 0:
                return self.call("POST", "/settlements", {"transfers": [
                    {"from_handle": a, "to_handle": b, "amount": 70},
                    {"from_handle": b, "to_handle": names[(i + 2) % 3], "amount": 30}]},
                    who="ada", key="s%d" % next(counter))
            return self.pay(a, b, 40 + i % 50, "p%d" % next(counter))
        res = run_parallel([lambda i=i: job(i) for i in range(150)])
        self.assertTrue(all(r[0] in (200, 201, 403, 409) for r in res))
        balances = [self.balance(n) for n in names]
        self.assertEqual(sum(balances), 900)
        self.assertTrue(all(b >= 0 for b in balances))

    def test_no_5xx_on_garbage(self):
        bodies = [b"", b"null", b"[]", b"1", b'"s"', b"{", b"\xff\xfe", b'{"amount":NaN}',
                  b'{"to_handle":"bob","amount":1e999}', b'{"to_handle":"bob","amount":"\\ud800"}',
                  b'{"to_handle":"\\ud800","amount":1}', b"[" * 5000, b'{"note":"\\ud800"}',
                  b'{"to_handle":"bob","amount":' + b"9" * 5000 + b"}",
                  b'{"transfers":[{"from_handle":{},"to_handle":[],"amount":{}}]}',
                  b'{"participant_handles":[[1]],"amount":5}']
        paths = ["/payments", "/requests", "/splits", "/settlements", "/requests/x/pay", "/auth/signup",
                 "/auth/login", "/_test/reset", "/_test/import", "/requests/%ff/pay"]
        for path in paths:
            for raw in bodies:
                s, _, _ = self.call("POST", path, raw=raw, who="ada", key="g")
                self.assertLess(s, 500, (path, raw[:30]))
        self.reset()
        for path in ("/me?limit=%ff", "/activity?offset=%00", "/requests?status=%ff&direction=%zz"):
            self.assertLess(self.call("GET", path, who="ada")[0], 500)
        self.assertLess(self.call("GET", "/me", headers={"Authorization": "Bearer é".encode("latin-1").decode("latin-1")})[0], 500)
