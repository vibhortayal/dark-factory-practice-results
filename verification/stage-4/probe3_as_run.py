#!/usr/bin/env python3
"""Stage-3 Tablekeeper API probes (explanations, history, policies, terms, series). Ids: CHECKS.md P3.*.

Usage: BASE=<stage-3 url> BASE2=<second stage-3 url> S1BASE=<stage-1 url> S2BASE=<stage-2 url> python probe3.py
"""
import copy
import json
import os
import random
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "stage-1"))
sys.path.insert(0, os.path.join(HERE, "..", "stage-2"))
import probe as p  # noqa: E402
from probe import J, K, PAST_THU, avail, book, cancel, check, code, expect, get, hours, listing, login, note, parallel, patch, ref, req, reset, show, slots  # noqa: E402
from probe2 import overlaps2  # noqa: E402

S1BASE = os.environ.get("S1BASE", "").rstrip("/")
S2BASE = os.environ.get("S2BASE", "").rstrip("/")
BASE2 = p.BASE2
LEAK = []
_audit = p.audit


def audit3(r, dt, limit):
    _audit(r, dt, limit)
    if "restaurant_revision" in r.text and "/_test/export" not in str(r.request.url):
        LEAK.append(f"{r.request.method} {r.request.url.raw_path.decode()}")


p.audit = audit3

MON, TUE, THU = "2027-09-20", "2027-09-21", "2027-09-23"
H0 = hours("18:00", "23:00")
TERMS0 = {"policy_version": 0, "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
          "opening_hours": H0, "capacities": {"t_1": 2, "t_2": 4, "t_3": 6}}
MGR = ("mgr@example.com", "manager secret")


def rest_m(**kw):
    r = {"id": "r_m", "name": "Managed", "timezone": "Europe/Berlin", "slot_minutes": 30, "reservation_duration_minutes": 90,
         "cancellation_cutoff_minutes": 120, "opening_hours": H0,
         "tables": [{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4}, {"id": "t_3", "label": "3", "capacity": 6}],
         "combinable": [["t_1", "t_2"]], "manager_user_ids": ["u_mgr"]}
    r.update(kw)
    return r


def fx3(reservations=None, extra_users=None, rests=None):
    f = p.fixture(reservations=reservations, extra_users=[{"id": "u_mgr", "email": MGR[0], "password": MGR[1], "display_name": "Manager"}] + (extra_users or []))
    for r in f["restaurants"]:
        if r["id"] == "r_night_b":
            r["manager_user_ids"] = ["u_mgr"]
    f["restaurants"] += rests if rests is not None else [rest_m(), {
        "id": "r_now", "name": "Now", "timezone": "Europe/Berlin", "slot_minutes": 15, "reservation_duration_minutes": 15,
        "cancellation_cutoff_minutes": 30, "opening_hours": hours("00:00", "23:59"),
        "tables": [{"id": "w_1", "label": "W1", "capacity": 4}, {"id": "w_2", "label": "W2", "capacity": 4}], "manager_user_ids": ["u_mgr"]}]
    return f


def mgr(base=None):
    return login(MGR[0], MGR[1], base)


def pol(eff, slot=30, dur=90, cutoff=120, hrs=None, caps=None, **extra):
    b = {"effective_from": eff, "slot_minutes": slot, "reservation_duration_minutes": dur, "cancellation_cutoff_minutes": cutoff,
         "opening_hours": hrs if hrs is not None else H0, "capacities": caps if caps is not None else {"t_1": 2, "t_2": 4, "t_3": 6}}
    b.update(extra)
    return b


def publish(tok, body, rid="r_m", key=None, base=None):
    return req("POST", f"/restaurants/{rid}/policies", token=tok, key=key or K(), body=body, base=base)


def terms_of(body, version):
    t = {k: v for k, v in body.items() if k in ("slot_minutes", "reservation_duration_minutes", "cancellation_cutoff_minutes", "opening_hours", "capacities")}
    t["policy_version"] = version
    return t


def bk(tok, tid, day, hhmm, party, rid="r_m", key=None, base=None):
    return book(tok, rid, tid, f"{day}T{hhmm}", party, key=key, base=base)


def bkp(tok, tids, day, hhmm, party, rid="r_m", key=None):
    return req("POST", "/reservations", token=tok, key=key or K(), body={"restaurant_id": rid, "table_ids": tids, "starts_at_local": f"{day}T{hhmm}", "party_size": party})


def hist(tok, reference, base=None):
    r = req("GET", f"/reservations/{reference}/history", token=tok, base=base)
    j = J(r) or {}
    return j.get("entries") if r.status_code == 200 else None


def dec(tok, reference):
    return req("GET", f"/reservations/{reference}/decision", token=tok)


def series(tok, anchor, count, weeks, key=None, base=None, **extra):
    b = {"anchor_reference": anchor, "count": count, "interval_weeks": weeks}
    b.update(extra)
    return req("POST", "/series", token=tok, key=key or K(), body=b, base=base)


def getseries(tok, sid):
    return req("GET", f"/series/{sid}", token=tok)


def explain(rid, day, party):
    r = req("GET", f"/availability?restaurant_id={rid}&date={day}&party_size={party}&explain=true")
    return {s["starts_at_local"][-5:]: s for s in (J(r) or {}).get("slots", [])}, r


def ex_row(tid, ver, cap, free):
    return {"table_id": tid, "policy_version": ver, "available": cap and free, "rules": [{"rule": "capacity", "holds": cap}, {"rule": "no_overlap", "holds": free}]}


def changes(entry):
    return [(c.get("field"), c.get("from"), c.get("to")) for c in entry.get("changes", [])]


def seq_ok(entries):
    try:
        ats = [datetime.fromisoformat(e["at"].replace("Z", "+00:00")) for e in entries]
    except Exception:
        return False
    return [e.get("seq") for e in entries] == list(range(1, len(entries) + 1)) and all(p.TS_RE.match(e["at"]) for e in entries) and ats == sorted(ats)


# ---------------------------------------------------------------- sections
def s_explain():
    reset(fx3())
    ta = p.ada()
    b = bk(ta, "t_2", THU, "19:00", 3)
    for i, v in enumerate(["false", "1", "", "TRUE", "yes", "0"]):
        expect(f"P3.EX1{'abcdef'[i]}", "EX1", "Availability explanations", f"explain={v!r}", req("GET", f"/availability?restaurant_id=r_m&date={THU}&party_size=2&explain={v}"), 422, "validation_failed")
    r = avail("r_m", THU, 2)
    sl = (J(r) or {}).get("slots", [])
    check("P3.EX2", "EX2", "Availability explanations", "without explain no slot has an explain field", r.status_code == 200 and sl and all("explain" not in s for s in sl), sl[:1])
    e, r = explain("r_m", THU, 3)
    want19 = [ex_row("t_1", 0, False, True), ex_row("t_2", 0, True, False), ex_row("t_3", 0, True, True)]
    want21 = [ex_row("t_1", 0, False, True), ex_row("t_2", 0, True, True), ex_row("t_3", 0, True, True)]
    check("P3.EX3a", "EX3", "Availability explanations", "explain=true: every table once in fixture order, policy_version, available, both rules in order (capacity-only and overlap-only exclusions)",
          b.status_code == 201 and r.status_code == 200 and e.get("19:00", {}).get("explain") == want19 and e.get("21:00", {}).get("explain") == want21, e.get("19:00"))
    e5, _ = explain("r_m", THU, 5)
    check("P3.EX3b", "EX3", "Availability explanations", "a table excluded by both rules reports both false (party 5, booked t_2)",
          e5.get("19:00", {}).get("explain") == [ex_row("t_1", 0, False, True), ex_row("t_2", 0, False, False), ex_row("t_3", 0, True, True)], e5.get("19:00"))
    bad = [k for k, s in {**e, **{k + "#5": v for k, v in e5.items()}}.items() if [x["table_id"] for x in s.get("explain", []) if x.get("available")] != s.get("available_table_ids")
           or len(s.get("explain", [])) != 3]
    check("P3.EX4", "EX4", "Availability explanations", "in every slot the available table_ids of explain equal available_table_ids in order; every slot explains all 3 tables", len(e) == 8 and not bad, bad)
    e7, _ = explain("r_m", THU, 7)
    check("P3.EX5a", "EX5", "Availability explanations", "party larger than every table: all 8 slots still appear, each with full explain, nothing available",
          len(e7) == 8 and all(s["available_table_ids"] == [] and len(s["explain"]) == 3 and not any(x["available"] for x in s["explain"]) for s in e7.values()), list(e7.values())[:1])
    r = req("GET", "/availability?restaurant_id=r_anker&date=2027-09-22&party_size=2&explain=true")
    check("P3.EX5b", "EX5", "Availability explanations", "closed day with explain -> slots []", r.status_code == 200 and (J(r) or {}).get("slots") == [], show(r))
    check("P3.EX7", "EX3", "stage-2 API", "available_options still present alongside explain", all("available_options" in s for s in e.values()), list(e.values())[:1])
    expect("P3.EX1g", "EX1", "stage-1 §8", "explain=true but party_size missing", req("GET", f"/availability?restaurant_id=r_m&date={THU}&explain=true"), 422, "validation_failed")


def s_history():
    reset(fx3())
    ta, tb, tm = p.ada(), p.bob(), mgr()
    k = K()
    A = bk(ta, "t_2", THU, "19:00", 3, key=k)
    ja = J(A) or {}
    a = ja.get("reference")
    check("P3.TE1a", "TE1", "Policies and accepted terms", "create response carries revision 1 and accepted_terms of policy 0 built from the fixture", A.status_code == 201 and ja.get("revision") == 1 and ja.get("accepted_terms") == TERMS0, show(A))
    r = req("GET", f"/reservations/{a}/history", token=ta)
    h = (J(r) or {}).get("entries") or []
    check("P3.HI1a", "HI1/HI3", "Reservation history", "owner reads history: {reference, entries}; one created entry naming table_id, starts_at_local, party_size with from null",
          r.status_code == 200 and (J(r) or {}).get("reference") == a and len(h) == 1 and h[0].get("event") == "created"
          and changes(h[0]) == [("table_id", None, "t_2"), ("starts_at_local", None, f"{THU}T19:00"), ("party_size", None, 3)], show(r))
    check("P3.HI7a", "HI7", "Policies and accepted terms", "the created entry carries revision 1 and the complete accepted_terms", h and h[0].get("revision") == 1 and h[0].get("accepted_terms") == TERMS0 and h[0].get("seq") == 1 and p.TS_RE.match(str(h[0].get("at"))), h[:1])
    for cid, desc, rr in [("P3.HI1b", "another user", req("GET", f"/reservations/{a}/history", token=tb)), ("P3.HI1c", "the restaurant's manager", req("GET", f"/reservations/{a}/history", token=tm)),
                          ("P3.HI1d", "no token", req("GET", f"/reservations/{a}/history")), ("P3.HI1e", "unknown reference, no token", req("GET", "/reservations/ZZZZZZ99/history")),
                          ("P3.HI1f", "unknown reference, owner token", req("GET", "/reservations/ZZZZZZ99/history", token=ta)),
                          ("P3.DE1b", "decision: another user", dec(tb, a)), ("P3.DE1c", "decision: manager", dec(tm, a)), ("P3.DE1d", "decision: no token", req("GET", f"/reservations/{a}/decision")),
                          ("P3.PO10a", "manager reads a diner's reservation", get(tm, a))]:
        expect(cid, "HI1/DE1/PO10", "Reservation history", f"history/decision by {desc}", rr, 404, "not_found")
    d = dec(ta, a)
    check("P3.DE1a", "DE1", "Policies and accepted terms", "decision -> {reference, revision 1, accepted_terms}", d.status_code == 200 and J(d) == {"reference": a, "revision": 1, "accepted_terms": TERMS0}, show(d))
    r1 = patch(ta, a, {"table_id": "t_3"})
    r2 = patch(ta, a, {"starts_at_local": f"{THU}T20:00", "party_size": 4})
    r3 = patch(ta, a, {"party_size": 4, "table_id": "t_3", "starts_at_local": f"{THU}T20:00"})
    r4 = patch(ta, a, {})
    r5 = patch(ta, a, {"party_size": 2, "starts_at_local": "2027-09-24T21:00", "table_id": "t_2"})
    rp = bk(ta, "t_2", THU, "19:00", 3, key=k)
    h = hist(ta, a) or []
    check("P3.HI4a", "HI4", "Reservation history", "changed entries list only the changed fields, in the order table_id, starts_at_local, party_size, with from/to",
          [x.status_code for x in (r1, r2, r5)] == [200, 200, 200] and len(h) == 4 and [e.get("event") for e in h] == ["created", "changed", "changed", "changed"]
          and changes(h[1]) == [("table_id", "t_2", "t_3")] and changes(h[2]) == [("starts_at_local", f"{THU}T19:00", f"{THU}T20:00"), ("party_size", 3, 4)]
          and changes(h[3]) == [("table_id", "t_3", "t_2"), ("starts_at_local", f"{THU}T20:00", "2027-09-24T21:00"), ("party_size", 4, 2)], [changes(e) for e in h])
    check("P3.HI4b", "HI4/TE5", "Reservation history", "PATCH with the current values and PATCH {} succeed, record no entry and keep the revision",
          r3.status_code == 200 and r4.status_code == 200 and (J(r3) or {}).get("revision") == 3 and (J(r4) or {}).get("revision") == 3 and (J(r3) or {}) == (J(r2) or {}), show(r3))
    check("P3.HI2", "HI2/HI7", "Reservation history", "seq 1..n consecutive, at non-decreasing with offset, entry revisions 1..4; PATCH responses carry revisions 2, 3, 4",
          seq_ok(h) and [e.get("revision") for e in h] == [1, 2, 3, 4] and [(J(x) or {}).get("revision") for x in (r1, r2, r5)] == [2, 3, 4], [(e.get("seq"), e.get("at"), e.get("revision")) for e in h])
    check("P3.HI6", "HI6/TE2", "Reservation history", "replay of the create key -> 200 with the original body (revision 1, original terms) and no new history entry", rp.status_code == 200 and J(rp) == ja and len(hist(ta, a) or []) == 4, show(rp))
    c1 = cancel(ta, a)
    c2 = cancel(ta, a)
    h = hist(ta, a) or []
    check("P3.HI5", "HI5/TE3", "Reservation history", "cancel adds a cancelled entry with changes [] and revision +1; repeated cancel adds nothing and keeps the revision",
          c1.status_code == 200 and (J(c1) or {}).get("revision") == 5 and (J(c2) or {}).get("revision") == 5 and len(h) == 5 and h[-1].get("event") == "cancelled" and h[-1].get("changes") == [] and h[-1].get("revision") == 5 and seq_ok(h), h[-1:])
    d = dec(ta, a)
    check("P3.DE1e", "DE1", "Policies and accepted terms", "decision after cancellation: current revision 5 and terms", d.status_code == 200 and J(d) == {"reference": a, "revision": 5, "accepted_terms": TERMS0}, show(d))
    expect("P3.TE5a", "TE5", "Policies and accepted terms", "no-op PATCH on a cancelled booking", patch(ta, a, {}), 409, "reservation_cancelled")
    l0 = (listing(ta) or [{}])[0]
    check("P3.TE1b", "TE1", "Policies and accepted terms", "list and GET carry revision and accepted_terms", l0.get("revision") == 5 and l0.get("accepted_terms") == TERMS0 and (J(get(ta, a)) or {}) == l0, l0)
    # pairs
    B = bkp(ta, ["t_2", "t_1"], MON, "19:00", 5)
    b = ref(B)
    h = hist(ta, b) or [{}]
    check("P3.HI8a", "HI8", "Combined-table history", "pair created (sent reversed): created entry uses table_ids null -> pair in declared order, no table_id change",
          B.status_code == 201 and changes(h[0]) == [("table_ids", None, ["t_1", "t_2"]), ("starts_at_local", None, f"{MON}T19:00"), ("party_size", None, 5)], changes(h[0]))
    n1 = patch(ta, b, {"table_ids": ["t_2", "t_1"]})
    check("P3.HI8b", "HI8", "Combined-table history", "PATCH with the same pair reversed is not an amendment: 200, no entry, revision 1", n1.status_code == 200 and (J(n1) or {}).get("revision") == 1 and len(hist(ta, b) or []) == 1, show(n1))
    q1 = patch(ta, b, {"table_id": "t_3"})
    q2 = patch(ta, b, {"table_ids": ["t_1", "t_2"], "party_size": 6})
    q3 = patch(ta, b, {"table_id": "t_3"})
    q4 = patch(ta, b, {"table_ids": ["t_2"], "party_size": 4})
    h = hist(ta, b) or []
    check("P3.HI8c", "HI8", "Combined-table history", "pair -> single and single -> pair use table_ids with complete before/after lists; single -> single uses table_id",
          [x.status_code for x in (q1, q2, q3, q4)] == [200] * 4 and len(h) == 5 and changes(h[1]) == [("table_ids", ["t_1", "t_2"], ["t_3"])]
          and changes(h[2]) == [("table_ids", ["t_3"], ["t_1", "t_2"]), ("party_size", 5, 6)] and changes(h[3]) == [("table_ids", ["t_1", "t_2"], ["t_3"])] and changes(h[4]) == [("table_id", "t_3", "t_2"), ("party_size", 6, 4)], [changes(e) for e in h])
    jq = J(q2) or {}
    check("P3.TE1c", "TE1", "Combined-table history", "PATCH response of a pair carries revision and accepted_terms", jq.get("revision") == 3 and jq.get("accepted_terms") == TERMS0 and jq.get("table_ids") == ["t_1", "t_2"], jq)
    # seeded
    reset(fx3(reservations=[{"id": "s1", "reference": "SEEDED01", "user_id": "u_ada", "restaurant_id": "r_m", "table_id": "t_2", "starts_at_local": f"{THU}T19:00", "party_size": 2}]))
    ta = p.ada()
    g = J(get(ta, "SEEDED01")) or {}
    h = hist(ta, "SEEDED01") or []
    check("P3.TE2a", "TE2", "Policies and accepted terms", "seeded booking: revision 1 under policy 0", g.get("revision") == 1 and g.get("accepted_terms") == TERMS0, g)
    check("P3.TE2b", "TE2", "map decision 4", "seeded booking history: one created entry, seq 1, revision 1", len(h) == 1 and h[0].get("event") == "created" and h[0].get("seq") == 1 and h[0].get("revision") == 1, h)


def s_policies():
    reset(fx3())
    ta, tm = p.ada(), mgr()
    before = J(req("GET", "/restaurants/r_m"))
    P1 = pol("2027-10-04", slot=60, dur=120, cutoff=60, hrs=hours("17:00", "23:00"), caps={"t_1": 4, "t_2": 4, "t_3": 8})
    expect("P3.PO2a", "PO2", "Policies", "publish without token", req("POST", "/restaurants/r_m/policies", key=K(), body=P1), 401, "unauthenticated")
    expect("P3.PO2b", "PO2", "Policies", "publish to an unknown restaurant (manager token)", publish(tm, P1, rid="r_nope"), 404, "not_found")
    expect("P3.PO2c", "PO2", "Policies", "publish by an authenticated non-manager", publish(ta, P1), 403, "forbidden")
    expect("P3.PO2d", "PO2", "Policies", "publish to a restaurant with no managers (default [])", publish(tm, pol("2027-10-04", caps={"t_1": 2, "t_2": 4}), rid="r_anker"), 403, "forbidden")
    expect("P3.PO2e", "PO2", "stage-1 §7", "publish without Idempotency-Key", req("POST", "/restaurants/r_m/policies", token=tm, body=P1), 400, "missing_idempotency_key")
    r = req("GET", "/restaurants/r_m/policies")
    check("P3.PO5a", "PO5", "Policies", "GET policies is public; empty before any publication (policy 0 omitted)", r.status_code == 200 and J(r) == {"policies": []}, show(r))
    expect("P3.PO5b", "PO5", "Policies", "GET policies of an unknown restaurant", req("GET", "/restaurants/r_nope/policies"), 404, "not_found")
    # bookings accepted under policy 0 before any publication
    B = bk(ta, "t_2", "2027-10-07", "19:00", 3)
    B2 = bk(ta, "t_3", "2027-10-07", "19:30", 3)
    hb = hist(ta, ref(B))
    k1 = K()
    r1 = publish(tm, dict(P1, note="ignored", timezone="UTC"), key=k1)
    j1 = J(r1) or {}
    check("P3.PO4a", "PO4", "Policies", "201 returns the supplied policy plus policy_version 1 (unknown fields ignored)", r1.status_code == 201 and all(j1.get(k) == v for k, v in P1.items()) and j1.get("policy_version") == 1, show(r1))
    r1b = publish(tm, dict(P1, note="ignored", timezone="UTC"), key=k1)
    check("P3.PO2f", "PO2", "stage-1 §7", "replay -> 200 identical body, no new version", r1b.status_code == 200 and J(r1b) == j1, show(r1b))
    expect("P3.PO2g", "PO2", "stage-1 §7", "same key, different policy body", publish(tm, dict(P1, slot_minutes=30), key=k1), 409, "idempotency_key_reuse")
    check("P3.PO6", "PO6", "Policies", "restaurant detail still returns the original fixture configuration", J(req("GET", "/restaurants/r_m")) == before, "")
    check("P3.PO9a", "PO9", "Policies", "publication changed no existing booking (body, ends_at, terms, revision) nor its history", J(get(ta, ref(B))) == J(B) and hist(ta, ref(B)) == hb and (J(B) or {}).get("ends_at", "").startswith("2027-10-07T20:30"), J(get(ta, ref(B))))
    s = slots("r_m", "2027-10-07", 2)
    got = {k[-5:]: ("t_2" in v["available_table_ids"], "t_3" in v["available_table_ids"]) for k, v in s.items()}
    check("P3.PO8a", "PO8", "Policies", "availability uses the selected policy's grid/hours/duration (17:00..21:00 hourly, 120 min) and each booking's own stored interval (t_2 19:00-20:30, t_3 19:30-21:00)",
          got == {"17:00": (True, True), "18:00": (False, False), "19:00": (False, False), "20:00": (False, False), "21:00": (True, True)}, got)
    s0 = slots("r_m", THU, 2)
    check("P3.PO7a", "PO7", "Policies", "a date before effective_from keeps policy 0 (half-hour grid 18:00..21:30)", [k[-5:] for k in s0] == ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30"], list(s0))
    o = [(x["table_ids"], x["capacity"]) for x in s["2027-10-07T17:00"].get("available_options", [])]
    e, _ = explain("r_m", "2027-10-07", 3)
    check("P3.PO8b", "PO8/EX6", "Policies", "capacities come from the selected policy: options t_1=4, pair=8; explain policy_version 1 and capacity rule holds for t_1 with party 3",
          o == [(["t_1"], 4), (["t_2"], 4), (["t_3"], 8), (["t_1", "t_2"], 8)] and e["17:00"]["explain"][0] == ex_row("t_1", 1, True, True), f"{o} {e['17:00']['explain'][0]}")
    e0, _ = explain("r_m", THU, 3)
    check("P3.EX6", "EX6", "Policies", "explain on a policy-0 date reports policy_version 0 and the fixture capacity", e0["19:00"]["explain"][0] == ex_row("t_1", 0, False, True), e0["19:00"]["explain"][0])
    C = bk(ta, "t_3", "2027-10-07", "17:00", 8)
    jc = J(C) or {}
    check("P3.PO8c", "PO8/TE1", "Policies", "booking under policy 1: capacity 8 accepted, ends_at = start + 120 min, accepted_terms = whole policy without effective_from, revision 1",
          C.status_code == 201 and p.same_ts(jc.get("ends_at"), "2027-10-07T19:00:00+02:00") and jc.get("accepted_terms") == terms_of(P1, 1) and jc.get("revision") == 1, show(C))
    expect("P3.PO8d", "PO8", "Policies", "18:30 is off the policy's hourly grid", bk(ta, "t_1", "2027-10-07", "18:30", 2), 422, "not_on_slot_grid")
    expect("P3.PO8e", "PO8", "Policies", "22:00 + 120 min ends after closes", bk(ta, "t_1", "2027-10-07", "22:00", 2), 422, "outside_opening_hours")
    expect("P3.PO8f", "PO8", "Policies", "party 4 on t_1 allowed by the policy capacity (fixture says 2)", bk(ta, "t_1", "2027-10-07", "21:00", 4), 201)
    expect("P3.PO8g", "PO8", "Policies", "party 3 on t_1 on a policy-0 date", bk(ta, "t_1", THU, "19:00", 3), 422, "party_exceeds_capacity")
    r = bkp(ta, ["t_1", "t_2"], "2027-10-07", "17:00", 9)
    expect("P3.PO8h", "PO8", "Combined-table history", "pair party 9 > summed policy capacity 8", r, 422, "party_exceeds_capacity")
    r = bkp(ta, ["t_1", "t_2"], "2027-10-07", "17:00", 8)
    check("P3.PO8i", "PO8", "Combined-table history", "pair party 8 = summed policy capacity -> 201 with policy-1 terms", r.status_code == 201 and (J(r) or {}).get("accepted_terms", {}).get("policy_version") == 1, show(r))
    # TE4/TE5/TE6 on bookings accepted under policy 0, now governed by policy 1
    n = patch(ta, ref(B2), {"party_size": 3})
    check("P3.TE5b", "TE5", "Policies and accepted terms", "no-op amendment of a policy-0 booking keeps terms, ends_at and revision (even though 19:30 is off the new grid)", n.status_code == 200 and J(n) == J(B2), show(n))
    f = patch(ta, ref(B2), {"party_size": 2})
    check("P3.TE6", "TE4/TE6", "Policies and accepted terms", "real amendment validates all resulting fields against the resulting date's policy: unchanged 19:30 start is off policy 1's grid -> 422 not_on_slot_grid, nothing changed",
          f.status_code == 422 and code(f) == "not_on_slot_grid" and J(get(ta, ref(B2))) == J(B2) and len(hist(ta, ref(B2)) or []) == 1, show(f))
    cancel(ta, ref(B2))
    a = patch(ta, ref(B), {"party_size": 4})
    ja = J(a) or {}
    h = hist(ta, ref(B)) or []
    check("P3.TE4a", "TE4", "Policies and accepted terms", "real amendment (party) of a policy-0 booking: terms replaced by policy 1, ends_at now start + 120 min, revision 2",
          a.status_code == 200 and ja.get("accepted_terms") == terms_of(P1, 1) and p.same_ts(ja.get("ends_at"), "2027-10-07T21:00:00+02:00") and ja.get("revision") == 2, show(a))
    check("P3.HI7b", "HI7", "Policies and accepted terms", "history: entry 1 keeps policy-0 terms, entry 2 carries policy-1 terms and revision 2", len(h) == 2 and h[0].get("accepted_terms") == TERMS0 and h[1].get("accepted_terms") == terms_of(P1, 1) and h[1].get("revision") == 2 and changes(h[1]) == [("party_size", 3, 4)], h)
    m = patch(ta, ref(B), {"starts_at_local": f"{THU}T21:30"})
    jm = J(m) or {}
    check("P3.TE4b", "TE4/PO7", "Policies and accepted terms", "amendment moving the booking to a policy-0 date adopts policy 0 (terms, 90 min end), revision 3", m.status_code == 200 and jm.get("accepted_terms") == TERMS0 and p.same_ts(jm.get("ends_at"), f"{THU}T23:00:00+02:00") and jm.get("revision") == 3, show(m))
    # selection: ties, later-published earlier date, past date
    P2 = pol("2027-10-04", slot=30, dur=60, cutoff=0)
    P3_ = pol("2027-10-06", slot=30, dur=90, cutoff=10)
    P4 = pol("2027-09-27", slot=30, dur=90, cutoff=20)
    rs = [publish(tm, x) for x in (P2, P3_, P4)]
    vers = [(J(x) or {}).get("policy_version") for x in rs]
    ver = lambda day: (explain("r_m", day, 1)[0].get("19:00") or {"explain": [{}]})["explain"][0].get("policy_version")
    sel = {d: ver(d) for d in (THU, "2027-09-27", "2027-10-03", "2027-10-04", "2027-10-05", "2027-10-06", "2027-10-07")}
    check("P3.PO7b", "PO7/PO4", "Policies", "versions 2,3,4; selection = greatest effective_from <= date, tie on 10-04 -> greatest version (2), later-published earlier-dated policy 4 applies from 09-27",
          vers == [2, 3, 4] and sel == {THU: 0, "2027-09-27": 4, "2027-10-03": 4, "2027-10-04": 2, "2027-10-05": 2, "2027-10-06": 3, "2027-10-07": 3}, f"{vers} {sel}")
    check("P3.PO9b", "PO9", "Policies", "the booking accepted under policy 1 is unchanged by the superseding same-date policy", J(get(ta, ref(C))) == jc, J(get(ta, ref(C))))
    P5 = pol("2020-01-01", slot=30, dur=90, cutoff=5)
    r5 = publish(tm, P5)
    check("P3.PO7c", "PO7/PO9", "Policies", "effective date in the past allowed (version 5): now selected for 09-23; the booking already on that date keeps its terms and revision", r5.status_code == 201 and (J(r5) or {}).get("policy_version") == 5 and ver(THU) == 5 and J(get(ta, ref(B))) == jm, show(r5))
    r = req("GET", "/restaurants/r_m/policies")
    pl = (J(r) or {}).get("policies") or []
    check("P3.PO5c", "PO5/PO4", "Policies", "GET policies: publication order, versions 1..5, each equal to its 201 body", [x.get("policy_version") for x in pl] == [1, 2, 3, 4, 5] and pl[0] == j1 and pl[4] == J(r5), [x.get("policy_version") for x in pl])


def s_policy_validation():
    reset(fx3())
    tm = mgr()
    good = pol("2099-01-01")
    cases = []
    for k in good:
        cases.append((f"missing {k}", {x: y for x, y in good.items() if x != k}))
    for v in ("2027-02-30", "27-10-04", "2027/10/04", 20271004, None):
        cases.append((f"effective_from {v!r}", dict(good, effective_from=v)))
    for f in ("slot_minutes", "reservation_duration_minutes"):
        for v in (0, 1441, "30", True, 30.5, -5):
            cases.append((f"{f} {v!r}", dict(good, **{f: v})))
    for v in (-1, 10081, True, "60", 1.5):
        cases.append((f"cancellation_cutoff_minutes {v!r}", dict(good, cancellation_cutoff_minutes=v)))
    cases += [("opening_hours duplicate weekday", dict(good, opening_hours=[{"weekday": "mon", "opens": "18:00", "closes": "23:00"}, {"weekday": "mon", "opens": "10:00", "closes": "12:00"}])),
              ("opening_hours closes <= opens", dict(good, opening_hours=[{"weekday": "mon", "opens": "18:00", "closes": "18:00"}])),
              ("opening_hours bad weekday", dict(good, opening_hours=[{"weekday": "monday", "opens": "18:00", "closes": "23:00"}])),
              ("opening_hours bad time", dict(good, opening_hours=[{"weekday": "mon", "opens": "25:00", "closes": "26:00"}])),
              ("opening_hours not a list", dict(good, opening_hours="always")),
              ("capacities missing a table", dict(good, capacities={"t_1": 2, "t_2": 4})),
              ("capacities with an unknown table", dict(good, capacities={"t_1": 2, "t_2": 4, "t_3": 6, "t_9": 2})),
              ("capacity 0", dict(good, capacities={"t_1": 0, "t_2": 4, "t_3": 6})), ("capacity 101", dict(good, capacities={"t_1": 101, "t_2": 4, "t_3": 6})),
              ("capacity string", dict(good, capacities={"t_1": "2", "t_2": 4, "t_3": 6})), ("capacity boolean", dict(good, capacities={"t_1": True, "t_2": 4, "t_3": 6})),
              ("capacities not an object", dict(good, capacities=[2, 4, 6]))]
    bad = []
    for desc, body in cases:
        r = publish(tm, body)
        if not (r.status_code == 422 and code(r) == "validation_failed"):
            bad.append(f"{desc}: {show(r)[:160]}")
    check("P3.PO3a", "PO3", "Policies", f"{len(cases)} invalid policies each -> 422 validation_failed", not bad, bad[:6])
    r = req("GET", "/restaurants/r_m/policies")
    check("P3.PO3b", "PO3", "Policies", "no version or state change after the rejected policies", J(r) == {"policies": []}, show(r))
    kf = K()
    f1 = publish(tm, dict(good, slot_minutes=0), key=kf)
    f2 = publish(tm, good, key=kf)
    check("P3.PO2h", "PO2/PO4", "stage-1 §7", "key of a failed publication is a first use; the first valid policy gets version 1", f1.status_code == 422 and f2.status_code == 201 and (J(f2) or {}).get("policy_version") == 1, show(f2))
    okc = [("slot 1", dict(good, slot_minutes=1)), ("slot 1440", dict(good, slot_minutes=1440)), ("duration 1", dict(good, reservation_duration_minutes=1)),
           ("duration 1440", dict(good, reservation_duration_minutes=1440)), ("cutoff 0", dict(good, cancellation_cutoff_minutes=0)), ("cutoff 10080", dict(good, cancellation_cutoff_minutes=10080)),
           ("capacity 1 and 100", dict(good, capacities={"t_1": 1, "t_2": 100, "t_3": 6}))]
    bad, vers = [], []
    for desc, body in okc:
        r = publish(tm, body)
        vers.append((J(r) or {}).get("policy_version"))
        if r.status_code != 201:
            bad.append(f"{desc}: {show(r)[:160]}")
    check("P3.PO3c", "PO3/PO4", "Policies", "boundary values accepted (1/1440, 1/1440, 0/10080, capacity 1/100); versions continue 2..8", not bad and vers == list(range(2, 9)), f"{bad[:3]} {vers}")
    kc = K()
    rs = parallel([(lambda: publish(tm, good, key=kc)) for _ in range(20)])
    sts = sorted(x.status_code for x in rs)
    check("P3.PO2i", "PO2", "stage-1 §7", "20 concurrent identical publications: one 201, nineteen 200, identical body", sts == [200] * 19 + [201] and len({json.dumps(J(x), sort_keys=True) for x in rs}) == 1, sts)
    rs = parallel([(lambda i=i: publish(tm, pol(f"2099-02-{i + 1:02d}"))) for i in range(20)])
    pl = (J(req("GET", "/restaurants/r_m/policies")) or {}).get("policies") or []
    check("P3.PO4b", "PO4/CC3", "Policies", "20 concurrent distinct publications: all 201, versions distinct; all versions 1..29 gap-free in publication order",
          all(x.status_code == 201 for x in rs) and sorted((J(x) or {}).get("policy_version") for x in rs) == list(range(10, 30)) and [x.get("policy_version") for x in pl] == list(range(1, 30)), [x.get("policy_version") for x in pl])
    expect("P3.PO1a", "PO1", "stage-1 §5", "reset: manager_user_ids a string", reset(fx3(rests=[rest_m(manager_user_ids="u_mgr")])), 400, "malformed_request")
    expect("P3.PO1b", "PO1", "stage-1 §5", "reset: manager_user_ids member a number", reset(fx3(rests=[rest_m(manager_user_ids=[5])])), 400, "malformed_request")
    expect("P3.PO1c", "PO1", "Policies", "reset: manager_user_ids empty list", reset(fx3(rests=[rest_m(manager_user_ids=[])])), 204)


def s_cutoff_terms():
    reset(fx3())
    ta, tm = p.ada(), mgr()
    near = p.slot_after(60)
    day = (datetime.fromisoformat(near) - timedelta(days=2)).date().isoformat()
    caps = {"w_1": 4, "w_2": 4}
    N = book(ta, "r_now", "w_1", near, 2)
    N2 = book(ta, "r_now", "w_2", near, 2)
    r = publish(tm, pol(day, slot=15, dur=15, cutoff=600, hrs=hours("00:00", "23:59"), caps=caps), rid="r_now")
    check("P3.TE3a", "TE3", "Policies and accepted terms", "setup: bookings ~1 h ahead accepted with cutoff 30, then a cutoff-600 policy published for today", N.status_code == 201 and N2.status_code == 201 and r.status_code == 201, show(N) + show(r))
    pa = patch(ta, ref(N2), {"party_size": 3})
    check("P3.TE4c", "TE4", "Policies and accepted terms", "real amendment checks the OLD accepted cutoff (30 min) -> 200, then adopts the new policy's terms (cutoff 600)", pa.status_code == 200 and (J(pa) or {}).get("accepted_terms", {}).get("cancellation_cutoff_minutes") == 600, show(pa))
    expect("P3.TE4d", "TE4/TE3", "Policies and accepted terms", "after that amendment the newly accepted cutoff (600) locks the booking: cancel", cancel(ta, ref(N2)), 409, "cutoff_passed")
    expect("P3.TE5c", "TE5", "Policies and accepted terms", "no-op amendment still requires an editable booking", patch(ta, ref(N2), {}), 409, "cutoff_passed")
    c = cancel(ta, ref(N))
    check("P3.TE3b", "TE3", "Policies and accepted terms", "cancel checks the accepted cutoff (30), not the current policy's (600) -> 200, revision 2", c.status_code == 200 and (J(c) or {}).get("revision") == 2, show(c))
    M = book(ta, "r_now", "w_1", near, 2)
    r = publish(tm, pol(day, slot=15, dur=15, cutoff=0, hrs=hours("00:00", "23:59"), caps=caps), rid="r_now")
    check("P3.TE3c", "TE3", "Policies and accepted terms", "booking accepted under cutoff 600 stays locked after a cutoff-0 policy: cancel -> 409 cutoff_passed",
          M.status_code == 201 and (J(M) or {}).get("accepted_terms", {}).get("cancellation_cutoff_minutes") == 600 and r.status_code == 201 and cancel(ta, ref(M)).status_code == 409, show(M))
    # expected_revision
    A = bk(ta, "t_2", THU, "19:00", 2)
    a = ref(A)
    P_ = bk(ta, "t_3", PAST_THU, "19:00", 2)
    bad = []
    for v in (0, -1, "1", True, 1.5, None):
        r = patch(ta, a, {"party_size": 3, "expected_revision": v})
        if not (r.status_code == 422 and code(r) == "validation_failed"):
            bad.append(f"{v!r}: {show(r)[:140]}")
    check("P3.TE7a", "TE7", "Policies and accepted terms", "expected_revision 0, -1, '1', true, 1.5, null -> 422 validation_failed", not bad, bad)
    expect("P3.TE7b", "TE7", "Policies and accepted terms", "expected_revision differing from the current revision", patch(ta, a, {"party_size": 3, "expected_revision": 2}), 409, "stale_revision")
    expect("P3.TE7c", "TE7", "Policies and accepted terms", "stale expected_revision comes before validation (invalid party_size)", patch(ta, a, {"party_size": 0, "expected_revision": 7}), 409, "stale_revision")
    expect("P3.TE7d", "TE7", "Policies and accepted terms", "stale expected_revision comes before the cutoff check (past booking)", patch(ta, ref(P_), {"party_size": 1, "expected_revision": 7}), 409, "stale_revision")
    expect("P3.TE7e", "TE7", "Policies and accepted terms", "matching expected_revision on a past booking -> cutoff", patch(ta, ref(P_), {"party_size": 1, "expected_revision": 1}), 409, "cutoff_passed")
    check("P3.TE7f", "TE6", "Policies and accepted terms", "refused PATCHes changed nothing", J(get(ta, a)) == J(A) and len(hist(ta, a) or []) == 1, "")
    r = patch(ta, a, {"party_size": 3, "expected_revision": 1, "whatever": 1})
    check("P3.TE7g", "TE7", "Policies and accepted terms", "matching expected_revision (unknown field ignored) -> 200, revision 2", r.status_code == 200 and (J(r) or {}).get("revision") == 2, show(r))
    r = patch(ta, a, {"party_size": 3, "expected_revision": 2})
    check("P3.TE7h", "TE7/TE5", "Policies and accepted terms", "matching expected_revision with a no-op -> 200, revision stays 2", r.status_code == 200 and (J(r) or {}).get("revision") == 2, show(r))
    rs = parallel([(lambda i=i: patch(ta, a, {"starts_at_local": f"{THU}T{18 + i // 2:02d}:{(i % 2) * 30:02d}", "party_size": 1 + i % 2, "expected_revision": 2})) for i in range(8)] * 3)
    sts = sorted(x.status_code for x in rs)
    g = J(get(ta, a)) or {}
    check("P3.TE8", "TE8", "Policies and accepted terms", "24 concurrent real amendments with one expected_revision: exactly one 200, the rest 409 stale_revision; revision 3, one new history entry",
          sts == [200] + [409] * 23 and all(code(x) == "stale_revision" for x in rs if x.status_code == 409) and g.get("revision") == 3 and len(hist(ta, a) or []) == 3, f"{sts} rev={g.get('revision')}")


def s_series():
    reset(fx3())
    ta, tb, tm = p.ada(), p.bob(), mgr()
    PD = pol("2027-11-01", dur=60)
    publish(tm, PD)
    ka = K()
    A = bk(ta, "t_2", MON, "19:00", 3, key=ka)
    a = ref(A)
    ha = hist(ta, a)
    expect("P3.SE1a", "SE1", "Recurring reservations", "POST /series without token", req("POST", "/series", key=K(), body={"anchor_reference": a, "count": 3, "interval_weeks": 1}), 401, "unauthenticated")
    expect("P3.SE1b", "SE1", "stage-1 §7", "POST /series without Idempotency-Key", req("POST", "/series", token=ta, body={"anchor_reference": a, "count": 3, "interval_weeks": 1}), 400, "missing_idempotency_key")
    bad = []
    for desc, c, w in [("count 1", 1, 1), ("count 13", 13, 1), ("count '3'", "3", 1), ("count true", True, 1), ("count 2.5", 2.5, 1), ("count 0", 0, 1), ("interval 0", 3, 0), ("interval 5", 3, 5), ("interval true", 3, True), ("interval '1'", 3, "1")]:
        r = series(ta, a, c, w)
        if not (r.status_code == 422 and code(r) == "validation_failed"):
            bad.append(f"{desc}: {show(r)[:140]}")
    for desc, body in [("count missing", {"anchor_reference": a, "interval_weeks": 1}), ("interval_weeks missing", {"anchor_reference": a, "count": 3}), ("anchor_reference missing", {"count": 3, "interval_weeks": 1})]:
        r = req("POST", "/series", token=ta, key=K(), body=body)
        if not (r.status_code == 422 and code(r) == "validation_failed"):
            bad.append(f"{desc}: {show(r)[:140]}")
    check("P3.SE2a", "SE2", "Recurring reservations", "invalid count / interval_weeks (incl. booleans, strings, floats, missing) -> 422 validation_failed", not bad, bad[:5])
    expect("P3.SE3a", "SE3", "Recurring reservations", "unknown anchor", series(ta, "ZZZZZZ99", 3, 1), 404, "not_found")
    expect("P3.SE3b", "SE3", "Recurring reservations", "another owner's anchor", series(tb, a, 3, 1), 404, "not_found")
    X = bk(ta, "t_3", MON, "21:00", 2)
    cancel(ta, ref(X))
    expect("P3.SE3c", "SE3", "Recurring reservations", "cancelled anchor", series(ta, ref(X), 3, 1), 409, "reservation_cancelled")
    Pst = bk(ta, "t_3", PAST_THU, "19:00", 2)
    expect("P3.SE3d", "SE3", "Recurring reservations", "anchor past its accepted cutoff", series(ta, ref(Pst), 2, 1), 409, "cutoff_passed")
    n0 = len(listing(ta) or [])
    ks = K()
    S = series(ta, a, 12, 1, key=ks, color="blue")
    js = J(S) or {}
    occ = js.get("occurrences") or []
    days = [(date.fromisoformat(MON) + timedelta(days=7 * i)).isoformat() for i in range(12)]
    check("P3.SE7a", "SE7/SE2", "Recurring reservations", "201 {series_id, revision 1, interval_weeks 1, occurrences} with 12 occurrences (count 12, unknown field ignored), indices 0..11, distinct references, exception false",
          S.status_code == 201 and isinstance(js.get("series_id"), str) and js.get("revision") == 1 and js.get("interval_weeks") == 1 and [o.get("index") for o in occ] == list(range(12))
          and len({o.get("reference") for o in occ}) == 12 and all(o.get("exception") is False and o.get("reference") == o.get("reservation", {}).get("reference") for o in occ), show(S)[:400])
    check("P3.SE4a", "SE4", "Recurring reservations", "occurrence 0 is the anchor, unchanged: same body, history and create replay",
          occ and occ[0].get("reference") == a and occ[0].get("reservation") == J(A) and J(get(ta, a)) == J(A) and hist(ta, a) == ha and J(bk(ta, "t_2", MON, "19:00", 3, key=ka)) == J(A), occ[:1])
    rs_ = [o.get("reservation", {}) for o in occ]
    check("P3.SE4b", "SE4", "Recurring reservations", "occurrence i starts on anchor date + 7*i days at 19:00 local, with the anchor's party size and table; offsets follow DST (+02:00 until 10-25, +01:00 from 11-01)",
          [x.get("starts_at_local") for x in rs_] == [f"{d}T19:00" for d in days] and all(x.get("party_size") == 3 and x.get("table_ids") == ["t_2"] and x.get("status") == "confirmed" for x in rs_)
          and all(p.same_ts(x.get("starts_at"), f"{d}T19:00:00{'+02:00' if d < '2027-10-31' else '+01:00'}") for x, d in zip(rs_, days)), [x.get("starts_at") for x in rs_])
    check("P3.SE5a", "SE5", "Recurring reservations", "each generated occurrence selects its own date's policy: before 11-01 policy 0 (ends 20:30), from 11-01 policy 1 (ends 20:00, terms version 1); all revision 1",
          all(x.get("revision") == 1 for x in rs_) and all((x.get("accepted_terms") == TERMS0 and x.get("ends_at", "")[11:16] == "20:30") if d < "2027-11-01" else (x.get("accepted_terms") == terms_of(PD, 1) and x.get("ends_at", "")[11:16] == "20:00") for x, d in zip(rs_, days)),
          [(x.get("ends_at"), x.get("accepted_terms", {}).get("policy_version")) for x in rs_])
    la = listing(ta) or []
    h3 = hist(ta, occ[3]["reference"]) if len(occ) > 3 else None
    check("P3.SE7b", "SE7", "Recurring reservations", "generated occurrences appear in the reservation list, have a created history (seq 1, revision 1) and occupy their table",
          len(la) == n0 + 11 and h3 and len(h3) == 1 and h3[0].get("event") == "created" and changes(h3[0]) == [("table_id", None, "t_2"), ("starts_at_local", None, f"{days[3]}T19:00"), ("party_size", None, 3)]
          and "t_2" not in (slots("r_m", days[3], 2).get(f"{days[3]}T19:00") or {}).get("available_table_ids", ["t_2"]), f"n={len(la)} h={h3}")
    g = getseries(ta, js.get("series_id"))
    check("P3.SE8a", "SE8", "Recurring reservations", "GET /series/{id} by the owner returns the same shape and current state", g.status_code == 200 and J(g) == js, show(g)[:300])
    for cid, desc, rr in [("P3.SE8b", "another user", getseries(tb, js.get("series_id"))), ("P3.SE8c", "no token", req("GET", f"/series/{js.get('series_id')}")), ("P3.SE8d", "unknown id", getseries(ta, "nope")),
                          ("P3.PO10b", "the restaurant's manager", getseries(tm, js.get("series_id")))]:
        expect(cid, "SE8/PO10", "Recurring reservations", f"GET /series by {desc}", rr, 404, "not_found")
    S2 = series(ta, a, 12, 1, key=ks, color="blue")
    check("P3.SE1c", "SE1", "stage-1 §7", "replay -> 200 identical", S2.status_code == 200 and J(S2) == js, show(S2)[:200])
    expect("P3.SE1d", "SE1", "stage-1 §7", "same key, different body", series(ta, a, 11, 1, key=ks), 409, "idempotency_key_reuse")
    expect("P3.SE3e", "SE3", "Recurring reservations", "anchor already adopted", series(ta, a, 2, 1), 409, "already_in_series")
    expect("P3.SE3f", "SE3", "Recurring reservations", "a generated occurrence used as anchor", series(ta, occ[2]["reference"], 2, 1), 409, "already_in_series")
    sid = js.get("series_id")
    cur = lambda: J(getseries(ta, sid)) or {}
    r = patch(ta, occ[3]["reference"], {"party_size": 2})
    c1 = cur()
    check("P3.SE9a", "SE9", "Recurring reservations", "real PATCH of occurrence 3: exception true, series revision 2, current reservation state shown, reference and index unchanged; others untouched",
          r.status_code == 200 and c1.get("revision") == 2 and c1["occurrences"][3].get("exception") is True and c1["occurrences"][3].get("reservation") == J(r) and c1["occurrences"][3].get("reference") == occ[3]["reference"]
          and [o.get("exception") for o in c1["occurrences"]].count(True) == 1, show(r)[:200])
    n1 = patch(ta, occ[4]["reference"], {"party_size": 3})
    f1 = patch(ta, occ[4]["reference"], {"party_size": 99})
    check("P3.SE9b", "SE9", "Recurring reservations", "no-op PATCH (200) and failed PATCH (422) of occurrence 4 change neither the exception flag nor the series revision", n1.status_code == 200 and f1.status_code == 422 and cur() == c1, cur().get("revision"))
    r = patch(ta, occ[3]["reference"], {"table_id": "t_3", "starts_at_local": f"{days[3]}T20:00"})
    c2 = cur()
    check("P3.SE9c", "SE9", "Recurring reservations", "second real PATCH (table and time): series revision 3, still an exception, same reference/index", r.status_code == 200 and c2.get("revision") == 3 and c2["occurrences"][3].get("exception") is True and c2["occurrences"][3].get("reference") == occ[3]["reference"], c2.get("revision"))
    x1 = cancel(ta, occ[5]["reference"])
    c3 = cur()
    x2 = cancel(ta, occ[5]["reference"])
    check("P3.SE10a", "SE10", "Recurring reservations", "cancel of occurrence 5: series revision 4, occurrence retained as cancelled, not an exception; repeated cancel changes nothing",
          x1.status_code == 200 and c3.get("revision") == 4 and len(c3["occurrences"]) == 12 and c3["occurrences"][5]["reservation"].get("status") == "cancelled" and c3["occurrences"][5].get("exception") is False and x2.status_code == 200 and cur() == c3, c3.get("revision"))
    x3 = cancel(ta, a)
    c4 = cur()
    check("P3.SE10b", "SE10", "Recurring reservations", "cancelling the anchor: series revision 5, siblings stay confirmed", x3.status_code == 200 and c4.get("revision") == 5 and c4["occurrences"][0]["reservation"].get("status") == "cancelled"
          and [o["reservation"].get("status") for o in c4["occurrences"]].count("confirmed") == 10, c4.get("revision"))
    S3 = series(ta, a, 12, 1, key=ks, color="blue")
    check("P3.SE11", "SE11", "Recurring reservations", "replay after later changes -> 200 with the original series response; no counter changed", S3.status_code == 200 and J(S3) == js and cur() == c4, show(S3)[:200])
    # count 2 / interval 4, pair anchor
    Bp = bkp(ta, ["t_2", "t_1"], TUE, "21:00", 5)
    Sp = series(ta, ref(Bp), 2, 4)
    op = (J(Sp) or {}).get("occurrences") or [{}, {}]
    check("P3.SE4c", "SE4/SE2", "Recurring reservations", "count 2, interval_weeks 4 with a pair anchor: occurrence 1 on anchor date + 28 days, same pair and party; interval_weeks echoed",
          Sp.status_code == 201 and (J(Sp) or {}).get("interval_weeks") == 4 and len(op) == 2 and op[1].get("reservation", {}).get("starts_at_local") == "2027-10-19T21:00" and op[1]["reservation"].get("table_ids") == ["t_1", "t_2"]
          and "table_id" not in op[1]["reservation"] and op[1]["reservation"].get("party_size") == 5, show(Sp)[:300])
    hp = hist(ta, op[1].get("reference")) or [{}]
    check("P3.HI8d", "HI8", "Combined-table history", "generated pair occurrence: created entry uses table_ids", changes(hp[0])[:1] == [("table_ids", None, ["t_1", "t_2"])], changes(hp[0]))


def s_series_failures():
    reset(fx3())
    ta, tb, tm = p.ada(), p.bob(), mgr()
    A = bk(ta, "t_1", TUE, "19:00", 2)
    a = ref(A)
    blk = bk(tb, "t_1", "2027-10-05", "19:30", 2)                # index 2 overlaps
    publish(tm, pol("2027-10-11", caps={"t_1": 1, "t_2": 4, "t_3": 6}))    # index 3 (10-12): party 2 > 1
    n0, snap0 = len(listing(ta) or []), J(avail("r_m", "2027-09-28", 2))
    kx = K()
    f = series(ta, a, 4, 1, key=kx)
    check("P3.SE5b", "SE5", "Recurring reservations", "first failing occurrence in index order decides: index 2 overlaps (409 table_unavailable) although index 3 would exceed capacity", blk.status_code == 201 and f.status_code == 409 and code(f) == "table_unavailable", show(f))
    check("P3.SE6a", "SE6", "Recurring reservations", "failed adoption left nothing: no new reservations, index-1 slot still free, anchor unchanged and not in a series",
          len(listing(ta) or []) == n0 and J(avail("r_m", "2027-09-28", 2)) == snap0 and J(get(ta, a)) == J(A) and len(hist(ta, a) or []) == 1, len(listing(ta) or []))
    cancel(tb, ref(blk))
    f = series(ta, a, 4, 1, key=kx)
    check("P3.SE5c", "SE5/SE6", "Recurring reservations", "same key and body after the blocker is gone: evaluated again as a first use, now index 3 fails on its date's policy capacity (422 party_exceeds_capacity)", f.status_code == 422 and code(f) == "party_exceeds_capacity", show(f))
    ok = series(ta, a, 3, 1, key=kx)
    check("P3.SE6b", "SE6", "Recurring reservations", "the key of the failed adoptions is reusable: count 3 -> 201 (anchor not marked adopted by the failures)", ok.status_code == 201 and len((J(ok) or {}).get("occurrences") or []) == 3, show(ok)[:200])
    # DST on r_night_b (sun 00:00-06:00, cutoff 0)
    G = book(ta, "r_night_b", "nb_1", "2027-03-21T02:30", 2)
    n0 = len(listing(ta) or [])
    f = series(ta, ref(G), 3, 1)
    check("P3.SE5d", "SE5", "Recurring reservations", "occurrence 1 would fall on the nonexistent 2027-03-28 02:30: whole adoption 422 invalid_local_time, nothing created", G.status_code == 201 and f.status_code == 422 and code(f) == "invalid_local_time" and len(listing(ta) or []) == n0, show(f))
    F = book(ta, "r_night_b", "nb_2", "2027-10-24T02:30", 2)
    s = series(ta, ref(F), 2, 1)
    o1 = ((J(s) or {}).get("occurrences") or [{}, {}])[1].get("reservation", {})
    check("P3.SE5e", "SE5", "Recurring reservations", "occurrence on the repeated hour (2027-10-31 02:30) resolves to the first occurrence (+02:00), 90 real minutes", s.status_code == 201 and p.same_ts(o1.get("starts_at"), "2027-10-31T02:30:00+02:00") and p.same_ts(o1.get("ends_at"), "2027-10-31T03:00:00+01:00"), o1)


def s_moves():
    reset(fx3())
    ta, tm = p.ada(), mgr()
    A = bk(ta, "t_2", MON, "19:00", 2)
    B = bk(ta, "t_3", MON, "19:00", 2)
    a, b = ref(A), ref(B)
    S = series(ta, a, 4, 1)
    js = J(S) or {}
    occ = js.get("occurrences") or [{}] * 4
    sid = js.get("series_id")
    cur = lambda: J(getseries(ta, sid)) or {}
    c0 = cur()
    state = lambda: ([J(get(ta, x)) for x in (a, b, occ[1].get("reference"), occ[2].get("reference"))], [hist(ta, x) for x in (a, b, occ[1].get("reference"), occ[2].get("reference"))], cur())
    s0 = state()
    expect("P3.MO1a", "MO1", "Collective moves", "per-move expected_revision mismatch", p.moves(ta, [{"reference": b, "party_size": 3, "expected_revision": 5}]), 409, "stale_revision")
    expect("P3.MO1b", "MO1", "Collective moves", "per-move expected_revision invalid (boolean)", p.moves(ta, [{"reference": b, "party_size": 3, "expected_revision": True}]), 422, "validation_failed")
    expect("P3.MO1c", "MO1", "Collective moves", "per-move expected_revision 0", p.moves(ta, [{"reference": b, "party_size": 3, "expected_revision": 0}]), 422, "validation_failed")
    f = p.moves(ta, [{"reference": occ[1]["reference"], "party_size": 1}, {"reference": occ[2]["reference"], "party_size": 99}])
    check("P3.MO2a", "MO2/MO3", "Collective moves", "failed batch (second item exceeds capacity) and refused revisions changed no booking, revision, history, series revision or exception flag", f.status_code == 422 and state() == s0, show(f))
    km = K()
    items = [{"reference": b, "party_size": 3, "expected_revision": 1}, {"reference": occ[1]["reference"], "party_size": 1}, {"reference": occ[2]["reference"], "table_id": "t_1", "party_size": 1}, {"reference": a}]
    r = p.moves(ta, items, key=km)
    jr = (J(r) or {}).get("reservations") or [{}] * 4
    c1 = cur()
    hs = [hist(ta, x.get("reference")) or [] for x in jr]
    check("P3.MO2b", "MO2/TE1", "Collective moves", "batch with three real changes and one no-op: changed bookings revision 2 with one changed history entry each, the no-op keeps revision 1 and its history; responses carry revision and terms",
          r.status_code == 201 and [x.get("revision") for x in jr] == [2, 2, 2, 1] and [len(h) for h in hs] == [2, 2, 2, 1] and changes((hs[2] + [{}, {}])[1]) == [("table_id", "t_2", "t_1"), ("party_size", 2, 1)]
          and all(x.get("accepted_terms") == TERMS0 for x in jr), show(r)[:300])
    check("P3.MO3a", "MO3", "Collective moves", "two occurrences of one series changed in one batch: series revision +1 once (1 -> 2), both become exceptions, the unchanged anchor does not",
          c0.get("revision") == 1 and c1.get("revision") == 2 and [o.get("exception") for o in c1.get("occurrences", [])] == [False, True, True, False], c1.get("revision"))
    r2 = p.moves(ta, items, key=km)
    check("P3.MO3b", "MO3", "Collective moves", "replay of the batch -> 200 original; no revision, history or series change", r2.status_code == 200 and J(r2) == J(r) and cur() == c1 and [len(hist(ta, x.get("reference")) or []) for x in jr] == [2, 2, 2, 1], show(r2)[:200])
    P1 = pol("2027-10-04", dur=60)
    publish(tm, P1)
    r = p.moves(ta, [{"reference": b, "starts_at_local": "2027-10-04T19:00"}])
    j = ((J(r) or {}).get("reservations") or [{}])[0]
    check("P3.MO1d", "MO1", "Collective moves", "a move to another date adopts that date's policy (terms version 1, 60-minute end), revision 3", r.status_code == 201 and j.get("accepted_terms") == terms_of(P1, 1) and p.same_ts(j.get("ends_at"), "2027-10-04T20:00:00+02:00") and j.get("revision") == 3, show(r)[:300])
    for path, body in ([] if os.environ.get("STAGE4") else [("/restaurants/r_m/replans", {}), (f"/series/{sid}/amend", {}), ("/restaurants/r_m/closures", {})]):
        rr = req("POST", path, token=tm, key=K(), body=body)
        check(f"P3.N{path.split('/')[-1]}", "N3a", "task (no stage-4 features)", f"POST {path} does not exist (404/405)", rr.status_code in (404, 405), show(rr))


def full_state(toks, refs, sids, base=None):
    s = {"policies": J(req("GET", "/restaurants/r_m/policies", base=base))}
    for n, t in toks.items():
        s["list:" + n] = listing(t, base=base)
    for n, t, rf in refs:
        s["hist:" + rf] = J(req("GET", f"/reservations/{rf}/history", token=toks[n], base=base))
        s["dec:" + rf] = J(req("GET", f"/reservations/{rf}/decision", token=toks[n], base=base))
    for n, sid in sids:
        s["series:" + sid] = J(req("GET", f"/series/{sid}", token=toks[n], base=base))
    s["av"] = J(req("GET", f"/availability?restaurant_id=r_m&date={MON}&party_size=2&explain=true", base=base))
    return s


def s_export_import():
    reset(fx3())
    ta, tb, tm = p.ada(), p.bob(), mgr()
    kp, kc, ks, kmv = K(), K(), K(), K()
    P1 = pol("2027-10-04", dur=60)
    RP = publish(tm, P1, key=kp)
    A = bk(ta, "t_2", MON, "19:00", 2, key=kc)
    S = series(ta, ref(A), 4, 1, key=ks)
    occ = (J(S) or {}).get("occurrences") or [{}] * 4
    patch(ta, occ[1].get("reference"), {"party_size": 3})
    cancel(ta, occ[3].get("reference"))
    B = bkp(tb, ["t_1"], MON, "19:00", 2)
    mvb = [{"reference": occ[2].get("reference"), "party_size": 1}]
    RM = p.moves(ta, mvb, key=kmv)
    toks = {"ada": ta, "bob": tb}
    refs = [("ada", ta, o.get("reference")) for o in occ] + [("bob", tb, ref(B))]
    sids = [("ada", (J(S) or {}).get("series_id"))]
    pre = full_state(toks, refs, sids)
    ex = req("GET", "/_test/export", limit=10)
    E = J(ex) or {}
    check("P3.UP2a", "UP2", "stage-1 §10", "setup and export ok (format_version 1)", [x.status_code for x in (RP, A, S, B, RM)] == [201] * 5 and ex.status_code == 200 and E.get("format_version") == 1, [x.status_code for x in (RP, A, S, B, RM)])
    publish(tm, pol("2027-12-01"))
    patch(ta, occ[2].get("reference"), {"party_size": 2})
    cancel(tb, ref(B))
    bad = req("POST", "/_test/import", body=dict(E, format_version=2), limit=10)
    im = req("POST", "/_test/import", body=E, limit=10)
    post = full_state(toks, refs, sids)
    diff = [k for k in pre if pre[k] != post.get(k)]
    check("P3.UP2b", "UP2", "stage-1 §10", "import restores policies, reservations with terms and revisions, histories, decisions, series (revision, exception flags), availability", bad.status_code == 422 and im.status_code == 204 and not diff, diff)
    rp = [publish(tm, P1, key=kp), bk(ta, "t_2", MON, "19:00", 2, key=kc), series(ta, ref(A), 4, 1, key=ks), p.moves(ta, mvb, key=kmv)]
    check("P3.UP2c", "UP2", "stage-1 §10", "receipts of all four idempotent paths replay 200 with the original bodies after import; nothing changed",
          [x.status_code for x in rp] == [200] * 4 and [J(x) for x in rp] == [J(RP), J(A), J(S), J(RM)] and full_state(toks, refs, sids) == pre, [x.status_code for x in rp])
    if BASE2:
        reset(p.SPEC_FIXTURE, base=BASE2)
        im2 = req("POST", "/_test/import", body=E, base=BASE2, limit=10)
        post2 = full_state(toks, refs, sids, base=BASE2)
        check("P3.UP2d", "UP2", "stage-1 §10", "import into a second stage-3 container shows the same state", im2.status_code == 204 and post2 == pre, [k for k in pre if pre[k] != post2.get(k)])
    r = publish(tm, pol("2027-12-01"))
    r2 = patch(ta, occ[2].get("reference"), {"party_size": 2})
    h = hist(ta, occ[2].get("reference")) or []
    check("P3.UP2e", "UP2", "stage-1 §10", "counters continue after import: next policy version 2, next history seq 3 / revision 3, series revision 5",
          (J(r) or {}).get("policy_version") == 2 and (J(r2) or {}).get("revision") == 3 and seq_ok(h) and len(h) == 3 and (J(getseries(ta, sids[0][1])) or {}).get("revision") == 5, f"{show(r)[:120]} {(J(r2) or {}).get('revision')} {(J(getseries(ta, sids[0][1])) or {}).get('revision')}")


def upgrade_from(tag, src):
    if not src:
        check(f"P3.UP1{tag}", "UP1", "upgrade", "source container available", False, "not set")
        return
    seed = [{"id": "res_seed_1", "reference": "SEED01", "user_id": "u_bob", "restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": "2027-09-24T18:00", "party_size": 2}]
    reset(p.fixture(reservations=seed), base=src)
    ta, tb = p.ada(src), p.bob(src)
    k1, km = K(), K()
    b1 = {"restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": f"{THU}T19:00", "party_size": 2}
    R1 = req("POST", "/reservations", token=ta, key=k1, body=b1, base=src)
    R2 = book(ta, "r_anker", "t_2", f"{THU}T21:00", 2, base=src)
    req("POST", f"/reservations/{ref(R2)}/cancel", token=ta, base=src)
    bm = {"moves": [{"reference": ref(R1), "party_size": 1}]}
    RM = req("POST", "/reservation-moves", token=ta, key=km, body=bm, base=src)
    l1 = listing(ta, base=src)
    E = J(req("GET", "/_test/export", base=src, limit=10))
    reset(fx3())
    im = req("POST", "/_test/import", body=E, limit=10)
    expect(f"P3.UP1{tag}a", "UP1", "Recurring reservations (upgrade paragraph)", f"stage-3 import of the unchanged {tag} export", im, 204)
    l3 = listing(ta) or []
    T0 = {"policy_version": 0, "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120, "opening_hours": p.fixture()["restaurants"][0]["opening_hours"], "capacities": {"t_1": 2, "t_2": 4}}
    bad = [x for x1, x in zip(l1 or [], l3) if any(x.get(k) != v for k, v in x1.items()) or x.get("revision") != 1 or x.get("accepted_terms") != T0]
    check(f"P3.UP1{tag}b", "UP1", "upgrade / map decision 4", "session token valid; imported reservations keep every earlier field and show revision 1 with policy-0 terms", len(l3) == len(l1 or [None]) == 2 and not bad, bad[:1] or l3)
    h = hist(ta, ref(R1)) or []
    hc = hist(ta, ref(R2)) or []
    check(f"P3.UP1{tag}c", "UP1", "map decision 4", "imported reservations have a history starting with a created entry (seq 1); decision readable", h and h[0].get("event") == "created" and h[0].get("seq") == 1 and hc and hc[0].get("event") == "created" and dec(ta, ref(R1)).status_code == 200, f"{h} {hc}")
    rp1, rp2 = req("POST", "/reservations", token=ta, key=k1, body=b1), req("POST", "/reservation-moves", token=ta, key=km, body=bm)
    check(f"P3.UP1{tag}d", "UP1", "upgrade", "original booking and moves retries replay 200 with the original bodies unchanged", rp1.status_code == 200 and J(rp1) == J(R1) and rp2.status_code == 200 and J(rp2) == J(RM), show(rp1)[:200])
    lg = req("POST", "/auth/login", body={"email": "ada@example.com", "password": "correct horse"})
    s = series(ta, ref(R1), 3, 1)
    js = J(s) or {}
    check(f"P3.UP1{tag}e", "UP1", "Recurring reservations (upgrade paragraph)", "password login works; adoption works on an imported reservation (201, occurrence 0 = the imported booking, 2 generated on following Thursdays)",
          lg.status_code == 200 and s.status_code == 201 and len(js.get("occurrences", [])) == 3 and js["occurrences"][0].get("reference") == ref(R1) and js["occurrences"][1]["reservation"].get("starts_at_local") == "2027-09-30T19:00", show(s)[:300])
    c = cancel(tb, "SEED01")
    hh = hist(tb, "SEED01") or []
    check(f"P3.UP1{tag}f", "UP1", "upgrade", "an imported seeded booking can be cancelled: revision 2, history ends with cancelled", c.status_code == 200 and (J(c) or {}).get("revision") == 2 and hh and hh[-1].get("event") == "cancelled" and seq_ok(hh), show(c)[:200])


def s_upgrade():
    upgrade_from("s1", S1BASE)
    upgrade_from("s2", S2BASE)


def s_concurrency():
    users = [{"id": f"u_load_{i}", "email": f"load{i}@example.com", "password": f"load password {i}", "display_name": f"L{i}"} for i in range(50)]
    reset(fx3(extra_users=users))
    tm = mgr()
    rs = parallel([(lambda i=i: req("POST", "/auth/login", body={"email": f"load{i}@example.com", "password": f"load password {i}"})) for i in range(50)])
    toks = [(J(x) or {}).get("token") for x in rs]
    rnd = random.Random(5)
    hh = ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30"]
    sets = [["t_1", "t_2"], ["t_1"], ["t_2"], ["t_3"]]
    days = [MON, TUE, "2027-09-22"]

    def worker(i, seed):
        rg = random.Random(seed)
        t = toks[i]
        out = []
        if i % 10 == 0:
            out.append(publish(tm, pol(f"2099-{rg.randint(1, 12):02d}-{rg.randint(1, 28):02d}")))
        b = bkp(t, rg.choice(sets), rg.choice(days), rg.choice(hh), 2)
        out.append(b)
        if b.status_code == 201:
            x = rg.random()
            if x < 0.4:
                out.append(patch(t, ref(b), {"table_ids": rg.choice(sets), "starts_at_local": f"{rg.choice(days)}T{rg.choice(hh)}"}))
            elif x < 0.7:
                out.append(series(t, ref(b), rg.randint(2, 4), 1))
            if rg.random() < 0.3:
                out.append(cancel(t, ref(b)))
        out.append(req("GET", f"/availability?restaurant_id=r_m&date={MON}&party_size=2&explain=true"))
        return out
    allr = []
    for _ in range(4):
        res = parallel([(lambda i=i, s=rnd.random(): worker(i, s)) for i in range(50)])
        allr += [x for o in res for x in o]
    badst = [show(x)[:160] for x in allr if x.status_code not in (200, 201, 409)]
    lists = {t: listing(t) or [] for t in toks}
    allc = [x for l in lists.values() for x in l if x.get("status") == "confirmed"]
    check("P3.CC3a", "CC3", "stage-2 Concurrent bookings", f"4 rounds x 50 in flight (book, PATCH, series, cancel, publish; {len(allr)} requests): only 200/201/409; no table in overlapping confirmed bookings ({len(allc)} confirmed)", not badst and not overlaps2(allc), f"{badst[:2]} {overlaps2(allc)[:3]}")
    pl = (J(req("GET", "/restaurants/r_m/policies")) or {}).get("policies") or []
    check("P3.CC3b", "CC3/PO4", "Policies", f"policy versions gap-free 1..{len(pl)} after concurrent publications", [x.get("policy_version") for x in pl] == list(range(1, len(pl) + 1)) and len(pl) == sum(1 for x in allr if x.status_code == 201 and "/policies" in str(x.request.url)), [x.get("policy_version") for x in pl])
    bad = []
    for t, l in lists.items():
        for x in l[:6]:
            h = hist(t, x["reference"]) or []
            if not (seq_ok(h) and h and h[-1].get("revision") == x.get("revision") == len(h) and [e.get("revision") for e in h] == list(range(1, len(h) + 1))):
                bad.append((x["reference"], x.get("revision"), [(e.get("seq"), e.get("revision"), e.get("event")) for e in h]))
    check("P3.CC3c", "CC3/HI2", "Reservation history", "after load every sampled reservation has history seq 1..k, entry revisions 1..k and current revision k", not bad, bad[:2])
    check("P3.N3leak", "N3a", "task (no stage-4 features)", "no response of any probe contained restaurant_revision", not LEAK, LEAK[:3])



def s_extra():
    """Round-1 additions: closed-day policy, pair occupancy in explain, racing adoptions, internal counter."""
    reset(fx3())
    ta, tm = p.ada(), mgr()
    A = bk(ta, "t_2", MON, "19:00", 2)
    r = publish(tm, pol("2027-10-04", hrs=[{"weekday": "tue", "opens": "18:00", "closes": "23:00"}]))
    sl = (J(avail("r_m", "2027-10-04", 2)) or {}).get("slots")
    check("P3.PO8j", "PO8", "Policies", "a policy whose opening_hours omit Monday closes Mondays from its effective date: slots [] and booking -> 422 outside_opening_hours; the Tuesday stays open",
          r.status_code == 201 and sl == [] and code(bk(ta, "t_3", "2027-10-04", "19:00", 2)) == "outside_opening_hours" and len(slots("r_m", "2027-10-05", 2)) == 8 and len(slots("r_m", "2027-09-27", 2)) == 8, sl)
    n0 = len(listing(ta) or [])
    f = series(ta, ref(A), 4, 1)
    check("P3.SE5f", "SE5", "Recurring reservations", "an occurrence falling on a day closed by its date's policy (index 2, 10-04) rejects the adoption with 422 outside_opening_hours; nothing created", f.status_code == 422 and code(f) == "outside_opening_hours" and len(listing(ta) or []) == n0, show(f))
    rs = parallel([(lambda: series(ta, ref(A), 2, 1)) for _ in range(10)])
    sts = sorted(x.status_code for x in rs)
    check("P3.SE3g", "SE3/CC3", "Recurring reservations", "10 concurrent adoptions of one anchor with different keys: exactly one 201, nine 409 already_in_series; one generated occurrence",
          sts == [201] + [409] * 9 and all(code(x) == "already_in_series" for x in rs if x.status_code == 409) and len(listing(ta) or []) == n0 + 1, sts)
    Bp = bkp(ta, ["t_1", "t_2"], TUE, "19:00", 5)
    e, _ = explain("r_m", TUE, 3)
    check("P3.EX3c", "EX3", "Availability explanations", "a pair booking makes no_overlap false on both member tables (t_1 also fails capacity for party 3)",
          Bp.status_code == 201 and e["19:00"]["explain"] == [ex_row("t_1", 0, False, False), ex_row("t_2", 0, True, False), ex_row("t_3", 0, True, True)], e["19:00"]["explain"])
    r = p.moves(ta, [{"reference": ref(Bp), "table_ids": ["t_3"]}])
    h = hist(ta, ref(Bp)) or [{}, {}]
    check("P3.HI8e", "HI8/MO2", "Combined-table history", "a move from a pair to a single records table_ids with complete before/after lists", r.status_code == 201 and len(h) == 2 and changes(h[1]) == [("table_ids", ["t_1", "t_2"], ["t_3"])], [changes(x) for x in h])
    ex = J(req("GET", "/_test/export", limit=10)) or {}
    note("P3.SE12", "internal restaurant revision in the export state (review)", {k: v for k, v in (ex.get("state") or {}).items() if "rev" in k})

def main():
    only = set(sys.argv[1:])
    for s in [s_explain, s_history, s_policies, s_policy_validation, s_cutoff_terms, s_series, s_series_failures, s_moves, s_export_import, s_upgrade, s_extra, s_concurrency]:
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
