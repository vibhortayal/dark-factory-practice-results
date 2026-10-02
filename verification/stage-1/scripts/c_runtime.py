"""§3 runtime contract and §4 model/fixture."""
from vlib import *


@check("B2", "§3.2", "GET /health -> 200 {\"status\":\"ok\"}")
def _():
    r = expect(call("GET", "/health"), 200)
    assert r.json == {"status": "ok"}, r


@check("B3", "§3.3", "POST /_test/reset -> 204, empty body, no authentication")
def _():
    r = call("POST", "/_test/reset", json_body=fixture())
    expect(r, 204)
    assert r.content == b""


@check("B4", "§3.3 'Replace all service state ... subsequent requests must see only that fixture'",
       "reset drops users, tokens, restaurants, reservations and idempotency records")
def _():
    reset()
    ada = tok("u_ada")
    su = expect(call("POST", "/auth/signup", json_body={"email": "carol@example.com",
                                                        "password": "carol pass 1", "display_name": "Carol"}), 201).json
    k1 = newkey()
    made = expect(book(ada, key=k1), 201).json
    fx2 = fixture(users=[user("u_dan", "dan@example.com", "dan password")],
                  restaurants=[restaurant("r_other", "Other", tables=[table("o_1", 4)])])
    reset(fx2)
    expect(call("GET", "/reservations", token=ada), 401, "unauthenticated")
    expect(call("GET", "/reservations", token=su["token"]), 401, "unauthenticated")
    expect(call("POST", "/auth/login", json_body={"email": EMAIL["u_ada"], "password": PW["u_ada"]}), 401, "unauthenticated")
    ids = [x["id"] for x in expect(call("GET", "/restaurants"), 200).json["restaurants"]]
    assert ids == ["r_other"], ids
    expect(call("GET", "/restaurants/r_anker"), 404, "not_found")
    expect(avail("r_anker", FUT, 2), 404, "not_found")
    reset()
    expect(call("GET", "/reservations", token=ada), 401, "unauthenticated")  # old token stays dead
    ada2 = tok("u_ada")
    assert my_list(ada2) == []
    expect(get_res(ada2, made["reference"]), 404, "not_found")
    assert "t_2" in slots("r_anker", FUT, 2)[f"{FUT}T19:00"]["available_table_ids"]
    # old key forgotten: same key with a different body is a first use, not 409
    r = call("POST", "/reservations", json_body=body(tid="t_3", local=f"{FUT}T20:00"), token=ada2, key=k1)
    expect(r, 201)
    expect(call("POST", "/auth/login", json_body={"email": "carol@example.com", "password": "carol pass 1"}), 401, "unauthenticated")
    expect(call("POST", "/auth/signup", json_body={"email": "carol@example.com", "password": "carol pass 1",
                                                   "display_name": "Carol"}), 201)
    expect(call("GET", "/restaurants/r_other"), 404, "not_found")


@check("B5", "§3.3 'Repeated resets are supported'", "same fixture twice and alternating fixtures; nothing duplicated")
def _():
    fx = fixture(reservations=[seed("res_s1", "SEED01", "u_ada", "r_anker", "t_2", f"{FUT}T19:00")])
    for _i in range(3):
        reset(fx)
        t = tok("u_ada")
        l = my_list(t)
        assert len(l) == 1 and l[0]["reference"] == "SEED01", l
        assert len(expect(call("GET", "/restaurants"), 200).json["restaurants"]) == 2
    reset(fixture(users=[], restaurants=[], reservations=[]))
    assert expect(call("GET", "/restaurants"), 200).json == {"restaurants": []}
    reset(fx)
    assert len(my_list(tok("u_ada"))) == 1


@check("B6a", "§3.4 'IDs ... at most 64 characters ... also applies to IDs supplied in reset fixtures' + §5 exceeding a stated length -> 422",
       "65-character fixture ids (user, restaurant, table, reservation) -> 422 validation_failed; previous state kept")
def _():
    reset()
    ada = tok("u_ada")
    made = book_ok(ada)
    long = "x" * 65
    bad = [
        fixture(users=[user(long, "long@example.com")]),
        fixture(restaurants=[restaurant(long)]),
        fixture(restaurants=[restaurant(tables=[table(long, 4)])]),
        fixture(reservations=[seed(long, "SEED01", "u_ada", "r_anker", "t_2", f"{FUT}T19:00")]),
    ]
    for fx in bad:
        expect(call("POST", "/_test/reset", json_body=fx), 422, "validation_failed")
        # §1: rejected requests must not leave partial state
        l = my_list(ada)
        assert [x["reference"] for x in l] == [made["reference"]], f"state changed by rejected reset: {l}"
        assert len(expect(call("GET", "/restaurants"), 200).json["restaurants"]) == 2


@check("B6b", "§5 malformed_request", "reset with unparseable body -> 400 malformed_request; state kept")
def _():
    reset()
    ada = tok("u_ada")
    expect(call("POST", "/_test/reset", raw=b'{"users": ['), 400, "malformed_request")
    expect(call("GET", "/reservations", token=ada), 200)


@check("B6c", "§8 'reference is 6 to 12 characters of A-Z0-9, unique across all reservations' + §5 invalid format -> 422",
       "seeded reference of wrong length/alphabet, or duplicated -> 422 validation_failed")
def _():
    reset()
    for ref in ["ABCDE", "ABCDEFGHIJKLM", "abcdef", "ABC-EF"]:
        fx = fixture(reservations=[seed("res_s1", ref, "u_ada", "r_anker", "t_2", f"{FUT}T19:00")])
        expect(call("POST", "/_test/reset", json_body=fx), 422, "validation_failed")
    fx = fixture(reservations=[seed("res_s1", "SEED01", "u_ada", "r_anker", "t_2", f"{FUT}T19:00"),
                               seed("res_s2", "SEED01", "u_ada", "r_anker", "t_3", f"{FUT}T19:00")])
    expect(call("POST", "/_test/reset", json_body=fx), 422, "validation_failed")
    for ref in ["ABCDEF", "ABCDEFGHIJKL", "A1B2C3D4"]:  # 6 and 12 are the allowed ends
        fx = fixture(reservations=[seed("res_s1", ref, "u_ada", "r_anker", "t_2", f"{FUT}T19:00")])
        reset(fx)
        expect(get_res(tok("u_ada"), ref), 200)


@check("B11", "§3.4 IDs at most 64 characters", "64-character fixture ids accepted and usable; service ids are strings <= 64")
def _():
    u64, r64, t64, s64 = "u" * 64, "r" * 64, "t" * 64, "s" * 64
    fx = fixture(users=[user(u64, "u64@example.com", "sixty-four pw")],
                 restaurants=[restaurant(r64, tables=[table(t64, 4)])],
                 reservations=[seed(s64, "SEED64", u64, r64, t64, f"{FUT}T19:00")])
    reset(fx)
    j = expect(call("POST", "/auth/login", json_body={"email": "u64@example.com", "password": "sixty-four pw"}), 200).json
    assert j["user_id"] == u64, j
    expect(call("GET", f"/restaurants/{r64}"), 200)
    assert slots(r64, FUT, 2)[f"{FUT}T21:00"]["available_table_ids"] == [t64]
    got = expect(get_res(j["token"], "SEED64"), 200).json
    assert got["reservation_id"] == s64 and got["table_id"] == t64 and got["restaurant_id"] == r64, got
    made = book_ok(j["token"], r64, t64, f"{FUT}T21:00")
    assert_res_shape(made)
    su = expect(call("POST", "/auth/signup", json_body={"email": "n@example.com", "password": "new password",
                                                        "display_name": "N"}), 201).json
    assert isinstance(su["user_id"], str) and 1 <= len(su["user_id"]) <= 64, su


@check("B9r", "§3.4 'Unknown fields in a request body are ignored'", "unknown fields in the reset fixture are ignored")
def _():
    fx = fixture()
    fx["extra_top"] = {"a": 1}
    fx["users"][0]["nickname"] = "x"
    fx["restaurants"][0]["cuisine"] = "fish"
    fx["restaurants"][0]["tables"][0]["shape"] = "round"
    fx["restaurants"][0]["opening_hours"][0]["note"] = "x"
    reset(fx)
    tok("u_ada")
    expect(call("GET", "/restaurants/r_anker"), 200)


@check("C2", "§4 fixture format / §8 GET /restaurants/{id} 'in the fixture's shape'", "restaurant returned with fixture values")
def _():
    oh = [{"weekday": "thu", "opens": "18:00", "closes": "23:00"}, {"weekday": "fri", "opens": "18:00", "closes": "23:30"}]
    tb = [table("t_z", 2, "1"), table("t_a", 4, "2"), table("t_m", 6, "Window")]
    reset(fixture(restaurants=[restaurant("r_anker", "Zum Anker", "Europe/Berlin", 30, 90, 120, oh, tb)]))
    j = expect(call("GET", "/restaurants/r_anker"), 200).json
    assert j["id"] == "r_anker" and j["name"] == "Zum Anker" and j["timezone"] == "Europe/Berlin", j
    assert (j["slot_minutes"], j["reservation_duration_minutes"], j["cancellation_cutoff_minutes"]) == (30, 90, 120), j
    assert j["opening_hours"] == oh, j["opening_hours"]
    assert j["tables"] == tb, j["tables"]
    lst = expect(call("GET", "/restaurants"), 200).json
    assert set(lst) == {"restaurants"} and len(lst["restaurants"]) == 1
    e = lst["restaurants"][0]
    assert (e["id"], e["name"], e["timezone"]) == ("r_anker", "Zum Anker", "Europe/Berlin"), e


@check("C5", "§4 'Seeded users must be able to log in with the given password immediately'", "seeded login; user_id and display_name from fixture")
def _():
    reset(fixture(users=[user("u_ada", name="Ada"), user("u_bob")]))
    j = expect(call("POST", "/auth/login", json_body={"email": EMAIL["u_ada"], "password": PW["u_ada"]}), 200).json
    assert j["user_id"] == "u_ada" and j["display_name"] == "Ada" and isinstance(j["token"], str) and j["token"], j
    expect(call("GET", "/reservations", token=j["token"]), 200)


@check("C6", "§4 'reservations may seed confirmed bookings ... plus id, reference and user_id'",
       "seeded booking is confirmed, owned, occupies its table, and behaves like an API-made one")
def _():
    fx = fixture(reservations=[seed("res_s1", "SEED01", "u_ada", "r_anker", "t_2", f"{FUT}T19:00", 3),
                               seed("res_s2", "SEED02", "u_bob", "r_anker", "t_3", f"{FUT}T19:00", 2)])
    reset(fx)
    ada, bob = tok("u_ada"), tok("u_bob")
    got = expect(get_res(ada, "SEED01"), 200).json
    assert_res_shape(got, reservation_id="res_s1", reference="SEED01", restaurant_id="r_anker", table_id="t_2",
                     party_size=3, status="confirmed", starts_at_local=f"{FUT}T19:00")
    assert_ts(got["starts_at"], "Europe/Berlin", f"{FUT}T19:00", 120, "starts_at")
    assert_ts(got["ends_at"], "Europe/Berlin", f"{FUT}T20:30", 120, "ends_at")
    assert [x["reference"] for x in my_list(ada)] == ["SEED01"]
    expect(get_res(bob, "SEED01"), 404, "not_found")
    s = slots("r_anker", FUT, 2)
    for hm in ["18:00", "18:30", "19:00", "19:30", "20:00"]:
        assert s[f"{FUT}T{hm}"]["available_table_ids"] == ["t_1"], (hm, s[f"{FUT}T{hm}"])
    assert s[f"{FUT}T20:30"]["available_table_ids"] == ["t_1", "t_2", "t_3"]
    expect(book(bob, tid="t_2", local=f"{FUT}T19:30"), 409, "table_unavailable")
    p = expect(patch(ada, "SEED01", {"table_id": "t_1", "party_size": 2}), 200).json
    assert p["reservation_id"] == "res_s1" and p["reference"] == "SEED01" and p["table_id"] == "t_1", p
    c = expect(cancel(bob, "SEED02"), 200).json
    assert c["status"] == "cancelled" and c["reference"] == "SEED02" and c["reservation_id"] == "res_s2", c
    expect(book(bob, tid="t_3", local=f"{FUT}T19:00"), 201)


@check("C7", "§4 'A booking must not be rejected solely because its start is in the past'", "create, seed and PATCH-target in the past succeed")
def _():
    reset(fixture(reservations=[seed("res_p", "PAST01", "u_ada", "r_anker", "t_3", f"{PAST}T19:00")]))
    ada = tok("u_ada")
    j = book_ok(ada, local=f"{PAST}T19:00")
    assert_ts(j["starts_at"], "Europe/Berlin", f"{PAST}T19:00", 120, "starts_at")
    j0 = book_ok(ada, local="2001-03-06T19:00", tid="t_1")
    assert_ts(j0["starts_at"], "Europe/Berlin", "2001-03-06T19:00", 60, "starts_at")
    expect(get_res(ada, "PAST01"), 200)
    f = book_ok(ada, local=f"{FUT}T19:00")
    m = expect(patch(ada, f["reference"], {"starts_at_local": f"{PAST}T21:00"}), 200).json
    assert m["starts_at_local"] == f"{PAST}T21:00", m


@check("C8", "§4 'the cancellation and amendment cutoff rules still apply' / §8 cancel 'or later'", "cancel and PATCH of a past booking -> 409 cutoff_passed")
def _():
    reset(fixture(reservations=[seed("res_p", "PAST01", "u_ada", "r_anker", "t_3", f"{PAST}T19:00")]))
    ada = tok("u_ada")
    j = book_ok(ada, local=f"{PAST}T19:00")
    for ref in (j["reference"], "PAST01"):
        expect(cancel(ada, ref), 409, "cutoff_passed")
        expect(patch(ada, ref, {"party_size": 1}), 409, "cutoff_passed")
        expect(patch(ada, ref, {"starts_at_local": f"{FUT}T19:00"}), 409, "cutoff_passed")
        g = expect(get_res(ada, ref), 200).json
        assert g["status"] == "confirmed" and g["starts_at_local"] == f"{PAST}T19:00" and g["party_size"] == 2, g


@check("B10", "§3.4 'Unknown query parameters are ignored'", "extra query parameters on GET endpoints")
def _():
    reset()
    ada = tok("u_ada")
    a = expect(avail("r_anker", FUT, 2), 200).json
    b = expect(avail("r_anker", FUT, 2, foo="bar", limit="1e9"), 200).json
    assert a == b
    expect(call("GET", "/restaurants", params={"x": "1"}), 200)
    expect(call("GET", "/restaurants/r_anker", params={"x": "1"}), 200)
    expect(call("GET", "/reservations", token=ada, params={"status": "zzz", "page": "-1"}), 200)
    expect(call("GET", "/health", params={"x": "1"}), 200)


@check("A7r", "§2 per-request timeout 10 s for POST /_test/reset", "reset with an ordinary-size fixture (30 users, 4 restaurants x 12 tables, 120 bookings) < 10 s")
def _():
    us = [user(f"u_{i}") for i in range(30)]
    rs = [restaurant(f"r_{i}", f"R{i}", tables=[table(f"r{i}_t{j}", 4) for j in range(12)]) for i in range(4)]
    sv = []
    n = 0
    for i in range(4):
        for j in range(12):
            for hm in ("18:00", "19:30", "21:00")[: 3 if j < 9 else 1]:
                n += 1
                sv.append(seed(f"res_{n}", f"SD{n:04d}", f"u_{n % 30}", f"r_{i}", f"r{i}_t{j}", f"{FUT}T{hm}"))
    r = reset(fixture(users=us, restaurants=rs, reservations=sv))
    assert r.elapsed < 10, f"reset took {r.elapsed:.2f}s"
    assert len(my_list(tok("u_7"))) >= 1
