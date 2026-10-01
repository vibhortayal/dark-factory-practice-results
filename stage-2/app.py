"""Pocketful stage 1: payments, requests, splits, activity feed, settlements.

Standard library only. All state lives in memory behind one lock: every money
movement is one critical section, so the three invariants of the spec hold under
concurrency by construction.
"""
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import signal
import sys
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

MAX_AMOUNT = 1_000_000_000
MAX_BALANCE = 2 ** 53
HANDLE_RE = re.compile(r"[a-z0-9_]{1,20}")
STATUSES = ("pending", "paid", "declined", "cancelled")
AUTH_STATUSES = ("open", "captured", "voided", "expired")
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 12, 8, 1
FIXTURE_SCRYPT_N = 2 ** 9  # seeded users: keep a 5000-user reset well inside 10 s
MAX_BODY = 8 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, status, code, message=""):
        super().__init__(message or code)
        self.status, self.code, self.message = status, code, message or code


def err(status, code, message=""):
    return ApiError(status, code, message)


# --------------------------------------------------------------------------
# JSON helpers
# --------------------------------------------------------------------------

def _parse_int(s):
    return int(s) if len(s) <= 30 else Decimal(s)


def _bad_constant(s):
    raise ValueError("bad constant " + s)


class Huge:
    """A JSON number too large for Decimal: never a valid amount, kept as text."""

    def __init__(self, text):
        self.text = text


def _parse_float(s):
    try:
        return Decimal(s)
    except ArithmeticError:
        return Huge(s)


def parse_json(raw):
    try:
        text = raw.decode("utf-8")
        return json.loads(text, parse_float=_parse_float, parse_int=_parse_int,
                          parse_constant=_bad_constant)
    except (ValueError, RecursionError, ArithmeticError):
        raise err(400, "malformed_request", "body is not valid JSON")


def num_canon(x):
    """Exact canonical text of a number: 1000, 1000.0 and 1e3 agree; no rounding."""
    sign, digits, exp = Decimal(x).as_tuple()
    digits = list(digits)
    while digits and digits[-1] == 0:
        digits.pop()
        exp += 1
    if not digits:
        return "0"
    return "%s%se%d" % ("-" if sign else "", "".join(map(str, digits)), exp)


def canon(v):
    """Canonical string for JSON-value equality (key order, whitespace, 1000 == 1e3)."""
    def conv(x):
        if isinstance(x, Huge):
            return ["h", x.text]
        if x is None:
            return ["z"]
        if isinstance(x, bool):
            return ["b", x]
        if isinstance(x, (int, Decimal)):
            return ["n", num_canon(x)]
        if isinstance(x, str):
            return ["s", x]
        if isinstance(x, list):
            return ["a", [conv(i) for i in x]]
        if isinstance(x, dict):
            return ["o", sorted([k, conv(i)] for k, i in x.items())]
        raise ValueError("unsupported")
    try:
        return json.dumps(conv(v), sort_keys=True)
    except RecursionError:
        raise err(400, "malformed_request", "body too deeply nested")


def dumps(obj):
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def fx_int(v):
    """Integral number (1000, 1000.0, 1e3) -> int, else None."""
    if is_int(v):
        return v
    if isinstance(v, Decimal) and v.is_finite() and v.adjusted() <= 30 \
            and v == v.to_integral_value():
        return int(v)
    return None


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def to_amount(v):
    """Return an int amount in 1..MAX_AMOUNT, or raise 422."""
    n = None
    if is_int(v):
        n = v
    elif isinstance(v, Decimal) and v.is_finite():
        if v.adjusted() <= 30 and v == v.to_integral_value():
            n = int(v)
    if n is None or n < 1 or n > MAX_AMOUNT:
        raise err(422, "validation_failed", "amount must be an integer from 1 to 1000000000")
    return n


def now_dt():
    return datetime.now(timezone.utc)


def now_ms():
    return now_dt().isoformat(timespec="milliseconds")


def now_str():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@lru_cache(maxsize=65536)
def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def hash_password(password, salt=None, n=SCRYPT_N):
    """scrypt with a per-hash salt; the cost parameters are stored inside the hash string,
    so hashes made with other parameters (e.g. a stage-1 export) still verify."""
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt, n=n, r=SCRYPT_R,
                       p=SCRYPT_P, maxmem=64 * 1024 * 1024, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (n, SCRYPT_R, SCRYPT_P, salt.hex(), h.hex())


def verify_password(password, stored):
    try:
        _, n, r, p, salt, h = stored.split("$")
        calc = hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=bytes.fromhex(salt), n=int(n),
                              r=int(r), p=int(p), maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------

class State:
    """All service state. Everything in here is plain JSON-able data."""

    def __init__(self):
        self.currency = "EUR"
        self.minor_units = 2
        self.users = {}        # id -> {id,email,display_name,handle,balance,password_hash}
        self.by_handle = {}
        self.by_email = {}
        self.tokens = {}       # sha256(token) -> user id
        self.payments = {}     # id -> payment dict (insertion order = oldest first)
        self.requests = {}
        self.splits = {}
        self.settlements = {}
        self.idem = {}         # (user_id, key, path) -> {"body": canon, "response": obj}
        self.operators = []
        self.authorizations = {}   # id -> authorization dict (insertion order = oldest first)
        self.open_auths = {}       # id -> authorization dict, status "open" only
        self.ttl = 600
        self.counters = {"p": 0, "rq": 0, "sp": 0, "st": 0, "u": 0, "a": 0}

    # -- ids
    def new_id(self, kind, table):
        while True:
            self.counters[kind] += 1
            i = "%s_%d" % (kind, self.counters[kind])
            if i not in table:
                return i

    def new_user_id(self):
        return self.new_id("u", self.users)

    # -- serialisation
    def export(self):
        return {
            "currency": self.currency,
            "minor_units": self.minor_units,
            "users": [dict(u) for u in self.users.values()],
            "tokens": dict(self.tokens),
            "payments": [dict(p) for p in self.payments.values()],
            "requests": [dict(r) for r in self.requests.values()],
            "splits": copy.deepcopy(list(self.splits.values())),
            "settlements": copy.deepcopy(list(self.settlements.values())),
            "idempotency": [{"user_id": k[0], "key": k[1], "path": k[2], "body": v["body"],
                             "response": copy.deepcopy(v["response"])}
                            for k, v in self.idem.items()],
            "operators": list(self.operators),
            "counters": dict(self.counters),
            "authorizations": [dict(a, payment_ids=list(a["payment_ids"]))
                               for a in self.authorizations.values()],
            "authorization_ttl_seconds": self.ttl,
        }

    @staticmethod
    def load(d):
        """Build a State from exported data, validating it. Raises ValueError."""
        def need(cond):
            if not cond:
                raise ValueError("invalid state")

        def is_str(x):
            return isinstance(x, str)

        need(isinstance(d, dict))

        def plain(x):
            if isinstance(x, dict):
                return all(isinstance(k, str) and plain(v) for k, v in x.items())
            if isinstance(x, list):
                return all(plain(v) for v in x)
            return x is None or isinstance(x, (str, bool, int)) and not isinstance(x, Huge)
        need(plain(d))
        s = State()
        need(is_str(d["currency"]) and d["currency"])
        need(is_int(d["minor_units"]) and d["minor_units"] in (0, 2, 3))
        s.currency, s.minor_units = d["currency"], d["minor_units"]
        for u in d["users"]:
            need(isinstance(u, dict))
            for f in ("id", "email", "display_name", "handle", "password_hash"):
                need(is_str(u[f]))
            need(is_int(u["balance"]) and 0 <= u["balance"] <= MAX_BALANCE)
            need(HANDLE_RE.fullmatch(u["handle"]))
            need(u["id"] not in s.users and u["handle"] not in s.by_handle
                 and u["email"].lower() not in s.by_email)
            need(len(u["id"]) <= 64)
            rec = {k: u[k] for k in ("id", "email", "display_name", "handle", "balance",
                                     "password_hash")}
            s.users[rec["id"]] = rec
            s.by_handle[rec["handle"]] = rec
            s.by_email[rec["email"].lower()] = rec
        tokens = d["tokens"]
        need(isinstance(tokens, dict))
        for k, v in tokens.items():
            need(is_str(k) and v in s.users)
        s.tokens = dict(tokens)
        for p in d["payments"]:
            need(isinstance(p, dict))
            for f in ("payment_id", "from_user_id", "to_user_id", "note", "visibility",
                      "created_at"):
                need(is_str(p[f]))
            need(p["from_user_id"] in s.users and p["to_user_id"] in s.users)
            need(is_int(p["amount"]) and p["amount"] >= 0 and p["visibility"] in
                 ("public", "private"))
            need(p["request_id"] is None or is_str(p["request_id"]))
            need(p["settlement_id"] is None or is_str(p["settlement_id"]))
            need(p.get("authorization_id") is None or is_str(p["authorization_id"]))
            p = dict(p, authorization_id=p.get("authorization_id"))
            need(isinstance(p["seq"], int) and p["payment_id"] not in s.payments)
            need(parse_ts(p["created_at"]).tzinfo is not None)
            s.payments[p["payment_id"]] = dict(p)
        for r in d["requests"]:
            need(isinstance(r, dict))
            for f in ("request_id", "requester_id", "payer_id", "note", "created_at"):
                need(is_str(r[f]))
            need(r["requester_id"] in s.users and r["payer_id"] in s.users)
            need(is_int(r["amount"]) and r["amount"] >= 0 and r["status"] in STATUSES)
            need(r["payment_id"] is None or is_str(r["payment_id"]))
            need(isinstance(r["seq"], int) and r["request_id"] not in s.requests)
            need(parse_ts(r["created_at"]).tzinfo is not None)
            s.requests[r["request_id"]] = dict(r)
        for key, table in (("splits", s.splits), ("settlements", s.settlements)):
            for x in d[key]:
                need(isinstance(x, dict))
                idk = "split_id" if key == "splits" else "settlement_id"
                need(is_str(x[idk]) and isinstance(x["response"], dict))
                table[x[idk]] = copy.deepcopy(x)
        for e in d["idempotency"]:
            need(isinstance(e, dict) and is_str(e["user_id"]) and is_str(e["key"])
                 and is_str(e["path"]) and is_str(e["body"]) and isinstance(e["response"], dict))
            s.idem[(e["user_id"], e["key"], e["path"])] = {
                "body": e["body"], "response": copy.deepcopy(e["response"])}
        need(isinstance(d["operators"], list) and all(is_str(o) for o in d["operators"]))
        s.operators = list(d["operators"])
        c = d["counters"]
        need(isinstance(c, dict) and all(is_int(c.get(k, 0 if k == "a" else None))
                                         for k in s.counters))
        s.counters = {k: c.get(k, 0) for k in s.counters}
        ttl = d.get("authorization_ttl_seconds", 600)
        need(is_int(ttl) and ttl > 0)
        s.ttl = ttl
        for a in d.get("authorizations", []):
            need(isinstance(a, dict))
            for f in ("authorization_id", "from_user_id", "to_user_id", "note", "visibility",
                      "status", "expires_at", "created_at"):
                need(is_str(a[f]))
            need(a["from_user_id"] in s.users and a["to_user_id"] in s.users)
            need(len(a["authorization_id"]) <= 64 and a["authorization_id"] not in s.authorizations)
            need(is_int(a["amount"]) and a["amount"] >= 1)
            need(is_int(a["captured_amount"]) and 0 <= a["captured_amount"] <= a["amount"])
            need(a["visibility"] in ("public", "private") and a["status"] in AUTH_STATUSES)
            need(isinstance(a["payment_ids"], list) and all(is_str(x) for x in a["payment_ids"]))
            need(isinstance(a["seq"], int))
            need(parse_ts(a["expires_at"]).tzinfo is not None)
            need(parse_ts(a["created_at"]).tzinfo is not None)
            rec = {k: a[k] for k in ("authorization_id", "from_user_id", "to_user_id", "amount",
                                     "captured_amount", "note", "visibility", "status",
                                     "expires_at", "created_at", "seq")}
            rec["payment_ids"] = list(a["payment_ids"])
            s.authorizations[rec["authorization_id"]] = rec
            if rec["status"] == "open":
                s.open_auths[rec["authorization_id"]] = rec
        s.check_holds()
        return s

    def check_holds(self, raising=ValueError):
        """Seeded/imported unexpired open holds must fit inside each payer's balance."""
        now = now_dt()
        held = {}
        for a in self.open_auths.values():
            if parse_ts(a["expires_at"]) > now:
                held[a["from_user_id"]] = held.get(a["from_user_id"], 0) + a["amount"] - a["captured_amount"]
        for uid, h in held.items():
            if h > self.users[uid]["balance"]:
                raise raising("holds exceed balance")

    # -- fixture
    @staticmethod
    def from_fixture(fx):
        def need(cond, msg="invalid fixture"):
            if not cond:
                raise err(422, "validation_failed", msg)

        need(isinstance(fx, dict), "fixture must be an object")
        s = State()
        cur = fx.get("currency")
        need(isinstance(cur, str) and cur, "currency required")
        mu = fx_int(fx.get("minor_units"))
        need(is_int(mu) and mu in (0, 2, 3), "minor_units must be 0, 2 or 3")
        s.currency, s.minor_units = cur, mu
        users = fx.get("users", [])
        need(isinstance(users, list), "users must be a list")
        pending = []
        for u in users:
            need(isinstance(u, dict), "user must be an object")
            uid, email, pw = u.get("id"), u.get("email"), u.get("password")
            name, handle, bal = u.get("display_name"), u.get("handle"), fx_int(u.get("balance", 0))
            need(isinstance(uid, str) and 0 < len(uid) <= 64, "user id")
            need(isinstance(email, str) and email, "user email")
            need(isinstance(pw, str), "user password")
            need(isinstance(name, str), "user display_name")
            need(isinstance(handle, str) and HANDLE_RE.fullmatch(handle), "user handle")
            need(is_int(bal) and 0 <= bal <= MAX_BALANCE, "balance must be an integer >= 0")
            need(uid not in s.users and handle not in s.by_handle
                 and email.lower() not in s.by_email, "duplicate user")
            rec = {"id": uid, "email": email, "display_name": name, "handle": handle,
                   "balance": bal, "password_hash": None}
            pending.append((rec, pw))
            s.users[uid] = rec
            s.by_handle[handle] = rec
            s.by_email[email.lower()] = rec
        if pending:
            with ThreadPoolExecutor(max_workers=8) as ex:
                for (rec, _), h in zip(pending, ex.map(lambda t: hash_password(t[1], n=FIXTURE_SCRYPT_N), pending)):
                    rec["password_hash"] = h
        if "authorization_ttl_seconds" in fx:
            ttl = fx_int(fx["authorization_ttl_seconds"])
            need(is_int(ttl) and ttl > 0, "authorization_ttl_seconds must be a positive integer")
            s.ttl = ttl
        ops = fx.get("settlement_operator_ids", [])
        need(isinstance(ops, list) and all(isinstance(o, str) for o in ops),
             "settlement_operator_ids must be a list of ids")
        s.operators = list(ops)
        payments = fx.get("payments", [])
        requests = fx.get("requests", [])
        need(isinstance(payments, list) and isinstance(requests, list), "lists expected")
        base = now_str()
        total = len(payments) + len(requests)
        for i, p in enumerate(payments):
            need(isinstance(p, dict), "payment must be an object")
            pid = p.get("id")
            need(isinstance(pid, str) and 0 < len(pid) <= 64 and pid not in s.payments)
            need(p.get("from_user_id") in s.users and p.get("to_user_id") in s.users,
                 "payment parties")
            amt = fx_int(p.get("amount"))
            need(is_int(amt) and amt >= 0, "payment amount")
            note = p.get("note", "")
            need(isinstance(note, str), "payment note")
            vis = p.get("visibility", "public")
            need(vis in ("public", "private"), "payment visibility")
            rid = p.get("request_id")
            need(rid is None or isinstance(rid, str), "payment request_id")
            created = _fixture_ts(p, base, total - i, need)
            s.counters["p"] += 1
            s.payments[pid] = {
                "payment_id": pid, "from_user_id": p["from_user_id"],
                "to_user_id": p["to_user_id"], "amount": amt, "note": note,
                "visibility": vis, "request_id": rid, "settlement_id": None,
                "authorization_id": None, "created_at": created, "seq": s.counters["p"]}
        for i, r in enumerate(requests):
            need(isinstance(r, dict), "request must be an object")
            rid = r.get("id")
            need(isinstance(rid, str) and 0 < len(rid) <= 64 and rid not in s.requests)
            need(r.get("requester_id") in s.users and r.get("payer_id") in s.users,
                 "request parties")
            amt = fx_int(r.get("amount"))
            need(is_int(amt) and amt >= 0, "request amount")
            note = r.get("note", "")
            need(isinstance(note, str), "request note")
            status = r.get("status", "pending")
            need(status in STATUSES, "request status")
            pid = r.get("payment_id")
            need(pid is None or isinstance(pid, str), "request payment_id")
            created = _fixture_ts(r, base, total - len(payments) - i, need)
            s.counters["rq"] += 1
            s.requests[rid] = {
                "request_id": rid, "requester_id": r["requester_id"],
                "payer_id": r["payer_id"], "amount": amt, "note": note, "status": status,
                "payment_id": pid, "created_at": created, "seq": s.counters["rq"]}
        auths = fx.get("authorizations", [])
        need(isinstance(auths, list), "authorizations must be a list")
        now = now_dt()
        for i, a in enumerate(auths):
            need(isinstance(a, dict), "authorization must be an object")
            aid = a.get("id")
            need(isinstance(aid, str) and 0 < len(aid) <= 64 and aid not in s.authorizations,
                 "authorization id")
            need(a.get("from_user_id") in s.users and a.get("to_user_id") in s.users,
                 "authorization parties")
            amt = fx_int(a.get("amount"))
            need(is_int(amt) and amt >= 1, "authorization amount")
            note = a.get("note", "")
            need(isinstance(note, str), "authorization note")
            vis = a.get("visibility", "public")
            need(vis in ("public", "private"), "authorization visibility")
            status = a.get("status", "open")
            need(status in AUTH_STATUSES, "authorization status")
            exp = a.get("expires_at")
            need(isinstance(exp, str), "authorization expires_at")
            try:
                exp_dt = parse_ts(exp)
            except ValueError:
                need(False, "authorization expires_at")
            need(exp_dt.tzinfo is not None, "authorization expires_at needs an offset")
            cap = a.get("captured_amount")
            if cap is None:
                cap = amt if status == "captured" else 0
            else:
                cap = fx_int(cap)
                need(is_int(cap) and 0 <= cap <= amt, "authorization captured_amount")
            pid = a.get("payment_id")
            need(pid is None or isinstance(pid, str), "authorization payment_id")
            created = _fixture_ts(a, base, len(auths) - i, need)
            if status == "open" and exp_dt <= now:
                status = "expired"
            s.counters["a"] += 1
            rec = {"authorization_id": aid, "from_user_id": a["from_user_id"],
                   "to_user_id": a["to_user_id"], "amount": amt, "captured_amount": cap,
                   "note": note, "visibility": vis, "status": status, "expires_at": exp,
                   "payment_ids": [pid] if pid else [], "created_at": created,
                   "seq": s.counters["a"]}
            s.authorizations[aid] = rec
            if status == "open":
                s.open_auths[aid] = rec
        s.check_holds(lambda m: err(422, "validation_failed", m))
        return s


def _fixture_ts(item, base, back, need):
    ts = item.get("created_at")
    if ts is None:
        # Fixture order is oldest-first; every seeded item predates "now" by a distinct
        # number of seconds, with the earliest listed being the oldest.
        return (parse_ts(base) - _seconds(back)).isoformat(timespec="seconds")
    need(isinstance(ts, str), "created_at")
    try:
        d = parse_ts(ts)
    except ValueError:
        need(False, "created_at")
    need(d.tzinfo is not None, "created_at needs an offset")
    return ts


def _seconds(n):
    return timedelta(seconds=n)


# --------------------------------------------------------------------------
# Service logic (every function below runs with LOCK held)
# --------------------------------------------------------------------------

LOCK = threading.RLock()
STATE = State()
_seq = {"n": 1_000_000}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def sort_key(item):
    return (parse_ts(item["created_at"]), item["seq"])


def payment_view(p):
    st = STATE
    return {
        "payment_id": p["payment_id"],
        "from_user_id": p["from_user_id"],
        "from_handle": st.users[p["from_user_id"]]["handle"],
        "to_user_id": p["to_user_id"],
        "to_handle": st.users[p["to_user_id"]]["handle"],
        "amount": p["amount"],
        "currency": st.currency,
        "note": p["note"],
        "visibility": p["visibility"],
        "request_id": p["request_id"],
        "settlement_id": p["settlement_id"],
        "authorization_id": p.get("authorization_id"),
        "created_at": p["created_at"],
    }


def request_view(r):
    st = STATE
    return {
        "request_id": r["request_id"],
        "requester_id": r["requester_id"],
        "requester_handle": st.users[r["requester_id"]]["handle"],
        "payer_id": r["payer_id"],
        "payer_handle": st.users[r["payer_id"]]["handle"],
        "amount": r["amount"],
        "currency": st.currency,
        "note": r["note"],
        "status": r["status"],
        "payment_id": r["payment_id"],
        "created_at": r["created_at"],
    }


def move(sender, receiver, amount, note, visibility, request_id, settlement_id, created_at,
         authorization_id=None):
    st = STATE
    sender["balance"] -= amount
    receiver["balance"] += amount
    pid = st.new_id("p", st.payments)
    p = {"payment_id": pid, "from_user_id": sender["id"], "to_user_id": receiver["id"],
         "amount": amount, "note": note, "visibility": visibility, "request_id": request_id,
         "settlement_id": settlement_id, "authorization_id": authorization_id,
         "created_at": created_at, "seq": next_seq()}
    st.payments[pid] = p
    return p


def sweep():
    """Close open authorizations whose deadline has passed (called on every request)."""
    st = STATE
    if not st.open_auths:
        return
    now = now_dt()
    for aid in [k for k, a in st.open_auths.items() if parse_ts(a["expires_at"]) <= now]:
        st.open_auths.pop(aid)["status"] = "expired"


def remaining(a):
    return a["amount"] - a["captured_amount"] if a["status"] == "open" else 0


def held_of(uid):
    return sum(remaining(a) for a in STATE.open_auths.values() if a["from_user_id"] == uid)


def available_of(user):
    return user["balance"] - held_of(user["id"])


def authorization_view(a):
    st = STATE
    return {
        "authorization_id": a["authorization_id"],
        "from_user_id": a["from_user_id"],
        "from_handle": st.users[a["from_user_id"]]["handle"],
        "to_user_id": a["to_user_id"],
        "to_handle": st.users[a["to_user_id"]]["handle"],
        "amount": a["amount"],
        "captured_amount": a["captured_amount"],
        "remaining_amount": remaining(a),
        "currency": st.currency,
        "note": a["note"],
        "visibility": a["visibility"],
        "status": a["status"],
        "expires_at": a["expires_at"],
        "payment_id": a["payment_ids"][-1] if a["payment_ids"] else None,
        "payment_ids": list(a["payment_ids"]),
        "created_at": a["created_at"],
    }


def need_body_object(body):
    if not isinstance(body, dict):
        raise err(400, "malformed_request", "body must be a JSON object")


def get_note(body):
    if "note" not in body:
        return ""
    note = body["note"]
    if not isinstance(note, str) or len(note) > 200:
        raise err(422, "validation_failed", "note must be a string of at most 200 characters")
    return note


def get_visibility(body):
    if "visibility" not in body:
        return "public"
    v = body["visibility"]
    if not isinstance(v, str) or v not in ("public", "private"):
        raise err(422, "validation_failed", "visibility must be public or private")
    return v


def need_str_field(body, name):
    """Wrong JSON type -> 400, missing -> 422."""
    if name in body and not isinstance(body[name], str):
        raise err(400, "malformed_request", "%s must be a string" % name)


def require_field(body, name):
    if name not in body:
        raise err(422, "validation_failed", "%s is required" % name)


def lookup_handle(handle):
    u = STATE.by_handle.get(handle)
    if u is None:
        raise err(404, "not_found", "no such user")
    return u


def idem_key_of(headers):
    key = headers.get("Idempotency-Key")
    if key is None or key == "":
        raise err(400, "missing_idempotency_key", "Idempotency-Key header is required")
    try:
        key = key.encode("latin-1").decode("utf-8")
    except (UnicodeError, ValueError):
        pass
    if len(key) > 255:
        raise err(422, "validation_failed", "Idempotency-Key is at most 255 characters")
    return key


def idempotent(user, path, headers, body, handler):
    """Shared flow for the five idempotent writes. `body` is the parsed JSON."""
    key = idem_key_of(headers)
    need_body_object(body)
    cb = canon(body)
    claimed = STATE.idem.get((user["id"], key, path))
    if claimed is not None:
        if claimed["body"] == cb:
            return 200, claimed["response"]
        raise err(409, "idempotency_key_reuse", "key already used with a different body")
    response = handler(user, body)
    STATE.idem[(user["id"], key, path)] = {"body": cb, "response": response}
    return 201, response


def do_payment(user, body):
    need_str_field(body, "to_handle")
    require_field(body, "to_handle")
    amount = to_amount(body.get("amount"))
    note = get_note(body)
    vis = get_visibility(body)
    to = lookup_handle(body["to_handle"])
    if to["id"] == user["id"]:
        raise err(422, "self_payment", "cannot pay yourself")
    if available_of(user) < amount:
        raise err(409, "insufficient_funds", "insufficient funds")
    p = move(user, to, amount, note, vis, None, None, now_str())
    return payment_view(p)


def do_authorization(user, body):
    need_str_field(body, "to_handle")
    require_field(body, "to_handle")
    amount = to_amount(body.get("amount"))
    note = get_note(body)
    vis = get_visibility(body)
    to = lookup_handle(body["to_handle"])
    if to["id"] == user["id"]:
        raise err(422, "self_payment", "cannot authorize a payment to yourself")
    if available_of(user) < amount:
        raise err(409, "insufficient_funds", "insufficient available funds")
    st = STATE
    aid = st.new_id("a", st.authorizations)
    created = now_dt().replace(microsecond=now_dt().microsecond // 1000 * 1000)
    a = {"authorization_id": aid, "from_user_id": user["id"], "to_user_id": to["id"],
         "amount": amount, "captured_amount": 0, "note": note, "visibility": vis,
         "status": "open",
         "expires_at": (created + timedelta(seconds=st.ttl)).isoformat(timespec="milliseconds"),
         "payment_ids": [], "created_at": created.isoformat(timespec="milliseconds"),
         "seq": next_seq()}
    st.authorizations[aid] = a
    st.open_auths[aid] = a
    return authorization_view(a)


def make_capture(aid):
    def do_capture(user, body):
        a = STATE.authorizations.get(aid)
        if a is None:
            raise err(404, "not_found", "no such authorization")
        if a["to_user_id"] != user["id"]:
            raise err(403, "forbidden", "only the receiver may capture")
        if "final" in body and not isinstance(body["final"], bool):
            raise err(400, "malformed_request", "final must be a boolean")
        amount = to_amount(body["amount"]) if "amount" in body else None
        if a["status"] == "expired":
            raise err(409, "authorization_expired", "authorization has expired")
        if a["status"] != "open":
            raise err(409, "authorization_not_open", "authorization is not open")
        rem = remaining(a)
        if amount is None:
            amount = rem
        if amount > rem:
            raise err(422, "capture_exceeds_authorization", "capture exceeds the remaining amount")
        payer, receiver = STATE.users[a["from_user_id"]], STATE.users[a["to_user_id"]]
        p = move(payer, receiver, amount, a["note"], a["visibility"], None, None, now_str(), aid)
        a["captured_amount"] += amount
        a["payment_ids"].append(p["payment_id"])
        if body.get("final", True) or a["captured_amount"] >= a["amount"]:
            a["status"] = "captured"
            STATE.open_auths.pop(aid, None)
        return payment_view(p)
    return do_capture


def void_authorization(user, aid):
    a = STATE.authorizations.get(aid)
    if a is None:
        raise err(404, "not_found", "no such authorization")
    if a["from_user_id"] != user["id"]:
        raise err(403, "forbidden", "only the payer may void")
    if a["status"] == "voided":
        return authorization_view(a)
    if a["status"] != "open":
        raise err(409, "authorization_not_open", "authorization is not open")
    a["status"] = "voided"
    STATE.open_auths.pop(aid, None)
    return authorization_view(a)


def do_request(user, body):
    need_str_field(body, "payer_handle")
    require_field(body, "payer_handle")
    amount = to_amount(body.get("amount"))
    note = get_note(body)
    payer = lookup_handle(body["payer_handle"])
    if payer["id"] == user["id"]:
        raise err(422, "self_request", "cannot request money from yourself")
    st = STATE
    rid = st.new_id("rq", st.requests)
    r = {"request_id": rid, "requester_id": user["id"], "payer_id": payer["id"],
         "amount": amount, "note": note, "status": "pending", "payment_id": None,
         "created_at": now_str(), "seq": next_seq()}
    st.requests[rid] = r
    return request_view(r)


def make_pay(rid):
    def do_pay(user, body):
        r = STATE.requests.get(rid)
        if r is None:
            raise err(404, "not_found", "no such request")
        if r["payer_id"] != user["id"]:
            raise err(403, "forbidden", "only the payer may pay")
        vis = get_visibility(body)
        if r["status"] != "pending":
            raise err(409, "request_not_pending", "request is not pending")
        if available_of(user) < r["amount"]:
            raise err(409, "insufficient_funds", "insufficient funds")
        p = move(user, STATE.users[r["requester_id"]], r["amount"], r["note"], vis,
                 r["request_id"], None, now_str())
        r["status"] = "paid"
        r["payment_id"] = p["payment_id"]
        return payment_view(p)
    return do_pay


def equal_split(amount, n):
    base, rem = divmod(amount, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def do_split(user, body):
    if "participant_handles" in body:
        ph = body["participant_handles"]
        if not isinstance(ph, list) or not all(isinstance(h, str) for h in ph):
            raise err(400, "malformed_request", "participant_handles must be a list of strings")
    require_field(body, "participant_handles")
    amount = to_amount(body.get("amount"))
    note = get_note(body)
    handles = body["participant_handles"]
    if not handles or len(set(handles)) != len(handles):
        raise err(422, "validation_failed", "participant_handles must be unique and non-empty")
    people = [lookup_handle(h) for h in handles]
    shares = equal_split(amount, len(people))
    st = STATE
    created = now_str()
    reqs = []
    for person, share in zip(people, shares):
        if person["id"] == user["id"]:
            continue
        rid = st.new_id("rq", st.requests)
        r = {"request_id": rid, "requester_id": user["id"], "payer_id": person["id"],
             "amount": share, "note": note, "status": "pending", "payment_id": None,
             "created_at": created, "seq": next_seq()}
        st.requests[rid] = r
        reqs.append(request_view(r))
    sid = st.new_id("sp", st.splits)
    resp = {"split_id": sid, "amount": amount, "currency": st.currency, "note": note,
            "shares": [{"handle": h, "amount": a} for h, a in zip(handles, shares)],
            "requests": reqs, "created_at": created}
    st.splits[sid] = {"split_id": sid, "response": resp}
    return resp


def do_settlement(user, body):
    st = STATE
    if user["id"] not in st.operators:
        raise err(403, "forbidden", "operators only")
    transfers = body.get("transfers")
    if not isinstance(transfers, list) or not 1 <= len(transfers) <= 32:
        raise err(422, "validation_failed", "transfers must be a list of 1 to 32 objects")
    if not all(isinstance(t, dict) for t in transfers):
        raise err(422, "validation_failed", "each transfer must be an object")
    parsed = []
    for t in transfers:
        need_str_field(t, "from_handle")
        need_str_field(t, "to_handle")
        require_field(t, "from_handle")
        require_field(t, "to_handle")
        amount = to_amount(t.get("amount"))
        note = get_note(t)
        vis = get_visibility(t)
        sender = lookup_handle(t["from_handle"])
        receiver = lookup_handle(t["to_handle"])
        if sender["id"] == receiver["id"]:
            raise err(422, "self_payment", "cannot pay yourself")
        parsed.append((sender, receiver, amount, note, vis))
    delta = {}
    for sender, receiver, amount, _, _ in parsed:
        delta[sender["id"]] = delta.get(sender["id"], 0) - amount
        delta[receiver["id"]] = delta.get(receiver["id"], 0) + amount
    for uid, d in delta.items():
        if st.users[uid]["balance"] + d - held_of(uid) < 0:
            raise err(409, "insufficient_funds", "settlement is not affordable")
    sid = st.new_id("st", st.settlements)
    committed = now_str()
    payments = [payment_view(move(s, r, a, n, v, None, sid, committed))
                for s, r, a, n, v in parsed]
    resp = {"settlement_id": sid, "committed_at": committed, "payments": payments}
    st.settlements[sid] = {"settlement_id": sid, "response": resp}
    return resp


# -- reads

def parse_page(query):
    def num(name, default, lo, hi):
        vals = query.get(name)
        if not vals:
            return default
        v = vals[0]
        if not re.fullmatch(r"[0-9]+", v):
            raise err(422, "validation_failed", "%s must be plain decimal digits" % name)
        n = int(v) if len(v) <= 18 else 10 ** 18
        if n < lo or (hi is not None and n > hi):
            raise err(422, "validation_failed", "%s out of range" % name)
        return n
    limit = num("limit", 50, 1, 200)
    offset = num("offset", 0, 0, None)
    return limit, offset


def page(items, limit, offset):
    return items[offset:offset + limit], offset + limit < len(items)


def list_requests(user, query):
    limit, offset = parse_page(query)
    direction = query["direction"][0] if "direction" in query else None
    status = query["status"][0] if "status" in query else None
    if direction is not None and direction not in ("incoming", "outgoing"):
        raise err(422, "validation_failed", "bad direction")
    if status is not None and status not in STATUSES:
        raise err(422, "validation_failed", "bad status")
    uid = user["id"]
    rows = []
    for r in STATE.requests.values():
        if direction == "incoming":
            ok = r["payer_id"] == uid
        elif direction == "outgoing":
            ok = r["requester_id"] == uid
        else:
            ok = uid in (r["payer_id"], r["requester_id"])
        if ok and (status is None or r["status"] == status):
            rows.append(r)
    rows.sort(key=sort_key, reverse=True)
    chunk, more = page(rows, limit, offset)
    return {"requests": [request_view(r) for r in chunk], "has_more": more}


def list_authorizations(user, query):
    limit, offset = parse_page(query)
    direction = query["direction"][0] if "direction" in query else None
    status = query["status"][0] if "status" in query else None
    if direction is not None and direction not in ("incoming", "outgoing"):
        raise err(422, "validation_failed", "bad direction")
    if status is not None and status not in AUTH_STATUSES:
        raise err(422, "validation_failed", "bad status")
    uid = user["id"]
    rows = []
    for a in STATE.authorizations.values():
        if direction == "outgoing":
            ok = a["from_user_id"] == uid
        elif direction == "incoming":
            ok = a["to_user_id"] == uid
        else:
            ok = uid in (a["from_user_id"], a["to_user_id"])
        if ok and (status is None or a["status"] == status):
            rows.append(a)
    rows.sort(key=sort_key, reverse=True)
    chunk, more = page(rows, limit, offset)
    return {"authorizations": [authorization_view(a) for a in chunk], "has_more": more}


def list_activity(user, query):
    limit, offset = parse_page(query)
    uid = user["id"]
    rows = [p for p in STATE.payments.values()
            if p["visibility"] == "public" or uid in (p["from_user_id"], p["to_user_id"])]
    rows.sort(key=sort_key, reverse=True)
    chunk, more = page(rows, limit, offset)
    return {"payments": [payment_view(p) for p in chunk], "has_more": more}


def transition(user, rid, who, target):
    r = STATE.requests.get(rid)
    if r is None:
        raise err(404, "not_found", "no such request")
    if r[who] != user["id"]:
        raise err(403, "forbidden", "not permitted")
    if r["status"] == target:
        return request_view(r)
    if r["status"] != "pending":
        raise err(409, "request_not_pending", "request is not pending")
    r["status"] = target
    return request_view(r)


# -- auth

def derive_handle(email):
    local = email.rsplit("@", 1)[0].lower()
    return re.sub(r"[^a-z0-9_]", "_", local)[:20]


EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+")


def auth_fields(body, names):
    need_body_object(body)
    for n in names:
        if n in body and not isinstance(body[n], str):
            raise err(400, "malformed_request", "%s must be a string" % n)
    for n in names:
        if n not in body:
            raise err(422, "validation_failed", "%s is required" % n)


def issue_token(user):
    token = secrets.token_urlsafe(32)
    STATE.tokens[token_hash(token)] = user["id"]
    return {"user_id": user["id"], "display_name": user["display_name"], "token": token}


def signup(body):
    auth_fields(body, ("email", "password", "display_name"))
    email, password, name = body["email"], body["password"], body["display_name"]
    if not EMAIL_RE.fullmatch(email):
        raise err(422, "validation_failed", "email must look like local@domain")
    if len(password) < 8:
        raise err(422, "validation_failed", "password must be at least 8 characters")
    pwh = hash_password(password)  # slow: done before taking the lock by the caller
    return email, name, pwh


def finish_signup(email, name, pwh):
    st = STATE
    if email.lower() in st.by_email:
        raise err(409, "email_taken", "email already registered")
    handle = derive_handle(email)
    if handle in st.by_handle:
        raise err(409, "handle_taken", "derived handle is already taken")
    uid = st.new_user_id()
    rec = {"id": uid, "email": email, "display_name": name, "handle": handle, "balance": 0,
           "password_hash": pwh}
    st.users[uid] = rec
    st.by_handle[handle] = rec
    st.by_email[email.lower()] = rec
    return issue_token(rec)


# --------------------------------------------------------------------------
# HTTP layer
# --------------------------------------------------------------------------

def authenticate(headers):
    h = headers.get("Authorization")
    if not h:
        raise err(401, "unauthenticated", "missing bearer token")
    parts = h.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise err(401, "unauthenticated", "malformed bearer token")
    uid = STATE.tokens.get(token_hash(parts[1].strip()))
    if uid is None or uid not in STATE.users:
        raise err(401, "unauthenticated", "unknown token")
    sweep()
    return STATE.users[uid]


class Raw:
    """A non-JSON response body (the UI shell and its static assets)."""

    def __init__(self, body, ctype, cache="no-store"):
        self.body, self.ctype, self.cache = body, ctype, cache


ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
ASSET_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
               ".svg": "image/svg+xml", ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}
_assets = {}


def load_assets():
    for name in os.listdir(ASSET_DIR):
        ext = os.path.splitext(name)[1]
        if ext in ASSET_TYPES:
            with open(os.path.join(ASSET_DIR, name), "rb") as f:
                _assets["/static/" + name] = Raw(f.read(), ASSET_TYPES[ext], "no-cache")
    with open(os.path.join(ASSET_DIR, "index.html"), "rb") as f:
        _assets["shell"] = f.read()


def page_for(path):
    route = {"/": "home", "/requests": "requests", "/split": "split", "/signup": "signup",
             "/login": "login", "/authorizations": "authorizations"}[path]
    return Raw(_assets["shell"].replace(b"@@ROUTE@@", route.encode()), "text/html; charset=utf-8")


REQ_PATH = re.compile(r"/requests/([^/]+)/(pay|decline|cancel)")
AUTH_PATH = re.compile(r"/authorizations/([^/]+)/(capture|void)")
UI_ROUTES = ("/", "/split", "/signup", "/login")
SHARED_ROUTES = ("/requests", "/authorizations")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "pocketful"
    sys_version = ""

    def log_message(self, *a):
        pass

    def send_error(self, code, message=None, explain=None):
        if code >= 500:
            code = 400
        self.request_version = "HTTP/1.1"  # always answer with a real status line
        if not hasattr(self, "command") or self.command is None:
            self.command = "GET"
        self._send(code, {"error": {"code": "malformed_request", "message": message or "error"}},
                   close=True)

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self._handle
        raise AttributeError(name)

    def _send(self, status, obj=None, close=False):
        if isinstance(obj, Raw):
            data, ctype = obj.body, obj.ctype
        else:
            data, ctype = (b"" if obj is None else dumps(obj)), "application/json; charset=utf-8"
        self.send_response(status)
        if obj is not None:
            self.send_header("Content-Type", ctype)
        if isinstance(obj, Raw):
            self.send_header("Cache-Control", obj.cache)
        self.send_header("Content-Length", str(len(data)))
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if data and self.command != "HEAD":
            self.wfile.write(data)

    def _read_body(self):
        te = self.headers.get("Transfer-Encoding", "")
        if "chunked" in te.lower():
            chunks = []
            total = 0
            while True:
                line = self.rfile.readline(1024)
                size = int(line.split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline(1024).strip():
                        pass
                    break
                total += size
                if total > MAX_BODY:
                    raise err(400, "malformed_request", "body too large")
                chunks.append(self.rfile.read(size))
                self.rfile.readline(8)
            return b"".join(chunks)
        n = self.headers.get("Content-Length")
        if not n:
            return b""
        n = int(n)
        if n < 0 or n > MAX_BODY:
            self.close_connection = True
            raise err(400, "malformed_request", "bad content length")
        return self.rfile.read(n)

    def _handle(self):
        try:
            try:
                raw = self._read_body()
            except ApiError:
                raise
            except Exception:
                self.close_connection = True
                raise err(400, "malformed_request", "unreadable body")
            status, obj = self._route(raw)
            self._send(status, obj)
        except ApiError as e:
            self._send(e.status, {"error": {"code": e.code, "message": e.message}})
        except Exception as e:  # never leak a traceback; the contract says no 5xx, log it
            sys.stderr.write("internal error: %r\n" % (e,))
            self._send(500, {"error": {"code": "internal_error", "message": "internal error"}})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _handle

    def _route(self, raw):
        try:
            parts = urlsplit(self.path)
        except ValueError:
            raise err(400, "malformed_request", "bad request target")
        path = parts.path
        method = self.command
        query = parse_qs(parts.query, keep_blank_values=True)
        h = self.headers
        if path == "/health" and method == "GET":
            return 200, {"status": "ok"}
        if method in ("GET", "HEAD"):
            accept = (h.get("Accept") or "").lower()
            if path in UI_ROUTES or (path in SHARED_ROUTES and "text/html" in accept):
                return 200, page_for(path)
            if path in _assets and path.startswith("/static/"):
                return 200, _assets[path]
        if path == "/_test/reset" and method == "POST":
            return self._reset(raw)
        if path == "/_test/export" and method == "GET":
            with LOCK:
                sweep()
                snap = STATE.export()
            return 200, {"track": "pocketful", "format_version": 1, "state": snap}
        if path == "/_test/import" and method == "POST":
            return self._import(raw)
        if path in ("/auth/signup", "/auth/login") and method == "POST":
            body = parse_json(raw)
            if path == "/auth/login":
                return self._login(body)
            email, name, pwh = signup(body)
            with LOCK:
                return 201, finish_signup(email, name, pwh)

        m = REQ_PATH.fullmatch(path)
        am = AUTH_PATH.fullmatch(path)
        known = (method, path) in {("GET", "/me"), ("GET", "/activity"), ("GET", "/requests"),
                                   ("GET", "/authorizations"), ("POST", "/authorizations"),
                                   ("POST", "/payments"), ("POST", "/requests"),
                                   ("POST", "/splits"), ("POST", "/settlements")}
        if not known and not ((m or am) and method == "POST"):
            raise err(404, "not_found", "no such route")

        if method == "GET":
            with LOCK:
                user = authenticate(h)
                if path == "/me":
                    st = STATE
                    held = held_of(user["id"])
                    return 200, {"user_id": user["id"], "display_name": user["display_name"],
                                 "handle": user["handle"], "balance": user["balance"],
                                 "total": user["balance"], "available": user["balance"] - held,
                                 "held": held, "currency": st.currency,
                                 "minor_units": st.minor_units}
                if path == "/activity":
                    return 200, list_activity(user, query)
                if path == "/authorizations":
                    return 200, list_authorizations(user, query)
                return 200, list_requests(user, query)
        if m and m.group(2) in ("decline", "cancel"):
            with LOCK:
                user = authenticate(h)
                if m.group(2) == "decline":
                    return 200, transition(user, m.group(1), "payer_id", "declined")
                return 200, transition(user, m.group(1), "requester_id", "cancelled")

        if am and am.group(2) == "void":
            with LOCK:
                user = authenticate(h)
                return 200, void_authorization(user, am.group(1))

        # Idempotent writes. Key presence/length is checked before the body is parsed.
        with LOCK:
            user = authenticate(h)
            idem_key_of(h)
        if ((m and m.group(2) == "pay") or (am and am.group(2) == "capture")) and not raw.strip():
            body = {}
        else:
            body = parse_json(raw)
        with LOCK:
            user = authenticate(h)
            if m:
                handler = make_pay(m.group(1))
            elif am:
                handler = make_capture(am.group(1))
            else:
                handler = {"/payments": do_payment, "/requests": do_request,
                           "/splits": do_split, "/settlements": do_settlement,
                           "/authorizations": do_authorization}[path]
            return idempotent(user, path, h, body, handler)

    def _login(self, body):
        auth_fields(body, ("email", "password"))
        with LOCK:
            user = STATE.by_email.get(body["email"].lower())
            stored = user["password_hash"] if user else None
        ok = verify_password(body["password"], stored) if stored else False
        if not ok:
            if not stored:
                verify_password(body["password"], DUMMY_HASH)
            raise err(401, "unauthenticated", "invalid email or password")
        with LOCK:
            if STATE.users.get(user["id"]) is not user:
                raise err(401, "unauthenticated", "invalid email or password")
            return 200, issue_token(user)

    def _reset(self, raw):
        global STATE
        fx = parse_json(raw)
        try:
            new = State.from_fixture(fx)
        except ApiError:
            raise
        except Exception:
            raise err(422, "validation_failed", "invalid fixture")
        with LOCK:
            STATE = new
        return 204, None

    def _import(self, raw):
        global STATE
        doc = parse_json(raw)
        if not isinstance(doc, dict):
            raise err(422, "validation_failed", "import body must be an object")
        if doc.get("track") != "pocketful" or not is_int(doc.get("format_version")) \
                or doc.get("format_version") != 1 or not isinstance(doc.get("state"), dict):
            raise err(422, "validation_failed", "bad track, format_version or state")
        try:
            new = State.load(doc["state"])
        except Exception:
            raise err(422, "validation_failed", "invalid state")
        with LOCK:
            STATE = new
            top = max([p["seq"] for p in new.payments.values()]
                      + [r["seq"] for r in new.requests.values()]
                      + [a["seq"] for a in new.authorizations.values()] + [_seq["n"]])
            _seq["n"] = top
        return 204, None


DUMMY_HASH = hash_password("dummy-password")


def main():
    load_assets()
    port = int(os.environ.get("PORT") or 8080)
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer.request_queue_size = 256
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    signal.signal(signal.SIGTERM, lambda *a: os._exit(0))
    srv.serve_forever()


if __name__ == "__main__":
    main()
