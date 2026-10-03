"""X2, L4, T8. Robustness of the new inputs, load at the stated limits on a long history, and the carried UI note."""
import json
import random
import time
from fractions import Fraction

import pytest

from lib import (BASE, BASE2, GET, POST, US, World, build_model, burst, call, check_everything, check_statement, code_of,
                 correct, err, fixture, fmt, full_statement, inst, k, me_at, note, now_f, ok, q, soft, statement, user)
from test_r_time import BAD, OPEN, ago, sp


@pytest.fixture()
def w():
    return World().login_all()


RAW_BODIES = [
    '{"expected_revision": 1e400, "amount": 60, "effective_at": "%s", "reason": "x"}',
    '{"expected_revision": 1, "amount": 1e400, "effective_at": "%s", "reason": "x"}',
    '{"expected_revision": 1, "amount": 6' + "0" * 5000 + ', "effective_at": "%s", "reason": "x"}',
    '{"expected_revision": 1' + "0" * 5000 + ', "amount": 60, "effective_at": "%s", "reason": "x"}',
    '{"expected_revision": 1, "amount": 60.0000000000000000000000001, "effective_at": "%s", "reason": "x"}',
    '{"expected_revision": 1, "amount": 0.6e2, "effective_at": "%s", "reason": "x"}',
    '{"expected_revision": 1, "amount": -0, "effective_at": "%s", "reason": "x"}',
    '{"expected_revision": 1, "amount": 60, "effective_at": "%s", "reason": "x", "reason": "y"}',
    '{"expected_revision": 1, "amount": 60, "effective_at": "%s", "reason": "x", "deep": ' + "[" * 800 + "]" * 800 + "}",
    '{"expected_revision": 1, "amount": 60, "effective_at": "%s", "reason": "x", "big": 1e999999}',
    '{"expected_revision": 1, "amount": 60, "effective_at": "%s", "reason": "\\ud83d"}',
    '{"expected_revision": 1, "amount": 60, "effective_at": "%s", "reason": "nul \\u0000 inside"}',
    '{"expected_revision": [], "amount": {}, "effective_at": [], "reason": {}}%s',
    '{"expected_revision": 1, "amount": 60, "effective_at": ["%s"], "reason": "x"}',
    '"%s"', "null%s", "[]%s", "123%s", "",
]


@pytest.mark.parametrize("i", range(len(RAW_BODIES)))
def test_x2_odd_correction_bodies_never_5xx(w, i):
    p = ok(w.pay("ada", "bob", 100), 201)
    raw = RAW_BODIES[i]
    raw = raw % p["created_at"] if "%s" in raw and i not in (12, 14, 15, 16, 17) else raw.replace("%s", "")
    r = call("POST", f"/payments/{p['payment_id']}/corrections", w.t("ada"), key=k(), raw=raw)
    assert r.status_code in (201, 400, 409, 422), f"{raw[:80]}: {r.status_code} {r.text[:200]}"
    assert ok(GET(f"/payments/{p['payment_id']}/revisions", w.t("ada")), 200)["revisions"]
    assert ok(statement(w, "ada"), 200)["closing_balance"] == w.bal("ada")
    e = call("GET", "/_test/export")
    assert e.status_code == 200 and call("POST", "/_test/import", raw=e.content).status_code == 204, "own export must re-import"
    w.assert_conserved()


def test_x2_effective_at_grammar_on_corrections(w):
    ps = [ok(w.pay("ada", "bob", 100), 201) for _ in range(3)]
    wrong = []
    for value in BAD:
        r = correct(w, "ada", ps[0]["payment_id"], 1, 60, value)
        if r.status_code != 422 or code_of(r) != "validation_failed":
            wrong.append((value, r.status_code, code_of(r)))
    assert not wrong, f"effective_at: expected 422 validation_failed for {wrong}"
    rev = 1
    for value in OPEN:
        r = correct(w, "ada", ps[1]["payment_id"], rev, 60, value)
        assert r.status_code in (201, 409, 422), f"effective_at={value[:40]}: {r.status_code} {r.text[:200]}"
        if r.status_code == 201:
            rev += 1
            for h in ("ada", "bob"):
                assert statement(w, h).status_code == 200 and me_at(w, h, value).status_code in (200, 422)
            e = call("GET", "/_test/export")
            assert call("POST", "/_test/import", raw=e.content).status_code == 204, f"export after effective_at={value[:40]}"
    w.assert_conserved()
    check_everything(w, build_model(w), random.Random(41), me_points=20, st_points=6)


def test_x2_long_and_repeated_query_values_never_5xx(w):
    ok(w.pay("ada", "bob", 100), 201)
    tok = w.t("ada")
    for path in ("/me?as_of=" + "9" * 6000, "/me?known_at=" + "2026-01-05T10:00:00." + "1" * 6000 + "Z",
                 "/statement?from=" + "x" * 6000, "/statement?to=%00&from=%ff", "/statement?snapshot=" + "a" * 6000,
                 "/me?as_of", "/me?as_of&known_at", "/statement?from&to", "/statement?snapshot",
                 "/me?as_of=2026-01-05T10:00:00Z&as_of=garbage", "/statement?" + "&".join(f"p{i}=1" for i in range(300)),
                 "/me?as_of=%E2%98%83", "/statement?limit=1&limit=2", "/me?AS_OF=garbage"):
        r = GET(path, tok)
        assert r.status_code in (200, 404, 422), f"{path[:60]}: {r.status_code} {r.text[:200]}"


# ---------------------------------------------------------------- L4: a long history at the stated limits

def long_fixture(n_pay=5000, n_users=20, seed=9):
    rng = random.Random(seed)
    hs = [f"u{i:02d}" for i in range(n_users)]
    bal = {h: 10 ** 7 for h in hs}
    base = Fraction(int(time.time())) - 300 * 86400
    pays = []
    for i in range(n_pay):
        frm, to = rng.sample(hs, 2)
        amt = rng.randint(1, 500)
        bal[frm] -= amt
        bal[to] += amt
        pays.append(sp(f"h{i:05d}", frm, to, amt, fmt(base + i * 5000 + rng.randrange(0, 4000)), rng.choice(["public", "private"])))
    return fixture(users=[user(h, bal[h]) for h in hs], payments=pays, ops=[]), hs, base


def test_l4_five_thousand_payments_and_three_hundred_revisions_within_the_limits():
    fx, hs, base = long_fixture()
    t0 = time.perf_counter()
    r = POST("/_test/reset", body=fx)
    reset_s = time.perf_counter() - t0
    assert r.status_code == 204, r.text[:300]
    assert reset_s <= 10, f"reset with 5,000 seeded payments took {reset_s:.2f}s"
    w = World(fx, do_reset=False).login_all()
    rng = random.Random(10)
    worst = {}

    def timed(name, r):
        worst[name] = max(worst.get(name, 0), r.elapsed_s)
        assert r.elapsed_s <= 5, f"{name} took {r.elapsed_s:.2f}s"
        return r

    for h in hs[:5]:
        ok(timed("me", GET("/me", w.t(h))), 200)
        ok(timed("me as_of", me_at(w, h, fmt(base + 150 * 86400), fmt(now_f()))), 200)
        first = ok(timed("statement", statement(w, h, limit=200)), 200)
        ok(timed("statement page", statement(w, h, snapshot=first["snapshot"], limit=200, offset=400)), 200)
        ok(timed("statement window", statement(w, h, **{"from": fmt(base + 100 * 86400), "to": fmt(base + 200 * 86400), "limit": 200})), 200)
        ok(timed("activity", GET("/activity?limit=200", w.t(h))), 200)
    done = {201: 0}
    codes = {}
    by_id = {p["id"]: p for p in fx["payments"]}
    rev = {}
    for i in range(300):
        p = by_id[f"h{rng.randrange(5000):05d}"]
        sender = p["from_user_id"][2:]
        eff = base + rng.randrange(0, 299 * 86400)
        r = timed("correction", correct(w, sender, p["id"], rev.get(p["id"], 1), rng.randint(0, 800), fmt(eff), f"load {i}"))
        codes[(r.status_code, code_of(r))] = codes.get((r.status_code, code_of(r)), 0) + 1
        assert r.status_code in (201, 409), r.text[:200]
        if r.status_code == 201:
            rev[p["id"]] = r.json()["revision"]
    assert codes.get((201, None), 0) >= 200, codes
    # 50 in flight on the long history
    snap = ok(statement(w, hs[0], limit=50), 200)
    fns = []
    for i in range(50):
        h = hs[i % 20]
        if i % 5 == 0:
            fns.append(lambda h=h: statement(w, h, limit=200))
        elif i % 5 == 1:
            fns.append(lambda h=h: me_at(w, h, fmt(base + 200 * 86400), fmt(now_f())))
        elif i % 5 == 2:
            p = by_id[f"h{rng.randrange(5000):05d}"]
            fns.append(lambda p=p: correct(w, p["from_user_id"][2:], p["id"], rev.get(p["id"], 1), 77,
                                           fmt(base + 100 * 86400), "burst"))
        elif i % 5 == 3:
            fns.append(lambda h=h, i=i: w.pay(h, hs[(i + 7) % 20], 3))
        else:
            fns.append(lambda: statement(w, hs[0], snapshot=snap["snapshot"], limit=50))
    for rnd in range(3):
        rs = burst(fns)
        for r in rs:
            timed("in a 50-way burst", r)
            assert r.status_code in (200, 201, 409), r.text[:200]
    e = call("GET", "/_test/export")
    assert e.status_code == 200 and e.elapsed_s <= 10, f"export took {e.elapsed_s:.2f}s"
    if BASE2:
        imp = call("POST", "/_test/import", raw=e.content, base=BASE2)
        assert imp.status_code == 204 and imp.elapsed_s <= 10, f"import took {imp.elapsed_s:.2f}s ({imp.status_code})"
        wb = World(fx, base=BASE2, do_reset=False)
        wb.tok = dict(w.tok)
        assert full_statement(wb, hs[3])["entries"] == full_statement(w, hs[3])["entries"]
    # the long history agrees with the model for a few users, and conservation holds in history
    m = build_model(w)
    assert m.overdraft([f"u_{h}" for h in hs[:3]], now_f()) is None
    check_everything(w, m, rng, me_points=4, st_points=2, handles=[hs[0], hs[7]])
    for T in (base + 50 * 86400, base + 250 * 86400, now_f()):
        total = sum(ok(timed("me as_of", me_at(w, h, fmt(T))), 200)["balance"] for h in hs)
        assert total == 20 * 10 ** 7, f"sum of balances as of {fmt(T)} is {total}"
    note("l4-timings", reset_s=round(reset_s, 2), export_s=round(e.elapsed_s, 2), worst={kk: round(v, 3) for kk, v in worst.items()},
         correction_outcomes={str(kk): v for kk, v in codes.items()})
    print("\nL4 timings", round(reset_s, 2), {kk: round(v, 3) for kk, v in worst.items()}, codes)


# ---------------------------------------------------------------- T8 carried from stage 2 (note, not a requirement)

def test_t8_forms_are_there_while_the_first_read_is_pending(ui):
    import re
    World()
    u = ui("wide").login("ada")
    held = []
    u.page.route(re.compile(r".*/me(\?.*)?$"), lambda route: held.append(route) if route.request.resource_type != "document" else route.continue_())
    u.page.goto("/", wait_until="domcontentloaded")
    u.page.wait_for_timeout(1200)
    present = all(u.t(t).count() > 0 for t in ("pay-handle", "pay-amount", "pay-submit", "request-submit", "authorize-submit"))
    soft(present, "T8-forms-absent-while-first-read-pending")
    for route in held:
        route.continue_()
    u.page.wait_for_timeout(500)
    from playwright.sync_api import expect
    expect(u.t("wallet-balance")).to_have_text("100.00 EUR")
    expect(u.t("pay-submit")).to_be_visible()
    assert not u.errors, u.errors
