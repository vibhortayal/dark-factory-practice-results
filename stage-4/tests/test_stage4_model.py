"""Randomised histories with refunds, settlements and batch corrections, predicted by the independent model."""
import random
import unittest
from datetime import datetime, timedelta, timezone

import model3 as M
import test_stage3_model as m3
from test_stage1 import call, nk
from test_stage3_api import iso

NAMES = m3.NAMES


class History4(m3.History):
    def __init__(self, seed, steps, **kw):
        self.settlements = {}      # settlement id -> [payment ids]
        self.linked = []           # captures, refunds, settlement members (immutable for single corrections)
        self.stats4 = {"refund_ok": 0, "refund_refused": 0, "batch_ok": 0, "batch_refused": 0, "single_linked": 0}
        self.codes = {}
        super().__init__(seed, steps, operator="dee", **kw)

    def note(self, code):
        self.codes[code] = self.codes.get(code, 0) + 1

    def available(self, name):
        return call("GET", "/me", token=self.tok[name])[1]["available"]

    def name_of(self, uid):
        return [n for n in NAMES if self.uid[n] == uid][0]

    def step(self, pause):
        r = self.rnd
        op = r.choices(["base", "refund", "settle", "batch", "linked"], [50, 14, 8, 20, 8])[0]
        if op == "base":
            return super().step(pause)
        if op == "refund":
            return self.do_refund()
        if op == "settle":
            return self.do_settle()
        if op == "batch":
            return self.do_batch()
        return self.do_linked()

    # --- observations feeding the model
    def feed_payment(self, p):
        self.model.add_payment(p)
        if p.get("refund_of") or p.get("settlement_id") or p.get("authorization_id"):
            self.linked.append(p["payment_id"])

    def do_refund(self):
        r = self.rnd
        if not self.model.payments:
            return
        pid = r.choice(list(self.model.payments))
        view = self.model.payments[pid]["view"]
        receiver = self.name_of(view["to_user_id"])
        caller = receiver if r.random() < 0.85 else r.choice(NAMES)
        latest = self.model.payments[pid]["revs"][-1][1]
        amount = r.choice([r.randint(1, max(1, latest)), max(1, latest - self.model.refunded(pid)), r.randint(1, 200)])
        if view.get("refund_of"):
            expect = "invalid_refund_target"
        elif caller != receiver:
            expect = "forbidden"
        elif self.model.refunded(pid) + amount > latest:
            expect = "refund_exceeds_payment"
        elif self.available(receiver) < amount:
            expect = "insufficient_funds"
        else:
            expect = 201
        s, j, _ = call("POST", "/payments/%s/refunds" % pid, {"amount": amount}, self.tok[caller], nk())
        if expect == 201:
            assert s == 201, (s, j, pid, amount)
            assert j["refund_of"] == pid and j["from_user_id"] == view["to_user_id"] and j["to_user_id"] == view["from_user_id"]
            self.feed_payment(j)
            self.stats4["refund_ok"] += 1
        else:
            assert j["error"]["code"] == expect, (s, j, expect)
            self.stats4["refund_refused"] += 1
        self.note(expect)

    def do_settle(self):
        r = self.rnd
        n = r.randint(1, 3)
        transfers = []
        for _ in range(n):
            a, b = r.sample(NAMES, 2)
            transfers.append({"from_handle": a, "to_handle": b, "amount": r.randint(1, 250)})
        s, j, _ = call("POST", "/settlements", {"transfers": transfers}, self.tok["dee"], nk())
        if s == 201:
            self.settlements[j["settlement_id"]] = [p["payment_id"] for p in j["payments"]]
            for p in j["payments"]:
                self.feed_payment(p)

    def do_linked(self):
        r = self.rnd
        if not self.linked:
            return
        pid = r.choice(self.linked)
        view = self.model.payments[pid]["view"]
        caller = r.choice(NAMES)
        sender = self.name_of(view["from_user_id"])
        eff = iso(self.now() - timedelta(milliseconds=1))
        s, j, _ = call("POST", "/payments/%s/corrections" % pid, {"expected_revision": 1, "amount": 5, "effective_at": eff, "reason": "x"},
                       self.tok[caller], nk())
        expect = "linked_payment_immutable" if caller == sender else "forbidden"
        assert s in (403, 422) and j["error"]["code"] == expect, (s, j, expect)
        self.stats4["single_linked"] += 1

    def do_batch(self):
        r = self.rnd
        pool = list(self.model.payments)
        if not pool:
            return
        chosen = []
        used = set()
        for _ in range(r.randint(1, 4)):
            pid = r.choice(pool)
            view = self.model.payments[pid]["view"]
            sid = view.get("settlement_id")
            group = [pid]
            if sid:
                group = list(self.settlements.get(sid, [pid]))
                if r.random() < 0.1 and len(group) > 1:
                    group = group[:1]   # incomplete on purpose
            for g in group:
                if g not in used:
                    used.add(g)
                    chosen.append(g)
        if r.random() < 0.05:
            chosen = chosen[:1]
        first = min(self.model.payments[p]["revs"][0][2] for p in chosen) - timedelta(minutes=r.choice([0, 0, 3]))
        span = max((self.now() - first).total_seconds(), 0.001)
        base_eff = min(first + timedelta(seconds=r.random() * span), self.now() - timedelta(milliseconds=2))
        items, meta = [], []
        groups_eff = {}
        for pid in chosen:
            p = self.model.payments[pid]
            latest = p["revs"][-1]
            sid = p["view"].get("settlement_id")
            if sid in groups_eff:
                eff = groups_eff[sid]
                if r.random() < 0.05:
                    eff = eff + timedelta(microseconds=1)
            else:
                eff = base_eff if r.random() < 0.5 else min(first + timedelta(seconds=r.random() * span), self.now() - timedelta(milliseconds=2))
                if sid:
                    groups_eff[sid] = eff
            text = m3.fmt_offset(eff, r)
            expected = latest[0] if r.random() < 0.9 else latest[0] + 1
            amount = r.choice([latest[1], 0, r.randint(1, 500), r.randint(1, 120)])
            items.append({"payment_id": pid, "expected_revision": expected, "amount": amount, "effective_at": text, "reason": "b%d" % r.randint(1, 9)})
            meta.append((pid, p, latest, expected, amount, M.dt(text), text))
        expect = self.predict(meta, chosen)
        s, j, _ = call("POST", "/correction-batches", {"corrections": items}, self.tok["dee"], nk())
        if expect == 201:
            assert s == 201, (s, j, items)
            rec = j["recorded_at"]
            assert [x["payment_id"] for x in j["revisions"]] == chosen
            for (pid, p, latest, expected, amount, eff, text), rv in zip(meta, j["revisions"]):
                assert rv["recorded_at"] == rec and rv["correction_batch_id"] == j["correction_batch_id"] and rv["revision"] == latest[0] + 1
                assert M.dt(rec) > latest[3]
                self.model.add_correction(rv)
            self.stats4["batch_ok"] += 1
        else:
            assert j["error"]["code"] == expect, (s, j, expect, items)
            self.stats4["batch_refused"] += 1
        self.note(expect)

    def predict(self, meta, chosen):
        model = self.model
        for pid, p, latest, expected, amount, eff, text in meta:
            if p["view"].get("authorization_id") or p["view"].get("refund_of"):
                return "linked_payment_immutable"
            if expected != latest[0]:
                return "stale_revision"
            if amount < model.refunded(pid):
                return "refund_exceeds_payment"
        present = set(chosen)
        sids = {p["view"]["settlement_id"] for _, p, *_ in meta if p["view"].get("settlement_id")}
        for sid in sids:
            if any(m not in present for m in self.settlements[sid]):
                return "incomplete_settlement"
        for sid in sids:
            es = {eff for _, p, _, _, _, eff, _ in meta if p["view"].get("settlement_id") == sid}
            if len(es) > 1:
                return "validation_failed"
        net = {}
        for pid, p, latest, expected, amount, eff, text in meta:
            d = amount - latest[1]
            net[p["from"]] = net.get(p["from"], 0) - d
            net[p["to"]] = net.get(p["to"], 0) + d
        for uid, d in net.items():
            if d < 0 and self.available(self.name_of(uid)) + d < 0:
                return "insufficient_funds"
        over = {pid: (latest[0] + 1, amount, eff, self.now(), text, "") for pid, p, latest, expected, amount, eff, text in meta}
        touched = {p["from"] for _, p, *_ in meta} | {p["to"] for _, p, *_ in meta}
        for uid in touched:
            if model.would_overdraw(uid, over, self.now()):
                return "historical_overdraft"
        return 201


class TestModel4(unittest.TestCase):
    def run_seed(self, seed, steps, **kw):
        h = History4(seed, steps, **kw)
        h.compare(n_asof=6, n_known=4, n_win=6)
        return h

    def test_random_histories(self):
        tot = {}
        codes = {}
        for seed in range(30, 36):
            h = self.run_seed(seed, 140)
            for k, v in h.stats4.items():
                tot[k] = tot.get(k, 0) + v
            for k, v in h.codes.items():
                codes[k] = codes.get(k, 0) + v
        print("stage-4 model stats:", tot, codes)
        self.assertGreater(tot["batch_ok"], 5)
        self.assertGreater(tot["refund_ok"], 5)

    def test_tight_wallets(self):
        tot = {}
        codes = {}
        for seed in range(40, 46):
            h = self.run_seed(seed, 130, bal=700, scale=2)
            for k, v in h.codes.items():
                codes[k] = codes.get(k, 0) + v
        print("stage-4 tight codes:", codes)
        self.assertGreater(codes.get("insufficient_funds", 0) + codes.get("historical_overdraft", 0), 0)

    def test_with_expiry(self):
        h = self.run_seed(50, 100, ttl=1, pause=True, bal=800, scale=2)
        print("stage-4 expiry codes:", h.codes)


if __name__ == "__main__":
    unittest.main(verbosity=1)
