"""§8 reservations: create, list, read, cancel, amend."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from vlib import *


@check("H1H2", "§8 POST /reservations 201 body / 'reservation_duration_minutes'", "response fields, types, offsets, ends_at = starts_at + duration, created_at now")
def _():
    reset()
    ada = tok("u_ada")
    before = datetime.now(timezone.utc)
    j = expect(book(ada, party=4), 201).json
    s, e, c = assert_res_shape(j, restaurant_id="r_anker", table_id="t_2", party_size=4, status="confirmed",
                               starts_at_local=f"{FUT}T19:00")
    assert_ts(j["starts_at"], "Europe/Berlin", f"{FUT}T19:00", 120, "starts_at")
    assert_ts(j["ends_at"], "Europe/Berlin", f"{FUT}T20:30", 120, "ends_at")
    assert e - s == timedelta(minutes=90)
    assert abs((c - before).total_seconds()) < 120, f"created_at {j['created_at']} is not the creation time"
    n = expect(book(ada, rid="r_ny", tid="n_1", local="2026-12-01T19:00"), 201).json
    assert_ts(n["starts_at"], "America/New_York", "2026-12-01T19:00", -300, "starts_at")
    assert_ts(n["ends_at"], "America/New_York", "2026-12-01T20:30", -300, "ends_at")


@check("H3", "§8 'reference is 6 to 12 characters of A-Z0-9, unique across all reservations'", "280 creations next to 40 seeded references: format and uniqueness of references and ids")
def _():
    tb = [table(f"t{i:02d}", 4) for i in range(40)]
    sv = [seed(f"res_s{i}", f"SEED{i:02d}", "u_ada", "r_anker", f"t{i:02d}", f"{FUT2}T19:00") for i in range(40)]
    reset(fixture(restaurants=[restaurant(tables=tb)], reservations=sv))
    ada = tok("u_ada")
    refs, ids = set(r["reference"] for r in sv), set(r["id"] for r in sv)
    n = 0
    for hm in ["18:00", "19:30", "21:00"]:
        for i in range(40):
            for d in (FUT, "2027-06-22", "2027-06-29")[: 3 if hm != "21:00" else 1]:
                if n >= 300:
                    break
                j = expect(book(ada, tid=f"t{i:02d}", local=f"{d}T{hm}"), 201).json
                assert REF_RE.match(j["reference"]), j
                assert j["reference"] not in refs and j["reservation_id"] not in ids, f"duplicate identity {j}"
                refs.add(j["reference"])
                ids.add(j["reservation_id"])
                n += 1
    assert n >= 250, n
    assert len(my_list(ada)) == n + 40


@check("H4", "§8 'The table is taken for an overlapping interval -> 409 table_unavailable' / §1 half-open interval",
       "every overlapping start refused; adjacent starts and other tables accepted")
def _():
    reset(fixture(restaurants=[restaurant(oh=hours("17:00", "23:30"))]))
    ada, bob = tok("u_ada"), tok("u_bob")
    book_ok(ada, tid="t_2", local=f"{FUT}T19:00")
    for hm in ["18:00", "18:30", "19:00", "19:30", "20:00"]:
        expect(book(bob, tid="t_2", local=f"{FUT}T{hm}"), 409, "table_unavailable")
        expect(book(ada, tid="t_2", local=f"{FUT}T{hm}"), 409, "table_unavailable")
    assert len(my_list(bob)) == 0
    expect(book(bob, tid="t_2", local=f"{FUT}T20:30"), 201)   # starts when the other ends
    expect(book(bob, tid="t_2", local=f"{FUT}T17:30"), 201)   # ends when the other starts
    expect(book(bob, tid="t_3", local=f"{FUT}T19:00"), 201)   # other table
    expect(book(bob, tid="t_2", local=f"{FUT2}T19:00"), 201)  # other day
    assert_no_overlap([ada, bob])


@check("H5", "§8 'starts_at_local is not on the slot grid -> 422 not_on_slot_grid' / §4 'grid of this many minutes from opening time'", "off-grid starts inside opening hours")
def _():
    oh = [{"weekday": "tue", "opens": "18:00", "closes": "23:00"}, {"weekday": "wed", "opens": "17:15", "closes": "22:00"}]
    reset(fixture(restaurants=[restaurant(oh=oh)]))
    ada = tok("u_ada")
    for hm in ["18:01", "19:15", "19:29", "20:45"]:
        expect(book(ada, local=f"{FUT}T{hm}"), 422, "not_on_slot_grid")
    expect(book(ada, local=f"{FUT2}T18:00"), 422, "not_on_slot_grid")  # wednesday grid is 17:15 + k*30
    expect(book(ada, local=f"{FUT2}T18:15"), 201)
    assert len(my_list(ada)) == 1


@check("H6", "§8 'Slot outside opening hours, or the reservation would end after closes -> 422 outside_opening_hours'",
       "before opens, at/after closes, ending after closes, closed weekday; last allowed start accepted")
def _():
    reset(fixture(restaurants=[restaurant(oh=[{"weekday": "tue", "opens": "18:00", "closes": "23:00"}])]))
    ada = tok("u_ada")
    for hm in ["17:00", "17:30", "22:00", "22:30", "23:00", "23:30", "00:00", "12:00"]:
        expect(book(ada, local=f"{FUT}T{hm}"), 422, "outside_opening_hours")
    expect(book(ada, local=f"{FUT2}T19:00"), 422, "outside_opening_hours")  # Wednesday is closed
    expect(book(ada, local=f"{FUT}T21:30"), 201)  # ends exactly at closes
    expect(book(ada, tid="t_3", local=f"{FUT}T18:00"), 201)  # starts exactly at opens
    assert len(my_list(ada)) == 2


@check("H7", "§8 'party_size exceeds the table's capacity -> 422 party_exceeds_capacity'", "capacity + 1 refused, capacity accepted, 1 accepted")
def _():
    reset()
    ada = tok("u_ada")
    expect(book(ada, tid="t_2", party=5), 422, "party_exceeds_capacity")
    expect(book(ada, tid="t_1", party=3), 422, "party_exceeds_capacity")
    expect(book(ada, tid="t_2", party=4), 201)
    expect(book(ada, tid="t_1", party=2), 201)
    expect(book(ada, tid="t_3", party=1), 201)


@check("H8", "§8 'party_size below 1, or not an integer -> 422 validation_failed' / §5 'invalid party_size values (including strings and booleans)'",
       "0, negative, fraction, string, boolean, null, array, object")
def _():
    reset()
    ada = tok("u_ada")
    for v in [0, -1, -100, 1.5, "4", "four", "", True, False, None, [4], {"n": 4}]:
        expect(call("POST", "/reservations", json_body=body(party=v), token=ada, key=newkey()), 422, "validation_failed")
    assert my_list(ada) == []


@check("H10", "§8 'Unknown restaurant, unknown table, or the table belongs to another restaurant -> 404 not_found'", "three cases")
def _():
    reset()
    ada = tok("u_ada")
    expect(book(ada, rid="r_nope"), 404, "not_found")
    expect(book(ada, tid="t_nope"), 404, "not_found")
    expect(book(ada, rid="r_anker", tid="n_1"), 404, "not_found")
    expect(book(ada, rid="r_ny", tid="t_2"), 404, "not_found")
    assert my_list(ada) == []


@check("H11", "§5 422 'A required field ... is missing'", "each of the four create fields missing; empty object")
def _():
    reset()
    ada = tok("u_ada")
    for f in ("restaurant_id", "table_id", "starts_at_local", "party_size"):
        b = body()
        del b[f]
        expect(call("POST", "/reservations", json_body=b, token=ada, key=newkey()), 422, "validation_failed")
    expect(call("POST", "/reservations", json_body={}, token=ada, key=newkey()), 422, "validation_failed")
    assert my_list(ada) == []


@check("D2", "§5 400 malformed_request 'Unparseable body, or a field of the wrong JSON type'", "create/PATCH: unparseable, non-object, wrong-typed string fields")
def _():
    reset()
    ada = tok("u_ada")
    a = book_ok(ada)
    for raw in [b"", b"{", b'{"restaurant_id": "r_anker",}', b"\xff\xfe\x00", b"restaurant_id=r_anker"]:
        expect(call("POST", "/reservations", raw=raw, token=ada, key=newkey()), 400, "malformed_request")
    for raw in [b"{", b"nope"]:
        expect(call("PATCH", f"/reservations/{a['reference']}", raw=raw, token=ada), 400, "malformed_request")
    for v in ([], [body()], "str", 5, None, True):
        expect(call("POST", "/reservations", json_body=v, token=ada, key=newkey()), 400, "malformed_request")
        expect(call("PATCH", f"/reservations/{a['reference']}", json_body=v, token=ada), 400, "malformed_request")
    for f, v in [("restaurant_id", 5), ("table_id", 5), ("starts_at_local", 5), ("table_id", ["t_3"]),
                 ("restaurant_id", {"id": "r_anker"}), ("starts_at_local", True), ("table_id", False)]:
        expect(call("POST", "/reservations", json_body=body(tid="t_3", **{f: v}), token=ada, key=newkey()), 400, "malformed_request")
    for f, v in [("table_id", 5), ("starts_at_local", 5), ("table_id", ["t_3"]), ("starts_at_local", {"a": 1})]:
        expect(patch(ada, a["reference"], {f: v}), 400, "malformed_request")
    l = my_list(ada)
    assert len(l) == 1, l
    same(l[0], a)


@check("D10", "§5 'starts_at_local strings that are not a bare local YYYY-MM-DDTHH:MM are 422 validation_failed' / §8 'with no offset and no Z'",
       "offset, Z, seconds, space separator, impossible dates and times - create and PATCH")
def _():
    reset()
    ada = tok("u_ada")
    a = book_ok(ada, tid="t_3")
    bad = [f"{FUT}T19:00:00", f"{FUT}T19:00Z", f"{FUT}T19:00+02:00", f"{FUT} 19:00", f"{FUT}", "19:00", "2026-02-30T19:00",
           "2027-13-01T19:00", f"{FUT}T24:00", f"{FUT}T19:60", f"{FUT}T7:00", "27-06-15T19:00", "tomorrow", "",
           f"{FUT}T19:00:00+02:00", f"{FUT}T19:00 ", f"{FUT}T19"]
    for v in bad:
        expect(book(ada, local=v), 422, "validation_failed")
        expect(patch(ada, a["reference"], {"starts_at_local": v}), 422, "validation_failed")
    l = my_list(ada)
    assert len(l) == 1, l
    same(l[0], a)


@check("B9b", "§3.4 'Unknown fields in a request body are ignored, never an error'", "create and PATCH with extra fields; they cannot set protected values")
def _():
    reset()
    ada = tok("u_ada")
    r = call("POST", "/reservations", json_body=body(note="window", status="cancelled", reference="HACKED", user_id="u_bob",
                                                    reservation_id="x", nested={"a": [1, 2]}), token=ada, key=newkey())
    j = expect(r, 201).json
    assert j["status"] == "confirmed" and j["reference"] != "HACKED" and j["reservation_id"] != "x", j
    assert my_list(tok("u_bob")) == []
    p = expect(patch(ada, j["reference"], {"party_size": 3, "status": "cancelled", "reference": "HACKED",
                                           "reservation_id": "y", "created_at": "2000-01-01T00:00:00+00:00", "zzz": None}), 200).json
    assert p["party_size"] == 3 and p["status"] == "confirmed" and p["reference"] == j["reference"] \
        and p["reservation_id"] == j["reservation_id"] and p["created_at"] == j["created_at"], p


@check("I1", "§8 GET /reservations 'The caller's reservations, starts_at descending, confirmed and cancelled alike'",
       "empty list, ownership, ordering by instant across zones, cancelled included, entry shape")
def _():
    reset()
    ada, bob = tok("u_ada"), tok("u_bob")
    assert expect(call("GET", "/reservations", token=ada), 200).json == {"reservations": []}
    made = {}
    # New York 13:00 EDT (17:00Z) is later than Berlin 18:00 CEST (16:00Z) though its local string is smaller
    oh = hours("10:00", "23:00")
    reset(fixture(restaurants=[restaurant(oh=oh), restaurant("r_ny", "Hudson", "America/New_York", oh=oh, tables=[table("n_1", 4)])]))
    ada, bob = tok("u_ada"), tok("u_bob")
    made["b18"] = book_ok(ada, local=f"{FUT}T18:00")
    made["n13"] = book_ok(ada, rid="r_ny", tid="n_1", local=f"{FUT}T13:00")
    made["b21"] = book_ok(ada, local=f"{FUT}T21:00")
    made["old"] = book_ok(ada, local=f"{PAST}T19:00")
    made["nxt"] = book_ok(ada, tid="t_3", local=f"{FUT2}T10:00")
    book_ok(bob, tid="t_1", local=f"{FUT}T18:00")
    c = expect(cancel(ada, made["b21"]["reference"]), 200).json
    l = my_list(ada)
    assert [x["reference"] for x in l] == [made[k]["reference"] for k in ("nxt", "b21", "n13", "b18", "old")], [x["starts_at"] for x in l]
    for x in l:
        assert_res_shape(x)
    same(l[1], c)
    assert l[1]["status"] == "cancelled"
    same(l[2], made["n13"])
    same(l[4], made["old"])
    assert len(my_list(bob)) == 1


@check("I2", "§8 GET /reservations/{reference} '404 if it is not the caller's'", "own -> 200 same body as create; other user's and unknown -> 404 not_found")
def _():
    reset()
    ada, bob = tok("u_ada"), tok("u_bob")
    a = book_ok(ada)
    same(expect(get_res(ada, a["reference"]), 200).json, a)
    expect(get_res(bob, a["reference"]), 404, "not_found")
    expect(get_res(ada, "ZZZZ99"), 404, "not_found")
    expect(get_res(ada, a["reservation_id"] + "x"), 404, "not_found")
    expect(get_res(ada, a["reference"].lower() + "q"), 404, "not_found")


@check("I3I4", "§8 cancel '200 {reference, status: cancelled, ...}' / 'Already cancelled -> 200 with the current state'",
       "cancel, table free and bookable, second cancel 200")
def _():
    reset()
    ada, bob = tok("u_ada"), tok("u_bob")
    a = book_ok(ada)
    c = expect(cancel(ada, a["reference"]), 200).json
    want = dict(a)
    want["status"] = "cancelled"
    same(c, want)
    assert slots("r_anker", FUT, 3)[f"{FUT}T19:00"]["available_table_ids"] == ["t_2", "t_3"]
    b = book_ok(bob)
    c2 = expect(cancel(ada, a["reference"]), 200).json
    same(c2, want)
    same(expect(get_res(ada, a["reference"]), 200).json, want)
    assert expect(get_res(bob, b["reference"]), 200).json["status"] == "confirmed"
    # cancel with a JSON body is the same operation
    expect(call("POST", f"/reservations/{b['reference']}/cancel", json_body={"reason": "x"}, token=bob), 200)


@check("I5", "§8 cancel 'Now is within cancellation_cutoff_minutes of starts_at, or later -> 409 cutoff_passed' / §4 cancellation_cutoff_minutes",
       "both sides of the cutoff, about one minute from the boundary; state unchanged on refusal")
def _():
    z = ZoneInfo("Europe/Berlin")
    now = datetime.now(z)
    cand = now + timedelta(hours=3)
    day, m = cand.date(), -(-(cand.hour * 60 + cand.minute + 1) // 15) * 15      # next quarter hour
    if m > 23 * 60 + 30:
        day, m = day + timedelta(days=1), 0
    start = datetime(day.year, day.month, day.day, m // 60, m % 60, tzinfo=z)
    local = start.strftime("%Y-%m-%dT%H:%M")
    # whole minutes until start; real elapsed time is used so the arithmetic also holds across a DST change
    mins = int((start.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds() // 60)
    def rest(rid, cutoff):
        return restaurant(rid, rid, slot=15, dur=15, cutoff=cutoff, oh=hours("00:00", "23:45"), tables=[table(f"{rid}_t", 4)])
    # allowed: start - cutoff is 1..2 minutes ahead; refused: start - cutoff is 0..1 minute behind, and far behind
    reset(fixture(restaurants=[rest("r_open", mins - 1), rest("r_shut", mins + 1), rest("r_far", mins + 600), rest("r_zero", 0)]))
    ada = tok("u_ada")
    o = book_ok(ada, "r_open", "r_open_t", local)
    s = book_ok(ada, "r_shut", "r_shut_t", local)
    f = book_ok(ada, "r_far", "r_far_t", local)
    zr = book_ok(ada, "r_zero", "r_zero_t", local)
    for x in (s, f):
        expect(cancel(ada, x["reference"]), 409, "cutoff_passed")
        expect(patch(ada, x["reference"], {"party_size": 3}), 409, "cutoff_passed")
        same(expect(get_res(ada, x["reference"]), 200).json, x)
    assert slots("r_shut", local[:10], 1)[local]["available_table_ids"] == []
    expect(patch(ada, o["reference"], {"party_size": 3}), 200)
    assert expect(cancel(ada, o["reference"]), 200).json["status"] == "cancelled"
    assert expect(cancel(ada, zr["reference"]), 200).json["status"] == "cancelled"
    assert slots("r_open", local[:10], 1)[local]["available_table_ids"] == ["r_open_t"]


@check("I4b", "§8 'Already cancelled -> 200 with the current state - cancelling twice is not an error'", "cancel repeated five more times: 200 with the same state each time")
def _():
    reset()
    ada = tok("u_ada")
    a = book_ok(ada)
    first = expect(cancel(ada, a["reference"]), 200).json
    for _i in range(5):
        same(expect(cancel(ada, a["reference"]), 200).json, first)
    assert len(my_list(ada)) == 1


@check("I6", "§8 cancel 'Not the caller's reservation -> 404 not_found'", "other user's and unknown reference; booking stays confirmed")
def _():
    reset()
    ada, bob = tok("u_ada"), tok("u_bob")
    a = book_ok(ada)
    expect(cancel(bob, a["reference"]), 404, "not_found")
    expect(cancel(bob, "NOPE00"), 404, "not_found")
    same(expect(get_res(ada, a["reference"]), 200).json, a)


@check("I7", "§8 PATCH 'Change the time, the table or the party size. Any subset ... No idempotency key is required'",
       "each single field, pairs, all three; identity and created_at kept; times recomputed")
def _():
    reset()
    ada = tok("u_ada")
    a = book_ok(ada, tid="t_2", party=2)
    p = expect(patch(ada, a["reference"], {"party_size": 4}), 200).json
    want = dict(a, party_size=4)
    same(p, want)
    p = expect(patch(ada, a["reference"], {"table_id": "t_3"}), 200).json
    want["table_id"] = "t_3"
    same(p, want)
    p = expect(patch(ada, a["reference"], {"starts_at_local": f"{FUT2}T21:30"}), 200).json
    assert_res_shape(p, reservation_id=a["reservation_id"], reference=a["reference"], table_id="t_3", party_size=4,
                     status="confirmed", starts_at_local=f"{FUT2}T21:30", created_at=a["created_at"], restaurant_id="r_anker")
    assert_ts(p["starts_at"], "Europe/Berlin", f"{FUT2}T21:30", 120, "starts_at")
    assert_ts(p["ends_at"], "Europe/Berlin", f"{FUT2}T23:00", 120, "ends_at")
    p = expect(patch(ada, a["reference"], {"table_id": "t_1", "party_size": 2, "starts_at_local": f"{FUT}T18:00"}), 200).json
    assert (p["table_id"], p["party_size"], p["starts_at_local"]) == ("t_1", 2, f"{FUT}T18:00"), p
    same(expect(get_res(ada, a["reference"]), 200).json, p)
    assert len(my_list(ada)) == 1


@check("I8", "§8 PATCH 'Validation is identical to POST /reservations'", "every create error code through PATCH, judged on merged values; booking unchanged after each")
def _():
    reset(fixture(restaurants=[restaurant(oh=[{"weekday": "tue", "opens": "18:00", "closes": "23:00"}]),
                               restaurant("r_ny", "Hudson", "America/New_York", tables=[table("n_1", 4)])]))
    ada, bob = tok("u_ada"), tok("u_bob")
    a = book_ok(ada, tid="t_2", party=3)
    blocker = book_ok(bob, tid="t_3", local=f"{FUT}T20:00")
    ref = a["reference"]
    cases = [({"table_id": "t_3"}, 409, "table_unavailable"),               # 19:00-20:30 overlaps 20:00
             ({"table_id": "t_3", "starts_at_local": f"{FUT}T21:00"}, 409, "table_unavailable"),
             ({"starts_at_local": f"{FUT}T19:15"}, 422, "not_on_slot_grid"),
             ({"starts_at_local": f"{FUT}T22:00"}, 422, "outside_opening_hours"),
             ({"starts_at_local": f"{FUT}T17:00"}, 422, "outside_opening_hours"),
             ({"starts_at_local": f"{FUT2}T19:00"}, 422, "outside_opening_hours"),
             ({"party_size": 5}, 422, "party_exceeds_capacity"),
             ({"table_id": "t_1"}, 422, "party_exceeds_capacity"),           # current party 3 > capacity 2
             ({"party_size": 0}, 422, "validation_failed"),
             ({"party_size": -2}, 422, "validation_failed"),
             ({"party_size": "3"}, 422, "validation_failed"),
             ({"party_size": 2.5}, 422, "validation_failed"),
             ({"party_size": True}, 422, "validation_failed"),
             ({"table_id": "t_nope"}, 404, "not_found"),
             ({"table_id": "n_1"}, 404, "not_found")]
    for b, st, code in cases:
        expect(patch(ada, ref, b), st, code)
        same(expect(get_res(ada, ref), 200).json, a, f"after failed PATCH {b}:")
    s = slots("r_anker", FUT, 3)
    assert s[f"{FUT}T19:00"]["available_table_ids"] == [] and s[f"{FUT}T18:00"]["available_table_ids"] == ["t_3"]
    assert s[f"{FUT}T21:00"]["available_table_ids"] == ["t_2"]
    same(expect(get_res(bob, blocker["reference"]), 200).json, blocker)


@check("I9", "§8 PATCH 'the same cutoff rule as cancel applies (409 cutoff_passed), measured against the current start time'",
       "past booking cannot be moved to the future; future booking can be moved into the past, after which it is locked")
def _():
    reset()
    ada = tok("u_ada")
    old = book_ok(ada, local=f"{PAST}T19:00")
    expect(patch(ada, old["reference"], {"starts_at_local": f"{FUT}T19:00"}), 409, "cutoff_passed")
    expect(patch(ada, old["reference"], {"table_id": "t_3"}), 409, "cutoff_passed")
    same(expect(get_res(ada, old["reference"]), 200).json, old)
    new = book_ok(ada, tid="t_3", local=f"{FUT}T19:00")
    moved = expect(patch(ada, new["reference"], {"starts_at_local": f"{PAST}T21:00"}), 200).json
    assert moved["starts_at_local"] == f"{PAST}T21:00"
    expect(patch(ada, new["reference"], {"starts_at_local": f"{FUT}T19:00"}), 409, "cutoff_passed")
    expect(cancel(ada, new["reference"]), 409, "cutoff_passed")


@check("I10", "§8 PATCH 'A cancelled reservation is 409 reservation_cancelled'", "any PATCH of a cancelled booking")
def _():
    reset()
    ada = tok("u_ada")
    a = book_ok(ada)
    c = expect(cancel(ada, a["reference"]), 200).json
    for b in ({"party_size": 3}, {"table_id": "t_3"}, {"starts_at_local": f"{FUT}T20:00"}):
        expect(patch(ada, a["reference"], b), 409, "reservation_cancelled")
    same(expect(get_res(ada, a["reference"]), 200).json, c)
    assert slots("r_anker", FUT, 3)[f"{FUT}T19:00"]["available_table_ids"] == ["t_2", "t_3"]


@check("I11", "§8 GET/PATCH ownership, §5 not_found 'not visible to this caller'", "PATCH of another user's or unknown booking -> 404; target unchanged")
def _():
    reset()
    ada, bob = tok("u_ada"), tok("u_bob")
    a = book_ok(ada)
    expect(patch(bob, a["reference"], {"party_size": 1}), 404, "not_found")
    expect(patch(bob, "NOPE00", {"party_size": 1}), 404, "not_found")
    same(expect(get_res(ada, a["reference"]), 200).json, a)


@check("I12", "§8 PATCH 'A successful amendment releases the old slot and reserves the new one together'",
       "old slot free, new slot taken; moving onto an interval overlapping its own old one succeeds")
def _():
    reset()
    ada, bob = tok("u_ada"), tok("u_bob")
    a = book_ok(ada, tid="t_2", local=f"{FUT}T19:00", party=3)
    p = expect(patch(ada, a["reference"], {"starts_at_local": f"{FUT}T19:30"}), 200).json   # overlaps only itself
    assert_ts(p["starts_at"], "Europe/Berlin", f"{FUT}T19:30", 120, "starts_at")
    assert_ts(p["ends_at"], "Europe/Berlin", f"{FUT}T21:00", 120, "ends_at")
    s = slots("r_anker", FUT, 3)
    assert s[f"{FUT}T18:00"]["available_table_ids"] == ["t_2", "t_3"]
    for hm in ["18:30", "19:00", "19:30", "20:00", "20:30"]:
        assert s[f"{FUT}T{hm}"]["available_table_ids"] == ["t_3"], hm
    assert s[f"{FUT}T21:00"]["available_table_ids"] == ["t_2", "t_3"]
    expect(patch(ada, a["reference"], {"table_id": "t_3"}), 200)
    expect(book(bob, tid="t_2", local=f"{FUT}T19:30", party=3), 201)   # released table is bookable
    expect(book(bob, tid="t_3", local=f"{FUT}T19:30", party=3), 409, "table_unavailable")
    assert_no_overlap([ada, bob])


@check("I16", "§8 PATCH 'Any subset of table_id, starts_at_local, party_size' (the empty subset) / §3.4 unknown fields ignored", "PATCH {} and unknown-only fields -> 200, nothing changed")
def _():
    reset()
    ada = tok("u_ada")
    a = book_ok(ada)
    same(expect(patch(ada, a["reference"], {}), 200).json, a)
    same(expect(patch(ada, a["reference"], {"colour": "red"}), 200).json, a)
    same(expect(patch(ada, a["reference"], {"table_id": "t_2", "party_size": 2, "starts_at_local": f"{FUT}T19:00"}), 200).json, a)
    same(expect(get_res(ada, a["reference"]), 200).json, a)
