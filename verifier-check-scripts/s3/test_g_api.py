"""G. API behaviour (§8)."""
import random
import time

import pytest

from lib import (GET, POST, World, me_core, assert_newest_first, burst, call, check_payment, check_request, code_of, err,
                 fixture, k, ok, soft, statuses, user)


@pytest.fixture()
def w():
    return World().login_all()


def test_g1_me(w):
    assert me_core(w.me("ada")) == {"user_id": "u_ada", "display_name": "Ada", "handle": "ada", "balance": 10000,
                                    "currency": "EUR", "minor_units": 2}
    assert w.wallet("ada")["available"] == 10000 and w.wallet("ada")["held"] == 0
    assert w.me("cy")["balance"] == 0


def test_g2_payment_fields_defaults_and_effect(w):
    r = POST("/payments", w.t("ada"), {"to_handle": "bob", "amount": 1500, "note": "dinner", "visibility": "public"},
             key=k())
    p = check_payment(ok(r, 201), from_user_id="u_ada", from_handle="ada", to_user_id="u_bob", to_handle="bob",
                      amount=1500, currency="EUR", note="dinner", visibility="public", request_id=None,
                      settlement_id=None)
    assert w.bal("ada") == 8500 and w.bal("bob") == 4000
    d = check_payment(ok(POST("/payments", w.t("ada"), {"to_handle": "bob", "amount": 1}, key=k()), 201),
                      note="", visibility="public", amount=1)
    assert d["payment_id"] != p["payment_id"]
    for h in ("ada", "bob", "cy"):
        feed = {x["payment_id"]: x for x in w.activity(h)}
        assert feed[p["payment_id"]] == p and feed[d["payment_id"]] == d
    w.assert_conserved()


def test_g3_payment_errors(w):
    ok(w.pay("dan", "ada", 500), 201)  # exactly the balance
    assert w.bal("dan") == 0
    err(w.pay("dan", "ada", 1), 409, "insufficient_funds")
    err(w.pay("cy", "ada", 1), 409, "insufficient_funds")
    err(w.pay("bob", "ada", 2501), 409, "insufficient_funds")
    ok(w.pay("bob", "ada", 2500), 201)
    err(w.pay("ada", "ada", 10), 422, "self_payment")
    err(w.pay("ada", "nobody", 10), 404, "not_found")
    for h in ["ADA", "Bob", " bob", "bob ", "@bob", "", "bob\n", "b" * 21, "b" * 500, "bob/..", "u_bob", "bób"]:
        r = w.pay("ada", h, 10)
        err(r, (404, 422), ("not_found", "validation_failed"), repr(h))
        soft(r.status_code == 404, "odd-handle-422", handle=h)
    b = w.assert_conserved()
    assert b["ada"] == 13000 and b["bob"] == 0 and b["dan"] == 0


NOTES = [
    "  leading and trailing  ", "tab\there\nnew line\r\nwindows", "😀👍🏽 zażółć gęślą jaźń", "é vs é",
    "<script>alert(1)</script> & \"quotes\" 'single' \\ back\\slash", "%20 + ? # & = %", "שלום مرحبا",
    "👨‍👩‍👧‍👦 family ‍ zwj", "ＦＵＬＬ　ｗｉｄｔｈ ﬁ ligature", " nbsp ", "null", "0", "{\"json\": true}",
    " line sep ", "a\u0000b" if False else "ctrl \u0001\u001f", "𝒳 astral \U0001F9D1‍\U0001F680",
]


@pytest.mark.parametrize("note", NOTES)
def test_g4_note_verbatim(w, note):
    p = ok(w.pay("ada", "bob", 1, note=note), 201)
    assert p["note"] == note and p["note"].encode("utf-8") == note.encode("utf-8")
    assert [x for x in w.activity("bob") if x["payment_id"] == p["payment_id"]][0]["note"] == note
    # the same note sent as \\u escapes
    import json as _json
    raw = _json.dumps({"to_handle": "bob", "amount": 1, "note": note}, ensure_ascii=True)
    p2 = ok(call("POST", "/payments", w.t("ada"), key=k(), raw=raw), 201)
    assert p2["note"] == note
    q = w.new_request("bob", "ada", 2, note=note)
    assert q["note"] == note
    assert [x for x in w.requests("ada") if x["request_id"] == q["request_id"]][0]["note"] == note
    s = ok(POST("/splits", w.t("ada"), {"amount": 2, "participant_handles": ["bob"], "note": note}, key=k()), 201)
    assert s["note"] == note
    st = ok(POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1,
                                                            "note": note}]}, key=k()), 201)
    assert st["payments"][0]["note"] == note


def test_g5_request_fields_and_no_balance_check(w):
    r = POST("/requests", w.t("bob"), {"payer_handle": "ada", "amount": 1200, "note": "taxi"}, key=k())
    q = check_request(ok(r, 201), requester_id="u_bob", requester_handle="bob", payer_id="u_ada", payer_handle="ada",
                      amount=1200, currency="EUR", note="taxi", status="pending", payment_id=None)
    d = check_request(ok(POST("/requests", w.t("bob"), {"payer_handle": "cy", "amount": 10 ** 9}, key=k()), 201),
                      note="", amount=10 ** 9, payer_handle="cy", status="pending")
    assert d["request_id"] != q["request_id"]
    assert w.bals() == {"ada": 10000, "bob": 2500, "cy": 0, "dan": 500, "op": 1000}
    assert {x["request_id"] for x in w.requests("bob")} == {q["request_id"], d["request_id"]}
    assert [x["request_id"] for x in w.requests("ada")] == [q["request_id"]]
    assert w.requests("ada")[0] == q
    assert w.activity("ada") == [] and w.activity("bob") == []


def test_g6_request_errors(w):
    err(w.request("ada", "ada", 5), 422, "self_request")
    err(w.request("ada", "nobody", 5), 404, "not_found")
    r = w.request("ada", "BOB", 5)
    err(r, (404, 422), ("not_found", "validation_failed"))
    for h in w.handles():
        assert w.requests(h) == []


def test_g7_pay_request(w):
    q = w.new_request("bob", "ada", 1200, note="taxi 🚕")
    rid = q["request_id"]
    p = check_payment(ok(w.pay_request("ada", rid, body={}), 201), from_user_id="u_ada", from_handle="ada",
                      to_user_id="u_bob", to_handle="bob", amount=1200, currency="EUR", visibility="public",
                      request_id=rid, settlement_id=None)
    soft(p["note"] == "taxi 🚕", "pay-note-not-request-note", note=p["note"])
    assert w.bal("ada") == 8800 and w.bal("bob") == 3700
    for h in ("ada", "bob"):
        got = [x for x in w.requests(h) if x["request_id"] == rid][0]
        check_request(got, status="paid", payment_id=p["payment_id"], amount=1200, note="taxi 🚕",
                      created_at=q["created_at"])
    for h in ("ada", "bob", "cy"):
        assert [x for x in w.activity(h) if x["payment_id"] == p["payment_id"]] == [p]
    # private choice by the payer
    q2 = w.new_request("bob", "ada", 5)
    p2 = check_payment(ok(w.pay_request("ada", q2["request_id"], body={"visibility": "private"}), 201),
                       visibility="private", request_id=q2["request_id"])
    assert p2["payment_id"] in [x["payment_id"] for x in w.activity("bob")]
    assert p2["payment_id"] not in [x["payment_id"] for x in w.activity("cy")]
    assert p2["payment_id"] not in [x["payment_id"] for x in w.activity("op")]
    q3 = w.new_request("bob", "ada", 5)
    assert ok(w.pay_request("ada", q3["request_id"], body={"visibility": "public"}), 201)["visibility"] == "public"
    w.assert_conserved()


def test_g8_pay_errors(w):
    err(w.pay_request("ada", "rq_does_not_exist"), 404, "not_found")
    q = w.new_request("bob", "ada", 100)
    rid = q["request_id"]
    err(w.pay_request("bob", rid), 403, "forbidden")  # the requester is not the payer
    r = w.pay_request("cy", rid)
    err(r, (403, 404), ("forbidden", "not_found"))
    soft(r.status_code == 403, "third-party-pay-404")
    assert [x["status"] for x in w.requests("ada")] == ["pending"]
    # short: stays pending, nothing moves, same key works once funded
    q2 = w.new_request("ada", "cy", 300)
    key = k()
    err(w.pay_request("cy", q2["request_id"], key=key), 409, "insufficient_funds")
    assert [x for x in w.requests("cy")][0]["status"] == "pending"
    assert w.bal("cy") == 0 and w.bal("ada") == 10000 and w.activity("cy") == []
    ok(w.pay("bob", "cy", 299), 201)
    err(w.pay_request("cy", q2["request_id"], key=key), 409, "insufficient_funds")
    ok(w.pay("bob", "cy", 1), 201)
    p = ok(w.pay_request("cy", q2["request_id"], key=key), 201)
    assert p["amount"] == 300 and w.bal("cy") == 0 and w.bal("ada") == 10300
    # not pending
    err(w.pay_request("cy", q2["request_id"]), 409, "request_not_pending")
    ok(POST(f"/requests/{rid}/decline", w.t("ada")), 200)
    err(w.pay_request("ada", rid), 409, "request_not_pending")
    q3 = w.new_request("bob", "ada", 100)
    ok(POST(f"/requests/{q3['request_id']}/cancel", w.t("bob")), 200)
    err(w.pay_request("ada", q3["request_id"]), 409, "request_not_pending")
    # wrong caller on a non-pending request is still not allowed to learn more than 403/404
    r = w.pay_request("bob", q3["request_id"])
    err(r, (403, 404, 409))
    soft(r.status_code == 403, "non-payer-on-closed-request-not-403", status=r.status_code)
    w.assert_conserved()


def test_g9_decline(w):
    q = w.new_request("bob", "ada", 100, note="n")
    rid = q["request_id"]
    err(POST(f"/requests/{rid}/decline", w.t("bob")), 403, "forbidden")
    r = POST(f"/requests/{rid}/decline", w.t("cy"))
    err(r, (403, 404), ("forbidden", "not_found"))
    err(POST("/requests/rq_none/decline", w.t("ada")), 404, "not_found")
    d = check_request(ok(POST(f"/requests/{rid}/decline", w.t("ada")), 200), status="declined", payment_id=None,
                      request_id=rid, amount=100, note="n", requester_handle="bob", payer_handle="ada",
                      created_at=q["created_at"])
    assert ok(POST(f"/requests/{rid}/decline", w.t("ada")), 200) == d
    assert ok(POST(f"/requests/{rid}/decline", w.t("ada")), 200)["status"] == "declined"
    err(POST(f"/requests/{rid}/cancel", w.t("bob")), 409, "request_not_pending")
    assert w.requests("bob")[0] == d
    # paid -> 409, cancelled -> 409
    q2 = w.new_request("bob", "ada", 1)
    ok(w.pay_request("ada", q2["request_id"]), 201)
    err(POST(f"/requests/{q2['request_id']}/decline", w.t("ada")), 409, "request_not_pending")
    q3 = w.new_request("bob", "ada", 1)
    ok(POST(f"/requests/{q3['request_id']}/cancel", w.t("bob")), 200)
    err(POST(f"/requests/{q3['request_id']}/decline", w.t("ada")), 409, "request_not_pending")
    assert w.bal("ada") == 9999


def test_g10_cancel(w):
    q = w.new_request("bob", "ada", 100, note="n")
    rid = q["request_id"]
    err(POST(f"/requests/{rid}/cancel", w.t("ada")), 403, "forbidden")
    r = POST(f"/requests/{rid}/cancel", w.t("cy"))
    err(r, (403, 404), ("forbidden", "not_found"))
    err(POST("/requests/rq_none/cancel", w.t("bob")), 404, "not_found")
    c = check_request(ok(POST(f"/requests/{rid}/cancel", w.t("bob")), 200), status="cancelled", payment_id=None,
                      request_id=rid, amount=100, created_at=q["created_at"])
    assert ok(POST(f"/requests/{rid}/cancel", w.t("bob")), 200) == c
    err(POST(f"/requests/{rid}/decline", w.t("ada")), 409, "request_not_pending")
    assert w.requests("ada")[0] == c
    q2 = w.new_request("bob", "ada", 1)
    ok(w.pay_request("ada", q2["request_id"]), 201)
    err(POST(f"/requests/{q2['request_id']}/cancel", w.t("bob")), 409, "request_not_pending")
    q3 = w.new_request("bob", "ada", 1)
    ok(POST(f"/requests/{q3['request_id']}/decline", w.t("ada")), 200)
    err(POST(f"/requests/{q3['request_id']}/cancel", w.t("bob")), 409, "request_not_pending")


def test_g11_lifecycle_race(w):
    outcomes = set()
    paid_total = 0
    for rnd in range(5):
        q = w.new_request("bob", "ada", 100)
        rid = q["request_id"]
        fns = ([lambda: w.pay_request("ada", rid) for _ in range(20)]
               + [lambda: POST(f"/requests/{rid}/decline", w.t("ada")) for _ in range(15)]
               + [lambda: POST(f"/requests/{rid}/cancel", w.t("bob")) for _ in range(15)])
        # interleave so that no kind is always first in line
        order = list(range(50))
        random.Random(rnd).shuffle(order)
        rs_all = burst([fns[i] for i in order])
        rs = [None] * 50
        for pos, i in enumerate(order):
            rs[i] = rs_all[pos]
        pays, decs, cans = rs[:20], rs[20:35], rs[35:]
        final = [x for x in w.requests("ada") if x["request_id"] == rid][0]
        outcomes.add(final["status"])
        assert final["status"] in ("paid", "declined", "cancelled")
        if final["status"] == "paid":
            paid_total += 100
            assert statuses(pays) == {201: 1, 409: 19}, statuses(pays)
            assert all(code_of(r) == "request_not_pending" for r in pays if r.status_code == 409)
            assert statuses(decs) == {409: 15} and statuses(cans) == {409: 15}
            assert final["payment_id"] == [r for r in pays if r.status_code == 201][0].json()["payment_id"]
        elif final["status"] == "declined":
            assert statuses(pays) == {409: 20} and statuses(cans) == {409: 15}
            assert statuses(decs) == {200: 15}
            assert final["payment_id"] is None
        else:
            assert statuses(pays) == {409: 20} and statuses(decs) == {409: 15}
            assert statuses(cans) == {200: 15}
            assert final["payment_id"] is None
        b = w.assert_conserved()
        assert b["ada"] == 10000 - paid_total and b["bob"] == 2500 + paid_total
        assert len([p for p in w.activity("ada") if p["request_id"] == rid]) == (1 if final["status"] == "paid" else 0)


def test_g12_requests_listing_filters(w):
    a = w.new_request("bob", "ada", 1, note="in-pending")       # incoming for ada
    b = w.new_request("bob", "ada", 2, note="in-paid")
    c = w.new_request("bob", "ada", 3, note="in-declined")
    d = w.new_request("bob", "ada", 4, note="in-cancelled")
    e = w.new_request("ada", "cy", 5, note="out-pending")       # outgoing for ada
    f = w.new_request("ada", "bob", 6, note="out-paid")
    g = w.new_request("ada", "dan", 7, note="out-declined")
    h = w.new_request("ada", "dan", 8, note="out-cancelled")
    x = w.new_request("bob", "cy", 9, note="not ada's")
    ok(w.pay_request("ada", b["request_id"]), 201)
    ok(POST(f"/requests/{c['request_id']}/decline", w.t("ada")), 200)
    ok(POST(f"/requests/{d['request_id']}/cancel", w.t("bob")), 200)
    ok(w.pay_request("bob", f["request_id"]), 201)
    ok(POST(f"/requests/{g['request_id']}/decline", w.t("dan")), 200)
    ok(POST(f"/requests/{h['request_id']}/cancel", w.t("ada")), 200)
    n = lambda q: {r["note"] for r in w.requests("ada", q)}  # noqa: E731
    every = {"in-pending", "in-paid", "in-declined", "in-cancelled", "out-pending", "out-paid", "out-declined",
             "out-cancelled"}
    assert n("limit=200") == every
    assert n("direction=incoming") == {s for s in every if s.startswith("in-")}
    assert n("direction=outgoing") == {s for s in every if s.startswith("out-")}
    for st in ("pending", "paid", "declined", "cancelled"):
        assert n(f"status={st}") == {f"in-{st}", f"out-{st}"}
        assert n(f"status={st}&direction=incoming") == {f"in-{st}"}
        assert n(f"direction=outgoing&status={st}") == {f"out-{st}"}
        for r in w.requests("ada", f"status={st}"):
            assert r["status"] == st
    assert {r["note"] for r in w.requests("cy")} == {"out-pending", "not ada's"}
    assert {r["note"] for r in w.requests("cy", "direction=outgoing")} == set()
    assert w.requests("op") == []
    j = ok(GET("/requests", w.t("ada")), 200)
    assert set(j) >= {"requests", "has_more"} and j["has_more"] is False and len(j["requests"]) == 8
    for r in j["requests"]:
        check_request(r)
        assert "ada" in (r["requester_handle"], r["payer_handle"])
    assert x["request_id"] not in {r["request_id"] for r in j["requests"]}


def test_g12_requests_order_and_pagination(w):
    made = []
    for i in range(5):
        made.append(w.new_request("bob", "ada", i + 1)["request_id"])
        time.sleep(1.1)
    full = [r["request_id"] for r in w.requests("ada")]
    assert full == made[::-1], "not newest first"
    assert_newest_first(w.requests("ada"))

    def page(q):
        j = ok(GET(f"/requests?{q}", w.t("ada")), 200)
        return [r["request_id"] for r in j["requests"]], j["has_more"]

    assert page("limit=2") == (full[:2], True)
    assert page("limit=2&offset=2") == (full[2:4], True)
    assert page("limit=2&offset=4") == (full[4:], False)
    assert page("limit=5") == (full, False)
    assert page("limit=4") == (full[:4], True)
    assert page("limit=1&offset=4") == (full[4:], False)
    assert page("limit=1&offset=3") == (full[3:4], True)
    assert page("offset=5") == ([], False)
    assert page("offset=50") == ([], False)
    assert page("limit=200&offset=1") == (full[1:], False)
    # filters apply before paging
    ok(POST(f"/requests/{made[4]}/decline", w.t("ada")), 200)
    assert page("status=pending&limit=2") == (full[1:3], True)
    assert page("status=pending&limit=2&offset=2") == (full[3:], False)
    assert page("status=declined&limit=1") == ([made[4]], False)
    assert page("direction=outgoing&limit=1") == ([], False)
    # bob sees the same five, as outgoing
    assert [r["request_id"] for r in w.requests("bob", "direction=outgoing")] == [made[4]] + full[1:]


def test_g12_g15_default_limit_is_50():
    w = World(fixture(users=[user("ada", 100000), user("bob", 0), user("cy", 0)])).login_all()
    for i in range(55):
        ok(w.pay("ada", "bob", 1), 201)
        w.new_request("bob", "ada", 1)
    for ep, key in (("/activity", "payments"), ("/requests", "requests")):
        j = ok(GET(ep, w.t("ada")), 200)
        assert len(j[key]) == 50 and j["has_more"] is True, f"{ep}: {len(j[key])} {j['has_more']}"
        j2 = ok(GET(f"{ep}?offset=50", w.t("ada")), 200)
        assert len(j2[key]) == 5 and j2["has_more"] is False
        j3 = ok(GET(f"{ep}?limit=200", w.t("ada")), 200)
        assert len(j3[key]) == 55 and j3["has_more"] is False
        idk = "payment_id" if key == "payments" else "request_id"
        ids = [x[idk] for x in j[key]] + [x[idk] for x in j2[key]]
        assert len(set(ids)) == 55 and set(ids) == {x[idk] for x in j3[key]}
        j4 = ok(GET(f"{ep}?limit=55", w.t("ada")), 200)
        assert j4["has_more"] is False
        j5 = ok(GET(f"{ep}?limit=54", w.t("ada")), 200)
        assert j5["has_more"] is True
        assert_newest_first(j3[key])


def test_g13_split_shape(w):
    r = POST("/splits", w.t("ada"), {"amount": 3000, "participant_handles": ["ada", "bob", "cy"], "note": "dinner"},
             key=k())
    s = ok(r, 201)
    assert set(s) >= {"split_id", "amount", "currency", "note", "shares", "requests", "created_at"}
    soft(set(s) == {"split_id", "amount", "currency", "note", "shares", "requests", "created_at"},
         "split-extra-keys", keys=sorted(s))
    assert isinstance(s["split_id"], str) and 1 <= len(s["split_id"]) <= 64
    assert (s["amount"], s["currency"], s["note"]) == (3000, "EUR", "dinner")
    assert s["shares"] == [{"handle": "ada", "amount": 1000}, {"handle": "bob", "amount": 1000},
                           {"handle": "cy", "amount": 1000}]
    assert [q["payer_handle"] for q in s["requests"]] == ["bob", "cy"]
    for q in s["requests"]:
        check_request(q, requester_id="u_ada", requester_handle="ada", amount=1000, currency="EUR",
                      status="pending", payment_id=None)
        soft(q["note"] == "dinner", "split-request-note-differs", note=q["note"])
    assert len({q["request_id"] for q in s["requests"]}) == 2
    # no money moved, nothing in any feed, requests visible to their two parties only
    assert w.bals() == {"ada": 10000, "bob": 2500, "cy": 0, "dan": 500, "op": 1000}
    for h in w.handles():
        assert w.activity(h) == []
    assert {q["request_id"] for q in w.requests("ada")} == {q["request_id"] for q in s["requests"]}
    assert w.requests("bob") == [s["requests"][0]] and w.requests("cy") == [s["requests"][1]]
    assert w.requests("dan") == [] and w.requests("op") == []
    assert w.requests("ada", "direction=outgoing&status=pending")[0]["requester_handle"] == "ada"


def test_g13_split_caller_positions(w):
    def split(handles, amount=10, who="ada"):
        return ok(POST("/splits", w.t(who), {"amount": amount, "participant_handles": handles}, key=k()), 201)

    s = split(["bob", "ada", "cy"])  # caller in the middle
    assert s["shares"] == [{"handle": "bob", "amount": 4}, {"handle": "ada", "amount": 3}, {"handle": "cy", "amount": 3}]
    assert [(q["payer_handle"], q["amount"]) for q in s["requests"]] == [("bob", 4), ("cy", 3)]
    assert s["note"] == ""
    s = split(["bob", "cy", "ada"])  # caller last
    assert [(q["payer_handle"], q["amount"]) for q in s["requests"]] == [("bob", 4), ("cy", 3)]
    s = split(["ada", "cy", "bob"])  # caller first takes the extra unit
    assert [x["amount"] for x in s["shares"]] == [4, 3, 3]
    assert [(q["payer_handle"], q["amount"]) for q in s["requests"]] == [("cy", 3), ("bob", 3)]
    s = split(["bob", "cy", "dan"])  # caller omitted: three shares, three requests
    assert s["shares"] == [{"handle": "bob", "amount": 4}, {"handle": "cy", "amount": 3}, {"handle": "dan", "amount": 3}]
    assert [(q["payer_handle"], q["amount"]) for q in s["requests"]] == [("bob", 4), ("cy", 3), ("dan", 3)]
    assert all(q["requester_handle"] == "ada" for q in s["requests"])
    s = split(["bob"])  # one other participant
    assert s["shares"] == [{"handle": "bob", "amount": 10}] and s["requests"][0]["amount"] == 10
    s = split(["ada"])  # only the caller
    assert s["shares"] == [{"handle": "ada", "amount": 10}] and s["requests"] == []
    s = split(["cy"], who="cy", amount=10 ** 9)  # zero-balance caller, maximum amount
    assert s["shares"] == [{"handle": "cy", "amount": 10 ** 9}] and s["requests"] == []
    s = split(["ada", "bob", "cy", "dan", "op"], who="cy", amount=10 ** 9)
    assert sum(x["amount"] for x in s["shares"]) == 10 ** 9 and len(s["requests"]) == 4
    assert w.bals() == {"ada": 10000, "bob": 2500, "cy": 0, "dan": 500, "op": 1000}


def test_g14_split_errors(w):
    def split(body):
        return POST("/splits", w.t("ada"), body, key=k())

    err(split({"amount": 10, "participant_handles": []}), 422, "validation_failed")
    err(split({"amount": 10, "participant_handles": ["bob", "bob"]}), 422, "validation_failed")
    err(split({"amount": 10, "participant_handles": ["ada", "ada"]}), 422, "validation_failed")
    err(split({"amount": 10, "participant_handles": ["bob", "cy", "ada", "cy"]}), 422, "validation_failed")
    err(split({"amount": 10, "participant_handles": ["bob", "ghost"]}), 404, "not_found")
    err(split({"amount": 10, "participant_handles": ["ghost"]}), 404, "not_found")
    r = split({"amount": 10, "participant_handles": ["ghost", "ghost"]})
    err(r, (404, 422), ("not_found", "validation_failed"))
    soft(r.status_code == 422, "split-duplicate-unknown-404")
    r = split({"amount": 10, "participant_handles": ["bob", "BOB"]})
    err(r, (404, 422), ("not_found", "validation_failed"))
    r = split({"amount": 10, "participant_handles": [f"ghost_{i}" for i in range(1000)]})
    err(r, (404, 422), ("not_found", "validation_failed"))
    for h in w.handles():
        assert w.requests(h) == [], "a failed split left requests behind"


def test_g15_activity_contract(w):
    pub = ok(w.pay("ada", "bob", 10, note="pub"), 201)
    prv = ok(w.pay("ada", "bob", 11, note="prv", visibility="private"), 201)
    prv2 = ok(w.pay("op", "dan", 12, note="prv2", visibility="private"), 201)
    w.new_request("bob", "ada", 5)
    ok(POST("/splits", w.t("ada"), {"amount": 9, "participant_handles": ["bob", "cy"]}, key=k()), 201)
    err(w.pay("cy", "ada", 5), 409, "insufficient_funds")
    ids = lambda h: {p["payment_id"] for p in w.activity(h)}  # noqa: E731
    assert ids("ada") == {pub["payment_id"], prv["payment_id"]}
    assert ids("bob") == {pub["payment_id"], prv["payment_id"]}
    assert ids("cy") == {pub["payment_id"]}
    assert ids("dan") == {pub["payment_id"], prv2["payment_id"]}
    assert ids("op") == {pub["payment_id"], prv2["payment_id"]}
    j = ok(GET("/activity", w.t("ada")), 200)
    assert set(j) >= {"payments", "has_more"} and j["has_more"] is False
    for p in j["payments"]:
        check_payment(p)
    # one value on the payment, identical for sender, receiver and everyone who sees it
    a = {p["payment_id"]: p for p in w.activity("ada")}
    b = {p["payment_id"]: p for p in w.activity("bob")}
    assert a == b and a[prv["payment_id"]]["visibility"] == "private" and a[pub["payment_id"]]["visibility"] == "public"
    assert {p["payment_id"]: p for p in w.activity("cy")}[pub["payment_id"]] == pub
    # request-only parameters are unknown here and ignored
    assert ids("ada") == {p["payment_id"] for p in w.activity("ada", "direction=incoming&status=paid")}
    # a newly signed-up user sees the public feed only
    s = w.signup("late@example.com")
    assert {p["payment_id"] for p in ok(GET("/activity", s["token"]), 200)["payments"]} == {pub["payment_id"]}


def test_g15_activity_order_and_pagination(w):
    made = []
    for i in range(5):
        vis = "private" if i % 2 else "public"
        made.append(ok(w.pay("ada", "bob", i + 1, visibility=vis), 201)["payment_id"])
        time.sleep(1.1)
    full = [p["payment_id"] for p in w.activity("bob")]
    assert full == made[::-1], "not newest first"

    def page(h, q):
        j = ok(GET(f"/activity?{q}", w.t(h)), 200)
        return [p["payment_id"] for p in j["payments"]], j["has_more"]

    assert page("bob", "limit=2") == (full[:2], True)
    assert page("bob", "limit=2&offset=2") == (full[2:4], True)
    assert page("bob", "limit=2&offset=4") == (full[4:], False)
    assert page("bob", "limit=5") == (full, False)
    assert page("bob", "offset=5") == ([], False)
    assert page("bob", "limit=1&offset=3") == (full[3:4], True)
    # a third party pages over the public ones only (made[0], made[2], made[4])
    pub = [made[4], made[2], made[0]]
    assert page("cy", "limit=200") == (pub, False)
    assert page("cy", "limit=2") == (pub[:2], True)
    assert page("cy", "limit=2&offset=2") == (pub[2:], False)
    assert page("cy", "limit=3") == (pub, False)
    assert page("cy", "limit=1&offset=2") == (pub[2:], False)


def test_g17_third_party_cannot_see_or_touch_requests(w):
    q = w.new_request("bob", "ada", 50)
    rid = q["request_id"]
    for h in ("cy", "dan", "op"):
        for flt in ("", "direction=incoming", "direction=outgoing", "status=pending", "limit=200&offset=0",
                    "status=pending&direction=incoming"):
            assert w.requests(h, flt) == [], f"{h} sees a foreign request with {flt!r}"
        for action in ("pay", "decline", "cancel"):
            r = POST(f"/requests/{rid}/{action}", w.t(h), {}, key=k() if action == "pay" else None)
            err(r, (403, 404), ("forbidden", "not_found"), f"{h} {action}")
            soft(r.status_code == 403, "third-party-action-404", action=action)
    assert w.requests("ada")[0] == q and q["status"] == "pending"
    assert w.bals() == {"ada": 10000, "bob": 2500, "cy": 0, "dan": 500, "op": 1000}
