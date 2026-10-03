#!/usr/bin/env python3
"""Nightshift Verifier - Pocketful stage 2 - API checks.

Runs the whole stage-1 list (checks1.py, unchanged: map row K1) plus the checks below, derived
from pocketful/spec/stage-2.md. Same options as checks1.py; --s1base (or env S1BASE) names a running
stage-1 container for the upgrade check R1.
"""
import datetime as dt
import http.client
import os
import sys
import time

import checks1 as c1
from checks1 import (HS, OTHERFX, PW, TOTAL, T, basefx, check, idok, ids, is_err, j_prepare, k, par,
                     parse_ts, pay_shape, tr, tsok, user)

AUTH_KEYS = ["authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
             "captured_amount", "remaining_amount", "currency", "note", "visibility", "status",
             "expires_at", "payment_id", "payment_ids", "created_at"]


def iso(delta_s):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=delta_s)).replace(microsecond=0).isoformat()


def seeded_auths():
    return [
        {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit",
         "visibility": "public", "status": "open", "expires_at": iso(7200)},
        {"id": "a_2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 300, "note": "old",
         "visibility": "private", "status": "open", "expires_at": iso(-7200)},
        {"id": "a_3", "from_user_id": "u_ada", "to_user_id": "u_dan", "amount": 100, "note": "c",
         "visibility": "public", "status": "captured", "expires_at": iso(7200)},
        {"id": "a_4", "from_user_id": "u_dan", "to_user_id": "u_ada", "amount": 50, "note": "v",
         "visibility": "public", "status": "voided", "expires_at": iso(7200)},
        {"id": "a_5", "from_user_id": "u_dan", "to_user_id": "u_ada", "amount": 60, "note": "e",
         "visibility": "public", "status": "expired", "expires_at": iso(-7200)}]


def authfx(**over):
    fx = basefx(authorizations=seeded_auths())
    fx.update(over)
    return fx


def auth_shape(t, a, what, **exp):
    if not t.ok(isinstance(a, dict), f"{what}: authorization is not an object: {a!r}"):
        return
    for kk in AUTH_KEYS:
        t.ok(kk in a, f"{what}: authorization lacks '{kk}'")
    idok(t, a.get("authorization_id"), what + " authorization_id")
    tsok(t, a.get("created_at"), what + " created_at")
    tsok(t, a.get("expires_at"), what + " expires_at")
    for kk, v in exp.items():
        t.eq(a.get(kk), v, f"{what}: {kk}")


def auths(S, h, q="?limit=200"):
    r = S.call("GET", "/authorizations" + q, as_=h)
    if r.status != 200 or not isinstance(r.j, dict) or not isinstance(r.j.get("authorizations"), list):
        raise c1.CheckError(f"GET /authorizations{q} as {h} expected 200 with authorizations, got {r!r}")
    return r.j["authorizations"]


def auth_by_id(S, h, aid):
    return next((a for a in auths(S, h) if a.get("authorization_id") == aid), None)


def me3(S, h):
    m = S.me(h)
    return (m.get("total"), m.get("available"), m.get("held"))


def mk_auth(t, S, frm, to, amount, **kw):
    r = S.call("POST", "/authorizations", dict({"to_handle": to, "amount": amount}, **kw), as_=frm, key=k())
    t.st(r, 201, f"authorize {frm}->{to} {amount}")
    return (r.j or {}).get("authorization_id") or "missing"


def cap(S, who, aid, body=None, key=None):
    return S.call("POST", f"/authorizations/{aid}/capture", {} if body is None else body, as_=who, key=key or k())


def html_get(S, path, token=None, accept="text/html"):
    c = http.client.HTTPConnection(S.host, S.port, timeout=7)
    h = {"Accept": accept} if accept else {}
    if token:
        h["Authorization"] = "Bearer " + token
    c.request("GET", path, headers=h)
    r = c.getresponse()
    body = r.read()
    out = (r.status, r.getheader("content-type") or "", body, r.getheader("location"))
    c.close()
    return out


# --------------------------------------------------------------------------- T1 / S6-S9
@check("T1-me-fields", "stage-2 API GET /me; existing API changes", "T1,S7", "/me adds total, available, held; balance == total; without holds all agree and held is 0; with a seeded open hold available = total - held")
def c_me(t, S):
    S.reset(basefx())
    for h, b in (("ada", 10000), ("cy", 0)):
        m = S.me(h)
        for kk in ("balance", "total", "available", "held"):
            t.ok(kk in m, f"/me {h} lacks {kk}")
        t.eq((m.get("balance"), m.get("total"), m.get("available"), m.get("held")), (b, b, b, 0), f"/me {h} without holds")
    S.reset(authfx())
    m = S.me("ada")
    t.eq((m.get("balance"), m.get("total"), m.get("available"), m.get("held")), (10000, 10000, 8000, 2000), "/me ada with a seeded open hold of 2000")
    t.eq(me3(S, "bob"), (2500, 2500, 0), "/me bob: seeded open hold already past expires_at holds nothing")
    t.eq(me3(S, "dan"), (500, 500, 0), "/me dan: seeded voided/expired holds hold nothing")


@check("S6-ttl-fixture", "stage-2 Model", "S6", "authorization_ttl_seconds defaults to 600; if supplied must be a positive integer, else reset is 422 and changes nothing; expires_at = created_at + ttl")
def c_ttl(t, S):
    S.reset(basefx())
    tok = S.token("ada")
    for bad in (0, -1, 1.5, "600", -600):
        r = S.call("POST", "/_test/reset", dict(OTHERFX, authorization_ttl_seconds=bad))
        t.err(r, 422, "validation_failed", f"reset with authorization_ttl_seconds={bad!r}")
    r = S.call("GET", "/me", token=tok)
    t.ok(r.status == 200 and (r.j or {}).get("balance") == 10000, f"state changed by rejected resets: {r!r}")
    for ttl, fx in ((600, basefx()), (60, basefx(authorization_ttl_seconds=60)), (1, basefx(authorization_ttl_seconds=1)),
                    (86400, basefx(authorization_ttl_seconds=86400))):
        S.reset(fx)
        r = S.call("POST", "/authorizations", {"to_handle": "bob", "amount": 10}, as_="ada", key=k())
        if t.st(r, 201, f"authorize with ttl {ttl}"):
            d = (parse_ts(r.j["expires_at"]) - parse_ts(r.j["created_at"])).total_seconds()
            t.eq(d, float(ttl), f"expires_at - created_at with ttl {ttl}")


@check("S7-seeded-auths", "stage-2 Model, GET /authorizations", "S7,T12,T4", "Seeded authorizations keep id, parties, amount, note, visibility, status and expires_at; only unexpired open ones hold funds; a seeded open hold past expires_at reads expired; visible only to their two parties; never in /activity; fixtures without the array work")
def c_seeded(t, S):
    fx = authfx()
    S.reset(fx)
    a = {x.get("authorization_id"): x for x in auths(S, "ada")}
    t.eq(sorted(a), ["a_1", "a_3", "a_4", "a_5"], "ada's authorizations")
    auth_shape(t, a.get("a_1"), "seeded a_1", authorization_id="a_1", from_user_id="u_ada", from_handle="ada", to_user_id="u_bob",
               to_handle="bob", amount=2000, captured_amount=0, remaining_amount=2000, currency="EUR", note="deposit",
               visibility="public", status="open", payment_id=None, payment_ids=[])
    if a.get("a_1"):
        t.eq(parse_ts(a["a_1"]["expires_at"]), parse_ts(fx["authorizations"][0]["expires_at"]), "seeded expires_at kept")
    for aid, st in (("a_3", "captured"), ("a_4", "voided"), ("a_5", "expired")):
        t.eq((a.get(aid) or {}).get("status"), st, f"seeded {aid} status")
        t.eq((a.get(aid) or {}).get("remaining_amount"), 0, f"seeded {aid} remaining_amount (closed)")
    b = {x.get("authorization_id"): x for x in auths(S, "bob")}
    t.eq(sorted(b), ["a_1", "a_2"], "bob's authorizations")
    t.eq((b.get("a_2") or {}).get("status"), "expired", "seeded open authorization past expires_at reads expired")
    t.eq((b.get("a_2") or {}).get("remaining_amount"), 0, "expired authorization remaining_amount")
    t.eq(b.get("a_1"), a.get("a_1"), "both parties see the same authorization")
    t.eq(ids(auths(S, "cy"), "authorization_id"), ["a_2"], "cy's authorizations")
    t.eq(auths(S, "op"), [], "operator / third party sees no authorizations")
    for h in HS:
        t.eq(sorted(ids(S.acts(h), "payment_id")), ["p_1", "p_2"] if h in ("bob", "dan") else ["p_1"], f"{h}: authorizations are not feed items")
    t.err_any(cap(S, "cy", "a_2"), [(409, "authorization_expired"), (409, "authorization_not_open")], "capture a seeded authorization past expires_at")
    t.err(cap(S, "dan", "a_3"), 409, "authorization_not_open", "capture a seeded captured authorization")
    t.err(cap(S, "ada", "a_4"), 409, "authorization_not_open", "capture a seeded voided authorization")
    r = S.call("POST", "/authorizations/a_4/void", as_="dan")
    t.st(r, 200, "void a seeded voided authorization again")
    t.err(S.call("POST", "/authorizations/a_3/void", as_="ada"), 409, "authorization_not_open", "void a seeded captured authorization")
    t.err(S.call("POST", "/authorizations/a_2/void", as_="bob"), 409, "authorization_not_open", "void an expired authorization")
    r = cap(S, "bob", "a_1", {"amount": 500})
    t.st(r, 201, "capture the seeded open authorization")
    t.eq(me3(S, "ada"), (9500, 9500, 0), "ada after capture of 500 from a seeded hold of 2000")
    S.reset(basefx())
    t.eq(auths(S, "ada"), [], "fixture without authorizations: empty list")


@check("S8-seeded-holds-vs-balance", "stage-2 Model", "S8", "Seeded unexpired open holds above the user's balance -> reset 422, nothing changes; equal to the balance is accepted (available 0); expired or closed holds do not count")
def c_seedover(t, S):
    S.reset(basefx())
    tok = S.token("ada")

    def fx(amounts, status="open", exp=7200):
        return basefx(authorizations=[{"id": f"a_{i}", "from_user_id": "u_dan", "to_user_id": "u_bob", "amount": a, "note": "",
                                       "visibility": "public", "status": status, "expires_at": iso(exp)} for i, a in enumerate(amounts)])
    for label, f in (("one hold 501 > 500", fx([501])), ("two holds 300+201 > 500", fx([300, 201]))):
        r = S.call("POST", "/_test/reset", f)
        t.err(r, 422, "validation_failed", f"reset with {label}")
        r = S.call("GET", "/me", token=tok)
        t.ok(r.status == 200 and (r.j or {}).get("balance") == 10000, f"state changed by rejected reset ({label}): {r!r}")
    S.reset(fx([300, 200]))
    t.eq(me3(S, "dan"), (500, 0, 500), "holds equal to the balance")
    t.err(S.call("POST", "/payments", {"to_handle": "bob", "amount": 1}, as_="dan", key=k()), 409, "insufficient_funds", "pay 1 with available 0")
    S.reset(fx([9999], exp=-7200))
    t.eq(me3(S, "dan"), (500, 500, 0), "expired seeded open hold above the balance is accepted and holds nothing")
    S.reset(fx([9999], status="captured"))
    t.eq(me3(S, "dan"), (500, 500, 0), "seeded captured authorization above the balance holds nothing")


@check("S9-expiry-by-clock", "stage-2 Model (expiry), capture table", "S9,T9,T11", "An authorization at or past expires_at is expired with no intervening request: /me available restored, GET /authorizations status expired (matches expired, never open), capture 409 authorization_expired, void 409; a partially captured one releases only the remainder and keeps its capture records")
def c_expiry(t, S):
    S.reset(basefx(authorization_ttl_seconds=2))
    a1 = mk_auth(t, S, "ada", "bob", 1000)
    a2 = mk_auth(t, S, "ada", "bob", 2000, note="part")
    r = cap(S, "bob", a2, {"amount": 300, "final": False})
    t.st(r, 201, "partial capture before expiry")
    pid = (r.j or {}).get("payment_id")
    t.eq(me3(S, "ada"), (9700, 7000, 2700), "ada while holds are open")
    t.eq(sorted(ids(auths(S, "ada", "?status=open"), "authorization_id")), sorted([a1, a2]), "status=open before expiry")
    time.sleep(3.6)
    t.eq(me3(S, "ada"), (9700, 9700, 0), "ada /me after expiry with no intervening request")
    x1, x2 = auth_by_id(S, "bob", a1) or {}, auth_by_id(S, "bob", a2) or {}
    t.eq((x1.get("status"), x1.get("remaining_amount"), x1.get("captured_amount")), ("expired", 0, 0), "untouched authorization after expiry")
    t.eq((x2.get("status"), x2.get("remaining_amount"), x2.get("captured_amount"), x2.get("payment_ids"), x2.get("payment_id")),
         ("expired", 0, 300, [pid], pid), "partially captured authorization after expiry keeps its capture records")
    t.eq(auths(S, "ada", "?status=open"), [], "status=open after expiry")
    t.eq(sorted(ids(auths(S, "ada", "?status=expired"), "authorization_id")), sorted([a1, a2]), "status=expired after expiry")
    t.err(cap(S, "bob", a1), 409, "authorization_expired", "capture after expires_at")
    t.err(cap(S, "bob", a2, {"amount": 1, "final": False}), 409, "authorization_expired", "further capture after expires_at")
    t.err(S.call("POST", f"/authorizations/{a1}/void", as_="ada"), 409, "authorization_not_open", "void after expiry")
    r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 9700}, as_="ada", key=k())
    t.st(r, 201, "released funds are spendable")
    t.eq(sum(S.me(h).get("total") for h in HS), TOTAL, "sum of totals")


# --------------------------------------------------------------------------- T2-T4
@check("T2-authorize", "stage-2 POST /authorizations; invariants 1,2", "T2,T3,T4,T14,S2", "Authorize: 201 body, defaults, a hold moves no money and is not a feed item; errors insufficient_funds against available (equal ok), validation, self_payment, not_found; held funds cannot fund payments, request pays, new authorizations or settlement net debits; POST /payments leaves no hold")
def c_authorize(t, S):
    S.reset(basefx())
    r = S.call("POST", "/authorizations", {"to_handle": "bob", "amount": 2000, "note": "deposit", "visibility": "private"}, as_="ada", key=k())
    t.st(r, 201, "authorize")
    auth_shape(t, r.j, "authorize", from_user_id="u_ada", from_handle="ada", to_user_id="u_bob", to_handle="bob", amount=2000,
               captured_amount=0, remaining_amount=2000, currency="EUR", note="deposit", visibility="private", status="open",
               payment_id=None, payment_ids=[])
    aid = (r.j or {}).get("authorization_id")
    t.eq(auth_by_id(S, "bob", aid), r.j, "receiver lists the same authorization")
    t.eq(me3(S, "ada"), (10000, 8000, 2000), "payer after hold")
    t.eq(me3(S, "bob"), (2500, 2500, 0), "receiver after hold (no money moved)")
    for h in HS:
        t.ok(all(p.get("payment_id") in ("p_1", "p_2") for p in S.acts(h)), f"{h}: open authorization leaked into /activity")
    r = S.call("POST", "/authorizations", {"to_handle": "bob", "amount": 1}, as_="ada", key=k())
    auth_shape(t, r.j, "authorize defaults", note="", visibility="public", amount=1, remaining_amount=1)
    t.eq(me3(S, "ada"), (10000, 7999, 2001), "payer after second hold")
    # held funds cannot be spent by any path (available 7999)
    t.err(S.call("POST", "/payments", {"to_handle": "bob", "amount": 8000}, as_="ada", key=k()), 409, "insufficient_funds", "payment above available")
    t.err(S.call("POST", "/authorizations", {"to_handle": "bob", "amount": 8000}, as_="ada", key=k()), 409, "insufficient_funds", "authorization above available")
    t.err(S.call("POST", "/settlements", {"transfers": [tr("ada", "cy", 8000)]}, as_="op", key=k()), 409, "insufficient_funds", "settlement net debit above available")
    t.err(S.call("POST", "/settlements", {"transfers": [tr("bob", "ada", 1), tr("ada", "cy", 8001)]}, as_="op", key=k()), 409, "insufficient_funds", "settlement net debit above available (net)")
    rq = S.call("POST", "/requests", {"payer_handle": "ada", "amount": 8000}, as_="cy", key=k())
    rid = (rq.j or {}).get("request_id")
    t.err(S.call("POST", f"/requests/{rid}/pay", {}, as_="ada", key=k()), 409, "insufficient_funds", "request pay above available")
    t.eq(me3(S, "ada"), (10000, 7999, 2001), "nothing changed by refused spends")
    r = S.call("POST", "/payments", {"to_handle": "cy", "amount": 999}, as_="ada", key=k())
    t.st(r, 201, "payment within available")
    t.eq((r.j or {"authorization_id": "MISSING"}).get("authorization_id", "MISSING"), None, "ordinary payment carries authorization_id null")
    t.eq(me3(S, "ada"), (9001, 7000, 2001), "POST /payments is immediate and leaves no hold")
    t.st(S.call("POST", "/settlements", {"transfers": [tr("ada", "cy", 3000)]}, as_="op", key=k()), 201, "settlement within available")
    t.st(S.call("POST", "/authorizations", {"to_handle": "dan", "amount": 3000}, as_="ada", key=k()), 201, "authorization within available")
    t.st(S.call("POST", "/requests/rq_1/pay", {}, as_="ada", key=k()), 409, "request pay of 1200 with available 1000")
    t.st(S.call("POST", "/requests/rq_2/pay", {}, as_="ada", key=k()), 201, "request pay of 300 with available 1000")
    t.st(S.call("POST", "/payments", {"to_handle": "cy", "amount": 700}, as_="ada", key=k()), 201, "payment equal to available")
    t.eq(me3(S, "ada"), (5001, 0, 5001), "ada with available 0")
    t.err(S.call("POST", "/authorizations", {"to_handle": "bob", "amount": 1}, as_="ada", key=k()), 409, "insufficient_funds", "authorize 1 with available 0")
    # validation
    cases = [({"to_handle": "bob", "amount": 0}, 422, "validation_failed"), ({"to_handle": "bob", "amount": 1000000001}, 422, "validation_failed"),
             ({"to_handle": "bob", "amount": 1.5}, 422, "validation_failed"), ({"to_handle": "bob", "amount": "10"}, 422, "validation_failed"),
             ({"to_handle": "bob", "amount": True}, 422, "validation_failed"), ({"to_handle": "bob"}, 422, "validation_failed"),
             ({"amount": 5}, 422, "validation_failed"), ({"to_handle": "bob", "amount": 5, "note": "x" * 201}, 422, "validation_failed"),
             ({"to_handle": "bob", "amount": 5, "note": None}, 422, "validation_failed"),
             ({"to_handle": "bob", "amount": 5, "visibility": "friends"}, 422, "validation_failed"),
             ({"to_handle": "bob", "amount": 5, "visibility": None}, 422, "validation_failed"),
             ({"to_handle": "bob", "amount": 5}, 422, "self_payment"), ({"to_handle": "nobody_here", "amount": 5}, 404, "not_found"),
             ({"to_handle": 7, "amount": 5}, 400, "malformed_request")]
    for body, st, code in cases:
        t.err(S.call("POST", "/authorizations", body, as_="bob", key=k()), st, code, f"authorize {str(body)[:60]}")
    t.eq(me3(S, "bob")[2], 0, "rejected authorizations hold nothing")
    S.reset(c1.richfx())
    for v, ok in ((1, True), (1000000000, True)):
        t.st(S.call("POST", "/authorizations", {"to_handle": "bob", "amount": v, "note": "x" * 200}, as_="ada", key=k()), 201, f"authorize amount {v}")
    r = S.call("POST", "/authorizations", raw='{"to_handle":"bob","amount":1e3,"zzz":1}', as_="ada", key=k())
    t.ok(r.status == 201 and (r.j or {}).get("amount") == 1000, f"authorize amount 1e3 with an unknown field: {r!r}")
    t.eq(sum(S.me(h).get("total") for h in HS), 25000000000, "sum of totals (holds move no money)")


# --------------------------------------------------------------------------- T5-T9 capture
@check("T5-capture-final", "stage-2 POST /authorizations/{id}/capture", "T5,T6,T7,S4", "Capture: receiver only; 201 payment in the POST /payments shape with authorization_id; default is final: status captured, remainder released at once; amount defaults to the remainder; captures spend reserved money even when available is 0; second capture 409 authorization_not_open")
def c_capture(t, S):
    S.reset(basefx())
    aid = mk_auth(t, S, "ada", "bob", 2000, note="dep \U0001F3E0", visibility="private")
    r = cap(S, "bob", aid, {"amount": 1500})
    t.st(r, 201, "capture 1500 of 2000")
    pay_shape(t, r.j, "capture payment", from_user_id="u_ada", from_handle="ada", to_user_id="u_bob", to_handle="bob", amount=1500,
              currency="EUR", note="dep \U0001F3E0", visibility="private", request_id=None, settlement_id=None, authorization_id=aid)
    pid = (r.j or {}).get("payment_id")
    t.eq(me3(S, "ada"), (8500, 8500, 0), "payer: 1500 moved, 500 released in the same step")
    t.eq(me3(S, "bob"), (4000, 4000, 0), "receiver credited")
    a = auth_by_id(S, "ada", aid) or {}
    t.eq((a.get("status"), a.get("captured_amount"), a.get("payment_id"), a.get("payment_ids"), a.get("remaining_amount"), a.get("amount")),
         ("captured", 1500, pid, [pid], 0, 2000), "authorization after final capture")
    for h, sees in (("ada", True), ("bob", True), ("cy", False), ("op", False)):
        t.eq(pid in ids(S.acts(h), "payment_id"), sees, f"private capture payment visible to {h}")
    mine = [p for p in S.acts("bob") if p.get("payment_id") == pid]
    t.ok(mine and mine[0] == r.j, "capture payment in the feed equals the capture response")
    t.err(cap(S, "bob", aid, {"amount": 1}), 409, "authorization_not_open", "second capture after a final capture")
    t.err(S.call("POST", f"/authorizations/{aid}/void", as_="ada"), 409, "authorization_not_open", "void a captured authorization")
    for p in S.acts("bob"):
        if p.get("payment_id") != pid:
            t.eq(p.get("authorization_id", "MISSING"), None, f"payment {p.get('payment_id')} without authorization carries authorization_id null")
    # default amount = remainder; public capture visible to all
    aid = mk_auth(t, S, "ada", "cy", 700)
    r = cap(S, "cy", aid)
    t.st(r, 201, "capture with {} (amount defaults to the remainder)")
    t.eq((r.j or {}).get("amount"), 700, "default capture amount")
    t.ok((r.j or {}).get("payment_id") in ids(S.acts("dan"), "payment_id"), "public capture payment visible to a third party")
    a0 = mk_auth(t, S, "ada", "cy", 5)
    r0 = S.call("POST", f"/authorizations/{a0}/capture", as_="cy", key=k())
    if not t.probe(r0.status == 201, f"capture with no body at all: got {r0!r}"):
        cap(S, "cy", a0)
    # captures spend reserved money with available 0
    left = S.me("ada").get("available")
    aid = mk_auth(t, S, "ada", "dan", left)
    t.eq(me3(S, "ada")[1], 0, "available 0 after authorizing everything")
    r = cap(S, "dan", aid)
    t.st(r, 201, "capture while the payer's available is 0")
    t.eq(me3(S, "ada"), (0, 0, 0), "payer emptied by capture")
    t.eq(sum(S.me(h).get("total") for h in HS), TOTAL, "sum of totals")


@check("T8-capture-extended", "stage-2 Extended capture mode", "T8,T9,T11", "final:false keeps the remainder held and the authorization open; captures up to the remainder; capturing the whole remainder closes it; a final capture releases the remainder; captured_amount cumulative, payment_id latest, payment_ids in order, remaining_amount; capture_exceeds_authorization compares with the remainder")
def c_extended(t, S):
    S.reset(basefx())
    aid = mk_auth(t, S, "ada", "bob", 2000)
    r1 = cap(S, "bob", aid, {"amount": 700, "final": False})
    t.st(r1, 201, "capture 700 final:false")
    p1 = (r1.j or {}).get("payment_id")
    a = auth_by_id(S, "bob", aid) or {}
    t.eq((a.get("status"), a.get("captured_amount"), a.get("remaining_amount"), a.get("payment_id"), a.get("payment_ids")),
         ("open", 700, 1300, p1, [p1]), "after a nonfinal capture")
    t.eq(me3(S, "ada"), (9300, 8000, 1300), "payer: remainder stays held")
    t.err(cap(S, "bob", aid, {"amount": 1301, "final": False}), 422, "capture_exceeds_authorization", "capture remainder+1 (nonfinal)")
    t.err(cap(S, "bob", aid, {"amount": 1301}), 422, "capture_exceeds_authorization", "capture remainder+1 (final)")
    t.err(cap(S, "bob", aid, {"amount": 2000}), 422, "capture_exceeds_authorization", "capture the original amount after a partial capture")
    for bad in (0, -5, 1.5, "100", True, None):
        t.err(cap(S, "bob", aid, {"amount": bad, "final": False}), 422, "validation_failed", f"capture amount {bad!r}")
    for bad in ("no", 0, None):
        r = cap(S, "bob", aid, {"amount": 1, "final": bad})
        t.err_any(r, [(400, "malformed_request"), (422, "validation_failed")], f"capture with final={bad!r}")
    t.eq((auth_by_id(S, "bob", aid) or {}).get("remaining_amount"), 1300, "rejected captures change nothing")
    r2 = cap(S, "bob", aid, {"amount": 300, "final": False})
    t.st(r2, 201, "second nonfinal capture")
    p2 = (r2.j or {}).get("payment_id")
    r3 = cap(S, "bob", aid, {"amount": 1000, "final": False})
    t.st(r3, 201, "nonfinal capture of the whole remainder")
    p3 = (r3.j or {}).get("payment_id")
    a = auth_by_id(S, "ada", aid) or {}
    t.eq((a.get("status"), a.get("captured_amount"), a.get("remaining_amount"), a.get("payment_id"), a.get("payment_ids")),
         ("captured", 2000, 0, p3, [p1, p2, p3]), "capturing the entire remainder closes it even with final:false")
    t.eq(me3(S, "ada"), (8000, 8000, 0), "payer after full capture")
    t.err(cap(S, "bob", aid, {"amount": 1, "final": False}), 409, "authorization_not_open", "capture a closed authorization")
    # final capture after partial releases the remainder
    aid = mk_auth(t, S, "ada", "bob", 2000)
    t.st(cap(S, "bob", aid, {"amount": 700, "final": False}), 201, "partial")
    r = cap(S, "bob", aid, {"amount": 300, "final": True})
    t.st(r, 201, "final capture of 300 with 1300 remaining")
    a = auth_by_id(S, "ada", aid) or {}
    t.eq((a.get("status"), a.get("captured_amount"), a.get("remaining_amount"), len(a.get("payment_ids") or [])), ("captured", 1000, 0, 2), "after final capture")
    t.eq(me3(S, "ada"), (7000, 7000, 0), "remainder of 1000 released")
    # omitted amount defaults to the remainder, also in extended mode
    aid = mk_auth(t, S, "ada", "bob", 2000)
    t.st(cap(S, "bob", aid, {"amount": 1999, "final": False}), 201, "partial 1999")
    r = cap(S, "bob", aid, {"final": False})
    t.ok(r.status == 201 and (r.j or {}).get("amount") == 1, f"omitted amount defaults to the remainder (1): {r!r}")
    t.eq((auth_by_id(S, "ada", aid) or {}).get("status"), "captured", "closed after remainder captured")
    # void of a partially captured authorization
    aid = mk_auth(t, S, "ada", "bob", 1000)
    rp = cap(S, "bob", aid, {"amount": 400, "final": False})
    before = S.me("ada").get("total")
    r = S.call("POST", f"/authorizations/{aid}/void", as_="ada")
    t.st(r, 200, "void a partially captured authorization")
    j = r.j or {}
    t.eq((j.get("status"), j.get("captured_amount"), j.get("remaining_amount"), j.get("payment_ids")),
         ("voided", 400, 0, [(rp.j or {}).get("payment_id")]), "voided partial keeps its capture records")
    m = S.me("ada")
    t.eq((m.get("total"), m.get("held")), (before, 0), "void releases only the remainder, moves no money")
    t.eq(sum(S.me(h).get("total") for h in HS), TOTAL, "sum of totals")


@check("T9-capture-void-permissions", "stage-2 capture and void tables", "T9,T10", "Capture: 404 unknown, 403 for the payer and for a third party. Void: payer only, no key; 200 voided and hold released; repeat 200; captured 409; receiver or third party 403; unknown 404")
def c_perms(t, S):
    S.reset(basefx())
    aid = mk_auth(t, S, "ada", "bob", 2000)
    t.err(cap(S, "ada", aid), 403, "forbidden", "payer captures")
    t.err(cap(S, "cy", aid), 403, "forbidden", "third party captures")
    t.err(cap(S, "op", aid), 403, "forbidden", "operator captures")
    t.err(cap(S, "bob", "a_nope"), 404, "not_found", "capture unknown authorization")
    t.err(S.call("POST", f"/authorizations/{aid}/void", as_="bob"), 403, "forbidden", "receiver voids")
    t.err(S.call("POST", f"/authorizations/{aid}/void", as_="cy"), 403, "forbidden", "third party voids")
    t.err(S.call("POST", "/authorizations/a_nope/void", as_="ada"), 404, "not_found", "void unknown authorization")
    t.eq(me3(S, "ada"), (10000, 8000, 2000), "hold untouched by refused calls")
    for i in range(2):
        r = S.call("POST", f"/authorizations/{aid}/void", as_="ada")
        t.st(r, 200, f"void #{i + 1}")
        auth_shape(t, r.j, f"void #{i + 1}", authorization_id=aid, status="voided", remaining_amount=0, captured_amount=0, payment_id=None, payment_ids=[], amount=2000)
    t.eq(me3(S, "ada"), (10000, 10000, 0), "hold released by void")
    t.err(cap(S, "bob", aid), 409, "authorization_not_open", "capture a voided authorization")
    t.eq(me3(S, "bob"), (2500, 2500, 0), "receiver unchanged")
    for m, p in (("GET", "/authorizations"), ("POST", "/authorizations"), ("POST", f"/authorizations/{aid}/capture"), ("POST", f"/authorizations/{aid}/void")):
        t.err(S.call(m, p), 401, "unauthenticated", f"{m} {p} without token")
        t.err(S.call(m, p, headers={"Authorization": "Bearer nope"}), 401, "unauthenticated", f"{m} {p} with unknown token")


@check("T12-list-authorizations", "stage-2 GET /authorizations", "T12", "Only the caller's; newest first; direction and status filters; unknown values 422; limit/offset/has_more as GET /requests; shape {authorizations, has_more}")
def c_list(t, S):
    S.reset(authfx())

    def got(h, q):
        return sorted(ids(auths(S, h, q), "authorization_id"))
    t.eq(got("ada", "?direction=outgoing"), ["a_1", "a_3"], "ada outgoing (payer)")
    t.eq(got("ada", "?direction=incoming"), ["a_4", "a_5"], "ada incoming (receiver)")
    t.eq(got("ada", "?status=open"), ["a_1"], "ada open")
    t.eq(got("ada", "?status=captured"), ["a_3"], "ada captured")
    t.eq(got("ada", "?status=voided"), ["a_4"], "ada voided")
    t.eq(got("ada", "?status=expired"), ["a_5"], "ada expired")
    t.eq(got("bob", "?status=open"), ["a_1"], "bob open (clock-expired a_2 never matches open)")
    t.eq(got("bob", "?status=expired"), ["a_2"], "bob expired (clock-expired a_2)")
    t.eq(got("ada", "?direction=incoming&status=voided&limit=50&offset=0&zzz=1"), ["a_4"], "full query with an unknown parameter")
    for q in ("?direction=sideways", "?status=pending", "?status=OPEN", "?limit=0", "?limit=201", "?offset=-1", "?limit=1e1", "?limit=4.0", "?offset=%2B4"):
        t.err(S.call("GET", "/authorizations" + q, as_="ada"), 422, "validation_failed", f"GET /authorizations{q}")
    for q, n, more in (("?limit=1", 1, True), ("?limit=4", 4, False), ("?limit=3", 3, True), ("?limit=200", 4, False),
                       ("?offset=3", 1, False), ("?offset=4", 0, False), ("?limit=1&offset=2", 1, True), ("", 4, False)):
        r = S.call("GET", "/authorizations" + q, as_="ada")
        ok = r.status == 200 and isinstance(r.j, dict) and isinstance(r.j.get("has_more"), bool)
        t.ok(ok and len(r.j.get("authorizations", [])) == n and r.j["has_more"] == more, f"GET /authorizations{q}: expected {n} items has_more={more}, got {r!r}"[:300])
    S.reset(basefx())
    made = []
    for i in range(3):
        made.append(mk_auth(t, S, "ada", "bob", 10 + i))
        time.sleep(1.1)
    t.eq(ids(auths(S, "ada"), "authorization_id"), made[::-1], "payer: newest first")
    t.eq(ids(auths(S, "bob"), "authorization_id"), made[::-1], "receiver: newest first")
    t.eq(ids(auths(S, "bob", "?limit=1&offset=1"), "authorization_id"), made[1:2], "limit=1&offset=1")


# --------------------------------------------------------------------------- T13 idempotency on the two new paths
@check("T13-idempotency-new-paths", "stage-2 'seven idempotent write paths'; stage-1 §7", "T13,T7", "POST /authorizations and capture follow §7 independently: missing/empty key 400, 255 ok, 256 422, replay 200 same body, other body 409 (also when invalid), {} vs {amount:N} differ, per-user scope, failed key reusable, replay after the resource changed")
def c_idem(t, S):
    S.reset(basefx())
    body = {"to_handle": "bob", "amount": 2000}
    t.err(S.call("POST", "/authorizations", body, as_="ada"), 400, "missing_idempotency_key", "authorize without key")
    t.err(S.call("POST", "/authorizations", body, as_="ada", headers={"Idempotency-Key": ""}), 400, "missing_idempotency_key", "authorize with empty key")
    t.err(S.call("POST", "/authorizations", body, as_="ada", key="K" * 256), 422, "validation_failed", "authorize with 256-char key")
    key = "K" * 255
    r1 = S.call("POST", "/authorizations", body, as_="ada", key=key)
    t.st(r1, 201, "authorize first use (255-char key)")
    aid = (r1.j or {}).get("authorization_id")
    r2 = S.call("POST", "/authorizations", raw='{ "amount":2000 , "to_handle":"bob" }', as_="ada", key=key)
    t.ok(r2.status == 200 and r2.j == r1.j, f"authorize replay (reordered keys): {r2!r}")
    t.err(S.call("POST", "/authorizations", dict(body, amount=2001), as_="ada", key=key), 409, "idempotency_key_reuse", "authorize same key, other body")
    t.err(S.call("POST", "/authorizations", dict(body, amount="x"), as_="ada", key=key), 409, "idempotency_key_reuse", "authorize same key, invalid body")
    t.eq(me3(S, "ada"), (10000, 8000, 2000), "one hold after replays")
    rb = S.call("POST", "/authorizations", {"to_handle": "cy", "amount": 5}, as_="bob", key=key)
    t.st(rb, 201, "another user, same key")
    t.st(S.call("POST", "/payments", body, as_="ada", key=key), 201, "same key and body on /payments is a new request")
    # capture
    t.err(S.call("POST", f"/authorizations/{aid}/capture", {}, as_="bob"), 400, "missing_idempotency_key", "capture without key")
    t.err(cap(S, "bob", aid, {}, key="K" * 256), 422, "validation_failed", "capture with 256-char key")
    kf = k()
    t.err(cap(S, "bob", aid, {"amount": 2001}, key=kf), 422, "capture_exceeds_authorization", "failing capture")
    kc = k()
    c1_ = cap(S, "bob", aid, {"amount": 600, "final": False}, key=kc)
    t.st(c1_, 201, "capture first use")
    c2 = cap(S, "bob", aid, {"final": False, "amount": 600}, key=kc)
    t.ok(c2.status == 200 and c2.j == c1_.j, f"capture replay: {c2!r}")
    t.err(cap(S, "bob", aid, {"amount": 600}, key=kc), 409, "idempotency_key_reuse", "capture same key, body without final")
    t.err(cap(S, "bob", aid, {"amount": "x"}, key=kc), 409, "idempotency_key_reuse", "capture same key, invalid body")
    t.eq((auth_by_id(S, "ada", aid) or {}).get("captured_amount"), 600, "replays captured nothing more")
    t.st(cap(S, "bob", aid, {"amount": 100, "final": False}, key=kf), 201, "key of a failed capture reused as a first use")
    ke = k()
    e1 = cap(S, "bob", aid, {}, key=ke)
    t.st(e1, 201, "final capture with {}")
    t.eq((e1.j or {}).get("amount"), 1300, "default amount is the remainder")
    t.err(cap(S, "bob", aid, {"amount": 1300}, key=ke), 409, "idempotency_key_reuse", "{} and {\"amount\": 1300} are different bodies")
    e2 = cap(S, "bob", aid, {}, key=ke)
    t.ok(e2.status == 200 and e2.j == e1.j, f"replay of a final capture on a closed authorization returns the original, not authorization_not_open: {e2!r}")
    r3 = S.call("POST", "/authorizations", body, as_="ada", key=key)
    t.ok(r3.status == 200 and r3.j == r1.j, "authorize replay after the authorization was captured returns the original (open) response")
    t.eq(me3(S, "ada"), (6000, 6000, 0), "ada after 2000 payment and 2000 captured")
    # failed authorization key reusable
    kk = k()
    t.err(S.call("POST", "/authorizations", {"to_handle": "bob", "amount": 1}, as_="cy", key=kk), 409, "insufficient_funds", "cy authorizes with 0")
    S.call("POST", "/payments", {"to_handle": "cy", "amount": 10}, as_="ada", key=k())
    t.st(S.call("POST", "/authorizations", {"to_handle": "bob", "amount": 1}, as_="cy", key=kk), 201, "same key and body after the failure is a first use")
    t.eq(sum(S.me(h).get("total") for h in HS), TOTAL, "sum of totals")


# --------------------------------------------------------------------------- S1-S5 concurrency
@check("S3-concurrent", "stage-2 invariants 1-3; Concurrent operations", "S1,S2,S3,S5,T13,K5", "Concurrent authorize/pay/capture behave as some serial order: available never negative, captures never exceed the authorization, identical keyed requests take effect once, sum of totals constant, no 5xx, under 5 s")
def c_conc(t, S):
    S.reset(basefx())
    for h in HS:
        S.token(h)
    # 10 authorizations + 10 payments of 1000 against available 10000: exactly 10 succeed
    seen, stop = [], c1.threading.Event()

    def poll():
        while not stop.is_set():
            r = S.call("GET", "/me", as_="ada")
            if isinstance(r.j, dict):
                seen.append((r.j.get("balance"), r.j.get("total"), r.j.get("available"), r.j.get("held")))
    th = c1.threading.Thread(target=poll)
    th.start()
    fns = [lambda: S.call("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, as_="ada", key=k()) for _ in range(12)]
    fns += [lambda: S.call("POST", "/payments", {"to_handle": "bob", "amount": 1000}, as_="ada", key=k()) for _ in range(12)]
    rs = par(fns)
    stop.set()
    th.join()
    t.eq(sum(r.status == 201 for r in rs), 10, f"24 concurrent 1000-unit spends of available 10000: 201 count {sorted(r.status for r in rs)}")
    t.ok(all(r.status == 201 or is_err(r, 409, "insufficient_funds") for r in rs), "others must be 409 insufficient_funds")
    t.ok(all(b == tot and a == tot - h and a >= 0 and h >= 0 for b, tot, a, h in seen), f"/me inconsistent at some read: {[x for x in seen if not (x[0] == x[1] and x[2] == x[1] - x[3] and x[2] >= 0)][:3]}")
    m = S.me("ada")
    t.eq(m.get("available"), 0, "available after the storm")
    t.eq(sum(S.me(h).get("total") for h in HS), TOTAL, "sum of totals after the storm")
    # final captures racing with different keys
    S.reset(basefx())
    aid = mk_auth(t, S, "ada", "bob", 2000)
    S.token("bob")
    rs = par([lambda: cap(S, "bob", aid) for _ in range(20)])
    t.ok(sum(r.status == 201 for r in rs) == 1 and all(r.status == 201 or is_err(r, 409, "authorization_not_open") for r in rs),
         f"20 concurrent final captures: expected 1x201 + 19x409 authorization_not_open, got {sorted(r.status for r in rs)}")
    t.eq(me3(S, "ada"), (8000, 8000, 0), "captured once")
    # nonfinal captures racing: 20 x 100 against 1000
    aid = mk_auth(t, S, "ada", "bob", 1000)
    rs = par([lambda: cap(S, "bob", aid, {"amount": 100, "final": False}) for _ in range(20)])
    t.eq(sum(r.status == 201 for r in rs), 10, f"20 concurrent nonfinal captures of 100 against 1000: 201 count {sorted(r.status for r in rs)}")
    t.ok(all(r.status == 201 or is_err(r, 409, "authorization_not_open") or is_err(r, 422, "capture_exceeds_authorization") for r in rs), "others must be refused")
    a = auth_by_id(S, "ada", aid) or {}
    t.eq((a.get("status"), a.get("captured_amount"), a.get("remaining_amount"), len(a.get("payment_ids") or [])), ("captured", 1000, 0, 10), "authorization after racing captures")
    t.eq(me3(S, "ada"), (7000, 7000, 0), "cumulative captures equal the authorization")
    # capture racing with void
    for rnd in range(3):
        aid = mk_auth(t, S, "ada", "bob", 100)
        S.token("ada")
        rs = par([lambda: ("c", cap(S, "bob", aid)) for _ in range(5)] + [lambda: ("v", S.call("POST", f"/authorizations/{aid}/void", as_="ada")) for _ in range(5)])
        st = (auth_by_id(S, "ada", aid) or {}).get("status")
        n = sum(r.status == 201 for kind, r in rs if kind == "c")
        t.ok(st in ("captured", "voided") and n == (1 if st == "captured" else 0), f"capture/void race round {rnd}: status {st}, capture 201s {n}")
        t.ok(all((r.status == 200) == (st == "voided") for kind, r in rs if kind == "v"), f"capture/void race round {rnd}: void responses {[r.status for kind, r in rs if kind == 'v']} with final {st}")
    # identical keyed requests
    key = k()
    rs = par([lambda: S.call("POST", "/authorizations", {"to_handle": "cy", "amount": 50}, as_="ada", key=key) for _ in range(20)])
    first = next((r for r in rs if r.status == 201), None)
    t.ok(sum(r.status == 201 for r in rs) == 1 and sum(r.status == 200 for r in rs) == 19 and all(r.j == first.j for r in rs if first),
         f"20 identical authorizations: {sorted(r.status for r in rs)}")
    aid = (first.j or {}).get("authorization_id") if first else "x"
    t.eq(S.me("ada").get("held"), 50, "one hold from 20 identical requests")
    S.token("cy")
    key = k()
    rs = par([lambda: cap(S, "cy", aid, {"amount": 20, "final": False}, key=key) for _ in range(20)])
    first = next((r for r in rs if r.status == 201), None)
    t.ok(sum(r.status == 201 for r in rs) == 1 and sum(r.status == 200 for r in rs) == 19 and all(r.j == first.j for r in rs if first),
         f"20 identical captures: {sorted(r.status for r in rs)}")
    t.eq((auth_by_id(S, "ada", aid) or {}).get("captured_amount"), 20, "one capture from 20 identical requests")
    # 50 in flight, mixed
    fx = basefx(payments=[], requests=[])
    for u in fx["users"]:
        u["balance"] = 100000
    S.reset(fx)
    for h in HS:
        S.token(h)
    open_ids = [(HS[i % 5], HS[(i + 1) % 5], mk_auth(t, S, HS[i % 5], HS[(i + 1) % 5], 500)) for i in range(10)]
    bad, worst = [], [0.0]

    def one(i):
        a, b = HS[i % 5], HS[(i + 1) % 5]
        kind = i % 5
        if kind == 0:
            r, okc = S.call("POST", "/authorizations", {"to_handle": b, "amount": 7}, as_=a, key=k()), (201,)
        elif kind == 1:
            frm, to, aid = open_ids[(i // 5) % 10]
            r, okc = cap(S, to, aid, {"amount": 1, "final": False}), (201,)
        elif kind == 2:
            r, okc = S.call("GET", "/authorizations?limit=50", as_=a), (200,)
        elif kind == 3:
            r, okc = S.call("POST", "/payments", {"to_handle": b, "amount": 3}, as_=a, key=k()), (201,)
        else:
            r, okc = S.call("GET", "/me", as_=a), (200,)
            j = r.j or {}
            if not (j.get("balance") == j.get("total") and j.get("available") == j.get("total", 0) - j.get("held", 0) and j.get("available", -1) >= 0):
                bad.append("inconsistent /me " + repr(r)[:140])
        worst[0] = max(worst[0], r.secs)
        if r.status not in okc:
            bad.append(repr(r)[:160])
    for _ in range(5):
        par([lambda i=i: one(i) for i in range(50)])
    t.ok(not bad, f"{len(bad)} unexpected responses under 50 in flight, e.g. {bad[:3]}")
    t.ok(worst[0] < 5.0, f"slowest request under 50 in flight took {worst[0]:.2f}s")
    t.note(f"stage-2 load: slowest request {worst[0]:.3f}s")
    t.eq(sum(S.me(h).get("total") for h in HS), 500000, "sum of totals after load")


# --------------------------------------------------------------------------- L2
@check("L2-content-negotiation", "stage-2 intro (shared routes)", "L1,L2", "/requests and /authorizations return the UI for Accept: text/html and JSON otherwise (401 JSON without a token); /, /split, /signup, /login return HTML")
def c_nego(t, S):
    S.reset(authfx())
    tok = S.token("ada")
    for p in ("/requests", "/authorizations"):
        st, ct, body, loc = html_get(S, p, accept="text/html")
        t.ok(st in (200, 302, 303) and (st != 200 or "text/html" in ct.lower()), f"GET {p} Accept: text/html -> expected the HTML screen, got {st} {ct}")
        st, ct, body, loc = html_get(S, p, accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        t.ok(st in (200, 302, 303) and (st != 200 or "text/html" in ct.lower()), f"GET {p} with a browser Accept header -> expected HTML, got {st} {ct}")
        for acc in (None, "application/json", "*/*"):
            st, ct, body, loc = html_get(S, p, token=tok, accept=acc)
            t.ok(st == 200 and "application/json" in ct.lower() and body.lstrip().startswith(b"{"), f"GET {p} Accept: {acc} with token -> expected JSON 200, got {st} {ct}")
            st, ct, body, loc = html_get(S, p, accept=acc)
            t.ok(st == 401 and b"unauthenticated" in body and "application/json" in ct.lower(), f"GET {p} Accept: {acc} without token -> expected 401 JSON, got {st} {ct} {body[:80]!r}")
    for p in ("/", "/split", "/signup", "/login"):
        st, ct, body, loc = html_get(S, p)
        t.ok(st in (200, 302, 303) and (st != 200 or ("text/html" in ct.lower() and b"<" in body)), f"GET {p} Accept: text/html -> expected HTML, got {st} {ct}")
    for p in ("/signup", "/login"):
        st, ct, body, loc = html_get(S, p)
        t.ok(st == 200 and "text/html" in ct.lower(), f"GET {p} signed out -> expected 200 HTML, got {st} {ct}")


# --------------------------------------------------------------------------- R5 / R1
def r_prepare(t, S):
    S.reset(basefx(authorization_ttl_seconds=1234))
    ctx = {"tok": {h: S.token(h) for h in HS}, "keys": {}}
    k1, k2, k3 = k(), k(), k()
    b1 = {"to_handle": "bob", "amount": 2000, "note": "hold \U0001F512", "visibility": "private"}
    r1 = S.call("POST", "/authorizations", b1, as_="ada", key=k1)
    t.st(r1, 201, "prepare: authorize")
    ctx["open"] = (r1.j or {}).get("authorization_id")
    b2 = {"amount": 700, "final": False}
    r2 = S.call("POST", f"/authorizations/{ctx['open']}/capture", b2, as_="bob", key=k2)
    t.st(r2, 201, "prepare: partial capture")
    aid2 = mk_auth(t, S, "ada", "cy", 300)
    r3 = S.call("POST", f"/authorizations/{aid2}/capture", {}, as_="cy", key=k3)
    t.st(r3, 201, "prepare: final capture")
    aid3 = mk_auth(t, S, "dan", "ada", 100)
    t.st(S.call("POST", f"/authorizations/{aid3}/void", as_="dan"), 200, "prepare: void")
    ctx["keys"] = {"authorize": ("ada", "/authorizations", b1, k1, r1.j), "capture": ("bob", f"/authorizations/{ctx['open']}/capture", b2, k2, r2.j),
                   "capture-final": ("cy", f"/authorizations/{aid2}/capture", {}, k3, r3.j)}
    ctx["snap"] = r_snapshot(S, ctx)
    r = S.call("GET", "/_test/export")
    t.ok(r.status == 200 and isinstance(r.j, dict) and r.j.get("track") == "pocketful" and r.j.get("format_version") == 1 and isinstance(r.j.get("state"), dict),
         f"export shape: {r.text[:120]}")
    ctx["export"] = r.j
    return ctx


def r_snapshot(S, ctx):
    snap = {}
    for h, tok in ctx["tok"].items():
        snap[h] = [S.call("GET", p, token=tok).j for p in ("/me", "/activity?limit=200", "/requests?limit=200", "/authorizations?limit=200")]
    return snap


@check("R5-export-import-holds", "stage-1 §10 applied to stage 2; stage-2 seven idempotent paths", "R5", "Stage-2 export/import round-trips authorizations, holds, partial captures, the ttl and the idempotency records of the two new paths; replays return the originals; the open hold stays capturable")
def c_r5(t, S):
    ctx = r_prepare(t, S)
    S.call("POST", "/payments", {"to_handle": "bob", "amount": 1}, as_="ada", key=k())
    S.reset(OTHERFX)
    r = S.call("POST", "/_test/import", ctx["export"])
    t.st(r, 204, "import")
    S.tok = {}
    t.ok(r_snapshot(S, ctx) == ctx["snap"], "/me, /activity, /requests or /authorizations differ after import")
    t.eq(me3(S, "ada"), (9000, 7700, 1300), "ada total/available/held after import")
    for name, (who, path, body, key, orig) in ctx["keys"].items():
        r = S.call("POST", path, body, token=ctx["tok"][who], key=key)
        t.ok(r.status == 200 and r.j == orig, f"replay of {name} after import: {r!r}"[:300])
        t.err(S.call("POST", path, dict(body, zz=1), token=ctx["tok"][who], key=key), 409, "idempotency_key_reuse", f"{name} key with another body after import")
    t.ok(r_snapshot(S, ctx) == ctx["snap"], "replays after import changed state")
    r = S.call("POST", "/_test/import", ctx["export"])
    t.ok(r.status == 204 and r_snapshot(S, ctx) == ctx["snap"], "repeated import must restore exactly the exported state")
    r = S.call("POST", "/authorizations", {"to_handle": "bob", "amount": 1}, token=ctx["tok"]["cy"], key=k())
    if t.st(r, 201, "authorize after import"):
        t.eq((parse_ts(r.j["expires_at"]) - parse_ts(r.j["created_at"])).total_seconds(), 1234.0, "authorization_ttl_seconds preserved by import")
    r = S.call("POST", f"/authorizations/{ctx['open']}/capture", {"amount": 1300}, token=ctx["tok"]["bob"], key=k())
    t.st(r, 201, "imported open hold captured in full")
    t.err(S.call("POST", f"/authorizations/{ctx['open']}/capture", {"amount": 1}, token=ctx["tok"]["bob"], key=k()), 409, "authorization_not_open", "no capture beyond the imported remainder")
    t.eq(sum(S.call("GET", "/me", token=ctx["tok"][h]).j.get("total") for h in HS), TOTAL + 1 - 1, "sum of totals after import")


def subset(a, b):
    """Every member of the stage-1 value `a` is present and equal in the stage-2 value `b`."""
    if isinstance(a, dict):
        return isinstance(b, dict) and all(kk in b and subset(v, b[kk]) for kk, v in a.items())
    if isinstance(a, (list, tuple)):
        return isinstance(b, (list, tuple)) and len(a) == len(b) and all(subset(x, y) for x, y in zip(a, b))
    return a == b and isinstance(a, bool) == isinstance(b, bool)


@check("R1-upgrade-import", "stage-2 Existing clients after an upgrade; stage-1 §10", "R1,R3,R4", "A stage-2 service accepts an export produced by this team's stage-1 service: tokens, password login, balances, payments, requests, operators and idempotency records survive; a lost-response payment is retryable with the same key and body; pending requests stay payable; there are no holds and the ttl is 600")
def c_r1(t, S):
    base1 = os.environ.get("S1BASE")
    if not base1:
        t.ok(False, "not run: needs S1BASE (a running stage-1 container)")
        return
    S1 = c1.Sess(base1)
    ctx = j_prepare(t, S1)
    S.reset(OTHERFX)
    r = S.call("POST", "/_test/import", ctx["export"])
    t.st(r, 204, "stage-2 import of the stage-1 export")
    S.tok = {}
    snap = c1.j_snapshot(S, ctx)
    for h in ctx["snap"]:
        t.ok(subset(ctx["snap"][h], snap[h]), f"{h}: stage-1 /me, /activity or /requests not preserved: {str(snap[h])[:240]} vs {str(ctx['snap'][h])[:240]}")
    for h in ("ada", "bob", "nina"):
        m = S.call("GET", "/me", token=ctx["tok"][h]).j or {}
        t.ok(m.get("balance") == m.get("total") == m.get("available") and m.get("held") == 0, f"{h} /me after upgrade: {m}")
        r = S.call("GET", "/authorizations", token=ctx["tok"][h])
        t.ok(r.status == 200 and (r.j or {}).get("authorizations") == [], f"{h}: authorizations after upgrade: {r!r}")
    for p in (snap["ada"][3] or {}).get("payments", []):
        t.eq(p.get("authorization_id", "MISSING"), None, f"imported payment {p.get('payment_id')} authorization_id")
    t.st(S.call("POST", "/auth/login", {"email": "ada@example.com", "password": PW}), 200, "password login after upgrade")
    for name, (who, path, body, key, orig) in ctx["keys"].items():
        r = S.call("POST", path, body, token=ctx["tok"][who], key=key)
        t.ok(r.status == 200 and subset(orig, r.j), f"retry of {name} with the same key and body after upgrade must return the original: {r!r}"[:300])
        t.err(S.call("POST", path, dict(body, zz_changed=1), token=ctx["tok"][who], key=key), 409, "idempotency_key_reuse", f"{name} key with another body after upgrade")
    t.ok(all(subset(ctx["snap"][h], s) for h, s in c1.j_snapshot(S, ctx).items()), "retries after upgrade changed state")
    r = S.call("POST", "/requests", {"payer_handle": "ada", "amount": 9}, token=ctx["tok"]["bob"], key=k())
    rid = (r.j or {}).get("request_id")
    t.st(S.call("POST", f"/requests/{rid}/pay", {}, token=ctx["tok"]["ada"], key=k()), 201, "request created after upgrade is payable")
    pend = [q for q in (snap["ada"][5] or {}).get("requests", []) if q.get("status") == "pending" and q.get("payer_handle") == "ada" and q.get("amount", 0) > 0]
    t.ok(bool(pend), "the stage-1 export holds a pending request for ada")
    for q in pend[:1]:
        t.st(S.call("POST", f"/requests/{q['request_id']}/pay", {}, token=ctx["tok"]["ada"], key=k()), 201, "pending request from the stage-1 export is payable")
    r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 5}, token=ctx["tok"]["dan"], key=ctx["failkey"])
    t.st(r, 201, "key of a request that failed in stage 1 is a first use after upgrade")
    r = S.call("POST", "/authorizations", {"to_handle": "bob", "amount": 10}, token=ctx["tok"]["ada"], key=k())
    if t.st(r, 201, "authorize after upgrade"):
        t.eq((parse_ts(r.j["expires_at"]) - parse_ts(r.j["created_at"])).total_seconds(), 600.0, "ttl after importing a stage-1 export (default 600)")
    t.st(S.call("POST", "/settlements", {"transfers": [tr("ada", "bob", 1)]}, token=ctx["tok"]["op"], key=k()), 201, "operator permission after upgrade")


if __name__ == "__main__":
    if "--s1base" in sys.argv:
        i = sys.argv.index("--s1base")
        os.environ["S1BASE"] = sys.argv[i + 1]
        del sys.argv[i:i + 2]
    sys.exit(c1.main())
