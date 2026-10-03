"""L5, H2. Exports of the accepted stage-1 and stage-2 services and of stage 3 itself, imported into stage 3."""
import copy
import json
import random
import time
from fractions import Fraction

import pytest

from lib import (BASE, BASE1, BASE2, BASEP2, GET, POST, PW, US, World, build_model, call, check_auth, check_everything,
                 check_payment, check_revision, correct, err, fixture, fmt, full_statement, inst, k, me_at, now_f, ok, q,
                 revisions, seeded_auth, soft, statement, user)
from test_u_http import build_stage1, snap1, strip2
from test_w_model import HANDLES, random_fixture, run_ops


def strip3(v):
    """Drop the members stage 3 adds to earlier answers."""
    if isinstance(v, dict):
        return {kk: strip3(x) for kk, x in v.items() if kk not in ("closed_at",)}
    if isinstance(v, (list, tuple)):
        return [strip3(x) for x in v]
    return v


def moved(w_old, tokens, extra=None):
    w = World(w_old.fx, base=BASE, do_reset=False)
    w.tok = {h: t for h, t in tokens.items() if h in [u["handle"] for u in w_old.fx["users"]]}
    w.extra = {h: t for h, t in tokens.items() if h not in w.tok}
    return w


def test_l5_h2_stage1_export_into_stage3():
    w1, done, tokens, failed_key, su = build_stage1()
    before = snap1(w1, tokens, BASE1)
    e = call("GET", "/_test/export", base=BASE1)
    World(fixture(users=[user("zed", 9)]))
    r = call("POST", "/_test/import", raw=e.content)
    assert r.status_code == 204, f"stage-3 import of the stage-1 export: {r.status_code} {r.text[:300]}"
    after = snap1(w1, tokens, BASE)
    assert strip2(after) == strip2(before)
    w = moved(w1, tokens)
    # the ledger: revision 1 for every payment, statements and historical reads over the imported history
    m = build_model(w)
    for pid, p in m.pay.items():
        assert len(p["revs"]) == 1
        r1 = p["revs"][0]
        assert (r1["revision"], r1["amount"], r1["reason"]) == (1, p["obj"]["amount"], "")
        assert r1["eff"] == r1["rec"] == inst(p["obj"]["created_at"])
    assert m.opening["u_ada"] == 10500 and m.opening["u_bob"] == 2000, m.opening
    first = min(inst(p["obj"]["created_at"]) for p in m.pay.values())
    for h in w.handles():
        uid = next(u for u, hh in m.handle_of.items() if hh == h)
        assert ok(me_at(w, h, fmt(first - 3600)), 200)["balance"] == m.opening[uid], f"{h}: opening balance before the first payment"
        s = full_statement(w, h)
        assert s["opening_balance"] == m.opening[uid] and s["closing_balance"] == before[h]["me"]["balance"]
    check_everything(w, m, random.Random(31), me_points=50, st_points=15)
    # replays and receipts
    for d in done:
        r = call("POST", d["path"], tokens[d["who"]], key=d["key"], body=d["body"])
        assert r.status_code == 200 and strip2(r.json()) == strip2(d["resp"]), f"replay {d['path']}: {r.status_code}"
    # an imported ordinary payment can be corrected; an imported settlement member cannot
    plain = [d for d in done if d["path"] == "/payments"][0]["resp"]
    member = [d for d in done if d["path"] == "/settlements"][0]["resp"]["payments"][0]
    err(correct(w, "ada", member["payment_id"], 1, 1, member["created_at"]), 422, "linked_payment_immutable")
    j = check_revision(ok(correct(w, "ada", plain["payment_id"], 1, 40, plain["created_at"], "after the upgrade"), 201), revision=2)
    assert inst(j["recorded_at"]) > max(inst(p["obj"]["created_at"]) for p in m.pay.values()), \
        "a correction after the import must be recorded after everything imported"
    assert w.bal("ada") == before["ada"]["me"]["balance"] + 60
    check_everything(w, build_model(w), random.Random(32), me_points=30, st_points=10)
    e3 = call("GET", "/_test/export")
    assert call("POST", "/_test/import", raw=e3.content).status_code == 204


def build_stage2():
    assert BASEP2, "BASEP2 (a container of the accepted stage-2 image) is not set"
    pays = [{"id": "p_seed", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee ☕", "visibility": "public"}]
    reqs = [{"id": "rq_seed", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]
    auths = [seeded_auth("a_seed", "ada", "bob", 250), seeded_auth("a_old", "ada", "bob", 90, status="captured", expires_in=-7200)]
    w = World(fixture(payments=pays, requests=reqs, auths=auths), base=BASEP2).login_all()
    done = []

    def rec(who, path, body):
        key = k()
        r = call("POST", path, w.t(who), key=key, body=body, base=BASEP2)
        assert r.status_code == 201, r.text
        done.append({"who": who, "path": path, "key": key, "body": body, "resp": r.json()})
        return r.json()

    rec("ada", "/payments", {"to_handle": "bob", "amount": 100, "note": "pub 😀"})
    rec("bob", "/payments", {"to_handle": "cy", "amount": 250, "note": "prv", "visibility": "private"})
    a1 = rec("ada", "/authorizations", {"to_handle": "bob", "amount": 300, "note": "hold 1"})
    time.sleep(1.1)
    rec("bob", f"/authorizations/{a1['authorization_id']}/capture", {"amount": 100, "final": False})
    time.sleep(1.1)
    rec("bob", f"/authorizations/{a1['authorization_id']}/capture", {"amount": 50})
    a2 = rec("ada", "/authorizations", {"to_handle": "cy", "amount": 400, "visibility": "private"})
    assert call("POST", f"/authorizations/{a2['authorization_id']}/void", w.t("ada"), base=BASEP2).status_code == 200
    time.sleep(1.2)                                   # stage 2 may stamp whole seconds: keep a3's creation apart
    a3 = rec("ada", "/authorizations", {"to_handle": "dan", "amount": 700})
    time.sleep(1.2)
    a4 = rec("bob", "/authorizations", {"to_handle": "ada", "amount": 200})
    rec("ada", f"/authorizations/{a4['authorization_id']}/capture", {"amount": 80, "final": False})
    time.sleep(1.1)
    assert call("POST", f"/authorizations/{a4['authorization_id']}/void", w.t("bob"), base=BASEP2).status_code == 200
    rec("op", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100},
                                             {"from_handle": "bob", "to_handle": "dan", "amount": 50, "visibility": "private"}]})
    rq = rec("cy", "/requests", {"payer_handle": "ada", "amount": 40})
    rec("ada", f"/requests/{rq['request_id']}/pay", {})
    tokens = {h: w.t(h) for h in w.handles()}
    return w, done, tokens, a3


def test_l5_h2_stage2_export_into_stage3():
    w2, done, tokens, a3 = build_stage2()
    before = w2.snapshot(tokens, base=BASEP2)
    e = call("GET", "/_test/export", base=BASEP2)
    World(fixture(users=[user("zed", 9)]))
    r = call("POST", "/_test/import", raw=e.content)
    assert r.status_code == 204, f"stage-3 import of the stage-2 export: {r.status_code} {r.text[:300]}"
    w = moved(w2, tokens)
    after = w.snapshot(tokens)
    assert strip3(after) == strip3(before), "what stage 2 answered is not what stage 3 answers after the import"
    for h in w.handles():
        for a in w.auths(h):
            check_auth(a)
            if a["status"] == "open":
                assert a["closed_at"] is None
            else:
                soft(a["closed_at"] is not None, "imported-closed-authorisation-without-closed_at", id=a["authorization_id"],
                     status=a["status"])
    m = build_model(w)
    assert all(len(p["revs"]) == 1 for p in m.pay.values())
    assert m.opening == {"u_ada": 10500, "u_bob": 2000, "u_cy": 0, "u_dan": 500, "u_op": 1000}, m.opening
    first = min(inst(p["obj"]["created_at"]) for p in m.pay.values())
    for h in w.handles():
        uid = f"u_{h}"
        b = ok(me_at(w, h, fmt(first - 3600)), 200)
        assert b["balance"] == b["total"] == m.opening[uid] and b["held"] == 0 and b["available"] == b["total"], b
        s = full_statement(w, h)
        assert s["opening_balance"] == m.opening[uid] and s["closing_balance"] == before[h]["me"][1]["balance"]
        caps = [x for x in s["entries"] if x["payment"]["authorization_id"]]
        assert len({x["payment"]["payment_id"] for x in caps}) == len(caps), "a capture appears exactly once"
    # totals are hard; the hold history of imported closed authorisations is the map's decision G-12
    check_everything(w, m, random.Random(33), me_points=50, st_points=15, hard_held=False)
    # captures and settlement members stay linked and immutable; replays answer as before
    for d in done:
        r = call("POST", d["path"], tokens[d["who"]], key=d["key"], body=d["body"])
        assert r.status_code == 200 and strip3(r.json()) == strip3(d["resp"]), f"replay {d['path']}: {r.status_code} {r.text[:200]}"
        if d["path"].endswith("/capture"):
            pay = d["resp"]
            err(correct(w, pay["from_handle"], pay["payment_id"], 1, 1, pay["created_at"]), 422, "linked_payment_immutable")
    member = [d for d in done if d["path"] == "/settlements"][0]["resp"]["payments"][1]
    err(correct(w, "bob", member["payment_id"], 1, 1, member["created_at"]), 422, "linked_payment_immutable")
    # the open holds are still open, hold historically from their creation, and can be captured
    ada_now = w.wallet("ada")
    assert ada_now["held"] == 250 + 700
    t_a3 = inst(a3["created_at"])
    b = ok(me_at(w, "ada", fmt(t_a3 - US)), 200)
    c = ok(me_at(w, "ada", fmt(t_a3)), 200)
    assert c["held"] - b["held"] == 700, f"the imported open hold should start at its creation: {b['held']} -> {c['held']}"
    cap = ok(w.capture("dan", a3["authorization_id"], body={"amount": 300}), 201)
    closed = check_auth(w.auth("ada", a3["authorization_id"]), status="captured")
    assert inst(closed["closed_at"]) == inst(cap["created_at"])
    plain = done[0]["resp"]
    ok(correct(w, "ada", plain["payment_id"], 1, 10, plain["created_at"], "after the upgrade"), 201)
    w.assert_conserved()
    m2 = build_model(w)
    check_everything(w, m2, random.Random(34), me_points=30, st_points=10, hard_held=False)
    e3 = call("GET", "/_test/export")
    assert call("POST", "/_test/import", raw=e3.content).status_code == 204


def deep_view(w, pids, points, base):
    out = {}
    for h in w.handles():
        tk = w.t(h)
        v = {"me": call("GET", "/me", tk, base=base).json()}
        for (T, K) in points:
            r = call("GET", "/me?" + q(as_of=T, known_at=K), tk, base=base)
            v[f"me {T} {K}"] = (r.status_code, r.json())
        for name, params in (("all", {}), ("known", {"known_at": points[3][1]}), ("window", {"from": points[1][0], "to": points[5][0]}),
                             ("paged", {"limit": 3, "offset": 2})):
            r = call("GET", "/statement?" + q(limit=200, **params) if name != "paged" else "/statement?" + q(**params), tk, base=base)
            j = r.json()
            j.pop("snapshot", None)
            v[f"statement {name}"] = (r.status_code, j)
        for ep in ("/activity?limit=200", "/requests?limit=200", "/authorizations?limit=200"):
            v[ep] = call("GET", ep, tk, base=base).json()
        for pid in pids:
            r = call("GET", f"/payments/{pid}/revisions", tk, base=base)
            v[f"rev {pid}"] = (r.status_code, r.json())
        out[h] = v
    return out


def test_l5_stage3_export_into_another_stage3_container():
    assert BASE2
    rng = random.Random(505)
    fx, opening, base_t = random_fixture(rng)
    w = World(fx).login_all()
    m = build_model(w)
    log = []
    run_ops(w, m, rng, base_t, 45, log)
    keyed = []
    for p in list(m.pay.values())[:3]:
        if p["obj"].get("authorization_id"):
            continue
        cur = p["revs"][-1]
        key = k()
        sender = m.handle_of[p["frm"]]
        body = {"expected_revision": cur["revision"], "amount": cur["amount"], "effective_at": cur["effective_at"], "reason": "keyed"}
        r = POST(f"/payments/{p['obj']['payment_id']}/corrections", w.t(sender), body, key=key)
        if r.status_code == 201:
            keyed.append((sender, p["obj"]["payment_id"], key, body, r.json()))
    assert keyed
    snaps = {h: ok(statement(w, h, limit=4), 200) for h in HANDLES}
    m = build_model(w)
    bs = m.boundaries()
    pts = [(fmt(rng.choice(bs) + rng.choice([-US, 0, US])), fmt(rng.choice(bs) + rng.choice([-US, 0, US]))) for _ in range(40)]
    pts += [(fmt(now_f() + 86400), None), (None, fmt(bs[len(bs) // 2])), (fmt(bs[0] - 60), fmt(now_f() + 86400))]
    pids = list(m.pay)
    before = deep_view(w, pids, pts, BASE)
    e = call("GET", "/_test/export")
    assert e.status_code == 200
    World(fixture(users=[user("zed", 9)]), base=BASE2)
    for attempt in range(2):                                   # import is replacement: repeating it changes nothing
        r = call("POST", "/_test/import", raw=e.content, base=BASE2)
        assert r.status_code == 204, f"stage-3 import of its own export: {r.status_code} {r.text[:300]}"
        wb = World(fx, base=BASE2, do_reset=False)
        wb.tok = dict(w.tok)
        after = deep_view(wb, pids, pts, BASE2)
        for h in before:
            for kk in before[h]:
                assert after[h][kk] == before[h][kk], f"attempt {attempt}: {h} {kk} differs after the import:\n{before[h][kk]}\n{after[h][kk]}"
    for sender, pid, key, body, resp in keyed:
        r = call("POST", f"/payments/{pid}/corrections", wb.t(sender), key=key, body=body, base=BASE2)
        assert r.status_code == 200 and r.json() == resp, f"correction replay after import: {r.status_code} {r.text[:200]}"
        err(call("POST", f"/payments/{pid}/corrections", wb.t(sender), key=key, body={**body, "reason": "other"}, base=BASE2),
            409, "idempotency_key_reuse")
    for h in HANDLES:
        r = statement(wb, h, snapshot=snaps[h]["snapshot"], limit=4)
        if soft(r.status_code == 200, "snapshot-token-not-valid-after-import-into-another-container", status=r.status_code):
            assert r.json()["entries"] == snaps[h]["entries"] and r.json()["closing_balance"] == snaps[h]["closing_balance"]
        else:
            err(r, 404, "not_found")
    # the imported service keeps working: the clock continues after everything imported
    mb = build_model(wb)
    latest = max(r["rec"] for p in mb.pay.values() for r in p["revs"])
    sender, pid, key, body, resp = keyed[0]
    cur = len(ok(revisions(wb, sender, pid), 200)["revisions"])
    j = ok(correct(wb, sender, pid, cur, body["amount"], body["effective_at"], "on the destination"), 201)
    assert inst(j["recorded_at"]) > latest, "recorded times must keep increasing after an import"
    newp = ok(wb.pay("ada", "bob", 1), 201) if wb.wallet("ada")["available"] >= 1 else None
    if newp:
        assert inst(newp["created_at"]) > latest
    check_everything(wb, build_model(wb), rng, me_points=40, st_points=12)
    # the source is untouched by all this, and a reset of the destination clears everything
    assert deep_view(w, pids, pts, BASE) == before
    World(fixture(users=[user("zed", 9)]), base=BASE2)
    err(call("GET", "/me", wb.t("ada"), base=BASE2), 401, "unauthenticated")


def test_l5_export_reset_import_on_the_same_container_keeps_snapshots_and_history():
    w = World().login_all()
    ps = [ok(w.pay("ada", "bob", 50 + i), 201) for i in range(6)]
    ok(correct(w, "ada", ps[0]["payment_id"], 1, 5, fmt(inst(ps[0]["created_at"]) - 3600), "earlier"), 201)
    a = w.new_auth("ada", "cy", 500)
    ok(w.capture("cy", a["authorization_id"], body={"amount": 100, "final": False}), 201)
    snap = ok(statement(w, "ada", limit=2), 200)
    whole = full_statement(w, "ada")
    m = build_model(w)
    e = call("GET", "/_test/export")
    ok(w.pay("ada", "bob", 999), 201)                                    # a later write does not change the export
    World(fixture(users=[user("zed", 9)]))
    err(statement(World(fixture(users=[user("ada", 5)])), "ada", snapshot=snap["snapshot"]), 404, "not_found")
    assert call("POST", "/_test/import", raw=e.content).status_code == 204
    assert full_statement(w, "ada")["entries"] == whole["entries"]
    r = statement(w, "ada", snapshot=snap["snapshot"], limit=2)
    if soft(r.status_code == 200, "snapshot-token-not-valid-after-export-reset-import", status=r.status_code):
        assert r.json()["entries"] == snap["entries"]
    check_everything(w, build_model(w), random.Random(35), me_points=40, st_points=12)
    assert w.wallet("ada")["held"] == 400
