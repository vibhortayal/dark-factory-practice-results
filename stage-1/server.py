"""Pocketful stage 1: payments and settlements. Standard library only, in-memory state."""
import datetime as dt
import decimal
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import _thread
from itertools import accumulate
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

MAX_AMOUNT = 1_000_000_000
MAX_BALANCE = 2 ** 53
MAX_BODY = 512 * 1024  # ordinary API endpoints
MAX_STRUCTURE = 16384  # bytes of non-string, non-whitespace JSON on ordinary endpoints
MAX_CONTROL_BODY = 512 * 1024 * 1024  # /_test/reset and /_test/import (memory guard)
CONTROL_PATHS = ("/_test/reset", "/_test/import")
MAX_DEPTH = 128
HANDLE_RE = re.compile(r"^[a-z0-9_]{1,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")
DIGITS_RE = re.compile(r"^[0-9]+$")
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
HASH_RE = re.compile(r"^scrypt\$\d+\$\d+\$\d+\$[0-9a-f]+\$[0-9a-f]+$")
DEFAULT_MINOR = {"EUR": 2, "JPY": 0, "BHD": 3}
STATUSES = ("pending", "paid", "declined", "cancelled")
EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
MISSING = object()


class ApiError(Exception):
    def __init__(self, status, code, message=None):
        super().__init__(message or code)
        self.status, self.code, self.message = status, code, message or code.replace("_", " ")


def bad(msg="invalid request"):
    return ApiError(422, "validation_failed", msg)


def malformed(msg="malformed request"):
    return ApiError(400, "malformed_request", msg)


# ---------------------------------------------------------------- JSON helpers

def _bad_constant(name):
    raise ValueError("bad constant " + name)


def _parse_float(s):
    try:
        return Decimal(s)
    except ArithmeticError:
        return Decimal("Infinity")


def _parse_int(s):
    return int(s) if len(s) <= 4000 else Decimal(s)


_STRING_RE = re.compile(rb'"[^"]*"')
_OPEN_RUN_RE = re.compile(rb"[\[{]{%d}" % (MAX_DEPTH + 1))  # fixed-length run: no backtracking
_DELTA = {91: 1, 123: 1, 93: -1, 125: -1}
_NOT_BRACKET = bytes(set(range(256)) - set(b"[]{}"))


def check_depth(structural):
    """Reject nesting deeper than MAX_DEPTH. `structural` has strings and whitespace removed; only
    brackets are kept and the maximum running open-minus-close balance (= depth) is taken with
    C-level iterators."""
    if structural.count(b"[") + structural.count(b"{") <= MAX_DEPTH:
        return
    br = structural.translate(None, _NOT_BRACKET)
    if max(accumulate(map(_DELTA.__getitem__, br), initial=0)) > MAX_DEPTH:
        raise malformed("body nested too deeply (limit %d)" % MAX_DEPTH)


def _load_exact(text):
    """Control-endpoint parse: ints as int, floats as Decimal (the C type is the hook)."""
    try:
        return json.loads(text, parse_float=Decimal, parse_constant=_bad_constant)
    except json.JSONDecodeError:
        raise
    except (ValueError, ArithmeticError):  # int literal beyond the digit limit / huge exponent
        return json.loads(text, parse_float=_parse_float, parse_int=_parse_int,
                          parse_constant=_bad_constant)


def _num(d):
    """Exact canonical text of a Decimal, independent of context precision: 1000 == 1000.0 == 1e3."""
    if not d.is_finite():
        return "inf" if d > 0 else "-inf"
    sign, digits, exp = d.as_tuple()
    s = "".join(map(str, digits)).lstrip("0")
    t = s.rstrip("0")
    if not t:
        return "0"
    return ("-" if sign else "") + t + "e" + str(exp + len(s) - len(t))


def _load_decimal(text):
    """Every number as Decimal (C type as both hooks); absurd exponents become Infinity."""
    try:
        return json.loads(text, parse_float=Decimal, parse_int=Decimal,
                          parse_constant=_bad_constant)
    except json.JSONDecodeError:
        raise
    except ArithmeticError:
        return json.loads(text, parse_float=_parse_float, parse_int=_parse_float,
                          parse_constant=_bad_constant)


def parse_body(raw, ordinary=True):
    """-> (value, digest). Ordinary endpoints (all work here is linear and runs outside the lock):
    parse first (a body that is not valid JSON is 400, so every string is terminated afterwards),
    then bound the JSON structure and nesting, then read every number exactly as a Decimal.

    digest = sha256(fingerprint + NUL + exact numbers): the fingerprint (numbers read as floats,
    keys sorted) fixes structure, strings and the kind of every scalar; the exact-number text makes
    numbers compare exactly. Two bodies are the same JSON value iff their digests are equal."""
    if not ordinary:
        try:
            return _load_exact(raw.decode("utf-8")), None
        except (ValueError, RecursionError, UnicodeDecodeError):
            raise malformed("body is not valid JSON")
    try:
        text = raw.decode("utf-8")
        fobj = json.loads(text, parse_float=float, parse_int=float, parse_constant=_bad_constant)
    except (ValueError, RecursionError, UnicodeDecodeError):
        raise malformed("body is not valid JSON")
    # Remove escaped backslashes, then escaped quotes: every quote left is a real string delimiter.
    cleaned = raw.replace(b"\\\\", b"").replace(b'\\"', b"")
    if cleaned.count(b'"') > 2 * MAX_STRUCTURE + 2:
        raise ApiError(413, "payload_too_large", "too many JSON tokens")
    structural = _STRING_RE.sub(b"", cleaned).translate(None, b" \t\r\n")
    if _OPEN_RUN_RE.search(structural):
        raise malformed("body nested too deeply (limit %d)" % MAX_DEPTH)
    if len(structural) > MAX_STRUCTURE:
        raise ApiError(413, "payload_too_large", "too many JSON tokens")
    check_depth(structural)
    try:
        alld = _load_decimal(text)
        fp = json.dumps(fobj, sort_keys=True, separators=(",", ":"))
        numtext = json.dumps(alld, sort_keys=True, separators=(",", ":"), default=_num)
    except (ValueError, RecursionError):
        raise malformed("body cannot be processed")
    return alld, hashlib.sha256((fp + "\x00" + numtext).encode("utf-8", "surrogatepass")).hexdigest()


def to_int(v, lo, hi):
    """An integral JSON number within [lo, hi] as int, or None."""
    if isinstance(v, bool) or not isinstance(v, (int, Decimal)):
        return None
    if isinstance(v, Decimal):
        if not v.is_finite() or v.adjusted() > 18:
            return None
        if v != v.to_integral_value():
            return None
        v = int(v)
    if v < lo or v > hi:
        return None
    return v


def parse_amount(v):
    a = to_int(v, 1, MAX_AMOUNT)
    if a is None:
        raise bad("amount must be an integer from 1 to 1000000000")
    return a


def parse_note(body):
    note = body.get("note", "")
    if not isinstance(note, str):
        raise bad("note must be a string")
    if len(note) > 200:
        raise bad("note too long")
    return note


def parse_visibility(body):
    vis = body.get("visibility", "public")
    if not isinstance(vis, str) or vis not in ("public", "private"):
        raise bad("visibility must be public or private")
    return vis


def split_checks(body, fields):
    """Two passes: wrong JSON type -> 400, then missing -> 422. fields: names of string fields."""
    for f in fields:
        if f in body and not isinstance(body[f], str):
            raise malformed(f + " must be a string")
    for f in fields:
        if f not in body:
            raise bad(f + " is required")


# ---------------------------------------------------------------- time

_ts_lock = threading.Lock()
_last_ts = [0]


def now_us():
    with _ts_lock:
        t = max(time.time_ns() // 1000, _last_ts[0] + 1)
        _last_ts[0] = t
        return t


def fmt_ts(us):
    return (EPOCH + dt.timedelta(microseconds=us)).isoformat(timespec="microseconds")


def parse_ts(s):
    if not isinstance(s, str):
        raise bad("created_at must be a string")
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00") if s.endswith("Z") else s)
    except ValueError:
        raise bad("invalid created_at")
    if d.tzinfo is None:
        raise bad("created_at needs an offset")
    delta = d - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


# ---------------------------------------------------------------- passwords

def hash_password(pw, n=2 ** 13):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode("utf-8", "surrogatepass"), salt=salt, n=n, r=8, p=1,
                       maxmem=64 * 1024 * 1024, dklen=32)
    return "scrypt$%d$8$1$%s$%s" % (n, salt.hex(), h.hex())


def verify_password(pw, stored):
    try:
        _, n, r, p, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode("utf-8", "surrogatepass"), salt=bytes.fromhex(salt),
                             n=int(n), r=int(r), p=int(p), maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(got.hex(), h)
    except Exception:
        return False


# ---------------------------------------------------------------- state

class State:
    def __init__(self):
        self.currency = "EUR"
        self.minor_units = 2
        self.users = {}
        self.by_email = {}
        self.by_handle = {}
        self.tokens = {}
        self.payments = {}
        self.pay_list = []
        self.requests = {}
        self.req_list = []
        self.idem = {}
        self.operators = set()
        self.counters = {"p": 0, "rq": 0, "sp": 0, "st": 0, "u": 0}
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq

    def next_id(self, prefix, taken=()):
        while True:
            self.counters[prefix] += 1
            i = "%s_%d" % (prefix, self.counters[prefix])
            if i not in taken:
                return i

    def add_user(self, u):
        self.users[u["id"]] = u
        self.by_email[u["email"]] = u["id"]
        self.by_handle[u["handle"]] = u["id"]

    # views
    def pay_view(self, p):
        return {
            "payment_id": p["id"], "from_user_id": p["from"],
            "from_handle": self.users[p["from"]]["handle"],
            "to_user_id": p["to"], "to_handle": self.users[p["to"]]["handle"],
            "amount": p["amount"], "currency": self.currency, "note": p["note"],
            "visibility": p["visibility"], "request_id": p["request_id"],
            "settlement_id": p["settlement_id"], "created_at": fmt_ts(p["ts"]),
        }

    def req_view(self, r):
        return {
            "request_id": r["id"], "requester_id": r["requester"],
            "requester_handle": self.users[r["requester"]]["handle"],
            "payer_id": r["payer"], "payer_handle": self.users[r["payer"]]["handle"],
            "amount": r["amount"], "currency": self.currency, "note": r["note"],
            "status": r["status"], "payment_id": r["payment_id"],
            "created_at": fmt_ts(r["ts"]),
        }

    def make_payment(self, frm, to, amount, note, visibility, request_id, settlement_id, ts):
        frm["balance"] -= amount
        to["balance"] += amount
        p = {"id": self.next_id("p", self.payments), "from": frm["id"], "to": to["id"],
             "amount": amount, "note": note, "visibility": visibility,
             "request_id": request_id, "settlement_id": settlement_id, "ts": ts,
             "seq": self.next_seq()}
        self.payments[p["id"]] = p
        self.pay_list.append(p)
        return p

    def make_request(self, requester, payer, amount, note, ts):
        r = {"id": self.next_id("rq", self.requests), "requester": requester["id"],
             "payer": payer["id"], "amount": amount, "note": note, "status": "pending",
             "payment_id": None, "ts": ts, "seq": self.next_seq()}
        self.requests[r["id"]] = r
        self.req_list.append(r)
        return r

    # export / import
    def export(self):
        return {
            "currency": self.currency, "minor_units": self.minor_units,
            "users": [{"id": u["id"], "email": u["email"], "handle": u["handle"],
                       "display_name": u["display_name"], "pw": u["pw"],
                       "balance": u["balance"]} for u in self.users.values()],
            "tokens": dict(self.tokens),
            "payments": [dict(p) for p in self.pay_list],
            "requests": [dict(r) for r in self.req_list],
            "idempotency": [{"user": k[0], "method": k[1], "path": k[2], "key": k[3],
                             "digest": v["digest"], "status": v["status"],
                             "response": v["response"]} for k, v in self.idem.items()],
            "operators": sorted(self.operators),
            "counters": dict(self.counters), "seq": self.seq, "last_ts": _last_ts[0],
        }


def need(cond, msg="invalid state"):
    if not cond:
        raise bad(msg)


def is_str(v, lo=0, hi=None):
    return isinstance(v, str) and len(v) >= lo and (hi is None or len(v) <= hi)


def check_id(v):
    need(is_str(v, 1, 64), "id must be a string of 1..64 characters")
    return v


def check_user_fields(u, st):
    check_id(u["id"])
    need(is_str(u["email"]) and is_str(u["display_name"]), "bad user")
    need(is_str(u["handle"]) and HANDLE_RE.fullmatch(u["handle"]), "bad handle")
    need(u["id"] not in st.users, "duplicate user id")
    need(u["email"] not in st.by_email, "duplicate email")
    need(u["handle"] not in st.by_handle, "duplicate handle")


def build_from_fixture(fx):
    need(isinstance(fx, dict), "fixture must be an object")
    st = State()
    cur = fx.get("currency", "EUR")
    need(is_str(cur, 1, 16), "currency must be a string")
    mu = to_int(fx["minor_units"], 0, 3) if "minor_units" in fx else DEFAULT_MINOR.get(cur, 2)
    need(mu in (0, 2, 3), "minor_units must be 0, 2 or 3")
    st.currency, st.minor_units = cur, mu
    users, payments, requests = (fx.get(k, []) for k in ("users", "payments", "requests"))
    ops = fx.get("settlement_operator_ids", [])
    for lst in (users, payments, requests, ops):
        need(isinstance(lst, list), "expected a list")
    pws = []
    for u in users:
        need(isinstance(u, dict), "user must be an object")
        for f in ("id", "email", "password", "display_name", "handle"):
            need(is_str(u.get(f)), "user." + f + " must be a string")
        bal = to_int(u.get("balance"), -MAX_BALANCE, MAX_BALANCE)
        need(bal is not None, "user.balance must be an integer")
        need(bal >= 0, "negative balance")
        pws.append(u["password"])
    with ThreadPoolExecutor(max_workers=4) as ex:
        hashes = list(ex.map(lambda p: hash_password(p, 2 ** 11), pws))
    for u, h in zip(users, hashes):
        rec = {"id": u["id"], "email": u["email"], "handle": u["handle"],
               "display_name": u["display_name"], "pw": h,
               "balance": to_int(u["balance"], 0, MAX_BALANCE)}
        check_user_fields(rec, st)
        st.add_user(rec)
    total = len(payments) + len(requests)
    base = now_us() - total - 1
    n = 0
    for p in payments:
        need(isinstance(p, dict), "payment must be an object")
        pid = check_id(p.get("id"))
        need(pid not in st.payments, "duplicate payment id")
        need(p.get("from_user_id") in st.users and p.get("to_user_id") in st.users,
             "payment references unknown user")
        amount = to_int(p.get("amount"), 0, MAX_BALANCE)
        need(amount is not None, "payment amount")
        note = p.get("note", "")
        need(is_str(note), "payment note")
        vis = p.get("visibility", "public")
        need(vis in ("public", "private"), "payment visibility")
        rid = p.get("request_id")
        need(rid is None or is_str(rid), "payment request_id")
        ts = parse_ts(p["created_at"]) if "created_at" in p else base + n
        n += 1
        rec = {"id": pid, "from": p["from_user_id"], "to": p["to_user_id"], "amount": amount,
               "note": note, "visibility": vis, "request_id": rid, "settlement_id": None,
               "ts": ts, "seq": st.next_seq()}
        st.payments[pid] = rec
        st.pay_list.append(rec)
    for r in requests:
        need(isinstance(r, dict), "request must be an object")
        rid = check_id(r.get("id"))
        need(rid not in st.requests, "duplicate request id")
        need(r.get("requester_id") in st.users and r.get("payer_id") in st.users,
             "request references unknown user")
        amount = to_int(r.get("amount"), 0, MAX_BALANCE)
        need(amount is not None, "request amount")
        note = r.get("note", "")
        need(is_str(note), "request note")
        status = r.get("status", "pending")
        need(status in STATUSES, "request status")
        pid = r.get("payment_id")
        need(pid is None or is_str(pid), "request payment_id")
        ts = parse_ts(r["created_at"]) if "created_at" in r else base + n
        n += 1
        rec = {"id": rid, "requester": r["requester_id"], "payer": r["payer_id"],
               "amount": amount, "note": note, "status": status, "payment_id": pid,
               "ts": ts, "seq": st.next_seq()}
        st.requests[rid] = rec
        st.req_list.append(rec)
    for o in ops:
        need(is_str(o) and o in st.users, "unknown operator id")
        st.operators.add(o)
    return st


def build_from_export(doc):
    need(isinstance(doc, dict), "export must be an object")
    for k in ("track", "format_version", "state"):
        need(k in doc, "missing " + k)
    need(doc["track"] == "pocketful", "wrong track")
    fv = doc["format_version"]
    need(not isinstance(fv, bool) and isinstance(fv, (int, Decimal)) and fv == 1, "wrong version")
    s = doc["state"]
    need(isinstance(s, dict), "state must be an object")
    st = State()
    need(is_str(s.get("currency"), 1, 16), "currency")
    st.currency = s["currency"]
    need(to_int(s.get("minor_units"), 0, 3) in (0, 2, 3), "minor_units")
    st.minor_units = to_int(s["minor_units"], 0, 3)
    for k in ("users", "payments", "requests", "idempotency", "operators"):
        need(isinstance(s.get(k), list), k + " must be a list")
    need(isinstance(s.get("tokens"), dict), "tokens must be an object")
    need(isinstance(s.get("counters"), dict), "counters must be an object")
    for u in s["users"]:
        need(isinstance(u, dict), "user")
        for f in ("id", "email", "handle", "display_name", "pw"):
            need(is_str(u.get(f)), "user." + f)
        need(HASH_RE.fullmatch(u["pw"]) is not None, "user.pw")
        bal = to_int(u.get("balance"), 0, MAX_BALANCE)
        need(bal is not None, "user.balance")
        rec = {k: u[k] for k in ("id", "email", "handle", "display_name", "pw")}
        rec["balance"] = bal
        check_user_fields(rec, st)
        st.add_user(rec)
    for tok, uid in s["tokens"].items():
        need(is_str(tok, 1) and uid in st.users, "token")
        st.tokens[tok] = uid
    for p in s["payments"]:
        need(isinstance(p, dict), "payment")
        pid = check_id(p.get("id"))
        need(pid not in st.payments, "duplicate payment")
        need(p.get("from") in st.users and p.get("to") in st.users, "payment users")
        amount = to_int(p.get("amount"), 0, MAX_BALANCE)
        ts, seq = to_int(p.get("ts"), -2 ** 62, 2 ** 62), to_int(p.get("seq"), 0, 2 ** 62)
        need(amount is not None and ts is not None and seq is not None, "payment numbers")
        need(is_str(p.get("note")) and p.get("visibility") in ("public", "private"), "payment")
        for f in ("request_id", "settlement_id"):
            need(p.get(f) is None or is_str(p[f]), "payment." + f)
        rec = {"id": pid, "from": p["from"], "to": p["to"], "amount": amount,
               "note": p["note"], "visibility": p["visibility"],
               "request_id": p["request_id"], "settlement_id": p["settlement_id"],
               "ts": ts, "seq": seq}
        st.payments[pid] = rec
        st.pay_list.append(rec)
    for r in s["requests"]:
        need(isinstance(r, dict), "request")
        rid = check_id(r.get("id"))
        need(rid not in st.requests, "duplicate request")
        need(r.get("requester") in st.users and r.get("payer") in st.users, "request users")
        amount = to_int(r.get("amount"), 0, MAX_BALANCE)
        ts, seq = to_int(r.get("ts"), -2 ** 62, 2 ** 62), to_int(r.get("seq"), 0, 2 ** 62)
        need(amount is not None and ts is not None and seq is not None, "request numbers")
        need(is_str(r.get("note")) and r.get("status") in STATUSES, "request")
        need(r.get("payment_id") is None or is_str(r["payment_id"]), "request.payment_id")
        rec = {"id": rid, "requester": r["requester"], "payer": r["payer"], "amount": amount,
               "note": r["note"], "status": r["status"], "payment_id": r["payment_id"],
               "ts": ts, "seq": seq}
        st.requests[rid] = rec
        st.req_list.append(rec)
    for e in s["idempotency"]:
        need(isinstance(e, dict), "idempotency entry")
        need(e.get("user") in st.users and is_str(e.get("method")) and is_str(e.get("path"))
             and is_str(e.get("key")) and is_str(e.get("digest"))
             and DIGEST_RE.fullmatch(e["digest"]) is not None, "idempotency entry")
        need(to_int(e.get("status"), 100, 599) is not None and isinstance(e.get("response"), dict),
             "idempotency entry")
        st.idem[(e["user"], e["method"], e["path"], e["key"])] = {
            "digest": e["digest"], "status": to_int(e["status"], 100, 599),
            "response": e["response"]}
    for o in s["operators"]:
        need(is_str(o) and o in st.users, "operator")
        st.operators.add(o)
    for k in st.counters:
        c = to_int(s["counters"].get(k), 0, 2 ** 62)
        need(c is not None, "counters")
        st.counters[k] = c
    st.seq = to_int(s.get("seq"), 0, 2 ** 62)
    need(st.seq is not None, "seq")
    lt = to_int(s.get("last_ts"), 0, 2 ** 62)
    need(lt is not None, "last_ts")
    with _ts_lock:
        _last_ts[0] = max(_last_ts[0], lt)
    return st


LOCK = threading.RLock()
BIG_BODY = 32 * 1024
BIG_SEM = threading.Semaphore(1)
STATE = [State()]


# ---------------------------------------------------------------- request context

class Ctx:
    def __init__(self, method, path, query, headers, raw):
        self.method, self.path, self.query, self.headers, self.raw = method, path, query, headers, raw
        self.user_id = None
        self.params = ()
        self.control = path in CONTROL_PATHS
        self.need_operator = False
        self.exact = self.digest = None

    def body_object(self, allow_empty=False):
        if allow_empty and not self.raw.strip():
            self.exact, self.digest = parse_body(b"{}")
            return self.exact
        v, self.digest = parse_body(self.raw, not self.control)
        if not isinstance(v, dict):
            raise malformed("body must be a JSON object")
        self.exact = v
        return v

    def authenticate(self):
        h = self.headers.get("Authorization")
        if not h:
            raise ApiError(401, "unauthenticated", "missing bearer token")
        parts = h.split(" ")
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
            raise ApiError(401, "unauthenticated", "malformed bearer token")
        with LOCK:
            uid = STATE[0].tokens.get(parts[1])
        if uid is None:
            raise ApiError(401, "unauthenticated", "unknown token")
        self.user_id = uid
        return uid

    def key(self):
        k = self.headers.get("Idempotency-Key")
        if k is None or k == "":
            raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header required")
        raw = k.encode("latin-1", "replace")
        try:
            n = len(raw.decode("utf-8"))
        except UnicodeDecodeError:
            n = len(raw)
        if n > 255:
            raise bad("Idempotency-Key too long")
        return k


def paginate(ctx):
    out = []
    for name, default, lo, hi in (("limit", 50, 1, 200), ("offset", 0, 0, None)):
        v = ctx.query.get(name)
        if v is None:
            out.append(default)
            continue
        if not DIGITS_RE.fullmatch(v) or len(v) > 1000:
            raise bad(name + " must be plain decimal digits")
        n = int(v)
        if n < lo or (hi is not None and n > hi):
            raise bad(name + " out of range")
        out.append(n)
    return out


def idempotent(ctx, body, fn):
    """Under one lock acquisition: re-authenticate, resolve a claimed key, validate, mutate.

    The body was parsed and digested (ctx.exact, ctx.digest) outside the lock; resolving a claimed
    key is a string comparison of fixed-size digests."""
    k_tail = (ctx.method, ctx.path, ctx.key_value)
    with LOCK:
        ctx.authenticate()
        st = STATE[0]
        if ctx.need_operator and ctx.user_id not in st.operators:
            raise ApiError(403, "forbidden", "settlement operators only")
        k = (ctx.user_id,) + k_tail
        rec = st.idem.get(k)
        if rec is not None:
            if rec["digest"] == ctx.digest:
                return 200, rec["response"]
            raise ApiError(409, "idempotency_key_reuse", "key already used with a different body")
        resp = fn(st)
        st.idem[k] = {"digest": ctx.digest, "status": 201, "response": resp}
        return 201, resp


# ---------------------------------------------------------------- handlers

def h_health(ctx):
    return 200, {"status": "ok"}


def h_reset(ctx):
    fx = ctx.body_object()
    st = build_from_fixture(fx)
    with LOCK:
        STATE[0] = st
    return 204, None


def h_export(ctx):
    with LOCK:  # atomic snapshot of copies; serialised outside the lock
        doc = {"track": "pocketful", "format_version": 1, "state": STATE[0].export()}
    return 200, json.dumps(doc, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def h_import(ctx):
    doc = ctx.body_object()
    try:
        st = build_from_export(doc)
    except ApiError:
        raise
    except (RecursionError, ValueError, TypeError, KeyError, AttributeError):
        raise bad("invalid state")
    with LOCK:
        STATE[0] = st
    return 204, None


def new_token(st, uid):
    t = secrets.token_urlsafe(32)
    st.tokens[t] = uid
    return t


def h_signup(ctx):
    body = ctx.body_object()
    split_checks(body, ("email", "password", "display_name"))
    email, pw, name = body["email"], body["password"], body["display_name"]
    if not EMAIL_RE.fullmatch(email):
        raise bad("email must look like local@domain")
    if len(pw) < 8:
        raise bad("password must be at least 8 characters")
    if len(email) > 320 or len(name) > 1000 or len(pw) > 1024:
        raise bad("email, display_name or password too long")
    local = email.split("@")[0]
    handle = re.sub(r"[^a-z0-9_]", "_", local.lower())[:20]
    pwh = hash_password(pw)
    with LOCK:
        st = STATE[0]
        if email in st.by_email:
            raise ApiError(409, "email_taken", "email already registered")
        if handle in st.by_handle:
            raise ApiError(409, "handle_taken", "handle already taken")
        uid = st.next_id("u", st.users)
        st.add_user({"id": uid, "email": email, "handle": handle, "display_name": name,
                     "pw": pwh, "balance": 0})
        tok = new_token(st, uid)
    return 201, {"user_id": uid, "display_name": name, "token": tok}


def h_login(ctx):
    body = ctx.body_object()
    split_checks(body, ("email", "password"))
    if len(body["email"]) > 320 or len(body["password"]) > 1024:
        raise ApiError(401, "unauthenticated", "invalid credentials")
    with LOCK:
        st = STATE[0]
        uid = st.by_email.get(body["email"])
        u = st.users.get(uid) if uid else None
        stored = u["pw"] if u else None
    ok = verify_password(body["password"], stored) if stored else False
    if not ok:
        raise ApiError(401, "unauthenticated", "invalid credentials")
    with LOCK:
        st = STATE[0]
        if st.users.get(uid) is not u:
            raise ApiError(401, "unauthenticated", "invalid credentials")
        tok = new_token(st, uid)
        name = u["display_name"]
    return 200, {"user_id": uid, "display_name": name, "token": tok}


def h_me(ctx):
    ctx.authenticate()
    with LOCK:
        st = STATE[0]
        u = st.users[ctx.user_id]
        return 200, {"user_id": u["id"], "display_name": u["display_name"],
                     "handle": u["handle"], "balance": u["balance"],
                     "currency": st.currency, "minor_units": st.minor_units}


def idem_entry(ctx, allow_empty=False):
    ctx.authenticate()
    ctx.key_value = ctx.key()
    body = ctx.body_object(allow_empty)
    return body


def h_payment(ctx):
    body = idem_entry(ctx)

    def run(st):
        if "to_handle" in body and not isinstance(body["to_handle"], str):
            raise malformed("to_handle must be a string")
        if "to_handle" not in body:
            raise bad("to_handle is required")
        if "amount" not in body:
            raise bad("amount is required")
        amount = parse_amount(body["amount"])
        note = parse_note(body)
        vis = parse_visibility(body)
        me = st.users[ctx.user_id]
        to_id = st.by_handle.get(body["to_handle"])
        if to_id is None:
            raise ApiError(404, "not_found", "no such handle")
        if to_id == me["id"]:
            raise ApiError(422, "self_payment", "cannot pay yourself")
        if me["balance"] < amount:
            raise ApiError(409, "insufficient_funds", "insufficient funds")
        p = st.make_payment(me, st.users[to_id], amount, note, vis, None, None, now_us())
        return st.pay_view(p)

    with LOCK:
        return idempotent(ctx, body, run)


def h_request_create(ctx):
    body = idem_entry(ctx)

    def run(st):
        if "payer_handle" in body and not isinstance(body["payer_handle"], str):
            raise malformed("payer_handle must be a string")
        if "payer_handle" not in body:
            raise bad("payer_handle is required")
        if "amount" not in body:
            raise bad("amount is required")
        amount = parse_amount(body["amount"])
        note = parse_note(body)
        me = st.users[ctx.user_id]
        pid = st.by_handle.get(body["payer_handle"])
        if pid is None:
            raise ApiError(404, "not_found", "no such handle")
        if pid == me["id"]:
            raise ApiError(422, "self_request", "cannot request from yourself")
        r = st.make_request(me, st.users[pid], amount, note, now_us())
        return st.req_view(r)

    with LOCK:
        return idempotent(ctx, body, run)


def h_pay(ctx):
    body = idem_entry(ctx, allow_empty=True)
    rid = ctx.params[0]

    def run(st):
        vis = parse_visibility(body)
        r = st.requests.get(rid)
        if r is None:
            raise ApiError(404, "not_found", "no such request")
        if r["payer"] != ctx.user_id:
            raise ApiError(403, "forbidden", "only the payer may pay")
        if r["status"] != "pending":
            raise ApiError(409, "request_not_pending", "request is not pending")
        payer, requester = st.users[r["payer"]], st.users[r["requester"]]
        if payer["balance"] < r["amount"]:
            raise ApiError(409, "insufficient_funds", "insufficient funds")
        p = st.make_payment(payer, requester, r["amount"], r["note"], vis, r["id"], None,
                            now_us())
        r["status"] = "paid"
        r["payment_id"] = p["id"]
        return st.pay_view(p)

    with LOCK:
        return idempotent(ctx, body, run)


def h_transition(ctx):
    ctx.authenticate()
    rid, action = ctx.params
    with LOCK:
        st = STATE[0]
        r = st.requests.get(rid)
        if r is None:
            raise ApiError(404, "not_found", "no such request")
        if action == "decline":
            who, target = r["payer"], "declined"
        else:
            who, target = r["requester"], "cancelled"
        if ctx.user_id != who:
            raise ApiError(403, "forbidden", "not permitted")
        if r["status"] == "pending":
            r["status"] = target
        elif r["status"] != target:
            raise ApiError(409, "request_not_pending", "request is not pending")
        return 200, st.req_view(r)


def h_requests_list(ctx):
    ctx.authenticate()
    limit, offset = paginate(ctx)
    direction = ctx.query.get("direction")
    status = ctx.query.get("status")
    if direction is not None and direction not in ("incoming", "outgoing"):
        raise bad("unknown direction")
    if status is not None and status not in STATUSES:
        raise bad("unknown status")
    uid = ctx.user_id
    with LOCK:
        st = STATE[0]
        items = []
        for r in st.req_list:
            if direction == "incoming":
                ok = r["payer"] == uid
            elif direction == "outgoing":
                ok = r["requester"] == uid
            else:
                ok = uid in (r["payer"], r["requester"])
            if ok and (status is None or r["status"] == status):
                items.append(r)
        items.sort(key=lambda r: (r["ts"], r["seq"]), reverse=True)
        page = items[offset:offset + limit]
        return 200, {"requests": [st.req_view(r) for r in page],
                     "has_more": offset + limit < len(items)}


def h_activity(ctx):
    ctx.authenticate()
    limit, offset = paginate(ctx)
    uid = ctx.user_id
    with LOCK:
        st = STATE[0]
        items = [p for p in st.pay_list
                 if p["visibility"] == "public" or p["from"] == uid or p["to"] == uid]
        items.sort(key=lambda p: (p["ts"], p["seq"]), reverse=True)
        page = items[offset:offset + limit]
        return 200, {"payments": [st.pay_view(p) for p in page],
                     "has_more": offset + limit < len(items)}


def h_split(ctx):
    body = idem_entry(ctx)

    def run(st):
        hs = body.get("participant_handles", MISSING)
        if hs is not MISSING and not isinstance(hs, list):
            raise malformed("participant_handles must be an array")
        if hs is not MISSING and any(not isinstance(h, str) for h in hs):
            raise malformed("participant_handles must contain strings")
        if hs is MISSING:
            raise bad("participant_handles is required")
        if "amount" not in body:
            raise bad("amount is required")
        amount = parse_amount(body["amount"])
        note = parse_note(body)
        if not hs or len(set(hs)) != len(hs):
            raise bad("participant_handles must be non-empty and unique")
        ids = []
        for h in hs:
            uid = st.by_handle.get(h)
            if uid is None:
                raise ApiError(404, "not_found", "unknown handle " + h[:30])
            ids.append(uid)
        n = len(hs)
        base, rem = divmod(amount, n)
        shares = [base + (1 if i < rem else 0) for i in range(n)]
        me = st.users[ctx.user_id]
        ts = now_us()
        reqs = []
        for uid, share in zip(ids, shares):
            if uid != me["id"]:
                reqs.append(st.req_view(st.make_request(me, st.users[uid], share, note,
                                                         now_us())))
        sid = st.next_id("sp")
        return {"split_id": sid, "amount": amount, "currency": st.currency, "note": note,
                "shares": [{"handle": h, "amount": s} for h, s in zip(hs, shares)],
                "requests": reqs, "created_at": fmt_ts(ts)}

    with LOCK:
        return idempotent(ctx, body, run)


def h_settlement(ctx):
    ctx.authenticate()
    with LOCK:
        if ctx.user_id not in STATE[0].operators:
            raise ApiError(403, "forbidden", "settlement operators only")
    ctx.need_operator = True
    ctx.key_value = ctx.key()
    body = ctx.body_object()

    def run(st):
        ts_ = body.get("transfers", MISSING)
        if not isinstance(ts_, list) or not 1 <= len(ts_) <= 32:
            raise bad("transfers must be an array of 1 to 32 objects")
        if any(not isinstance(t, dict) for t in ts_):
            raise bad("each transfer must be an object")
        entries = []
        for t in ts_:
            for f in ("from_handle", "to_handle"):
                if f in t and not isinstance(t[f], str):
                    raise malformed(f + " must be a string")
            for f in ("from_handle", "to_handle", "amount"):
                if f not in t:
                    raise bad(f + " is required")
            amount = parse_amount(t["amount"])
            note = parse_note(t)
            vis = parse_visibility(t)
            frm = st.by_handle.get(t["from_handle"])
            to = st.by_handle.get(t["to_handle"])
            if frm is None or to is None:
                raise ApiError(404, "not_found", "no such handle")
            if frm == to:
                raise ApiError(422, "self_payment", "self transfer")
            entries.append((frm, to, amount, note, vis))
        net = {}
        for frm, to, amount, _, _ in entries:
            net[frm] = net.get(frm, st.users[frm]["balance"]) - amount
            net[to] = net.get(to, st.users[to]["balance"]) + amount
        if any(v < 0 for v in net.values()):
            raise ApiError(409, "insufficient_funds", "settlement is not affordable")
        sid = st.next_id("st")
        ts = now_us()
        pays = []
        for frm, to, amount, note, vis in entries:
            p = st.make_payment(st.users[frm], st.users[to], amount, note, vis, None, sid, ts)
            pays.append(st.pay_view(p))
        return {"settlement_id": sid, "committed_at": fmt_ts(ts), "payments": pays}

    with LOCK:
        return idempotent(ctx, body, run)


ROUTES = [
    ("GET", r"/health", h_health),
    ("POST", r"/_test/reset", h_reset),
    ("GET", r"/_test/export", h_export),
    ("POST", r"/_test/import", h_import),
    ("POST", r"/auth/signup", h_signup),
    ("POST", r"/auth/login", h_login),
    ("GET", r"/me", h_me),
    ("POST", r"/payments", h_payment),
    ("POST", r"/requests", h_request_create),
    ("GET", r"/requests", h_requests_list),
    ("POST", r"/requests/([^/]+)/pay", h_pay),
    ("POST", r"/requests/([^/]+)/(decline|cancel)", h_transition),
    ("POST", r"/splits", h_split),
    ("GET", r"/activity", h_activity),
    ("POST", r"/settlements", h_settlement),
]
LOCKED = {h_me, h_transition, h_requests_list, h_activity}
ROUTES = [(m, re.compile(p + "$"), h) for m, p, h in ROUTES]


def route(method, path):
    allowed = []
    for m, rx, h in ROUTES:
        mt = rx.fullmatch(path)
        if mt:
            if m == method:
                return h, mt.groups(), allowed
            allowed.append(m)
    return None, (), allowed


# ---------------------------------------------------------------- HTTP

def error_code_for(status):
    return {400: "malformed_request", 401: "unauthenticated", 403: "forbidden",
            404: "not_found", 405: "method_not_allowed",
            413: "payload_too_large"}.get(status, "malformed_request")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 60
    server_version = "pocketful"
    sys_version = ""

    def log_message(self, *a):
        pass

    def send_json(self, status, payload, extra=None):
        if payload is None:
            body = b""
        elif isinstance(payload, bytes):
            body = payload
        else:
            body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if status != 204:
            self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if status != 204 and self.command != "HEAD":
            self.wfile.write(body)

    def send_error(self, code, message=None, explain=None):
        status = code if 400 <= code < 500 else (405 if code == 501 else 400)
        self.close_connection = True
        try:
            if not hasattr(self, "command") or self.command is None:
                self.command = "GET"
            self.send_json(status, {"error": {"code": error_code_for(status),
                                              "message": message or "bad request"}})
        except OSError:
            pass

    def read_body(self, limit):
        te = (self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in te:
            data = b""
            while True:
                line = self.rfile.readline(65537)
                try:
                    size = int(line.split(b";")[0].strip() or b"x", 16)
                except ValueError:
                    raise malformed("bad chunk")
                if size == 0:
                    while True:
                        t = self.rfile.readline(65537)
                        if t in (b"\r\n", b"\n", b""):
                            break
                    return data
                if len(data) + size > limit:
                    self.close_connection = True
                    raise ApiError(413, "payload_too_large", "body too large")
                data += self.rfile.read(size)
                self.rfile.readline(65537)
        cl = self.headers.get("Content-Length")
        if cl is None or cl.strip() == "":
            return b""
        if not DIGITS_RE.fullmatch(cl.strip()):
            self.close_connection = True
            raise malformed("bad Content-Length")
        n = int(cl)
        if n > limit:
            self.close_connection = True
            left = min(n, 64 * 1024 * 1024)  # drain at most 64 MiB
            while left > 0:  # discard (never buffer) so the client can read the 413
                chunk = self.rfile.read(min(left, 65536))
                if not chunk:
                    break
                left -= len(chunk)
            raise ApiError(413, "payload_too_large", "body too large")
        return self.rfile.read(n) if n else b""

    def dispatch(self):
        method = self.command
        try:
            try:
                parts = urlsplit(self.path)
            except ValueError:
                self.close_connection = True
                raise malformed("bad URL")
            raw = self.read_body(MAX_CONTROL_BODY if parts.path in CONTROL_PATHS else MAX_BODY)
            path = parts.path
            query = {k: v[-1] for k, v in parse_qs(parts.query, keep_blank_values=True,
                                                   errors="replace").items()}
            h, groups, allowed = route(method, unquote(path, errors="replace"))
            if h is None:
                if allowed:
                    raise ApiError(405, "method_not_allowed", "method not allowed")
                raise ApiError(404, "not_found", "no such route")
            ctx = Ctx(method, unquote(path, errors="replace"), query, self.headers, raw)
            ctx.params = groups
            if h in LOCKED:
                with LOCK:
                    status, payload = h(ctx)
            elif len(raw) > BIG_BODY and not ctx.control:
                with BIG_SEM:  # keep large-body CPU work from starving small requests
                    status, payload = h(ctx)
            else:
                status, payload = h(ctx)
            self.send_json(status, payload)
        except ApiError as e:
            extra = None
            if e.status == 405:
                extra = {"Allow": ", ".join(sorted(set(route(method, unquote(self.path.split("?")[0]))[2])))}
            self.send_json(e.status, {"error": {"code": e.code, "message": e.message}}, extra)
        except (BrokenPipeError, ConnectionError, TimeoutError):
            self.close_connection = True
        except Exception:
            sys.stderr.write("internal error: %s\n" % traceback.format_exc().strip().splitlines()[-1][:300])
            try:
                self.send_json(400, {"error": {"code": "malformed_request",
                                               "message": "request could not be processed"}})
            except OSError:
                self.close_connection = True

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = dispatch


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def process_request(self, request, client_address):
        # start_new_thread does not wait for the new thread to be scheduled (Thread.start does),
        # so the accept loop is never starved by CPU-heavy request threads.
        _thread.start_new_thread(self.process_request_thread, (request, client_address))

    request_queue_size = 512
    allow_reuse_address = True


def main():
    sys.setswitchinterval(0.001)
    try:
        port = int(os.environ.get("PORT") or 8080)
    except ValueError:
        port = 8080
    Server(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
