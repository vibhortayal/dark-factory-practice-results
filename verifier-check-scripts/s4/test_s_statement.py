"""S, N. GET /statement: window, ordering, balances, pagination, snapshots."""
import random
import time
from fractions import Fraction

import pytest

from lib import (GET, POST, US, World, build_model, burst, call, check_everything, check_payment, check_statement,
                 check_statement_shape, code_of, correct, err, fixture, fmt, full_statement, inst, k, now_f, ok, q, soft,
                 statement, user)
from test_r_time import ago, hist, sp


def ids(body):
    return [e["payment"]["payment_id"] for e in body["entries"]]


# ---------------------------------------------------------------- S. content of a statement

def test_s2_s3_s4_default_window_by_hand():
    w, (t1, t2, t3), (before, after) = hist()
    s = check_statement_shape(ok(statement(w, "ada"), 200))
    assert s["opening_balance"] == 10000, "from defaults to the opening of the wallet"
    assert s["closing_balance"] == 9540, "to defaults to now"
    assert ids(s) == ["p_1", "p_3", "p_4", "p_0"], "oldest first; ties by payment id ascending"
    assert [e["delta"] for e in s["entries"]] == [-500, 100, -50, -10]
    assert [e["balance_after"] for e in s["entries"]] == [9500, 9600, 9550, 9540]
    assert s["has_more"] is False
    feed = {p["payment_id"]: p for p in w.activity("ada")}
    for e in s["entries"]:
        assert e["payment"] == feed[e["payment"]["payment_id"]], "the entry carries the payment object"
        assert e["revision"] == 1
        assert inst(e["effective_at"]) == inst(e["recorded_at"]) == inst(e["payment"]["created_at"])
    # only the caller's own payments, whatever their visibility
    b = ok(statement(w, "bob"), 200)
    assert ids(b) == ["p_1", "p_2", "p_0"] and [e["delta"] for e in b["entries"]] == [500, -300, 10]
    assert (b["opening_balance"], b["closing_balance"]) == (2500, 2710)
    c = ok(statement(w, "cy"), 200)
    assert ids(c) == ["p_2", "p_3", "p_4"], "cy is party to the private p_2 and p_4; the public p_1 and p_0 of others stay out"
    assert [e["delta"] for e in c["entries"]] == [300, -100, 50] and (c["opening_balance"], c["closing_balance"]) == (0, 250)
    d = check_statement_shape(ok(statement(w, "dan"), 200))
    assert d["entries"] == [] and d["opening_balance"] == 0 and d["closing_balance"] == 0 and d["has_more"] is False


def test_s2_s4_half_open_window_by_hand():
    w, (t1, t2, t3), (before, after) = hist()

    def st(frm=None, to=None):
        p = {}
        if frm is not None:
            p["from"] = fmt(frm)
        if to is not None:
            p["to"] = fmt(to)
        return ok(statement(w, "ada", **p), 200)

    s = st(t1, t3)
    assert ids(s) == ["p_1"] and (s["opening_balance"], s["closing_balance"]) == (10000, 9500), "from inclusive, to exclusive"
    s = st(t1 + US, t3 + US)
    assert ids(s) == ["p_3", "p_4"] and (s["opening_balance"], s["closing_balance"]) == (9500, 9550)
    assert [e["balance_after"] for e in s["entries"]] == [9600, 9550]
    s = st(t3, t3 + US)
    assert ids(s) == ["p_3", "p_4"]
    s = st(None, t1)
    assert ids(s) == [] and (s["opening_balance"], s["closing_balance"]) == (10000, 10000)
    s = st(t3 + US, None)
    assert ids(s) == ["p_0"] and (s["opening_balance"], s["closing_balance"]) == (9550, 9540)
    s = st(t1 - 86400 * 365, now_f() + 86400 * 365)
    assert ids(s) == ["p_1", "p_3", "p_4", "p_0"] and (s["opening_balance"], s["closing_balance"]) == (10000, 9540)
    s = st(now_f() + 86400, now_f() + 86400 * 2)
    assert ids(s) == [] and (s["opening_balance"], s["closing_balance"]) == (9540, 9540), "both instants may be in the future"
    s = st(t3, t3)
    assert ids(s) == [] and s["opening_balance"] == s["closing_balance"] == 9500, "from == to is an empty window"
    # the same instants written with other offsets select the same window
    s = ok(statement(w, "ada", **{"from": fmt(t1, 330), "to": fmt(t3, -480)}), 200)
    assert ids(s) == ["p_1"]
    r = statement(w, "ada", **{"from": fmt(t3), "to": fmt(t1)})
    assert r.status_code in (200, 422), r.text[:200]
    if r.status_code == 200:
        soft(False, "statement-from-after-to-not-422")
    else:
        err(r, 422, "validation_failed")


def test_s2_ties_order_by_payment_id():
    t = ago(2)
    order = ["b", "a", "d", "c", "p_9", "p_10", "B", "_x"]
    pays = [sp(pid, "ada", "bob", i + 1, fmt(t, off)) for i, (pid, off) in enumerate(zip(order, [0, 60, -60, 0, 330, 0, 0, 0]))]
    total = sum(p["amount"] for p in pays)
    w = World(fixture(users=[user("ada", 1000 - total), user("bob", total)], payments=pays, ops=[])).login_all()
    got = ids(ok(statement(w, "ada"), 200))
    simple = [x for x in got if x in ("a", "b", "c", "d")]
    assert simple == ["a", "b", "c", "d"], f"ties must be ordered by payment id ascending: {got}"
    soft(got == sorted(order), "tie-order-not-by-code-point", got=got, want=sorted(order))
    check_everything(w, build_model(w), random.Random(3), me_points=10, st_points=6) if got == sorted(order) else None


@pytest.mark.parametrize("who", ["ada", "bob"])
def test_s5_pagination_keeps_balances_and_reports_has_more(who):
    t = ago(3)
    pays = [sp(f"p_{i:02d}", "ada" if i % 3 else "bob", "bob" if i % 3 else "ada", 10 + i, fmt(t + i * 60)) for i in range(11)]
    net = sum(p["amount"] * (1 if p["to_user_id"] == "u_ada" else -1) for p in pays)
    w = World(fixture(users=[user("ada", 5000 + net), user("bob", 5000 - net)], payments=pays, ops=[])).login_all()
    full = check_statement_shape(ok(statement(w, who, limit=200), 200))
    n = len(full["entries"])
    assert n == 11
    for limit in (1, 2, 3, 5, 10, 11, 12, 200):
        seen = []
        for offset in range(0, n + 3):
            pg = check_statement_shape(ok(statement(w, who, limit=limit, offset=offset), 200))
            assert pg["opening_balance"] == full["opening_balance"] and pg["closing_balance"] == full["closing_balance"], \
                f"limit={limit} offset={offset}: the balances describe the full window"
            assert pg["entries"] == full["entries"][offset:offset + limit], f"limit={limit} offset={offset}"
            assert pg["has_more"] is (offset + limit < n), f"limit={limit} offset={offset}: has_more {pg['has_more']}"
            seen.append(pg)
    far = ok(statement(w, who, offset=10 ** 6), 200)
    assert far["entries"] == [] and far["has_more"] is False and far["opening_balance"] == full["opening_balance"]
    assert len(ok(statement(w, who), 200)["entries"]) == 11, "limit defaults to 50"
    # a window inside the history, paged
    a, b = t + 120, t + 480
    win = ok(statement(w, who, **{"from": fmt(a), "to": fmt(b)}), 200)
    assert ids(win) == [f"p_{i:02d}" for i in range(2, 8)]
    for offset in range(0, 8):
        pg = ok(statement(w, who, **{"from": fmt(a), "to": fmt(b), "limit": 2, "offset": offset}), 200)
        assert pg["entries"] == win["entries"][offset:offset + 2]
        assert (pg["opening_balance"], pg["closing_balance"]) == (win["opening_balance"], win["closing_balance"])
        assert pg["has_more"] is (offset + 2 < 6)


def test_s1_limit_offset_rules_are_those_of_get_requests():
    w, _, _ = hist()
    tok = w.t("ada")
    for bad in ("limit=0", "limit=201", "limit=-1", "limit=1e1", "limit=4.0", "limit=%2B4", "limit=abc", "limit=", "offset=-1",
                "offset=1e1", "offset=abc", "offset=", "offset=1.0", "limit=" + "9" * 4400, "offset=%2B1"):
        err(GET(f"/statement?{bad}", tok), 422, "validation_failed", bad)
    for good, n in (("limit=1", 1), ("limit=200", 4), ("limit=0050", 4), ("offset=000", 4), ("offset=3", 1),
                    ("limit=2&offset=1&unknown=1", 2), ("offset=" + "9" * 30, 0)):
        assert len(ok(GET(f"/statement?{good}", tok), 200)["entries"]) == n, good
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        r = call(method, "/statement", tok, kind="any")
        assert 400 <= r.status_code < 500, (method, r.status_code)
    # request-list filters are just unknown parameters here
    assert len(ok(GET("/statement?direction=incoming&status=paid", tok), 200)["entries"]) == 4


def test_s6_only_money_movements_and_linked_payments_once():
    w = World().login_all()
    a = w.new_auth("ada", "bob", 2000, note="deposit", visibility="private")
    assert ok(statement(w, "ada"), 200)["entries"] == [], "an authorisation is not a payment"
    c1 = ok(w.capture("bob", a["authorization_id"], body={"amount": 700, "final": False}), 201)
    c2 = ok(w.capture("bob", a["authorization_id"], body={"amount": 300}), 201)
    a2 = w.new_auth("ada", "cy", 100)
    ok(w.void("ada", a2["authorization_id"]), 200)
    st = ok(POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 11, "note": "s"},
                                                           {"from_handle": "bob", "to_handle": "cy", "amount": 3, "visibility": "private"}]}, key=k()), 201)
    rq = w.new_request("bob", "ada", 40)
    pr = ok(w.pay_request("ada", rq["request_id"], body={"visibility": "private"}), 201)
    ok(POST("/splits", w.t("ada"), {"amount": 90, "participant_handles": ["ada", "bob", "cy"]}, key=k()), 201)
    s = check_statement_shape(ok(statement(w, "ada"), 200))
    assert ids(s) == [c1["payment_id"], c2["payment_id"], st["payments"][0]["payment_id"], pr["payment_id"]]
    assert [e["delta"] for e in s["entries"]] == [-700, -300, -11, -40]
    assert s["entries"][0]["payment"] == c1 and s["entries"][1]["payment"] == c2
    assert s["entries"][0]["payment"]["authorization_id"] == a["authorization_id"]
    assert s["entries"][2]["payment"]["settlement_id"] == st["settlement_id"]
    assert s["entries"][3]["payment"]["request_id"] == rq["request_id"]
    assert (s["opening_balance"], s["closing_balance"]) == (10000, 10000 - 1051)
    b = ok(statement(w, "bob"), 200)
    assert ids(b) == [c1["payment_id"], c2["payment_id"], st["payments"][0]["payment_id"], st["payments"][1]["payment_id"], pr["payment_id"]]
    assert [e["delta"] for e in b["entries"]] == [700, 300, 11, -3, 40]
    op = ok(statement(w, "op"), 200)
    assert op["entries"] == [], "an operator's statement has only the operator's own payments"
    check_everything(w, build_model(w), random.Random(4), me_points=25, st_points=8)


# ---------------------------------------------------------------- N. snapshots

def busy_world():
    w = World().login_all()
    pays = [ok(w.pay("ada", "bob", 10 + i, note=f"n{i}"), 201) for i in range(7)]
    return w, pays


def test_n1_n2_snapshot_pages_the_frozen_result_after_everything_changed():
    w, pays = busy_world()
    first = check_statement_shape(ok(statement(w, "ada", limit=3), 200))
    tok = first["snapshot"]
    soft(len(tok) <= 200, "snapshot-token-longer-than-200", length=len(tok))
    assert first["has_more"] is True and len(first["entries"]) == 3
    whole = full_statement(w, "ada", page=200)
    bob_first = ok(statement(w, "bob", limit=200), 200)
    assert whole["closing_balance"] == 10000 - sum(10 + i for i in range(7))
    # everything changes: payments, corrections that change amounts and move payments in time, holds, captures
    ok(w.pay("ada", "cy", 500), 201)
    ok(w.pay("bob", "ada", 77), 201)
    j = ok(correct(w, "ada", pays[0]["payment_id"], 1, 1, pays[0]["created_at"], "less"), 201)
    ok(correct(w, "ada", pays[1]["payment_id"], 1, 0, fmt(inst(pays[1]["created_at"]) - 3600), "reversed, earlier"), 201)
    ok(correct(w, "ada", pays[2]["payment_id"], 1, 400, fmt(now_f() - 1), "more, later"), 201)
    a = w.new_auth("ada", "bob", 300)
    ok(w.capture("bob", a["authorization_id"], body={"amount": 100}), 201)
    a2 = w.new_auth("ada", "cy", 50)
    ok(w.void("ada", a2["authorization_id"]), 200)
    now_view = full_statement(w, "ada")
    assert now_view["entries"] != whole["entries"] and now_view["closing_balance"] != whole["closing_balance"]
    assert now_view["snapshot"] != tok
    for limit in (1, 2, 3, 7, 50, 200):
        for offset in range(0, 10):
            pg = ok(statement(w, "ada", snapshot=tok, limit=limit, offset=offset), 200)
            assert pg["entries"] == whole["entries"][offset:offset + limit], f"snapshot page limit={limit} offset={offset} changed"
            assert (pg["opening_balance"], pg["closing_balance"]) == (whole["opening_balance"], whole["closing_balance"])
            assert pg["has_more"] is (offset + limit < 7)
            soft(pg.get("snapshot") == tok, "snapshot-page-does-not-repeat-the-token", got=str(pg.get("snapshot"))[:40])
    again = ok(statement(w, "ada", snapshot=tok), 200)
    assert again["entries"] == whole["entries"], "limit defaults to 50 on a snapshot page"
    # bob's snapshot of the same moment is frozen too, and tokens are per caller
    assert ok(statement(w, "bob", snapshot=bob_first["snapshot"], limit=200), 200)["entries"] == bob_first["entries"]
    err(statement(w, "bob", snapshot=tok), 404, "not_found", "another user's token")
    err(statement(w, "ada", snapshot=bob_first["snapshot"]), 404, "not_found", "another user's token")
    err(GET(f"/statement?snapshot={tok}"), 401, "unauthenticated")
    # unknown parameters are still ignored next to a snapshot
    assert ok(GET(f"/statement?{q(snapshot=tok)}&colour=blue&limit=2", w.t("ada")), 200)["entries"] == whole["entries"][:2]
    # tokens last until reset: still good after many more reads
    for _ in range(30):
        statement(w, "ada", limit=1)
    assert ok(statement(w, "ada", snapshot=tok, limit=200), 200)["entries"] == whole["entries"]


def test_n1_snapshot_freezes_the_default_to_and_a_future_to():
    w, pays = busy_world()
    plain = ok(statement(w, "ada", limit=200), 200)                                     # to defaults to now
    future = ok(statement(w, "ada", limit=200, to=fmt(now_f() + 86400)), 200)           # to supplied, in the future
    known = ok(statement(w, "ada", limit=200, known_at=fmt(now_f() + 86400)), 200)      # knowledge "in the future"
    time.sleep(0.05)
    late = ok(w.pay("ada", "bob", 999), 201)
    ok(correct(w, "ada", pays[3]["payment_id"], 1, 0, pays[3]["created_at"], "gone"), 201)
    for name, snap in (("default to", plain), ("future to", future), ("future known_at", known)):
        pg = ok(statement(w, "ada", snapshot=snap["snapshot"], limit=200), 200)
        assert pg["entries"] == snap["entries"], f"{name}: the snapshot changed after a payment and a correction"
        assert pg["closing_balance"] == snap["closing_balance"] and pg["opening_balance"] == snap["opening_balance"]
        assert late["payment_id"] not in ids(pg)
    fresh = ok(statement(w, "ada", limit=200), 200)
    assert late["payment_id"] in ids(fresh) and fresh["closing_balance"] == plain["closing_balance"] - 999 + 13


def test_n3_snapshot_accepts_only_limit_and_offset():
    w, pays = busy_world()
    tok = ok(statement(w, "ada", limit=2), 200)["snapshot"]
    now = fmt(now_f())
    for extra in ({"from": now}, {"to": now}, {"known_at": now}, {"from": now, "to": now, "known_at": now},
                  {"from": "garbage"}, {"to": ""}):
        err(statement(w, "ada", snapshot=tok, **extra), 422, "validation_failed", str(extra))
    r = statement(w, "ada", snapshot="no-such-token", **{"from": now})
    err(r, (422, 404), ("validation_failed", "not_found"))
    soft(r.status_code == 422, "unknown-token-with-forbidden-parameter-not-422")
    for bad in ("limit=0", "limit=201", "offset=-1", "limit=abc"):
        err(GET(f"/statement?{q(snapshot=tok)}&{bad}", w.t("ada")), 422, "validation_failed", bad)
    r = statement(w, "ada", snapshot=tok, as_of=now)
    assert r.status_code in (200, 422)                                    # as_of is not a statement parameter
    for unknown in ("no-such-token", tok + "x", "x" * 5000, "ünï😀", "../../etc", "null", "%00", tok + "&"):
        r = GET(f"/statement?{q(snapshot=unknown)}", w.t("ada"))
        err(r, 404, "not_found", f"unknown token {unknown[:20]!r}")
    r = GET("/statement?snapshot=", w.t("ada"))
    err(r, (404, 422), ("not_found", "validation_failed"))
    soft(r.status_code == 404, "empty-snapshot-not-404", status=r.status_code)
    # a token from before the reset
    w2 = World().login_all()
    err(statement(w2, "ada", snapshot=tok), 404, "not_found", "a token from before reset")
    tok2 = ok(statement(w2, "ada"), 200)["snapshot"]
    assert ok(statement(w2, "ada", snapshot=tok2), 200)["entries"] == []


def test_n2_snapshots_stay_frozen_during_concurrent_writes():
    w, pays = busy_world()
    snaps = {h: ok(statement(w, h, limit=200), 200) for h in ("ada", "bob")}
    part = ok(statement(w, "ada", limit=2, offset=1), 200)
    fns = []
    for i in range(10):
        fns.append(lambda i=i: w.pay("ada", "bob", 1 + i))
        fns.append(lambda i=i: correct(w, "ada", pays[i % 7]["payment_id"], 1, 5 + i, pays[i % 7]["created_at"], "race"))
    for i in range(30):
        h = "ada" if i % 2 else "bob"
        fns.append(lambda h=h: statement(w, h, snapshot=snaps[h]["snapshot"], limit=200))
    rs = burst(fns)
    for r, i in zip(rs[20:], range(30)):
        h = "ada" if i % 2 else "bob"
        j = ok(r, 200)
        assert j["entries"] == snaps[h]["entries"] and j["closing_balance"] == snaps[h]["closing_balance"], \
            "a snapshot read during concurrent payments and corrections differs from the first read"
    assert ok(statement(w, "ada", snapshot=part["snapshot"], limit=2, offset=1), 200)["entries"] == part["entries"]
    codes = sorted({(r.status_code, code_of(r)) for r in rs[:20]}, key=str)
    assert all(c[0] in (201, 409) for c in codes), codes
    check_everything(w, build_model(w), random.Random(6), me_points=25, st_points=8)
    w.assert_conserved()


def test_n1_many_first_reads_each_get_a_working_token():
    w, pays = busy_world()
    toks = []
    for i in range(120):
        j = ok(statement(w, "ada" if i % 2 else "bob", limit=1 + i % 5, offset=i % 3), 200)
        toks.append(("ada" if i % 2 else "bob", j["snapshot"]))
    ok(w.pay("ada", "bob", 3), 201)
    base = {h: None for h in ("ada", "bob")}
    for h, t in toks:
        j = ok(statement(w, h, snapshot=t, limit=200), 200)
        assert len(j["entries"]) == 7
        base[h] = base[h] or j["entries"]
        assert j["entries"] == base[h]
