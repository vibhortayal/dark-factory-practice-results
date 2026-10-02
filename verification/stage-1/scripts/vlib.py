"""Verifier black-box library for Tablekeeper stage 1.

Talks only HTTP to a running container (TK_BASE, optional second container TK_BASE2).
Every request is logged; global checks (no 5xx, error envelope, content type, time limit)
are evaluated over the whole log at the end of a run.
"""
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

BASE = os.environ.get("TK_BASE", "http://127.0.0.1:18431")
BASE2 = os.environ.get("TK_BASE2", "")

LOG = []
_log_lock = threading.Lock()
_local = threading.local()
NOTSET = object()

ERR_KEYS = ("code", "message")
TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$")
REF_RE = re.compile(r"^[A-Z0-9]{6,12}$")
LOCAL_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d$")
RES_KEYS = {"reservation_id", "reference", "restaurant_id", "table_id", "party_size",
            "status", "starts_at_local", "starts_at", "ends_at", "created_at"}


def _client(base):
    d = getattr(_local, "clients", None)
    if d is None:
        d = _local.clients = {}
    if base not in d:
        d[base] = httpx.Client(base_url=base, timeout=30.0)
    return d[base]


class R:
    def __init__(self, desc, status, headers, content, elapsed):
        self.desc = desc
        self.status = status
        self.headers = headers
        self.content = content
        self.elapsed = elapsed

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")

    @property
    def json(self):
        try:
            return json.loads(self.content)
        except Exception:
            raise AssertionError(f"{self.desc}: body is not JSON: {self.text[:200]!r} (status {self.status})")

    @property
    def code(self):
        try:
            return self.json["error"]["code"]
        except AssertionError:
            raise
        except Exception:
            return None

    def __repr__(self):
        return f"<{self.desc} -> {self.status} {self.text[:300]}>"


def _problems(method, path, status, headers, content):
    probs = []
    if status >= 500:
        probs.append("5xx")
    if status >= 400:
        ok = False
        try:
            j = json.loads(content)
            e = j.get("error") if isinstance(j, dict) else None
            ok = isinstance(e, dict) and all(isinstance(e.get(k), str) for k in ERR_KEYS)
        except Exception:
            ok = False
        if not ok:
            probs.append("envelope")
    if content and method != "HEAD":
        ct = headers.get("content-type", "")
        norm = ct.lower().replace(" ", "")
        if norm != "application/json;charset=utf-8":
            probs.append("ctype")
    if status == 204 and content:
        probs.append("204-with-body")
    limit = 10.0 if path.startswith("/_test/") else 5.0
    return probs, limit


def call(method, path, *, json_body=NOTSET, raw=None, token=None, key=None, headers=None,
         params=None, base=None, ctype="application/json; charset=utf-8"):
    base = base or BASE
    h = {}
    content = None
    if json_body is not NOTSET:
        content = json.dumps(json_body).encode()
        h["Content-Type"] = ctype
    elif raw is not None:
        content = raw
        h["Content-Type"] = ctype
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    if key is not None:
        h["Idempotency-Key"] = key
    if headers:
        h.update(headers)
    desc = f"{method} {path}"
    if params:
        desc += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    if content is not None:
        desc += " body=" + content[:400].decode("utf-8", "replace")
    if key is not None:
        desc += f" key={key[:40]!r}"
    t0 = time.monotonic()
    try:
        resp = _client(base).request(method, path, content=content, headers=h, params=params)
        status, rh, body = resp.status_code, dict(resp.headers), resp.content
    except Exception as e:  # transport failure is recorded as status 599
        status, rh, body = 599, {}, f"TRANSPORT {type(e).__name__}: {e}".encode()
    el = time.monotonic() - t0
    probs, limit = _problems(method, path, status, rh, body)
    if el > limit:
        probs.append("slow")
    with _log_lock:
        LOG.append({"base": base, "desc": desc, "status": status, "elapsed": round(el, 4),
                    "ctype": rh.get("content-type"), "problems": probs,
                    "body": body[:300].decode("utf-8", "replace")})
    return R(desc, status, rh, body, el)


def expect(r, status, code=None):
    assert r.status == status, f"expected {status} {code or ''}, got {r.status}: {r!r}"
    if code is not None:
        assert r.code == code, f"expected code {code}, got {r.code}: {r!r}"
    return r


def expect_in(r, statuses):
    assert r.status in statuses, f"expected one of {statuses}, got {r.status}: {r!r}"
    return r


# ---------------------------------------------------------------- fixtures
ALLDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
FUT = "2027-06-15"    # Tuesday, far beyond any cutoff; Berlin +02:00, New York -04:00
FUT2 = "2027-06-16"
PAST = "2026-09-24"   # Thursday, already past on the day of verification
PW = {"u_ada": "correct horse", "u_bob": "bob battery 9", "u_cy": "cy staple 77"}
EMAIL = {"u_ada": "ada@example.com", "u_bob": "bob@example.com", "u_cy": "cy@example.com"}


def hours(opens="18:00", closes="23:00", days=ALLDAYS):
    return [{"weekday": d, "opens": opens, "closes": closes} for d in days]


def table(tid, cap, label=None):
    return {"id": tid, "label": label or tid, "capacity": cap}


def restaurant(rid="r_anker", name="Zum Anker", tz="Europe/Berlin", slot=30, dur=90, cutoff=120,
               oh=None, tables=None):
    return {"id": rid, "name": name, "timezone": tz, "slot_minutes": slot,
            "reservation_duration_minutes": dur, "cancellation_cutoff_minutes": cutoff,
            "opening_hours": hours() if oh is None else oh,
            "tables": [table("t_1", 2), table("t_2", 4), table("t_3", 4)] if tables is None else tables}


def user(uid, email=None, password=None, name=None):
    return {"id": uid, "email": email or EMAIL.get(uid, f"{uid}@example.com"),
            "password": password or PW.get(uid, f"pw-{uid}-long"), "display_name": name or uid}


def seed(rid_, ref, uid, restaurant_id, table_id, local, party=2):
    return {"id": rid_, "reference": ref, "user_id": uid, "restaurant_id": restaurant_id,
            "table_id": table_id, "starts_at_local": local, "party_size": party}


def fixture(users=None, restaurants=None, reservations=None):
    return {
        "users": [user("u_ada"), user("u_bob")] if users is None else users,
        "restaurants": [restaurant(),
                        restaurant("r_ny", "Hudson", "America/New_York",
                                   tables=[table("n_1", 4), table("n_2", 2)])]
        if restaurants is None else restaurants,
        "reservations": [] if reservations is None else reservations,
    }


def reset(fx=None, base=None):
    r = call("POST", "/_test/reset", json_body=fixture() if fx is None else fx, base=base)
    expect(r, 204)
    assert r.content == b"", f"reset 204 must have no body: {r!r}"
    return r


def login(email, password, base=None):
    r = expect(call("POST", "/auth/login", json_body={"email": email, "password": password}, base=base), 200)
    return r.json["token"]


def tok(uid, base=None):
    return login(EMAIL.get(uid, f"{uid}@example.com"), PW.get(uid, f"pw-{uid}-long"), base=base)


def newkey():
    return "k-" + uuid.uuid4().hex


def body(rid="r_anker", tid="t_2", local=f"{FUT}T19:00", party=2, **extra):
    b = {"restaurant_id": rid, "table_id": tid, "starts_at_local": local, "party_size": party}
    b.update(extra)
    return b


def book(token, rid="r_anker", tid="t_2", local=f"{FUT}T19:00", party=2, key=None, base=None):
    return call("POST", "/reservations", json_body=body(rid, tid, local, party), token=token,
                key=key or newkey(), base=base)


def book_ok(token, *a, **kw):
    return expect(book(token, *a, **kw), 201).json


def avail(rid, date, party, base=None, **extra):
    p = {"restaurant_id": rid, "date": date, "party_size": party}
    p.update(extra)
    return call("GET", "/availability", params=p, base=base)


def slots(rid, date, party=1, base=None):
    r = expect(avail(rid, date, party, base=base), 200)
    return {s["starts_at_local"]: s for s in r.json["slots"]}


def my_list(token, base=None):
    return expect(call("GET", "/reservations", token=token, base=base), 200).json["reservations"]


def get_res(token, ref, base=None):
    return call("GET", f"/reservations/{ref}", token=token, base=base)


def cancel(token, ref, base=None):
    return call("POST", f"/reservations/{ref}/cancel", token=token, base=base)


def patch(token, ref, b, base=None):
    return call("PATCH", f"/reservations/{ref}", json_body=b, token=token, base=base)


def moves(token, items, key=None, base=None, **extra):
    b = {"moves": items}
    b.update(extra)
    return call("POST", "/reservation-moves", json_body=b, token=token, key=key or newkey(), base=base)


# ---------------------------------------------------------------- assertions
def parse_ts(s):
    assert isinstance(s, str) and TS_RE.match(s), f"not RFC 3339 with explicit numeric offset: {s!r}"
    return datetime.fromisoformat(s)


def expected_instant(tzname, local, fold=0):
    """First-occurrence resolution of a bare local time in a zone."""
    dt = datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(tzname), fold=fold)
    return dt


def assert_ts(actual, tzname, local_expected_wall, offset_minutes, what):
    """actual must be RFC 3339, read local_expected_wall (YYYY-MM-DDTHH:MM) with the given offset."""
    dt = parse_ts(actual)
    assert dt.utcoffset() == timedelta(minutes=offset_minutes), \
        f"{what}: offset {dt.utcoffset()} != {offset_minutes} min in {actual!r}"
    assert dt.strftime("%Y-%m-%dT%H:%M") == local_expected_wall and dt.second == 0, \
        f"{what}: reads {actual!r}, expected wall clock {local_expected_wall}"


def assert_res_shape(d, **expected):
    assert isinstance(d, dict), f"reservation is not an object: {d!r}"
    missing = RES_KEYS - set(d)
    assert not missing, f"reservation lacks {sorted(missing)}: {d!r}"
    assert isinstance(d["reservation_id"], str) and 1 <= len(d["reservation_id"]) <= 64, d
    assert isinstance(d["reference"], str) and REF_RE.match(d["reference"]), f"bad reference {d['reference']!r}"
    assert isinstance(d["party_size"], int) and not isinstance(d["party_size"], bool), d
    assert d["status"] in ("confirmed", "cancelled"), d
    assert isinstance(d["starts_at_local"], str) and LOCAL_RE.match(d["starts_at_local"]), d
    s, e, c = parse_ts(d["starts_at"]), parse_ts(d["ends_at"]), parse_ts(d["created_at"])
    assert e > s, d
    for k, v in expected.items():
        assert d[k] == v, f"{k}: expected {v!r}, got {d[k]!r} in {d!r}"
    return s, e, c


def core(d):
    """The specified reservation fields only (an implementation may add others)."""
    return {k: d.get(k) for k in RES_KEYS}


def same(x, y, what=""):
    assert core(x) == core(y), f"{what} reservation differs:\n  got  {core(x)}\n  want {core(y)}"


def assert_no_overlap(tokens, base=None):
    """Core invariant (§1): no two confirmed reservations overlap on one table."""
    seen = {}
    for t in tokens:
        for r in my_list(t, base=base):
            seen[r["reservation_id"]] = r
    by_table = {}
    for r in seen.values():
        if r["status"] == "confirmed":
            by_table.setdefault((r["restaurant_id"], r["table_id"]), []).append(
                (parse_ts(r["starts_at"]), parse_ts(r["ends_at"]), r["reference"]))
    for k, lst in by_table.items():
        lst.sort()
        for (s1, e1, r1), (s2, e2, r2) in zip(lst, lst[1:]):
            assert e1 <= s2, f"DOUBLE BOOKING on {k}: {r1} [{s1},{e1}) overlaps {r2} [{s2},{e2})"
    refs = [r["reference"] for r in seen.values()]
    assert len(refs) == len(set(refs)), "duplicate references"
    return seen


def burst(fns):
    """Run callables concurrently (<= 50, the stated in-flight limit), released together."""
    assert len(fns) <= 50
    out = [None] * len(fns)
    barrier = threading.Barrier(len(fns))

    def run(i):
        try:
            barrier.wait(timeout=30)
            out[i] = fns[i]()
        except Exception as e:
            out[i] = e

    th = [threading.Thread(target=run, args=(i,)) for i in range(len(fns))]
    for t in th:
        t.start()
    for t in th:
        t.join()
    for o in out:
        if isinstance(o, Exception):
            raise AssertionError(f"burst worker raised {o!r}")
    return out


def tally(rs):
    d = {}
    for r in rs:
        k = (r.status, r.code if r.status >= 400 else None)
        d[k] = d.get(k, 0) + 1
    return d


def observe(tokens, base=None, dates=(FUT,)):
    """Client-visible state: restaurants, details, availability, each token's reservations."""
    out = {}
    rs = expect(call("GET", "/restaurants", base=base), 200).json["restaurants"]
    out["restaurants"] = sorted(rs, key=lambda x: x["id"])
    for r in rs:
        out["detail:" + r["id"]] = expect(call("GET", f"/restaurants/{r['id']}", base=base), 200).json
        for d in dates:
            out[f"avail:{r['id']}:{d}"] = expect(avail(r["id"], d, 1, base=base), 200).json
    for name, t in tokens.items():
        rr = call("GET", "/reservations", token=t, base=base)
        out["list:" + name] = (rr.status, rr.json)
    return out


# ---------------------------------------------------------------- registry
CHECKS = []


def check(cid, clause, title):
    def deco(fn):
        CHECKS.append((cid, clause, title, fn))
        return fn
    return deco
