#!/usr/bin/env python3
"""Nightshift Verifier - Pocketful stage 1 - independent HTTP checks.

Derived from pocketful/spec/stage-1.md clause by clause (not from the
Implementer's tests). Standard library only.

  checks.py --list                       print the check list (markdown)
  checks.py --base http://h:p [--base2 http://h:p] [--kill-cmd CMD]
            [--only PREFIX[,PREFIX]] [--json OUT]

t.ok()    = firm assertion tied to a specification statement (failure => finding)
t.probe() = behaviour the specification leaves open; recorded, never a failure
"""
import argparse
import http.client
import json
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

PW = "correct horse"
NOB = object()
AUDIT = []          # (method, path, status, seconds, ctype_problem, limit)
AUDIT_LOCK = threading.Lock()
CHECKS = []


def check(cid, clause, row, desc):
    def deco(fn):
        CHECKS.append(dict(id=cid, clause=clause, row=row, desc=desc, fn=fn))
        return fn
    return deco


class CheckError(Exception):
    pass


class Resp:
    def __init__(self, status, headers, raw, secs):
        self.status, self.headers, self.raw, self.secs = status, headers, raw, secs
        try:
            self.text = raw.decode("utf-8")
        except Exception:
            self.text = repr(raw)
        try:
            self.j = json.loads(raw.decode("utf-8")) if raw else None
        except Exception:
            self.j = None

    def __repr__(self):
        return f"<{self.status} {self.text[:300]}>"


class T:
    def __init__(self):
        self.fails, self.notes = [], []

    def ok(self, cond, msg):
        if not cond:
            self.fails.append(msg)
        return bool(cond)

    def probe(self, cond, msg):
        if not cond:
            self.notes.append(msg)
        return bool(cond)

    def note(self, msg):
        self.notes.append(msg)

    def eq(self, a, e, msg):
        same = a == e and isinstance(a, bool) == isinstance(e, bool)
        return self.ok(same, f"{msg}: expected {e!r}, got {a!r}")

    def st(self, r, status, what):
        return self.ok(r.status == status, f"{what}: expected {status}, got {r!r}")

    def err(self, r, status, code, what):
        return self.ok(is_err(r, status, code), f"{what}: expected {status} {code}, got {r!r}")

    def err_any(self, r, alts, what):
        """Specification leaves the choice among `alts` open; first is our reading."""
        hit = [a for a in alts if is_err(r, *a)]
        if self.ok(bool(hit), f"{what}: expected one of {alts}, got {r!r}"):
            if hit[0] != alts[0]:
                self.note(f"{what}: got {hit[0]} (open choice; first reading {alts[0]})")
            return True
        return False


def is_err(r, status, code):
    e = r.j.get("error") if isinstance(r.j, dict) else None
    return (r.status == status and isinstance(e, dict) and e.get("code") == code
            and isinstance(e.get("message"), str))


TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|z|[+-]\d\d:\d\d)$")


def parse_ts(s):
    return datetime.fromisoformat(re.sub(r"[Zz]$", "+00:00", re.sub(r"(\.\d{6})\d+", r"\1", s)))


def tsok(t, s, what):
    if not t.ok(isinstance(s, str) and TS_RE.match(s) is not None,
                f"{what}: not RFC 3339 with explicit offset: {s!r}"):
        return
    try:
        parse_ts(s)
    except Exception as ex:
        t.ok(False, f"{what}: unparseable timestamp {s!r} ({ex})")
    if s[-1] in "Zz":
        t.note(f"{what}: timestamp uses 'Z' rather than a numeric offset ({s})")


def idok(t, v, what):
    t.ok(isinstance(v, str) and 1 <= len(v) <= 64, f"{what}: id must be a string of 1..64 chars, got {v!r}")


def k():
    return "k-" + uuid.uuid4().hex


def par(fns):
    n = len(fns)
    bar = threading.Barrier(n)

    def w(f):
        try:
            bar.wait(10)
        except Exception:
            pass
        return f()
    with ThreadPoolExecutor(n) as ex:
        return list(ex.map(w, fns))


class Sess:
    def __init__(self, base):
        u = urllib.parse.urlparse(base)
        self.base, self.host, self.port = base, u.hostname, u.port or 80
        self.tok = {}

    def call(self, method, path, body=NOB, as_=None, key=None, raw=None, headers=None,
             token=None, timeout=None):
        ctl = path.startswith("/_test/")
        limit = 10.0 if ctl else 5.0
        h = {}
        data = None
        if raw is not None:
            data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
            h["Content-Type"] = "application/json"
        elif body is not NOB:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            h["Content-Type"] = "application/json"
        if as_ is not None:
            token = self.token(as_)
        if token is not None:
            h["Authorization"] = "Bearer " + token
        if key is not None:
            h["Idempotency-Key"] = key
        if headers:
            h.update(headers)
        if method in ("POST", "PUT", "PATCH") and data is None:
            h["Content-Length"] = "0"
        t0 = time.monotonic()
        try:
            c = http.client.HTTPConnection(self.host, self.port, timeout=timeout or limit + 2)
            c.request(method, path, body=data, headers=h)
            rr = c.getresponse()
            rawb = rr.read()
            hd = {a.lower(): b for a, b in rr.getheaders()}
            c.close()
            r = Resp(rr.status, hd, rawb, time.monotonic() - t0)
        except Exception as ex:
            r = Resp(0, {}, f"TRANSPORT ERROR/TIMEOUT: {ex!r}".encode(), time.monotonic() - t0)
        prob = None
        if r.status and r.raw:
            ct = r.headers.get("content-type", "")
            norm = ct.lower().replace(" ", "")
            if norm != "application/json;charset=utf-8":
                prob = ct or "(none)"
        with AUDIT_LOCK:
            AUDIT.append((method, path[:80], r.status, r.secs, prob, limit))
        return r

    def reset(self, fixture):
        r = self.call("POST", "/_test/reset", fixture)
        self.tok = {}
        if r.status != 204:
            raise CheckError(f"reset expected 204, got {r!r}")
        if r.raw:
            raise CheckError(f"reset 204 carried a body: {r!r}")
        return r

    def login(self, handle, pw=PW, email=None):
        r = self.call("POST", "/auth/login", {"email": email or f"{handle}@example.com", "password": pw})
        if r.status != 200 or not isinstance(r.j, dict) or not isinstance(r.j.get("token"), str):
            raise CheckError(f"login {handle} expected 200 with token, got {r!r}")
        return r.j["token"]

    def token(self, handle):
        if handle not in self.tok:
            self.tok[handle] = self.login(handle)
        return self.tok[handle]

    def me(self, handle):
        r = self.call("GET", "/me", as_=handle)
        if r.status != 200 or not isinstance(r.j, dict):
            raise CheckError(f"GET /me as {handle} expected 200, got {r!r}")
        return r.j

    def bal(self, handle):
        return self.me(handle).get("balance")

    def bals(self, handles):
        return {h: self.bal(h) for h in handles}

    def acts(self, handle, q="?limit=200"):
        r = self.call("GET", "/activity" + q, as_=handle)
        if r.status != 200 or not isinstance(r.j, dict) or not isinstance(r.j.get("payments"), list):
            raise CheckError(f"GET /activity{q} as {handle} expected 200 with payments, got {r!r}")
        return r.j["payments"]

    def reqs(self, handle, q="?limit=200"):
        r = self.call("GET", "/requests" + q, as_=handle)
        if r.status != 200 or not isinstance(r.j, dict) or not isinstance(r.j.get("requests"), list):
            raise CheckError(f"GET /requests{q} as {handle} expected 200 with requests, got {r!r}")
        return r.j["requests"]

    def req_by_id(self, handle, rid):
        for x in self.reqs(handle):
            if x.get("request_id") == rid:
                return x
        return None


def user(uid, handle, bal, pw=PW):
    return {"id": uid, "email": f"{handle}@example.com", "password": pw,
            "display_name": handle.capitalize(), "handle": handle, "balance": bal}


HS = ["ada", "bob", "cy", "dan", "op"]
TOTAL = 14000


def basefx(**over):
    fx = {
        "currency": "EUR", "minor_units": 2,
        "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500), user("u_cy", "cy", 0),
                  user("u_dan", "dan", 500), user("u_op", "op", 1000)],
        "payments": [
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
             "note": "coffee", "visibility": "public"},
            {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_dan", "amount": 200,
             "note": "secret", "visibility": "private"}],
        "requests": [
            {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200,
             "note": "taxi", "status": "pending"},
            {"id": "rq_2", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 300,
             "note": "tea", "status": "pending"}],
        "settlement_operator_ids": ["u_op"],
    }
    fx.update(over)
    return fx


def richfx():
    fx = basefx()
    for u in fx["users"]:
        u["balance"] = 5000000000
    return fx


OTHERFX = {"currency": "JPY", "minor_units": 0,
           "users": [user("u_zed", "zed", 200), user("u_yan", "yan", 100)],
           "payments": [], "requests": []}

PAY_KEYS = ["payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
            "currency", "note", "visibility", "request_id", "settlement_id", "created_at"]
REQ_KEYS = ["request_id", "requester_id", "requester_handle", "payer_id", "payer_handle", "amount",
            "currency", "note", "status", "payment_id", "created_at"]


def pay_shape(t, p, what, **exp):
    if not t.ok(isinstance(p, dict), f"{what}: payment is not an object: {p!r}"):
        return
    for kk in PAY_KEYS:
        t.ok(kk in p, f"{what}: payment lacks '{kk}'")
    idok(t, p.get("payment_id"), what + " payment_id")
    tsok(t, p.get("created_at"), what + " created_at")
    for kk, v in exp.items():
        t.eq(p.get(kk), v, f"{what}: {kk}")


def req_shape(t, q, what, **exp):
    if not t.ok(isinstance(q, dict), f"{what}: request is not an object: {q!r}"):
        return
    for kk in REQ_KEYS:
        t.ok(kk in q, f"{what}: request lacks '{kk}'")
    idok(t, q.get("request_id"), what + " request_id")
    tsok(t, q.get("created_at"), what + " created_at")
    for kk, v in exp.items():
        t.eq(q.get(kk), v, f"{what}: {kk}")


def ids(lst, key):
    return [x.get(key) for x in lst]


# --------------------------------------------------------------------------- A
@check("A4-health", "§3.2", "A4", "GET /health -> 200 {\"status\":\"ok\"}; unknown query parameter ignored; no auth needed")
def c_health(t, S):
    r = S.call("GET", "/health")
    t.st(r, 200, "GET /health")
    t.eq(r.j, {"status": "ok"}, "GET /health body")
    r = S.call("GET", "/health?zzz=1")
    t.st(r, 200, "GET /health?zzz=1")


@check("A8-unknown-fields", "§3.4", "A8", "Unknown body fields and unknown query parameters are ignored on every endpoint")
def c_unknown(t, S):
    fx = basefx()
    fx["zzz"] = {"a": 1}
    fx["users"][0]["zzz"] = [1]
    fx["payments"][0]["zzz"] = "x"
    fx["requests"][0]["zzz"] = None
    S.reset(fx)
    r = S.call("POST", "/auth/signup", {"email": "newbie@example.com", "password": "longenough",
                                         "display_name": "New", "zzz": 1, "handle": "hijack"})
    t.st(r, 201, "signup with unknown fields")
    r = S.call("POST", "/auth/login", {"email": "ada@example.com", "password": PW, "zzz": 1})
    t.st(r, 200, "login with unknown field")
    r = S.call("GET", "/me?zzz=1", as_="ada")
    t.st(r, 200, "GET /me?zzz=1")
    r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 10, "zzz": {"x": 1}}, as_="ada", key=k())
    t.st(r, 201, "payment with unknown field")
    r = S.call("POST", "/requests", {"payer_handle": "ada", "amount": 10, "zzz": 1, "visibility": "nope"},
               as_="bob", key=k())
    t.st(r, 201, "request with unknown fields (visibility is not a field of POST /requests)")
    rid = r.j.get("request_id") if isinstance(r.j, dict) else "x"
    r = S.call("POST", f"/requests/{rid}/pay", {"zzz": 1, "amount": "junk"}, as_="ada", key=k())
    t.st(r, 201, "pay with unknown fields")
    r = S.call("POST", "/splits", {"amount": 30, "participant_handles": ["bob"], "zzz": 1}, as_="ada", key=k())
    t.st(r, 201, "split with unknown field")
    r = S.call("POST", "/settlements", {"zzz": 1, "transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 1, "zzz": 1}]}, as_="op", key=k())
    t.st(r, 201, "settlement with unknown fields")
    r = S.call("POST", "/requests/rq_1/decline", {"zzz": 1}, as_="ada")
    t.st(r, 200, "decline with a body of unknown fields")
    r = S.call("POST", "/requests/rq_2/cancel", {"zzz": 1}, as_="bob")
    t.st(r, 200, "cancel with a body of unknown fields")
    for p in ("/activity?zzz=1&limit=5", "/requests?zzz=1&limit=5"):
        r = S.call("GET", p, as_="ada")
        t.st(r, 200, "GET " + p)


@check("A9-ids", "§3.4", "A9", "Generated IDs are strings of at most 64 characters; seeded IDs are kept as given")
def c_ids(t, S):
    S.reset(basefx())
    r = S.call("POST", "/auth/signup", {"email": "idcheck@example.com", "password": "longenough", "display_name": "I"})
    t.st(r, 201, "signup")
    idok(t, (r.j or {}).get("user_id"), "signup user_id")
    r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 1}, as_="ada", key=k())
    idok(t, (r.j or {}).get("payment_id"), "payment_id")
    r = S.call("POST", "/requests", {"payer_handle": "ada", "amount": 1}, as_="bob", key=k())
    idok(t, (r.j or {}).get("request_id"), "request_id")
    r = S.call("POST", "/splits", {"amount": 3, "participant_handles": ["bob"]}, as_="ada", key=k())
    idok(t, (r.j or {}).get("split_id"), "split_id")
    r = S.call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]},
               as_="op", key=k())
    idok(t, (r.j or {}).get("settlement_id"), "settlement_id")
    t.eq(S.me("ada").get("user_id"), "u_ada", "seeded user id kept")


@check("A10-out-of-scope", "§1, §4", "A10", "Deposits, top-ups, withdrawals and an admin balance endpoint are out of scope: no such route changes a balance")
def c_scope(t, S):
    S.reset(basefx())
    for m, p in [("POST", "/deposits"), ("POST", "/topups"), ("POST", "/top-ups"), ("POST", "/withdrawals"),
                 ("POST", "/me/deposit"), ("POST", "/admin/balance"), ("POST", "/_test/balance"),
                 ("PUT", "/me"), ("PATCH", "/me")]:
        r = S.call(m, p, {"amount": 100, "handle": "ada", "balance": 99999, "user_id": "u_ada"}, as_="ada", key=k())
        t.ok(400 <= r.status < 500, f"{m} {p}: expected a 4xx, got {r!r}")
    b = S.bals(HS)
    t.eq(sum(b.values()), TOTAL, "sum of balances after out-of-scope probes")
    t.eq(b["ada"], 10000, "ada balance after out-of-scope probes")


# --------------------------------------------------------------------------- B
@check("B2-overspend", "§1 inv 1,2", "B1,B2", "20 parallel payments of 100 from a wallet holding 500: exactly 5 succeed, 15 are 409 insufficient_funds, balance never negative, sum preserved")
def c_overspend(t, S):
    for rnd in range(3):
        S.reset(basefx())
        S.token("dan"), S.token("bob")
        seen = []
        stop = threading.Event()

        def poll():
            while not stop.is_set():
                r = S.call("GET", "/me", as_="dan")
                if isinstance(r.j, dict):
                    seen.append(r.j.get("balance"))
        th = threading.Thread(target=poll)
        th.start()
        rs = par([lambda: S.call("POST", "/payments", {"to_handle": "bob", "amount": 100}, as_="dan", key=k())
                  for _ in range(20)])
        stop.set()
        th.join()
        n201 = sum(r.status == 201 for r in rs)
        n409 = sum(is_err(r, 409, "insufficient_funds") for r in rs)
        t.ok(n201 == 5 and n409 == 15, f"round {rnd}: expected 5x201 + 15x409 insufficient_funds, got {sorted(r.status for r in rs)}")
        t.ok(all(isinstance(x, int) and x >= 0 for x in seen), f"round {rnd}: observed negative/non-integer balance {seen}")
        b = S.bals(HS)
        t.eq(b["dan"], 0, f"round {rnd}: dan balance")
        t.eq(b["bob"], 3000, f"round {rnd}: bob balance")
        t.eq(sum(b.values()), TOTAL, f"round {rnd}: sum of balances")


@check("B3-pay-once", "§1 inv 3, §8 pay", "B3", "10 parallel pays of one request with different keys: exactly one 201, the rest 409 request_not_pending, money moves once")
def c_payonce(t, S):
    for rnd in range(3):
        S.reset(basefx())
        S.token("ada")
        rs = par([lambda i=i: S.call("POST", "/requests/rq_1/pay", {"visibility": "private" if i % 2 else "public"},
                                     as_="ada", key=k()) for i in range(10)])
        n201 = sum(r.status == 201 for r in rs)
        n409 = sum(is_err(r, 409, "request_not_pending") for r in rs)
        t.ok(n201 == 1 and n409 == 9, f"round {rnd}: expected 1x201 + 9x409 request_not_pending, got {[repr(r)[:90] for r in rs]}")
        b = S.bals(HS)
        t.eq(b["ada"], 8800, f"round {rnd}: ada balance")
        t.eq(b["bob"], 3700, f"round {rnd}: bob balance")
        q = S.req_by_id("ada", "rq_1")
        t.eq((q or {}).get("status"), "paid", f"round {rnd}: rq_1 status")
        mine = [p for p in S.acts("ada") if p.get("request_id") == "rq_1"]
        t.eq(len(mine), 1, f"round {rnd}: payments linked to rq_1")


@check("B3-race-terminal", "§1 inv 3, §4 requests", "B3", "Concurrent pay / decline / cancel of one request leave exactly one terminal state, consistent with the money moved")
def c_race(t, S):
    for rnd in range(5):
        S.reset(basefx())
        S.token("ada"), S.token("bob")
        fns = [lambda: ("pay", S.call("POST", "/requests/rq_1/pay", {}, as_="ada", key=k())) for _ in range(6)]
        fns += [lambda: ("decline", S.call("POST", "/requests/rq_1/decline", as_="ada")) for _ in range(4)]
        fns += [lambda: ("cancel", S.call("POST", "/requests/rq_1/cancel", as_="bob")) for _ in range(4)]
        rs = par(fns)
        st = (S.req_by_id("ada", "rq_1") or {}).get("status")
        t.ok(st in ("paid", "declined", "cancelled"), f"round {rnd}: final status {st!r}")
        pays = [r for n, r in rs if n == "pay"]
        n201 = sum(r.status == 201 for r in pays)
        t.eq(n201, 1 if st == "paid" else 0, f"round {rnd}: pay 201 count with final status {st}")
        t.ok(all(r.status == 201 or is_err(r, 409, "request_not_pending") for r in pays),
             f"round {rnd}: pay responses {[r.status for r in pays]}")
        for name, final in (("decline", "declined"), ("cancel", "cancelled")):
            xs = [r for n, r in rs if n == name]
            if st == final:
                t.ok(all(r.status == 200 for r in xs), f"round {rnd}: {name} with final {st}: {[r.status for r in xs]}")
            else:
                t.ok(all(is_err(r, 409, "request_not_pending") for r in xs),
                     f"round {rnd}: {name} with final {st}: {[repr(r)[:80] for r in xs]}")
        b = S.bals(HS)
        t.eq(b["ada"], 8800 if st == "paid" else 10000, f"round {rnd}: ada balance with final {st}")
        t.eq(sum(b.values()), TOTAL, f"round {rnd}: sum of balances")


@check("B4-exact-2p53", "§4 arithmetic range", "B4", "Balances up to 2^53 stay exact: seed near 2^53, move 1 unit at a time, compare exactly")
def c_2p53(t, S):
    fx = basefx()
    fx["users"] = [user("u_big", "big", 9007199254740000), user("u_lil", "lil", 992)]
    fx["payments"], fx["requests"], fx["settlement_operator_ids"] = [], [], []
    S.reset(fx)
    t.eq(S.bal("big"), 9007199254740000, "seeded big balance")
    r = S.call("POST", "/payments", {"to_handle": "big", "amount": 991}, as_="lil", key=k())
    t.st(r, 201, "lil pays big 991")
    t.eq(S.bal("big"), 9007199254740991, "big balance = 2^53-1")
    r = S.call("POST", "/payments", {"to_handle": "big", "amount": 1}, as_="lil", key=k())
    t.st(r, 201, "lil pays big 1")
    t.eq(S.bal("big"), 9007199254740992, "big balance = 2^53")
    t.eq(S.bal("lil"), 0, "lil balance")
    r = S.call("POST", "/payments", {"to_handle": "lil", "amount": 1}, as_="big", key=k())
    t.st(r, 201, "big pays lil 1")
    t.eq(S.bal("big"), 9007199254740991, "big balance back to 2^53-1")
    t.eq(S.bal("lil"), 1, "lil balance")


# --------------------------------------------------------------------------- C
@check("C1-reset-replaces", "§3.3", "C1,C7", "Reset returns 204 without auth and replaces all state: users, tokens, payments, requests, idempotency records, operators; repeated resets work")
def c_reset(t, S):
    S.reset(basefx())
    ta = S.token("ada")
    key = k()
    body = {"to_handle": "bob", "amount": 10}
    r = S.call("POST", "/payments", body, as_="ada", key=key)
    t.st(r, 201, "payment before reset")
    r = S.call("POST", "/auth/signup", {"email": "gone@example.com", "password": "longenough", "display_name": "G"})
    t.st(r, 201, "signup before reset")
    S.reset(OTHERFX)
    t.err(S.call("GET", "/me", token=ta), 401, "unauthenticated", "old token after reset")
    t.err(S.call("POST", "/auth/login", {"email": "ada@example.com", "password": PW}), 401, "unauthenticated",
          "old user login after reset")
    t.err(S.call("POST", "/auth/login", {"email": "gone@example.com", "password": "longenough"}), 401,
          "unauthenticated", "signed-up user login after reset")
    me = S.me("zed")
    t.eq(me.get("balance"), 200, "zed balance")
    t.eq(me.get("currency"), "JPY", "currency after reset")
    t.eq(me.get("minor_units"), 0, "minor_units after reset")
    t.eq(S.acts("zed"), [], "activity after reset to fixture without payments")
    t.eq(S.reqs("zed"), [], "requests after reset to fixture without requests")
    r = S.call("POST", "/settlements", {"transfers": [{"from_handle": "zed", "to_handle": "yan", "amount": 1}]},
               as_="zed", key=k())
    t.err(r, 403, "forbidden", "settlement when fixture omits settlement_operator_ids (default [])")
    fx = dict(OTHERFX, settlement_operator_ids=["u_zed"])
    S.reset(fx)
    r = S.call("POST", "/settlements", {"transfers": [{"from_handle": "yan", "to_handle": "zed", "amount": 1}]},
               as_="zed", key=k())
    t.st(r, 201, "settlement by fixture operator")
    S.reset(basefx())
    r = S.call("POST", "/payments", body, as_="ada", key=key)
    t.st(r, 201, "same key+body after reset is a first use (idempotency records cleared)")
    t.eq(sorted(ids(S.acts("ada"), "note")), sorted(["coffee", ""]), "ada activity after reset (only seeded + new)")
    t.eq(S.bal("ada"), 9990, "ada balance after reset + one payment")
    r = S.call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]},
               as_="ada", key=k())
    t.err(r, 403, "forbidden", "non-operator after reset")


@check("C2-seeded-users", "§4 fixture, §8 /me", "C2,C3,G1", "Seeded users log in at once; /me shows seeded id, display_name, handle, balance (not replayed), currency, minor_units")
def c_seed_users(t, S):
    S.reset(basefx())
    exp = {"ada": 10000, "bob": 2500, "cy": 0, "dan": 500, "op": 1000}
    for h, b in exp.items():
        r = S.call("POST", "/auth/login", {"email": f"{h}@example.com", "password": PW})
        t.st(r, 200, f"login {h}")
        j = r.j or {}
        t.eq(j.get("user_id"), "u_" + h, f"login {h} user_id")
        t.eq(j.get("display_name"), h.capitalize(), f"login {h} display_name")
        t.ok(isinstance(j.get("token"), str) and j.get("token"), f"login {h} token")
        me = S.me(h)
        t.eq(me, dict(me, user_id="u_" + h, display_name=h.capitalize(), handle=h, balance=b,
                      currency="EUR", minor_units=2), f"/me {h}")
        for kk in ("user_id", "display_name", "handle", "balance", "currency", "minor_units"):
            t.ok(kk in me, f"/me {h} lacks {kk}")


@check("C4-seeded-records", "§4 fixture, feed contract", "C4", "Seeded payments appear in /activity under the feed rule with the full payment shape; seeded requests appear in /requests with their status")
def c_seed_records(t, S):
    fx = basefx()
    fx["requests"] += [
        {"id": "rq_d", "requester_id": "u_cy", "payer_id": "u_dan", "amount": 70, "note": "d", "status": "declined"},
        {"id": "rq_c", "requester_id": "u_cy", "payer_id": "u_dan", "amount": 80, "note": "c", "status": "cancelled"}]
    S.reset(fx)
    for h in HS:
        a = {p.get("payment_id"): p for p in S.acts(h)}
        t.ok("p_1" in a, f"public seeded p_1 missing from {h}'s activity")
        t.eq("p_2" in a, h in ("bob", "dan"), f"private seeded p_2 in {h}'s activity")
        if "p_1" in a:
            pay_shape(t, a["p_1"], f"{h} p_1", payment_id="p_1", from_user_id="u_ada", from_handle="ada",
                      to_user_id="u_bob", to_handle="bob", amount=500, currency="EUR", note="coffee",
                      visibility="public", request_id=None, settlement_id=None)
        if "p_2" in a:
            pay_shape(t, a["p_2"], f"{h} p_2", payment_id="p_2", from_handle="bob", to_handle="dan",
                      amount=200, note="secret", visibility="private", request_id=None, settlement_id=None)
    for h in ("ada", "bob"):
        q = S.req_by_id(h, "rq_1")
        req_shape(t, q, f"{h} rq_1", request_id="rq_1", requester_id="u_bob", requester_handle="bob",
                  payer_id="u_ada", payer_handle="ada", amount=1200, currency="EUR", note="taxi",
                  status="pending", payment_id=None)
    for h in ("cy", "dan"):
        t.eq((S.req_by_id(h, "rq_d") or {}).get("status"), "declined", f"{h} sees seeded declined request")
        t.eq((S.req_by_id(h, "rq_c") or {}).get("status"), "cancelled", f"{h} sees seeded cancelled request")
    t.eq(S.reqs("op"), [], "third party sees no seeded requests")
    t.err(S.call("POST", "/requests/rq_d/pay", {}, as_="dan", key=k()), 409, "request_not_pending", "pay seeded declined request")


@check("C5-negative-balance", "§4 fixture", "C5", "Fixture balance below zero -> 422 validation_failed and nothing changes; balance 0 is accepted")
def c_negbal(t, S):
    S.reset(basefx())
    ta = S.token("ada")
    fx = dict(OTHERFX, users=[user("u_zed", "zed", 200), user("u_yan", "yan", -1)])
    r = S.call("POST", "/_test/reset", fx)
    t.err(r, 422, "validation_failed", "reset with balance -1")
    r = S.call("GET", "/me", token=ta)
    t.st(r, 200, "previous token after rejected reset")
    t.eq((r.j or {}).get("balance"), 10000, "previous balance after rejected reset")
    t.eq((r.j or {}).get("currency"), "EUR", "previous currency after rejected reset")
    t.err(S.call("POST", "/auth/login", {"email": "zed@example.com", "password": PW}), 401, "unauthenticated",
          "user of rejected fixture cannot log in")
    t.eq(S.bal("cy"), 0, "balance 0 seeded")


@check("C6-currencies", "§4 model, fixture", "C6", "minor_units 0, 2, 3 (JPY, EUR, BHD); currency echoed on /me, payments, requests, splits")
def c_cur(t, S):
    for cur, mu in (("JPY", 0), ("EUR", 2), ("BHD", 3)):
        S.reset(basefx(currency=cur, minor_units=mu))
        me = S.me("ada")
        t.eq(me.get("currency"), cur, f"{cur} /me currency")
        t.eq(me.get("minor_units"), mu, f"{cur} /me minor_units")
        r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 1000}, as_="ada", key=k())
        t.eq((r.j or {}).get("currency"), cur, f"{cur} payment currency")
        t.eq((r.j or {}).get("amount"), 1000, f"{cur} payment amount")
        t.eq(S.bal("ada"), 9000, f"{cur} balance after paying 1000 minor units")
        r = S.call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, as_="bob", key=k())
        t.eq((r.j or {}).get("currency"), cur, f"{cur} request currency")
        r = S.call("POST", "/splits", {"amount": 5, "participant_handles": ["bob"]}, as_="ada", key=k())
        t.eq((r.j or {}).get("currency"), cur, f"{cur} split currency")
        t.eq(((r.j or {}).get("requests") or [{}])[0].get("currency"), cur, f"{cur} split request currency")
        t.eq((S.acts("ada") or [{}])[0].get("currency"), cur, f"{cur} activity currency")


@check("C8-reset-malformed", "§3.3, §5", "C8", "Unparseable reset body -> 400 malformed_request; state unchanged")
def c_reset_bad(t, S):
    S.reset(basefx())
    ta = S.token("ada")
    r = S.call("POST", "/_test/reset", raw='{"currency": "EUR", "users": [')
    t.err(r, 400, "malformed_request", "reset with unparseable body")
    r = S.call("GET", "/me", token=ta)
    t.st(r, 200, "token after malformed reset")
    t.eq((r.j or {}).get("balance"), 10000, "balance after malformed reset")


# --------------------------------------------------------------------------- D
@check("D1-error-shape", "§5", "D1", "Every 4xx body is {error:{code,message}}, including unknown routes and wrong methods")
def c_errshape(t, S):
    S.reset(basefx())
    for m, p in [("GET", "/nope"), ("POST", "/nope"), ("GET", "/payments"), ("DELETE", "/me"),
                 ("GET", "/requests/rq_1"), ("GET", "/auth/login"), ("PUT", "/requests/rq_1/pay")]:
        r = S.call(m, p, as_="ada")
        e = r.j.get("error") if isinstance(r.j, dict) else None
        t.ok(400 <= r.status < 500 and isinstance(e, dict) and isinstance(e.get("code"), str)
             and isinstance(e.get("message"), str), f"{m} {p}: expected 4xx with error body, got {r!r}")
    t.err(S.call("GET", "/definitely/not/here", as_="ada"), 404, "not_found", "unknown route, authenticated")


@check("D2-malformed", "§5", "D2", "Unparseable body, or a field of the wrong JSON type (other than amount/note/visibility) -> 400 malformed_request")
def c_malformed(t, S):
    S.reset(basefx())
    posts = [("/payments", "ada"), ("/requests", "bob"), ("/splits", "ada"), ("/settlements", "op"),
             ("/requests/rq_1/pay", "ada"), ("/auth/signup", None), ("/auth/login", None)]
    for p, who in posts:
        for raw in ('{"to_handle": "bob", "amount": ', "this is not json", '{"a":1,}'):
            r = S.call("POST", p, raw=raw, as_=who, key=k() if who else None)
            t.err(r, 400, "malformed_request", f"POST {p} unparseable body {raw!r}")
        for raw in ("[]", '"str"', "5", "null"):
            r = S.call("POST", p, raw=raw, as_=who, key=k() if who else None)
            t.err_any(r, [(400, "malformed_request"), (422, "validation_failed")], f"POST {p} non-object body {raw}")
    cases = [("/payments", "ada", {"to_handle": 5, "amount": 10}),
             ("/payments", "ada", {"to_handle": ["bob"], "amount": 10}),
             ("/payments", "ada", {"to_handle": True, "amount": 10}),
             ("/requests", "bob", {"payer_handle": 5, "amount": 10}),
             ("/requests", "bob", {"payer_handle": {"h": "ada"}, "amount": 10}),
             ("/splits", "ada", {"amount": 10, "participant_handles": "bob"}),
             ("/splits", "ada", {"amount": 10, "participant_handles": {"a": 1}}),
             ("/splits", "ada", {"amount": 10, "participant_handles": 7}),
             ("/auth/signup", None, {"email": 1, "password": "longenough", "display_name": "X"}),
             ("/auth/signup", None, {"email": "t1@example.com", "password": 12345678, "display_name": "X"}),
             ("/auth/signup", None, {"email": "t2@example.com", "password": "longenough", "display_name": 5}),
             ("/auth/login", None, {"email": 1, "password": PW}),
             ("/auth/login", None, {"email": "ada@example.com", "password": 5})]
    for p, who, body in cases:
        r = S.call("POST", p, body, as_=who, key=k() if who else None)
        t.err(r, 400, "malformed_request", f"POST {p} {json.dumps(body)}")
    for p, who, body in [("/payments", "ada", {"to_handle": None, "amount": 10}),
                         ("/splits", "ada", {"amount": 10, "participant_handles": [1, 2]}),
                         ("/settlements", "op", {"transfers": [{"from_handle": 5, "to_handle": "bob", "amount": 1}]})]:
        r = S.call("POST", p, body, as_=who, key=k())
        t.err_any(r, [(400, "malformed_request"), (422, "validation_failed")], f"POST {p} {json.dumps(body)}")
    b = S.bals(HS)
    t.eq(b, {"ada": 10000, "bob": 2500, "cy": 0, "dan": 500, "op": 1000}, "balances after malformed requests")
    r = S.call("POST", "/payments", raw=b'{"note": "\xff\xfe", "to_handle": "bob", "amount": 1}', as_="ada", key=k())
    t.probe(is_err(r, 400, "malformed_request"), f"POST /payments body with invalid UTF-8: got {r!r}")


def _targets():
    """(name, caller, path, builder(field,value)->body) for amount/note/visibility matrices."""
    def pay(f, v):
        b = {"to_handle": "bob", "amount": 10}
        b[f] = v
        return b

    def rq(f, v):
        b = {"payer_handle": "ada", "amount": 10}
        b[f] = v
        return b

    def sp(f, v):
        b = {"amount": 10, "participant_handles": ["bob"]}
        b[f] = v
        return b

    def se(f, v):
        e = {"from_handle": "ada", "to_handle": "bob", "amount": 10}
        e[f] = v
        return {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}, e]}

    def py(f, v):
        return {f: v}
    return [("payments", "ada", "/payments", pay, ("amount", "note", "visibility")),
            ("requests", "bob", "/requests", rq, ("amount", "note")),
            ("splits", "ada", "/splits", sp, ("amount", "note")),
            ("settlements", "op", "/settlements", se, ("amount", "note", "visibility")),
            ("pay", "ada", "/requests/rq_1/pay", py, ("visibility",))]


@check("D3-field-rules", "§5 bullet 1, §8, §11", "D3,D5,D6", "Invalid amount (string, boolean, null, fractional, <1, >1e9, array, object), non-string note incl. null, note of 201 chars, and any visibility other than public/private -> 422 validation_failed on every endpoint taking them; nothing moves")
def c_fieldrules(t, S):
    S.reset(richfx())
    bad = {"amount": ["100", "", True, False, None, 1.5, 0, 0.0, -1, -1000, 1000000001, 1e12, [], {}, [10]],
           "note": [5, None, True, ["a"], {"a": 1}, "x" * 201, "\u00e9" * 201],
           "visibility": ["friends", "", "PUBLIC", "Private", " public", 5, None, True, [], {}]}
    for name, who, path, build, fields in _targets():
        for f in fields:
            for v in bad[f]:
                r = S.call("POST", path, build(f, v), as_=who, key=k())
                shown = v if not (isinstance(v, str) and len(v) > 30) else f"<{len(v)} chars>"
                t.err(r, 422, "validation_failed", f"POST {path} {f}={shown!r}")
    b = S.bals(HS)
    t.ok(all(v == 5000000000 for v in b.values()), f"balances changed by rejected requests: {b}")
    t.eq((S.req_by_id("ada", "rq_1") or {}).get("status"), "pending", "rq_1 still pending after rejected pays")
    t.eq(len(S.acts("ada")), 1, "ada activity count after rejected requests (only seeded p_1)")
    t.eq(len(S.reqs("ada")), 2, "ada request count after rejected requests (only seeded)")


@check("D4-integral-forms", "§4 model", "D4", "JSON 1000, 1000.0 and 1e3 are the same valid amount; 1000.5 is 422")
def c_integral(t, S):
    S.reset(richfx())
    for lit in ("1000", "1000.0", "1e3", "1E3", "10e2", "1000.000"):
        r = S.call("POST", "/payments", raw='{"to_handle":"bob","amount":%s}' % lit, as_="ada", key=k())
        t.st(r, 201, f"payment amount literal {lit}")
        t.eq((r.j or {}).get("amount"), 1000, f"payment amount literal {lit} echoed")
        r = S.call("POST", "/requests", raw='{"payer_handle":"ada","amount":%s}' % lit, as_="bob", key=k())
        t.st(r, 201, f"request amount literal {lit}")
        t.eq((r.j or {}).get("amount"), 1000, f"request amount literal {lit} echoed")
    r = S.call("POST", "/splits", raw='{"amount":1e3,"participant_handles":["ada","bob","cy"]}', as_="ada", key=k())
    t.st(r, 201, "split amount 1e3")
    t.eq([s.get("amount") for s in (r.j or {}).get("shares", [])], [334, 333, 333], "split 1e3 shares")
    r = S.call("POST", "/settlements", raw='{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":1000.0}]}',
               as_="op", key=k())
    t.st(r, 201, "settlement amount 1000.0")
    r = S.call("POST", "/requests", raw='{"payer_handle":"ada","amount":1e9}', as_="bob", key=k())
    t.st(r, 201, "request amount 1e9")
    t.eq((r.j or {}).get("amount"), 1000000000, "request amount 1e9 echoed")
    for lit in ("1000.5", "0.5", "1e-1", "999.999"):
        r = S.call("POST", "/payments", raw='{"to_handle":"bob","amount":%s}' % lit, as_="ada", key=k())
        t.err(r, 422, "validation_failed", f"payment amount literal {lit}")
    t.eq(S.bal("ada"), 5000000000 - 7000, "ada balance after 6 payments + settlement of 1000")


@check("D5-amount-bounds", "§4 arithmetic range, §8, §11", "D5", "amount 0 -> 422, 1 ok, 1000000000 ok, 1000000001 -> 422 on payments, requests, splits and settlement entries")
def c_bounds(t, S):
    S.reset(richfx())
    for name, who, path, build, fields in _targets():
        if "amount" not in fields:
            continue
        for v, ok in ((0, False), (1, True), (1000000000, True), (1000000001, False)):
            r = S.call("POST", path, build("amount", v), as_=who, key=k())
            if ok:
                t.st(r, 201, f"POST {path} amount={v}")
            else:
                t.err(r, 422, "validation_failed", f"POST {path} amount={v}")
    b = S.bals(HS)
    t.eq(sum(b.values()), 25000000000, "sum after boundary amounts")
    t.eq(b["ada"], 5000000000 - 1 - 1000000000 - 1 - 1 - 1 - 1000000000, "ada after boundary amounts")


NOTES = ["  padded  ", "\tTab and\nnewline\r\n", "<b>bold</b> &amp; \"quotes\" 'single' \\ / %20 %s {0}",
         "emoji \U0001F355\U0001F389 \U0001F468\u200D\U0001F469\u200D\U0001F467", "nfd e\u0301 vs nfc \u00e9",
         "\u65e5\u672c\u8a9e \u0627\u0644\u0639\u0631\u0628\u064a\u0629 \u05e2\u05d1\u05e8\u05d9\u05ea", " ", "null", "0"]


@check("D6-note", "§8 payments note", "D6", "note of 200 characters ok, 201 -> 422 (characters, not bytes); stored and returned verbatim (no trimming, escaping or normalisation) on payments, requests, splits, settlements, feed and replay")
def c_note(t, S):
    S.reset(basefx())
    for n in NOTES:
        key = k()
        r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": n}, as_="ada", key=key)
        t.st(r, 201, f"payment note {n!r}")
        t.eq((r.j or {}).get("note"), n, "payment note echoed verbatim")
        seen = [p for p in S.acts("bob") if p.get("payment_id") == (r.j or {}).get("payment_id")]
        t.eq((seen or [{}])[0].get("note"), n, "payment note in receiver's feed verbatim")
        r2 = S.call("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": n}, as_="ada", key=key)
        t.eq((r2.j or {}).get("note"), n, "payment note in replay verbatim")
        r = S.call("POST", "/requests", {"payer_handle": "ada", "amount": 1, "note": n}, as_="bob", key=k())
        t.eq((r.j or {}).get("note"), n, "request note echoed verbatim")
        rid = (r.j or {}).get("request_id")
        t.eq((S.req_by_id("ada", rid) or {}).get("note"), n, "request note in GET /requests verbatim")
        r = S.call("POST", "/splits", {"amount": 2, "participant_handles": ["bob"], "note": n}, as_="ada", key=k())
        t.eq((r.j or {}).get("note"), n, "split note echoed verbatim")
        t.eq(((r.j or {}).get("requests") or [{}])[0].get("note"), n, "split request note verbatim")
        r = S.call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1, "note": n}]},
                   as_="op", key=k())
        t.eq((((r.j or {}).get("payments")) or [{}])[0].get("note"), n, "settlement member note verbatim")
    for ch, label in (("x", "ASCII"), ("\u00e9", "2-byte"), ("\u65e5", "3-byte")):
        r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": ch * 200}, as_="ada", key=k())
        t.st(r, 201, f"payment note of 200 {label} characters")
        t.eq((r.j or {}).get("note"), ch * 200, f"200 {label} characters echoed")
        r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": ch * 201}, as_="ada", key=k())
        t.err(r, 422, "validation_failed", f"payment note of 201 {label} characters")
        r = S.call("POST", "/requests", {"payer_handle": "ada", "amount": 1, "note": ch * 200}, as_="bob", key=k())
        t.st(r, 201, f"request note of 200 {label} characters")
        r = S.call("POST", "/splits", {"amount": 1, "participant_handles": ["bob"], "note": ch * 200}, as_="ada", key=k())
        t.st(r, 201, f"split note of 200 {label} characters")
    r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": "\U0001F355" * 200}, as_="ada", key=k())
    t.ok(r.status == 201 and (r.j or {}).get("note") == "\U0001F355" * 200,
         f"payment note of 200 emoji characters (code points outside the BMP): expected 201 verbatim, got {r.status} {r.text[:120]}")
    r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": "\U0001F355" * 201}, as_="ada", key=k())
    t.err(r, 422, "validation_failed", "payment note of 201 emoji characters")
    r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": ""}, as_="ada", key=k())
    t.st(r, 201, "payment with empty note")


@check("D7-missing-fields", "§5", "D7", "A missing required field -> 422 validation_failed")
def c_missing(t, S):
    S.reset(basefx())
    cases = [("/payments", "ada", {"amount": 10}), ("/payments", "ada", {"to_handle": "bob"}),
             ("/payments", "ada", {}),
             ("/requests", "bob", {"amount": 10}), ("/requests", "bob", {"payer_handle": "ada"}),
             ("/splits", "ada", {"amount": 10}), ("/splits", "ada", {"participant_handles": ["bob"]}),
             ("/settlements", "op", {}),
             ("/settlements", "op", {"transfers": [{"to_handle": "bob", "amount": 1}]}),
             ("/settlements", "op", {"transfers": [{"from_handle": "ada", "amount": 1}]}),
             ("/settlements", "op", {"transfers": [{"from_handle": "ada", "to_handle": "bob"}]}),
             ("/auth/signup", None, {"password": "longenough", "display_name": "X"}),
             ("/auth/signup", None, {"email": "m1@example.com", "display_name": "X"}),
             ("/auth/login", None, {"password": PW}), ("/auth/login", None, {"email": "ada@example.com"})]
    for p, who, body in cases:
        r = S.call("POST", p, body, as_=who, key=k() if who else None)
        t.err(r, 422, "validation_failed", f"POST {p} {json.dumps(body)}")
    r = S.call("POST", "/auth/signup", {"email": "m2@example.com", "password": "longenough"})
    t.probe(is_err(r, 422, "validation_failed"), f"signup without display_name: got {r!r}")
    t.eq(sum(S.bals(HS).values()), TOTAL, "sum after missing-field requests")


@check("D8-query-digits", "§5 bullet 2", "D8", "Integer query parameters must be plain decimal digits: 1e1, 4.0, +4, -1, abc -> 422 on /requests and /activity")
def c_qdigits(t, S):
    S.reset(basefx())
    for ep in ("/activity", "/requests"):
        for par_ in ("limit", "offset"):
            for v in ("1e1", "1e9", "4.0", "%2B4", "-1", "abc", "0x10", "4%20", "%204", "1,0", "4."):
                r = S.call("GET", f"{ep}?{par_}={urllib.parse.quote(v, safe='%')}", as_="ada")
                t.err(r, 422, "validation_failed", f"GET {ep}?{par_}={v}")
            r = S.call("GET", f"{ep}?{par_}=+4", as_="ada")
            t.err(r, 422, "validation_failed", f"GET {ep}?{par_}=+4 (raw plus)")
            r = S.call("GET", f"{ep}?{par_}=", as_="ada")
            t.probe(is_err(r, 422, "validation_failed"), f"GET {ep}?{par_}= (empty value): got {r!r}")
        r = S.call("GET", f"{ep}?limit=4&offset=0", as_="ada")
        t.st(r, 200, f"GET {ep}?limit=4&offset=0")


def _pagefx():
    fx = basefx()
    fx["payments"] = [{"id": f"p_s{i}", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1,
                       "note": str(i), "visibility": "public"} for i in range(60)]
    fx["requests"] = [{"id": f"rq_s{i}", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1,
                       "note": str(i), "status": "pending"} for i in range(60)]
    return fx


@check("D9-limit-offset", "§5 shared ranges, §8 GET /requests, GET /activity", "D9,G12,G16", "limit 1..200 (0, 201 -> 422; 1, 200 ok), default 50; offset >= 0, default 0; has_more true iff items exist beyond the last returned")
def c_paging(t, S):
    S.reset(_pagefx())
    for ep, lk, idk in (("/activity", "payments", "payment_id"), ("/requests", "requests", "request_id")):
        for q in ("?limit=0", "?limit=201", "?limit=1000000", "?offset=-1"):
            t.err(S.call("GET", ep + q, as_="ada"), 422, "validation_failed", f"GET {ep}{q}")

        def page(q):
            r = S.call("GET", ep + q, as_="ada")
            if not t.ok(r.status == 200 and isinstance(r.j, dict) and isinstance(r.j.get(lk), list)
                        and isinstance(r.j.get("has_more"), bool), f"GET {ep}{q}: expected 200 {{{lk}, has_more}}, got {r!r}"):
                return [], None
            return r.j[lk], r.j["has_more"]
        for q, n, more in (("", 50, True), ("?limit=200", 60, False), ("?limit=1", 1, True), ("?limit=60", 60, False),
                           ("?limit=59", 59, True), ("?offset=0", 50, True), ("?offset=50", 10, False),
                           ("?offset=10", 50, False), ("?offset=9", 50, True),
                           ("?limit=1&offset=59", 1, False), ("?limit=1&offset=58", 1, True),
                           ("?offset=60", 0, False), ("?offset=100000", 0, False), ("?limit=200&offset=59", 1, False)):
            items, hm = page(q)
            t.eq(len(items), n, f"GET {ep}{q} item count")
            t.eq(hm, more, f"GET {ep}{q} has_more")
        a, _ = page("?limit=50&offset=0")
        b, _ = page("?limit=50&offset=50")
        t.probe(len(set(ids(a + b, idk))) == 60, f"{ep}: pages 0-49 and 50-59 do not cover 60 distinct items (order of same-second items unspecified)")


@check("D10-idem-key-header", "§5 shared ranges, §7", "D10", "Idempotency-Key absent or empty -> 400 missing_idempotency_key; 255 chars ok; 256 -> 422 validation_failed; on all five paths")
def c_keyhdr(t, S):
    for name, who, path, body, alt, bad in _idem_paths():
        S.reset(basefx())
        r = S.call("POST", path, body, as_=who)
        t.err(r, 400, "missing_idempotency_key", f"{name}: no Idempotency-Key")
        r = S.call("POST", path, body, as_=who, headers={"Idempotency-Key": ""})
        t.err(r, 400, "missing_idempotency_key", f"{name}: empty Idempotency-Key")
        r = S.call("POST", path, body, as_=who, key="K" * 256)
        t.err(r, 422, "validation_failed", f"{name}: 256-char Idempotency-Key")
        t.eq(S.bals(HS), {"ada": 10000, "bob": 2500, "cy": 0, "dan": 500, "op": 1000}, f"{name}: balances after rejected keys")
        r = S.call("POST", path, body, as_=who, key="K" * 255)
        t.st(r, 201, f"{name}: 255-char Idempotency-Key")
        r2 = S.call("POST", path, body, as_=who, key="K" * 255)
        t.st(r2, 200, f"{name}: replay with 255-char key")
        r = S.call("POST", path, alt if name != "pay" else body, as_=who, key="z") if name != "pay" else None
        if r is not None:
            t.st(r, 201, f"{name}: 1-char Idempotency-Key")


PROTECTED = [("GET", "/me"), ("POST", "/payments"), ("POST", "/requests"), ("POST", "/requests/rq_1/pay"),
             ("POST", "/requests/rq_1/decline"), ("POST", "/requests/rq_1/cancel"), ("GET", "/requests"),
             ("POST", "/splits"), ("GET", "/activity"), ("POST", "/settlements")]


@check("D11-unauthenticated", "§5, §6, §11", "D11,E9,F10,I1", "Missing, malformed or unknown bearer token -> 401 unauthenticated on every protected endpoint, before body and key checks; health, reset, export, signup, login need no token")
def c_401(t, S):
    S.reset(basefx())
    tok = S.token("ada")
    variants = [("no header", {}), ("unknown token", {"Authorization": "Bearer not-a-real-token"}),
                ("Basic scheme", {"Authorization": "Basic YWRhOmNvcnJlY3Q="}), ("scheme only", {"Authorization": "Bearer"}),
                ("empty token", {"Authorization": "Bearer "}), ("token without scheme", {"Authorization": tok}),
                ("wrong scheme + valid token", {"Authorization": "Token " + tok}),
                ("valid token + suffix", {"Authorization": "Bearer " + tok + "x"})]
    for m, p in PROTECTED:
        for label, h in variants:
            r = S.call(m, p, headers=h)
            t.err(r, 401, "unauthenticated", f"{m} {p} [{label}]")
        if m == "POST":
            r = S.call(m, p, raw="{not json")
            t.err(r, 401, "unauthenticated", f"{m} {p} no token + unparseable body + no key")
            r = S.call(m, p, {"amount": "bad"}, headers={"Authorization": "Bearer nope"}, key=k())
            t.err(r, 401, "unauthenticated", f"{m} {p} unknown token + invalid body")
    t.eq(S.bals(HS), {"ada": 10000, "bob": 2500, "cy": 0, "dan": 500, "op": 1000}, "balances after unauthenticated calls")
    t.eq((S.req_by_id("ada", "rq_1") or {}).get("status"), "pending", "rq_1 untouched by unauthenticated calls")
    t.st(S.call("GET", "/health"), 200, "health without token")
    t.st(S.call("GET", "/_test/export"), 200, "export without token")
    t.st(S.call("POST", "/auth/login", {"email": "ada@example.com", "password": PW}), 200, "login without token")


# --------------------------------------------------------------------------- E
@check("E1-signup", "§6, §4 users", "E1,B1", "Signup -> 201 {user_id, display_name, token}; balance 0; can be paid and asked for money immediately")
def c_signup(t, S):
    S.reset(basefx())
    r = S.call("POST", "/auth/signup", {"email": "nina@example.com", "password": "longenough", "display_name": "Nina N"})
    t.st(r, 201, "signup")
    j = r.j or {}
    idok(t, j.get("user_id"), "signup user_id")
    t.eq(j.get("display_name"), "Nina N", "signup display_name")
    t.ok(isinstance(j.get("token"), str) and j.get("token"), "signup token")
    tok = j.get("token") or "x"
    r = S.call("GET", "/me", token=tok)
    t.st(r, 200, "/me with signup token")
    me = r.j or {}
    t.eq(me.get("user_id"), j.get("user_id"), "/me user_id")
    t.eq(me.get("handle"), "nina", "derived handle")
    t.eq(me.get("balance"), 0, "new user balance")
    t.eq(me.get("currency"), "EUR", "new user currency")
    t.eq(me.get("minor_units"), 2, "new user minor_units")
    t.eq(me.get("display_name"), "Nina N", "/me display_name")
    r = S.call("POST", "/payments", {"to_handle": "nina", "amount": 100}, as_="ada", key=k())
    t.st(r, 201, "pay new user")
    t.eq((r.j or {}).get("to_user_id"), j.get("user_id"), "payment to_user_id is the new user")
    r = S.call("POST", "/requests", {"payer_handle": "nina", "amount": 40}, as_="bob", key=k())
    t.st(r, 201, "request money from new user")
    rid = (r.j or {}).get("request_id")
    r = S.call("POST", f"/requests/{rid}/pay", {}, token=tok, key=k())
    t.st(r, 201, "new user pays the request")
    r = S.call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, token=tok, key=k())
    t.st(r, 201, "new user requests money")
    r = S.call("GET", "/me", token=tok)
    t.eq((r.j or {}).get("balance"), 60, "new user balance after +100 -40")
    t.eq(sum(S.bals(HS).values()) + 60, TOTAL, "sum of balances incl. new user")
    r = S.call("POST", "/auth/login", {"email": "nina@example.com", "password": "longenough"})
    t.st(r, 200, "new user login")
    t.eq((r.j or {}).get("user_id"), j.get("user_id"), "login user_id")
    r = S.call("POST", "/payments", {"to_handle": "ada", "amount": 61}, token=tok, key=k())
    t.err(r, 409, "insufficient_funds", "new user overspends")


@check("E2-handle-derivation", "§4 users and handles", "E2,E8", "Handle derived from the email: local part, lowercased, characters outside [a-z0-9_] -> _, truncated to 20")
def c_handle(t, S):
    S.reset(basefx())
    cases = [("A.b-C+tag@x.com", "a_b_c_tag"), ("abcdefghijklmnopqrstuvwxy@x.com", "abcdefghijklmnopqrst"),
             ("UPPER_case9@x.com", "upper_case9"), ("exactly_twenty_chars@x.com", "exactly_twenty_chars"),
             ("x@x.com", "x"), ("o'neil@x.com", "o_neil"), ("Mixed.Case.And.Very.Long.Local@x.com", "mixed_case_and_very_")]
    for email, h in cases:
        r = S.call("POST", "/auth/signup", {"email": email, "password": "longenough", "display_name": "D"})
        if not t.st(r, 201, f"signup {email}"):
            continue
        me = S.call("GET", "/me", token=(r.j or {}).get("token") or "x").j or {}
        t.eq(me.get("handle"), h, f"handle derived from {email}")
        r = S.call("POST", "/payments", {"to_handle": h, "amount": 1}, as_="ada", key=k())
        t.st(r, 201, f"pay derived handle {h}")
    r = S.call("POST", "/auth/signup", {"email": "jos\u00e9@x.com", "password": "longenough", "display_name": "D"})
    if r.status == 201:
        me = S.call("GET", "/me", token=(r.j or {}).get("token") or "x").j or {}
        t.eq(me.get("handle"), "jos_", "handle derived from jos\u00e9@x.com")
    else:
        t.probe(False, f"signup with non-ASCII local part jos\u00e9@x.com: got {r!r}")
    r = S.call("POST", "/auth/signup", {"email": "withfield@x.com", "password": "longenough", "display_name": "D", "handle": "chosen"})
    t.st(r, 201, "signup with a handle field in the body")
    me = S.call("GET", "/me", token=(r.j or {}).get("token") or "x").j or {}
    t.eq(me.get("handle"), "withfield", "handle field in signup body is ignored")


@check("E3-signup-conflicts", "§6 table, §4", "E3", "Email already registered -> 409 email_taken; derived handle taken (seeded or signed-up, incl. by truncation) -> 409 handle_taken and no account is created")
def c_conflict(t, S):
    S.reset(basefx())
    r = S.call("POST", "/auth/signup", {"email": "ada@example.com", "password": "longenough", "display_name": "X"})
    t.err(r, 409, "email_taken", "signup with a seeded email")
    r = S.call("POST", "/auth/login", {"email": "ada@example.com", "password": "longenough"})
    t.err(r, 401, "unauthenticated", "seeded account password not replaced by rejected signup")
    r = S.call("POST", "/auth/signup", {"email": "ada@other.org", "password": "longenough", "display_name": "X"})
    t.err(r, 409, "handle_taken", "derived handle equals a seeded handle")
    r = S.call("POST", "/auth/login", {"email": "ada@other.org", "password": "longenough"})
    t.err(r, 401, "unauthenticated", "no account created after handle_taken")
    r = S.call("POST", "/auth/signup", {"email": "p.q@example.com", "password": "longenough", "display_name": "X"})
    t.st(r, 201, "signup p.q")
    r = S.call("POST", "/auth/signup", {"email": "p.q@example.com", "password": "longenough", "display_name": "X"})
    t.err(r, 409, "email_taken", "signup with a signed-up email")
    r = S.call("POST", "/auth/signup", {"email": "p-q@example.com", "password": "longenough", "display_name": "X"})
    t.err(r, 409, "handle_taken", "p-q collides with p.q (both p_q)")
    r = S.call("POST", "/auth/signup", {"email": "P_Q@elsewhere.com", "password": "longenough", "display_name": "X"})
    t.err(r, 409, "handle_taken", "P_Q collides with p_q")
    r = S.call("POST", "/auth/signup", {"email": "abcdefghijklmnopqrst111@x.com", "password": "longenough", "display_name": "X"})
    t.st(r, 201, "signup long local part")
    r = S.call("POST", "/auth/signup", {"email": "abcdefghijklmnopqrst222@x.com", "password": "longenough", "display_name": "X"})
    t.err(r, 409, "handle_taken", "collision after truncation to 20")
    r = S.call("POST", "/auth/login", {"email": "abcdefghijklmnopqrst222@x.com", "password": "longenough"})
    t.err(r, 401, "unauthenticated", "no account created after truncation collision")
    rs = par([lambda: S.call("POST", "/auth/signup", {"email": "racer@example.com", "password": "longenough", "display_name": "R"})
              for _ in range(8)])
    t.eq(sum(r.status == 201 for r in rs), 1, f"8 concurrent signups of one email: 201 count (statuses {[r.status for r in rs]})")
    t.ok(all(r.status == 201 or is_err(r, 409, "email_taken") or is_err(r, 409, "handle_taken") for r in rs),
         f"8 concurrent signups: others must be 409: {[repr(r)[:80] for r in rs]}")


@check("E4-signup-validation", "§6 table", "E4", "Password shorter than 8 characters -> 422 (7 fails, 8 ok); email not of the form local@domain -> 422")
def c_signupval(t, S):
    S.reset(basefx())
    r = S.call("POST", "/auth/signup", {"email": "pw7@example.com", "password": "1234567", "display_name": "X"})
    t.err(r, 422, "validation_failed", "7-char password")
    r = S.call("POST", "/auth/login", {"email": "pw7@example.com", "password": "1234567"})
    t.err(r, 401, "unauthenticated", "no account after rejected password")
    r = S.call("POST", "/auth/signup", {"email": "pw0@example.com", "password": "", "display_name": "X"})
    t.err(r, 422, "validation_failed", "empty password")
    r = S.call("POST", "/auth/signup", {"email": "pw8@example.com", "password": "12345678", "display_name": "X"})
    t.st(r, 201, "8-char password")
    r = S.call("POST", "/auth/login", {"email": "pw8@example.com", "password": "12345678"})
    t.st(r, 200, "login with 8-char password")
    for e in ("nodomain", "@example.com", "local@", "", "plain.example.com", "@"):
        r = S.call("POST", "/auth/signup", {"email": e, "password": "longenough", "display_name": "X"})
        t.err(r, 422, "validation_failed", f"signup email {e!r}")


@check("E5-login", "§6", "E5,E6", "Login -> 200 {user_id, display_name, token}; wrong password or unknown email -> 401; tokens do not expire on new login; several tokens valid at once")
def c_login(t, S):
    S.reset(basefx())
    t.err(S.call("POST", "/auth/login", {"email": "ada@example.com", "password": "wrong horse"}), 401, "unauthenticated", "wrong password")
    t.err(S.call("POST", "/auth/login", {"email": "ada@example.com", "password": ""}), 401, "unauthenticated", "empty password")
    t.err(S.call("POST", "/auth/login", {"email": "nobody@example.com", "password": PW}), 401, "unauthenticated", "unknown email")
    toks = [S.login("ada") for _ in range(3)]
    for i, tk in enumerate(toks):
        r = S.call("GET", "/me", token=tk)
        t.st(r, 200, f"token {i} of 3 valid after later logins")
        t.eq((r.j or {}).get("user_id"), "u_ada", f"token {i} identifies ada")
    rs = par([lambda tk=tk: S.call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=tk, key=k()) for tk in toks])
    t.ok(all(r.status == 201 for r in rs), f"concurrent sessions of one account: {[r.status for r in rs]}")
    t.eq(S.bal("ada"), 9997, "ada after 3 concurrent session payments")
    r = S.call("POST", "/auth/signup", {"email": "multi@example.com", "password": "longenough", "display_name": "M"})
    t1 = (r.j or {}).get("token") or "x"
    t2 = S.login("multi", pw="longenough")
    t.st(S.call("GET", "/me", token=t1), 200, "signup token still valid after login")
    t.st(S.call("GET", "/me", token=t2), 200, "login token valid")


# --------------------------------------------------------------------------- F
def _idem_paths():
    return [("payments", "ada", "/payments", {"to_handle": "bob", "amount": 100, "note": "n"},
             {"to_handle": "bob", "amount": 101, "note": "n"}, {"to_handle": "bob", "amount": "x"}),
            ("requests", "bob", "/requests", {"payer_handle": "ada", "amount": 50},
             {"payer_handle": "ada", "amount": 51}, {"payer_handle": "ada", "amount": "x"}),
            ("pay", "ada", "/requests/rq_1/pay", {}, {"visibility": "private"}, {"visibility": "bogus"}),
            ("splits", "ada", "/splits", {"amount": 300, "participant_handles": ["ada", "bob", "cy"]},
             {"amount": 301, "participant_handles": ["ada", "bob", "cy"]}, {"amount": "x", "participant_handles": []}),
            ("settlements", "op", "/settlements",
             {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}]},
             {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 101}]}, {"transfers": "x"})]


def _state(S):
    return (S.bals(HS), sorted(ids(S.reqs("bob"), "request_id")), sorted(ids(S.acts("bob"), "payment_id")))


@check("F1-replay", "§7 table", "F1,F3,F9", "On each of the five paths: first use 201; replay 200 with the identical JSON body and no further effect; same key with a different body 409 idempotency_key_reuse, also when the new body is invalid")
def c_replay(t, S):
    for name, who, path, body, alt, bad in _idem_paths():
        S.reset(basefx())
        key = k()
        r1 = S.call("POST", path, body, as_=who, key=key)
        t.st(r1, 201, f"{name}: first use")
        st1 = _state(S)
        for i in range(2):
            r2 = S.call("POST", path, body, as_=who, key=key)
            t.st(r2, 200, f"{name}: replay {i + 1}")
            t.ok(r2.j == r1.j, f"{name}: replay body differs: {r2.text[:200]} vs {r1.text[:200]}")
        r2 = S.call("POST", path, body, token=S.login(who), key=key)
        t.st(r2, 200, f"{name}: replay through another session of the same user")
        t.ok(r2.j == r1.j, f"{name}: replay body via other session differs")
        t.err(S.call("POST", path, alt, as_=who, key=key), 409, "idempotency_key_reuse", f"{name}: same key, different body")
        t.err(S.call("POST", path, bad, as_=who, key=key), 409, "idempotency_key_reuse", f"{name}: same key, now-invalid body")
        extra = dict(body, zzz_unknown=1)
        t.err(S.call("POST", path, extra, as_=who, key=key), 409, "idempotency_key_reuse",
              f"{name}: same key, body differing only by an unknown field (a different JSON value)")
        t.ok(_state(S) == st1, f"{name}: state changed by replays / rejected reuse")


@check("F2-same-body", "§7", "F2", "Same body means the same JSON value: key order and whitespace do not matter; {} and {\"visibility\":\"public\"} differ")
def c_samebody(t, S):
    S.reset(basefx())
    key = k()
    r1 = S.call("POST", "/payments", raw='{"to_handle":"bob","amount":100,"note":"n","visibility":"private"}', as_="ada", key=key)
    t.st(r1, 201, "first use")
    r2 = S.call("POST", "/payments", raw='  {\n "visibility" : "private",\t"note":"n",\n\n"amount" : 100, "to_handle" :"bob" }  ',
                as_="ada", key=key)
    t.st(r2, 200, "replay with reordered keys and whitespace")
    t.ok(r2.j == r1.j, "replay body differs")
    t.eq(S.bal("ada"), 9900, "ada balance after replay")
    key = k()
    r1 = S.call("POST", "/settlements", raw='{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":5}]}', as_="op", key=key)
    t.st(r1, 201, "settlement first use")
    r2 = S.call("POST", "/settlements", raw='{ "transfers" : [ { "amount":5, "to_handle":"bob", "from_handle":"ada" } ] }', as_="op", key=key)
    t.st(r2, 200, "settlement replay with reordered keys")
    key = k()
    r1 = S.call("POST", "/requests/rq_1/pay", {}, as_="ada", key=key)
    t.st(r1, 201, "pay with {}")
    t.err(S.call("POST", "/requests/rq_1/pay", {"visibility": "public"}, as_="ada", key=key), 409, "idempotency_key_reuse",
          "pay replay with {\"visibility\":\"public\"} after {}")
    key = k()
    r1 = S.call("POST", "/requests/rq_2/pay", {"visibility": "public"}, as_="ada", key=key)
    t.st(r1, 201, "pay with explicit public")
    t.err(S.call("POST", "/requests/rq_2/pay", {}, as_="ada", key=key), 409, "idempotency_key_reuse",
          "pay replay with {} after {\"visibility\":\"public\"}")
    t.st(S.call("POST", "/requests/rq_2/pay", raw=' { "visibility" : "public" } ', as_="ada", key=key), 200, "pay replay, whitespace only differs")


@check("F4-key-scope", "§7", "F4,F5", "Key is scoped to the authenticated user; the same key and body on a different path is a new request and succeeds")
def c_scope_key(t, S):
    S.reset(basefx())
    key = k()
    body = {"to_handle": "cy", "amount": 10, "payer_handle": "cy", "participant_handles": ["cy"]}
    ra = S.call("POST", "/payments", body, as_="ada", key=key)
    rb = S.call("POST", "/payments", body, as_="bob", key=key)
    t.st(ra, 201, "ada first use")
    t.st(rb, 201, "bob same key+body is his own first use")
    t.ok((ra.j or {}).get("payment_id") != (rb.j or {}).get("payment_id"), "two users with the same key got the same payment")
    t.eq((rb.j or {}).get("from_handle"), "bob", "bob's payment is from bob")
    t.eq(S.bal("cy"), 20, "cy received both payments")
    rd = S.call("POST", "/payments", {"to_handle": "cy", "amount": 11}, as_="dan", key=key)
    t.st(rd, 201, "third user, same key, different body")
    r = S.call("POST", "/requests", body, as_="ada", key=key)
    t.st(r, 201, "same key + same body on /requests")
    r = S.call("POST", "/splits", body, as_="ada", key=key)
    t.st(r, 201, "same key + same body on /splits")
    key2 = k()
    r1 = S.call("POST", "/requests/rq_1/pay", {}, as_="ada", key=key2)
    r2 = S.call("POST", "/requests/rq_2/pay", {}, as_="ada", key=key2)
    t.st(r1, 201, "fresh key on /requests/rq_1/pay")
    t.st(r2, 201, "same key + same body on /requests/rq_2/pay")
    t.ok((r1.j or {}).get("request_id") == "rq_1" and (r2.j or {}).get("request_id") == "rq_2", "pay responses name their own request")
    t.st(S.call("POST", "/payments", body, as_="ada", key=key), 200, "original /payments replay still 200")
    t.eq(S.bal("ada"), 10000 - 10 - 1200 - 300, "ada balance after scoped-key sequence")


@check("F6-failed-key-reusable", "§7 table", "F6", "A key whose original request failed with 4xx is treated as a first use afterwards, with the same or a different body")
def c_failedkey(t, S):
    S.reset(basefx())
    key = k()
    body = {"to_handle": "bob", "amount": 100}
    t.err(S.call("POST", "/payments", body, as_="cy", key=key), 409, "insufficient_funds", "cy pays with balance 0")
    t.err(S.call("POST", "/payments", body, as_="cy", key=key), 409, "insufficient_funds", "same again (still a first use)")
    t.st(S.call("POST", "/payments", {"to_handle": "cy", "amount": 150}, as_="ada", key=k()), 201, "fund cy")
    r = S.call("POST", "/payments", body, as_="cy", key=key)
    t.st(r, 201, "same key + same body after the 409 now succeeds as a first use")
    t.st(S.call("POST", "/payments", body, as_="cy", key=key), 200, "and is replayable")
    t.eq(S.bal("cy"), 50, "cy balance")
    for label, bad, st, code in (("422", {"to_handle": "bob", "amount": 0}, 422, "validation_failed"),
                                 ("404", {"to_handle": "nobody_here", "amount": 5}, 404, "not_found"),
                                 ("self", {"to_handle": "ada", "amount": 5}, 422, "self_payment")):
        key = k()
        t.err(S.call("POST", "/payments", bad, as_="ada", key=key), st, code, f"failing payment ({label})")
        t.st(S.call("POST", "/payments", {"to_handle": "bob", "amount": 7}, as_="ada", key=key), 201,
             f"key reused with a different body after {label} failure")
    key = k()
    t.err(S.call("POST", "/requests/rq_1/pay", {}, as_="bob", key=key), 403, "forbidden", "pay by non-payer")
    t.st(S.call("POST", "/requests", {"payer_handle": "ada", "amount": 1}, as_="bob", key=key), 201, "bob's key free on another path")
    key = k()
    t.err(S.call("POST", "/requests", {"payer_handle": "bob", "amount": 1}, as_="bob", key=key), 422, "self_request", "self request")
    t.st(S.call("POST", "/requests", {"payer_handle": "ada", "amount": 1}, as_="bob", key=key), 201, "key reused after self_request")
    key = k()
    t.err(S.call("POST", "/splits", {"amount": 5, "participant_handles": []}, as_="ada", key=key), 422, "validation_failed", "empty split")
    t.st(S.call("POST", "/splits", {"amount": 5, "participant_handles": ["bob"]}, as_="ada", key=key), 201, "key reused after failed split")


@check("F7-concurrent-identical", "§7", "F7,B1", "20 concurrent identical requests with an unused key on each of the five paths: exactly one 201, the others 200 with the same body, one effect")
def c_concidem(t, S):
    for name, who, path, body, alt, bad in _idem_paths():
        S.reset(basefx())
        S.token(who)
        before = _state(S)
        key = k()
        rs = par([lambda: S.call("POST", path, body, as_=who, key=key) for _ in range(20)])
        n201 = sum(r.status == 201 for r in rs)
        n200 = sum(r.status == 200 for r in rs)
        t.ok(n201 == 1 and n200 == 19, f"{name}: expected 1x201 + 19x200, got {sorted(r.status for r in rs)} e.g. {[repr(r)[:120] for r in rs if r.status not in (200, 201)][:2]}")
        first = next((r for r in rs if r.status == 201), None)
        if first is not None:
            t.ok(all(r.j == first.j for r in rs if r.status == 200), f"{name}: replay bodies differ from the 201 body")
        after = _state(S)
        t.eq(sum(after[0].values()), TOTAL, f"{name}: sum of balances")
        if name in ("payments", "settlements"):
            t.eq(after[0]["ada"], 9900, f"{name}: ada balance (one effect)")
            t.eq(len(after[2]) - len(before[2]), 1, f"{name}: new payments in bob's feed")
        elif name == "pay":
            t.eq(after[0]["ada"], 8800, f"{name}: ada balance (one effect)")
            t.eq(len(after[2]) - len(before[2]), 1, f"{name}: new payments in bob's feed")
        elif name == "requests":
            t.eq(len(after[1]) - len(before[1]), 1, f"{name}: new requests visible to bob")
        else:
            t.eq(len(after[1]) - len(before[1]), 1, f"{name}: new requests visible to bob (one split, bob's share)")


@check("F8-replay-after-change", "§7", "F8,G9", "A successful replay returns the original response even after the resource changed or was cancelled, or the balance no longer covers it; no further state change")
def c_replaychange(t, S):
    S.reset(basefx())
    kq = k()
    body = {"payer_handle": "ada", "amount": 77}
    r1 = S.call("POST", "/requests", body, as_="bob", key=kq)
    t.st(r1, 201, "create request")
    rid = (r1.j or {}).get("request_id")
    t.st(S.call("POST", f"/requests/{rid}/cancel", as_="bob"), 200, "cancel it")
    r2 = S.call("POST", "/requests", body, as_="bob", key=kq)
    t.st(r2, 200, "replay create after cancel")
    t.ok(r2.j == r1.j, "replay after cancel must be the original (pending) response")
    t.eq((S.req_by_id("bob", rid) or {}).get("status"), "cancelled", "request stays cancelled after replay")
    kp = k()
    p1 = S.call("POST", "/requests/rq_1/pay", {"visibility": "private"}, as_="ada", key=kp)
    t.st(p1, 201, "pay rq_1")
    p2 = S.call("POST", "/requests/rq_1/pay", {"visibility": "private"}, as_="ada", key=kp)
    t.st(p2, 200, "replay pay when request is already paid (not 409 request_not_pending)")
    t.ok(p2.j == p1.j, "pay replay body differs")
    t.err(S.call("POST", "/requests/rq_1/pay", {"visibility": "private"}, as_="ada", key=k()), 409, "request_not_pending",
          "pay paid request with a new key")
    t.eq(S.bal("ada"), 8800, "ada balance after pay + replay")
    kd = k()
    d1 = S.call("POST", "/payments", {"to_handle": "bob", "amount": 500}, as_="dan", key=kd)
    t.st(d1, 201, "dan pays all 500")
    d2 = S.call("POST", "/payments", {"to_handle": "bob", "amount": 500}, as_="dan", key=kd)
    t.st(d2, 200, "replay although dan's balance is now 0")
    t.ok(d2.j == d1.j, "payment replay body differs")
    t.eq(S.bal("dan"), 0, "dan balance after replay")
    ks = k()
    sb = {"amount": 90, "participant_handles": ["bob", "cy"], "note": "s"}
    s1 = S.call("POST", "/splits", sb, as_="ada", key=ks)
    t.st(s1, 201, "split")
    srid = (((s1.j or {}).get("requests")) or [{}])[0].get("request_id")
    t.st(S.call("POST", f"/requests/{srid}/decline", as_="bob"), 200, "bob declines his split request")
    s2 = S.call("POST", "/splits", sb, as_="ada", key=ks)
    t.st(s2, 200, "split replay after a request was declined")
    t.ok(s2.j == s1.j, "split replay body differs")
    t.eq(sum(S.bals(HS).values()), TOTAL, "sum of balances")


@check("F10-order", "§7 last paragraph, §5", "F10", "Order of checks: 401 first; a claimed key is resolved before field validation and current-resource checks")
def c_order(t, S):
    S.reset(basefx())
    r = S.call("POST", "/payments", raw="{bad json", as_="ada")
    t.ok(is_err(r, 400, "malformed_request") or is_err(r, 400, "missing_idempotency_key"),
         f"unparseable body + no key: expected a 400, got {r!r}")
    r = S.call("POST", "/payments", {"to_handle": "bob", "amount": "x"}, as_="ada")
    t.err_any(r, [(400, "missing_idempotency_key"), (422, "validation_failed")], "invalid field + no key")
    r = S.call("POST", "/payments", {"to_handle": "nobody_here", "amount": 5}, as_="ada")
    t.err_any(r, [(400, "missing_idempotency_key"), (404, "not_found")], "unknown handle + no key")
    key = k()
    t.st(S.call("POST", "/requests/rq_1/pay", {}, as_="ada", key=key), 201, "pay rq_1")
    t.err(S.call("POST", "/requests/rq_1/pay", {"visibility": "private"}, as_="ada", key=key), 409, "idempotency_key_reuse",
          "claimed key + different body on a paid request (not request_not_pending)")
    t.err(S.call("POST", "/requests/rq_1/pay", {"visibility": 7}, as_="ada", key=key), 409, "idempotency_key_reuse",
          "claimed key + invalid visibility")
    key = k()
    t.st(S.call("POST", "/payments", {"to_handle": "bob", "amount": 500}, as_="dan", key=key), 201, "dan pays 500")
    t.err(S.call("POST", "/payments", {"to_handle": "bob", "amount": 501}, as_="dan", key=key), 409, "idempotency_key_reuse",
          "claimed key + body that would be insufficient_funds")
    t.err(S.call("POST", "/payments", {"to_handle": "dan", "amount": 500}, as_="dan", key=key), 409, "idempotency_key_reuse",
          "claimed key + body that would be self_payment")
    t.err(S.call("POST", "/payments", {"to_handle": "nobody_here", "amount": 500}, as_="dan", key=key), 409, "idempotency_key_reuse",
          "claimed key + body that would be not_found")
    t.err(S.call("POST", "/payments", {}, as_="dan", key=key), 409, "idempotency_key_reuse", "claimed key + empty object body")
    r = S.call("POST", "/payments", raw="{bad json", as_="dan", key=key)
    t.err(r, 400, "malformed_request", "claimed key + unparseable body (body has not parsed)")


# --------------------------------------------------------------------------- G
@check("G2-payment", "§8 POST /payments", "G2,G3,G4", "Payment 201 body, defaults, atomic debit+credit; errors insufficient_funds (balance == amount ok), self_payment, not_found; a failed payment leaves no trace")
def c_payment(t, S):
    S.reset(basefx())
    r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 1500, "note": "dinner", "visibility": "public"}, as_="ada", key=k())
    t.st(r, 201, "payment")
    pay_shape(t, r.j, "payment", from_user_id="u_ada", from_handle="ada", to_user_id="u_bob", to_handle="bob",
              amount=1500, currency="EUR", note="dinner", visibility="public", request_id=None, settlement_id=None)
    t.eq(S.bal("ada"), 8500, "sender debited")
    t.eq(S.bal("bob"), 4000, "receiver credited")
    r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 1}, as_="ada", key=k())
    pay_shape(t, r.j, "payment with defaults", note="", visibility="public", amount=1)
    r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 1, "visibility": "private"}, as_="ada", key=k())
    pay_shape(t, r.j, "private payment", visibility="private")
    before = (S.bals(HS), [len(S.acts(h)) for h in HS])
    t.err(S.call("POST", "/payments", {"to_handle": "bob", "amount": 501}, as_="dan", key=k()), 409, "insufficient_funds", "balance 500, amount 501")
    t.err(S.call("POST", "/payments", {"to_handle": "bob", "amount": 1}, as_="cy", key=k()), 409, "insufficient_funds", "balance 0, amount 1")
    t.err(S.call("POST", "/payments", {"to_handle": "dan", "amount": 10}, as_="dan", key=k()), 422, "self_payment", "own handle")
    t.err(S.call("POST", "/payments", {"to_handle": "nobody_here", "amount": 10}, as_="dan", key=k()), 404, "not_found", "unknown handle")
    t.err(S.call("POST", "/payments", {"to_handle": "u_bob", "amount": 10}, as_="dan", key=k()), 404, "not_found", "user id used as handle")
    t.ok(before == (S.bals(HS), [len(S.acts(h)) for h in HS]), "failed payments left a trace in balances or feeds")
    r = S.call("POST", "/payments", {"to_handle": "cy", "amount": 500}, as_="dan", key=k())
    t.st(r, 201, "balance 500, amount 500")
    t.eq(S.bal("dan"), 0, "dan balance 0 after paying everything")
    t.eq(S.bal("cy"), 500, "cy credited")
    t.eq(sum(S.bals(HS).values()), TOTAL, "sum of balances")


@check("G5-request", "§8 POST /requests, §4 requests", "G5,G6", "Request 201 body; caller is requester; payer balance not checked; errors self_request, not_found")
def c_request(t, S):
    S.reset(basefx())
    r = S.call("POST", "/requests", {"payer_handle": "ada", "amount": 1200, "note": "taxi"}, as_="bob", key=k())
    t.st(r, 201, "request")
    req_shape(t, r.j, "request", requester_id="u_bob", requester_handle="bob", payer_id="u_ada", payer_handle="ada",
              amount=1200, currency="EUR", note="taxi", status="pending", payment_id=None)
    r = S.call("POST", "/requests", {"payer_handle": "cy", "amount": 999999}, as_="bob", key=k())
    t.st(r, 201, "request exceeding the payer's balance")
    req_shape(t, r.j, "big request", status="pending", note="", amount=999999)
    t.err(S.call("POST", "/requests", {"payer_handle": "bob", "amount": 5}, as_="bob", key=k()), 422, "self_request", "own handle")
    t.err(S.call("POST", "/requests", {"payer_handle": "nobody_here", "amount": 5}, as_="bob", key=k()), 404, "not_found", "unknown handle")
    t.eq(S.bals(HS), {"ada": 10000, "bob": 2500, "cy": 0, "dan": 500, "op": 1000}, "requests move no money")
    t.ok(all(p.get("request_id") is None for p in S.acts("bob")) and len(S.acts("bob")) == 2, "requests created feed items")


@check("G7-pay", "§8 pay, §4 requests", "G7,G8,G17", "Pay: payer only; 201 payment with request_id; request becomes paid with payment_id; visibility is the payer's; errors 404, 403, 409 request_not_pending, 409 insufficient_funds (changes nothing, payable later)")
def c_pay(t, S):
    S.reset(basefx())
    r = S.call("POST", "/requests/rq_1/pay", {"visibility": "private"}, as_="ada", key=k())
    t.st(r, 201, "pay rq_1")
    pay_shape(t, r.j, "pay", from_user_id="u_ada", from_handle="ada", to_user_id="u_bob", to_handle="bob", amount=1200,
              currency="EUR", note="taxi", visibility="private", request_id="rq_1", settlement_id=None)
    pid = (r.j or {}).get("payment_id")
    for h in ("ada", "bob"):
        q = S.req_by_id(h, "rq_1") or {}
        t.eq(q.get("status"), "paid", f"{h}: rq_1 status")
        t.eq(q.get("payment_id"), pid, f"{h}: rq_1 payment_id")
        a = [p for p in S.acts(h) if p.get("payment_id") == pid]
        t.ok(len(a) == 1 and a[0].get("visibility") == "private" and a[0].get("request_id") == "rq_1",
             f"{h}: private request payment in own feed with one visibility value: {a}")
    for h in ("cy", "dan", "op"):
        t.ok(pid not in ids(S.acts(h), "payment_id"), f"{h}: private request payment leaked to third party")
    t.eq(S.bal("ada"), 8800, "payer debited")
    t.eq(S.bal("bob"), 3700, "requester credited")
    r = S.call("POST", "/requests/rq_2/pay", as_="ada", key=k(), raw="{}")
    pay_shape(t, r.j, "pay default visibility", visibility="public", request_id="rq_2", amount=300, note="tea")
    t.ok((r.j or {}).get("payment_id") in ids(S.acts("cy"), "payment_id"), "public request payment visible to third party")
    t.err(S.call("POST", "/requests/rq_2/pay", {}, as_="ada", key=k()), 409, "request_not_pending", "pay a paid request")
    t.err(S.call("POST", "/requests/rq_nope/pay", {}, as_="ada", key=k()), 404, "not_found", "unknown request")
    S.reset(basefx())
    t.err(S.call("POST", "/requests/rq_1/pay", {}, as_="bob", key=k()), 403, "forbidden", "requester tries to pay")
    t.err(S.call("POST", "/requests/rq_1/pay", {}, as_="cy", key=k()), 403, "forbidden", "third party tries to pay")
    t.eq((S.req_by_id("ada", "rq_1") or {}).get("status"), "pending", "rq_1 still pending")
    r = S.call("POST", "/requests", {"payer_handle": "cy", "amount": 400, "note": "later"}, as_="dan", key=k())
    rid = (r.j or {}).get("request_id")
    key = k()
    t.err(S.call("POST", f"/requests/{rid}/pay", {}, as_="cy", key=key), 409, "insufficient_funds", "pay while short")
    t.eq((S.req_by_id("cy", rid) or {}).get("status"), "pending", "request stays pending after insufficient_funds")
    t.eq((S.req_by_id("cy", rid) or {}).get("payment_id"), None, "no payment_id after insufficient_funds")
    t.eq(S.bals(["cy", "dan"]), {"cy": 0, "dan": 500}, "nothing moved")
    t.st(S.call("POST", "/payments", {"to_handle": "cy", "amount": 399}, as_="ada", key=k()), 201, "fund cy with 399")
    t.err(S.call("POST", f"/requests/{rid}/pay", {}, as_="cy", key=k()), 409, "insufficient_funds", "pay with 399 of 400")
    t.st(S.call("POST", "/payments", {"to_handle": "cy", "amount": 1}, as_="ada", key=k()), 201, "fund cy with 1 more")
    r = S.call("POST", f"/requests/{rid}/pay", {}, as_="cy", key=key)
    t.st(r, 201, "same request, same key, payable once money arrived (balance == amount)")
    t.eq(S.bals(["cy", "dan"]), {"cy": 0, "dan": 900}, "money moved once")
    t.eq(sum(S.bals(HS).values()), TOTAL, "sum of balances")


@check("G10-decline-cancel", "§8 decline, cancel; §4 requests", "G10,G11", "Decline: payer only, 200 declined, repeat 200, paid/cancelled 409, non-payer 403, unknown 404. Cancel: requester only, 200 cancelled, repeat 200, paid/declined 409, non-requester 403, unknown 404. No idempotency key needed; no money moves")
def c_declcanc(t, S):
    S.reset(basefx())
    t.err(S.call("POST", "/requests/rq_1/decline", as_="bob"), 403, "forbidden", "requester declines")
    t.err(S.call("POST", "/requests/rq_1/decline", as_="cy"), 403, "forbidden", "third party declines")
    t.err(S.call("POST", "/requests/rq_1/decline", as_="op"), 403, "forbidden", "operator declines")
    t.err(S.call("POST", "/requests/rq_1/cancel", as_="ada"), 403, "forbidden", "payer cancels")
    t.err(S.call("POST", "/requests/rq_1/cancel", as_="cy"), 403, "forbidden", "third party cancels")
    t.err(S.call("POST", "/requests/rq_nope/decline", as_="ada"), 404, "not_found", "decline unknown")
    t.err(S.call("POST", "/requests/rq_nope/cancel", as_="ada"), 404, "not_found", "cancel unknown")
    t.eq((S.req_by_id("ada", "rq_1") or {}).get("status"), "pending", "rq_1 still pending after forbidden calls")
    for i in range(2):
        r = S.call("POST", "/requests/rq_1/decline", as_="ada")
        t.st(r, 200, f"decline #{i + 1}")
        req_shape(t, r.j, f"decline #{i + 1}", request_id="rq_1", status="declined", payment_id=None, amount=1200,
                  requester_handle="bob", payer_handle="ada", note="taxi")
    t.err(S.call("POST", "/requests/rq_1/cancel", as_="bob"), 409, "request_not_pending", "cancel a declined request")
    t.err(S.call("POST", "/requests/rq_1/pay", {}, as_="ada", key=k()), 409, "request_not_pending", "pay a declined request")
    for i in range(2):
        r = S.call("POST", "/requests/rq_2/cancel", as_="bob")
        t.st(r, 200, f"cancel #{i + 1}")
        req_shape(t, r.j, f"cancel #{i + 1}", request_id="rq_2", status="cancelled", payment_id=None, amount=300)
    t.err(S.call("POST", "/requests/rq_2/decline", as_="ada"), 409, "request_not_pending", "decline a cancelled request")
    t.err(S.call("POST", "/requests/rq_2/pay", {}, as_="ada", key=k()), 409, "request_not_pending", "pay a cancelled request")
    r = S.call("POST", "/requests", {"payer_handle": "ada", "amount": 10}, as_="bob", key=k())
    rid = (r.j or {}).get("request_id")
    t.st(S.call("POST", f"/requests/{rid}/pay", {}, as_="ada", key=k()), 201, "pay a new request")
    t.err(S.call("POST", f"/requests/{rid}/decline", as_="ada"), 409, "request_not_pending", "decline a paid request")
    t.err(S.call("POST", f"/requests/{rid}/cancel", as_="bob"), 409, "request_not_pending", "cancel a paid request")
    t.eq((S.req_by_id("bob", rid) or {}).get("status"), "paid", "paid request stays paid")
    t.eq(S.bals(HS), {"ada": 9990, "bob": 2510, "cy": 0, "dan": 500, "op": 1000}, "decline/cancel move no money")
    r = S.call("POST", "/requests/rq_1/decline", as_="ada", key=k())
    t.st(r, 200, "decline with a stray Idempotency-Key header")


@check("G12-list-requests", "§8 GET /requests, §4 feed contract", "G12,G17", "GET /requests: only the caller's (requester or payer); newest first; direction and status filters; unknown values 422; shape {requests, has_more}")
def c_listreq(t, S):
    fx = basefx()
    fx["requests"] = [
        {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
        {"id": "rq_2", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 300, "note": "tea", "status": "pending"},
        {"id": "rq_3", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 40, "note": "x", "status": "declined"},
        {"id": "rq_4", "requester_id": "u_cy", "payer_id": "u_dan", "amount": 70, "note": "y", "status": "cancelled"}]
    S.reset(fx)

    def got(h, q):
        return sorted(ids(S.reqs(h, q), "request_id"))
    t.eq(got("ada", ""), ["rq_1", "rq_2", "rq_3"], "ada, no filter")
    t.eq(got("ada", "?direction=incoming"), ["rq_1"], "ada incoming (ada is payer)")
    t.eq(got("ada", "?direction=outgoing"), ["rq_2", "rq_3"], "ada outgoing (ada is requester)")
    t.eq(got("ada", "?status=pending"), ["rq_1", "rq_2"], "ada pending")
    t.eq(got("ada", "?status=declined"), ["rq_3"], "ada declined")
    t.eq(got("ada", "?status=paid"), [], "ada paid")
    t.eq(got("ada", "?status=cancelled"), [], "ada cancelled")
    t.eq(got("ada", "?direction=outgoing&status=declined"), ["rq_3"], "ada outgoing+declined")
    t.eq(got("ada", "?direction=incoming&status=declined"), [], "ada incoming+declined")
    t.eq(got("cy", ""), ["rq_3", "rq_4"], "cy, no filter")
    t.eq(got("cy", "?direction=incoming"), ["rq_3"], "cy incoming")
    t.eq(got("dan", "?status=cancelled&direction=incoming&limit=50&offset=0"), ["rq_4"], "dan, full query")
    t.eq(got("op", ""), [], "operator / third party sees no requests")
    for q in ("?direction=sideways", "?status=open", "?status=PENDING", "?direction=both", "?status=pending,paid"):
        t.err(S.call("GET", "/requests" + q, as_="ada"), 422, "validation_failed", f"GET /requests{q}")
    r = S.call("GET", "/requests", as_="ada")
    t.ok(isinstance(r.j, dict) and isinstance(r.j.get("has_more"), bool), f"shape {{requests, has_more}}: {r!r}")
    for q in (r.j or {}).get("requests", []):
        req_shape(t, q, "listed request")
    S.reset(basefx(requests=[]))
    made = []
    for i in range(3):
        r = S.call("POST", "/requests", {"payer_handle": "ada", "amount": 10 + i}, as_="bob", key=k())
        made.append((r.j or {}).get("request_id"))
        time.sleep(1.1)
    t.eq(ids(S.reqs("bob"), "request_id"), made[::-1], "bob: newest first")
    t.eq(ids(S.reqs("ada"), "request_id"), made[::-1], "ada: newest first")
    t.eq(ids(S.reqs("ada", "?limit=1&offset=1"), "request_id"), made[1:2], "limit=1&offset=1 is the middle one")
    t.st(S.call("POST", f"/requests/{made[0]}/decline", as_="ada"), 200, "decline oldest")
    t.eq(ids(S.reqs("bob"), "request_id"), made[::-1], "order by created_at unchanged by a status change")
    t.eq(ids(S.reqs("bob", "?status=pending"), "request_id"), made[:0:-1], "pending after a decline")


@check("G13-split", "§8 POST /splits", "G13,G14,G15,G17", "Split 201 body; shares cover all participants in the given order; requests for every participant except the caller, caller as requester; caller included or omitted; errors; caller-only split valid; no balance check; not a feed item")
def c_split(t, S):
    S.reset(basefx())
    r = S.call("POST", "/splits", {"amount": 3000, "participant_handles": ["ada", "bob", "cy"], "note": "dinner"}, as_="ada", key=k())
    t.st(r, 201, "split, caller included first")
    j = r.j or {}
    idok(t, j.get("split_id"), "split_id")
    tsok(t, j.get("created_at"), "split created_at")
    t.eq(j.get("amount"), 3000, "split amount")
    t.eq(j.get("currency"), "EUR", "split currency")
    t.eq(j.get("note"), "dinner", "split note")
    t.eq(j.get("shares"), [{"handle": "ada", "amount": 1000}, {"handle": "bob", "amount": 1000}, {"handle": "cy", "amount": 1000}], "shares")
    rq = j.get("requests") or []
    t.eq(len(rq), 2, "requests count")
    for q, h in zip(rq, ("bob", "cy")):
        req_shape(t, q, f"split request for {h}", requester_id="u_ada", requester_handle="ada", payer_id="u_" + h,
                  payer_handle=h, amount=1000, currency="EUR", note="dinner", status="pending", payment_id=None)
    t.ok(len(set(ids(rq, "request_id"))) == len(rq), "split request ids distinct")
    for q, h in zip(rq, ("bob", "cy")):
        t.ok(S.req_by_id(h, q.get("request_id")) is not None, f"{h} sees the split request in GET /requests")
        t.ok(S.req_by_id("dan", q.get("request_id")) is None, "third party sees a split request")
    t.eq(len(S.acts("cy")), 1, "split created no feed item (cy sees only seeded p_1)")
    t.eq(S.bals(HS), {"ada": 10000, "bob": 2500, "cy": 0, "dan": 500, "op": 1000}, "split moves no money")
    r = S.call("POST", "/splits", {"amount": 1000, "participant_handles": ["bob", "ada", "cy"]}, as_="ada", key=k())
    j = r.j or {}
    t.eq(j.get("shares"), [{"handle": "bob", "amount": 334}, {"handle": "ada", "amount": 333}, {"handle": "cy", "amount": 333}], "caller in the middle: shares")
    t.eq([(q.get("payer_handle"), q.get("amount")) for q in j.get("requests") or []], [("bob", 334), ("cy", 333)], "caller in the middle: requests")
    t.eq(j.get("note"), "", "split note default")
    r = S.call("POST", "/splits", {"amount": 1000, "participant_handles": ["cy", "bob", "dan"]}, as_="ada", key=k())
    j = r.j or {}
    t.st(r, 201, "split, caller omitted")
    t.eq(j.get("shares"), [{"handle": "cy", "amount": 334}, {"handle": "bob", "amount": 333}, {"handle": "dan", "amount": 333}], "caller omitted: shares")
    t.eq([(q.get("payer_handle"), q.get("amount"), q.get("requester_handle")) for q in j.get("requests") or []],
         [("cy", 334, "ada"), ("bob", 333, "ada"), ("dan", 333, "ada")], "caller omitted: requests")
    r = S.call("POST", "/splits", {"amount": 777, "participant_handles": ["cy"]}, as_="cy", key=k())
    t.st(r, 201, "caller-only split (caller has balance 0)")
    t.eq((r.j or {}).get("shares"), [{"handle": "cy", "amount": 777}], "caller-only shares")
    t.eq((r.j or {}).get("requests"), [], "caller-only requests")
    r = S.call("POST", "/splits", {"amount": 1000000000, "participant_handles": ["cy", "dan"]}, as_="cy", key=k())
    t.st(r, 201, "split far above anyone's balance")
    n_before = len(S.reqs("bob"))
    t.err(S.call("POST", "/splits", {"amount": 10, "participant_handles": []}, as_="ada", key=k()), 422, "validation_failed", "empty participants")
    t.err(S.call("POST", "/splits", {"amount": 10, "participant_handles": ["bob", "cy", "bob"]}, as_="ada", key=k()), 422, "validation_failed", "duplicate handle")
    t.err(S.call("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "ada"]}, as_="ada", key=k()), 422, "validation_failed", "duplicate caller handle")
    t.err(S.call("POST", "/splits", {"amount": 10, "participant_handles": ["bob", "nobody_here"]}, as_="ada", key=k()), 404, "not_found", "unknown handle")
    t.eq(len(S.reqs("bob")), n_before, "failed splits created no request for bob")


@check("G16-activity", "§4 feed contract, §8 GET /activity", "G16,G17", "Activity: payments only; visible iff public or the caller is sender or receiver; one visibility value seen by both parties; newest first; shape {payments, has_more}")
def c_activity(t, S):
    S.reset(basefx(payments=[], requests=[]))
    made = []
    for i, (frm, to, vis) in enumerate([("ada", "bob", "public"), ("ada", "bob", "private"), ("bob", "cy", "private"), ("dan", "cy", "public")]):
        r = S.call("POST", "/payments", {"to_handle": to, "amount": 10 + i, "visibility": vis, "note": f"n{i}"}, as_=frm, key=k())
        made.append((r.j or {}).get("payment_id"))
        time.sleep(1.1)
    S.call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, as_="bob", key=k())
    S.call("POST", "/splits", {"amount": 9, "participant_handles": ["bob", "cy"]}, as_="ada", key=k())
    exp = {"ada": [3, 1, 0], "bob": [3, 2, 1, 0], "cy": [3, 2, 0], "dan": [3, 0], "op": [3, 0]}
    for h, idx in exp.items():
        r = S.call("GET", "/activity", as_=h)
        t.ok(r.status == 200 and isinstance(r.j, dict) and isinstance(r.j.get("has_more"), bool) and isinstance(r.j.get("payments"), list),
             f"{h}: shape {{payments, has_more}}: {r!r}")
        got = ids((r.j or {}).get("payments") or [], "payment_id")
        t.eq(got, [made[i] for i in idx], f"{h}: visible payments, newest first")
        for p in (r.j or {}).get("payments") or []:
            pay_shape(t, p, f"{h} feed item")
    a = {p.get("payment_id"): p for p in S.acts("ada")}
    b = {p.get("payment_id"): p for p in S.acts("bob")}
    t.ok(a.get(made[1]) == b.get(made[1]) and (a.get(made[1]) or {}).get("visibility") == "private",
         "private payment must look identical to sender and receiver")
    t.ok(a.get(made[0]) == (S.acts("op")[-1] if S.acts("op") else None), "public payment must look identical to a third party")
    r = S.call("POST", "/auth/signup", {"email": "fresh@example.com", "password": "longenough", "display_name": "F"})
    r = S.call("GET", "/activity", token=(r.j or {}).get("token") or "x")
    t.eq(ids((r.j or {}).get("payments") or [], "payment_id"), [made[3], made[0]], "a new user sees exactly the public payments")
    ts = [parse_ts(p["created_at"]) for p in S.acts("bob") if isinstance(p.get("created_at"), str)]
    t.ok(all(x >= y for x, y in zip(ts, ts[1:])), "created_at not non-increasing down the feed")
    now = datetime.now(ts[0].tzinfo) if ts else None
    t.probe(bool(ts) and abs((now - ts[0]).total_seconds()) < 120, f"created_at of a fresh payment is not the current time: {ts[:1]}")


# --------------------------------------------------------------------------- H
@check("H1-rounding", "§9", "H1,H2", "Equal-split table: 1000/3 -> 334,333,333; 1/3 -> 1,0,0; 10/3 -> 4,3,3; 999/3 -> 333 x3; 5/5 -> 1 x5; order moves the extra unit; a share of 0 still produces a request")
def c_round(t, S):
    S.reset(basefx())
    table = [(1000, ["ada", "bob", "cy"], [334, 333, 333]), (1, ["ada", "bob", "cy"], [1, 0, 0]),
             (10, ["ada", "bob", "cy"], [4, 3, 3]), (999, ["ada", "bob", "cy"], [333, 333, 333]),
             (5, ["ada", "bob", "cy", "dan", "op"], [1, 1, 1, 1, 1]),
             (1000, ["cy", "bob", "ada"], [334, 333, 333]), (1000, ["bob", "cy", "ada"], [334, 333, 333]),
             (11, ["ada", "bob", "cy", "dan"], [3, 3, 3, 2]), (2, ["bob", "cy", "dan"], [1, 1, 0]),
             (1, ["bob", "ada"], [1, 0]), (1000000000, ["ada", "bob", "cy"], [333333334, 333333333, 333333333]),
             (7, ["bob"], [7]), (4, ["ada", "bob", "cy", "dan", "op"], [1, 1, 1, 1, 0])]
    for amount, hs, shares in table:
        r = S.call("POST", "/splits", {"amount": amount, "participant_handles": hs}, as_="ada", key=k())
        if not t.st(r, 201, f"split {amount} among {hs}"):
            continue
        j = r.j or {}
        t.eq(j.get("shares"), [{"handle": h, "amount": a} for h, a in zip(hs, shares)], f"split {amount} among {hs}: shares")
        exp = [(h, a) for h, a in zip(hs, shares) if h != "ada"]
        t.eq([(q.get("payer_handle"), q.get("amount")) for q in j.get("requests") or []], exp, f"split {amount} among {hs}: requests")
        t.ok(all(q.get("status") == "pending" for q in j.get("requests") or []), "split requests pending")
    r = S.call("POST", "/splits", {"amount": 1, "participant_handles": ["ada", "bob", "cy"], "note": "zero"}, as_="ada", key=k())
    zr = ((r.j or {}).get("requests") or [{}])[0]
    t.eq(zr.get("amount"), 0, "zero share request amount")
    q = S.req_by_id("bob", zr.get("request_id"))
    t.ok(q is not None and q.get("amount") == 0 and q.get("status") == "pending", f"zero-share request listed for its payer: {q}")
    r = S.call("POST", f"/requests/{zr.get('request_id')}/pay", {}, as_="bob", key=k())
    t.note(f"paying a zero-amount split request returns {r.status} {r.text[:160]} (specification is silent)")
    t.ok(r.status < 500, "paying a zero-amount request must not 5xx")
    t.eq(sum(S.bals(HS).values()), TOTAL, "sum of balances")


@check("H3-splits-paid", "§9 last paragraph", "H3,B1", "Shares are independent across splits; after several splits are paid in full the balances still sum to the seeded total")
def c_splitspaid(t, S):
    fx = basefx(payments=[], requests=[])
    for u in fx["users"]:
        u["balance"] = 10000
    S.reset(fx)
    gained = 0
    for amount in (1000, 1000, 10, 999, 101, 7, 1000):
        r = S.call("POST", "/splits", {"amount": amount, "participant_handles": ["ada", "bob", "cy", "dan"][: 3 if amount != 101 else 4]},
                   as_="ada", key=k())
        t.st(r, 201, f"split {amount}")
        if amount == 1000:
            t.eq([s.get("amount") for s in (r.j or {}).get("shares") or []], [334, 333, 333], "every 1000/3 split gives 334,333,333 (independent of earlier splits)")
        for q in (r.j or {}).get("requests") or []:
            if q.get("amount", 0) > 0:
                p = S.call("POST", f"/requests/{q.get('request_id')}/pay", {}, as_=q.get("payer_handle"), key=k())
                t.st(p, 201, f"pay share {q.get('amount')} by {q.get('payer_handle')}")
                gained += q.get("amount", 0)
    b = S.bals(HS)
    t.eq(sum(b.values()), 50000, "sum of balances after paying all splits")
    t.eq(b["ada"], 10000 + gained, "ada received exactly the sum of the others' shares")


# --------------------------------------------------------------------------- I
def tr(f, to, a, **kw):
    return dict({"from_handle": f, "to_handle": to, "amount": a}, **kw)


@check("I1-settlement-auth", "§11", "I1,I2", "Settlements: no token 401; non-operator 403 forbidden; operator may move money between wallets it is not party to; the permission grants no access to others' requests or private activity")
def c_setauth(t, S):
    S.reset(basefx())
    body = {"transfers": [tr("ada", "bob", 100)]}
    t.err(S.call("POST", "/settlements", body, key=k()), 401, "unauthenticated", "no token")
    for h in ("ada", "bob"):
        t.err(S.call("POST", "/settlements", body, as_=h, key=k()), 403, "forbidden", f"non-operator {h}")
    t.err(S.call("POST", "/settlements", {"transfers": [tr("bob", "ada", 100)]}, as_="ada", key=k()), 403, "forbidden",
          "non-operator moving money to itself")
    t.eq(S.bals(HS), {"ada": 10000, "bob": 2500, "cy": 0, "dan": 500, "op": 1000}, "nothing moved by non-operators")
    r = S.call("POST", "/settlements", {"transfers": [tr("ada", "bob", 100, visibility="private", note="s1"), tr("dan", "cy", 50)]}, as_="op", key=k())
    t.st(r, 201, "operator settles wallets it is not party to")
    t.eq(S.bals(HS), {"ada": 9900, "bob": 2600, "cy": 50, "dan": 450, "op": 1000}, "balances after settlement")
    pids = ids((r.j or {}).get("payments") or [], "payment_id")
    if t.ok(len(pids) == 2, "two member payments"):
        for h, sees in (("ada", True), ("bob", True), ("op", False), ("cy", False), ("dan", False)):
            t.eq(pids[0] in ids(S.acts(h), "payment_id"), sees, f"private member visible to {h}")
        for h in HS:
            t.ok(pids[1] in ids(S.acts(h), "payment_id"), f"public member visible to {h}")
        mine = [p for p in S.acts("ada") if p.get("payment_id") == pids[0]]
        t.ok(mine and mine[0] == (r.j or {}).get("payments")[0], "member in the feed equals its receipt in the settlement response")
    t.eq(S.reqs("op"), [], "operator sees no one else's requests")
    t.err(S.call("POST", "/requests/rq_1/pay", {}, as_="op", key=k()), 403, "forbidden", "operator pays another user's request")
    t.err(S.call("POST", "/requests/rq_1/cancel", as_="op"), 403, "forbidden", "operator cancels another user's request")
    t.ok("p_2" not in ids(S.acts("op"), "payment_id"), "operator sees a seeded private payment of others")
    r = S.call("POST", "/settlements", {"transfers": [tr("op", "ada", 10), tr("bob", "op", 5)]}, as_="op", key=k())
    t.st(r, 201, "operator as a party")
    t.eq(S.bal("op"), 995, "operator balance")


@check("I3-settlement-shape", "§11", "I3,I4,D3", "transfers holds 1..32 objects (0 and 33 -> 422; 1 and 32 ok); malformed batch shape -> 422; entry rules and defaults as for payments; unknown fields ignored")
def c_setshape(t, S):
    S.reset(basefx())
    r = S.call("POST", "/settlements", {"transfers": [tr("ada", "bob", 1)] * 32}, as_="op", key=k())
    t.st(r, 201, "32 transfers")
    t.eq(len((r.j or {}).get("payments") or []), 32, "32 member payments")
    t.eq(len(set(ids((r.j or {}).get("payments") or [], "payment_id"))), 32, "32 distinct payment ids")
    t.eq(S.bal("ada"), 9968, "ada after 32 x 1")
    bad = [("33 transfers", {"transfers": [tr("ada", "bob", 1)] * 33}), ("0 transfers", {"transfers": []}),
           ("missing transfers", {}), ("transfers object", {"transfers": {}}), ("transfers string", {"transfers": "x"}),
           ("transfers null", {"transfers": None}), ("transfers number", {"transfers": 5}),
           ("entry number", {"transfers": [5]}), ("entry string", {"transfers": ["x"]}), ("entry null", {"transfers": [None]}),
           ("entry array", {"transfers": [[]]}), ("valid entry then non-object", {"transfers": [tr("ada", "bob", 1), 7]})]
    for label, body in bad:
        t.err(S.call("POST", "/settlements", body, as_="op", key=k()), 422, "validation_failed", f"settlement {label}")
    t.eq(S.bals(HS), {"ada": 9968, "bob": 2532, "cy": 0, "dan": 500, "op": 1000}, "malformed batches move nothing")
    r = S.call("POST", "/settlements", {"transfers": [tr("ada", "bob", 1)]}, as_="op", key=k())
    t.st(r, 201, "1 transfer")
    p = ((r.j or {}).get("payments") or [{}])[0]
    t.eq(p.get("note"), "", "entry default note")
    t.eq(p.get("visibility"), "public", "entry default visibility")
    r = S.call("POST", "/settlements", {"transfers": [tr("ada", "bob", 1, note="x" * 200, visibility="private")]}, as_="op", key=k())
    t.st(r, 201, "entry with 200-char note")


@check("I4-settlement-errors", "§11", "I4,I6", "Unknown handle 404; self-transfer 422 self_payment; entry errors take precedence in input order and before insufficient funds; a failed settlement claims no key and creates no payment")
def c_seterr(t, S):
    S.reset(basefx())
    base = (S.bals(HS), [len(S.acts(h)) for h in HS])
    cases = [("unknown to_handle", [tr("ada", "nobody_here", 1)], 404, "not_found"),
             ("unknown from_handle", [tr("nobody_here", "ada", 1)], 404, "not_found"),
             ("self-transfer", [tr("ada", "ada", 1)], 422, "self_payment"),
             ("self first, unknown second", [tr("ada", "ada", 1), tr("ada", "nobody_here", 1)], 422, "self_payment"),
             ("unknown first, self second", [tr("ada", "nobody_here", 1), tr("ada", "ada", 1)], 404, "not_found"),
             ("bad amount first, unknown second", [tr("ada", "bob", 0), tr("ada", "nobody_here", 1)], 422, "validation_failed"),
             ("unknown first, bad amount second", [tr("ada", "nobody_here", 1), tr("ada", "bob", 0)], 404, "not_found"),
             ("valid, then self, then unknown", [tr("ada", "bob", 1), tr("bob", "bob", 1), tr("x_unknown", "bob", 1)], 422, "self_payment"),
             ("unaffordable first, self second", [tr("dan", "bob", 99999), tr("ada", "ada", 1)], 422, "self_payment"),
             ("unaffordable first, unknown second", [tr("dan", "bob", 99999), tr("ada", "nobody_here", 1)], 404, "not_found"),
             ("unaffordable first, bad visibility second", [tr("dan", "bob", 99999), tr("ada", "bob", 1, visibility="x")], 422, "validation_failed"),
             ("unaffordable", [tr("ada", "bob", 1), tr("dan", "bob", 501)], 409, "insufficient_funds"),
             ("valid first, 201-char note last", [tr("ada", "bob", 1), tr("ada", "bob", 1, note="x" * 201)], 422, "validation_failed")]
    keys = []
    for label, trs, st, code in cases:
        key = k()
        keys.append(key)
        t.err(S.call("POST", "/settlements", {"transfers": trs}, as_="op", key=key), st, code, f"settlement {label}")
    t.ok(base == (S.bals(HS), [len(S.acts(h)) for h in HS]), "failed settlements changed balances or feeds (must be all-or-nothing)")
    for key in keys[:3] + keys[-2:]:
        r = S.call("POST", "/settlements", {"transfers": [tr("ada", "bob", 1)]}, as_="op", key=key)
        t.st(r, 201, "key of a failed settlement reused with a valid body is a first use")
    t.eq(S.bal("ada"), 9995, "ada after five 1-unit settlements")


@check("I5-net-affordability", "§11", "I5,B1,B2", "Affordability is net over the whole batch: a wallet may pass on money it receives in the same batch, in any input order; otherwise 409 insufficient_funds and nothing moves")
def c_net(t, S):
    S.reset(basefx())
    r = S.call("POST", "/settlements", {"transfers": [tr("ada", "cy", 100), tr("cy", "dan", 50)]}, as_="op", key=k())
    t.st(r, 201, "ada->cy 100, cy->dan 50 with cy at 0")
    t.eq(S.bals(HS), {"ada": 9900, "bob": 2500, "cy": 50, "dan": 550, "op": 1000}, "balances")
    r = S.call("POST", "/settlements", {"transfers": [tr("cy", "dan", 150), tr("ada", "cy", 100)]}, as_="op", key=k())
    t.st(r, 201, "outgoing listed before the incoming that funds it (cy 50 -> 0)")
    t.eq(S.bals(HS), {"ada": 9800, "bob": 2500, "cy": 0, "dan": 700, "op": 1000}, "balances")
    r = S.call("POST", "/settlements", {"transfers": [tr("cy", "dan", 51), tr("ada", "cy", 50)]}, as_="op", key=k())
    t.err(r, 409, "insufficient_funds", "cy net -1")
    r = S.call("POST", "/settlements", {"transfers": [tr("cy", "bob", 100), tr("bob", "cy", 100)]}, as_="op", key=k())
    t.st(r, 201, "cycle with net zero for a wallet holding 0")
    r = S.call("POST", "/settlements", {"transfers": [tr("dan", "cy", 700), tr("dan", "bob", 1)]}, as_="op", key=k())
    t.err(r, 409, "insufficient_funds", "dan 700, outgoing 701")
    t.eq(S.bals(HS), {"ada": 9800, "bob": 2500, "cy": 0, "dan": 700, "op": 1000}, "nothing moved by unaffordable batches")
    r = S.call("POST", "/settlements", {"transfers": [tr("dan", "cy", 699), tr("dan", "bob", 1)]}, as_="op", key=k())
    t.st(r, 201, "dan spends exactly his balance over two transfers")
    t.eq(S.bals(HS), {"ada": 9800, "bob": 2501, "cy": 699, "dan": 0, "op": 1000}, "balances")
    S.reset(basefx())
    S.token("op"), S.token("dan")
    fns = [lambda: S.call("POST", "/settlements", {"transfers": [tr("dan", "bob", 60), tr("dan", "cy", 40)]}, as_="op", key=k()) for _ in range(10)]
    fns += [lambda: S.call("POST", "/payments", {"to_handle": "bob", "amount": 100}, as_="dan", key=k()) for _ in range(10)]
    rs = par(fns)
    t.eq(sum(r.status == 201 for r in rs), 5, f"20 concurrent 100-unit debits (settlements and payments) of a wallet holding 500: 201 count {sorted(r.status for r in rs)}")
    t.ok(all(r.status == 201 or is_err(r, 409, "insufficient_funds") for r in rs), "others must be 409 insufficient_funds")
    b = S.bals(HS)
    t.eq(b["dan"], 0, "dan after the storm")
    t.eq(sum(b.values()), TOTAL, "sum of balances after the storm")


@check("I7-settlement-response", "§11", "I7,I8", "201 {settlement_id, committed_at, payments in input order}; members are ordinary payments with settlement_id set, request_id null and created_at == committed_at; non-members show settlement_id null; replay 200 with the complete original response")
def c_setresp(t, S):
    S.reset(basefx())
    key = k()
    body = {"transfers": [tr("ada", "bob", 100, note="a"), tr("bob", "cy", 50, visibility="private"), tr("dan", "ada", 7, note="c")]}
    r = S.call("POST", "/settlements", body, as_="op", key=key)
    t.st(r, 201, "settlement")
    j = r.j or {}
    sid = j.get("settlement_id")
    idok(t, sid, "settlement_id")
    tsok(t, j.get("committed_at"), "committed_at")
    ps = j.get("payments") or []
    if t.eq(len(ps), 3, "member count"):
        exp = [("ada", "bob", 100, "a", "public"), ("bob", "cy", 50, "", "private"), ("dan", "ada", 7, "c", "public")]
        for p, (f, to, a, n, v) in zip(ps, exp):
            pay_shape(t, p, f"member {f}->{to}", from_handle=f, from_user_id="u_" + f, to_handle=to, to_user_id="u_" + to,
                      amount=a, note=n, visibility=v, currency="EUR", request_id=None, settlement_id=sid,
                      created_at=j.get("committed_at"))
        t.eq(len(set(ids(ps, "payment_id"))), 3, "distinct member ids")
    feed = {p.get("payment_id"): p for p in S.acts("ada")}
    t.eq((feed.get(ps[0].get("payment_id")) if ps else None), ps[0] if ps else 1, "member in ada's feed equals its receipt")
    t.eq((feed.get("p_1") or {}).get("settlement_id", "MISSING"), None, "non-member (seeded) exposes settlement_id null")
    r1 = S.call("POST", "/payments", {"to_handle": "bob", "amount": 1}, as_="ada", key=k())
    t.eq((r1.j or {"settlement_id": "MISSING"}).get("settlement_id", "MISSING"), None, "ordinary payment exposes settlement_id null")
    r2 = S.call("POST", "/settlements", body, as_="op", key=key)
    t.st(r2, 200, "settlement replay")
    t.ok(r2.j == r.j, "settlement replay differs from the original response")
    t.eq(S.bals(HS), {"ada": 9906, "bob": 2551, "cy": 50, "dan": 493, "op": 1000}, "balances after settlement + replay + 1")


# --------------------------------------------------------------------------- A5 load
@check("A5-load-50", "§2 resource limits, §5 last line, §1 invariants", "A5,A6,B1", "50 requests in flight (mixed reads, payments, requests, logins): no 5xx, each under 5 s, sum of balances preserved; reset of a 60-user fixture under 10 s")
def c_load(t, S):
    fx = basefx(payments=[], requests=[])
    for u in fx["users"]:
        u["balance"] = 100000
    S.reset(fx)
    for h in HS:
        S.token(h)
    bad = []
    worst = [0.0]

    def one(i, rnd):
        a, b = HS[i % 5], HS[(i + 1 + rnd) % 5]
        if a == b:
            b = HS[(i + 2) % 5]
        kind = i % 5
        if kind == 0:
            r = S.call("GET", "/activity?limit=50", as_=a)
            okc = (200,)
        elif kind == 1:
            r = S.call("POST", "/payments", {"to_handle": b, "amount": 1 + i}, as_=a, key=k())
            okc = (201,)
        elif kind == 2:
            r = S.call("POST", "/requests", {"payer_handle": b, "amount": 3}, as_=a, key=k())
            okc = (201,)
        elif kind == 3:
            r = S.call("GET", "/me", as_=a)
            okc = (200,)
        else:
            r = S.call("POST", "/settlements", {"transfers": [tr(a, b, 2), tr(b, a, 1)]}, as_="op", key=k())
            okc = (201,)
        worst[0] = max(worst[0], r.secs)
        if r.status not in okc:
            bad.append(repr(r)[:160])
    for rnd in range(6):
        par([lambda i=i: one(i, rnd) for i in range(50)])
    t.ok(not bad, f"{len(bad)} unexpected responses under 50 in flight, e.g. {bad[:3]}")
    t.ok(worst[0] < 5.0, f"slowest request under 50 in flight took {worst[0]:.2f}s (limit 5 s)")
    t.eq(sum(S.bals(HS).values()), 500000, "sum of balances after load")
    rs = par([lambda i=i: S.call("POST", "/auth/login", {"email": f"{HS[i % 5]}@example.com", "password": PW}) for i in range(50)])
    t.ok(all(r.status == 200 for r in rs), f"50 concurrent logins: {sorted(r.status for r in rs)}")
    t.ok(max(r.secs for r in rs) < 5.0, f"slowest of 50 concurrent logins took {max(r.secs for r in rs):.2f}s (limit 5 s)")
    t.note(f"load: slowest mixed request {worst[0]:.3f}s; slowest of 50 concurrent logins {max(r.secs for r in rs):.3f}s")
    big = {"currency": "EUR", "minor_units": 2, "users": [user(f"u_{i}", f"user{i}", 1000) for i in range(60)],
           "payments": [{"id": f"p_{i}", "from_user_id": f"u_{i}", "to_user_id": f"u_{(i + 1) % 60}", "amount": 5,
                         "note": "", "visibility": "public"} for i in range(60)], "requests": []}
    r = S.call("POST", "/_test/reset", big)
    S.tok = {}
    t.st(r, 204, "reset with 60 users / 60 payments")
    t.ok(r.secs < 10.0, f"reset of a 60-user fixture took {r.secs:.2f}s (limit 10 s)")
    t.note(f"reset of a 60-user fixture took {r.secs:.3f}s")
    t.st(S.call("POST", "/auth/login", {"email": "user59@example.com", "password": PW}), 200, "login of the 60th seeded user")


# --------------------------------------------------------------------------- J
def j_prepare(t, S):
    """Build state on S, export it. Returns ctx with everything to verify after import."""
    S.reset(basefx())
    ctx = {"keys": {}, "tok": {}}
    r = S.call("POST", "/auth/signup", {"email": "nina@example.com", "password": "nina-secret-pw", "display_name": "Nina"})
    t.st(r, 201, "prepare: signup")
    ctx["tok"]["nina"] = (r.j or {}).get("token") or "x"
    ctx["nina_id"] = (r.j or {}).get("user_id")
    for h in HS:
        ctx["tok"][h] = S.token(h)
    ctx["tok"]["ada2"] = S.login("ada")
    calls = {
        "payment": ("ada", "/payments", {"to_handle": "nina", "amount": 250, "note": "wel\u00e7ome \U0001F389", "visibility": "private"}),
        "request": ("bob", "/requests", {"payer_handle": "ada", "amount": 77, "note": "r"}),
        "pay": ("ada", "/requests/rq_1/pay", {"visibility": "private"}),
        "split": ("ada", "/splits", {"amount": 1000, "participant_handles": ["ada", "bob", "cy"], "note": "sp"}),
        "settlement": ("op", "/settlements", {"transfers": [tr("ada", "cy", 100, visibility="private"), tr("cy", "dan", 50)]}),
    }
    for name, (who, path, body) in calls.items():
        key = k()
        r = S.call("POST", path, body, as_=who, key=key)
        t.st(r, 201, f"prepare: {name}")
        ctx["keys"][name] = (who, path, body, key, r.j)
    ctx["failkey"] = k()
    t.err(S.call("POST", "/payments", {"to_handle": "bob", "amount": 999999}, as_="dan", key=ctx["failkey"]), 409,
          "insufficient_funds", "prepare: failing payment")
    t.st(S.call("POST", "/requests/rq_2/decline", as_="ada"), 200, "prepare: decline rq_2")
    ctx["snap"] = j_snapshot(S, ctx)
    r = S.call("GET", "/_test/export")
    t.st(r, 200, "GET /_test/export without auth")
    e = r.j
    if t.ok(isinstance(e, dict), f"export is a JSON object: {r.text[:120]}"):
        t.eq(e.get("track"), "pocketful", "export track")
        t.eq(e.get("format_version"), 1, "export format_version")
        t.ok(isinstance(e.get("state"), dict), "export state is a JSON object")
        t.ok(PW not in r.text and "nina-secret-pw" not in r.text, "export contains a plaintext password")
    ctx["export"] = e
    ctx["export_secs"] = r.secs
    t.ok(r.secs < 10.0, f"export took {r.secs:.2f}s")
    r2 = S.call("GET", "/_test/export")
    t.ok(r2.j == e, "two exports with no write in between differ (export must be read-only)")
    t.ok(j_snapshot(S, ctx) == ctx["snap"], "export changed observable state")
    return ctx


def j_snapshot(S, ctx):
    snap = {}
    for h, tok in ctx["tok"].items():
        me = S.call("GET", "/me", token=tok)
        ac = S.call("GET", "/activity?limit=200", token=tok)
        rq = S.call("GET", "/requests?limit=200", token=tok)
        snap[h] = (me.status, me.j, ac.status, ac.j, rq.status, rq.j)
    return snap


def j_verify(t, S, ctx, label):
    snap = j_snapshot(S, ctx)
    for h in ctx["snap"]:
        t.ok(snap[h] == ctx["snap"][h],
             f"{label}: {h}'s /me, /activity or /requests differ after import (tokens, ids, timestamps, balances must be preserved): "
             f"{json.dumps(snap[h])[:300]} vs {json.dumps(ctx['snap'][h])[:300]}")
    r = S.call("POST", "/auth/login", {"email": "ada@example.com", "password": PW})
    t.st(r, 200, f"{label}: seeded user password login after import")
    t.eq((r.j or {}).get("user_id"), "u_ada", f"{label}: login user_id")
    r = S.call("POST", "/auth/login", {"email": "nina@example.com", "password": "nina-secret-pw"})
    t.st(r, 200, f"{label}: signed-up user password login after import")
    t.eq((r.j or {}).get("user_id"), ctx["nina_id"], f"{label}: signed-up user id preserved")
    t.err(S.call("POST", "/auth/login", {"email": "ada@example.com", "password": "wrong horse"}), 401, "unauthenticated", f"{label}: wrong password after import")
    for name, (who, path, body, key, orig) in ctx["keys"].items():
        r = S.call("POST", path, body, token=ctx["tok"][who], key=key)
        t.st(r, 200, f"{label}: replay of {name} after import")
        t.ok(r.j == orig, f"{label}: replay of {name} differs from the original response")
        alt = dict(body, zz_changed=1)
        t.err(S.call("POST", path, alt, token=ctx["tok"][who], key=key), 409, "idempotency_key_reuse", f"{label}: {name} key with another body after import")
    t.ok(j_snapshot(S, ctx) == ctx["snap"], f"{label}: replays after import changed state")
    t.err(S.call("POST", "/settlements", {"transfers": [tr("ada", "bob", 1)]}, token=ctx["tok"]["ada"], key=k()), 403, "forbidden", f"{label}: non-operator after import")
    t.err(S.call("POST", "/requests/rq_1/pay", {}, token=ctx["tok"]["ada"], key=k()), 409, "request_not_pending", f"{label}: paid request stays paid after import")
    r = S.call("POST", "/auth/signup", {"email": "nina@example.com", "password": "another-pw-1", "display_name": "N"})
    t.err(r, 409, "email_taken", f"{label}: imported account blocks a second signup")
    # writes below change state; callers re-import afterwards when they need the snapshot again
    r = S.call("POST", "/payments", {"to_handle": "bob", "amount": 5}, token=ctx["tok"]["dan"], key=ctx["failkey"])
    t.st(r, 201, f"{label}: key of a request that failed before export is a first use after import")
    r = S.call("POST", "/settlements", {"transfers": [tr("ada", "bob", 1)]}, token=ctx["tok"]["op"], key=k())
    t.st(r, 201, f"{label}: operator permission preserved")
    r = S.call("POST", "/payments", {"to_handle": "ada", "amount": 250}, token=ctx["tok"]["nina"], key=k())
    t.st(r, 201, f"{label}: imported balance is spendable in full")
    idok(t, (r.j or {}).get("payment_id"), "payment id after import")
    t.ok((r.j or {}).get("payment_id") not in [p.get("payment_id") for p in (ctx["snap"]["ada"][3] or {}).get("payments", [])],
         f"{label}: a new payment reused the id of an imported payment")


@check("J1-export-import", "§10", "J1,J2,J3,J4,E7", "Export shape; import of an unchanged export -> 204, replaces (not merges) all state; accounts, password login, tokens, balances, payments, requests, operators, settlement membership, ids, timestamps and idempotency records survive; failed keys stay reusable; repeat import duplicates nothing; reset clears imported state")
def c_export(t, S):
    ctx = j_prepare(t, S)
    e = ctx["export"]
    t.st(S.call("POST", "/payments", {"to_handle": "bob", "amount": 3}, as_="ada", key=k()), 201, "write after export")
    S.reset(dict(OTHERFX, settlement_operator_ids=["u_zed"]))
    zed = S.token("zed")
    r = S.call("POST", "/_test/import", e)
    t.st(r, 204, "import of the unchanged export, without auth")
    t.ok(not r.raw, "import 204 carries a body")
    t.ok(r.secs < 10.0, f"import took {r.secs:.2f}s")
    S.tok = {}
    t.err(S.call("GET", "/me", token=zed), 401, "unauthenticated", "destination token removed by import")
    t.err(S.call("POST", "/auth/login", {"email": "zed@example.com", "password": PW}), 401, "unauthenticated", "destination account removed by import")
    j_verify(t, S, ctx, "same container")
    r = S.call("POST", "/_test/import", e)
    t.st(r, 204, "import repeated")
    t.ok(j_snapshot(S, ctx) == ctx["snap"], "repeated import must restore exactly the exported state (no duplicates, later writes gone)")
    r = S.call("POST", "/_test/import", e)
    t.st(r, 204, "import a third time")
    t.ok(j_snapshot(S, ctx) == ctx["snap"], "third import: state differs from the export")
    r = S.call("GET", "/_test/export")
    t.probe(r.j == e, "export -> import -> export is not byte-identical as a JSON value (allowed; state is opaque)")
    r2 = S.call("POST", "/_test/import", r.j)
    t.st(r2, 204, "import of a re-export")
    t.ok(j_snapshot(S, ctx) == ctx["snap"], "state after importing a re-export differs")
    S.reset(OTHERFX)
    t.err(S.call("GET", "/me", token=ctx["tok"]["ada"]), 401, "unauthenticated", "reset clears imported tokens")
    t.eq(S.me("zed").get("currency"), "JPY", "reset clears imported currency")
    t.eq(S.acts("zed"), [], "reset clears imported payments")


@check("J5-import-invalid", "§10, §5", "J5", "Import: invalid JSON -> 400 malformed_request; missing fields, wrong track, wrong format_version or invalid state -> 422 validation_failed; destination unchanged")
def c_import_bad(t, S):
    S.reset(basefx())
    tok = S.token("ada")
    e = S.call("GET", "/_test/export").j or {}
    S.reset(dict(OTHERFX))
    zed = S.token("zed")
    t.err(S.call("POST", "/_test/import", raw='{"track": "pocketful", '), 400, "malformed_request", "import invalid JSON")
    bad = [("missing track", {kk: v for kk, v in e.items() if kk != "track"}),
           ("missing format_version", {kk: v for kk, v in e.items() if kk != "format_version"}),
           ("missing state", {kk: v for kk, v in e.items() if kk != "state"}),
           ("empty object", {}),
           ("wrong track", dict(e, track="tablekeeper")), ("wrong format_version 2", dict(e, format_version=2)),
           ("wrong format_version 0", dict(e, format_version=0)),
           ("state string", dict(e, state="x")), ("state array", dict(e, state=[])), ("state null", dict(e, state=None)),
           ("state number", dict(e, state=5))]
    for label, body in bad:
        t.err(S.call("POST", "/_test/import", body), 422, "validation_failed", f"import {label}")
    r = S.call("POST", "/_test/import", dict(e, format_version="1"))
    t.err_any(r, [(422, "validation_failed"), (400, "malformed_request")], "import format_version as string")
    r = S.call("POST", "/_test/import", dict(e, state={}))
    t.probe(is_err(r, 422, "validation_failed"), f"import with state {{}}: got {r!r}")
    still = S.call("GET", "/me", token=zed)
    if not (still.status == 200 and (still.j or {}).get("balance") == 200):
        t.note("state {} was accepted and replaced the destination")
        S.reset(dict(OTHERFX))
        zed = S.token("zed")
    if isinstance(e.get("state"), dict) and e["state"]:
        broken = dict(e, state={kk: 12345 for kk in e["state"]})
        r = S.call("POST", "/_test/import", broken)
        t.err(r, 422, "validation_failed", "import with every state member replaced by a number (invalid state)")
    for raw in ("[]", '"x"', "7"):
        t.err_any(S.call("POST", "/_test/import", raw=raw), [(400, "malformed_request"), (422, "validation_failed")], f"import non-object body {raw}")
    r = S.call("GET", "/me", token=zed)
    t.st(r, 200, "destination token still valid after rejected imports")
    t.eq((r.j or {}).get("balance"), 200, "destination balance unchanged after rejected imports")
    t.eq((r.j or {}).get("currency"), "JPY", "destination currency unchanged after rejected imports")
    t.err(S.call("GET", "/me", token=tok), 401, "unauthenticated", "source token not imported by a rejected import")
    r = S.call("POST", "/_test/import", dict(e, zzz_unknown=1))
    t.st(r, 204, "import with an unknown top-level field (ignored)")
    t.st(S.call("GET", "/me", token=tok), 200, "source token valid after the accepted import")


@check("J6-cross-container", "§10", "J3,J6", "Export from one container, import into a second, fresh container, with the source container stopped before verification: everything is preserved with no dependency on the source process, files, port or address")
def c_cross(t, S, S2=None, kill_cmd=None):
    if S2 is None:
        t.ok(False, "not run: needs --base2 (a second container)")
        return
    ctx = j_prepare(t, S)
    t.st(S.call("POST", "/payments", {"to_handle": "bob", "amount": 3}, as_="ada", key=k()), 201, "source write after export")
    if kill_cmd:
        out = subprocess.run(kill_cmd, shell=True, capture_output=True, text=True)
        t.ok(out.returncode == 0, f"kill command failed: {out.stderr}")
        t.note(f"source container stopped with: {kill_cmd}")
    else:
        S.reset(OTHERFX)
        t.note("no --kill-cmd: source was reset to another fixture instead of being stopped")
    r = S2.call("GET", "/health")
    t.st(r, 200, "second container healthy")
    r = S2.call("POST", "/_test/import", ctx["export"])
    t.st(r, 204, "import into a fresh second container (never reset)")
    t.ok(r.secs < 10.0, f"import took {r.secs:.2f}s")
    j_verify(t, S2, ctx, "second container")
    r = S2.call("POST", "/_test/import", ctx["export"])
    t.st(r, 204, "second container: import repeated")
    t.ok(j_snapshot(S2, ctx) == ctx["snap"], "second container: repeated import must restore exactly the exported state")


# --------------------------------------------------------------------------- global audits
@check("A6-no-5xx", "§5 last line", "A6", "Across every request sent by this run: no 5xx response and no transport error")
def c_no5xx(t, S):
    bad = [a for a in AUDIT if a[2] >= 500 or a[2] == 0]
    t.ok(not bad, f"{len(bad)} of {len(AUDIT)} requests gave 5xx or a transport error, e.g. {[(a[0], a[1], a[2]) for a in bad[:8]]}")
    t.note(f"{len(AUDIT)} requests audited")


@check("A7-content-type", "§3.4", "A7", "Across every response with a body: Content-Type is application/json; charset=utf-8")
def c_ctype(t, S):
    bad = [a for a in AUDIT if a[4]]
    kinds = sorted({(a[0], a[1].split("?")[0], a[2], a[4]) for a in bad})
    t.ok(not bad, f"{len(bad)} responses with another Content-Type, e.g. {kinds[:8]}")


@check("A5-latency", "§2 resource limits", "A5", "Across every request sent by this run: under 5 s (10 s for /_test/* control calls)")
def c_latency(t, S):
    slow = [a for a in AUDIT if a[3] >= a[5]]
    t.ok(not slow, f"{len(slow)} requests over their limit, e.g. {[(a[0], a[1], round(a[3], 2)) for a in slow[:8]]}")
    if AUDIT:
        w = max(AUDIT, key=lambda a: a[3])
        t.note(f"slowest request: {w[0]} {w[1]} {w[3]:.3f}s")


LAST = ["J6-cross-container", "A6-no-5xx", "A7-content-type", "A5-latency"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base")
    ap.add_argument("--base2")
    ap.add_argument("--kill-cmd")
    ap.add_argument("--only")
    ap.add_argument("--json")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    order = [c for c in CHECKS if c["id"] not in LAST] + [c for n in LAST for c in CHECKS if c["id"] == n]
    if a.list:
        print("| Check | Spec | Map rows | What it checks |\n|---|---|---|---|")
        for c in order:
            print(f"| {c['id']} | {c['clause']} | {c['row']} | {c['desc']} |")
        return 0
    S = Sess(a.base)
    S2 = Sess(a.base2) if a.base2 else None
    only = a.only.split(",") if a.only else None
    results = []
    for c in order:
        if only and not any(c["id"].startswith(p) for p in only):
            continue
        t = T()
        t0 = time.monotonic()
        try:
            if c["id"] == "J6-cross-container":
                c["fn"](t, S, S2, a.kill_cmd)
            else:
                c["fn"](t, S)
        except Exception as ex:
            t.fails.append(f"ERROR {type(ex).__name__}: {ex}\n{traceback.format_exc(limit=3)}")
        status = "FAIL" if t.fails else "PASS"
        results.append(dict(id=c["id"], clause=c["clause"], row=c["row"], status=status, fails=t.fails, notes=t.notes,
                            secs=round(time.monotonic() - t0, 2)))
        print(f"[{status}] {c['id']} ({c['clause']}; rows {c['row']}) {time.monotonic() - t0:.1f}s", flush=True)
        for f in t.fails:
            print(f"    FAIL: {f}", flush=True)
        for n in t.notes:
            print(f"    note: {n}", flush=True)
    npass = sum(r["status"] == "PASS" for r in results)
    print(f"\nTOTAL {len(results)} checks: {npass} passed, {len(results) - npass} failed; {len(AUDIT)} HTTP requests")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(results, f, indent=1)
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
