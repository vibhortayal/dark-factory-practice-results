"""§9 time and DST."""
from vlib import *

NIGHT = hours("00:00", "06:00")


def night_fixture(dur=60):
    return fixture(restaurants=[
        restaurant("r_b", "Berlin night", "Europe/Berlin", 30, dur, 0, NIGHT, [table("b_1", 4), table("b_2", 4)]),
        restaurant("r_n", "NY night", "America/New_York", 30, dur, 0, NIGHT, [table("n_1", 4), table("n_2", 4)])])


def slot_list(rid, date):
    j = expect(avail(rid, date, 2), 200).json
    return [(s["starts_at_local"][11:], parse_ts(s["starts_at"]).utcoffset().total_seconds() / 60) for s in j["slots"]], j


@check("J1", "§9 'Offsets must follow the IANA rules for the specified zone and date' / §3.4 timestamps with explicit offset",
       "standard and summer offsets for Berlin, New York and two further IANA zones")
def _():
    day = hours("10:00", "23:00")
    zones = [("Europe/Berlin", "2026-12-01", 60), ("Europe/Berlin", "2026-07-01", 120), ("America/New_York", "2026-12-01", -300),
             ("America/New_York", "2026-07-01", -240), ("Asia/Kolkata", "2026-07-01", 330), ("Australia/Sydney", "2026-12-01", 660),
             ("Australia/Sydney", "2026-07-01", 600), ("UTC", "2026-07-01", 0)]
    names = sorted(set(z for z, _d, _o in zones))
    reset(fixture(restaurants=[restaurant(f"r{i}", z, z, oh=day, tables=[table(f"z{i}", 4)]) for i, z in enumerate(names)]))
    ada = tok("u_ada")
    for z, d, off in zones:
        i = names.index(z)
        j = expect(avail(f"r{i}", d, 2), 200).json
        assert j["timezone"] == z and j["date"] == d, j
        s0 = j["slots"][0]
        assert s0["starts_at_local"] == f"{d}T10:00", s0
        assert_ts(s0["starts_at"], z, f"{d}T10:00", off, f"{z} {d} slot")
        b = book_ok(ada, f"r{i}", f"z{i}", f"{d}T12:00")
        assert_ts(b["starts_at"], z, f"{d}T12:00", off, f"{z} {d} starts_at")
        assert_ts(b["ends_at"], z, f"{d}T13:30", off, f"{z} {d} ends_at")
    # J6: Berlin 20:00 CET and New York 14:00 EST on 2026-12-01 are one instant
    b = book_ok(ada, f"r{names.index('Europe/Berlin')}", f"z{names.index('Europe/Berlin')}", "2026-12-01T20:00")
    n = book_ok(ada, f"r{names.index('America/New_York')}", f"z{names.index('America/New_York')}", "2026-12-01T14:00")
    assert parse_ts(b["starts_at"]) == parse_ts(n["starts_at"]), (b["starts_at"], n["starts_at"])


@check("J2a", "§9 Spring forward 'never appear in availability, and booking one is 422 invalid_local_time' (Europe/Berlin 2026-03-29)",
       "availability skips 02:00-02:59, offsets switch, gap bookings refused via create and PATCH, neighbours fine")
def _():
    reset(night_fixture(60))
    ada = tok("u_ada")
    got, _j = slot_list("r_b", "2026-03-29")
    want = [("00:00", 60), ("00:30", 60), ("01:00", 60), ("01:30", 60), ("03:00", 120), ("03:30", 120), ("04:00", 120),
            ("04:30", 120), ("05:00", 120)]
    assert got == want, got
    for hm in ("02:00", "02:30"):
        expect(book(ada, "r_b", "b_1", f"2026-03-29T{hm}"), 422, "invalid_local_time")
    fut = book_ok(ada, "r_b", "b_2", f"{FUT}T03:00")
    for hm in ("02:00", "02:30"):
        expect(patch(ada, fut["reference"], {"starts_at_local": f"2026-03-29T{hm}"}), 422, "invalid_local_time")
        expect(moves(ada, [{"reference": fut["reference"], "starts_at_local": f"2026-03-29T{hm}"}]), 422, "invalid_local_time")
    same(expect(get_res(ada, fut["reference"]), 200).json, fut)
    a = book_ok(ada, "r_b", "b_1", "2026-03-29T01:30")
    assert_ts(a["starts_at"], "Europe/Berlin", "2026-03-29T01:30", 60, "starts_at")
    assert_ts(a["ends_at"], "Europe/Berlin", "2026-03-29T03:30", 120, "ends_at (60 real minutes later)")
    c = book_ok(ada, "r_b", "b_2", "2026-03-29T03:00")
    assert_ts(c["starts_at"], "Europe/Berlin", "2026-03-29T03:00", 120, "starts_at")
    # the same wall-clock times exist on the days around the change
    d = book_ok(ada, "r_b", "b_1", "2026-03-28T02:00")
    assert_ts(d["starts_at"], "Europe/Berlin", "2026-03-28T02:00", 60, "day before")
    e = book_ok(ada, "r_b", "b_1", "2026-03-30T02:30")
    assert_ts(e["starts_at"], "Europe/Berlin", "2026-03-30T02:30", 120, "day after")
    assert len(slot_list("r_b", "2026-03-28")[0]) == 11 and len(slot_list("r_b", "2026-03-30")[0]) == 11


@check("J2b", "§9 Spring forward (America/New_York 2026-03-08)", "availability skips 02:00-02:59, offsets -05:00 -> -04:00, gap booking refused")
def _():
    reset(night_fixture(60))
    ada = tok("u_ada")
    got, _j = slot_list("r_n", "2026-03-08")
    want = [("00:00", -300), ("00:30", -300), ("01:00", -300), ("01:30", -300), ("03:00", -240), ("03:30", -240), ("04:00", -240),
            ("04:30", -240), ("05:00", -240)]
    assert got == want, got
    for hm in ("02:00", "02:30"):
        expect(book(ada, "r_n", "n_1", f"2026-03-08T{hm}"), 422, "invalid_local_time")
    # 02:00-02:59 exists in Berlin on that date and in New York three weeks later
    expect(book(ada, "r_b", "b_1", "2026-03-08T02:00"), 201)
    n = book_ok(ada, "r_n", "n_1", "2026-03-29T02:00")
    assert_ts(n["starts_at"], "America/New_York", "2026-03-29T02:00", -240, "starts_at")
    assert my_list(ada)[0]["starts_at_local"] == "2026-03-29T02:00"


@check("J3a", "§9 Fall back 'Always resolve to the first occurrence ... The slot appears once in availability' (Europe/Berlin 2026-10-25)",
       "repeated hour listed once with +02:00; 03:00 has +01:00; bookings in the repeated hour take the first occurrence")
def _():
    reset(night_fixture(90))
    ada = tok("u_ada")
    got, _j = slot_list("r_b", "2026-10-25")
    want = [("00:00", 120), ("00:30", 120), ("01:00", 120), ("01:30", 120), ("02:00", 120), ("02:30", 120), ("03:00", 60),
            ("03:30", 60), ("04:00", 60), ("04:30", 60)]
    assert got == want, got
    a = book_ok(ada, "r_b", "b_1", "2026-10-25T02:00")
    assert_ts(a["starts_at"], "Europe/Berlin", "2026-10-25T02:00", 120, "starts_at (first occurrence)")
    assert_ts(a["ends_at"], "Europe/Berlin", "2026-10-25T02:30", 60, "ends_at (90 real minutes later)")
    assert a["starts_at_local"] == "2026-10-25T02:00"
    # the same local time on the same table is the same first occurrence again: taken
    expect(book(ada, "r_b", "b_1", "2026-10-25T02:00"), 409, "table_unavailable")
    expect(book(ada, "r_b", "b_1", "2026-10-25T02:30"), 409, "table_unavailable")
    b = book_ok(ada, "r_b", "b_2", "2026-10-25T02:30")
    assert_ts(b["starts_at"], "Europe/Berlin", "2026-10-25T02:30", 120, "starts_at (first occurrence)")
    assert_ts(b["ends_at"], "Europe/Berlin", "2026-10-25T03:00", 60, "ends_at")


@check("J4", "§9 'A 90-minute reservation starting at 01:30 on a fall-back night ends 90 real minutes later, and its local ends_at will read 02:00, not 03:00'",
       "Berlin 2026-10-25 01:30 + 90 min")
def _():
    reset(night_fixture(90))
    ada = tok("u_ada")
    a = book_ok(ada, "r_b", "b_1", "2026-10-25T01:30")
    assert_ts(a["starts_at"], "Europe/Berlin", "2026-10-25T01:30", 120, "starts_at")
    assert_ts(a["ends_at"], "Europe/Berlin", "2026-10-25T02:00", 60, "ends_at")
    assert (parse_ts(a["ends_at"]) - parse_ts(a["starts_at"])).total_seconds() == 5400
    same(expect(get_res(ada, a["reference"]), 200).json, a)


@check("J3b", "§9 Fall back (America/New_York 2026-11-01, 02:00 -> 01:00)", "01:00/01:30 listed once with -04:00; 02:00 has -05:00; absolute duration")
def _():
    reset(night_fixture(90))
    ada = tok("u_ada")
    got, _j = slot_list("r_n", "2026-11-01")
    want = [("00:00", -240), ("00:30", -240), ("01:00", -240), ("01:30", -240), ("02:00", -300), ("02:30", -300), ("03:00", -300),
            ("03:30", -300), ("04:00", -300), ("04:30", -300)]
    assert got == want, got
    a = book_ok(ada, "r_n", "n_1", "2026-11-01T01:00")
    assert_ts(a["starts_at"], "America/New_York", "2026-11-01T01:00", -240, "starts_at (first occurrence)")
    assert_ts(a["ends_at"], "America/New_York", "2026-11-01T01:30", -300, "ends_at")
    b = book_ok(ada, "r_n", "n_2", "2026-11-01T00:30")
    assert_ts(b["ends_at"], "America/New_York", "2026-11-01T01:00", -300, "ends_at reads 01:00 standard time")


@check("J5a", "§9 'reservation_duration_minutes is absolute time, not wall-clock' / §1 occupancy interval - fall back",
       "occupancy across the repeated hour uses instants: no false overlap, no false clearance")
def _():
    reset(night_fixture(90))
    ada = tok("u_ada")
    # b_1 at 02:30 first occurrence = [00:30Z, 02:00Z); 03:00 CET = 02:00Z is adjacent, not overlapping
    book_ok(ada, "r_b", "b_1", "2026-10-25T02:30")
    s = {k[11:]: v["available_table_ids"] for k, v in slots("r_b", "2026-10-25", 2).items()}
    assert s["03:00"] == ["b_1", "b_2"], s
    for hm in ("01:30", "02:00", "02:30"):
        assert s[hm] == ["b_2"], (hm, s)
    assert s["01:00"] == ["b_1", "b_2"], s          # [23:00Z, 00:30Z) ends when the booking starts
    expect(book(ada, "r_b", "b_1", "2026-10-25T03:00"), 201)
    expect(book(ada, "r_b", "b_1", "2026-10-25T02:00"), 409, "table_unavailable")
    expect(book(ada, "r_b", "b_1", "2026-10-25T01:00"), 201)
    assert_no_overlap([ada])


@check("J5b", "§9 absolute duration / §1 occupancy interval - spring forward",
       "a 90-minute booking at 01:30 before the gap occupies until 04:00 local")
def _():
    reset(night_fixture(90))
    ada = tok("u_ada")
    a = book_ok(ada, "r_b", "b_1", "2026-03-29T01:30")     # [00:30Z, 02:00Z) = until 04:00 CEST
    assert_ts(a["ends_at"], "Europe/Berlin", "2026-03-29T04:00", 120, "ends_at")
    s = {k[11:]: v["available_table_ids"] for k, v in slots("r_b", "2026-03-29", 2).items()}
    assert "02:00" not in s and "02:30" not in s, s
    assert s["03:00"] == ["b_2"] and s["03:30"] == ["b_2"], s
    assert s["04:00"] == ["b_1", "b_2"], s
    expect(book(ada, "r_b", "b_1", "2026-03-29T03:00"), 409, "table_unavailable")
    expect(book(ada, "r_b", "b_1", "2026-03-29T03:30"), 409, "table_unavailable")
    expect(book(ada, "r_b", "b_1", "2026-03-29T04:00"), 201)
    assert_no_overlap([ada])
