"""Concurrency / load checks: 50 requests in flight. Run against a live service
(ideally started with --cpus 2 --memory 2g). Prints a summary; exits non-zero on failure."""
import collections
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(__file__))
from client import call, fixture, key, user, reset, login, balance  # noqa: E402

N = 50
lat = []
FAILS = []


def timed(*a, **kw):
    t = time.time()
    r = call(*a, **kw)
    lat.append(time.time() - t)
    return r


def burst(fn, n=N):
    barrier = threading.Barrier(n)

    def run(i):
        barrier.wait()
        return fn(i)
    with ThreadPoolExecutor(n) as ex:
        return list(ex.map(run, range(n)))


def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name, info)
    if not cond:
        FAILS.append(name)


def tally(rs):
    return dict(collections.Counter(r[0] for r in rs))


def main():
    # 1. overspend race, one wallet, 50 clients
    reset(fixture(users=[user("ada", 1000), user("bob", 0)]))
    toks = [login("ada") for _ in range(N)]
    rs = burst(lambda i: timed("POST", "/payments", {"to_handle": "bob", "amount": 1000}, toks[i], key()))
    check("B2 overspend one wallet", tally(rs) == {201: 1, N - 1 + 0: 0} or tally(rs) == {201: 1, 409: N - 1}, tally(rs))
    check("B1 sum after overspend", balance(toks[0]) == 0 and balance(login("bob")) == 1000)

    # 2. drain in parts
    reset(fixture(users=[user("ada", 1000), user("bob", 0)]))
    toks = [login("ada") for _ in range(N)]
    rs = burst(lambda i: timed("POST", "/payments", {"to_handle": "bob", "amount": 30}, toks[i], key()))
    check("B2 drain in parts", tally(rs) == {201: 33, 409: 17}, tally(rs))
    check("B1 drain conservation", balance(toks[0]) == 10 and balance(login("bob")) == 990)

    # 3. ring of three wallets
    reset(fixture(users=[user("ada", 100), user("bob", 100), user("cy", 100)]))
    toks = {h: [login(h) for _ in range(N)] for h in ("ada", "bob", "cy")}
    ring = {"ada": "bob", "bob": "cy", "cy": "ada"}
    hs = ["ada", "bob", "cy"]
    rs = burst(lambda i: timed("POST", "/payments", {"to_handle": ring[hs[i % 3]], "amount": 100},
                               toks[hs[i % 3]][i], key()))
    total = sum(balance(toks[h][0]) for h in hs)
    check("B1/B2 ring conservation", total == 300 and all(r[0] < 500 for r in rs) and all(balance(toks[h][0]) >= 0 for h in hs), tally(rs))

    # 4. identical concurrent requests, same key
    reset(fixture())
    ada = login("ada")
    k = key()
    body = {"to_handle": "bob", "amount": 100}
    rs = burst(lambda i: timed("POST", "/payments", body, ada, k))
    bodies = {repr(r[1]) for r in rs}
    check("F8 same key concurrent", tally(rs) == {201: 1, 200: N - 1} and len(bodies) == 1, tally(rs))
    check("F8 effect once", balance(ada) == 9900)
    for path, b in (("/requests", {"payer_handle": "ada", "amount": 5}), ("/splits", {"amount": 10, "participant_handles": ["bob", "cy"]})):
        bob = login("bob")
        k = key()
        rs = burst(lambda i: timed("POST", path, b, bob, k))
        check("F8 " + path, tally(rs) == {201: 1, 200: N - 1} and len({repr(r[1]) for r in rs}) == 1, tally(rs))
    check("F8 requests created once", len(call("GET", "/requests?limit=200", token=bob)[1]["requests"]) == 2)

    # 5. a request moves money at most once
    reset(fixture())
    ada, bob = login("ada"), login("bob")
    rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 1000}, bob, key())[1]["request_id"]
    rs = burst(lambda i: timed("POST", f"/requests/{rid}/pay", {}, ada, key()))
    check("B3 pay vs pay", tally(rs) == {201: 1, 409: N - 1}, tally(rs))
    check("B3 moved once", balance(ada) == 9000 and balance(bob) == 3500)
    rid = call("POST", "/requests", {"payer_handle": "ada", "amount": 1000}, bob, key())[1]["request_id"]

    before = balance(ada)

    def mixed(i):
        if i % 3 == 0:
            return timed("POST", f"/requests/{rid}/pay", {}, ada, key())
        if i % 3 == 1:
            return timed("POST", f"/requests/{rid}/decline", None, ada)
        return timed("POST", f"/requests/{rid}/cancel", None, bob)
    rs = burst(mixed)
    st = call("GET", "/requests?limit=200", token=ada)[1]["requests"]
    final = [r for r in st if r["request_id"] == rid][0]
    moved = before - balance(ada)
    check("B3 pay vs decline/cancel", moved in (0, 1000) and (moved == 1000) == (final["status"] == "paid")
          and all(r[0] < 500 for r in rs), (final["status"], moved, tally(rs)))

    # 6. mixed load, 50 in flight, conservation, no 5xx, latency
    users = [user(f"u{i}", 500) for i in range(20)]
    reset(fixture(users=users, settlement_operator_ids=["u_u0"]))
    toks = [login(f"u{i}") for i in range(20)]
    rnd = random.Random(7)
    plan = []
    for i in range(1500):
        a, b = rnd.sample(range(20), 2)
        kind = rnd.choice(["pay", "pay", "ask", "split", "feed", "reqs", "me", "settle", "same"])
        plan.append((kind, a, b, rnd.randint(1, 300)))
    shared = key()

    def do(item):
        kind, a, b, amt = item
        t, h = toks[a], f"u{b}"
        if kind == "pay":
            return timed("POST", "/payments", {"to_handle": h, "amount": amt}, t, key())
        if kind == "ask":
            return timed("POST", "/requests", {"payer_handle": h, "amount": amt}, t, key())
        if kind == "split":
            return timed("POST", "/splits", {"amount": amt, "participant_handles": [f"u{a}", h]}, t, key())
        if kind == "feed":
            return timed("GET", "/activity?limit=20", token=t)
        if kind == "reqs":
            return timed("GET", "/requests?limit=20", token=t)
        if kind == "me":
            return timed("GET", "/me", token=t)
        if kind == "same":
            return timed("POST", "/payments", {"to_handle": "u1", "amount": 1}, toks[0], shared)
        return timed("POST", "/settlements", {"transfers": [
            {"from_handle": f"u{a}", "to_handle": h, "amount": amt}]}, toks[0], key())
    t0 = time.time()
    with ThreadPoolExecutor(N) as ex:
        rs = list(ex.map(do, plan))
    el = time.time() - t0
    check("A13 mixed load no 5xx", all(r[0] < 500 for r in rs), tally(rs))
    bals = [balance(t) for t in toks]
    check("B1/B2 mixed conservation", sum(bals) == 20 * 500 and min(bals) >= 0, (sum(bals), min(bals)))
    # fully paying requests keeps conservation
    pend = []
    for t in toks:
        pend += [(t, r) for r in call("GET", "/requests?direction=incoming&status=pending&limit=200", token=t)[1]["requests"]]

    def payit(item):
        t, r = item
        return timed("POST", f"/requests/{r['request_id']}/pay", {}, t, key())
    with ThreadPoolExecutor(N) as ex:
        rs = list(ex.map(payit, pend))
    check("B1 after paying requests", all(r[0] in (201, 409) for r in rs) and sum(balance(t) for t in toks) == 10000,
          tally(rs))
    print(f"mixed: {len(plan)} requests in {el:.1f}s")

    # 7. 50 concurrent logins, reset with many users, export/import timing
    rs = burst(lambda i: timed("POST", "/auth/login", {"email": f"u{i % 20}@example.com", "password": "correct horse"}))
    check("A5 50 concurrent logins", tally(rs) == {200: N}, f"max {max(lat):.2f}s")
    big = fixture(users=[user(f"x{i}", 100) for i in range(500)])
    t = time.time()
    s, _, _ = call("POST", "/_test/reset", big, timeout=10)
    d_reset = time.time() - t
    check("A5 reset 500 users < 10s", s == 204 and d_reset < 10, f"{d_reset:.2f}s")
    t = time.time()
    s, snap, _ = call("GET", "/_test/export", timeout=10)
    d_exp = time.time() - t
    t = time.time()
    s2, _, _ = call("POST", "/_test/import", snap, timeout=10)
    d_imp = time.time() - t
    check("A5 export/import < 10s", s == 200 and s2 == 204 and max(d_exp, d_imp) < 10, f"export {d_exp:.2f}s import {d_imp:.2f}s")
    print(f"max latency of timed requests (excl. above): {max(lat) if lat else 0:.2f}s")
    mx = max(lat) if lat else 0
    check("A5 max latency < 5s", mx < 5, f"{mx:.2f}s")
    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL LOAD CHECKS PASSED")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
