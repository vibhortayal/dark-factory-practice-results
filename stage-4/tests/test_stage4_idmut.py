"""Id-member mutation sweep: every id-typed member of every record and stored response of all ten idempotent paths."""
import json
import unittest
from datetime import timedelta

import test_stage1 as t1
from test_stage1 import call, fixture, login, nk, reset, user
from test_stage3_api import Q, iso, me, now, pay, stmt
from test_stage4_api import item, refund

ID_SCALARS = {"id", "payment_id", "request_id", "authorization_id", "settlement_id", "refund_of", "split_id", "correction_batch_id",
              "batch_id", "user_id", "from_user_id", "to_user_id", "requester_id", "payer_id"}
ID_LISTS = {"payment_ids", "request_ids"}
KIND = {"payment_id": "payment", "refund_of": "payment", "payment_ids": "payment", "request_id": "request", "request_ids": "request",
        "authorization_id": "auth", "settlement_id": "settlement", "split_id": "split", "correction_batch_id": "batch", "batch_id": "batch",
        "user_id": "user", "from_user_id": "user", "to_user_id": "user", "requester_id": "user", "payer_id": "user"}
CONTAINER_KIND = {"users": "user", "payments": "payment", "requests": "request", "authorizations": "auth", "settlements": "settlement",
                  "splits": "split"}


def collect(node, path, out):
    """Paths of every id-typed member (path tuple, kind)."""
    if isinstance(node, dict):
        for k, v in node.items():
            p = path + (k,)
            if k in ID_SCALARS and (isinstance(v, str)):
                kind = KIND.get(k) or CONTAINER_KIND.get(path[1] if len(path) > 1 else "")
                out.append((p, kind or "unknown"))
            elif k in ID_LISTS and isinstance(v, list):
                for i, x in enumerate(v):
                    if isinstance(x, str):
                        out.append((p + (i,), KIND[k]))
            elif k == "tokens" and path == ("state",):
                for tk, uid in v.items():
                    out.append((p + (tk,), "user"))
            elif k in ("snapshots", "counters", "secret"):
                continue
            else:
                collect(v, p, out)
    elif isinstance(node, list):
        for i, x in enumerate(node):
            collect(x, path + (i,), out)


def put(tree, path, v):
    node = tree
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = v


def get(tree, path):
    node = tree
    for k in path:
        node = node[k]
    return node


def ledger_ids(state):
    ids = {"user": {u["id"] for u in state["users"]}, "payment": {p["id"] for p in state["payments"]},
           "request": {r["id"] for r in state["requests"]}, "auth": {a["id"] for a in state["authorizations"]},
           "settlement": {s["id"] for s in state["settlements"]}, "split": {s["id"] for s in state["splits"]},
           "batch": {c["batch_id"] for p in state["payments"] for c in p["corrections"] if c.get("batch_id")}}
    return ids


def walk_response_ids(node, bad, known):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ID_SCALARS:
                if v is not None and not (isinstance(v, str) and 1 <= len(v) <= 64 and v in known):
                    bad.append((k, v))
            elif k in ID_LISTS:
                for x in v:
                    if not (isinstance(x, str) and 1 <= len(x) <= 64 and x in known):
                        bad.append((k, x))
            else:
                walk_response_ids(v, bad, known)
    elif isinstance(node, list):
        for x in node:
            walk_response_ids(x, bad, known)


class TestIdSweep(unittest.TestCase):
    def rich(self):
        reset(fixture(users=[user("ada", 9000), user("bob", 2500), user("cy", 1500), user("op", 100)], settlement_operator_ids=["u_op"],
                      payments=[{"id": "p_s", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 400, "note": "s", "visibility": "public",
                                 "created_at": "2021-03-01T10:00:00Z"}],
                      requests=[{"id": "rq_s", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 20, "note": "", "status": "pending"}]))
        self.tk = tk = {n: login(n) for n in ("ada", "bob", "cy", "op")}
        self.keys = []

        def post(path, body, tok):
            k = nk()
            r = call("POST", path, body, tok, k)
            assert r[0] == 201, (path, r)
            self.keys.append((path, body, tok, k))
            return r[1]
        p = post("/payments", {"to_handle": "bob", "amount": 500}, tk["ada"])
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 70}, tk["bob"], nk())[1]["request_id"]
        post("/requests/%s/pay" % rq, {}, tk["ada"])
        post("/requests", {"payer_handle": "cy", "amount": 5}, tk["ada"])
        post("/splits", {"amount": 30, "participant_handles": ["ada", "bob", "cy"]}, tk["ada"])
        st = post("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 25}, {"from_handle": "cy", "to_handle": "bob", "amount": 5}]}, tk["op"])
        a = post("/authorizations", {"to_handle": "bob", "amount": 900}, tk["cy"])["authorization_id"]
        post("/authorizations/%s/capture" % a, {"amount": 100, "final": False}, tk["bob"])
        call("POST", "/authorizations/%s/void" % a, None, tk["cy"])
        post("/payments/%s/corrections" % p["payment_id"], {"expected_revision": 1, "amount": 450, "effective_at": p["created_at"], "reason": "c"}, tk["ada"])
        post("/payments/%s/refunds" % p["payment_id"], {"amount": 100}, tk["bob"])
        post("/correction-batches", {"corrections": [item(m["payment_id"], 1, m["amount"] - 1, st["committed_at"]) for m in st["payments"]]}, tk["op"])
        stmt(tk["ada"], limit=2)
        return call("GET", "/_test/export")[1]

    def check_after_accept(self, label, tokens_by_user):
        s, ex2, _ = call("GET", "/_test/export")
        self.assertEqual(s, 200, label)
        self.assertEqual(call("POST", "/_test/import", ex2)[0], 204, label)
        known = set().union(*ledger_ids(ex2["state"]).values())
        for path, body, tok, k in self.keys:
            r = call("POST", path, body, tok, k)
            self.assertLess(r[0], 500, (label, path))
            if isinstance(r[1], dict) and r[0] == 200:  # a first use (201) creates new records of its own
                bad = []
                walk_response_ids(r[1], bad, known)
                self.assertEqual(bad, [], (label, path, bad))
        known = set().union(*ledger_ids(call("GET", "/_test/export")[1]["state"]).values())  # first uses above created records of their own
        for name, tok in self.tk.items():
            for pth in ("/activity?limit=200", "/requests?limit=200", "/authorizations?limit=200", "/statement?limit=200"):
                r = call("GET", pth, token=tok)
                self.assertLess(r[0], 500, (label, pth))
                if r[0] == 200:
                    bad = []
                    walk_response_ids(r[1], bad, known)
                    self.assertEqual(bad, [], (label, pth, bad))
            for pid in ex2["state"]["payments"]:
                r = call("GET", "/payments/%s/revisions" % pid["id"], token=tok)
                self.assertLess(r[0], 500)
                if r[0] == 200:
                    bad = []
                    walk_response_ids(r[1], bad, known)
                    self.assertEqual(bad, [], (label, "revisions", bad))

    def test_id_members(self):
        ex = self.rich()
        found = []
        collect(ex, (), found)
        ids = ledger_ids(ex["state"])
        kinds = sorted(ids)
        mutants = refused = accepted = 0
        by_kind_member = {}
        for path, kind in found:
            by_kind_member.setdefault(path[-1] if not isinstance(path[-1], int) else path[-2], 0)
            by_kind_member[path[-1] if not isinstance(path[-1], int) else path[-2]] += 1
            cur = get(ex, path)
            same = sorted(v for v in ids.get(kind, ()) if v != cur)
            other = sorted(v for k2 in kinds if k2 != kind for v in ids[k2] if v != cur)
            values = [("empty", ""), ("len64", "z" * 64), ("len65", "z" * 65), ("len300", "z" * 300)]
            if same:
                values.append(("same-kind", same[0]))
                values.append(("same-kind2", same[-1]))
            if other:
                values.append(("other-kind", other[0]))
            for label, v in values:
                m = json.loads(json.dumps(ex))
                put(m, path, v)
                self.assertEqual(call("POST", "/_test/import", ex)[0], 204)
                before = call("GET", "/_test/export")[1]
                r = call("POST", "/_test/import", raw=json.dumps(m).encode())
                mutants += 1
                where = (".".join(str(x) for x in path), label)
                self.assertIn(r[0], (204, 422), (where, r))
                if label in ("empty", "len65", "len300", "len64") and kind != "unknown":
                    # an unknown 64-character id names nothing; the others are not ids at all
                    if label != "len64" or "id" not in path[-1:]:
                        self.assertEqual(r[0], 422, (where, r))
                if r[0] == 422:
                    refused += 1
                    self.assertEqual(call("GET", "/_test/export")[1], before, where)
                else:
                    accepted += 1
                    self.check_after_accept(where, None)
        print("id sweep: %d id members, %d mutants, %d refused, %d accepted; members: %s" % (len(found), mutants, refused, accepted, by_kind_member))
        self.assertGreater(mutants, 700)


if __name__ == "__main__":
    unittest.main(verbosity=1)
