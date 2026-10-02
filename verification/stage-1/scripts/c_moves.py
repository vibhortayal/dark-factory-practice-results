"""§11 atomic reservation moves."""
from vlib import *

TB = [table("t_1", 2), table("t_2", 4), table("t_3", 4), table("t_4", 6)]


def mfix(extra=None):
    sv = [seed("res_b1", "BOOK01", "u_ada", "r_anker", "t_1", f"{FUT}T19:00"),
          seed("res_b2", "BOOK02", "u_ada", "r_anker", "t_2", f"{FUT}T19:00"),
          seed("res_b3", "BOOK03", "u_ada", "r_anker", "t_3", f"{FUT}T19:00"),
          seed("res_bb", "BOBS01", "u_bob", "r_anker", "t_4", f"{FUT}T19:00"),
          seed("res_pp", "PASTBK", "u_ada", "r_anker", "t_3", f"{PAST}T19:00"),
          seed("res_ny", "NYBK01", "u_ada", "r_ny", "n_1", f"{FUT}T19:00")]
    return fixture(restaurants=[restaurant(tables=TB), restaurant("r_ny", "Hudson", "America/New_York", tables=[table("n_1", 4)])],
                   reservations=sv + (extra or []))


def snap(token, refs=("BOOK01", "BOOK02", "BOOK03", "PASTBK", "NYBK01")):
    return {r: core(expect(get_res(token, r), 200).json) for r in refs}


def setup():
    reset(mfix())
    ada, bob = tok("u_ada"), tok("u_bob")
    return ada, bob, snap(ada)


@check("L12", "§11 'On success return 201 with {\"reservations\": [...]} in input order, including unchanged items' + the §11 example (swap)",
       "swap two tables; rotation of three; order and shape of the response")
def _():
    ada, bob, before = setup()
    r = expect(moves(ada, [{"reference": "BOOK02", "table_id": "t_1"}, {"reference": "BOOK01", "table_id": "t_2"}]), 201).json
    assert set(r) >= {"reservations"} and [x["reference"] for x in r["reservations"]] == ["BOOK02", "BOOK01"], r
    for x in r["reservations"]:
        assert_res_shape(x, status="confirmed", starts_at_local=f"{FUT}T19:00")
    assert r["reservations"][0]["table_id"] == "t_1" and r["reservations"][1]["table_id"] == "t_2"
    after = snap(ada)
    assert after["BOOK02"] == dict(before["BOOK02"], table_id="t_1") and after["BOOK01"] == dict(before["BOOK01"], table_id="t_2")
    assert after["BOOK03"] == before["BOOK03"]
    r = expect(moves(ada, [{"reference": "BOOK01", "table_id": "t_3"}, {"reference": "BOOK03", "table_id": "t_1"},
                           {"reference": "BOOK02", "table_id": "t_2"}]), 201).json
    assert [(x["reference"], x["table_id"]) for x in r["reservations"]] == [("BOOK01", "t_3"), ("BOOK03", "t_1"), ("BOOK02", "t_2")], r
    assert_no_overlap([ada, bob])
    assert slots("r_anker", FUT, 1)[f"{FUT}T19:00"]["available_table_ids"] == []


@check("L1", "§11 'requires authentication and an idempotency key' / 'No token gives 401'", "401 without token; 400 without key; body must be a JSON object")
def _():
    ada, bob, before = setup()
    b = {"moves": [{"reference": "BOOK01", "table_id": "t_4"}]}
    expect(call("POST", "/reservation-moves", json_body=b, key=newkey()), 401, "unauthenticated")
    expect(call("POST", "/reservation-moves", json_body=b, token="nope", key=newkey()), 401, "unauthenticated")
    expect(call("POST", "/reservation-moves", json_body=b, token=ada), 400, "missing_idempotency_key")
    for raw in (b"{", b"", b"moves"):
        expect(call("POST", "/reservation-moves", raw=raw, token=ada, key=newkey()), 400, "malformed_request")
    for v in ([], "x", 3, None):
        expect(call("POST", "/reservation-moves", json_body=v, token=ada, key=newkey()), 400, "malformed_request")
    assert snap(ada) == before


@check("L2", "§11 'moves contains 1..8 objects with distinct string references. Invalid shape or duplicate references gives 422 validation_failed'",
       "0 and 9 items refused, 1 and 8 accepted; non-array, missing, non-object item, bad reference, duplicates")
def _():
    sv = [seed(f"res_m{i}", f"MANY{i:02d}", "u_ada", "r_anker", f"t_{1 + i % 3}", f"{FUT2}T{('18:00', '19:30', '21:00')[i // 3]}")
          for i in range(9)]
    reset(mfix(sv))
    ada = tok("u_ada")
    refs = [f"MANY{i:02d}" for i in range(9)]
    before = snap(ada, refs)
    before_b = snap(ada)
    bad = [[], [{"reference": r} for r in refs], "BOOK01", {"reference": "BOOK01"}, None, 5, ["BOOK01"], [{}], [{"table_id": "t_4"}],
           [{"reference": 5}], [{"reference": None}], [{"reference": ["BOOK01"]}], [None], [[{"reference": "BOOK01"}]],
           [{"reference": "BOOK01"}, {"reference": "BOOK01"}],
           [{"reference": "BOOK01", "table_id": "t_4"}, {"reference": "BOOK02"}, {"reference": "BOOK01", "party_size": 1}],
           [{"reference": "BOOK01"}, 7]]
    for mv in bad:
        expect(moves(ada, mv), 422, "validation_failed")
    expect(call("POST", "/reservation-moves", json_body={}, token=ada, key=newkey()), 422, "validation_failed")
    expect(call("POST", "/reservation-moves", json_body={"move": []}, token=ada, key=newkey()), 422, "validation_failed")
    assert snap(ada, refs) == before and snap(ada) == before_b
    r = expect(moves(ada, [{"reference": "MANY00"}]), 201).json
    assert len(r["reservations"]) == 1
    r = expect(moves(ada, [{"reference": x} for x in refs[:8]]), 201).json
    assert [x["reference"] for x in r["reservations"]] == refs[:8]
    assert snap(ada, refs) == before


@check("L3", "§11 'Unknown/another owner's reference gives 404 not_found'", "unknown, other owner's, and mixed with valid items; nothing moves")
def _():
    ada, bob, before = setup()
    expect(moves(ada, [{"reference": "NOPE00", "table_id": "t_4"}]), 404, "not_found")
    expect(moves(ada, [{"reference": "BOBS01", "table_id": "t_1"}]), 404, "not_found")
    expect(moves(ada, [{"reference": "BOOK01", "starts_at_local": f"{FUT}T21:00"}, {"reference": "BOBS01"}]), 404, "not_found")
    expect(moves(bob, [{"reference": "BOOK01"}, {"reference": "BOBS01"}]), 404, "not_found")
    assert snap(ada) == before
    assert expect(get_res(bob, "BOBS01"), 200).json["table_id"] == "t_4"


@check("L4", "§11 'Every booking must belong to the caller and the same restaurant ... different restaurants give 422 validation_failed'", "two restaurants in one batch")
def _():
    ada, bob, before = setup()
    expect(moves(ada, [{"reference": "BOOK01"}, {"reference": "NYBK01"}]), 422, "validation_failed")
    expect(moves(ada, [{"reference": "NYBK01", "party_size": 3}, {"reference": "BOOK02", "party_size": 3}]), 422, "validation_failed")
    assert snap(ada) == before
    r = expect(moves(ada, [{"reference": "NYBK01", "party_size": 3}]), 201).json   # a single-restaurant batch elsewhere is fine
    assert r["reservations"][0]["party_size"] == 3 and r["reservations"][0]["restaurant_id"] == "r_ny"


@check("L5", "§11 'Each item accepts the ordinary PATCH fields ...; omitted fields retain their current values and unknown fields are ignored'",
       "party only, table only, time only, all three, unknown fields; times recomputed")
def _():
    ada, bob, before = setup()
    r = expect(moves(ada, [{"reference": "BOOK02", "party_size": 4, "colour": "red"},
                           {"reference": "BOOK01", "starts_at_local": f"{FUT2}T20:00", "status": "cancelled"},
                           {"reference": "BOOK03", "table_id": "t_4", "starts_at_local": f"{FUT}T21:00", "party_size": 6}],
                     note="top-level unknown"), 201).json
    x, y, z = r["reservations"]
    assert core(x) == dict(before["BOOK02"], party_size=4), x
    assert (y["table_id"], y["party_size"], y["starts_at_local"], y["status"]) == ("t_1", 2, f"{FUT2}T20:00", "confirmed"), y
    assert_ts(y["starts_at"], "Europe/Berlin", f"{FUT2}T20:00", 120, "starts_at")
    assert_ts(y["ends_at"], "Europe/Berlin", f"{FUT2}T21:30", 120, "ends_at")
    assert (z["table_id"], z["party_size"], z["starts_at_local"]) == ("t_4", 6, f"{FUT}T21:00"), z
    after = snap(ada)
    assert after["BOOK02"] == core(x) and after["BOOK01"] == core(y) and after["BOOK03"] == core(z)
    s = slots("r_anker", FUT, 1)
    assert s[f"{FUT}T19:00"]["available_table_ids"] == ["t_1", "t_3"], s[f"{FUT}T19:00"]
    assert s[f"{FUT}T21:00"]["available_table_ids"] == ["t_1", "t_2", "t_3"]


@check("L6", "§11 'Cancelled bookings give 409 reservation_cancelled'", "a cancelled booking anywhere in the batch")
def _():
    ada, bob, before = setup()
    expect(cancel(ada, "BOOK03"), 200)
    before = snap(ada)
    expect(moves(ada, [{"reference": "BOOK03", "table_id": "t_4", "starts_at_local": f"{FUT}T21:00"}]), 409, "reservation_cancelled")
    expect(moves(ada, [{"reference": "BOOK01", "starts_at_local": f"{FUT}T21:00"}, {"reference": "BOOK03", "party_size": 1}]), 409, "reservation_cancelled")
    assert snap(ada) == before


@check("L7L8", "§11 'Each booking's existing cutoff applies. Non-occupancy errors use ordinary amendment codes and take precedence in input order, with cutoff errors preceding other changes for that booking'",
       "cutoff; amendment codes; first failing item decides; cutoff before that booking's other errors; non-occupancy before occupancy")
def _():
    ada, bob, before = setup()
    P = lambda **kw: dict({"reference": "PASTBK"}, **kw)
    B1 = lambda **kw: dict({"reference": "BOOK01"}, **kw)
    B2 = lambda **kw: dict({"reference": "BOOK02"}, **kw)
    cases = [
        ([P(party_size=1)], 409, "cutoff_passed"),
        ([P(starts_at_local=f"{FUT}T19:15")], 409, "cutoff_passed"),                       # cutoff before its grid error
        ([P(party_size=99)], 409, "cutoff_passed"),
        ([B1(starts_at_local=f"{FUT}T19:15")], 422, "not_on_slot_grid"),
        ([B1(starts_at_local=f"{FUT}T23:00")], 422, "outside_opening_hours"),
        ([B1(starts_at_local=f"{FUT}T22:00")], 422, "outside_opening_hours"),
        ([B1(party_size=3)], 422, "party_exceeds_capacity"),
        ([B2(table_id="t_1", party_size=3)], 422, "party_exceeds_capacity"),
        ([B1(party_size=0)], 422, "validation_failed"),
        ([B1(party_size="2")], 422, "validation_failed"),
        ([B1(starts_at_local=f"{FUT}T19:00Z")], 422, "validation_failed"),
        ([B1(table_id="t_nope")], 404, "not_found"),
        ([B1(table_id="n_1")], 404, "not_found"),
        ([B1(table_id=5)], 400, "malformed_request"),
        ([B1(starts_at_local=5)], 400, "malformed_request"),
        ([B1(starts_at_local=f"{FUT}T19:15"), B2(party_size=9)], 422, "not_on_slot_grid"),   # input order
        ([B2(party_size=9), B1(starts_at_local=f"{FUT}T19:15")], 422, "party_exceeds_capacity"),
        ([B1(party_size=9), P(party_size=1)], 422, "party_exceeds_capacity"),
        ([P(party_size=1), B1(party_size=9)], 409, "cutoff_passed"),
        ([B1(table_id="t_4"), B2(party_size=9)], 422, "party_exceeds_capacity"),             # occupancy comes last
        ([B1(table_id="t_4"), B2(starts_at_local=f"{FUT}T19:15")], 422, "not_on_slot_grid"),
        ([B1(starts_at_local=f"{FUT}T21:00"), B2(party_size=9)], 422, "party_exceeds_capacity"),  # valid first item is not applied
    ]
    for mv, st, code in cases:
        expect(moves(ada, mv), st, code)
        assert snap(ada) == before, f"state changed by failed batch {mv}"
    assert slots("r_anker", FUT, 1)[f"{FUT}T21:00"]["available_table_ids"] == ["t_1", "t_2", "t_3", "t_4"]


@check("L9L10", "§11 'An overlap among resulting bookings or with an unlisted booking gives 409 table_unavailable. Unchanged listed bookings retain their occupancy'",
       "unlisted booking, two items onto one table, unchanged listed item; nothing moves")
def _():
    ada, bob, before = setup()
    cases = [
        [{"reference": "BOOK01", "table_id": "t_4"}],                                                   # bob's unlisted booking
        [{"reference": "BOOK01", "table_id": "t_2"}],                                                   # own unlisted booking
        [{"reference": "BOOK01", "table_id": "t_4", "starts_at_local": f"{FUT}T20:00"}],                # partial overlap
        [{"reference": "BOOK01", "table_id": "t_2", "starts_at_local": f"{FUT}T21:00"},
         {"reference": "BOOK03", "table_id": "t_2", "starts_at_local": f"{FUT}T20:30"}],                # the two results collide
        [{"reference": "BOOK01"}, {"reference": "BOOK02", "table_id": "t_1", "party_size": 2}],         # listed but unchanged
        [{"reference": "BOOK02", "table_id": "t_1", "party_size": 2}, {"reference": "BOOK01"}],
        [{"reference": "BOOK01", "starts_at_local": f"{FUT}T21:00"}, {"reference": "BOOK02", "table_id": "t_4"}],  # one valid, one colliding
    ]
    for mv in cases:
        expect(moves(ada, mv), 409, "table_unavailable")
        assert snap(ada) == before, f"state changed by failed batch {mv}"
    s = slots("r_anker", FUT, 1)
    assert s[f"{FUT}T19:00"]["available_table_ids"] == [] and s[f"{FUT}T21:00"]["available_table_ids"] == ["t_1", "t_2", "t_3", "t_4"]
    # adjacency is not overlap: BOOK01 moves to t_2 right after BOOK02 ends
    expect(moves(ada, [{"reference": "BOOK01", "table_id": "t_2", "starts_at_local": f"{FUT}T20:30"}]), 201)
    assert_no_overlap([ada, bob])


@check("L11", "§11 'Either every move commits or nothing changes: occupancy, reservation records and retry keys'",
       "failed batch leaves records and occupancy alone and does not consume its key")
def _():
    ada, bob, before = setup()
    occ = expect(avail("r_anker", FUT, 1), 200).json
    k = newkey()
    bad = [{"reference": "BOOK01", "starts_at_local": f"{FUT}T21:00"}, {"reference": "BOOK02", "table_id": "t_4"}]
    expect(moves(ada, bad, key=k), 409, "table_unavailable")
    bad2 = [{"reference": "BOOK01", "starts_at_local": f"{FUT}T21:00"}, {"reference": "BOOK02", "party_size": 9}]
    expect(moves(ada, bad2, key=k), 422, "party_exceeds_capacity")       # different body, key not consumed: no 409 reuse
    assert snap(ada) == before and expect(avail("r_anker", FUT, 1), 200).json == occ
    good = [{"reference": "BOOK01", "starts_at_local": f"{FUT}T21:00"}]
    first = expect(moves(ada, good, key=k), 201).json
    assert expect(moves(ada, good, key=k), 200).json == first
    # the failing body from before is now a reuse of a completed key
    expect(moves(ada, bad, key=k), 409, "idempotency_key_reuse")
    # same failing body retried after its cause is gone succeeds as a first use
    k2 = newkey()
    mv = [{"reference": "BOOK02", "table_id": "t_4"}]
    expect(moves(ada, mv, key=k2), 409, "table_unavailable")
    expect(cancel(bob, "BOBS01"), 200)
    expect(moves(ada, mv, key=k2), 201)


@check("L13", "§11 'Replays return that original response with 200, even after amendments or cancellations' / §7",
       "replay, replay after PATCH and cancel, different body 409 (also invalid), per-user scope")
def _():
    ada, bob, before = setup()
    k = newkey()
    mv = [{"reference": "BOOK02", "table_id": "t_1"}, {"reference": "BOOK01", "table_id": "t_2"}]
    first = expect(moves(ada, mv, key=k), 201).json
    assert expect(moves(ada, mv, key=k), 200).json == first
    expect(patch(ada, "BOOK01", {"starts_at_local": f"{FUT}T21:00", "party_size": 4}), 200)
    expect(cancel(ada, "BOOK02"), 200)
    mid = snap(ada)
    assert expect(moves(ada, mv, key=k), 200).json == first
    assert expect(moves(tok("u_ada"), list(mv), key=k), 200).json == first
    assert snap(ada) == mid, "replay changed state"
    for other in ([{"reference": "BOOK01", "table_id": "t_3"}], [], [{"reference": "NOPE00"}], [{"reference": "BOOK02"}], "x"):
        expect(moves(ada, other, key=k), 409, "idempotency_key_reuse")
    expect(call("POST", "/reservation-moves", json_body={"moves": mv, "x": 1}, token=ada, key=k), 409, "idempotency_key_reuse")
    assert snap(ada) == mid
    # bob may use the same key string independently
    r = expect(moves(bob, [{"reference": "BOBS01", "party_size": 5}], key=k), 201).json
    assert r["reservations"][0]["party_size"] == 5


@check("L14", "§11 'The booking's identity, owner and creation time never change' / 'No-op moves retain all existing values'",
       "no-op batch returns current values; moved bookings keep id, reference, created_at and owner")
def _():
    ada, bob, before = setup()
    made = book_ok(ada, tid="t_2", local=f"{FUT}T21:00")
    r = expect(moves(ada, [{"reference": made["reference"]}, {"reference": "BOOK01"}]), 201).json
    same(r["reservations"][0], made)
    assert core(r["reservations"][1]) == before["BOOK01"]
    assert snap(ada) == before
    r = expect(moves(ada, [{"reference": made["reference"], "table_id": "t_4", "starts_at_local": f"{FUT2}T18:00", "party_size": 5}]), 201).json
    x = r["reservations"][0]
    assert (x["reservation_id"], x["reference"], x["created_at"], x["restaurant_id"]) == \
        (made["reservation_id"], made["reference"], made["created_at"], "r_anker"), x
    assert made["reference"] in [y["reference"] for y in my_list(ada)]
    assert made["reference"] not in [y["reference"] for y in my_list(bob)]
    expect(get_res(bob, made["reference"]), 404, "not_found")
    assert len(my_list(ada)) == 6
