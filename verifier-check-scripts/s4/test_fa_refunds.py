"""F, G. POST /payments/{id}/refunds, and single corrections next to refunds."""
import json
import random
import time

import pytest

from lib import (GET, MAX_AMOUNT, POST, US, World, batch, build_model, burst, call, check_auth, check_everything,
                 check_payment, check_revision, code_of, correct, err, fixture, fmt, full_statement, inst, item, k, me_at,
                 now_f, ok, refund, revisions, soft, statement, statuses, user)
from test_t_corrections import deep


@pytest.fixture()
def w():
    return World().login_all()


def settle(w, transfers, key=None):
    return ok(POST("/settlements", w.t("op"), {"transfers": transfers}, key=key or k()), 201)


# ---------------------------------------------------------------- F5, F8, F9

def test_f5_f8_f9_a_refund_is_a_linked_payment_in_the_opposite_direction(w):
    pkey = k()
    p = check_payment(ok(w.pay("ada", "bob", 1000, key=pkey, note="dinner 🍝", visibility="private"), 201), refund_of=None)
    key = k()
    r = refund(w, "bob", p["payment_id"], 200, key=key)
    j = check_payment(ok(r, 201), refund_of=p["payment_id"], from_handle="bob", to_handle="ada", from_user_id="u_bob",
                      to_user_id="u_ada", amount=200, request_id=None, authorization_id=None, settlement_id=None,
                      note="dinner 🍝", visibility="private", currency="EUR")
    assert j["payment_id"] != p["payment_id"] and inst(j["created_at"]) > inst(p["created_at"])
    assert (w.wallet("ada")["total"], w.wallet("bob")["total"]) == (9200, 3300)
    assert ok(refund(w, "bob", p["payment_id"], 200, key=key), 200) == j, "a replay returns the original body"
    err(refund(w, "bob", p["payment_id"], 201, key=key), 409, "idempotency_key_reuse")
    assert (w.wallet("ada")["total"], w.wallet("bob")["total"]) == (9200, 3300)
    # the original payment and its receipt are unchanged; both are ordinary feed items for their parties only
    assert ok(w.pay("ada", "bob", 1000, key=pkey, note="dinner 🍝", visibility="private"), 200) == p
    for h in ("ada", "bob"):
        assert w.activity(h) == [j, p]
    assert w.activity("cy") == []
    # ledger: revision 1, statements of both parties, historical views
    for h in ("ada", "bob"):
        rv = ok(revisions(w, h, j["payment_id"]), 200)["revisions"]
        assert len(rv) == 1
        check_revision(rv[0], payment_id=j["payment_id"], revision=1, amount=200, reason="")
        assert inst(rv[0]["effective_at"]) == inst(rv[0]["recorded_at"]) == inst(j["created_at"])
    err(revisions(w, "cy", j["payment_id"]), 404, "not_found")
    err(revisions(w, "op", j["payment_id"]), 404, "not_found")
    s = ok(statement(w, "ada"), 200)
    assert [e["payment"] for e in s["entries"]] == [p, j] and [e["delta"] for e in s["entries"]] == [-1000, 200]
    assert s["closing_balance"] == 9200
    s = ok(statement(w, "bob"), 200)
    assert [e["delta"] for e in s["entries"]] == [1000, -200]
    tj = inst(j["created_at"])
    assert ok(me_at(w, "ada", fmt(tj - US)), 200)["balance"] == 9000 and ok(me_at(w, "ada", fmt(tj)), 200)["balance"] == 9200
    assert ok(me_at(w, "bob", None, fmt(tj - US)), 200)["balance"] == 3500
    # a public payment's refund is public
    p2 = ok(w.pay("ada", "bob", 10), 201)
    j2 = check_payment(ok(refund(w, "bob", p2["payment_id"], 10), 201), refund_of=p2["payment_id"], visibility="public", note="")
    assert j2 in w.activity("cy")
    for x in w.activity("cy"):
        check_payment(x)
    check_everything(w, build_model(w), random.Random(51), me_points=30, st_points=8)


# ---------------------------------------------------------------- F1, F3

def test_f1_who_may_refund_and_key_rules(w):
    p = ok(w.pay("ada", "bob", 1000, visibility="private"), 201)
    path = f"/payments/{p['payment_id']}/refunds"
    body = {"amount": 100}
    err(POST(path, None, body, key=k()), 401, "unauthenticated")
    err(POST(path, "bogus", body, key=k()), 401, "unauthenticated")
    err(POST(path, w.t("ada"), body, key=k()), 403, "forbidden", "the sender")
    err(POST(path, w.t("cy"), body, key=k()), 403, "forbidden", "a third party")
    err(POST(path, w.t("op"), body, key=k()), 403, "forbidden", "an operator who is not the receiver")
    err(POST("/payments/p_nope/refunds", w.t("bob"), body, key=k()), 404, "not_found")
    err(POST(path, w.t("bob"), body), 400, "missing_idempotency_key")
    err(POST(path, w.t("bob"), body, key=""), 400, "missing_idempotency_key")
    err(POST(path, w.t("bob"), body, key="x" * 256), 422, "validation_failed")
    err(call("POST", path, w.t("bob"), key=k(), raw=b"{nope"), 400, "malformed_request")
    err(call("POST", path, w.t("bob"), key=k(), raw=b"[1]"), 400, "malformed_request")
    r = call("POST", path, w.t("bob"), key=k())
    err(r, (400, 422), ("malformed_request", "validation_failed"), "no body")
    assert (w.bal("ada"), w.bal("bob")) == (9000, 3500) and len(w.activity("ada")) == 1
    ok(POST(path, w.t("bob"), {**body, "colour": "blue", "refund_of": "x", "to_handle": "cy"}, key="y" * 255), 201)
    assert (w.bal("ada"), w.bal("bob"), w.bal("cy")) == (9100, 3400, 0), "unknown fields are ignored"
    for method in ("GET", "PUT", "DELETE", "PATCH"):
        r = call(method, path, w.t("bob"), kind="any")
        assert 400 <= r.status_code < 500, (method, r.status_code)
    for odd in ("a/b", "ünï-😀", "x" * 300, "%00", ""):
        r = call("POST", f"/payments/{odd}/refunds", w.t("bob"), key=k(), body=body, kind="any")
        assert 400 <= r.status_code < 500, f"{odd!r}: {r.status_code}"


BAD_AMOUNTS = {"missing": "@@DROP@@", "zero": "0", "negative": "-1", "above the maximum": str(MAX_AMOUNT + 1), "fraction": "1.5",
               "string": '"100"', "true": "true", "null": "null", "list": "[100]", "object": "{}", "1e30": "1e30",
               "huge": "1" + "0" * 400, "tiny fraction": "100.0000000000000000000001"}


@pytest.mark.parametrize("name", sorted(BAD_AMOUNTS))
def test_f3_invalid_amount_is_422(w, name):
    p = ok(w.pay("ada", "bob", 1000), 201)
    before = deep(w)
    raw = "{}" if BAD_AMOUNTS[name] == "@@DROP@@" else '{"amount": %s}' % BAD_AMOUNTS[name]
    key = k()
    err(call("POST", f"/payments/{p['payment_id']}/refunds", w.t("bob"), key=key, raw=raw), 422, "validation_failed", name)
    assert deep(w) == before
    ok(refund(w, "bob", p["payment_id"], 100, key=key), 201)           # the failed attempt claimed no key


def test_f3_integral_spellings_are_accepted(w):
    p = ok(w.pay("ada", "bob", 1000), 201)
    for raw, amt in (('{"amount": 100.0}', 100), ('{"amount": 1e2}', 100), ('{"amount": 1}', 1)):
        j = ok(call("POST", f"/payments/{p['payment_id']}/refunds", w.t("bob"), key=k(), raw=raw), 201)
        assert j["amount"] == amt and type(j["amount"]) is int
    assert w.bal("bob") == 3500 - 201


# ---------------------------------------------------------------- F2, F7

def test_f2_f7_targets_request_payment_capture_and_settlement_member(w):
    rq = w.new_request("bob", "ada", 400, note="taxi")
    rkey = k()
    pr = ok(w.pay_request("ada", rq["request_id"], key=rkey, body={"visibility": "private"}), 201)
    a = w.new_auth("ada", "dan", 900, note="deposit")
    ckey = k()
    cap = ok(w.capture("dan", a["authorization_id"], key=ckey, body={"amount": 600}), 201)        # final: 300 released
    skey = k()
    st = settle(w, [{"from_handle": "ada", "to_handle": "cy", "amount": 50, "note": "s1"},
                    {"from_handle": "cy", "to_handle": "bob", "amount": 20, "visibility": "private"}], key=skey)
    held_before = w.wallet("ada")["held"]
    # request payment
    j = check_payment(ok(refund(w, "bob", pr["payment_id"], 150), 201), refund_of=pr["payment_id"], request_id=None,
                      authorization_id=None, settlement_id=None, note="taxi", visibility="private", from_handle="bob", to_handle="ada")
    q = [x for x in w.requests("ada") if x["request_id"] == rq["request_id"]][0]
    assert q["status"] == "paid" and q["payment_id"] == pr["payment_id"] and q["amount"] == 400, "a refund never reopens a request"
    err(w.pay_request("ada", rq["request_id"]), 409, "request_not_pending")
    assert ok(w.pay_request("ada", rq["request_id"], key=rkey, body={"visibility": "private"}), 200) == pr
    # capture
    j2 = check_payment(ok(refund(w, "dan", cap["payment_id"], 600), 201), refund_of=cap["payment_id"], authorization_id=None,
                       request_id=None, settlement_id=None, note="deposit", from_handle="dan", to_handle="ada", amount=600)
    au = check_auth(w.auth("ada", a["authorization_id"]), status="captured", captured_amount=600, remaining_amount=0)
    assert au["payment_ids"] == [cap["payment_id"]], "a refund never reopens an authorisation"
    assert w.wallet("ada")["held"] == held_before == 0, "a refund never restores a released hold"
    err(w.capture("dan", a["authorization_id"], body={"amount": 1}), 409, "authorization_not_open")
    assert ok(w.capture("dan", a["authorization_id"], key=ckey, body={"amount": 600}), 200) == cap
    # settlement member
    m0, m1 = st["payments"]
    j3 = check_payment(ok(refund(w, "cy", m0["payment_id"], 30), 201), refund_of=m0["payment_id"], settlement_id=None,
                       from_handle="cy", to_handle="ada", note="s1")
    assert ok(POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 50, "note": "s1"},
                                                             {"from_handle": "cy", "to_handle": "bob", "amount": 20, "visibility": "private"}]},
                   key=skey), 200) == st, "refunds never change settlement membership or its receipt"
    feed = {x["payment_id"]: x for x in w.activity("ada") + w.activity("bob") + w.activity("cy")}
    assert [pid for pid, x in feed.items() if x["settlement_id"] == st["settlement_id"]].__len__() == 2
    assert all(x["refund_of"] is None for pid, x in feed.items() if pid not in (j["payment_id"], j2["payment_id"], j3["payment_id"]))
    # refunds of refunds
    for who, ref in (("ada", j), ("ada", j2), ("ada", j3)):
        err(refund(w, who, ref["payment_id"], 1), 422, "invalid_refund_target", "the receiver of a refund refunding it")
    r = refund(w, "bob", j["payment_id"], 1)
    err(r, (422, 403), ("invalid_refund_target", "forbidden"))
    soft(code_of(r) == "invalid_refund_target", "refund-of-refund-by-non-receiver-403")
    r = refund(w, "op", j3["payment_id"], 1)
    err(r, (422, 403), ("invalid_refund_target", "forbidden"))
    # refunds cannot be corrected, by anyone, by either route
    err(correct(w, "bob", j["payment_id"], 1, 100, j["created_at"]), 422, "linked_payment_immutable")
    err(correct(w, "dan", j2["payment_id"], 1, 0, j2["created_at"]), 422, "linked_payment_immutable")
    err(batch(w, [item(j, 100)]), 422, "linked_payment_immutable")
    err(batch(w, [item(cap, 100)]), 422, "linked_payment_immutable")
    err(correct(w, "ada", cap["payment_id"], 1, 100, cap["created_at"]), 422, "linked_payment_immutable")
    err(correct(w, "ada", m0["payment_id"], 1, 40, m0["created_at"]), 422, "linked_payment_immutable")
    w.assert_conserved()
    check_everything(w, build_model(w), random.Random(52), me_points=30, st_points=8)


# ---------------------------------------------------------------- F4, G2

def test_f4_cumulative_refunds_against_the_corrected_amount(w):
    p = ok(w.pay("ada", "bob", 1000), 201)
    pid = p["payment_id"]
    ok(refund(w, "bob", pid, 300), 201)
    before = deep(w)
    key = k()
    err(refund(w, "bob", pid, 701, key=key), 422, "refund_exceeds_payment")
    r = refund(w, "bob", pid, MAX_AMOUNT)
    err(r, (422, 409), ("refund_exceeds_payment", "insufficient_funds"))
    soft(code_of(r) == "refund_exceeds_payment", "refund-limit-and-funds-order", code=code_of(r))
    assert deep(w) == before
    ok(refund(w, "bob", pid, 700, key=key), 201)                       # exactly the remainder; the key was not claimed
    err(refund(w, "bob", pid, 1), 422, "refund_exceeds_payment")
    assert (w.bal("ada"), w.bal("bob")) == (10000, 2500)
    # the limit is the current corrected amount
    p2 = ok(w.pay("ada", "bob", 1000), 201)
    ok(correct(w, "ada", p2["payment_id"], 1, 500, p2["created_at"], "it was 500"), 201)
    err(refund(w, "bob", p2["payment_id"], 501), 422, "refund_exceeds_payment")
    ok(refund(w, "bob", p2["payment_id"], 200), 201)
    ok(correct(w, "ada", p2["payment_id"], 2, 800, p2["created_at"], "it was 800"), 201)
    err(refund(w, "bob", p2["payment_id"], 601), 422, "refund_exceeds_payment")
    ok(refund(w, "bob", p2["payment_id"], 600), 201)
    # a fully reversed payment cannot be refunded at all
    p3 = ok(w.pay("ada", "bob", 100), 201)
    ok(correct(w, "ada", p3["payment_id"], 1, 0, p3["created_at"], "reversed"), 201)
    err(refund(w, "bob", p3["payment_id"], 1), 422, "refund_exceeds_payment")
    w.assert_conserved()
    check_everything(w, build_model(w), random.Random(53), me_points=30, st_points=8)


def test_g2_a_correction_cannot_go_below_the_refunded_amount(w):
    p = ok(w.pay("ada", "bob", 1000), 201)
    pid = p["payment_id"]
    ok(refund(w, "bob", pid, 300), 201)
    before = deep(w)
    key = k()
    err(correct(w, "ada", pid, 1, 299, p["created_at"], key=key), 422, "refund_exceeds_payment")
    err(correct(w, "ada", pid, 1, 0, p["created_at"]), 422, "refund_exceeds_payment")
    err(batch(w, [item(p, 299)]), 422, "refund_exceeds_payment")
    assert deep(w) == before and len(ok(revisions(w, "ada", pid), 200)["revisions"]) == 1
    j = ok(correct(w, "ada", pid, 1, 300, p["created_at"], "equal to the refunded amount", key=key), 201)
    assert (w.bal("ada"), w.bal("bob")) == (10000, 2500)
    err(refund(w, "bob", pid, 1), 422, "refund_exceeds_payment")
    ok(correct(w, "ada", pid, 2, 5000, p["created_at"], "more"), 201)
    ok(refund(w, "bob", pid, 4700), 201)
    err(correct(w, "ada", pid, 3, 4999, p["created_at"]), 422, "refund_exceeds_payment")
    # stale and refund_exceeds together: the map puts the stale revision first
    r = correct(w, "ada", pid, 1, 0, p["created_at"])
    err(r, (409, 422), ("stale_revision", "refund_exceeds_payment"))
    soft(code_of(r) == "stale_revision", "stale-and-refund_exceeds-order", code=code_of(r))
    w.assert_conserved()
    check_everything(w, build_model(w), random.Random(54), me_points=30, st_points=8)


# ---------------------------------------------------------------- F6, G3

def test_f6_refunds_come_out_of_available_funds(w):
    p = ok(w.pay("ada", "bob", 1000), 201)                 # bob 3500
    ok(w.pay("bob", "cy", 3000), 201)                      # bob 500
    hold = w.new_auth("bob", "dan", 400)                   # bob available 100
    before = deep(w)
    key = k()
    err(refund(w, "bob", p["payment_id"], 101, key=key), 409, "insufficient_funds")
    err(refund(w, "bob", p["payment_id"], 1000), 409, "insufficient_funds")
    assert deep(w) == before
    j = ok(refund(w, "bob", p["payment_id"], 100, key=key), 201)
    assert (w.wallet("bob")["total"], w.wallet("bob")["available"], w.wallet("bob")["held"]) == (400, 0, 400)
    err(refund(w, "bob", p["payment_id"], 1), 409, "insufficient_funds")
    # both limits exceeded: the refund limit is checked before the funds
    r = refund(w, "bob", p["payment_id"], 901)
    err(r, (422, 409), ("refund_exceeds_payment", "insufficient_funds"))
    soft(code_of(r) == "refund_exceeds_payment", "refund-limit-and-funds-order", code=code_of(r))
    ok(w.void("bob", hold["authorization_id"]), 200)
    ok(refund(w, "bob", p["payment_id"], 400), 201)
    assert w.wallet("bob")["total"] == 0
    w.assert_conserved()


def test_g3_correction_debits_are_checked_against_available_then_history(w):
    p = ok(w.pay("ada", "bob", 1000), 201)                 # ada 9000, bob 3500
    ok(refund(w, "bob", p["payment_id"], 100), 201)        # ada 9100, bob 3400
    ha = w.new_auth("ada", "cy", 9000)                     # ada available 100
    before = deep(w)
    err(correct(w, "ada", p["payment_id"], 1, 1101, p["created_at"]), 409, "insufficient_funds")
    assert deep(w) == before
    ok(correct(w, "ada", p["payment_id"], 1, 1100, p["created_at"], "exactly the available 100"), 201)
    assert w.wallet("ada")["available"] == 0
    hb = w.new_auth("bob", "cy", 3500)                     # bob available 0
    err(correct(w, "ada", p["payment_id"], 2, 1099, p["created_at"]), 409, "insufficient_funds")
    # history: the refund was paid out of the payment; moving the payment after the refund leaves bob short at the refund
    w2 = World(fixture(users=[user("ada", 1000), user("bob", 0), user("cy", 0)], ops=[])).login_all()
    q = ok(w2.pay("ada", "bob", 1000), 201)
    time.sleep(0.05)
    rf = ok(refund(w2, "bob", q["payment_id"], 600), 201)
    time.sleep(0.05)
    r = correct(w2, "ada", q["payment_id"], 1, 1000, fmt(inst(rf["created_at"]) + US), "effective just after the refund")
    err(r, 409, "historical_overdraft", "bob refunded 600 before the 1000 arrived")
    ok(correct(w2, "ada", q["payment_id"], 1, 1000, rf["created_at"], "effective at the instant of the refund"), 201)
    check_everything(w2, build_model(w2), random.Random(55), me_points=30, st_points=8)


# ---------------------------------------------------------------- F10

def test_f10_fifty_concurrent_refunds_never_exceed_the_amount(w):
    p = ok(w.pay("ada", "bob", 1000), 201)
    rs = burst([lambda: refund(w, "bob", p["payment_id"], 30) for _ in range(50)])
    st = statuses(rs)
    assert st == {201: 33, 422: 17}, st
    assert {code_of(r) for r in rs if r.status_code == 422} == {"refund_exceeds_payment"}
    assert (w.bal("ada"), w.bal("bob")) == (9000 + 990, 3500 - 990)
    assert len({r.json()["payment_id"] for r in rs if r.status_code == 201}) == 33
    w.assert_conserved()


def test_f10_fifty_concurrent_identical_refunds(w):
    p = ok(w.pay("ada", "bob", 1000), 201)
    key = k()
    rs = burst([lambda: refund(w, "bob", p["payment_id"], 30, key=key) for _ in range(50)])
    assert statuses(rs) == {201: 1, 200: 49}, statuses(rs)
    assert all(r.json() == rs[0].json() for r in rs) and w.bal("bob") == 3470


def test_f10_refunds_race_corrections_that_lower_the_amount(w):
    for rnd in range(4):
        p = ok(w.pay("ada", "bob", 1000), 201)
        fns = [lambda: refund(w, "bob", p["payment_id"], 100) for _ in range(20)]
        fns += [lambda i=i: correct(w, "ada", p["payment_id"], 1, 300 + 10 * i, p["created_at"], "lower") for i in range(15)]
        fns += [lambda i=i: batch(w, [item(p, 200 + i)]) for i in range(15)]
        rs = burst(fns)
        assert all(r.status_code in (201, 409, 422) for r in rs), statuses(rs)
        m = build_model(w)
        pid = p["payment_id"]
        from lib import refunded
        cur = m.pay[pid]["revs"][-1]["amount"]
        assert refunded(m, pid) <= cur, f"round {rnd}: refunded {refunded(m, pid)} exceeds the current amount {cur}"
        assert len(m.pay[pid]["revs"]) <= 2, "at most one of the corrections with expected revision 1 wins"
        wins = [r for r in rs[20:] if r.status_code == 201]
        assert len(wins) == len(m.pay[pid]["revs"]) - 1
        assert m.overdraft(list(m.opening), now_f()) is None
        w.assert_conserved()
    check_everything(w, build_model(w), random.Random(56), me_points=30, st_points=8)
