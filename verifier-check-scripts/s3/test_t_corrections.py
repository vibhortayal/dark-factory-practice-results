"""C, K, H. POST /payments/{id}/corrections, known_at, linked payments."""
import json
import random
import time
from fractions import Fraction

import pytest

from lib import (GET, MAX_AMOUNT, POST, US, World, build_model, burst, call, check_everything, check_payment,
                 check_revision, code_of, correct, err, fixture, fmt, full_statement, inst, k, me_at, now_f, ok, pid_path,
                 revisions, soft, statement, statuses, user)
from test_r_time import ago, sp


def deep(w, handles=("ada", "bob", "cy", "dan", "op")):
    """Everything a correction could change, per user."""
    out = {}
    for h in handles:
        if h not in w.handles():
            continue
        out[h] = (w.wallet(h), w.activity(h), ok(statement(w, h, limit=200), 200)["entries"],
                  ok(statement(w, h, limit=200), 200)["closing_balance"], w.requests(h), w.auths(h))
    return out


def revs(w, who, pid):
    return ok(revisions(w, who, pid), 200)["revisions"]


@pytest.fixture()
def w():
    return World().login_all()


# ---------------------------------------------------------------- C3, C6, C8

def test_c3_c6_c8_a_correction_appends_a_revision_and_moves_the_difference(w):
    key = k()
    p = ok(w.pay("ada", "bob", 100, key=key, note="lunch", visibility="private"), 201)
    pid = p["payment_id"]
    t0 = now_f()
    r = correct(w, "ada", pid, 1, 60, p["created_at"], "correct amount")
    j = check_revision(ok(r, 201), payment_id=pid, revision=2, amount=60, reason="correct amount")
    assert inst(j["effective_at"]) == inst(p["created_at"])
    soft(j["effective_at"] == p["created_at"], "effective_at-not-echoed-verbatim", got=j["effective_at"], want=p["created_at"])
    assert inst(j["recorded_at"]) > inst(p["created_at"]), "recorded times of one payment strictly increase"
    assert t0 - 2 <= inst(j["recorded_at"]) <= now_f() + 2, "recorded_at is the server's time of the correction"
    assert w.wallet("ada")["balance"] == 10000 - 60 and w.wallet("bob")["balance"] == 2500 + 60
    rv = revs(w, "ada", pid)
    assert rv == revs(w, "bob", pid) and len(rv) == 2 and rv[1] == j
    check_revision(rv[0], payment_id=pid, revision=1, amount=100, reason="")
    assert inst(rv[0]["effective_at"]) == inst(rv[0]["recorded_at"]) == inst(p["created_at"])
    # the original payment and its receipt stay as they were; the feed has one item with the original amount
    for h in ("ada", "bob"):
        feed = w.activity(h)
        assert [x for x in feed if x["payment_id"] == pid] == [p], "GET /activity keeps showing the original payment"
        assert len(feed) == 1, "a correction is not a new feed payment"
    assert w.activity("cy") == []
    assert ok(w.pay("ada", "bob", 100, key=key, note="lunch", visibility="private"), 200) == p
    # the statement shows the selected revision once
    for h, sign in (("ada", -1), ("bob", 1)):
        s = ok(statement(w, h), 200)
        assert len(s["entries"]) == 1
        e = s["entries"][0]
        assert e["payment"] == {**p, "amount": 60}, e
        assert (e["delta"], e["revision"]) == (sign * 60, 2)
        assert inst(e["effective_at"]) == inst(j["effective_at"]) and inst(e["recorded_at"]) == inst(j["recorded_at"])
    # increase (debits the sender), zero (reverses everything), and back up from zero
    j3 = check_revision(ok(correct(w, "ada", pid, 2, 250, p["created_at"], "more"), 201), revision=3, amount=250)
    assert (w.wallet("ada")["balance"], w.wallet("bob")["balance"]) == (9750, 2750)
    j4 = check_revision(ok(correct(w, "ada", pid, 3, 0, p["created_at"], "reverse"), 201), revision=4, amount=0)
    assert (w.wallet("ada")["balance"], w.wallet("bob")["balance"]) == (10000, 2500)
    s = ok(statement(w, "ada"), 200)
    assert len(s["entries"]) == 1 and s["entries"][0]["delta"] == 0 and s["entries"][0]["payment"]["amount"] == 0, \
        "a zero-amount revision still appears as an entry with zero delta"
    assert s["entries"][0]["balance_after"] == 10000 == s["closing_balance"]
    j5 = check_revision(ok(correct(w, "ada", pid, 4, 7, p["created_at"], "again"), 201), revision=5, amount=7)
    recs = [inst(x["recorded_at"]) for x in revs(w, "ada", pid)]
    assert recs == sorted(set(recs)) and len(recs) == 5, f"recorded times must strictly increase: {recs}"
    assert [x["revision"] for x in revs(w, "bob", pid)] == [1, 2, 3, 4, 5]
    assert revs(w, "ada", pid)[1:] == [j, j3, j4, j5], "earlier revisions are immutable"
    assert w.activity("ada") == [p]
    w.assert_conserved()
    check_everything(w, build_model(w), random.Random(7), me_points=40, st_points=10)


def test_c8_request_payment_can_be_corrected_and_receipts_stay(w):
    rq = w.new_request("bob", "ada", 400, note="taxi")
    key = k()
    pr = ok(w.pay_request("ada", rq["request_id"], key=key, body={"visibility": "private"}), 201)
    j = ok(correct(w, "ada", pr["payment_id"], 1, 350, pr["created_at"], "less"), 201)
    assert j["revision"] == 2
    assert ok(w.pay_request("ada", rq["request_id"], key=key, body={"visibility": "private"}), 200) == pr
    q2 = [x for x in w.requests("ada") if x["request_id"] == rq["request_id"]][0]
    assert q2["status"] == "paid" and q2["amount"] == 400 and q2["payment_id"] == pr["payment_id"]
    assert (w.bal("ada"), w.bal("bob")) == (10000 - 350, 2500 + 350)
    err(correct(w, "bob", pr["payment_id"], 2, 300, pr["created_at"], "the requester is not the sender"), 403, "forbidden")


# ---------------------------------------------------------------- C1

def test_c1_who_may_correct(w):
    p = ok(w.pay("ada", "bob", 100), 201)
    pid = p["payment_id"]
    body = {"expected_revision": 1, "amount": 60, "effective_at": p["created_at"], "reason": "x"}
    path = f"/payments/{pid}/corrections"
    err(POST(path, None, body, key=k()), 401, "unauthenticated")
    err(POST(path, "bogus-token", body, key=k()), 401, "unauthenticated")
    err(POST(path, None, body), 401, "unauthenticated")
    err(POST(path, w.t("bob"), body, key=k()), 403, "forbidden", "the receiver")
    err(POST(path, w.t("cy"), body, key=k()), 403, "forbidden", "a third party")
    err(POST(path, w.t("op"), body, key=k()), 403, "forbidden", "an operator")
    err(POST("/payments/p_nope/corrections", w.t("ada"), body, key=k()), 404, "not_found")
    priv = ok(w.pay("bob", "cy", 5, visibility="private"), 201)
    r = POST(f"/payments/{priv['payment_id']}/corrections", w.t("ada"), {**body, "effective_at": priv["created_at"]}, key=k())
    err(r, (403, 404), ("forbidden", "not_found"), "a private payment of two other people")
    soft(r.status_code == 403, "third-party-correction-of-private-payment-404")
    err(POST(path, w.t("ada"), body), 400, "missing_idempotency_key")
    err(POST(path, w.t("ada"), body, key=""), 400, "missing_idempotency_key")
    err(POST(path, w.t("ada"), body, key="x" * 256), 422, "validation_failed")
    err(call("POST", path, w.t("ada"), key=k(), raw=b"{nope"), 400, "malformed_request")
    err(call("POST", path, w.t("ada"), key=k(), raw=b"[1]"), 400, "malformed_request")
    err(call("POST", path, w.t("ada"), key=k()), (400, 422), ("malformed_request", "validation_failed"), "no body at all")
    assert len(revs(w, "ada", pid)) == 1 and (w.bal("ada"), w.bal("bob")) == (9900 , 2595)
    ok(POST(path, w.t("ada"), body, key="y" * 255), 201)
    for odd in ("a/b", "ünï-😀", "x" * 300, "%00", "..", ""):
        r = call("POST", f"/payments/{odd}/corrections", w.t("ada"), key=k(), body=body, kind="any")
        assert 400 <= r.status_code < 500, f"{odd!r}: {r.status_code}"
    for method in ("GET", "PUT", "DELETE", "PATCH"):
        r = call(method, path, w.t("ada"), kind="any")
        assert 400 <= r.status_code < 500, (method, r.status_code)


# ---------------------------------------------------------------- C2

def _body(p, **over):
    b = {"expected_revision": 1, "amount": 60, "effective_at": p["created_at"], "reason": "fix"}
    for kk, v in over.items():
        if v is DROP:
            b.pop(kk)
        else:
            b[kk] = v
    return b


DROP = object()
INVALID_422 = {
    "expected_revision missing": {"expected_revision": DROP}, "amount missing": {"amount": DROP},
    "effective_at missing": {"effective_at": DROP}, "reason missing": {"reason": DROP},
    "expected_revision 0": {"expected_revision": 0}, "expected_revision -1": {"expected_revision": -1},
    "amount -1": {"amount": -1}, "amount above the maximum": {"amount": MAX_AMOUNT + 1}, "amount 1.5": {"amount": 1.5},
    "amount string": {"amount": "60"}, "amount true": {"amount": True}, "amount null": {"amount": None},
    "amount 1e30": {"amount": 10 ** 30}, "reason empty": {"reason": ""}, "reason 201 characters": {"reason": "r" * 201},
    "effective_at naive": {"effective_at": "2026-01-05T10:00:00"}, "effective_at bare date": {"effective_at": "2026-01-05"},
    "effective_at empty": {"effective_at": ""}, "effective_at garbage": {"effective_at": "last week"},
    "effective_at 30 February": {"effective_at": "2026-02-30T10:00:00+00:00"},
    "effective_at in the future": {"effective_at": "FUTURE"}, "effective_at far future": {"effective_at": "2999-01-01T00:00:00Z"},
}
INVALID_TYPE = {  # the endpoint says "Invalid input is 422"; stage 1 says a wrong JSON type is 400: either, never a success
    "expected_revision string": {"expected_revision": "1"}, "expected_revision true": {"expected_revision": True},
    "expected_revision null": {"expected_revision": None}, "expected_revision 1.5": {"expected_revision": 1.5},
    "expected_revision list": {"expected_revision": [1]}, "reason number": {"reason": 5}, "reason null": {"reason": None},
    "reason list": {"reason": ["x"]}, "effective_at number": {"effective_at": 1767607200}, "effective_at null": {"effective_at": None},
    "effective_at object": {"effective_at": {}},
}


@pytest.mark.parametrize("name", sorted(INVALID_422))
def test_c2_invalid_input_is_422(w, name):
    p = ok(w.pay("ada", "bob", 100), 201)
    before = deep(w)
    over = dict(INVALID_422[name])
    if over.get("effective_at") == "FUTURE":
        over["effective_at"] = fmt(now_f() + 30)
    key = k()
    err(correct_raw(w, p, _body(p, **over), key), 422, "validation_failed", name)
    assert deep(w) == before and len(revs(w, "ada", p["payment_id"])) == 1
    # the failed attempt claimed no key
    ok(correct_raw(w, p, _body(p), key), 201)


def correct_raw(w, p, body, key=None, who="ada"):
    return POST(f"/payments/{pid_path(p['payment_id'])}/corrections", w.t(who), body, key=key or k())


@pytest.mark.parametrize("name", sorted(INVALID_TYPE))
def test_c2_wrong_types_are_refused(w, name):
    p = ok(w.pay("ada", "bob", 100), 201)
    before = deep(w)
    r = correct_raw(w, p, _body(p, **INVALID_TYPE[name]))
    err(r, (400, 422), ("malformed_request", "validation_failed"), name)
    soft(r.status_code == 422, "correction-wrong-type-400", case=name)
    assert deep(w) == before


def test_c2_valid_boundaries():
    w = World(fixture(users=[user("ada", 3 * MAX_AMOUNT), user("bob", 0), user("cy", 0)], ops=[])).login_all()
    ps = [ok(w.pay("ada", "bob", 100, note=str(i)), 201) for i in range(16)]
    c = lambda i, **over: correct_raw(w, ps[i], _body(ps[i], **over))  # noqa: E731
    assert ok(c(0, amount=0), 201)["amount"] == 0
    assert ok(c(1, amount=MAX_AMOUNT), 201)["amount"] == MAX_AMOUNT
    r = call("POST", f"/payments/{ps[2]['payment_id']}/corrections", w.t("ada"), key=k(),
             raw=json.dumps(_body(ps[2], amount="@@A@@")).replace('"@@A@@"', "60.0"))
    assert ok(r, 201)["amount"] == 60 and type(r.json()["amount"]) is int, "60.0 is an integral amount"
    r = call("POST", f"/payments/{ps[3]['payment_id']}/corrections", w.t("ada"), key=k(),
             raw=json.dumps(_body(ps[3], amount="@@A@@")).replace('"@@A@@"', "6e1"))
    assert ok(r, 201)["amount"] == 60
    assert ok(c(4, reason="r" * 200), 201)["reason"] == "r" * 200
    r = c(5, reason="😀" * 200)
    soft(r.status_code == 201, "reason-200-emoji-refused", status=r.status_code)
    assert r.status_code in (201, 422)
    assert ok(c(6, reason=" padded \n ünï "), 201)["reason"] == " padded \n ünï ", "the reason is kept as given"
    assert ok(c(7, colour="blue", payment_id="p_other", revision=99), 201)["revision"] == 2, "unknown fields are ignored"
    j = ok(c(8, effective_at=fmt(now_f() - 2)), 201)
    for i, spelling in ((9, fmt(inst(ps[9]["created_at"]), 330)), (10, fmt(inst(ps[10]["created_at"]), z=True)),
                        (11, fmt(inst(ps[11]["created_at"]) - Fraction(1, 2), -480)),
                        (12, fmt(inst(ps[12]["created_at"]) - Fraction(123456789, 10 ** 9)))):
        j = ok(c(i, effective_at=spelling), 201)
        assert inst(j["effective_at"]) == inst(spelling)
        soft(j["effective_at"] == spelling, "effective_at-not-echoed-verbatim", got=j["effective_at"], want=spelling)
    j = ok(c(13, effective_at="2001-02-03T04:05:06+00:00"), 201)          # long before the service existed; ada had the funds
    assert ok(c(14, amount=100, reason="only the time changes", effective_at=fmt(now_f() - 5)), 201)["amount"] == 100
    r = call("POST", f"/payments/{ps[15]['payment_id']}/corrections", w.t("ada"), key=k(),
             raw=json.dumps(_body(ps[15], expected_revision="@@R@@")).replace('"@@R@@"', "1.0"))
    assert r.status_code in (201, 422), r.text
    soft(r.status_code == 201, "expected_revision-1.0-refused")
    w.assert_conserved()
    check_everything(w, build_model(w), random.Random(8), me_points=40, st_points=10)


# ---------------------------------------------------------------- C4, C5

def test_c4_stale_revision(w):
    p = ok(w.pay("ada", "bob", 100), 201)
    ok(correct(w, "ada", p["payment_id"], 1, 60, p["created_at"]), 201)
    before = deep(w)
    err(correct(w, "ada", p["payment_id"], 1, 50, p["created_at"]), 409, "stale_revision")
    r = correct(w, "ada", p["payment_id"], 3, 50, p["created_at"])
    err(r, (409, 422), ("stale_revision", "validation_failed"), "an expected revision ahead of the latest")
    soft(code_of(r) == "stale_revision", "expected-revision-ahead-not-stale_revision", code=code_of(r))
    err(correct(w, "ada", p["payment_id"], 10 ** 30, 50, p["created_at"]), (409, 422))
    assert deep(w) == before and len(revs(w, "ada", p["payment_id"])) == 2
    # validation comes before the revision check
    err(correct(w, "ada", p["payment_id"], 1, -5, p["created_at"]), 422, "validation_failed")
    ok(correct(w, "ada", p["payment_id"], 2, 50, p["created_at"]), 201)


def test_c4_fifty_concurrent_corrections_with_one_expected_revision(w):
    p = ok(w.pay("ada", "bob", 100), 201)
    rs = burst([lambda i=i: correct(w, "ada", p["payment_id"], 1, 10 + i, p["created_at"], f"racer {i}") for i in range(50)])
    st = statuses(rs)
    assert st == {201: 1, 409: 49}, st
    assert {code_of(r) for r in rs if r.status_code == 409} == {"stale_revision"}
    win = [r for r in rs if r.status_code == 201][0].json()
    assert revs(w, "ada", p["payment_id"])[1:] == [win]
    assert (w.bal("ada"), w.bal("bob")) == (10000 - win["amount"], 2500 + win["amount"])
    w.assert_conserved()


def test_c5_replay_reuse_and_failed_keys(w):
    p = ok(w.pay("ada", "bob", 100), 201)
    p2 = ok(w.pay("ada", "bob", 100), 201)
    pid = p["payment_id"]
    key = k()
    body = _body(p)
    j = ok(correct_raw(w, p, body, key), 201)
    after = deep(w)
    assert ok(correct_raw(w, p, body, key), 200) == j
    j3 = ok(correct(w, "ada", pid, 2, 80, p["created_at"], "newer"), 201)
    j4 = ok(correct(w, "ada", pid, 3, 90, p["created_at"], "newest"), 201)
    newest = deep(w)
    for _ in range(3):
        assert ok(correct_raw(w, p, body, key), 200) == j, "a replay returns the original revision even after newer ones"
    raw = "  " + json.dumps({kk: body[kk] for kk in reversed(list(body))}, indent=3) + "\n"
    assert ok(call("POST", f"/payments/{pid}/corrections", w.t("ada"), key=key, raw=raw), 200) == j
    err(correct_raw(w, p, {**body, "amount": 61}, key), 409, "idempotency_key_reuse")
    err(correct_raw(w, p, {**body, "reason": "other"}, key), 409, "idempotency_key_reuse")
    err(correct_raw(w, p, {**body, "extra": 1}, key), 409, "idempotency_key_reuse")
    err(correct_raw(w, p, {"amount": "x"}, key), 409, "idempotency_key_reuse", "a claimed key is resolved before validation")
    err(correct_raw(w, p, {}, key), 409, "idempotency_key_reuse")
    assert deep(w) == newest
    # the same key and body on another payment's path is a first use
    j2 = ok(correct_raw(w, p2, _body(p2), key), 201)
    assert j2["payment_id"] == p2["payment_id"]
    # the same key string of another user does not interact
    pb = ok(w.pay("bob", "cy", 10), 201)
    ok(correct_raw(w, pb, _body(pb, amount=5), key, who="bob"), 201)
    assert ok(correct_raw(w, p, body, key), 200) == j
    w.assert_conserved()


def test_c5_fifty_concurrent_identical_corrections(w):
    p = ok(w.pay("ada", "bob", 100), 201)
    key = k()
    body = _body(p)
    rs = burst([lambda: correct_raw(w, p, body, key) for _ in range(50)])
    assert statuses(rs) == {201: 1, 200: 49}, statuses(rs)
    first = rs[0].json()
    assert all(r.json() == first for r in rs)
    assert len(revs(w, "ada", p["payment_id"])) == 2 and (w.bal("ada"), w.bal("bob")) == (9940, 2560)


def test_c5_failed_corrections_leave_their_key_reusable(w):
    p = ok(w.pay("ada", "bob", 100), 201)
    cases = ((lambda cur: _body(p, expected_revision=cur, amount=-1), 422, "validation_failed"),
             (lambda cur: _body(p, expected_revision=cur + 4), (409, 422), None),
             (lambda cur: _body(p, expected_revision=cur - 1 or 99), (409, 422), None),
             (lambda cur: _body(p, expected_revision=cur, amount=10 ** 9), 409, "insufficient_funds"))
    for make, status, code in cases:
        key = k()
        cur = len(revs(w, "ada", p["payment_id"]))
        err(correct_raw(w, p, make(cur), key), status, code)
        g = ok(correct_raw(w, p, _body(p, expected_revision=cur, amount=50 + cur), key), 201)
        assert g["revision"] == cur + 1
    key = k()
    err(correct_raw(w, p, _body(p), key, who="bob"), 403, "forbidden")
    pb = ok(w.pay("bob", "cy", 10), 201)
    ok(correct_raw(w, pb, _body(pb, amount=5), key, who="bob"), 201)


# ---------------------------------------------------------------- C7

def test_c7_insufficient_funds_on_an_increase(w):
    p = ok(w.pay("ada", "bob", 100), 201)
    before = deep(w)
    key = k()
    err(correct(w, "ada", p["payment_id"], 1, 10001, p["created_at"], key=key), 409, "insufficient_funds")
    assert deep(w) == before and len(revs(w, "ada", p["payment_id"])) == 1
    j = ok(correct(w, "ada", p["payment_id"], 1, 10000, p["created_at"], key=key), 201)    # exactly affordable; key reusable
    assert (w.bal("ada"), w.bal("bob")) == (0, 12500)


def test_c7_insufficient_funds_on_a_decrease(w):
    p = ok(w.pay("ada", "bob", 100), 201)
    ok(w.pay("bob", "cy", 2590), 201)                       # the receiver has spent all but 10
    before = deep(w)
    err(correct(w, "ada", p["payment_id"], 1, 89, p["created_at"]), 409, "insufficient_funds")
    err(correct(w, "ada", p["payment_id"], 1, 0, p["created_at"]), 409, "insufficient_funds")
    assert deep(w) == before
    ok(correct(w, "ada", p["payment_id"], 1, 90, p["created_at"]), 201)      # exactly what the receiver still has
    assert w.bal("bob") == 0 and w.bal("ada") == 9910
    w.assert_conserved()


def test_c7_held_funds_cannot_fund_a_correction(w):
    p = ok(w.pay("ada", "bob", 100), 201)
    a = w.new_auth("ada", "cy", 9900)                        # ada: total 9900, available 0
    hb = w.new_auth("bob", "cy", 2590)                       # bob: total 2600, available 10
    before = deep(w)
    err(correct(w, "ada", p["payment_id"], 1, 101, p["created_at"]), 409, "insufficient_funds", "the sender's available is 0")
    err(correct(w, "ada", p["payment_id"], 1, 89, p["created_at"]), 409, "insufficient_funds", "the receiver's available is 10")
    assert deep(w) == before
    ok(correct(w, "ada", p["payment_id"], 1, 90, p["created_at"]), 201)
    assert w.wallet("bob")["available"] == 0 and w.wallet("ada")["available"] == 10


def overdraft_world():
    """ada opens with 100, pays bob 100 five days ago; bob (opening 0) pays cy 100 four days ago."""
    t1, t2 = ago(5), ago(4)
    w = World(fixture(users=[user("ada", 0), user("bob", 0), user("cy", 100), user("dan", 500)],
                      payments=[sp("p_a", "ada", "bob", 100, fmt(t1)), sp("p_b", "bob", "cy", 100, fmt(t2))], ops=[])).login_all()
    return w, t1, t2


def test_c7_historical_overdraft_when_a_payment_is_moved_before_its_funding():
    w, t1, t2 = overdraft_world()
    before = deep(w)
    key = k()
    r = correct(w, "bob", "p_b", 1, 100, fmt(t1 - 86400), "it really left a day before the money came", key=key)
    err(r, 409, "historical_overdraft")
    err(correct(w, "bob", "p_b", 1, 100, fmt(t1 - US)), 409, "historical_overdraft", "one microsecond before the funding")
    assert deep(w) == before and len(revs(w, "bob", "p_b")) == 1
    # at exactly the funding instant both movements combine: 0 + 100 - 100
    j = ok(correct(w, "bob", "p_b", 1, 100, fmt(t1), "same instant as the funding", key=key), 201)
    assert j["revision"] == 2
    assert ok(me_at(w, "bob", fmt(t1)), 200)["balance"] == 0 and ok(me_at(w, "bob", fmt(t1 - US)), 200)["balance"] == 0
    assert ok(me_at(w, "cy", fmt(t1)), 200)["balance"] == 100
    check_everything(w, build_model(w), random.Random(9), me_points=30, st_points=10)


def test_c7_historical_overdraft_when_the_funding_is_moved_later():
    w, t1, t2 = overdraft_world()
    before = deep(w)
    err(correct(w, "ada", "p_a", 1, 100, fmt(t2 + 3600), "paid later than recorded"), 409, "historical_overdraft")
    err(correct(w, "ada", "p_a", 1, 100, fmt(t2 + US)), 409, "historical_overdraft")
    assert deep(w) == before
    ok(correct(w, "ada", "p_a", 1, 100, fmt(t2), "same instant as the spending"), 201)
    check_everything(w, build_model(w), random.Random(10), me_points=30, st_points=10)


def test_c7_insufficient_funds_takes_precedence_then_historical_overdraft():
    w, t1, t2 = overdraft_world()
    before = deep(w)
    # bob holds nothing now: giving back 40 is unaffordable today
    err(correct(w, "ada", "p_a", 1, 60, fmt(t1), "it was 60"), 409, "insufficient_funds")
    assert deep(w) == before
    ok(w.pay("dan", "bob", 40), 201)                 # affordable today, but four days ago bob paid 100 out of 60
    before = deep(w)
    err(correct(w, "ada", "p_a", 1, 60, fmt(t1), "it was 60"), 409, "historical_overdraft")
    assert deep(w) == before
    # the sender side: an increase that today's balance covers but the balance at the effective time does not
    ok(w.pay("dan", "ada", 50), 201)
    before = deep(w)
    err(correct(w, "ada", "p_a", 1, 150, fmt(t1), "it was 150"), 409, "historical_overdraft")
    assert deep(w) == before
    w.assert_conserved()
    check_everything(w, build_model(w), random.Random(11), me_points=30, st_points=10)


def test_c7_historical_overdraft_of_available_under_a_past_hold():
    w = World(fixture(users=[user("ada", 100), user("bob", 0), user("cy", 0)], ops=[])).login_all()
    a = w.new_auth("ada", "bob", 80)
    time.sleep(0.3)
    v = ok(w.void("ada", a["authorization_id"]), 200)
    time.sleep(0.3)
    p = ok(w.pay("ada", "cy", 10), 201)
    ta, tv = inst(a["created_at"]), inst(v["closed_at"])
    assert ta < tv < inst(p["created_at"])
    before = deep(w, ("ada", "bob", "cy"))
    mid = (ta + tv) / 2
    # 30 effective while 80 of the 100 were held: total 70, available -10
    err(correct(w, "ada", p["payment_id"], 1, 30, fmt(mid), "during the hold"), 409, "historical_overdraft")
    err(correct(w, "ada", p["payment_id"], 1, 30, fmt(ta), "at the instant the hold began"), 409, "historical_overdraft")
    err(correct(w, "ada", p["payment_id"], 1, 30, fmt(ta - 3600), "before the hold, still short when it began"), 409,
        "historical_overdraft")
    assert deep(w, ("ada", "bob", "cy")) == before
    ok(correct(w, "ada", p["payment_id"], 1, 20, fmt(mid), "20 fits beside the hold"), 201)
    ok(correct(w, "ada", p["payment_id"], 2, 30, fmt(tv), "30 from the instant the hold was released"), 201)
    check_everything(w, build_model(w), random.Random(12), me_points=40, st_points=10)


# ---------------------------------------------------------------- C9 / H

def test_c9_h1_linked_payments_are_immutable(w):
    st = ok(POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 11},
                                                           {"from_handle": "op", "to_handle": "cy", "amount": 3, "visibility": "private"}]}, key=k()), 201)
    a = w.new_auth("ada", "dan", 200)
    cap1 = ok(w.capture("dan", a["authorization_id"], body={"amount": 50, "final": False}), 201)
    cap2 = ok(w.capture("dan", a["authorization_id"], body={"amount": 60}), 201)
    before = deep(w)
    for pay, sender in ((st["payments"][0], "ada"), (st["payments"][1], "op"), (cap1, "ada"), (cap2, "ada")):
        for amount in (1, 0, pay["amount"]):
            key = k()
            err(correct(w, sender, pay["payment_id"], 1, amount, pay["created_at"], "try", key=key), 422, "linked_payment_immutable")
        r = correct(w, "bob" if sender != "bob" else "cy", pay["payment_id"], 1, 1, pay["created_at"])
        err(r, (403, 422), ("forbidden", "linked_payment_immutable"))
        rv = revs(w, sender, pay["payment_id"])
        assert len(rv) == 1 and inst(rv[0]["effective_at"]) == inst(rv[0]["recorded_at"]) == inst(pay["created_at"])
    assert inst(st["payments"][0]["created_at"]) == inst(st["committed_at"])
    assert deep(w) == before
    # the settlement's receipt is unchanged
    s = ok(statement(w, "ada"), 200)
    assert [e["revision"] for e in s["entries"]] == [1, 1, 1]
    # an ordinary payment beside them stays correctable
    p = ok(w.pay("ada", "bob", 9), 201)
    ok(correct(w, "ada", p["payment_id"], 1, 8, p["created_at"]), 201)


def test_c9_seeded_payment_can_be_corrected_and_the_opening_balance_stays():
    t1 = ago(5)
    w = World(fixture(users=[user("ada", 9500), user("bob", 3000), user("cy", 0)], payments=[sp("p_1", "ada", "bob", 500, fmt(t1))],
                      ops=[])).login_all()
    assert ok(me_at(w, "ada", fmt(t1 - 1)), 200)["balance"] == 10000
    ok(correct(w, "ada", "p_1", 1, 200, fmt(t1 + 86400), "less and a day later"), 201)
    assert (w.bal("ada"), w.bal("bob")) == (9800, 2700)
    assert ok(me_at(w, "ada", fmt(t1 - 1)), 200)["balance"] == 10000, "corrections must not change the opening balance"
    assert ok(me_at(w, "bob", fmt(t1 - 1)), 200)["balance"] == 2500
    assert ok(me_at(w, "ada", fmt(t1)), 200)["balance"] == 10000, "the payment no longer takes effect at its original time"
    assert ok(me_at(w, "ada", fmt(t1 + 86400)), 200)["balance"] == 9800
    s = ok(statement(w, "ada"), 200)
    assert s["opening_balance"] == 10000 and s["closing_balance"] == 9800
    assert w.activity("ada")[0]["amount"] == 500 and inst(w.activity("ada")[0]["created_at"]) == t1
    check_everything(w, build_model(w), random.Random(13), me_points=30, st_points=10)


# ---------------------------------------------------------------- K. known_at

def test_k1_k2_k3_known_at_selects_revisions_by_recorded_time(w):
    p = ok(w.pay("ada", "bob", 100), 201)
    c0 = inst(p["created_at"])
    time.sleep(0.05)
    r2 = ok(correct(w, "ada", p["payment_id"], 1, 60, fmt(c0 - 86400), "60, a day earlier"), 201)
    time.sleep(0.05)
    r3 = ok(correct(w, "ada", p["payment_id"], 2, 80, fmt(c0 - 2 * 86400), "80, two days earlier"), 201)
    k2, k3 = inst(r2["recorded_at"]), inst(r3["recorded_at"])
    assert c0 < k2 < k3

    def bob(T, K):
        return ok(me_at(w, "bob", fmt(T) if T is not None else None, fmt(K) if K is not None else None), 200)["balance"]

    far, old = now_f() + 86400, c0 - 10 * 86400
    assert bob(far, c0 - US) == 2500, "known_at before the payment was recorded: it contributes nothing"
    assert bob(far, c0) == 2600 and bob(far, k2 - US) == 2600, "revision 1 is selected until the correction was recorded"
    assert bob(c0 - US, c0) == 2500 and bob(c0, c0) == 2600
    assert bob(far, k2) == 2560 and bob(far, k3 - US) == 2560, "revision 2 from its recorded time (inclusive)"
    assert bob(c0 - 86400 - US, k2) == 2500 and bob(c0 - 86400, k2) == 2560, "revision 2 applies at its effective time"
    assert bob(far, k3) == 2580 and bob(c0 - 2 * 86400, k3) == 2580 and bob(c0 - 2 * 86400 - US, k3) == 2500
    assert bob(None, k2) == 2560 and bob(None, far) == 2580 and bob(None, None) == 2580 and bob(old, None) == 2500
    assert bob(c0 - 86400, None) == 2580, "without known_at everything known now is used"
    # the statement follows the same selection, and the correction moves the payment between windows
    win = {"from": fmt(c0 - 86400 - 3600), "to": fmt(c0 - 3600)}       # holds only revision 2's effective time
    def st(K=None, **kw):
        if K is not None:
            kw["known_at"] = fmt(K)
        return ok(statement(w, "bob", **kw), 200)
    assert st(k2, **win)["entries"][0]["revision"] == 2 and st(k2, **win)["entries"][0]["delta"] == 60
    assert st(k3, **win)["entries"] == [] and st(None, **win)["entries"] == [], "revision 3 moved it out of this window"
    assert st(c0, **win)["entries"] == [], "revision 1 took effect later than this window"
    assert st(c0 - US)["entries"] == [] and st(c0 - US)["closing_balance"] == 2500
    e = st(c0)["entries"]
    assert len(e) == 1 and (e[0]["revision"], e[0]["delta"], e[0]["payment"]["amount"]) == (1, 100, 100)
    e = st(far)["entries"]
    assert len(e) == 1 and (e[0]["revision"], e[0]["delta"], e[0]["payment"]["amount"]) == (3, 80, 80)
    assert inst(e[0]["effective_at"]) == c0 - 2 * 86400 and inst(e[0]["recorded_at"]) == k3
    assert e[0]["payment"]["created_at"] == p["created_at"], "the payment's created_at stays the original instant"
    check_everything(w, build_model(w), random.Random(14), me_points=60, st_points=20)


def test_k3_corrections_reorder_a_statement(w):
    ps = [ok(w.pay("ada", "bob", 10 * (i + 1)), 201) for i in range(4)]
    first = [e["payment"]["payment_id"] for e in ok(statement(w, "ada"), 200)["entries"]]
    assert first == [p["payment_id"] for p in ps]
    time.sleep(0.1)
    ok(correct(w, "ada", ps[3]["payment_id"], 1, 40, fmt(inst(ps[0]["created_at"]) - 60), "really the first"), 201)
    ok(correct(w, "ada", ps[0]["payment_id"], 1, 10, fmt(now_f() - Fraction(1, 100)), "really the last"), 201)
    s = ok(statement(w, "ada"), 200)
    assert [e["payment"]["payment_id"] for e in s["entries"]] == [ps[i]["payment_id"] for i in (3, 1, 2, 0)]
    assert [e["balance_after"] for e in s["entries"]] == [9960, 9940, 9910, 9900]
    assert [p["payment_id"] for p in w.activity("ada")] == [p["payment_id"] for p in reversed(ps)], \
        "GET /activity keeps its ordering by created_at"
    check_everything(w, build_model(w), random.Random(15), me_points=40, st_points=15)
