"""Y1. The service against the brute-force model, with refunds, settlements and correction batches."""
import json
import os
import random
import time
from fractions import Fraction

import pytest

from lib import (POST, US, VOUT, Model, World, batch, build_model, call, check_batch, check_everything, code_of, correct, err,
                 fixture, fmt, inst, k, members, now_f, ok, refund, refunded, soft, statement, user)
from test_w_model import HANDLES, random_fixture, same_model

ITEM_ERRORS = ("linked_payment_immutable", "stale_revision", "refund_exceeds_payment")


def run_ops4(w, m, rng, base, steps, log):
    uid = {h: f"u_{h}" for h in HANDLES + ["op"]}
    hof = {v: kk for kk, v in uid.items()}

    def avail(h):
        return m.total(uid[h]) - m.held(uid[h], now_f())

    def open_auths():
        now = now_f()
        return [a for a in m.auth.values() if a["status"] == "open" and a["expires"] > now + 5]

    def linked(p):
        o = p["obj"]
        return bool(o.get("authorization_id") or o.get("refund_of"))

    def item_errors(p, expected, new, single):
        e = []
        if linked(p) or (single and p["obj"].get("settlement_id")):
            e.append("linked_payment_immutable")
        if expected != p["revs"][-1]["revision"]:
            e.append("stale_revision")
        if new < refunded(m, p["obj"]["payment_id"]):
            e.append("refund_exceeds_payment")
        return e

    def pick_eff(p):
        now = now_f()
        bs = [b for b in m.boundaries() if b <= now - 1]
        eff = rng.choice([inst(p["obj"]["created_at"]), p["revs"][-1]["eff"],
                          base + Fraction(rng.randrange(0, int((now - base) * 1000) - 500), 1000),
                          rng.choice(bs) + rng.choice([-US, 0, US]), now - Fraction(1, 2)])
        return fmt(eff, rng.choice([0, 0, 0, 330, -120]))

    def pick_amount(cur):
        return rng.choice([0, cur, max(0, cur - rng.randint(1, 300)), cur + rng.randint(1, 300), rng.randint(0, 4000),
                           cur + rng.randint(300, 9000)])

    def judge(proposals):
        """proposals: [(payment, new amount, effective string)] already free of item errors. -> (status, code, why)"""
        net = {}
        for p, new, effs in proposals:
            diff = new - p["revs"][-1]["amount"]
            net[p["frm"]] = net.get(p["frm"], 0) - diff
            net[p["to"]] = net.get(p["to"], 0) + diff
        for u, d in net.items():
            if d < 0 and avail(hof[u]) < -d:
                return 409, "insufficient_funds", f"{hof[u]} has {avail(hof[u])} available, net {-d} needed"
        now = now_f()
        for p, new, effs in proposals:
            m.add_revision(p["obj"]["payment_id"], {"revision": p["revs"][-1]["revision"] + 1, "amount": new, "effective_at": effs,
                                                    "recorded_at": fmt(now), "reason": "tentative"})
        why = m.overdraft(sorted(net), now + 2)
        for p, new, effs in proposals:
            p["revs"].pop()
        return (409, "historical_overdraft", why) if why else (201, None, None)

    for step in range(steps):
        op = rng.choices(["pay", "correct", "authorize", "capture", "void", "refund", "settle", "batch"], [3, 4, 2, 2, 1, 4, 1, 4])[0]
        if op in ("pay", "authorize"):
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
            ao = a["obj"]
            j = ok(w.capture(ao["to_handle"], ao["authorization_id"], body={"amount": rng.randint(1, rem), "final": rng.random() < 0.5}),
                   201, f"step {step}")
            m.add_payment(j)
            m.set_auth(w.auth(ao["from_handle"], ao["authorization_id"]))
            log.append({"step": step, "op": "capture", "payment": j["payment_id"]})
        elif op == "void" and open_auths():
            ao = rng.choice(open_auths())["obj"]
            m.set_auth(ok(w.void(ao["from_handle"], ao["authorization_id"]), 200, f"step {step}"))
            log.append({"step": step, "op": "void"})
        elif op == "settle":
            a, b, c = rng.sample(HANDLES, 3)
            x, y = rng.randint(1, 200), rng.randint(1, 200)
            net = {a: -x, b: x - y, c: y}
            fine = all(avail(h) + d >= 0 for h, d in net.items())
            r = call("POST", "/settlements", w.t("op"), key=k(), base=w.base,
                     body={"transfers": [{"from_handle": a, "to_handle": b, "amount": x},
                                         {"from_handle": b, "to_handle": c, "amount": y, "visibility": "private"}]})
            log.append({"step": step, "op": "settle", "status": r.status_code, "fine": fine})
            if fine:
                for pj in ok(r, 201, f"step {step}: settlement")["payments"]:
                    m.add_payment(pj)
            else:
                err(r, 409, "insufficient_funds", f"step {step}: settlement {net}")
        elif op == "refund":
            p = rng.choice(list(m.pay.values()))
            o = p["obj"]
            pid = o["payment_id"]
            left = p["revs"][-1]["amount"] - refunded(m, pid)
            amount = rng.choice([max(1, left), rng.randint(1, max(1, left)), left + rng.randint(1, 50), rng.randint(1, 3000)])
            who = hof[p["to"]] if rng.random() < 0.9 else hof[p["frm"]]
            if o.get("refund_of"):
                want = (422, "invalid_refund_target")
            elif who != hof[p["to"]]:
                want = (403, "forbidden")
            elif amount > left:
                want = (422, "refund_exceeds_payment")
            elif avail(who) < amount:
                want = (409, "insufficient_funds")
            else:
                want = (201, None)
            r = refund(w, who, pid, amount)
            got = (r.status_code, code_of(r) if r.status_code != 201 else None)
            log.append({"step": step, "op": "refund", "payment": pid, "who": who, "amount": amount, "left": left, "want": want, "got": got})
            if o.get("refund_of") and who != hof[p["to"]] and got == (403, "forbidden"):
                continue                                         # refund of a refund by a non-receiver: 422 or 403
            assert got == want, (f"step {step}: refund of {amount} on {pid} by {who} (left {left}, available {avail(who)}): "
                                 f"model says {want}, service says {got} {r.text[:200]}")
            if r.status_code == 201:
                j = r.json()
                assert j["refund_of"] == pid and j["from_user_id"] == p["to"] and j["to_user_id"] == p["frm"]
                m.add_payment(j)
        elif op == "correct":
            p = rng.choice(list(m.pay.values()))
            pid, cur = p["obj"]["payment_id"], p["revs"][-1]
            new, effs = pick_amount(cur["amount"]), pick_eff(p)
            expected = cur["revision"] if rng.random() < 0.9 else max(1, cur["revision"] - 1)
            errs = item_errors(p, expected, new, single=True)
            why = None
            if errs:
                want = [(422 if e != "stale_revision" else 409, e) for e in errs]
            else:
                st, code, why = judge([(p, new, effs)])
                want = [(st, code)]
            r = correct(w, hof[p["frm"]], pid, expected, new, effs, f"step {step}")
            got = (r.status_code, code_of(r) if r.status_code != 201 else None)
            log.append({"step": step, "op": "correct", "payment": pid, "old": cur["amount"], "new": new, "effective_at": effs,
                        "expected_revision": expected, "want": want, "got": got, "why": str(why)})
            assert got in want, (f"step {step}: correction of {pid} from {cur['amount']} to {new} effective {effs}, "
                                 f"expected_revision {expected}: model says {want} ({why}), service says {got} {r.text[:200]}")
            soft(got == want[0], "single-correction-error-order", want=want, got=got)
            if r.status_code == 201:
                m.add_revision(pid, r.json())
        elif op == "batch":
            pool = list(m.pay.values())
            chosen = rng.sample(pool, min(len(pool), rng.randint(1, 4)))
            # usually complete the settlements touched, sometimes leave one incomplete
            complete = rng.random() < 0.8
            ids = [p["obj"]["payment_id"] for p in chosen]
            if complete:
                for p in list(chosen):
                    sid = p["obj"].get("settlement_id")
                    if sid:
                        for pid in members(m, sid):
                            if pid not in ids:
                                ids.append(pid)
                                chosen.append(m.pay[pid])
            rng.shuffle(chosen)
            sett_eff = {}
            items, props, first_err = [], [], None
            for p in chosen:
                cur = p["revs"][-1]
                sid = p["obj"].get("settlement_id")
                new = pick_amount(cur["amount"])
                if sid:
                    effs = sett_eff.setdefault(sid, pick_eff(p))
                    effs = fmt(inst(effs), rng.choice([0, 60, -300]))        # the same instant in other spellings
                else:
                    effs = pick_eff(p)
                expected = cur["revision"] if rng.random() < 0.93 else cur["revision"] + 1
                items.append({"payment_id": p["obj"]["payment_id"], "expected_revision": expected, "amount": new,
                              "effective_at": effs, "reason": f"step {step}"})
                errs = item_errors(p, expected, new, single=False)
                if errs and first_err is None:
                    first_err = [(422 if e != "stale_revision" else 409, e) for e in errs]
                props.append((p, new, effs))
            why = None
            if first_err:
                want = first_err
            else:
                sids = {p["obj"]["settlement_id"] for p in chosen if p["obj"].get("settlement_id")}
                if any(set(members(m, sid)) - set(i["payment_id"] for i in items) for sid in sids):
                    want = [(422, "incomplete_settlement")]
                else:
                    st, code, why = judge(props)
                    want = [(st, code)]
            r = batch(w, items)
            got = (r.status_code, code_of(r) if r.status_code != 201 else None)
            log.append({"step": step, "op": "batch", "items": items, "want": want, "got": got, "why": str(why)})
            if got == (422, "validation_failed") and any(i["expected_revision"] > m.pay[i["payment_id"]]["revs"][-1]["revision"] for i in items):
                continue                                         # an expected revision ahead of the latest: 409 or 422
            assert got in want, f"step {step}: batch {items}: model says {want} ({why}), service says {got} {r.text[:300]}"
            soft(got == want[0], "batch-item-error-order", want=want, got=got)
            if r.status_code == 201:
                j = check_batch(r.json(), items)
                for rv in j["revisions"]:
                    m.add_revision(rv["payment_id"], rv)


@pytest.mark.parametrize("seed", [1101, 2202, 3303, 4404])
def test_model4_random_history_with_refunds_and_batches(seed):
    rng = random.Random(seed)
    fx, opening, base = random_fixture(rng)
    fx["users"].append(user("op", 0))
    fx["settlement_operator_ids"] = ["u_op"]
    w = World(fx).login_all()
    m = build_model(w)
    assert m.overdraft(list(m.opening), now_f() + 2) is None
    snaps = {h: ok(statement(w, h, limit=200), 200) for h in HANDLES}
    log = []
    try:
        run_ops4(w, m, rng, base, 90, log)
    finally:
        with open(os.path.join(VOUT, f"model4-ops-{seed}.jsonl"), "w") as fh:
            for line in log:
                fh.write(json.dumps(line, default=str) + "\n")
    out = {}
    for line in log:
        if line["op"] in ("correct", "batch", "refund"):
            key = f"{line['op']} {line['got']}"
            out[key] = out.get(key, 0) + 1
    print(f"\nseed {seed}: {len(log)} operations, outcomes {out}")
    m2 = build_model(w)
    same_model(m, m2)
    assert m2.overdraft(list(m2.opening), now_f()) is None, "accepted operations left a negative total or available in history"
    for pid, p in m2.pay.items():
        assert refunded(m2, pid) <= p["revs"][-1]["amount"], f"{pid}: refunded {refunded(m2, pid)} above the current amount"
    check_everything(w, m2, rng, me_points=70, st_points=25)
    for h in HANDLES:
        pg = ok(statement(w, h, snapshot=snaps[h]["snapshot"], limit=200), 200)
        assert pg["entries"] == snaps[h]["entries"] and pg["closing_balance"] == snaps[h]["closing_balance"], "an old snapshot changed"
    w.assert_conserved()
