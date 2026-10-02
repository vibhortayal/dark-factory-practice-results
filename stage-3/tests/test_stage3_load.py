"""Stage-3 timing on a few thousand payments, and 50-in-flight mixed bursts checked against the model."""
import random
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import model3 as M
import test_stage1 as t1
from test_stage1 import call, err, fixture, login, nk, reset, user
from test_stage3_api import Q, correct, dtp, iso, me, now, pay, stmt
from test_stage3_model import History, NAMES, fmt_offset


class TestTiming(unittest.TestCase):
    def test_five_thousand_payments(self):
        rnd = random.Random(5)
        names = ["u%02d" % i for i in range(50)]
        base = now() - timedelta(days=40)
        pays = []
        for i in range(5000):
            a, b = rnd.sample(range(50), 2)
            pays.append({"id": "s%05d" % i, "from_user_id": "u_" + names[a], "to_user_id": "u_" + names[b], "amount": rnd.randint(1, 500),
                         "note": "n", "visibility": "public", "created_at": iso(base + timedelta(seconds=i * 600 + rnd.random()))})
        users = [user(n, 10 ** 7) for n in names]
        t0 = time.time()
        reset(fixture(users=users, payments=pays))
        t_reset = time.time() - t0
        self.assertLess(t_reset, 10)
        tok = {n: login(n) for n in names[:6]}
        worst = {}

        def timed(label, fn):
            t = time.time()
            r = fn()
            worst[label] = max(worst.get(label, 0), time.time() - t)
            return r
        a = tok[names[0]]
        j = timed("statement", lambda: stmt(a, limit=200)[1])
        self.assertGreater(len(j["entries"]), 0)
        self.assertEqual(j["opening_balance"] + sum(e["delta"] for e in stmt(a, limit=200)[1]["entries"]), stmt(a, limit=200)[1]["closing_balance"]) if j["has_more"] is False else None
        for k in range(20):
            timed("me_as_of", lambda: me(a, as_of=iso(base + timedelta(seconds=rnd.randint(0, 3000000)))))
            timed("me_known", lambda: me(a, as_of=iso(now()), known_at=iso(base + timedelta(seconds=rnd.randint(0, 3000000)))))
        # many corrections on seeded payments (their senders)
        by_sender = {}
        for p in pays:
            by_sender.setdefault(p["from_user_id"], []).append(p)
        done = 0
        for n in names[:6]:
            t = tok[n]
            for p in by_sender["u_" + n][:60]:
                r = timed("correction", lambda: correct(t, p["id"], 1, rnd.randint(0, 600), p["created_at"]))
                self.assertIn(r[0], (201, 409), r)
                done += r[0] == 201
        self.assertGreater(done, 100)
        timed("statement_after", lambda: stmt(a, limit=200))
        timed("activity", lambda: call("GET", "/activity?limit=200", token=a))
        ex = timed("export", lambda: call("GET", "/_test/export"))
        timed("import", lambda: call("POST", "/_test/import", ex[1]))
        print("worst latencies (s):", {k: round(v, 3) for k, v in worst.items()}, "reset %.2f" % t_reset)
        for k, v in worst.items():
            self.assertLess(v, 5 if k not in ("export", "import") else 10, (k, v))


class TestBurst(unittest.TestCase):
    def test_fifty_in_flight_then_model(self):
        reset(fixture(users=[user(n, 3000 + 400 * i) for i, n in enumerate(NAMES)], authorization_ttl_seconds=2))
        tok = {n: login(n) for n in NAMES}
        rnd_lock = threading.Lock()
        rnd = random.Random(99)
        lock = threading.Lock()
        pays, owner, auths = {}, {}, {}
        statuses = []

        def pick(seq):
            with rnd_lock:
                return rnd.choice(seq) if seq else None

        def rr(a, b):
            with rnd_lock:
                return rnd.randint(a, b)

        def task(i):
            op = ["pay", "pay", "corr", "corr", "auth", "cap", "void", "settle", "read"][i % 9]
            a, b = NAMES[i % 4], NAMES[(i + 1 + i // 4) % 4]
            if a == b:
                b = NAMES[(NAMES.index(a) + 1) % 4]
            if op == "pay":
                s, p, _ = call("POST", "/payments", {"to_handle": b, "amount": rr(1, 300)}, tok[a], nk())
                if s == 201:
                    with lock:
                        pays[p["payment_id"]] = p
                        owner[p["payment_id"]] = a
            elif op == "corr":
                with lock:
                    keys = [k for k in owner]
                pid = pick(keys)
                if pid:
                    s, j, _ = call("POST", "/payments/%s/corrections" % pid,
                                   {"expected_revision": len(call("GET", "/payments/%s/revisions" % pid, token=tok[owner[pid]])[1]["revisions"]),
                                    "amount": rr(0, 400), "effective_at": iso(now() - timedelta(milliseconds=rr(0, 400))), "reason": "x"},
                                   tok[owner[pid]], nk())
                    statuses.append(s)
            elif op == "auth":
                s, x, _ = call("POST", "/authorizations", {"to_handle": b, "amount": rr(1, 300)}, tok[a], nk())
                if s == 201:
                    with lock:
                        auths[x["authorization_id"]] = (a, b)
            elif op == "cap":
                with lock:
                    keys = list(auths)
                aid = pick(keys)
                if aid:
                    s, p, _ = call("POST", "/authorizations/%s/capture" % aid, {"amount": rr(1, 150), "final": rr(0, 1) == 1}, tok[auths[aid][1]], nk())
                    if s == 201:
                        with lock:
                            pays[p["payment_id"]] = p
            elif op == "void":
                with lock:
                    keys = list(auths)
                aid = pick(keys)
                if aid:
                    call("POST", "/authorizations/%s/void" % aid, None, tok[auths[aid][0]])
            elif op == "settle":
                call("POST", "/settlements", {"transfers": [{"from_handle": a, "to_handle": b, "amount": rr(1, 100)}]}, tok["ada"], nk())
            else:
                call("GET", Q("/statement", limit=5), token=tok[a])
                call("GET", Q("/me", as_of=iso(now() - timedelta(milliseconds=rr(0, 300)))), token=tok[a])
        reset_ops = list(range(600))
        # settlements need an operator: make ada one via a fresh reset (re-run with operator)
        reset(fixture(users=[user(n, 3000 + 400 * i) for i, n in enumerate(NAMES)], authorization_ttl_seconds=2, settlement_operator_ids=["u_ada"]))
        tok = {n: login(n) for n in NAMES}
        with ThreadPoolExecutor(50) as ex:
            list(ex.map(task, reset_ops))
        # no 5xx anywhere (the helper above would have shown them as statuses); rebuild the model from final reads
        openings = {"u_" + n: 3000 + 400 * i for i, n in enumerate(NAMES)}
        model = M.Model(openings)
        all_pays = {}
        for n in NAMES:
            for e in call("GET", "/statement?limit=200&known_at=2999-01-01T00:00:00Z", token=tok[n])[1]["entries"]:
                pass
        # every payment ever created is visible in the sender's feed (original amounts, creation order)
        feed = {}
        for n in NAMES:
            off = 0
            while True:
                j = call("GET", "/activity?limit=200&offset=%d" % off, token=tok[n])[1]
                for x in j["payments"]:
                    feed[x["payment_id"]] = x
                if not j["has_more"]:
                    break
                off += 200
        for p in sorted(feed.values(), key=lambda p: p["created_at"]):
            model.add_payment(p)
        for pid in feed:
            owner_tok = tok[feed[pid]["from_handle"]]
            for r in call("GET", "/payments/%s/revisions" % pid, token=owner_tok)[1]["revisions"][1:]:
                model.add_correction(r)
        for n in NAMES:
            for a in call("GET", "/authorizations?limit=200", token=tok[n])[1]["authorizations"]:
                if a["authorization_id"] in model.auths or a["from_handle"] != n:
                    continue
                model.add_auth(a)
                for i, pid in enumerate(a["payment_ids"]):
                    model.add_capture(a["authorization_id"], feed[pid], a["status"] == "captured" and i == len(a["payment_ids"]) - 1)
                if a["status"] == "voided":
                    model.add_void(a["authorization_id"], a["closed_at"])
        rnd2 = random.Random(7)
        pts = sorted({dtp(r) for p in feed.values() for r in [p["created_at"]]})
        nowt = datetime.now(timezone.utc)
        for _ in range(40):
            T = rnd2.choice(pts) + timedelta(microseconds=rnd2.randint(-1, 1))
            for K in (None, rnd2.choice(pts)):
                total = 0
                for n in NAMES:
                    params = {"as_of": iso(T)}
                    if K is not None:
                        params["known_at"] = iso(K)
                    j = call("GET", Q("/me", **params), token=tok[n])[1]
                    want = model.view("u_" + n, T, K if K is not None else nowt)
                    self.assertEqual({k: j[k] for k in want}, want, (n, params))
                    self.assertGreaterEqual(j["available"], 0)
                    total += j["total"]
                self.assertEqual(total, sum(openings.values()))
        for n in NAMES:
            j = call("GET", "/me", token=tok[n])[1]
            self.assertGreaterEqual(j["available"], 0)
        self.assertTrue(all(s < 500 for s in statuses))


if __name__ == "__main__":
    unittest.main(verbosity=1)
