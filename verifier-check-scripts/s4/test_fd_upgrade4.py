"""M4. Exports of the accepted stage-1, stage-2 and stage-3 services and of stage 4 itself, imported into stage 4."""
import random

import pytest

from lib import (BASE, BASE1, BASE2, BASEP3, GET, POST, US, World, batch, build_model, call, check_batch, check_everything,
                 check_payment, correct, err, fixture, fmt, full_statement, inst, item, k, members, now_f, ok, q, refund,
                 revisions, soft, statement, user)
from test_fc_model4 import run_ops4
from test_u_http import build_stage1, snap1, strip2
from test_w_model import HANDLES, random_fixture, run_ops
from test_x_upgrade3 import deep_view, strip3


def with_op(fx):
    fx["users"].append(user("op", 0))
    fx["settlement_operator_ids"] = ["u_op"]
    return fx


def ring(w):
    """The handle with the most available funds first, then two others."""
    order = sorted(HANDLES, key=lambda h: -w.wallet(h)["available"])
    return order[0], order[1], order[2]


def points(m, rng, n=40):
    bs = m.boundaries()
    pts = [(fmt(rng.choice(bs) + rng.choice([-US, 0, US])), fmt(rng.choice(bs) + rng.choice([-US, 0, US]))) for _ in range(n)]
    return pts + [(fmt(now_f() + 86400), None), (None, fmt(bs[len(bs) // 2])), (fmt(bs[0] - 60), fmt(now_f() + 86400))]


def test_m4_stage3_export_into_stage4_keeps_corrections_and_snapshots():
    assert BASEP3, "BASEP3 (a container of the accepted stage-3 image) is not set"
    rng = random.Random(707)
    fx, opening, base_t = random_fixture(rng)
    with_op(fx)
    w3 = World(fx, base=BASEP3).login_all()
    m = build_model(w3)
    run_ops(w3, m, rng, base_t, 45, [])
    skey = k()
    a, b, c = ring(w3)
    sbody = {"transfers": [{"from_handle": a, "to_handle": b, "amount": 3, "note": "s"},
                           {"from_handle": b, "to_handle": c, "amount": 2, "visibility": "private"}]}
    st = ok(call("POST", "/settlements", w3.t("op"), key=skey, body=sbody, base=BASEP3), 201)
    keyed = []
    for p in list(m.pay.values())[:4]:
        if p["obj"].get("authorization_id"):
            continue
        cur = p["revs"][-1]
        key, sender = k(), m.handle_of[p["frm"]]
        body = {"expected_revision": cur["revision"], "amount": cur["amount"], "effective_at": cur["effective_at"], "reason": "keyed"}
        r = call("POST", f"/payments/{p['obj']['payment_id']}/corrections", w3.t(sender), key=key, body=body, base=BASEP3)
        if r.status_code == 201:
            keyed.append((sender, p["obj"]["payment_id"], key, body, r.json()))
    assert keyed
    m = build_model(w3)
    longf = "2020-01-01T00:00:00." + "1" * 150 + "Z"
    snaps = {}
    for h in HANDLES:
        snaps[h] = [ok(statement(w3, h, limit=4), 200), ok(statement(w3, h, limit=3, offset=1, known_at=fmt(m.boundaries()[len(m.boundaries()) // 2])), 200),
                    ok(statement(w3, h, **{"from": longf, "limit": 5}), 200)]
    pts = points(m, rng)
    pids = list(m.pay)
    before = deep_view(w3, pids, pts, BASEP3)
    e = call("GET", "/_test/export", base=BASEP3)
    World(fixture(users=[user("zed", 9)]))
    r = call("POST", "/_test/import", raw=e.content)
    assert r.status_code == 204, f"stage-4 import of the stage-3 export: {r.status_code} {r.text[:300]}"
    w = World(fx, do_reset=False)
    w.tok = dict(w3.tok)
    after = deep_view(w, pids, pts, BASE)
    for h in before:
        for kk in before[h]:
            assert strip3(after[h][kk]) == strip3(before[h][kk]), f"{h} {kk} differs after the import into stage 4"
    for h in HANDLES:
        for p in w.activity(h):
            check_payment(p, refund_of=None)
    # stage-3 snapshot tokens keep paging their frozen entries
    for h in HANDLES:
        for first, (limit, offset) in zip(snaps[h], ((4, 0), (3, 1), (5, 0))):
            pg = ok(statement(w, h, snapshot=first["snapshot"], limit=limit, offset=offset), 200, f"stage-3 snapshot token of {h} after the import")
            assert strip3(pg["entries"]) == strip3(first["entries"]), "a stage-3 snapshot pages other entries after the import"
            assert (pg["opening_balance"], pg["closing_balance"], pg["has_more"]) == \
                (first["opening_balance"], first["closing_balance"], first["has_more"])
    # correction and settlement retries answer as before
    for sender, pid, key, body, resp in keyed:
        r = call("POST", f"/payments/{pid}/corrections", w.t(sender), key=key, body=body)
        assert r.status_code == 200 and strip3(r.json()) == strip3(resp), f"correction replay after the import: {r.status_code} {r.text[:200]}"
    r = call("POST", "/settlements", w.t("op"), key=skey, body=sbody)
    assert r.status_code == 200 and strip3(r.json()) == strip3(st)
    # the imported ledger takes stage-4 operations: batches over the imported settlement, refunds, further corrections
    m4 = build_model(w)
    check_everything(w, m4, rng, me_points=40, st_points=12)
    mem = st["payments"]
    err(batch(w, [item(mem[0], 3)]), 422, "incomplete_settlement")
    err(correct(w, a, mem[0]["payment_id"], 1, 3, mem[0]["created_at"]), 422, "linked_payment_immutable")
    items = [item(x, x["amount"]) for x in mem]
    j = check_batch(ok(batch(w, items), 201), items)
    latest = max(r["rec"] for p in m4.pay.values() for r in p["revs"])
    assert inst(j["recorded_at"]) > latest, "recorded times must keep increasing after the import"
    rf = check_payment(ok(refund(w, b, mem[0]["payment_id"], 1), 201), refund_of=mem[0]["payment_id"], settlement_id=None)
    sender, pid, key, body, resp = keyed[0]
    cur = len(ok(revisions(w, sender, pid), 200)["revisions"])
    ok(correct(w, sender, pid, cur, body["amount"], body["effective_at"], "on stage 4"), 201)
    run_ops4(w, m5 := build_model(w), rng, base_t, 30, [])
    check_everything(w, build_model(w), rng, me_points=40, st_points=12)
    for h in HANDLES:
        pg = ok(statement(w, h, snapshot=snaps[h][0]["snapshot"], limit=4), 200)
        assert strip3(pg["entries"]) == strip3(snaps[h][0]["entries"]), "a stage-3 snapshot changed after stage-4 operations"
    w.assert_conserved()
    e4 = call("GET", "/_test/export")
    assert call("POST", "/_test/import", raw=e4.content).status_code == 204


def test_m4_stage4_export_into_another_stage4_container():
    assert BASE2
    rng = random.Random(808)
    fx, opening, base_t = random_fixture(rng)
    with_op(fx)
    w = World(fx).login_all()
    m = build_model(w)
    run_ops4(w, m, rng, base_t, 60, [])
    m = build_model(w)
    # one keyed refund, one keyed batch over a whole settlement plus an ordinary payment, one keyed single correction
    done = []
    skey = k()
    a, b, c = ring(w)
    sbody = {"transfers": [{"from_handle": a, "to_handle": b, "amount": 4}, {"from_handle": b, "to_handle": c, "amount": 4}]}
    st = ok(POST("/settlements", w.t("op"), sbody, key=skey), 201)
    done.append(("op", "/settlements", skey, sbody, st))
    key = k()
    rb = {"amount": 1}
    rf = ok(call("POST", f"/payments/{st['payments'][1]['payment_id']}/refunds", w.t(c), key=key, body=rb), 201)
    done.append((c, f"/payments/{st['payments'][1]['payment_id']}/refunds", key, rb, rf))
    plain = ok(w.pay(a, b, 1), 201) if w.wallet(a)["available"] >= 1 else None
    its = [item(x, x["amount"]) for x in st["payments"]] + ([item(plain, 1, reason="with the settlement")] if plain else [])
    key = k()
    bj = ok(batch(w, its, key=key), 201)
    done.append(("op", "/correction-batches", key, {"corrections": its}, bj))
    m = build_model(w)
    snaps = {h: ok(statement(w, h, limit=4), 200) for h in HANDLES}
    pts = points(m, rng)
    pids = list(m.pay)
    before = deep_view(w, pids, pts, BASE)
    e = call("GET", "/_test/export")
    World(fixture(users=[user("zed", 9)]), base=BASE2)
    for attempt in range(2):
        r = call("POST", "/_test/import", raw=e.content, base=BASE2)
        assert r.status_code == 204, f"stage-4 import of its own export: {r.status_code} {r.text[:300]}"
        wb = World(fx, base=BASE2, do_reset=False)
        wb.tok = dict(w.tok)
        after = deep_view(wb, pids, pts, BASE2)
        for h in before:
            for kk in before[h]:
                assert after[h][kk] == before[h][kk], f"attempt {attempt}: {h} {kk} differs after the import"
    for who, path, key, body, resp in done:
        r = call("POST", path, wb.t(who), key=key, body=body, base=BASE2)
        assert r.status_code == 200 and r.json() == resp, f"replay {path} after import: {r.status_code} {r.text[:200]}"
        err(call("POST", path, wb.t(who), key=key, body={**body, "x": 1}, base=BASE2), 409, "idempotency_key_reuse")
    for h in HANDLES:
        pg = ok(statement(wb, h, snapshot=snaps[h]["snapshot"], limit=4), 200)
        assert pg["entries"] == snaps[h]["entries"]
    mb = build_model(wb)
    for pid, p in mb.pay.items():
        assert p["obj"].get("refund_of") == m.pay[pid]["obj"].get("refund_of")
        assert [r.get("correction_batch_id") for r in p["revs"]] == [r.get("correction_batch_id") for r in m.pay[pid]["revs"]]
    assert set(members(mb, st["settlement_id"])) == {x["payment_id"] for x in st["payments"]}
    run_ops4(wb, mb, rng, base_t, 30, [])
    check_everything(wb, build_model(wb), rng, me_points=40, st_points=12)
    assert deep_view(w, pids, pts, BASE) == before, "the source changed"
    World(fixture(users=[user("zed", 9)]), base=BASE2)
    err(call("GET", "/me", wb.t("ada"), base=BASE2), 401, "unauthenticated")


def test_m4_stage1_export_then_refunds_and_batches():
    w1, done, tokens, failed_key, su = build_stage1()
    before = snap1(w1, tokens, BASE1)
    e = call("GET", "/_test/export", base=BASE1)
    World(fixture(users=[user("zed", 9)]))
    assert call("POST", "/_test/import", raw=e.content).status_code == 204
    assert strip2(snap1(w1, tokens, BASE)) == strip2(before)
    w = World(w1.fx, do_reset=False)
    w.tok = {h: t for h, t in tokens.items() if h in [u["handle"] for u in w1.fx["users"]]}
    w.extra = {h: t for h, t in tokens.items() if h not in w.tok}
    sd = [d for d in done if d["path"] == "/settlements"][0]
    mem = sd["resp"]["payments"]                       # ada -> bob 100, bob -> dan 50 (private)
    plain = [d for d in done if d["path"] == "/payments"][0]["resp"]
    for p in w.activity("ada"):
        check_payment(p, refund_of=None)
    err(batch(w, [item(mem[1], 50)]), 422, "incomplete_settlement")
    items = [item(mem[0], 80), item(mem[1], 50), item(plain, 90)]
    j = check_batch(ok(batch(w, items), 201), items)
    rf = check_payment(ok(refund(w, "dan", mem[1]["payment_id"], 20), 201), refund_of=mem[1]["payment_id"], visibility="private",
                       settlement_id=None, from_handle="dan", to_handle="bob")
    r = call("POST", "/settlements", tokens["op"], key=sd["key"], body=sd["body"])
    assert r.status_code == 200 and strip2(r.json()) == strip2(sd["resp"]), "the settlement retry must return its original body"
    check_everything(w, build_model(w), random.Random(71), me_points=40, st_points=12)
    total = sum(w.me(h)["total"] for h in w.handles())
    assert total == w1.seeded_total()
