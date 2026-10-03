"""A. Delivery and runtime — the parts checked over HTTP (run.sh covers build/start)."""
import pytest

from lib import GET, POST, World, call, err, fixture, k, ok, soft, user


def test_a4_health_body_exact():
    r = GET("/health")
    assert ok(r, 200) == {"status": "ok"}
    assert ok(GET("/health?x=1&limit=abc"), 200) == {"status": "ok"}


def test_a9_unknown_body_fields_ignored_everywhere():
    w = World()
    junk = {"zzz": 1, "handle": "evil", "balance": 999999, "nested": {"a": [1, 2]}}
    r = POST("/auth/signup", body={"email": "new.one@example.com", "password": "longenough1",
                                   "display_name": "N", **junk})
    j = ok(r, 201)
    me = ok(GET("/me", j["token"]), 200)
    assert me["handle"] == "new_one" and me["balance"] == 0
    ok(POST("/auth/login", body={"email": "new.one@example.com", "password": "longenough1", **junk}), 200)
    p = ok(POST("/payments", w.t("ada"), {"to_handle": "bob", "amount": 10, "from_handle": "cy",
                                           "request_id": "x", "settlement_id": "y", **junk}, key=k()), 201)
    assert p["from_handle"] == "ada" and p["request_id"] is None and p["settlement_id"] is None
    q = ok(POST("/requests", w.t("bob"), {"payer_handle": "ada", "amount": 10, "status": "paid",
                                           "visibility": "private", **junk}, key=k()), 201)
    assert q["status"] == "pending"
    pp = ok(POST(f"/requests/{q['request_id']}/pay", w.t("ada"), {"amount": 1, **junk}, key=k()), 201)
    assert pp["amount"] == 10 and pp["visibility"] == "public"
    s = ok(POST("/splits", w.t("ada"), {"amount": 9, "participant_handles": ["ada", "bob"],
                                         "shares": [1, 8], **junk}, key=k()), 201)
    assert [x["amount"] for x in s["shares"]] == [5, 4]
    st = ok(POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1,
                                                            "settlement_id": "x", **junk}], **junk}, key=k()), 201)
    assert len(st["payments"]) == 1
    w.assert_conserved()


def test_a9_unknown_query_params_ignored():
    w = World()
    t = w.t("ada")
    ok(GET("/me?foo=bar&limit=abc", t), 200)
    ok(GET("/requests?foo=bar&cursor=zzz&sort=asc", t), 200)
    ok(GET("/activity?foo=bar&direction=sideways&status=open&visibility=nope", t), 200)
    ok(POST("/payments?foo=bar&limit=abc", t, {"to_handle": "bob", "amount": 1}, key=k()), 201)
    r = call("POST", "/_test/reset?foo=bar", body=fixture())
    assert r.status_code == 204


OUT_OF_SCOPE = [
    ("POST", "/deposits"), ("POST", "/deposit"), ("POST", "/topups"), ("POST", "/top-ups"), ("POST", "/topup"),
    ("POST", "/withdrawals"), ("POST", "/withdraw"), ("GET", "/cards"), ("POST", "/cards"), ("GET", "/bank"),
    ("GET", "/bank-accounts"), ("GET", "/users"), ("GET", "/users/search?q=a"), ("GET", "/users/ada"),
    ("GET", "/directory"), ("GET", "/search?q=a"), ("GET", "/admin/balance"), ("POST", "/admin/balance"),
    ("POST", "/_test/balance"), ("POST", "/auth/verify"), ("POST", "/auth/verify-email"),
    ("POST", "/auth/password-reset"), ("POST", "/auth/reset-password"), ("POST", "/auth/refresh"),
    ("POST", "/auth/logout"), ("GET", "/roles"), ("POST", "/roles"), ("GET", "/payments"),
    ("GET", "/splits"), ("GET", "/settlements"), ("GET", "/wallet"), ("GET", "/balance"),
]


@pytest.fixture(scope="module")
def w11():
    return World().login_all()


@pytest.mark.parametrize("method,path", OUT_OF_SCOPE)
def test_a11_out_of_scope_routes_absent(w11, method, path):
    if method == "POST":
        r = call(method, path, w11.t("ada"), body={"amount": 1, "to_handle": "bob"}, key=k())
    else:
        r = call(method, path, w11.t("ada"))
    assert r.status_code in (404, 405), f"{method} {path} answered {r.status_code} {r.text[:200]}"
    soft(r.status_code == 404, "out-of-scope-not-404", path=path, status=r.status_code)


def test_a10_fixture_ids_kept_and_generated_ids_short():
    long_id = "u_" + "x" * 62
    assert len(long_id) == 64
    pid, rid = "p_" + "y" * 62, "rq_" + "z" * 61
    w = World(fixture(users=[user("ada", 100, id=long_id), user("bob", 100)],
                      payments=[{"id": pid, "from_user_id": long_id, "to_user_id": "u_bob", "amount": 5,
                                 "note": "n", "visibility": "public"}],
                      requests=[{"id": rid, "requester_id": "u_bob", "payer_id": long_id, "amount": 7,
                                 "note": "r", "status": "pending"}]))
    assert w.me("ada")["user_id"] == long_id
    assert w.activity("bob")[0]["payment_id"] == pid
    assert w.activity("bob")[0]["from_user_id"] == long_id
    assert w.requests("ada")[0]["request_id"] == rid
    p = ok(w.pay_request("ada", rid), 201)
    assert p["request_id"] == rid and p["from_user_id"] == long_id
