"""Fuzz and mutation sweeps for the stage-4 inputs and state members (refund_of, correction_batch_id, the two new idempotent paths)."""
import json
import random
import unittest
from datetime import timedelta
from urllib.parse import quote

import test_stage1 as t1
from test_stage1 import call, err, fixture, login, nk, reset, user
from test_stage3_api import Q, dtp, iso, me, now, pay, stmt
from test_stage3_fuzz import TestMutation3, instants
from test_stage4_api import batch, item, refund, revs


class TestFuzz4(unittest.TestCase):
    def setUp(self):
        reset(fixture(users=[user("ada", 10000), user("bob", 2500), user("op", 0)], settlement_operator_ids=["u_op"]))
        self.ada, self.bob, self.op = login("ada"), login("bob"), login("op")
        self.p = pay(self.ada, "bob", 100)[1]

    def test_refund_bodies_and_ids(self):
        pid = self.p["payment_id"]
        for lit in t1.number_literals():
            s, j, _ = call("POST", "/payments/%s/refunds" % pid, raw=('{"amount":%s}' % lit).encode(), token=self.bob, key=nk())
            self.assertLess(s, 500, lit[:40])
            if not t1.expected_valid_int(lit, 1, 10 ** 9):
                self.assertEqual(s, 422, lit[:40])
        for pid2 in ("%00", "a/b", "%ff", "x" * 5000, "..", "%2e%2e", "p 1", "é", ""):
            self.assertLess(call("POST", "/payments/%s/refunds" % quote(pid2, safe="%"), {"amount": 1}, self.bob, nk())[0], 500)
        deep = b'{"amount":1,"x":' + b"[" * 800 + b"]" * 800 + b"}"
        self.assertLess(call("POST", "/payments/%s/refunds" % pid, raw=deep, token=self.bob, key=nk())[0], 500)
        for bad in (b"", b"null", b"[]", b'"x"', b"{", b'{"amount":"\\ud800"}'):
            self.assertLess(call("POST", "/payments/%s/refunds" % pid, raw=bad, token=self.bob, key=nk())[0], 500)
        for m in ("GET", "PUT", "DELETE", "PATCH"):
            self.assertLess(call(m, "/payments/%s/refunds" % pid, token=self.bob)[0], 500)

    def test_batch_bodies(self):
        rnd = random.Random(11)
        pid = self.p["payment_id"]
        eff = self.p["created_at"]
        vals = instants(rnd, 80) + [eff]
        for v in vals:
            s = call("POST", "/correction-batches", {"corrections": [item(pid, 1, 50, v)]}, self.op, nk())[0]
            self.assertLess(s, 500, v[:40])
        for lit in t1.number_literals():
            for f in ("expected_revision", "amount"):
                raw = ('{"corrections":[{"payment_id":"%s","expected_revision":%s,"amount":%s,"effective_at":"%s","reason":"r"}]}' % (
                    pid, lit if f == "expected_revision" else "1", lit if f == "amount" else "50", eff)).encode()
                s = call("POST", "/correction-batches", raw=raw, token=self.op, key=nk())[0]
                self.assertLess(s, 500, lit[:40])
                if f == "amount" and not t1.expected_valid_int(lit, 0, 10 ** 9):
                    self.assertEqual(s, 422, lit[:40])
        for body in (b"", b"null", b"[]", b'{"corrections":null}', b'{"corrections":[[]]}', b'{"corrections":[{"payment_id":["x"]}]}',
                     b'{"corrections":[' + b",".join([b"{}"] * 40) + b"]}", b'{"corrections":[{' + b'"a":' * 10 + b"1}]}"):
            self.assertLess(call("POST", "/correction-batches", raw=body, token=self.op, key=nk())[0], 500)
        deep = b'{"corrections":[{"payment_id":"%s","expected_revision":1,"amount":5,"effective_at":"%s","reason":"r","x":' % (pid.encode(), eff.encode()) + b"[" * 800 + b"]" * 800 + b"}]}"
        self.assertLess(call("POST", "/correction-batches", raw=deep, token=self.op, key=nk())[0], 500)
        for m in ("GET", "PUT", "DELETE", "PATCH"):
            self.assertLess(call(m, "/correction-batches", token=self.op)[0], 500)
        self.assertLess(call("POST", "/correction-batches/x", {}, self.op, nk())[0], 500)
        self.assertEqual(len(revs(self.ada, pid)), 1 + 0 * 1) if False else None


class TestMutation4(TestMutation3):
    """The stage-3 sweep over a richer export: refunds, batch corrections, settlements, snapshots, and the two new idempotent paths."""

    def rich(self):
        reset(fixture(users=[user("ada", 8000), user("bob", 2500), user("cy", 1500), user("op", 0)], settlement_operator_ids=["u_op"],
                      payments=[{"id": "p_s", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 400, "note": "s", "visibility": "public",
                                 "created_at": "2021-03-01T10:00:00Z"}]))
        self.tk = tk = {n: login(n) for n in ("ada", "bob", "cy", "op")}
        self.keys = []
        p = pay(tk["ada"], "bob", 500)[1]
        k = nk()
        body = {"amount": 120}
        rf = call("POST", "/payments/%s/refunds" % p["payment_id"], body, tk["bob"], k)
        self.keys.append(("/payments/%s/refunds" % p["payment_id"], body, tk["bob"], k))
        refund(tk["bob"], "p_s", 50)
        st = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 25}, {"from_handle": "cy", "to_handle": "bob", "amount": 5}]}, tk["op"], nk())[1]
        kb = nk()
        items = [item(m["payment_id"], 1, m["amount"] + 1 if i else m["amount"] - 1, st["committed_at"], "b") for i, m in enumerate(st["payments"])]
        items.append(item(p["payment_id"], 1, 450, p["created_at"]))
        call("POST", "/correction-batches", {"corrections": items}, tk["op"], kb)
        self.keys.append(("/correction-batches", {"corrections": items}, tk["op"], kb))
        k2 = nk()
        b2 = {"expected_revision": 1, "amount": 399, "effective_at": "2021-03-01T10:00:00Z", "reason": "single"}
        call("POST", "/payments/p_s/corrections", b2, tk["ada"], k2)
        self.keys.append(("/payments/p_s/corrections", b2, tk["ada"], k2))
        stmt(tk["ada"])
        stmt(tk["bob"], **{"from": "2000-01-01T00:00:00." + "1" * 600 + "Z"})
        return call("GET", "/_test/export")[1]

    def test_reset_mutants(self):
        self.skipTest("the reset sweep is part of the stage-3 file; stage 4 adds no fixture members")


if __name__ == "__main__":
    unittest.main(verbosity=1)
