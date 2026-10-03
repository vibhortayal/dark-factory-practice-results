"""F. Idempotency on the eight write paths (stage 1: five, stage 2: two, stage 3: corrections)."""
import json

import pytest

from lib import GET, POST, World, burst, call, code_of, err, fixture, k, ok, soft, statuses, user

PATHS = ["payments", "requests", "pay", "splits", "settlements", "authorizations", "capture", "corrections"]


class Case:
    """One valid request on one of the five paths, plus a count of its visible effect."""

    def __init__(self, w: World, name: str, amount: int = 40):
        self.w, self.name = w, name
        self.who = "op" if name == "settlements" else "ada"
        if name == "payments":
            self.path, self.body = "/payments", {"to_handle": "bob", "amount": amount, "note": "idem"}
        elif name == "requests":
            self.path, self.body = "/requests", {"payer_handle": "bob", "amount": amount, "note": "idem"}
        elif name == "pay":
            self.rid = w.new_request("bob", "ada", amount)["request_id"]
            self.path, self.body = f"/requests/{self.rid}/pay", {"visibility": "private"}
        elif name == "splits":
            self.path, self.body = "/splits", {"amount": amount, "participant_handles": ["ada", "bob", "cy"],
                                               "note": "idem"}
        elif name == "authorizations":
            self.path, self.body = "/authorizations", {"to_handle": "bob", "amount": amount, "note": "idem"}
        elif name == "capture":
            self.aid = w.new_auth("bob", "ada", amount + 5)["authorization_id"]
            self.path, self.body = f"/authorizations/{self.aid}/capture", {"amount": amount}
        elif name == "corrections":
            self.payment = ok(w.pay("ada", "bob", amount + 20, note="to be corrected"), 201)
            self.path = f"/payments/{self.payment['payment_id']}/corrections"
            self.body = {"expected_revision": 1, "amount": amount, "effective_at": self.payment["created_at"],
                         "reason": "idem"}
        else:
            self.path, self.body = "/settlements", {"transfers": [
                {"from_handle": "ada", "to_handle": "bob", "amount": amount, "note": "idem"},
                {"from_handle": "bob", "to_handle": "cy", "amount": 1}]}
        self.other = dict(self.body)
        if name == "pay":
            self.other = {"visibility": "public"}
        elif name == "settlements":
            self.other = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": amount + 1}]}
        else:
            self.other["amount"] = amount + 1

    def send(self, key, body=None, token=None, raw=None):
        if raw is not None:
            return call("POST", self.path, token or self.w.t(self.who), key=key, raw=raw)
        return POST(self.path, token or self.w.t(self.who), self.body if body is None else body, key=key)

    def effect(self):
        """State a repeat would change: every balance, and how many payments / requests exist."""
        w = self.w
        return (w.wallets(), len(w.activity("ada")), len(w.requests("ada")), len(w.requests("bob")),
                len(w.requests("cy")), len(w.activity("op")),
                [(a["status"], a["captured_amount"], a["remaining_amount"]) for a in w.auths("ada")])


@pytest.fixture()
def w():
    return World().login_all()


@pytest.mark.parametrize("name", PATHS)
def test_f1_f2_first_201_replay_200_no_further_effect(w, name):
    c = Case(w, name)
    before = c.effect()
    key = k()
    first = c.send(key)
    j = ok(first, 201)
    after = c.effect()
    assert after != before
    for _ in range(3):
        assert ok(c.send(key), 200) == j
    assert c.effect() == after
    w.assert_conserved()


@pytest.mark.parametrize("name", PATHS)
def test_f2_replay_key_order_and_whitespace(w, name):
    c = Case(w, name)
    key = k()
    j = ok(c.send(key), 201)

    def rev(v):
        if isinstance(v, dict):
            return {kk: rev(v[kk]) for kk in reversed(list(v))}
        if isinstance(v, list):
            return [rev(x) for x in v]
        return v

    raw = json.dumps(rev(c.body), indent=4, separators=(" ,  ", " :\n\t "))
    assert ok(c.send(key, raw=raw), 200) == j
    raw2 = "\n\n  " + json.dumps(c.body, ensure_ascii=True) + "  \r\n"
    assert ok(c.send(key, raw=raw2), 200) == j


@pytest.mark.parametrize("name", ["payments", "requests", "splits", "settlements", "authorizations", "capture"])
def test_f2_replay_with_other_number_spelling(w, name):
    c = Case(w, name, amount=1000)
    key = k()
    j = ok(c.send(key), 201)
    raw = json.dumps(c.body).replace("1000", "1e3")
    r = c.send(key, raw=raw)
    if soft(r.status_code == 200, "replay-1e3-vs-1000-not-200", path=c.path, status=r.status_code):
        assert r.json() == j
    else:
        err(r, 409, "idempotency_key_reuse")


@pytest.mark.parametrize("name", PATHS)
def test_f2_replay_through_another_token_of_same_user(w, name):
    c = Case(w, name)
    key = k()
    j = ok(c.send(key), 201)
    u = w._u(c.who)
    t2 = ok(POST("/auth/login", body={"email": u["email"], "password": u["password"]}), 200)["token"]
    assert ok(c.send(key, token=t2), 200) == j
    err(c.send(key, body=c.other, token=t2), 409, "idempotency_key_reuse")


@pytest.mark.parametrize("name", PATHS)
def test_f3_same_key_different_body_409(w, name):
    c = Case(w, name)
    key = k()
    j = ok(c.send(key), 201)
    after = c.effect()
    err(c.send(key, body=c.other), 409, "idempotency_key_reuse")
    assert c.effect() == after
    assert ok(c.send(key), 200) == j


def test_f3_pay_empty_vs_public(w):
    rid = w.new_request("bob", "ada", 10)["request_id"]
    key = k()
    j = ok(w.pay_request("ada", rid, key=key, body={}), 201)
    assert j["visibility"] == "public"
    err(w.pay_request("ada", rid, key=key, body={"visibility": "public"}), 409, "idempotency_key_reuse")
    assert ok(w.pay_request("ada", rid, key=key, body={}), 200) == j
    rid2 = w.new_request("bob", "ada", 10)["request_id"]
    key2 = k()
    j2 = ok(w.pay_request("ada", rid2, key=key2, body={"visibility": "public"}), 201)
    err(w.pay_request("ada", rid2, key=key2, body={}), 409, "idempotency_key_reuse")
    assert ok(w.pay_request("ada", rid2, key=key2, body={"visibility": "public"}), 200) == j2


@pytest.mark.parametrize("name", ["payments", "requests", "splits"])
def test_f4_key_scoped_to_user(w, name):
    key = k()
    c = Case(w, name)
    body = {"payments": {"to_handle": "cy", "amount": 5}, "requests": {"payer_handle": "cy", "amount": 5},
            "splits": {"amount": 5, "participant_handles": ["cy"]}}[name]
    a = ok(POST(c.path, w.t("ada"), body, key=key), 201)
    b = ok(POST(c.path, w.t("bob"), body, key=key), 201)
    assert a != b
    idk = {"payments": "payment_id", "requests": "request_id", "splits": "split_id"}[name]
    assert a[idk] != b[idk]
    assert ok(POST(c.path, w.t("ada"), body, key=key), 200) == a
    assert ok(POST(c.path, w.t("bob"), body, key=key), 200) == b
    # a different body from the other user with the same key is that user's own conflict only
    err(POST(c.path, w.t("bob"), dict(body, amount=6), key=key), 409, "idempotency_key_reuse")
    assert ok(POST(c.path, w.t("ada"), body, key=key), 200) == a


def test_f4_pay_and_settlement_keys_do_not_cross_users():
    w = World(fixture(ops=["u_op", "u_dan"])).login_all()
    key = k()
    body = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 3}]}
    a = ok(POST("/settlements", w.t("op"), body, key=key), 201)
    b = ok(POST("/settlements", w.t("dan"), body, key=key), 201)
    assert a["settlement_id"] != b["settlement_id"]
    assert ok(POST("/settlements", w.t("op"), body, key=key), 200) == a
    assert w.bal("ada") == 10000 - 6
    # a non-payer using the payer's key string on the same pay path does not see the payer's response
    rid = w.new_request("bob", "ada", 10)["request_id"]
    j = ok(w.pay_request("ada", rid, key=key), 201)
    r = w.pay_request("cy", rid, key=key)
    assert r.status_code in (403, 404, 409), r.text
    assert r.status_code != 200
    assert ok(w.pay_request("ada", rid, key=key), 200) == j


def test_f5_same_key_and_body_on_different_paths(w):
    key = k()
    body = {"to_handle": "bob", "payer_handle": "bob", "participant_handles": ["bob"], "amount": 30, "note": "x"}
    p = ok(POST("/payments", w.t("ada"), body, key=key), 201)
    q = ok(POST("/requests", w.t("ada"), body, key=key), 201)
    s = ok(POST("/splits", w.t("ada"), body, key=key), 201)
    assert "payment_id" in p and "request_id" in q and "split_id" in s
    assert ok(POST("/payments", w.t("ada"), body, key=key), 200) == p
    assert ok(POST("/requests", w.t("ada"), body, key=key), 200) == q
    assert ok(POST("/splits", w.t("ada"), body, key=key), 200) == s
    # the same key and body on two request ids
    r1 = w.new_request("bob", "ada", 10)["request_id"]
    r2 = w.new_request("bob", "ada", 20)["request_id"]
    a = ok(w.pay_request("ada", r1, key=key, body={}), 201)
    b = ok(w.pay_request("ada", r2, key=key, body={}), 201)
    assert (a["amount"], b["amount"]) == (10, 20) and a["payment_id"] != b["payment_id"]
    assert ok(w.pay_request("ada", r1, key=key, body={}), 200) == a
    assert ok(w.pay_request("ada", r2, key=key, body={}), 200) == b
    # operator: settlements with a key it also used on /payments
    kk = k()
    pb = {"to_handle": "bob", "amount": 1, "transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}
    ok(POST("/payments", w.t("op"), pb, key=kk), 201)
    ok(POST("/settlements", w.t("op"), pb, key=kk), 201)
    assert w.bal("ada") == 10000 - 30 - 10 - 20 - 1
    w.assert_conserved()


def test_f6_failed_key_is_first_use_again(w):
    # 422 then valid
    key = k()
    err(w.pay("ada", "bob", 0, key=key), 422, "validation_failed")
    ok(w.pay("ada", "bob", 5, key=key), 201)
    # 404 then valid, other body
    key = k()
    err(w.pay("ada", "ghost", 5, key=key), 404, "not_found")
    ok(w.pay("ada", "bob", 5, key=key), 201)
    # self_payment then valid
    key = k()
    err(w.pay("ada", "ada", 5, key=key), 422, "self_payment")
    ok(w.pay("ada", "bob", 5, key=key), 201)
    # insufficient funds, then the same body succeeds once funded, then replays
    key = k()
    err(w.pay("cy", "dan", 50, key=key), 409, "insufficient_funds")
    err(w.pay("cy", "dan", 50, key=key), 409, "insufficient_funds")
    ok(w.pay("ada", "cy", 50), 201)
    j = ok(w.pay("cy", "dan", 50, key=key), 201)
    assert ok(w.pay("cy", "dan", 50, key=key), 200) == j
    assert w.bal("cy") == 0 and w.bal("dan") == 550
    # requests
    key = k()
    err(w.request("ada", "ada", 5, key=key), 422, "self_request")
    err(w.request("ada", "ghost", 5, key=key), 404, "not_found")
    err(w.request("ada", "bob", 10 ** 9 + 1, key=key), 422, "validation_failed")
    ok(w.request("ada", "bob", 5, key=key), 201)
    # splits
    key = k()
    err(POST("/splits", w.t("ada"), {"amount": 5, "participant_handles": []}, key=key), 422, "validation_failed")
    err(POST("/splits", w.t("ada"), {"amount": 5, "participant_handles": ["ghost"]}, key=key), 404, "not_found")
    ok(POST("/splits", w.t("ada"), {"amount": 5, "participant_handles": ["bob"]}, key=key), 201)
    # pay: insufficient, forbidden, then success with the same key
    rid = w.new_request("ada", "cy", 70)["request_id"]
    key = k()
    err(w.pay_request("cy", rid, key=key), 409, "insufficient_funds")
    err(w.pay_request("bob", rid, key=key), (403, 404), ("forbidden", "not_found"))
    ok(w.pay("ada", "cy", 70), 201)
    j = ok(w.pay_request("cy", rid, key=key), 201)
    assert ok(w.pay_request("cy", rid, key=key), 200) == j
    # settlements: 403 for a non-operator claims nothing, operator failure claims nothing
    key = k()
    body = {"transfers": [{"from_handle": "cy", "to_handle": "bob", "amount": 999999}]}
    err(POST("/settlements", w.t("op"), body, key=key), 409, "insufficient_funds")
    ok(POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 9}]},
            key=key), 201)
    w.assert_conserved()


@pytest.mark.parametrize("name", PATHS)
def test_f7_fifty_concurrent_identical(w, name):
    c = Case(w, name)
    before = c.effect()
    key = k()
    rs = burst([lambda: c.send(key) for _ in range(50)])
    st = statuses(rs)
    assert st == {201: 1, 200: 49}, st
    first = rs[0].json()
    assert all(r.json() == first for r in rs)
    after = c.effect()
    # the effect equals that of exactly one request
    w2 = World().login_all()
    c2 = Case(w2, name)
    b2 = c2.effect()
    ok(c2.send(k()), 201)
    a2 = c2.effect()
    assert after == a2 and before == b2
    w2.assert_conserved()


@pytest.mark.parametrize("name", PATHS)
def test_f7_fifty_concurrent_one_key_two_bodies(w, name):
    c = Case(w, name)
    key = k()
    rs = burst([(lambda: c.send(key)) if i % 2 else (lambda: c.send(key, body=c.other)) for i in range(50)])
    st = statuses(rs)
    assert set(st) <= {201, 200, 409}, st
    assert st.get(201) == 1, st
    winner = [r for r in rs if r.status_code == 201][0].json()
    for r in rs:
        if r.status_code == 200:
            assert r.json() == winner
        elif r.status_code == 409:
            assert code_of(r) == "idempotency_key_reuse", r.text
    assert st.get(200, 0) == 24 and st.get(409, 0) == 25, st
    w.assert_conserved()


INVALID = {
    "payments": [{"to_handle": "bob", "amount": 0}, {"to_handle": "bob"}, {"to_handle": "ghost", "amount": 5},
                 {"to_handle": "ada", "amount": 5}, {"to_handle": "bob", "amount": "x"}, {},
                 {"to_handle": 5, "amount": 5}, {"to_handle": "bob", "amount": 5, "visibility": "nope"},
                 {"to_handle": "bob", "amount": 10 ** 12}],
    "requests": [{"payer_handle": "bob", "amount": -1}, {"amount": 5}, {"payer_handle": "ghost", "amount": 5},
                 {"payer_handle": "ada", "amount": 5}, {}],
    "pay": [{"visibility": "nope"}, {"visibility": None}, {"visibility": 5}],
    "splits": [{"amount": 5, "participant_handles": []}, {"amount": 5, "participant_handles": ["ghost"]},
               {"amount": 0, "participant_handles": ["bob"]}, {"participant_handles": ["bob"]}, {},
               {"amount": 5, "participant_handles": "bob"}],
    "authorizations": [{"to_handle": "bob", "amount": 0}, {"to_handle": "bob"}, {"to_handle": "ghost", "amount": 5},
                       {"to_handle": "ada", "amount": 5}, {"to_handle": "bob", "amount": "x"}, {},
                       {"to_handle": 5, "amount": 5}, {"to_handle": "bob", "amount": 5, "visibility": "nope"},
                       {"to_handle": "bob", "amount": 10 ** 12}],
    "corrections": [{}, {"expected_revision": 1}, {"expected_revision": 0, "amount": 5, "effective_at": "2020-01-01T00:00:00Z", "reason": "x"},
                    {"expected_revision": 1, "amount": -1, "effective_at": "2020-01-01T00:00:00Z", "reason": "x"},
                    {"expected_revision": 1, "amount": 5, "effective_at": "yesterday", "reason": "x"},
                    {"expected_revision": 1, "amount": 5, "effective_at": "2020-01-01T00:00:00Z", "reason": ""},
                    {"expected_revision": 7, "amount": 5, "effective_at": "2020-01-01T00:00:00Z", "reason": "stale"},
                    {"expected_revision": 1, "amount": 10 ** 12, "effective_at": "2020-01-01T00:00:00Z", "reason": "x"}],
    "capture": [{"amount": 0}, {"amount": "x"}, {"amount": 10 ** 12}, {"final": "no"}, {"amount": 1.5}, {"amount": None}],
    "settlements": [{"transfers": []}, {}, {"transfers": [{"from_handle": "ada", "to_handle": "ada", "amount": 1}]},
                    {"transfers": [{"from_handle": "ghost", "to_handle": "ada", "amount": 1}]},
                    {"transfers": "x"}, {"transfers": [{"from_handle": "cy", "to_handle": "ada", "amount": 10 ** 9}]}],
}


@pytest.mark.parametrize("name", PATHS)
def test_f8_claimed_key_with_invalid_body_is_409_reuse(w, name):
    c = Case(w, name)
    key = k()
    j = ok(c.send(key), 201)
    after = c.effect()
    for bad in INVALID[name]:
        err(c.send(key, body=bad), 409, "idempotency_key_reuse", f"{name} {bad}")
    # an unparseable body is not "parsed as a JSON object": it stays 400
    err(c.send(key, raw=b"{nope"), 400, "malformed_request")
    assert c.effect() == after
    assert ok(c.send(key), 200) == j


def test_f8_f2_replay_after_resource_changed(w):
    # request created, then cancelled: replay returns the original pending body
    key = k()
    q = ok(w.request("ada", "bob", 15, key=key), 201)
    assert ok(POST(f"/requests/{q['request_id']}/cancel", w.t("ada")), 200)["status"] == "cancelled"
    assert ok(w.request("ada", "bob", 15, key=key), 200) == q
    assert q["status"] == "pending"
    # request created, then paid
    key = k()
    q = ok(w.request("ada", "bob", 15, key=key), 201)
    kp = k()
    p = ok(w.pay_request("bob", q["request_id"], key=kp), 201)
    assert ok(w.request("ada", "bob", 15, key=key), 200) == q
    # pay replay on the now paid request: 200, never request_not_pending
    assert ok(w.pay_request("bob", q["request_id"], key=kp), 200) == p
    err(w.pay_request("bob", q["request_id"], key=k()), 409, "request_not_pending")
    assert ok(w.pay_request("bob", q["request_id"], key=kp), 200) == p
    # payment, then the payer is drained: replay still 200 and moves nothing
    key = k()
    p = ok(w.pay("dan", "cy", 400, key=key), 201)
    ok(w.pay("dan", "cy", 100), 201)
    assert w.bal("dan") == 0
    assert ok(w.pay("dan", "cy", 400, key=key), 200) == p
    assert w.bal("dan") == 0 and w.bal("cy") == 500
    # split, then its requests declined / paid: replay returns the original split with pending requests
    key = k()
    body = {"amount": 9, "participant_handles": ["ada", "bob", "cy"]}
    s = ok(POST("/splits", w.t("ada"), body, key=key), 201)
    ok(POST(f"/requests/{s['requests'][0]['request_id']}/decline", w.t("bob")), 200)
    ok(w.pay_request("cy", s["requests"][1]["request_id"]), 201)
    assert ok(POST("/splits", w.t("ada"), body, key=key), 200) == s
    assert [x["status"] for x in s["requests"]] == ["pending", "pending"]
    assert len(w.requests("bob", "status=pending&limit=200")) == 0
    # settlement replay after balances moved on
    key = k()
    sb = {"transfers": [{"from_handle": "cy", "to_handle": "bob", "amount": w.bal("cy")}]}
    st = ok(POST("/settlements", w.t("op"), sb, key=key), 201)
    assert w.bal("cy") == 0
    assert ok(POST("/settlements", w.t("op"), sb, key=key), 200) == st
    assert w.bal("cy") == 0
    w.assert_conserved()


@pytest.mark.parametrize("name", PATHS)
def test_f9_unknown_field_makes_a_different_body(w, name):
    c = Case(w, name)
    key = k()
    j = ok(c.send(key), 201)
    err(c.send(key, body={**c.body, "extra_field": 1}), 409, "idempotency_key_reuse")
    assert ok(c.send(key), 200) == j
    key2 = k()
    c2 = Case(w, name, amount=41)
    j2 = ok(c2.send(key2, body={**c2.body, "extra_field": 1}), 201)
    err(c2.send(key2), 409, "idempotency_key_reuse")
    err(c2.send(key2, body={**c2.body, "extra_field": 2}), 409, "idempotency_key_reuse")
    assert ok(c2.send(key2, body={**c2.body, "extra_field": 1}), 200) == j2


def test_f10_keys_compare_exactly(w):
    base = k()
    a = ok(w.pay("ada", "bob", 1, key=base + "abc"), 201)
    b = ok(w.pay("ada", "bob", 1, key=base + "ABC"), 201)
    c = ok(w.pay("ada", "bob", 1, key=base + "abc "[:-1] + "d"), 201)
    assert len({a["payment_id"], b["payment_id"], c["payment_id"]}) == 3
    assert ok(w.pay("ada", "bob", 1, key=base + "abc"), 200) == a
    assert w.bal("ada") == 10000 - 3


def test_f_replay_does_not_need_funds_or_pending_state_and_bool_vs_number(w):
    key = k()
    j = ok(POST("/payments", w.t("ada"), {"to_handle": "bob", "amount": 1, "flag": 1}, key=key), 201)
    r = POST("/payments", w.t("ada"), {"to_handle": "bob", "amount": 1, "flag": True}, key=key)
    err(r, 409, "idempotency_key_reuse")
    r = POST("/payments", w.t("ada"), {"to_handle": "bob", "amount": 1, "flag": "1"}, key=key)
    err(r, 409, "idempotency_key_reuse")
    assert ok(POST("/payments", w.t("ada"), {"flag": 1, "amount": 1, "to_handle": "bob"}, key=key), 200) == j
