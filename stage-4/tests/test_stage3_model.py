"""Randomised histories (payments, corrections, authorizations, captures, voids, expiries) checked against the
independent model in model3.py over a grid of (as_of, known_at, from, to)."""
import random
import time
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import model3 as M
import test_stage1 as t1
from test_stage1 import call, fixture, login, nk, reset, user

NAMES = ["ada", "bob", "cy", "dee"]


def fmt_offset(d, rnd):
    """The same instant written with a random offset and spelling."""
    off = rnd.choice([0, 0, 120, -330, 60 * 14, -60 * 11])
    z = timezone(timedelta(minutes=off))
    x = d.astimezone(z)
    text = x.isoformat(timespec="microseconds")
    if off == 0 and rnd.random() < 0.5:
        text = text.replace("+00:00", "Z")
    if rnd.random() < 0.15:
        text = text.replace("T", "t")
    return text


def q(path, **params):
    parts = ["%s=%s" % (k, quote(str(v), safe="")) for k, v in params.items() if v is not None]
    return path + ("?" + "&".join(parts) if parts else "")


class History:
    def __init__(self, seed, steps, ttl=600, pause=False, bal=6000, scale=1, operator=None):
        self.rnd = random.Random(seed)
        self.scale = scale
        reset(fixture(users=[user(n, bal + 100 * i) for i, n in enumerate(NAMES)], authorization_ttl_seconds=ttl,
                      settlement_operator_ids=["u_" + operator] if operator else []))
        self.tok = {n: login(n) for n in NAMES}
        self.uid = {n: "u_" + n for n in NAMES}
        self.model = M.Model({self.uid[n]: bal + 100 * i for i, n in enumerate(NAMES)})
        self.auth_state = {}
        self.pay_owner = {}
        self.stats = {"corrections": 0, "overdraft": 0, "stale": 0, "insufficient": 0, "caps": 0, "voids": 0}
        self.last = None
        for _ in range(steps):
            self.step(pause)

    def now(self):
        return datetime.now(timezone.utc) + timedelta(milliseconds=1)

    def step(self, pause):
        r = self.rnd
        op = r.choices(["pay", "corr", "auth", "cap", "void", "sleep"], [34, 30, 12, 12, 5, 7])[0]
        a, b = r.sample(NAMES, 2)
        if op == "pay":
            s, p, _ = call("POST", "/payments", {"to_handle": b, "amount": r.randint(1, 900 // self.scale)}, self.tok[a], nk())
            if s == 201:
                self.model.add_payment(p)
                self.pay_owner[p["payment_id"]] = a
        elif op == "corr" and self.pay_owner:
            self.correct()
        elif op == "auth":
            s, x, _ = call("POST", "/authorizations", {"to_handle": b, "amount": r.randint(1, 700 // self.scale)}, self.tok[a], nk())
            if s == 201:
                self.model.add_auth(x)
                self.auth_state[x["authorization_id"]] = {"from": a, "to": b, "open": True, "remaining": x["amount"]}
        elif op == "cap" and self.auth_state:
            open_ids = [k for k, v in self.auth_state.items() if v["open"]]
            if open_ids:
                aid = r.choice(open_ids)
                st = self.auth_state[aid]
                amount = r.randint(1, st["remaining"])
                final = r.random() < 0.4
                body = {"amount": amount, "final": final}
                s, p, _ = call("POST", "/authorizations/%s/capture" % aid, body, self.tok[st["to"]], nk())
                if s == 201:
                    closing = final or amount == st["remaining"]
                    self.model.add_payment(p)
                    self.model.add_capture(aid, p, closing)
                    st["remaining"] -= amount
                    if closing:
                        st["open"] = False
                    self.stats["caps"] += 1
                elif s == 409:
                    st["open"] = False  # expired by the clock
        elif op == "void" and self.auth_state:
            open_ids = [k for k, v in self.auth_state.items() if v["open"]]
            if open_ids:
                aid = r.choice(open_ids)
                st = self.auth_state[aid]
                s, x, _ = call("POST", "/authorizations/%s/void" % aid, None, self.tok[st["from"]])
                if s == 200 and x["status"] == "voided":
                    self.model.add_void(aid, x["closed_at"])
                    st["open"] = False
                    self.stats["voids"] += 1
                elif s == 409:
                    st["open"] = False
        elif op == "sleep" and pause:
            time.sleep(r.choice([0.2, 0.4, 0.7]))

    def correct(self):
        r = self.rnd
        pid = r.choice(list(self.pay_owner))
        owner = self.pay_owner[pid]
        p = self.model.payments[pid]
        latest = p["revs"][-1][0]
        expected = latest if r.random() < 0.85 else max(1, latest - 1)
        amount = r.choice([0, r.randint(1, 1200 // self.scale), r.randint(1, 300 // self.scale)])
        first = min(x["created"] for x in self.model.payments.values()) if False else p["revs"][0][2] - timedelta(minutes=r.choice([0, 0, 5, 60]))
        span = (self.now() - first).total_seconds()
        eff = first + timedelta(seconds=r.random() * max(span, 0.001))
        eff = min(eff, self.now() - timedelta(milliseconds=2))
        eff_text = fmt_offset(eff, r)
        body = {"expected_revision": expected, "amount": amount, "effective_at": eff_text, "reason": "fix %d" % r.randint(1, 99)}
        sender, receiver = p["from"], p["to"]
        latest_amount = p["revs"][-1][1]
        diff = amount - latest_amount
        # what the service must answer, from the model
        expect = 201
        if expected != latest:
            expect = "stale_revision"
        elif amount < self.model.refunded(pid):
            expect = "refund_exceeds_payment"
        else:
            su = call("GET", "/me", token=self.tok[owner])[1]
            ru = call("GET", "/me", token=self.tok[[n for n in NAMES if self.uid[n] == receiver][0]])[1]
            if diff > 0 and su["available"] < diff or diff < 0 and ru["available"] < -diff:
                expect = "insufficient_funds"
            else:
                cand = (latest + 1, amount, M.dt(eff_text), self.now(), eff_text, "")
                if self.model.would_overdraw(sender, {pid: cand}, self.now()) or self.model.would_overdraw(receiver, {pid: cand}, self.now()):
                    expect = "historical_overdraft"
        s, j, _ = call("POST", "/payments/%s/corrections" % pid, body, self.tok[owner], nk())
        if expect == 201:
            assert s == 201, (s, j, body, pid)
            self.model.add_correction(j)
            self.stats["corrections"] += 1
            assert j["effective_at"] == eff_text and j["revision"] == latest + 1
        else:
            assert s in (409, 422) and j["error"]["code"] == expect, (s, j, expect, body)
            self.stats[{"stale_revision": "stale", "insufficient_funds": "insufficient", "historical_overdraft": "overdraft",
                        "refund_exceeds_payment": "stale"}[expect]] += 1

    # ---- the grid
    def points(self):
        pts = set()
        for p in self.model.payments.values():
            for r in p["revs"]:
                pts.update([r[2], r[3]])
        for a in self.model.auths.values():
            pts.update([a["created"], a["expires"]])
            pts.update(t for t, _ in a["caps"])
            if a["void"]:
                pts.add(a["void"])
        out = set()
        for t in pts:
            out.update([t, t - timedelta(microseconds=1), t + timedelta(microseconds=1)])
        return sorted(out)

    def compare(self, n_asof=10, n_known=6, n_win=10):
        r = self.rnd
        pts = self.points()
        if not pts:
            return
        first, last = pts[0], pts[-1]
        extra = [first - timedelta(seconds=5), last + timedelta(hours=1), last + timedelta(days=400)]
        pool = pts + extra
        for _ in range(n_asof):
            T = r.choice(pool)
            for _ in range(n_known):
                K = r.choice(pool + [None])
                T_text = fmt_offset(T, r)
                for n in NAMES:
                    params = {"as_of": T_text}
                    if K is not None:
                        params["known_at"] = fmt_offset(K, r)
                    s, j, _ = call("GET", q("/me", **params), token=self.tok[n])
                    assert s == 200, (s, j, params)
                    want = self.model.view(self.uid[n], T, K if K is not None else M.INF if False else self.now())
                    got = {k: j[k] for k in ("balance", "total", "available", "held")}
                    assert got == want, (n, params, got, want)
                    assert j["as_of"] == params["as_of"] and j.get("known_at") == params.get("known_at")
        # current values are the same function at (now, now)
        now = self.now()
        for n in NAMES:
            j = call("GET", "/me", token=self.tok[n])[1]
            want = self.model.view(self.uid[n], now, now)
            assert {k: j[k] for k in ("balance", "total", "available", "held")} == want, (n, j, want)
        for _ in range(n_win):
            frm = r.choice(pool + [None])
            to = r.choice(pool + [None])
            K = r.choice(pool + [None])
            if frm is not None and to is not None and frm > to:
                frm, to = to, frm
            for n in NAMES:
                params = {}
                if frm is not None:
                    params["from"] = fmt_offset(frm, r)
                if to is not None:
                    params["to"] = fmt_offset(to, r)
                if K is not None:
                    params["known_at"] = fmt_offset(K, r)
                s, j, _ = call("GET", q("/statement", **params), token=self.tok[n])
                assert s == 200, (s, j, params)
                to_m = to if to is not None else self.now() + timedelta(seconds=1)
                K_m = K if K is not None else self.now()
                opening, entries, closing = self.model.statement(self.uid[n], frm, to_m, K_m)
                assert j["opening_balance"] == opening and j["closing_balance"] == closing, (n, params, j["opening_balance"], opening, j["closing_balance"], closing)
                got = [(e["payment"]["payment_id"], e["delta"], e["balance_after"], e["revision"], e["effective_at"], e["recorded_at"], e["payment"]["amount"])
                       for e in j["entries"]]
                want = [(e["payment_id"], e["delta"], e["balance_after"], e["revision"], e["effective_at"], e["recorded_at"], e["amount"]) for e in entries]
                if len(want) <= 50:
                    assert got == want, (n, params, got, want)
                assert opening + sum(e["delta"] for e in entries) == closing
                # paging: pieces of the same window
                if entries:
                    pages, off = [], 0
                    while True:
                        s2, j2, _ = call("GET", q("/statement", snapshot=j["snapshot"], limit=3, offset=off), token=self.tok[n])
                        assert s2 == 200 and j2["opening_balance"] == opening and j2["closing_balance"] == closing
                        pages += [(e["payment"]["payment_id"], e["balance_after"]) for e in j2["entries"]]
                        if not j2["has_more"]:
                            break
                        off += 3
                    assert pages == [(e["payment_id"], e["balance_after"]) for e in entries]


class TestModel(unittest.TestCase):
    def run_seed(self, seed, steps, **kw):
        h = History(seed, steps, **kw)
        h.compare()
        return h

    def test_seed_1(self):
        h = self.run_seed(1, 120)
        self.assertGreater(h.stats["corrections"], 5)

    def test_seed_2(self):
        h = self.run_seed(2, 160)
        self.assertGreater(h.stats["corrections"], 5)

    def test_seed_3_with_expiry(self):
        h = self.run_seed(3, 90, ttl=1, pause=True)
        self.assertGreater(h.stats["caps"] + h.stats["voids"], 1)

    def test_seed_4(self):
        h = self.run_seed(4, 200)
        print("seed 4 stats:", h.stats)

    def test_tight_wallets_force_refusals(self):
        total = {"overdraft": 0, "insufficient": 0, "stale": 0, "corrections": 0}
        for seed in range(10, 16):
            h = self.run_seed(seed, 150, bal=700, scale=2)
            for k in total:
                total[k] += h.stats[k]
        print("tight stats:", total)
        self.assertGreater(total["overdraft"], 0)
        self.assertGreater(total["insufficient"], 0)

    def test_tight_wallets_with_expiry(self):
        total = {"overdraft": 0, "insufficient": 0}
        for seed in range(20, 24):
            h = self.run_seed(seed, 110, ttl=1, pause=True, bal=800, scale=2)
            for k in total:
                total[k] += h.stats[k]
        print("tight expiry stats:", total)

    def test_seed_5_with_expiry(self):
        h = self.run_seed(5, 110, ttl=2, pause=True)
        print("seed 5 stats:", h.stats)


if __name__ == "__main__":
    unittest.main(verbosity=1)
