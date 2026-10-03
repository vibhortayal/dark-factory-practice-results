"""L. Fix round 2: checks for the code that changed between 6c6d0a6 and df4b305
(lexical number handling, raw-text idempotency bodies in the export, email predicate, zero-padded query integers).
R1-R3 are covered by test_k_round1.py, R4 by test_e_auth.py, clarification 3 by test_k2_zero_padded_*."""
import copy
import json

import pytest

from lib import BASE2, GET, POST, World, call, code_of, err, fixture, k, ok, soft, user


@pytest.fixture()
def w():
    return World().login_all()


def send(w, raw, key, who="ada", path="/payments", base=None):
    return call("POST", path, w.t(who), key=key, raw=raw, base=base)


def roundtrip(base=None):
    e = call("GET", "/_test/export")
    assert e.status_code == 200
    r = call("POST", "/_test/import", raw=e.content, base=base)
    assert r.status_code == 204, f"import of own export -> {r.status_code} {r.text[:200]}"
    return e.json()


# ---------------------------------------------------------------- number equality in replays (N12, D-7)

SAME_VALUE = [
    ("1.50", ["1.5", "15e-1", "0.15e1", "1.500000", "150E-2"]),
    ("52.52", ["52.520", "5252e-2", "0.5252E+2"]),
    ("1000", ["1e3", "1000.0", "1E+3", "0.1e4", "100000e-2"]),
    ("0", ["0.0", "-0", "0e5", "-0.000", "0e99999999999999999999"]),
    ("-2.5", ["-25e-1", "-2.50"]),
    ("1e40", ["10e39", "1" + "0" * 40, "0.1e41"]),
]
DIFFERENT_VALUE = [("1.5", "1.51"), ("52.52", "52.53"), ("1000", "1001"), ("1e40", "1e41"), ("0.5", "-0.5"),
                   ("1e99999999999999999999", "2e99999999999999999999"), ("1", "true"), ("1", '"1"'), ("0", "null"),
                   ("1e-99999999999999999999", "1e99999999999999999999"), ("5", '{"$num":"5"}')]


@pytest.mark.parametrize("first,others", SAME_VALUE, ids=[s[0] for s in SAME_VALUE])
def test_l_equal_numbers_in_ignored_field_replay(w, first, others):
    key = k()
    body = '{"to_handle":"bob","amount":2,"x":%s}'
    j = ok(send(w, body % first, key), 201)
    for o in others:
        r = send(w, body % o, key)
        assert r.status_code < 500
        if soft(r.status_code == 200, "equal-number-spelling-not-replayed", first=first, other=o, status=r.status_code):
            assert r.json() == j
        else:
            err(r, 409, "idempotency_key_reuse")
    assert ok(send(w, body % first, key), 200) == j
    roundtrip()
    assert ok(send(w, body % first, key), 200) == j
    assert w.bal("ada") == 9998


@pytest.mark.parametrize("a,b", DIFFERENT_VALUE, ids=[f"{a[:12]}|{b[:12]}" for a, b in DIFFERENT_VALUE])
def test_l_different_values_in_ignored_field_conflict(w, a, b):
    key = k()
    body = '{"to_handle":"bob","amount":2,"x":%s}'
    j = ok(send(w, body % a, key), 201)
    err(send(w, body % b, key), 409, "idempotency_key_reuse")
    roundtrip()
    err(send(w, body % b, key), 409, "idempotency_key_reuse")
    assert ok(send(w, body % a, key), 200) == j
    assert w.bal("ada") == 9998


def test_l_amount_spellings_replay(w):
    key = k()
    j = ok(send(w, '{"to_handle":"bob","amount":1000}', key), 201)
    for o in ("1e3", "1000.0", "0.1e4", "1000.000"):
        r = send(w, '{"amount":%s, "to_handle":"bob"}' % o, key)
        if soft(r.status_code == 200, "amount-spelling-not-replayed", other=o, status=r.status_code):
            assert r.json() == j
    err(send(w, '{"to_handle":"bob","amount":1000.5}', key), 409, "idempotency_key_reuse")
    err(send(w, '{"to_handle":"bob","amount":1e99999999999999999999}', key), 409, "idempotency_key_reuse")
    assert w.bal("ada") == 9000


# ---------------------------------------------------------------- raw-text bodies in export / import

def test_l_marker_like_body_is_ordinary(w):
    key = k()
    raw = '{"to_handle":"bob","amount":3,"x":{"$num":"5"},"body_raw":"{}","body":{"a":[1,2.5]}}'
    j = ok(send(w, raw, key), 201)
    assert ok(send(w, raw, key), 200) == j
    err(send(w, raw.replace('{"$num":"5"}', "5"), key), 409, "idempotency_key_reuse")
    roundtrip()
    assert ok(send(w, raw, key), 200) == j
    err(send(w, raw.replace('{"$num":"5"}', "5"), key), 409, "idempotency_key_reuse")


ODD_BODIES = [
    '  {\n\t"to_handle" : "bob" ,\r\n "amount":4, "note":"caf\\u00e9 \\ud83d\\ude00 \\u0000 \\ud800"}  ',
    '{"to_handle":"bob","amount":4,"note":"zażółć 😀","x":[1.5,{"y":null,"z":[true,false,"\\\\\\""]}]}',
    '{"amount":4,"to_handle":"bob","to_handle":"bob","amount":4}',
    '{"to_handle":"bob","amount":4,"pad":"' + "x" * 150_000 + '"}',
    '{"to_handle":"bob","amount":4,"x":' + "[" * 900 + "]" * 900 + "}",
    '{"to_handle":"bob","amount":4,"x":[' + ",".join(["1e99999999999999999999", "-0.0", "9" * 5000, "1e-5000"]) + "]}",
]


@pytest.mark.parametrize("i", range(len(ODD_BODIES)))
def test_l_odd_bodies_replay_after_import_in_both_containers(w, i):
    assert BASE2, "BASE2 (second container) is not set"
    raw = ODD_BODIES[i].encode("utf-8")
    key = k()
    j = ok(send(w, raw, key), 201)
    assert ok(send(w, raw, key), 200) == j
    snap = w.snapshot()
    roundtrip()
    assert ok(send(w, raw, key), 200) == j
    assert w.snapshot() == snap
    # a fresh container
    World(fixture(users=[user("zed", 1)]), base=BASE2)
    exported = roundtrip(base=BASE2)
    r = send(w, raw, key, base=BASE2)
    assert r.status_code == 200 and r.json() == j, f"replay in second container: {r.status_code} {r.text[:160]}"
    tokens = {h: w.t(h) for h in w.handles()}
    assert w.snapshot(tokens=tokens, base=BASE2) == snap
    # export -> import -> export is stable
    again = call("GET", "/_test/export", base=BASE2).json()
    soft(again == exported, "export-import-export-differs")


def test_l_pay_with_empty_body_replays_after_import(w):
    q = w.new_request("bob", "ada", 9)
    path = f"/requests/{q['request_id']}/pay"
    key = k()
    r = call("POST", path, w.t("ada"), key=key)  # no body at all
    if r.status_code != 201:
        err(r, 400, "malformed_request")
        r = call("POST", path, w.t("ada"), key=key, raw="{}")
        j = ok(r, 201)
    else:
        j = r.json()
        assert ok(call("POST", path, w.t("ada"), key=key), 200) == j
    assert ok(call("POST", path, w.t("ada"), key=key, raw="{}"), 200) == j
    assert ok(call("POST", path, w.t("ada"), key=key, raw=" { } "), 200) == j
    roundtrip()
    assert ok(call("POST", path, w.t("ada"), key=key, raw="{}"), 200) == j
    err(call("POST", path, w.t("ada"), key=key, raw='{"visibility":"public"}'), 409, "idempotency_key_reuse")
    assert w.bal("ada") == 9991


# ---------------------------------------------------------------- import validation of the changed record format

def _idem(st):
    return st["idempotency"][0]


IDEM_MUTATIONS = {
    "body text removed": lambda s: _idem(s).pop(next(kk for kk in _idem(s) if "body" in kk)),
    "body text number": lambda s: _idem(s).__setitem__(next(kk for kk in _idem(s) if "body" in kk), 5),
    "body text not json": lambda s: _idem(s).__setitem__(next(kk for kk in _idem(s) if "body" in kk), "{nope"),
    "body text null": lambda s: _idem(s).__setitem__(next(kk for kk in _idem(s) if "body" in kk), None),
    "response string": lambda s: _idem(s).__setitem__("response", "x"),
    "status 200": lambda s: _idem(s).__setitem__("status", 200),
    "path number": lambda s: _idem(s).__setitem__("path", 5),
    "duplicate record": lambda s: s["idempotency"].append(copy.deepcopy(_idem(s))),
}


@pytest.fixture(scope="module")
def exported():
    w = World().login_all()
    key = k()
    body = {"to_handle": "bob", "amount": 5}
    j = ok(w.pay("ada", "bob", 5, key=key), 201)
    return w, call("GET", "/_test/export").json(), w.snapshot(), key, body, j


@pytest.mark.parametrize("name", list(IDEM_MUTATIONS))
def test_l_bad_idempotency_record_rejected(exported, name):
    w, e, before, key, body, j = exported
    doc = copy.deepcopy(e)
    IDEM_MUTATIONS[name](doc["state"])
    r = call("POST", "/_test/import", body=doc)
    unchanged = w.snapshot() == before
    if r.status_code == 204 or not unchanged:
        assert call("POST", "/_test/import", body=e).status_code == 204
    err(r, 422, "validation_failed", name)
    assert unchanged


@pytest.mark.parametrize("value", ["1.5", "1e99999999999999999999", "9" * 5000, "-0.5"])
def test_l_non_integer_number_inside_imported_record_never_5xx(exported, value):
    """An import that puts a non-integer number where the service later serialises it must be refused, or served."""
    w, e, before, key, body, j = exported
    raw = json.dumps(e).replace('"amount": 5', '"amount": %s' % value)
    assert value in raw
    r = call("POST", "/_test/import", raw=raw)
    assert r.status_code in (204, 422), r.text[:200]
    exp = call("GET", "/_test/export")
    rep = POST("/payments", w.t("ada"), body, key=key)
    feed = GET("/activity", w.t("ada"))
    restored = call("POST", "/_test/import", body=e).status_code
    assert exp.status_code == 200, f"export after import of {value}: {exp.status_code}"
    assert rep.status_code < 500 and feed.status_code < 500, (rep.status_code, feed.status_code)
    assert restored == 204
    if r.status_code == 422:
        assert rep.status_code == 200 and rep.json() == j
    assert w.snapshot() == before


@pytest.mark.parametrize("where", ["response", "split", "settlement", "top"])
def test_l_fraction_in_free_form_parts_of_state_never_5xx(where):
    w = World().login_all()
    ok(POST("/splits", w.t("ada"), {"amount": 9, "participant_handles": ["bob", "cy"]}, key="s1"), 201)
    ok(POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]},
            key="t1"), 201)
    e = call("GET", "/_test/export").json()
    doc = copy.deepcopy(e)
    st = doc["state"]
    if where == "response":
        st["idempotency"][0]["response"]["extra"] = 0.25
    elif where == "split":
        st["splits"][0]["extra"] = 0.25
    elif where == "settlement":
        st["settlements"][0]["extra"] = 0.25
    else:
        st["extra"] = {"ratio": 0.25}
    r = call("POST", "/_test/import", body=doc)
    assert r.status_code in (204, 422), r.text[:200]
    exp = call("GET", "/_test/export")
    rep1 = POST("/splits", w.t("ada"), {"amount": 9, "participant_handles": ["bob", "cy"]}, key="s1")
    rep2 = POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]},
                key="t1")
    assert exp.status_code == 200, f"export after import with a fraction in {where}: {exp.status_code} {exp.text[:120]}"
    assert rep1.status_code == 200 and rep2.status_code == 200, (rep1.status_code, rep2.status_code)
    assert call("POST", "/_test/import", raw=exp.content).status_code == 204


# ---------------------------------------------------------------- email predicate also on fixture and import

@pytest.mark.parametrize("email", ["ctl\u0000@example.com", "nbsp @example.com", "zw​@example.com",
                                   "a b@example.com", "two@@example.com", "@example.com", "x@"])
def test_l_bad_email_in_fixture_rejected(email):
    w = World().login_all()
    before = w.snapshot()
    r = call("POST", "/_test/reset", body=fixture(users=[user("ada", 5, email=email), user("bob", 1)]))
    err(r, 422, "validation_failed", repr(email))
    assert w.snapshot() == before


@pytest.mark.parametrize("email", ["plain@example.com", "Üñí.çødé+tag@exämple.com", "emoji😀@example.com",
                                   "a.b-c_d%e'f@sub.domain.example", "UPPER@EXAMPLE.COM", "1@2"])
def test_l_ordinary_emails_accepted_everywhere(email):
    w = World(fixture(users=[user("ada", 5, email=email), user("bob", 1)]))
    assert w.bal("ada") == 5
    j = ok(POST("/auth/signup", body={"email": "x" + email, "password": "longenough1", "display_name": "n"}), 201)
    roundtrip()
    assert ok(GET("/me", j["token"]), 200)["balance"] == 0
    ok(POST("/auth/login", body={"email": email, "password": "correct horse"}), 200)
