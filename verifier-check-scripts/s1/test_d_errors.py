"""D. Errors: codes, precedence, shared ranges."""
import json

import pytest

from lib import GET, POST, World, call, code_of, err, fixture, k, ok, soft, user


@pytest.fixture(scope="module")
def w():
    """Rich wallets so that validation checks never run into insufficient funds."""
    return World(fixture(users=[user("ada", 10 ** 12), user("bob", 10 ** 12), user("cy", 0), user("dan", 500),
                                user("op", 1000)])).login_all()


# ---------------------------------------------------------------- D1 routes and methods

@pytest.mark.parametrize("method,path", [("GET", "/nope"), ("POST", "/nope"), ("GET", "/"), ("GET", "/me/x"),
                                         ("GET", "/requests/abc"), ("POST", "/requests/abc/refund"),
                                         ("GET", "/health/x"), ("DELETE", "/nope"), ("GET", "/_test/nope"),
                                         ("GET", "/auth"), ("POST", "/payments/p_1")])
def test_d1_unknown_route_404(w, method, path):
    r = call(method, path, w.t("ada"), body={} if method == "POST" else None) if method == "POST" \
        else call(method, path, w.t("ada"))
    err(r, 404, "not_found")


@pytest.mark.parametrize("method,path", [("GET", "/payments"), ("PUT", "/payments"), ("DELETE", "/me"),
                                         ("POST", "/me"), ("GET", "/auth/login"), ("PUT", "/auth/signup"),
                                         ("GET", "/_test/reset"), ("POST", "/_test/export"), ("GET", "/_test/import"),
                                         ("POST", "/health"), ("PATCH", "/requests"), ("DELETE", "/activity"),
                                         ("GET", "/requests/x/pay"), ("PUT", "/splits"), ("GET", "/settlements")])
def test_d1_wrong_method_is_4xx_envelope(w, method, path):
    r = call(method, path, w.t("ada"))
    assert 400 <= r.status_code < 500, f"{method} {path}: {r.status_code} {r.text[:200]}"
    assert isinstance(code_of(r), str)
    soft(r.status_code in (404, 405), "wrong-method-status", method=method, path=path, status=r.status_code)


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS"])
@pytest.mark.parametrize("path", ["/health", "/me", "/payments", "/activity"])
def test_d10_head_options_no_5xx(w, method, path):
    r = call(method, path, w.t("ada"))
    assert r.status_code < 500


# ---------------------------------------------------------------- D2 unparseable / non-object bodies

def _paths(w):
    q = w.new_request("bob", "ada", 5)
    return [("/auth/signup", None, None), ("/auth/login", None, None), ("/payments", "ada", k()),
            ("/requests", "ada", k()), (f"/requests/{q['request_id']}/pay", "ada", k()), ("/splits", "ada", k()),
            ("/settlements", "op", k()), ("/_test/import", None, None)]


@pytest.mark.parametrize("raw", [b'{"amount": 5,', b"{amount: 5}", b"not json", b"{'a': 1}", b'{"a": 1}}',
                                 b"\xff\xfe\x00", b'{"a": tru}', b'{"a": 1,}'])
def test_d2_unparseable_body_400(w, raw):
    before = w.snapshot()
    for path, who, key in _paths(w)[:-1] + [("/_test/import", None, None)]:
        r = call("POST", path, w.t(who) if who else None, key=key, raw=raw)
        err(r, 400, "malformed_request", f"{path} {raw!r}")
    after = w.snapshot()
    assert {h: v["me"] for h, v in after.items()} == {h: v["me"] for h, v in before.items()}


def test_d2_empty_body_400_where_fields_are_required(w):
    for path, who, key in [("/auth/signup", None, None), ("/auth/login", None, None), ("/payments", "ada", k()),
                           ("/requests", "ada", k()), ("/splits", "ada", k()), ("/settlements", "op", k()),
                           ("/_test/import", None, None)]:
        r = call("POST", path, w.t(who) if who else None, key=key, raw=b"")
        err(r, (400, 422), ("malformed_request", "validation_failed"), path)
        soft(r.status_code == 400, "empty-body-not-400", path=path, status=r.status_code)


@pytest.mark.parametrize("raw", ["[]", '"x"', "5", "null", "true", '[{"to_handle": "bob", "amount": 1}]'])
def test_d2_non_object_body(w, raw):
    for path, who, key in _paths(w):
        r = call("POST", path, w.t(who) if who else None, key=key, raw=raw)
        err(r, (400, 422), ("malformed_request", "validation_failed"), f"{path} {raw}")
        soft(r.status_code == 400, "non-object-body-422", path=path, raw=raw)


# ---------------------------------------------------------------- D2.3 wrong types, D3 missing

WRONG_TYPE = [
    ("/payments", "ada", {"to_handle": 5, "amount": 1}),
    ("/payments", "ada", {"to_handle": ["bob"], "amount": 1}),
    ("/payments", "ada", {"to_handle": {"h": "bob"}, "amount": 1}),
    ("/payments", "ada", {"to_handle": True, "amount": 1}),
    ("/requests", "ada", {"payer_handle": 5, "amount": 1}),
    ("/requests", "ada", {"payer_handle": ["bob"], "amount": 1}),
    ("/splits", "ada", {"amount": 10, "participant_handles": "ada"}),
    ("/splits", "ada", {"amount": 10, "participant_handles": {"a": 1}}),
    ("/splits", "ada", {"amount": 10, "participant_handles": 5}),
    ("/splits", "ada", {"amount": 10, "participant_handles": ["bob", 5]}),
    ("/splits", "ada", {"amount": 10, "participant_handles": [None]}),
    ("/settlements", "op", {"transfers": [{"from_handle": 5, "to_handle": "bob", "amount": 1}]}),
    ("/settlements", "op", {"transfers": [{"from_handle": "ada", "to_handle": ["bob"], "amount": 1}]}),
    ("/auth/signup", None, {"email": 5, "password": "longenough1", "display_name": "X"}),
    ("/auth/signup", None, {"email": "t1@example.com", "password": 12345678, "display_name": "X"}),
    ("/auth/signup", None, {"email": "t2@example.com", "password": "longenough1", "display_name": 5}),
    ("/auth/login", None, {"email": 5, "password": "longenough1"}),
    ("/auth/login", None, {"email": "ada@example.com", "password": 5}),
    ("/auth/login", None, {"email": ["ada@example.com"], "password": {"a": 1}}),
]


@pytest.mark.parametrize("path,who,body", WRONG_TYPE, ids=lambda v: json.dumps(v)[:60] if isinstance(v, dict) else str(v))
def test_d2_wrong_json_type_400(w, path, who, body):
    r = POST(path, w.t(who) if who else None, body, key=k() if who else None)
    err(r, 400, "malformed_request")


NULL_REQUIRED = [
    ("/payments", "ada", {"to_handle": None, "amount": 1}),
    ("/requests", "ada", {"payer_handle": None, "amount": 1}),
    ("/splits", "ada", {"amount": 10, "participant_handles": None}),
    ("/auth/signup", None, {"email": None, "password": "longenough1", "display_name": "X"}),
    ("/auth/login", None, {"email": "ada@example.com", "password": None}),
]


@pytest.mark.parametrize("path,who,body", NULL_REQUIRED, ids=lambda v: json.dumps(v)[:60] if isinstance(v, dict) else str(v))
def test_d2_null_required_field_is_4xx(w, path, who, body):
    r = POST(path, w.t(who) if who else None, body, key=k() if who else None)
    err(r, (400, 422), ("malformed_request", "validation_failed"))


MISSING = [
    ("/payments", "ada", {"amount": 1}),
    ("/payments", "ada", {"to_handle": "bob"}),
    ("/payments", "ada", {}),
    ("/requests", "ada", {"amount": 1}),
    ("/requests", "ada", {"payer_handle": "bob"}),
    ("/requests", "ada", {}),
    ("/splits", "ada", {"participant_handles": ["bob"]}),
    ("/splits", "ada", {"amount": 10}),
    ("/splits", "ada", {}),
    ("/settlements", "op", {}),
    ("/settlements", "op", {"transfers": [{"to_handle": "bob", "amount": 1}]}),
    ("/settlements", "op", {"transfers": [{"from_handle": "ada", "amount": 1}]}),
    ("/settlements", "op", {"transfers": [{"from_handle": "ada", "to_handle": "bob"}]}),
    ("/auth/signup", None, {"password": "longenough1", "display_name": "X"}),
    ("/auth/signup", None, {"email": "m1@example.com", "display_name": "X"}),
    ("/auth/signup", None, {"email": "m2@example.com", "password": "longenough1"}),
    ("/auth/signup", None, {}),
    ("/auth/login", None, {"password": "longenough1"}),
    ("/auth/login", None, {"email": "ada@example.com"}),
    ("/auth/login", None, {}),
]


@pytest.mark.parametrize("path,who,body", MISSING, ids=lambda v: json.dumps(v)[:60] if isinstance(v, dict) else str(v))
def test_d3_missing_required_field_422(w, path, who, body):
    r = POST(path, w.t(who) if who else None, body, key=k() if who else None)
    err(r, 422, "validation_failed")


# ---------------------------------------------------------------- D4/D5 amount

VALID_AMOUNTS = [("1", 1), ("1000", 1000), ("1000.0", 1000), ("1e3", 1000), ("1E3", 1000), ("1000000000", 10 ** 9),
                 ("1e9", 10 ** 9), ("1.0e2", 100), ("25e-1", None), ("10e-1", 1)]
INVALID_AMOUNTS = ["0", "-1", "1.5", '"100"', '"abc"', "true", "false", "null", "1000000001", "1e10", "[]", "{}",
                   "[5]", "0.5", "-0.0", "0.0", "1e30", "999999999.5", "1000000000.5", "-1000", "1e-3",
                   "123456789012345678901234567890"]


def _amount_bodies(w, amount_raw):
    q = None
    return [
        ("/payments", "ada", '{"to_handle": "bob", "amount": %s}' % amount_raw),
        ("/requests", "ada", '{"payer_handle": "bob", "amount": %s}' % amount_raw),
        ("/splits", "ada", '{"participant_handles": ["ada", "bob"], "amount": %s}' % amount_raw),
        ("/settlements", "op", '{"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": %s}]}' % amount_raw),
    ]


@pytest.mark.parametrize("raw,value", [a for a in VALID_AMOUNTS if a[1] is not None])
def test_d5_valid_amount_forms(w, raw, value):
    for path, who, body in _amount_bodies(w, raw):
        j = ok(call("POST", path, w.t(who), key=k(), raw=body), 201, f"{path} amount {raw}")
        got = j["payments"][0]["amount"] if path == "/settlements" else j["amount"]
        assert got == value and type(got) is int, f"{path}: amount {raw} came back as {got!r}"


@pytest.mark.parametrize("raw", INVALID_AMOUNTS + ["25e-1"])
def test_d4_invalid_amount_422(w, raw):
    before = (w.bal("ada"), w.bal("bob"), len(w.requests("ada", "limit=200")))
    for path, who, body in _amount_bodies(w, raw):
        r = call("POST", path, w.t(who), key=k(), raw=body)
        err(r, 422, "validation_failed", f"{path} amount {raw}")
    assert (w.bal("ada"), w.bal("bob"), len(w.requests("ada", "limit=200"))) == before


@pytest.mark.parametrize("raw", ["1e400", "-1e400", "1e999999"])
def test_d4_overflowing_amount_is_4xx(w, raw):
    for path, who, body in _amount_bodies(w, raw):
        r = call("POST", path, w.t(who), key=k(), raw=body)
        err(r, (400, 422), ("malformed_request", "validation_failed"), f"{path} amount {raw}")


# ---------------------------------------------------------------- D4.2 note

def _note_bodies(note_json):
    return [
        ("/payments", "ada", '{"to_handle": "bob", "amount": 1, "note": %s}' % note_json),
        ("/requests", "ada", '{"payer_handle": "bob", "amount": 1, "note": %s}' % note_json),
        ("/splits", "ada", '{"participant_handles": ["ada", "bob"], "amount": 2, "note": %s}' % note_json),
        ("/settlements", "op", '{"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1, "note": %s}]}'
         % note_json),
    ]


def _note_of(path, j):
    return j["payments"][0]["note"] if path == "/settlements" else j["note"]


@pytest.mark.parametrize("note", ["x" * 200, "é" * 200, "", " ", "a" * 199 + "é"])
def test_d4_note_up_to_200_chars_ok(w, note):
    for path, who, body in _note_bodies(json.dumps(note, ensure_ascii=False)):
        j = ok(call("POST", path, w.t(who), key=k(), raw=body), 201, path)
        assert _note_of(path, j) == note


def test_d4_note_200_emoji(w):
    note = "😀" * 200
    for path, who, body in _note_bodies(json.dumps(note, ensure_ascii=False)):
        r = call("POST", path, w.t(who), key=k(), raw=body)
        if soft(r.status_code == 201, "200-emoji-note-rejected", path=path, status=r.status_code):
            assert _note_of(path, r.json()) == note
        else:
            err(r, 422, "validation_failed")


@pytest.mark.parametrize("note", ["x" * 201, "é" * 201, "😀" * 201, "x" * 5000])
def test_d4_note_over_200_chars_422(w, note):
    for path, who, body in _note_bodies(json.dumps(note, ensure_ascii=False)):
        err(call("POST", path, w.t(who), key=k(), raw=body), 422, "validation_failed", path)


@pytest.mark.parametrize("note_json", ["null", "5", "true", "[]", "{}", '["a"]', "1.5"])
def test_d4_non_string_note_422(w, note_json):
    for path, who, body in _note_bodies(note_json):
        err(call("POST", path, w.t(who), key=k(), raw=body), 422, "validation_failed", f"{path} note {note_json}")


# ---------------------------------------------------------------- D4.3 visibility

@pytest.mark.parametrize("vis_json", ['"PUBLIC"', '"Private"', '"friends"', '""', "null", "1", "true", "[]", "{}",
                                      '" public"', '["public"]'])
def test_d4_bad_visibility_422(w, vis_json):
    q = w.new_request("bob", "ada", 3)
    cases = [
        ("/payments", "ada", '{"to_handle": "bob", "amount": 1, "visibility": %s}' % vis_json),
        (f"/requests/{q['request_id']}/pay", "ada", '{"visibility": %s}' % vis_json),
        ("/settlements", "op", '{"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1, "visibility": %s}]}'
         % vis_json),
    ]
    for path, who, body in cases:
        err(call("POST", path, w.t(who), key=k(), raw=body), 422, "validation_failed", f"{path} visibility {vis_json}")
    still = {x["request_id"]: x for x in w.requests("ada", "status=pending&limit=200")}
    assert q["request_id"] in still
    ok(POST(f"/requests/{q['request_id']}/cancel", w.t("bob")), 200)


def test_d4_visibility_values_and_default(w):
    assert ok(w.pay("ada", "bob", 1), 201)["visibility"] == "public"
    assert ok(w.pay("ada", "bob", 1, visibility="public"), 201)["visibility"] == "public"
    assert ok(w.pay("ada", "bob", 1, visibility="private"), 201)["visibility"] == "private"
    assert ok(w.pay("ada", "bob", 1), 201)["note"] == ""


# ---------------------------------------------------------------- D8 Idempotency-Key range

def _five(w):
    q1 = w.new_request("bob", "ada", 2)
    return [("/payments", "ada", {"to_handle": "bob", "amount": 1}),
            ("/requests", "ada", {"payer_handle": "bob", "amount": 1}),
            (f"/requests/{q1['request_id']}/pay", "ada", {}),
            ("/splits", "ada", {"amount": 3, "participant_handles": ["ada", "bob"]}),
            ("/settlements", "op", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]})]


def test_d8_key_absent_or_empty_400(w):
    for path, who, body in _five(w):
        err(POST(path, w.t(who), body), 400, "missing_idempotency_key", f"{path} no key")
        err(POST(path, w.t(who), body, key=""), 400, "missing_idempotency_key", f"{path} empty key")


def test_d8_key_255_ok_256_rejected(w):
    for path, who, body in _five(w):
        err(POST(path, w.t(who), body, key="k" * 256), 422, "validation_failed", f"{path} 256")
        err(POST(path, w.t(who), body, key="k" * 2000), 422, "validation_failed", f"{path} 2000")
        k255 = (k() + "z" * 255)[:255]
        first = ok(POST(path, w.t(who), body, key=k255), 201, f"{path} 255")
        assert ok(POST(path, w.t(who), body, key=k255), 200, f"{path} 255 replay") == first
        if not path.endswith("/pay"):  # a one-character key is valid too
            ok(POST(path, w.t(who), body, key="x"), 201, f"{path} 1-char key")


def test_d8_key_not_needed_for_decline_cancel(w):
    q = w.new_request("bob", "ada", 2)
    assert ok(POST(f"/requests/{q['request_id']}/decline", w.t("ada")), 200)["status"] == "declined"
    assert ok(POST(f"/requests/{q['request_id']}/decline", w.t("ada"), {}, key=k()), 200)["status"] == "declined"
    q = w.new_request("bob", "ada", 2)
    assert ok(POST(f"/requests/{q['request_id']}/cancel", w.t("bob"), {"x": 1}, key=k()), 200)["status"] == "cancelled"
    assert ok(POST(f"/requests/{q['request_id']}/cancel", w.t("bob")), 200)["status"] == "cancelled"


# ---------------------------------------------------------------- D9 authentication on every endpoint

def _authed(w):
    q = w.new_request("bob", "ada", 2)
    rid = q["request_id"]
    return [("GET", "/me", None), ("GET", "/requests", None), ("GET", "/activity", None),
            ("POST", "/payments", {"to_handle": "bob", "amount": 1}),
            ("POST", "/requests", {"payer_handle": "bob", "amount": 1}),
            ("POST", f"/requests/{rid}/pay", {}), ("POST", f"/requests/{rid}/decline", None),
            ("POST", f"/requests/{rid}/cancel", None),
            ("POST", "/splits", {"amount": 3, "participant_handles": ["ada", "bob"]}),
            ("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]})]


def test_d9_unauthenticated_everywhere(w):
    good = w.t("ada")
    variants = [{}, {"Authorization": "Bearer bogus-token"}, {"Authorization": "Basic YWRhOnB3"},
                {"Authorization": "Bearer"}, {"Authorization": good},
                {"Authorization": f"Token {good}"}, {"Authorization": ""}, {"Authorization": f"Bearer {good}x"},
                {"Authorization": f"Bearer {good[:-1]}"}, {"Authorization": "Bearer null"}]
    before = w.snapshot()
    for method, path, body in _authed(w):
        for hv in variants:
            for with_key in (True, False):
                if method == "GET" and with_key:
                    continue
                kw = {"headers": hv}
                if body is not None:
                    kw["body"] = body
                r = call(method, path, key=k() if with_key else None, **kw)
                err(r, 401, "unauthenticated", f"{method} {path} {hv}")
        # 401 also wins over an unparseable body
        if method == "POST":
            err(call("POST", path, raw=b"{bad", key=k()), 401, "unauthenticated", f"{path} bad body, no token")
    after = w.snapshot()
    assert {h: v["me"] for h, v in after.items()} == {h: v["me"] for h, v in before.items()}


def test_d9_public_endpoints_need_no_token(w):
    assert GET("/health").status_code == 200
    assert GET("/health", headers={"Authorization": "Bearer bogus"}).status_code == 200
    assert GET("/_test/export").status_code == 200
    ok(POST("/auth/login", body={"email": "ada@example.com", "password": "correct horse"},
            headers={"Authorization": "Bearer bogus"}), 200)


# ---------------------------------------------------------------- D10 content types

@pytest.mark.parametrize("ct", ["application/json", "application/json; charset=utf-8", "application/json;charset=UTF-8"])
def test_d10_json_content_types_accepted(w, ct):
    ok(call("POST", "/payments", w.t("ada"), key=k(), body={"to_handle": "bob", "amount": 1, "note": "zażółć"},
            ctype=ct), 201)


@pytest.mark.parametrize("ct", ["text/plain", "application/x-www-form-urlencoded", None, "application/xml",
                                "multipart/form-data; boundary=x", "application/json; charset=latin-1"])
def test_d10_other_content_types_never_5xx(w, ct):
    r = call("POST", "/payments", w.t("ada"), key=k(), body={"to_handle": "bob", "amount": 1}, ctype=ct)
    assert r.status_code in (201, 400, 415, 422), f"{ct}: {r.status_code} {r.text[:200]}"
    r = call("POST", "/payments", w.t("ada"), key=k(), raw=b"to_handle=bob&amount=1", ctype=ct)
    assert 400 <= r.status_code < 500


# ---------------------------------------------------------------- D11 unknown request ids

@pytest.mark.parametrize("rid", ["nope", "rq_999999", "x" * 65, "x" * 300, "%20", "..", "rq_1%00", "😀", "a%2Fb",
                                 "-1", "0", "null"])
@pytest.mark.parametrize("action", ["pay", "decline", "cancel"])
def test_d11_unknown_request_id_404(w, rid, action):
    r = POST(f"/requests/{rid}/{action}", w.t("ada"), {}, key=k() if action == "pay" else None)
    err(r, 404, "not_found", f"{action} {rid}")


# ---------------------------------------------------------------- D6/D7 query parameters (last: this fixture resets the service)

@pytest.fixture(scope="module")
def wq():
    w = World().login_all()
    for i in range(3):
        ok(w.pay("ada", "bob", 1), 201)
        w.new_request("bob", "ada", 1)
    return w


@pytest.mark.parametrize("ep", ["/requests", "/activity"])
@pytest.mark.parametrize("q,n", [("limit=1", 1), ("limit=2", 2), ("limit=200", 3), ("limit=3&offset=0", 3),
                                 ("offset=1", 2), ("offset=3", 0), ("offset=100000", 0), ("", 3),
                                 ("limit=200&offset=2", 1)])
def test_d7_valid_limit_offset(wq, ep, q, n):
    j = ok(GET(f"{ep}?{q}" if q else ep, wq.t("ada")), 200)
    items = j["requests" if ep == "/requests" else "payments"]
    assert len(items) == n, f"{ep}?{q}: {len(items)} items"
    assert isinstance(j["has_more"], bool)


BAD_Q = ["limit=0", "limit=201", "limit=-1", "limit=abc", "limit=1e9", "limit=1e1", "limit=4.0", "limit=+4",
         "limit=%2B4", "limit=", "limit=%204", "limit=4%20", "limit=0x10", "limit=1,0", "limit=1000000",
         "limit=99999999999999999999999999", "limit=٣", "limit=null", "limit=true",
         "offset=-1", "offset=1.0", "offset=abc", "offset=+1", "offset=%2B1", "offset=1e0", "offset=", "offset=-0",
         "offset=%201", "limit=10&offset=-5", "limit=0&offset=0"]


@pytest.mark.parametrize("ep", ["/requests", "/activity"])
@pytest.mark.parametrize("q", BAD_Q)
def test_d6_bad_limit_offset_422(wq, ep, q):
    err(GET(f"{ep}?{q}", wq.t("ada")), 422, "validation_failed", f"{ep}?{q}")


@pytest.mark.parametrize("ep", ["/requests", "/activity"])
def test_d7_huge_offset_no_5xx(wq, ep):
    r = GET(f"{ep}?offset=99999999999999999999999999999", wq.t("ada"))
    assert r.status_code in (200, 422), r.text[:200]


@pytest.mark.parametrize("q", ["direction=sideways", "direction=INCOMING", "direction=both", "status=open",
                               "status=PENDING", "status=canceled", "status=all", "direction=incoming&status=nope",
                               "direction=in&status=pending"])
def test_d7_unknown_direction_status_422(wq, q):
    err(GET(f"/requests?{q}", wq.t("ada")), 422, "validation_failed", q)
    ok(GET(f"/activity?{q}", wq.t("ada")), 200)
