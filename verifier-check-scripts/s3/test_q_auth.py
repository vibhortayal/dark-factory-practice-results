"""Q / P. Authorisations and captures: API and invariants (stage-2 specification)."""
import copy
import json
import threading
import time

import pytest

from lib import (BASE2, GET, POST, PW, World, assert_newest_first, burst, call, check_auth, check_payment, code_of,
                 err, fixture, iso, k, ok, seeded_auth, soft, statuses, ts, user)


@pytest.fixture()
def w():
    return World().login_all()


def cap(w, who, aid, body=None, key=None):
    return w.capture(who, aid, key=key, body=body)


# ---------------------------------------------------------------- Q1 /me

def test_q1_me_fields_without_holds(w):
    m = w.wallet("ada")
    assert (m["balance"], m["total"], m["available"], m["held"]) == (10000, 10000, 10000, 0)
    assert set(m) >= {"user_id", "display_name", "handle", "balance", "total", "available", "held", "currency",
                      "minor_units"}
    s = w.signup("fresh@example.com")
    m = ok(GET("/me", s["token"]), 200)
    assert (m["balance"], m["total"], m["available"], m["held"]) == (0, 0, 0, 0)


def test_q1_me_with_hold(w):
    a = w.new_auth("ada", "bob", 2000, note="deposit")
    m = w.wallet("ada")
    assert (m["balance"], m["total"], m["available"], m["held"]) == (10000, 10000, 8000, 2000)
    b = w.wallet("bob")
    assert (b["total"], b["available"], b["held"]) == (2500, 2500, 0), "a hold moves no money and reserves nothing for the receiver"
    w.assert_conserved()
    ok(w.void("ada", a["authorization_id"]), 200)
    m = w.wallet("ada")
    assert (m["total"], m["available"], m["held"]) == (10000, 10000, 0)


# ---------------------------------------------------------------- Q2 insufficient funds against available

def test_q2_payments_requests_settlements_use_available(w):
    w.new_auth("ada", "bob", 8000)
    assert w.wallet("ada")["available"] == 2000
    before = w.snapshot()
    err(w.pay("ada", "cy", 2001), 409, "insufficient_funds")
    q = w.new_request("cy", "ada", 2001)
    q2 = w.new_request("cy", "ada", 2000)
    snap = w.snapshot()
    err(w.pay_request("ada", q["request_id"]), 409, "insufficient_funds")
    err(POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 2001}]},
             key=k()), 409, "insufficient_funds")
    err(w.authorize("ada", "cy", 2001), 409, "insufficient_funds")
    assert w.snapshot() == snap
    # net settlement: 2500 out, 500 in -> net 2000, exactly what is available
    st = ok(POST("/settlements", w.t("op"), {"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 2500},
        {"from_handle": "dan", "to_handle": "ada", "amount": 500}]}, key=k()), 201)
    assert all(p["authorization_id"] is None for p in st["payments"])
    m = w.wallet("ada")
    assert (m["total"], m["available"], m["held"]) == (8000, 0, 8000)
    err(w.pay("ada", "cy", 1), 409, "insufficient_funds")
    err(w.pay_request("ada", q2["request_id"]), 409, "insufficient_funds")
    w.assert_conserved()
    assert before["ada"]["me"][1]["held"] == 8000


def test_q2_payment_is_immediate_and_leaves_no_hold(w):
    p = check_payment(ok(w.pay("ada", "bob", 1500), 201), authorization_id=None, request_id=None)
    a, b = w.wallet("ada"), w.wallet("bob")
    assert (a["total"], a["available"], a["held"]) == (8500, 8500, 0)
    assert (b["total"], b["available"], b["held"]) == (4000, 4000, 0)
    assert w.auths("ada") == [] and w.auths("bob") == []
    assert p["payment_id"] in [x["payment_id"] for x in w.activity("bob")]
    q = w.new_request("bob", "ada", 10)
    pp = check_payment(ok(w.pay_request("ada", q["request_id"]), 201), authorization_id=None, request_id=q["request_id"])
    assert w.wallet("ada")["held"] == 0 and pp["amount"] == 10
    s = ok(POST("/splits", w.t("cy"), {"amount": 10 ** 9, "participant_handles": ["ada", "bob"]}, key=k()), 201)
    assert len(s["requests"]) == 2 and w.wallet("cy")["held"] == 0


def test_q2_available_exactly_spendable(w):
    w.new_auth("ada", "bob", 9000)
    ok(w.pay("ada", "cy", 1000), 201)
    m = w.wallet("ada")
    assert (m["total"], m["available"], m["held"]) == (9000, 0, 9000)
    err(w.pay("ada", "cy", 1), 409, "insufficient_funds")
    # received money becomes available at once
    ok(w.pay("bob", "ada", 7), 201)
    assert w.wallet("ada")["available"] == 7
    ok(w.pay("ada", "cy", 7), 201)


# ---------------------------------------------------------------- Q3 fixture

def test_q3_ttl_default_and_supplied():
    w = World(fixture())  # no ttl, no authorizations
    a = w.new_auth("ada", "bob", 10)
    assert (ts(a["expires_at"]) - ts(a["created_at"])).total_seconds() == 600
    assert w.auths("cy") == []
    for ttl in (1, 30, 86400, 1234):
        w = World(fixture(ttl=ttl))
        a = w.new_auth("ada", "bob", 10)
        assert (ts(a["expires_at"]) - ts(a["created_at"])).total_seconds() == ttl, a


@pytest.mark.parametrize("ttl", [0, -1, -600, 1.5, "600", True, False, [600], {"s": 600}, 0.0])
def test_q3_bad_ttl_rejected(ttl):
    w = World().login_all()
    before = w.snapshot()
    r = call("POST", "/_test/reset", body=fixture(ttl=ttl))
    err(r, (422, 400), ("validation_failed", "malformed_request"), repr(ttl))
    assert w.snapshot() == before


def test_q3_ttl_spellings_and_null():
    raw = json.dumps(fixture(ttl=777)).replace("777", "6e2")
    r = call("POST", "/_test/reset", raw=raw)
    if soft(r.status_code == 204, "ttl-6e2-rejected", status=r.status_code):
        w = World(fixture(), do_reset=False)
        a = w.new_auth("ada", "bob", 10)
        assert (ts(a["expires_at"]) - ts(a["created_at"])).total_seconds() == 600
    r = call("POST", "/_test/reset", body=fixture(ttl=None))
    assert r.status_code in (204, 422), r.text
    r = call("POST", "/_test/reset", raw=json.dumps(fixture(ttl=777)).replace("777", "9" * 400))
    assert r.status_code in (204, 422), r.text
    if r.status_code == 204:
        w = World(fixture(), do_reset=False)
        rr = w.authorize("ada", "bob", 10)
        assert rr.status_code < 500


def seeded_world(**kw):
    auths = [
        seeded_auth("a_open", "ada", "bob", 2000, note="deposit", visibility="public"),
        seeded_auth("a_open2", "ada", "cy", 500, note="prv", visibility="private", expires_in=3 * 3600),
        seeded_auth("a_cap", "ada", "bob", 700, status="captured", expires_in=-7200),
        seeded_auth("a_void", "ada", "bob", 800, status="voided"),
        seeded_auth("a_exp", "ada", "bob", 900, status="expired", expires_in=-7200),
        seeded_auth("a_clock", "ada", "bob", 9000, status="open", expires_in=-3700),   # open but past its deadline
        seeded_auth("a_in", "bob", "ada", 1000, note="incoming"),
        seeded_auth("a_other", "bob", "cy", 100),
    ]
    return World(fixture(auths=auths, **kw)), auths


def test_q3_seeded_authorizations_hold_only_when_open_and_unexpired():
    w, auths = seeded_world()
    a = w.wallet("ada")
    assert (a["total"], a["available"], a["held"]) == (10000, 7500, 2500)
    b = w.wallet("bob")
    assert (b["total"], b["available"], b["held"]) == (2500, 1400, 1100)
    c = w.wallet("cy")
    assert (c["total"], c["available"], c["held"]) == (0, 0, 0)
    by = {x["authorization_id"]: x for x in w.auths("ada")}
    assert set(by) == {"a_open", "a_open2", "a_cap", "a_void", "a_exp", "a_clock", "a_in"}
    check_auth(by["a_open"], from_user_id="u_ada", from_handle="ada", to_user_id="u_bob", to_handle="bob",
               amount=2000, captured_amount=0, remaining_amount=2000, currency="EUR", note="deposit",
               visibility="public", status="open", payment_id=None, payment_ids=[])
    assert ts(by["a_open"]["expires_at"]) == ts(auths[0]["expires_at"])
    soft(by["a_open"]["expires_at"] == auths[0]["expires_at"], "seeded-expires_at-respelled",
         given=auths[0]["expires_at"], got=by["a_open"]["expires_at"])
    check_auth(by["a_open2"], status="open", visibility="private", remaining_amount=500)
    check_auth(by["a_cap"], status="captured", remaining_amount=0)
    soft(by["a_cap"]["captured_amount"] == 700, "seeded-captured-amount", got=by["a_cap"]["captured_amount"])
    check_auth(by["a_void"], status="voided", remaining_amount=0, captured_amount=0)
    check_auth(by["a_exp"], status="expired", remaining_amount=0, captured_amount=0)
    check_auth(by["a_clock"], status="expired", remaining_amount=0, captured_amount=0)
    check_auth(by["a_in"], status="open", from_handle="bob", to_handle="ada")
    assert {x["authorization_id"] for x in w.auths("cy")} == {"a_open2", "a_other"}
    assert w.auths("dan") == [] and w.auths("op") == []
    # nothing seeded shows up in the feed
    for h in w.handles():
        assert w.activity(h) == []
    # seeded open holds are live
    p = check_payment(ok(w.capture("bob", "a_open", body={"amount": 1500}), 201), amount=1500, authorization_id="a_open",
                      from_handle="ada", to_handle="bob", note="deposit", visibility="public")
    a = w.wallet("ada")
    assert (a["total"], a["available"], a["held"]) == (8500, 8000, 500)
    assert ok(w.void("ada", "a_open2"), 200)["status"] == "voided"
    assert w.wallet("ada")["held"] == 0
    for aid in ("a_cap", "a_void"):
        err(w.capture("bob", aid), 409, "authorization_not_open", aid)
    err(w.capture("bob", "a_exp"), 409, ("authorization_not_open", "authorization_expired"))
    r = w.capture("bob", "a_clock")
    err(r, 409, ("authorization_expired", "authorization_not_open"))
    assert code_of(r) == "authorization_expired", "a seeded open authorisation past its deadline is expired by the clock"
    err(w.void("ada", "a_cap"), 409, "authorization_not_open")
    err(w.void("ada", "a_exp"), 409, "authorization_not_open")
    err(w.void("ada", "a_clock"), 409, "authorization_not_open")
    assert ok(w.void("ada", "a_void"), 200)["status"] == "voided"
    w.assert_conserved()
    assert p["payment_id"] in [x["payment_id"] for x in w.activity("dan")]


def test_q3_seeded_expires_at_spellings():
    auths = [seeded_auth("a_z", "ada", "bob", 10, expires_at=iso(7200, "Z")),
             {**seeded_auth("a_off", "ada", "bob", 10), "expires_at": "2099-01-01T10:00:00+02:00"},
             {**seeded_auth("a_frac", "ada", "bob", 10), "expires_at": "2099-01-01T10:00:00.250-05:30"}]
    r = call("POST", "/_test/reset", body=fixture(auths=auths))
    assert r.status_code == 204, r.text
    w = World(fixture(auths=auths), do_reset=False)
    by = {x["authorization_id"]: x for x in w.auths("ada")}
    for a in auths:
        assert ts(by[a["id"]]["expires_at"]) == ts(a["expires_at"]), (a["expires_at"], by[a["id"]]["expires_at"])
        assert by[a["id"]]["status"] == "open"
    assert w.wallet("ada")["held"] == 30


def test_q3_over_hold_is_a_reset_error():
    w = World().login_all()
    ok(w.pay("ada", "bob", 1), 201)
    before = w.snapshot()
    over = [seeded_auth("a1", "cy", "bob", 1)]                       # cy has 0
    err(call("POST", "/_test/reset", body=fixture(auths=over)), 422, "validation_failed")
    over = [seeded_auth("a1", "dan", "bob", 300), seeded_auth("a2", "dan", "ada", 201)]   # dan has 500
    err(call("POST", "/_test/reset", body=fixture(auths=over)), 422, "validation_failed")
    assert w.snapshot() == before
    # exactly the balance is fine; closed and clock-expired holds do not count
    fine = [seeded_auth("a1", "dan", "bob", 300), seeded_auth("a2", "dan", "ada", 200),
            seeded_auth("a3", "dan", "ada", 400, status="voided"), seeded_auth("a4", "dan", "ada", 400, status="captured"),
            seeded_auth("a5", "dan", "ada", 400, status="expired", expires_in=-7200),
            seeded_auth("a6", "dan", "ada", 400, status="open", expires_in=-7200)]
    assert call("POST", "/_test/reset", body=fixture(auths=fine)).status_code == 204
    w2 = World(fixture(auths=fine), do_reset=False)
    d = w2.wallet("dan")
    assert (d["total"], d["available"], d["held"]) == (500, 0, 500)
    err(w2.pay("dan", "ada", 1), 409, "insufficient_funds")


def _amut(fn):
    auths = [seeded_auth("a1", "ada", "bob", 100), seeded_auth("a2", "bob", "ada", 100)]
    fn(auths)
    return fixture(auths=auths)


BAD_AUTH_FIXTURES = {
    "unknown from": (lambda a: a[0].__setitem__("from_user_id", "u_ghost"), True),
    "unknown to": (lambda a: a[0].__setitem__("to_user_id", "u_ghost"), True),
    "from is a list": (lambda a: a[0].__setitem__("from_user_id", ["u_ada"]), True),
    "status pending": (lambda a: a[0].__setitem__("status", "pending"), True),
    "status null": (lambda a: a[0].__setitem__("status", None), True),
    "status number": (lambda a: a[0].__setitem__("status", 1), True),
    "expires_at words": (lambda a: a[0].__setitem__("expires_at", "tomorrow"), True),
    "expires_at without offset": (lambda a: a[0].__setitem__("expires_at", "2099-01-01T10:00:00"), True),
    "expires_at number": (lambda a: a[0].__setitem__("expires_at", 1790000000), True),
    "expires_at null": (lambda a: a[0].__setitem__("expires_at", None), True),
    "expires_at impossible date": (lambda a: a[0].__setitem__("expires_at", "2099-13-45T99:99:99+00:00"), True),
    "amount negative": (lambda a: a[0].__setitem__("amount", -5), True),
    "amount fraction": (lambda a: a[0].__setitem__("amount", 1.5), True),
    "amount string": (lambda a: a[0].__setitem__("amount", "100"), True),
    "amount null": (lambda a: a[0].__setitem__("amount", None), True),
    "duplicate id": (lambda a: a[1].__setitem__("id", "a1"), True),
    "id number": (lambda a: a[0].__setitem__("id", 5), True),
    "id 65 chars": (lambda a: a[0].__setitem__("id", "a" * 65), True),
    "missing id": (lambda a: a[0].pop("id"), True),
    "missing from": (lambda a: a[0].pop("from_user_id"), True),
    "missing to": (lambda a: a[0].pop("to_user_id"), True),
    "missing amount": (lambda a: a[0].pop("amount"), True),
    "missing status": (lambda a: a[0].pop("status"), False),   # first run: accepted as open; no statement requires the member
    "missing expires_at": (lambda a: a[0].pop("expires_at"), True),
    "record is a string": (lambda a: a.__setitem__(0, "a1"), True),
    "visibility friends": (lambda a: a[0].__setitem__("visibility", "friends"), True),
    "note number": (lambda a: a[0].__setitem__("note", 5), True),
    # the specification is silent on these; the map (E-11) rejects them
    "amount zero": (lambda a: a[0].__setitem__("amount", 0), False),
    "amount above 1e9": (lambda a: a[0].__setitem__("amount", 10 ** 9 + 1), False),
    "self authorisation": (lambda a: a[0].__setitem__("to_user_id", "u_ada"), False),
    "note 201 chars": (lambda a: a[0].__setitem__("note", "x" * 201), False),
}


@pytest.fixture(scope="module")
def base_world():
    w = World().login_all()
    ok(w.pay("ada", "bob", 100), 201)
    w.new_auth("ada", "bob", 50)
    return w, w.snapshot()


@pytest.mark.parametrize("name", list(BAD_AUTH_FIXTURES))
def test_q3_invalid_seeded_authorization(base_world, name):
    w, before = base_world
    mut, strict = BAD_AUTH_FIXTURES[name]
    r = call("POST", "/_test/reset", body=_amut(mut))
    assert r.status_code < 500
    if r.status_code == 204:
        base_world[0].__init__()
        w.login_all()
        ok(w.pay("ada", "bob", 100), 201)
        w.new_auth("ada", "bob", 50)
        base_world[1].clear()
        base_world[1].update(w.snapshot())
        if strict:
            pytest.fail(f"invalid seeded authorisation ({name}) accepted with 204")
        soft(False, "seeded-authorization-accepted", case=name)
        return
    err(r, (422, 400), ("validation_failed", "malformed_request"), name)
    assert w.snapshot() == before, f"state changed after rejected reset ({name})"


def test_q3_authorizations_not_an_array(base_world):
    w, before = base_world
    for bad in ("x", {"a": 1}, 5, True):
        f = fixture()
        f["authorizations"] = bad
        err(call("POST", "/_test/reset", body=f), (422, 400), ("validation_failed", "malformed_request"), repr(bad))
    assert w.snapshot() == before


# ---------------------------------------------------------------- Q4 expiry by the clock

def test_q4_expiry_without_any_request_at_the_deadline():
    w = World(fixture(ttl=2)).login_all()
    a = w.new_auth("ada", "bob", 3000, note="short")
    b = w.new_auth("ada", "bob", 1000)
    p1 = ok(w.capture("bob", b["authorization_id"], body={"amount": 400, "final": False}), 201)
    m = w.wallet("ada")
    assert (m["total"], m["available"], m["held"]) == (9600, 6000, 3600)
    assert w.auth("ada", a["authorization_id"])["status"] == "open"
    time.sleep(2.6)
    # first requests after the deadline, each on a different surface
    m = w.wallet("ada")
    assert (m["total"], m["available"], m["held"]) == (9600, 9600, 0), "expired holds must be released in /me"
    got = check_auth(w.auth("bob", a["authorization_id"]), status="expired", remaining_amount=0, captured_amount=0,
                     payment_ids=[], payment_id=None)
    assert got["expires_at"] == a["expires_at"]
    part = check_auth(w.auth("ada", b["authorization_id"]), status="expired", remaining_amount=0, captured_amount=400,
                      payment_ids=[p1["payment_id"]], payment_id=p1["payment_id"])
    assert part["amount"] == 1000
    assert [x["authorization_id"] for x in w.auths("ada", "status=open")] == []
    assert {x["authorization_id"] for x in w.auths("ada", "status=expired")} == {a["authorization_id"], b["authorization_id"]}
    err(w.capture("bob", a["authorization_id"]), 409, "authorization_expired")
    err(w.capture("bob", b["authorization_id"], body={"amount": 1}), 409, "authorization_expired")
    err(w.void("ada", a["authorization_id"]), 409, "authorization_not_open")
    # the released money is spendable
    ok(w.pay("ada", "cy", 9600), 201)
    w.assert_conserved()
    assert w.wallet("bob")["total"] == 2900


def test_q4_first_request_after_deadline_is_a_write():
    w = World(fixture(ttl=2)).login_all()
    a = w.new_auth("ada", "bob", 10000)
    err(w.pay("ada", "cy", 1), 409, "insufficient_funds")
    time.sleep(2.6)
    ok(w.pay("ada", "cy", 10000), 201)          # no read in between: the write itself must see the expiry
    w2 = World(fixture(ttl=2)).login_all()
    a = w2.new_auth("ada", "bob", 500)
    time.sleep(2.6)
    err(w2.capture("bob", a["authorization_id"]), 409, "authorization_expired")
    assert w2.wallet("bob")["total"] == 2500 and w2.wallet("ada")["held"] == 0
    w3 = World(fixture(ttl=2)).login_all()
    w3.new_auth("ada", "bob", 10000)
    time.sleep(2.6)
    ok(w3.authorize("ada", "cy", 10000), 201)   # a new hold may use what the expired one released


def test_q4_still_open_before_the_deadline():
    w = World(fixture(ttl=4)).login_all()
    a = w.new_auth("ada", "bob", 100)
    time.sleep(1.0)
    assert w.auth("ada", a["authorization_id"])["status"] == "open"
    assert w.wallet("ada")["held"] == 100
    ok(w.capture("bob", a["authorization_id"]), 201)


def test_q4_expiry_survives_export_import():
    w = World(fixture(ttl=2)).login_all()
    a = w.new_auth("ada", "bob", 700)
    e = call("GET", "/_test/export")
    time.sleep(2.6)
    assert call("POST", "/_test/import", raw=e.content).status_code == 204
    assert w.auth("ada", a["authorization_id"])["status"] == "expired"
    assert w.wallet("ada")["held"] == 0


# ---------------------------------------------------------------- Q5-Q7 create

def test_q5_create_shape_and_listing(w):
    r = POST("/authorizations", w.t("ada"), {"to_handle": "bob", "amount": 2000, "note": "deposit",
                                              "visibility": "private"}, key=k())
    a = check_auth(ok(r, 201), from_user_id="u_ada", from_handle="ada", to_user_id="u_bob", to_handle="bob",
                   amount=2000, captured_amount=0, remaining_amount=2000, currency="EUR", note="deposit",
                   visibility="private", status="open", payment_id=None, payment_ids=[])
    assert 1 <= len(a["authorization_id"]) <= 64
    assert (ts(a["expires_at"]) - ts(a["created_at"])).total_seconds() == 600
    d = check_auth(ok(w.authorize("ada", "bob", 1), 201), note="", visibility="public", amount=1)
    assert d["authorization_id"] != a["authorization_id"]
    assert [x["authorization_id"] for x in w.auths("ada")][:2] == [d["authorization_id"], a["authorization_id"]] or \
        {x["authorization_id"] for x in w.auths("ada")} == {d["authorization_id"], a["authorization_id"]}
    assert w.auth("ada", a["authorization_id"]) == a and w.auth("bob", a["authorization_id"]) == a
    assert w.auths("cy") == [] and w.auths("op") == []
    # Q7: never a feed item, for anyone
    for h in w.handles():
        assert w.activity(h) == []
    assert w.requests("ada") == [] and w.requests("bob") == []


def test_q6_create_errors(w):
    before = w.snapshot()
    err(w.authorize("ada", "bob", 10001), 409, "insufficient_funds")
    err(w.authorize("cy", "bob", 1), 409, "insufficient_funds")
    err(w.authorize("ada", "ada", 5), 422, "self_payment")
    err(w.authorize("ada", "nobody", 5), 404, "not_found")
    err(w.authorize("ada", "bob", 5, note="x" * 201), 422, "validation_failed")
    err(w.authorize("ada", "bob", 5, note=None), 422, "validation_failed")
    err(w.authorize("ada", "bob", 5, visibility="friends"), 422, "validation_failed")
    err(w.authorize("ada", "bob", 5, visibility=None), 422, "validation_failed")
    err(POST("/authorizations", w.t("ada"), {"amount": 5}, key=k()), 422, "validation_failed")
    err(POST("/authorizations", w.t("ada"), {"to_handle": "bob"}, key=k()), 422, "validation_failed")
    err(POST("/authorizations", w.t("ada"), {"to_handle": 5, "amount": 5}, key=k()), 400, "malformed_request")
    err(call("POST", "/authorizations", w.t("ada"), key=k(), raw="{nope"), 400, "malformed_request")
    err(POST("/authorizations", w.t("ada"), {"to_handle": "bob", "amount": 5}), 400, "missing_idempotency_key")
    err(POST("/authorizations", w.t("ada"), {"to_handle": "bob", "amount": 5}, key=""), 400, "missing_idempotency_key")
    err(POST("/authorizations", w.t("ada"), {"to_handle": "bob", "amount": 5}, key="k" * 256), 422, "validation_failed")
    err(POST("/authorizations", None, {"to_handle": "bob", "amount": 5}, key=k()), 401, "unauthenticated")
    err(call("POST", "/authorizations", "bogus", key=k(), body={"to_handle": "bob", "amount": 5}), 401, "unauthenticated")
    assert w.snapshot() == before
    ok(POST("/authorizations", w.t("ada"), {"to_handle": "bob", "amount": 5, "unknown": [1.5], "status": "captured",
                                             "expires_at": "2000-01-01T00:00:00+00:00"}, key="k" * 255), 201)
    a = w.auths("ada")[0]
    assert a["status"] == "open" and ts(a["expires_at"]) > ts(a["created_at"])


@pytest.mark.parametrize("raw,valid", [("1", True), ("1000.0", True), ("1e3", True), ("1000000000", True), ("0", False),
                                       ("-1", False), ("1.5", False), ('"100"', False), ("true", False), ("null", False),
                                       ("1000000001", False), ("0.99999999999999999999", False), ("[]", False),
                                       ("1e99999999999999999999", False), ("9" * 4400, False)])
def test_q6_authorization_amount_rules(raw, valid):
    w = World(fixture(users=[user("ada", 10 ** 12), user("bob", 0)]))
    r = call("POST", "/authorizations", w.t("ada"), key=k(), raw='{"to_handle":"bob","amount":%s}' % raw)
    if valid:
        assert type(ok(r, 201)["amount"]) is int
    else:
        err(r, 422, "validation_failed", raw[:30])
        assert w.wallet("ada")["held"] == 0


def test_q6_holds_stack_up_to_available(w):
    w.new_auth("ada", "bob", 4000)
    w.new_auth("ada", "cy", 4000)
    err(w.authorize("ada", "dan", 2001), 409, "insufficient_funds")
    w.new_auth("ada", "dan", 2000)          # exactly what is left
    m = w.wallet("ada")
    assert (m["total"], m["available"], m["held"]) == (10000, 0, 10000)
    err(w.authorize("ada", "dan", 1), 409, "insufficient_funds")
    err(w.pay("ada", "dan", 1), 409, "insufficient_funds")
    # the receivers hold nothing and cannot spend what is merely reserved for them
    err(w.pay("cy", "ada", 1), 409, "insufficient_funds")
    w.assert_conserved()


# ---------------------------------------------------------------- Q8-Q10 capture

def test_q8_final_capture_default(w):
    a = w.new_auth("ada", "bob", 2000, note="deposit ☕", visibility="private")
    aid = a["authorization_id"]
    r = w.capture("bob", aid, body={"amount": 1500})
    p = check_payment(ok(r, 201), from_user_id="u_ada", from_handle="ada", to_user_id="u_bob", to_handle="bob",
                      amount=1500, currency="EUR", note="deposit ☕", visibility="private", request_id=None,
                      settlement_id=None, authorization_id=aid)
    m = w.wallet("ada")
    assert (m["total"], m["available"], m["held"]) == (8500, 8500, 0), "the uncaptured 500 is released in the same step"
    assert w.wallet("bob")["total"] == 4000
    got = check_auth(w.auth("ada", aid), status="captured", captured_amount=1500, remaining_amount=0,
                     payment_id=p["payment_id"], payment_ids=[p["payment_id"]], amount=2000)
    assert w.auth("bob", aid) == got
    # feed: a private capture is seen by its two parties only
    for h, sees in (("ada", True), ("bob", True), ("cy", False), ("op", False)):
        assert (p["payment_id"] in [x["payment_id"] for x in w.activity(h)]) == sees, h
    assert [x for x in w.activity("bob") if x["payment_id"] == p["payment_id"]][0] == p
    err(w.capture("bob", aid), 409, "authorization_not_open")
    err(w.capture("bob", aid, body={"amount": 1}), 409, "authorization_not_open")
    err(w.void("ada", aid), 409, "authorization_not_open")
    w.assert_conserved()


def test_q8_capture_defaults_to_everything(w):
    a = w.new_auth("ada", "bob", 2000)
    p = check_payment(ok(w.capture("bob", a["authorization_id"], body={}), 201), amount=2000, visibility="public",
                      note="", authorization_id=a["authorization_id"])
    check_auth(w.auth("ada", a["authorization_id"]), status="captured", captured_amount=2000, remaining_amount=0)
    assert p["payment_id"] in [x["payment_id"] for x in w.activity("cy")]
    # body-less capture
    b = w.new_auth("ada", "bob", 30)
    r = call("POST", f"/authorizations/{b['authorization_id']}/capture", w.t("bob"), key=k())
    if soft(r.status_code == 201, "capture-without-body-refused", status=r.status_code):
        assert r.json()["amount"] == 30


def test_q8_capture_spends_reserved_money_when_available_is_zero(w):
    a = w.new_auth("ada", "bob", 10000)
    assert w.wallet("ada")["available"] == 0
    ok(w.capture("bob", a["authorization_id"]), 201)
    m = w.wallet("ada")
    assert (m["total"], m["available"], m["held"]) == (0, 0, 0)
    assert w.wallet("bob")["total"] == 12500
    w.assert_conserved()


def test_q10_extended_capture_mode(w):
    a = w.new_auth("ada", "bob", 2000, note="multi")
    aid = a["authorization_id"]
    p1 = check_payment(ok(w.capture("bob", aid, body={"amount": 700, "final": False}), 201), amount=700,
                       authorization_id=aid, note="multi")
    x = check_auth(w.auth("ada", aid), status="open", captured_amount=700, remaining_amount=1300,
                   payment_id=p1["payment_id"], payment_ids=[p1["payment_id"]])
    m = w.wallet("ada")
    assert (m["total"], m["available"], m["held"]) == (9300, 8000, 1300)
    err(w.capture("bob", aid, body={"amount": 1301, "final": False}), 422, "capture_exceeds_authorization")
    err(w.capture("bob", aid, body={"amount": 1301}), 422, "capture_exceeds_authorization")
    err(w.capture("bob", aid, body={"amount": 2000}), 422, "capture_exceeds_authorization")
    p2 = ok(w.capture("bob", aid, body={"amount": 300, "final": False}), 201)
    x = check_auth(w.auth("bob", aid), status="open", captured_amount=1000, remaining_amount=1000,
                   payment_id=p2["payment_id"], payment_ids=[p1["payment_id"], p2["payment_id"]])
    p3 = ok(w.capture("bob", aid, body={"amount": 400}), 201)           # final: closes and releases 600
    x = check_auth(w.auth("ada", aid), status="captured", captured_amount=1400, remaining_amount=0,
                   payment_id=p3["payment_id"], payment_ids=[p1["payment_id"], p2["payment_id"], p3["payment_id"]])
    m = w.wallet("ada")
    assert (m["total"], m["available"], m["held"]) == (8600, 8600, 0)
    assert w.wallet("bob")["total"] == 3900
    err(w.capture("bob", aid, body={"amount": 1, "final": False}), 409, "authorization_not_open")
    feed = [p for p in w.activity("cy") if p["authorization_id"] == aid]
    assert sorted(p["amount"] for p in feed) == [300, 400, 700] and len({p["payment_id"] for p in feed}) == 3
    w.assert_conserved()


def test_q10_nonfinal_capture_of_the_whole_remainder_closes(w):
    a = w.new_auth("ada", "bob", 500)
    aid = a["authorization_id"]
    ok(w.capture("bob", aid, body={"amount": 200, "final": False}), 201)
    p = ok(w.capture("bob", aid, body={"final": False}), 201)       # amount omitted: the remainder
    assert p["amount"] == 300
    check_auth(w.auth("ada", aid), status="captured", captured_amount=500, remaining_amount=0)
    err(w.capture("bob", aid, body={"final": False}), 409, "authorization_not_open")
    b = w.new_auth("ada", "bob", 500)
    ok(w.capture("bob", b["authorization_id"], body={"amount": 500, "final": False}), 201)
    check_auth(w.auth("ada", b["authorization_id"]), status="captured", captured_amount=500, remaining_amount=0)
    c = w.new_auth("ada", "bob", 500)
    ok(w.capture("bob", c["authorization_id"], body={"amount": 100, "final": True}), 201)
    check_auth(w.auth("ada", c["authorization_id"]), status="captured", captured_amount=100, remaining_amount=0)
    assert w.wallet("ada")["held"] == 0


def test_q13_void_after_partial_capture_keeps_records(w):
    a = w.new_auth("ada", "bob", 2000)
    aid = a["authorization_id"]
    p1 = ok(w.capture("bob", aid, body={"amount": 700, "final": False}), 201)
    v = check_auth(ok(w.void("ada", aid), 200), status="voided", captured_amount=700, remaining_amount=0,
                   payment_id=p1["payment_id"], payment_ids=[p1["payment_id"]], amount=2000)
    m = w.wallet("ada")
    assert (m["total"], m["available"], m["held"]) == (9300, 9300, 0)
    assert ok(w.void("ada", aid), 200) == v
    err(w.capture("bob", aid, body={"amount": 1, "final": False}), 409, "authorization_not_open")
    assert p1["payment_id"] in [x["payment_id"] for x in w.activity("bob")]


# ---------------------------------------------------------------- Q11 capture errors

def test_q11_capture_errors(w):
    a = w.new_auth("ada", "bob", 1000)
    aid = a["authorization_id"]
    before = w.snapshot()
    err(w.capture("bob", "a_does_not_exist"), 404, "not_found")
    err(w.capture("ada", aid), 403, "forbidden")               # the payer is not the receiver
    err(w.capture("cy", aid), 403, "forbidden")                # neither party
    err(w.capture("op", aid), 403, "forbidden")                # operator permission grants nothing here
    for bad in (0, -1, 1.5, "5", True, None, [], {}):
        err(w.capture("bob", aid, body={"amount": bad}), 422, "validation_failed", f"amount {bad!r}")
    err(w.capture("bob", aid, body={"amount": 1001}), 422, "capture_exceeds_authorization")
    r = w.capture("bob", aid, body={"amount": 10 ** 9 + 1})
    err(r, 422, ("capture_exceeds_authorization", "validation_failed"))
    r = call("POST", f"/authorizations/{aid}/capture", w.t("bob"), key=k(), raw='{"amount": 1e99999999999999999999}')
    err(r, 422, ("capture_exceeds_authorization", "validation_failed"))
    for bad in ("no", 1, None, "false", []):
        r = w.capture("bob", aid, body={"amount": 1, "final": bad})
        err(r, (400, 422), ("malformed_request", "validation_failed"), f"final {bad!r}")
        soft(r.status_code == 400, "final-wrong-type-422", value=repr(bad))
    err(call("POST", f"/authorizations/{aid}/capture", w.t("bob"), body={}), 400, "missing_idempotency_key")
    err(call("POST", f"/authorizations/{aid}/capture", w.t("bob"), body={}, key="k" * 256), 422, "validation_failed")
    err(call("POST", f"/authorizations/{aid}/capture", None, body={}, key=k()), 401, "unauthenticated")
    err(call("POST", f"/authorizations/{aid}/capture", w.t("bob"), key=k(), raw="{nope"), 400, "malformed_request")
    err(call("POST", f"/authorizations/{aid}/capture", w.t("bob"), key=k(), raw="[]"), (400, 422))
    assert w.snapshot() == before
    # unknown fields are ignored
    ok(w.capture("bob", aid, body={"amount": 10, "final": False, "tip": 0.5, "to_handle": "cy"}), 201)
    assert w.wallet("cy")["total"] == 0
    ok(w.void("ada", aid), 200)
    err(w.capture("bob", aid, body={"amount": 1}), 409, "authorization_not_open")
    err(w.capture("cy", aid), (403, 409), ("forbidden", "authorization_not_open"))


@pytest.mark.parametrize("aid", ["nope", "a_999999", "x" * 65, "%20", "😀", "a%2Fb", "0", "null"])
@pytest.mark.parametrize("action", ["capture", "void"])
def test_q11_unknown_authorization_404(w, aid, action):
    r = POST(f"/authorizations/{aid}/{action}", w.t("ada"), {}, key=k() if action == "capture" else None)
    err(r, 404, "not_found", f"{action} {aid}")


@pytest.mark.parametrize("method,path", [("GET", "/authorizations/x"), ("GET", "/authorizations/x/capture"),
                                         ("POST", "/authorizations/x/refund"), ("DELETE", "/authorizations/x"),
                                         ("PUT", "/authorizations"), ("GET", "/authorizations/x/void"),
                                         ("PATCH", "/authorizations/x/capture")])
def test_q11_other_routes_and_methods_are_json_4xx(w, method, path):
    r = call(method, path, w.t("ada"))
    assert 400 <= r.status_code < 500 and isinstance(code_of(r), str), f"{method} {path}: {r.status_code} {r.text[:120]}"


# ---------------------------------------------------------------- Q12 idempotency specifics of the new paths

def test_q12_capture_body_identity(w):
    a = w.new_auth("ada", "bob", 2000)
    path = f"/authorizations/{a['authorization_id']}/capture"
    key = k()
    p = ok(POST(path, w.t("bob"), {}, key=key), 201)
    assert p["amount"] == 2000
    for other in ({"amount": 2000}, {"final": True}, {"amount": 2000, "final": True}, {"amount": 1}, {"x": 1}):
        err(POST(path, w.t("bob"), other, key=key), 409, "idempotency_key_reuse", str(other))
    assert ok(POST(path, w.t("bob"), {}, key=key), 200) == p
    assert w.wallet("bob")["total"] == 4500
    b = w.new_auth("ada", "bob", 2000)
    path = f"/authorizations/{b['authorization_id']}/capture"
    key = k()
    p = ok(POST(path, w.t("bob"), {"amount": 2000}, key=key), 201)
    err(POST(path, w.t("bob"), {}, key=key), 409, "idempotency_key_reuse")
    assert ok(call("POST", path, w.t("bob"), key=key, raw='{ "amount" : 2e3 }'), 200) == p


def test_q12_replay_after_close_expiry_and_void():
    w = World(fixture(ttl=2)).login_all()
    a = w.new_auth("ada", "bob", 1000)
    aid = a["authorization_id"]
    k1, k2, ka = k(), k(), k()
    p1 = ok(w.capture("bob", aid, key=k1, body={"amount": 300, "final": False}), 201)
    assert ok(w.capture("bob", aid, key=k1, body={"amount": 300, "final": False}), 200) == p1
    assert w.auth("ada", aid)["captured_amount"] == 300
    b = ok(w.authorize("ada", "bob", 50, key=ka), 201)
    time.sleep(2.6)
    # after expiry: replays still answer with the originals, new captures are refused
    assert ok(w.capture("bob", aid, key=k1, body={"amount": 300, "final": False}), 200) == p1
    assert ok(w.authorize("ada", "bob", 50, key=ka), 200) == b
    assert b["status"] == "open"
    err(w.capture("bob", aid, key=k2, body={"amount": 300, "final": False}), 409, "authorization_expired")
    err(w.capture("bob", aid, key=k1, body={"amount": 301, "final": False}), 409, "idempotency_key_reuse")
    assert w.wallet("bob")["total"] == 2800
    w2 = World().login_all()
    a = w2.new_auth("ada", "bob", 1000)
    kk = k()
    p = ok(w2.capture("bob", a["authorization_id"], key=kk), 201)
    assert ok(w2.capture("bob", a["authorization_id"], key=kk), 200) == p        # closed now: still a replay
    err(w2.capture("bob", a["authorization_id"], key=k()), 409, "authorization_not_open")
    ka = k()
    c = ok(w2.authorize("ada", "bob", 77, key=ka), 201)
    ok(w2.void("ada", c["authorization_id"]), 200)
    assert ok(w2.authorize("ada", "bob", 77, key=ka), 200) == c                    # original body, status open
    assert w2.wallet("ada")["held"] == 0


def test_q12_keys_scope_and_failed_keys(w):
    key = k()
    body = {"to_handle": "cy", "amount": 5}
    a = ok(POST("/authorizations", w.t("ada"), body, key=key), 201)
    b = ok(POST("/authorizations", w.t("bob"), body, key=key), 201)          # another user, same key
    p = ok(POST("/payments", w.t("ada"), body, key=key), 201)                 # another path, same key and body
    assert a["authorization_id"] != b["authorization_id"] and "payment_id" in p
    assert ok(POST("/authorizations", w.t("ada"), body, key=key), 200) == a
    # one key on the capture path of two authorisations
    x = w.new_auth("ada", "dan", 10)
    y = w.new_auth("bob", "dan", 20)
    px = ok(w.capture("dan", x["authorization_id"], key=key), 201)
    py = ok(w.capture("dan", y["authorization_id"], key=key), 201)
    assert (px["amount"], py["amount"]) == (10, 20)
    assert ok(w.capture("dan", x["authorization_id"], key=key), 200) == px
    # a non-receiver using the receiver's key string gets no replay
    r = w.capture("ada", x["authorization_id"], key=key)
    assert r.status_code in (403, 409) and r.status_code != 200
    # failed requests claim nothing
    key = k()
    err(w.authorize("cy", "ada", 50, key=key), 409, "insufficient_funds")
    err(w.authorize("cy", "ghost", 50, key=key), 404, "not_found")
    err(w.authorize("cy", "ada", 0, key=key), 422, "validation_failed")
    ok(w.pay("ada", "cy", 50), 201)
    ok(w.authorize("cy", "ada", 50, key=key), 201)
    z = w.new_auth("ada", "dan", 100)
    key = k()
    err(w.capture("dan", z["authorization_id"], key=key, body={"amount": 101}), 422, "capture_exceeds_authorization")
    err(w.capture("bob", z["authorization_id"], key=key, body={"amount": 1}), 403, "forbidden")
    ok(w.capture("dan", z["authorization_id"], key=key, body={"amount": 100}), 201)
    w.assert_conserved()


# ---------------------------------------------------------------- Q13 void

def test_q13_void(w):
    a = w.new_auth("ada", "bob", 1000, note="n")
    aid = a["authorization_id"]
    err(w.void("bob", aid), 403, "forbidden")                   # the receiver may not void
    err(w.void("cy", aid), 403, "forbidden")
    err(w.void("op", aid), 403, "forbidden")
    err(w.void("ada", "a_none"), 404, "not_found")
    err(call("POST", f"/authorizations/{aid}/void"), 401, "unauthenticated")
    assert w.wallet("ada")["held"] == 1000
    v = check_auth(ok(w.void("ada", aid), 200), status="voided", remaining_amount=0, captured_amount=0,
                   amount=1000, note="n", payment_id=None, payment_ids=[], created_at=a["created_at"],
                   expires_at=a["expires_at"])
    assert w.wallet("ada")["held"] == 0 and w.wallet("ada")["available"] == 10000
    assert ok(w.void("ada", aid), 200) == v
    assert ok(POST(f"/authorizations/{aid}/void", w.t("ada"), {"x": 1}, key=k()), 200) == v     # body and key are harmless
    err(w.capture("bob", aid), 409, "authorization_not_open")
    assert w.auth("bob", aid) == v
    b = w.new_auth("ada", "bob", 10)
    ok(w.capture("bob", b["authorization_id"]), 201)
    err(w.void("ada", b["authorization_id"]), 409, "authorization_not_open")
    err(w.void("bob", b["authorization_id"]), (403, 409), ("forbidden", "authorization_not_open"))
    for h in w.handles():
        assert all(p["authorization_id"] == b["authorization_id"] for p in w.activity(h))


# ---------------------------------------------------------------- Q14 listing

def test_q14_listing_filters():
    w, _ = seeded_world()
    n = lambda h, q="": {x["authorization_id"] for x in w.auths(h, q or "limit=200")}  # noqa: E731
    assert n("ada", "direction=outgoing") == {"a_open", "a_open2", "a_cap", "a_void", "a_exp", "a_clock"}
    assert n("ada", "direction=incoming") == {"a_in"}
    assert n("bob", "direction=incoming") == {"a_open", "a_cap", "a_void", "a_exp", "a_clock"}
    assert n("bob", "direction=outgoing") == {"a_in", "a_other"}
    assert n("ada", "status=open") == {"a_open", "a_open2", "a_in"}
    assert n("ada", "status=expired") == {"a_exp", "a_clock"}
    assert n("ada", "status=captured") == {"a_cap"}
    assert n("ada", "status=voided") == {"a_void"}
    assert n("ada", "status=open&direction=outgoing") == {"a_open", "a_open2"}
    assert n("ada", "direction=incoming&status=expired") == set()
    for st in ("open", "captured", "voided", "expired"):
        assert all(x["status"] == st for x in w.auths("ada", f"status={st}"))
    j = ok(GET("/authorizations", w.t("ada")), 200)
    assert set(j) >= {"authorizations", "has_more"} and j["has_more"] is False and len(j["authorizations"]) == 7
    for x in j["authorizations"]:
        check_auth(x)
        assert "ada" in (x["from_handle"], x["to_handle"])
    for bad in ("direction=sideways", "direction=INCOMING", "status=pending", "status=OPEN", "status=closed",
                "limit=0", "limit=201", "limit=abc", "limit=1e1", "limit=+4", "limit=", "offset=-1", "offset=1.0",
                "offset=abc"):
        err(GET(f"/authorizations?{bad}", w.t("ada")), 422, "validation_failed", bad)
    ok(GET("/authorizations?foo=bar&limit=0050&offset=000", w.t("ada")), 200)
    err(GET("/authorizations"), 401, "unauthenticated")
    err(GET("/authorizations", "bogus"), 401, "unauthenticated")
    # the feed ignores authorisation-only parameters
    ok(GET("/activity?status=open&direction=outgoing", w.t("ada")), 200)


def test_q14_order_and_pagination(w):
    made = []
    for i in range(5):
        made.append(w.new_auth("ada", "bob", i + 1)["authorization_id"])
        time.sleep(1.1)
    full = [x["authorization_id"] for x in w.auths("ada")]
    assert full == made[::-1], "not newest first"
    assert_newest_first(w.auths("bob"))

    def page(q):
        j = ok(GET(f"/authorizations?{q}", w.t("ada")), 200)
        return [x["authorization_id"] for x in j["authorizations"]], j["has_more"]

    assert page("limit=2") == (full[:2], True)
    assert page("limit=2&offset=2") == (full[2:4], True)
    assert page("limit=2&offset=4") == (full[4:], False)
    assert page("limit=5") == (full, False)
    assert page("limit=4") == (full[:4], True)
    assert page("offset=5") == ([], False)
    assert page("offset=" + "9" * 4400) == ([], False)
    ok(w.void("ada", made[4]), 200)
    assert page("status=open&limit=2") == (full[1:3], True)
    assert page("status=voided") == ([made[4]], False)


def test_q14_default_limit_is_50():
    w = World(fixture(users=[user("ada", 100000), user("bob", 0)])).login_all()
    rs = []
    for _ in range(2):
        rs += burst([lambda: w.authorize("ada", "bob", 1) for _ in range(28)])
    assert statuses(rs) == {201: 56}
    j = ok(GET("/authorizations", w.t("bob")), 200)
    assert len(j["authorizations"]) == 50 and j["has_more"] is True
    j2 = ok(GET("/authorizations?offset=50", w.t("bob")), 200)
    assert len(j2["authorizations"]) == 6 and j2["has_more"] is False
    assert w.wallet("ada")["held"] == 56


# ---------------------------------------------------------------- P / Q15 invariants under concurrency

def _poller(w, handles, seen, stop):
    while not stop.is_set():
        for h in handles:
            m = call("GET", "/me", w.t(h)).json()
            seen.append((h, m["balance"], m["total"], m["available"], m["held"]))


def _check_seen(seen):
    assert seen, "the poller saw nothing"
    for h, bal, total, avail, held in seen:
        assert bal == total and avail == total - held and avail >= 0 and held >= 0, (h, bal, total, avail, held)


def test_p2_fifty_concurrent_authorizations_never_overdraw():
    w = World().login_all()
    seen, stop = [], threading.Event()
    th = threading.Thread(target=_poller, args=(w, ["ada"], seen, stop))
    th.start()
    try:
        rs = burst([lambda: w.authorize("ada", "bob", 300) for _ in range(49)])
    finally:
        stop.set()
        th.join()
    rs.append(w.authorize("ada", "bob", 300))
    st = statuses(rs)
    assert st == {201: 33, 409: 17}, st
    assert all(code_of(r) == "insufficient_funds" for r in rs if r.status_code == 409)
    _check_seen(seen)
    m = w.wallet("ada")
    assert (m["total"], m["available"], m["held"]) == (10000, 100, 9900)
    w.assert_conserved()


def test_p2_payments_and_authorizations_share_available():
    w = World().login_all()
    seen, stop = [], threading.Event()
    th = threading.Thread(target=_poller, args=(w, ["ada"], seen, stop))
    th.start()
    try:
        fns = [(lambda: w.authorize("ada", "bob", 300)) if i % 2 else (lambda: w.pay("ada", "cy", 300)) for i in range(49)]
        rs = burst(fns)
    finally:
        stop.set()
        th.join()
    assert set(statuses(rs)) <= {201, 409}
    assert statuses(rs).get(201) == 33, statuses(rs)
    _check_seen(seen)
    m = w.wallet("ada")
    assert m["available"] == 100
    paid = sum(1 for r in rs if r.status_code == 201 and r.request.url.path == "/payments")
    assert (m["total"], m["held"]) == (10000 - 300 * paid, 300 * (33 - paid))
    w.assert_conserved()


def test_p3_fifty_concurrent_final_captures_distinct_keys(w):
    a = w.new_auth("ada", "bob", 700)
    rs = burst([lambda: w.capture("bob", a["authorization_id"], body={"amount": 700}) for _ in range(50)])
    st = statuses(rs)
    assert st == {201: 1, 409: 49}, st
    assert all(code_of(r) == "authorization_not_open" for r in rs if r.status_code == 409)
    assert (w.wallet("ada")["total"], w.wallet("bob")["total"]) == (9300, 3200)
    assert len([p for p in w.activity("ada") if p["authorization_id"] == a["authorization_id"]]) == 1


def test_p3_fifty_concurrent_captures_same_key(w):
    a = w.new_auth("ada", "bob", 700)
    key = k()
    rs = burst([lambda: w.capture("bob", a["authorization_id"], key=key, body={"amount": 100, "final": False})
                for _ in range(50)])
    assert statuses(rs) == {201: 1, 200: 49}, statuses(rs)
    first = rs[0].json()
    assert all(r.json() == first for r in rs)
    check_auth(w.auth("ada", a["authorization_id"]), status="open", captured_amount=100, remaining_amount=600)
    assert w.wallet("ada")["total"] == 9900
    key = k()
    rs = burst([lambda: w.authorize("ada", "cy", 25, key=key) for _ in range(50)])
    assert statuses(rs) == {201: 1, 200: 49}
    assert w.wallet("ada")["held"] == 625


def test_p3_nonfinal_captures_never_exceed_the_authorization(w):
    a = w.new_auth("ada", "bob", 3000)
    aid = a["authorization_id"]
    seen, stop = [], threading.Event()
    th = threading.Thread(target=_poller, args=(w, ["ada", "bob"], seen, stop))
    th.start()
    try:
        rs = burst([lambda: w.capture("bob", aid, body={"amount": 100, "final": False}) for _ in range(49)])
    finally:
        stop.set()
        th.join()
    st = statuses(rs)
    assert st.get(201) == 30 and set(st) <= {201, 409, 422}, st
    for r in rs:
        if r.status_code == 409:
            assert code_of(r) == "authorization_not_open"
        elif r.status_code == 422:
            assert code_of(r) == "capture_exceeds_authorization"
    _check_seen(seen)
    x = check_auth(w.auth("ada", aid), status="captured", captured_amount=3000, remaining_amount=0)
    assert len(x["payment_ids"]) == 30 and len(set(x["payment_ids"])) == 30
    assert sorted(x["payment_ids"]) == sorted(r.json()["payment_id"] for r in rs if r.status_code == 201)
    m = w.wallet("ada")
    assert (m["total"], m["available"], m["held"]) == (7000, 7000, 0)
    assert w.wallet("bob")["total"] == 5500
    w.assert_conserved()


def test_q15_capture_against_void(w):
    outcomes = set()
    moved = 0
    for rnd in range(6):
        a = w.new_auth("ada", "bob", 400)
        aid = a["authorization_id"]
        fns = [lambda: w.capture("bob", aid) for _ in range(25)] + [lambda: w.void("ada", aid) for _ in range(25)]
        if rnd % 2:
            fns = fns[::-1]
        rs = burst(fns)
        caps = [r for r in rs if r.request.url.path.endswith("/capture")]
        voids = [r for r in rs if r.request.url.path.endswith("/void")]
        final = w.auth("ada", aid)
        outcomes.add(final["status"])
        if final["status"] == "captured":
            moved += 400
            assert statuses(caps) == {201: 1, 409: 24} and statuses(voids) == {409: 25}, (statuses(caps), statuses(voids))
            assert final["captured_amount"] == 400
        else:
            assert final["status"] == "voided", final
            assert statuses(caps) == {409: 25} and statuses(voids) == {200: 25}, (statuses(caps), statuses(voids))
            assert final["captured_amount"] == 0 and final["payment_ids"] == []
        assert all(code_of(r) == "authorization_not_open" for r in rs if r.status_code == 409)
        m = w.wallet("ada")
        assert (m["total"], m["held"]) == (10000 - moved, 0)
    w.assert_conserved()


def test_q15_captures_around_the_deadline():
    w = World(fixture(ttl=2)).login_all()
    a = w.new_auth("ada", "bob", 10000)
    aid = a["authorization_id"]
    deadline = ts(a["expires_at"]).timestamp()
    results = []
    while time.time() < deadline + 0.6:
        results += burst([lambda: w.capture("bob", aid, body={"amount": 1, "final": False}) for _ in range(10)])
    okc = [r for r in results if r.status_code == 201]
    late = [r for r in results if r.status_code != 201]
    assert late and all(r.status_code == 409 and code_of(r) == "authorization_expired" for r in late), statuses(results)
    assert okc, "no capture succeeded before the deadline"
    x = check_auth(w.auth("ada", aid), status="expired", remaining_amount=0, captured_amount=len(okc))
    assert len(x["payment_ids"]) == len(okc)
    # no capture was accepted at or after the deadline
    for r in okc:
        assert ts(r.json()["created_at"]).timestamp() <= deadline + 1
    m = w.wallet("ada")
    assert (m["total"], m["available"], m["held"]) == (10000 - len(okc), 10000 - len(okc), 0)
    w.assert_conserved()


def test_p4_mixed_load_with_holds():
    import random
    rnd = random.Random(5)
    w = World().login_all()
    hs = ["ada", "bob", "cy", "dan", "op"]
    open_auths = []
    for _round in range(4):
        seen, stop = [], threading.Event()
        th = threading.Thread(target=_poller, args=(w, hs, seen, stop))
        fns = []
        for i in range(49):
            a, b = rnd.sample(hs, 2)
            amt = rnd.randint(1, 400)
            kind = i % 7
            if kind in (0, 1):
                fns.append(lambda a=a, b=b, amt=amt: w.authorize(a, b, amt))
            elif kind == 2:
                fns.append(lambda a=a, b=b, amt=amt: w.pay(a, b, amt))
            elif kind == 3 and open_auths:
                x = open_auths.pop()
                fns.append(lambda x=x, amt=amt: w.capture(x["to_handle"], x["authorization_id"],
                                                          body={"amount": min(amt, x["amount"]), "final": rnd.random() < 0.5}))
            elif kind == 4 and open_auths:
                x = open_auths.pop()
                fns.append(lambda x=x: w.void(x["from_handle"], x["authorization_id"]))
            elif kind == 5:
                fns.append(lambda a=a, b=b, amt=amt: POST("/settlements", w.t("op"), {"transfers": [
                    {"from_handle": a, "to_handle": b, "amount": amt}]}, key=k()))
            else:
                fns.append(lambda a=a: GET("/authorizations?limit=200", w.t(a)))
        th.start()
        try:
            rs = burst(fns)
        finally:
            stop.set()
            th.join()
        bad = [(r.request.method, r.request.url.path, r.status_code, r.text[:100]) for r in rs
               if r.status_code not in (200, 201, 409, 422)]
        assert not bad, bad
        for r in rs:
            if r.status_code == 201 and "status" in r.json() and "authorization_id" in r.json():
                open_auths.append(r.json())
        _check_seen(seen)
        w.assert_conserved()
        # held equals the sum of the open remainders in the listing
        for h in hs:
            held = sum(x["remaining_amount"] for x in w.auths(h, "direction=outgoing&status=open&limit=200"))
            assert w.wallet(h)["held"] == held, h


# ---------------------------------------------------------------- Q16 / M1 export, import, reset

def build2(base=None, ttl=1234):
    """A stage-2 state with authorisations in every status and keys on both new paths."""
    auths = [seeded_auth("a_seed_open", "bob", "ada", 300, note="seeded"),
             seeded_auth("a_seed_exp", "bob", "ada", 300, status="open", expires_in=-7200),
             seeded_auth("a_seed_cap", "bob", "ada", 100, status="captured", expires_in=-7200)]
    w = World(fixture(auths=auths, ttl=ttl), base=base).login_all()
    done = []

    def rec(who, path, body):
        key = k()
        r = call("POST", path, w.t(who), key=key, body=body, base=w.base)
        assert r.status_code == 201, r.text
        done.append({"who": who, "path": path, "key": key, "body": body, "resp": r.json()})
        return r.json()

    a1 = rec("ada", "/authorizations", {"to_handle": "bob", "amount": 2000, "note": "open one", "visibility": "private"})
    a2 = rec("ada", "/authorizations", {"to_handle": "cy", "amount": 900, "note": "partly"})
    rec("cy", f"/authorizations/{a2['authorization_id']}/capture", {"amount": 400, "final": False})
    a3 = rec("ada", "/authorizations", {"to_handle": "dan", "amount": 500})
    rec("dan", f"/authorizations/{a3['authorization_id']}/capture", {"amount": 450})
    a4 = rec("ada", "/authorizations", {"to_handle": "dan", "amount": 60})
    assert call("POST", f"/authorizations/{a4['authorization_id']}/void", w.t("ada"), base=w.base).status_code == 200
    rec("ada", "/authorizations/a_seed_open/capture", {"amount": 100, "final": False})
    rec("ada", "/payments", {"to_handle": "bob", "amount": 5})
    failed_key = k()
    assert call("POST", "/authorizations", w.t("cy"), key=failed_key, body={"to_handle": "ada", "amount": 10 ** 9},
                base=w.base).status_code == 409
    tokens = {h: w.t(h) for h in w.handles()}
    return w, done, tokens, failed_key, {"a1": a1, "a2": a2, "a3": a3, "a4": a4}


def test_q16_export_import_same_container():
    w, done, tokens, failed_key, au = build2()
    before = w.snapshot()
    e = call("GET", "/_test/export")
    assert e.status_code == 200
    ok(w.pay("ada", "bob", 1), 201)
    ok(w.void("ada", au["a1"]["authorization_id"]), 200)
    assert call("POST", "/_test/import", raw=e.content).status_code == 204
    assert w.snapshot() == before
    for d in done:
        r = call("POST", d["path"], tokens[d["who"]], key=d["key"], body=d["body"])
        assert r.status_code == 200 and r.json() == d["resp"], f"replay {d['path']}: {r.status_code} {r.text[:150]}"
        err(call("POST", d["path"], tokens[d["who"]], key=d["key"], body={**d["body"], "changed": 1}), 409,
            "idempotency_key_reuse")
    assert w.snapshot() == before
    soft(call("GET", "/_test/export").json() == e.json(), "export-import-export-differs")


def test_q16_import_into_fresh_container_and_reset():
    assert BASE2, "BASE2 (second container) is not set"
    w, done, tokens, failed_key, au = build2()
    before = w.snapshot()
    e = call("GET", "/_test/export")
    World(fixture(users=[user("zed", 5)], auths=[]), base=BASE2)
    assert call("POST", "/_test/import", raw=e.content, base=BASE2).status_code == 204
    assert w.snapshot(tokens=tokens, base=BASE2) == before
    for d in done:
        r = call("POST", d["path"], tokens[d["who"]], key=d["key"], body=d["body"], base=BASE2)
        assert r.status_code == 200 and r.json() == d["resp"], f"replay {d['path']}: {r.status_code}"
    # the imported service keeps working: ttl preserved, holds live, failed key reusable, ids do not collide
    a = call("POST", "/authorizations", tokens["ada"], key=k(), body={"to_handle": "bob", "amount": 1}, base=BASE2).json()
    assert (ts(a["expires_at"]) - ts(a["created_at"])).total_seconds() == 1234
    old_ids = {x["authorization_id"] for h in before for x in before[h]["authorizations"][1]["authorizations"]}
    assert a["authorization_id"] not in old_ids
    r = call("POST", "/authorizations", tokens["cy"], key=failed_key, body={"to_handle": "ada", "amount": 1}, base=BASE2)
    assert r.status_code == 201, r.text
    r = call("POST", f"/authorizations/{au['a2']['authorization_id']}/capture", tokens["cy"], key=k(), body={}, base=BASE2)
    assert r.status_code == 201 and r.json()["amount"] == 500
    old_p = {p["payment_id"] for h in before for p in before[h]["activity"][1]["payments"]}
    assert r.json()["payment_id"] not in old_p
    assert call("POST", f"/authorizations/{au['a1']['authorization_id']}/void", tokens["ada"], base=BASE2).json()["status"] == "voided"
    total = sum(call("GET", "/me", tokens[h], base=BASE2).json()["total"] for h in ("ada", "bob", "cy", "dan", "op"))
    assert total == w.seeded_total()
    assert w.snapshot() == before, "the source changed"
    # reset clears authorisations, holds and the new keys
    w3 = World(fixture(), base=BASE2).login_all()
    for h in w3.handles():
        assert w3.auths(h) == [] and w3.wallet(h)["held"] == 0
    d = done[0]
    r = call("POST", d["path"], w3.t("ada"), key=d["key"], body=d["body"], base=BASE2)
    assert r.status_code == 201 and r.json()["authorization_id"] not in ("",)


AUTH_STATE_VALUES = ["0.25", "1" + "0" * 30, "-1", "null", '"x"', "[]", "{}", "true"]


def test_q16_import_rejects_broken_authorization_records():
    w, done, tokens, failed_key, au = build2()
    e = call("GET", "/_test/export").json()
    before = w.snapshot()
    skey = next((kk for kk in e["state"] if "auth" in kk and isinstance(e["state"][kk], list)), None)
    assert skey, f"no authorisation list in the export state: {sorted(e['state'])}"
    recs = e["state"][skey]
    assert len(recs) >= 7
    accepted = rejected = 0
    for field in list(recs[0]):
        for value in AUTH_STATE_VALUES:
            doc = copy.deepcopy(e)
            doc["state"][skey][0][field] = "@@MUT@@"
            r = call("POST", "/_test/import", raw=json.dumps(doc).replace('"@@MUT@@"', value))
            assert r.status_code in (204, 422), f"{field} <- {value}: {r.status_code} {r.text[:120]}"
            if r.status_code == 422:
                rejected += 1
                continue
            accepted += 1
            x = call("GET", "/_test/export")
            assert x.status_code == 200
            assert call("POST", "/_test/import", raw=x.content).status_code == 204
            for h, tk in tokens.items():
                for ep in ("/me", "/authorizations?limit=200", "/activity?limit=200"):
                    rr = call("GET", ep, tk)
                    assert rr.status_code < 500
                    if ep == "/me" and rr.status_code == 200:
                        m = rr.json()
                        assert m["available"] >= 0 and m["available"] == m["total"] - m["held"], (field, value, m)
            assert call("POST", "/_test/import", body=e).status_code == 204
    assert rejected > 0
    assert w.snapshot() == before
    # a hold larger than the wallet must not be importable
    doc = copy.deepcopy(e)
    target = next(x for x in doc["state"][skey] if x.get("status") == "open" or x.get("state") == "open")
    target["amount"] = 10 ** 9
    for kk in ("remaining_amount", "remaining"):
        if kk in target:
            target[kk] = 10 ** 9
    r = call("POST", "/_test/import", body=doc)
    assert r.status_code in (204, 422)
    if r.status_code == 204:
        for h, tk in tokens.items():
            m = call("GET", "/me", tk).json()
            assert m["available"] >= 0, f"import accepted a hold larger than the wallet: {m}"
        assert call("POST", "/_test/import", body=e).status_code == 204
