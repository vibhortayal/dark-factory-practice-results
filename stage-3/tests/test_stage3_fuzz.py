"""Instant, number and state fuzz for the stage-3 inputs: never a 5xx, own export always re-imports."""
import json
import random
import unittest
from datetime import timedelta
from urllib.parse import quote

import test_stage1 as t1
from test_stage1 import call, err, fixture, login, nk, reset, user
from test_stage3_api import Q, correct, dtp, iso, me, now, pay, stmt


def instants(rnd, n):
    out = []
    parts = lambda: ("%04d-%02d-%02d" % (rnd.choice([0, 1, 1999, 2026, 9999, 10000]), rnd.choice([0, 1, 2, 12, 13]), rnd.choice([0, 1, 28, 29, 30, 31, 32])),
                     "%02d:%02d:%02d" % (rnd.choice([0, 12, 23, 24, 25]), rnd.choice([0, 59, 60]), rnd.choice([0, 59, 60, 61])))
    for _ in range(n):
        d, t = parts()
        frac = rnd.choice(["", ".", ".5", ".123456789", "." + "9" * rnd.choice([1, 30, 300, 3000, 5000]), ".0", "." + "0" * 400])
        off = rnd.choice(["Z", "z", "+00:00", "-00:00", "+23:59", "-23:59", "+24:00", "+00:60", "+0530", "", " ", "+5", "UTC", "+99:99"])
        sep = rnd.choice(["T", "T", "t", " ", "_"])
        out.append(d + sep + t + frac + off)
    out += ["", " ", "x" * 5000, "\u0000", "2026-09-24T13:20:00+00:00\n", "%00", "9" * 5000, "-1", "1e999", "null", "[]", "{}"]
    return out


class TestFuzz(unittest.TestCase):
    def setUp(self):
        reset(fixture())
        self.ada, self.bob = login("ada"), login("bob")
        self.p = pay(self.ada, "bob", 100)[1]

    def test_query_instants(self):
        rnd = random.Random(3)
        for v in instants(rnd, 250):
            for ep, name in (("/me", "as_of"), ("/me", "known_at"), ("/statement", "from"), ("/statement", "to"), ("/statement", "known_at"),
                             ("/statement", "snapshot")):
                s, j, ct = call("GET", Q(ep, **{name: v}), token=self.ada)
                self.assertLess(s, 500, (ep, name, v[:50], s, j))
                self.assertIn(s, (200, 404, 422), (ep, name, v[:50], s))
                self.assertEqual(ct, "application/json; charset=utf-8")
        # many parameters, repeated parameters, unknown ones
        for q in ("as_of=a&as_of=b", "as_of&known_at", "as_of=%FF", "from=%00&to=%00", "snapshot=%2B&limit=1", "limit=1&limit=2&from=2020-01-01T00:00:00Z&from=bad"):
            s = call("GET", "/me?" + q, token=self.ada)[0]
            self.assertLess(s, 500)
            self.assertLess(call("GET", "/statement?" + q, token=self.ada)[0], 500)

    def test_correction_bodies(self):
        rnd = random.Random(4)
        pid = self.p["payment_id"]
        path = "/payments/%s/corrections" % pid
        vals = instants(rnd, 120) + [self.p["created_at"], iso(now())]
        for v in vals:
            body = {"expected_revision": 1, "amount": 100, "effective_at": v, "reason": "r"}
            s = call("POST", path, body, self.ada, nk())[0]
            self.assertLess(s, 500, v[:50])
        for lit in t1.number_literals():
            for field in ("expected_revision", "amount"):
                raw = ('{"expected_revision":%s,"amount":%s,"effective_at":"%s","reason":"r"}' % (
                    lit if field == "expected_revision" else "1", lit if field == "amount" else "100", self.p["created_at"])).encode()
                s, j, _ = call("POST", path, raw=raw, token=self.ada, key=nk())
                self.assertLess(s, 500, lit[:40])
                if field == "amount" and not t1.expected_valid_int(lit, 0, 10 ** 9):
                    self.assertEqual(s, 422, lit[:40])
                if field == "expected_revision" and not t1.expected_valid_int(lit, 1, 10 ** 400):
                    self.assertEqual(s, 422, lit[:40])
        # odd ids in the path, deep and huge bodies
        for pid2 in ("%00", "a/b", "%ff", "x" * 5000, "..", "%2e%2e", "p 1", "é"):
            for m, p in (("POST", "/payments/%s/corrections"), ("GET", "/payments/%s/revisions")):
                s = call(m, p % quote(pid2, safe="%"), {"expected_revision": 1} if m == "POST" else None, self.ada, nk() if m == "POST" else None)[0]
                self.assertLess(s, 500)
        deep = b'{"expected_revision":1,"amount":1,"effective_at":"%s","reason":"r","x":' % self.p["created_at"].encode() + b"[" * 800 + b"]" * 800 + b"}"
        self.assertLess(call("POST", path, raw=deep, token=self.ada, key=nk())[0], 500)
        for bad in (b"", b"null", b"[]", b'"x"', b"{", b'{"reason":"\\ud800"}'):
            self.assertLess(call("POST", path, raw=bad, token=self.ada, key=nk())[0], 500)
        for m in ("GET", "PUT", "DELETE", "PATCH"):
            self.assertLess(call(m, path, token=self.ada)[0], 500)
        self.assertLess(call("POST", "/payments/%s/revisions" % pid, {}, self.ada, nk())[0], 500)
        self.assertLess(call("POST", "/statement", {}, self.ada, nk())[0], 500)

    def test_fixture_instants(self):
        rnd = random.Random(5)
        base_p = {"id": "p", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5, "note": "", "visibility": "public"}
        for v in instants(rnd, 120):
            s = call("POST", "/_test/reset", fixture(payments=[{**base_p, "created_at": v}]))[0]
            self.assertIn(s, (204, 422), v[:50])
            if s == 204:
                self.assertTrue(dtp_ok(v))
            s = call("POST", "/_test/reset", fixture(authorizations=[{"id": "a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5,
                                                                      "status": "open", "expires_at": v}]))[0]
            self.assertIn(s, (204, 422), v[:50])
            s = call("POST", "/_test/reset", fixture(authorizations=[{"id": "a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5,
                                                                      "status": "open", "expires_at": "2999-01-01T00:00:00Z", "created_at": v}]))[0]
            self.assertIn(s, (204, 422), v[:50])
        for v in (5, None, True, [], {}, 1.5, 10 ** 40):
            for key in ("created_at",):
                self.assertEqual(call("POST", "/_test/reset", fixture(payments=[{**base_p, key: v}]))[0], 422)

    def test_long_instant_snapshots_use_the_registry_and_survive_export(self):
        reset(fixture())
        ada = login("ada")
        pay(ada, "bob", 7)
        frm = "2000-01-01T00:00:00." + "1" * 600 + "Z"
        j = stmt(ada, **{"from": frm})[1]
        tok = j["snapshot"]
        self.assertLessEqual(len(tok), 200)
        self.assertEqual(stmt(ada, snapshot=tok)[1]["entries"], j["entries"])
        ex = call("GET", "/_test/export")[1]
        self.assertTrue(ex["state"]["snapshots"])
        ada0 = ada
        reset(fixture())
        ada = login("ada")
        err(stmt(ada, snapshot=tok), 404, "not_found")
        self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        ada = ada0
        self.assertEqual(stmt(ada, snapshot=tok)[1]["entries"], j["entries"])
        # an unknown registry token is a plain 404
        err(stmt(ada, snapshot="rsnap_999"), 404, "not_found")
        err(stmt(ada, snapshot="r"), 404, "not_found")


def dtp_ok(v):
    try:
        dtp(v)
        return True
    except ValueError:
        return False


class TestMutation3(unittest.TestCase):
    """Every member of the new state (revisions, opening balances, hold lifecycle, snapshots, correction records), nine replacement values each."""

    def rich(self):
        reset(fixture(users=[user("ada", 8000), user("bob", 2500), user("cy", 1500), user("op", 0)], settlement_operator_ids=["u_op"],
                      payments=[{"id": "p_s", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 400, "note": "s", "visibility": "public",
                                 "created_at": "2021-03-01T10:00:00Z"}],
                      authorizations=[{"id": "a_s", "from_user_id": "u_cy", "to_user_id": "u_ada", "amount": 200, "status": "open",
                                       "expires_at": iso(now() + timedelta(days=2)), "created_at": "2021-04-01T00:00:00Z"},
                                      {"id": "a_c", "from_user_id": "u_cy", "to_user_id": "u_ada", "amount": 20, "status": "captured",
                                       "expires_at": iso(now() + timedelta(days=2))}]))
        self.tk = {n: login(n) for n in ("ada", "bob", "cy", "op")}
        tk = self.tk
        self.keys = []
        p = pay(tk["ada"], "bob", 500)[1]
        for i, amount in enumerate((450, 0, 520)):
            k = nk()
            body = {"expected_revision": i + 1, "amount": amount, "effective_at": p["created_at"], "reason": "c%d" % i}
            r = call("POST", "/payments/%s/corrections" % p["payment_id"], body, tk["ada"], k)
            self.keys.append(("/payments/%s/corrections" % p["payment_id"], body, tk["ada"], k))
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 900}, tk["cy"], nk())[1]["authorization_id"]
        call("POST", "/authorizations/%s/capture" % a, {"amount": 100, "final": False}, tk["bob"], nk())
        call("POST", "/authorizations/%s/void" % a, None, tk["cy"])
        call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 25}]}, tk["op"], nk())
        stmt(tk["ada"], **{"from": "2000-01-01T00:00:00." + "1" * 600 + "Z"})
        stmt(tk["bob"])
        return call("GET", "/_test/export")[1]

    def test_import_mutants(self):
        ex = self.rich()
        st = ex["state"]
        members, containers = t1.locations(st)
        keep = ("payments", "users", "authorizations", "snapshots", "secret", "idempotency")
        members = [m for m in members if m[0] in keep and not (m[0] == "idempotency" and "body_raw" in m)]
        containers = [c for c in containers if c and c[0] in keep]
        n = 0
        base_import = lambda: self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
        for kind, paths in (("set", members), ("add", containers)):
            for path in paths:
                for v in t1.SUBST:
                    m = json.loads(json.dumps(ex))
                    if kind == "set":
                        t1.put(m["state"], path, v)
                    else:
                        t1.get(m["state"], path)["zz_extra"] = v
                    base_import()
                    before = call("GET", "/_test/export")[1]
                    r = call("POST", "/_test/import", raw=json.dumps(m).encode())
                    n += 1
                    label = (kind, path, repr(v)[:20])
                    self.assertIn(r[0], (204, 422), (label, r))
                    if r[0] == 422:
                        self.assertEqual(call("GET", "/_test/export")[1], before, label)
                    else:
                        s, ex2, _ = call("GET", "/_test/export")
                        self.assertEqual(s, 200, label)
                        self.assertEqual(call("POST", "/_test/import", ex2)[0], 204, label)
                        for name, tok in self.tk.items():
                            for pth in ("/me", "/activity", "/statement", "/authorizations", Q("/me", as_of="2021-05-01T00:00:00Z"),
                                        Q("/me", known_at="2021-05-01T00:00:00Z", as_of="2999-01-01T00:00:00Z"),
                                        Q("/statement", **{"from": "2021-01-01T00:00:00Z", "to": "2999-01-01T00:00:00Z"})):
                                self.assertLess(call("GET", pth, token=tok)[0], 500, (label, pth))
                        for pth, body, tok, k in self.keys:
                            self.assertLess(call("POST", pth, body, tok, k)[0], 500, (label, pth))
                        for sn in ex["state"]["snapshots"]:
                            self.assertLess(call("GET", Q("/statement", snapshot="r" + sn), token=self.tk["ada"])[0], 500)
        print("stage-3 import mutants:", n)

    def test_reset_mutants(self):
        fx = fixture(users=[user("ada", 100), user("bob", 100), user("op", 0)], settlement_operator_ids=["u_op"],
                     payments=[{"id": "p1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5, "note": "x", "visibility": "public",
                                "created_at": "2021-01-01T00:00:00Z"}],
                     authorizations=[{"id": "a1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5, "status": "open",
                                      "expires_at": "2999-01-01T00:00:00Z", "created_at": "2021-01-01T00:00:00Z"}])
        members, containers = t1.locations(fx)
        n = 0
        for kind, paths in (("set", [m for m in members if m[0] in ("payments", "authorizations")]),
                            ("add", [c for c in containers if c and c[0] in ("payments", "authorizations")])):
            for path in paths:
                for v in t1.SUBST:
                    m = json.loads(json.dumps(fx))
                    if kind == "set":
                        t1.put(m, path, v)
                    else:
                        t1.get(m, path)["zz_extra"] = v
                    reset(fx)
                    r = call("POST", "/_test/reset", raw=json.dumps(m).encode())
                    n += 1
                    self.assertIn(r[0], (204, 422), (kind, path, v, r))
                    if r[0] == 204:
                        ex = call("GET", "/_test/export")
                        self.assertEqual(ex[0], 200, (kind, path, v))
                        self.assertEqual(call("POST", "/_test/import", ex[1])[0], 204, (kind, path, v))
                        tok = login("ada")
                        for pth in ("/me", Q("/me", as_of="2021-01-01T00:00:00Z"), "/statement"):
                            self.assertLess(call("GET", pth, token=tok)[0], 500)
        print("stage-3 reset mutants:", n)


if __name__ == "__main__":
    unittest.main(verbosity=1)
