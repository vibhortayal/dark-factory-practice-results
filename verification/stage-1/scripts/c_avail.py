"""§8 restaurants and availability, §5 query-parameter rules."""
from vlib import *


@check("G1", "§8 GET /restaurants", "list of {id, name, timezone}; public")
def _():
    reset()
    j = expect(call("GET", "/restaurants"), 200).json
    got = sorted((x["id"], x["name"], x["timezone"]) for x in j["restaurants"])
    assert got == [("r_anker", "Zum Anker", "Europe/Berlin"), ("r_ny", "Hudson", "America/New_York")], j


@check("G2", "§8 GET /restaurants/{id} '404 if unknown'", "known restaurant has all configuration fields; unknown -> 404 not_found")
def _():
    reset()
    j = expect(call("GET", "/restaurants/r_ny"), 200).json
    for k in ("slot_minutes", "reservation_duration_minutes", "cancellation_cutoff_minutes", "opening_hours", "tables"):
        assert k in j, (k, j)
    assert j["tables"] == [table("n_1", 4), table("n_2", 2)] and j["opening_hours"] == hours(), j
    expect(call("GET", "/restaurants/nope"), 404, "not_found")


@check("G3", "§8 'All three parameters are required; a missing one is 422 validation_failed'", "each parameter missing, and all missing")
def _():
    reset()
    full = {"restaurant_id": "r_anker", "date": FUT, "party_size": "2"}
    for k in full:
        p = dict(full)
        del p[k]
        expect(call("GET", "/availability", params=p), 422, "validation_failed")
    expect(call("GET", "/availability"), 422, "validation_failed")


@check("G4", "§5 'invalid format or out-of-range value gives 422 ... This includes invalid dates'", "date not a real YYYY-MM-DD -> 422")
def _():
    reset()
    for d in ["2026-02-30", "not-a-date", "24-09-2026", "2026-13-01", "2026-9-4", "2027-06-15T19:00", "20270615", ""]:
        expect(avail("r_anker", d, 2), 422, "validation_failed")
    expect(avail("r_anker", "2028-02-29", 2), 200)  # a real leap day


@check("D11", "§5 'An integer-valued query parameter is written as plain decimal digits: 1e9, 4.0 and +4 are 422' / 'negative counts'",
       "party_size query values")
def _():
    reset()
    for v in ["1e9", "4.0", "+4", "-1", "0", "abc", "", " 4", "4 ", "0x4", "4,0", "true", "null"]:
        expect(avail("r_anker", FUT, v), 422, "validation_failed")
    for v in ["1", "2", "4"]:
        expect(avail("r_anker", FUT, v), 200)


@check("G5", "§5 404 not_found 'No such resource'", "availability for an unknown restaurant -> 404 not_found")
def _():
    reset()
    expect(avail("r_nope", FUT, 2), 404, "not_found")


@check("G6G7", "§8 'A slot appears for every slot_minutes step from opens such that slot + reservation_duration_minutes <= closes'",
       "response shape, slot grid and both ends of the window")
def _():
    oh = [{"weekday": "tue", "opens": "18:00", "closes": "23:00"}, {"weekday": "wed", "opens": "17:15", "closes": "22:00"}]
    reset(fixture(restaurants=[restaurant(oh=oh), restaurant("r_45", "Odd", slot=45, dur=60, oh=oh, tables=[table("x_1", 4)]),
                               restaurant("r_tight", "Tight", slot=30, dur=90,
                                          oh=[{"weekday": "tue", "opens": "18:00", "closes": "19:30"},
                                              {"weekday": "wed", "opens": "18:00", "closes": "19:29"}],
                                          tables=[table("y_1", 4)])]))
    j = expect(avail("r_anker", FUT, 2), 200).json
    assert j["restaurant_id"] == "r_anker" and j["date"] == FUT and j["timezone"] == "Europe/Berlin", j
    want = [f"{FUT}T{h}" for h in ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30"]]
    assert [s["starts_at_local"] for s in j["slots"]] == want, [s["starts_at_local"] for s in j["slots"]]
    for s in j["slots"]:
        assert set(s) >= {"starts_at_local", "starts_at", "available_table_ids"}, s
        assert_ts(s["starts_at"], "Europe/Berlin", s["starts_at_local"], 120, "slot starts_at")
        assert s["available_table_ids"] == ["t_1", "t_2", "t_3"], s
    # wednesday: grid counted from opens 17:15; 17:15 + k*30, last start 20:15 (ends 21:45 <= 22:00)
    w = [s["starts_at_local"][11:] for s in expect(avail("r_anker", FUT2, 2), 200).json["slots"]]
    assert w == ["17:15", "17:45", "18:15", "18:45", "19:15", "19:45", "20:15"], w
    # 45-minute grid, 60-minute duration, 18:00-23:00: last start 21:45 (ends 22:45); 22:30 would end 23:30
    o = [s["starts_at_local"][11:] for s in expect(avail("r_45", FUT, 2), 200).json["slots"]]
    assert o == ["18:00", "18:45", "19:30", "20:15", "21:00", "21:45"], o
    # window exactly one duration long: one slot; one minute shorter: none
    assert [s["starts_at_local"][11:] for s in expect(avail("r_tight", FUT, 2), 200).json["slots"]] == ["18:00"]
    assert expect(avail("r_tight", FUT2, 2), 200).json["slots"] == []


@check("G8", "§8 'available_table_ids lists the tables of that restaurant with capacity >= party_size ... in fixture order'",
       "capacity boundary, fixture order, only this restaurant's tables")
def _():
    tb = [table("t_z", 2), table("t_a", 4), table("t_m", 6), table("t_b", 4)]
    reset(fixture(restaurants=[restaurant(tables=tb), restaurant("r_ny", "Hudson", "America/New_York", tables=[table("n_1", 8)])]))
    def at(p):
        return slots("r_anker", FUT, p)[f"{FUT}T19:00"]["available_table_ids"]
    assert at(1) == ["t_z", "t_a", "t_m", "t_b"]
    assert at(2) == ["t_z", "t_a", "t_m", "t_b"]
    assert at(3) == ["t_a", "t_m", "t_b"]
    assert at(4) == ["t_a", "t_m", "t_b"]
    assert at(5) == ["t_m"]
    assert at(6) == ["t_m"]


@check("G9", "§8 'A slot with no available table still appears, with an empty list'", "party larger than every table; all tables booked")
def _():
    reset()
    j = expect(avail("r_anker", FUT, 7), 200).json
    assert len(j["slots"]) == 8 and all(s["available_table_ids"] == [] for s in j["slots"]), j
    ada = tok("u_ada")
    for t in ("t_2", "t_3"):
        book_ok(ada, tid=t, local=f"{FUT}T19:00", party=3)
    s = slots("r_anker", FUT, 3)
    assert len(s) == 8
    assert s[f"{FUT}T19:00"]["available_table_ids"] == [] and s[f"{FUT}T20:00"]["available_table_ids"] == []
    assert s[f"{FUT}T20:30"]["available_table_ids"] == ["t_2", "t_3"]


@check("G10", "§8 'A closed day returns \"slots\": []' / §4 'A day with no entry is closed'", "weekday without opening hours")
def _():
    reset(fixture(restaurants=[restaurant(oh=[{"weekday": "thu", "opens": "18:00", "closes": "23:00"}])]))
    j = expect(avail("r_anker", FUT, 2), 200).json  # FUT is a Tuesday
    assert j["slots"] == [] and j["restaurant_id"] == "r_anker" and j["date"] == FUT and j["timezone"] == "Europe/Berlin", j
    assert len(expect(avail("r_anker", "2027-06-17", 2), 200).json["slots"]) == 8  # Thursday
    reset(fixture(restaurants=[restaurant(oh=[])]))
    assert expect(avail("r_anker", FUT, 2), 200).json["slots"] == []


@check("G11", "§1 'Occupancy is the half-open interval [starts_at, starts_at + reservation_duration)' / §8 'no overlapping confirmed reservation'",
       "a 90-minute booking hides its table from every overlapping slot and not from adjacent ones")
def _():
    reset(fixture(restaurants=[restaurant(oh=hours("17:00", "23:30"))]))
    ada = tok("u_ada")
    book_ok(ada, tid="t_2", local=f"{FUT}T19:00")
    s = slots("r_anker", FUT, 3)
    got = {k[11:]: v["available_table_ids"] for k, v in s.items()}
    for hm in ["18:00", "18:30", "19:00", "19:30", "20:00"]:
        assert got[hm] == ["t_3"], (hm, got[hm])
    for hm in ["17:00", "17:30", "20:30", "21:00", "22:00"]:
        assert got[hm] == ["t_2", "t_3"], (hm, got[hm])
    # another date is unaffected
    assert slots("r_anker", FUT2, 3)[f"{FUT2}T19:00"]["available_table_ids"] == ["t_2", "t_3"]


@check("G12", "§8 cancel 'Frees the table immediately: the next GET /availability must offer that slot again'", "cancelled reservations do not occupy")
def _():
    reset()
    ada = tok("u_ada")
    a = book_ok(ada, tid="t_2")
    assert slots("r_anker", FUT, 3)[f"{FUT}T19:00"]["available_table_ids"] == ["t_3"]
    expect(cancel(ada, a["reference"]), 200)
    s = slots("r_anker", FUT, 3)
    for hm in ["18:00", "18:30", "19:00", "19:30", "20:00"]:
        assert s[f"{FUT}T{hm}"]["available_table_ids"] == ["t_2", "t_3"], hm
    expect(book(tok("u_bob"), tid="t_2"), 201)


@check("E8b", "§8 'public - no bearer token'", "NOTE-level: a stale/garbage Authorization header on public endpoints is not an error")
def _():
    reset()
    h = {"Authorization": "Bearer stale-token"}
    expect(call("GET", "/restaurants", headers=h), 200)
    expect(call("GET", "/restaurants/r_anker", headers=h), 200)
    expect(call("GET", "/availability", params={"restaurant_id": "r_anker", "date": FUT, "party_size": "2"}, headers=h), 200)
    expect(call("GET", "/health", headers=h), 200)
