"""B. Invariants under concurrency (at most 50 requests in flight, the stated limit)."""
import random
import threading

from lib import GET, POST, World, burst, call, code_of, err, fixture, k, ok, statuses, user


def test_b2_fifty_concurrent_drains_never_overdraw():
    w = World().login_all()
    seen = []
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            seen.append(call("GET", "/me", w.t("ada")).json()["balance"])

    th = threading.Thread(target=poll)
    fns = [lambda: w.pay("ada", "bob", 300) for _ in range(49)]
    th.start()
    try:
        rs = burst(fns)  # 49 writers + 1 poller = 50 in flight
    finally:
        stop.set()
        th.join()
    rs += [w.pay("ada", "bob", 300)]
    st = statuses(rs)
    assert set(st) <= {201, 409}, st
    assert st.get(201) == 33, f"10000 // 300 = 33 payments must succeed, got {st}"
    for r in rs:
        if r.status_code == 409:
            err(r, 409, "insufficient_funds")
    assert min(seen) >= 0, f"negative balance observed: {min(seen)}"
    b = w.assert_conserved()
    assert b["ada"] == 100 and b["bob"] == 2500 + 9900
    assert len([p for p in w.activity("ada") if p["from_handle"] == "ada"]) == 33


def test_b2_fifty_in_flight_exact():
    w = World().login_all()
    rs = burst([lambda: w.pay("ada", "cy", 300) for _ in range(50)])
    st = statuses(rs)
    assert st == {201: 33, 409: 17}, st
    assert all(code_of(r) == "insufficient_funds" for r in rs if r.status_code == 409)
    b = w.assert_conserved()
    assert b["ada"] == 100 and b["cy"] == 9900


def test_b2_two_requests_one_wallet():
    for _ in range(5):
        w = World(fixture(users=[user("ada", 1000), user("bob", 0), user("cy", 0)])).login_all()
        r1 = w.new_request("bob", "ada", 800)
        r2 = w.new_request("cy", "ada", 800)
        rs = burst([lambda: w.pay_request("ada", r1["request_id"]), lambda: w.pay_request("ada", r2["request_id"])])
        assert sorted(r.status_code for r in rs) == [201, 409], [r.text for r in rs]
        err([r for r in rs if r.status_code == 409][0], 409, "insufficient_funds")
        b = w.assert_conserved()
        assert b["ada"] == 200
        assert sorted(q["status"] for q in w.requests("ada")) == ["paid", "pending"]


def test_b3_request_paid_once_distinct_keys():
    w = World().login_all()
    q = w.new_request("bob", "ada", 700)
    rs = burst([lambda: w.pay_request("ada", q["request_id"]) for _ in range(50)])
    st = statuses(rs)
    assert st == {201: 1, 409: 49}, st
    assert all(code_of(r) == "request_not_pending" for r in rs if r.status_code == 409)
    b = w.assert_conserved()
    assert b["ada"] == 9300 and b["bob"] == 3200
    assert len([p for p in w.activity("ada") if p["request_id"] == q["request_id"]]) == 1


def test_b3_request_paid_once_same_key():
    w = World().login_all()
    q = w.new_request("bob", "ada", 700)
    key = k()
    rs = burst([lambda: w.pay_request("ada", q["request_id"], key=key) for _ in range(50)])
    st = statuses(rs)
    assert st == {201: 1, 200: 49}, st
    first = rs[0].json()
    assert all(r.json() == first for r in rs)
    b = w.assert_conserved()
    assert b["ada"] == 9300 and b["bob"] == 3200
    assert len([p for p in w.activity("ada") if p["request_id"] == q["request_id"]]) == 1


def test_b4_exact_integers_near_2_53():
    top = 2 ** 53 - 1
    a0, b0 = 5_000_000_001, top - 5_000_000_001 - 1_000_000_000 - 7  # sum stays below 2^53
    w = World(fixture(users=[user("ada", a0), user("bob", b0), user("cy", 1_000_000_007)]))
    assert w.bals() == {"ada": a0, "bob": b0, "cy": 1_000_000_007}
    assert sum(w.bals().values()) == top
    ok(w.pay("ada", "bob", 1_000_000_000), 201)
    ok(w.pay("ada", "bob", 1), 201)
    ok(w.pay("cy", "bob", 1_000_000_000), 201)
    ok(w.pay("cy", "bob", 7), 201)
    ok(w.pay("ada", "bob", 4_000_000_000 // 4), 201)
    b = w.assert_conserved()
    assert b == {"ada": a0 - 2_000_000_001, "bob": b0 + 3_000_000_008, "cy": 0}
    q = w.new_request("ada", "bob", 999_999_999)
    ok(w.pay_request("bob", q["request_id"]), 201)
    b = w.assert_conserved()
    assert b["bob"] == b0 + 3_000_000_008 - 999_999_999
    # one wallet holding the whole 2^53 - 1
    w = World(fixture(users=[user("ada", top - 5), user("bob", 5)]))
    ok(w.pay("bob", "ada", 5), 201)
    assert w.bal("ada") == top
    ok(w.pay("ada", "bob", 1), 201)
    assert w.bals() == {"ada": top - 1, "bob": 1}


def test_b4_minor_units_0_and_3():
    for cur, mu in (("JPY", 0), ("BHD", 3), ("EUR", 2)):
        w = World(fixture(users=[user("ada", 1001), user("bob", 0)], currency=cur, minor=mu))
        me = w.me("ada")
        assert (me["currency"], me["minor_units"], me["balance"]) == (cur, mu, 1001)
        p = ok(w.pay("ada", "bob", 1001), 201)
        assert p["currency"] == cur and p["amount"] == 1001
        q = w.new_request("ada", "bob", 333)
        assert q["currency"] == cur
        s = ok(POST("/splits", w.t("ada"), {"amount": 1000, "participant_handles": ["ada", "bob"]}, key=k()), 201)
        assert s["currency"] == cur
        assert w.bals() == {"ada": 0, "bob": 1001}


def test_b5_failed_payment_leaves_no_trace():
    w = World().login_all()
    before = w.snapshot()
    err(w.pay("cy", "ada", 1), 409, "insufficient_funds")
    err(w.pay("dan", "ada", 501), 409, "insufficient_funds")
    err(w.pay("ada", "ada", 5), 422, "self_payment")
    err(w.pay("ada", "nobody", 5), 404, "not_found")
    err(w.pay("ada", "bob", 0), 422, "validation_failed")
    err(w.pay("ada", "bob", 5, visibility="x"), 422, "validation_failed")
    assert w.snapshot() == before


def test_b6_cycle_fifty_in_flight():
    w = World(fixture(users=[user("ada", 100000), user("bob", 100000), user("cy", 100000)])).login_all()
    ring = [("ada", "bob"), ("bob", "cy"), ("cy", "ada")]
    counts = {"ada": 0, "bob": 0, "cy": 0}
    for _ in range(4):
        fns = []
        for i in range(50):
            a, b = ring[i % 3]
            amt = 10 + i
            counts[a] -= amt
            counts[b] += amt
            fns.append(lambda a=a, b=b, amt=amt: w.pay(a, b, amt))
        rs = burst(fns)
        assert statuses(rs) == {201: 50}, statuses(rs)
    b = w.assert_conserved()
    assert b == {h: 100000 + d for h, d in counts.items()}


def test_b6_opposite_directions():
    w = World(fixture(users=[user("ada", 50000), user("bob", 50000)])).login_all()
    fns = [(lambda: w.pay("ada", "bob", 7)) if i % 2 == 0 else (lambda: w.pay("bob", "ada", 11)) for i in range(50)]
    for _ in range(3):
        assert statuses(burst(fns)) == {201: 50}
    b = w.assert_conserved()
    assert b == {"ada": 50000 + 3 * 25 * 4, "bob": 50000 - 3 * 25 * 4}


def test_b7_mixed_load_fifty_in_flight():
    rnd = random.Random(7)
    w = World().login_all()
    hs = ["ada", "bob", "cy", "dan", "op"]
    pending = [w.new_request(rnd.choice(["bob", "cy"]), "ada", 50)["request_id"] for _ in range(10)]
    for _round in range(4):
        fns = []
        for i in range(50):
            kind = i % 10
            a, b = rnd.sample(hs, 2)
            amt = rnd.randint(1, 400)
            if kind in (0, 1, 2):
                fns.append(lambda a=a, b=b, amt=amt: w.pay(a, b, amt, visibility=rnd.choice(["public", "private"])))
            elif kind == 3:
                fns.append(lambda a=a, b=b, amt=amt: w.request(a, b, amt))
            elif kind == 4 and pending:
                rid = pending.pop()
                fns.append(lambda rid=rid: w.pay_request("ada", rid))
            elif kind == 5:
                fns.append(lambda a=a, amt=amt: POST("/splits", w.t(a), {"amount": amt, "participant_handles": hs},
                                                     key=k()))
            elif kind == 6:
                c = rnd.choice(hs)
                fns.append(lambda a=a, b=b, c=c, amt=amt: POST("/settlements", w.t("op"), {"transfers": [
                    {"from_handle": a, "to_handle": b, "amount": amt},
                    {"from_handle": b, "to_handle": a, "amount": amt // 2 + 1}]}, key=k()))
            elif kind == 7:
                fns.append(lambda a=a: GET("/activity?limit=200", w.t(a)))
            elif kind == 8:
                fns.append(lambda a=a: GET("/requests?limit=200", w.t(a)))
            else:
                fns.append(lambda a=a: GET("/me", w.t(a)))
        rs = burst(fns)
        bad = [(r.request.method, r.request.url.path, r.status_code, r.text[:120]) for r in rs
               if r.status_code not in (200, 201, 409)]
        assert not bad, bad
        assert all(code_of(r) in ("insufficient_funds", "request_not_pending") for r in rs if r.status_code == 409)
        w.assert_conserved()
