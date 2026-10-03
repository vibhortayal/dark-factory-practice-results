#!/usr/bin/env python3
"""Stage-4 Tablekeeper API probes: closure replans (with an independent brute-force oracle),
plan application, series amendments, upgrades. Ids: CHECKS.md P4.*.

Usage: BASE=<stage-4> BASE2=<second stage-4> S1BASE= S2BASE= S3BASE= [SCENARIOS=80] [SKIP_WAIT=1] python probe4.py [sections]
"""
import itertools
import json
import os
import random
import sys
import time
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
for d in ("stage-1", "stage-2", "stage-3"):
    sys.path.insert(0, os.path.join(HERE, "..", d))
os.environ.setdefault("STAGE4", "1")
import probe as p  # noqa: E402
from probe import J, K, PAST_THU, avail, book, cancel, check, code, expect, get, hours, listing, login, note, parallel, patch, ref, req, reset, show, slots  # noqa: E402
from probe2 import overlaps2  # noqa: E402
import probe3 as p3  # noqa: E402
from probe3 import MON, TUE, THU, TERMS0, bk, bkp, changes, explain, ex_row, fx3, getseries, hist, mgr, pol, publish, series, seq_ok, terms_of  # noqa: E402

p.audit = p3._audit            # stage 4 legitimately returns restaurant_revision in plan responses
S1BASE, S2BASE, S3BASE = (os.environ.get(k, "").rstrip("/") for k in ("S1BASE", "S2BASE", "S3BASE"))
BASE2 = p.BASE2
NSCEN = int(os.environ.get("SCENARIOS", "80"))
CAPS = [2, 2, 4, 4, 6, 8]
PT = [f"p_{i}" for i in range(1, 7)]


def rest_p(pairs=None, **kw):
    r = {"id": "r_p", "name": "Planner", "timezone": "Europe/Berlin", "slot_minutes": 30, "reservation_duration_minutes": 90,
         "cancellation_cutoff_minutes": 120, "opening_hours": hours("17:00", "23:00"),
         "tables": [{"id": t, "label": t[-1], "capacity": c} for t, c in zip(PT, CAPS)],
         "combinable": pairs if pairs is not None else [["p_1", "p_2"], ["p_3", "p_4"], ["p_2", "p_3"], ["p_5", "p_6"]], "manager_user_ids": ["u_mgr"]}
    r.update(kw)
    return r


def fx4(pairs=None, extra_users=None, reservations=None, extra_rests=None):
    f = fx3(extra_users=extra_users, reservations=reservations)
    f["restaurants"].append(rest_p(pairs))
    f["restaurants"] += extra_rests or []
    return f


def iso(day, hhmm, off="+02:00"):
    return f"{day}T{hhmm}:00{off}"


def preview(tok, table, frm, to, rid="r_p", key=None, base=None, **extra):
    b = {"table_id": table, "from": frm, "to": to}
    b.update(extra)
    return req("POST", f"/restaurants/{rid}/replans", token=tok, key=key or K(), body=b, base=base)


def apply_(tok, plan_id, rid="r_p", key=None, base=None):
    return req("POST", f"/restaurants/{rid}/replans/{plan_id}/apply", token=tok, key=key or K(), body={}, base=base)


def amend(tok, sid, rev, idx, hhmm, key=None, base=None, **extra):
    b = {"expected_revision": rev, "from_index": idx, "local_time": hhmm}
    b.update(extra)
    return req("POST", f"/series/{sid}/amend", token=tok, key=key or K(), body=b, base=base)


def rr(tm, rid="r_p", base=None):
    """Restaurant revision, read through a throw-away preview far in the future (previews never bump it)."""
    t = {"r_p": "p_1", "r_m": "t_1", "r_now": "w_1", "r_min": "m_1", "r_anker": "t_1"}[rid]
    r = preview(tm, t, "2090-01-01T00:00:00Z", "2090-01-01T01:00:00Z", rid=rid, base=base)
    return (J(r) or {}).get("restaurant_revision")


def bp(tok, tids, day, hhmm, party, key=None):
    return req("POST", "/reservations", token=tok, key=key or K(), body={"restaurant_id": "r_p", "table_ids": tids, "starts_at_local": f"{day}T{hhmm}", "party_size": party})


# ---------------------------------------------------------------- oracle
def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def oracle(rest, bookings, closures, table, frm, to):
    """Brute-force optimal plan. bookings: confirmed reservation bodies; closures: [(table, from, to)] already applied.
    Returns None when infeasible, else (assignments, moved, unused)."""
    options = [[t["id"]] for t in rest["tables"]] + [list(x) for x in rest.get("combinable", [])]
    F, T = _dt(frm), _dt(to)
    iv = lambda b: (_dt(b["starts_at"]), _dt(b["ends_at"]))
    cons = sorted([b for b in bookings if iv(b)[0] < T and iv(b)[1] > F], key=lambda b: b["reference"])
    cref = {b["reference"] for b in cons}
    fixed = [b for b in bookings if b["reference"] not in cref]
    allcl = [(t, _dt(a), _dt(z)) for t, a, z in closures] + [(table, F, T)]
    feas = []
    for b in cons:
        s, e = iv(b)
        caps = b["accepted_terms"]["capacities"]
        mine = []
        for rank, o in enumerate(options):
            cap = sum(caps[t] for t in o)
            if cap < b["party_size"]:
                continue
            if any(t in o and a < e and z > s for t, a, z in allcl):
                continue
            if any(set(o) & set(x["table_ids"]) and iv(x)[0] < e and iv(x)[1] > s for x in fixed):
                continue
            mine.append((rank, o, cap - b["party_size"], set(o) != set(b["table_ids"])))
        feas.append(mine)
    best = [None, None]

    def rec(i, chosen, moved, unused, ranks):
        if best[0] is not None and (moved, unused) > best[0][:2]:
            return
        if i == len(cons):
            key = (moved, unused, tuple(ranks))
            if best[0] is None or key < best[0]:
                best[0], best[1] = key, list(chosen)
            return
        s, e = iv(cons[i])
        for rank, o, un, ch in feas[i]:
            if any(set(o) & set(co) and iv(cons[j])[0] < e and iv(cons[j])[1] > s for j, (_, co, _, _) in enumerate(chosen)):
                continue
            rec(i + 1, chosen + [(rank, o, un, ch)], moved + ch, unused + un, ranks + [rank])
    rec(0, [], 0, 0, [])
    if best[0] is None:
        return None
    return ([{"reference": b["reference"], "table_ids": o, "changed": ch} for b, (_, o, _, ch) in zip(cons, best[1])], best[0][0], best[0][1])


def s_oracle():
    rnd = random.Random(int(os.environ.get("SEED", "20261003")))
    day = "2027-09-22"
    times = ["17:00", "17:30", "18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00"]
    allpairs = [list(x) for x in itertools.permutations(PT, 2)]
    bad, stats, n_apply, bad_apply, limit422 = [], {"201": 0, "409": 0, "considered": []}, 0, [], 0
    for sc in range(NSCEN):
        pairs = []
        for cand in rnd.sample(allpairs, len(allpairs)):
            if len(pairs) == 4:
                break
            if not any(set(cand) == set(x) for x in pairs):
                pairs.append(cand)
        rest = rest_p(pairs)
        reset(fx4(pairs))
        ta, tb, tm = p.ada(), p.bob(), mgr()
        options = [[t] for t in PT] + pairs
        caps = dict(zip(PT, CAPS))
        nb = rnd.randint(3, 9)
        pol_at = rnd.randint(0, nb) if rnd.random() < 0.5 else -1
        made = []
        for i in range(nb):
            if i == pol_at:
                caps = {t: max(1, c + rnd.choice([-1, 0, 2])) for t, c in zip(PT, CAPS)}
                publish(tm, pol("2027-09-01", slot=30, dur=rnd.choice([60, 90, 120]), cutoff=60, hrs=hours("17:00", "23:00"), caps=caps), rid="r_p")
            o = rnd.choice(options)
            r = bp(rnd.choice([ta, tb]), o, day, rnd.choice(times), rnd.randint(1, sum(caps[t] for t in o)))
            if r.status_code == 201:
                made.append(J(r))
        if made and rnd.random() < 0.2:
            victim = made.pop(rnd.randrange(len(made)))
            cancel(ta, victim["reference"]), cancel(tb, victim["reference"])
        closures = []
        rounds = 2 if rnd.random() < 0.4 else 1
        for rd in range(rounds):
            table = rnd.choice(PT)
            h0 = rnd.choice(times)
            frm = iso(day, h0)
            to = (datetime.fromisoformat(frm) + timedelta(minutes=rnd.choice([30, 60, 90, 150, 240]))).isoformat()
            exp = oracle(rest, made, closures, table, frm, to)
            ncons = len([b for b in made if _dt(b["starts_at"]) < _dt(to) and _dt(b["ends_at"]) > _dt(frm)])
            r = preview(tm, table, frm, to)
            j = J(r) or {}
            tag = f"scenario {sc}.{rd} (pairs {pairs}, close {table} {h0}+, {ncons} considered)"
            if r.status_code == 422 and code(r) == "planning_limit" and ncons > 6:
                limit422 += 1
                break
            if exp is None:
                stats["409"] += 1
                if not (r.status_code == 409 and code(r) == "no_feasible_plan"):
                    bad.append(f"{tag}: oracle says infeasible, service {show(r)[:200]}")
                break
            stats["201"] += 1
            stats["considered"].append(ncons)
            got = (j.get("assignments"), j.get("moved_count"), j.get("unused_seats"))
            if r.status_code != 201 or got != exp:
                bad.append(f"{tag}: oracle {exp} != service {r.status_code} {got}")
                break
            if rd + 1 < rounds or rnd.random() < 0.3:
                a = apply_(tm, j.get("plan_id"))
                n_apply += 1
                ja = J(a) or {}
                now = {x["reference"]: x for x in (listing(ta) or []) + (listing(tb) or [])}
                okk = a.status_code == 201 and [x.get("reference") for x in ja.get("reservations", [])] == [x["reference"] for x in exp[0]]
                for asg in exp[0]:
                    cur = now.get(asg["reference"], {})
                    old = next(b for b in made if b["reference"] == asg["reference"])
                    if cur.get("table_ids") != asg["table_ids"] or cur.get("revision") != old["revision"] + (1 if asg["changed"] else 0) or any(cur.get(k) != old[k] for k in ("starts_at", "ends_at", "party_size", "accepted_terms", "status")):
                        okk = False
                if not okk:
                    bad_apply.append(f"{tag}: {show(a)[:200]}")
                made = [now.get(b["reference"], b) for b in made]
                closures.append((table, frm, to))
                if overlaps2([x for x in now.values() if x["status"] == "confirmed"]):
                    bad_apply.append(f"{tag}: overlap after apply")
    check("P4.O1", "RP3/RP4/RP5", "Seating changes", f"oracle: {NSCEN} randomised scenarios (6 tables, 4 random pairs, 3-9 bookings, policies changing capacities/duration, cancelled bookings, second closures): service plan == brute-force optimum "
          f"(assignments in reference order, changed flags, moved_count, unused_seats) or no_feasible_plan exactly when infeasible [{stats['201']} plans, {stats['409']} infeasible, considered max {max(stats['considered'] or [0])}, planning_limit beyond 6: {limit422}]", not bad, bad[:3])
    check("P4.O2", "AP4/AP6", "Seating changes", f"oracle: {n_apply} plans applied: every considered booking sits on its assigned tables, revision +1 only when changed, times/party/terms identical, no overlaps; later plans respect applied closures", not bad_apply, bad_apply[:3])


def s_limits():
    reset(fx4())
    ta, tm = p.ada(), mgr()
    day = "2027-09-22"
    rs = [bp(ta, [t], day, "19:00", 1) for t in PT]
    t0 = time.monotonic()
    r = preview(tm, "p_6", iso(day, "18:00"), iso(day, "22:00"))
    dt = time.monotonic() - t0
    check("P4.RP6a", "RP6", "Seating changes", "6 tables, 4 pairs, 6 considered bookings filling every table, closing one: answered within 5 s with 409 no_feasible_plan (5 tables for 6 bookings)", all(x.status_code == 201 for x in rs) and r.status_code == 409 and code(r) == "no_feasible_plan" and dt < 5, f"{show(r)[:160]} {dt:.2f}s")
    cancel(ta, ref(rs[0]))
    t0 = time.monotonic()
    r = preview(tm, "p_6", iso(day, "18:00"), iso(day, "22:00"))
    dt = time.monotonic() - t0
    j = J(r) or {}
    check("P4.RP6b", "RP6/RP5", "Seating changes", "5 considered: only the booking on the closed table moves, to the first free single (p_1), within 5 s", r.status_code == 201 and j.get("moved_count") == 1 and [a for a in j.get("assignments", []) if a["changed"]] == [{"reference": ref(rs[5]), "table_ids": ["p_1"], "changed": True}] and dt < 5, f"{show(r)[:300]} {dt:.2f}s")
    more = [bp(ta, [t], day, "21:00", 1) for t in PT[:4]]
    t0 = time.monotonic()
    r = preview(tm, "p_6", iso(day, "17:00"), iso(day, "23:00"))
    dt = time.monotonic() - t0
    check("P4.RP6c", "RP6", "Seating changes", "9 considered bookings (beyond the stated limit): a plan or 422 planning_limit, within 5 s, never 5xx", (r.status_code == 201 or (r.status_code == 422 and code(r) == "planning_limit")) and dt < 5, f"{show(r)[:160]} {dt:.2f}s")
    note("P4.RP6n", "beyond-limit behaviour (9 considered)", f"{r.status_code} {code(r)} in {dt:.2f}s")


def s_preview():
    reset(fx4())
    ta, tb, tm = p.ada(), p.bob(), mgr()
    day = "2027-09-22"
    X = bp(ta, ["p_3"], day, "19:00", 4)
    Y = bp(tb, ["p_5"], day, "19:30", 5)
    Z = bp(ta, ["p_4"], day, "21:00", 2)                    # outside the closure window below
    C = bp(ta, ["p_6"], day, "19:00", 2)
    cancel(ta, ref(C))
    frm, to = iso(day, "18:00"), iso(day, "20:30")
    body = {"table_id": "p_3", "from": frm, "to": to}
    expect("P4.RP1a", "RP1", "Seating changes", "preview without token", req("POST", "/restaurants/r_p/replans", key=K(), body=body), 401, "unauthenticated")
    expect("P4.RP1b", "RP1", "Seating changes", "preview at an unknown restaurant", preview(tm, "p_3", frm, to, rid="r_nope"), 404, "not_found")
    expect("P4.RP1c", "RP1", "Seating changes", "preview by a non-manager", preview(ta, "p_3", frm, to), 403, "forbidden")
    expect("P4.RP1d", "RP1", "stage-1 §7", "preview without Idempotency-Key", req("POST", "/restaurants/r_p/replans", token=tm, body=body), 400, "missing_idempotency_key")
    bad = []
    for desc, f, t in [("from == to", frm, frm), ("from > to", to, frm), ("from without offset", f"{day}T18:00:00", to), ("to without offset", frm, f"{day}T20:30:00"), ("garbage", "soon", to),
                       ("from a number", 1800, to), ("date only", day, to), ("to null", frm, None)]:
        r = preview(tm, "p_3", f, t)
        if not (r.status_code == 422 and code(r) == "validation_failed"):
            bad.append(f"{desc}: {show(r)[:140]}")
    for desc, b in [("from missing", {"table_id": "p_3", "to": to}), ("to missing", {"table_id": "p_3", "from": frm}), ("table_id missing", {"from": frm, "to": to})]:
        r = req("POST", "/restaurants/r_p/replans", token=tm, key=K(), body=b)
        if not (r.status_code == 422 and code(r) == "validation_failed"):
            bad.append(f"{desc}: {show(r)[:140]}")
    check("P4.RP2a", "RP2", "Seating changes", "invalid interval (from >= to, no offset, garbage, wrong type, missing fields) -> 422 validation_failed", not bad, bad[:4])
    expect("P4.RP2b", "RP2", "Seating changes", "unknown table", preview(tm, "p_9", frm, to), 404, "not_found")
    expect("P4.RP2c", "RP2", "Seating changes", "table of another restaurant", preview(tm, "t_1", frm, to), 404, "not_found")
    expect("P4.RP2d", "RP2", "stage-1 §5", "table_id of wrong JSON type", preview(tm, 3, frm, to), 400, "malformed_request")
    state = lambda: ([listing(ta), listing(tb)], [hist(ta, ref(X)), hist(tb, ref(Y))], J(req("GET", f"/availability?restaurant_id=r_p&date={day}&party_size=2&explain=true")))
    s0, r0 = state(), rr(tm)
    kp = K()
    r = preview(tm, "p_3", frm, to, key=kp, comment="ignored")
    j = J(r) or {}
    refs = sorted([ref(X), ref(Y)])
    want = sorted([{"reference": ref(X), "table_ids": ["p_4"], "changed": True}, {"reference": ref(Y), "table_ids": ["p_5"], "changed": False}], key=lambda a: a["reference"])
    check("P4.RP7a", "RP7/RP3", "Seating changes", "201 {plan_id, restaurant_revision, closure, assignments, moved_count, unused_seats}: considered = the two confirmed bookings overlapping the interval (not the later one, not the cancelled one), in reference order; closure echoed",
          r.status_code == 201 and isinstance(j.get("plan_id"), str) and j.get("restaurant_revision") == r0 and j.get("closure") == body and j.get("assignments") == want and j.get("moved_count") == 1 and j.get("unused_seats") == 1 and [a["reference"] for a in j["assignments"]] == refs, show(r)[:400])
    check("P4.RP8a", "RP8/RR1", "Seating changes", "preview changed nothing: reservations, revisions, histories, availability (no closure), restaurant revision", state() == s0 and rr(tm) == r0, "")
    r2 = preview(tm, "p_3", frm, to, key=kp, comment="ignored")
    check("P4.RP1e", "RP1", "stage-1 §7", "replay of the preview -> 200 identical (same plan_id)", r2.status_code == 200 and J(r2) == j, show(r2)[:200])
    expect("P4.RP1f", "RP1", "stage-1 §7", "same key, different body", preview(tm, "p_4", frm, to, key=kp), 409, "idempotency_key_reuse")
    rz = preview(tm, "p_3", f"{day}T16:00:00Z", f"{day}T18:30:00Z")
    check("P4.RP2e", "RP2", "Seating changes", "instants with Z offset accepted and compared as instants (same interval -> same assignments)", rz.status_code == 201 and (J(rz) or {}).get("assignments") == want, show(rz)[:200])
    # half-open: X occupies 19:00-20:30
    a = preview(tm, "p_3", iso(day, "17:00"), iso(day, "19:00"))
    b = preview(tm, "p_3", iso(day, "20:30"), iso(day, "21:00"))
    c = preview(tm, "p_3", iso(day, "20:29"), iso(day, "20:31"))
    check("P4.RP3a", "RP3", "Seating changes", "half-open intervals: a closure ending at the booking's start or starting at its end considers nothing on that table; one minute of overlap considers it",
          ref(X) not in [x["reference"] for x in (J(a) or {}).get("assignments", [{"reference": ref(X)}])] and ref(X) not in [x["reference"] for x in (J(b) or {}).get("assignments", [{"reference": ref(X)}])]
          and ref(X) in [x["reference"] for x in (J(c) or {}).get("assignments", [])], f"{show(a)[:150]} | {show(b)[:150]} | {show(c)[:150]}")
    e = preview(tm, "p_1", "2090-01-01T00:00:00Z", "2090-01-01T01:00:00Z")
    check("P4.RP7b", "RP7", "map decision 4", "interval with no bookings: 201 with empty assignments, moved_count 0, unused_seats 0", e.status_code == 201 and (J(e) or {}).get("assignments") == [] and (J(e) or {}).get("moved_count") == 0 and (J(e) or {}).get("unused_seats") == 0, show(e)[:200])
    # infeasible: party 8 on p_6 can only sit on p_6 or the pair p_5+p_6
    reset(fx4())
    ta, tm = p.ada(), mgr()
    B8 = bp(ta, ["p_6"], day, "19:00", 8)
    bp(ta, ["p_3"], day, "20:00", 1)        # fixed (outside the closure window) but overlapping the party of 8: blocks the pair p_3+p_4
    s0 = (listing(ta), rr(tm))
    kf = K()
    f = preview(tm, "p_6", iso(day, "19:00"), iso(day, "19:30"), key=kf)
    check("P4.RP8b", "RP8/RP4", "Seating changes", "no feasible plan (party 8: p_6 closed, pair p_5+p_6 closed, pair p_3+p_4 blocked by a fixed booking) -> 409 no_feasible_plan, nothing changed", B8.status_code == 201 and f.status_code == 409 and code(f) == "no_feasible_plan" and (listing(ta), rr(tm)) == s0, show(f))
    g = preview(tm, "p_5", iso(day, "19:00"), iso(day, "19:30"), key=kf)
    check("P4.RP8c", "RP8", "stage-1 §7", "the key of the failed preview is reusable (different body -> 201)", g.status_code == 201, show(g)[:160])
    # own accepted terms: booking accepted when p_1 seated 2; a later policy makes p_1 seat 6 for new bookings only
    reset(fx4())
    ta, tm = p.ada(), mgr()
    O = bp(ta, ["p_3"], day, "19:00", 3)
    publish(tm, pol("2027-09-01", hrs=hours("17:00", "23:00"), caps={"p_1": 6, "p_2": 6, "p_3": 4, "p_4": 1, "p_5": 6, "p_6": 8}), rid="r_p")
    r = preview(tm, "p_3", frm, to)
    asg = (J(r) or {}).get("assignments", [{}])
    check("P4.RP4a", "RP4", "Seating changes", "capacity under the booking's OWN accepted terms: party 3 accepted under the fixture capacities goes to p_4 (4 seats then), not to p_1/p_2 (6 only under the newer policy)", r.status_code == 201 and asg == [{"reference": ref(O), "table_ids": ["p_4"], "changed": True}] and (J(r) or {}).get("unused_seats") == 1, show(r)[:300])
    # cutoff does not block: a past booking is moved
    reset(fx4())
    ta, tm = p.ada(), mgr()
    Pb = bp(ta, ["p_3"], "2020-09-23", "19:00", 4)
    r = preview(tm, "p_3", "2020-09-23T18:00:00+02:00", "2020-09-23T22:00:00+02:00")
    a = apply_(tm, (J(r) or {}).get("plan_id"))
    check("P4.RP4b", "RP4", "Seating changes", "diner cutoffs do not prevent a repair: a booking in the past is planned and moved by apply", Pb.status_code == 201 and r.status_code == 201 and a.status_code == 201 and (J(get(ta, ref(Pb))) or {}).get("table_ids") == ["p_4"], show(a)[:200])


def s_apply():
    reset(fx4())
    ta, tb, tm = p.ada(), p.bob(), mgr()
    day = "2027-09-22"
    X = bp(ta, ["p_3"], day, "19:00", 4)
    Y = bp(tb, ["p_5"], day, "19:30", 5)
    frm, to = iso(day, "19:00"), iso(day, "20:30")
    pv = preview(tm, "p_3", frm, to)
    jp = J(pv) or {}
    pid = jp.get("plan_id")
    other = preview(tm, "t_1", iso(MON, "18:00"), iso(MON, "19:00"), rid="r_m")
    expect("P4.AP1a", "AP1", "Seating changes", "apply without token", req("POST", f"/restaurants/r_p/replans/{pid}/apply", key=K(), body={}), 401, "unauthenticated")
    expect("P4.AP1b", "AP1", "Seating changes", "apply by a non-manager", apply_(ta, pid), 403, "forbidden")
    expect("P4.AP1c", "AP1", "stage-1 §7", "apply without Idempotency-Key", req("POST", f"/restaurants/r_p/replans/{pid}/apply", token=tm, body={}), 400, "missing_idempotency_key")
    expect("P4.AP3a", "AP3", "Seating changes", "apply an unknown plan", apply_(tm, "nope"), 404, "not_found")
    expect("P4.AP3b", "AP3", "Seating changes", "apply a plan that belongs to another restaurant", apply_(tm, (J(other) or {}).get("plan_id")), 404, "not_found")
    expect("P4.AP1d", "AP1", "Seating changes", "apply at an unknown restaurant", apply_(tm, pid, rid="r_nope"), 404, "not_found")
    # intervening revision -> stale
    W = bp(ta, ["p_1"], day, "21:00", 1)
    s0 = (listing(ta), listing(tb), rr(tm))
    st = apply_(tm, pid)
    check("P4.AP3c", "AP3", "Seating changes", "an intervening restaurant revision (a new booking) invalidates the plan: 409 stale_plan, nothing changed", W.status_code == 201 and st.status_code == 409 and code(st) == "stale_plan" and (listing(ta), listing(tb), rr(tm)) == s0, show(st))
    pv = preview(tm, "p_3", frm, to)
    jp = J(pv) or {}
    pid = jp.get("plan_id")
    bk(ta, "t_3", MON, "19:00", 2)                                    # write at another restaurant
    r0 = rr(tm)
    ka = K()
    a = apply_(tm, pid, key=ka)
    ja = J(a) or {}
    gx, gy = J(get(ta, ref(X))) or {}, J(get(tb, ref(Y))) or {}
    check("P4.AP2", "AP2/AP7", "Seating changes", "apply -> 201 {plan_id, restaurant_revision = preview + 1, reservations = every considered booking in reference order as ordinary responses}; a write at another restaurant did not invalidate the plan",
          a.status_code == 201 and ja.get("plan_id") == pid and ja.get("restaurant_revision") == jp.get("restaurant_revision") + 1 == r0 + 1
          and ja.get("reservations") == [x for x in sorted([gx, gy], key=lambda x: x["reference"])], show(a)[:400])
    hx, hy = hist(ta, ref(X)) or [], hist(tb, ref(Y)) or []
    e = hx[-1] if hx else {}
    check("P4.AP4a", "AP4", "Seating changes", "moved booking: revision 2, same times/party/terms; one reassigned history entry with a table_ids change (complete lists), plan_id, resulting revision and unchanged terms",
          gx.get("table_ids") == ["p_4"] and gx.get("revision") == 2 and all(gx.get(k) == (J(X) or {}).get(k) for k in ("starts_at", "ends_at", "starts_at_local", "party_size", "accepted_terms", "status", "reference", "reservation_id", "created_at"))
          and len(hx) == 2 and e.get("event") == "reassigned" and changes(e) == [("table_ids", ["p_3"], ["p_4"])] and e.get("plan_id") == pid and e.get("revision") == 2 and e.get("accepted_terms") == gx.get("accepted_terms") and seq_ok(hx), e)
    check("P4.AP4b", "AP4", "Seating changes", "unmoved considered booking gained nothing (revision 1, one history entry)", gy == J(Y) and len(hy) == 1, gy)
    check("P4.RR1a", "RR1/AP4", "Seating changes", "restaurant revision +1 once for the whole plan", rr(tm) == r0 + 1, rr(tm))
    a2 = apply_(tm, pid, key=ka)
    check("P4.AP3d", "AP3", "Seating changes", "replay of the successful apply key -> 200 original response", a2.status_code == 200 and J(a2) == ja, show(a2)[:200])
    expect("P4.AP3e", "AP3", "Seating changes", "the applied plan under a different key", apply_(tm, pid), 409, "plan_already_applied")
    # closure effects
    s = slots("r_p", day, 2)
    got = {k[-5:]: ("p_3" in v["available_table_ids"], any("p_3" in o["table_ids"] for o in v["available_options"])) for k, v in s.items()}
    want = {h: (False, False) if h in ("18:00", "18:30", "19:00", "19:30", "20:00") else (True, True) for h in [k[-5:] for k in s]}
    want = {h: (v if h not in ("17:30",) else (True, True)) for h, v in want.items()}
    check("P4.AP5a", "AP5", "Seating changes", "closure 19:00-20:30 on p_3 removes the single and its pairs from every overlapping slot (18:00..20:00) and from no other (17:30 ends at 19:00, 20:30 starts at the end)", got == want, got)
    ex, _ = explain("r_p", day, 2)
    row = [x for x in ex["19:00"]["explain"] if x["table_id"] == "p_3"][0]
    row2 = [x for x in ex["20:30"]["explain"] if x["table_id"] == "p_3"][0]
    check("P4.AP5b", "AP5", "Seating changes", "explain: no_overlap false for the closed table inside the closure (capacity true), true outside", row == ex_row("p_3", 0, True, False) and row2 == ex_row("p_3", 0, True, True), row)
    expect("P4.AP5c", "AP5", "Seating changes", "create on the closed table inside the closure", bp(ta, ["p_3"], day, "18:00", 2), 409, "table_unavailable")
    expect("P4.AP5d", "AP5", "Seating changes", "create on a pair containing the closed table", bp(ta, ["p_2", "p_3"], day, "18:00", 2), 409, "table_unavailable")
    expect("P4.AP5e", "AP5", "Seating changes", "PATCH onto the closed table", patch(ta, ref(W), {"table_id": "p_3", "starts_at_local": f"{day}T19:00"}), 409, "table_unavailable")
    expect("P4.AP5f", "AP5", "Seating changes", "moves onto the closed table", p.moves(ta, [{"reference": ref(W), "table_id": "p_3", "starts_at_local": f"{day}T19:30"}]), 409, "table_unavailable")
    ok1 = bp(ta, ["p_3"], day, "17:30", 2)
    ok2 = bp(ta, ["p_3"], day, "20:30", 2)
    ok3 = bp(ta, ["p_3"], "2027-09-23", "19:00", 2)
    check("P4.AP5g", "AP5", "Seating changes", "outside [from,to) the table is bookable: 17:30 (ends at from), 20:30 (starts at to), another day", [x.status_code for x in (ok1, ok2, ok3)] == [201] * 3, [show(x)[:100] for x in (ok1, ok2, ok3)])
    A0 = bp(ta, ["p_3"], "2027-09-15", "19:00", 2)
    f = series(ta, ref(A0), 2, 1)
    check("P4.AP5h", "AP5", "Seating changes", "series adoption whose occurrence falls into the closure -> 409 table_unavailable", f.status_code == 409 and code(f) == "table_unavailable", show(f))
    a3 = apply_(tm, pid, key=ka)
    check("P4.AP3f", "AP3", "Seating changes", "replay of the apply key after later changes -> 200 original response", a3.status_code == 200 and J(a3) == ja, show(a3)[:160])
    # AP6: later plan respects the applied closure: X2 on p_4 19:00 party 4 -> closing p_4 must not use p_3
    r = preview(tm, "p_4", frm, to)
    asg = {x["reference"]: x["table_ids"] for x in (J(r) or {}).get("assignments", [])}
    check("P4.AP6", "AP6", "Seating changes", "a later plan does not assign the previously closed table (the party of 4 leaves p_4 for a free table that is not p_3)", r.status_code == 201 and asg.get(ref(X)) not in (None, ["p_3"], ["p_4"]) and "p_3" not in asg.get(ref(X), ["p_3"]), show(r)[:300])
    # AP7: two plans from one revision applied concurrently
    reset(fx4())
    ta, tm = p.ada(), mgr()
    X = bp(ta, ["p_3"], day, "19:00", 4)
    Y = bp(ta, ["p_5"], day, "19:00", 5)
    p1, p2 = preview(tm, "p_3", frm, to), preview(tm, "p_5", frm, to)
    rs = parallel([lambda: apply_(tm, (J(p1) or {}).get("plan_id")), lambda: apply_(tm, (J(p2) or {}).get("plan_id"))] * 5)
    sts = sorted(x.status_code for x in rs)
    gx, gy = J(get(ta, ref(X))) or {}, J(get(ta, ref(Y))) or {}
    moved = [gx.get("table_ids") != ["p_3"], gy.get("table_ids") != ["p_5"]]
    check("P4.AP7", "AP7", "Seating changes", "10 concurrent applies of two plans made at one revision: exactly one 201, the rest 409 (stale_plan or plan_already_applied); exactly one plan's move is in effect, restaurant revision +1",
          sts == [201] + [409] * 9 and all(code(x) in ("stale_plan", "plan_already_applied") for x in rs if x.status_code == 409) and moved.count(True) == 1 and rr(tm) == 3, f"{sts} {moved} rr={rr(tm)}")


def s_plan_series():
    reset(fx4())
    ta, tm = p.ada(), mgr()
    A = bp(ta, ["p_3"], "2027-09-15", "19:00", 4)
    S = series(ta, ref(A), 4, 1)
    js = J(S) or {}
    occ = js.get("occurrences") or [{}] * 4
    sid = js.get("series_id")
    patch(ta, occ[1].get("reference"), {"party_size": 3})                 # occurrence 1 becomes an exception (09-22)
    B = bp(ta, ["p_3"], "2027-09-22", "21:00", 4)                          # non-series booking, same day
    S2 = series(ta, ref(B), 2, 1)
    c0 = J(getseries(ta, sid)) or {}
    c20 = J(getseries(ta, (J(S2) or {}).get("series_id"))) or {}
    r0 = rr(tm)
    pv = preview(tm, "p_3", iso("2027-09-22", "17:00"), iso("2027-09-22", "23:00"))
    a = apply_(tm, (J(pv) or {}).get("plan_id"))
    c1 = J(getseries(ta, sid)) or {}
    c21 = J(getseries(ta, (J(S2) or {}).get("series_id"))) or {}
    o0, o1 = c0["occurrences"][1], c1["occurrences"][1]
    check("P4.AP8a", "AP8", "Amend recurring reservations", "a repair moves series occurrences: each affected series revision +1 once; exception flags, references, indices, scheduled dates and terms preserved; restaurant revision +1 once",
          a.status_code == 201 and c1.get("revision") == c0.get("revision") + 1 and c21.get("revision") == c20.get("revision") + 1 and [o["exception"] for o in c1["occurrences"]] == [False, True, False, False]
          and o1["reference"] == o0["reference"] and o1["reservation"]["table_ids"] != ["p_3"] and all(o1["reservation"][k] == o0["reservation"][k] for k in ("starts_at_local", "ends_at", "party_size", "accepted_terms"))
          and [o["exception"] for o in c21["occurrences"]] == [False, False] and rr(tm) == r0 + 1, f"{c0.get('revision')}->{c1.get('revision')} {c20.get('revision')}->{c21.get('revision')} rr {r0}->{rr(tm)}")
    check("P4.AP8b", "AP8", "Amend recurring reservations", "occurrences outside the closure are untouched", c1["occurrences"][0] == c0["occurrences"][0] and c1["occurrences"][2] == c0["occurrences"][2], "")
    sid2 = (J(S2) or {}).get("series_id")
    moved_tables = c21["occurrences"][0]["reservation"].get("table_ids")
    am = amend(ta, sid2, c21.get("revision"), 0, "21:30")
    oa = (J(am) or {}).get("occurrences") or [{"reservation": {}}, {"reservation": {}}]
    check("P4.SA4b", "SA4/AP8", "Amend recurring reservations", "amending a series whose occurrence 0 was moved by the plan (not an exception): it is still eligible, keeps the plan's tables and its scheduled date; occurrence 1 keeps p_3",
          am.status_code == 201 and oa[0]["reservation"].get("starts_at_local") == "2027-09-22T21:30" and oa[0]["reservation"].get("table_ids") == moved_tables and moved_tables != ["p_3"]
          and oa[1]["reservation"].get("starts_at_local") == "2027-09-29T21:30" and oa[1]["reservation"].get("table_ids") == ["p_3"] and [o.get("exception") for o in oa] == [False, False], show(am)[:300])


def s_revision():
    reset(fx4())
    ta, tm = p.ada(), mgr()
    seen = [("reset", rr(tm), 0)]
    exp = 0

    def step(desc, delta, fn):
        nonlocal exp
        r = fn()
        exp += delta
        seen.append((desc, rr(tm), exp))
        return r
    k = K()
    A = step("new booking", 1, lambda: bp(ta, ["p_3"], "2027-09-15", "19:00", 2, key=k))
    step("booking replay", 0, lambda: bp(ta, ["p_3"], "2027-09-15", "19:00", 2, key=k))
    step("failed booking", 0, lambda: bp(ta, ["p_3"], "2027-09-15", "19:00", 2))
    step("no-op PATCH", 0, lambda: patch(ta, ref(A), {"party_size": 2}))
    step("failed PATCH", 0, lambda: patch(ta, ref(A), {"party_size": 99}))
    step("real PATCH", 1, lambda: patch(ta, ref(A), {"party_size": 3}))
    kp = K()
    step("policy publication", 1, lambda: publish(tm, pol("2099-01-01", hrs=hours("17:00", "23:00"), caps=dict(zip(PT, CAPS))), rid="r_p", key=kp))
    step("policy replay", 0, lambda: publish(tm, pol("2099-01-01", hrs=hours("17:00", "23:00"), caps=dict(zip(PT, CAPS))), rid="r_p", key=kp))
    step("failed policy", 0, lambda: publish(tm, pol("2099-01-01", slot=0, caps=dict(zip(PT, CAPS))), rid="r_p"))
    B = step("second booking", 1, lambda: bp(ta, ["p_4"], "2027-09-15", "19:00", 2))
    step("moves batch with two real changes", 1, lambda: p.moves(ta, [{"reference": ref(A), "party_size": 2}, {"reference": ref(B), "party_size": 1}]))
    step("moves batch of no-ops", 0, lambda: p.moves(ta, [{"reference": ref(A)}, {"reference": ref(B)}]))
    S = step("series adoption (3 occurrences)", 1, lambda: series(ta, ref(A), 3, 1))
    sid = (J(S) or {}).get("series_id")
    step("failed adoption", 0, lambda: series(ta, ref(A), 3, 1))
    step("series amend with changes", 1, lambda: amend(ta, sid, 1, 1, "20:00"))
    step("series amend all no-op", 0, lambda: amend(ta, sid, 2, 1, "20:00"))
    step("cancel", 1, lambda: cancel(ta, ref(B)))
    step("repeat cancel", 0, lambda: cancel(ta, ref(B)))
    pv = step("preview", 0, lambda: preview(tm, "p_3", iso("2027-09-15", "18:00"), iso("2027-09-15", "22:00")))
    ka = K()
    step("plan application", 1, lambda: apply_(tm, (J(pv) or {}).get("plan_id"), key=ka))
    step("apply replay", 0, lambda: apply_(tm, (J(pv) or {}).get("plan_id"), key=ka))
    step("write at another restaurant", 0, lambda: bk(ta, "t_2", MON, "19:00", 2))
    bad = [(d, got, want) for d, got, want in seen if got != want]
    check("P4.RR1", "RR1", "Seating changes", "restaurant revision: 0 after reset; +1 per booking, real amendment, cancellation, policy publication, plan application, once per moves batch, series adoption and series amendment; unchanged by replays, failures, no-ops, previews and other restaurants' writes", not bad, bad[:5])
    check("P4.RR1b", "RR1", "Seating changes", "the other restaurant has its own counter", rr(tm, "r_m") == 1, rr(tm, "r_m"))


def s_amend():
    reset(fx4())
    ta, tb, tm = p.ada(), p.bob(), mgr()
    A = bk(ta, "t_2", MON, "19:00", 3)
    S = series(ta, ref(A), 5, 1)
    js = J(S) or {}
    sid = js.get("series_id")
    occ = js.get("occurrences") or [{}] * 5
    days = [(date.fromisoformat(MON) + timedelta(days=7 * i)).isoformat() for i in range(5)]
    expect("P4.SA1a", "SA1", "Amend recurring reservations", "amend without token", req("POST", f"/series/{sid}/amend", key=K(), body={"expected_revision": 1, "from_index": 0, "local_time": "20:00"}), 401, "unauthenticated")
    expect("P4.SA1b", "SA1", "Amend recurring reservations", "amend another owner's series", amend(tb, sid, 1, 0, "20:00"), 404, "not_found")
    expect("P4.SA1c", "SA1", "Amend recurring reservations", "amend an unknown series", amend(ta, "nope", 1, 0, "20:00"), 404, "not_found")
    expect("P4.SA1d", "SA1", "stage-1 §7", "amend without Idempotency-Key", req("POST", f"/series/{sid}/amend", token=ta, body={"expected_revision": 1, "from_index": 0, "local_time": "20:00"}), 400, "missing_idempotency_key")
    bad = []
    for desc, rev, idx, lt in [("revision 0", 0, 0, "20:00"), ("revision '1'", "1", 0, "20:00"), ("revision true", True, 0, "20:00"), ("revision 1.5", 1.5, 0, "20:00"), ("from_index -1", 1, -1, "20:00"), ("from_index = count", 1, 5, "20:00"),
                               ("from_index true", 1, True, "20:00"), ("from_index '2'", 1, "2", "20:00"), ("local_time 24:00", 1, 0, "24:00"), ("local_time 8:00", 1, 0, "8:00"), ("local_time with seconds", 1, 0, "20:00:00"),
                               ("local_time 2000", 1, 0, "2000"), ("local_time number", 1, 0, 20), ("local_time 19:60", 1, 0, "19:60")]:
        r = amend(ta, sid, rev, idx, lt)
        if not (r.status_code == 422 and code(r) == "validation_failed"):
            bad.append(f"{desc}: {show(r)[:140]}")
    for desc, b in [("expected_revision missing", {"from_index": 0, "local_time": "20:00"}), ("from_index missing", {"expected_revision": 1, "local_time": "20:00"}), ("local_time missing", {"expected_revision": 1, "from_index": 0})]:
        r = req("POST", f"/series/{sid}/amend", token=ta, key=K(), body=b)
        if not (r.status_code == 422 and code(r) == "validation_failed"):
            bad.append(f"{desc}: {show(r)[:140]}")
    check("P4.SA2", "SA2", "Amend recurring reservations", "invalid expected_revision / from_index / local_time (booleans, strings, out of range, wrong format, missing) -> 422 validation_failed", not bad, bad[:5])
    expect("P4.SA3a", "SA3", "Amend recurring reservations", "mismatched series revision", amend(ta, sid, 7, 0, "20:00"), 409, "stale_revision")
    expect("P4.SA3b", "SA3", "Amend recurring reservations", "mismatched revision comes before booking validation (off-grid time)", amend(ta, sid, 7, 0, "20:10"), 409, "stale_revision")
    blk = bk(tb, "t_2", days[3], "21:00", 2)
    state = lambda: (J(getseries(ta, sid)), [hist(ta, o.get("reference")) for o in occ], rr(tm, "r_m"))
    s0 = state()
    kx = K()
    f = amend(ta, sid, 1, 2, "20:00", key=kx)
    check("P4.SA6a", "SA6/SA7", "Amend recurring reservations", "a resulting occurrence overlapping another diner's booking -> 409 table_unavailable; series, histories and revisions unchanged", blk.status_code == 201 and f.status_code == 409 and code(f) == "table_unavailable" and state() == s0, show(f))
    for desc, lt, ec in [("off the grid", "20:10", "not_on_slot_grid"), ("ending after closes", "22:00", "outside_opening_hours")]:
        r = amend(ta, sid, 1, 0, lt)
        check(f"P4.SA5{ec[0]}", "SA5", "Amend recurring reservations", f"amend to a time {desc} -> 422 {ec}, nothing changed", r.status_code == 422 and code(r) == ec and state() == s0, show(r))
    PX = pol(days[4], dur=60, hrs=hours("18:00", "21:00"))
    publish(tm, PX)
    s0 = state()
    f = amend(ta, sid, 1, 2, "20:30")
    check("P4.SA6b", "SA6", "Amend recurring reservations", "non-occupancy error takes precedence: index 3 would overlap (20:30-22:00 vs a booking at 21:00) but index 4 ends after its date's policy closes -> 422 outside_opening_hours", f.status_code == 422 and code(f) == "outside_opening_hours" and state() == s0, show(f))
    cancel(tb, ref(blk))
    r0 = rr(tm, "r_m")
    ok = amend(ta, sid, 1, 2, "20:00", key=kx, note="x")
    jo = J(ok) or {}
    oo = jo.get("occurrences") or [{}] * 5
    rs_ = [o.get("reservation", {}) for o in oo]
    check("P4.SA8a", "SA8/SA4/SA7", "Amend recurring reservations", "amend from index 2 to 20:00 (the key of the failed attempt is reusable; unknown field ignored) -> 201 current series: indices 2..4 at 20:00 on their original dates, 0..1 untouched; references, party and tables kept; series revision 2; no exception marks",
          ok.status_code == 201 and jo.get("revision") == 2 and [x.get("starts_at_local") for x in rs_] == [f"{d}T{'19:00' if i < 2 else '20:00'}" for i, d in enumerate(days)]
          and [o.get("reference") for o in oo] == [o.get("reference") for o in occ] and all(o.get("exception") is False for o in oo) and all(x.get("party_size") == 3 and x.get("table_ids") == ["t_2"] for x in rs_)
          and rs_[0] == occ[0].get("reservation") and rs_[1] == occ[1].get("reservation") and J(getseries(ta, sid)) == jo, show(ok)[:400])
    hs = [hist(ta, o.get("reference")) or [] for o in occ]
    check("P4.SA8b", "SA8", "Amend recurring reservations", "each changed occurrence: reservation revision 2 and one changed history entry naming starts_at_local; unchanged ones keep revision 1; restaurant revision +1 once",
          [x.get("revision") for x in rs_] == [1, 1, 2, 2, 2] and [len(h) for h in hs] == [1, 1, 2, 2, 2] and changes(hs[2][-1]) == [("starts_at_local", f"{days[2]}T19:00", f"{days[2]}T20:00")] and hs[2][-1].get("event") == "changed" and rr(tm, "r_m") == r0 + 1, [x.get("revision") for x in rs_])
    check("P4.SA5a", "SA5", "Amend recurring reservations", "each real change adopts the policy of its resulting date: index 4 now has the 60-minute policy's terms and end (21:00); indices 2-3 keep policy 0 (21:30)",
          rs_[4].get("accepted_terms") == terms_of(PX, 1) and rs_[4].get("ends_at", "")[11:16] == "21:00" and rs_[3].get("accepted_terms") == TERMS0 and rs_[3].get("ends_at", "")[11:16] == "21:30", (rs_[4].get("ends_at"), rs_[4].get("accepted_terms", {}).get("policy_version")))
    # no-op and replay
    n = amend(ta, sid, 2, 2, "20:00")
    check("P4.SA8c", "SA8/SA5", "Amend recurring reservations", "all-no-op amend -> 201 with unchanged series, reservation and restaurant revisions", n.status_code == 201 and J(n) == jo and rr(tm, "r_m") == r0 + 1 and [len(hist(ta, o.get("reference")) or []) for o in occ] == [1, 1, 2, 2, 2], show(n)[:200])
    # exceptions and cancelled occurrences are skipped
    patch(ta, occ[3]["reference"], {"party_size": 2})        # exception, series rev 3
    cancel(ta, occ[4]["reference"])                          # cancelled, series rev 4
    c0 = J(getseries(ta, sid)) or {}
    ok2 = amend(ta, sid, 4, 0, "19:30")
    j2 = J(ok2) or {}
    r2 = [o.get("reservation", {}) for o in j2.get("occurrences", [{}] * 5)]
    check("P4.SA4", "SA4/SA6", "Amend recurring reservations", "amend from index 0 skips the exception (index 3) and the cancelled occurrence (index 4); others move to 19:30 (overlapping their own old slot); flags unchanged; series revision 5",
          ok2.status_code == 201 and j2.get("revision") == 5 and [x.get("starts_at_local", "")[-5:] for x in r2] == ["19:30", "19:30", "19:30", "20:00", "20:00"] and r2[3] == c0["occurrences"][3]["reservation"] and r2[4] == c0["occurrences"][4]["reservation"]
          and [o.get("exception") for o in j2["occurrences"]] == [False, False, False, True, False], show(ok2)[:300])
    e = amend(ta, sid, 5, 3, "18:00")
    check("P4.SA8d", "SA8", "Amend recurring reservations", "empty eligible set (only an exception and a cancelled occurrence from index 3) -> 201, nothing changed", e.status_code == 201 and J(e) == j2, show(e)[:200])
    rp = amend(ta, sid, 1, 2, "20:00", key=kx, note="x")
    check("P4.SA1e", "SA1", "Amend recurring reservations", "replay of the first successful amend key -> 200 with the original response, after further edits and a cancellation; nothing changes", rp.status_code == 200 and J(rp) == jo and J(getseries(ta, sid)) == j2, show(rp)[:200])
    expect("P4.SA1f", "SA1", "stage-1 §7", "same key, different body", amend(ta, sid, 5, 0, "21:00", key=kx), 409, "idempotency_key_reuse")
    # closure blocks an amend
    pv = preview(tm, "t_2", iso(days[1], "21:00"), iso(days[1], "22:30"), rid="r_m")
    ap = apply_(tm, (J(pv) or {}).get("plan_id"), rid="r_m")
    s0 = J(getseries(ta, sid))
    f = amend(ta, sid, (s0 or {}).get("revision"), 0, "20:00")
    check("P4.SA6c", "SA6/AP5", "Amend recurring reservations", "amend into an applied closure (index 1 would run 20:00-21:30, t_2 closed 21:00-22:30) -> 409 table_unavailable, nothing changed", ap.status_code == 201 and f.status_code == 409 and code(f) == "table_unavailable" and J(getseries(ta, sid)) == s0, show(f))
    # SA9
    cur = J(getseries(ta, sid)) or {}
    rs = parallel([(lambda i=i: amend(ta, sid, cur.get("revision"), 0, ["18:00", "18:30", "19:00"][i % 3])) for i in range(12)])
    sts = sorted(x.status_code for x in rs)
    check("P4.SA9", "SA9", "Amend recurring reservations", "12 concurrent amends from one expected revision: exactly one 201, the rest 409 stale_revision; series revision +1", sts == [201] + [409] * 11 and all(code(x) == "stale_revision" for x in rs if x.status_code == 409)
          and (J(getseries(ta, sid)) or {}).get("revision") == cur.get("revision") + 1, sts)
    # DST and invalid local time
    G = book(ta, "r_night_b", "nb_1", "2027-03-21T01:00", 2)
    Sd = series(ta, ref(G), 2, 1)
    f = amend(ta, (J(Sd) or {}).get("series_id"), 1, 0, "02:30")
    check("P4.SA5d", "SA5", "Amend recurring reservations", "amend to a clock time that does not exist on occurrence 1's date (2027-03-28 02:30) -> 422 invalid_local_time", Sd.status_code == 201 and f.status_code == 422 and code(f) == "invalid_local_time", show(f))


def s_amend_cutoff():
    if os.environ.get("SKIP_WAIT"):
        note("P4.SA5c", "cutoff check in series amend skipped (SKIP_WAIT set)", "")
        return
    rmin = {"id": "r_min", "name": "Minute", "timezone": "Europe/Berlin", "slot_minutes": 1, "reservation_duration_minutes": 1, "cancellation_cutoff_minutes": 0,
            "opening_hours": hours("00:00", "23:59"), "tables": [{"id": "m_1", "label": "M1", "capacity": 4}], "manager_user_ids": ["u_mgr"]}
    reset(fx4(extra_rests=[rmin]))
    ta = p.ada()
    start = (datetime.now(p.ZoneInfo("Europe/Berlin")) + timedelta(minutes=2)).replace(second=0, microsecond=0, tzinfo=None)
    if start.hour == 23 and start.minute >= 50 or start.hour == 0 and start.minute < 5:
        note("P4.SA5c", "cutoff check in series amend skipped (too close to midnight)", "")
        return
    A = book(ta, "r_min", "m_1", start.strftime("%Y-%m-%dT%H:%M"), 2)
    S = series(ta, ref(A), 2, 1)
    sid = (J(S) or {}).get("series_id")
    wait = (start - datetime.now(p.ZoneInfo("Europe/Berlin")).replace(tzinfo=None)).total_seconds() + 3
    time.sleep(max(wait, 0))
    later = (start + timedelta(minutes=5)).strftime("%H:%M")
    f = amend(ta, sid, 1, 0, later)
    s0 = J(getseries(ta, sid))
    ok = amend(ta, sid, 1, 1, later)
    check("P4.SA5c", "SA5", "Amend recurring reservations", "each real change checks its old accepted cutoff: once the anchor has started, amend from index 0 -> 409 cutoff_passed (nothing changed); from index 1 (a week ahead) -> 201",
          A.status_code == 201 and S.status_code == 201 and f.status_code == 409 and code(f) == "cutoff_passed" and (s0 or {}).get("revision") == 1 and ok.status_code == 201 and (J(ok) or {}).get("revision") == 2, f"{show(f)[:150]} | {show(ok)[:150]}")


def s_export_import():
    reset(fx4())
    ta, tm = p.ada(), mgr()
    day = "2027-09-22"
    X = bp(ta, ["p_3"], day, "19:00", 4)
    A = bk(ta, "t_2", MON, "19:00", 2)
    S = series(ta, ref(A), 3, 1)
    sid = (J(S) or {}).get("series_id")
    k1, k2, k3, k4 = K(), K(), K(), K()
    PV = preview(tm, "p_3", iso(day, "19:00"), iso(day, "20:30"), key=k1)
    AP = apply_(tm, (J(PV) or {}).get("plan_id"), key=k2)
    AM = amend(ta, sid, 1, 1, "20:00", key=k3)
    PEND = preview(tm, "p_4", iso(day, "19:00"), iso(day, "20:30"), key=k4)
    snap = lambda base=None: (listing(ta, base=base), J(req("GET", f"/series/{sid}", token=ta, base=base)), J(req("GET", f"/reservations/{ref(X)}/history", token=ta, base=base)),
                              J(req("GET", f"/availability?restaurant_id=r_p&date={day}&party_size=2&explain=true", base=base)), rr(tm, base=base), rr(tm, "r_m", base=base))
    pre = snap()
    E = J(req("GET", "/_test/export", limit=10)) or {}
    check("P4.UP5a", "UP5", "stage-1 §10", "setup (apply, amend, pending plan) and export ok", [x.status_code for x in (X, S, PV, AP, AM, PEND)] == [201] * 6 and E.get("format_version") == 1, [x.status_code for x in (X, S, PV, AP, AM, PEND)])
    bp(ta, ["p_1"], "2027-09-29", "19:00", 1)
    cancel(ta, ref(X))
    bad = req("POST", "/_test/import", body=dict(E, track="pocketful"), limit=10)
    im = req("POST", "/_test/import", body=E, limit=10)
    post = snap()
    check("P4.UP5b", "UP5", "stage-1 §10", "import restores reservations, series, reassigned history, the closure (availability and explain) and both restaurant revisions; a rejected import changed nothing", bad.status_code == 422 and im.status_code == 204 and post == pre, [i for i, (a, b) in enumerate(zip(pre, post)) if a != b])
    rp = [preview(tm, "p_3", iso(day, "19:00"), iso(day, "20:30"), key=k1), apply_(tm, (J(PV) or {}).get("plan_id"), key=k2), amend(ta, sid, 1, 1, "20:00", key=k3), preview(tm, "p_4", iso(day, "19:00"), iso(day, "20:30"), key=k4)]
    check("P4.UP5c", "UP5", "stage-1 §10", "replan, apply and amend receipts replay 200 with the original bodies after import", [x.status_code for x in rp] == [200] * 4 and [J(x) for x in rp] == [J(PV), J(AP), J(AM), J(PEND)] and snap() == pre, [x.status_code for x in rp])
    expect("P4.UP5d", "UP5/AP3", "stage-1 §10", "the applied plan is still applied after import (different key)", apply_(tm, (J(PV) or {}).get("plan_id")), 409, "plan_already_applied")
    a = apply_(tm, (J(PEND) or {}).get("plan_id"))
    check("P4.UP5e", "UP5", "stage-1 §10", "the pending plan made before the export can be applied after import (201, revision continues)", a.status_code == 201 and (J(a) or {}).get("restaurant_revision") == pre[4] + 1, show(a)[:200])
    if BASE2:
        reset(p.SPEC_FIXTURE, base=BASE2)
        im2 = req("POST", "/_test/import", body=E, base=BASE2, limit=10)
        check("P4.UP5f", "UP5", "stage-1 §10", "import into a second stage-4 container shows the same state", im2.status_code == 204 and snap(BASE2) == pre, "")


def upgrade_from(tag, src, stage):
    if not src:
        check(f"P4.UP4{tag}", "UP4", "upgrade", "source container available", False, "not set")
        return
    reset(fx3() if stage == 3 else p.fixture(), base=src)
    ta = p.ada(src)
    k1 = K()
    rid, tid = ("r_m", "t_2") if stage == 3 else ("r_anker", "t_2")
    b1 = {"restaurant_id": rid, "table_id": tid, "starts_at_local": f"{THU}T19:00", "party_size": 2}
    R1 = req("POST", "/reservations", token=ta, key=k1, body=b1, base=src)
    exp_rev, sres, ks = 1, None, K()
    if stage == 3:
        sres = req("POST", "/series", token=ta, key=ks, body={"anchor_reference": ref(R1), "count": 4, "interval_weeks": 1}, base=src)
        occ = (J(sres) or {}).get("occurrences") or [{}] * 4
        req("PATCH", f"/reservations/{occ[1].get('reference')}", token=ta, body={"table_id": "t_3"}, base=src)       # moved -> exception
        req("POST", f"/reservations/{occ[2].get('reference')}/cancel", token=ta, base=src)                          # cancelled
        exp_rev = 4
    l1 = listing(ta, base=src)
    E = J(req("GET", "/_test/export", base=src, limit=10))
    reset(fx4())
    tm0 = mgr()
    im = req("POST", "/_test/import", body=E, limit=10)
    expect(f"P4.UP4{tag}a", "UP4", "Amend recurring reservations (upgrade paragraph)", f"stage-4 import of the unchanged stage-{stage} export", im, 204)
    l4 = listing(ta) or []
    okl = len(l4) == len(l1 or [None]) and all(all(y.get(k) == v for k, v in x.items()) for x, y in zip(l1 or [], l4))
    rp = req("POST", "/reservations", token=ta, key=k1, body=b1)
    check(f"P4.UP4{tag}b", "UP4", "upgrade", "sessions valid; imported reservations keep every earlier field; the original booking retry replays 200 unchanged", okl and rp.status_code == 200 and J(rp) == J(R1), show(rp)[:200])
    if stage == 3:
        tm = mgr()
        check(f"P4.UP4{tag}c", "UP4/RR1", "upgrade", "restaurant revision is taken from the stage-3 export (booking + adoption + amendment + cancel = 4); the series receipt replays unchanged",
              rr(tm, "r_m") == exp_rev and J(req("POST", "/series", token=ta, key=ks, body={"anchor_reference": ref(R1), "count": 4, "interval_weeks": 1})) == J(sres), rr(tm, "r_m"))
        sid = (J(sres) or {}).get("series_id")
        cur = J(getseries(ta, sid)) or {}
        am = amend(ta, sid, cur.get("revision"), 0, "20:00")
        ja = J(am) or {}
        got = [(o["reservation"]["starts_at_local"][-5:], o["exception"], o["reservation"]["status"]) for o in ja.get("occurrences", [])]
        check(f"P4.UP4{tag}d", "UP4/SA4", "Amend recurring reservations (upgrade paragraph)", "series amend works on an imported series with a moved (exception) and a cancelled occurrence: only indices 0 and 3 change",
              am.status_code == 201 and got == [("20:00", False, "confirmed"), ("19:00", True, "confirmed"), ("19:00", False, "cancelled"), ("20:00", False, "confirmed")], f"{show(am)[:200]} {got}")
        pv = preview(tm, "t_3", iso("2027-09-30", "18:00"), iso("2027-09-30", "22:00"), rid="r_m")
        ap = apply_(tm, (J(pv) or {}).get("plan_id"), rid="r_m")
        after = J(getseries(ta, sid)) or {"occurrences": [{}, {"reservation": {}}]}
        check(f"P4.UP4{tag}e", "UP4/AP8", "Amend recurring reservations (upgrade paragraph)", "a replan moves the imported exception occurrence off the closed table; it stays an exception; series revision +1",
              pv.status_code == 201 and ap.status_code == 201 and after["occurrences"][1]["reservation"].get("table_ids") not in (["t_3"], None) and after["occurrences"][1].get("exception") is True and after.get("revision") == ja.get("revision") + 1, show(ap)[:200])
    else:
        # managers do not exist in a stage-1/2 fixture, so replans are refused for everyone there; adoption and amend must work
        s = series(ta, ref(R1), 3, 1)
        am = amend(ta, (J(s) or {}).get("series_id"), 1, 1, "20:00")
        check(f"P4.UP4{tag}c", "UP4", "Amend recurring reservations (upgrade paragraph)", "adoption and series amend work on a reservation imported from this stage", s.status_code == 201 and am.status_code == 201 and (J(am) or {}).get("revision") == 2, f"{show(s)[:150]} | {show(am)[:150]}")
        r = preview(tm0, "t_1", iso(THU, "18:00"), iso(THU, "22:00"), rid="r_anker")
        note(f"P4.UP4{tag}n", "replan on an imported restaurant without managers", show(r)[:160])


def s_upgrade():
    upgrade_from("s1", S1BASE, 1)
    upgrade_from("s2", S2BASE, 2)
    upgrade_from("s3", S3BASE, 3)


def s_concurrency():
    users = [{"id": f"u_load_{i}", "email": f"load{i}@example.com", "password": f"load password {i}", "display_name": f"L{i}"} for i in range(50)]
    reset(fx4(extra_users=users))
    tm = mgr()
    rs = parallel([(lambda i=i: req("POST", "/auth/login", body={"email": f"load{i}@example.com", "password": f"load password {i}"})) for i in range(50)])
    toks = [(J(x) or {}).get("token") for x in rs]
    rnd = random.Random(9)
    hh = ["17:00", "17:30", "18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30"]
    opts = [[t] for t in PT] + rest_p()["combinable"]
    days = ["2027-09-22", "2027-09-23"]
    applied = []

    def worker(i, seed):
        rg = random.Random(seed)
        t = toks[i]
        out = []
        if i % 8 == 0:
            d, h = rg.choice(days), rg.choice(hh[:6])
            frm = iso(d, h)
            to = (datetime.fromisoformat(frm) + timedelta(minutes=rg.choice([60, 120]))).isoformat()
            tb_ = rg.choice(PT)
            pv = preview(tm, tb_, frm, to)
            out.append(pv)
            if pv.status_code == 201:
                a = apply_(tm, J(pv)["plan_id"])
                out.append(a)
                if a.status_code == 201:
                    applied.append((tb_, frm, to))
            return out
        b = bp(t, rg.choice(opts), rg.choice(days), rg.choice(hh), 1)
        out.append(b)
        if b.status_code == 201:
            x = rg.random()
            if x < 0.35:
                out.append(patch(t, ref(b), {"table_ids": rg.choice(opts), "starts_at_local": f"{rg.choice(days)}T{rg.choice(hh)}"}))
            elif x < 0.7:
                s = series(t, ref(b), 2, 1)
                out.append(s)
                if s.status_code == 201:
                    out.append(amend(t, J(s)["series_id"], 1, 0, rg.choice(hh)))
            elif x < 0.85:
                out.append(cancel(t, ref(b)))
        return out
    allr = []
    for _ in range(4):
        res = parallel([(lambda i=i, s=rnd.random(): worker(i, s)) for i in range(50)])
        allr += [x for o in res for x in o]
    okst = {200, 201, 409, 422}
    badst = [show(x)[:160] for x in allr if x.status_code not in okst or (x.status_code == 422 and code(x) != "planning_limit")]
    lists = {t: listing(t) or [] for t in toks}
    allc = [x for l in lists.values() for x in l if x.get("status") == "confirmed"]
    onclosed = [(x["reference"], tb_) for x in allc for tb_, f, z in applied if tb_ in x["table_ids"] and _dt(x["starts_at"]) < _dt(z) and _dt(x["ends_at"]) > _dt(f)]
    check("P4.CC4a", "CC4", "Seating changes", f"4 rounds x 50 in flight (book, PATCH, cancel, series + amend, preview + apply; {len(allr)} requests, {len(applied)} plans applied): only 200/201/409 (or 422 planning_limit); no overlapping confirmed bookings; no confirmed booking on a closed table inside its closure",
          not badst and not overlaps2(allc) and not onclosed, f"{badst[:2]} {overlaps2(allc)[:2]} {onclosed[:2]}")
    bad = []
    for t, l in lists.items():
        for x in l[:5]:
            h = hist(t, x["reference"]) or []
            if not (seq_ok(h) and h and h[-1].get("revision") == x.get("revision") == len(h)):
                bad.append((x["reference"], x.get("revision"), [(e.get("seq"), e.get("revision"), e.get("event")) for e in h]))
    check("P4.CC4b", "CC4", "Reservation history", "after load every sampled reservation has history seq 1..k and revision k (reassigned entries included)", not bad, bad[:2])


def main():
    only = set(sys.argv[1:])
    for s in [s_preview, s_apply, s_plan_series, s_revision, s_limits, s_amend, s_export_import, s_upgrade, s_oracle, s_concurrency, s_amend_cutoff]:
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
