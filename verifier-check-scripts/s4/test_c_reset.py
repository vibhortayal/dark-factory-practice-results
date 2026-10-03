"""C. Reset and fixture."""
import copy
import json

import pytest

from lib import GET, POST, PW, World, call, check_payment, check_request, code_of, err, fixture, k, ok, soft, user


def test_c1_reset_204_no_auth_empty_body():
    r = call("POST", "/_test/reset", body=fixture())
    assert r.status_code == 204 and r.content == b""


def test_c1_reset_replaces_everything():
    w = World().login_all()
    key = k()
    ok(w.pay("ada", "bob", 100, key=key), 201)
    q = w.new_request("bob", "ada", 5)
    su = w.signup("fresh@example.com")
    ok(POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]},
            key=k()), 201)
    old = dict(w.tok)
    # a different world: other users, ada kept by handle but with other id/email/password, op no longer operator
    fx2 = fixture(users=[user("ada", 77, id="u_ada2", email="ada2@example.com", password="another pass"),
                         user("bob", 23), user("op", 0), user("zed", 0)], ops=[])
    w2 = World(fx2)
    for h, tk in old.items():
        err(GET("/me", tk), 401, "unauthenticated", f"old token of {h}")
    err(GET("/me", su["token"]), 401, "unauthenticated")
    err(POST("/auth/login", body={"email": "ada@example.com", "password": PW}), 401, "unauthenticated")
    err(POST("/auth/login", body={"email": "fresh@example.com", "password": "longenough1"}), 401, "unauthenticated")
    err(POST("/auth/login", body={"email": "cy@example.com", "password": PW}), 401, "unauthenticated")
    assert w2.bals() == {"ada": 77, "bob": 23, "op": 0, "zed": 0}
    assert w2.me("ada")["user_id"] == "u_ada2"
    for h in w2.handles():
        assert w2.activity(h) == [] and w2.requests(h) == []
    # the old key is a first use again (201, not a 200 replay of the old response)
    p = ok(w2.pay("ada", "bob", 1, key=key), 201)
    assert p["from_user_id"] == "u_ada2"
    err(POST(f"/requests/{q['request_id']}/pay", w2.t("ada"), {}, key=k()), 404, "not_found")
    err(POST("/settlements", w2.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]},
             key=k()), 403, "forbidden")
    err(w2.pay("ada", "cy", 1), 404, "not_found")
    # the freed email/handle can sign up again
    ok(POST("/auth/signup", body={"email": "fresh@example.com", "password": "longenough1", "display_name": "F"}), 201)


def test_c1_repeated_resets():
    for i in range(5):
        w = World(fixture(users=[user("ada", 100 + i), user(f"u{i}", i)]))
        assert w.bals() == {"ada": 100 + i, f"u{i}": i}
        ok(w.pay("ada", f"u{i}", 100), 201)
        assert len(w.activity("ada")) == 1


def test_c2_optional_parts_absent_or_empty():
    fx = {"currency": "EUR", "minor_units": 2, "users": [user("ada", 5), user("bob", 0)]}
    assert call("POST", "/_test/reset", body=fx).status_code == 204
    w = World(fx, do_reset=False)
    assert w.bals() == {"ada": 5, "bob": 0}
    assert w.activity("ada") == [] and w.requests("ada") == []
    err(POST("/settlements", w.t("ada"), {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]},
             key=k()), 403, "forbidden")
    fx2 = dict(fx, payments=[], requests=[], settlement_operator_ids=[])
    assert call("POST", "/_test/reset", body=fx2).status_code == 204
    fx3 = dict(fx, users=[])
    r = call("POST", "/_test/reset", body=fx3)
    assert r.status_code in (204, 422), r.text
    soft(r.status_code == 204, "reset-empty-users-rejected", status=r.status_code)


def test_c2_unknown_fixture_fields_ignored():
    fx = fixture(users=[user("ada", 5, nickname="A", extra={"a": 1}), user("bob", 0)],
                 payments=[{"id": "p1", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 5, "note": "",
                            "visibility": "public", "whatever": [1]}])
    fx["schema"] = "v9"
    fx["splits"] = "ignored?"
    r = call("POST", "/_test/reset", body=fx)
    assert r.status_code == 204, r.text
    assert World(fx, do_reset=False).bal("ada") == 5


def test_c2_integral_float_forms_in_fixture():
    raw = json.dumps(fixture(users=[user("ada", 111), user("bob", 222)],
                             payments=[{"id": "p1", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 333,
                                        "note": "", "visibility": "public"}]))
    raw = raw.replace("111", "1e4").replace("222", "2500.0").replace("333", "5.0")
    r = call("POST", "/_test/reset", raw=raw)
    if not soft(r.status_code == 204, "fixture-float-forms-rejected", status=r.status_code, body=r.text[:200]):
        assert 400 <= r.status_code < 500
        return
    w = World(fixture(users=[user("ada", 10000), user("bob", 2500)]), do_reset=False)
    assert w.bals() == {"ada": 10000, "bob": 2500}
    assert w.activity("ada")[0]["amount"] == 5


def test_c3_seeded_users_log_in_immediately():
    fx = fixture(users=[user("ada", 1, password="pässwörd with spaces "), user("bob", 2, password="12345678"),
                        user("cy", 3, password="x" * 72)])
    w = World(fx)
    for u in fx["users"]:
        j = ok(POST("/auth/login", body={"email": u["email"], "password": u["password"]}), 200)
        assert j["user_id"] == u["id"] and j["display_name"] == u["display_name"] and isinstance(j["token"], str)
        err(POST("/auth/login", body={"email": u["email"], "password": u["password"] + "x"}), 401, "unauthenticated")
    assert w.bals() == {"ada": 1, "bob": 2, "cy": 3}


SEED_P = [
    {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
    {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 9000, "note": "sécret 🤫", "visibility": "private"},
    {"id": "p_3", "from_user_id": "u_cy", "to_user_id": "u_ada", "amount": 1, "note": "", "visibility": "public"},
]
SEED_R = [
    {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
    {"id": "rq_2", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 10, "note": "a", "status": "paid"},
    {"id": "rq_3", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 11, "note": "b", "status": "declined"},
    {"id": "rq_4", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 12, "note": "c", "status": "cancelled"},
    {"id": "rq_5", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 13, "note": "d", "status": "pending"},
    {"id": "rq_6", "requester_id": "u_cy", "payer_id": "u_bob", "amount": 14, "note": "e", "status": "pending"},
]


def seeded():
    return World(fixture(payments=copy.deepcopy(SEED_P), requests=copy.deepcopy(SEED_R)))


def test_c4_balances_not_replayed():
    w = seeded()
    assert w.bals() == {"ada": 10000, "bob": 2500, "cy": 0, "dan": 500, "op": 1000}


def test_c7_seeded_payments_feed_contract():
    w = seeded()
    ids = lambda h: {p["payment_id"] for p in w.activity(h)}  # noqa: E731
    assert ids("ada") == {"p_1", "p_3"}
    assert ids("bob") == {"p_1", "p_2", "p_3"}
    assert ids("cy") == {"p_1", "p_2", "p_3"}
    assert ids("dan") == {"p_1", "p_3"}
    assert ids("op") == {"p_1", "p_3"}
    by = {p["payment_id"]: p for p in w.activity("bob")}
    check_payment(by["p_1"], from_user_id="u_ada", from_handle="ada", to_user_id="u_bob", to_handle="bob",
                  amount=500, currency="EUR", note="coffee", visibility="public", request_id=None, settlement_id=None)
    check_payment(by["p_2"], from_user_id="u_bob", to_user_id="u_cy", amount=9000, note="sécret 🤫",
                  visibility="private", request_id=None, settlement_id=None)
    assert {p["payment_id"]: p for p in w.activity("cy")}["p_2"] == by["p_2"]
    order = [p["payment_id"] for p in w.activity("bob")]
    soft(order == ["p_3", "p_2", "p_1"], "seed-order-not-fixture-order", order=order)


def test_c7_seeded_requests():
    w = seeded()
    rid = lambda h: {q["request_id"] for q in w.requests(h)}  # noqa: E731
    assert rid("ada") == {"rq_1", "rq_2", "rq_3", "rq_4", "rq_5"}
    assert rid("bob") == {"rq_1", "rq_2", "rq_3", "rq_4", "rq_6"}
    assert rid("cy") == {"rq_5", "rq_6"}
    assert rid("dan") == set() and rid("op") == set()
    by = {q["request_id"]: q for q in w.requests("ada")}
    check_request(by["rq_1"], requester_id="u_bob", requester_handle="bob", payer_id="u_ada", payer_handle="ada",
                  amount=1200, currency="EUR", note="taxi", status="pending", payment_id=None)
    assert [by[f"rq_{i}"]["status"] for i in (2, 3, 4)] == ["paid", "declined", "cancelled"]
    assert {q["request_id"] for q in w.requests("ada", "status=pending&direction=incoming")} == {"rq_1"}
    assert {q["request_id"] for q in w.requests("ada", "direction=outgoing")} == {"rq_5"}
    for i in (2, 3, 4):
        err(w.pay_request("ada", f"rq_{i}"), 409, "request_not_pending")
    assert ok(POST("/requests/rq_3/decline", w.t("ada")), 200)["status"] == "declined"
    assert ok(POST("/requests/rq_4/cancel", w.t("bob")), 200)["status"] == "cancelled"
    err(POST("/requests/rq_2/decline", w.t("ada")), 409, "request_not_pending")
    err(POST("/requests/rq_2/cancel", w.t("bob")), 409, "request_not_pending")
    err(POST("/requests/rq_4/decline", w.t("ada")), 409, "request_not_pending")
    err(POST("/requests/rq_3/cancel", w.t("bob")), 409, "request_not_pending")
    # pending seeded requests are live
    p = check_payment(ok(w.pay_request("ada", "rq_1", body={"visibility": "private"}), 201),
                      request_id="rq_1", amount=1200, from_handle="ada", to_handle="bob", visibility="private")
    assert {q["request_id"]: q for q in w.requests("bob")}["rq_1"]["payment_id"] == p["payment_id"]
    err(w.pay_request("cy", "rq_5"), 409, "insufficient_funds")
    assert ok(POST("/requests/rq_5/cancel", w.t("ada")), 200)["status"] == "cancelled"
    assert ok(POST("/requests/rq_6/decline", w.t("bob")), 200)["status"] == "declined"
    b = w.assert_conserved()
    assert b["ada"] == 8800 and b["bob"] == 3700


def test_c5_negative_balance_rejected_and_nothing_changes():
    w = World().login_all()
    ok(w.pay("ada", "bob", 100), 201)
    before = w.snapshot()
    bad = fixture(users=[user("ada", 5), user("zed", -1)])
    err(call("POST", "/_test/reset", body=bad), 422, "validation_failed")
    assert w.snapshot() == before


def _mut(fn):
    fx = fixture(payments=copy.deepcopy(SEED_P), requests=copy.deepcopy(SEED_R))
    fn(fx)
    return fx


def _set(path, value):
    def fn(fx):
        cur = fx
        for p in path[:-1]:
            cur = cur[p]
        cur[path[-1]] = value
    return fn


def _del(path):
    def fn(fx):
        cur = fx
        for p in path[:-1]:
            cur = cur[p]
        del cur[path[-1]]
    return fn


BAD_FIXTURES = {
    # name: (mutation, allowed statuses)
    "minor_units_1": (_set(["minor_units"], 1), (422,)),
    "minor_units_5": (_set(["minor_units"], 5), (422,)),
    "minor_units_-2": (_set(["minor_units"], -2), (422,)),
    "minor_units_string": (_set(["minor_units"], "2"), (400, 422)),
    "missing_users": (_del(["users"]), (422,)),
    "missing_currency": (_del(["currency"]), (422,)),
    "missing_minor_units": (_del(["minor_units"]), (422,)),
    "users_not_array": (_set(["users"], "ada"), (400, 422)),
    "user_not_object": (_set(["users", 0], "ada"), (400, 422)),
    "duplicate_user_id": (_set(["users", 1, "id"], "u_ada"), (422,)),
    "duplicate_handle": (_set(["users", 1, "handle"], "ada"), (422,)),
    "duplicate_email": (_set(["users", 1, "email"], "ada@example.com"), (422,)),
    "handle_uppercase": (_set(["users", 3, "handle"], "DAN"), (422,)),
    "handle_21_chars": (_set(["users", 3, "handle"], "d" * 21), (422,)),
    "handle_empty": (_set(["users", 3, "handle"], ""), (422,)),
    "handle_dash": (_set(["users", 3, "handle"], "da-n"), (422,)),
    "user_missing_balance": (_del(["users", 3, "balance"]), (422,)),
    "user_missing_handle": (_del(["users", 3, "handle"]), (422,)),
    "user_missing_password": (_del(["users", 3, "password"]), (422,)),
    "user_missing_email": (_del(["users", 3, "email"]), (422,)),
    "user_missing_id": (_del(["users", 3, "id"]), (422,)),
    "balance_fraction": (_set(["users", 0, "balance"], 10.5), (400, 422)),
    "balance_string": (_set(["users", 0, "balance"], "100"), (400, 422)),
    "balance_null": (_set(["users", 0, "balance"], None), (400, 422)),
    "balance_negative": (_set(["users", 4, "balance"], -1), (422,)),
    "user_id_65_chars": (_set(["users", 3, "id"], "u" * 65), (422,)),
    "payment_unknown_sender": (_set(["payments", 0, "from_user_id"], "u_ghost"), (422,)),
    "payment_unknown_receiver": (_set(["payments", 0, "to_user_id"], "u_ghost"), (422,)),
    "payment_bad_visibility": (_set(["payments", 0, "visibility"], "friends"), (422,)),
    "payment_negative_amount": (_set(["payments", 0, "amount"], -5), (422,)),
    "payment_amount_string": (_set(["payments", 0, "amount"], "5"), (400, 422)),
    "payment_duplicate_id": (_set(["payments", 1, "id"], "p_1"), (422,)),
    "payments_not_array": (_set(["payments"], {"a": 1}), (400, 422)),
    "request_unknown_requester": (_set(["requests", 0, "requester_id"], "u_ghost"), (422,)),
    "request_unknown_payer": (_set(["requests", 0, "payer_id"], "u_ghost"), (422,)),
    "request_bad_status": (_set(["requests", 0, "status"], "open"), (422,)),
    "request_duplicate_id": (_set(["requests", 1, "id"], "rq_1"), (422,)),
    "request_negative_amount": (_set(["requests", 0, "amount"], -1), (422,)),
    "operator_unknown": (_set(["settlement_operator_ids"], ["u_ghost"]), (422,)),
    "operators_not_array": (_set(["settlement_operator_ids"], "u_op"), (400, 422)),
}


@pytest.fixture(scope="module")
def base_world():
    w = World().login_all()
    ok(w.pay("ada", "bob", 100, visibility="private"), 201)
    w.new_request("bob", "ada", 5)
    return w, w.snapshot()


@pytest.mark.parametrize("name", list(BAD_FIXTURES))
def test_c6_invalid_fixture_rejected_without_change(base_world, name):
    w, before = base_world
    mutation, allowed = BAD_FIXTURES[name]
    r = call("POST", "/_test/reset", body=_mut(mutation))
    changed = w.snapshot() != before
    if r.status_code == 204:
        # re-establish the base state for the following cases before failing
        base_world[0].__init__()
        pytest.fail(f"invalid fixture {name} was accepted with 204")
    assert not changed, f"state changed after rejected reset {name} ({r.status_code})"
    assert r.status_code in allowed, f"{name}: {r.status_code} {r.text[:200]}"
    assert code_of(r) == ("validation_failed" if r.status_code == 422 else "malformed_request"), r.text[:200]


@pytest.mark.parametrize("raw", ['{"currency": "EUR", "users": [', "", "not json", '{"users": [}', "\xff\xfe"])
def test_c6_unparseable_reset_body(base_world, raw):
    w, before = base_world
    r = call("POST", "/_test/reset", raw=raw.encode("latin-1"))
    err(r, 400, "malformed_request")
    assert w.snapshot() == before


@pytest.mark.parametrize("raw", ["[]", '"x"', "5", "null", "true"])
def test_c6_non_object_reset_body(base_world, raw):
    w, before = base_world
    r = call("POST", "/_test/reset", raw=raw)
    err(r, (400, 422), ("malformed_request", "validation_failed"))
    soft(r.status_code == 400, "non-object-body-422", path="/_test/reset", raw=raw)
    assert w.snapshot() == before


def test_c8_reset_sixty_users_within_limit():
    users = [user(f"user_{i:02d}", 1000 + i) for i in range(60)]
    pays = [{"id": f"p_{i}", "from_user_id": f"u_user_{i:02d}", "to_user_id": f"u_user_{(i + 1) % 60:02d}",
             "amount": 5, "note": f"n{i}", "visibility": "public" if i % 2 else "private"} for i in range(60)]
    reqs = [{"id": f"rq_{i}", "requester_id": f"u_user_{i:02d}", "payer_id": f"u_user_{(i + 7) % 60:02d}",
             "amount": 9, "note": "", "status": ["pending", "paid", "declined", "cancelled"][i % 4]} for i in range(60)]
    fx = fixture(users=users, payments=pays, requests=reqs, ops=["u_user_00"])
    r = call("POST", "/_test/reset", body=fx)
    assert r.status_code == 204, r.text[:200]
    assert r.elapsed_s <= 10.0, f"reset took {r.elapsed_s:.2f}s"
    w = World(fx, do_reset=False)
    for h in ("user_00", "user_31", "user_59"):
        assert w.bal(h) == 1000 + int(h[-2:])
    assert len(w.activity("user_00")) >= 30
    w.assert_conserved()
