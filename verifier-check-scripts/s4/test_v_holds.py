"""O. Historical holds: GET /me?as_of=T&known_at=K with authorisations, captures, voids and expiry; closed_at."""
import random
import time
from fractions import Fraction

import pytest

from lib import (POST, US, World, build_model, check_auth, check_everything, correct, err, fixture, fmt, inst, iso, k,
                 me_at, now_f, ok, seeded_auth, soft, statement, user)
from test_r_time import ago, sp


def view(w, h, T=None, K=None):
    b = ok(me_at(w, h, fmt(T) if T is not None else None, fmt(K) if K is not None else None), 200)
    assert b["balance"] == b["total"] and b["available"] == b["total"] - b["held"], b
    return (b["total"], b["held"], b["available"])


def test_o1_o2_o3_o4_lifecycle_with_two_captures():
    w = World().login_all()
    a = check_auth(w.new_auth("ada", "bob", 2000), closed_at=None)
    aid = a["authorization_id"]
    time.sleep(0.15)
    c1 = ok(w.capture("bob", aid, body={"amount": 500, "final": False}), 201)
    mid = check_auth(w.auth("ada", aid), status="open", closed_at=None, remaining_amount=1500)
    time.sleep(0.15)
    c2 = ok(w.capture("bob", aid, body={"amount": 700}), 201)
    done = check_auth(w.auth("ada", aid), status="captured", remaining_amount=0, captured_amount=1200)
    assert done == w.auth("bob", aid)
    ta, t1, t2, e = inst(a["created_at"]), inst(c1["created_at"]), inst(c2["created_at"]), inst(a["expires_at"])
    assert ta < t1 < t2 < e
    assert done["closed_at"] is not None, "closed_at is the event time once the authorisation is closed"
    assert inst(done["closed_at"]) == t2, f"closed_at {done['closed_at']} is not the time of the final capture {c2['created_at']}"
    far = now_f() + 86400
    v = lambda T=None, K=None: view(w, "ada", T, K)  # noqa: E731
    assert v(ta - US) == (10000, 0, 10000), "no hold before the authorisation was created"
    assert v(ta) == (10000, 2000, 8000), "a hold starts at authorisation creation"
    assert v(t1 - US) == (10000, 2000, 8000)
    assert v(t1) == (9500, 1500, 8000), "a non-final capture reduces the hold at capture time and moves the money"
    assert v(t2 - US) == (9500, 1500, 8000)
    assert v(t2) == (8800, 0, 8800), "a final capture releases the remainder at that event's time"
    assert v(far) == (8800, 0, 8800) and v() == (8800, 0, 8800)
    # what was known when
    assert v(far, ta - US) == (10000, 0, 10000), "before the creation was known there is nothing"
    assert v(t2, ta) == (10000, 2000, 8000), "with only the creation known, the captures are not applied"
    assert v(e - US, ta) == (10000, 2000, 8000)
    assert v(e, ta) == (10000, 0, 10000), "once the creation is known the expiry deadline is known too"
    assert v(t2, t1) == (9500, 1500, 8000) and v(e, t1) == (9500, 0, 9500)
    assert v(t2, t2) == (8800, 0, 8800) and v(t1, t2) == (9500, 1500, 8000) and v(ta, far) == (10000, 2000, 8000)
    assert view(w, "bob", t1) == (3000, 0, 3000) and view(w, "bob", t2) == (3700, 0, 3700) and view(w, "bob", ta) == (2500, 0, 2500)
    check_everything(w, build_model(w), random.Random(21), me_points=60, st_points=10)


def test_o2_o3_o4_void_and_partial_capture_then_void():
    w = World().login_all()
    a = w.new_auth("ada", "bob", 300)
    b = w.new_auth("ada", "cy", 1000)
    time.sleep(0.15)
    cb = ok(w.capture("cy", b["authorization_id"], body={"amount": 400, "final": False}), 201)
    time.sleep(0.15)
    va = ok(w.void("ada", a["authorization_id"]), 200)
    time.sleep(0.15)
    vb = ok(w.void("ada", b["authorization_id"]), 200)
    check_auth(va, status="voided", remaining_amount=0)
    check_auth(vb, status="voided", remaining_amount=0, captured_amount=400)
    assert va["closed_at"] is not None and vb["closed_at"] is not None
    ta, tb, tc, tva, tvb = (inst(a["created_at"]), inst(b["created_at"]), inst(cb["created_at"]), inst(va["closed_at"]),
                            inst(vb["closed_at"]))
    assert ta < tb < tc < tva < tvb <= now_f() + 2
    assert ok(w.void("ada", a["authorization_id"]), 200)["closed_at"] == va["closed_at"], "voiding again keeps the event time"
    v = lambda T=None, K=None: view(w, "ada", T, K)  # noqa: E731
    assert v(tb) == (10000, 1300, 8700) and v(tc) == (9600, 900, 8700)
    assert v(tva - US) == (9600, 900, 8700) and v(tva) == (9600, 600, 9000)
    assert v(tvb - US) == (9600, 600, 9000) and v(tvb) == (9600, 0, 9600) and v() == (9600, 0, 9600)
    assert v(tvb, tva) == (9600, 600, 9000), "a void recorded after known_at is not applied"
    assert v(tvb, tc) == (9600, 900, 8700) and v(tvb, tb) == (10000, 1300, 8700) and v(tvb, ta) == (10000, 300, 9700)
    assert v(inst(b["expires_at"]), tb) == (10000, 0, 10000)
    assert ok(statement(w, "ada"), 200)["entries"][0]["payment"] == cb and len(ok(statement(w, "ada"), 200)["entries"]) == 1
    check_everything(w, build_model(w), random.Random(22), me_points=60, st_points=10)


def test_o2_o3_o4_expiry_takes_effect_at_expires_at():
    w = World(fixture(ttl=2)).login_all()
    a = w.new_auth("ada", "bob", 400)
    b = w.new_auth("ada", "cy", 600)
    cb = ok(w.capture("cy", b["authorization_id"], body={"amount": 100, "final": False}), 201)
    ta, ea, tb, eb, tc = (inst(a["created_at"]), inst(a["expires_at"]), inst(b["created_at"]), inst(b["expires_at"]),
                          inst(cb["created_at"]))
    assert ea == ta + 2 and eb == tb + 2
    v = lambda T=None, K=None: view(w, "ada", T, K)  # noqa: E731
    # still open: queries beyond now see the hold expire at its deadline
    assert v() == (9900, 900, 9000)
    assert v(ea - US) == (9900, 900, 9000), "before the deadline (in the future) the hold still stands"
    assert v(ea) == (9900, 500, 9400), "for a query beyond now an open hold expires at its deadline"
    assert v(eb) == (9900, 0, 9900) and v(now_f() + 86400) == (9900, 0, 9900)
    time.sleep(2.4)
    assert v() == (9900, 0, 9900)
    xa = check_auth(w.auth("ada", a["authorization_id"]), status="expired", remaining_amount=0)
    xb = check_auth(w.auth("ada", b["authorization_id"]), status="expired", remaining_amount=0, captured_amount=100)
    assert xa["closed_at"] is not None and inst(xa["closed_at"]) == ea, f"closed_at {xa['closed_at']} is not expires_at {a['expires_at']}"
    assert inst(xb["closed_at"]) == eb
    # history is unchanged by the expiry having happened
    assert v(ta - US) == (10000, 0, 10000) and v(ta) == (10000, 400, 9600) and v(tc) == (9900, 900, 9000)
    assert v(ea - US) == (9900, 900, 9000) and v(ea) == (9900, 500, 9400) and v(eb - US) == (9900, 500, 9400)
    assert v(eb) == (9900, 0, 9900)
    assert v(eb, ta) == (10000, 0, 10000) and v(ea - US, ta) == (10000, 400, 9600)
    assert v(ea, tb) == (10000, 600, 9400), "known_at before the capture: the second hold is whole until its own deadline"
    check_everything(w, build_model(w), random.Random(23), me_points=60, st_points=10)


def test_o5_seeded_open_holds():
    t3 = ago(3)
    auths = [seeded_auth("a_dated", "ada", "bob", 700, created_at=fmt(t3, 120)), seeded_auth("a_plain", "ada", "cy", 300)]
    before = now_f()
    w = World(fixture(auths=auths)).login_all()
    after = now_f()
    got = {a["authorization_id"]: check_auth(a, status="open", closed_at=None) for a in w.auths("ada")}
    assert inst(got["a_dated"]["created_at"]) == t3, "a supplied created_at is the creation time of a seeded hold"
    assert before - 2 <= inst(got["a_plain"]["created_at"]) <= after + 2, "a seeded open hold is assumed created at reset"
    v = lambda T=None, K=None: view(w, "ada", T, K)  # noqa: E731
    assert v() == (10000, 1000, 9000)
    assert v(t3 - US) == (10000, 0, 10000) and v(t3) == (10000, 700, 9300) and v(before - 5) == (10000, 700, 9300)
    assert v(after + 5) == (10000, 1000, 9000)
    assert v(after + 5, t3 - US) == (10000, 0, 10000) and v(after + 5, t3) == (10000, 700, 9300)
    assert v(inst(got["a_dated"]["expires_at"])) in ((10000, 0, 10000), (10000, 300, 9700))
    check_everything(w, build_model(w), random.Random(24), me_points=60, st_points=6)
    # the dated hold limits a correction in the past: money that arrived today cannot fund a payment made then
    p = ok(w.pay("ada", "dan", 100), 201)
    ok(w.pay("bob", "ada", 2500), 201)
    assert v() == (12400, 1000, 11400)
    err(correct(w, "ada", p["payment_id"], 1, 9400, fmt(t3 + 3600), "9400 while 700 of 10000 were held"), 409, "historical_overdraft")
    ok(correct(w, "ada", p["payment_id"], 1, 9000, fmt(t3 + 3600), "9000 fits beside 700 then and 1000 at reset"), 201)
    assert v() == (3500, 1000, 2500)
    assert v(t3 + 3600) == (1000, 700, 300)


def test_o5_seeded_closed_holds_hold_nothing():
    t3 = ago(3)
    auths = [seeded_auth("a_cap", "ada", "bob", 700, status="captured", expires_in=-7200),
             seeded_auth("a_void", "ada", "bob", 300, status="voided"),
             seeded_auth("a_exp", "ada", "bob", 200, status="expired", expires_in=-7200),
             seeded_auth("a_late", "ada", "bob", 100, status="open", expires_in=-7200, created_at=fmt(t3))]
    w = World(fixture(auths=auths)).login_all()
    got = {a["authorization_id"]: check_auth(a) for a in w.auths("ada")}
    assert got["a_late"]["status"] == "expired"
    for aid, a in got.items():
        soft(a["closed_at"] is not None, "seeded-closed-hold-without-closed_at", id=aid)
    assert view(w, "ada") == (10000, 0, 10000)
    for T in (t3 - 86400, t3 + 3600, now_f() - 3600, now_f() + 86400):
        t = view(w, "ada", T)
        assert t[0] == 10000
        soft(t[1] == 0 or (T >= t3 and T < now_f() - 7200 and t[1] == 100), "seeded-closed-hold-holds-in-history", held=t[1], at=fmt(T))


@pytest.mark.parametrize("value", ["FUTURE", "2026-01-05T10:00:00", "garbage", "", 5])
def test_o5_bad_seeded_authorization_created_at(value):
    w = World().login_all()
    snap = w.snapshot()
    v = fmt(now_f() + 3600) if value == "FUTURE" else value
    r = POST("/_test/reset", body=fixture(auths=[seeded_auth("a_x", "ada", "bob", 700, created_at=v)]))
    if value == "FUTURE":
        assert r.status_code in (204, 422), r.text[:200]
        soft(r.status_code == 422, "seeded-authorisation-created_at-in-the-future-accepted")
        return
    err(r, (400, 422), ("validation_failed", "malformed_request"))
    assert w.snapshot() == snap


def test_o6_capture_is_a_payment_at_capture_time_and_cannot_be_corrected():
    w = World().login_all()
    a = w.new_auth("ada", "bob", 500, note="deposit", visibility="private")
    time.sleep(0.1)
    c = ok(w.capture("bob", a["authorization_id"], body={"amount": 200}), 201)
    tc = inst(c["created_at"])
    assert view(w, "bob", tc - US) == (2500, 0, 2500) and view(w, "bob", tc) == (2700, 0, 2700)
    for h, d in (("ada", -200), ("bob", 200)):
        s = ok(statement(w, h), 200)
        assert len(s["entries"]) == 1 and s["entries"][0]["payment"] == c and s["entries"][0]["delta"] == d
        assert s["entries"][0]["payment"]["authorization_id"] == a["authorization_id"]
    err(correct(w, "ada", c["payment_id"], 1, 100, c["created_at"]), 422, "linked_payment_immutable")
    err(correct(w, "bob", c["payment_id"], 1, 100, c["created_at"]), (403, 422), ("forbidden", "linked_payment_immutable"))
    assert view(w, "ada") == (9800, 0, 9800)
