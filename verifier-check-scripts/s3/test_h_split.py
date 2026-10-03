"""H. Rounding (§9)."""
import pytest

from lib import POST, World, check_payment, err, fixture, k, ok, shares, user

SIX = ["ada", "bob", "cy", "dan", "eve", "fay"]


@pytest.fixture()
def w():
    return World(fixture(users=[user(h, 5_000_000_000) for h in SIX])).login_all()


def split(w, who, amount, handles, **kw):
    return POST("/splits", w.t(who), {"amount": amount, "participant_handles": handles, **kw}, key=k())


TABLE = [(1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]), (999, 3, [333, 333, 333]),
         (5, 5, [1, 1, 1, 1, 1]), (10 ** 9, 3, [333333334, 333333333, 333333333]), (7, 6, [2, 1, 1, 1, 1, 1]),
         (100, 1, [100]), (2, 5, [1, 1, 0, 0, 0]), (11, 6, [2, 2, 2, 2, 2, 1]), (10 ** 9, 6, None), (1, 6, None),
         (6, 6, None), (5, 6, None), (999_999_999, 2, [500_000_000, 499_999_999])]


@pytest.mark.parametrize("amount,n,expected", TABLE)
def test_h1_share_table(w, amount, n, expected):
    expected = expected or shares(amount, n)
    assert expected == shares(amount, n) and sum(expected) == amount and max(expected) - min(expected) <= 1
    handles = SIX[:n]
    s = ok(split(w, "ada", amount, handles), 201)
    assert s["shares"] == [{"handle": h, "amount": a} for h, a in zip(handles, expected)]
    assert [(q["payer_handle"], q["amount"]) for q in s["requests"]] == list(zip(handles[1:], expected[1:]))
    # caller omitted: the first given participant takes the larger share
    if n < 6:
        others = SIX[1:n + 1]
        s2 = ok(split(w, "ada", amount, others), 201)
        assert [x["amount"] for x in s2["shares"]] == expected
        assert [(q["payer_handle"], q["amount"]) for q in s2["requests"]] == list(zip(others, expected))


def test_h2_order_moves_the_extra_unit_and_zero_shares(w):
    s1 = ok(split(w, "ada", 1000, ["ada", "bob", "cy"]), 201)
    s2 = ok(split(w, "ada", 1000, ["cy", "bob", "ada"]), 201)
    s3 = ok(split(w, "ada", 1000, ["bob", "cy", "ada"]), 201)
    assert [(x["handle"], x["amount"]) for x in s1["shares"]] == [("ada", 334), ("bob", 333), ("cy", 333)]
    assert [(x["handle"], x["amount"]) for x in s2["shares"]] == [("cy", 334), ("bob", 333), ("ada", 333)]
    assert [(x["handle"], x["amount"]) for x in s3["shares"]] == [("bob", 334), ("cy", 333), ("ada", 333)]
    assert [(q["payer_handle"], q["amount"]) for q in s2["requests"]] == [("cy", 334), ("bob", 333)]
    # zero shares still create pending requests
    z = ok(split(w, "ada", 1, ["bob", "cy", "dan"]), 201)
    assert [(q["payer_handle"], q["amount"], q["status"]) for q in z["requests"]] == \
        [("bob", 1, "pending"), ("cy", 0, "pending"), ("dan", 0, "pending")]
    zero = z["requests"][1]
    assert [q for q in w.requests("cy") if q["request_id"] == zero["request_id"]][0]["amount"] == 0
    assert [q for q in w.requests("ada") if q["request_id"] == zero["request_id"]][0]["status"] == "pending"
    before = w.bals()
    # a zero request can be declined and cancelled like any other
    assert ok(POST(f"/requests/{z['requests'][2]['request_id']}/decline", w.t("dan")), 200)["status"] == "declined"
    # paying a zero share (map decision D-11): succeeds, moves nothing
    r = w.pay_request("cy", zero["request_id"])
    p = check_payment(ok(r, 201), amount=0, request_id=zero["request_id"], from_handle="cy", to_handle="ada")
    assert w.bals() == before
    assert [q for q in w.requests("cy") if q["request_id"] == zero["request_id"]][0]["status"] == "paid"
    assert [q for q in w.requests("cy") if q["request_id"] == zero["request_id"]][0]["payment_id"] == p["payment_id"]
    err(w.pay_request("cy", zero["request_id"]), 409, "request_not_pending")


def test_h2_zero_share_payable_by_empty_wallet():
    w = World(fixture(users=[user("ada", 10), user("bob", 0), user("cy", 0)]))
    z = ok(split(w, "ada", 1, ["ada", "bob", "cy"]), 201)
    assert [q["amount"] for q in z["requests"]] == [0, 0]
    ok(w.pay_request("bob", z["requests"][0]["request_id"]), 201)
    assert w.bals() == {"ada": 10, "bob": 0, "cy": 0}


def test_h3_splits_independent_and_conserved(w):
    total = w.seeded_total()
    expect = {h: 5_000_000_000 for h in SIX}
    plans = [("ada", 1000, ["ada", "bob", "cy"]), ("ada", 1000, ["ada", "bob", "cy"]), ("ada", 1000, ["ada", "bob", "cy"]),
             ("bob", 10, ["cy", "dan", "eve"]), ("cy", 7, SIX), ("dan", 1, ["eve", "fay", "ada"]),
             ("eve", 10 ** 9, ["fay", "eve", "ada", "bob", "cy", "dan"]), ("fay", 999, ["ada", "bob", "fay"])]
    for who, amount, handles in plans:
        s = ok(split(w, who, amount, handles), 201)
        exp = shares(amount, len(handles))
        # the extra unit goes to the first participants every time: no carry-over between splits
        assert [x["amount"] for x in s["shares"]] == exp
        assert sum(x["amount"] for x in s["shares"]) == amount
        for q in s["requests"]:
            p = ok(w.pay_request(q["payer_handle"], q["request_id"]), 201)
            assert p["amount"] == q["amount"] and p["to_handle"] == who
            expect[q["payer_handle"]] -= q["amount"]
            expect[who] += q["amount"]
    b = w.assert_conserved()
    assert b == expect and sum(b.values()) == total
    for h in SIX:
        assert w.requests(h, "status=pending") == []
