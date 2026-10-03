"""B. POST /correction-batches."""
import json
import random
import time
from fractions import Fraction

import pytest

from lib import (GET, MAX_AMOUNT, POST, US, World, batch, build_model, burst, call, check_batch, check_everything,
                 check_payment, check_revision, code_of, correct, err, fixture, fmt, full_statement, inst, item, k, me_at,
                 now_f, ok, refund, revisions, soft, statement, statuses, user)
from test_r_time import BAD, ago, sp
from test_t_corrections import deep


@pytest.fixture()
def w():
    return World().login_all()


def settle(w, transfers, key=None):
    return ok(POST("/settlements", w.t("op"), {"transfers": transfers}, key=key or k()), 201)


def revs(w, who, pid):
    return ok(revisions(w, who, pid), 200)["revisions"]


# ---------------------------------------------------------------- B8, B9, B10

def test_b8_b9_b10_a_batch_revises_several_payments_at_once(w):
    k1, k2 = k(), k()
    p1 = ok(w.pay("ada", "bob", 100, key=k1, visibility="private"), 201)
    p2 = ok(w.pay("bob", "cy", 300, key=k2), 201)
    rq = w.new_request("dan", "ada", 40)
    p3 = ok(w.pay_request("ada", rq["request_id"]), 201)
    snaps = {h: ok(statement(w, h, limit=200), 200) for h in ("ada", "bob", "cy", "dan")}
    items = [item(p2, 250, reason="less"), item(p1, 160, effective_at=fmt(inst(p1["created_at"]), 330), reason="more"),
             item(p3, 40, effective_at=fmt(inst(p3["created_at"]) - 3600), reason="an hour earlier")]
    key = k()
    t0 = now_f()
    r = batch(w, items, key=key)
    j = check_batch(ok(r, 201), items)
    rec = inst(j["recorded_at"])
    assert t0 - 2 <= rec <= now_f() + 2
    assert rec > max(inst(p["created_at"]) for p in (p1, p2, p3)), "recorded_at is later than every member's previous recorded_at"
    # money: ada -60, bob +60 +50, cy -50, in one step
    assert (w.bal("ada"), w.bal("bob"), w.bal("cy"), w.bal("dan")) == (10000 - 160 - 40, 2500 + 160 - 250, 250, 540)
    w.assert_conserved()
    # each payment's history shows the batch revision, to its two parties only (the operator is not a party)
    for p, parties in ((p1, ("ada", "bob")), (p2, ("bob", "cy")), (p3, ("ada", "dan"))):
        for h in parties:
            rv = revs(w, h, p["payment_id"])
            assert len(rv) == 2 and rv[1] == [x for x in j["revisions"] if x["payment_id"] == p["payment_id"]][0]
            soft(rv[0].get("correction_batch_id", "absent") is None, "revision-1-correction_batch_id-not-null", got=rv[0].get("correction_batch_id", "absent"))
        err(revisions(w, "op", p["payment_id"]), 404, "not_found")
    # originals and receipts never change
    assert ok(w.pay("ada", "bob", 100, key=k1, visibility="private"), 200) == p1
    assert ok(w.pay("bob", "cy", 300, key=k2), 200) == p2
    assert [x for x in w.activity("ada") if x["payment_id"] == p1["payment_id"]] == [p1]
    assert [x["amount"] for x in w.activity("cy")] == [40, 300]
    # new statements reflect the revisions; earlier snapshots page their frozen entries
    s = ok(statement(w, "ada"), 200)
    assert [(e["payment"]["payment_id"], e["delta"], e["revision"]) for e in s["entries"]] == \
        [(p3["payment_id"], -40, 2), (p1["payment_id"], -160, 2)]
    for h in snaps:
        pg = ok(statement(w, h, snapshot=snaps[h]["snapshot"], limit=200), 200)
        assert pg["entries"] == snaps[h]["entries"] and pg["closing_balance"] == snaps[h]["closing_balance"]
    # replay and reuse
    after = deep(w)
    assert ok(batch(w, items, key=key), 200) == j
    raw = json.dumps({"corrections": [{kk: i[kk] for kk in reversed(list(i))} for i in items]}, indent=2)
    assert ok(call("POST", "/correction-batches", w.t("op"), key=key, raw=raw), 200) == j
    err(batch(w, list(reversed(items)), key=key), 409, "idempotency_key_reuse")
    err(batch(w, items[:2], key=key), 409, "idempotency_key_reuse")
    err(batch(w, items, key=key, note="extra"), 409, "idempotency_key_reuse")
    err(call("POST", "/correction-batches", w.t("op"), key=key, body={}), 409, "idempotency_key_reuse")
    assert deep(w) == after
    # a later single correction and a later batch continue the history; the first batch still replays
    j2 = ok(correct(w, "ada", p1["payment_id"], 2, 100, p1["created_at"], "single again"), 201)
    soft(j2.get("correction_batch_id", "absent") is None, "single-correction-correction_batch_id-not-null")
    items2 = [item(p1, 90, expected=3), item(p2, 300, expected=2)]
    j3 = check_batch(ok(batch(w, items2), 201), items2)
    assert j3["correction_batch_id"] != j["correction_batch_id"] and inst(j3["recorded_at"]) > inst(j2["recorded_at"]) > rec
    assert ok(batch(w, items, key=key), 200) == j
    assert [x.get("correction_batch_id") for x in revs(w, "ada", p1["payment_id"])][1::2] == [j["correction_batch_id"], j3["correction_batch_id"]]
    check_everything(w, build_model(w), random.Random(61), me_points=40, st_points=10)


# ---------------------------------------------------------------- B1

def test_b1_operator_and_key_rules(w):
    p = ok(w.pay("ada", "bob", 100), 201)
    body = {"corrections": [item(p, 50)]}
    err(POST("/correction-batches", None, body, key=k()), 401, "unauthenticated")
    err(POST("/correction-batches", "bogus", body, key=k()), 401, "unauthenticated")
    err(POST("/correction-batches", None, body), 401, "unauthenticated")
    for h in ("ada", "bob", "cy"):
        err(POST("/correction-batches", w.t(h), body, key=k()), 403, "forbidden", f"{h} is not an operator")
    err(POST("/correction-batches", w.t("ada"), {"corrections": []}, key=k()), 403, "forbidden")
    r = POST("/correction-batches", w.t("ada"), body)
    err(r, (403, 400), ("forbidden", "missing_idempotency_key"))
    err(POST("/correction-batches", w.t("op"), body), 400, "missing_idempotency_key")
    err(POST("/correction-batches", w.t("op"), body, key=""), 400, "missing_idempotency_key")
    err(POST("/correction-batches", w.t("op"), body, key="x" * 256), 422, "validation_failed")
    err(call("POST", "/correction-batches", w.t("op"), key=k(), raw=b"{nope"), 400, "malformed_request")
    err(call("POST", "/correction-batches", w.t("op"), key=k(), raw=b"[]"), 400, "malformed_request")
    assert len(revs(w, "ada", p["payment_id"])) == 1 and w.bal("ada") == 9900
    ok(POST("/correction-batches", w.t("op"), body, key="y" * 255), 201)
    assert w.bal("ada") == 9950 and w.bal("op") == 1000
    for method in ("GET", "PUT", "DELETE", "PATCH"):
        r = call(method, "/correction-batches", w.t("op"), kind="any")
        assert 400 <= r.status_code < 500, (method, r.status_code)
    r = call("GET", "/correction-batches", w.t("op"), headers={"Accept": "text/html"}, kind="any")
    assert r.status_code < 500
    # a second operator has the same right; a user removed by reset has not
    w2 = World(fixture(ops=["u_op", "u_dan"])).login_all()
    q = ok(w2.pay("ada", "bob", 100), 201)
    check_batch(ok(batch(w2, [item(q, 10)], who="dan"), 201), [item(q, 10)])


# ---------------------------------------------------------------- B2, B3

def test_b2_batch_shape(w):
    ps = [ok(w.pay("ada", "bob", 10 + i), 201) for i in range(33)]
    before = deep(w)
    good = [item(p, 5) for p in ps]
    shapes = {"missing": {}, "null": {"corrections": None}, "string": {"corrections": "x"}, "object": {"corrections": {"0": good[0]}},
              "empty": {"corrections": []}, "33 items": {"corrections": good}, "non-object item": {"corrections": [good[0], 5]},
              "null item": {"corrections": [None]}, "list item": {"corrections": [[good[0]]]},
              "duplicate id": {"corrections": [good[0], good[1], dict(good[0], amount=6)]},
              "duplicate id identical": {"corrections": [good[0], good[0]]}}
    for name, body in shapes.items():
        key = k()
        r = call("POST", "/correction-batches", w.t("op"), key=key, body=body)
        err(r, 422, "validation_failed", name)
    assert deep(w) == before
    # 32 is accepted, with unknown fields at both levels
    items = [dict(i, colour="blue", revision=99) for i in good[:32]]
    j = check_batch(ok(batch(w, items, comment="unknown top-level field", transfers=[]), 201), items)
    assert len(j["revisions"]) == 32 and w.bal("ada") == before["ada"][0]["balance"] + sum(5 + i for i in range(32))
    w.assert_conserved()


ITEM_422 = {"payment_id missing": {"payment_id": "@@DROP@@"}, "expected_revision missing": {"expected_revision": "@@DROP@@"},
            "amount missing": {"amount": "@@DROP@@"}, "effective_at missing": {"effective_at": "@@DROP@@"},
            "reason missing": {"reason": "@@DROP@@"}, "expected_revision 0": {"expected_revision": 0},
            "expected_revision -1": {"expected_revision": -1}, "amount -1": {"amount": -1},
            "amount above the maximum": {"amount": MAX_AMOUNT + 1}, "amount 1.5": {"amount": 1.5}, "amount string": {"amount": "5"},
            "amount true": {"amount": True}, "amount null": {"amount": None}, "reason empty": {"reason": ""},
            "reason 201 characters": {"reason": "r" * 201}, "effective_at naive": {"effective_at": "2026-01-05T10:00:00"},
            "effective_at empty": {"effective_at": ""}, "effective_at garbage": {"effective_at": "last week"},
            "effective_at in the future": {"effective_at": "FUTURE"}}
ITEM_TYPE = {"payment_id number": {"payment_id": 5}, "payment_id null": {"payment_id": None},
             "expected_revision string": {"expected_revision": "1"}, "expected_revision 1.5": {"expected_revision": 1.5},
             "reason number": {"reason": 5}, "effective_at number": {"effective_at": 5}, "effective_at null": {"effective_at": None}}


def mutate(i, over):
    out = dict(i)
    for kk, v in over.items():
        if v == "@@DROP@@":
            out.pop(kk)
        elif v == "FUTURE":
            out[kk] = fmt(now_f() + 30)
        else:
            out[kk] = v
    return out


@pytest.mark.parametrize("name", sorted(ITEM_422) + sorted(ITEM_TYPE))
@pytest.mark.parametrize("position", [0, 1])
def test_b3_item_validation(w, name, position):
    p1, p2 = ok(w.pay("ada", "bob", 100), 201), ok(w.pay("bob", "cy", 100), 201)
    before = deep(w)
    over = ITEM_422.get(name) or ITEM_TYPE[name]
    items = [item(p1, 50), item(p2, 50)]
    items[position] = mutate(items[position], over)
    key = k()
    r = call("POST", "/correction-batches", w.t("op"), key=key, body={"corrections": items})
    if name in ITEM_422:
        err(r, 422, "validation_failed", name)
    else:
        err(r, (400, 422), ("malformed_request", "validation_failed"), name)
        soft(r.status_code == 422, "batch-item-wrong-type-400", case=name)
    assert deep(w) == before, "a rejected batch leaves everything unchanged"
    good = [item(p1, 50), item(p2, 50)]
    check_batch(ok(batch(w, good, key=key), 201), good)             # the key stayed reusable


def test_b3_effective_at_grammar_and_valid_boundaries(w):
    ps = [ok(w.pay("ada", "bob", 100), 201) for _ in range(6)]
    wrong = []
    for value in BAD:
        r = batch(w, [item(ps[0], 50, effective_at=value)])
        if r.status_code != 422 or code_of(r) != "validation_failed":
            wrong.append((value, r.status_code, code_of(r)))
    assert not wrong, f"effective_at in a batch item: expected 422 validation_failed for {wrong}"
    items = [item(ps[0], 0), item(ps[1], MAX_AMOUNT if False else 100, reason="r" * 200),
             item(ps[2], 100, effective_at=fmt(now_f() - 2)), item(ps[3], 7, effective_at="2001-02-03T04:05:06Z"),
             item(ps[4], 100, effective_at=fmt(inst(ps[4]["created_at"]) - Fraction(123456789, 10 ** 9), -480))]
    check_batch(ok(batch(w, items), 201), items)
    raw = json.dumps({"corrections": [item(ps[5], "@@A@@")]}).replace('"@@A@@"', "6e1")
    j = ok(call("POST", "/correction-batches", w.t("op"), key=k(), raw=raw), 201)
    assert j["revisions"][0]["amount"] == 60 and type(j["revisions"][0]["amount"]) is int
    w.assert_conserved()
    check_everything(w, build_model(w), random.Random(62), me_points=30, st_points=8)


def test_b3_b4_unknown_stale_linked_and_refunded_items(w):
    p = ok(w.pay("ada", "bob", 100), 201)
    q = ok(w.pay("bob", "cy", 100, visibility="private"), 201)
    a = w.new_auth("ada", "dan", 200)
    cap = ok(w.capture("dan", a["authorization_id"], body={"amount": 150}), 201)
    rf = ok(refund(w, "bob", p["payment_id"], 30), 201)
    before = deep(w)
    fake = {"payment_id": "p_nope", "created_at": p["created_at"]}
    err(batch(w, [item(q, 50), item(fake, 50)]), 404, "not_found")
    err(batch(w, [item(q, 50), item(p, 50, expected=2)]), 409, "stale_revision")
    r = batch(w, [item(q, 50), item(p, 50, expected=7)])
    err(r, (409, 422), ("stale_revision", "validation_failed"))
    err(batch(w, [item(q, 50), item(cap, 50)]), 422, "linked_payment_immutable")
    err(batch(w, [item(q, 50), item(rf, 10)]), 422, "linked_payment_immutable")
    err(batch(w, [item(q, 50), item(rf, 30)]), 422, "linked_payment_immutable", "an unchanged amount is still a correction")
    err(batch(w, [item(q, 50), item(p, 29)]), 422, "refund_exceeds_payment")
    assert deep(w) == before
    # the operator is not a party to any of these and may correct them, also a private one, and exactly to the refunded amount
    items = [item(q, 50), item(p, 30)]
    check_batch(ok(batch(w, items), 201), items)
    assert (w.bal("ada"), w.bal("bob"), w.bal("cy")) == (10000 - 150, 2500 - 50, 50)
    err(GET(f"/payments/{q['payment_id']}/revisions", w.t("op")), 404, "not_found")
    assert not [x for x in w.activity("op") if x["payment_id"] == q["payment_id"]], "the operator still cannot see the private payment"
    w.assert_conserved()


# ---------------------------------------------------------------- B5, B12

def test_b5_b12_settlement_members_need_the_whole_settlement(w):
    skey = k()
    st = settle(w, [{"from_handle": "ada", "to_handle": "bob", "amount": 100, "note": "a"},
                    {"from_handle": "bob", "to_handle": "cy", "amount": 60, "visibility": "private"},
                    {"from_handle": "cy", "to_handle": "dan", "amount": 20}], key=skey)
    st2 = settle(w, [{"from_handle": "dan", "to_handle": "ada", "amount": 5}, {"from_handle": "ada", "to_handle": "cy", "amount": 7}])
    plain = ok(w.pay("ada", "bob", 9), 201)
    m = st["payments"]
    n = st2["payments"]
    t = st["committed_at"]
    before = deep(w)
    err(batch(w, [item(m[0], 50)]), 422, "incomplete_settlement")
    err(batch(w, [item(m[0], 50), item(m[1], 60)]), 422, "incomplete_settlement")
    err(batch(w, [item(m[2], 20), item(plain, 5), item(m[0], 100)]), 422, "incomplete_settlement")
    err(batch(w, [item(x, x["amount"]) for x in m] + [item(n[0], 5)]), 422, "incomplete_settlement", "the second settlement is incomplete")
    # complete, but the members' effective instants differ
    r = batch(w, [item(m[0], 50), item(m[1], 60), item(m[2], 20, effective_at=fmt(inst(t) - 1))])
    err(r, 422, "validation_failed", "members of one settlement must share the effective instant")
    r = batch(w, [item(m[0], 50, effective_at=fmt(inst(t) - US)), item(m[1], 60), item(m[2], 20)])
    err(r, 422, "validation_failed")
    assert deep(w) == before
    # the single endpoint still refuses members
    err(correct(w, "ada", m[0]["payment_id"], 1, 50, t), 422, "linked_payment_immutable")
    # complete, same instant in three spellings, mixed with an ordinary payment and a second complete settlement
    e = inst(t) - 3600
    items = [item(m[2], 20, effective_at=fmt(e, 330)), item(plain, 5), item(m[0], 50, effective_at=fmt(e)),
             item(n[1], 7, effective_at=n[1]["created_at"]), item(m[1], 60, effective_at=fmt(e, -480)),
             item(n[0], 4, effective_at=fmt(inst(n[0]["created_at"]), 60))]
    j = check_batch(ok(batch(w, items), 201), items)
    assert (w.bal("ada"), w.bal("bob"), w.bal("cy"), w.bal("dan")) == \
        (10000 - 50 + 4 - 7 - 5, 2500 + 50 - 60 + 5, 60 - 20 + 7, 500 + 20 - 4)
    w.assert_conserved()
    # membership and receipts are unchanged; every member shows the batch revision to its parties
    assert ok(POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100, "note": "a"},
                                                             {"from_handle": "bob", "to_handle": "cy", "amount": 60, "visibility": "private"},
                                                             {"from_handle": "cy", "to_handle": "dan", "amount": 20}]}, key=skey), 200) == st
    for x, parties in ((m[0], ("ada", "bob")), (m[1], ("bob", "cy")), (m[2], ("cy", "dan"))):
        for h in parties:
            rv = revs(w, h, x["payment_id"])
            assert len(rv) == 2 and rv[1]["correction_batch_id"] == j["correction_batch_id"] and inst(rv[1]["effective_at"]) == e
        feed = [y for y in w.activity(parties[0]) if y["payment_id"] == x["payment_id"]]
        assert feed == [x] and feed[0]["settlement_id"] == st["settlement_id"]
    # correcting again still needs all three; a refund of a member is not a member
    rf = check_payment(ok(refund(w, "bob", m[0]["payment_id"], 20), 201), refund_of=m[0]["payment_id"], settlement_id=None)
    err(batch(w, [item(m[0], 50, expected=2), item(m[1], 60, expected=2)]), 422, "incomplete_settlement")
    err(batch(w, [item(m[0], 19, expected=2), item(m[1], 60, expected=2), item(m[2], 20, expected=2)]), 422, "refund_exceeds_payment")
    items3 = [item(m[0], 20, expected=2, effective_at=fmt(e)), item(m[1], 60, expected=2, effective_at=fmt(e)),
              item(m[2], 20, expected=2, effective_at=fmt(e))]
    check_batch(ok(batch(w, items3), 201), items3)
    err(batch(w, items3 + [item(rf, 20)]), (409, 422))
    w.assert_conserved()
    check_everything(w, build_model(w), random.Random(63), me_points=40, st_points=10)


# ---------------------------------------------------------------- B6, B7

def test_b6_item_errors_decide_in_input_order(w):
    p = [ok(w.pay("ada", "bob", 100), 201) for _ in range(4)]
    a = w.new_auth("ada", "dan", 200)
    cap = ok(w.capture("dan", a["authorization_id"], body={"amount": 150}), 201)
    ok(refund(w, "bob", p[3]["payment_id"], 60), 201)
    fake = {"payment_id": "p_nope", "created_at": p[0]["created_at"]}
    bad = {"invalid": (lambda: item(p[0], -1), 422, "validation_failed"), "unknown": (lambda: item(fake, 5), 404, "not_found"),
           "linked": (lambda: item(cap, 5), 422, "linked_payment_immutable"),
           "stale": (lambda: item(p[2], 5, expected=2), 409, "stale_revision"),
           "refunded": (lambda: item(p[3], 59), 422, "refund_exceeds_payment")}
    before = deep(w)
    names = sorted(bad)
    for first in names:
        for second in names:
            if first == second or {first, second} == {"invalid"}:
                continue
            i1, i2 = bad[first][0](), bad[second][0]()
            r = batch(w, [item(p[1], 50), i1, i2])
            if first == "invalid" or second != "invalid":
                err(r, bad[first][1], bad[first][2], f"first bad item {first}, then {second}")
            else:
                # a malformed later item against an earlier well-formed but refused one: the map validates item by item
                err(r, (bad[first][1], 422), (bad[first][2], "validation_failed"), f"{first} then invalid")
                soft(code_of(r) == bad[first][2], "batch-validates-all-items-before-other-item-errors", first=first)
    assert deep(w) == before


def test_b6_precedence_between_the_phases():
    """item error -> settlement completeness -> current funds -> history."""
    t1, t2 = ago(5), ago(4)
    users = [user("ada", 0), user("bob", 0), user("cy", 100), user("dan", 500), user("op", 1000)]
    w = World(fixture(users=users, payments=[sp("p_a", "ada", "bob", 100, fmt(t1)), sp("p_b", "bob", "cy", 100, fmt(t2))])).login_all()
    st = ok(POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "dan", "to_handle": "cy", "amount": 10},
                                                           {"from_handle": "cy", "to_handle": "dan", "amount": 5}]}, key=k()), 201)
    m = st["payments"]
    A = {"payment_id": "p_a", "created_at": fmt(t1)}
    B = {"payment_id": "p_b", "created_at": fmt(t2)}
    before = deep(w, ("ada", "bob", "cy", "dan", "op"))
    stale = item(B, 100, expected=3)
    incomplete = item(m[0], 10)
    unaffordable = item(A, 60)                           # bob would have to return 40 and has nothing
    overdraft = item(B, 100, effective_at=fmt(t1 - 86400))   # bob pays out a day before the funding
    # each alone
    err(batch(w, [stale]), 409, "stale_revision")
    err(batch(w, [incomplete]), 422, "incomplete_settlement")
    err(batch(w, [unaffordable]), 409, "insufficient_funds")
    err(batch(w, [overdraft]), 409, "historical_overdraft")
    # adjacent pairs, in both input orders: the earlier phase decides
    for x, y, status, code in ((incomplete, stale, 409, "stale_revision"), (stale, incomplete, 409, "stale_revision")):
        err(batch(w, [x, y]), status, code, "an item error comes before settlement completeness")
    for order in ([incomplete, unaffordable], [unaffordable, incomplete]):
        err(batch(w, order), 422, "incomplete_settlement", "completeness comes before current funds")
    D = ok(w.pay("dan", "ada", 1), 201)
    before = deep(w, ("ada", "bob", "cy", "dan", "op"))
    od2 = item(A, 100, effective_at=fmt(t2 + 3600))      # the funding moved after bob's spending: history, affordable today
    need = item(D, 400)                                  # dan would pay ada 399 more; dan has 500 - 10 + 5 - 1 = 494: affordable
    short = item(D, 600)                                 # dan would need 599: not affordable today
    for order in ([short, od2], [od2, short]):
        err(batch(w, order), 409, "insufficient_funds", "current funds come before history")
    err(batch(w, [need, od2]), 409, "historical_overdraft")
    for order in ([incomplete, od2], [od2, incomplete]):
        err(batch(w, order), 422, "incomplete_settlement")
    err(batch(w, [stale, od2]), 409, "stale_revision")
    err(batch(w, [od2, item({"payment_id": "p_nope", "created_at": fmt(t1)}, 1)]), 404, "not_found")
    assert deep(w, ("ada", "bob", "cy", "dan", "op")) == before
    ok(batch(w, [need]), 201)
    w.assert_conserved()


def test_b6_affordability_is_the_combined_effect(w):
    """Two payments in opposite directions between two empty wallets: each increase alone is unaffordable, together they net out."""
    w = World(fixture(users=[user("ada", 100), user("bob", 100), user("op", 0)])).login_all()
    p1 = ok(w.pay("ada", "bob", 100), 201)
    p2 = ok(w.pay("bob", "ada", 200), 201)               # ada 200, bob 0
    ok(w.pay("ada", "op", 200), 201)                     # ada 0, bob 0
    err(batch(w, [item(p1, 300)]), 409, "insufficient_funds")
    err(batch(w, [item(p2, 400)]), 409, "insufficient_funds")
    err(correct(w, "ada", p1["payment_id"], 1, 300, p1["created_at"]), 409, "insufficient_funds")
    # together: ada pays 200 more on p1 and receives 200 more on p2; same effective instant so history nets too
    e = p2["created_at"]
    items = [item(p1, 300, effective_at=e), item(p2, 400, effective_at=e)]
    j = check_batch(ok(batch(w, items), 201), items)
    assert (w.bal("ada"), w.bal("bob")) == (0, 0)
    # combined shortfall: one item alone is affordable for bob, both together are not
    w = World(fixture(users=[user("ada", 1000), user("bob", 50), user("cy", 0), user("op", 0)])).login_all()
    q1 = ok(w.pay("ada", "bob", 100), 201)
    q2 = ok(w.pay("ada", "bob", 100), 201)               # bob 250
    ok(w.pay("bob", "cy", 190), 201)                     # bob 60
    ok(batch(w, [item(q1, 60)]), 201)                    # bob returns 40 -> 20
    err(batch(w, [item(q1, 50, expected=2), item(q2, 85)]), 409, "insufficient_funds", "10 + 15 against 20 available")
    items = [item(q1, 50, expected=2), item(q2, 90)]
    check_batch(ok(batch(w, items), 201), items)
    assert w.bal("bob") == 0
    w.assert_conserved()
    check_everything(w, build_model(w), random.Random(64), me_points=30, st_points=8)


def test_b6_history_is_checked_for_the_combined_batch():
    t1, t2 = ago(5), ago(4)
    users = [user("ada", 0), user("bob", 0), user("cy", 100), user("op", 0)]
    w = World(fixture(users=users, payments=[sp("p_a", "ada", "bob", 100, fmt(t1)), sp("p_b", "bob", "cy", 100, fmt(t2))])).login_all()
    A = {"payment_id": "p_a", "created_at": fmt(t1)}
    B = {"payment_id": "p_b", "created_at": fmt(t2)}
    before = deep(w, ("ada", "bob", "cy"))
    later = fmt(t2 + 86400)
    err(batch(w, [item(A, 100, effective_at=later)]), 409, "historical_overdraft", "the funding alone moved after the spending")
    err(batch(w, [item(B, 100, effective_at=fmt(t1 - 86400))]), 409, "historical_overdraft")
    assert deep(w, ("ada", "bob", "cy")) == before
    # both moved together keep bob whole at every boundary
    items = [item(A, 100, effective_at=later), item(B, 100, effective_at=later)]
    check_batch(ok(batch(w, items), 201), items)
    assert ok(me_at(w, "bob", fmt(t2)), 200)["balance"] == 0 and ok(me_at(w, "cy", fmt(t2)), 200)["balance"] == 0
    assert ok(me_at(w, "cy", later), 200)["balance"] == 100 and ok(me_at(w, "ada", fmt(t2)), 200)["balance"] == 100
    check_everything(w, build_model(w), random.Random(65), me_points=40, st_points=10)


# ---------------------------------------------------------------- B11

def test_b11_overlapping_batches_and_single_corrections_race(w):
    users = [user(h, 100000) for h in ("ada", "bob", "cy", "dan")] + [user("op", 0)]
    w = World(fixture(users=users)).login_all()
    ps = [ok(w.pay(("ada", "bob", "cy", "dan")[i % 4], ("bob", "cy", "dan", "ada")[i % 4], 100 + i), 201) for i in range(12)]
    st = ok(POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10},
                                                           {"from_handle": "bob", "to_handle": "cy", "amount": 10}]}, key=k()), 201)
    rng = random.Random(8)
    for rnd in range(3):
        m = build_model(w)
        latest = {pid: len(p["revs"]) for pid, p in m.pay.items()}
        sets, fns = [], []
        for i in range(30):                                   # batches over random overlapping subsets
            chosen = rng.sample(ps, rng.randint(1, 4))
            body = [item(p, 50 + i + rnd, expected=latest[p["payment_id"]]) for p in chosen]
            if i % 6 == 0:
                body += [item(x, 10 + rnd, expected=latest[x["payment_id"]]) for x in st["payments"]]
                chosen = chosen + st["payments"]
            sets.append({p["payment_id"] for p in chosen})
            fns.append(lambda body=body: batch(w, body))
        for i in range(20):                                   # single corrections by the senders
            p = ps[i % 12]
            sets.append({p["payment_id"]})
            fns.append(lambda p=p, i=i: correct(w, p["from_handle"], p["payment_id"], latest[p["payment_id"]], 60 + i,
                                                p["created_at"], "single racer"))
        rs = burst(fns)
        won = [s for r, s in zip(rs, sets) if r.status_code == 201]
        for r in rs:
            assert r.status_code in (201, 409), r.text[:200]
            if r.status_code == 409:
                assert code_of(r) == "stale_revision", r.text[:200]
        assert won, "no correction won at all"
        for i in range(len(won)):
            for j2 in range(i + 1, len(won)):
                assert not (won[i] & won[j2]), f"round {rnd}: two corrections sharing an expected revision both succeeded: {won[i] & won[j2]}"
        m2 = build_model(w)
        touched = set().union(*won)
        for pid, p in m2.pay.items():
            assert len(p["revs"]) == latest.get(pid, 1) + (1 if pid in touched else 0), f"{pid}: {len(p['revs'])} revisions"
        # every loser overlapped a winner (a batch that lost to nobody would be an unexplained refusal)
        for r, s in zip(rs, sets):
            if r.status_code == 409:
                assert s & touched, "a correction was refused as stale although none of its payments was revised"
        assert m2.overdraft(list(m2.opening), now_f()) is None
        w.assert_conserved()
        check_everything(w, m2, rng, me_points=20, st_points=5)


def test_b7_b10_fifty_identical_batches_and_a_rejected_one(w):
    p1, p2 = ok(w.pay("ada", "bob", 100), 201), ok(w.pay("bob", "cy", 100), 201)
    items = [item(p1, 40), item(p2, 70)]
    key = k()
    rs = burst([lambda: batch(w, items, key=key) for _ in range(50)])
    assert statuses(rs) == {201: 1, 200: 49}, statuses(rs)
    assert all(r.json() == rs[0].json() for r in rs)
    assert len(revs(w, "ada", p1["payment_id"])) == 2 and (w.bal("ada"), w.bal("bob"), w.bal("cy")) == (9960, 2500 + 40 - 70, 70)
    # failed batches claim no key, whatever the reason
    cases = ((lambda cur: [item(p1, 10, expected=cur - 1)], 409, "stale_revision"),
             (lambda cur: [item(p1, 10, expected=cur), item(p2, 10 ** 10, expected=2)], 422, "validation_failed"),
             (lambda cur: [item(p1, 10 ** 9, expected=cur)], 409, "insufficient_funds"))
    for make, status, code in cases:
        key2 = k()
        before = deep(w)
        cur = len(revs(w, "ada", p1["payment_id"]))
        err(batch(w, make(cur), key=key2), status, code)
        assert deep(w) == before
        good = [item(p1, 41 + cur, expected=cur)]
        check_batch(ok(batch(w, good, key=key2), 201), good)
