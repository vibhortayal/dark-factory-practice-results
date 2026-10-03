#!/usr/bin/env python3
"""Stage-2 Tablekeeper API probes (combined tables, upgrade). Check ids: CHECKS.md P2.*.

Usage: BASE=<stage-2 url> BASE2=<second stage-2 url> S1BASE=<stage-1 url> [OUT=..] python probe2.py
Reuses the helper framework of the stage-1 probe (imported as a library).
"""
import json
import os
import random
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "stage-1"))
import probe as p  # noqa: E402
from probe import (J, K, THU, FRI, PAST_THU, avail, book, cancel, check, code, expect, get, hours, listing, login,  # noqa: E402
                   note, parallel, patch, ref, req, reset, show, slots)

S1BASE = os.environ.get("S1BASE", "").rstrip("/")
BASE2 = p.BASE2
SEC = "stage-2"


def rest_c(**kw):
    r = {"id": "r_c", "name": "Kombinat", "timezone": "Europe/Berlin", "slot_minutes": 30,
         "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120, "opening_hours": hours("18:00", "23:00"),
         "tables": [{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4},
                    {"id": "t_3", "label": "3", "capacity": 4}, {"id": "t_4", "label": "4", "capacity": 6}],
         "combinable": [["t_1", "t_2"], ["t_3", "t_2"]]}
    r.update(kw)
    return r


def fx2(reservations=None, rest=None, extra_users=None):
    f = p.fixture(reservations=reservations, extra_users=extra_users)
    f["restaurants"].append(rest or rest_c())
    return f


def bookc(tok, tids, hhmm, party, day=THU, key=None, base=None, rid="r_c"):
    b = {"restaurant_id": rid, "table_ids": tids, "starts_at_local": f"{day}T{hhmm}", "party_size": party}
    return req("POST", "/reservations", token=tok, key=key or K(), body=b, base=base)


def opts(rid, day, hhmm, party):
    s = slots(rid, day, party).get(f"{day}T{hhmm}") or {}
    return [(o.get("table_ids"), o.get("capacity")) for o in (s.get("available_options") or [])], s.get("available_table_ids")


def tids_ok(j, want):
    """table_ids as a set equal to want; table_id present exactly when one member."""
    if not isinstance(j, dict) or sorted(j.get("table_ids") or []) != sorted(want):
        return False
    return (j.get("table_id") == want[0]) if len(want) == 1 else ("table_id" not in j)


def overlaps2(reservations):
    by = {}
    for x in reservations:
        for t in x.get("table_ids") or [x.get("table_id")]:
            by.setdefault((x["restaurant_id"], t), []).append(x)
    bad = []
    for k, xs in by.items():
        xs.sort(key=lambda x: datetime.fromisoformat(x["starts_at"]))
        for a, b in zip(xs, xs[1:]):
            if datetime.fromisoformat(a["ends_at"]) > datetime.fromisoformat(b["starts_at"]):
                bad.append((k, a["reference"], b["reference"]))
    return bad


S1, S2, S3, S4 = (["t_1"], 2), (["t_2"], 4), (["t_3"], 4), (["t_4"], 6)
P12, P32 = (["t_1", "t_2"], 6), (["t_3", "t_2"], 8)


def s_model():
    r = reset(fx2())
    expect("P2.M1a", "M1", SEC, "reset with combinable", r, 204)
    g = J(req("GET", "/restaurants/r_c")) or {}
    check("P2.M5", "M5", SEC, "GET /restaurants/{id} returns combinable in the fixture's shape", g.get("combinable") == [["t_1", "t_2"], ["t_3", "t_2"]], g.get("combinable"))
    g = J(req("GET", "/restaurants/r_anker")) or {}
    note("P2.M5n", "combinable of a restaurant whose fixture had none", g.get("combinable", "<absent>"))
    for cid, desc, val, st, ec in [
            ("P2.M1b", "combinable a string", "x", 400, "malformed_request"),
            ("P2.M1c", "combinable entry a string", ["t_1"], 400, "malformed_request"),
            ("P2.M1d", "combinable id a number", [["t_1", 2]], 400, "malformed_request"),
            ("P2.M1e", "entry of three ids", [["t_1", "t_2", "t_3"]], 422, "validation_failed"),
            ("P2.M1f", "entry of one id", [["t_1"]], 422, "validation_failed"),
            ("P2.M1g", "unknown table id", [["t_1", "t_9"]], 422, "validation_failed"),
            ("P2.M1h", "same id twice", [["t_1", "t_1"]], 422, "validation_failed")]:
        expect(cid, "M1", "Model/§5", f"reset: {desc}", reset(fx2(rest=rest_c(combinable=val))), st, ec)
    expect("P2.M1i", "M1", "Model", "reset: empty combinable list", reset(fx2(rest=rest_c(combinable=[]))), 204)


def s_availability():
    reset(fx2())
    W = lambda *o: [(t, c) for t, c in o]
    for cid, party, wopts, wsingles in [
            ("P2.AV1a", 2, W(S1, S2, S3, S4, P12, P32), ["t_1", "t_2", "t_3", "t_4"]),
            ("P2.AV1b", 3, W(S2, S3, S4, P12, P32), ["t_2", "t_3", "t_4"]),
            ("P2.AV1c", 6, W(S4, P12, P32), ["t_4"]),
            ("P2.AV1d", 7, W(P32), []),
            ("P2.AV1e", 8, W(P32), []),
            ("P2.AV1f", 9, [], [])]:
        o, s = opts("r_c", THU, "19:00", party)
        check(cid, "AV1/AV2/M3", "API/availability", f"party {party}: available_options (singles in fixture order, pairs in combinable order, summed capacity) and available_table_ids", o == wopts and s == wsingles, f"{o} {s}")
    sl = slots("r_c", THU, 2)
    check("P2.AV1g", "AV1", "API/availability", "every slot carries available_options", sl and all(isinstance(v.get("available_options"), list) for v in sl.values()), list(sl.values())[:1])
    o, s = opts("r_anker", THU, "19:00", 2)
    check("P2.AV1h", "AV1", "API/availability", "restaurant without combinable: options are the singles only", o == [(["t_1"], 2), (["t_2"], 4)] and s == ["t_1", "t_2"], f"{o} {s}")
    ta = p.ada()
    b = bookc(ta, ["t_2"], "19:30", 2)
    got = {h: opts("r_c", THU, h, 2) for h in ("18:00", "18:30", "19:30", "20:30", "21:00")}
    free, taken = (W(S1, S2, S3, S4, P12, P32), ["t_1", "t_2", "t_3", "t_4"]), (W(S1, S3, S4), ["t_1", "t_3", "t_4"])
    check("P2.AV3a", "AV1/BK5", "API/availability", "single booking on t_2 19:30 removes t_2 and both pairs from 18:30..20:30 only",
          b.status_code == 201 and got["18:00"] == free and got["21:00"] == free and all(got[h] == taken for h in ("18:30", "19:30", "20:30")), got)
    reset(fx2())
    ta = p.ada()
    b = bookc(ta, ["t_1", "t_2"], "19:00", 6)
    o, s = opts("r_c", THU, "19:00", 2)
    check("P2.AV3b", "AV1/BK5", "API/availability", "pair booking t_1+t_2 removes both singles and every pair sharing a member", b.status_code == 201 and o == W(S3, S4) and s == ["t_3", "t_4"], f"{o} {s}")


def s_create():
    reset(fx2())
    ta, tb = p.ada(), p.bob()
    r = bookc(ta, ["t_1", "t_2"], "19:00", 6)
    j = J(r) or {}
    check("P2.BK1a", "BK1/BK2/BK6", "API/POST", "pair with party = summed capacity -> 201, table_ids, no table_id, all stage-1 fields",
          r.status_code == 201 and j.get("table_ids") == ["t_1", "t_2"] and "table_id" not in j and not [x for x in p.shape_problems(dict(j, table_id="x"))], show(r))
    pair_ref = j.get("reference")
    for cid, desc, rr in [("P2.BK2a", "GET", get(ta, pair_ref)), ("P2.BK2b", "list", req("GET", "/reservations", token=ta))]:
        jj = J(rr) or {}
        jj = jj["reservations"][0] if "reservations" in jj else jj
        check(cid, "BK2", "API/POST", f"{desc} of a pair booking carries table_ids and omits table_id", jj == j, show(rr))
    expect("P2.BK5a", "BK5", "API/POST", "single on a member of the pair, overlapping (t_1 19:30)", bookc(tb, ["t_1"], "19:30", 2), 409, "table_unavailable")
    expect("P2.BK5b", "BK5", "API/POST", "single via table_id on the other member (t_2 18:00)", book(tb, "r_c", "t_2", f"{THU}T18:00", 2), 409, "table_unavailable")
    expect("P2.BK5c", "BK5", "API/POST", "other pair sharing t_2, overlapping", bookc(tb, ["t_3", "t_2"], "20:00", 6), 409, "table_unavailable")
    r = bookc(tb, ["t_3", "t_2"], "20:30", 8)
    check("P2.BK5d", "BK5/BK6", "API/POST", "other pair at the adjacent slot 20:30, party 8 = capacity -> 201", r.status_code == 201 and (J(r) or {}).get("table_ids") == ["t_3", "t_2"], show(r))
    r = book(tb, "r_c", "t_4", f"{THU}T19:00", 6)
    check("P2.BK1b", "BK1/BK2", "API/POST", "table_id still accepted -> 201 with table_id and table_ids of one", r.status_code == 201 and tids_ok(J(r), ["t_4"]), show(r))
    r = bookc(tb, ["t_3"], "18:30", 4)
    check("P2.BK1c", "BK1/BK2", "API/POST", "table_ids of one -> 201 with table_id and table_ids", r.status_code == 201 and tids_ok(J(r), ["t_3"]), show(r))
    base = {"restaurant_id": "r_c", "starts_at_local": f"{FRI}T19:00", "party_size": 2}
    expect("P2.BK1d", "BK1", "API/POST", "both table_id and table_ids", req("POST", "/reservations", token=ta, key=K(), body=dict(base, table_id="t_1", table_ids=["t_1"])), 422, "validation_failed")
    expect("P2.BK1e", "BK1", "stage-1 §5", "neither table_id nor table_ids", req("POST", "/reservations", token=ta, key=K(), body=base), 422, "validation_failed")
    expect("P2.BK3a", "BK3/M2", "API/POST", "undeclared pair t_1+t_4", bookc(ta, ["t_1", "t_4"], "19:00", 2, FRI), 422, "combination_not_allowed")
    expect("P2.BK3b", "BK3/M2", "Model", "transitive pair t_1+t_3 not bookable", bookc(ta, ["t_1", "t_3"], "19:00", 2, FRI), 422, "combination_not_allowed")
    expect("P2.BK4", "BK4", "API/POST", "three tables", bookc(ta, ["t_1", "t_2", "t_3"], "19:00", 2, FRI), 422, "combination_not_allowed")
    expect("P2.BK6", "BK6/M3", "API/POST", "party 7 on t_1+t_2 (capacity 6)", bookc(ta, ["t_1", "t_2"], "19:00", 7, FRI), 422, "party_exceeds_capacity")
    expect("P2.BK7a", "BK7", "API/POST", "duplicate table id", bookc(ta, ["t_1", "t_1"], "19:00", 2, FRI), 422, "validation_failed")
    expect("P2.BK7b", "BK7", "stage-1 §5", "empty table_ids", bookc(ta, [], "19:00", 2, FRI), 422, "validation_failed")
    expect("P2.BK7c", "BK7", "stage-1 §5", "table_ids a string", bookc(ta, "t_1", "19:00", 2, FRI), 400, "malformed_request")
    expect("P2.BK7d", "BK7", "stage-1 §5", "table_ids member a number", bookc(ta, ["t_1", 2], "19:00", 2, FRI), 400, "malformed_request")
    expect("P2.BK7e", "BK7", "stage-1 §8", "unknown table in the set", bookc(ta, ["t_1", "t_9"], "19:00", 2, FRI), 404, "not_found")
    expect("P2.BK7f", "BK7", "stage-1 §8", "table of another restaurant in the set", bookc(ta, ["t_1", "n_1"], "19:00", 2, FRI), 404, "not_found")
    r = bookc(ta, ["t_2", "t_1"], "19:00", 6, FRI)
    check("P2.BK3c", "BK3", "Model (unordered pair)", "declared pair given in reverse order -> 201", r.status_code == 201 and sorted((J(r) or {}).get("table_ids") or []) == ["t_1", "t_2"] and "table_id" not in (J(r) or {}), show(r))
    n = len(listing(ta) or [])
    check("P2.BK0", "BK1", "stage-1 §1", "rejected requests created nothing (ada has exactly 2 reservations)", n == 2, n)
    # idempotency with pairs
    k = K()
    a = bookc(ta, ["t_3", "t_2"], "21:00", 5, FRI, key=k)
    b = bookc(ta, ["t_3", "t_2"], "21:00", 5, FRI, key=k)
    c = bookc(ta, ["t_2", "t_3"], "21:00", 5, FRI, key=k)
    check("P2.ID1", "BK2", "stage-1 §7", "pair booking: first 201, replay 200 identical; different body (reversed ids) 409 idempotency_key_reuse",
          a.status_code == 201 and b.status_code == 200 and J(a) == J(b) and c.status_code == 409 and code(c) == "idempotency_key_reuse", show(a) + " | " + show(b) + " | " + show(c))
    # cancel frees both
    c = cancel(ta, pair_ref)
    jc = J(c) or {}
    o, s = opts("r_c", THU, "19:00", 2)
    check("P2.PA2", "PA2/BK2", "API/POST", "cancel of a pair -> 200 cancelled with table_ids; both tables free again (t_4 still booked)",
          c.status_code == 200 and jc.get("status") == "cancelled" and jc.get("table_ids") == ["t_1", "t_2"] and "table_id" not in jc and s == ["t_1", "t_2"] and (["t_1", "t_2"], 6) in o, f"{show(c)} {o} {s}")
    r1, r2 = bookc(tb, ["t_1"], "19:00", 2), bookc(tb, ["t_2"], "19:00", 2)
    check("P2.PA2b", "PA2", "API/POST", "both freed tables bookable separately", r1.status_code == 201 and r2.status_code == 201, show(r1) + " | " + show(r2))


def s_patch_moves():
    reset(fx2())
    ta, tb = p.ada(), p.bob()
    A = bookc(ta, ["t_1"], "19:00", 2)
    a = ref(A)
    r = patch(ta, a, {"table_ids": ["t_1", "t_2"], "party_size": 6})
    j = J(r) or {}
    check("P2.PA1a", "PA1", "API/PATCH", "single -> pair (own table kept) -> 200, table_ids pair, table_id omitted, identity kept",
          r.status_code == 200 and j.get("table_ids") == ["t_1", "t_2"] and "table_id" not in j and j.get("party_size") == 6 and j.get("reference") == a and j.get("reservation_id") == (J(A) or {}).get("reservation_id"), show(r))
    r = patch(ta, a, {"table_ids": ["t_3", "t_2"]})
    j = J(r) or {}
    o, s = opts("r_c", THU, "19:00", 2)
    check("P2.PA1b", "PA1", "API/PATCH", "pair -> pair sharing t_2 -> 200; t_1 released", r.status_code == 200 and j.get("table_ids") == ["t_3", "t_2"] and s == ["t_1", "t_4"], f"{show(r)} {s}")
    snap = lambda: (J(get(ta, a)), J(avail("r_c", THU, 2)))
    s0, bad = snap(), []
    X = bookc(tb, ["t_1"], "19:00", 2)
    s0 = snap()

    def fail(cid, desc, body, st, ec):
        expect(cid, "PA1", "API/PATCH", desc, patch(ta, a, body), st, ec)
        if snap() != s0:
            bad.append(cid)
    fail("P2.PA1c", "PATCH with both table_id and table_ids", {"table_id": "t_4", "table_ids": ["t_4"]}, 422, "validation_failed")
    fail("P2.PA1d", "PATCH to an undeclared pair", {"table_ids": ["t_3", "t_4"]}, 422, "combination_not_allowed")
    fail("P2.PA1e", "PATCH to three tables", {"table_ids": ["t_1", "t_2", "t_3"]}, 422, "combination_not_allowed")
    fail("P2.PA1f", "PATCH to a pair whose member is taken by another booking", {"table_ids": ["t_1", "t_2"]}, 409, "table_unavailable")
    fail("P2.PA1g", "PATCH party above the summed capacity (9 > 8)", {"party_size": 9}, 422, "party_exceeds_capacity")
    fail("P2.PA1h", "PATCH pair -> single t_3 with party 6 > 4", {"table_id": "t_3"}, 422, "party_exceeds_capacity")
    fail("P2.PA1i", "PATCH duplicate ids", {"table_ids": ["t_3", "t_3"]}, 422, "validation_failed")
    fail("P2.PA1j", "PATCH table_ids of wrong type", {"table_ids": "t_3"}, 400, "malformed_request")
    check("P2.PA1k", "PA1", "stage-1 §8", "every failed PATCH left the booking and availability unchanged", X.status_code == 201 and not bad, bad)
    r = patch(ta, a, {"table_id": "t_3", "party_size": 4})
    j = J(r) or {}
    check("P2.PA1l", "PA1/BK2", "API/PATCH", "pair -> single via table_id -> 200 with table_id and table_ids of one; t_2 released",
          r.status_code == 200 and tids_ok(j, ["t_3"]) and opts("r_c", THU, "19:00", 2)[1] == ["t_2", "t_4"], show(r))
    r = patch(ta, a, {"party_size": 3})
    check("P2.PA1m", "PA1/BK2", "API/PATCH", "PATCH of another field keeps the table set and still returns table_ids", r.status_code == 200 and tids_ok(J(r), ["t_3"]), show(r))
    # moves: A single t_3 (party 3), B pair
    cancel(tb, ref(X))
    B = bookc(ta, ["t_1", "t_2"], "19:00", 2)
    b = ref(B)
    patch(ta, a, {"party_size": 2})
    before = [J(get(ta, a)), J(get(ta, b))]
    r = p.moves(ta, [{"reference": a, "table_ids": ["t_3", "t_2"]}, {"reference": b}])
    expect("P2.MV1a", "MV1", "UI (moves paragraph)", "moves: A takes t_3+t_2 while unchanged B keeps t_1+t_2 (t_2 in two overlapping results)", r, 409, "table_unavailable")
    expect("P2.MV1b", "MV1", "API/POST", "moves item with both table_id and table_ids", p.moves(ta, [{"reference": a, "table_id": "t_4", "table_ids": ["t_4"]}]), 422, "validation_failed")
    expect("P2.MV1c", "MV1", "API/POST", "moves item with an undeclared pair", p.moves(ta, [{"reference": a, "table_ids": ["t_3", "t_4"]}]), 422, "combination_not_allowed")
    check("P2.MV1d", "MV1", "stage-1 §11", "nothing changed after refused moves", [J(get(ta, a)), J(get(ta, b))] == before, "")
    k = K()
    r = p.moves(ta, [{"reference": a, "table_ids": ["t_1", "t_2"]}, {"reference": b, "table_ids": ["t_3"]}], key=k)
    jr = (J(r) or {}).get("reservations") or [{}, {}]
    check("P2.MV1e", "MV1/BK2", "UI (moves paragraph)", "moves: pair booking and single booking exchange tables atomically -> 201, input order, table_ids in each",
          r.status_code == 201 and tids_ok(jr[0], ["t_1", "t_2"]) and tids_ok(jr[1], ["t_3"]) and jr[0].get("reference") == a and jr[1].get("reference") == b, show(r))
    r2 = p.moves(ta, [{"reference": a, "table_ids": ["t_1", "t_2"]}, {"reference": b, "table_ids": ["t_3"]}], key=k)
    check("P2.MV1f", "MV1", "stage-1 §7", "moves replay -> 200 identical", r2.status_code == 200 and J(r2) == J(r), show(r2))
    r = p.moves(ta, [{"reference": a, "table_ids": ["t_3", "t_2"]}, {"reference": b, "table_id": "t_1"}])
    jr = (J(r) or {}).get("reservations") or [{}, {}]
    check("P2.MV1g", "MV1", "UI (moves paragraph)", "moves: pair t_1+t_2 -> t_3+t_2 while the single moves t_3 -> t_1 -> 201", r.status_code == 201 and tids_ok(jr[0], ["t_3", "t_2"]) and tids_ok(jr[1], ["t_1"]), show(r))
    allc = [x for x in (listing(ta) or []) if x.get("status") == "confirmed"]
    check("P2.MV1h", "MV1", "UI (moves paragraph)", "no table belongs to overlapping resulting bookings", not overlaps2(allc), overlaps2(allc))


def s_seeded():
    seed = [{"id": "s_pair", "reference": "SEEDPAIR", "user_id": "u_ada", "restaurant_id": "r_c", "table_ids": ["t_1", "t_2"], "starts_at_local": f"{THU}T19:00", "party_size": 5},
            {"id": "s_one", "reference": "SEEDONE1", "user_id": "u_ada", "restaurant_id": "r_c", "table_id": "t_3", "starts_at_local": f"{THU}T19:00", "party_size": 2},
            {"id": "s_canc", "reference": "SEEDCANC", "user_id": "u_ada", "restaurant_id": "r_c", "table_ids": ["t_4"], "starts_at_local": f"{THU}T19:00", "party_size": 2, "status": "cancelled"}]
    r = reset(fx2(reservations=seed))
    ta = p.ada()
    g1, g2, g3 = (J(get(ta, x)) or {} for x in ("SEEDPAIR", "SEEDONE1", "SEEDCANC"))
    check("P2.M4a", "M4", "Model", "seeded pair reservation: confirmed, table_ids, no table_id", r.status_code == 204 and g1.get("status") == "confirmed" and g1.get("table_ids") == ["t_1", "t_2"] and "table_id" not in g1 and g1.get("reservation_id") == "s_pair", f"{show(r)} {g1}")
    check("P2.M4b", "M4", "Model", "seeded single reservation: table_id and table_ids of one", g2.get("status") == "confirmed" and tids_ok(g2, ["t_3"]), g2)
    check("P2.M4c", "M4", "Model", "seeded reservation with status cancelled is cancelled", g3.get("status") == "cancelled" and tids_ok(g3, ["t_4"]), g3)
    o, s = opts("r_c", THU, "19:00", 2)
    check("P2.M4d", "M4", "Model", "seeded pair and single occupy their tables; the cancelled one does not", s == ["t_4"] and o == [(["t_4"], 6)], f"{o} {s}")
    c = cancel(ta, "SEEDPAIR")
    check("P2.M4e", "M4/PA2", "Model", "seeded pair can be cancelled; both tables freed", c.status_code == 200 and opts("r_c", THU, "19:00", 2)[1] == ["t_1", "t_2", "t_4"], show(c))


def snapshot(toks, base=None):
    s = p.snapshot(toks, base=base)
    s["avc"] = J(avail("r_c", THU, 2, base=base))
    return s


def s_export_import():
    reset(fx2())
    ta, tb = p.ada(), p.bob()
    k1 = K()
    R1 = bookc(ta, ["t_1", "t_2"], "19:00", 6, key=k1)
    R2 = bookc(ta, ["t_3"], "19:00", 2)
    cancel(ta, ref(R2))
    R3 = bookc(tb, ["t_3", "t_2"], "20:30", 7)
    toks = {"ada": ta, "bob": tb}
    pre = snapshot(toks)
    ex = req("GET", "/_test/export", limit=10)
    E = J(ex) or {}
    check("P2.X4a", "X4", "stage-1 §10", "export -> 200 track tablekeeper, format_version 1", ex.status_code == 200 and E.get("track") == "tablekeeper" and E.get("format_version") == 1 and R1.status_code == 201 and R3.status_code == 201, ex.text[:200])
    bookc(ta, ["t_4"], "19:00", 2)
    cancel(tb, ref(R3))
    im = req("POST", "/_test/import", body=E, limit=10)
    post = snapshot(toks)
    check("P2.X4b", "X4", "stage-1 §10", "import restores the exported state incl. pair bookings, cancelled status, combinable, availability", im.status_code == 204 and post == pre, [k for k in pre if pre[k] != post.get(k)])
    rp = bookc(ta, ["t_1", "t_2"], "19:00", 6, key=k1)
    check("P2.X4c", "X4", "stage-1 §10", "replay of the pair booking after import -> 200 original", rp.status_code == 200 and J(rp) == J(R1), show(rp))
    if BASE2:
        reset(p.SPEC_FIXTURE, base=BASE2)
        im = req("POST", "/_test/import", body=E, base=BASE2, limit=10)
        post = snapshot(toks, base=BASE2)
        check("P2.X4d", "X4", "stage-1 §10", "import into a second stage-2 container shows the same state", im.status_code == 204 and post == pre, [k for k in pre if pre[k] != post.get(k)])
    else:
        check("P2.X4d", "X4", "stage-1 §10", "second container available", False, "BASE2 not set")


def s_upgrade():
    if not S1BASE:
        check("P2.X1", "X1", "upgrade", "stage-1 container available", False, "S1BASE not set")
        return
    seed = [{"id": "res_seed_1", "reference": "SEED01", "user_id": "u_bob", "restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": f"{FRI}T18:00", "party_size": 2}]
    r = reset(p.fixture(reservations=seed), base=S1BASE)
    ta, tb = p.ada(S1BASE), p.bob(S1BASE)
    su = req("POST", "/auth/signup", body={"email": "carol@example.com", "password": "carol secret pw", "display_name": "Carol"}, base=S1BASE)
    tc = (J(su) or {}).get("token")
    k1, km, kf = K(), K(), K()
    b1 = {"restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": f"{THU}T19:00", "party_size": 2}
    R1 = req("POST", "/reservations", token=ta, key=k1, body=b1, base=S1BASE)
    R2 = book(ta, "r_anker", "t_1", f"{THU}T21:00", 2, base=S1BASE)
    req("POST", f"/reservations/{ref(R2)}/cancel", token=ta, base=S1BASE)
    R3 = book(tb, "r_anker", "t_2", f"{THU}T19:00", 2, base=S1BASE)
    bm = {"moves": [{"reference": ref(R1), "party_size": 1}]}
    RM = req("POST", "/reservation-moves", token=ta, key=km, body=bm, base=S1BASE)
    RF = book(ta, "r_anker", "t_2", f"{THU}T19:00", 2, key=kf, base=S1BASE)
    toks = {"ada": ta, "bob": tb, "carol": tc}
    lists1 = {n: listing(t, base=S1BASE) for n, t in toks.items()}
    ex = req("GET", "/_test/export", base=S1BASE, limit=10)
    E = J(ex) or {}
    check("P2.X1a", "X1", "upgrade", "stage-1 state built and exported", r.status_code == 204 and [x.status_code for x in (R1, R2, R3, RM, RF)] == [201, 201, 201, 201, 409] and ex.status_code == 200, [x.status_code for x in (R1, R2, R3, RM, RF)])
    reset(fx2())
    old = p.ada()
    im = req("POST", "/_test/import", body=E, limit=10)
    expect("P2.X1b", "X1", "upgrade", "stage-2 import of the unchanged stage-1 export", im, 204)
    expect("P2.X1c", "X1", "stage-1 §10", "import removed the destination's previous credentials", req("GET", "/reservations", token=old), 401, "unauthenticated")
    bad = []
    for n, t in toks.items():
        l2 = listing(t)
        l1 = lists1[n] or []
        if l2 is None or len(l2) != len(l1):
            bad.append(f"{n}: {l2}")
            continue
        for x1, x2 in zip(l1, l2):
            if any(x2.get(k) != v for k, v in x1.items()) or x2.get("table_ids") != [x1["table_id"]]:
                bad.append(f"{n}: {x1} -> {x2}")
    check("P2.X1d", "X1/BK2", "upgrade", "stage-1 tokens valid; every reservation keeps all stage-1 fields (ids, references, statuses, timestamps) and gains table_ids of one", not bad, bad[:2])
    lg = [req("POST", "/auth/login", body={"email": e, "password": pw}) for e, pw in [("ada@example.com", "correct horse"), ("carol@example.com", "carol secret pw")]]
    check("P2.X1e", "X1", "stage-1 §10", "password login of seeded and signed-up stage-1 accounts", all(x.status_code == 200 for x in lg) and (J(lg[1]) or {}).get("user_id") == (J(su) or {}).get("user_id"), [show(x) for x in lg])
    rp = req("POST", "/reservations", token=ta, key=k1, body=b1)
    check("P2.X1f", "X1/BK2", "upgrade", "replay of the stage-1 create receipt -> 200 with the original body unchanged", rp.status_code == 200 and J(rp) == J(R1), show(rp) + " vs " + R1.text[:200])
    rp = req("POST", "/reservation-moves", token=ta, key=km, body=bm)
    check("P2.X1g", "X1", "upgrade", "replay of the stage-1 moves receipt -> 200 with the original body unchanged", rp.status_code == 200 and J(rp) == J(RM), show(rp))
    expect("P2.X1h", "X1", "stage-1 §10", "used stage-1 key with a different body", req("POST", "/reservations", token=ta, key=k1, body=dict(b1, party_size=1)), 409, "idempotency_key_reuse")
    o, s = opts("r_anker", THU, "19:00", 2)
    check("P2.X1i", "X1/AV1", "upgrade", "imported restaurant (no combinable): availability reflects imported bookings and has available_options", s == [] and o == [], f"{o} {s}")
    g = J(req("GET", "/restaurants/r_anker")) or {}
    check("P2.X1j", "X1", "upgrade", "imported restaurant configuration preserved", g.get("slot_minutes") == 30 and len(g.get("tables") or []) == 2 and g.get("opening_hours") == p.fixture()["restaurants"][0]["opening_hours"], g)
    r = book(ta, "r_anker", "t_2", f"{THU}T21:00", 2, key=kf)
    check("P2.X1k", "X1", "stage-1 §10", "key that failed on stage 1 is a first use on stage 2 (201) and the response carries table_ids", r.status_code == 201 and tids_ok(J(r), ["t_2"]), show(r))
    known = {x["reference"] for l in lists1.values() for x in (l or [])}
    knownids = {x["reservation_id"] for l in lists1.values() for x in (l or [])}
    new = [book(ta, "r_all", "a_2", f"2027-10-08T10:{m:02d}", 1) for m in (0, 15, 30, 45)]
    check("P2.X1l", "X1", "stage-1 §10", "new bookings after the upgrade do not collide with imported references/ids",
          all(x.status_code == 201 for x in new) and not ({ref(x) for x in new} & known) and not ({(J(x) or {}).get("reservation_id") for x in new} & knownids), [ref(x) for x in new])
    ex2 = req("GET", "/_test/export", limit=10)
    im2 = req("POST", "/_test/import", body=J(ex2), limit=10)
    rp = req("POST", "/reservations", token=ta, key=k1, body=b1)
    check("P2.X1m", "X1/X4", "stage-1 §10", "stage-2 re-export and re-import keeps the stage-1 receipt (still the original body)", im2.status_code == 204 and rp.status_code == 200 and J(rp) == J(R1), show(rp))


def s_concurrency():
    users = [{"id": f"u_load_{i}", "email": f"load{i}@example.com", "password": f"load password {i}", "display_name": f"L{i}"} for i in range(50)]
    reset(fx2(extra_users=users))
    rs = parallel([(lambda i=i: req("POST", "/auth/login", body={"email": f"load{i}@example.com", "password": f"load password {i}"})) for i in range(50)])
    toks = [(J(x) or {}).get("token") for x in rs]
    choices = [(["t_1", "t_2"], 2), (["t_3", "t_2"], 2), (["t_2"], 2), (["t_1"], 2), (["t_3"], 2)]
    rs = parallel([(lambda i=i, t=t: bookc(t, choices[i % 5][0], "19:00", 2)) for i, t in enumerate(toks)])
    allc = [x for t in toks for x in (listing(t) or []) if x.get("status") == "confirmed"]
    n201 = sum(1 for x in rs if x.status_code == 201)
    check("P2.CC1a", "CC1", "Concurrent bookings", "50 concurrent pair/single bookings sharing tables at one slot: only 201/409, no table in two confirmed bookings, confirmed count = 201 count",
          all(x.status_code in (201, 409) for x in rs) and not overlaps2(allc) and len(allc) == n201 and 1 <= n201 <= 3, f"{sorted(x.status_code for x in rs)} {overlaps2(allc)} confirmed={len(allc)}")
    o, s = opts("r_c", THU, "19:00", 2)
    taken = {t for x in allc for t in x["table_ids"]}
    check("P2.CC1b", "CC1", "Concurrent bookings", "availability after the race is consistent with the confirmed bookings", set(s) == {"t_1", "t_2", "t_3", "t_4"} - taken and all(not (set(t) & taken) for t, _ in o), f"{s} {o} taken={taken}")
    rnd = random.Random(11)
    hh = ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30"]
    sets = [["t_1", "t_2"], ["t_3", "t_2"], ["t_1"], ["t_2"], ["t_3"], ["t_4"]]

    def worker(i, seed):
        rg = random.Random(seed)
        t = toks[i]
        out = [avail("r_c", FRI, 2)]
        b = bookc(t, rg.choice(sets), rg.choice(hh), 2, FRI)
        out.append(b)
        if b.status_code == 201:
            out.append(patch(t, ref(b), {"table_ids": rg.choice(sets), "starts_at_local": f"{FRI}T{rg.choice(hh)}"}))
            if rg.random() < 0.3:
                out.append(cancel(t, ref(b)))
        out.append(req("GET", "/reservations", token=t))
        return out
    allr = []
    for _ in range(4):
        res = parallel([(lambda i=i, s=rnd.random(): worker(i, s)) for i in range(50)])
        allr += [x for o_ in res for x in o_]
    badst = [show(x) for x in allr if x.status_code not in (200, 201, 409)]
    allc = [x for t in toks for x in (listing(t) or []) if x.get("status") == "confirmed"]
    check("P2.CC1c", "CC1", "Concurrent bookings", f"4 rounds x 50 in-flight create/PATCH/cancel with pairs ({len(allr)} requests): only 200/201/409; no table in overlapping confirmed bookings ({len(allc)} confirmed)", not badst and not overlaps2(allc), f"{badst[:2]} {overlaps2(allc)[:3]}")
    sl = slots("r_c", FRI, 1)
    incons = []
    for k, v in sl.items():
        st = datetime.fromisoformat(v["starts_at"])
        for tid in ("t_1", "t_2", "t_3", "t_4"):
            busy = any(tid in x["table_ids"] and datetime.fromisoformat(x["starts_at"]) < st + (datetime.fromisoformat(x["ends_at"]) - datetime.fromisoformat(x["starts_at"])) and datetime.fromisoformat(x["ends_at"]) > st
                       for x in allc if x["restaurant_id"] == "r_c" and x["starts_at_local"].startswith(FRI))
            if busy == (tid in v["available_table_ids"]):
                incons.append((k, tid))
    check("P2.CC1d", "CC1", "Concurrent bookings", "after load, availability of every slot agrees with the confirmed bookings", not incons, incons[:5])


def main():
    only = set(sys.argv[1:])
    for s in [s_model, s_availability, s_create, s_patch_moves, s_seeded, s_export_import, s_upgrade, s_concurrency]:
        if not only or s.__name__ in only:
            p.section(s)
    p.final_audits()
    fails = [r for r in p.RESULTS if not r["ok"]]
    print(f"\nTOTAL {len(p.RESULTS)} checks: {len(p.RESULTS) - len(fails)} passed, {len(fails)} failed, {len(p.NOTES)} notes", flush=True)
    for f in fails:
        print(f"  FAIL {f['id']} [{f['row']} {f['sec']}] {f['desc']} :: {f['detail']}")
    if p.OUT:
        with open(p.OUT, "w") as fh:
            json.dump({"results": p.RESULTS, "notes": p.NOTES}, fh, indent=1)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
