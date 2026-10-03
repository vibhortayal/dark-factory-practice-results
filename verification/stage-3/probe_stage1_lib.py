#!/usr/bin/env python3
"""Stage-1 Tablekeeper verifier probes. Check ids refer to CHECKS.md.

Usage: BASE=http://host:port [BASE2=http://host2:port] [OUT=results.json] python probe.py
Exit code 1 when any check fails or errors.
"""
import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

BASE = os.environ.get("BASE", "http://127.0.0.1:8080").rstrip("/")
BASE2 = os.environ.get("BASE2", "").rstrip("/")
OUT = os.environ.get("OUT")

client = httpx.Client(timeout=30, limits=httpx.Limits(max_connections=200, max_keepalive_connections=100))

RESULTS = []      # dict(id,row,sec,desc,ok,detail)
NOTES = []
LOCK = threading.Lock()
FIVEXX, BADERR, BADCT, BADTS, SLOW = [], [], [], [], []
CREATED = {}      # token -> set(reference) created through book()
_NO = object()
TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)$")
REF_RE = re.compile(r"^[A-Z0-9]{6,12}$")
RES_KEYS = ["reservation_id", "reference", "restaurant_id", "table_id", "party_size", "status",
            "starts_at_local", "starts_at", "ends_at", "created_at"]

THU, FRI, WED, THU2 = "2027-09-23", "2027-09-24", "2027-09-22", "2027-09-30"
assert [datetime.fromisoformat(d).weekday() for d in (THU, FRI, WED, THU2)] == [3, 4, 2, 3]
PAST_THU = "2020-09-24"
assert datetime.fromisoformat(PAST_THU).weekday() == 3


# ---------------------------------------------------------------- framework
def check(cid, row, sec, desc, ok, detail=""):
    ok = bool(ok)
    with LOCK:
        RESULTS.append(dict(id=cid, row=row, sec=sec, desc=desc, ok=ok, detail="" if ok else str(detail)[:600]))
    print(("PASS " if ok else "FAIL ") + f"{cid} [{row} {sec}] {desc}" + ("" if ok else f" :: {str(detail)[:600]}"), flush=True)
    return ok


def note(cid, desc, detail):
    NOTES.append(dict(id=cid, desc=desc, detail=str(detail)[:400]))
    print(f"NOTE {cid} {desc} :: {str(detail)[:400]}", flush=True)


STRIP = [k for k in os.environ.get("STRIP_KEYS", "").split(",") if k]


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in STRIP}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def J(r):
    """Parsed body. STRIP_KEYS (env) removes fields a later stage adds and legitimately changes
    (e.g. `revision` from stage 3 on), so earlier-stage equality checks compare the fields they know."""
    try:
        return _strip(r.json()) if STRIP else r.json()
    except Exception:
        return None


def code(r):
    j = J(r)
    try:
        return j["error"]["code"]
    except Exception:
        return None


def show(r):
    return f"{r.request.method} {r.request.url.raw_path.decode()} -> {r.status_code} {r.text[:240]}"


def expect(cid, row, sec, desc, r, status, ecode=None):
    st = status if isinstance(status, tuple) else (status,)
    ok = r.status_code in st
    if ok and ecode is not None:
        ec = ecode if isinstance(ecode, tuple) else (ecode,)
        ok = code(r) in ec
    return check(cid, row, sec, f"{desc} -> {status}{' ' + str(ecode) if ecode else ''}", ok, show(r))


def _scan_ts(obj, where):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("starts_at", "ends_at", "created_at"):
                if not (isinstance(v, str) and TS_RE.match(v)):
                    BADTS.append(f"{where}: {k}={v!r}")
            else:
                _scan_ts(v, where)
    elif isinstance(obj, list):
        for v in obj:
            _scan_ts(v, where)


def audit(r, dt, limit):
    where = f"{r.request.method} {r.request.url.raw_path.decode()[:120]} -> {r.status_code}"
    with LOCK:
        if r.status_code >= 500:
            FIVEXX.append(f"{where} {r.text[:200]}")
        if dt > limit:
            SLOW.append(f"{where} took {dt:.2f}s (limit {limit}s)")
        if r.content:
            ct = r.headers.get("content-type", "").lower().replace(" ", "")
            if ct != "application/json;charset=utf-8":
                BADCT.append(f"{where}: content-type={r.headers.get('content-type')!r}")
        j = J(r)
        if r.status_code >= 400:
            e = j.get("error") if isinstance(j, dict) else None
            if not (isinstance(e, dict) and isinstance(e.get("code"), str) and isinstance(e.get("message"), str)):
                BADERR.append(f"{where}: body={r.text[:200]!r}")
        elif "/_test/export" not in where:
            _scan_ts(j, where)


def req(method, path, token=None, key=None, body=_NO, raw=None, headers=None, base=None, limit=5.0):
    h = {}
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    if key is not None:
        h["Idempotency-Key"] = key
    kw = {}
    if raw is not None:
        kw["content"] = raw if isinstance(raw, bytes) else raw.encode()
        h["Content-Type"] = "application/json"
    elif body is not _NO:
        kw["content"] = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if headers:
        h.update(headers)
    t = time.monotonic()
    r = client.request(method, (base or BASE) + path, headers=h, **kw)
    audit(r, time.monotonic() - t, limit)
    return r


def section(fn):
    print(f"\n=== {fn.__name__} ===", flush=True)
    try:
        fn()
    except Exception:
        check(f"CRASH.{fn.__name__}", "-", "-", f"section {fn.__name__} ran to completion", False, traceback.format_exc()[-600:])


def parallel(fns, workers=50):
    barrier = threading.Barrier(len(fns)) if len(fns) <= workers else None

    def run(f):
        if barrier:
            try:
                barrier.wait(timeout=20)
            except Exception:
                pass
        return f()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(run, fns))


# ---------------------------------------------------------------- domain helpers
ALLDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def hours(opens, closes, days=ALLDAYS):
    return [{"weekday": d, "opens": opens, "closes": closes} for d in days]


def fixture(reservations=None, extra_users=None):
    return {
        "users": [
            {"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada"},
            {"id": "u_bob", "email": "bob@example.com", "password": "battery staple", "display_name": "Bob"},
        ] + (extra_users or []),
        "restaurants": [
            {"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin", "slot_minutes": 30,
             "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
             "opening_hours": [{"weekday": "thu", "opens": "18:00", "closes": "23:00"},
                               {"weekday": "fri", "opens": "18:00", "closes": "23:30"}],
             "tables": [{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4}]},
            {"id": "r_ny", "name": "Harbor", "timezone": "America/New_York", "slot_minutes": 30,
             "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 60,
             "opening_hours": hours("10:00", "23:00"),
             "tables": [{"id": "n_1", "label": "N1", "capacity": 4}]},
            {"id": "r_night_b", "name": "Nachtcafe", "timezone": "Europe/Berlin", "slot_minutes": 30,
             "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 0,
             "opening_hours": hours("00:00", "06:00", ["sun"]),
             "tables": [{"id": "nb_1", "label": "B1", "capacity": 4}, {"id": "nb_2", "label": "B2", "capacity": 4}]},
            {"id": "r_night_ny", "name": "Night Owl", "timezone": "America/New_York", "slot_minutes": 30,
             "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 0,
             "opening_hours": hours("00:00", "06:00", ["sun"]),
             "tables": [{"id": "nn_1", "label": "O1", "capacity": 4}, {"id": "nn_2", "label": "O2", "capacity": 4}]},
            {"id": "r_odd", "name": "Odd Grid", "timezone": "Europe/Berlin", "slot_minutes": 20,
             "reservation_duration_minutes": 45, "cancellation_cutoff_minutes": 0,
             "opening_hours": hours("18:15", "20:00"),
             "tables": [{"id": "t_z", "label": "Z", "capacity": 6}, {"id": "t_a", "label": "A", "capacity": 2},
                        {"id": "t_m", "label": "M", "capacity": 4}]},
            {"id": "r_all", "name": "Always", "timezone": "Europe/Berlin", "slot_minutes": 15,
             "reservation_duration_minutes": 15, "cancellation_cutoff_minutes": 600,
             "opening_hours": hours("00:00", "23:59"),
             "tables": [{"id": "a_1", "label": "A1", "capacity": 4}, {"id": "a_2", "label": "A2", "capacity": 4}]},
            {"id": "r_all30", "name": "Always30", "timezone": "Europe/Berlin", "slot_minutes": 15,
             "reservation_duration_minutes": 15, "cancellation_cutoff_minutes": 30,
             "opening_hours": hours("00:00", "23:59"),
             "tables": [{"id": "b_1", "label": "B1", "capacity": 4}]},
        ],
        "reservations": reservations or [],
    }


def reset(fx=None, base=None):
    return req("POST", "/_test/reset", body=fx if fx is not None else fixture(), base=base, limit=10)


def login(email, pw, base=None):
    r = req("POST", "/auth/login", body={"email": email, "password": pw}, base=base)
    j = J(r) or {}
    return j.get("token") if r.status_code == 200 else None


def ada(base=None):
    return login("ada@example.com", "correct horse", base)


def bob(base=None):
    return login("bob@example.com", "battery staple", base)


def signup(email=None, pw="password123", name="New"):
    email = email or f"u{uuid.uuid4().hex[:12]}@example.com"
    r = req("POST", "/auth/signup", body={"email": email, "password": pw, "display_name": name})
    j = J(r) or {}
    return j.get("token"), j.get("user_id"), email


def K():
    return uuid.uuid4().hex


def book(tok, rid, tid, when, party, key=None, extra=None, base=None):
    b = {"restaurant_id": rid, "table_id": tid, "starts_at_local": when, "party_size": party}
    if extra:
        b.update(extra)
    r = req("POST", "/reservations", token=tok, key=key or K(), body=b, base=base)
    if r.status_code == 201 and isinstance(J(r), dict):
        with LOCK:
            CREATED.setdefault(tok, set()).add(J(r).get("reference"))
    return r


def ref(r):
    return (J(r) or {}).get("reference")


def get(tok, reference, base=None):
    return req("GET", f"/reservations/{reference}", token=tok, base=base)


def listing(tok, base=None):
    r = req("GET", "/reservations", token=tok, base=base)
    j = J(r)
    return j.get("reservations") if isinstance(j, dict) else None


def cancel(tok, reference):
    return req("POST", f"/reservations/{reference}/cancel", token=tok)


def patch(tok, reference, body):
    return req("PATCH", f"/reservations/{reference}", token=tok, body=body)


def moves(tok, items, key=None):
    return req("POST", "/reservation-moves", token=tok, key=key or K(), body={"moves": items})


def avail(rid, date, party, base=None, extra=""):
    return req("GET", f"/availability?restaurant_id={rid}&date={date}&party_size={party}{extra}", base=base)


def slots(rid, date, party, base=None):
    j = J(avail(rid, date, party, base)) or {}
    return {s.get("starts_at_local"): s for s in j.get("slots", []) if isinstance(s, dict)}


def tables_at(rid, date, hhmm, party):
    return (slots(rid, date, party).get(f"{date}T{hhmm}") or {}).get("available_table_ids")


def same_ts(actual, expected):
    try:
        a, e = datetime.fromisoformat(actual), datetime.fromisoformat(expected)
        return a == e and a.utcoffset() == e.utcoffset()
    except Exception:
        return False


def shape_problems(d):
    p = []
    if not isinstance(d, dict):
        return [f"not an object: {d!r}"]
    for k in RES_KEYS:
        if k not in d:
            p.append(f"missing {k}")
    if p:
        return p
    if not (isinstance(d["reservation_id"], str) and 0 < len(d["reservation_id"]) <= 64):
        p.append("reservation_id not a string of 1..64 chars")
    if not (isinstance(d["reference"], str) and REF_RE.match(d["reference"])):
        p.append(f"reference {d['reference']!r} not [A-Z0-9]{{6,12}}")
    if type(d["party_size"]) is not int:
        p.append("party_size not an integer")
    if d["status"] not in ("confirmed", "cancelled"):
        p.append(f"status {d['status']!r}")
    if not re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d$", str(d["starts_at_local"])):
        p.append(f"starts_at_local {d['starts_at_local']!r}")
    for k in ("starts_at", "ends_at", "created_at"):
        if not (isinstance(d[k], str) and TS_RE.match(d[k])):
            p.append(f"{k} {d[k]!r} not RFC3339 with offset")
    return p


def slot_after(minutes, tz="Europe/Berlin"):
    t = (datetime.now(ZoneInfo(tz)) + timedelta(minutes=minutes)).replace(second=0, microsecond=0, tzinfo=None)
    t += timedelta(minutes=(15 - t.minute % 15) % 15)
    if t.hour == 23 and t.minute > 30:
        t = (t + timedelta(days=1)).replace(hour=0, minute=0)
    return t.strftime("%Y-%m-%dT%H:%M")


def no_overlap(reservations):
    """reservations: list of confirmed reservation bodies. Returns list of overlapping pairs."""
    by = {}
    for x in reservations:
        by.setdefault((x["restaurant_id"], x["table_id"]), []).append(x)
    bad = []
    for k, xs in by.items():
        xs.sort(key=lambda x: datetime.fromisoformat(x["starts_at"]))
        for a, b in zip(xs, xs[1:]):
            if datetime.fromisoformat(a["ends_at"]) > datetime.fromisoformat(b["starts_at"]):
                bad.append((k, a["reference"], a["starts_at"], b["reference"], b["starts_at"]))
    return bad


# ---------------------------------------------------------------- sections
SPEC_FIXTURE = {
    "users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada"}],
    "restaurants": [{
        "id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin", "slot_minutes": 30,
        "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
        "opening_hours": [{"weekday": "thu", "opens": "18:00", "closes": "23:00"},
                          {"weekday": "fri", "opens": "18:00", "closes": "23:30"}],
        "tables": [{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4}]}],
    "reservations": [],
}


def s_health_reset():
    r = req("GET", "/health")
    check("C2.1", "C2", "§3.2", "GET /health -> 200 {status: ok}", r.status_code == 200 and J(r) == {"status": "ok"}, show(r))
    r = reset(SPEC_FIXTURE)
    check("M1.1", "M1", "§4", "spec example fixture accepted verbatim -> 204 with empty body",
          r.status_code == 204 and not r.content, show(r))
    r = req("POST", "/auth/login", body={"email": "ada@example.com", "password": "correct horse"})
    j = J(r) or {}
    check("M2.1", "M2", "§4", "seeded user logs in immediately; user_id/display_name from fixture",
          r.status_code == 200 and j.get("user_id") == "u_ada" and j.get("display_name") == "Ada"
          and isinstance(j.get("token"), str) and j.get("token"), show(r))
    r = reset()
    expect("C3.1", "C3", "§3.3", "reset without auth", r, 204)
    ta = ada()
    tx, _, ex = signup()
    k = K()
    b1 = book(ta, "r_anker", "t_2", f"{THU}T19:00", 4, key=k)
    bx = book(tx, "r_anker", "t_1", f"{THU}T19:00", 2)
    check("C3.0", "C3", "§3.3", "setup before second reset (bookings created)", b1.status_code == 201 and bx.status_code == 201, show(b1) + " | " + show(bx))
    r1, r2 = reset(), reset()
    check("C3.3", "C3", "§3.3", "repeated reset of same fixture -> 204 twice", r1.status_code == 204 and r2.status_code == 204, show(r2))
    expect("C3.2a", "C3", "§3.3", "token issued before reset is no longer valid", req("GET", "/reservations", token=ta), 401, "unauthenticated")
    expect("C3.2b", "C3", "§3.3", "user signed up before reset cannot log in", req("POST", "/auth/login", body={"email": ex, "password": "password123"}), 401, "unauthenticated")
    ta = ada()
    check("C3.2c", "C3", "§3.3", "reservations from before reset are gone", listing(ta) == [], listing(ta))
    check("C3.2d", "C3", "§3.3", "table free again after reset", tables_at("r_anker", THU, "19:00", 2) == ["t_1", "t_2"], tables_at("r_anker", THU, "19:00", 2))
    r = book(ta, "r_anker", "t_1", f"{THU}T20:00", 1, key=k)
    expect("C3.2e", "C3", "§3.3", "idempotency key used before reset is fresh (different body)", r, 201)
    other = {"users": [], "restaurants": [{"id": "r_other", "name": "Other", "timezone": "America/New_York", "slot_minutes": 60,
             "reservation_duration_minutes": 60, "cancellation_cutoff_minutes": 0, "opening_hours": hours("12:00", "14:00"),
             "tables": [{"id": "o_1", "label": "1", "capacity": 2}]}], "reservations": []}
    expect("C3.3b", "C3", "§3.3", "reset with a different fixture", reset(other), 204)
    r = req("GET", "/restaurants")
    ids = [x.get("id") for x in (J(r) or {}).get("restaurants", [])]
    check("C3.2f", "C3", "§3.3", "only the new fixture's restaurants are visible", ids == ["r_other"], ids)
    expect("C3.2g", "C3", "§3.3", "restaurant of previous fixture gone", req("GET", "/restaurants/r_anker"), 404, "not_found")
    expect("C3.2h", "C3", "§3.3", "user of previous fixture gone", req("POST", "/auth/login", body={"email": "ada@example.com", "password": "correct horse"}), 401, "unauthenticated")
    expect("C3.4a", "C3", "§5", "reset with unparseable body", req("POST", "/_test/reset", raw="{not json", limit=10), 400, "malformed_request")
    expect("C3.4b", "C3", "§5", "reset with users of wrong JSON type", req("POST", "/_test/reset", body={"users": "x", "restaurants": [], "reservations": []}, limit=10), 400, "malformed_request")
    rj = json.dumps(SPEC_FIXTURE["restaurants"][0])
    for cid, desc, raw in [
            ("C3.4c", "restaurants of wrong JSON type (object)", '{"users": [], "restaurants": {}, "reservations": []}'),
            ("C3.4d", "slot_minutes of wrong JSON type (string)", '{"users": [], "restaurants": [%s], "reservations": []}' % rj.replace('"slot_minutes": 30', '"slot_minutes": "30"')),
            ("C3.4e", "restaurant id of wrong JSON type (number)", '{"users": [], "restaurants": [%s], "reservations": []}' % rj.replace('"id": "r_anker"', '"id": 7')),
            ("C3.4f", "user email of wrong JSON type (number)", '{"users": [{"id": "u1", "email": 5, "password": "password1", "display_name": "x"}], "restaurants": [], "reservations": []}')]:
        expect(cid, "C3/E2", "§5", f"reset with {desc}", req("POST", "/_test/reset", raw=raw, limit=10), 400, "malformed_request")
    r = req("GET", "/definitely/not/a/route")
    check("E1.1a", "E1", "§5", "unknown route -> 4xx with error body", 400 <= r.status_code < 500, show(r))
    r = req("DELETE", "/restaurants")
    check("E1.1b", "E1", "§5", "unsupported method -> 4xx with error body", 400 <= r.status_code < 500, show(r))


def s_auth():
    reset()
    e = f"n{uuid.uuid4().hex[:10]}@example.com"
    r = req("POST", "/auth/signup", body={"email": e, "password": "correct horse", "display_name": "Nia", "zzz": [1]})
    j = J(r) or {}
    check("A1.1", "A1", "§6", "signup -> 201 {user_id, display_name, token} (unknown field ignored, C6.1)",
          r.status_code == 201 and isinstance(j.get("user_id"), str) and 0 < len(j["user_id"]) <= 64
          and j.get("display_name") == "Nia" and isinstance(j.get("token"), str) and j["token"], show(r))
    t0, uid = j.get("token"), j.get("user_id")
    check("A1.2", "A1", "§6", "signup token authenticates", listing(t0) == [], listing(t0))
    r = req("POST", "/auth/login", body={"email": e, "password": "correct horse", "extra": True})
    j = J(r) or {}
    check("A2.1", "A2", "§6", "login -> 200 same shape and same user_id",
          r.status_code == 200 and j.get("user_id") == uid and j.get("display_name") == "Nia" and isinstance(j.get("token"), str) and j["token"], show(r))
    t1 = j.get("token")
    t2 = login(e, "correct horse")
    oks = [listing(t) == [] for t in (t0, t1, t2)]
    check("A7.1", "A7", "§6", "signup token and two login tokens all valid concurrently", all(oks), oks)
    expect("A3.1a", "A3", "§6", "signup with an already registered email", req("POST", "/auth/signup", body={"email": e, "password": "another pass", "display_name": "X"}), 409, "email_taken")
    expect("A3.1b", "A3", "§6", "signup with a seeded email", req("POST", "/auth/signup", body={"email": "ada@example.com", "password": "another pass", "display_name": "X"}), 409, "email_taken")
    check("A3.1c", "A3", "§6", "rejected duplicate signup did not change the password", login(e, "another pass") is None and login(e, "correct horse"), "")
    expect("A4.1a", "A4", "§6", "password of 7 characters", req("POST", "/auth/signup", body={"email": f"p7{uuid.uuid4().hex[:8]}@example.com", "password": "1234567", "display_name": "X"}), 422, "validation_failed")
    expect("A4.1b", "A4", "§6", "password of 8 characters", req("POST", "/auth/signup", body={"email": f"p8{uuid.uuid4().hex[:8]}@example.com", "password": "12345678", "display_name": "X"}), 201)
    for i, bad in enumerate(["nodomain", "@x.com", "a@", ""]):
        expect(f"A4.2{'abcd'[i]}", "A4", "§6", f"signup email {bad!r} not local@domain", req("POST", "/auth/signup", body={"email": bad, "password": "correct horse", "display_name": "X"}), 422, "validation_failed")
    expect("A4.3a", "A4", "§5", "signup missing email", req("POST", "/auth/signup", body={"password": "correct horse", "display_name": "X"}), 422, "validation_failed")
    expect("A4.3b", "A4", "§5", "signup missing password", req("POST", "/auth/signup", body={"email": f"m{uuid.uuid4().hex[:8]}@example.com", "display_name": "X"}), 422, "validation_failed")
    expect("A4.3c", "A4", "§5", "login missing password", req("POST", "/auth/login", body={"email": e}), 422, "validation_failed")
    expect("E2.3a", "E2", "§5", "signup email of wrong JSON type (number)", req("POST", "/auth/signup", body={"email": 5, "password": "correct horse", "display_name": "X"}), 400, "malformed_request")
    expect("E2.3b", "E2", "§5", "signup password of wrong JSON type (number)", req("POST", "/auth/signup", body={"email": f"t{uuid.uuid4().hex[:8]}@example.com", "password": 123456789, "display_name": "X"}), 400, "malformed_request")
    expect("E2.3g", "E2", "§5", "signup display_name of wrong JSON type (number)", req("POST", "/auth/signup", body={"email": f"t{uuid.uuid4().hex[:8]}@example.com", "password": "correct horse", "display_name": 5}), 400, "malformed_request")
    expect("E2.3c", "E2", "§5", "login password of wrong JSON type (array)", req("POST", "/auth/login", body={"email": e, "password": ["x"]}), 400, "malformed_request")
    expect("E2.1a", "E2", "§5", "signup unparseable body", req("POST", "/auth/signup", raw='{"email": '), 400, "malformed_request")
    expect("E2.1b", "E2", "§5", "login unparseable body", req("POST", "/auth/login", raw="nope"), 400, "malformed_request")
    expect("E2.2a", "E2", "§5", "signup body is a JSON array, not an object", req("POST", "/auth/signup", body=["a"]), 400, "malformed_request")
    expect("A5.1a", "A5", "§6", "login wrong password", req("POST", "/auth/login", body={"email": e, "password": "wrong password"}), 401, "unauthenticated")
    expect("A5.1b", "A5", "§6", "login unknown email", req("POST", "/auth/login", body={"email": "nobody@example.com", "password": "correct horse"}), 401, "unauthenticated")
    r = req("POST", "/auth/signup", body={"email": f"d{uuid.uuid4().hex[:8]}@example.com", "password": "correct horse"})
    note("A4.3n1", "signup without display_name", show(r))
    r = req("POST", "/auth/signup", body={"email": f"l{uuid.uuid4().hex[:8]}@localhost", "password": "correct horse", "display_name": "X"})
    note("A4.3n2", "signup with dot-less domain x@localhost", show(r))
    r = req("POST", "/auth/signup", body={"email": e.upper(), "password": "correct horse", "display_name": "X"})
    note("A3.n1", "signup with upper-cased duplicate email", show(r))
    # A6: protected endpoints
    ta = ada()
    rr = ref(book(ta, "r_anker", "t_1", f"{THU}T19:00", 2))
    body = {"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": f"{THU}T19:00", "party_size": 2}
    prot = [("GET", "/reservations", None), ("GET", f"/reservations/{rr}", None), ("POST", f"/reservations/{rr}/cancel", None),
            ("PATCH", f"/reservations/{rr}", {"party_size": 1}), ("POST", "/reservations", body),
            ("POST", "/reservation-moves", {"moves": [{"reference": rr}]})]
    variants = [("no header", {}), ("scheme only", {"Authorization": "Bearer"}), ("Basic scheme", {"Authorization": "Basic abc"}),
                ("valid token without Bearer", {"Authorization": ta or "x"}), ("unknown token", {"Authorization": "Bearer not-a-real-token"})]
    for i, (m, p, b) in enumerate(prot):
        bad = []
        for name, h in variants:
            hh = dict(h)
            if m == "POST" and b is not None:
                hh["Idempotency-Key"] = K()
            r = req(m, p, body=b if b is not None else _NO, headers=hh)
            if not (r.status_code == 401 and code(r) == "unauthenticated"):
                bad.append(f"{name}: {show(r)}")
        check(f"A6.1{'abcdef'[i]}", "A6", "§6", f"{m} {p.replace(str(rr), '{ref}')} without/malformed/unknown token -> 401 unauthenticated", not bad, bad)
    g = get(ta, rr)
    check("A6.1g", "A6", "§6", "unauthenticated attempts changed nothing", (J(g) or {}).get("status") == "confirmed" and (J(g) or {}).get("party_size") == 2 and len(listing(ta) or []) == 1, show(g))
    pub = [req("GET", "/health"), req("GET", "/restaurants"), req("GET", "/restaurants/r_anker"), avail("r_anker", THU, 2)]
    check("A6.2", "A6", "§6/§8", "public endpoints answer 200 without a token", all(x.status_code == 200 for x in pub), [show(x) for x in pub if x.status_code != 200])


def s_restaurants_availability():
    fx = fixture()
    reset(fx)
    r = req("GET", "/restaurants?foo=bar")
    lst = (J(r) or {}).get("restaurants")
    want = sorted([{"id": x["id"], "name": x["name"], "timezone": x["timezone"]} for x in fx["restaurants"]], key=lambda x: x["id"])
    got = sorted([{k: x.get(k) for k in ("id", "name", "timezone")} for x in (lst or [])], key=lambda x: str(x["id"]))
    check("R1.1", "R1", "§8", "GET /restaurants lists every restaurant with id, name, timezone (unknown query param ignored, C6.2)", r.status_code == 200 and got == want, show(r))
    bad = []
    for x in fx["restaurants"]:
        r = req("GET", f"/restaurants/{x['id']}?unknown=1")
        j = J(r) or {}
        for k in ("slot_minutes", "reservation_duration_minutes", "cancellation_cutoff_minutes", "opening_hours", "tables"):
            if j.get(k) != x[k]:
                bad.append(f"{x['id']}.{k}: {j.get(k)!r} != {x[k]!r}")
    check("R2.1", "R2", "§8", "GET /restaurants/{id} returns config, opening_hours and tables in the fixture's shape", not bad, bad[:4])
    expect("R2.2", "R2", "§8", "GET /restaurants/{unknown}", req("GET", "/restaurants/r_nope"), 404, "not_found")
    # V1
    expect("V1.1a", "V1", "§8", "availability missing restaurant_id", req("GET", f"/availability?date={THU}&party_size=2"), 422, "validation_failed")
    expect("V1.1b", "V1", "§8", "availability missing date", req("GET", "/availability?restaurant_id=r_anker&party_size=2"), 422, "validation_failed")
    expect("V1.1c", "V1", "§8", "availability missing party_size", req("GET", f"/availability?restaurant_id=r_anker&date={THU}"), 422, "validation_failed")
    for i, d in enumerate(["2026-02-30", "2026-13-01", "24-09-2026", "tomorrow"]):
        expect(f"V2.1{'abcd'[i]}", "V2/E3", "§5", f"availability date={d}", avail("r_anker", d, 2), 422, "validation_failed")
    for i, p in enumerate(["1e9", "4.0", "%2B4", "abc", "-1", "0", ""]):
        expect(f"E6.1{'abcdefg'[i]}", "E6", "§5", f"availability party_size={p!r}", avail("r_anker", THU, p), 422, "validation_failed")
    expect("V2.2", "V2", "§8", "availability unknown restaurant", avail("r_nope", THU, 2), 404, "not_found")
    r = avail("r_anker", THU, 4, extra="&utm=x&zzz=1")
    j = J(r) or {}
    sl = j.get("slots") or []
    locs = [s.get("starts_at_local") for s in sl]
    want = [f"{THU}T{h}" for h in ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30"]]
    check("V3.1", "V3", "§8", "availability top-level shape (restaurant_id, date, timezone, slots) with unknown query params ignored",
          r.status_code == 200 and j.get("restaurant_id") == "r_anker" and j.get("date") == THU and j.get("timezone") == "Europe/Berlin" and isinstance(j.get("slots"), list), show(r))
    check("V4.1a", "V4", "§8", "Thu 18:00-23:00, slot 30, duration 90 -> slots 18:00..21:30", locs == want, locs)
    check("V3.2", "V3", "§8", "each slot has starts_at_local, starts_at (+02:00), available_table_ids",
          sl and all(same_ts(s.get("starts_at"), s.get("starts_at_local", "") + ":00+02:00") and isinstance(s.get("available_table_ids"), list) for s in sl), sl[:2])
    check("V4.2a", "V4", "§8", "party 4 (= capacity of t_2) -> [t_2] in every slot", sl and all(s.get("available_table_ids") == ["t_2"] for s in sl), sl[:2])
    s2 = slots("r_anker", THU, 2)
    check("V4.2b", "V4", "§8", "party 2 (= capacity of t_1) -> [t_1, t_2]", s2 and all(s["available_table_ids"] == ["t_1", "t_2"] for s in s2.values()), list(s2.values())[:2])
    s3 = slots("r_anker", THU, 3)
    check("V4.2c", "V4", "§8", "party 3 (capacity+1 of t_1) -> [t_2]", s3 and all(s["available_table_ids"] == ["t_2"] for s in s3.values()), list(s3.values())[:2])
    s5 = slots("r_anker", THU, 5)
    check("V4.2d", "V4", "§8", "party 5: slots still appear, each with empty list", list(s5) == want and all(s["available_table_ids"] == [] for s in s5.values()), list(s5.values())[:2])
    sf = slots("r_anker", FRI, 2)
    check("V4.1b", "V4", "§8", "Fri closes 23:30 -> last slot 22:00 (9 slots)", list(sf) == [f"{FRI}T{h}" for h in ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30", "22:00"]], list(sf))
    so = slots("r_odd", THU, 1)
    check("V4.1c", "V4", "§8", "grid from opens: 18:15 / 20 min / 45 min / closes 20:00 -> 18:15,18:35,18:55,19:15", list(so) == [f"{THU}T{h}" for h in ["18:15", "18:35", "18:55", "19:15"]], list(so))
    check("V4.2e", "V4", "§8", "available_table_ids in fixture order (t_z, t_a, t_m)", so and all(s["available_table_ids"] == ["t_z", "t_a", "t_m"] for s in so.values()), list(so.values())[:1])
    so3 = slots("r_odd", THU, 3)
    check("V4.2f", "V4", "§8", "fixture order kept after capacity filter (t_z, t_m)", so3 and all(s["available_table_ids"] == ["t_z", "t_m"] for s in so3.values()), list(so3.values())[:1])
    r = avail("r_anker", WED, 2)
    check("V5.1", "V5/M5", "§8/§4", "closed weekday -> 200 with slots []", r.status_code == 200 and (J(r) or {}).get("slots") == [], show(r))
    ta = ada()
    b = book(ta, "r_anker", "t_2", f"{THU}T19:30", 2)
    s2 = slots("r_anker", THU, 2)
    got = {k[-5:]: v["available_table_ids"] for k, v in s2.items()}
    wantm = {"18:00": ["t_1", "t_2"], "18:30": ["t_1"], "19:00": ["t_1"], "19:30": ["t_1"], "20:00": ["t_1"], "20:30": ["t_1"], "21:00": ["t_1", "t_2"], "21:30": ["t_1", "t_2"]}
    check("V4.3", "V4/B3", "§8/§1", "booking 19:30-21:00 on t_2 removes t_2 from 18:30..20:30 only (half-open)", b.status_code == 201 and got == wantm, got)
    r = avail("r_anker", THU, 100)
    check("V4.2g", "V4", "§8", "large party_size (100) -> 200 with empty lists", r.status_code == 200 and all(s["available_table_ids"] == [] for s in (J(r) or {}).get("slots", [{"available_table_ids": 1}])), show(r))


def s_create():
    reset()
    ta, tb = ada(), bob()
    r = book(ta, "r_anker", "t_2", f"{THU}T19:00", 4, extra={"note": "window", "status": "cancelled", "reference": "HACKED1"})
    j = J(r) or {}
    exp = {"restaurant_id": "r_anker", "table_id": "t_2", "party_size": 4, "status": "confirmed", "starts_at_local": f"{THU}T19:00"}
    check("B1.1", "B1", "§8", "create -> 201 with all fields (unknown body fields ignored, C6.1)",
          r.status_code == 201 and not shape_problems(j) and all(j.get(k) == v for k, v in exp.items()), f"{shape_problems(j)} {show(r)}")
    check("B1.2", "B1/C5", "§8/§3.4", "starts_at/ends_at correct instants and +02:00 offset",
          same_ts(j.get("starts_at"), f"{THU}T19:00:00+02:00") and same_ts(j.get("ends_at"), f"{THU}T20:30:00+02:00"), show(r))
    try:
        age = abs((datetime.now(timezone.utc) - datetime.fromisoformat(j["created_at"].replace("Z", "+00:00"))).total_seconds())
    except Exception:
        age = None
    check("B1.3", "B1", "§8", "created_at is the creation time (within 120 s of now)", age is not None and age < 120, j.get("created_at"))
    first = j.get("reference")
    expect("B3.1a", "B3", "§8", "same table, same slot (same user, new key)", book(ta, "r_anker", "t_2", f"{THU}T19:00", 2), 409, "table_unavailable")
    expect("B3.1b", "B3", "§8", "same table, same slot (other user)", book(tb, "r_anker", "t_2", f"{THU}T19:00", 2), 409, "table_unavailable")
    expect("B3.1c", "B3", "§8", "overlapping earlier slot 18:00", book(tb, "r_anker", "t_2", f"{THU}T18:00", 2), 409, "table_unavailable")
    expect("B3.1d", "B3", "§8", "overlapping later slot 20:00", book(tb, "r_anker", "t_2", f"{THU}T20:00", 2), 409, "table_unavailable")
    expect("B3.1e", "B3", "§1", "adjacent slot 20:30 after 19:00+90min", book(tb, "r_anker", "t_2", f"{THU}T20:30", 2), 201)
    expect("B3.1f", "B3", "§8", "cancel the 19:00 booking", cancel(ta, first), 200)
    expect("B3.1g", "B3", "§8", "cancelled booking does not block: 19:00 bookable again", book(tb, "r_anker", "t_2", f"{THU}T19:00", 2), 201)
    expect("B4.1a", "B4", "§8", "19:10 off grid", book(ta, "r_anker", "t_1", f"{THU}T19:10", 2), 422, "not_on_slot_grid")
    expect("B4.1b", "B4", "§8", "19:15 off grid", book(ta, "r_anker", "t_1", f"{THU}T19:15", 2), 422, "not_on_slot_grid")
    expect("B4.1c", "B4", "§4", "r_odd 18:30 (grid runs from opens 18:15 in 20-min steps)", book(ta, "r_odd", "t_z", f"{THU}T18:30", 2), 422, "not_on_slot_grid")
    expect("B4.1d", "B4", "§4", "r_odd 18:35 on grid", book(ta, "r_odd", "t_z", f"{THU}T18:35", 2), 201)
    expect("B5.1a", "B5", "§8", "Thu 22:00 would end 23:30 > closes 23:00", book(ta, "r_anker", "t_1", f"{THU}T22:00", 2), 422, "outside_opening_hours")
    expect("B5.1b", "B5/B6", "§8", "Thu 21:30 ends exactly at closes; party = capacity 2", book(ta, "r_anker", "t_1", f"{THU}T21:30", 2), 201)
    expect("B5.1c", "B5", "§8", "Fri 22:00 ends exactly at closes 23:30", book(ta, "r_anker", "t_1", f"{FRI}T22:00", 2), 201)
    expect("B5.1d", "B5", "§8", "Fri 22:30 ends after closes", book(ta, "r_anker", "t_2", f"{FRI}T22:30", 2), 422, "outside_opening_hours")
    expect("B5.1e", "B5", "§8/§4", "closed day (Wed) 19:00", book(ta, "r_anker", "t_1", f"{WED}T19:00", 2), 422, "outside_opening_hours")
    expect("B5.1f", "B5", "§8", "Thu 23:00 (at closes)", book(ta, "r_anker", "t_1", f"{THU}T23:00", 2), 422, "outside_opening_hours")
    expect("B5.1g", "B5", "§8", "r_odd 19:35 on grid but ends 20:20 > closes", book(ta, "r_odd", "t_z", f"{THU}T19:35", 2), 422, "outside_opening_hours")
    r = book(ta, "r_anker", "t_1", f"{THU}T17:30", 2)
    check("B5.1h", "B5", "§8", "Thu 17:30 before opening -> 422 (outside_opening_hours or not_on_slot_grid)", r.status_code == 422 and code(r) in ("outside_opening_hours", "not_on_slot_grid"), show(r))
    expect("B6.1", "B6", "§8", "party 3 on table of capacity 2", book(ta, "r_anker", "t_1", f"{THU}T18:00", 3), 422, "party_exceeds_capacity")
    for i, (v, nm) in enumerate([(0, "0"), (-1, "-1"), ("4", "string '4'"), (True, "true"), (2.5, "2.5"), (None, "null")]):
        expect(f"E4.1{'abcdef'[i]}", "E4", "§5/§8", f"party_size {nm}", book(ta, "r_anker", "t_1", f"{THU}T18:00", v), 422, "validation_failed")
    base = {"restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": f"{THU}T18:00", "party_size": 2}
    for i, k in enumerate(["party_size", "restaurant_id", "table_id", "starts_at_local"]):
        b = {x: y for x, y in base.items() if x != k}
        expect(f"E4.2{'abcd'[i]}", "E4", "§5", f"POST /reservations missing {k}", req("POST", "/reservations", token=ta, key=K(), body=b), 422, "validation_failed")
    for i, s in enumerate([f"{THU}T18:00:00", f"{THU}T18:00+02:00", f"{THU}T18:00Z", f"{THU} 18:00", "garbage", "2027-02-30T18:00", f"{THU}T25:00", ""]):
        expect(f"E5.1{'abcdefgh'[i]}", "E5", "§5/§8", f"starts_at_local {s!r}", book(ta, "r_anker", "t_1", s, 2), 422, "validation_failed")
    expect("E2.3d", "E2", "§5", "starts_at_local of wrong JSON type (number)", book(ta, "r_anker", "t_1", 1800, 2), 400, "malformed_request")
    expect("E2.3e", "E2", "§5", "restaurant_id of wrong JSON type (number)", book(ta, 7, "t_1", f"{THU}T18:00", 2), 400, "malformed_request")
    expect("E2.3f", "E2", "§5", "table_id of wrong JSON type (array)", book(ta, "r_anker", ["t_1"], f"{THU}T18:00", 2), 400, "malformed_request")
    expect("E2.1c", "E2", "§5", "POST /reservations unparseable body", req("POST", "/reservations", token=ta, key=K(), raw='{"restaurant_id": "r_anker",'), 400, "malformed_request")
    expect("E2.2b", "E2", "§5/§7", "POST /reservations body is a JSON array", req("POST", "/reservations", token=ta, key=K(), body=[base]), 400, "malformed_request")
    expect("E2.2c", "E2", "§5/§7", "POST /reservations body is a JSON string", req("POST", "/reservations", token=ta, key=K(), body="hello"), 400, "malformed_request")
    expect("B8.1a", "B8", "§8", "unknown restaurant", book(ta, "r_nope", "t_1", f"{THU}T18:00", 2), 404, "not_found")
    expect("B8.1b", "B8", "§8", "unknown table", book(ta, "r_anker", "t_nope", f"{THU}T18:00", 2), 404, "not_found")
    expect("B8.1c", "B8", "§8", "table belongs to another restaurant", book(ta, "r_anker", "n_1", f"{THU}T18:00", 2), 404, "not_found")
    expect("E7.2a", "E7/I2", "§7", "POST /reservations without Idempotency-Key", req("POST", "/reservations", token=ta, body=base), 400, "missing_idempotency_key")
    expect("E7.2b", "E7/I2", "§7", "POST /reservations with empty Idempotency-Key", req("POST", "/reservations", token=ta, body=base, headers={"Idempotency-Key": ""}), 400, "missing_idempotency_key")
    expect("E7.2c", "E7/I5", "§7", "no key + body failing field validation (idempotency resolved first)", req("POST", "/reservations", token=ta, body=dict(base, party_size=0)), 400, "missing_idempotency_key")
    expect("E7.1a", "E7", "§5", "Idempotency-Key of 256 characters", book(ta, "r_anker", "t_1", f"{THU}T18:00", 2, key="k" * 256), 422, "validation_failed")
    expect("E7.1b", "E7", "§5", "Idempotency-Key of 255 characters", book(ta, "r_anker", "t_1", f"{THU}T18:00", 2, key="k" * 255), 201)
    expect("E7.1c", "E7", "§5", "Idempotency-Key of 1 character", book(ta, "r_anker", "t_1", f"{FRI}T18:00", 2, key="k"), 201)
    r = book(ta, "r_anker", "t_2", f"{PAST_THU}T19:00", 2)
    j = J(r) or {}
    check("M4.1", "M4", "§4", "booking with a start in the past (2020) -> 201", r.status_code == 201 and same_ts(j.get("starts_at"), f"{PAST_THU}T19:00:00+02:00"), show(r))
    expect("M4.2a", "M4/X3", "§4/§8", "cancel a past booking", cancel(ta, j.get("reference")), 409, "cutoff_passed")
    expect("M4.2b", "M4/P2", "§4/§8", "PATCH a past booking", patch(ta, j.get("reference"), {"party_size": 1}), 409, "cutoff_passed")
    g = J(get(ta, j.get("reference"))) or {}
    check("M4.2c", "M4", "§8", "past booking unchanged after refused cancel/PATCH", g.get("status") == "confirmed" and g.get("party_size") == 2, g)
    day = "2027-10-06"
    rs = [book(ta, "r_all", "a_1", f"{day}T{h:02d}:{m:02d}", 1) for h in range(8, 16) for m in (0, 15, 30, 45)]
    refs = [ref(x) for x in rs]
    check("B2.1a", "B2", "§8", "32 further bookings all 201", all(x.status_code == 201 for x in rs), [show(x) for x in rs if x.status_code != 201][:2])
    allrefs = list(CREATED.get(ta, set()) | CREATED.get(tb, set()))
    check("B2.1b", "B2", "§8", "all references match [A-Z0-9]{6,12} and are unique", all(isinstance(x, str) and REF_RE.match(x) for x in allrefs) and len(set(refs)) == len(refs), allrefs[:5])
    ids = [(J(x) or {}).get("reservation_id") for x in rs]
    check("B2.1c", "C7", "§3.4", "reservation_id values unique", len(set(ids)) == len(ids), ids[:5])
    la = listing(ta) or []
    check("B0.1", "B1", "§1", "rejected requests created nothing: caller's list holds exactly the 201 responses",
          {x.get("reference") for x in la} == CREATED.get(ta, set()) and len(la) == len(CREATED.get(ta, set())), f"list={len(la)} created={len(CREATED.get(ta, set()))}")


def s_idempotency():
    reset()
    ta, tb = ada(), bob()
    k = K()
    body = {"restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": f"{THU}T19:00", "party_size": 2}
    r1 = req("POST", "/reservations", token=ta, key=k, body=body)
    r2 = req("POST", "/reservations", token=ta, key=k, body=body)
    check("I6.1", "I6", "§7", "first use 201, replay 200 with identical JSON", r1.status_code == 201 and r2.status_code == 200 and J(r1) == J(r2) and J(r1) is not None, show(r1) + " | " + show(r2))
    raw = '{\n  "party_size" : 2,\n\t"starts_at_local":"%sT19:00" ,  "table_id":"t_1",\n\n "restaurant_id" :  "r_anker" }' % THU
    r3 = req("POST", "/reservations", token=ta, key=k, raw=raw)
    check("I4.1", "I4", "§7", "replay with reordered keys and different whitespace -> 200 identical", r3.status_code == 200 and J(r3) == J(r1), show(r3))
    check("I6.1b", "I6", "§7", "replays created no second reservation", len(listing(ta) or []) == 1, listing(ta))
    expect("I6.2a", "I6", "§7", "same key, different body (party_size)", req("POST", "/reservations", token=ta, key=k, body=dict(body, party_size=1)), 409, "idempotency_key_reuse")
    expect("I6.2b", "I6", "§7", "same key, body with an extra unknown field (different JSON value)", req("POST", "/reservations", token=ta, key=k, body=dict(body, extra=1)), 409, "idempotency_key_reuse")
    expect("I5.1a", "I5", "§7", "used key + different body with invalid party_size", req("POST", "/reservations", token=ta, key=k, body=dict(body, party_size="x")), 409, "idempotency_key_reuse")
    expect("I5.1b", "I5", "§7", "used key + different body with unknown restaurant", req("POST", "/reservations", token=ta, key=k, body=dict(body, restaurant_id="r_nope")), 409, "idempotency_key_reuse")
    expect("I5.1c", "I5", "§7", "used key + different body missing fields", req("POST", "/reservations", token=ta, key=k, body={}), 409, "idempotency_key_reuse")
    rb = req("POST", "/reservations", token=tb, key=k, body=dict(body, table_id="t_2"))
    check("I3.1", "I3", "§7", "other user, same key string, different body -> independent 201", rb.status_code == 201 and (J(rb) or {}).get("reference") != (J(r1) or {}).get("reference"), show(rb))
    rb2 = req("POST", "/reservations", token=tb, key=k, body=dict(body, table_id="t_2"))
    check("I3.1b", "I3", "§7", "other user's replay returns their own response", rb2.status_code == 200 and J(rb2) == J(rb), show(rb2))
    # I4.2: same key, same body, other path
    k2 = K()
    dual = {"restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": f"{FRI}T18:00", "party_size": 2,
            "moves": [{"reference": ref(r1), "party_size": 1}]}
    d1 = req("POST", "/reservations", token=ta, key=k2, body=dual)
    d2 = req("POST", "/reservation-moves", token=ta, key=k2, body=dual)
    jj = J(d2) or {}
    check("I4.2", "I4", "§7", "same key + same body on the other write path succeeds normally (201, not a replay)",
          d1.status_code == 201 and d2.status_code == 201 and isinstance(jj.get("reservations"), list) and jj["reservations"][0].get("party_size") == 1, show(d1) + " | " + show(d2))
    d3 = req("POST", "/reservations", token=ta, key=k2, body=dual)
    d4 = req("POST", "/reservation-moves", token=ta, key=k2, body=dual)
    check("I4.3", "I4", "§7", "each path then replays its own response", d3.status_code == 200 and J(d3) == J(d1) and d4.status_code == 200 and J(d4) == J(d2), show(d3) + " | " + show(d4))
    # I7
    k3 = K()
    f1 = book(ta, "r_anker", "t_1", f"{THU}T21:00", 3, key=k3)
    f2 = book(ta, "r_anker", "t_1", f"{THU}T21:00", 2, key=k3)
    check("I7.1a", "I7", "§7", "key reused after 422 with a valid different body -> 201", f1.status_code == 422 and f2.status_code == 201, show(f1) + " | " + show(f2))
    k4 = K()
    g1 = book(ta, "r_anker", "t_2", f"{THU}T19:00", 2, key=k4)       # bob holds t_2 19:00
    c = cancel(tb, ref(rb))
    g2 = book(ta, "r_anker", "t_2", f"{THU}T19:00", 2, key=k4)
    check("I7.1b", "I7", "§7", "key that failed 409 table_unavailable, same body after the table was freed -> 201", g1.status_code == 409 and c.status_code == 200 and g2.status_code == 201, show(g1) + " | " + show(c) + " | " + show(g2))
    k5 = K()
    h1 = book(ta, "r_nope", "t_2", f"{FRI}T20:00", 2, key=k5)
    h2 = book(ta, "r_anker", "t_2", f"{FRI}T20:00", 2, key=k5)
    check("I7.1c", "I7", "§7", "key reused after 404 -> 201", h1.status_code == 404 and h2.status_code == 201, show(h1) + " | " + show(h2))
    # I8
    tn, _, _ = signup()
    k6 = K()
    b6 = {"restaurant_id": "r_ny", "table_id": "n_1", "starts_at_local": f"{THU}T12:00", "party_size": 2}
    rs = parallel([lambda: req("POST", "/reservations", token=tn, key=k6, body=b6) for _ in range(20)])
    sts = sorted(x.status_code for x in rs)
    bodies = {json.dumps(J(x), sort_keys=True) for x in rs}
    check("I8.1", "I8", "§7", "20 concurrent identical requests: exactly one 201, nineteen 200, identical body", sts == [200] * 19 + [201] and len(bodies) == 1, f"{sts} bodies={len(bodies)}")
    check("I8.1b", "I8", "§7", "operation took effect once", len(listing(tn) or []) == 1, listing(tn))
    # I9
    k7 = K()
    o = book(ta, "r_ny", "n_1", f"{FRI}T12:00", 2, key=k7)
    c = cancel(ta, ref(o))
    rp = book(ta, "r_ny", "n_1", f"{FRI}T12:00", 2, key=k7)
    g = J(get(ta, ref(o))) or {}
    check("I9.1a", "I9", "§7", "replay after cancel -> 200 with original (confirmed) body; reservation stays cancelled",
          o.status_code == 201 and c.status_code == 200 and rp.status_code == 200 and J(rp) == J(o) and g.get("status") == "cancelled", show(rp) + f" | now={g.get('status')}")
    check("I9.1b", "I9", "§7", "replay after cancel did not re-occupy the table", tables_at("r_ny", FRI, "12:00", 2) == ["n_1"], tables_at("r_ny", FRI, "12:00", 2))
    k8 = K()
    o = book(ta, "r_ny", "n_1", f"{FRI}T15:00", 2, key=k8)
    p = patch(ta, ref(o), {"party_size": 3})
    rp = book(ta, "r_ny", "n_1", f"{FRI}T15:00", 2, key=k8)
    g = J(get(ta, ref(o))) or {}
    check("I9.1c", "I9/I1", "§7", "replay after PATCH (no key needed) -> 200 original body; amended value kept",
          p.status_code == 200 and rp.status_code == 200 and J(rp) == J(o) and g.get("party_size") == 3, show(p) + " | " + show(rp))


def s_list_get_cancel():
    reset()
    ta, tb = ada(), bob()
    tn, _, _ = signup()
    r = req("GET", "/reservations?foo=1", token=tn)
    check("L1.1a", "L1", "§8", "empty list is exactly {reservations: []} (unknown query param ignored)", r.status_code == 200 and J(r) == {"reservations": []}, show(r))
    a = book(ta, "r_anker", "t_1", f"{THU}T19:00", 2)      # 17:00Z
    n = book(ta, "r_ny", "n_1", f"{THU}T14:00", 2)         # 18:00Z
    f = book(ta, "r_anker", "t_1", f"{FRI}T18:00", 2)
    p = book(ta, "r_anker", "t_1", f"{PAST_THU}T19:00", 2)
    b = book(tb, "r_anker", "t_2", f"{THU}T19:00", 2)
    check("L1.0", "L1", "§8", "setup bookings created", all(x.status_code == 201 for x in (a, n, f, p, b)), [show(x) for x in (a, n, f, p, b) if x.status_code != 201])
    la = listing(ta) or []
    check("L1.1b", "L1", "§8", "list ordered by starts_at descending as instants (NY 14:00 after Berlin 19:00 same day)",
          [x.get("reference") for x in la] == [ref(f), ref(n), ref(a), ref(p)], [(x.get("reference"), x.get("starts_at")) for x in la])
    check("L1.1c", "L1", "§8", "list entries equal the create responses (same shape)", la == [J(f), J(n), J(a), J(p)], la[:1])
    check("L1.1d", "L1", "§8", "list has only the caller's reservations", [x.get("reference") for x in (listing(tb) or [])] == [ref(b)], listing(tb))
    g = get(ta, ref(a))
    check("G1.1a", "G1", "§8", "GET own reservation -> 200 equal to create body", g.status_code == 200 and J(g) == J(a), show(g))
    expect("G1.1b", "G1", "§8", "GET another user's reservation", get(tb, ref(a)), 404, "not_found")
    expect("G1.1c", "G1", "§8", "GET unknown reference", get(ta, "ZZZZZZ99"), 404, "not_found")
    expect("X4.1a", "X4", "§8", "cancel another user's reservation", cancel(tb, ref(a)), 404, "not_found")
    expect("X4.1b", "X4", "§8", "cancel unknown reference", cancel(ta, "ZZZZZZ99"), 404, "not_found")
    expect("P4.1a", "P4", "§8", "PATCH another user's reservation", patch(tb, ref(a), {"party_size": 1}), 404, "not_found")
    expect("P4.1b", "P4", "§8", "PATCH unknown reference", patch(ta, "ZZZZZZ99", {"party_size": 1}), 404, "not_found")
    check("X4.1c", "X4", "§8", "reservation untouched by other user's attempts", J(get(ta, ref(a))) == J(a), "")
    before = tables_at("r_anker", THU, "19:00", 2)
    c = cancel(ta, ref(a))
    jc = J(c) or {}
    want = dict(J(a) or {}, status="cancelled")
    check("X1.1a", "X1", "§8", "cancel -> 200, status cancelled, all other fields unchanged", c.status_code == 200 and jc == want, show(c))
    after = tables_at("r_anker", THU, "19:00", 2)
    check("X1.1b", "X1", "§8", "next availability offers the slot again", before == [] and after == ["t_1"], f"before={before} after={after}")
    c2 = cancel(ta, ref(a))
    check("X2.1", "X2", "§8", "cancel twice -> 200 with current (cancelled) state", c2.status_code == 200 and J(c2) == want, show(c2))
    expect("X1.1c", "X1", "§8", "freed table is bookable again", book(tb, "r_anker", "t_1", f"{THU}T19:00", 2), 201)
    la = listing(ta) or []
    check("L1.1e", "L1", "§8", "list includes cancelled reservations, order unchanged", [(x.get("reference"), x.get("status")) for x in la] ==
          [(ref(f), "confirmed"), (ref(n), "confirmed"), (ref(a), "cancelled"), (ref(p), "confirmed")], [(x.get("reference"), x.get("status")) for x in la])
    g = get(ta, ref(a))
    check("G1.1d", "G1", "§8", "GET cancelled reservation -> 200 status cancelled", g.status_code == 200 and J(g) == want, show(g))


def s_patch():
    reset()
    ta, tb = ada(), bob()
    a = book(ta, "r_anker", "t_2", f"{THU}T19:00", 2)
    r0 = J(a) or {}
    rf = r0.get("reference")
    ident = lambda j: (j.get("reference"), j.get("reservation_id"), j.get("created_at"), j.get("restaurant_id"), j.get("status"))
    p = patch(ta, rf, {"party_size": 3, "color": "red"})
    j = J(p) or {}
    check("P1.1a", "P1", "§8", "PATCH party_size only (unknown field ignored) -> 200, other fields unchanged", p.status_code == 200 and j == dict(r0, party_size=3), show(p))
    snap = lambda: (J(get(ta, rf)), J(avail("r_anker", THU, 2)), J(avail("r_anker", FRI, 2)))
    s0 = snap()
    fails = []

    def fail(cid, desc, r, status, ec):
        okk = expect(cid, "P2", "§8", desc, r, status, ec)
        if snap() != s0:
            fails.append(cid)
        return okk
    fail("P2.1a", "PATCH table to t_1 (capacity 2) with party 3", patch(ta, rf, {"table_id": "t_1"}), 422, "party_exceeds_capacity")
    fail("P2.1b", "PATCH party_size 5 on capacity 4", patch(ta, rf, {"party_size": 5}), 422, "party_exceeds_capacity")
    fail("P2.1c", "PATCH starts_at_local off grid", patch(ta, rf, {"starts_at_local": f"{THU}T18:10"}), 422, "not_on_slot_grid")
    fail("P2.1d", "PATCH starts_at_local ending after closes", patch(ta, rf, {"starts_at_local": f"{THU}T22:00"}), 422, "outside_opening_hours")
    fail("P2.1e", "PATCH starts_at_local on closed day", patch(ta, rf, {"starts_at_local": f"{WED}T19:00"}), 422, "outside_opening_hours")
    fail("P2.1f", "PATCH starts_at_local with seconds", patch(ta, rf, {"starts_at_local": f"{THU}T19:30:00"}), 422, "validation_failed")
    fail("P2.1g", "PATCH party_size string", patch(ta, rf, {"party_size": "3"}), 422, "validation_failed")
    fail("P2.1h", "PATCH party_size 0", patch(ta, rf, {"party_size": 0}), 422, "validation_failed")
    fail("P2.1i", "PATCH table_id wrong JSON type", patch(ta, rf, {"table_id": 5}), 400, "malformed_request")
    fail("P2.1j", "PATCH unknown table", patch(ta, rf, {"table_id": "t_nope"}), 404, "not_found")
    fail("P2.1k", "PATCH table of another restaurant", patch(ta, rf, {"table_id": "n_1"}), 404, "not_found")
    fail("P2.1l", "PATCH unparseable body", req("PATCH", f"/reservations/{rf}", token=ta, raw="{oops"), 400, "malformed_request")
    fail("P2.1m", "PATCH without token", req("PATCH", f"/reservations/{rf}", body={"party_size": 1}), 401, "unauthenticated")
    bb = book(tb, "r_anker", "t_1", f"{FRI}T18:00", 2)
    s0 = snap()
    fail("P2.1n", "PATCH into a slot/table held by another booking", patch(ta, rf, {"table_id": "t_1", "starts_at_local": f"{FRI}T18:00", "party_size": 2}), 409, "table_unavailable")
    fail("P2.1o", "PATCH into a slot overlapping another booking", patch(ta, rf, {"table_id": "t_1", "starts_at_local": f"{FRI}T19:00", "party_size": 2}), 409, "table_unavailable")
    check("P3.2", "P3", "§8", "every failed PATCH left the booking and availability unchanged", bb.status_code == 201 and not fails, fails)
    p = patch(ta, rf, {"party_size": 2})
    p = patch(ta, rf, {"table_id": "t_1"})
    j = J(p) or {}
    check("P1.1b", "P1", "§8", "PATCH table_id only -> 200", p.status_code == 200 and j == dict(r0, party_size=2, table_id="t_1"), show(p))
    p = patch(ta, rf, {"starts_at_local": f"{THU}T19:30"})
    j = J(p) or {}
    check("P3.1a", "P1/P3", "§8", "PATCH starts_at_local only into a slot overlapping its own old slot -> 200, ends_at recomputed",
          p.status_code == 200 and j.get("starts_at_local") == f"{THU}T19:30" and same_ts(j.get("starts_at"), f"{THU}T19:30:00+02:00")
          and same_ts(j.get("ends_at"), f"{THU}T21:00:00+02:00") and ident(j) == ident(r0) and j.get("table_id") == "t_1", show(p))
    s = slots("r_anker", THU, 2)
    got = {k[-5:]: v["available_table_ids"] for k, v in s.items()}
    check("P3.1b", "P3", "§8", "old slot released and new one occupied together (t_1 free at 18:00, taken 18:30..20:30)",
          got.get("18:00") == ["t_1", "t_2"] and all(got.get(h) == ["t_2"] for h in ("18:30", "19:00", "19:30", "20:00", "20:30")) and got.get("21:00") == ["t_1", "t_2"], got)
    p = patch(ta, rf, {"table_id": "t_2", "starts_at_local": f"{FRI}T20:00", "party_size": 4})
    j = J(p) or {}
    check("P1.1c", "P1/P4", "§8", "PATCH all three fields -> 200; reference, reservation_id, created_at unchanged",
          p.status_code == 200 and ident(j) == ident(r0) and j.get("table_id") == "t_2" and j.get("party_size") == 4 and j.get("starts_at_local") == f"{FRI}T20:00"
          and same_ts(j.get("ends_at"), f"{FRI}T21:30:00+02:00"), show(p))
    check("P1.1d", "P1", "§8", "GET and list reflect the amendment", J(get(ta, rf)) == j and (listing(ta) or [None])[0] == j, "")
    check("P3.1c", "P3", "§8", "Thursday slot fully released after move to Friday", tables_at("r_anker", THU, "19:30", 2) == ["t_1", "t_2"], tables_at("r_anker", THU, "19:30", 2))
    r = patch(ta, rf, {})
    note("P1.n1", "PATCH with empty object", show(r))
    # P2.2
    c = book(ta, "r_anker", "t_1", f"{THU2}T19:00", 2)
    cancel(ta, ref(c))
    expect("P2.2a", "P2", "§8", "PATCH a cancelled reservation", patch(ta, ref(c), {"party_size": 1}), 409, "reservation_cancelled")
    m = book(ta, "r_anker", "t_2", f"{THU2}T19:00", 2)
    p = patch(ta, ref(m), {"starts_at_local": f"{PAST_THU}T19:00"})
    check("P2.2b", "P2/M4", "§8/§4", "booking beyond cutoff may be moved to a past time (cutoff measured against current start) -> 200",
          p.status_code == 200 and (J(p) or {}).get("starts_at_local") == f"{PAST_THU}T19:00", show(p))
    expect("P2.2c", "P2", "§8", "the booking now starts in the past: further PATCH", patch(ta, ref(m), {"party_size": 1}), 409, "cutoff_passed")
    expect("P2.2d", "X3", "§8", "the booking now starts in the past: cancel", cancel(ta, ref(m)), 409, "cutoff_passed")


def s_cutoff_dynamic():
    reset()
    ta = ada()
    near = slot_after(60)
    far = slot_after(11 * 60)
    b = book(ta, "r_all", "a_1", near, 2)
    check("X3.0", "X3", "§8", f"setup: booking ~1 h ahead ({near}) in restaurant with 600 min cutoff", b.status_code == 201, show(b))
    expect("X3.1a", "X3", "§8", "cancel within cutoff (start ~1 h ahead, cutoff 600 min)", cancel(ta, ref(b)), 409, "cutoff_passed")
    expect("X3.1b", "P2", "§8", "PATCH within cutoff", patch(ta, ref(b), {"party_size": 1}), 409, "cutoff_passed")
    check("X3.1c", "X3", "§8", "booking unchanged after refused cancel", (J(get(ta, ref(b))) or {}) == J(b), "")
    b2 = book(ta, "r_all30", "b_1", near, 2)
    p = patch(ta, ref(b2), {"party_size": 3})
    check("X3.1d", "P2", "§8", "PATCH beyond cutoff (start ~1 h ahead, cutoff 30 min) -> 200", b2.status_code == 201 and p.status_code == 200, show(b2) + " | " + show(p))
    expect("X3.1e", "X3", "§8", "cancel beyond cutoff (start ~1 h ahead, cutoff 30 min)", cancel(ta, ref(b2)), 200)
    b3 = book(ta, "r_all", "a_2", far, 2)
    c = cancel(ta, ref(b3))
    check("X3.1f", "X3", "§8", f"cancel beyond cutoff (start ~11 h ahead {far}, cutoff 600 min) -> 200", b3.status_code == 201 and c.status_code == 200, show(b3) + " | " + show(c))


def s_dst():
    reset()
    ta = ada()
    H = ["00:00", "00:30", "01:00", "01:30", "02:00", "02:30", "03:00", "03:30", "04:00", "04:30"]

    def day(cid, row, desc, rid, d, hhmm, off_of):
        s = slots(rid, d, 2)
        want = [f"{d}T{h}" for h in hhmm]
        okk = list(s) == want and all(same_ts(v.get("starts_at"), f"{k}:00{off_of(k[-5:])}") for k, v in s.items())
        check(cid, row, "§9", desc, okk, [(k, v.get("starts_at")) for k, v in s.items()])
    spring = [h for h in H if h not in ("02:00", "02:30")]
    day("T1.1a", "T1", "Berlin 2026-03-29: 02:00/02:30 absent; +01:00 before, +02:00 from 03:00", "r_night_b", "2026-03-29", spring, lambda h: "+01:00" if h < "02:00" else "+02:00")
    day("T1.1b", "T1", "New York 2026-03-08: 02:00/02:30 absent; -05:00 before, -04:00 from 03:00", "r_night_ny", "2026-03-08", spring, lambda h: "-05:00" if h < "02:00" else "-04:00")
    day("T2.1a", "T2", "Berlin 2026-10-25: every slot once; 02:00/02:30 first occurrence +02:00; 03:00 +01:00", "r_night_b", "2026-10-25", H, lambda h: "+02:00" if h < "03:00" else "+01:00")
    day("T2.1b", "T2", "New York 2026-11-01: every slot once; 01:00/01:30 first occurrence -04:00; 02:00 -05:00", "r_night_ny", "2026-11-01", H, lambda h: "-04:00" if h < "02:00" else "-05:00")
    for i, (rid, tid, d) in enumerate([("r_night_b", "nb_1", "2026-03-29"), ("r_night_ny", "nn_1", "2026-03-08")]):
        expect(f"T1.2{'ab'[i]}", "T1/B7", "§9", f"{rid} {d} 02:00 does not exist", book(ta, rid, tid, f"{d}T02:00", 2), 422, "invalid_local_time")
        expect(f"T1.2{'cd'[i]}", "T1/B7", "§9", f"{rid} {d} 02:30 does not exist", book(ta, rid, tid, f"{d}T02:30", 2), 422, "invalid_local_time")

    def booked(cid, row, desc, rid, tid, when, st, en):
        r = book(ta, rid, tid, when, 2)
        j = J(r) or {}
        check(cid, row, "§9", desc, r.status_code == 201 and same_ts(j.get("starts_at"), st) and same_ts(j.get("ends_at"), en) and j.get("starts_at_local") == when,
              show(r))
        return r
    booked("T3.1a", "T3", "NY fall-back 01:30 -> starts 01:30-04:00, ends 02:00-05:00", "r_night_ny", "nn_1", "2026-11-01T01:30", "2026-11-01T01:30:00-04:00", "2026-11-01T02:00:00-05:00")
    booked("T3.1b", "T3", "Berlin fall-back 01:30 -> ends 02:00+01:00", "r_night_b", "nb_1", "2026-10-25T01:30", "2026-10-25T01:30:00+02:00", "2026-10-25T02:00:00+01:00")
    booked("T3.1c", "T3", "Berlin spring 01:30 -> ends 04:00+02:00", "r_night_b", "nb_1", "2026-03-29T01:30", "2026-03-29T01:30:00+01:00", "2026-03-29T04:00:00+02:00")
    booked("T3.1d", "T3", "NY spring 01:00 -> ends 03:30-04:00", "r_night_ny", "nn_1", "2026-03-08T01:00", "2026-03-08T01:00:00-05:00", "2026-03-08T03:30:00-04:00")
    # T5 spring: nb_1 holds 00:30Z..02:00Z (01:30 CET .. 04:00 CEST)
    s = slots("r_night_b", "2026-03-29", 2)
    got = {k[-5:]: v["available_table_ids"] for k, v in s.items()}
    want = {"00:00": ["nb_1", "nb_2"], "00:30": ["nb_2"], "01:00": ["nb_2"], "01:30": ["nb_2"], "03:00": ["nb_2"], "03:30": ["nb_2"], "04:00": ["nb_1", "nb_2"], "04:30": ["nb_1", "nb_2"]}
    check("T5.1a", "T5", "§9/§8", "spring: availability overlap computed on instants (01:30 booking blocks 03:00 and 03:30, not 04:00)", got == want, got)
    expect("T5.1b", "T5", "§9", "spring: 03:00 overlaps the 01:30 booking", book(ta, "r_night_b", "nb_1", "2026-03-29T03:00", 2), 409, "table_unavailable")
    expect("T5.1c", "T5", "§9", "spring: 03:30 overlaps the 01:30 booking", book(ta, "r_night_b", "nb_1", "2026-03-29T03:30", 2), 409, "table_unavailable")
    expect("T5.1d", "T5", "§9", "spring: 04:00 is free", book(ta, "r_night_b", "nb_1", "2026-03-29T04:00", 2), 201)
    # T5 fall: nb_2 02:30 first occurrence = 00:30Z..02:00Z, ends 03:00 CET
    booked("T2.2", "T2/T3", "Berlin fall-back 02:30 resolves to first occurrence (+02:00), ends 03:00+01:00", "r_night_b", "nb_2", "2026-10-25T02:30", "2026-10-25T02:30:00+02:00", "2026-10-25T03:00:00+01:00")
    s = slots("r_night_b", "2026-10-25", 2)
    got = {k[-5:]: ("nb_2" in v["available_table_ids"]) for k, v in s.items()}
    want = {"00:00": True, "00:30": True, "01:00": True, "01:30": False, "02:00": False, "02:30": False, "03:00": True, "03:30": True, "04:00": True, "04:30": True}
    check("T5.1e", "T5", "§9/§8", "fall: 02:30(first) booking frees nb_2 from 03:00 CET; 01:00 CEST (ends 02:30 CEST) free, 01:30 blocked", got == want, got)
    expect("T5.1f", "T5", "§9", "fall: 03:00 (+01:00) does not overlap the 02:30 (+02:00) booking", book(ta, "r_night_b", "nb_2", "2026-10-25T03:00", 2), 201)
    expect("T5.1g", "T5", "§9", "fall: 02:00 (first occurrence) overlaps the 02:30 booking", book(ta, "r_night_b", "nb_2", "2026-10-25T02:00", 2), 409, "table_unavailable")
    for cid, rid, d, off in [("T4.1a", "r_ny", "2026-01-15", "-05:00"), ("T4.1b", "r_ny", "2026-07-16", "-04:00"),
                             ("T4.1c", "r_anker", "2026-01-15", "+01:00"), ("T4.1d", "r_anker", "2026-07-16", "+02:00")]:
        s = slots(rid, d, 2)
        check(cid, "T4", "§9", f"{rid} {d} offset {off}", s and all(same_ts(v.get("starts_at"), f"{k}:00{off}") for k, v in s.items()), list(s.values())[:1])
    b = book(ta, "r_night_b", "nb_2", "2027-03-28T01:00", 2)
    expect("T1.3", "T1/P2", "§9/§8", "PATCH into the skipped hour (Berlin 2027-03-28 02:30)", patch(ta, ref(b), {"starts_at_local": "2027-03-28T02:30"}), 422, "invalid_local_time")
    check("T1.3b", "P3", "§8", "booking unchanged after refused PATCH", J(get(ta, ref(b))) == J(b) and b.status_code == 201, show(b))


def s_moves():
    reset()
    ta, tb = ada(), bob()
    A = book(ta, "r_anker", "t_1", f"{THU}T19:00", 2)
    B = book(ta, "r_anker", "t_2", f"{THU}T19:00", 2)
    a, b = ref(A), ref(B)
    ident = lambda j: (j.get("reference"), j.get("reservation_id"), j.get("created_at"), j.get("restaurant_id"), j.get("status"))
    cur = lambda *refs: [J(get(ta, x)) for x in refs]
    swap = [{"reference": a, "table_id": "t_2"}, {"reference": b, "table_id": "t_1"}]
    expect("MV1.1a", "MV1", "§11", "moves without token", req("POST", "/reservation-moves", key=K(), body={"moves": swap}), 401, "unauthenticated")
    expect("MV1.1b", "MV1", "§7", "moves without Idempotency-Key", req("POST", "/reservation-moves", token=ta, body={"moves": swap}), 400, "missing_idempotency_key")
    expect("MV1.1c", "MV1/E7", "§5", "moves with 256-char Idempotency-Key", moves(ta, swap, key="m" * 256), 422, "validation_failed")
    expect("MV1.1d", "E2", "§5", "moves unparseable body", req("POST", "/reservation-moves", token=ta, key=K(), raw='{"moves": ['), 400, "malformed_request")
    expect("MV2.1a", "MV2", "§11", "moves missing", req("POST", "/reservation-moves", token=ta, key=K(), body={}), 422, "validation_failed")
    expect("MV2.1b", "MV2", "§11", "moves empty (0 items)", moves(ta, []), 422, "validation_failed")
    expect("MV2.1c", "MV2", "§11", "duplicate references", moves(ta, [{"reference": a, "party_size": 1}, {"reference": a, "party_size": 2}]), 422, "validation_failed")
    expect("MV2.1d", "MV2", "§11", "item without reference", moves(ta, [{"table_id": "t_2"}]), 422, "validation_failed")
    for cid, desc, body in [("MV2.n1", "moves is a string", {"moves": "x"}), ("MV2.n2", "moves item is a number", {"moves": [1]}), ("MV2.n3", "reference is a number", {"moves": [{"reference": 5}]})]:
        r = req("POST", "/reservation-moves", token=ta, key=K(), body=body)
        check(cid, "MV2", "§11/§5", f"{desc} -> 422 validation_failed or 400 malformed_request", (r.status_code, code(r)) in ((422, "validation_failed"), (400, "malformed_request")), show(r))
    check("MV2.1e", "MV7", "§11", "rejected shapes changed nothing", cur(a, b) == [J(A), J(B)], "")
    expect("MV3.1a", "MV3", "§11", "unknown reference", moves(ta, [{"reference": a, "party_size": 1}, {"reference": "ZZZZZZ99"}]), 404, "not_found")
    X = book(tb, "r_anker", "t_1", f"{THU}T21:00", 2)
    expect("MV3.1b", "MV3", "§11", "another owner's reference", moves(ta, [{"reference": a, "party_size": 1}, {"reference": ref(X)}]), 404, "not_found")
    N = book(ta, "r_ny", "n_1", f"{THU}T12:00", 2)
    expect("MV3.1c", "MV3", "§11", "bookings from different restaurants", moves(ta, [{"reference": a}, {"reference": ref(N)}]), 422, "validation_failed")
    check("MV3.1d", "MV7", "§11", "nothing changed after 404/422 (first item's valid change not applied)", cur(a, b) == [J(A), J(B)] and J(get(tb, ref(X))) == J(X), cur(a, b))
    expect("MV6.0", "MV6", "§8", "single PATCH of A onto B's table is refused (table occupied)", patch(ta, a, {"table_id": "t_2"}), 409, "table_unavailable")
    ks = K()
    S = moves(ta, swap, key=ks)
    js = (J(S) or {}).get("reservations") or [{}, {}]
    check("MV6.1a", "MV6/MV7", "§11", "swap tables of two listed bookings -> 201 {reservations} in input order",
          S.status_code == 201 and len(js) == 2 and js[0] == dict(J(A), table_id="t_2") and js[1] == dict(J(B), table_id="t_1"), show(S))
    check("MV6.1b", "MV7", "§11", "swap is visible via GET", cur(a, b) == js, cur(a, b))
    S2 = moves(ta, swap, key=ks)
    check("MV1.1e", "MV1/MV8", "§7/§11", "replay -> 200 identical body", S2.status_code == 200 and J(S2) == J(S), show(S2))
    expect("MV1.1f", "MV1", "§7", "same key, different body", moves(ta, [{"reference": a}], key=ks), 409, "idempotency_key_reuse")
    M = moves(ta, [{"reference": a, "starts_at_local": f"{THU}T21:00", "party_size": 3, "junk": {"x": 1}}])
    jm = ((J(M) or {}).get("reservations") or [{}])[0]
    check("MV4.1", "MV4", "§11", "item starts_at_local + party_size applied, table retained, unknown item field ignored, identity kept",
          M.status_code == 201 and jm.get("starts_at_local") == f"{THU}T21:00" and jm.get("party_size") == 3 and jm.get("table_id") == "t_2"
          and same_ts(jm.get("ends_at"), f"{THU}T22:30:00+02:00") and ident(jm) == ident(J(A)), show(M))
    S3 = moves(ta, swap, key=ks)
    check("MV8.1a", "MV8", "§11", "replay of the swap after a later amendment -> 200 original body, no state change", S3.status_code == 200 and J(S3) == J(S) and J(get(ta, a)) == jm, show(S3))
    Z = moves(ta, [{"reference": b}])
    check("MV8.1b", "MV8", "§11", "no-op move -> 201, all existing values retained", Z.status_code == 201 and (J(Z) or {}).get("reservations") == [js[1]] and J(get(ta, b)) == js[1], show(Z))
    # occupancy conflicts (Friday)
    C = book(tb, "r_anker", "t_2", f"{FRI}T18:00", 2)
    D = book(ta, "r_anker", "t_1", f"{FRI}T18:00", 2)
    F1 = book(ta, "r_anker", "t_1", f"{FRI}T20:00", 2)
    F2 = book(ta, "r_anker", "t_2", f"{FRI}T20:00", 2)
    d, f1, f2 = ref(D), ref(F1), ref(F2)
    before = cur(a, b, d, f1, f2)
    av0 = (J(avail("r_anker", THU, 2)), J(avail("r_anker", FRI, 2)))
    kf = K()
    r = moves(ta, [{"reference": b, "party_size": 1}, {"reference": d, "table_id": "t_2"}], key=kf)
    expect("MV6.1c", "MV6", "§11", "result overlaps an unlisted booking", r, 409, "table_unavailable")
    check("MV7.1a", "MV7", "§11", "all-or-nothing: first item's party change not applied, availability unchanged", cur(a, b, d, f1, f2) == before and (J(avail("r_anker", THU, 2)), J(avail("r_anker", FRI, 2))) == av0, cur(b))
    expect("MV6.1d", "MV6", "§11", "unchanged listed booking retains its occupancy", moves(ta, [{"reference": f1, "table_id": "t_2"}, {"reference": f2}]), 409, "table_unavailable")
    expect("MV6.1e", "MV6", "§11", "two results on the same table and time", moves(ta, [{"reference": f1, "starts_at_local": f"{FRI}T21:30"}, {"reference": f2, "starts_at_local": f"{FRI}T21:30", "table_id": "t_1"}]), 409, "table_unavailable")
    check("MV7.1b", "MV7", "§11", "nothing changed after occupancy failures", cur(a, b, d, f1, f2) == before, "")
    r = moves(ta, [{"reference": b, "party_size": 1}], key=kf)
    check("MV7.1c", "MV7/I7", "§11/§7", "key of the failed move is reusable as a first use -> 201", r.status_code == 201 and ((J(r) or {}).get("reservations") or [{}])[0].get("party_size") == 1, show(r))
    r = moves(ta, [{"reference": f1, "starts_at_local": f"{FRI}T21:30"}, {"reference": f2, "starts_at_local": f"{FRI}T21:30"}])
    jr = (J(r) or {}).get("reservations") or [{}, {}]
    check("MV4.2", "MV4", "§11", "two bookings moved in time together -> 201, input order", r.status_code == 201 and [x.get("reference") for x in jr] == [f1, f2]
          and all(x.get("starts_at_local") == f"{FRI}T21:30" for x in jr), show(r))
    # MV5
    G = book(ta, "r_anker", "t_1", f"{THU2}T19:00", 2)
    cancel(ta, ref(G))
    H = book(ta, "r_anker", "t_2", f"{THU2}T19:00", 2)
    I = book(ta, "r_anker", "t_1", f"{THU2}T19:00", 2)
    Jb = book(ta, "r_anker", "t_2", f"{THU2}T21:00", 2)
    P = book(ta, "r_anker", "t_1", f"{PAST_THU}T19:00", 2)
    h, i_, jb, p = ref(H), ref(I), ref(Jb), ref(P)
    check("MV5.0", "MV5", "§11", "setup bookings created", all(x.status_code == 201 for x in (G, H, I, Jb, P)), [show(x) for x in (G, H, I, Jb, P) if x.status_code != 201])
    before = cur(h, i_, jb, p, ref(G))
    expect("MV5.1a", "MV5", "§11", "cancelled booking listed", moves(ta, [{"reference": ref(G), "party_size": 1}]), 409, "reservation_cancelled")
    expect("MV5.1b", "MV5", "§11", "booking past its cutoff listed", moves(ta, [{"reference": p, "party_size": 1}]), 409, "cutoff_passed")
    expect("MV5.2a", "MV5", "§11", "cutoff precedes other errors of the same booking (off-grid change on past booking)", moves(ta, [{"reference": p, "starts_at_local": f"{PAST_THU}T19:10"}]), 409, "cutoff_passed")
    expect("MV5.2b", "MV5", "§11", "input order: [off-grid item, past-cutoff item]", moves(ta, [{"reference": h, "starts_at_local": f"{THU2}T19:10"}, {"reference": p}]), 422, "not_on_slot_grid")
    expect("MV5.2c", "MV5", "§11", "input order: [past-cutoff item, off-grid item]", moves(ta, [{"reference": p}, {"reference": h, "starts_at_local": f"{THU2}T19:10"}]), 409, "cutoff_passed")
    expect("MV5.2e", "MV5", "§11", "cutoff precedes an invalid party_size change of the same booking", moves(ta, [{"reference": p, "party_size": 0}]), 409, "cutoff_passed")
    expect("MV5.2f", "MV5", "§11", "input order: [past-cutoff item, item with invalid party_size]", moves(ta, [{"reference": p}, {"reference": h, "party_size": 0}]), 409, "cutoff_passed")
    expect("MV5.2d", "MV5", "§11", "non-occupancy error (2nd item off-grid) wins over occupancy conflict (1st item)", moves(ta, [{"reference": h, "table_id": "t_1"}, {"reference": jb, "starts_at_local": f"{THU2}T19:10"}]), 422, "not_on_slot_grid")
    expect("MV5.1c", "MV5", "§11", "item ending after closes", moves(ta, [{"reference": h, "starts_at_local": f"{THU2}T22:00"}]), 422, "outside_opening_hours")
    expect("MV5.1d", "MV5", "§11", "item party exceeds capacity", moves(ta, [{"reference": h, "party_size": 5}]), 422, "party_exceeds_capacity")
    expect("MV5.1e", "MV5", "§11", "item party_size 0", moves(ta, [{"reference": h, "party_size": 0}]), 422, "validation_failed")
    expect("MV5.1f", "MV5", "§11", "item starts_at_local with seconds", moves(ta, [{"reference": h, "starts_at_local": f"{THU2}T19:30:00"}]), 422, "validation_failed")
    expect("MV5.1g", "MV5", "§11", "item unknown table", moves(ta, [{"reference": h, "table_id": "t_nope"}]), 404, "not_found")
    expect("MV5.1h", "MV5", "§11", "item off grid", moves(ta, [{"reference": h, "starts_at_local": f"{THU2}T19:10"}]), 422, "not_on_slot_grid")
    check("MV7.1d", "MV7", "§11", "nothing changed after all refused moves", cur(h, i_, jb, p, ref(G)) == before, "")
    # 1..8 boundary
    day = "2027-10-07"
    nine = [ref(book(ta, "r_all", "a_1", f"{day}T10:{m:02d}", 1)) for m in (0, 15, 30, 45)] + [ref(book(ta, "r_all", "a_1", f"{day}T11:{m:02d}", 1)) for m in (0, 15, 30, 45)] + [ref(book(ta, "r_all", "a_1", f"{day}T12:00", 1))]
    expect("MV2.1f", "MV2", "§11", "9 moves", moves(ta, [{"reference": x} for x in nine]), 422, "validation_failed")
    r = moves(ta, [{"reference": x, "party_size": 2} for x in nine[:8]])
    jr = (J(r) or {}).get("reservations") or []
    check("MV2.1g", "MV2", "§11", "8 moves -> 201 in input order", r.status_code == 201 and [x.get("reference") for x in jr] == nine[:8] and all(x.get("party_size") == 2 for x in jr), show(r))
    kc = K()
    body = [{"reference": h, "party_size": 1}]
    rs = parallel([lambda: moves(ta, body, key=kc) for _ in range(20)])
    sts = sorted(x.status_code for x in rs)
    check("MV9.1", "MV1/I8", "§7", "20 concurrent identical moves: one 201, nineteen 200, identical body", sts == [200] * 19 + [201] and len({json.dumps(J(x), sort_keys=True) for x in rs}) == 1, sts)
    cancel(ta, h)
    r = moves(ta, body, key=kc)
    check("MV8.1c", "MV8", "§11", "replay after cancellation -> 200 original; booking stays cancelled", r.status_code == 200 and (J(get(ta, h)) or {}).get("status") == "cancelled", show(r))


def snapshot(toks, base=None):
    s = {}
    r = req("GET", "/restaurants", base=base)
    lst = (J(r) or {}).get("restaurants") or []
    s["restaurants"] = sorted(lst, key=lambda x: str(x.get("id")))
    for x in lst:
        s["r:" + str(x.get("id"))] = J(req("GET", f"/restaurants/{x.get('id')}", base=base))
    for name, tok in toks.items():
        r = req("GET", "/reservations", token=tok, base=base)
        s["l:" + name] = [r.status_code, J(r)]
    s["av1"] = J(avail("r_anker", THU, 2, base=base))
    s["av2"] = J(avail("r_anker", FRI, 2, base=base))
    return s


def s_export_import():
    seed = [{"id": "res_seed_1", "reference": "SEED01", "user_id": "u_bob", "restaurant_id": "r_anker", "table_id": "t_1",
             "starts_at_local": f"{FRI}T18:00", "party_size": 2}]
    reset(fixture(reservations=seed))
    ta, tb = ada(), bob()
    tc, uc, ec = signup(pw="carol secret pw")
    k1, km, kf = K(), K(), K()
    b1 = {"restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": f"{THU}T19:00", "party_size": 2}
    R1 = req("POST", "/reservations", token=ta, key=k1, body=b1)
    R2 = book(ta, "r_anker", "t_1", f"{THU}T21:00", 2)
    cancel(ta, ref(R2))
    R3 = book(tb, "r_anker", "t_2", f"{THU}T19:00", 2)
    bm = {"moves": [{"reference": ref(R1), "party_size": 1}]}
    RM = req("POST", "/reservation-moves", token=ta, key=km, body=bm)
    RF = book(ta, "r_anker", "t_2", f"{THU}T19:00", 2, key=kf)
    RC = book(tc, "r_ny", "n_1", f"{THU}T12:00", 3)
    check("IE0.1", "IE1", "§10", "setup state created", [x.status_code for x in (R1, R2, R3, RM, RF, RC)] == [201, 201, 201, 201, 409, 201], [x.status_code for x in (R1, R2, R3, RM, RF, RC)])
    toks = {"ada": ta, "bob": tb, "carol": tc}
    pre = snapshot(toks)
    ex = req("GET", "/_test/export", limit=10)
    E = J(ex) or {}
    check("IE1.1", "IE1", "§10", "export -> 200 {track: tablekeeper, format_version: 1, state: object}, unauthenticated",
          ex.status_code == 200 and E.get("track") == "tablekeeper" and E.get("format_version") == 1 and type(E.get("format_version")) is int and isinstance(E.get("state"), dict), ex.text[:200])
    leaked = [p for p in ("correct horse", "battery staple", "carol secret pw") if p in ex.text]
    check("A8.1", "A8", "§6", "export holds no plaintext password", not leaked, leaked)
    check("IE1.2a", "IE1", "§10", "export is read-only (visible state identical afterwards)", snapshot(toks) == pre, "")
    ex2 = req("GET", "/_test/export", limit=10)
    if J(ex2) != E:
        note("IE1.n1", "two exports of unchanged state differ as JSON values", "")
    # writes after the export
    td, ud, ed = signup(pw="dave secret pw")
    R4 = book(ta, "r_anker", "t_2", f"{FRI}T20:00", 2)
    c1 = cancel(ta, ref(R1))
    p3 = patch(tb, ref(R3), {"party_size": 4})
    cs = cancel(tb, "SEED01")
    check("IE0.2", "IE1", "§10", "post-export writes succeeded", td and R4.status_code == 201 and c1.status_code == 200 and p3.status_code == 200 and cs.status_code == 200, [R4.status_code, c1.status_code, p3.status_code, cs.status_code])
    im = req("POST", "/_test/import", body=E, limit=10)
    check("IE2.1a", "IE2", "§10", "import of unchanged export -> 204 with empty body", im.status_code == 204 and not im.content, show(im))
    post = snapshot(toks)
    diff = [k for k in pre if pre[k] != post.get(k)]
    check("IE1.2b", "IE1/IE2/IE3", "§10", "after import the visible state equals the state at export time (restaurants, reservations incl. statuses/timestamps, availability, tokens)", not diff, diff)
    expect("IE2.1b", "IE2", "§10", "user created after the export cannot log in (replacement, not merge)", req("POST", "/auth/login", body={"email": ed, "password": "dave secret pw"}), 401, "unauthenticated")
    expect("IE2.1c", "IE2", "§10", "token created after the export is invalid", req("GET", "/reservations", token=td), 401, "unauthenticated")
    expect("IE2.1d", "IE2", "§10", "reservation created after the export is gone", get(ta, ref(R4)), 404, "not_found")
    im2 = req("POST", "/_test/import", body=E, limit=10)
    check("IE2.1e", "IE2", "§10", "repeated import -> 204, no duplicates", im2.status_code == 204 and snapshot(toks) == pre, show(im2))

    def preserved(tag, base=None):
        bad = []
        for em, pw, uid in [("ada@example.com", "correct horse", "u_ada"), ("bob@example.com", "battery staple", "u_bob"), (ec, "carol secret pw", uc)]:
            r = req("POST", "/auth/login", body={"email": em, "password": pw}, base=base)
            if not (r.status_code == 200 and (J(r) or {}).get("user_id") == uid):
                bad.append(f"login {em}: {show(r)}")
        r = req("POST", "/auth/login", body={"email": "ada@example.com", "password": "wrong password"}, base=base)
        if r.status_code != 401:
            bad.append(f"wrong password accepted: {show(r)}")
        check(f"IE3.1{tag}", "IE3", "§10", "accounts and hashed-password login preserved (ids unchanged, wrong password still refused)", not bad, bad)
        g = req("GET", "/reservations/SEED01", token=tb, base=base)
        check(f"IE3.1{tag}s", "IE3", "§10", "seeded reservation preserved with id and confirmed status", g.status_code == 200 and (J(g) or {}).get("reservation_id") == "res_seed_1" and (J(g) or {}).get("status") == "confirmed", show(g))
        r = req("POST", "/reservations", token=ta, key=k1, body=b1, base=base)
        check(f"IE3.2{tag}a", "IE3", "§10", "replay of completed create key -> 200 original body", r.status_code == 200 and J(r) == J(R1), show(r))
        r = req("POST", "/reservation-moves", token=ta, key=km, body=bm, base=base)
        check(f"IE3.2{tag}b", "IE3/MV8", "§10/§11", "replay of batch receipt -> 200 original body", r.status_code == 200 and J(r) == J(RM), show(r))
        r = req("POST", "/reservations", token=ta, key=k1, body=dict(b1, party_size=1), base=base)
        check(f"IE3.2{tag}c", "IE3", "§10", "used key with different body -> 409 idempotency_key_reuse", r.status_code == 409 and code(r) == "idempotency_key_reuse", show(r))
    preserved("")
    check("IE3.2d", "IE3", "§10", "replays after import changed nothing", snapshot(toks) == pre, "")
    # invalid imports leave destination unchanged
    bad_state = {k: 12345 for k in E.get("state", {})} or {"bogus": True}
    cases = [("IE4.1a", "unparseable body", None, 400, "malformed_request"),
             ("IE4.1b", "missing track", {k: v for k, v in E.items() if k != "track"}, 422, "validation_failed"),
             ("IE4.1c", "missing format_version", {k: v for k, v in E.items() if k != "format_version"}, 422, "validation_failed"),
             ("IE4.1d", "missing state", {k: v for k, v in E.items() if k != "state"}, 422, "validation_failed"),
             ("IE4.1e", "wrong track", dict(E, track="pocketful"), 422, "validation_failed"),
             ("IE4.1f", "wrong format_version 2", dict(E, format_version=2), 422, "validation_failed"),
             ("IE4.1g", "invalid state (every top-level value replaced by a number)", dict(E, state=bad_state), 422, "validation_failed"),
             ("IE4.1h", "empty object", {}, 422, "validation_failed")]
    for cid, desc, body, st, ec_ in cases:
        r = req("POST", "/_test/import", raw='{"track": "tablekeeper", ', limit=10) if body is None else req("POST", "/_test/import", body=body, limit=10)
        expect(cid, "IE4", "§10", f"import with {desc}", r, st, ec_)
    r = req("POST", "/_test/import", body=dict(E, state="x"), limit=10)
    check("IE4.1i", "IE4", "§10/§5", "import with state of wrong JSON type -> 422 validation_failed or 400 malformed_request", (r.status_code, code(r)) in ((422, "validation_failed"), (400, "malformed_request")), show(r))
    check("IE4.2", "IE4", "§10", "destination unchanged after every rejected import", snapshot(toks) == pre, [k for k, v in snapshot(toks).items() if pre.get(k) != v])
    # fresh container
    if BASE2:
        h = req("GET", "/health", base=BASE2)
        reset({"users": [{"id": "u_zed", "email": "zed@example.com", "password": "zed password", "display_name": "Zed"}], "restaurants": [], "reservations": []}, base=BASE2)
        tz = login("zed@example.com", "zed password", base=BASE2)
        im = req("POST", "/_test/import", body=E, base=BASE2, limit=10)
        check("IE5.1a", "IE5", "§10", "import into a second container -> 204", h.status_code == 200 and im.status_code == 204, show(im))
        post2 = snapshot(toks, base=BASE2)
        diff = [k for k in pre if pre[k] != post2.get(k)]
        check("IE5.1b", "IE5/IE3", "§10", "second container shows the exported state; source tokens valid there", not diff, diff)
        expect("IE5.1c", "IE2", "§10", "import removed the destination's previous credentials (old token)", req("GET", "/reservations", token=tz, base=BASE2), 401, "unauthenticated")
        expect("IE5.1d", "IE2", "§10", "import removed the destination's previous accounts", req("POST", "/auth/login", body={"email": "zed@example.com", "password": "zed password"}, base=BASE2), 401, "unauthenticated")
        preserved("x", base=BASE2)
        r = book(ta, "r_anker", "t_2", f"{THU}T19:00", 2, key=kf, base=BASE2)
        expect("IE5.1e", "IE3", "§10", "second container: the failed key replays nothing (same body still 409 table_unavailable, i.e. evaluated as first use)", r, 409, "table_unavailable")
        ex3 = req("GET", "/_test/export", base=BASE2, limit=10)
        check("IE5.1f", "IE1", "§10", "second container can export again", ex3.status_code == 200 and (J(ex3) or {}).get("track") == "tablekeeper", ex3.text[:200])
        rr = reset(SPEC_FIXTURE, base=BASE2)
        r1 = req("GET", "/reservations", token=tb, base=BASE2)
        r2 = req("GET", "/restaurants", base=BASE2)
        check("IE5.1g", "IE5", "§10", "reset clears imported state (tokens invalid, only new fixture)", rr.status_code == 204 and r1.status_code == 401 and [x.get("id") for x in (J(r2) or {}).get("restaurants", [])] == ["r_anker"], show(r1))
    else:
        check("IE5.1a", "IE5", "§10", "second container available for import test", False, "BASE2 not set")
    # failed key still reusable, and generators do not collide (mutating; last)
    r = book(ta, "r_anker", "t_2", f"{THU}T21:00", 2, key=kf)
    expect("IE3.2e", "IE3", "§10", "key that failed before the export is a first use after import (new valid body)", r, 201)
    known_refs = {ref(R1), ref(R2), ref(R3), ref(RC), "SEED01"}
    known_ids = {(J(x) or {}).get("reservation_id") for x in (R1, R2, R3, RC)} | {"res_seed_1"}
    new = [book(ta, "r_all", "a_2", f"2027-10-08T10:{m:02d}", 1) for m in (0, 15, 30, 45)] + [r]
    nrefs = [ref(x) for x in new]
    nids = [(J(x) or {}).get("reservation_id") for x in new]
    check("IE6.1a", "IE6", "§10/§8", "new reservations after import: unique references and ids, no collision with imported ones",
          all(x.status_code == 201 for x in new) and len(set(nrefs)) == 5 and not (set(nrefs) & known_refs) and len(set(nids)) == 5 and not (set(nids) & known_ids), f"{nrefs} {nids}")
    tn, un, _ = signup()
    check("IE6.1b", "IE6", "§10", "new signup after import gets a user_id distinct from imported users", tn and un not in ("u_ada", "u_bob", uc, None), un)
    rr = reset()
    check("IE5.2", "IE5/C3", "§10", "reset clears imported state on the source too (imported tokens invalid)", rr.status_code == 204 and req("GET", "/reservations", token=tc).status_code == 401, show(rr))


def s_ids():
    u, rr, t, i = "u" * 64, "r" * 64, "t" * 64, "i" * 64

    def fx(uid=u, rid=rr, tid=t, iid=i):
        return {"users": [{"id": uid, "email": "long@example.com", "password": "long password", "display_name": "Long"}],
                "restaurants": [{"id": rid, "name": "Long", "timezone": "Europe/Berlin", "slot_minutes": 30, "reservation_duration_minutes": 90,
                                 "cancellation_cutoff_minutes": 0, "opening_hours": hours("18:00", "23:00"), "tables": [{"id": tid, "label": "L", "capacity": 4}]}],
                "reservations": [{"id": iid, "reference": "LONG01", "user_id": uid, "restaurant_id": rid, "table_id": tid, "starts_at_local": f"{THU}T19:00", "party_size": 2}]}
    r = reset(fx())
    lj = J(req("POST", "/auth/login", body={"email": "long@example.com", "password": "long password"})) or {}
    g = req("GET", f"/restaurants/{rr}")
    s = slots(rr, THU, 2)
    gr = get(lj.get("token"), "LONG01")
    check("C7.1", "C7", "§3.4", "fixture ids of exactly 64 characters accepted and usable (user, restaurant, table, reservation)",
          r.status_code == 204 and lj.get("user_id") == u and g.status_code == 200 and s.get(f"{THU}T18:00", {}).get("available_table_ids") == []
          and s.get(f"{THU}T21:00", {}).get("available_table_ids") == [t] and (J(gr) or {}).get("reservation_id") == i, f"{show(r)} | {show(g)} | {show(gr)}")
    for cid, what, kw in [("C7.2a", "user id", {"uid": "u" * 65}), ("C7.2b", "restaurant id", {"rid": "r" * 65}), ("C7.2c", "table id", {"tid": "t" * 65}), ("C7.2d", "reservation id", {"iid": "i" * 65})]:
        expect(cid, "C7", "§3.4/§5", f"reset fixture with 65-character {what}", reset(fx(**kw)), 422, "validation_failed")


def s_seeded():
    seed = [{"id": "res_seed_1", "reference": "SEED01", "user_id": "u_bob", "restaurant_id": "r_anker", "table_id": "t_1", "starts_at_local": f"{FRI}T18:00", "party_size": 2},
            {"id": "res_seed_2", "reference": "SEED02", "user_id": "u_ada", "restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": f"{THU}T19:00", "party_size": 4},
            {"id": "res_seed_3", "reference": "SEED03", "user_id": "u_ada", "restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": f"{PAST_THU}T19:00", "party_size": 4}]
    r = reset(fixture(reservations=seed))
    ta, tb = ada(), bob()
    g = get(tb, "SEED01")
    j = J(g) or {}
    check("M3.1a", "M3", "§4", "seeded reservation visible to owner: id, reference, confirmed, computed starts_at/ends_at, full shape",
          r.status_code == 204 and g.status_code == 200 and not [p for p in shape_problems(j) if "reference" not in p] and j.get("reservation_id") == "res_seed_1" and j.get("reference") == "SEED01"
          and j.get("status") == "confirmed" and j.get("table_id") == "t_1" and j.get("party_size") == 2 and j.get("starts_at_local") == f"{FRI}T18:00"
          and same_ts(j.get("starts_at"), f"{FRI}T18:00:00+02:00") and same_ts(j.get("ends_at"), f"{FRI}T19:30:00+02:00"), f"{shape_problems(j)} {show(g)}")
    la = listing(ta) or []
    check("M3.1b", "M3/L1", "§4", "seeded reservations in owner's list, starts_at descending", [x.get("reference") for x in la] == ["SEED02", "SEED03"], [x.get("reference") for x in la])
    expect("M3.2a", "M3", "§4", "other user cannot see a seeded reservation", get(ta, "SEED01"), 404, "not_found")
    check("M3.2b", "M3", "§4", "seeded reservation occupies its table in availability", tables_at("r_anker", FRI, "18:00", 2) == ["t_2"] and tables_at("r_anker", FRI, "19:00", 2) == ["t_2"] and tables_at("r_anker", FRI, "19:30", 2) == ["t_1", "t_2"], slots("r_anker", FRI, 2))
    expect("M3.2c", "M3", "§4", "booking over a seeded reservation", book(ta, "r_anker", "t_1", f"{FRI}T18:30", 2), 409, "table_unavailable")
    p = patch(ta, "SEED02", {"party_size": 3})
    check("M3.3a", "M3", "§4", "seeded reservation can be amended by owner", p.status_code == 200 and (J(p) or {}).get("party_size") == 3 and (J(p) or {}).get("reservation_id") == "res_seed_2", show(p))
    expect("M3.3b", "M3/X3", "§4", "seeded past reservation: cancel", cancel(ta, "SEED03"), 409, "cutoff_passed")
    c = cancel(tb, "SEED01")
    check("M3.3c", "M3", "§4", "seeded reservation can be cancelled by owner; table freed", c.status_code == 200 and (J(c) or {}).get("status") == "cancelled" and tables_at("r_anker", FRI, "18:00", 2) == ["t_1", "t_2"], show(c))
    new = [book(ta, "r_all", "a_1", f"2027-10-09T09:{m:02d}", 1) for m in (0, 15, 30, 45)]
    check("B2.2", "B2", "§8", "generated references/ids never collide with seeded ones", all(x.status_code == 201 for x in new) and not ({ref(x) for x in new} & {"SEED01", "SEED02", "SEED03"})
          and not ({(J(x) or {}).get("reservation_id") for x in new} & {"res_seed_1", "res_seed_2", "res_seed_3"}), [ref(x) for x in new])


def s_load():
    users = [{"id": f"u_load_{i}", "email": f"load{i}@example.com", "password": f"load password {i}", "display_name": f"L{i}"} for i in range(50)]
    r = reset(fixture(extra_users=users))
    check("LOAD.0", "D3", "§2", "reset with 50 users -> 204 (within 10 s, audited)", r.status_code == 204, show(r))
    rs = parallel([(lambda i=i: req("POST", "/auth/login", body={"email": f"load{i}@example.com", "password": f"load password {i}"})) for i in range(50)])
    toks = [(J(x) or {}).get("token") for x in rs]
    check("LOAD.1a", "D3/E8", "§2", "50 concurrent logins all 200", all(x.status_code == 200 for x in rs), [x.status_code for x in rs])
    rs = parallel([(lambda i=i: req("POST", "/auth/signup", body={"email": f"new{i}@example.com", "password": "new password", "display_name": "N"})) for i in range(50)])
    check("LOAD.1b", "D3/E8", "§2", "50 concurrent signups all 201 with distinct user_ids", all(x.status_code == 201 for x in rs) and len({(J(x) or {}).get("user_id") for x in rs}) == 50, [x.status_code for x in rs])
    rs = parallel([(lambda: req("POST", "/auth/signup", body={"email": "race@example.com", "password": "race password", "display_name": "R"})) for _ in range(20)])
    sts = sorted(x.status_code for x in rs)
    check("LOAD.1c", "A3", "§6", "20 concurrent signups of one email: exactly one 201, others 409 email_taken", sts == [201] + [409] * 19, sts)
    rs = parallel([(lambda t=t: book(t, "r_anker", "t_2", f"{THU}T19:00", 2)) for t in toks])
    sts = sorted(x.status_code for x in rs)
    check("B9.1", "B9", "§1", "50 concurrent creates for one table+slot: exactly one 201, 49 x 409 table_unavailable",
          sts == [201] + [409] * 49 and all(code(x) == "table_unavailable" for x in rs if x.status_code == 409), sts)
    hh = ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30"]
    rs = parallel([(lambda i=i, t=t: book(t, "r_anker", "t_1", f"{THU}T{hh[i % 8]}", 2)) for i, t in enumerate(toks)])
    allc = [x for t in toks for x in (listing(t) or []) if x.get("status") == "confirmed"]
    n201 = sum(1 for x in rs if x.status_code == 201)
    ov = no_overlap(allc)
    check("B9.2", "B9", "§1", "50 concurrent creates over overlapping slots: no overlapping confirmed reservations; every non-201 is 409",
          not ov and n201 >= 1 and all(x.status_code in (201, 409) for x in rs) and len([x for x in allc if x["table_id"] == "t_1"]) == n201, f"overlaps={ov[:3]} statuses={sorted(x.status_code for x in rs)}")
    import random
    rnd = random.Random(7)

    def worker(i, rnd_seed):
        rg = random.Random(rnd_seed)
        t = toks[i]
        out = []
        day = f"2027-11-{rg.randint(10, 12):02d}"
        slot = lambda: f"{day}T{rg.randint(10, 11):02d}:{rg.choice([0, 15, 30, 45]):02d}"
        out.append(avail("r_all", day, 2))
        b = book(t, "r_all", rg.choice(["a_1", "a_2"]), slot(), 2)
        out.append(b)
        out.append(req("GET", "/reservations", token=t))
        if b.status_code == 201:
            out.append(patch(t, ref(b), {"starts_at_local": slot(), "table_id": rg.choice(["a_1", "a_2"])}))
            if rg.random() < 0.3:
                out.append(cancel(t, ref(b)))
        out.append(req("GET", "/restaurants"))
        return out
    allr = []
    for rnd_i in range(4):
        res = parallel([(lambda i=i, s=rnd.random(): worker(i, s)) for i in range(50)])
        allr += [x for o in res for x in o]
    bad = [show(x) for x in allr if x.status_code not in (200, 201, 409)]
    check("LOAD.2a", "D3/E8", "§2/§5", f"4 rounds x 50 in-flight mixed requests ({len(allr)} requests): only 200/201/409", not bad, bad[:3])
    allc = [x for t in toks for x in (listing(t) or []) if x.get("status") == "confirmed"]
    ov = no_overlap(allc)
    check("LOAD.2b", "B9", "§1", f"after load: no two confirmed reservations overlap on a table ({len(allc)} confirmed)", not ov, ov[:3])
    h = req("GET", "/health")
    check("LOAD.3", "D3", "§2", "service healthy after load", h.status_code == 200, show(h))



def s_round2():
    """Checks added in round 2 for the code changed in 0487a51 and the map amendment."""
    seed = lambda **kw: fixture(reservations=[dict({"id": "x1", "reference": "ABCDEF", "user_id": "u_ada", "restaurant_id": "r_anker",
                                                    "table_id": "t_1", "starts_at_local": f"{THU}T19:00", "party_size": 2}, **kw)])
    expect("C3.5a", "C3/E4", "§5/§4", "reset: seeded reservation party_size of string type (party_size exemption)", reset(seed(party_size="4")), 422, "validation_failed")
    expect("C3.5b", "C3/E4", "§5/§4", "reset: seeded reservation party_size true", reset(seed(party_size=True)), 422, "validation_failed")
    expect("C3.5c", "C3/E4", "§5/§4", "reset: seeded reservation party_size 0", reset(seed(party_size=0)), 422, "validation_failed")
    expect("C3.5d", "C3/E5", "§5/§4", "reset: seeded starts_at_local with seconds", reset(seed(starts_at_local=f"{THU}T19:00:00")), 422, "validation_failed")
    expect("C3.5e", "C3/E2", "§5", "reset: seeded restaurant_id of wrong JSON type", reset(seed(restaurant_id=7)), 400, "malformed_request")
    expect("C3.5f", "C3/E2", "§5", "reset: seeded table_id of wrong JSON type (array)", reset(seed(table_id=["t_1"])), 400, "malformed_request")
    expect("C3.5g", "C3/E2", "§5", "reset: seeded starts_at_local of wrong JSON type (number)", reset(seed(starts_at_local=5)), 400, "malformed_request")
    expect("C3.5h", "C3", "§3.3", "reset: valid seeded fixture", reset(seed()), 204)
    # a rejected reset leaves the previous state in place? not stated by the spec -> observation only
    ta = ada()
    note("C3.n1", "state after a rejected reset", f"old token valid={listing(ta) is not None}")
    # PATCH order (map amendment P2)
    reset()
    ta = ada()
    P = book(ta, "r_anker", "t_1", f"{PAST_THU}T19:00", 2)
    C = book(ta, "r_anker", "t_2", f"{THU}T19:00", 2)
    cancel(ta, ref(C))
    expect("P2.3a", "P2", "§8/§11 (map amendment 1)", "PATCH past-cutoff booking with party_size 0: cutoff first", patch(ta, ref(P), {"party_size": 0}), 409, "cutoff_passed")
    expect("P2.3b", "P2", "§8/§11 (map amendment 1)", "PATCH past-cutoff booking with table_id of wrong type: cutoff first", patch(ta, ref(P), {"table_id": 5}), 409, "cutoff_passed")
    expect("P2.3c", "P2", "§8/§11 (map amendment 1)", "PATCH cancelled booking with invalid starts_at_local: cancelled first", patch(ta, ref(C), {"starts_at_local": "nope"}), 409, "reservation_cancelled")
    expect("P2.3d", "P2", "§5", "PATCH past-cutoff booking with unparseable body", req("PATCH", f"/reservations/{ref(P)}", token=ta, raw="{x"), 400, "malformed_request")
    expect("P2.3e", "P4", "§8", "PATCH unknown reference with unparseable body: 404 first (map amendment 1)", req("PATCH", "/reservations/ZZZZZZ99", token=ta, raw="{x"), 404, "not_found")
    # reset atomicity under concurrency: readers during resets only ever see one complete fixture
    fa = {"users": [{"id": "ua", "email": "a@example.com", "password": "password a", "display_name": "A"}],
          "restaurants": [dict(SPEC_FIXTURE["restaurants"][0], id="ra1"), dict(SPEC_FIXTURE["restaurants"][0], id="ra2")], "reservations": []}
    fb = {"users": [{"id": "ub", "email": "b@example.com", "password": "password b", "display_name": "B"}],
          "restaurants": [dict(SPEC_FIXTURE["restaurants"][0], id="rb1"), dict(SPEC_FIXTURE["restaurants"][0], id="rb2"), dict(SPEC_FIXTURE["restaurants"][0], id="rb3")], "reservations": []}
    reset(fa)
    seen, sts = [], []

    def reader():
        for _ in range(15):
            r = req("GET", "/restaurants")
            seen.append(tuple(sorted(x.get("id") for x in (J(r) or {}).get("restaurants", []))))

    def resetter(f):
        for _ in range(5):
            sts.append(reset(f).status_code)
    parallel([reader] * 10 + [lambda: resetter(fa), lambda: resetter(fb), lambda: resetter(fa), lambda: resetter(fb)])
    okset = {("ra1", "ra2"), ("rb1", "rb2", "rb3")}
    check("C3.6a", "C3", "§3.3", "concurrent resets all 204; concurrent readers only ever see one complete fixture", all(x == 204 for x in sts) and set(seen) <= okset, f"{set(sts)} {set(seen) - okset}")
    r = reset(fb)
    la, lb = login("a@example.com", "password a"), login("b@example.com", "password b")
    ids = [x.get("id") for x in (J(req("GET", "/restaurants")) or {}).get("restaurants", [])]
    check("C3.6b", "C3", "§3.3", "after the last reset returns 204 only that fixture is visible (users and restaurants)", r.status_code == 204 and la is None and lb and ids == ["rb1", "rb2", "rb3"], f"{la} {lb} {ids}")
    # a reset racing with writes: after reset returns, no reservation from before survives
    reset()
    ta = ada()
    stop = []

    def writer(i):
        out = []
        for n in range(12):
            out.append(book(ta, "r_all", "a_1", f"2027-12-{10 + i:02d}T{8 + n // 4:02d}:{(n % 4) * 15:02d}", 1).status_code)
        return out
    res = parallel([(lambda i=i: writer(i)) for i in range(8)] + [lambda: [reset().status_code]])
    t2 = ada()
    flat = [x for o in res for x in o]
    check("C3.6c", "C3/E8", "§3.3/§5", "reset racing with 96 bookings: only 201/401/204 seen, no 5xx", set(flat) <= {201, 401, 204}, set(flat))
    r1 = reset()
    t3 = ada()
    check("C3.6d", "C3", "§3.3", "after reset returned, state is exactly the fixture (no reservation survives, table free)", r1.status_code == 204 and listing(t3) == [] and listing(ta) is None
          and tables_at("r_all", "2027-12-10", "08:00", 1) == ["a_1", "a_2"], listing(t3))
    # signup racing with reset must not leak an account into the new state with a stale id clash
    rs = parallel([(lambda i=i: req("POST", "/auth/signup", body={"email": f"race{i}@example.com", "password": "race password", "display_name": "R"})) for i in range(20)] + [lambda: reset()])
    check("C3.6e", "C3/E8", "§3.3/§5", "20 signups racing a reset: only 201/204", all(x.status_code in (201, 204) for x in rs), [x.status_code for x in rs])
    big = fixture(extra_users=[{"id": f"u_big_{i}", "email": f"big{i}@example.com", "password": f"big password {i}", "display_name": "B"} for i in range(500)])
    t = time.monotonic()
    r = reset(big)
    dt = time.monotonic() - t
    tk = login("big499@example.com", "big password 499")
    note("C3.n2", "reset with 502 users (no size stated by spec)", f"status={r.status_code} took {dt:.2f}s login_last_user={'ok' if tk else 'FAILED'}")
    check("C3.6f", "C3/M2", "§3.3/§4", "after a 502-user reset the last seeded user logs in immediately", r.status_code == 204 and tk, show(r))


def final_audits():
    print("\n=== final audits ===", flush=True)
    check("E8.1", "E8", "§5", "no 5xx response in any probe request", not FIVEXX, f"{len(FIVEXX)}: {FIVEXX[:3]}")
    check("E1.1", "E1", "§5", "every 4xx/5xx body is {error: {code, message}}", not BADERR, f"{len(BADERR)}: {BADERR[:3]}")
    check("C4.1", "C4", "§3.4", "every response body is application/json; charset=utf-8", not BADCT, f"{len(BADCT)}: {BADCT[:3]}")
    check("C5.1", "C5", "§3.4", "every starts_at/ends_at/created_at is RFC 3339 with explicit offset", not BADTS, f"{len(BADTS)}: {BADTS[:3]}")
    check("D3.2", "D3", "§2", "every request within 5 s (reset/export/import within 10 s)", not SLOW, f"{len(SLOW)}: {SLOW[:3]}")


def main():
    only = set(sys.argv[1:])
    secs = [s_health_reset, s_auth, s_restaurants_availability, s_create, s_idempotency, s_list_get_cancel, s_patch,
            s_cutoff_dynamic, s_dst, s_moves, s_seeded, s_ids, s_export_import, s_load, s_round2]
    for s in secs:
        if not only or s.__name__ in only:
            section(s)
    final_audits()
    fails = [r for r in RESULTS if not r["ok"]]
    print(f"\nTOTAL {len(RESULTS)} checks: {len(RESULTS) - len(fails)} passed, {len(fails)} failed, {len(NOTES)} notes", flush=True)
    for f in fails:
        print(f"  FAIL {f['id']} [{f['row']} {f['sec']}] {f['desc']} :: {f['detail']}")
    if OUT:
        with open(OUT, "w") as fh:
            json.dump({"base": BASE, "base2": BASE2, "results": RESULTS, "notes": NOTES}, fh, indent=1)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
