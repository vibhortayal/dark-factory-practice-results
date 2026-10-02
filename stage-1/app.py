"""Pocketful stage 1: payments, requests, splits, settlements.

Standard library only. All state is in memory behind one lock, so every
operation (including idempotency-key claims) is atomic with respect to every
other. Password hashing (scrypt) is done outside the lock.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit

MAX_AMOUNT = 1_000_000_000
MAX_BALANCE = 2 ** 53
MAX_NOTE = 200
MAX_BODY = 16 * 1024 * 1024
HANDLE_RE = re.compile(r"^[a-z0-9_]{1,20}\Z")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\Z")
DIGITS_RE = re.compile(r"^[0-9]+\Z")
STATUSES = ("pending", "paid", "declined", "cancelled")

# scrypt parameters: ~5 ms per hash, so a reset with hundreds of users and 50
# concurrent logins both stay far inside the 10 s / 5 s limits on 2 vCPU.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2048, 8, 1


# ----------------------------------------------------------------- errors

class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str | None = None):
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message or code.replace("_", " ")


def bad(msg="malformed request"):
    return ApiError(400, "malformed_request", msg)


def invalid(msg="validation failed"):
    return ApiError(422, "validation_failed", msg)


# ---------------------------------------------------------------- hashing

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt,
                       n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=64 * 1024 * 1024)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${h.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        alg, n, r, p, salt, expected = encoded.split("$")
        if alg != "scrypt":
            return False
        h = hashlib.scrypt(password.encode("utf-8", "surrogatepass"),
                           salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                           maxmem=128 * 1024 * 1024)
        return hmac.compare_digest(h.hex(), expected)
    except (ValueError, TypeError, AttributeError):
        return False


# ------------------------------------------------------------------- json

def _no_constant(name):
    raise ValueError("bad constant " + name)


def _parse_float(s):
    """Decimal(s); an exponent beyond Decimal's range becomes a huge/tiny sentinel."""
    try:
        return Decimal(s)
    except InvalidOperation:
        sign = "-" if s.startswith("-") else ""
        exp = s.lower().split("e", 1)[1] if "e" in s.lower() else "0"
        return Decimal(sign + ("1e-1000" if exp.startswith("-") else "1e1000"))


def parse_json(raw: bytes):
    """Parse with every number as Decimal (exact, no float rounding)."""
    try:
        text = raw.decode("utf-8")
        return json.loads(text, parse_int=Decimal, parse_float=_parse_float,
                          parse_constant=_no_constant)
    except (ValueError, RecursionError, ArithmeticError):
        raise bad("body is not valid JSON")


def jeq(a, b) -> bool:
    """JSON value equality; numbers compare numerically, bool is not a number."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, dict):
        return (isinstance(b, dict) and a.keys() == b.keys()
                and all(jeq(a[k], b[k]) for k in a))
    if isinstance(a, list):
        return (isinstance(b, list) and len(a) == len(b)
                and all(jeq(x, y) for x, y in zip(a, b)))
    if isinstance(a, Decimal):
        return isinstance(b, Decimal) and a == b
    return type(a) is type(b) and a == b


def to_int(v):
    """An integral JSON number as int, else None (bool/str/fraction/huge -> None)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, Decimal):
        if not v.is_finite() or v.adjusted() > 30:
            return None
        if v != v.to_integral_value():
            return None
        return int(v)
    return None


def plain(v):
    """Decimal -> int/float so a parsed document can be stored/serialised."""
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [plain(x) for x in v]
    if isinstance(v, Decimal):
        i = to_int(v)
        return i if i is not None else float(v)
    return v


def dumps(obj) -> bytes:
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except UnicodeEncodeError:
        return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def clean(v):
    """Round-trip safe copy of JSON-native data."""
    return copy.deepcopy(v)


# ------------------------------------------------------------------ state

class State:
    def __init__(self):
        self.currency = "EUR"
        self.minor_units = 2
        self.users = {}        # id -> dict(id,email,display_name,handle,pw,balance)
        self.by_email = {}
        self.by_handle = {}
        self.tokens = {}       # token -> user id
        self.payments = {}     # id -> dict (insertion ordered)
        self.requests = {}     # id -> dict
        self.operators = set()
        self.idem = {}         # (user_id, path, key) -> dict(body_raw, body, status, response)
        self.seq = 0
        self.last_ts = 0
        self.ctr = {"u": 0, "p": 0, "rq": 0, "sp": 0, "st": 0}

    # -- ids / time
    def next_seq(self):
        self.seq += 1
        return self.seq

    def new_id(self, prefix, taken):
        while True:
            self.ctr[prefix] += 1
            cand = f"{prefix}_{self.ctr[prefix]}"
            if cand not in taken:
                return cand

    def now(self) -> str:
        t = max(int(datetime.now(timezone.utc).timestamp()), self.last_ts)
        self.last_ts = t
        return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")

    # -- views
    def payment_view(self, p):
        return {
            "payment_id": p["id"],
            "from_user_id": p["from"],
            "from_handle": self.users[p["from"]]["handle"],
            "to_user_id": p["to"],
            "to_handle": self.users[p["to"]]["handle"],
            "amount": p["amount"],
            "currency": self.currency,
            "note": p["note"],
            "visibility": p["visibility"],
            "request_id": p["request_id"],
            "settlement_id": p["settlement_id"],
            "created_at": p["created_at"],
        }

    def request_view(self, r):
        return {
            "request_id": r["id"],
            "requester_id": r["requester"],
            "requester_handle": self.users[r["requester"]]["handle"],
            "payer_id": r["payer"],
            "payer_handle": self.users[r["payer"]]["handle"],
            "amount": r["amount"],
            "currency": self.currency,
            "note": r["note"],
            "status": r["status"],
            "payment_id": r["payment_id"],
            "created_at": r["created_at"],
        }

    # -- mutations (caller holds the lock and has validated funds)
    def add_payment(self, frm, to, amount, note, visibility, request_id, settlement_id, ts):
        pid = self.new_id("p", self.payments)
        self.users[frm]["balance"] -= amount
        self.users[to]["balance"] += amount
        p = {"id": pid, "from": frm, "to": to, "amount": amount, "note": note,
             "visibility": visibility, "request_id": request_id,
             "settlement_id": settlement_id, "created_at": ts, "seq": self.next_seq()}
        self.payments[pid] = p
        return p

    def add_request(self, requester, payer, amount, note, ts):
        rid = self.new_id("rq", self.requests)
        r = {"id": rid, "requester": requester, "payer": payer, "amount": amount,
             "note": note, "status": "pending", "payment_id": None,
             "created_at": ts, "seq": self.next_seq()}
        self.requests[rid] = r
        return r

    # -- export / import
    def export(self):
        return {
            "currency": self.currency,
            "minor_units": self.minor_units,
            "users": [dict(u) for u in self.users.values()],
            "tokens": dict(self.tokens),
            "payments": [dict(p) for p in self.payments.values()],
            "requests": [dict(r) for r in self.requests.values()],
            "operators": sorted(self.operators),
            "idempotency": [
                {"user_id": k[0], "path": k[1], "key": k[2], "body_raw": v["body_raw"],
                 "status": v["status"], "response": clean(v["response"])}
                for k, v in self.idem.items()],
            "seq": self.seq,
            "last_ts": self.last_ts,
            "counters": dict(self.ctr),
        }


def _chk(cond, msg="invalid state"):
    if not cond:
        raise invalid(msg)


def _isint(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _str(v):
    _chk(isinstance(v, str))
    return v


def state_from_export(doc) -> State:
    _chk(isinstance(doc, dict))
    try:
        st = State()
        st.currency = _str(doc["currency"])
        st.minor_units = doc["minor_units"]
        _chk(_isint(st.minor_units) and st.minor_units in (0, 2, 3))
        for u in doc["users"]:
            _chk(isinstance(u, dict))
            uid, handle = _str(u["id"]), _str(u["handle"])
            email = _str(u["email"])
            _chk(HANDLE_RE.match(handle) is not None)
            _chk(_isint(u["balance"]) and 0 <= u["balance"] <= MAX_BALANCE)
            _chk(uid not in st.users and email not in st.by_email and handle not in st.by_handle)
            rec = {"id": uid, "email": email, "display_name": _str(u["display_name"]),
                   "handle": handle, "pw": _str(u["pw"]), "balance": u["balance"]}
            st.users[uid] = rec
            st.by_email[email] = uid
            st.by_handle[handle] = uid
        for tok, uid in doc["tokens"].items():
            _chk(isinstance(tok, str) and uid in st.users)
            st.tokens[tok] = uid
        for p in doc["payments"]:
            rec = {"id": _str(p["id"]), "from": p["from"], "to": p["to"], "amount": p["amount"],
                   "note": _str(p["note"]), "visibility": p["visibility"],
                   "request_id": p["request_id"], "settlement_id": p["settlement_id"],
                   "created_at": _str(p["created_at"]), "seq": p["seq"]}
            _chk(rec["id"] not in st.payments and rec["from"] in st.users and rec["to"] in st.users)
            _chk(_isint(rec["amount"]) and rec["amount"] >= 0 and _isint(rec["seq"]))
            _chk(rec["visibility"] in ("public", "private"))
            _chk(rec["request_id"] is None or isinstance(rec["request_id"], str))
            _chk(rec["settlement_id"] is None or isinstance(rec["settlement_id"], str))
            st.payments[rec["id"]] = rec
        for r in doc["requests"]:
            rec = {"id": _str(r["id"]), "requester": r["requester"], "payer": r["payer"],
                   "amount": r["amount"], "note": _str(r["note"]), "status": r["status"],
                   "payment_id": r["payment_id"], "created_at": _str(r["created_at"]),
                   "seq": r["seq"]}
            _chk(rec["id"] not in st.requests and rec["requester"] in st.users
                 and rec["payer"] in st.users)
            _chk(_isint(rec["amount"]) and rec["amount"] >= 0 and _isint(rec["seq"]))
            _chk(rec["status"] in STATUSES)
            _chk(rec["payment_id"] is None or isinstance(rec["payment_id"], str))
            st.requests[rec["id"]] = rec
        for op in doc["operators"]:
            _chk(op in st.users)
            st.operators.add(op)
        for e in doc["idempotency"]:
            uid, path, key = _str(e["user_id"]), _str(e["path"]), _str(e["key"])
            _chk(uid in st.users)
            raw = _str(e["body_raw"])
            body = parse_json(raw.encode("utf-8"))
            _chk(_isint(e["status"]))
            st.idem[(uid, path, key)] = {"body_raw": raw, "body": body, "status": e["status"],
                                         "response": clean(e["response"])}
        st.seq = doc["seq"]
        st.last_ts = doc["last_ts"]
        _chk(_isint(st.seq) and _isint(st.last_ts))
        for k in st.ctr:
            _chk(_isint(doc["counters"][k]))
            st.ctr[k] = doc["counters"][k]
        return st
    except ApiError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise invalid("invalid state")


def state_from_fixture(fx) -> State:
    if not isinstance(fx, dict):
        raise bad("fixture must be an object")
    st = State()
    cur = fx.get("currency", "EUR")
    _chk(isinstance(cur, str) and cur != "", "currency")
    mu = fx.get("minor_units", {"EUR": 2, "JPY": 0, "BHD": 3}.get(cur, 2))
    mu = to_int(mu)
    _chk(mu in (0, 2, 3), "minor_units")
    st.currency, st.minor_units = cur, mu
    users = fx.get("users", [])
    _chk(isinstance(users, list), "users")
    pending = []
    for u in users:
        _chk(isinstance(u, dict), "user")
        uid, email, pw = u.get("id"), u.get("email"), u.get("password")
        handle = u.get("handle")
        _chk(isinstance(uid, str) and uid != "", "user id")
        _chk(isinstance(email, str) and email != "", "user email")
        _chk(isinstance(pw, str), "user password")
        _chk(isinstance(handle, str) and HANDLE_RE.match(handle) is not None, "user handle")
        name = u.get("display_name", handle)
        _chk(isinstance(name, str), "display_name")
        bal = to_int(u.get("balance", 0))
        _chk(bal is not None and 0 <= bal <= MAX_BALANCE, "user balance")
        _chk(uid not in st.users and email not in st.by_email and handle not in st.by_handle,
             "duplicate user")
        st.users[uid] = {"id": uid, "email": email, "display_name": name, "handle": handle,
                         "pw": None, "balance": bal}
        st.by_email[email] = uid
        st.by_handle[handle] = uid
        pending.append((uid, pw))
    for p in fx.get("payments") or []:
        _chk(isinstance(p, dict), "payment")
        pid = p.get("id")
        _chk(isinstance(pid, str) and pid != "" and pid not in st.payments, "payment id")
        frm, to = p.get("from_user_id"), p.get("to_user_id")
        _chk(frm in st.users and to in st.users, "payment parties")
        amt = to_int(p.get("amount"))
        _chk(amt is not None and 0 <= amt <= MAX_BALANCE, "payment amount")
        note = p.get("note", "")
        vis = p.get("visibility", "public")
        _chk(isinstance(note, str) and vis in ("public", "private"), "payment fields")
        rq = p.get("request_id")
        _chk(rq is None or isinstance(rq, str), "payment request_id")
        st.payments[pid] = {"id": pid, "from": frm, "to": to, "amount": amt, "note": note,
                            "visibility": vis, "request_id": rq, "settlement_id": None,
                            "created_at": None, "seq": st.next_seq()}
    for r in fx.get("requests") or []:
        _chk(isinstance(r, dict), "request")
        rid = r.get("id")
        _chk(isinstance(rid, str) and rid != "" and rid not in st.requests, "request id")
        rr, rp = r.get("requester_id"), r.get("payer_id")
        _chk(rr in st.users and rp in st.users, "request parties")
        amt = to_int(r.get("amount"))
        _chk(amt is not None and 0 <= amt <= MAX_BALANCE, "request amount")
        note = r.get("note", "")
        status = r.get("status", "pending")
        _chk(isinstance(note, str) and status in STATUSES, "request fields")
        pay = r.get("payment_id")
        _chk(pay is None or isinstance(pay, str), "request payment_id")
        st.requests[rid] = {"id": rid, "requester": rr, "payer": rp, "amount": amt,
                            "note": note, "status": status, "payment_id": pay,
                            "created_at": None, "seq": st.next_seq()}
    ops = fx.get("settlement_operator_ids") or []
    _chk(isinstance(ops, list), "operators")
    for o in ops:
        _chk(isinstance(o, str) and o in st.users, "operator id")
        st.operators.add(o)
    ts = st.now()
    for p in st.payments.values():
        p["created_at"] = ts
    for r in st.requests.values():
        r["created_at"] = ts
    return st, pending


_POOL = ThreadPoolExecutor(max_workers=4)


def build_fixture_state(fx) -> State:
    st, pending = state_from_fixture(fx)
    hashes = list(_POOL.map(lambda pair: hash_password(pair[1]), pending))
    for (uid, _), h in zip(pending, hashes):
        st.users[uid]["pw"] = h
    return st


STATE = State()
LOCK = threading.RLock()


# ---------------------------------------------------------------- helpers

def check_note(body):
    note = body.get("note", "")
    if not isinstance(note, str) or len(note) > MAX_NOTE:
        raise invalid("note must be a string of at most 200 characters")
    return note


def check_visibility(body):
    vis = body.get("visibility", "public")
    if vis not in ("public", "private") or not isinstance(vis, str):
        raise invalid("visibility must be public or private")
    return vis


def check_amount(body, lo=1):
    if "amount" not in body:
        raise invalid("amount is required")
    amt = to_int(body["amount"])
    if amt is None or amt < lo or amt > MAX_AMOUNT:
        raise invalid("amount must be an integer between 1 and 1000000000")
    return amt


def handle_field(body, name, wrong_type=bad):
    if name not in body:
        raise invalid(f"{name} is required")
    v = body[name]
    if not isinstance(v, str):
        raise wrong_type(f"{name} must be a string")
    return v


def lookup_handle(st, handle):
    uid = st.by_handle.get(handle) if HANDLE_RE.match(handle) else None
    if uid is None:
        raise ApiError(404, "not_found", "no such handle")
    return uid


def check_range(st, uid, delta):
    if st.users[uid]["balance"] + delta > MAX_BALANCE:
        raise invalid("balance out of range")


def derive_handle(email):
    local = email.split("@")[0]
    return re.sub(r"[^a-z0-9_]", "_", local.lower())[:20]


def page(q):
    def get(name, default, lo, hi):
        if name not in q:
            return default
        v = q[name]
        if not DIGITS_RE.match(v):
            raise invalid(f"{name} must be a plain decimal integer")
        n = int(v) if len(v) <= 1000 else 10 ** 1000
        if n < lo or (hi is not None and n > hi):
            raise invalid(f"{name} out of range")
        return n
    return get("limit", 50, 1, 200), get("offset", 0, 0, None)


def paginate(items, q):
    limit, offset = page(q)
    chunk = items[offset:offset + limit]
    return chunk, len(items) > offset + limit


# --------------------------------------------------------------- handlers
# Each handler returns (status, payload). `ctx` carries request details.

class Ctx:
    def __init__(self, method, path, query, headers, raw):
        self.method, self.path, self.query, self.headers, self.raw = method, path, query, headers, raw
        self.user = None
        self._body = None
        self._parsed = False

    def body(self, required=True):
        """Body as a dict. Empty body: {} when not required, else malformed."""
        if not self._parsed:
            if not self.raw.strip():
                self._body = None
            else:
                self._body = parse_json(self.raw)
            self._parsed = True
        if self._body is None:
            if required:
                raise bad("a JSON object body is required")
            return {}
        if not isinstance(self._body, dict):
            raise bad("body must be a JSON object")
        return self._body


def authenticate(ctx):
    h = ctx.headers.get("Authorization", "")
    parts = h.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise ApiError(401, "unauthenticated", "missing or malformed bearer token")
    with LOCK:
        uid = STATE.tokens.get(parts[1])
    if uid is None:
        raise ApiError(401, "unauthenticated", "unknown token")
    ctx.user = uid


def idem_key(ctx):
    k = ctx.headers.get("Idempotency-Key")
    if k is not None:
        try:
            k = k.encode("latin-1").decode("utf-8")
        except (UnicodeError, ValueError):
            pass
    if k is None or k == "":
        raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header is required")
    if len(k) > 255:
        raise invalid("Idempotency-Key must be 1 to 255 characters")
    return k


def idempotent(ctx, op, raw_ok_empty=False):
    """Run `op(st, body)` once per (user, path, key). Caller holds no lock."""
    key = idem_key(ctx)
    body = ctx.body(required=not raw_ok_empty)
    with LOCK:
        st = STATE
        rec = st.idem.get((ctx.user, ctx.path, key))
        if rec is not None:
            if jeq(rec["body"], body):
                return 200, clean(rec["response"])
            raise ApiError(409, "idempotency_key_reuse", "key used with a different body")
        status, response = op(st, body)
        raw_text = ctx.raw.decode("utf-8") if ctx.raw.strip() else "{}"
        st.idem[(ctx.user, ctx.path, key)] = {
            "body_raw": raw_text, "body": body, "status": status, "response": clean(response)}
        return status, response


def h_health(ctx):
    return 200, {"status": "ok"}


def h_reset(ctx):
    global STATE
    if not ctx.raw.strip():
        raise bad("a JSON fixture body is required")
    fx = parse_json(ctx.raw)
    try:
        new = build_fixture_state(fx)
    except (TypeError, ValueError, AttributeError, KeyError):
        raise invalid("invalid fixture")
    with LOCK:
        STATE = new
    return 204, None


def h_export(ctx):
    with LOCK:
        doc = {"track": "pocketful", "format_version": 1, "state": STATE.export()}
        return 200, doc


def h_import(ctx):
    global STATE
    try:
        doc = json.loads(ctx.raw.decode("utf-8"), parse_constant=_no_constant)
    except (ValueError, RecursionError):
        raise bad("body is not valid JSON")
    if not isinstance(doc, dict):
        raise bad("body must be a JSON object")
    _chk(doc.get("track") == "pocketful", "wrong track")
    fv = doc.get("format_version")
    _chk(_isint(fv) and fv == 1, "wrong format_version")
    _chk("state" in doc, "missing state")
    new = state_from_export(doc["state"])
    with LOCK:
        STATE = new
    return 204, None


def h_signup(ctx):
    body = ctx.body()
    email = handle_field(body, "email")
    pw = handle_field(body, "password")
    name = handle_field(body, "display_name")
    if not EMAIL_RE.match(email):
        raise invalid("email must look like local@domain")
    if len(pw) < 8:
        raise invalid("password must be at least 8 characters")
    if name == "":
        raise invalid("display_name must not be empty")
    pw_hash = hash_password(pw)
    handle = derive_handle(email)
    with LOCK:
        st = STATE
        if email in st.by_email:
            raise ApiError(409, "email_taken", "email already registered")
        if handle in st.by_handle:
            raise ApiError(409, "handle_taken", "derived handle already taken")
        uid = st.new_id("u", st.users)
        st.users[uid] = {"id": uid, "email": email, "display_name": name, "handle": handle,
                         "pw": pw_hash, "balance": 0}
        st.by_email[email] = uid
        st.by_handle[handle] = uid
        token = secrets.token_urlsafe(32)
        st.tokens[token] = uid
        return 201, {"user_id": uid, "display_name": name, "token": token}


def h_login(ctx):
    body = ctx.body()
    email = handle_field(body, "email")
    pw = handle_field(body, "password")
    with LOCK:
        uid = STATE.by_email.get(email)
        enc = STATE.users[uid]["pw"] if uid else None
    ok = verify_password(pw, enc) if enc else False
    if not ok:
        raise ApiError(401, "unauthenticated", "wrong email or password")
    with LOCK:
        st = STATE
        if uid not in st.users or st.users[uid]["pw"] != enc:
            raise ApiError(401, "unauthenticated", "wrong email or password")
        token = secrets.token_urlsafe(32)
        st.tokens[token] = uid
        return 200, {"user_id": uid, "display_name": st.users[uid]["display_name"],
                     "token": token}


def h_me(ctx):
    with LOCK:
        u = STATE.users[ctx.user]
        return 200, {"user_id": u["id"], "display_name": u["display_name"],
                     "handle": u["handle"], "balance": u["balance"],
                     "currency": STATE.currency, "minor_units": STATE.minor_units}


def h_payment(ctx):
    def op(st, body):
        to_handle = handle_field(body, "to_handle")
        amount = check_amount(body)
        note = check_note(body)
        vis = check_visibility(body)
        me = st.users[ctx.user]
        if to_handle == me["handle"]:
            raise ApiError(422, "self_payment", "cannot pay yourself")
        to = lookup_handle(st, to_handle)
        if me["balance"] < amount:
            raise ApiError(409, "insufficient_funds", "balance too low")
        check_range(st, to, amount)
        p = st.add_payment(ctx.user, to, amount, note, vis, None, None, st.now())
        return 201, st.payment_view(p)
    return idempotent(ctx, op)


def h_request_create(ctx):
    def op(st, body):
        payer_handle = handle_field(body, "payer_handle")
        amount = check_amount(body)
        note = check_note(body)
        if payer_handle == st.users[ctx.user]["handle"]:
            raise ApiError(422, "self_request", "cannot request from yourself")
        payer = lookup_handle(st, payer_handle)
        r = st.add_request(ctx.user, payer, amount, note, st.now())
        return 201, st.request_view(r)
    return idempotent(ctx, op)


def h_request_pay(ctx, rid):
    def op(st, body):
        vis = check_visibility(body)
        r = st.requests.get(rid)
        if r is None:
            raise ApiError(404, "not_found", "no such request")
        if r["payer"] != ctx.user:
            raise ApiError(403, "forbidden", "only the payer may pay")
        if r["status"] != "pending":
            raise ApiError(409, "request_not_pending", "request is not pending")
        if st.users[ctx.user]["balance"] < r["amount"]:
            raise ApiError(409, "insufficient_funds", "balance too low")
        check_range(st, r["requester"], r["amount"])
        p = st.add_payment(ctx.user, r["requester"], r["amount"], r["note"], vis,
                           r["id"], None, st.now())
        r["status"] = "paid"
        r["payment_id"] = p["id"]
        return 201, st.payment_view(p)
    return idempotent(ctx, op, raw_ok_empty=True)


def h_request_decide(ctx, rid, action):
    with LOCK:
        st = STATE
        r = st.requests.get(rid)
        if r is None:
            raise ApiError(404, "not_found", "no such request")
        party, target = ("payer", "declined") if action == "decline" else ("requester", "cancelled")
        if r[party] != ctx.user:
            raise ApiError(403, "forbidden", f"only the {party} may {action}")
        if r["status"] == "pending":
            r["status"] = target
        elif r["status"] != target:
            raise ApiError(409, "request_not_pending", "request is not pending")
        return 200, st.request_view(r)


def h_requests_list(ctx):
    q = ctx.query
    limit_offset = page(q)  # validates paging first
    direction = q.get("direction")
    status = q.get("status")
    if direction is not None and direction not in ("incoming", "outgoing"):
        raise invalid("direction must be incoming or outgoing")
    if status is not None and status not in STATUSES:
        raise invalid("unknown status")
    with LOCK:
        st = STATE
        me = ctx.user
        rows = []
        for r in st.requests.values():
            if direction == "incoming":
                ok = r["payer"] == me
            elif direction == "outgoing":
                ok = r["requester"] == me
            else:
                ok = r["payer"] == me or r["requester"] == me
            if ok and (status is None or r["status"] == status):
                rows.append(r)
        rows.sort(key=lambda r: r["seq"], reverse=True)
        chunk, more = paginate(rows, q)
        return 200, {"requests": [st.request_view(r) for r in chunk], "has_more": more}


def h_activity(ctx):
    page(ctx.query)
    with LOCK:
        st = STATE
        me = ctx.user
        rows = [p for p in st.payments.values()
                if p["visibility"] == "public" or p["from"] == me or p["to"] == me]
        rows.sort(key=lambda p: p["seq"], reverse=True)
        chunk, more = paginate(rows, ctx.query)
        return 200, {"payments": [st.payment_view(p) for p in chunk], "has_more": more}


def equal_split(amount, n):
    base, rem = divmod(amount, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def h_split(ctx):
    def op(st, body):
        amount = check_amount(body)
        if "participant_handles" not in body:
            raise invalid("participant_handles is required")
        handles = body["participant_handles"]
        if not isinstance(handles, list) or not all(isinstance(h, str) for h in handles):
            raise bad("participant_handles must be an array of strings")
        note = check_note(body)
        if not handles or len(set(handles)) != len(handles):
            raise invalid("participant_handles must be non-empty and unique")
        uids = [lookup_handle(st, h) for h in handles]
        shares = equal_split(amount, len(handles))
        ts = st.now()
        reqs = [st.request_view(st.add_request(ctx.user, uid, share, note, ts))
                for uid, share in zip(uids, shares) if uid != ctx.user]
        sid = st.new_id("sp", {})
        return 201, {"split_id": sid, "amount": amount, "currency": st.currency, "note": note,
                     "shares": [{"handle": h, "amount": s} for h, s in zip(handles, shares)],
                     "requests": reqs, "created_at": ts}
    return idempotent(ctx, op)


def h_settlement(ctx):
    with LOCK:
        if ctx.user not in STATE.operators:
            raise ApiError(403, "forbidden", "settlement operators only")

    def op(st, body):
        transfers = body.get("transfers")
        if not isinstance(transfers, list) or not 1 <= len(transfers) <= 32 \
                or not all(isinstance(t, dict) for t in transfers):
            raise invalid("transfers must be 1 to 32 objects")
        parsed = []
        for t in transfers:
            fh = handle_field(t, "from_handle", invalid)
            th = handle_field(t, "to_handle", invalid)
            amount = check_amount(t)
            note = check_note(t)
            vis = check_visibility(t)
            if fh == th:
                raise ApiError(422, "self_payment", "cannot pay yourself")
            parsed.append((lookup_handle(st, fh), lookup_handle(st, th), amount, note, vis))
        delta = {}
        for f, t, a, _, _ in parsed:
            delta[f] = delta.get(f, 0) - a
            delta[t] = delta.get(t, 0) + a
        for uid, d in delta.items():
            after = st.users[uid]["balance"] + d
            if after < 0:
                raise ApiError(409, "insufficient_funds", "settlement is not affordable")
            if after > MAX_BALANCE:
                raise invalid("balance out of range")
        ts = st.now()
        sid = st.new_id("st", {})
        pays = [st.payment_view(st.add_payment(f, t, a, n, v, None, sid, ts))
                for f, t, a, n, v in parsed]
        return 201, {"settlement_id": sid, "committed_at": ts, "payments": pays}
    return idempotent(ctx, op)


# ----------------------------------------------------------------- routing

PUBLIC = {("GET", "/health"): h_health,
          ("POST", "/_test/reset"): h_reset,
          ("GET", "/_test/export"): h_export,
          ("POST", "/_test/import"): h_import,
          ("POST", "/auth/signup"): h_signup,
          ("POST", "/auth/login"): h_login}
AUTHED = {("GET", "/me"): h_me,
          ("POST", "/payments"): h_payment,
          ("POST", "/requests"): h_request_create,
          ("GET", "/requests"): h_requests_list,
          ("POST", "/splits"): h_split,
          ("POST", "/settlements"): h_settlement,
          ("GET", "/activity"): h_activity}
REQ_RE = re.compile(r"^/requests/([^/]+)/(pay|decline|cancel)$")


def route(ctx):
    path = ctx.path
    fn = PUBLIC.get((ctx.method, path))
    if fn:
        return fn(ctx)
    fn = AUTHED.get((ctx.method, path))
    args = ()
    if fn is None:
        m = REQ_RE.match(path)
        if m and ctx.method == "POST":
            rid, action = m.groups()
            args = (rid,) if action == "pay" else (rid, action)
            fn = h_request_pay if action == "pay" else h_request_decide
    if fn is None:
        known = {p for (_, p) in PUBLIC} | {p for (_, p) in AUTHED}
        if path in known or REQ_RE.match(path):
            raise ApiError(405, "method_not_allowed", "method not allowed")
        raise ApiError(404, "not_found", "no such route")
    authenticate(ctx)
    return fn(ctx, *args)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 60

    def log_message(self, *args):
        pass

    def read_body(self):
        te = (self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in te:
            out = bytearray()
            while True:
                line = self.rfile.readline(1024)
                try:
                    size = int(line.split(b";")[0].strip() or b"x", 16)
                except ValueError:
                    raise bad("bad chunk")
                if size == 0:
                    while True:
                        t = self.rfile.readline(1024)
                        if t in (b"\r\n", b"\n", b""):
                            break
                    break
                out += self.rfile.read(size)
                self.rfile.readline(4)
                if len(out) > MAX_BODY:
                    raise bad("body too large")
            return bytes(out)
        cl = self.headers.get("Content-Length")
        if not cl:
            return b""
        try:
            n = int(cl)
        except ValueError:
            raise bad("bad Content-Length")
        if n < 0 or n > MAX_BODY:
            raise bad("bad Content-Length")
        return self.rfile.read(n)

    def send_error(self, code, message=None, explain=None):
        """Framework-generated errors (bad request line, oversized header, ...) use the envelope."""
        if code >= 500:
            code = 400
        self.close_connection = True
        if getattr(self, "request_version", "HTTP/0.9") not in ("HTTP/1.0", "HTTP/1.1"):
            self.request_version = "HTTP/1.1"  # otherwise no status line / headers are written
        self.send(code, {"error": {"code": "malformed_request", "message": message or "bad request"}})

    def __getattr__(self, name):
        # any other HTTP method (TRACE, PROPFIND, ...) is routed, ending in 404/405
        if name.startswith("do_"):
            return self.handle_any
        raise AttributeError(name)

    def send(self, status, payload):
        body = b"" if payload is None else dumps(payload)
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and getattr(self, "command", None) != "HEAD":
            self.wfile.write(body)

    def handle_any(self):
        try:
            try:
                raw = self.read_body()
                parts = urlsplit(self.path)
                query = dict(parse_qsl(parts.query, keep_blank_values=True,
                                       errors="replace"))
                path = unquote(parts.path)
                if len(path) > 1 and path.endswith("/"):
                    path = path.rstrip("/")
                ctx = Ctx(self.command, path, query, self.headers, raw)
                status, payload = route(ctx)
            except ApiError as e:
                status, payload = e.status, {"error": {"code": e.code, "message": e.message}}
            except Exception as e:  # never leak a traceback; still an error envelope
                print("internal error:", repr(e), file=sys.stderr, flush=True)
                status, payload = 500, {"error": {"code": "internal_error",
                                                  "message": "internal error"}}
            self.send(status, payload)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = handle_any


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 512
    allow_reuse_address = True


def main():
    port = int(os.environ.get("PORT") or 8080)
    srv = Server(("0.0.0.0", port), Handler)
    print(f"listening on 0.0.0.0:{port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
