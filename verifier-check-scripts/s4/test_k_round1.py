"""K. Fix round 1: one check per finding of the first verdict, plus checks for the code that changed
between 5493ad0 and 6c6d0a6 (transport errors, exact number parsing, deep bodies, fixture/import validation)."""
import copy
import json
import socket
from urllib.parse import urlsplit

import pytest

from lib import BASE, GET, POST, World, call, code_of, err, fixture, k, ok, user

_u = urlsplit(BASE)


def raw(data: bytes, timeout=6.0) -> tuple[int, str, str]:
    """Send bytes, return (status, content-type, body)."""
    s = socket.create_connection((_u.hostname, _u.port), timeout=timeout)
    buf = b""
    try:
        s.sendall(data)
        while True:
            try:
                chunk = s.recv(65536)
            except (socket.timeout, ConnectionError):
                break
            if not chunk:
                break
            buf += chunk
            if b"\r\n\r\n" in buf:
                head, _, rest = buf.partition(b"\r\n\r\n")
                cl = [l for l in head.split(b"\r\n") if l.lower().startswith(b"content-length:")]
                if cl and len(rest) >= int(cl[0].split(b":")[1]):
                    break
    finally:
        s.close()
    text = buf.decode("latin-1")
    head, _, body = text.partition("\r\n\r\n")
    lines = head.split("\r\n")
    status = int(lines[0].split()[1]) if lines[0].startswith("HTTP/") else -1
    ct = next((l.split(":", 1)[1].strip() for l in lines if l.lower().startswith("content-type:")), "")
    return status, ct, body


def assert_json_4xx(res, label, statuses=None):
    status, ct, body = res
    assert 400 <= status < 500, f"{label}: status {status}, body {body[:120]!r}"
    if statuses:
        assert status in statuses, f"{label}: status {status}"
    assert ct.lower().replace(" ", "") == "application/json;charset=utf-8", f"{label}: content type {ct!r}"
    e = json.loads(body)["error"]
    assert isinstance(e["code"], str) and isinstance(e["message"], str), f"{label}: {body[:120]}"


@pytest.fixture()
def w():
    return World().login_all()


# ---------------------------------------------------------------- finding 1, N2, N4, finding 5

@pytest.mark.parametrize("method", ["OPTIONS", "TRACE", "CONNECT", "PROPFIND", "get", "FOO", "LINK"])
@pytest.mark.parametrize("path", ["/health", "/payments", "/me", "/nope"])
def test_k1_other_methods_json_4xx(w, method, path):
    assert_json_4xx(raw(f"{method} {path} HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {w.t('ada')}\r\n\r\n".encode()),
                    f"{method} {path}")


@pytest.mark.parametrize("path", ["/health", "/payments", "/me", "/activity", "/nope"])
def test_k1_head_4xx_or_2xx_without_body(w, path):
    r = call("HEAD", path, w.t("ada"))
    assert r.status_code < 500 and r.content == b""
    assert r.headers.get("content-type", "").lower().replace(" ", "") in ("application/json;charset=utf-8", "")


def test_k1_service_still_serves_after_odd_methods(w):
    for m in ("OPTIONS", "HEAD", "TRACE"):
        call(m, "/payments", w.t("ada"))
    ok(w.pay("ada", "bob", 1), 201)
    assert w.bal("ada") == 9999


TRANSPORT = {
    "garbage line": b"GARBAGE\r\n\r\n",
    "bad version": b"GET /health HTTP/9.9\r\nHost: x\r\n\r\n",
    "four words": b"GET /health HTTP/1.1 extra\r\nHost: x\r\n\r\n",
    "url 70000 bytes": b"GET /health?x=" + b"a" * 70000 + b" HTTP/1.1\r\nHost: x\r\n\r\n",
    "150 headers": b"GET /health HTTP/1.1\r\nHost: x\r\n" + b"".join(b"X-H%d: 1\r\n" % i for i in range(150)) + b"\r\n",
    "header 70000 bytes": b"GET /health HTTP/1.1\r\nHost: x\r\nX-Big: " + b"a" * 70000 + b"\r\n\r\n",
    "absolute form bad host": b"GET http://[bad/me HTTP/1.1\r\nHost: x\r\n\r\n",
    "absolute form bad host post": b"POST http://[::zz/payments HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\n\r\n{}",
    "content-length abc": b"POST /payments HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\n\r\n",
    "content-length negative": b"POST /payments HTTP/1.1\r\nHost: x\r\nContent-Length: -5\r\n\r\n",
    "content-length huge": b"POST /payments HTTP/1.1\r\nHost: x\r\nContent-Length: 99999999999999999999999\r\n\r\n",
    "chunk 7FFFFFFFFFFF": b"POST /payments HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n7FFFFFFFFFFF\r\nabc\r\n0\r\n\r\n",
    "chunk 24 F": b"POST /payments HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\nFFFFFFFFFFFFFFFFFFFFFFFF\r\nabc\r\n0\r\n\r\n",
    "chunk negative": b"POST /payments HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n-5\r\nabc\r\n0\r\n\r\n",
    "chunk zz": b"POST /payments HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\nabc\r\n0\r\n\r\n",
    "chunk huge on reset": b"POST /_test/reset HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n7FFFFFFFFFFF\r\nabc\r\n0\r\n\r\n",
}


@pytest.mark.parametrize("name", list(TRANSPORT))
def test_k1_transport_errors_are_json_4xx(name):
    assert_json_4xx(raw(TRANSPORT[name]), name)
    assert GET("/health").status_code == 200


def test_k1_chunked_valid_body_still_works(w):
    body = b'{"to_handle":"bob","amount":3}'
    head = (f"POST /payments HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {w.t('ada')}\r\nIdempotency-Key: ck1\r\n"
            "Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n").encode()
    status, ct, out = raw(head + b"%x\r\n" % len(body) + body + b"\r\n0\r\n\r\n")
    assert status == 201 and json.loads(out)["amount"] == 3
    assert w.bal("ada") == 9997


def test_k1_body_cap_is_4xx_and_ordinary_sizes_pass(w):
    big_unknown = {"to_handle": "bob", "amount": 1, "pad": "x" * 200_000}  # 200 KB: an ordinary large body
    ok(POST("/payments", w.t("ada"), big_unknown, key=k()), 201)
    r = POST("/payments", w.t("ada"), {"to_handle": "bob", "amount": 1, "pad": "x" * 1_200_000}, key=k())
    assert 400 <= r.status_code < 500
    assert w.bal("ada") == 9999


# ---------------------------------------------------------------- finding 2, N1

@pytest.mark.parametrize("ep", ["/activity", "/requests"])
@pytest.mark.parametrize("digits", [31, 4300, 4301, 4400, 20000])
def test_k2_long_limit_422_long_offset_ok(w, ep, digits):
    err(GET(f"{ep}?limit={'9' * digits}", w.t("ada")), 422, "validation_failed")
    r = GET(f"{ep}?offset={'9' * digits}", w.t("ada"))
    j = ok(r, 200)
    assert j["has_more"] is False and j.get("payments", j.get("requests")) == []


@pytest.mark.parametrize("ep", ["/activity", "/requests"])
def test_k2_long_values_with_leading_zeros(w, ep):
    ok(w.pay("ada", "bob", 1), 201)
    w.new_request("bob", "ada", 1)
    zeros = "0" * 40
    j = ok(GET(f"{ep}?limit={zeros}1&offset={zeros}", w.t("ada")), 200)
    assert len(j.get("payments", j.get("requests"))) == 1
    err(GET(f"{ep}?limit={zeros}", w.t("ada")), 422, "validation_failed")


# ---------------------------------------------------------------- finding 3, N6

@pytest.mark.parametrize("section,field", [("payments", "from_user_id"), ("payments", "to_user_id"),
                                           ("requests", "requester_id"), ("requests", "payer_id")])
@pytest.mark.parametrize("bad", [["u_ada"], {"id": "u_ada"}, [], {}, 5, None, True, 1.5])
def test_k3_reset_bad_reference_types(section, field, bad):
    w = World().login_all()
    ok(w.pay("ada", "bob", 7), 201)
    before = w.snapshot()
    fx = fixture(payments=[{"id": "p1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1, "note": "",
                            "visibility": "public"}],
                 requests=[{"id": "r1", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 1, "note": "",
                            "status": "pending"}])
    fx[section][0][field] = bad
    r = call("POST", "/_test/reset", body=fx)
    err(r, (400, 422), ("malformed_request", "validation_failed"), f"{section}.{field}={bad!r}")
    assert w.snapshot() == before


@pytest.mark.parametrize("mut", [
    lambda fx: fx["users"][0].__setitem__("handle", "ada\n"),
    lambda fx: fx["users"][0].__setitem__("handle", "\nada"),
    lambda fx: fx["users"][0].__setitem__("id", ["u_ada"]),
    lambda fx: fx["users"][0].__setitem__("email", {"a": 1}),
    lambda fx: fx["users"][0].__setitem__("handle", ["ada"]),
    lambda fx: fx.__setitem__("settlement_operator_ids", [["u_op"]]),
    lambda fx: fx.__setitem__("settlement_operator_ids", {"u_op": 1}),
    lambda fx: fx.__setitem__("currency", ["EUR"]),
    lambda fx: fx.__setitem__("minor_units", [2]),
    lambda fx: fx["users"].append([1, 2]),
])
def test_k3_reset_other_bad_shapes(mut):
    w = World().login_all()
    before = w.snapshot()
    fx = fixture()
    mut(fx)
    r = call("POST", "/_test/reset", body=fx)
    err(r, (400, 422), ("malformed_request", "validation_failed"))
    assert w.snapshot() == before


# ---------------------------------------------------------------- finding 4

def nested(depth, obj=False):
    inner = ('{"a":' * depth + "1" + "}" * depth) if obj else ("[" * depth + "]" * depth)
    return '{"to_handle":"bob","amount":1,"x":' + inner + "}"


@pytest.mark.parametrize("depth", [10, 400, 500, 600, 850, 898, 899, 900, 901, 950, 1500, 2990, 3100, 5000, 100000])
@pytest.mark.parametrize("obj", [False, True])
def test_k4_deep_body_same_answer_on_first_use_and_replay(w, depth, obj):
    body = nested(depth, obj)
    key = k()
    a = call("POST", "/payments", w.t("ada"), key=key, raw=body)
    b = call("POST", "/payments", w.t("ada"), key=key, raw=body)
    assert a.status_code in (201, 400), a.text[:200]
    if a.status_code == 201:
        assert b.status_code == 200 and b.json() == a.json(), f"depth {depth}: replay {b.status_code} {b.text[:120]}"
        assert w.bal("ada") == 9999
        # the stored body must survive export/import: "It must accept an unchanged export produced by this service"
        e = call("GET", "/_test/export")
        assert e.status_code == 200
        r = call("POST", "/_test/import", raw=e.content)
        assert r.status_code == 204, f"depth {depth}: import of own export -> {r.status_code} {r.text[:200]}"
        c = call("POST", "/payments", w.t("ada"), key=key, raw=body)
        assert c.status_code == 200 and c.json() == a.json()
    else:
        err(a, 400, "malformed_request")
        err(b, 400, "malformed_request")
        assert w.bal("ada") == 10000
    if depth <= 600:
        assert a.status_code == 201


# ---------------------------------------------------------------- findings 6 and 7

BAD_NUMBERS = ["0.99999999999999999999", "1.00000000000000000001", "1000000000.0000000001", "999999999.9999999999999999",
               "1e-400", "1e-5000", "0." + "0" * 5000 + "1", "1." + "0" * 300 + "1", "9" * 4301, "9" * 50000,
               "-" + "9" * 4301, "1e999999999", "1e99999999999999999999", "1e-99999999999999999999",
               "0e99999999999999999999", "1E+1000000000000000000", "-1e99999999999999999999", "1e400", "5e-1",
               "1000000001.0", "1e9000", "0.1e1000000000000000000000", "2e9"]
GOOD_NUMBERS = [("1.0", 1), ("1e0", 1), ("1E0", 1), ("10e-1", 1), ("1e3", 1000), ("1000.000000000000000000000", 1000),
                ("1." + "0" * 5000, 1), ("0.001e3", 1), ("1e+3", 1000), ("100000000000e-2", 10 ** 9),
                ("0.0000000001e19", 10 ** 9), ("1e9", 10 ** 9)]


def number_bodies(num):
    return [("/payments", "ada", '{"to_handle":"bob","amount":%s}' % num),
            ("/requests", "ada", '{"payer_handle":"bob","amount":%s}' % num),
            ("/splits", "ada", '{"participant_handles":["ada","bob"],"amount":%s}' % num),
            ("/settlements", "op", '{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":%s}]}' % num)]


@pytest.fixture(scope="module")
def rich():
    return World(fixture(users=[user("ada", 10 ** 13), user("bob", 0), user("op", 0)])).login_all()


@pytest.mark.parametrize("num", BAD_NUMBERS, ids=lambda s: s[:28] + ("…" if len(s) > 28 else ""))
def test_k6_non_integral_or_out_of_range_amount_422(rich, num):
    before = rich.bal("bob")
    for path, who, body in number_bodies(num):
        r = call("POST", path, rich.t(who), key=k(), raw=body)
        err(r, 422, "validation_failed", f"{path} amount {num[:40]}")
    assert rich.bal("bob") == before


@pytest.mark.parametrize("num,value", GOOD_NUMBERS, ids=lambda s: str(s)[:28])
def test_k6_integral_spellings_accepted(rich, num, value):
    for path, who, body in number_bodies(num):
        j = ok(call("POST", path, rich.t(who), key=k(), raw=body), 201, f"{path} amount {num[:40]}")
        got = j["payments"][0]["amount"] if path == "/settlements" else j["amount"]
        assert got == value and type(got) is int


@pytest.mark.parametrize("num", ["1e99999999999999999999", "9" * 5000, "0.5", "1e-99999999999999999999", "-0.0", "1.25e1"])
def test_k6_odd_numbers_in_ignored_fields_and_query_do_not_break(w, num):
    body = '{"to_handle":"bob","amount":2,"x":%s,"y":[%s]}' % (num, num)
    key = k()
    a = call("POST", "/payments", w.t("ada"), key=key, raw=body)
    assert a.status_code in (201, 400), a.text[:200]
    b = call("POST", "/payments", w.t("ada"), key=key, raw=body)
    if a.status_code == 201:
        assert b.status_code == 200 and b.json() == a.json()
    for path in ("/_test/reset", "/_test/import", "/auth/login", "/auth/signup"):
        r = call("POST", path, raw='{"x":%s}' % num)
        assert 400 <= r.status_code < 500, f"{path}: {r.status_code}"


@pytest.mark.parametrize("field,num,okay", [("balance", "0.99999999999999999999", False), ("balance", "1e4", True),
                                            ("balance", "2500.0", True), ("balance", "9" * 4400, False),
                                            ("balance", "1e99999999999999999999", False), ("balance", "-0.5", False),
                                            ("minor_units", "2.5", False), ("minor_units", "1e99999999999999999999", False)])
def test_k6_fixture_numbers_exact(field, num, okay):
    w = World().login_all()
    before = w.snapshot()
    fx = fixture(users=[user("ada", 111), user("bob", 5)])
    raw_fx = json.dumps(fx).replace('"balance": 111', '"balance": %s' % num) if field == "balance" else \
        json.dumps(fx).replace('"minor_units": 2', '"minor_units": %s' % num)
    assert num in raw_fx
    r = call("POST", "/_test/reset", raw=raw_fx)
    if okay:
        assert r.status_code == 204, r.text[:200]
    else:
        err(r, (400, 422), ("malformed_request", "validation_failed"))
        assert w.snapshot() == before


def test_k6_fractional_unknown_field_replays_before_and_after_import(w):
    """An ignored field holding an ordinary fraction (e.g. a client-side coordinate) must not disturb §7 or §10."""
    cases = [("/payments", "ada", {"to_handle": "bob", "amount": 5, "lat": 52.52, "ts": 1759381200.25}),
             ("/requests", "ada", {"payer_handle": "bob", "amount": 5, "ratio": 0.5}),
             ("/splits", "ada", {"amount": 9, "participant_handles": ["bob", "cy"], "weights": [0.5, 0.25, 1e-7]}),
             ("/settlements", "op", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1, "fee": 0.1}]})]
    done = []
    for path, who, body in cases:
        key = k()
        j = ok(POST(path, w.t(who), body, key=key), 201, path)
        assert ok(POST(path, w.t(who), body, key=key), 200, f"{path} replay") == j
        err(POST(path, w.t(who), {**body, "other": 0.75}, key=key), 409, "idempotency_key_reuse")
        done.append((path, who, body, key, j))
    snap = w.snapshot()
    e = call("GET", "/_test/export")
    r = call("POST", "/_test/import", raw=e.content)
    assert r.status_code == 204, r.text[:200]
    assert w.snapshot() == snap
    for path, who, body, key, j in done:
        r = POST(path, w.t(who), body, key=key)
        assert r.status_code == 200 and r.json() == j, f"{path}: replay after import -> {r.status_code} {r.text[:160]}"
    assert w.snapshot() == snap
    e2 = call("GET", "/_test/export")
    assert call("POST", "/_test/import", raw=e2.content).status_code == 204
    for path, who, body, key, j in done:
        r = POST(path, w.t(who), body, key=key)
        assert r.status_code == 200 and r.json() == j, f"{path}: replay after second import -> {r.status_code}"


# ---------------------------------------------------------------- finding 8

def rich_state():
    w = World().login_all()
    ok(w.pay("ada", "bob", 5, note="n"), 201)
    q = w.new_request("bob", "ada", 7)
    ok(w.pay_request("ada", q["request_id"]), 201)
    ok(POST("/splits", w.t("ada"), {"amount": 9, "participant_handles": ["bob", "cy"]}, key=k()), 201)
    ok(POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]},
            key=k()), 201)
    return w


def _first(st, name):
    return st[name][0]


STATE_MUTATIONS = {
    "payment amount -5": lambda s: _first(s, "payments").__setitem__("amount", -5),
    "payment created_at yesterday": lambda s: _first(s, "payments").__setitem__("created_at", "yesterday"),
    "payment created_at no offset": lambda s: _first(s, "payments").__setitem__("created_at", "2026-10-02T04:00:00"),
    "payment created_at with newline": lambda s: _first(s, "payments").__setitem__("created_at", "2026-10-02T04:00:00+00:00\n"),
    "payment id 100 chars": lambda s: _first(s, "payments").__setitem__("id", "p" * 100),
    "payment id empty": lambda s: _first(s, "payments").__setitem__("id", ""),
    "payment request_id 5": lambda s: _first(s, "payments").__setitem__("request_id", 5),
    "payment request_id unknown": lambda s: _first(s, "payments").__setitem__("request_id", "rq_ghost"),
    "payment settlement_id unknown": lambda s: _first(s, "payments").__setitem__("settlement_id", "st_ghost"),
    "payment amount 1.5": lambda s: _first(s, "payments").__setitem__("amount", 1.5),
    "payment amount string": lambda s: _first(s, "payments").__setitem__("amount", "5"),
    "payment note 201 chars": lambda s: _first(s, "payments").__setitem__("note", "x" * 201),
    "payment note null": lambda s: _first(s, "payments").__setitem__("note", None),
    "payment visibility list": lambda s: _first(s, "payments").__setitem__("visibility", ["public"]),
    "payment from list": lambda s: _first(s, "payments").__setitem__("from_user_id", ["u_ada"]),
    "user id 100 chars": lambda s: _first(s, "users").__setitem__("id", "u" * 100),
    "user id number": lambda s: _first(s, "users").__setitem__("id", 5),
    "user handle newline": lambda s: _first(s, "users").__setitem__("handle", "ada\n"),
    "user handle upper": lambda s: _first(s, "users").__setitem__("handle", "ADA"),
    "user balance -1": lambda s: _first(s, "users").__setitem__("balance", -1),
    "user balance above 2^53": lambda s: _first(s, "users").__setitem__("balance", 2 ** 53 + 1),
    "user email no at": lambda s: _first(s, "users").__setitem__("email", "nope"),
    "user removed but referenced": lambda s: s["users"].pop(0),
    "request amount -1": lambda s: _first(s, "requests").__setitem__("amount", -1),
    "request status open": lambda s: _first(s, "requests").__setitem__("status", "open"),
    "request payment_id unknown": lambda s: _first(s, "requests").__setitem__("payment_id", "p_ghost"),
    "request created_at number": lambda s: _first(s, "requests").__setitem__("created_at", 5),
    "request payer unknown": lambda s: _first(s, "requests").__setitem__("payer_id", "u_ghost"),
    "request id duplicate": lambda s: s["requests"].append(copy.deepcopy(s["requests"][0])),
    "settlement committed_at bad": lambda s: _first(s, "settlements").__setitem__("committed_at", "soon"),
    "settlement payment unknown": lambda s: _first(s, "settlements").__setitem__("payment_ids", ["p_ghost"]),
    "split request unknown": lambda s: _first(s, "splits").__setitem__("request_ids", ["rq_ghost"]),
    "token to unknown user": lambda s: s["tokens"].__setitem__("tok", "u_ghost"),
    "token to list": lambda s: s["tokens"].__setitem__("tok", ["u_ada"]),
    "operator unknown": lambda s: s["operators"].append("u_ghost"),
    "operator list": lambda s: s["operators"].append(["u_op"]),
    "idempotency response null": lambda s: _first(s, "idempotency").__setitem__("response", None),
    "idempotency key empty": lambda s: _first(s, "idempotency").__setitem__("key", ""),
    "idempotency key 256": lambda s: _first(s, "idempotency").__setitem__("key", "k" * 256),
    "idempotency user unknown": lambda s: _first(s, "idempotency").__setitem__("user_id", "u_ghost"),
    "minor_units 7": lambda s: s.__setitem__("minor_units", 7),
    "currency number": lambda s: s.__setitem__("currency", 5),
    "counters string value": lambda s: s["counters"].__setitem__("p", "9"),
}


@pytest.fixture(scope="module")
def imp_world():
    w = rich_state()
    return w, call("GET", "/_test/export").json(), w.snapshot()


@pytest.mark.parametrize("name", list(STATE_MUTATIONS))
def test_k8_invalid_state_rejected_without_change(imp_world, name):
    w, e, before = imp_world
    doc = copy.deepcopy(e)
    try:
        STATE_MUTATIONS[name](doc["state"])
    except (KeyError, IndexError) as exc:  # the state format changed: the mutation no longer applies
        pytest.fail(f"mutation {name} does not apply to this export format: {exc!r}")
    r = call("POST", "/_test/import", body=doc)
    unchanged = w.snapshot() == before
    if r.status_code == 204 or not unchanged:
        assert call("POST", "/_test/import", body=e).status_code == 204
    err(r, 422, "validation_failed", name)
    assert unchanged, f"{name}: destination changed"


def test_k8_unchanged_export_still_imports(imp_world):
    w, e, before = imp_world
    assert call("POST", "/_test/import", body=e).status_code == 204
    assert w.snapshot() == before


# ---------------------------------------------------------------- N7, N9, path spellings

def test_k7_replay_through_encoded_path(w):
    q = w.new_request("bob", "ada", 5)
    rid = q["request_id"]
    enc = rid.replace("_", "%5F")
    assert enc != rid
    p = ok(POST(f"/requests/{rid}/pay", w.t("ada"), {}, key="enc1"), 201)
    assert ok(POST(f"/requests/{enc}/pay", w.t("ada"), {}, key="enc1"), 200) == p
    assert ok(POST(f"/requests/{rid}/pay?x=1", w.t("ada"), {}, key="enc1"), 200) == p
    assert w.bal("ada") == 9995
    # two different requests keep separate scopes
    q2 = w.new_request("bob", "ada", 6)
    p2 = ok(POST(f"/requests/{q2['request_id']}/pay", w.t("ada"), {}, key="enc1"), 201)
    assert p2["payment_id"] != p["payment_id"]


def test_k9_signup_email_after_import_and_login(w):
    err(POST("/auth/signup", body={"email": "a b@example.com", "password": "longenough1", "display_name": "x"}),
        422, "validation_failed")
    j = ok(POST("/auth/signup", body={"email": "o'neil+tag@sub.example.co", "password": "longenough1",
                                      "display_name": ""}), 201)
    e = call("GET", "/_test/export")
    assert call("POST", "/_test/import", raw=e.content).status_code == 204
    assert ok(GET("/me", j["token"]), 200)["handle"] == "o_neil_tag"


# ---------------------------------------------------------------- map clarification 3 (fix round 2)

@pytest.mark.parametrize("ep", ["/activity", "/requests"])
def test_k2_zero_padded_query_integers_use_their_value(ep):
    w = World().login_all()
    for _ in range(3):
        ok(w.pay("ada", "bob", 1), 201)
        w.new_request("bob", "ada", 1)
    items = lambda q: ok(GET(f"{ep}?{q}", w.t("ada")), 200)  # noqa: E731
    n = lambda j: len(j.get("payments", j.get("requests")))  # noqa: E731
    assert n(items("limit=0002")) == 2
    assert n(items("limit=0050&offset=000")) == 3
    assert n(items("limit=" + "0" * 5000 + "2")) == 2
    assert n(items("offset=" + "0" * 5000 + "1")) == 2
    assert n(items("limit=00200")) == 3
    err(GET(f"{ep}?limit=00201", w.t("ada")), 422, "validation_failed")
    err(GET(f"{ep}?limit=000", w.t("ada")), 422, "validation_failed")
    err(GET(f"{ep}?limit=" + "0" * 100, w.t("ada")), 422, "validation_failed")
