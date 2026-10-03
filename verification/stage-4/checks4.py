#!/usr/bin/env python3
"""Nightshift Verifier - Pocketful stage 4 - API checks.

Runs the stage-1, stage-2 and stage-3 lists (checks1/2/3.py) unchanged (map row AD1), plus the
checks below, derived from pocketful/spec/stage-4.md. Options as checks1.py.
Env S1BASE / S2BASE / S3OLD name running stage-1/2/3 containers for the import checks;
S3B names a second container of the stage under test.
"""
import datetime as dt
import os
import sys
import time

import checks1 as c1
import checks2 as c2
import checks3 as c3
from checks1 import HS, OTHERFX, PW, T, basefx, check, idok, ids, is_err, k, par, parse_ts, pay_shape, tr, tsok
from checks2 import auth_by_id, cap, me3, mk_auth
from checks3 import REV_KEYS, correct, iso, me, now, qs, revs, rows, stmt, total_at

BATCH_REV_KEYS = REV_KEYS + ["correction_batch_id"]


def refund(S, who, pid, amount, key=None, **kw):
    return S.call("POST", f"/payments/{pid}/refunds", {"amount": amount}, as_=who, key=key or k(), **kw)


def item(pid, expected, amount, effective, reason="batch", **over):
    d = {"payment_id": pid, "expected_revision": expected, "amount": amount,
         "effective_at": effective if isinstance(effective, str) else iso(effective), "reason": reason}
    d.update(over)
    return d


def batch(S, who, items, key=None):
    return S.call("POST", "/correction-batches", {"corrections": items}, as_=who, key=key or k())


def pay(S, frm, to, amount, **kw):
    r = S.call("POST", "/payments", dict({"to_handle": to, "amount": amount}, **kw), as_=frm, key=k())
    if r.status != 201:
        raise c1.CheckError(f"setup payment {frm}->{to} {amount} failed: {r!r}")
    return r.j


def totals(S):
    return {h: S.me(h).get("total") for h in HS}


def clean():
    return basefx(payments=[], requests=[])


# --------------------------------------------------------------------------- AE refunds
@check("AE1-refund-rules", "stage-4 Refunds and corrected history", "AE1,AE3,AE4,AE5,AE8,AE9,AD4", "Refund: key required, original receiver only (403 for sender and third party), unknown payment 404, no token 401; invalid amount 422; cumulative refunds may not exceed the current corrected amount (422 refund_exceeds_payment); 201 is a new payment in the opposite direction with refund_of, null request/authorization ids, original note and visibility; replay 200; refund of a refund 422 invalid_refund_target; other payments carry refund_of null; refunds appear in feed and statements")
def c_refund(t, S):
    S.reset(clean())
    p = pay(S, "ada", "bob", 1000, note="gift \U0001F381", visibility="private")
    pid = p["payment_id"]
    t.eq(p.get("refund_of", "MISSING"), None, "ordinary payment response carries refund_of null")
    path = f"/payments/{pid}/refunds"
    t.err(S.call("POST", path, {"amount": 200}, key=k()), 401, "unauthenticated", "refund without token")
    t.err(S.call("POST", path, {"amount": 200}, as_="bob"), 400, "missing_idempotency_key", "refund without key")
    t.err(S.call("POST", path, {"amount": 200}, as_="bob", headers={"Idempotency-Key": ""}), 400, "missing_idempotency_key", "refund with empty key")
    t.err(refund(S, "bob", pid, 200, key="K" * 256), 422, "validation_failed", "refund with 256-char key")
    t.err(refund(S, "ada", pid, 200), 403, "forbidden", "original sender refunds")
    t.err(refund(S, "cy", pid, 200), 403, "forbidden", "third party refunds")
    t.err(refund(S, "op", pid, 200), 403, "forbidden", "operator (not a party) refunds")
    t.err(refund(S, "bob", "p_nope", 200), 404, "not_found", "refund an unknown payment")
    t.err(S.call("POST", path, {}, as_="bob", key=k()), 422, "validation_failed", "refund without amount")
    kf = k()
    for bad in (0, -1, 1.5, "200", True, None, 1000000001, [200]):
        t.err(refund(S, "bob", pid, bad, key=kf), 422, "validation_failed", f"refund amount {bad!r}")
    t.err(refund(S, "bob", pid, 1001), 422, "refund_exceeds_payment", "refund above the payment amount")
    t.eq(S.bals(["ada", "bob"]), {"ada": 9000, "bob": 3500}, "nothing moved by refused refunds")
    key = "K" * 255
    r = refund(S, "bob", pid, 200, key=key)
    t.st(r, 201, "refund 200 (255-char key)")
    j = r.j or {}
    pay_shape(t, j, "refund payment", from_user_id="u_bob", from_handle="bob", to_user_id="u_ada", to_handle="ada", amount=200, currency="EUR",
              note="gift \U0001F381", visibility="private", request_id=None, settlement_id=None, authorization_id=None, refund_of=pid)
    t.ok(j.get("payment_id") != pid, "refund must have its own payment id")
    t.eq(S.bals(["ada", "bob"]), {"ada": 9200, "bob": 3300}, "refund moved 200 back")
    r2 = refund(S, "bob", pid, 200, key=key)
    t.ok(r2.status == 200 and r2.j == j, f"refund replay: {r2!r}")
    t.err(refund(S, "bob", pid, 201, key=key), 409, "idempotency_key_reuse", "refund key with another body")
    t.err(refund(S, "bob", pid, "x", key=key), 409, "idempotency_key_reuse", "refund key with an invalid body")
    t.st(refund(S, "bob", pid, 1, key=kf), 201, "key of a failed refund reused; amount 1")
    for lit in ("2e2", "199.0"):
        r = S.call("POST", path, raw='{"amount": %s, "zzz": 1}' % lit, as_="bob", key=k())
        t.ok(r.status == 201 and (r.j or {}).get("amount") == int(float(lit)), f"refund amount literal {lit} with an unknown field: {r!r}"[:200])
    t.err(refund(S, "bob", pid, 401), 422, "refund_exceeds_payment", "remaining 400: refund 401")
    r = refund(S, "bob", pid, 400)
    t.st(r, 201, "refund exactly the remaining 400")
    t.err(refund(S, "bob", pid, 1), 422, "refund_exceeds_payment", "fully refunded payment")
    t.eq(S.bals(["ada", "bob"]), {"ada": 10000, "bob": 2500}, "fully refunded")
    rid = j.get("payment_id")
    t.err(refund(S, "ada", rid, 50), 422, "invalid_refund_target", "refund of a refund (by its receiver)")
    t.err(correct(S, "bob", rid, 1, 100, now() - dt.timedelta(seconds=1)), 422, "linked_payment_immutable", "correct a refund payment")
    # feed / statement / revisions
    for h, sees in (("ada", True), ("bob", True), ("cy", False), ("op", False)):
        t.eq(rid in ids(S.acts(h), "payment_id"), sees, f"private refund visible to {h}")
    feed = {x["payment_id"]: x for x in S.acts("ada")}
    t.ok(feed.get(rid) == j, "refund in the feed equals its 201 body")
    t.ok(feed.get(pid) == p, f"original payment in the feed unchanged: {feed.get(pid)}")
    t.ok(all("refund_of" in x for x in feed.values()), "every feed payment carries refund_of")
    st = stmt(S, "ada")
    t.eq([x[1] for x in rows(st)], [-1000, 200, 1, 200, 199, 400], "sender's statement: original then refunds, with signs")
    t.ok(all("refund_of" in e["payment"] for e in st["entries"]) and st["entries"][1]["payment"]["refund_of"] == pid, "statement payments carry refund_of")
    t.eq([x[1] for x in rows(stmt(S, "bob"))], [1000, -200, -1, -200, -199, -400], "receiver's statement")
    rv = revs(S, "ada", rid)
    t.ok(len(rv) == 1 and rv[0]["revision"] == 1 and rv[0]["amount"] == 200 and parse_ts(rv[0]["effective_at"]) == parse_ts(j["created_at"]), f"refund has revision 1 at its created_at: {rv}")
    t.eq(len(revs(S, "ada", pid)), 1, "refunds add no revision to the original")
    t.eq(sum(totals(S).values()), 14000, "sum of totals")


@check("AE4-refund-vs-correction", "stage-4 Refunds and corrected history", "AE4,AF1,AF3,AF4,AG10", "The refund limit is the current corrected amount; a correction cannot reduce a payment below its already-refunded amount (422 refund_exceeds_payment; equal is fine); single-correction responses and revisions expose correction_batch_id null")
def c_refund_corr(t, S):
    S.reset(clean())
    p = pay(S, "ada", "bob", 500)
    pid, made = p["payment_id"], p["created_at"]
    r = correct(S, "ada", pid, 1, 300, made)
    t.st(r, 201, "correct 500 -> 300")
    t.eq((r.j or {"correction_batch_id": "MISSING"}).get("correction_batch_id", "MISSING"), None, "single-correction response exposes correction_batch_id null")
    t.err(refund(S, "bob", pid, 301), 422, "refund_exceeds_payment", "refund above the corrected amount")
    t.st(refund(S, "bob", pid, 200), 201, "refund 200 of 300")
    t.err(correct(S, "ada", pid, 2, 199, made), 422, "refund_exceeds_payment", "correct to 199 with 200 refunded")
    t.err(correct(S, "ada", pid, 2, 0, made), 422, "refund_exceeds_payment", "correct to 0 with 200 refunded")
    t.eq(len(revs(S, "ada", pid)), 2, "refused corrections appended nothing")
    t.st(correct(S, "ada", pid, 2, 200, made), 201, "correct to exactly the refunded amount")
    t.err(refund(S, "bob", pid, 1), 422, "refund_exceeds_payment", "nothing left to refund")
    t.st(correct(S, "ada", pid, 3, 900, made), 201, "increase after refunds")
    t.st(refund(S, "bob", pid, 700), 201, "refund up to the new corrected amount")
    t.eq(S.bals(["ada", "bob"]), {"ada": 10000, "bob": 2500}, "payment of 900 fully refunded")
    t.ok(all(x.get("correction_batch_id", "MISSING") is None for x in revs(S, "bob", pid)), "revisions from single corrections and revision 1 expose correction_batch_id null")
    t.eq(sum(totals(S).values()), 14000, "sum of totals")


@check("AE6-refund-funds-and-links", "stage-4 Refunds and corrected history", "AE2,AE6,AE7,AG14", "A refund moves money from the receiver's available funds or fails 409 insufficient_funds atomically (held funds do not count); request payments, captures and settlement members are refundable; a refund never reopens a request or authorization, never restores a hold, never changes settlement membership")
def c_refund_links(t, S):
    S.reset(basefx(payments=[]))
    p = pay(S, "ada", "cy", 100)
    pay(S, "cy", "dan", 100)
    t.err(refund(S, "cy", p["payment_id"], 50), 409, "insufficient_funds", "receiver has spent the money")
    t.eq(S.bals(["ada", "cy"]), {"ada": 9900, "cy": 0}, "nothing moved")
    p2 = pay(S, "ada", "dan", 300)
    aid = mk_auth(t, S, "dan", "bob", 800)
    t.eq(me3(S, "dan"), (900, 100, 800), "dan with a hold")
    t.err(refund(S, "dan", p2["payment_id"], 101), 409, "insufficient_funds", "refund above available (held funds do not count)")
    t.st(refund(S, "dan", p2["payment_id"], 100), 201, "refund equal to available")
    t.eq(me3(S, "dan"), (800, 0, 800), "dan after the refund")
    # request payment
    rp = S.call("POST", "/requests/rq_1/pay", {}, as_="ada", key=k())
    r = refund(S, "bob", rp.j["payment_id"], 1200)
    t.st(r, 201, "refund a request payment in full")
    t.eq(((r.j or {}).get("request_id"), (r.j or {}).get("refund_of")), (None, rp.j["payment_id"]), "refund of a request payment: request_id null, refund_of set")
    q = S.req_by_id("ada", "rq_1") or {}
    t.eq((q.get("status"), q.get("payment_id")), ("paid", rp.j["payment_id"]), "request stays paid after the refund")
    t.err(S.call("POST", "/requests/rq_1/pay", {}, as_="ada", key=k()), 409, "request_not_pending", "refunded request cannot be paid again")
    # capture
    a2 = mk_auth(t, S, "ada", "bob", 500)
    cp = cap(S, "bob", a2, {"amount": 300})
    before = me3(S, "ada")
    r = refund(S, "bob", cp.j["payment_id"], 300)
    t.st(r, 201, "refund a capture")
    t.eq(((r.j or {}).get("authorization_id"), (r.j or {}).get("refund_of")), (None, cp.j["payment_id"]), "refund of a capture: authorization_id null")
    a = auth_by_id(S, "ada", a2) or {}
    t.eq((a.get("status"), a.get("captured_amount"), a.get("remaining_amount")), ("captured", 300, 0), "authorization unchanged by the refund")
    t.eq(me3(S, "ada"), (before[0] + 300, before[1] + 300, 0), "refund restores no hold")
    t.err(cap(S, "bob", a2, {"amount": 1}), 409, "authorization_not_open", "authorization not reopened")
    # settlement member
    ks = k()
    sb = {"transfers": [tr("ada", "cy", 100), tr("cy", "dan", 40)]}
    s = S.call("POST", "/settlements", sb, as_="op", key=ks)
    m1 = s.j["payments"][0]
    r = refund(S, "cy", m1["payment_id"], 60)
    t.st(r, 201, "refund a settlement member")
    t.eq(((r.j or {}).get("settlement_id"), (r.j or {}).get("refund_of")), (None, m1["payment_id"]), "refund of a settlement member: settlement_id null")
    s2 = S.call("POST", "/settlements", sb, as_="op", key=ks)
    t.ok(s2.status == 200 and s2.j == s.j, "settlement replay unchanged after a member was refunded")
    t.eq(sum(totals(S).values()), 14000, "sum of totals")


@check("AE10-refund-races", "stage-4 Refunds; stage-1 §7; stage-2 Concurrent operations", "AE10,AD4", "Concurrent refunds never exceed the corrected amount; a refund racing a reducing correction serialises; identical keyed refunds take effect once")
def c_refund_race(t, S):
    S.reset(clean())
    p = pay(S, "ada", "bob", 1000)
    pid = p["payment_id"]
    S.token("bob")
    rs = par([lambda: refund(S, "bob", pid, 100) for _ in range(20)])
    t.ok(sum(r.status == 201 for r in rs) == 10 and all(r.status == 201 or is_err(r, 422, "refund_exceeds_payment") for r in rs),
         f"20 concurrent refunds of 100 against 1000: expected 10x201 + 10x422 refund_exceeds_payment, got {sorted(r.status for r in rs)}")
    t.eq(S.bals(["ada", "bob"]), {"ada": 10000, "bob": 2500}, "refunded exactly the payment amount")
    for rnd in range(3):
        p = pay(S, "ada", "bob", 1000)
        pid = p["payment_id"]
        fns = [lambda: ("r", refund(S, "bob", pid, 100)) for _ in range(10)] + [lambda: ("c", correct(S, "ada", pid, 1, 500, p["created_at"]))]
        rs = par(fns)
        ok_r = sum(r.status == 201 for kind, r in rs if kind == "r")
        cr = next(r for kind, r in rs if kind == "c")
        amount = revs(S, "ada", pid)[-1]["amount"]
        t.ok(cr.status == 201 or is_err(cr, 422, "refund_exceeds_payment"), f"round {rnd}: correction response {cr!r}"[:200])
        t.ok(ok_r * 100 <= amount, f"round {rnd}: refunded {ok_r * 100} exceeds the corrected amount {amount}")
        t.ok(all(r.status == 201 or is_err(r, 422, "refund_exceeds_payment") for kind, r in rs if kind == "r"), f"round {rnd}: refund responses {[r.status for kind, r in rs if kind == 'r']}")
        b = S.bals(["ada", "bob"])
        t.eq(b, {"ada": 10000 - amount + ok_r * 100, "bob": 2500 + amount - ok_r * 100}, f"round {rnd}: balances consistent with amount {amount} and {ok_r} refunds")
        if amount > ok_r * 100:
            refund(S, "bob", pid, amount - ok_r * 100)
    p = pay(S, "ada", "bob", 300)
    key = k()
    rs = par([lambda: refund(S, "bob", p["payment_id"], 120, key=key) for _ in range(20)])
    first = next((r for r in rs if r.status == 201), None)
    t.ok(first is not None and sum(r.status == 201 for r in rs) == 1 and all(r.status == 200 and r.j == first.j for r in rs if r is not first), f"20 identical refunds: {sorted(r.status for r in rs)}")
    t.eq(S.bals(["ada", "bob"]), {"ada": 9820, "bob": 2680}, "identical refunds applied once")
    t.st(refund(S, "bob", p["payment_id"], 120, key=k()), 201, "another user-scoped key refunds again")
    t.eq(sum(totals(S).values()), 14000, "sum of totals")


# --------------------------------------------------------------------------- AG batches
def _world(t, S):
    """Payments p_a (ada->bob 300), p_b (bob->cy 200), settlement [ada->bob 100, bob->cy 50], a capture and a refund."""
    S.reset(clean())
    w = {}
    w["a"] = pay(S, "ada", "bob", 300, note="a")
    w["b"] = pay(S, "bob", "cy", 200, note="b", visibility="private")
    w["skey"] = k()
    w["sbody"] = {"transfers": [tr("ada", "bob", 100), tr("bob", "cy", 50)]}
    w["s"] = S.call("POST", "/settlements", w["sbody"], as_="op", key=w["skey"]).j
    w["m1"], w["m2"] = w["s"]["payments"]
    aid = mk_auth(t, S, "ada", "dan", 60)
    w["cap"] = cap(S, "dan", aid).j
    w["ref"] = refund(S, "bob", w["a"]["payment_id"], 10).j
    return w


@check("AG1-batch-rules", "stage-4 Batch corrections", "AG1,AG2,AG3,AG4,AG5,AG8,AF2,AF3", "Batches: operator and key required (401/403 as settlements); 1..32 objects with distinct payment_ids; ordinary correction field validation per item; unknown payment 404; stale 409; captures and refunds immutable; a settlement needs all its members (422 incomplete_settlement) with identical effective instants; refund floor; a rejected batch changes nothing and claims no key")
def c_batch_rules(t, S):
    w = _world(t, S)
    a, b, m1, m2 = w["a"], w["b"], w["m1"], w["m2"]
    good = [item(a["payment_id"], 1, 250, a["created_at"])]
    before = (S.bals(HS), [revs(S, "ada", x["payment_id"]) for x in (a, m1)], revs(S, "bob", b["payment_id"]), stmt(S, "bob")["entries"])
    t.err(S.call("POST", "/correction-batches", {"corrections": good}, key=k()), 401, "unauthenticated", "batch without token")
    for h in ("ada", "bob"):
        t.err(batch(S, h, good), 403, "forbidden", f"batch by non-operator {h}")
    t.err(S.call("POST", "/correction-batches", {"corrections": good}, as_="op"), 400, "missing_idempotency_key", "batch without key")
    t.err(batch(S, "op", good, key="K" * 256), 422, "validation_failed", "batch with 256-char key")
    kfail = k()
    for label, body in (("missing corrections", {}), ("corrections object", {"corrections": {}}), ("corrections string", {"corrections": "x"}), ("empty", {"corrections": []}),
                        ("item number", {"corrections": [5]}), ("item null", {"corrections": [None]}),
                        ("duplicate payment_id", {"corrections": [good[0], dict(good[0], amount=240)]}),
                        ("33 items", {"corrections": [item(f"p_{i}", 1, 1, a["created_at"]) for i in range(33)]})):
        t.err(S.call("POST", "/correction-batches", body, as_="op", key=kfail), 422, "validation_failed", f"batch {label}")
    for f in ("payment_id", "expected_revision", "amount", "effective_at", "reason"):
        t.err(batch(S, "op", [{kk: v for kk, v in good[0].items() if kk != f}]), 422, "validation_failed", f"batch item without {f}")
    future = iso(now() + dt.timedelta(hours=1))
    for f, v in (("expected_revision", 0), ("expected_revision", "1"), ("amount", -1), ("amount", 1000000001), ("amount", 1.5), ("reason", ""), ("reason", "x" * 201),
                 ("effective_at", future), ("effective_at", "2026-09-20T12:00:00"), ("effective_at", "garbage")):
        shown = v if not (isinstance(v, str) and len(v) > 40) else f"<{len(v)} chars>"
        t.err(batch(S, "op", [dict(good[0], **{f: v})]), 422, "validation_failed", f"batch item {f}={shown!r}")
    t.err(batch(S, "op", [item("p_nope", 1, 1, a["created_at"])]), 404, "not_found", "batch with an unknown payment")
    t.err(batch(S, "op", [dict(good[0], expected_revision=2)]), 409, "stale_revision", "batch with a stale expected revision")
    t.err(batch(S, "op", [item(w["cap"]["payment_id"], 1, 10, w["cap"]["created_at"])]), 422, "linked_payment_immutable", "batch correcting a capture")
    t.err(batch(S, "op", [item(w["ref"]["payment_id"], 1, 5, w["ref"]["created_at"])]), 422, "linked_payment_immutable", "batch correcting a refund")
    t.err(batch(S, "op", [item(a["payment_id"], 1, 9, a["created_at"])]), 422, "refund_exceeds_payment", "batch reducing a payment below its refunded amount (10)")
    com = w["s"]["committed_at"]
    t.err(batch(S, "op", [item(m1["payment_id"], 1, 90, com)]), 422, "incomplete_settlement", "batch with one of two settlement members")
    t.err(batch(S, "op", [item(m2["payment_id"], 1, 40, com), good[0]]), 422, "incomplete_settlement", "batch with the other member and an ordinary payment")
    earlier = iso(parse_ts(com) - dt.timedelta(seconds=1))
    t.err(batch(S, "op", [item(m1["payment_id"], 1, 90, com), item(m2["payment_id"], 1, 40, earlier)]), 422, "validation_failed", "settlement members with different effective instants")
    t.err(correct(S, "ada", m1["payment_id"], 1, 90, com), 422, "linked_payment_immutable", "single correction of a settlement member")
    after = (S.bals(HS), [revs(S, "ada", x["payment_id"]) for x in (a, m1)], revs(S, "bob", b["payment_id"]), stmt(S, "bob")["entries"])
    t.ok(before == after, "rejected batches changed balances, revisions or statements")
    # accepted: same instant in two spellings, unknown fields, key of a failed batch
    alt = parse_ts(com).astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).isoformat()
    r = S.call("POST", "/correction-batches", {"zzz": 1, "corrections": [item(m1["payment_id"], 1, 90, com, zzz=2), item(m2["payment_id"], 1, 40, alt)]}, as_="op", key=kfail)
    t.st(r, 201, "both members, one instant in two offset spellings, unknown fields, key of a failed batch")
    t.eq(S.bals(HS), {"ada": 9560, "bob": 2640, "cy": 240, "dan": 560, "op": 1000}, "balances after the settlement batch (ada +10, bob -10 +10, cy -10)")
    t.st(correct(S, "ada", a["payment_id"], 1, 250, a["created_at"]), 201, "single correction still available for a non-member")
    S.reset(clean())
    many = [pay(S, "ada", "bob", 1) for _ in range(32)]
    r = batch(S, "op", [item(p["payment_id"], 1, 2, p["created_at"]) for p in many])
    t.ok(r.status == 201 and len((r.j or {}).get("revisions", [])) == 32, f"batch of 32 items: {r.status}")
    t.eq(S.bals(["ada", "bob"]), {"ada": 10000 - 64, "bob": 2500 + 64}, "32 corrections applied")
    r = batch(S, "op", [item(many[0]["payment_id"], 2, 1, many[0]["created_at"])])
    t.st(r, 201, "batch of 1 item")


@check("AG9-batch-effects", "stage-4 Batch corrections", "AG4,AG9,AG10,AG11,AG12,AE8", "Batch success: 201 {correction_batch_id, recorded_at, revisions in input order}; one shared recorded_at later than every member's previous one; revisions expose correction_batch_id; atomic; originals, feed and original retries unchanged; new statements reflect the revisions; earlier snapshots stay frozen; replay 200 with the original response")
def c_batch_effects(t, S):
    w = _world(t, S)
    a, b, m1, m2 = w["a"], w["b"], w["m1"], w["m2"]
    com = w["s"]["committed_at"]
    snap_before = stmt(S, "bob", limit="200")
    feeds = {h: S.acts(h) for h in HS}
    t.st(correct(S, "bob", b["payment_id"], 1, 180, b["created_at"]), 201, "single correction of p_b first (revision 2)")
    prev = {x["payment_id"]: parse_ts(revs(S, "bob", x["payment_id"])[-1]["recorded_at"]) for x in (a, b, m1, m2)}
    time.sleep(0.05)
    items = [item(m2["payment_id"], 1, 0, com, reason="reversal"), item(a["payment_id"], 1, 400, a["created_at"], reason="up"),
             item(m1["payment_id"], 1, 0, com, reason="reversal"), item(b["payment_id"], 2, 100, b["created_at"], reason="down")]
    key = k()
    r = batch(S, "op", items, key=key)
    t.st(r, 201, "batch of four (two settlement members, two ordinary; operator is no party)")
    j = r.j or {}
    bid = j.get("correction_batch_id")
    idok(t, bid, "correction_batch_id")
    tsok(t, j.get("recorded_at"), "batch recorded_at")
    rv = j.get("revisions") or []
    t.eq([(x.get("payment_id"), x.get("revision"), x.get("amount"), x.get("reason")) for x in rv],
         [(m2["payment_id"], 2, 0, "reversal"), (a["payment_id"], 2, 400, "up"), (m1["payment_id"], 2, 0, "reversal"), (b["payment_id"], 3, 100, "down")], "revisions in input order")
    for x in rv:
        for kk in BATCH_REV_KEYS:
            t.ok(kk in x, f"batch revision lacks '{kk}'")
        t.eq(x.get("correction_batch_id"), bid, "revision correction_batch_id")
        t.ok(parse_ts(x["recorded_at"]) == parse_ts(j["recorded_at"]) and parse_ts(x["recorded_at"]) > prev[x["payment_id"]], f"shared recorded_at later than the previous one: {x}")
    # money: m2 50->0 (cy -50, bob +50); a 300->400 (ada -100, bob +100); m1 100->0 (bob -100, ada +100); b 180->100 (cy -80, bob +80)
    t.eq(S.bals(HS), {"ada": 9550, "bob": 2500 + 300 - 180 + 100 - 50 - 10 + 50 + 100 - 100 + 80, "cy": 180 + 50 - 50 - 80, "dan": 560, "op": 1000}, "balances after the batch")
    h = revs(S, "bob", b["payment_id"])
    t.eq([x.get("correction_batch_id", "MISSING") for x in h], [None, None, bid], "revision history: null for revision 1 and the single correction, batch id for the batch revision")
    t.ok(h[2] == rv[3], "batch revision in the history equals the batch response entry")
    # originals
    for hh in HS:
        t.ok(S.acts(hh) == feeds[hh], f"{hh}: /activity changed by corrections")
    s2 = S.call("POST", "/settlements", w["sbody"], as_="op", key=w["skey"])
    t.ok(s2.status == 200 and s2.j == w["s"], "settlement retry must return its original body")
    snap = stmt(S, "bob", snapshot=snap_before["snapshot"], limit="200")
    t.ok(snap["entries"] == snap_before["entries"] and snap["closing_balance"] == snap_before["closing_balance"], "earlier snapshot changed by the batch")
    live = stmt(S, "bob", limit="200")
    amt = {e["payment"]["payment_id"]: (e["payment"]["amount"], e["revision"], e["delta"]) for e in live["entries"]}
    t.eq((amt.get(m1["payment_id"]), amt.get(m2["payment_id"]), amt.get(a["payment_id"]), amt.get(b["payment_id"])), ((0, 2, 0), (0, 2, 0), (400, 2, 400), (100, 3, -100)), "new statement reflects the batch revisions")
    t.eq(live["closing_balance"], S.bal("bob"), "statement closing equals the balance")
    for inst in (a["created_at"], com, iso(now())):
        t.eq(total_at(S, as_of=inst), 14000, f"sum of balances as_of {inst}")
    t.eq(total_at(S, known_at=iso(prev[a["payment_id"]])), 14000, "sum of balances known before the batch")
    # replay
    t.st(correct(S, "ada", a["payment_id"], 2, 390, a["created_at"]), 201, "newer single revision after the batch")
    r2 = batch(S, "op", items, key=key)
    t.ok(r2.status == 200 and r2.j == j, f"batch replay after a newer revision: {r2!r}"[:200])
    t.err(batch(S, "op", items[:3], key=key), 409, "idempotency_key_reuse", "batch key with another body")
    t.err(batch(S, "op", items), 409, "stale_revision", "same batch with a new key is stale")
    # refunds of settlement members and batches
    t.err(refund(S, "bob", m1["payment_id"], 1), 422, "refund_exceeds_payment", "member corrected to 0 cannot be refunded")


@check("AG6-batch-precedence", "stage-4 Batch corrections (error precedence, combined affordability)", "AG6,AG7,AG8", "Precedence: item errors in input order, then settlement completeness, then current available funds, then historical overdraft; affordability uses the combined effect of all proposed revisions")
def c_batch_prec(t, S):
    w = _world(t, S)
    a, b, m1, m2 = w["a"], w["b"], w["m1"], w["m2"]
    com = w["s"]["committed_at"]
    stale = item(a["payment_id"], 7, 250, a["created_at"])
    unknown = item("p_nope", 1, 1, a["created_at"])
    badamt = item(b["payment_id"], 1, -5, b["created_at"])
    capt = item(w["cap"]["payment_id"], 1, 10, w["cap"]["created_at"])
    half = item(m1["payment_id"], 1, 90, com)
    huge = item(b["payment_id"], 1, 900000, b["created_at"])
    for label, items, st, code in (
            ("stale then unknown", [stale, unknown], 409, "stale_revision"), ("unknown then stale", [unknown, stale], 404, "not_found"),
            ("bad amount then capture", [badamt, capt], 422, "validation_failed"), ("capture then bad amount", [capt, badamt], 422, "linked_payment_immutable"),
            ("half settlement then bad amount (item error before completeness)", [half, badamt], 422, "validation_failed"),
            ("half settlement then unknown payment", [half, unknown], 404, "not_found"),
            ("half settlement and an unaffordable item (completeness before funds)", [half, huge], 422, "incomplete_settlement"),
            ("unaffordable item alone", [huge], 409, "insufficient_funds")):
        t.err(batch(S, "op", items), st, code, f"batch {label}")
    t.eq(len(revs(S, "ada", a["payment_id"])), 1, "nothing appended by refused batches")
    # funds before history, and combined effect
    fx, (f1, f2, f3) = c3.cyfx()
    S.reset(fx)
    t.err(batch(S, "op", [item("f2", 1, 1301, f2)]), 409, "insufficient_funds", "current shortfall decides before history")
    t.err(batch(S, "op", [item("f2", 1, 400, f2)]), 409, "historical_overdraft", "affordable now, negative four days ago")
    t.st(batch(S, "op", [item("f2", 1, 400, f2), item("f1", 1, 400, f1)]), 201, "the same increase together with a larger funding payment (combined history is fine)")
    S.reset(clean())
    x = pay(S, "ada", "cy", 100)
    y = pay(S, "cy", "dan", 100)
    t.err(batch(S, "op", [item(x["payment_id"], 1, 0, x["created_at"])]), 409, "insufficient_funds", "reversing ada->cy alone: cy has nothing")
    kk = k()
    t.err(batch(S, "op", [item(x["payment_id"], 1, 0, x["created_at"])], key=kk), 409, "insufficient_funds", "again, to reuse its key")
    r = batch(S, "op", [item(x["payment_id"], 1, 0, x["created_at"]), item(y["payment_id"], 1, 0, y["created_at"])], key=kk)
    t.st(r, 201, "reversing both together: the effects offset for cy (key of the failed batch reused)")
    t.eq(S.bals(HS), {"ada": 10000, "bob": 2500, "cy": 0, "dan": 500, "op": 1000}, "balances after reversing both")
    t.eq(total_at(S, as_of=x["created_at"]), 14000, "sum of balances at a past instant")


@check("AG13-batch-races", "stage-4 Batch corrections (concurrency)", "AG13,AD4", "Concurrent corrections, single or batch, sharing an expected payment revision cannot both succeed; identical keyed batches take effect once; sums conserved")
def c_batch_race(t, S):
    S.reset(clean())
    p1, p2, p3 = pay(S, "ada", "bob", 100), pay(S, "ada", "bob", 200), pay(S, "ada", "bob", 300)
    S.token("op")
    rs = par([lambda i=i: batch(S, "op", [item(p1["payment_id"], 1, 101 + i, p1["created_at"]), item(p2["payment_id"], 1, 201 + i, p2["created_at"])]) for i in range(12)])
    t.ok(sum(r.status == 201 for r in rs) == 1 and all(r.status == 201 or is_err(r, 409, "stale_revision") for r in rs), f"12 concurrent batches on the same revisions: {sorted(r.status for r in rs)}")
    t.eq((len(revs(S, "ada", p1["payment_id"])), len(revs(S, "ada", p2["payment_id"]))), (2, 2), "exactly one new revision per payment")
    fns = [lambda i=i: batch(S, "op", [item(p3["payment_id"], 1, 310 + i, p3["created_at"]), item(p1["payment_id"], 2, 150 + i, p1["created_at"])]) for i in range(6)]
    fns += [lambda i=i: correct(S, "ada", p3["payment_id"], 1, 320 + i, p3["created_at"]) for i in range(6)]
    rs = par(fns)
    t.ok(sum(r.status == 201 for r in rs) == 1 and all(r.status == 201 or is_err(r, 409, "stale_revision") for r in rs), f"6 batches vs 6 single corrections on one revision: {sorted(r.status for r in rs)}")
    t.eq(len(revs(S, "ada", p3["payment_id"])), 2, "one new revision of the contested payment")
    t.ok(len(revs(S, "ada", p1["payment_id"])) in (2, 3), "batch atomicity: p1 advanced only with the winning batch")
    amounts = sum(revs(S, "ada", p["payment_id"])[-1]["amount"] for p in (p1, p2, p3))
    t.eq(S.bals(["ada", "bob"]), {"ada": 10000 - amounts, "bob": 2500 + amounts}, "balances equal the latest revisions")
    key = k()
    cur = {p["payment_id"]: revs(S, "ada", p["payment_id"])[-1]["revision"] for p in (p1, p2)}
    items = [item(p1["payment_id"], cur[p1["payment_id"]], 1, p1["created_at"]), item(p2["payment_id"], cur[p2["payment_id"]], 2, p2["created_at"])]
    rs = par([lambda: batch(S, "op", items, key=key) for _ in range(20)])
    first = next((r for r in rs if r.status == 201), None)
    t.ok(first is not None and sum(r.status == 201 for r in rs) == 1 and all(r.status == 200 and r.j == first.j for r in rs if r is not first), f"20 identical batches: {sorted(r.status for r in rs)}")
    t.eq(sum(S.bals(HS).values()), 14000, "sum of balances")
    t.eq(total_at(S, as_of=p2["created_at"]), 14000, "sum of balances at a past instant")


# --------------------------------------------------------------------------- AH
@check("AH1-import-earlier-stages", "stage-4 last paragraph (exports of stages 1-3)", "AH1,AH2", "A stage-4 service accepts exports of this team's stage-1, stage-2 and stage-3 services, retaining settlement membership, corrections and snapshots; imported payments expose refund_of null and are refundable; imported revisions expose correction_batch_id null; settlement completeness works on imported settlements")
def c_import_all(t, S):
    b1, b2, b3 = os.environ.get("S1BASE"), os.environ.get("S2BASE"), os.environ.get("S3OLD")
    if not (b1 and b2 and b3):
        t.ok(False, "not run: needs S1BASE, S2BASE and S3OLD (running stage-1, stage-2 and stage-3 containers)")
        return
    # stage 3: corrections, snapshot, settlement
    X = c1.Sess(b3)
    X.reset(clean())
    toks = {h: X.token(h) for h in HS}
    p = X.call("POST", "/payments", {"to_handle": "bob", "amount": 800}, as_="ada", key=k()).j
    ckey = k()
    cbody = {"expected_revision": 1, "amount": 600, "effective_at": p["created_at"], "reason": "fix"}
    cr = X.call("POST", f"/payments/{p['payment_id']}/corrections", cbody, as_="ada", key=ckey)
    skey = k()
    sbody = {"transfers": [tr("ada", "bob", 100), tr("bob", "cy", 50)]}
    s = X.call("POST", "/settlements", sbody, as_="op", key=skey).j
    full = X.call("GET", "/statement?limit=200", as_="bob").j
    X.call("POST", "/payments", {"to_handle": "bob", "amount": 5}, as_="ada", key=k())
    exp = X.call("GET", "/_test/export").j
    S.reset(OTHERFX)
    t.st(S.call("POST", "/_test/import", exp), 204, "stage-4 import of a stage-3 export")
    S.tok = {}
    g = S.call("GET", "/statement" + qs(snapshot=full["snapshot"], limit="200"), token=toks["bob"])
    t.ok(g.status == 200 and [c3.rows({"entries": [e]})[0] for e in g.j["entries"]] == rows(full) and g.j["closing_balance"] == full["closing_balance"],
         f"stage-3 snapshot token must page the same frozen result on stage-4: {g!r}"[:300])
    r = S.call("GET", f"/payments/{p['payment_id']}/revisions", token=toks["bob"])
    t.ok(r.status == 200 and [(x["revision"], x["amount"], x.get("correction_batch_id", "MISSING")) for x in r.j["revisions"]] == [(1, 800, None), (2, 600, None)], f"imported revisions: {r!r}"[:300])
    rr = S.call("POST", f"/payments/{p['payment_id']}/corrections", cbody, token=toks["ada"], key=ckey)
    t.ok(rr.status == 200 and c2.subset(cr.j, rr.j), f"replay of a stage-3 correction: {rr!r}"[:200])
    acts = S.call("GET", "/activity?limit=200", token=toks["ada"]).j["payments"]
    t.ok(all(x.get("refund_of", "MISSING") is None for x in acts), "imported payments expose refund_of null")
    s2 = S.call("POST", "/settlements", sbody, token=toks["op"], key=skey)
    t.ok(s2.status == 200 and c2.subset(s, s2.j), "replay of the imported settlement")
    m1, m2 = s["payments"]
    com = s["committed_at"]
    t.err(S.call("POST", "/correction-batches", {"corrections": [item(m1["payment_id"], 1, 90, com)]}, token=toks["op"], key=k()), 422, "incomplete_settlement", "imported settlement: one member only")
    t.st(S.call("POST", "/correction-batches", {"corrections": [item(m1["payment_id"], 1, 90, com), item(m2["payment_id"], 1, 40, com)]}, token=toks["op"], key=k()), 201, "imported settlement: both members")
    t.st(S.call("POST", f"/payments/{p['payment_id']}/refunds", {"amount": 600}, token=toks["bob"], key=k()), 201, "imported corrected payment refundable up to the corrected amount")
    t.err(S.call("POST", f"/payments/{p['payment_id']}/refunds", {"amount": 1}, token=toks["bob"], key=k()), 422, "refund_exceeds_payment", "imported payment fully refunded")
    t.eq(sum(S.call("GET", "/me", token=tk).j["total"] for tk in toks.values()), 14000, "sum of totals after the stage-3 import")
    # stage 1 and stage 2
    for label, base, prep, snapf in (("stage-1", b1, c1.j_prepare, c1.j_snapshot), ("stage-2", b2, c2.r_prepare, c2.r_snapshot)):
        ctx = prep(t, c1.Sess(base))
        S.reset(OTHERFX)
        t.st(S.call("POST", "/_test/import", ctx["export"]), 204, f"stage-4 import of a {label} export")
        S.tok = {}
        snap = snapf(S, ctx)
        for h in ctx["snap"]:
            t.ok(c2.subset(ctx["snap"][h], snap[h]), f"{label} import: {h}'s views not preserved")
        c3._consistent(t, S, {h: v for h, v in ctx["tok"].items() if h != "ada2"}, f"{label} import", 14000)
        for name, (who, path, body, key, orig) in ctx["keys"].items():
            r = S.call("POST", path, body, token=ctx["tok"][who], key=key)
            t.ok(r.status == 200 and c2.subset(orig, r.j), f"{label} import: replay of {name}: {r!r}"[:240])
        acts = S.call("GET", "/activity?limit=200", token=ctx["tok"]["ada"]).j["payments"]
        t.ok(acts and all(x.get("refund_of", "MISSING") is None for x in acts), f"{label} import: payments expose refund_of null")
        if label == "stage-1":
            sp = ctx["keys"]["settlement"][4]
            mm = sp["payments"]
            t.err(S.call("POST", "/correction-batches", {"corrections": [item(mm[0]["payment_id"], 1, 90, sp["committed_at"])]}, token=ctx["tok"]["op"], key=k()), 422, "incomplete_settlement", "stage-1 settlement membership retained")
            r = S.call("POST", f"/payments/{mm[1]['payment_id']}/refunds", {"amount": 10}, token=ctx["tok"]["dan"], key=k())
            t.st(r, 201, "imported stage-1 settlement member refundable by its receiver")
        else:
            cp = ctx["keys"]["capture"][4]
            r = S.call("POST", f"/payments/{cp['payment_id']}/refunds", {"amount": 100}, token=ctx["tok"]["bob"], key=k())
            t.st(r, 201, "imported stage-2 capture refundable by its receiver")
            t.err(S.call("POST", "/correction-batches", {"corrections": [item(cp["payment_id"], 1, 1, cp["created_at"])]}, token=ctx["tok"]["op"], key=k()), 422, "linked_payment_immutable", "imported capture immutable in a batch")


@check("AH3-export-import-refunds-batches", "stage-1 §10 applied to stage 4", "AH3,AD4", "Stage-4 export/import round-trips refunds (links and refunded totals), batches (ids, shared recorded_at), the two new paths' idempotency records and snapshots")
def c_roundtrip4(t, S):
    w = _world(t, S)
    toks = {h: S.token(h) for h in HS}
    a, m1, m2 = w["a"], w["m1"], w["m2"]
    com = w["s"]["committed_at"]
    rkey, bkey = k(), k()
    rf = S.call("POST", f"/payments/{a['payment_id']}/refunds", {"amount": 90}, as_="bob", key=rkey)
    items = [item(m1["payment_id"], 1, 80, com), item(m2["payment_id"], 1, 30, com), item(a["payment_id"], 1, 250, a["created_at"])]
    bt = batch(S, "op", items, key=bkey)
    t.ok(rf.status == 201 and bt.status == 201, f"prepare: refund {rf.status}, batch {bt.status}")
    snap = stmt(S, "bob", limit="200")

    def view():
        out = {h: [S.call("GET", pth, token=tok).j for pth in ("/me", "/activity?limit=200", "/authorizations?limit=200")] for h, tok in toks.items()}
        for h, tok in toks.items():
            st = S.call("GET", "/statement?limit=200", token=tok).j or {}
            out[h].append({kk: v for kk, v in st.items() if kk != "snapshot"})
        out["rev"] = [S.call("GET", f"/payments/{x['payment_id']}/revisions", token=toks["bob"]).j for x in (a, m1, m2)]
        return out
    v0 = view()
    exp = S.call("GET", "/_test/export").j
    S.reset(OTHERFX)
    t.st(S.call("POST", "/_test/import", exp), 204, "import")
    S.tok = {}
    v1 = view()
    for kk in v0:
        t.ok(v0[kk] == v1[kk], f"views differ after export/import for {kk}: {str(v1[kk])[:160]}")
    r = S.call("POST", f"/payments/{a['payment_id']}/refunds", {"amount": 90}, token=toks["bob"], key=rkey)
    t.ok(r.status == 200 and r.j == rf.j, f"refund replay after import: {r!r}"[:200])
    r = S.call("POST", "/correction-batches", {"corrections": items}, token=toks["op"], key=bkey)
    t.ok(r.status == 200 and r.j == bt.j, f"batch replay after import: {r!r}"[:200])
    t.err(S.call("POST", "/correction-batches", {"corrections": items[:2]}, token=toks["op"], key=bkey), 409, "idempotency_key_reuse", "batch key with another body after import")
    g = S.call("GET", "/statement" + qs(snapshot=snap["snapshot"], limit="200"), token=toks["bob"])
    t.ok(g.status == 200 and g.j["entries"] == snap["entries"], "snapshot token after import")
    # refunded total preserved: a is 250 with 10 + 90 refunded
    t.err(S.call("POST", f"/payments/{a['payment_id']}/refunds", {"amount": 151}, token=toks["bob"], key=k()), 422, "refund_exceeds_payment", "refunded total preserved by import (150 left)")
    t.st(S.call("POST", f"/payments/{a['payment_id']}/refunds", {"amount": 150}, token=toks["bob"], key=k()), 201, "refund the remaining 150 after import")
    t.err(S.call("POST", f"/payments/{rf.j['payment_id']}/refunds", {"amount": 1}, token=toks["ada"], key=k()), 422, "invalid_refund_target", "imported refund is still a refund")
    t.err(S.call("POST", "/correction-batches", {"corrections": [item(m1["payment_id"], 2, 70, com)]}, token=toks["op"], key=k()), 422, "incomplete_settlement", "settlement membership preserved by import")
    t.eq(sum(S.call("GET", "/me", token=tk).j["total"] for tk in toks.values()), 14000, "sum of totals after import")


@check("AD2-load-refunds-batches", "stage-1 §2 limits and §5 (no 5xx) with stage-4 endpoints", "AD2", "50 requests in flight mixing refunds, batches, corrections, statements and payments: no 5xx, each under 5 s, sums preserved")
def c_load4(t, S):
    fx = clean()
    for u in fx["users"]:
        u["balance"] = 100000
    S.reset(fx)
    for h in HS:
        S.token(h)
    pays = [(HS[i % 5], HS[(i + 1) % 5], pay(S, HS[i % 5], HS[(i + 1) % 5], 50 + i)) for i in range(40)]
    bad, worst = [], [0.0]

    def one(i, rnd):
        frm, to, p = pays[(i + rnd * 7) % 40]
        kind = i % 5
        if kind == 0:
            r, okc = refund(S, to, p["payment_id"], 1), (201, 422)
        elif kind == 1:
            q = pays[(i + rnd * 7 + 1) % 40][2]
            r, okc = batch(S, "op", [item(p["payment_id"], 1, 60 + i, p["created_at"]), item(q["payment_id"], 1, 61 + i, q["created_at"])]), (201, 409, 422)
        elif kind == 2:
            r, okc = S.call("GET", "/statement?limit=200", as_=frm), (200,)
        elif kind == 3:
            r, okc = pay_try(S, frm, to), (201,)
        else:
            r, okc = S.call("GET", "/me" + qs(as_of=p["created_at"]), as_=to), (200,)
        worst[0] = max(worst[0], r.secs)
        if r.status not in okc:
            bad.append(repr(r)[:160])
    for rnd in range(4):
        par([lambda i=i: one(i, rnd) for i in range(50)])
    t.ok(not bad, f"{len(bad)} unexpected responses under 50 in flight, e.g. {bad[:3]}")
    t.ok(worst[0] < 5.0, f"slowest request under 50 in flight took {worst[0]:.2f}s")
    t.note(f"stage-4 load: slowest request {worst[0]:.3f}s")
    t.eq(sum(S.bals(HS).values()), 500000, "sum of balances after load")
    t.eq(total_at(S, as_of=pays[20][2]["created_at"]), 500000, "sum of balances at a past instant after load")
    for h in HS:
        st = stmt(S, h, limit="200")
        t.ok(st["opening_balance"] == 100000 and st["closing_balance"] == S.bal(h), f"{h}: statement opening/closing after load: {st['opening_balance']}, {st['closing_balance']}")


def pay_try(S, frm, to):
    return S.call("POST", "/payments", {"to_handle": to, "amount": 2}, as_=frm, key=k())


if __name__ == "__main__":
    for flag, env in (("--s1base", "S1BASE"), ("--s2base", "S2BASE"), ("--s3old", "S3OLD")):
        if flag in sys.argv:
            i = sys.argv.index(flag)
            os.environ[env] = sys.argv[i + 1]
            del sys.argv[i:i + 2]
    sys.exit(c1.main())
