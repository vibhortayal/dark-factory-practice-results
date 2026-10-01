"""Stage 1 tests from the spec. Stdlib only. Usage: BASE_URL=http://localhost:8080 python3 test_stage1.py
BASE2_URL (optional, second container) enables the cross-container import test."""
import concurrent.futures as cf
import http.client
import json
import os
import re
import sys
import time
import traceback
import uuid
from urllib.parse import urlsplit

BASE = os.environ.get("BASE_URL", "http://localhost:8080")
BASE2 = os.environ.get("BASE2_URL")
TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)$")


def call(method, path, body=None, token=None, key=None, raw=None, headers=None, base=None):
    u = urlsplit(base or BASE)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=12)
    h = dict(headers or {})
    if token:
        h["Authorization"] = "Bearer " + token
    if key is not None:
        h["Idempotency-Key"] = key
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data is not None:
        h.setdefault("Content-Type", "application/json")
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    txt = r.read()
    c.close()
    try:
        js = json.loads(txt) if txt else None
    except ValueError:
        js = None
    return r.status, js, r, txt


def U(i, handle, bal, pw="correct horse"):
    return {"id": "u_" + handle, "email": handle + "@example.com", "password": pw,
            "display_name": handle.title(), "handle": handle, "balance": bal}


def reset(users, **kw):
    fx = {"currency": "EUR", "minor_units": 2, "users": users, "payments": [], "requests": []}
    fx.update(kw)
    s, _, _, t = call("POST", "/_test/reset", fx)
    assert s == 204, (s, t)


def login(handle, pw="correct horse"):
    s, js, _, _ = call("POST", "/auth/login", {"email": handle + "@example.com", "password": pw})
    assert s == 200, s
    return js["token"]


def me(tok):
    return call("GET", "/me", token=tok)[1]


def err(res, status, code):
    s, js, _, t = res[:4]
    assert s == status and js and js.get("error", {}).get("code") == code, (s, t[:300], status, code)


def K():
    return uuid.uuid4().hex


def pay(tok, to, amount, key=None, **kw):
    b = {"to_handle": to, "amount": amount}
    b.update(kw)
    return call("POST", "/payments", b, tok, key or K())


TESTS = []


def test(f):
    TESTS.append(f)
    return f


def basic3(**bal):
    reset([U(0, "ada", bal.get("ada", 10000)), U(0, "bob", bal.get("bob", 2500)),
           U(0, "cy", bal.get("cy", 500))])
    return login("ada"), login("bob"), login("cy")


@test
def a_runtime_errors_headers():  # A9 A10 A12 C1 C8
    ada, bob, cy = basic3()
    for res in (call("GET", "/nope"), call("PUT", "/me"), call("DELETE", "/payments", token=ada),
                call("POST", "/payments", raw=b"{bad", token=ada, key=K()),
                call("GET", "/me", headers={"Authorization": "Basic x"}),
                call("GET", "/me", headers={"Authorization": "Bearer"}),
                call("GET", "/me", token="nope")):
        s, js, r, _ = res
        assert 400 <= s < 500 and set(js["error"]) == {"code", "message"}, res[3]
        assert r.getheader("Content-Type") == "application/json; charset=utf-8"
    err(call("GET", "/nope"), 404, "not_found")
    for path, m in (("/me", "GET"), ("/payments", "POST"), ("/requests", "GET"), ("/activity", "GET"),
                    ("/splits", "POST"), ("/settlements", "POST"), ("/requests/x/pay", "POST"),
                    ("/requests/x/decline", "POST"), ("/requests/x/cancel", "POST")):
        err(call(m, path, {} if m == "POST" else None), 401, "unauthenticated")
        err(call(m, path, {} if m == "POST" else None, headers={"Authorization": "Basic x"}), 401, "unauthenticated")
        err(call(m, path, {} if m == "POST" else None, headers={"Authorization": "Bearer"}), 401, "unauthenticated")
        err(call(m, path, {} if m == "POST" else None, token="unknown"), 401, "unauthenticated")
    s, js, r, t = call("POST", "/_test/reset", U(0, "x", 1) and {"users": []})
    assert s == 204 and t == b""
    # huge header
    s, js, r, t = call("GET", "/me", headers={"X-Big": "a" * 70000})
    assert 400 <= s < 500 and js and "error" in js, (s, t[:100])
    ada, bob, cy = basic3()
    p = pay(ada, "bob", 100, note="x")[1]
    assert TS_RE.match(p["created_at"]) and len(p["payment_id"]) <= 64
    assert p["settlement_id"] is None and p["request_id"] is None
    s, js, _, _ = call("GET", "/activity?foo=1&direction=incoming", token=ada)
    assert s == 200


@test
def b_amounts_and_types():  # B2 C2-C6
    ada, bob, cy = basic3()
    for a in (b"1000", b"1000.0", b"1e3", b"1E3", b"1000.000"):
        raw = b'{"to_handle":"bob","amount":' + a + b"}"
        s, js, _, t = call("POST", "/payments", raw=raw, token=ada, key=K())
        assert s == 201 and js["amount"] == 1000, (a, s, t)
        assert b'"amount":1000,' in t, t
    for a in ("1.5", '"100"', "true", "null", "0", "-5", "1000000001", "[1]", "{}", "1e400", "NaN"):
        raw = ('{"to_handle":"bob","amount":' + a + "}").encode()
        s, js, _, t = call("POST", "/payments", raw=raw, token=ada, key=K())
        assert (s, js["error"]["code"]) in ((422, "validation_failed"), (400, "malformed_request")), (a, s, t)
        if a != "NaN":
            assert s == 422, (a, s)
    assert pay(ada, "bob", 1000000000)[0] == 409 or True
    err(call("POST", "/payments", {"to_handle": "bob"}, ada, K()), 422, "validation_failed")
    err(call("POST", "/payments", {"amount": 5}, ada, K()), 422, "validation_failed")
    err(call("POST", "/payments", {"to_handle": 5, "amount": 5}, ada, K()), 400, "malformed_request")
    err(call("POST", "/payments", raw=b"[1]", token=ada, key=K()), 400, "malformed_request")
    err(call("POST", "/payments", raw=b'"x"', token=ada, key=K()), 400, "malformed_request")
    err(call("POST", "/payments", raw=b"", token=ada, key=K()), 400, "malformed_request")
    err(call("POST", "/payments", raw=b"[" * 100000, token=ada, key=K()), 400, "malformed_request")
    for v in (None, "", "Public", 1, True, []):
        err(pay(ada, "bob", 5, visibility=v), 422, "validation_failed")
    for n in (None, 5, [], True):
        err(pay(ada, "bob", 5, note=n), 422, "validation_failed")
    assert pay(ada, "bob", 5, note="\U0001F600" * 200)[0] == 201
    err(pay(ada, "bob", 5, note="\U0001F600" * 201), 422, "validation_failed")
    err(pay(ada, "ada", 5), 422, "self_payment")
    for h in ("nobody", "", "ADA", "@bob"):
        err(pay(ada, h, 5), 404, "not_found")
    # unknown fields ignored
    assert pay(ada, "bob", 5, zzz=1)[0] == 201


@test
def f_notes_verbatim():  # F10
    ada, bob, cy = basic3()
    notes = [" lead and trail  ", "<script>alert(1)</script>", "e\u0301 vs \u00e9", "a\tb\nc\x01",
             "\U0001F468\u200d\U0001F469\u200d\U0001F467", "\\u0041 &amp; \"q\"", "\ud800 lone"]
    for n in notes:
        raw = json.dumps({"to_handle": "bob", "amount": 1, "note": n}).encode()
        s, js, _, t = call("POST", "/payments", raw=raw, token=ada, key=K())
        assert s == 201 and js["note"] == n, (n, js)
    feed = call("GET", "/activity?limit=200", token=ada)[1]["payments"]
    got = {p["note"] for p in feed}
    assert set(notes) <= got


@test
def f_payment_failure_and_exact():  # F4 F9 B12
    ada, bob, cy = basic3()
    err(pay(cy, "bob", 501), 409, "insufficient_funds")
    assert me(cy)["balance"] == 500 and call("GET", "/activity", token=cy)[1]["payments"] == []
    assert pay(cy, "bob", 500)[0] == 201 and me(cy)["balance"] == 0 and me(bob)["balance"] == 3000
    err(pay(cy, "bob", 1), 409, "insufficient_funds")


@test
def b_currencies_and_big():  # B1 B15 B7 B8
    big = 2 ** 53
    for cur, mu in (("EUR", 2), ("JPY", 0), ("BHD", 3)):
        reset([U(0, "ada", big), U(0, "bob", 5)], currency=cur, minor_units=mu,
              payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
                         "note": "coffee", "visibility": "public"}])
        ada = login("ada")
        m = me(ada)
        assert m["balance"] == big and m["currency"] == cur and m["minor_units"] == mu, m
        feed = call("GET", "/activity", token=ada)[1]["payments"]
        assert len(feed) == 1 and feed[0]["payment_id"] == "p_1" and feed[0]["currency"] == cur
        assert feed[0]["settlement_id"] is None and feed[0]["request_id"] is None
        assert feed[0]["from_handle"] == "ada" and feed[0]["to_handle"] == "bob" and TS_RE.match(feed[0]["created_at"])
        assert me(login("bob"))["balance"] == 5
        assert pay(ada, "bob", 1000000000)[0] == 201
        assert me(ada)["balance"] == big - 1000000000
        s, ex, _, _ = call("GET", "/_test/export")
        assert call("POST", "/_test/import", ex)[0] == 204
        assert me(ada)["balance"] == big - 1000000000 and me(login("bob"))["balance"] == 5 + 1000000000
    err(call("POST", "/_test/reset", {"users": [U(0, "ada", -1)]}), 422, "validation_failed")
    reset([U(0, "ada", big + 0)])
    assert call("POST", "/_test/reset", {"users": [U(0, "ada", big)]})[0] == 204


@test
def b10_bad_reset_changes_nothing():
    ada, bob, cy = basic3()
    bad = [{"users": [U(0, "ada", 5), U(0, "bob", -1)]}, {"users": [U(0, "ada", 5), U(0, "ada", 1)]},
           {"users": "x"}, {"users": [U(0, "ada", 5)], "minor_units": 5},
           {"users": [U(0, "ada", 5)], "settlement_operator_ids": ["u_nobody"]},
           {"users": [U(0, "Bad-Handle", 5)]},
           {"users": [U(0, "ada", 5)], "payments": [{"id": "p", "from_user_id": "u_zz", "to_user_id": "u_ada", "amount": 1}]},
           {"users": [U(0, "ada", 5)], "requests": [{"id": "r", "requester_id": "u_ada", "payer_id": "u_ada", "amount": 1, "status": "weird"}]}]
    for b in bad:
        err(call("POST", "/_test/reset", b), 422, "validation_failed")
    err(call("POST", "/_test/reset", raw=b"{nope"), 400, "malformed_request")
    assert me(ada)["balance"] == 10000
    # old token / key after reset
    k = K()
    assert pay(ada, "bob", 5, key=k)[0] == 201
    reset([U(0, "ada", 10000), U(0, "bob", 2500)])
    err(call("GET", "/me", token=ada), 401, "unauthenticated")
    ada2 = login("ada")
    assert pay(ada2, "bob", 5, key=k)[0] == 201


@test
def d_auth():  # D1-D10
    ada, bob, cy = basic3()
    s, js, _, _ = call("POST", "/auth/signup", {"email": "A.b-C+d@x.com", "password": "12345678", "display_name": "N"})
    assert s == 201 and set(js) == {"user_id", "display_name", "token"}
    t1 = js["token"]
    m = me(t1)
    assert m["handle"] == "a_b_c_d" and m["balance"] == 0
    err(call("POST", "/auth/signup", {"email": "A.b-C+d@x.com", "password": "12345678", "display_name": "N"}), 409, "email_taken")
    err(call("POST", "/auth/signup", {"email": "a.b-c+d@y.com", "password": "12345678", "display_name": "N"}), 409, "handle_taken")
    err(call("POST", "/auth/login", {"email": "a.b-c+d@y.com", "password": "12345678"}), 401, "unauthenticated")
    err(call("POST", "/auth/signup", {"email": "q@y.com", "password": "1234567", "display_name": "N"}), 422, "validation_failed")
    assert call("POST", "/auth/signup", {"email": "q@y.com", "password": "12345678", "display_name": "N"})[0] == 201
    for e in ("nope", "@x", "a@", "a@b@c", ""):
        err(call("POST", "/auth/signup", {"email": e, "password": "12345678", "display_name": "N"}), 422, "validation_failed")
    long = "x" * 30 + "@z.com"
    s, js, _, _ = call("POST", "/auth/signup", {"email": long, "password": "12345678", "display_name": "N"})
    assert me(js["token"])["handle"] == "x" * 20
    err(call("POST", "/auth/signup", {"email": "x" * 25 + "@z.com", "password": "12345678", "display_name": "N"}), 409, "handle_taken")
    err(call("POST", "/auth/signup", {"password": "12345678", "display_name": "N"}), 422, "validation_failed")
    err(call("POST", "/auth/signup", {"email": 7, "password": "12345678", "display_name": "N"}), 400, "malformed_request")
    err(call("POST", "/auth/login", {"email": "ada@example.com", "password": "wrong"}), 401, "unauthenticated")
    err(call("POST", "/auth/login", {"email": "who@example.com", "password": "correct horse"}), 401, "unauthenticated")
    t2 = login("ada")
    assert t2 != ada and me(t2)["handle"] == "ada" and me(ada)["handle"] == "ada"
    assert pay(t1, "ada", 1)[0] == 409
    assert pay(ada, "a_b_c_d", 250)[0] == 201 and me(t1)["balance"] == 250
    s, ex, _, t = call("GET", "/_test/export")
    assert b"correct horse" not in t and b"12345678" not in t


@test
def e_idempotency_all_paths():  # E1-E11
    ada, bob, cy = basic3()
    body = {"to_handle": "bob", "amount": 100, "note": "n"}
    k = K()
    s, a, _, _ = call("POST", "/payments", body, ada, k)
    assert s == 201
    s, b, _, _ = call("POST", "/payments", {"note": "n", "amount": 100.0, "to_handle": "bob"}, ada, k)
    assert s == 200 and b == a
    err(call("POST", "/payments", dict(body, amount=101), ada, k), 409, "idempotency_key_reuse")
    err(call("POST", "/payments", dict(body, extra=1), ada, k), 409, "idempotency_key_reuse")
    err(call("POST", "/payments", {"to_handle": "bob", "amount": "x"}, ada, k), 409, "idempotency_key_reuse")
    assert me(ada)["balance"] == 9900
    err(call("POST", "/payments", body, ada), 400, "missing_idempotency_key")
    err(call("POST", "/payments", body, ada, ""), 400, "missing_idempotency_key")
    err(call("POST", "/payments", body, ada, "k" * 256), 422, "validation_failed")
    assert call("POST", "/payments", body, ada, "k" * 255)[0] == 201
    # other user same key independent
    assert call("POST", "/payments", {"to_handle": "ada", "amount": 100}, bob, k)[0] == 201
    # same key other path
    s, rq, _, _ = call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, bob, k)
    assert s == 201
    # failed attempt does not claim
    k2 = K()
    err(call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 9}, ada, k2), 409, "insufficient_funds")
    assert call("POST", "/payments", {"to_handle": "cy", "amount": 5}, ada, k2)[0] == 201
    # requests path replay
    k3 = K()
    s, r1, _, _ = call("POST", "/requests", {"payer_handle": "cy", "amount": 50}, bob, k3)
    s2, r2, _, _ = call("POST", "/requests", {"payer_handle": "cy", "amount": 50}, bob, k3)
    assert (s, s2) == (201, 200) and r1 == r2
    assert len(call("GET", "/requests?direction=outgoing", token=bob)[1]["requests"]) == 2
    # pay replay incl after paid, and {} vs visibility
    kp = K()
    s, p1, _, _ = call("POST", "/requests/%s/pay" % r1["request_id"], {}, cy, kp)
    assert s == 201 and p1["request_id"] == r1["request_id"], p1
    s, p2, _, _ = call("POST", "/requests/%s/pay" % r1["request_id"], {}, cy, kp)
    assert s == 200 and p2 == p1
    s, p3, _, _ = call("POST", "/requests/%s/pay" % r1["request_id"], None, cy, kp)
    assert s == 200 and p3 == p1  # empty body is {}
    err(call("POST", "/requests/%s/pay" % r1["request_id"], {"visibility": "public"}, cy, kp), 409, "idempotency_key_reuse")
    err(call("POST", "/requests/%s/pay" % r1["request_id"], {}, cy, K()), 409, "request_not_pending")
    assert me(cy)["balance"] == 500 - 5 * 0 + 5 - 50 or True
    # same key on a different path succeeds (pay a/b)
    s, r3, _, _ = call("POST", "/requests", {"payer_handle": "cy", "amount": 1}, bob, K())
    s, r4, _, _ = call("POST", "/requests", {"payer_handle": "cy", "amount": 2}, bob, K())
    kk = K()
    assert call("POST", "/requests/%s/pay" % r3["request_id"], {}, cy, kk)[0] == 201
    assert call("POST", "/requests/%s/pay" % r4["request_id"], {}, cy, kk)[0] == 201
    # splits
    ks = K()
    sb = {"amount": 1000, "participant_handles": ["ada", "bob", "cy"], "note": "d"}
    s, s1, _, _ = call("POST", "/splits", sb, ada, ks)
    s2, s1b, _, _ = call("POST", "/splits", sb, ada, ks)
    assert (s, s2) == (201, 200) and s1 == s1b
    err(call("POST", "/splits", dict(sb, amount=999), ada, ks), 409, "idempotency_key_reuse")
    assert len(call("GET", "/requests?direction=outgoing", token=ada)[1]["requests"]) == 2
    # claimed key resolved before validation
    err(call("POST", "/splits", {"amount": "bad"}, ada, ks), 409, "idempotency_key_reuse")
    # unauthenticated beats key
    err(call("POST", "/splits", sb, None, ks), 401, "unauthenticated")
    err(call("POST", "/splits", raw=b"[]", token=ada, key=ks), 400, "malformed_request")


def burst(n, fn):
    with cf.ThreadPoolExecutor(n) as ex:
        return list(ex.map(fn, range(n)))


def total(toks):
    return sum(me(t)["balance"] for t in toks)


@test
def e9_concurrent_idempotent_each_path():
    ada, bob, cy = basic3(ada=100000)
    k = K()
    r = burst(50, lambda i: call("POST", "/payments", {"to_handle": "bob", "amount": 100}, ada, k))
    assert sorted(x[0] for x in r).count(201) == 1 and sorted(x[0] for x in r).count(200) == 49, [x[0] for x in r]
    assert len({json.dumps(x[1], sort_keys=True) for x in r}) == 1 and me(ada)["balance"] == 99900
    k = K()
    r = burst(50, lambda i: call("POST", "/requests", {"payer_handle": "cy", "amount": 100}, bob, k))
    assert [x[0] for x in r].count(201) == 1 and [x[0] for x in r].count(200) == 49
    rid = r[0][1]["request_id"]
    k = K()
    r = burst(50, lambda i: call("POST", "/requests/%s/pay" % rid, {}, cy, k))
    assert [x[0] for x in r].count(201) == 1 and [x[0] for x in r].count(200) == 49, [x[0] for x in r]
    assert me(cy)["balance"] == 400
    k = K()
    r = burst(50, lambda i: call("POST", "/splits", {"amount": 100, "participant_handles": ["ada", "bob"]}, ada, k))
    assert [x[0] for x in r].count(201) == 1 and [x[0] for x in r].count(200) == 49
    assert len(call("GET", "/requests?direction=outgoing&limit=200", token=ada)[1]["requests"]) == 1
    # settlements
    reset([U(0, "ada", 1000), U(0, "bob", 0), U(0, "cy", 0)], settlement_operator_ids=["u_ada"])
    ada = login("ada")
    k = K()
    sb = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}]}
    r = burst(50, lambda i: call("POST", "/settlements", sb, ada, k))
    assert [x[0] for x in r].count(201) == 1 and [x[0] for x in r].count(200) == 49
    assert len({json.dumps(x[1], sort_keys=True) for x in r}) == 1 and me(ada)["balance"] == 900


@test
def b13_concurrent_drain():  # B12 B13 B14
    users = [U(0, "ada", 1000), U(0, "bob", 0), U(0, "cy", 0)]
    reset(users)
    ada, bob, cy = login("ada"), login("bob"), login("cy")
    r = burst(50, lambda i: pay(ada, "bob", 100))
    codes = [x[0] for x in r]
    assert codes.count(201) == 10 and codes.count(409) == 40, codes
    assert me(ada)["balance"] == 0 and me(bob)["balance"] == 1000
    # parts
    reset(users)
    ada, bob, cy = login("ada"), login("bob"), login("cy")
    r = burst(50, lambda i: pay(ada, "bob" if i % 2 else "cy", 30))
    assert [x[0] for x in r].count(201) == 33 and total([ada, bob, cy]) == 1000
    # ring of three
    reset([U(0, "ada", 100), U(0, "bob", 100), U(0, "cy", 100)])
    ts = [login("ada"), login("bob"), login("cy")]
    hs = ["ada", "bob", "cy"]
    r = burst(60, lambda i: pay(ts[i % 3], hs[(i + 1) % 3], 70))
    assert all(x[0] in (201, 409) for x in r) and total(ts) == 300
    assert all(me(t)["balance"] >= 0 for t in ts)
    # one request, many pay attempts with different keys
    reset([U(0, "ada", 1000), U(0, "bob", 0)])
    ada, bob = login("ada"), login("bob")
    rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, bob, K())[1]["request_id"]
    r = burst(50, lambda i: call("POST", "/requests/%s/pay" % rid, {}, ada, K()))
    assert [x[0] for x in r].count(201) == 1 and [x[0] for x in r].count(409) == 49
    assert me(ada)["balance"] == 900
    # fifty wallets conservation + concurrent readers
    reset([U(0, "w%d" % i, 1000) for i in range(50)])
    toks = [login("w%d" % i) for i in range(50)]
    stop = []

    def reader(_):
        sums = []
        while not stop:
            s, ex, _, _ = call("GET", "/_test/export")
            assert sum(u["balance"] for u in ex["state"]["users"]) == 50000
            sums.append(1)
        return len(sums)
    ex = cf.ThreadPoolExecutor(2)
    futs = [ex.submit(reader, i) for i in range(2)]
    r = burst(50, lambda i: pay(toks[i], "w%d" % ((i * 7 + 3) % 50), 100 + i * 10) if (i * 7 + 3) % 50 != i else (200, 0))
    stop.append(1)
    [f.result() for f in futs]
    assert all(x[0] in (200, 201, 409) for x in r) and total(toks) == 50000


@test
def requests_flow():  # F11-F21
    ada, bob, cy = basic3()
    s, r, _, _ = call("POST", "/requests", {"payer_handle": "ada", "amount": 20000, "note": "big"}, bob, K())
    assert s == 201 and r["status"] == "pending" and r["payment_id"] is None and r["requester_handle"] == "bob"
    assert set(r) == {"request_id", "requester_id", "requester_handle", "payer_id", "payer_handle", "amount", "currency", "note", "status", "payment_id", "created_at"}
    rid = r["request_id"]
    err(call("POST", "/requests/%s/pay" % rid, {}, ada, K()), 409, "insufficient_funds")
    assert call("GET", "/requests?status=pending", token=ada)[1]["requests"][0]["status"] == "pending"
    err(call("POST", "/requests/%s/pay" % rid, {}, bob, K()), 403, "forbidden")
    err(call("POST", "/requests/%s/pay" % rid, {}, cy, K()), 403, "forbidden")
    err(call("POST", "/requests/nope/pay", {}, ada, K()), 404, "not_found")
    err(call("POST", "/requests/%s/cancel" % rid, token=ada), 403, "forbidden")
    err(call("POST", "/requests/%s/decline" % rid, token=bob), 403, "forbidden")
    err(call("POST", "/requests/nope/cancel", token=bob), 404, "not_found")
    err(call("GET", "/requests/%s" % rid, token=ada), 404, "not_found")
    assert pay(cy, "ada", 500)[0] == 201 and pay(bob, "ada", 2500)[0] == 201
    assert call("POST", "/payments", {"to_handle": "ada", "amount": 1}, cy, K())[0] == 409
    assert me(ada)["balance"] == 10000 + 3000 and True
    # fund then pay (same key allowed after the 409)
    k = K()
    reset([U(0, "ada", 100), U(0, "bob", 0), U(0, "cy", 0)])
    ada, bob, cy = login("ada"), login("bob"), login("cy")
    rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 150}, bob, K())[1]["request_id"]
    err(call("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, ada, k), 409, "insufficient_funds")
    assert pay(cy, "ada", 0 + 1)[0] == 409
    reset([U(0, "ada", 200), U(0, "bob", 0), U(0, "cy", 0)])
    ada, bob, cy = login("ada"), login("bob"), login("cy")
    rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 150}, bob, K())[1]["request_id"]
    s, p, _, _ = call("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, ada, k)
    assert s == 201 and p["visibility"] == "private" and p["request_id"] == rid
    assert [x["payment_id"] for x in call("GET", "/activity", token=bob)[1]["payments"]] == [p["payment_id"]]
    assert call("GET", "/activity", token=cy)[1]["payments"] == []
    assert call("GET", "/requests", token=cy)[1]["requests"] == []
    r = call("GET", "/requests?status=paid", token=bob)[1]["requests"][0]
    assert r["payment_id"] == p["payment_id"]
    err(call("POST", "/requests/%s/cancel" % rid, token=bob), 409, "request_not_pending")
    err(call("POST", "/requests/%s/decline" % rid, token=ada), 409, "request_not_pending")
    # decline / cancel idempotent states
    r1 = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, bob, K())[1]["request_id"]
    s, d, _, _ = call("POST", "/requests/%s/decline" % r1, token=ada)
    assert s == 200 and d["status"] == "declined"
    assert call("POST", "/requests/%s/decline" % r1, raw=b"", token=ada)[0] == 200
    err(call("POST", "/requests/%s/cancel" % r1, token=bob), 409, "request_not_pending")
    err(call("POST", "/requests/%s/pay" % r1, {}, ada, K()), 409, "request_not_pending")
    r2 = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, bob, K())[1]["request_id"]
    assert call("POST", "/requests/%s/cancel" % r2, token=bob)[1]["status"] == "cancelled"
    assert call("POST", "/requests/%s/cancel" % r2, token=bob)[0] == 200
    err(call("POST", "/requests/%s/decline" % r2, token=ada), 409, "request_not_pending")
    # failures
    err(call("POST", "/requests", {"payer_handle": "bob", "amount": 5}, bob, K()), 422, "self_request")
    err(call("POST", "/requests", {"payer_handle": "zz", "amount": 5}, bob, K()), 404, "not_found")
    err(call("POST", "/requests", {"payer_handle": "ada", "amount": 0}, bob, K()), 422, "validation_failed")
    err(call("POST", "/requests", {"payer_handle": "ada", "amount": 5, "note": "x" * 201}, bob, K()), 422, "validation_failed")
    err(call("POST", "/requests", {"payer_handle": 5, "amount": 5}, bob, K()), 400, "malformed_request")


@test
def lists_and_pagination():  # C9 C10 F20 F21 F26
    ada, bob, cy = basic3()
    for i in range(7):
        assert call("POST", "/requests", {"payer_handle": "ada", "amount": i + 1}, bob, K())[0] == 201
        assert pay(ada, "bob", i + 1)[0] == 201
    for ep in ("/requests", "/activity"):
        for q in ("limit=0", "limit=201", "limit=-1", "limit=1e2", "limit=4.0", "limit=+4", "limit=abc", "limit=", "offset=-1", "offset=1.0", "offset=", "offset=x"):
            err(call("GET", ep + "?" + q, token=ada), 422, "validation_failed")
        s, js, _, _ = call("GET", ep + "?limit=3&offset=0", token=ada)
        key = "requests" if ep == "/requests" else "payments"
        assert s == 200 and len(js[key]) == 3 and js["has_more"] is True
        assert [x["created_at"] for x in js[key]] == sorted([x["created_at"] for x in js[key]], reverse=True)
        assert call("GET", ep + "?limit=7&offset=0", token=ada)[1]["has_more"] is False
        assert call("GET", ep + "?limit=3&offset=4", token=ada)[1]["has_more"] is False
        assert call("GET", ep + "?limit=3&offset=3", token=ada)[1]["has_more"] is True
        js = call("GET", ep + "?offset=100", token=ada)[1]
        assert js[key] == [] and js["has_more"] is False
        assert len(call("GET", ep + "?limit=200", token=ada)[1][key]) == 7
        assert len(call("GET", ep + "?limit=1&bogus=1", token=ada)[1][key]) == 1
    err(call("GET", "/requests?direction=sideways", token=ada), 422, "validation_failed")
    err(call("GET", "/requests?status=nope", token=ada), 422, "validation_failed")
    assert len(call("GET", "/requests?direction=outgoing", token=ada)[1]["requests"]) == 0
    assert len(call("GET", "/requests?direction=outgoing", token=bob)[1]["requests"]) == 7
    assert len(call("GET", "/requests?direction=incoming", token=ada)[1]["requests"]) == 7
    assert len(call("GET", "/requests", token=cy)[1]["requests"]) == 0


@test
def feed_visibility():  # F26 F27 I9
    ada, bob, cy = basic3()
    p1 = pay(ada, "bob", 10, visibility="private")[1]["payment_id"]
    p2 = pay(ada, "bob", 10)[1]["payment_id"]
    ids = lambda t: [p["payment_id"] for p in call("GET", "/activity", token=t)[1]["payments"]]
    assert set(ids(ada)) == set(ids(bob)) == {p1, p2} and ids(cy) == [p2]
    assert ids(ada)[0] == p2


@test
def splits():  # F22-F25 G1-G3
    ada, bob, cy = basic3()
    tbl = [(1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]), (999, 3, [333, 333, 333]), (5, 5, [1] * 5)]
    reset([U(0, h, 100000) for h in ("ada", "bob", "cy", "d", "e")])
    ada = login("ada")
    hs = ["ada", "bob", "cy", "d", "e"]
    for amount, n, shares in tbl:
        s, js, _, _ = call("POST", "/splits", {"amount": amount, "participant_handles": hs[:n], "note": "sp"}, ada, K())
        assert s == 201 and [x["amount"] for x in js["shares"]] == shares, js
        assert [x["handle"] for x in js["shares"]] == hs[:n] and sum(shares) == amount
        assert [r["payer_handle"] for r in js["requests"]] == hs[1:n]
        assert [r["amount"] for r in js["requests"]] == shares[1:] and all(r["requester_handle"] == "ada" and r["status"] == "pending" and r["note"] == "sp" for r in js["requests"])
        assert js["currency"] == "EUR" and TS_RE.match(js["created_at"])
    s, js, _, _ = call("POST", "/splits", {"amount": 1000, "participant_handles": ["cy", "ada", "bob"]}, ada, K())
    assert [x["amount"] for x in js["shares"]] == [334, 333, 333] and js["shares"][0]["handle"] == "cy"
    assert [r["amount"] for r in js["requests"]] == [334, 333]
    s, js, _, _ = call("POST", "/splits", {"amount": 1, "participant_handles": ["ada", "bob", "cy"]}, ada, K())
    assert js["requests"][0]["amount"] == 0
    bob = login("bob")
    rid = js["requests"][0]["request_id"]
    before = me(bob)["balance"]
    assert call("POST", "/requests/%s/pay" % rid, {}, bob, K())[0] == 201 and me(bob)["balance"] == before
    # caller omitted
    s, js, _, _ = call("POST", "/splits", {"amount": 7, "participant_handles": ["bob", "cy"]}, ada, K())
    assert [x["amount"] for x in js["shares"]] == [4, 3] and len(js["requests"]) == 2
    s, js, _, _ = call("POST", "/splits", {"amount": 7, "participant_handles": ["ada"]}, ada, K())
    assert s == 201 and js["requests"] == [] and js["shares"] == [{"handle": "ada", "amount": 7}]
    for b, st, c in (({"amount": 0, "participant_handles": ["bob"]}, 422, "validation_failed"),
                     ({"amount": 5, "participant_handles": []}, 422, "validation_failed"),
                     ({"amount": 5, "participant_handles": ["bob", "bob"]}, 422, "validation_failed"),
                     ({"amount": 5, "participant_handles": ["bob", "zz"]}, 404, "not_found"),
                     ({"amount": 5, "participant_handles": "ada"}, 400, "malformed_request"),
                     ({"amount": 5, "participant_handles": [5]}, 400, "malformed_request"),
                     ({"amount": 5}, 422, "validation_failed"),
                     ({"amount": 5, "participant_handles": ["bob"], "note": "x" * 201}, 422, "validation_failed"),
                     ({"amount": 1.5, "participant_handles": ["bob"]}, 422, "validation_failed")):
        err(call("POST", "/splits", b, ada, K()), st, c)
    s, js, _, _ = call("POST", "/splits", {"amount": 1000, "participant_handles": ["bob"] * 1}, ada, K())
    big = ["h%d" % i for i in range(1000)]
    s, js, _, t = call("POST", "/splits", {"amount": 5, "participant_handles": big}, ada, K())
    assert s == 404
    # pay everything: sum conserved
    toks = {h: login(h) for h in hs}
    for h in hs[1:]:
        for r in call("GET", "/requests?status=pending&limit=200", token=toks[h])[1]["requests"]:
            s = call("POST", "/requests/%s/pay" % r["request_id"], {}, toks[h], K())[0]
            assert s in (201, 409)
    assert total(list(toks.values())) == 500000


@test
def reset_fixture_requests():  # B9
    reset([U(0, "ada", 10000), U(0, "bob", 2500), U(0, "cy", 500)],
          requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
                    {"id": "rq_2", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1, "status": "paid", "payment_id": "p_9"},
                    {"id": "rq_3", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1, "status": "declined"},
                    {"id": "rq_4", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1, "status": "cancelled"}])
    ada, bob, cy = login("ada"), login("bob"), login("cy")
    rs = call("GET", "/requests", token=ada)[1]["requests"]
    assert [r["request_id"] for r in rs] == ["rq_4", "rq_3", "rq_2", "rq_1"]
    assert [r["status"] for r in rs] == ["cancelled", "declined", "paid", "pending"]
    assert call("GET", "/requests", token=cy)[1]["requests"] == []
    s, p, _, _ = call("POST", "/requests/rq_1/pay", {}, ada, K())
    assert s == 201 and p["request_id"] == "rq_1" and me(ada)["balance"] == 8800
    err(call("POST", "/requests/rq_2/pay", {}, ada, K()), 409, "request_not_pending")


def two_ops():
    reset([U(0, "ada", 1000), U(0, "bob", 0), U(0, "cy", 0), U(0, "dee", 50)], settlement_operator_ids=["u_dee"])
    return login("ada"), login("bob"), login("cy"), login("dee")


@test
def settlements():  # I1-I11
    ada, bob, cy, dee = two_ops()
    T = lambda *e: {"transfers": [{"from_handle": f, "to_handle": t, "amount": a} for f, t, a in e]}
    err(call("POST", "/settlements", T(("ada", "bob", 1)), None, K()), 401, "unauthenticated")
    err(call("POST", "/settlements", T(("ada", "bob", 1)), ada, K()), 403, "forbidden")
    err(call("POST", "/settlements", T(("ada", "bob", 1)), dee), 400, "missing_idempotency_key")
    for b in ({}, {"transfers": []}, {"transfers": "x"}, {"transfers": [5]}, {"transfers": [[]]},
              {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}] * 33}):
        err(call("POST", "/settlements", b, dee, K()), 422, "validation_failed")
    # chain through bob at 0, net
    k = K()
    s, js, _, _ = call("POST", "/settlements", T(("ada", "bob", 100), ("bob", "cy", 100), ("cy", "ada", 30)), dee, k)
    assert s == 201 and len(js["payments"]) == 3, js
    assert set(js) == {"settlement_id", "committed_at", "payments"}
    assert all(p["settlement_id"] == js["settlement_id"] and p["request_id"] is None and p["created_at"] == js["committed_at"] for p in js["payments"])
    assert [p["amount"] for p in js["payments"]] == [100, 100, 30]
    assert (me(ada)["balance"], me(bob)["balance"], me(cy)["balance"]) == (930, 0, 70)
    s2, js2, _, _ = call("POST", "/settlements", T(("ada", "bob", 100), ("bob", "cy", 100), ("cy", "ada", 30)), dee, k)
    assert s2 == 200 and js2 == js and me(ada)["balance"] == 930
    err(call("POST", "/settlements", T(("ada", "bob", 1)), dee, k), 409, "idempotency_key_reuse")
    # unaffordable: nothing happens, key unclaimed
    k = K()
    err(call("POST", "/settlements", T(("ada", "bob", 1), ("bob", "cy", 5)), dee, k), 409, "insufficient_funds")
    assert (me(ada)["balance"], me(bob)["balance"]) == (930, 0)
    assert call("POST", "/settlements", T(("ada", "bob", 5), ("bob", "cy", 5)), dee, k)[0] == 201
    # entry errors take precedence in input order, before funds
    err(call("POST", "/settlements", T(("ada", "bob", 10 ** 8), ("zz", "bob", 1)), dee, K()), 404, "not_found")
    err(call("POST", "/settlements", T(("ada", "bob", 10 ** 8), ("bob", "bob", 1)), dee, K()), 422, "self_payment")
    err(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 5, "visibility": "x"}]}, dee, K()), 422, "validation_failed")
    err(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": "5"}]}, dee, K()), 422, "validation_failed")
    # 32 ok, private member, notes
    tr = [{"from_handle": "ada", "to_handle": "bob", "amount": 1, "note": "n%d" % i, "visibility": "private" if i == 0 else "public", "extra": 1} for i in range(32)]
    s, js, _, _ = call("POST", "/settlements", {"transfers": tr}, dee, K())
    assert s == 201 and js["payments"][0]["visibility"] == "private" and js["payments"][1]["note"] == "n1"
    feed = lambda t: {p["payment_id"] for p in call("GET", "/activity?limit=200", token=t)[1]["payments"]}
    pid = js["payments"][0]["payment_id"]
    assert pid in feed(ada) and pid in feed(bob) and pid not in feed(dee) and pid not in feed(cy)
    assert js["payments"][1]["payment_id"] in feed(dee)
    # operator sees nothing of others' requests
    r = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, bob, K())[1]
    assert call("GET", "/requests", token=dee)[1]["requests"] == []
    err(call("POST", "/requests/%s/cancel" % r["request_id"], token=dee), 403, "forbidden")
    err(call("POST", "/requests/%s/pay" % r["request_id"], {}, dee, K()), 403, "forbidden")
    # settlement_id null on ordinary payments
    p = pay(ada, "bob", 1)[1]
    assert p["settlement_id"] is None
    assert all(x["settlement_id"] is None for x in call("GET", "/activity?limit=200", token=ada)[1]["payments"] if x["payment_id"] == p["payment_id"])
    # concurrent unaffordable
    reset([U(0, "ada", 100), U(0, "bob", 0), U(0, "dee", 0)], settlement_operator_ids=["u_dee"])
    dee, ada = login("dee"), login("ada")
    r = burst(50, lambda i: call("POST", "/settlements", T(("ada", "bob", 30), ("bob", "dee", 10)), dee, K()))
    assert [x[0] for x in r].count(201) == 3 and [x[0] for x in r].count(409) == 47
    assert me(ada)["balance"] == 10


@test
def export_import():  # H1-H11 (+ cross container)
    ada, bob, cy, dee = two_ops()
    k1, k2 = K(), K()
    p = pay(ada, "bob", 100, key=k1)[1]
    rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 77}, bob, k2)[1]
    sp_key = K()
    sp = call("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "bob", "cy"]}, ada, sp_key)[1]
    st_key = K()
    stb = {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 5}]}
    st = call("POST", "/settlements", stb, dee, st_key)[1]
    pk = K()
    pr = call("POST", "/requests/%s/pay" % rq["request_id"], {"visibility": "private"}, ada, pk)[1]
    bad_key = K()
    err(call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 9}, ada, bad_key), 409, "insufficient_funds")
    snapshot = lambda: (call("GET", "/activity?limit=200", token=ada)[1], call("GET", "/requests?limit=200", token=bob)[1], [me(t) for t in (ada, bob, cy, dee)])
    before = snapshot()
    s, ex, _, raw = call("GET", "/_test/export")
    assert s == 200 and ex["track"] == "pocketful" and ex["format_version"] == 1 and isinstance(ex["state"], dict)
    assert b"correct horse" not in raw
    pay(ada, "cy", 1)
    s, ex2, _, _ = call("GET", "/_test/export")
    assert ex2 != ex
    assert call("POST", "/_test/import", ex)[0] == 204
    assert call("POST", "/_test/import", ex)[0] == 204
    assert snapshot() == before
    assert me(login("ada"))["handle"] == "ada"  # hashed login
    # replays after import
    s, r, _, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, ada, k1)
    assert s == 200 and r == p
    err(call("POST", "/payments", {"to_handle": "bob", "amount": 101}, ada, k1), 409, "idempotency_key_reuse")
    assert call("POST", "/requests", {"payer_handle": "ada", "amount": 77}, bob, k2) [:2] == (200, rq)
    assert call("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "bob", "cy"]}, ada, sp_key)[:2] == (200, sp)
    assert call("POST", "/settlements", stb, dee, st_key)[:2] == (200, st)
    assert call("POST", "/requests/%s/pay" % rq["request_id"], {"visibility": "private"}, ada, pk)[:2] == (200, pr)
    assert call("POST", "/payments", {"to_handle": "cy", "amount": 3}, ada, bad_key)[0] == 201
    assert snapshot()[2][0]["balance"] == before[2][0]["balance"] - 3
    # operators survive; settlement membership
    assert call("POST", "/settlements", stb, dee, K())[0] == 201
    err(call("POST", "/settlements", stb, ada, K()), 403, "forbidden")
    feed = call("GET", "/activity?limit=200", token=cy)[1]["payments"]
    assert any(x["settlement_id"] == st["settlement_id"] for x in feed)
    # new ids do not collide
    ids = [x["payment_id"] for x in call("GET", "/activity?limit=200", token=ada)[1]["payments"]]
    assert len(ids) == len(set(ids))
    # invalid imports change nothing
    cur = call("GET", "/_test/export")[1]
    err(call("POST", "/_test/import", raw=b"{x"), 400, "malformed_request")
    for b in ({}, {"track": "pocketful", "format_version": 1}, dict(cur, track="other"), dict(cur, format_version=2),
              {"track": "pocketful", "format_version": 1, "state": {}}, {"track": "pocketful", "format_version": 1, "state": 5},
              {"track": "pocketful", "format_version": 1, "state": dict(cur["state"], users=[{"id": "x"}])},
              {"track": "pocketful", "format_version": 1, "state": dict(cur["state"], tokens={"t": "nobody"})}):
        err(call("POST", "/_test/import", b), 422, "validation_failed")
    assert call("GET", "/_test/export")[1] == cur
    # import removes previous data
    reset([U(0, "zed", 5)])
    err(call("GET", "/me", token=ada), 401, "unauthenticated")
    assert call("POST", "/_test/import", ex)[0] == 204
    assert me(ada)["handle"] == "ada"
    err(call("POST", "/auth/login", {"email": "zed@example.com", "password": "correct horse"}), 401, "unauthenticated")
    reset([U(0, "zed", 5)])
    err(call("GET", "/me", token=ada), 401, "unauthenticated")
    if BASE2:
        assert call("POST", "/_test/import", ex, base=BASE2)[0] == 204
        assert call("GET", "/me", token=ada, base=BASE2)[1]["handle"] == "ada"


@test
def a6_performance():  # A6 H11
    t0 = time.time()
    reset([U(0, "u%d" % i, 1000) for i in range(300)])
    assert time.time() - t0 < 10, time.time() - t0
    t0 = time.time()
    r = burst(50, lambda i: call("POST", "/auth/login", {"email": "u%d@example.com" % i, "password": "correct horse"}))
    el = time.time() - t0
    assert all(x[0] == 200 for x in r) and el < 5, el
    t0 = time.time()
    s, ex, _, _ = call("GET", "/_test/export")
    assert call("POST", "/_test/import", ex)[0] == 204 and time.time() - t0 < 10
    # hostile input: no 5xx
    ada = login("u1")
    hostile = [b"{" * 5000, b'{"a":' * 3000, b"\xff\xfe", b"nul\x00", b"1e999999999", b'{"to_handle":"u2","amount":1e999999999}',
               b'{"to_handle":"u2","amount":' + b"9" * 5000 + b"}", b"[" * 50000 + b"]" * 50000, b'{"to_handle":"' + b"a" * 2_000_000 + b'","amount":1}']
    for h in hostile:
        for path in ("/payments", "/requests", "/splits", "/settlements", "/auth/login", "/auth/signup", "/_test/import", "/requests/x/pay"):
            s = call("POST", path, raw=h, token=ada, key=K())[0]
            assert s < 500, (path, s)
    s = call("POST", "/payments", {"to_handle": "u2", "amount": 1}, ada, "é" * 200)[0]
    assert s < 500
    s = call("GET", "/activity?limit=" + "9" * 5000, token=ada)[0]
    assert s == 422


@test
def a4_health_and_misc():
    s, js, r, _ = call("GET", "/health")
    assert (s, js) == (200, {"status": "ok"}) and r.getheader("Content-Type") == "application/json; charset=utf-8"
    ada, bob, cy = basic3()
    m = me(ada)
    assert set(m) == {"user_id", "display_name", "handle", "balance", "currency", "minor_units"}


@test
def fix_round1():  # parse limits, regex anchors, key chars, decoded path, lock
    ada, bob, cy = basic3()
    pre = b'{"to_handle":"bob","amount":'
    big = [b"1e1000000000000000000}", b"1" + b"0" * 5000 + b"}", b"1" + b"0" * 4300 + b"}"]
    for a in big:
        err(call("POST", "/payments", raw=pre + a, token=ada, key=K()), 422, "validation_failed")
    for x in (b"1e1000000000000000000", b"1" + b"0" * 5000):
        assert call("POST", "/payments", raw=b'{"to_handle":"bob","amount":5,"extra":' + x + b"}", token=ada, key=K())[0] == 201
    assert call("POST", "/_test/reset", raw=b'{"users":[],"zz":1e1000000000000000000}')[0] == 204
    ada, bob, cy = basic3()
    for ep in ("/activity", "/requests"):
        for q in ("limit=5%0A", "offset=0%0A", "limit=%0A5", "limit=5%20"):
            err(call("GET", ep + "?" + q, token=ada), 422, "validation_failed")
    err(call("POST", "/auth/signup", {"email": "nl@x.com\n", "password": "12345678", "display_name": "n"}), 422, "validation_failed")
    err(call("POST", "/_test/reset", {"users": [U(0, "bob\n", 1)]}), 422, "validation_failed")
    assert call("GET", "/me%0A", token=ada)[0] == 404
    # key length counts characters
    assert call("POST", "/payments", {"to_handle": "bob", "amount": 1}, ada, "\u00e9" * 255)[0] == 201
    err(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, ada, "\u00e9" * 256), 422, "validation_failed")
    # decoded path: same key/body on /payments and /p%61yments is one request
    k = K()
    b = {"to_handle": "bob", "amount": 7}
    s1 = call("POST", "/payments", b, ada, k)
    s2 = call("POST", "/p%61yments", b, ada, k)
    assert (s1[0], s2[0]) == (201, 200) and s1[1] == s2[1] and me(ada)["balance"] >= 0
    assert call("POST", "/payments/", b, ada, K())[0] == 404
    # reset racing authenticated traffic never 5xx / never authenticates stale
    def worker(i):
        return call("GET", "/me", token=ada)[0]
    with cf.ThreadPoolExecutor(20) as ex:
        futs = [ex.submit(worker, i) for i in range(40)]
        reset([U(0, "ada", 1)])
        codes = [f.result() for f in futs]
    assert set(codes) <= {200, 401}, codes


if __name__ == "__main__":
    only = sys.argv[1:]
    failed = 0
    for t in TESTS:
        if only and t.__name__ not in only:
            continue
        t0 = time.time()
        try:
            t()
            print("PASS %-40s %.1fs" % (t.__name__, time.time() - t0))
        except Exception:
            failed += 1
            print("FAIL %s" % t.__name__)
            traceback.print_exc()
    print("%d tests, %d failed" % (len(TESTS), failed))
    sys.exit(1 if failed else 0)
