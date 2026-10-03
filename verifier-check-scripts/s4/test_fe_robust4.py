"""Y2, M3. Robustness of the stage-4 inputs and a 32-item batch on a long history."""
import json
import random
import time
from fractions import Fraction

import pytest

from lib import (BASE2, GET, POST, World, batch, build_model, burst, call, check_batch, check_everything, code_of, correct,
                 fixture, fmt, inst, item, k, me_at, note, now_f, ok, refund, statement, user)
from test_y_robust import long_fixture


@pytest.fixture()
def w():
    return World().login_all()


def after_odd_request(w, p):
    assert ok(GET(f"/payments/{p['payment_id']}/revisions", w.t("ada")), 200)["revisions"]
    assert ok(statement(w, "ada"), 200)["closing_balance"] == w.bal("ada")
    e = call("GET", "/_test/export")
    assert e.status_code == 200 and call("POST", "/_test/import", raw=e.content).status_code == 204, "own export must re-import"
    w.assert_conserved()


REFUND_RAW = ['{"amount": 1e400}', '{"amount": 1' + "0" * 5000 + "}", '{"amount": 10.0000000000000000000000001}', '{"amount": 0.1e2}',
              '{"amount": -0}', '{"amount": 10, "amount": 20}', '{"amount": 10, "deep": ' + "[" * 800 + "]" * 800 + "}",
              '{"amount": 10, "big": 1e999999}', '{"amount": [10]}', '{"amount": {"value": 10}}', '{"Amount": 10}', '"10"', "null", "[]", "10", "",
              '{"amount": 10, "note": "\\ud83d"}', '{"amount": 1E1}']


@pytest.mark.parametrize("i", range(len(REFUND_RAW)))
def test_y2_odd_refund_bodies_never_5xx(w, i):
    p = ok(w.pay("ada", "bob", 100), 201)
    r = call("POST", f"/payments/{p['payment_id']}/refunds", w.t("bob"), key=k(), raw=REFUND_RAW[i])
    assert r.status_code in (201, 400, 409, 422), f"{REFUND_RAW[i][:60]}: {r.status_code} {r.text[:200]}"
    after_odd_request(w, p)


def batch_raws(p, q):
    good = json.dumps(item(p, 50))
    return [
        '{"corrections": [%s, %s]}' % (good, good),
        '{"corrections": [%s], "corrections": []}' % good,
        '{"corrections": [%s, %s]}' % (good, json.dumps(item(q, "@@")).replace('"@@"', "1e400")),
        '{"corrections": [%s]}' % json.dumps(item(p, "@@")).replace('"@@"', "5" + "0" * 4000),
        '{"corrections": [%s]}' % json.dumps(item(p, 50, expected="@@")).replace('"@@"', "1e0"),
        '{"corrections": [%s]}' % json.dumps(item(p, 50, expected="@@")).replace('"@@"', "1" + "0" * 4000),
        '{"corrections": [%s], "deep": %s}' % (good, "[" * 800 + "]" * 800),
        '{"corrections": %s}' % ("[" * 800 + "]" * 800),
        '{"corrections": [%s]}' % json.dumps(dict(item(p, 50), payment_id=["x"])),
        '{"corrections": [%s]}' % json.dumps(dict(item(p, 50), payment_id="x" * 5000)),
        '{"corrections": [%s]}' % json.dumps(dict(item(p, 50), payment_id="")),
        '{"corrections": [%s]}' % json.dumps(dict(item(p, 50), reason="\\ud83d")).replace("\\\\ud83d", "\\ud83d"),
        '{"corrections": [%s]}' % json.dumps(dict(item(p, 50), effective_at="0001-01-01T00:00:00+23:59")),
        '{"corrections": [%s]}' % json.dumps(dict(item(p, 50), effective_at="2026-01-05T10:00:00." + "9" * 400 + "Z")),
        '{"corrections": [' + ",".join(json.dumps(dict(item(p, 50), payment_id=f"p_{n}")) for n in range(2000)) + "]}",
        '{"corrections": {"length": 1, "0": %s}}' % good, "[]", '"x"', "", "{",
    ]


@pytest.mark.parametrize("i", range(20))
def test_y2_odd_batch_bodies_never_5xx(w, i):
    p, q = ok(w.pay("ada", "bob", 100), 201), ok(w.pay("ada", "cy", 100), 201)
    raw = batch_raws(p, q)[i]
    r = call("POST", "/correction-batches", w.t("op"), key=k(), raw=raw)
    assert r.status_code in (201, 400, 404, 409, 422), f"{raw[:60]}: {r.status_code} {r.text[:200]}"
    after_odd_request(w, p)


def test_y2_fixture_and_import_members_for_refunds(w):
    """A fixture may not smuggle the new members in a way that breaks the service."""
    for extra in ({"refund_of": "p_x"}, {"refund_of": 5}, {"refund_of": None}, {"correction_batch_id": "b"}, {"revisions": [{"amount": "x"}]},
                  {"settlement_id": "s_1"}, {"authorization_id": "a_1"}):
        fx = fixture(users=[user("ada", 90), user("bob", 10)], payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                                                                         "amount": 10, "note": "", "visibility": "public", **extra}], ops=[])
        r = POST("/_test/reset", body=fx)
        assert r.status_code in (204, 400, 422), f"{extra}: {r.status_code}"
        if r.status_code == 204:
            w2 = World(fx, do_reset=False).login_all()
            for ep in ("/me", "/activity", "/statement", "/payments/p_1/revisions"):
                assert GET(ep, w2.t("ada")).status_code == 200, (extra, ep)
            rr = refund(w2, "bob", "p_1", 1)
            assert rr.status_code in (201, 422), (extra, rr.status_code, rr.text[:100])
            e = call("GET", "/_test/export")
            assert call("POST", "/_test/import", raw=e.content).status_code == 204, extra
            w2.assert_conserved()


def test_m3_thirty_two_item_batches_on_five_thousand_payments():
    fx, hs, base = long_fixture()
    fx["users"].append(user("op", 0))
    fx["settlement_operator_ids"] = ["u_op"]
    assert POST("/_test/reset", body=fx).status_code == 204
    w = World(fx, do_reset=False).login_all()
    rng = random.Random(12)
    by_id = {p["id"]: p for p in fx["payments"]}
    rev, worst = {}, {}

    def timed(name, r):
        worst[name] = max(worst.get(name, 0), r.elapsed_s)
        assert r.elapsed_s <= 5, f"{name} took {r.elapsed_s:.2f}s"
        return r

    def some_items(n):
        out = []
        for pid in rng.sample(sorted(by_id), n):
            p = by_id[pid]
            out.append({"payment_id": pid, "expected_revision": rev.get(pid, 1), "amount": rng.randint(0, 800),
                        "effective_at": fmt(base + rng.randrange(0, 299 * 86400)), "reason": "load"})
        return out

    done = 0
    for i in range(12):
        items = some_items(32)
        r = timed("32-item batch", batch(w, items))
        assert r.status_code in (201, 409), r.text[:200]
        if r.status_code == 201:
            done += 1
            for x in check_batch(r.json(), items)["revisions"]:
                rev[x["payment_id"]] = x["revision"]
    assert done >= 8, f"only {done} of 12 batches were accepted"
    # a 32-member settlement corrected as a whole
    tr = [{"from_handle": hs[i % 20], "to_handle": hs[(i + 1) % 20], "amount": 10 + i} for i in range(32)]
    st = ok(timed("settlement", POST("/settlements", w.t("op"), {"transfers": tr}, key=k())), 201)
    items = [item(x, x["amount"] + 1) for x in st["payments"]]
    check_batch(ok(timed("32-member settlement batch", batch(w, items)), 201), items)
    # refunds on the long history
    for i in range(40):
        p = by_id[f"h{rng.randrange(5000):05d}"]
        r = timed("refund", refund(w, p["to_user_id"][2:], p["id"], 1))
        assert r.status_code in (201, 422), r.text[:200]
    # 50 in flight: batches, refunds, single corrections, reads
    fns = []
    for i in range(50):
        if i % 5 == 0:
            its = some_items(32)
            fns.append(lambda its=its: batch(w, its))
        elif i % 5 == 1:
            p = by_id[f"h{rng.randrange(5000):05d}"]
            fns.append(lambda p=p: refund(w, p["to_user_id"][2:], p["id"], 1))
        elif i % 5 == 2:
            p = by_id[f"h{rng.randrange(5000):05d}"]
            fns.append(lambda p=p: correct(w, p["from_user_id"][2:], p["id"], rev.get(p["id"], 1), 77, fmt(base + 100 * 86400), "burst"))
        elif i % 5 == 3:
            fns.append(lambda i=i: statement(w, hs[i % 20], limit=200))
        else:
            fns.append(lambda i=i: me_at(w, hs[i % 20], fmt(base + 200 * 86400), fmt(now_f())))
    for rnd in range(2):
        for r in burst(fns):
            timed("in a 50-way burst", r)
            assert r.status_code in (200, 201, 409, 422), r.text[:200]
    e = call("GET", "/_test/export")
    assert e.status_code == 200 and e.elapsed_s <= 10
    if BASE2:
        imp = call("POST", "/_test/import", raw=e.content, base=BASE2)
        assert imp.status_code == 204 and imp.elapsed_s <= 10, f"import took {imp.elapsed_s:.2f}s ({imp.status_code})"
    m = build_model(w)
    assert m.overdraft([f"u_{h}" for h in hs[:3]], now_f()) is None
    check_everything(w, m, rng, me_points=4, st_points=2, handles=[hs[0], hs[7]])
    total = sum(ok(me_at(w, h, fmt(base + 150 * 86400)), 200)["balance"] for h in hs + ["op"])
    assert total == 20 * 10 ** 7
    note("m3-timings", worst={kk: round(v, 3) for kk, v in worst.items()}, accepted_batches=done)
    print("\nM3 timings", {kk: round(v, 3) for kk, v in worst.items()})
