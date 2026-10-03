"""T, A, R. Payment timestamps, GET /me as of an instant, instant grammar, GET /payments/{id}/revisions."""
import random
import time
from fractions import Fraction

import pytest

from lib import (GET, INF, POST, PW, US, Model, World, build_model, call, check_everything, check_me, check_payment,
                 check_revision, code_of, correct, err, fixture, fmt, inst, k, me_at, now_f, ok, q, revisions, soft,
                 statement, user)


def ago(days, extra=0):
    return Fraction(int(time.time())) - days * 86400 + extra


def sp(pid, frm, to, amount, at=None, vis="public", note=""):
    p = {"id": pid, "from_user_id": f"u_{frm}", "to_user_id": f"u_{to}", "amount": amount, "note": note, "visibility": vis}
    if at is not None:
        p["created_at"] = at
    return p


def hist():
    """Openings ada 10000, bob 2500, cy 0, dan 0. Seeded payments out of chronological order, in several spellings."""
    t1, t2, t3 = ago(5), ago(4), ago(3)
    pays = [sp("p_4", "ada", "cy", 50, fmt(t3), "private", "tie b"),
            sp("p_0", "ada", "bob", 10, None, "public", "no time"),
            sp("p_2", "bob", "cy", 300, fmt(t2, 120), "private", "second"),
            sp("p_3", "cy", "ada", 100, fmt(t3, -330), "public", "tie a"),
            sp("p_1", "ada", "bob", 500, fmt(t1, z=True), "public", "first")]
    users = [user("ada", 9540), user("bob", 2710), user("cy", 250), user("dan", 0)]
    before = now_f()
    w = World(fixture(users=users, payments=pays, ops=[])).login_all()
    after = now_f()
    return w, (t1, t2, t3), (before, after)


# ---------------------------------------------------------------- T. payment timestamps

def test_t1_t2_seeded_created_at_is_kept_and_orders_the_feed():
    w, (t1, t2, t3), (before, after) = hist()
    feed = {p["payment_id"]: p for p in w.activity("ada") + w.activity("bob") + w.activity("cy")}
    assert set(feed) == {"p_0", "p_1", "p_2", "p_3", "p_4"}
    for pid, t in (("p_1", t1), ("p_2", t2), ("p_3", t3), ("p_4", t3)):
        check_payment(feed[pid])
        assert inst(feed[pid]["created_at"]) == t, f"{pid}: created_at {feed[pid]['created_at']} is not the seeded instant {fmt(t)}"
        seeded = next(x for x in w.fx["payments"] if x["id"] == pid)["created_at"]
        soft(feed[pid]["created_at"] == seeded, "seeded-created_at-not-verbatim", got=feed[pid]["created_at"], want=seeded)
    r0 = inst(feed["p_0"]["created_at"])
    assert before - 2 <= r0 <= after + 2, f"omitted created_at should be the reset time, got {feed['p_0']['created_at']}"
    # GET /activity keeps its ordering by created_at, newest first, whatever the fixture order
    ada = [p["payment_id"] for p in w.activity("ada")]
    assert ada[0] == "p_0" and ada[-1] == "p_1" and set(ada[1:3]) == {"p_3", "p_4"}, ada
    assert [p["payment_id"] for p in w.activity("bob")] == ["p_0", "p_3", "p_2", "p_1"], w.activity("bob")
    # a payment made through the API comes after the reset instant
    p = ok(w.pay("ada", "bob", 7), 201)
    assert inst(p["created_at"]) >= r0, "an API payment is not after the reset time of a seeded payment"
    soft(inst(p["created_at"]) > r0, "api-payment-ties-with-reset-instant")
    assert w.activity("ada")[0]["payment_id"] == p["payment_id"]


def test_t3_loading_seeded_payments_does_not_change_the_balance():
    w, _, _ = hist()
    assert {h: w.wallet(h)["balance"] for h in ("ada", "bob", "cy", "dan")} == {"ada": 9540, "bob": 2710, "cy": 250, "dan": 0}
    for h in ("ada", "bob", "cy", "dan"):
        m = w.wallet(h)
        assert m["held"] == 0 and m["available"] == m["balance"]


BAD_SEEDED = {"future": lambda: fmt(now_f() + 3600), "future by a day with offset": lambda: fmt(ago(-1), 120),
              "naive": lambda: "2026-01-05T10:00:00", "bare date": lambda: "2026-01-05", "empty": lambda: "",
              "garbage": lambda: "yesterday", "month 13": lambda: "2026-13-05T10:00:00+00:00",
              "30 February": lambda: "2026-02-30T10:00:00+00:00"}


@pytest.mark.parametrize("name", sorted(BAD_SEEDED))
def test_t2_bad_seeded_created_at_is_422_and_changes_nothing(name):
    w, _, _ = hist()
    snap = w.snapshot()
    bad = fixture(users=[user("zed", 100), user("yan", 0)], payments=[sp("p_z", "zed", "yan", 1, BAD_SEEDED[name]())], ops=[])
    err(POST("/_test/reset", body=bad), 422, "validation_failed", name)
    assert w.snapshot() == snap, "a refused reset changed the state"


@pytest.mark.parametrize("value", [5, 1.5, True, None, [], {}])
def test_t2_seeded_created_at_of_wrong_type_never_5xx(value):
    w, _, _ = hist()
    snap = w.snapshot()
    bad = fixture(users=[user("zed", 100), user("yan", 0)], payments=[{**sp("p_z", "zed", "yan", 1), "created_at": value}], ops=[])
    r = POST("/_test/reset", body=bad)
    if value is None and r.status_code == 204:
        soft(False, "seeded-created_at-null-treated-as-omitted")
        return
    err(r, (400, 422), ("malformed_request", "validation_failed"))
    assert w.snapshot() == snap


def test_t2_seeded_created_at_spellings_are_accepted():
    t = ago(2)
    spell = [fmt(t, z=True), fmt(t + Fraction(1, 2)), fmt(t + Fraction(123456, 10 ** 6), 330), fmt(t - 5, -480),
             fmt(t + Fraction(123456789, 10 ** 9))]
    pays = [sp(f"p_{i}", "ada", "bob", 1, s) for i, s in enumerate(spell)]
    w = World(fixture(users=[user("ada", 95), user("bob", 5)], payments=pays, ops=[])).login_all()
    got = {p["payment_id"]: p["created_at"] for p in w.activity("ada")}
    for i, s in enumerate(spell):
        assert inst(got[f"p_{i}"]) == inst(s), f"{s} came back as {got[f'p_{i}']}"
    m = build_model(w)
    check_everything(w, m, random.Random(5), me_points=20, st_points=6)


# ---------------------------------------------------------------- A. GET /me as of an instant

def test_a1_me_without_temporal_parameters_is_unchanged():
    w, _, _ = hist()
    me = w.me("ada")
    assert "as_of" not in me and "known_at" not in me, me
    assert set(me) >= {"user_id", "display_name", "handle", "balance", "total", "available", "held", "currency", "minor_units"}
    soft(set(me) == {"user_id", "display_name", "handle", "balance", "total", "available", "held", "currency", "minor_units"},
         "me-extra-keys", keys=sorted(me))


def test_a3_as_of_before_at_and_after_each_payment():
    w, (t1, t2, t3), (before, after) = hist()

    def bal(h, T):
        return ok(me_at(w, h, fmt(T)), 200)["balance"]

    # ada: opening 10000; -500 at t1; +100 and -50 at t3; -10 at reset
    assert bal("ada", t1 - 86400) == 10000, "before the earliest payment the opening balance is expected"
    assert bal("ada", t1 - US) == 10000
    assert bal("ada", t1) == 9500, "a payment made at exactly as_of counts"
    assert bal("ada", t1 + US) == 9500
    assert bal("ada", t3 - US) == 9500
    assert bal("ada", t3) == 9550
    assert bal("ada", before - 5) == 9550
    assert bal("ada", after + 5) == 9540
    assert bal("ada", now_f() + 86400 * 400) == 9540, "an as_of after the latest payment is the current balance"
    # bob: opening 2500; +500 at t1; -300 at t2; +10 at reset.  cy: opening 0.  dan: nothing ever
    assert [bal("bob", x) for x in (t1 - US, t1, t2 - US, t2, after + 5)] == [2500, 3000, 3000, 2700, 2710]
    assert [bal("cy", x) for x in (t2 - US, t2, t3, after + 5)] == [0, 300, 250, 250]
    assert bal("dan", t1 - 86400) == 0 and bal("dan", after + 5) == 0
    # the whole response describes that instant, and the other members stay
    body = ok(me_at(w, "ada", fmt(t1)), 200)
    assert body["total"] == 9500 and body["available"] == 9500 and body["held"] == 0, body
    assert body["handle"] == "ada" and body["currency"] == "EUR" and body["minor_units"] == 2
    m = build_model(w)
    assert m.opening == {"u_ada": 10000, "u_bob": 2500, "u_cy": 0, "u_dan": 0}
    check_everything(w, m, random.Random(1), me_points=40, st_points=10)


def test_a3_api_payments_and_a_signed_up_account():
    w = World().login_all()
    su = w.signup("fresh.face@example.com")
    t0 = now_f()
    p1 = ok(w.pay("ada", su["handle"], 300), 201)
    p2 = ok(w.pay(su["handle"], "bob", 120), 201)
    c1, c2 = inst(p1["created_at"]), inst(p2["created_at"])
    assert c1 <= c2

    def bal(h, T):
        return ok(me_at(w, h, fmt(T)), 200)["balance"]

    h = su["handle"]
    assert bal(h, t0 - 86400 * 30) == 0, "new accounts open at zero"
    assert bal(h, c1 - US) == 0 and bal(h, c1) == (300 if c1 < c2 else 180)
    assert bal(h, c2) == 180 and bal(h, c2 + 86400) == 180
    assert bal("ada", c1 - US) == 10000 and bal("ada", c1) == 9700
    # exact comparison of fractions: one nanosecond before the payment it has not happened yet
    ns = Fraction(1, 10 ** 9)
    assert bal("ada", c1 - ns) == 10000, f"as_of one nanosecond before {p1['created_at']} must not include the payment"
    assert bal("ada", c1 + ns) == 9700
    for off in (330, -480, 0):
        assert ok(me_at(w, "ada", fmt(c1, off)), 200)["balance"] == 9700, "the same instant written with another offset"
    m = build_model(w)
    check_everything(w, m, random.Random(2), me_points=30, st_points=8)


ECHO = ["2026-01-05T10:00:00Z", "2026-01-05T12:00:00+02:00", "2026-01-05T10:00:00.5+00:00", "2026-01-05T10:00:00.123456-08:00",
        "2026-01-05T10:00:00.123456789+05:30", "2031-12-31T23:59:59+14:00", "2001-01-01T00:00:00-11:30",
        "2026-01-05T10:00:00.000000+00:00", "2026-01-05T10:00:00.120+00:00"]


@pytest.mark.parametrize("value", ECHO)
def test_a4_as_of_and_known_at_are_echoed_exactly(value):
    w, _, _ = hist()
    a = ok(me_at(w, "ada", value), 200)
    assert a["as_of"] == value and "known_at" not in a, a
    b = ok(me_at(w, "ada", None, value), 200)
    assert b["known_at"] == value and "as_of" not in b, b
    c = ok(me_at(w, "ada", value, value), 200)
    assert c["as_of"] == value and c["known_at"] == value
    s = ok(statement(w, "ada", **{"from": value, "to": "2999-01-01T00:00:00Z", "known_at": value}), 200)
    assert isinstance(s["entries"], list)


# RFC 3339 instants with an offset are valid; everything in BAD is something else
BAD = ["", "2026-01-05T10:00:00", "2026-01-05", "garbage", "10:00:00+00:00", "2026-13-05T10:00:00+00:00",
       "2026-02-30T10:00:00+00:00", "2026-01-05T24:30:00+00:00", "2026-01-05T10:61:00+00:00", "2026-01-05T10:00:61+00:00",
       "2026-01-05T10:00:00 00:00", "2026-01-05T10:00:00+00:00junk", " 2026-01-05T10:00:00+00:00", "2026-01-05T10:00+00:00",
       "20260105T100000Z", "1767607200", "2026-01-05T10:00:00.+00:00", "2026-1-5T10:00:00Z", "2026-01-05T10:00:00+24:00",
       "2026-01-05T10:00:00+00:60", "null", "2026-W02-1T10:00:00Z", "2026-01-05T10:00:00+0000", "2026-01-05T10:00:00+00",
       "2026-01-05T10:00:00,5Z", "-2026-01-05T10:00:00Z", "2026-01-05T10:00:00Z\x00", "２０２６-01-05T10:00:00Z",
       "2026-01-05T10:00:00+00:00,2026-01-05T10:00:00+00:00"]
# spellings RFC 3339 tolerates or leaves open, and extreme values: 200 or 422, never a server error
OPEN = ["2026-01-05 10:00:00+00:00", "2026-01-05t10:00:00z", "2026-06-30T23:59:60Z", "2026-01-05T10:00:00-00:00",
        "0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59", "0000-01-01T00:00:00Z", "0001-01-01T00:00:00Z",
        "9999-12-31T23:59:59.999999999Z", "2026-01-05T10:00:00." + "9" * 400 + "Z", "2026-02-29T00:00:00Z",
        "2024-02-29T00:00:00Z", "1969-12-31T23:59:59Z", "1900-01-01T00:00:00Z", "2026-01-05T10:00:00.5+23:59"]


PLAINLY_VALID = ("2024-02-29T00:00:00Z", "1969-12-31T23:59:59Z", "1900-01-01T00:00:00Z", "0001-01-01T00:00:00Z",
                 "2026-01-05t10:00:00z", "2026-01-05T10:00:00-00:00", "9999-12-31T23:59:59.999999999Z",
                 "2026-01-05T10:00:00.5+23:59")


@pytest.mark.parametrize("target", ["me:as_of", "me:known_at", "statement:from", "statement:to", "statement:known_at"])
def test_a2_invalid_instants_are_422(target):
    w, _, _ = hist()
    ep, param = target.split(":")
    wrong = []
    for value in BAD:
        r = GET(f"/{ep}?{q(**{param: value})}", w.t("ada"))
        if r.status_code != 422 or code_of(r) != "validation_failed":
            wrong.append((value, r.status_code, code_of(r)))
    assert not wrong, f"{target}: expected 422 validation_failed for {wrong}"
    # the raw '+' of an unencoded offset is a space after decoding
    r = GET(f"/{ep}?{param}=2026-01-05T10:00:00+00:00", w.t("ada"))
    assert r.status_code in (200, 422), r.text[:200]
    soft(r.status_code == 422, "unencoded-plus-offset-accepted", target=target)
    for value in OPEN:
        r = GET(f"/{ep}?{q(**{param: value})}", w.t("ada"))
        assert r.status_code in (200, 422), f"{target}={value[:40]}: {r.status_code} {r.text[:200]}"
        if r.status_code == 422:
            err(r, 422, "validation_failed")
        if value in PLAINLY_VALID:
            soft(r.status_code == 200, "valid-looking-instant-refused", target=target, value=value[:40])
    # repeated parameter and no 5xx; an unknown parameter is ignored
    r = GET(f"/{ep}?{param}=2026-01-05T10%3A00%3A00Z&{param}=2027-01-05T10%3A00%3A00Z", w.t("ada"))
    assert r.status_code in (200, 422)
    assert GET(f"/{ep}?nonsense=1&as_off=x", w.t("ada")).status_code == 200


def test_a2_temporal_parameters_need_a_token_and_future_is_valid():
    w, _, _ = hist()
    err(GET("/me?as_of=2026-01-05T10%3A00%3A00Z"), 401, "unauthenticated")
    err(GET("/statement"), 401, "unauthenticated")
    err(GET("/statement", "not-a-token"), 401, "unauthenticated")
    far = fmt(now_f() + 86400 * 3650)
    b = ok(me_at(w, "ada", far, far), 200)
    assert b["balance"] == 9540 and b["as_of"] == far and b["known_at"] == far
    b = ok(me_at(w, "ada", None, far), 200)
    assert b["balance"] == 9540


# ---------------------------------------------------------------- R. revisions

def test_r1_r2_revisions_of_plain_seeded_and_linked_payments():
    w = World(fixture(payments=[sp("p_seed", "ada", "bob", 500, fmt(ago(2), 60), "public", "coffee"),
                                sp("p_priv", "bob", "cy", 5, None, "private")],
                      users=[user("ada", 10000), user("bob", 2500), user("cy", 5), user("dan", 500), user("op", 1000)])).login_all()
    feed = {p["payment_id"]: p for h in ("ada", "bob", "cy") for p in w.activity(h)}
    for pid, parties, third in (("p_seed", ("ada", "bob"), ("cy", "dan", "op")), ("p_priv", ("bob", "cy"), ("ada", "op"))):
        for h in parties:
            j = ok(revisions(w, h, pid), 200)
            assert set(j) == {"revisions"} and len(j["revisions"]) == 1, j
            r1 = check_revision(j["revisions"][0], payment_id=pid, revision=1, amount=feed[pid]["amount"], reason="")
            assert inst(r1["effective_at"]) == inst(r1["recorded_at"]) == inst(feed[pid]["created_at"])
            soft(r1["effective_at"] == r1["recorded_at"] == feed[pid]["created_at"], "revision-1-instants-not-verbatim",
                 got=[r1["effective_at"], r1["recorded_at"]], want=feed[pid]["created_at"])
        for h in third:
            err(revisions(w, h, pid), 404, "not_found", f"{h} reading revisions of {pid}")
    err(GET("/payments/p_seed/revisions"), 401, "unauthenticated")
    err(GET("/payments/p_seed/revisions", "bogus"), 401, "unauthenticated")
    err(revisions(w, "ada", "p_nope"), 404, "not_found")
    for odd in ("", "a/b", "ünï-😀", "x" * 300, "%00", "..", "p_seed/extra"):
        r = call("GET", f"/payments/{odd}/revisions", w.t("ada"), kind="any")
        assert r.status_code in (404, 400, 422, 405), f"{odd!r}: {r.status_code}"
    # an API payment, a request payment, a settlement member, a capture
    p = ok(w.pay("ada", "bob", 100, visibility="private"), 201)
    rq = w.new_request("bob", "ada", 40)
    pr = ok(w.pay_request("ada", rq["request_id"]), 201)
    st = ok(POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 11},
                                                           {"from_handle": "bob", "to_handle": "cy", "amount": 3, "visibility": "private"}]}, key=k()), 201)
    a = w.new_auth("ada", "dan", 200)
    cap = ok(w.capture("dan", a["authorization_id"], body={"amount": 150}), 201)
    for pay, parties, third in ((p, ("ada", "bob"), ("cy", "op")), (pr, ("ada", "bob"), ("cy",)),
                                (st["payments"][0], ("ada", "bob"), ("cy", "op")), (st["payments"][1], ("bob", "cy"), ("ada", "op")),
                                (cap, ("ada", "dan"), ("bob", "op"))):
        for h in parties:
            j = ok(revisions(w, h, pay["payment_id"]), 200)["revisions"]
            assert len(j) == 1
            r1 = check_revision(j[0], payment_id=pay["payment_id"], revision=1, amount=pay["amount"], reason="")
            assert inst(r1["effective_at"]) == inst(r1["recorded_at"]) == inst(pay["created_at"])
        for h in third:
            err(revisions(w, h, pay["payment_id"]), 404, "not_found")
    assert inst(st["payments"][0]["created_at"]) == inst(st["committed_at"]) == inst(st["payments"][1]["created_at"])
    # POST and other methods on the read route are not a server error
    for method in ("POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
        r = call(method, f"/payments/{p['payment_id']}/revisions", w.t("ada"), kind="any")
        assert r.status_code < 500 and r.status_code != 200 or method in ("HEAD", "OPTIONS"), (method, r.status_code)
