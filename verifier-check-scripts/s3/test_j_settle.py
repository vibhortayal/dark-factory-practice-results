"""J. Atomic net settlements (§11)."""
import random

import pytest

from lib import GET, POST, World, burst, call, check_payment, code_of, err, fixture, k, ok, soft, statuses, ts, user


@pytest.fixture()
def w():
    return World().login_all()


def settle(w, transfers, who="op", key=None, **top):
    return POST("/settlements", w.t(who), {"transfers": transfers, **top}, key=key or k())


def T(a, b, amount, **kw):
    return {"from_handle": a, "to_handle": b, "amount": amount, **kw}


def test_j1_permissions(w):
    body = {"transfers": [T("ada", "bob", 1)]}
    err(call("POST", "/settlements", body=body, key=k()), 401, "unauthenticated")
    err(call("POST", "/settlements", "bogus", body=body, key=k()), 401, "unauthenticated")
    for h in ("ada", "bob", "cy", "dan"):
        err(POST("/settlements", w.t(h), body, key=k()), 403, "forbidden", h)
    # a non-operator moving only its own money is still forbidden
    err(settle(w, [T("ada", "bob", 1)], who="ada"), 403, "forbidden")
    s = w.signup("newop@example.com")
    err(POST("/settlements", s["token"], body, key=k()), 403, "forbidden")
    ok(settle(w, [T("ada", "bob", 1)]), 201)
    assert w.bal("ada") == 9999
    # default []: nobody is an operator
    for fx in (fixture(ops=None), fixture(ops=[])):
        w2 = World(fx)
        assert ("settlement_operator_ids" in fx) == (fx.get("settlement_operator_ids") == [])
        for h in ("ada", "op"):
            err(POST("/settlements", w2.t(h), body, key=k()), 403, "forbidden", h)
        assert w2.bal("ada") == 10000
    # several operators
    w3 = World(fixture(ops=["u_op", "u_cy"]))
    ok(settle(w3, [T("ada", "bob", 1)], who="cy"), 201)
    ok(settle(w3, [T("ada", "bob", 1)], who="op"), 201)
    err(settle(w3, [T("ada", "bob", 1)], who="dan"), 403, "forbidden")


def test_j2_batch_shape(w):
    ok(settle(w, [T("ada", "bob", 1) for _ in range(32)]), 201)
    assert w.bal("ada") == 10000 - 32
    err(settle(w, [T("ada", "bob", 1) for _ in range(33)]), 422, "validation_failed")
    err(settle(w, [T("ada", "bob", 1) for _ in range(100)]), 422, "validation_failed")
    err(settle(w, []), 422, "validation_failed")
    err(POST("/settlements", w.t("op"), {}, key=k()), 422, "validation_failed")
    for bad in ({}, "x", None, 5, True, {"0": T("ada", "bob", 1)}):
        err(POST("/settlements", w.t("op"), {"transfers": bad}, key=k()), 422, "validation_failed", repr(bad))
    for bad in (5, "x", None, [], True, [T("ada", "bob", 1)]):
        err(settle(w, [bad]), 422, "validation_failed", f"entry {bad!r}")
        err(settle(w, [T("ada", "bob", 1), bad]), 422, "validation_failed", f"second entry {bad!r}")
    assert w.bal("ada") == 10000 - 32 and w.bal("bob") == 2500 + 32


def test_j3_entry_rules_and_defaults(w):
    s = ok(settle(w, [T("ada", "bob", 100), T("bob", "cy", 50, note="n2", visibility="private"),
                      T("dan", "ada", 1, note="", visibility="public", extra="ignored", request_id="x")],
                  note="top-level ignored", visibility="private", settlement_id="mine"), 201)
    p = s["payments"]
    check_payment(p[0], from_handle="ada", to_handle="bob", amount=100, note="", visibility="public")
    check_payment(p[1], from_handle="bob", to_handle="cy", amount=50, note="n2", visibility="private")
    check_payment(p[2], from_handle="dan", to_handle="ada", amount=1, note="", visibility="public", request_id=None)
    assert s["settlement_id"] != "mine"
    for bad in (0, -1, 1.5, "100", True, None, 10 ** 9 + 1):
        err(settle(w, [T("ada", "bob", bad)]), 422, "validation_failed", f"amount {bad!r}")
    ok(settle(w, [T("op", "cy", 1), T("ada", "bob", 1)]), 201)
    for bad in ("x" * 201, None, 5, ["a"]):
        err(settle(w, [T("ada", "bob", 1, note=bad)]), 422, "validation_failed", f"note {str(bad)[:10]!r}")
    for bad in ("friends", "", None, 1, "PUBLIC"):
        err(settle(w, [T("ada", "bob", 1, visibility=bad)]), 422, "validation_failed", f"visibility {bad!r}")
    err(settle(w, [T("ghost", "bob", 1)]), 404, "not_found")
    err(settle(w, [T("ada", "ghost", 1)]), 404, "not_found")
    err(settle(w, [T("ada", "ada", 1)]), 422, "self_payment")
    err(settle(w, [T("op", "op", 1)]), 422, "self_payment")
    err(settle(w, [{"to_handle": "bob", "amount": 1}]), 422, "validation_failed")
    err(settle(w, [{"from_handle": "ada", "amount": 1}]), 422, "validation_failed")
    err(settle(w, [{"from_handle": "ada", "to_handle": "bob"}]), 422, "validation_failed")
    err(settle(w, [{}]), 422, "validation_failed")
    w.assert_conserved()


def test_j3_first_bad_entry_decides(w):
    before = w.snapshot()
    unaff = T("cy", "ada", 10 ** 9)  # cy has 0
    cases = [
        ([T("ghost", "bob", 1), T("ada", "ada", 1)], 404, "not_found"),
        ([T("ada", "ada", 1), T("ghost", "bob", 1)], 422, "self_payment"),
        ([T("ada", "bob", 0), T("ghost", "bob", 1)], 422, "validation_failed"),
        ([T("ghost", "bob", 1), T("ada", "bob", 0)], 404, "not_found"),
        ([T("ada", "bob", 1), T("ada", "bob", 1, visibility="nope"), T("ghost", "bob", 1)], 422, "validation_failed"),
        ([T("ada", "bob", 1), T("ghost", "bob", 1), T("ada", "bob", 1, note=5)], 404, "not_found"),
        ([unaff, T("ghost", "bob", 1)], 404, "not_found"),
        ([unaff, T("ada", "ada", 1)], 422, "self_payment"),
        ([unaff, T("ada", "bob", "x")], 422, "validation_failed"),
        ([unaff, T("ada", "bob", 1), T("ada", "bob", 1, note="x" * 201)], 422, "validation_failed"),
        ([unaff], 409, "insufficient_funds"),
        ([T("ada", "bob", 1), unaff, T("bob", "cy", 1)], 409, "insufficient_funds"),
    ]
    for transfers, status, code in cases:
        err(settle(w, transfers), status, code, str(transfers)[:120])
    assert w.snapshot() == before


def test_j4_net_affordability():
    w = World(fixture(users=[user("ada", 0), user("bob", 0), user("cy", 100), user("dan", 0), user("op", 0)]))
    # both wallets are empty, the net is zero for each
    s = ok(settle(w, [T("ada", "bob", 100), T("bob", "ada", 100)]), 201)
    assert len(s["payments"]) == 2 and w.bals() == {"ada": 0, "bob": 0, "cy": 100, "dan": 0, "op": 0}
    # chain through empty wallets, in an order that would fail if applied one by one
    s = ok(settle(w, [T("ada", "bob", 100), T("bob", "dan", 100), T("cy", "ada", 100)]), 201)
    assert w.bals() == {"ada": 0, "bob": 0, "cy": 0, "dan": 100, "op": 0}
    # exactly to zero is affordable, one unit more is not
    err(settle(w, [T("dan", "ada", 60), T("dan", "bob", 41)]), 409, "insufficient_funds")
    ok(settle(w, [T("dan", "ada", 60), T("dan", "bob", 40)]), 201)
    assert w.bals() == {"ada": 60, "bob": 40, "cy": 0, "dan": 0, "op": 0}
    # gross outflow above the balance but net fine
    ok(settle(w, [T("ada", "cy", 500), T("cy", "ada", 440)]), 201)
    assert w.bals() == {"ada": 0, "bob": 40, "cy": 60, "dan": 0, "op": 0}
    # net one unit short
    err(settle(w, [T("bob", "cy", 500), T("cy", "bob", 459)]), 409, "insufficient_funds")
    err(settle(w, [T("op", "ada", 1)]), 409, "insufficient_funds")
    # one wallet short makes the whole batch fail even if others are fine
    err(settle(w, [T("bob", "ada", 40), T("cy", "ada", 60), T("dan", "ada", 1)]), 409, "insufficient_funds")
    assert w.bals() == {"ada": 0, "bob": 40, "cy": 60, "dan": 0, "op": 0}
    assert w.seeded_total() == sum(w.bals().values())


def test_j5_all_or_nothing_and_key_reusable(w):
    before = w.snapshot()
    key = k()
    err(settle(w, [T("ada", "bob", 100), T("cy", "bob", 1)], key=key), 409, "insufficient_funds")
    assert w.snapshot() == before
    err(settle(w, [T("ada", "bob", 100), T("ada", "ghost", 1)], key=key), 404, "not_found")
    err(settle(w, [T("ada", "bob", 100), T("bob", "bob", 1)], key=key), 422, "self_payment")
    err(settle(w, [T("ada", "bob", 100), T("ada", "bob", 0)], key=key), 422, "validation_failed")
    err(settle(w, [], key=key), 422, "validation_failed")
    assert w.snapshot() == before
    s = ok(settle(w, [T("ada", "bob", 100), T("cy", "bob", 1), T("ada", "cy", 1)], key=key), 201)
    assert len(s["payments"]) == 3
    assert ok(settle(w, [T("ada", "bob", 100), T("cy", "bob", 1), T("ada", "cy", 1)], key=key), 200) == s
    assert w.bals() == {"ada": 9899, "bob": 2601, "cy": 0, "dan": 500, "op": 1000}


def test_j6_response_and_membership(w):
    direct = ok(w.pay("ada", "bob", 5), 201)
    q = w.new_request("bob", "ada", 6)
    paid = ok(w.pay_request("ada", q["request_id"]), 201)
    assert direct["settlement_id"] is None and paid["settlement_id"] is None
    transfers = [T("ada", "bob", 100, note="one"), T("bob", "cy", 50, note="two"), T("cy", "dan", 25, note="three"),
                 T("ada", "bob", 100, note="one")]
    s = ok(settle(w, transfers), 201)
    assert set(s) >= {"settlement_id", "committed_at", "payments"}
    soft(set(s) == {"settlement_id", "committed_at", "payments"}, "settlement-extra-keys", keys=sorted(s))
    sid = s["settlement_id"]
    assert isinstance(sid, str) and 1 <= len(sid) <= 64
    ts(s["committed_at"])
    assert [(p["from_handle"], p["to_handle"], p["amount"], p["note"]) for p in s["payments"]] == \
        [(t["from_handle"], t["to_handle"], t["amount"], t["note"]) for t in transfers]
    for p in s["payments"]:
        check_payment(p, settlement_id=sid, request_id=None, created_at=s["committed_at"], currency="EUR",
                      visibility="public")
    assert s["payments"][0]["from_user_id"] == "u_ada" and s["payments"][0]["to_user_id"] == "u_bob"
    ids = [p["payment_id"] for p in s["payments"]]
    assert len(set(ids)) == 4 and direct["payment_id"] not in ids and paid["payment_id"] not in ids
    assert w.bals() == {"ada": 10000 - 11 - 200, "bob": 2500 + 11 + 200 - 50, "cy": 25, "dan": 525, "op": 1000}
    feed = {p["payment_id"]: p for p in w.activity("dan")}
    for p in s["payments"]:
        assert feed[p["payment_id"]] == p
    assert feed[direct["payment_id"]]["settlement_id"] is None
    assert feed[paid["payment_id"]]["settlement_id"] is None and feed[paid["payment_id"]]["request_id"] == q["request_id"]
    s2 = ok(settle(w, [T("dan", "ada", 1)]), 201)
    assert s2["settlement_id"] != sid
    assert not ({p["payment_id"] for p in s2["payments"]} & set(ids))
    # a settlement creates no requests
    for h in w.handles():
        assert all(r["request_id"] == q["request_id"] for r in w.requests(h))


def test_j7_visibility_and_no_extra_access(w):
    s = ok(settle(w, [T("ada", "bob", 10, visibility="private", note="prv"), T("ada", "cy", 10, note="pub"),
                      T("dan", "op", 10, visibility="private", note="op-prv")]), 201)
    prv, pub, opprv = (p["payment_id"] for p in s["payments"])
    ids = lambda h: {p["payment_id"] for p in w.activity(h)}  # noqa: E731
    assert ids("ada") == {prv, pub} and ids("bob") == {prv, pub}
    assert ids("cy") == {pub}
    assert ids("dan") == {pub, opprv}
    assert ids("op") == {pub, opprv}, "operator sees a private payment it is not party to (or misses its own)"
    assert {p["payment_id"]: p for p in w.activity("bob")}[prv] == s["payments"][0]
    # operator has no access to other users' requests
    q = w.new_request("bob", "ada", 5)
    direct_prv = ok(w.pay("ada", "bob", 3, visibility="private"), 201)
    assert w.requests("op") == []
    for flt in ("direction=incoming", "direction=outgoing", "status=pending"):
        assert w.requests("op", flt) == []
    for action in ("pay", "decline", "cancel"):
        r = POST(f"/requests/{q['request_id']}/{action}", w.t("op"), {}, key=k() if action == "pay" else None)
        err(r, (403, 404), ("forbidden", "not_found"), action)
    assert direct_prv["payment_id"] not in ids("op")
    assert w.requests("ada")[0]["status"] == "pending"
    # the operator is an ordinary user otherwise
    ok(w.pay("op", "ada", 1), 201)
    assert w.me("op")["balance"] == 1000 + 10 - 1
    w.assert_conserved()


def test_j8_replay_and_conflict(w):
    key = k()
    body = [T("ada", "bob", 10), T("bob", "cy", 5, visibility="private")]
    s = ok(settle(w, body, key=key), 201)
    after = w.snapshot()
    for _ in range(3):
        assert ok(settle(w, body, key=key), 200) == s
    err(settle(w, body[::-1], key=key), 409, "idempotency_key_reuse")  # order matters in an array
    err(settle(w, body[:1], key=key), 409, "idempotency_key_reuse")
    err(settle(w, [], key=key), 409, "idempotency_key_reuse")
    assert w.snapshot() == after
    # the same transfers under a new key are a new settlement
    s2 = ok(settle(w, body), 201)
    assert s2["settlement_id"] != s["settlement_id"]


def test_j8_fifty_concurrent_identical(w):
    key = k()
    body = [T("ada", "bob", 10), T("bob", "cy", 5), T("cy", "dan", 5)]
    rs = burst([lambda: settle(w, body, key=key) for _ in range(50)])
    assert statuses(rs) == {201: 1, 200: 49}, statuses(rs)
    first = rs[0].json()
    assert all(r.json() == first for r in rs)
    assert w.bals() == {"ada": 9990, "bob": 2505, "cy": 0, "dan": 505, "op": 1000}
    assert len(w.activity("ada")) == 3


def test_j8_fifty_concurrent_different_settlements():
    rnd = random.Random(11)
    hs = ["ada", "bob", "cy", "dan", "op"]
    start = {"ada": 3000, "bob": 2000, "cy": 0, "dan": 500, "op": 1000}
    w = World(fixture(users=[user(h, v) for h, v in start.items()])).login_all()
    expect = dict(start)
    for _round in range(4):
        bodies = []
        for _ in range(50):
            n = rnd.randint(1, 6)
            bodies.append([T(*rnd.sample(hs, 2), rnd.randint(1, 900)) for _ in range(n)])
        seen = []

        def poll():
            for h in hs:
                seen.append(call("GET", "/me", w.t(h)).json()["balance"])

        rs = burst([lambda b=b: settle(w, b) for b in bodies[:48]] + [poll, poll])
        rs = [r for r in rs if r is not None]
        st = statuses(rs)
        assert set(st) <= {201, 409}, st
        assert st.get(201, 0) >= 1
        for r, b in zip(rs, bodies[:48]):
            if r.status_code == 201:
                j = r.json()
                assert [(p["from_handle"], p["to_handle"], p["amount"]) for p in j["payments"]] == \
                    [(t["from_handle"], t["to_handle"], t["amount"]) for t in b]
                assert len({p["created_at"] for p in j["payments"]} | {j["committed_at"]}) == 1
                for t in b:
                    expect[t["from_handle"]] -= t["amount"]
                    expect[t["to_handle"]] += t["amount"]
            else:
                assert code_of(r) == "insufficient_funds", r.text
        assert min(seen) >= 0
        b = w.assert_conserved()
        assert b == expect, f"balances {b} != net of committed settlements {expect}"


def test_j8_settlements_against_payments_no_overdraw():
    w = World(fixture(users=[user("ada", 1000), user("bob", 0), user("cy", 0), user("op", 0)])).login_all()
    fns = []
    for i in range(50):
        if i % 2:
            fns.append(lambda: w.pay("ada", "bob", 100))
        else:
            fns.append(lambda: settle(w, [T("ada", "cy", 60), T("ada", "bob", 40)]))
    rs = burst(fns)
    st = statuses(rs)
    assert st == {201: 10, 409: 40}, st
    assert all(code_of(r) == "insufficient_funds" for r in rs if r.status_code == 409)
    b = w.assert_conserved()
    assert b["ada"] == 0
