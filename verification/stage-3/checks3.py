#!/usr/bin/env python3
"""Nightshift Verifier - Pocketful stage 3 - API checks.

Runs the stage-1 list (checks1.py) and the stage-2 API list (checks2.py) unchanged (map row V1),
plus the checks below, derived from pocketful/spec/stage-3.md. Options as checks1.py.
Env S1BASE / S2BASE name running stage-1 and stage-2 containers for the import checks.
"""
import datetime as dt
import os
import sys
import time
import urllib.parse

import checks1 as c1
import checks2 as c2
from checks1 import HS, OTHERFX, PW, T, basefx, check, idok, ids, is_err, k, par, parse_ts, pay_shape, tr, tsok, user
from checks2 import auth_by_id, auths, cap, me3, mk_auth

UTC = dt.timezone.utc
REV_KEYS = ["payment_id", "revision", "amount", "effective_at", "recorded_at", "reason"]


def now():
    return dt.datetime.now(UTC)


def iso(d):
    return d.isoformat()


def ago(**kw):
    return (now() - dt.timedelta(**kw)).replace(microsecond=0)


def qs(**params):
    p = {kk: v for kk, v in params.items() if v is not None}
    return ("?" + urllib.parse.urlencode(p)) if p else ""


def me(S, h, **params):
    r = S.call("GET", "/me" + qs(**params), as_=h)
    if r.status != 200 or not isinstance(r.j, dict):
        raise c1.CheckError(f"GET /me{qs(**params)} as {h} expected 200, got {r!r}")
    return r.j


def stmt(S, h, **params):
    r = S.call("GET", "/statement" + qs(**params), as_=h)
    if r.status != 200 or not isinstance(r.j, dict) or not isinstance(r.j.get("entries"), list):
        raise c1.CheckError(f"GET /statement{qs(**params)} as {h} expected 200 with entries, got {r!r}")
    return r.j


def rows(st):
    """(payment_id, delta, balance_after, revision, payment.amount) per entry."""
    return [((e.get("payment") or {}).get("payment_id"), e.get("delta"), e.get("balance_after"), e.get("revision"),
             (e.get("payment") or {}).get("amount")) for e in st.get("entries", [])]


def revs(S, h, pid):
    r = S.call("GET", f"/payments/{pid}/revisions", as_=h)
    if r.status != 200 or not isinstance(r.j, dict) or not isinstance(r.j.get("revisions"), list):
        raise c1.CheckError(f"GET /payments/{pid}/revisions as {h} expected 200, got {r!r}")
    return r.j["revisions"]


def correct(S, who, pid, expected, amount, effective, reason="fix", key=None, **over):
    body = {"expected_revision": expected, "amount": amount, "effective_at": effective if isinstance(effective, str) else iso(effective), "reason": reason}
    body.update(over)
    return S.call("POST", f"/payments/{pid}/corrections", body, as_=who, key=key or k())


def histfx():
    """Seeded history. Openings: ada 10400, bob 2200, cy 0, dan 400, op 1000 (sum 14000)."""
    t1, t2, t3 = ago(days=10), ago(days=9), ago(days=8)
    fx = basefx(requests=[])
    fx["payments"] = [
        {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public", "created_at": iso(t1)},
        {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_dan", "amount": 200, "note": "secret", "visibility": "private", "created_at": iso(t2)},
        {"id": "p_3", "from_user_id": "u_dan", "to_user_id": "u_ada", "amount": 100, "note": "back", "visibility": "public", "created_at": iso(t3)}]
    return fx, (t1, t2, t3)


def cyfx():
    """cy: opening 0, +300 (f1, -5d), -300 (f2, -4d), +1000 (f3, -1d) -> 1000 now."""
    f1, f2, f3 = ago(days=5), ago(days=4), ago(days=1)
    fx = basefx(requests=[])
    fx["users"][2]["balance"] = 1000
    fx["payments"] = [
        {"id": "f1", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 300, "note": "", "visibility": "public", "created_at": iso(f1)},
        {"id": "f2", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 300, "note": "", "visibility": "public", "created_at": iso(f2)},
        {"id": "f3", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 1000, "note": "", "visibility": "public", "created_at": iso(f3)}]
    return fx, (f1, f2, f3)


def total_at(S, **params):
    return sum(me(S, h, **params).get("balance") for h in HS)


def tick(s=0.3):
    time.sleep(s)
    d = now()
    time.sleep(s)
    return d


# --------------------------------------------------------------------------- W
@check("W1-payment-timestamps", "stage-3 Payment timestamps", "W1,W2,W3,W4,W5", "Seeded created_at is kept; omission uses reset time, before later API payments; a seeded created_at in the future is a reset 422 with no state change; fixture balance is not changed by loading payments; /activity stays ordered by created_at; opening balance = ending balance minus the net of seeded payments; new accounts open at zero")
def c_stamps(t, S):
    fx, (t1, t2, t3) = histfx()
    S.reset(fx)
    tok = S.token("ada")
    t.eq(S.bals(HS), {"ada": 10000, "bob": 2500, "cy": 0, "dan": 500, "op": 1000}, "balances after loading seeded payments")
    a = S.acts("ada")
    t.eq(ids(a, "payment_id"), ["p_3", "p_1"], "ada's /activity newest first by seeded created_at")
    for p, tt in zip(a, (t3, t1)):
        tsok(t, p.get("created_at"), "seeded created_at")
        t.eq(parse_ts(p["created_at"]), tt, f"seeded created_at of {p.get('payment_id')} kept as the same instant")
    bad = dict(fx, payments=fx["payments"] + [{"id": "p_f", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1, "note": "", "visibility": "public", "created_at": iso(now() + dt.timedelta(days=1))}])
    t.err(S.call("POST", "/_test/reset", bad), 422, "validation_failed", "reset with a seeded created_at one day in the future")
    r = S.call("GET", "/me", token=tok)
    t.ok(r.status == 200 and (r.j or {}).get("balance") == 10000, f"state changed by the rejected reset: {r!r}")
    before = now()
    S.reset(basefx())
    after = now()
    p1 = next(p for p in S.acts("ada") if p["payment_id"] == "p_1")
    t.ok(before - dt.timedelta(seconds=2) <= parse_ts(p1["created_at"]) <= after + dt.timedelta(seconds=2), f"seeded payment without created_at must use reset time: {p1['created_at']}")
    r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 5}, as_="ada", key=k())
    t.ok(parse_ts(r.j["created_at"]) >= parse_ts(p1["created_at"]), "API payment created before the reset-time seeded payment")
    t.eq(ids(S.acts("ada"), "payment_id")[0], r.j["payment_id"], "API payment is newest in the feed")
    fx, (t1, t2, t3) = histfx()
    S.reset(fx)
    old = iso(ago(days=30))
    exp = {"ada": 10400, "bob": 2200, "cy": 0, "dan": 400, "op": 1000}
    for h, v in exp.items():
        t.eq(me(S, h, as_of=old).get("balance"), v, f"{h} opening balance (as_of before the earliest payment)")
    r = S.call("POST", "/auth/signup", {"email": "newbie@example.com", "password": "longenough", "display_name": "N"})
    r2 = S.call("GET", "/me" + qs(as_of=old), token=(r.j or {}).get("token") or "x")
    t.eq((r2.j or {}).get("balance"), 0, "new account opening balance")


# --------------------------------------------------------------------------- X
@check("X1-me-as-of", "stage-3 GET /me as of an instant", "X1,X2,X3,X4,X5,X7,Z11", "as_of must be RFC 3339 with offset else 422; balance is the balance after every payment at or before as_of (a payment exactly at as_of counts); at/after the latest payment -> current; before the earliest -> opening; future allowed; as_of echoed exactly; the four money fields agree; sum over users equals the seeded total at every instant")
def c_asof(t, S):
    fx, (t1, t2, t3) = histfx()
    S.reset(fx)
    m = me(S, "ada")
    t.eq((m.get("balance"), m.get("total"), m.get("available"), m.get("held")), (10000, 10000, 10000, 0), "/me without temporal parameters")
    t.probe("as_of" not in m and "known_at" not in m, f"/me without temporal parameters carries as_of/known_at: {m}")
    sec = dt.timedelta(seconds=1)
    for label, inst, bal in (("exactly at p_1", t1, 9900), ("1 s before p_1", t1 - sec, 10400), ("1 s after p_1", t1 + sec, 9900),
                             ("1 s before p_3", t3 - sec, 9900), ("exactly at p_3", t3, 10000), ("now", now(), 10000),
                             ("a year ahead", now() + dt.timedelta(days=365), 10000), ("a year back", ago(days=365), 10400)):
        s = iso(inst)
        m = me(S, "ada", as_of=s)
        t.eq(m.get("balance"), bal, f"ada balance as_of {label}")
        t.eq(m.get("as_of"), s, f"as_of echoed exactly ({label})")
        t.ok(m.get("total") == m.get("balance") and m.get("available") == m.get("total", 0) - m.get("held", 0), f"money fields disagree as_of {label}: {m}")
    for inst in (t1 - sec, t1, t2, t3, now()):
        t.eq(total_at(S, as_of=iso(inst)), 14000, f"sum of balances as_of {iso(inst)}")
    # the same instant in other spellings, echoed as given
    z = t1.strftime("%Y-%m-%dT%H:%M:%SZ")
    off = t1.astimezone(dt.timezone(dt.timedelta(hours=2))).isoformat()
    neg = (t1 - sec).astimezone(dt.timezone(dt.timedelta(hours=-5, minutes=-30))).isoformat()
    frac = (t1 - dt.timedelta(microseconds=1)).isoformat()
    for s, bal in ((z, 9900), (off, 9900), (neg, 10400), (frac, 10400)):
        m = me(S, "ada", as_of=s)
        t.eq((m.get("balance"), m.get("as_of")), (bal, s), f"as_of={s}")
    for bad in (t1.strftime("%Y-%m-%dT%H:%M:%S"), t1.strftime("%Y-%m-%d"), "", "garbage", "1727180400", t1.strftime("%Y-%m-%d %H:%M:%S"), "2026-13-45T99:00:00+00:00"):
        for par_ in ("as_of", "known_at"):
            t.err(S.call("GET", "/me" + qs(**{par_: bad}), as_="ada"), 422, "validation_failed", f"GET /me {par_}={bad!r}")
    r = S.call("GET", "/me?as_of=" + iso(t1), as_="ada")
    t.probe(is_err(r, 422, "validation_failed"), f"as_of with an unencoded '+' (decodes to a space): got {r.status}")
    t.err(S.call("GET", "/me" + qs(as_of=iso(t1))), 401, "unauthenticated", "GET /me?as_of without token")
    t.eq(me(S, "ada", as_of=iso(now()), zzz="1").get("balance"), 10000, "unknown query parameter ignored")


# --------------------------------------------------------------------------- Y
@check("Y1-statement", "stage-3 GET /statement", "Y1,Y2,Y3,Y4,Y5,Y8,Y10,W1", "Statement: only the caller's payments (private included, others' public excluded), oldest first, half-open window [from, to), delta sign, balance_after, opening/closing balances, opening + deltas = closing; revision fields; ties ordered by payment id; from/to validated; auth required")
def c_statement(t, S):
    fx, (t1, t2, t3) = histfx()
    S.reset(fx)
    st = stmt(S, "ada")
    for kk in ("opening_balance", "entries", "closing_balance", "has_more", "snapshot"):
        t.ok(kk in st, f"statement lacks '{kk}'")
    t.ok(isinstance(st.get("snapshot"), str) and st.get("snapshot"), f"snapshot token must be a non-empty string: {st.get('snapshot')!r}")
    t.eq((st.get("opening_balance"), st.get("closing_balance"), st.get("has_more")), (10400, 10000, False), "ada full statement opening/closing/has_more")
    t.eq(rows(st), [("p_1", -500, 9900, 1, 500), ("p_3", 100, 10000, 1, 100)], "ada entries (id, delta, balance_after, revision, amount), oldest first")
    for e, tt in zip(st["entries"], (t1, t3)):
        for kk in ("payment", "delta", "balance_after", "revision", "effective_at", "recorded_at"):
            t.ok(kk in e, f"entry lacks '{kk}'")
        pay_shape(t, e.get("payment"), "statement payment")
        tsok(t, e.get("effective_at"), "entry effective_at")
        tsok(t, e.get("recorded_at"), "entry recorded_at")
        t.ok(parse_ts(e["effective_at"]) == tt == parse_ts(e["recorded_at"]) == parse_ts(e["payment"]["created_at"]), f"revision 1 effective_at = recorded_at = created_at: {e}")
    t.eq(rows(stmt(S, "bob")), [("p_1", 500, 2700, 1, 500), ("p_2", -200, 2500, 1, 200)], "bob entries (private payment included)")
    t.eq(rows(stmt(S, "dan")), [("p_2", 200, 600, 1, 200), ("p_3", -100, 500, 1, 100)], "dan entries")
    st = stmt(S, "cy")
    t.eq((st.get("opening_balance"), st.get("entries"), st.get("closing_balance"), st.get("has_more")), (0, [], 0, False), "cy statement (public payments of others excluded)")
    sec = dt.timedelta(seconds=1)
    for label, f, to, opening, closing, got in (
            ("from = p_1 time (included)", t1, None, 10400, 10000, ["p_1", "p_3"]),
            ("from just after p_1", t1 + sec, None, 9900, 10000, ["p_3"]),
            ("to = p_3 time (excluded)", None, t3, 10400, 9900, ["p_1"]),
            ("to just after p_3", None, t3 + sec, 10400, 10000, ["p_1", "p_3"]),
            ("[p_1, p_3)", t1, t3, 10400, 9900, ["p_1"]),
            ("to = p_1 time", None, t1, 10400, 10400, []),
            ("from = p_3 time", t3, None, 9900, 10000, ["p_3"]),
            ("from after everything", t3 + sec, None, 10000, 10000, []),
            ("to in the future", None, now() + dt.timedelta(days=30), 10400, 10000, ["p_1", "p_3"])):
        st = stmt(S, "ada", **{"from": iso(f) if f else None, "to": iso(to) if to else None})
        t.eq((st.get("opening_balance"), st.get("closing_balance"), [r[0] for r in rows(st)]), (opening, closing, got), f"window {label}")
        t.eq(st.get("opening_balance") + sum(e["delta"] for e in st["entries"]), st.get("closing_balance"), f"opening + deltas = closing ({label})")
    for par_ in ("from", "to", "known_at"):
        for bad in (t1.strftime("%Y-%m-%dT%H:%M:%S"), t1.strftime("%Y-%m-%d"), "", "yesterday"):
            t.err(S.call("GET", "/statement" + qs(**{par_: bad}), as_="ada"), 422, "validation_failed", f"GET /statement {par_}={bad!r}")
    for q in ("?limit=0", "?limit=201", "?limit=1e1", "?limit=4.0", "?offset=-1", "?offset=%2B4", "?limit=abc"):
        t.err(S.call("GET", "/statement" + q, as_="ada"), 422, "validation_failed", f"GET /statement{q}")
    t.err(S.call("GET", "/statement"), 401, "unauthenticated", "GET /statement without token")
    t.eq(rows(stmt(S, "ada", zzz="1", limit="200")), [("p_1", -500, 9900, 1, 500), ("p_3", 100, 10000, 1, 100)], "unknown query parameter ignored")
    # ties: same instant, ordered by payment id
    tie = ago(days=3)
    fx = basefx(requests=[])
    fx["payments"] = [{"id": pid, "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": a, "note": "", "visibility": "public", "created_at": iso(tie)}
                      for pid, a in (("p_c", 3), ("p_a", 1), ("p_b", 2))]
    S.reset(fx)
    t.eq(rows(stmt(S, "ada")), [("p_a", -1, 10005, 1, 1), ("p_b", -2, 10003, 1, 2), ("p_c", -3, 10000, 1, 3)], "equal timestamps ordered by payment id ascending")
    r = S.call("POST", "/settlements", {"transfers": [tr("ada", "bob", 10), tr("bob", "ada", 4), tr("ada", "cy", 6)]}, as_="op", key=k())
    mem = sorted(p["payment_id"] for p in (r.j or {}).get("payments", []))
    got = [x[0] for x in rows(stmt(S, "ada")) if x[0] in mem]
    t.eq(got, mem, "settlement members (one committed_at) appear ordered by payment id")
    st = stmt(S, "ada")
    t.ok(all(e["payment"].get("settlement_id") == (r.j or {}).get("settlement_id") for e in st["entries"] if e["payment"]["payment_id"] in mem), "settlement members keep settlement_id in the statement")
    t.eq(st["closing_balance"], S.bal("ada"), "closing balance equals the current balance")


@check("Y6-statement-paging", "stage-3 GET /statement requirement 4; Stable statement pagination", "Y6,AA1,AA2,AA3,AA4,AA5,AC6", "Paging never changes balance_after, opening or closing; has_more right on the final partial page and beyond the end; snapshot token pages the frozen result after later payments, corrections and hold actions; only limit/offset may accompany it; unknown, foreign or pre-reset tokens are 404")
def c_paging(t, S):
    S.reset(basefx(payments=[], requests=[]))
    made = []
    for i in range(7):
        frm, to = ("ada", "bob") if i % 2 == 0 else ("bob", "ada")
        r = S.call("POST", "/payments", {"to_handle": to, "amount": 10 + i, "note": f"n{i}"}, as_=frm, key=k())
        made.append(r.j["payment_id"])
        time.sleep(0.02)
    full = stmt(S, "ada", limit="200")
    t.eq([x[0] for x in rows(full)], made, "one-shot statement holds the 7 payments oldest first")
    t.eq((full["opening_balance"], full["closing_balance"], full["has_more"]), (10000, S.bal("ada"), False), "one-shot opening/closing/has_more")
    tok = full.get("snapshot")
    for lim in (1, 2, 3, 7):
        got = []
        for off in range(0, 7, lim):
            pg = stmt(S, "ada", limit=str(lim), offset=str(off), to=iso(now() + dt.timedelta(hours=1)))
            t.eq((pg["opening_balance"], pg["closing_balance"]), (full["opening_balance"], full["closing_balance"]), f"limit={lim} offset={off}: opening/closing describe the full window")
            t.eq(pg["has_more"], off + lim < 7, f"limit={lim} offset={off}: has_more")
            got += pg["entries"]
        t.ok([{kk: v for kk, v in e.items()} for e in got] == full["entries"], f"pages with limit={lim} differ from the one-shot entries")
    for off, n in ((7, 0), (100, 0), (6, 1)):
        pg = stmt(S, "ada", offset=str(off))
        t.eq((len(pg["entries"]), pg["has_more"]), (n, False), f"offset={off}")
    # mutate: payment, correction, hold lifecycle
    other = stmt(S, "bob").get("snapshot")
    S.call("POST", "/payments", {"to_handle": "bob", "amount": 999}, as_="ada", key=k())
    t.st(correct(S, "ada", made[0], 1, 1, now() - dt.timedelta(seconds=1)), 201, "correction after the snapshot")
    aid = mk_auth(t, S, "ada", "bob", 50)
    cap(S, "bob", aid, {"amount": 20})
    live = stmt(S, "ada", limit="200")
    t.ok(live["entries"] != full["entries"] and live["closing_balance"] != full["closing_balance"], "a fresh statement must reflect the later payment, correction and capture")
    snap = stmt(S, "ada", snapshot=tok, limit="200")
    t.ok(snap["entries"] == full["entries"] and (snap["opening_balance"], snap["closing_balance"], snap["has_more"]) == (full["opening_balance"], full["closing_balance"], False),
         f"snapshot result changed after later writes: {rows(snap)} vs {rows(full)}")
    got = []
    for off in range(0, 7, 3):
        pg = stmt(S, "ada", snapshot=tok, limit="3", offset=str(off), zzz="1")
        t.eq(pg["has_more"], off + 3 < 7, f"snapshot paging offset={off}: has_more")
        got += pg["entries"]
    t.ok(got == full["entries"], "snapshot pages differ from the frozen one-shot entries")
    pg = stmt(S, "ada", snapshot=tok, offset="50")
    t.eq((pg["entries"], pg["has_more"], pg["closing_balance"]), ([], False, full["closing_balance"]), "snapshot offset beyond the end")
    for extra in ({"from": iso(ago(days=1))}, {"to": iso(now())}, {"known_at": iso(now())}):
        t.err(S.call("GET", "/statement" + qs(snapshot=tok, **extra), as_="ada"), 422, "validation_failed", f"snapshot with {list(extra)[0]}")
    for q in ({"limit": "0"}, {"limit": "201"}, {"offset": "-1"}, {"limit": "1e1"}):
        t.err(S.call("GET", "/statement" + qs(snapshot=tok, **q), as_="ada"), 422, "validation_failed", f"snapshot with {q}")
    t.err(S.call("GET", "/statement" + qs(snapshot="no-such-token"), as_="ada"), 404, "not_found", "unknown snapshot token")
    t.err(S.call("GET", "/statement" + qs(snapshot=tok), as_="bob"), 404, "not_found", "another user's snapshot token")
    t.err(S.call("GET", "/statement" + qs(snapshot=other), as_="ada"), 404, "not_found", "another user's snapshot token (reverse)")
    t.err(S.call("GET", "/statement" + qs(snapshot=tok)), 401, "unauthenticated", "snapshot without token")
    S.reset(basefx(payments=[], requests=[]))
    t.err(S.call("GET", "/statement" + qs(snapshot=tok), as_="ada"), 404, "not_found", "snapshot token from before a reset")


# --------------------------------------------------------------------------- Z
@check("Z1-revisions", "stage-3 Effective time, recorded time, and corrections", "Z1,Z13", "Every payment has revision 1 (original amount, effective_at = recorded_at = created_at, reason \"\"); /revisions readable only by the two parties: third party 404 even for a public payment, unknown 404, no token 401")
def c_revisions(t, S):
    fx, (t1, t2, t3) = histfx()
    S.reset(fx)
    for h in ("ada", "bob"):
        rv = revs(S, h, "p_1")
        t.eq(len(rv), 1, f"{h}: revisions of p_1")
        r1 = rv[0] if rv else {}
        for kk in REV_KEYS:
            t.ok(kk in r1, f"revision lacks '{kk}'")
        t.eq((r1.get("payment_id"), r1.get("revision"), r1.get("amount"), r1.get("reason")), ("p_1", 1, 500, ""), f"{h}: revision 1 of p_1")
        t.ok(parse_ts(r1["effective_at"]) == parse_ts(r1["recorded_at"]) == t1, f"revision 1 times must equal the seeded created_at: {r1}")
    for h in ("cy", "dan", "op"):
        t.err(S.call("GET", "/payments/p_1/revisions", as_=h), 404, "not_found", f"{h} (third party) reads revisions of a public payment")
    t.err(S.call("GET", "/payments/p_nope/revisions", as_="ada"), 404, "not_found", "revisions of an unknown payment")
    t.err(S.call("GET", "/payments/p_1/revisions"), 401, "unauthenticated", "revisions without token")
    r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 77}, as_="ada", key=k())
    rv = revs(S, "bob", r.j["payment_id"])
    t.ok(len(rv) == 1 and rv[0].get("amount") == 77 and rv[0].get("revision") == 1 and rv[0].get("reason") == "" and
         parse_ts(rv[0]["effective_at"]) == parse_ts(rv[0]["recorded_at"]) == parse_ts(r.j["created_at"]), f"revision 1 of an API payment: {rv} vs created_at {r.j['created_at']}")
    r = S.call("POST", "/settlements", {"transfers": [tr("ada", "bob", 5)]}, as_="op", key=k())
    rv = revs(S, "ada", r.j["payments"][0]["payment_id"])
    t.ok(len(rv) == 1 and parse_ts(rv[0]["effective_at"]) == parse_ts(rv[0]["recorded_at"]) == parse_ts(r.j["committed_at"]), f"settlement member revision 1 uses committed_at: {rv}")
    t.err(S.call("GET", f"/payments/{r.j['payments'][0]['payment_id']}/revisions", as_="op"), 404, "not_found", "operator (not a party) reads revisions of a settlement member")


@check("Z2-correction-rules", "stage-3 corrections (request rules)", "Z2,Z3,Z10,Z14", "Corrections: key required, original sender only (403 for receiver and third party), unknown payment 404, no token 401; all four fields required; expected_revision positive integer; amount integer 0..1e9; reason 1..200 characters; effective_at RFC 3339 not later than now; invalid input 422 and nothing changes; settlement members and captures are 422 linked_payment_immutable")
def c_corr_rules(t, S):
    fx, (t1, t2, t3) = histfx()
    S.reset(fx)
    good = {"expected_revision": 1, "amount": 400, "effective_at": iso(t1), "reason": "corrected amount"}
    path = "/payments/p_1/corrections"
    before = (S.bals(HS), revs(S, "ada", "p_1"), stmt(S, "ada")["entries"], stmt(S, "bob")["entries"])
    t.err(S.call("POST", path, good, key=k()), 401, "unauthenticated", "correction without token")
    t.err(S.call("POST", path, good, as_="ada"), 400, "missing_idempotency_key", "correction without key")
    t.err(S.call("POST", path, good, as_="ada", headers={"Idempotency-Key": ""}), 400, "missing_idempotency_key", "correction with empty key")
    t.err(S.call("POST", path, good, as_="ada", key="K" * 256), 422, "validation_failed", "correction with 256-char key")
    t.err(S.call("POST", path, good, as_="bob", key=k()), 403, "forbidden", "receiver corrects")
    t.err(S.call("POST", path, good, as_="cy", key=k()), 403, "forbidden", "third party corrects")
    t.err(S.call("POST", "/payments/p_nope/corrections", good, as_="ada", key=k()), 404, "not_found", "correct an unknown payment")
    t.err(S.call("POST", path, raw="{bad", as_="ada", key=k()), 400, "malformed_request", "unparseable correction body")
    keys = []
    for f in good:
        kk = k()
        keys.append(kk)
        t.err(S.call("POST", path, {a: b for a, b in good.items() if a != f}, as_="ada", key=kk), 422, "validation_failed", f"correction without {f}")
    bad = {"expected_revision": [0, -1, 1.5, "1", True, None],
           "amount": [-1, 1000000001, 1.5, "400", True, None],
           "reason": ["", "x" * 201],
           "effective_at": [iso(now() + dt.timedelta(hours=1)), iso(now() + dt.timedelta(days=400)), t1.strftime("%Y-%m-%dT%H:%M:%S"), t1.strftime("%Y-%m-%d"), "", "garbage"]}
    for f, vals in bad.items():
        for v in vals:
            shown = v if not (isinstance(v, str) and len(v) > 40) else f"<{len(v)} chars>"
            t.err(S.call("POST", path, dict(good, **{f: v}), as_="ada", key=k()), 422, "validation_failed", f"correction {f}={shown!r}")
    for f, v in (("reason", 5), ("reason", None), ("effective_at", 5), ("effective_at", None)):
        t.err_any(S.call("POST", path, dict(good, **{f: v}), as_="ada", key=k()), [(422, "validation_failed"), (400, "malformed_request")], f"correction {f}={v!r}")
    t.err(S.call("POST", path, dict(good, expected_revision=2), as_="ada", key=k()), 409, "stale_revision", "expected_revision ahead of the current revision")
    after = (S.bals(HS), revs(S, "ada", "p_1"), stmt(S, "ada")["entries"], stmt(S, "bob")["entries"])
    t.ok(before == after, "rejected corrections changed balances, revisions or statements")
    # boundaries that must be accepted
    r = S.call("POST", path, dict(good, amount=0, reason="x", zzz=1), as_="ada", key=keys[0])
    t.st(r, 201, "amount 0, 1-character reason, unknown field, key of an earlier failed correction")
    t.eq(S.bals(["ada", "bob"]), {"ada": 10500, "bob": 2000}, "amount 0 reverses the entire payment")
    r = S.call("POST", path, dict(good, expected_revision=2, amount=500, reason="y" * 200, effective_at=iso(now() - dt.timedelta(seconds=1))), as_="ada", key="K" * 255)
    t.st(r, 201, "200-character reason, 255-char key, effective_at just before now")
    S.reset(c1.richfx())
    r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 1}, as_="ada", key=k())
    pid = r.j["payment_id"]
    t.st(correct(S, "ada", pid, 1, 1000000000, parse_ts(r.j["created_at"])), 201, "correct to amount 1000000000")
    t.eq(S.bal("ada"), 5000000000 - 1000000000, "sender debited the difference up to 1e9")
    # linked payments
    S.reset(basefx())
    r = S.call("POST", "/settlements", {"transfers": [tr("ada", "bob", 50)]}, as_="op", key=k())
    mem = r.j["payments"][0]
    t.err(correct(S, "ada", mem["payment_id"], 1, 10, now() - dt.timedelta(seconds=1)), 422, "linked_payment_immutable", "correct a settlement member")
    aid = mk_auth(t, S, "ada", "bob", 200)
    cp = cap(S, "bob", aid, {"amount": 150})
    t.err(correct(S, "ada", cp.j["payment_id"], 1, 10, now() - dt.timedelta(seconds=1)), 422, "linked_payment_immutable", "correct a capture")
    t.eq(len(revs(S, "ada", cp.j["payment_id"])), 1, "capture keeps a single revision")
    t.eq([p for p in S.acts("ada") if p["payment_id"] == mem["payment_id"]], [mem], "settlement member receipt unchanged")
    rp = S.call("POST", "/requests/rq_2/pay", {}, as_="ada", key=k())
    t.st(correct(S, "ada", rp.j["payment_id"], 1, 250, now() - dt.timedelta(seconds=1)), 201, "a payment made by paying a request is an ordinary payment and correctable")


@check("Z4-correction-effects", "stage-3 corrections (effects), known_at", "Z4,Z6,Z7,Z12,Z15,X6,Y7,W5,Z11", "A correction appends an immutable revision (201 body, recorded_at strictly increasing), moves the difference between the same two wallets, leaves the original payment, feed and idempotent responses unchanged; replay returns the original revision; known_at selects the latest revision recorded at or before it; a zero-amount revision stays as an entry with delta 0; effective_at moves a payment between windows; openings never change; sums hold in every view")
def c_corr_effects(t, S):
    fx, (t1, t2, t3) = histfx()
    S.reset(fx)
    kp = k()
    pb = {"to_handle": "bob", "amount": 800, "note": "orig", "visibility": "private"}
    p = S.call("POST", "/payments", pb, as_="ada", key=kp)
    pid = p.j["payment_id"]
    made = parse_ts(p.j["created_at"])
    k0 = tick()
    key1 = k()
    body1 = {"expected_revision": 1, "amount": 600, "effective_at": iso(made), "reason": "corrected amount"}
    r = S.call("POST", f"/payments/{pid}/corrections", body1, as_="ada", key=key1)
    t.st(r, 201, "first correction")
    j = r.j or {}
    for kk in REV_KEYS:
        t.ok(kk in j, f"correction response lacks '{kk}'")
    t.eq((j.get("payment_id"), j.get("revision"), j.get("amount"), j.get("reason")), (pid, 2, 600, "corrected amount"), "correction response")
    tsok(t, j.get("recorded_at"), "recorded_at")
    t.ok(parse_ts(j["effective_at"]) == made, f"effective_at kept: {j.get('effective_at')}")
    t.ok(k0 < parse_ts(j["recorded_at"]) <= now() + dt.timedelta(seconds=2), f"recorded_at must be server time of the correction: {j.get('recorded_at')}")
    t.eq(S.bals(["ada", "bob"]), {"ada": 9400, "bob": 3100}, "decrease of 200 debits the original receiver")
    k1 = tick()
    r2 = correct(S, "ada", pid, 2, 900, made, reason="up")
    t.st(r2, 201, "second correction (increase)")
    t.eq(S.bals(["ada", "bob"]), {"ada": 9100, "bob": 3400}, "increase of 300 debits the original sender")
    rv = revs(S, "bob", pid)
    t.eq([(x.get("revision"), x.get("amount"), x.get("reason")) for x in rv], [(1, 800, ""), (2, 600, "corrected amount"), (3, 900, "up")], "revision history in order")
    t.ok(rv[1] == j, "revision 2 in the history differs from its 201 body")
    rt = [parse_ts(x["recorded_at"]) for x in rv]
    t.ok(rt[0] < rt[1] < rt[2], f"recorded_at must strictly increase: {[x['recorded_at'] for x in rv]}")
    rr = S.call("POST", f"/payments/{pid}/corrections", body1, as_="ada", key=key1)
    t.ok(rr.status == 200 and rr.j == j, f"replay of the first correction after a newer revision: {rr!r}")
    t.err(S.call("POST", f"/payments/{pid}/corrections", dict(body1, amount=601), as_="ada", key=key1), 409, "idempotency_key_reuse", "correction key with another body")
    t.err(correct(S, "ada", pid, 1, 100, made), 409, "stale_revision", "stale expected_revision 1")
    t.err(correct(S, "ada", pid, 2, 100, made), 409, "stale_revision", "stale expected_revision 2")
    t.eq(S.bals(["ada", "bob"]), {"ada": 9100, "bob": 3400}, "replay / stale corrections moved nothing")
    # originals unchanged
    orig = S.call("POST", "/payments", pb, as_="ada", key=kp)
    t.ok(orig.status == 200 and orig.j == p.j, "replay of the original POST /payments must return the original response")
    feed = [x for x in S.acts("bob") if x["payment_id"] == pid]
    t.ok(feed == [p.j], f"/activity must still show the original payment: {feed}")
    t.eq(len(S.acts("bob")), 4, "corrections add no feed items (3 seeded visible to bob + 1)")
    for h in ("cy", "dan"):
        t.ok(pid not in ids(S.acts(h), "payment_id"), "private payment leaked after correction")
    # views
    st = stmt(S, "ada")
    e = [x for x in st["entries"] if x["payment"]["payment_id"] == pid]
    t.ok(len(e) == 1 and (e[0]["delta"], e[0]["revision"], e[0]["payment"]["amount"], e[0]["balance_after"]) == (-900, 3, 900, 9100), f"current statement entry: {rows(st)}")
    t.ok(parse_ts(e[0]["recorded_at"]) == rt[2] and parse_ts(e[0]["effective_at"]) == made, "entry carries the selected revision's times")
    t.eq((st["opening_balance"], st["closing_balance"]), (10400, 9100), "opening unchanged by corrections; closing current")
    for K, amount, rev in ((k0, 800, 1), (k1, 600, 2), (now(), 900, 3), (now() + dt.timedelta(days=1), 900, 3)):
        ks = iso(K)
        sk = stmt(S, "ada", known_at=ks)
        ek = [x for x in sk["entries"] if x["payment"]["payment_id"] == pid]
        t.ok(len(ek) == 1 and (ek[0]["delta"], ek[0]["revision"], ek[0]["payment"]["amount"]) == (-amount, rev, amount), f"statement known_at {ks}: expected revision {rev} amount {amount}, got {rows(sk)}")
        t.eq(sk.get("known_at"), ks, "statement echoes known_at exactly")
        t.eq(sk["closing_balance"], 10000 - amount, f"closing balance known_at {ks}")
        m = me(S, "ada", known_at=ks)
        t.eq((m.get("balance"), m.get("known_at")), (10000 - amount, ks), f"/me known_at {ks}")
        t.eq(me(S, "bob", known_at=ks, as_of=iso(now())).get("balance"), 2500 + amount, f"bob /me known_at {ks}")
        t.eq(total_at(S, known_at=ks), 14000, f"sum of balances known_at {ks}")
    kb = iso(made - dt.timedelta(seconds=5))
    sk = stmt(S, "ada", known_at=kb)
    t.ok(pid not in [x[0] for x in rows(sk)] and sk["closing_balance"] == 10000, f"known_at before the payment was recorded: it contributes nothing: {rows(sk)}")
    t.eq(me(S, "ada", known_at=iso(ago(days=30)), as_of=iso(now())).get("balance"), 10400, "known_at before anything was recorded: opening balance")
    t.eq(total_at(S, known_at=iso(ago(days=30))), 14000, "sum of balances with nothing known")
    # zero-amount revision stays as an entry
    t.st(correct(S, "ada", pid, 3, 0, made, reason="reverse"), 201, "correct to amount 0")
    t.eq(S.bals(["ada", "bob"]), {"ada": 10000, "bob": 2500}, "amount 0 reverses the payment")
    st = stmt(S, "bob")
    e = [x for x in st["entries"] if x["payment"]["payment_id"] == pid]
    t.ok(len(e) == 1 and (e[0]["delta"], e[0]["revision"], e[0]["payment"]["amount"]) == (0, 4, 0), f"zero-amount revision must stay as one entry with delta 0: {rows(st)}")
    t.eq(st["opening_balance"] + sum(x["delta"] for x in st["entries"]), st["closing_balance"], "opening + deltas = closing after corrections")
    # effective time moves a seeded payment between windows
    mid = t1 - dt.timedelta(days=5)
    t.st(correct(S, "ada", "p_1", 1, 500, mid, reason="backdate"), 201, "move p_1 five days earlier (same amount)")
    st = stmt(S, "ada", **{"from": iso(t1 - dt.timedelta(hours=1)), "to": iso(t1 + dt.timedelta(hours=1))})
    t.eq(([x[0] for x in rows(st)], st["opening_balance"], st["closing_balance"]), ([], 9900, 9900), "p_1 moved out of its old window")
    st = stmt(S, "ada", **{"from": iso(mid), "to": iso(mid + dt.timedelta(seconds=1))})
    t.eq((rows(st), st["opening_balance"], st["closing_balance"]), ([("p_1", -500, 9900, 2, 500)], 10400, 9900), "p_1 moved into the new window")
    t.eq(me(S, "ada", as_of=iso(mid)).get("balance"), 9900, "as_of at the new effective time")
    t.eq(me(S, "ada", as_of=iso(mid - dt.timedelta(seconds=1))).get("balance"), 10400, "as_of before the new effective time: opening unchanged")
    t.eq(me(S, "ada", as_of=iso(t1), known_at=iso(k0)).get("balance"), 9900, "known_at before the backdating: old effective time applies")
    t.eq(me(S, "ada", as_of=iso(t1 - dt.timedelta(seconds=1)), known_at=iso(k0)).get("balance"), 10400, "known_at before the backdating, as_of just before the old time")
    for inst in (mid - dt.timedelta(days=1), mid, t1, t2, t3, made, now()):
        t.eq(total_at(S, as_of=iso(inst)), 14000, f"sum of balances as_of {iso(inst)} after corrections")
    full = stmt(S, "ada", limit="200")
    eff = [(parse_ts(x["effective_at"]), x["payment"]["payment_id"]) for x in full["entries"]]
    t.ok(eff == sorted(eff), "statement must be ordered by selected effective_at, then payment id")


@check("Z8-correction-refusals", "stage-3 corrections (insufficient_funds, historical_overdraft)", "Z8,Z9,Z10,Z5", "Currently unaffordable debit -> 409 insufficient_funds (first); otherwise a negative balance at any effective-time boundary -> 409 historical_overdraft, with all movements at one instant combined; failures preserve balances, revisions, statements and the key; concurrent corrections with one expected revision: exactly one succeeds")
def c_corr_refuse(t, S):
    fx, (f1, f2, f3) = cyfx()
    S.reset(fx)
    t.eq(me(S, "cy", as_of=iso(ago(days=30))).get("balance"), 0, "cy opening balance")
    before = (S.bals(HS), revs(S, "cy", "f2"), stmt(S, "cy")["entries"])
    kk = k()
    t.err(correct(S, "cy", "f2", 1, 400, f2, key=kk), 409, "historical_overdraft", "increase f2 to 400 at its own time: cy would be -100 four days ago (now affordable)")
    t.err(correct(S, "cy", "f2", 1, 300, f1 - dt.timedelta(days=1)), 409, "historical_overdraft", "move f2 before the payment that funded it")
    t.err(correct(S, "cy", "f2", 1, 1301, f2), 409, "insufficient_funds", "increase beyond the current balance: insufficient_funds comes first")
    t.ok(before == (S.bals(HS), revs(S, "cy", "f2"), stmt(S, "cy")["entries"]), "refused corrections changed balances, revisions or statements")
    r = correct(S, "cy", "f2", 1, 300, f1, key=kk)
    t.st(r, 201, "move f2 to exactly the instant of its funding payment (combined effect 0), reusing the key of a refused correction")
    t.eq(me(S, "cy", as_of=iso(f1)).get("balance"), 0, "cy balance at the shared instant")
    t.st(correct(S, "cy", "f2", 2, 300, f2, reason="move back"), 201, "move f2 back")
    # receiver cannot cover a decrease now
    S.call("POST", "/payments", {"to_handle": "dan", "amount": 2400}, as_="bob", key=k())
    t.eq(S.bal("bob"), 100, "bob left with 100")
    t.err(correct(S, "cy", "f2", 3, 100, f2), 409, "insufficient_funds", "decrease of 200 while the receiver holds 100")
    t.st(correct(S, "cy", "f2", 3, 200, f2), 201, "decrease of 100 with the receiver holding exactly 100")
    t.eq(S.bals(["cy", "bob"]), {"cy": 1100, "bob": 0}, "decrease debits the receiver")
    # held funds do not cover a correction
    fx, (f1, f2, f3) = cyfx()
    S.reset(fx)
    mk_auth(t, S, "cy", "dan", 950)
    t.err(correct(S, "cy", "f2", 1, 351, f2), 409, "insufficient_funds", "increase of 51 with available 50 (held 950)")
    # receiver decrease that breaks the receiver's history: bob spent the money in between
    fx = basefx(requests=[])
    a, b, c = ago(days=6), ago(days=5), ago(days=2)
    fx["users"][3]["balance"] = 0
    fx["users"][1]["balance"] = 2500
    fx["payments"] = [
        {"id": "g1", "from_user_id": "u_ada", "to_user_id": "u_dan", "amount": 400, "note": "", "visibility": "public", "created_at": iso(a)},
        {"id": "g2", "from_user_id": "u_dan", "to_user_id": "u_bob", "amount": 400, "note": "", "visibility": "public", "created_at": iso(b)},
        {"id": "g3", "from_user_id": "u_bob", "to_user_id": "u_dan", "amount": 400, "note": "", "visibility": "public", "created_at": iso(c)}]
    fx["users"][3]["balance"] = 400
    S.reset(fx)
    t.eq(me(S, "dan", as_of=iso(ago(days=30))).get("balance"), 0, "dan opening balance")
    t.err(correct(S, "ada", "g1", 1, 100, a), 409, "historical_overdraft", "decrease g1 to 100: dan would be -300 between g2 and g3 (now affordable)")
    t.st(correct(S, "ada", "g1", 1, 100, c), 409, "decrease g1 and move it to the time of g3: dan is -400 after g2")
    t.eq(S.bals(["ada", "dan"]), {"ada": 10000, "dan": 400}, "nothing moved by refused corrections")
    # concurrency
    S.reset(basefx(payments=[], requests=[]))
    p = S.call("POST", "/payments", {"to_handle": "bob", "amount": 100}, as_="ada", key=k())
    pid, made = p.j["payment_id"], parse_ts(p.j["created_at"])
    rs = par([lambda i=i: correct(S, "ada", pid, 1, 101 + i, made, reason=f"r{i}") for i in range(20)])
    t.ok(sum(r.status == 201 for r in rs) == 1 and all(r.status == 201 or is_err(r, 409, "stale_revision") for r in rs),
         f"20 concurrent corrections with expected_revision 1: expected 1x201 + 19x409 stale_revision, got {sorted(r.status for r in rs)}")
    win = next((r.j for r in rs if r.status == 201), {})
    rv = revs(S, "ada", pid)
    t.ok(len(rv) == 2 and rv[1] == win, f"exactly one new revision: {rv}")
    t.eq(S.bals(["ada", "bob"]), {"ada": 10000 - win.get("amount", 0), "bob": 2500 + win.get("amount", 0)}, "balances match the single winning correction")
    key = k()
    body = {"expected_revision": 2, "amount": 50, "effective_at": iso(made), "reason": "same"}
    rs = par([lambda: S.call("POST", f"/payments/{pid}/corrections", body, as_="ada", key=key) for _ in range(20)])
    first = next((r for r in rs if r.status == 201), None)
    t.ok(first is not None and sum(r.status == 201 for r in rs) == 1 and all(r.status == 200 and r.j == first.j for r in rs if r is not first),
         f"20 identical corrections with one key: {sorted(r.status for r in rs)}")
    t.eq(S.bals(["ada", "bob"]), {"ada": 9950, "bob": 2550}, "identical corrections applied once")
    t.eq(sum(S.bals(HS).values()), 14000, "sum of balances")


# --------------------------------------------------------------------------- AC
@check("AC1-historical-holds", "stage-3 Historical holds", "AC1,AC2,AC3,AC4,X7,Y9", "closed_at null while open and the event time when closed (expires_at for expiry); /me?as_of&known_at: a hold starts at creation, shrinks at a nonfinal capture, is released at final capture/void/expiry; events are known at their time, the deadline once creation is known; future views expire open holds; seeded open holds start at reset unless created_at is supplied; statements hold money movements only, a capture once")
def c_hist_holds(t, S):
    S.reset(basefx(payments=[], requests=[]))
    q0 = tick(0.2)
    aid = mk_auth(t, S, "ada", "bob", 1000)
    a0 = auth_by_id(S, "ada", aid) or {}
    t.ok("closed_at" in a0 and a0.get("closed_at") is None, f"closed_at must be null while open: {a0.get('closed_at', 'MISSING')!r}")
    q1 = tick(0.2)
    c_ = cap(S, "bob", aid, {"amount": 300, "final": False})
    q2 = tick(0.2)
    v = S.call("POST", f"/authorizations/{aid}/void", as_="ada")
    t.st(v, 200, "void")
    q3 = tick(0.2)
    tsok(t, (v.j or {}).get("closed_at"), "closed_at after void")
    t.ok(q2 < parse_ts(v.j["closed_at"]) < q3, f"closed_at must be the void time: {v.j.get('closed_at')}")
    for label, T, K, exp in (("before creation", q0, None, (10000, 10000, 0)), ("after creation", q1, None, (10000, 9000, 1000)),
                             ("after the nonfinal capture", q2, None, (9700, 9000, 700)), ("after the void", q3, None, (9700, 9700, 0)),
                             ("now, known before the void", q3, q2, (9700, 9000, 700)), ("now, known before the capture", q3, q1, (10000, 9000, 1000)),
                             ("now, known before creation", q3, q0, (10000, 10000, 0)),
                             ("2 h ahead, known before the void (deadline passed)", now() + dt.timedelta(hours=2), q2, (9700, 9700, 0))):
        m = me(S, "ada", as_of=iso(T), known_at=iso(K) if K else None)
        t.eq((m.get("total"), m.get("available"), m.get("held")), exp, f"ada (total, available, held) {label}")
        t.ok(m.get("balance") == m.get("total"), f"balance != total {label}")
    t.eq(me(S, "bob", as_of=iso(q1)).get("total"), 2500, "receiver before the capture")
    t.eq(me(S, "bob", as_of=iso(q2)).get("total"), 2800, "receiver after the capture")
    st = stmt(S, "ada")
    t.eq([(x[0], x[1]) for x in rows(st)], [(c_.j["payment_id"], -300)], "statement holds the capture once and no hold/void entries")
    t.eq(st["entries"][0]["payment"].get("authorization_id"), aid, "capture entry keeps its authorization link")
    # final capture closes at capture time; open hold released at its deadline in future views
    a2 = mk_auth(t, S, "ada", "bob", 400)
    q4 = tick(0.2)
    cap(S, "bob", a2, {"amount": 100})
    x = auth_by_id(S, "ada", a2) or {}
    t.ok(x.get("closed_at") and q4 < parse_ts(x["closed_at"]) <= now(), f"closed_at after a final capture: {x.get('closed_at')!r}")
    a3 = mk_auth(t, S, "ada", "bob", 250)
    m = me(S, "ada")
    t.eq((m.get("total"), m.get("held")), (9600, 250), "current view with an open hold")
    m = me(S, "ada", as_of=iso(now() + dt.timedelta(hours=2)))
    t.eq((m.get("total"), m.get("available"), m.get("held")), (9600, 9600, 0), "view beyond the deadline: the open hold has expired")
    t.eq(me(S, "ada", as_of=iso(q4)).get("held"), 400, "between creating and capturing the second hold")
    # clock expiry: closed_at = expires_at
    S.reset(basefx(payments=[], requests=[], authorization_ttl_seconds=2))
    aid = mk_auth(t, S, "ada", "bob", 500)
    cr = parse_ts((auth_by_id(S, "ada", aid) or {}).get("created_at"))
    time.sleep(3.2)
    x = auth_by_id(S, "ada", aid) or {}
    t.ok(x.get("status") == "expired" and x.get("closed_at") and parse_ts(x["closed_at"]) == parse_ts(x["expires_at"]), f"expired authorization: closed_at must equal expires_at: {x}")
    t.eq(me(S, "ada", as_of=iso(cr + dt.timedelta(seconds=1))).get("held"), 500, "one second after creation, before the deadline")
    t.eq(me(S, "ada", as_of=x["expires_at"]).get("held"), 0, "exactly at expires_at the hold is released")
    t.eq(me(S, "ada", as_of=iso(cr - dt.timedelta(seconds=1))).get("held"), 0, "before creation")
    # seeded holds
    old = ago(days=2)
    fx = basefx(payments=[], requests=[], authorizations=[
        {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "", "visibility": "public", "status": "open", "expires_at": iso(now() + dt.timedelta(hours=2))},
        {"id": "a_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 700, "note": "", "visibility": "public", "status": "open", "expires_at": iso(now() + dt.timedelta(hours=3)), "created_at": iso(old)},
        {"id": "a_3", "from_user_id": "u_dan", "to_user_id": "u_ada", "amount": 100, "note": "", "visibility": "public", "status": "voided", "expires_at": iso(now() + dt.timedelta(hours=3))}])
    S.reset(fx)
    t.eq(me3(S, "ada"), (10000, 8000, 2000), "seeded open hold now")
    t.eq(me(S, "ada", as_of=iso(ago(days=1))).get("held"), 0, "seeded open hold without created_at is assumed created at reset: none a day before")
    t.eq(me(S, "bob", as_of=iso(ago(days=1))).get("held"), 700, "seeded open hold with created_at two days ago: held a day ago")
    t.eq(me(S, "bob", as_of=iso(ago(days=3))).get("held"), 0, "before its supplied created_at")
    t.eq(me(S, "dan", as_of=iso(ago(days=1))).get("held"), 0, "seeded closed hold holds nothing in the past")
    t.eq(me(S, "ada", as_of=iso(now() + dt.timedelta(hours=2, minutes=1))).get("held"), 0, "after the seeded deadline")
    t.eq(stmt(S, "ada")["entries"], [], "authorizations are not statement entries")


@check("AC5-overdraft-with-holds", "stage-3 Historical holds (corrections)", "AC5,Z8,Z9", "A correction that makes available (total - held) negative at a past boundary is 409 historical_overdraft; a current shortfall is insufficient_funds first")
def c_hold_overdraft(t, S):
    S.reset(basefx(payments=[], requests=[]))
    p = S.call("POST", "/payments", {"to_handle": "cy", "amount": 1000}, as_="ada", key=k())
    pid, made = p.j["payment_id"], parse_ts(p.j["created_at"])
    time.sleep(0.2)
    aid = mk_auth(t, S, "cy", "bob", 800)
    t.err(correct(S, "ada", pid, 1, 500, made), 409, "insufficient_funds", "decrease of 500 while cy's available is 200 (hold open)")
    time.sleep(0.2)
    t.st(S.call("POST", f"/authorizations/{aid}/void", as_="cy"), 200, "void the hold")
    time.sleep(0.2)
    t.eq(me3(S, "cy"), (1000, 1000, 0), "cy after the void")
    t.err(correct(S, "ada", pid, 1, 500, made), 409, "historical_overdraft", "decrease of 500: cy's available would have been -300 while the hold was open")
    t.err(correct(S, "ada", pid, 1, 799, made), 409, "historical_overdraft", "decrease to 799: available -1 during the hold")
    t.eq(S.bals(["ada", "cy"]), {"ada": 9000, "cy": 1000}, "nothing moved")
    t.eq(len(revs(S, "ada", pid)), 1, "no revision appended by refused corrections")
    t.st(correct(S, "ada", pid, 1, 800, made), 201, "decrease to 800: available exactly 0 during the hold")
    t.eq(S.bals(["ada", "cy"]), {"ada": 9200, "cy": 800}, "balances after the accepted correction")


# --------------------------------------------------------------------------- AB
def _consistent(t, S, toks, label, total):
    old = iso(ago(days=400))
    s_open = s_now = 0
    for h, tok in toks.items():
        cur = S.call("GET", "/me", token=tok).j or {}
        opn = S.call("GET", "/me" + qs(as_of=old), token=tok).j or {}
        st = S.call("GET", "/statement?limit=200", token=tok).j or {}
        ent = st.get("entries") or []
        t.ok(st.get("closing_balance") == cur.get("balance") and st.get("opening_balance") == opn.get("balance") and
             st.get("opening_balance", 0) + sum(e.get("delta", 0) for e in ent) == st.get("closing_balance"),
             f"{label}: {h} statement inconsistent with balances: opening {st.get('opening_balance')} / as_of-old {opn.get('balance')}, closing {st.get('closing_balance')} / current {cur.get('balance')}")
        t.ok(all(e.get("revision") == 1 for e in ent), f"{label}: {h} imported payments must be at revision 1")
        s_open += opn.get("balance", 0)
        s_now += cur.get("balance", 0)
    t.eq((s_open, s_now), (total, total), f"{label}: sum of opening balances and of current balances")


@check("AB1-import-earlier-stages", "stage-3 Settlement history (exports of stage 1 and stage 2)", "AB1", "A stage-3 service accepts exports of this team's stage-1 and stage-2 services; imported payments get revision 1, opening balances are derived, statements and as_of agree with imported balances; captures are immutable linked payments; holds survive")
def c_import_old(t, S):
    b1, b2 = os.environ.get("S1BASE"), os.environ.get("S2BASE")
    if not (b1 and b2):
        t.ok(False, "not run: needs S1BASE and S2BASE (running stage-1 and stage-2 containers)")
        return
    S1 = c1.Sess(b1)
    ctx = c1.j_prepare(t, S1)
    S.reset(OTHERFX)
    t.st(S.call("POST", "/_test/import", ctx["export"]), 204, "stage-3 import of a stage-1 export")
    S.tok = {}
    toks = {h: v for h, v in ctx["tok"].items() if h != "ada2"}
    snap = c1.j_snapshot(S, ctx)
    for h in ctx["snap"]:
        t.ok(c2.subset(ctx["snap"][h], snap[h]), f"stage-1 import: {h}'s /me, /activity or /requests not preserved")
    _consistent(t, S, toks, "stage-1 import", 14000)
    for name, (who, path, body, key, orig) in ctx["keys"].items():
        r = S.call("POST", path, body, token=ctx["tok"][who], key=key)
        t.ok(r.status == 200 and c2.subset(orig, r.j), f"stage-1 import: replay of {name}: {r!r}"[:260])
    sp = ctx["keys"]["settlement"][4]["payments"][0]
    t.err(S.call("POST", f"/payments/{sp['payment_id']}/corrections", {"expected_revision": 1, "amount": 1, "effective_at": iso(now() - dt.timedelta(seconds=1)), "reason": "x"},
                 token=ctx["tok"]["ada"], key=k()), 422, "linked_payment_immutable", "imported settlement member is immutable")
    pp = ctx["keys"]["payment"][4]
    r = S.call("POST", f"/payments/{pp['payment_id']}/corrections", {"expected_revision": 1, "amount": 200, "effective_at": pp["created_at"], "reason": "x"}, token=ctx["tok"]["ada"], key=k())
    t.st(r, 201, "imported ordinary payment is correctable")
    r = S.call("GET", f"/payments/{pp['payment_id']}/revisions", token=ctx["tok"]["nina"])
    t.ok(r.status == 200 and [x.get("amount") for x in r.j.get("revisions", [])] == [250, 200] and
         parse_ts(r.j["revisions"][0]["effective_at"]) == parse_ts(pp["created_at"]), f"revisions of an imported payment: {r!r}"[:300])
    # stage 2
    S2 = c1.Sess(b2)
    ctx = c2.r_prepare(t, S2)
    S.reset(OTHERFX)
    t.st(S.call("POST", "/_test/import", ctx["export"]), 204, "stage-3 import of a stage-2 export")
    S.tok = {}
    snap = c2.r_snapshot(S, ctx)
    for h in ctx["snap"]:
        t.ok(c2.subset(ctx["snap"][h], snap[h]), f"stage-2 import: {h}'s /me, /activity, /requests or /authorizations not preserved: {str(snap[h])[:200]}")
    _consistent(t, S, ctx["tok"], "stage-2 import", 14000)
    m = S.call("GET", "/me", token=ctx["tok"]["ada"]).j or {}
    t.eq((m.get("total"), m.get("available"), m.get("held")), (9000, 7700, 1300), "stage-2 import: ada total/available/held")
    st = S.call("GET", "/statement", token=ctx["tok"]["bob"]).j or {}
    caps = [e for e in st.get("entries", []) if e["payment"].get("authorization_id") == ctx["open"]]
    t.ok(len(caps) == 1 and caps[0]["delta"] == 700, f"stage-2 import: the capture appears once in the receiver's statement: {rows(st)}")
    cp = ctx["keys"]["capture"][4]
    t.err(S.call("POST", f"/payments/{cp['payment_id']}/corrections", {"expected_revision": 1, "amount": 1, "effective_at": iso(now() - dt.timedelta(seconds=1)), "reason": "x"},
                 token=ctx["tok"]["ada"], key=k()), 422, "linked_payment_immutable", "imported capture is immutable")
    for name, (who, path, body, key, orig) in ctx["keys"].items():
        r = S.call("POST", path, body, token=ctx["tok"][who], key=key)
        t.ok(r.status == 200 and c2.subset(orig, r.j), f"stage-2 import: replay of {name}: {r!r}"[:260])
    r = S.call("GET", "/authorizations?limit=200", token=ctx["tok"]["ada"])
    t.ok(all("closed_at" in a for a in (r.j or {}).get("authorizations", [])), "imported authorizations expose closed_at")
    t.ok(all((a.get("closed_at") is None) == (a.get("status") == "open") for a in (r.j or {}).get("authorizations", [])), f"closed_at null exactly for open imported holds: {[(a.get('status'), a.get('closed_at')) for a in (r.j or {}).get('authorizations', [])]}")
    t.st(S.call("POST", f"/authorizations/{ctx['open']}/capture", {"amount": 1300}, token=ctx["tok"]["bob"], key=k()), 201, "imported open hold captured")


@check("AB2-export-import-history", "stage-1 §10 applied to stage 3", "AB2,AA4", "Stage-3 export/import round-trips revisions, correction idempotency records, hold history and historical views")
def c_roundtrip(t, S):
    fx, (t1, t2, t3) = histfx()
    S.reset(fx)
    toks = {h: S.token(h) for h in HS}
    p = S.call("POST", "/payments", {"to_handle": "bob", "amount": 800}, as_="ada", key=k())
    pid, made = p.j["payment_id"], parse_ts(p.j["created_at"])
    k0 = tick(0.2)
    key = k()
    body = {"expected_revision": 1, "amount": 600, "effective_at": iso(made), "reason": "fix"}
    cr = S.call("POST", f"/payments/{pid}/corrections", body, as_="ada", key=key)
    t.st(cr, 201, "prepare: correction")
    t.st(correct(S, "ada", "p_1", 1, 450, t1 - dt.timedelta(days=1), reason="older"), 201, "prepare: backdated correction")
    aid = mk_auth(t, S, "ada", "bob", 1000)
    q1 = tick(0.2)
    cap(S, "bob", aid, {"amount": 300, "final": False})
    a2 = mk_auth(t, S, "dan", "ada", 100)
    S.call("POST", f"/authorizations/{a2}/void", as_="dan")
    old_tok = stmt(S, "ada").get("snapshot")

    def view():
        out = {}
        for h, tok in toks.items():
            out[h] = [S.call("GET", pth, token=tok).j for pth in (
                "/me", "/me" + qs(as_of=iso(ago(days=30))), "/me" + qs(as_of=iso(t1)), "/me" + qs(as_of=iso(q1)), "/me" + qs(known_at=iso(k0)),
                "/activity?limit=200", "/authorizations?limit=200")]
            st = S.call("GET", "/statement?limit=200", token=tok).j or {}
            sk = S.call("GET", "/statement" + qs(known_at=iso(k0), to=iso(q1)), token=tok).j or {}
            out[h] += [{kk: v for kk, v in st.items() if kk not in ("snapshot", "closing_balance")}, st.get("closing_balance"), {kk: v for kk, v in sk.items() if kk != "snapshot"}]
        out["rev"] = [S.call("GET", f"/payments/{x}/revisions", token=toks["ada"]).j for x in (pid, "p_1")]
        return out
    v0 = view()
    exp = S.call("GET", "/_test/export").j
    S.reset(OTHERFX)
    t.st(S.call("POST", "/_test/import", exp), 204, "import")
    S.tok = {}
    v1 = view()
    for kk in v0:
        t.ok(v0[kk] == v1[kk], f"historical views differ after export/import for {kk}: {str(v1[kk])[:200]} vs {str(v0[kk])[:200]}")
    r = S.call("POST", f"/payments/{pid}/corrections", body, token=toks["ada"], key=key)
    t.ok(r.status == 200 and r.j == cr.j, f"replay of the correction after import: {r!r}")
    t.err(S.call("POST", f"/payments/{pid}/corrections", dict(body, amount=1), token=toks["ada"], key=key), 409, "idempotency_key_reuse", "correction key with another body after import")
    t.err(S.call("POST", f"/payments/{pid}/corrections", body, token=toks["ada"], key=k()), 409, "stale_revision", "revision counter preserved by import")
    t.eq(sum(S.call("GET", "/me", token=tok).j.get("balance") for tok in toks.values()), 14000, "sum of balances after import")


@check("AB4-snapshots-survive-import", "stage-3 Stable statement pagination ('Tokens last until reset'); stage-1 §10 (import replaces state; existing tokens stay valid)", "AA4,AB4", "A snapshot token issued before GET /_test/export pages the identical frozen result after POST /_test/import, in the same and in another stage-3 container; a token not in the imported state (issued on the destination before the import, or on the source after the export) is 404; another user's token stays 404; reset clears imported tokens; export and import stay under 10 s")
def c_snap_import(t, S):
    S.reset(basefx(payments=[], requests=[]))
    toks = {h: S.token(h) for h in HS}
    made = []
    for i in range(6):
        frm, to = ("ada", "bob") if i % 2 == 0 else ("bob", "ada")
        r = S.call("POST", "/payments", {"to_handle": to, "amount": 20 + i, "note": f"s{i}"}, as_=frm, key=k())
        made.append(r.j["payment_id"])
    full = stmt(S, "ada", limit="200")
    tok = full.get("snapshot")
    win = stmt(S, "ada", **{"from": full["entries"][1]["effective_at"], "to": full["entries"][4]["effective_at"], "limit": "200"})
    tok_w = win.get("snapshot")
    tok_bob = stmt(S, "bob").get("snapshot")
    # mutate after the snapshots, then export
    S.call("POST", "/payments", {"to_handle": "bob", "amount": 777}, as_="ada", key=k())
    t.st(correct(S, "ada", made[0], 1, 1, now() - dt.timedelta(seconds=1)), 201, "correction after the snapshots")
    r = S.call("GET", "/_test/export")
    t.ok(r.status == 200 and r.secs < 10.0, f"export with live snapshots: {r.status} in {r.secs:.2f}s")
    exp = r.j
    late = stmt(S, "ada").get("snapshot")

    def frozen(X, label):
        got = X.call("GET", "/statement" + qs(snapshot=tok, limit="200"), token=toks["ada"])
        t.ok(got.status == 200 and (got.j or {}).get("entries") == full["entries"] and
             ((got.j or {}).get("opening_balance"), (got.j or {}).get("closing_balance"), (got.j or {}).get("has_more")) == (full["opening_balance"], full["closing_balance"], False),
             f"{label}: token issued before the export must page the identical frozen result: {got!r}"[:330])
        pages = []
        for off in range(0, 6, 4):
            pg = X.call("GET", "/statement" + qs(snapshot=tok, limit="4", offset=str(off)), token=toks["ada"])
            t.ok(pg.status == 200 and (pg.j or {}).get("has_more") == (off + 4 < 6), f"{label}: snapshot paging offset={off}: {pg.status}")
            pages += (pg.j or {}).get("entries", [])
        t.ok(pages == full["entries"], f"{label}: snapshot pages differ from the frozen entries")
        gw = X.call("GET", "/statement" + qs(snapshot=tok_w, limit="200"), token=toks["ada"])
        t.ok(gw.status == 200 and (gw.j or {}).get("entries") == win["entries"] and (gw.j or {}).get("opening_balance") == win["opening_balance"]
             and (gw.j or {}).get("closing_balance") == win["closing_balance"], f"{label}: windowed snapshot not preserved: {gw!r}"[:300])
        t.err(X.call("GET", "/statement" + qs(snapshot=tok_bob), token=toks["ada"]), 404, "not_found", f"{label}: another user's imported token")
        t.st(X.call("GET", "/statement" + qs(snapshot=tok_bob), token=toks["bob"]), 200, f"{label}: bob's own imported token")
        t.err(X.call("GET", "/statement" + qs(snapshot=late), token=toks["ada"]), 404, "not_found", f"{label}: token issued on the source after the export")
        t.err(X.call("GET", "/statement" + qs(snapshot=tok, to=iso(now())), token=toks["ada"]), 422, "validation_failed", f"{label}: imported snapshot with to")
        live = X.call("GET", "/statement?limit=200", token=toks["ada"]).j or {}
        t.ok(len(live.get("entries", [])) == 7 and live.get("closing_balance") != full["closing_balance"], f"{label}: live statement must reflect the imported later writes")
    # same container: destination state replaced in between
    S.reset(OTHERFX)
    dest_tok = stmt(S, "zed").get("snapshot")
    r = S.call("POST", "/_test/import", exp)
    t.ok(r.status == 204 and r.secs < 10.0, f"import with snapshots: {r.status} in {r.secs:.2f}s")
    S.tok = {}
    frozen(S, "same container")
    t.err(S.call("GET", "/statement" + qs(snapshot=dest_tok), token=toks["ada"]), 404, "not_found", "token issued on the destination before the import")
    t.st(S.call("POST", "/_test/import", exp), 204, "import repeated")
    frozen(S, "same container, second import")
    e2 = S.call("GET", "/_test/export").j
    t.st(S.call("POST", "/_test/import", e2), 204, "import of a re-export")
    frozen(S, "after re-export and import")
    if isinstance(exp.get("state"), dict):
        r = S.call("POST", "/_test/import", dict(exp, state="x"))
        t.err(r, 422, "validation_failed", "invalid state still 422")
        frozen(S, "after a rejected import")
    b3 = os.environ.get("S3B")
    if b3:
        X = c1.Sess(b3)
        r = X.call("POST", "/_test/import", exp)
        t.ok(r.status == 204, f"import into another stage-3 container: {r!r}")
        frozen(X, "another container")
    else:
        t.ok(False, "cross-container part not run: needs S3B (a second stage-3 container)")
    S.reset(basefx(payments=[], requests=[]))
    t.err(S.call("GET", "/statement" + qs(snapshot=tok), as_="ada"), 404, "not_found", "reset clears imported snapshot tokens")


# --------------------------------------------------------------------------- load
@check("V2-load-history", "stage-1 §2 limits and §5 (no 5xx) with stage-3 endpoints", "V2", "50 requests in flight mixing statements, historical /me, revisions, corrections and payments: no 5xx, each under 5 s, sum of balances preserved")
def c_load3(t, S):
    fx = basefx(payments=[], requests=[])
    for u in fx["users"]:
        u["balance"] = 100000
    S.reset(fx)
    for h in HS:
        S.token(h)
    pays = []
    for i in range(40):
        a, b = HS[i % 5], HS[(i + 1) % 5]
        r = S.call("POST", "/payments", {"to_handle": b, "amount": 10 + i}, as_=a, key=k())
        pays.append((a, r.j["payment_id"], r.j["created_at"]))
    bad, worst = [], [0.0]

    def one(i, rnd):
        a = HS[i % 5]
        kind = i % 5
        if kind == 0:
            r, okc = S.call("GET", "/statement?limit=200", as_=a), (200,)
        elif kind == 1:
            r, okc = S.call("GET", "/me" + qs(as_of=pays[i % 40][2], known_at=iso(now())), as_=a), (200,)
        elif kind == 2:
            s, pid, made = pays[(i // 5 + rnd * 10) % 40]
            r, okc = correct(S, s, pid, 1, 5 + i, made), (201, 409)
        elif kind == 3:
            r, okc = S.call("POST", "/payments", {"to_handle": HS[(i + 2) % 5], "amount": 2}, as_=a, key=k()), (201,)
        else:
            s, pid, made = pays[i % 40]
            r, okc = S.call("GET", f"/payments/{pid}/revisions", as_=s), (200,)
        worst[0] = max(worst[0], r.secs)
        if r.status not in okc:
            bad.append(repr(r)[:160])
    for rnd in range(4):
        par([lambda i=i: one(i, rnd) for i in range(50)])
    t.ok(not bad, f"{len(bad)} unexpected responses under 50 in flight, e.g. {bad[:3]}")
    t.ok(worst[0] < 5.0, f"slowest request under 50 in flight took {worst[0]:.2f}s")
    t.note(f"stage-3 load: slowest request {worst[0]:.3f}s")
    t.eq(sum(S.bals(HS).values()), 500000, "sum of balances after load")
    t.eq(total_at(S, as_of=pays[20][2]), 500000, "sum of balances at a past instant after corrections")
    for h in HS:
        st = stmt(S, h, limit="200")
        t.eq(st["opening_balance"] + sum(e["delta"] for e in st["entries"]), st["closing_balance"], f"{h}: opening + deltas = closing after load")
        t.eq(st["closing_balance"], S.bal(h), f"{h}: closing equals the current balance")


if __name__ == "__main__":
    for flag, env in (("--s1base", "S1BASE"), ("--s2base", "S2BASE")):
        if flag in sys.argv:
            i = sys.argv.index(flag)
            os.environ[env] = sys.argv[i + 1]
            del sys.argv[i:i + 2]
    sys.exit(c1.main())
