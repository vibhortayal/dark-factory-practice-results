"""Concurrency at the stated limit of 50 in-flight requests (§2), §1 invariant, §5 'no 5xx under concurrent load'."""
from vlib import *

N = 50
USERS = [user(f"u_c{i}") for i in range(5)]


def cfix(ntables=3, reservations=None, hours_=None):
    tb = [table(f"t_{i}", 4) for i in range(ntables)]
    return fixture(users=USERS, restaurants=[restaurant(tables=tb, oh=hours_)], reservations=reservations)


def toks():
    return [tok(f"u_c{i}") for i in range(5)]


def fast(rs, limit=5.0):
    slow = [(r.desc[:60], round(r.elapsed, 2)) for r in rs if r.elapsed > limit]
    assert not slow, f"requests over {limit}s: {slow}"
    assert all(r.status < 500 for r in rs), tally(rs)


@check("H12a", "§1 'Two confirmed reservations must never occupy the same table at overlapping times, including during concurrent requests'",
       "50 clients race for one table and slot: exactly one 201, 49 x 409 table_unavailable")
def _():
    reset(cfix())
    T = toks()
    rs = burst([lambda i=i: book(T[i % 5], tid="t_0") for i in range(N)])
    fast(rs)
    assert tally(rs) == {(201, None): 1, (409, "table_unavailable"): N - 1}, tally(rs)
    seen = assert_no_overlap(T)
    assert len(seen) == 1
    assert slots("r_anker", FUT, 2)[f"{FUT}T19:00"]["available_table_ids"] == ["t_1", "t_2"]


@check("H12b", "§1 invariant under concurrency", "50 clients race for mutually overlapping slots on one table: exactly one wins")
def _():
    reset(cfix())
    T = toks()
    hm = ["18:00", "18:30", "19:00"]   # with 90 minutes these three all overlap each other
    rs = burst([lambda i=i: book(T[i % 5], tid="t_0", local=f"{FUT}T{hm[i % 3]}") for i in range(N)])
    fast(rs)
    assert tally(rs) == {(201, None): 1, (409, "table_unavailable"): N - 1}, tally(rs)
    assert len(assert_no_overlap(T)) == 1


@check("H12c", "§1 invariant under concurrency / §8 reference 'unique across all reservations'",
       "50 clients over five start times of one table: successes never overlap; 50 distinct tables all succeed with distinct references")
def _():
    reset(cfix(ntables=51))
    T = toks()
    hm = ["18:00", "18:30", "19:00", "19:30", "20:00"]
    rs = burst([lambda i=i: book(T[i % 5], tid="t_50", local=f"{FUT}T{hm[i % 5]}") for i in range(N)])
    fast(rs)
    ok = [r for r in rs if r.status == 201]
    assert 1 <= len(ok) <= 2 and all(r.status in (201, 409) for r in rs), tally(rs)
    assert len(assert_no_overlap(T)) == len(ok)
    rs = burst([lambda i=i: book(T[i % 5], tid=f"t_{i}", local=f"{FUT2}T19:00") for i in range(N)])
    fast(rs)
    assert tally(rs) == {(201, None): N}, tally(rs)
    assert len({r.json["reference"] for r in rs}) == N and len({r.json["reservation_id"] for r in rs}) == N
    assert len(assert_no_overlap(T)) == len(ok) + N


@check("F9", "§7 'For concurrent identical requests with an unused key, exactly one returns 201. The others return 200 with the same body. The operation takes effect only once'",
       "50 identical POST /reservations with one key")
def _():
    reset(cfix())
    t = tok("u_c0")
    k = newkey()
    rs = burst([lambda: book(t, tid="t_0", key=k) for _ in range(N)])
    fast(rs)
    assert tally(rs) == {(201, None): 1, (200, None): N - 1}, tally(rs)
    first = rs[0].json
    assert all(r.json == first for r in rs)
    assert len(my_list(t)) == 1


@check("E12", "§6 'Email already registered -> 409 email_taken' under concurrency / §2 per-request 5 s", "50 concurrent signups with one email: one 201, 49 x 409")
def _():
    reset(cfix())
    b = {"email": "race@example.com", "password": "race password", "display_name": "Race"}
    rs = burst([lambda: call("POST", "/auth/signup", json_body=b) for _ in range(N)])
    fast(rs)
    assert tally(rs) == {(201, None): 1, (409, "email_taken"): N - 1}, tally(rs)
    expect(call("POST", "/auth/login", json_body={"email": b["email"], "password": b["password"]}), 200)


@check("A7a", "§2 'Concurrent requests: up to 50 in flight' / 'Per-request timeout 5 s'", "50 concurrent logins, 50 concurrent distinct signups, 50 concurrent availability reads, each under 5 s")
def _():
    reset(cfix())
    rs = burst([lambda i=i: call("POST", "/auth/login", json_body={"email": f"u_c{i % 5}@example.com", "password": f"pw-u_c{i % 5}-long"})
                for i in range(N)])
    fast(rs)
    assert tally(rs) == {(200, None): N}, tally(rs)
    for r in rs[:5]:
        expect(call("GET", "/reservations", token=r.json["token"]), 200)
    rs = burst([lambda i=i: call("POST", "/auth/signup", json_body={"email": f"n{i}@example.com", "password": "new password", "display_name": f"N{i}"})
                for i in range(N)])
    fast(rs)
    assert tally(rs) == {(201, None): N}, tally(rs)
    assert len({r.json["user_id"] for r in rs}) == N
    rs = burst([lambda: avail("r_anker", FUT, 2) for _ in range(N)])
    fast(rs)
    assert tally(rs) == {(200, None): N} and all(r.json == rs[0].json for r in rs)


@check("I15a", "§8 PATCH 'releases the old slot and reserves the new one together' / §1 invariant under concurrency",
       "50 bookings PATCH onto one free table at once: exactly one 200, 49 x 409")
def _():
    sv = [seed(f"res_{i}", f"RACE{i:02d}", f"u_c{i % 5}", "r_anker", f"t_{i}", f"{FUT}T19:00") for i in range(N)]
    reset(cfix(ntables=51, reservations=sv))
    T = toks()
    rs = burst([lambda i=i: patch(T[i % 5], f"RACE{i:02d}", {"table_id": "t_50"}) for i in range(N)])
    fast(rs)
    assert tally(rs) == {(200, None): 1, (409, "table_unavailable"): N - 1}, tally(rs)
    seen = assert_no_overlap(T)
    assert len(seen) == N and sum(1 for r in seen.values() if r["table_id"] == "t_50") == 1
    a = slots("r_anker", FUT, 2)[f"{FUT}T19:00"]["available_table_ids"]
    assert len(a) == 1 and a[0] != "t_50", a


@check("I15b", "§8 cancel 'Frees the table immediately' / §1 invariant under concurrency", "one cancel racing 49 creates for the same table and slot: never two confirmed")
def _():
    reset(cfix())
    T = toks()
    held = book_ok(T[0], tid="t_0")
    fns = [lambda: cancel(T[0], held["reference"])] + [lambda i=i: book(T[i % 5], tid="t_0", local=f"{FUT}T{('19:00', '19:30')[i % 2]}") for i in range(N - 1)]
    rs = burst(fns)
    fast(rs)
    expect(rs[0], 200)
    assert all(r.status in (201, 409) for r in rs[1:]) and sum(1 for r in rs[1:] if r.status == 201) <= 1, tally(rs[1:])
    seen = assert_no_overlap(T)
    assert sum(1 for r in seen.values() if r["status"] == "confirmed") == sum(1 for r in rs[1:] if r.status == 201)


@check("L16a", "§7 concurrent identical requests / §11 replays", "50 identical batches with one key: one 201, 49 x 200 with the same body")
def _():
    sv = [seed("res_a", "RACE00", "u_c0", "r_anker", "t_0", f"{FUT}T19:00"), seed("res_b", "RACE01", "u_c0", "r_anker", "t_1", f"{FUT}T19:00")]
    reset(cfix(reservations=sv))
    t = tok("u_c0")
    k = newkey()
    mv = [{"reference": "RACE00", "table_id": "t_1"}, {"reference": "RACE01", "table_id": "t_0"}]
    rs = burst([lambda: moves(t, mv, key=k) for _ in range(N)])
    fast(rs)
    assert tally(rs) == {(201, None): 1, (200, None): N - 1}, tally(rs)
    assert all(r.json == rs[0].json for r in rs)
    assert expect(get_res(t, "RACE00"), 200).json["table_id"] == "t_1"
    assert_no_overlap([t])


@check("L16b", "§11 'An overlap among resulting bookings or with an unlisted booking gives 409 table_unavailable' / §1 invariant under concurrency",
       "50 conflicting batches onto one free table: one 201; then 25 batches against 25 creates: one success in total")
def _():
    sv = [seed(f"res_{i}", f"RACE{i:02d}", f"u_c{i % 5}", "r_anker", f"t_{i}", f"{FUT}T19:00") for i in range(N)]
    reset(cfix(ntables=52, reservations=sv))
    T = toks()
    rs = burst([lambda i=i: moves(T[i % 5], [{"reference": f"RACE{i:02d}", "table_id": "t_50"}]) for i in range(N)])
    fast(rs)
    assert tally(rs) == {(201, None): 1, (409, "table_unavailable"): N - 1}, tally(rs)
    assert len(assert_no_overlap(T)) == N
    fns = []
    for i in range(N):
        if i % 2:
            fns.append(lambda i=i: moves(T[i % 5], [{"reference": f"RACE{i:02d}", "table_id": "t_51"}]))
        else:
            fns.append(lambda i=i: book(T[i % 5], tid="t_51", local=f"{FUT}T{('18:30', '19:00', '19:30')[i % 3]}"))
    rs = burst(fns)
    fast(rs)
    win = [r for r in rs if r.status == 201]
    assert len(win) == 1 and all(r.status == 409 and r.code == "table_unavailable" for r in rs if r.status != 201), tally(rs)
    seen = assert_no_overlap(T)
    assert sum(1 for r in seen.values() if r["table_id"] == "t_51" and r["status"] == "confirmed") == 1


@check("A7b", "§2 '50 in flight' / §5 'Requests must not produce 5xx responses, including under concurrent load'",
       "50 mixed requests at once (reads, creates, PATCH, cancel, moves, login, export): no 5xx, each under its limit, invariant holds")
def _():
    sv = [seed(f"res_{i}", f"MIXD{i:02d}", f"u_c{i % 5}", "r_anker", f"t_{i}", f"{FUT}T19:00") for i in range(20)]
    reset(cfix(ntables=30, reservations=sv))
    T = toks()
    fns = []
    for i in range(N):
        t = T[i % 5]
        kind = i % 10
        if kind == 0:
            fns.append(lambda t=t: call("GET", "/reservations", token=t))
        elif kind == 1:
            fns.append(lambda: avail("r_anker", FUT, 2))
        elif kind == 2:
            fns.append(lambda i=i, t=t: book(t, tid=f"t_{20 + i % 10}", local=f"{FUT}T21:00"))
        elif kind == 3:
            fns.append(lambda i=i, t=t: patch(t, f"MIXD{i % 20:02d}", {"table_id": f"t_{25 + i % 5}"}))
        elif kind == 4:
            fns.append(lambda i=i, t=t: cancel(t, f"MIXD{i % 20:02d}"))
        elif kind == 5:
            fns.append(lambda i=i, t=t: moves(t, [{"reference": f"MIXD{i % 20:02d}", "starts_at_local": f"{FUT}T21:00"}]))
        elif kind == 6:
            fns.append(lambda i=i: call("POST", "/auth/login", json_body={"email": f"u_c{i % 5}@example.com", "password": f"pw-u_c{i % 5}-long"}))
        elif kind == 7:
            fns.append(lambda: call("GET", "/_test/export"))
        elif kind == 8:
            fns.append(lambda i=i, t=t: call("POST", "/reservations", json_body=body(party="x"), token=t, key=newkey()))
        else:
            fns.append(lambda: call("GET", "/restaurants/r_anker"))
    rs = burst(fns)
    for r in rs:
        lim = 10.0 if "/_test/" in r.desc else 5.0
        assert r.status < 500 and r.elapsed <= lim, (r.desc[:80], r.status, r.elapsed)
    assert_no_overlap(T)
