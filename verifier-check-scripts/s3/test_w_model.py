"""K1, A5, C7, X1. The service against an independent brute-force model on randomised histories."""
import json
import os
import random
import time
from fractions import Fraction

import pytest

from lib import (POST, US, VOUT, Model, World, build_model, burst, check_everything, code_of, correct, err, fixture, fmt,
                 inst, k, me_at, now_f, ok, seeded_auth, statement, statuses, user)
from test_r_time import sp

HANDLES = ["ada", "bob", "cy", "dan", "eve"]


def random_fixture(rng, n=24, with_hold=True):
    opening = {h: rng.choice([0, 500, 3000, 10000]) for h in HANDLES}
    opening["ada"] = 10000
    bal = dict(opening)
    base = Fraction(int(time.time())) - 10 * 86400
    times = sorted(rng.randrange(0, 9 * 86400) for _ in range(n))
    for i in range(1, n, 5):
        times[i] = times[i - 1]                                   # some equal instants
    pays = []
    for i, t in enumerate(times):
        frm = rng.choice([h for h in HANDLES if bal[h] > 0])
        to = rng.choice([h for h in HANDLES if h != frm])
        amt = rng.randint(1, min(bal[frm], 2500))
        bal[frm] -= amt
        bal[to] += amt
        at = base + t + (Fraction(rng.choice([0, 0, 500000, 123456]), 10 ** 6) if i % 5 != 1 else 0)
        if i % 5 == 1:
            at = inst(pays[-1]["created_at"])
        pays.append(sp(f"s{rng.randrange(1000):03d}_{i:02d}", frm, to, amt, fmt(at, rng.choice([0, 0, 120, -330])),
                       rng.choice(["public", "private"]), f"seed {i}"))
    ada_before = bal["ada"]
    for i in range(2):                                            # without created_at: the reset instant
        frm = rng.choice([h for h in HANDLES if bal[h] > 0])
        to = rng.choice([h for h in HANDLES if h != frm])
        amt = rng.randint(1, min(bal[frm], 500))
        bal[frm] -= amt
        bal[to] += amt
        pays.append(sp(f"r{i}", frm, to, amt, None, "public", "at reset"))
    order = list(pays)
    rng.shuffle(order)
    order = [p for p in order if "created_at" in p] + [p for p in pays if "created_at" not in p]
    auths = []
    hold = min(ada_before, bal["ada"]) // 3
    if with_hold and hold >= 1:
        auths.append(seeded_auth("a_seed", "ada", "bob", hold, created_at=fmt(base + 9 * 86400 + 43200)))
    users = [user(h, bal[h]) for h in HANDLES]
    return fixture(users=users, payments=order, auths=auths, ops=[]), opening, base


def run_ops(w, m, rng, base, steps, log):
    uid = {h: f"u_{h}" for h in HANDLES}
    hof = {v: kk for kk, v in uid.items()}

    def avail(h):
        return m.total(uid[h]) - m.held(uid[h], now_f())

    def open_auths():
        now = now_f()
        return [a for a in m.auth.values() if a["status"] == "open" and a["expires"] > now + 5]

    for step in range(steps):
        op = rng.choices(["pay", "correct", "authorize", "capture", "void"], [3, 6, 2, 2, 1])[0]
        if op == "pay" or op == "authorize":
            frm = rng.choice(HANDLES)
            to = rng.choice([h for h in HANDLES if h != frm])
            a = avail(frm)
            amount = rng.randint(1, max(1, min(a + 40, 3000)))
            r = (w.pay if op == "pay" else w.authorize)(frm, to, amount, visibility=rng.choice(["public", "private"]))
            log.append({"step": step, "op": op, "from": frm, "to": to, "amount": amount, "available": a, "status": r.status_code})
            if amount <= a:
                j = ok(r, 201, f"step {step}: {op} of {amount} with {a} available")
                m.add_payment(j) if op == "pay" else m.set_auth(j)
            else:
                err(r, 409, "insufficient_funds", f"step {step}: {op} of {amount} with {a} available")
        elif op == "capture" and open_auths():
            a = rng.choice(open_auths())
            rem = a["amount"] - sum(x for (_, x) in a["caps"])
            amt = rng.randint(1, rem)
            final = rng.random() < 0.5
            ao = a["obj"]
            j = ok(w.capture(ao["to_handle"], ao["authorization_id"], body={"amount": amt, "final": final}), 201, f"step {step}")
            m.add_payment(j)
            m.set_auth(w.auth(ao["from_handle"], ao["authorization_id"]))
            log.append({"step": step, "op": "capture", "auth": ao["authorization_id"], "amount": amt, "final": final})
        elif op == "void" and open_auths():
            ao = rng.choice(open_auths())["obj"]
            m.set_auth(ok(w.void(ao["from_handle"], ao["authorization_id"]), 200, f"step {step}"))
            log.append({"step": step, "op": "void", "auth": ao["authorization_id"]})
        elif op == "correct":
            cands = [p for p in m.pay.values() if not p["obj"].get("authorization_id") and not p["obj"].get("settlement_id")]
            if not cands:
                continue
            p = rng.choice(cands)
            pid, cur = p["obj"]["payment_id"], p["revs"][-1]
            s, rcv = p["frm"], p["to"]
            new = rng.choice([0, cur["amount"], max(0, cur["amount"] - rng.randint(1, 300)), cur["amount"] + rng.randint(1, 300),
                              rng.randint(0, 4000), cur["amount"] + rng.randint(300, 9000)])
            now = now_f()
            bs = [b for b in m.boundaries() if b <= now - 1]
            eff = rng.choice([inst(p["obj"]["created_at"]), cur["eff"],
                              base + Fraction(rng.randrange(0, int((now - base) * 1000) - 500), 1000),
                              rng.choice(bs) + rng.choice([-US, 0, US]), now - Fraction(1, 2)])
            effs = fmt(eff, rng.choice([0, 0, 0, 330, -120]))
            expected = cur["revision"] if rng.random() < 0.9 else rng.choice([max(1, cur["revision"] - 1), cur["revision"] + 1])
            want, why = (201, None), None
            if expected != cur["revision"]:
                want = (409, "stale_revision")
            else:
                diff = new - cur["amount"]
                deb = hof[s] if diff > 0 else hof[rcv]
                if diff != 0 and avail(deb) < abs(diff):
                    want, why = (409, "insufficient_funds"), f"{deb} has {avail(deb)} available, needs {abs(diff)}"
                else:
                    m.add_revision(pid, {"revision": cur["revision"] + 1, "amount": new, "effective_at": effs,
                                         "recorded_at": fmt(now), "reason": "tentative"})
                    why = m.overdraft([s, rcv], now + 2)
                    m.pay[pid]["revs"].pop()
                    if why:
                        want = (409, "historical_overdraft")
            r = correct(w, hof[s], pid, expected, new, effs, f"step {step}")
            got = (r.status_code, code_of(r) if r.status_code != 201 else None)
            log.append({"step": step, "op": "correct", "payment": pid, "from": hof[s], "to": hof[rcv], "old": cur["amount"],
                        "new": new, "effective_at": effs, "expected_revision": expected, "latest": cur["revision"],
                        "want": want, "got": got, "why": str(why)})
            if expected > cur["revision"] and got[0] == 422:
                continue                                           # an expected revision ahead of the latest: 409 or 422
            assert got == want, (f"step {step}: correction of {pid} ({hof[s]} -> {hof[rcv]}) from {cur['amount']} to {new} "
                                 f"effective {effs}, expected_revision {expected} (latest {cur['revision']}): "
                                 f"model says {want} ({why}), service says {got} {r.text[:200]}")
            if r.status_code == 201:
                m.add_revision(pid, r.json())


def same_model(a: Model, b: Model):
    assert set(a.pay) == set(b.pay), set(a.pay) ^ set(b.pay)
    for pid in a.pay:
        ra = [(r["revision"], r["amount"], r["eff"], r["rec"]) for r in a.pay[pid]["revs"]]
        rb = [(r["revision"], r["amount"], r["eff"], r["rec"]) for r in b.pay[pid]["revs"]]
        assert ra == rb, f"revisions of {pid}: tracked {ra}, read back {rb}"
        assert a.pay[pid]["obj"] == b.pay[pid]["obj"], f"payment {pid} changed: {a.pay[pid]['obj']} vs {b.pay[pid]['obj']}"
    assert set(a.auth) == set(b.auth)
    for aid in a.auth:
        x, y = a.auth[aid], b.auth[aid]
        if y["status"] == "expired" and x["status"] == "open":
            continue
        assert (x["status"], x["caps"], x["closed"], x["created"], x["expires"]) == \
               (y["status"], y["caps"], y["closed"], y["created"], y["expires"]), f"authorisation {aid}: {x} vs {y}"


@pytest.mark.parametrize("seed", [101, 202, 303, 404])
def test_model_random_history_with_corrections_and_holds(seed):
    rng = random.Random(seed)
    fx, opening, base = random_fixture(rng)
    w = World(fx).login_all()
    m = build_model(w)
    assert m.opening == {f"u_{h}": opening[h] for h in HANDLES}
    assert m.overdraft(list(m.opening), now_f() + 2) is None, "my seeded history must be nonnegative"
    check_everything(w, m, rng, me_points=30, st_points=8)
    log = []
    try:
        run_ops(w, m, rng, base, 70, log)
    finally:
        with open(os.path.join(VOUT, f"model-ops-{seed}.jsonl"), "w") as fh:
            for line in log:
                fh.write(json.dumps(line, default=str) + "\n")
    outcomes = {}
    for line in log:
        if line["op"] == "correct":
            outcomes[str(line["got"])] = outcomes.get(str(line["got"]), 0) + 1
    print(f"\nseed {seed}: {len(log)} operations, correction outcomes {outcomes}")
    m2 = build_model(w)
    same_model(m, m2)
    assert m2.overdraft(list(m2.opening), now_f()) is None, "accepted corrections left a negative total or available in history"
    check_everything(w, m2, rng, me_points=70, st_points=25)
    w.assert_conserved()


def test_x1_mixed_bursts_with_corrections_keep_every_view_consistent():
    users = [user(h, 50000) for h in HANDLES] + [user("op", 1000)]
    w = World(fixture(users=users)).login_all()
    pays = [ok(w.pay(HANDLES[i % 5], HANDLES[(i + 1) % 5], 100 + i), 201) for i in range(10)]
    rng = random.Random(77)
    for rnd in range(3):
        auths = [w.new_auth("ada", "cy", 300) for _ in range(3)]
        snaps = {h: ok(statement(w, h, limit=200), 200) for h in HANDLES}
        latest = {p["payment_id"]: len(ok(w_revs(w, p), 200)["revisions"]) for p in pays}
        fns, kinds = [], []
        for i, p in enumerate(pays[:6]):                              # two corrections race on each of six payments
            for j in range(2):
                fns.append(lambda p=p, j=j: correct(w, p["from_handle"], p["payment_id"], latest[p["payment_id"]],
                                                    90 + 10 * j + rnd, p["created_at"], f"round {rnd} racer {j}"))
                kinds.append(("correct", p["payment_id"]))
        for i in range(10):
            fns.append(lambda i=i: w.pay(HANDLES[i % 5], HANDLES[(i + 2) % 5], 7 + i))
            kinds.append(("pay", None))
        fns += [lambda: w.capture("cy", auths[0]["authorization_id"], body={"amount": 100}),
                lambda: w.capture("cy", auths[0]["authorization_id"], body={"amount": 120}),
                lambda: w.capture("cy", auths[1]["authorization_id"], body={"amount": 50, "final": False}),
                lambda: w.void("ada", auths[1]["authorization_id"]),
                lambda: w.void("ada", auths[2]["authorization_id"]),
                lambda: w.capture("cy", auths[2]["authorization_id"], body={})]
        kinds += [("hold", None)] * 6
        for i in range(4):
            fns.append(lambda i=i: POST("/settlements", w.t("op"), {"transfers": [
                {"from_handle": HANDLES[i], "to_handle": HANDLES[i + 1], "amount": 5 + i},
                {"from_handle": HANDLES[i + 1], "to_handle": "ada", "amount": 2}]}, key=k()))
            kinds.append(("settle", None))
        for i in range(10):
            h = HANDLES[i % 5]
            fns.append(lambda h=h: statement(w, h, snapshot=snaps[h]["snapshot"], limit=200))
            kinds.append(("snap", h))
        for i in range(4):
            fns.append(lambda i=i: statement(w, HANDLES[i], limit=200))
            kinds.append(("read", None))
        for i in range(4):
            fns.append(lambda i=i: me_at(w, HANDLES[i], fmt(now_f() - 1), fmt(now_f() + 1)))
            kinds.append(("me", None))
        assert len(fns) == 50
        rs = burst(fns)
        won = {}
        for r, (kind, ref) in zip(rs, kinds):
            if kind == "correct":
                assert r.status_code in (201, 409), r.text
                if r.status_code == 201:
                    won[ref] = won.get(ref, 0) + 1
                else:
                    assert code_of(r) == "stale_revision", r.text
            elif kind == "snap":
                j = ok(r, 200)
                assert j["entries"] == snaps[ref]["entries"] and j["closing_balance"] == snaps[ref]["closing_balance"]
            elif kind in ("read", "me"):
                ok(r, 200)
            elif kind in ("pay", "settle"):
                ok(r, 201)
            else:
                assert r.status_code in (200, 201, 409), r.text
        assert won == {p["payment_id"]: 1 for p in pays[:6]}, f"round {rnd}: of two corrections with one expected revision exactly one wins: {won}"
        m = build_model(w)
        assert m.overdraft(list(m.opening), now_f()) is None
        check_everything(w, m, rng, me_points=25, st_points=6)
        b = w.assert_conserved()
        for h in HANDLES:
            assert w.wallet(h)["available"] >= 0


def w_revs(w, p):
    from lib import revisions
    return revisions(w, p["from_handle"], p["payment_id"])
