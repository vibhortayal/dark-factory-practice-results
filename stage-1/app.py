"""Pocketful stage 1: payments and settlements. Standard library only."""
import binascii
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

MAX_AMOUNT = 1_000_000_000
MAX_BALANCE = 2 ** 53
HANDLE_RE = re.compile(r"^[a-z0-9_]{1,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")
DIGITS_RE = re.compile(r"^[0-9]+$", re.ASCII)
STATUSES = ("pending", "paid", "declined", "cancelled")
SCRYPT = {"n": 2048, "r": 8, "p": 1}

LOCK = threading.RLock()


class ApiError(Exception):
    def __init__(self, status, code, message=None):
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code.replace("_", " ")


def bad(code="validation_failed", message=None, status=422):
    return ApiError(status, code, message)


def malformed(message="malformed request"):
    return ApiError(400, "malformed_request", message)


# ---------------------------------------------------------------- helpers

def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def new_id(prefix, taken):
    while True:
        i = prefix + "_" + uuid.uuid4().hex[:16]
        if i not in taken:
            return i


def hash_password(password, salt=None):
    salt = salt or os.urandom(16)
    h = hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt,
                       n=SCRYPT["n"], r=SCRYPT["r"], p=SCRYPT["p"], dklen=32,
                       maxmem=64 * 1024 * 1024)
    return {"salt": salt.hex(), "hash": h.hex(), **SCRYPT}


def check_password(password, rec):
    try:
        h = hashlib.scrypt(password.encode("utf-8", "surrogatepass"),
                           salt=bytes.fromhex(rec["salt"]), n=rec["n"], r=rec["r"],
                           p=rec["p"], dklen=32, maxmem=64 * 1024 * 1024)
    except Exception:
        return False
    return hmac.compare_digest(h.hex(), rec["hash"])


def is_integral(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, float) and v.is_integer()


def normalize(v):
    """Make numerically equal JSON numbers compare equal."""
    if isinstance(v, bool):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, list):
        return [normalize(x) for x in v]
    if isinstance(v, dict):
        return {k: normalize(x) for k, x in v.items()}
    return v


def canon(v):
    return json.dumps(normalize(v), sort_keys=True, separators=(",", ":"))


def _no_const(name):
    raise ValueError("bad constant " + name)


def parse_json(raw):
    try:
        text = raw.decode("utf-8")
        return json.loads(text, parse_constant=_no_const)
    except (ValueError, RecursionError):
        raise malformed("body is not valid JSON")


def parse_object(raw, empty_ok=False):
    if empty_ok and not raw.strip():
        return {}
    v = parse_json(raw)
    if not isinstance(v, dict):
        raise malformed("body must be a JSON object")
    return v


def v_amount(body, key="amount"):
    if key not in body:
        raise bad(message=key + " is required")
    v = body[key]
    if not is_integral(v):
        raise bad(message=key + " must be an integer")
    v = int(v)
    if v < 1 or v > MAX_AMOUNT:
        raise bad(message=key + " out of range")
    return v


def v_note(body):
    if "note" not in body:
        return ""
    n = body["note"]
    if not isinstance(n, str):
        raise bad(message="note must be a string")
    if len(n) > 200:
        raise bad(message="note too long")
    return n


def v_visibility(body):
    if "visibility" not in body:
        return "public"
    v = body["visibility"]
    if not isinstance(v, str) or v not in ("public", "private"):
        raise bad(message="visibility must be public or private")
    return v


def v_handle(body, key, wrong_type=None):
    if key not in body:
        raise bad(message=key + " is required")
    h = body[key]
    if not isinstance(h, str):
        if wrong_type == 422:
            raise bad(message=key + " must be a string")
        raise malformed(key + " must be a string")
    return h


def query_int(q, name, default, lo, hi=None):
    if name not in q:
        return default
    s = q[name][0]
    if not DIGITS_RE.match(s) or len(s) > 18:
        raise bad(message=name + " must be a plain integer")
    v = int(s)
    if v < lo or (hi is not None and v > hi):
        raise bad(message=name + " out of range")
    return v


# ---------------------------------------------------------------- state

class State:
    def __init__(self):
        self.currency = "EUR"
        self.minor_units = 2
        self.users = {}       # id -> dict
        self.by_email = {}
        self.by_handle = {}
        self.tokens = {}
        self.payments = []    # oldest first
        self.pay_by_id = {}
        self.requests = []
        self.req_by_id = {}
        self.operators = set()
        self.idem = {}        # (user_id, method, path, key) -> (canon_body, response)

    def add_user(self, u):
        self.users[u["id"]] = u
        self.by_email[u["email"].lower()] = u
        self.by_handle[u["handle"]] = u


STATE = State()


def payment_view(st, p):
    return {
        "payment_id": p["id"],
        "from_user_id": p["from"],
        "from_handle": st.users[p["from"]]["handle"],
        "to_user_id": p["to"],
        "to_handle": st.users[p["to"]]["handle"],
        "amount": p["amount"],
        "currency": st.currency,
        "note": p["note"],
        "visibility": p["visibility"],
        "request_id": p["request_id"],
        "settlement_id": p["settlement_id"],
        "created_at": p["created_at"],
    }


def request_view(st, r):
    return {
        "request_id": r["id"],
        "requester_id": r["requester"],
        "requester_handle": st.users[r["requester"]]["handle"],
        "payer_id": r["payer"],
        "payer_handle": st.users[r["payer"]]["handle"],
        "amount": r["amount"],
        "currency": st.currency,
        "note": r["note"],
        "status": r["status"],
        "payment_id": r["payment_id"],
        "created_at": r["created_at"],
    }


def new_payment(st, sender, receiver, amount, note, vis, request_id, settlement_id,
                created_at):
    p = {"id": new_id("p", st.pay_by_id), "from": sender["id"], "to": receiver["id"],
         "amount": amount, "note": note, "visibility": vis, "request_id": request_id,
         "settlement_id": settlement_id, "created_at": created_at}
    sender["balance"] -= amount
    receiver["balance"] += amount
    st.payments.append(p)
    st.pay_by_id[p["id"]] = p
    return p


def new_request(st, requester, payer, amount, note, created_at):
    r = {"id": new_id("rq", st.req_by_id), "requester": requester["id"],
         "payer": payer["id"], "amount": amount, "note": note, "status": "pending",
         "payment_id": None, "created_at": created_at}
    st.requests.append(r)
    st.req_by_id[r["id"]] = r
    return r


# ---------------------------------------------------------------- fixture / import

def req_str(d, key, maxlen=None, optional=False, default=None):
    if key not in d:
        if optional:
            return default
        raise bad(message=key + " is required")
    v = d[key]
    if not isinstance(v, str):
        raise bad(message=key + " must be a string")
    if maxlen is not None and len(v) > maxlen:
        raise bad(message=key + " too long")
    return v


def balance_value(v):
    if not is_integral(v):
        raise bad(message="balance must be an integer")
    v = int(v)
    if v < 0 or v > MAX_BALANCE:
        raise bad(message="balance out of range")
    return v


def common_header(obj):
    cur = obj.get("currency", "EUR")
    if not isinstance(cur, str) or not cur:
        raise bad(message="currency must be a string")
    mu = obj.get("minor_units", 2)
    if not is_integral(mu) or int(mu) not in (0, 2, 3):
        raise bad(message="minor_units must be 0, 2 or 3")
    return cur, int(mu)


def build_from_fixture(obj):
    """Validate a reset fixture and build a fresh State (hashing outside the lock)."""
    if not isinstance(obj, dict):
        raise bad(message="fixture must be an object")
    st = State()
    st.currency, st.minor_units = common_header(obj)
    users = obj.get("users", [])
    if not isinstance(users, list):
        raise bad(message="users must be a list")
    passwords = []
    for u in users:
        if not isinstance(u, dict):
            raise bad(message="user must be an object")
        uid = req_str(u, "id", 64)
        if not uid:
            raise bad(message="id must not be empty")
        email = req_str(u, "email")
        handle = req_str(u, "handle")
        password = req_str(u, "password")
        display = req_str(u, "display_name", optional=True, default=handle)
        if not HANDLE_RE.match(handle):
            raise bad(message="invalid handle")
        bal = balance_value(u.get("balance", 0))
        if uid in st.users or email.lower() in st.by_email or handle in st.by_handle:
            raise bad(message="duplicate user")
        st.add_user({"id": uid, "email": email, "display_name": display,
                     "handle": handle, "balance": bal, "pw": None})
        passwords.append((uid, password))
    if passwords:
        with ThreadPoolExecutor(4) as ex:
            for (uid, _), pw in zip(passwords, ex.map(lambda x: hash_password(x[1]), passwords)):
                st.users[uid]["pw"] = pw
    ops = obj.get("settlement_operator_ids", [])
    if not isinstance(ops, list) or not all(isinstance(x, str) for x in ops):
        raise bad(message="settlement_operator_ids must be a list of ids")
    for x in ops:
        if x not in st.users:
            raise bad(message="unknown operator")
    st.operators = set(ops)
    base = int(datetime.now(timezone.utc).timestamp())
    stamp = datetime.fromtimestamp(base, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    payments = obj.get("payments", [])
    requests = obj.get("requests", [])
    if not isinstance(payments, list) or not isinstance(requests, list):
        raise bad(message="payments and requests must be lists")
    for p in payments:
        if not isinstance(p, dict):
            raise bad(message="payment must be an object")
        pid = req_str(p, "id", 64)
        a, b = req_str(p, "from_user_id"), req_str(p, "to_user_id")
        if a not in st.users or b not in st.users or pid in st.pay_by_id or not pid:
            raise bad(message="bad seeded payment")
        amount = p.get("amount")
        if not is_integral(amount) or int(amount) < 0 or int(amount) > MAX_BALANCE:
            raise bad(message="bad seeded payment amount")
        vis = p.get("visibility", "public")
        if vis not in ("public", "private") or not isinstance(vis, str):
            raise bad(message="bad seeded visibility")
        note = req_str(p, "note", optional=True, default="")
        rid = p.get("request_id")
        sid = p.get("settlement_id")
        if rid is not None and not isinstance(rid, str):
            raise bad(message="bad request_id")
        if sid is not None and not isinstance(sid, str):
            raise bad(message="bad settlement_id")
        rec = {"id": pid, "from": a, "to": b, "amount": int(amount), "note": note,
               "visibility": vis, "request_id": rid, "settlement_id": sid,
               "created_at": stamp}
        st.payments.append(rec)
        st.pay_by_id[pid] = rec
    for r in requests:
        if not isinstance(r, dict):
            raise bad(message="request must be an object")
        rid = req_str(r, "id", 64)
        a, b = req_str(r, "requester_id"), req_str(r, "payer_id")
        if a not in st.users or b not in st.users or rid in st.req_by_id or not rid:
            raise bad(message="bad seeded request")
        amount = r.get("amount")
        if not is_integral(amount) or int(amount) < 0 or int(amount) > MAX_BALANCE:
            raise bad(message="bad seeded request amount")
        status = r.get("status", "pending")
        if not isinstance(status, str) or status not in STATUSES:
            raise bad(message="bad seeded status")
        note = req_str(r, "note", optional=True, default="")
        pid = r.get("payment_id")
        if pid is not None and not isinstance(pid, str):
            raise bad(message="bad payment_id")
        rec = {"id": rid, "requester": a, "payer": b, "amount": int(amount),
               "note": note, "status": status, "payment_id": pid, "created_at": stamp}
        st.requests.append(rec)
        st.req_by_id[rid] = rec
    return st


def export_state(st):
    users = []
    for u in st.users.values():
        users.append({"id": u["id"], "email": u["email"],
                      "display_name": u["display_name"], "handle": u["handle"],
                      "balance": u["balance"], "password_hash": u["pw"]})
    return {
        "currency": st.currency,
        "minor_units": st.minor_units,
        "users": users,
        "tokens": dict(st.tokens),
        "payments": [dict(p) for p in st.payments],
        "requests": [dict(r) for r in st.requests],
        "settlement_operator_ids": sorted(st.operators),
        "idempotency": [{"user_id": k[0], "method": k[1], "path": k[2], "key": k[3],
                         "body": v[0], "response": v[1]}
                        for k, v in st.idem.items()],
    }


def is_hex(s):
    try:
        bytes.fromhex(s)
        return True
    except (ValueError, TypeError):
        return False


def build_from_export(obj):
    """Rebuild a State from the opaque exported state, validating it fully."""
    try:
        return _build_from_export(obj)
    except ApiError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise bad(message="invalid state")


def _int(v, lo=0, hi=MAX_BALANCE):
    if isinstance(v, bool) or not isinstance(v, int) or v < lo or v > hi:
        raise bad(message="invalid number in state")
    return v


def _str(v, maxlen=None):
    if not isinstance(v, str) or (maxlen is not None and len(v) > maxlen):
        raise bad(message="invalid string in state")
    return v


def _opt_str(v):
    return None if v is None else _str(v)


def _build_from_export(obj):
    if not isinstance(obj, dict):
        raise bad(message="state must be an object")
    st = State()
    st.currency = _str(obj["currency"])
    st.minor_units = _int(obj["minor_units"], 0, 3)
    if st.minor_units not in (0, 2, 3):
        raise bad(message="invalid minor_units")
    for u in obj["users"]:
        pw = u["password_hash"]
        rec = {"salt": _str(pw["salt"]), "hash": _str(pw["hash"]),
               "n": _int(pw["n"], 2, 2 ** 20), "r": _int(pw["r"], 1, 64),
               "p": _int(pw["p"], 1, 16)}
        if not is_hex(rec["salt"]) or not is_hex(rec["hash"]):
            raise bad(message="invalid password hash")
        uid = _str(u["id"], 64)
        email = _str(u["email"])
        handle = _str(u["handle"])
        if not HANDLE_RE.match(handle):
            raise bad(message="invalid handle")
        if uid in st.users or email.lower() in st.by_email or handle in st.by_handle:
            raise bad(message="duplicate user")
        st.add_user({"id": uid, "email": email, "display_name": _str(u["display_name"]),
                     "handle": handle, "balance": _int(u["balance"]), "pw": rec})
    for tok, uid in obj["tokens"].items():
        if _str(uid) not in st.users:
            raise bad(message="token for unknown user")
        st.tokens[_str(tok)] = uid
    for p in obj["payments"]:
        rec = {"id": _str(p["id"], 64), "from": _str(p["from"]), "to": _str(p["to"]),
               "amount": _int(p["amount"]), "note": _str(p["note"]),
               "visibility": _str(p["visibility"]), "request_id": _opt_str(p["request_id"]),
               "settlement_id": _opt_str(p["settlement_id"]),
               "created_at": _str(p["created_at"])}
        if (rec["from"] not in st.users or rec["to"] not in st.users
                or rec["visibility"] not in ("public", "private")
                or rec["id"] in st.pay_by_id):
            raise bad(message="invalid payment")
        st.payments.append(rec)
        st.pay_by_id[rec["id"]] = rec
    for r in obj["requests"]:
        rec = {"id": _str(r["id"], 64), "requester": _str(r["requester"]),
               "payer": _str(r["payer"]), "amount": _int(r["amount"]),
               "note": _str(r["note"]), "status": _str(r["status"]),
               "payment_id": _opt_str(r["payment_id"]),
               "created_at": _str(r["created_at"])}
        if (rec["requester"] not in st.users or rec["payer"] not in st.users
                or rec["status"] not in STATUSES or rec["id"] in st.req_by_id):
            raise bad(message="invalid request")
        st.requests.append(rec)
        st.req_by_id[rec["id"]] = rec
    ops = obj["settlement_operator_ids"]
    if not isinstance(ops, list):
        raise bad(message="invalid operators")
    for x in ops:
        if _str(x) not in st.users:
            raise bad(message="unknown operator")
    st.operators = set(ops)
    for e in obj["idempotency"]:
        k = (_str(e["user_id"]), _str(e["method"]), _str(e["path"]), _str(e["key"]))
        if k[0] not in st.users or not isinstance(e["response"], dict):
            raise bad(message="invalid idempotency record")
        st.idem[k] = (_str(e["body"]), e["response"])
    return st


# ---------------------------------------------------------------- endpoints

class Ctx:
    def __init__(self, handler, method, path, query, raw, headers):
        self.method = method
        self.path = path
        self.query = query
        self.raw = raw
        self.headers = headers
        self.user = None


def authenticate(ctx):
    h = ctx.headers.get("Authorization")
    if h is None:
        raise ApiError(401, "unauthenticated", "missing bearer token")
    parts = h.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise ApiError(401, "unauthenticated", "malformed bearer token")
    with LOCK:
        uid = STATE.tokens.get(parts[1])
        if uid is None or uid not in STATE.users:
            raise ApiError(401, "unauthenticated", "unknown token")
        ctx.user = uid
    return uid


def derive_handle(email):
    local = email.split("@", 1)[0].lower()
    return re.sub(r"[^a-z0-9_]", "_", local)[:20]


def new_token(st, uid):
    while True:
        t = secrets.token_urlsafe(32)
        if t not in st.tokens:
            st.tokens[t] = uid
            return t


def ep_signup(ctx):
    body = parse_object(ctx.raw)
    email = v_handle(body, "email")
    password = v_handle(body, "password")
    display = v_handle(body, "display_name")
    if not EMAIL_RE.match(email):
        raise bad(message="invalid email")
    if len(password) < 8:
        raise bad(message="password too short")
    pw = hash_password(password)
    with LOCK:
        st = STATE
        if email.lower() in st.by_email:
            raise ApiError(409, "email_taken", "email already registered")
        handle = derive_handle(email)
        if handle in st.by_handle:
            raise ApiError(409, "handle_taken", "handle already taken")
        uid = new_id("u", st.users)
        st.add_user({"id": uid, "email": email, "display_name": display,
                     "handle": handle, "balance": 0, "pw": pw})
        tok = new_token(st, uid)
    return 201, {"user_id": uid, "display_name": display, "token": tok}


def ep_login(ctx):
    body = parse_object(ctx.raw)
    email = v_handle(body, "email")
    password = v_handle(body, "password")
    with LOCK:
        u = STATE.by_email.get(email.lower())
        rec = u["pw"] if u else None
    ok = check_password(password, rec) if rec else False
    if not ok:
        raise ApiError(401, "unauthenticated", "invalid credentials")
    with LOCK:
        if STATE.users.get(u["id"]) is not u:
            raise ApiError(401, "unauthenticated", "invalid credentials")
        tok = new_token(STATE, u["id"])
        return 200, {"user_id": u["id"], "display_name": u["display_name"], "token": tok}


def ep_me(ctx):
    authenticate(ctx)
    with LOCK:
        st = STATE
        u = st.users[ctx.user]
        return 200, {"user_id": u["id"], "display_name": u["display_name"],
                     "handle": u["handle"], "balance": u["balance"],
                     "currency": st.currency, "minor_units": st.minor_units}


def idempotent(ctx, fn, operator_only=False):
    """Shared preamble of the five idempotent write paths (see §7)."""
    uid = authenticate(ctx)
    if operator_only:
        with LOCK:
            if uid not in STATE.operators:
                raise ApiError(403, "forbidden", "settlement operator required")
    key = ctx.headers.get("Idempotency-Key")
    if key is None or key.strip() == "":
        raise ApiError(400, "missing_idempotency_key", "Idempotency-Key required")
    if len(key) > 255:
        raise bad(message="Idempotency-Key too long")
    body = parse_object(ctx.raw, empty_ok=(ctx.pathkind == "pay"))
    cb = canon(body)
    rk = (uid, ctx.method, ctx.path, key)
    with LOCK:
        st = STATE
        rec = st.idem.get(rk)
        if rec is not None:
            if rec[0] != cb:
                raise ApiError(409, "idempotency_key_reuse",
                               "key already used with a different body")
            return 200, rec[1]
        resp = fn(st, st.users[uid], body)
        st.idem[rk] = (cb, resp)
        return 201, resp


def lookup_handle(st, h):
    u = st.by_handle.get(h)
    if u is None:
        raise ApiError(404, "not_found", "no such handle")
    return u


def ep_payments(ctx):
    def run(st, me, body):
        amount = v_amount(body)
        note = v_note(body)
        vis = v_visibility(body)
        to = v_handle(body, "to_handle")
        other = lookup_handle(st, to)
        if other["id"] == me["id"]:
            raise bad("self_payment", "cannot pay yourself")
        if me["balance"] < amount:
            raise ApiError(409, "insufficient_funds", "insufficient funds")
        p = new_payment(st, me, other, amount, note, vis, None, None, now_str())
        return payment_view(st, p)
    return idempotent(ctx, run)


def ep_requests_create(ctx):
    def run(st, me, body):
        amount = v_amount(body)
        note = v_note(body)
        ph = v_handle(body, "payer_handle")
        payer = lookup_handle(st, ph)
        if payer["id"] == me["id"]:
            raise bad("self_request", "cannot request from yourself")
        r = new_request(st, me, payer, amount, note, now_str())
        return request_view(st, r)
    return idempotent(ctx, run)


def ep_pay(ctx):
    rid = ctx.params[0]

    def run(st, me, body):
        vis = v_visibility(body)
        r = st.req_by_id.get(rid)
        if r is None:
            raise ApiError(404, "not_found", "no such request")
        if r["payer"] != me["id"]:
            raise ApiError(403, "forbidden", "only the payer may pay")
        if r["status"] != "pending":
            raise ApiError(409, "request_not_pending", "request is not pending")
        if me["balance"] < r["amount"]:
            raise ApiError(409, "insufficient_funds", "insufficient funds")
        requester = st.users[r["requester"]]
        p = new_payment(st, me, requester, r["amount"], r["note"], vis, r["id"], None,
                        now_str())
        r["status"] = "paid"
        r["payment_id"] = p["id"]
        return payment_view(st, p)
    return idempotent(ctx, run)


def ep_transition(ctx):
    authenticate(ctx)
    rid, action = ctx.params
    with LOCK:
        st = STATE
        r = st.req_by_id.get(rid)
        if r is None:
            raise ApiError(404, "not_found", "no such request")
        if action == "decline":
            actor, target = r["payer"], "declined"
        else:
            actor, target = r["requester"], "cancelled"
        if ctx.user != actor:
            raise ApiError(403, "forbidden", "not permitted for this request")
        if r["status"] == "pending":
            r["status"] = target
        elif r["status"] != target:
            raise ApiError(409, "request_not_pending", "request is not pending")
        return 200, request_view(st, r)


def page_params(q):
    limit = query_int(q, "limit", 50, 1, 200)
    offset = query_int(q, "offset", 0, 0)
    return limit, offset


def ep_requests_list(ctx):
    authenticate(ctx)
    q = ctx.query
    limit, offset = page_params(q)
    direction = q["direction"][0] if "direction" in q else None
    status = q["status"][0] if "status" in q else None
    if direction is not None and direction not in ("incoming", "outgoing"):
        raise bad(message="invalid direction")
    if status is not None and status not in STATUSES:
        raise bad(message="invalid status")
    with LOCK:
        st = STATE
        me = ctx.user
        out = []
        for r in reversed(st.requests):
            if direction == "incoming":
                ok = r["payer"] == me
            elif direction == "outgoing":
                ok = r["requester"] == me
            else:
                ok = r["payer"] == me or r["requester"] == me
            if ok and (status is None or r["status"] == status):
                out.append(r)
        page = out[offset:offset + limit]
        return 200, {"requests": [request_view(st, r) for r in page],
                     "has_more": offset + limit < len(out)}


def ep_activity(ctx):
    authenticate(ctx)
    limit, offset = page_params(ctx.query)
    with LOCK:
        st = STATE
        me = ctx.user
        out = [p for p in reversed(st.payments)
               if p["visibility"] == "public" or p["from"] == me or p["to"] == me]
        page = out[offset:offset + limit]
        return 200, {"payments": [payment_view(st, p) for p in page],
                     "has_more": offset + limit < len(out)}


def ep_splits(ctx):
    def run(st, me, body):
        amount = v_amount(body)
        note = v_note(body)
        if "participant_handles" not in body:
            raise bad(message="participant_handles is required")
        hs = body["participant_handles"]
        if not isinstance(hs, list) or not all(isinstance(h, str) for h in hs):
            raise malformed("participant_handles must be a list of strings")
        if not hs or len(set(hs)) != len(hs):
            raise bad(message="participants empty or duplicated")
        users = [lookup_handle(st, h) for h in hs]
        n = len(hs)
        base, rem = divmod(amount, n)
        shares = [base + (1 if i < rem else 0) for i in range(n)]
        ts = now_str()
        reqs = []
        for u, s in zip(users, shares):
            if u["id"] != me["id"]:
                reqs.append(request_view(st, new_request(st, me, u, s, note, ts)))
        sid = new_id("sp", {})
        return {"split_id": sid, "amount": amount, "currency": st.currency,
                "note": note,
                "shares": [{"handle": h, "amount": s} for h, s in zip(hs, shares)],
                "requests": reqs, "created_at": ts}
    return idempotent(ctx, run)


def ep_settlements(ctx):
    def run(st, me, body):
        tr = body.get("transfers")
        if not isinstance(tr, list) or not 1 <= len(tr) <= 32:
            raise bad(message="transfers must be a list of 1 to 32 objects")
        entries = []
        for t in tr:
            if not isinstance(t, dict):
                raise bad(message="transfer must be an object")
            amount = v_amount(t)
            note = v_note(t)
            vis = v_visibility(t)
            fh = v_handle(t, "from_handle", 422)
            th = v_handle(t, "to_handle", 422)
            a = lookup_handle(st, fh)
            b = lookup_handle(st, th)
            if a["id"] == b["id"]:
                raise bad("self_payment", "cannot pay yourself")
            entries.append((a, b, amount, note, vis))
        net = {}
        for a, b, amount, _, _ in entries:
            net[a["id"]] = net.get(a["id"], 0) - amount
            net[b["id"]] = net.get(b["id"], 0) + amount
        for uid, d in net.items():
            if st.users[uid]["balance"] + d < 0:
                raise ApiError(409, "insufficient_funds", "insufficient funds")
        ts = now_str()
        sid = new_id("st", {})
        pays = []
        for a, b, amount, note, vis in entries:
            p = new_payment(st, a, b, amount, note, vis, None, sid, ts)
            pays.append(payment_view(st, p))
        return {"settlement_id": sid, "committed_at": ts, "payments": pays}
    return idempotent(ctx, run, operator_only=True)


def ep_health(ctx):
    return 200, {"status": "ok"}


def ep_reset(ctx):
    obj = parse_object(ctx.raw)
    st = build_from_fixture(obj)
    global STATE
    with LOCK:
        STATE = st
    return 204, None


def ep_export(ctx):
    with LOCK:
        state = export_state(STATE)
        text = json.dumps({"track": "pocketful", "format_version": 1, "state": state})
    return 200, RawJson(text)


def ep_import(ctx):
    obj = parse_object(ctx.raw)
    if obj.get("track") != "pocketful" or "state" not in obj:
        raise bad(message="bad track or missing state")
    ver = obj.get("format_version")
    if isinstance(ver, bool) or ver != 1:
        raise bad(message="bad format_version")
    st = build_from_export(copy.deepcopy(obj["state"]))
    global STATE
    with LOCK:
        STATE = st
    return 204, None


class RawJson:
    def __init__(self, text):
        self.text = text


ROUTES = [
    ("GET", re.compile(r"^/health$"), ep_health, "health"),
    ("POST", re.compile(r"^/_test/reset$"), ep_reset, "reset"),
    ("GET", re.compile(r"^/_test/export$"), ep_export, "export"),
    ("POST", re.compile(r"^/_test/import$"), ep_import, "import"),
    ("POST", re.compile(r"^/auth/signup$"), ep_signup, "signup"),
    ("POST", re.compile(r"^/auth/login$"), ep_login, "login"),
    ("GET", re.compile(r"^/me$"), ep_me, "me"),
    ("POST", re.compile(r"^/payments$"), ep_payments, "payments"),
    ("POST", re.compile(r"^/requests$"), ep_requests_create, "requests"),
    ("GET", re.compile(r"^/requests$"), ep_requests_list, "requests_list"),
    ("POST", re.compile(r"^/requests/([^/]+)/pay$"), ep_pay, "pay"),
    ("POST", re.compile(r"^/requests/([^/]+)/(decline|cancel)$"), ep_transition,
     "transition"),
    ("POST", re.compile(r"^/splits$"), ep_splits, "splits"),
    ("GET", re.compile(r"^/activity$"), ep_activity, "activity"),
    ("POST", re.compile(r"^/settlements$"), ep_settlements, "settlements"),
]


def route(method, path):
    path_matched = False
    for m, rx, fn, kind in ROUTES:
        mt = rx.match(path)
        if mt:
            path_matched = True
            if m == method:
                return fn, kind, [unquote(g) for g in mt.groups()]
    if path_matched:
        raise ApiError(405, "method_not_allowed", "method not allowed")
    raise ApiError(404, "not_found", "no such route")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 60
    server_version = "pocketful"

    def log_message(self, *a):
        pass

    def read_body(self):
        te = self.headers.get("Transfer-Encoding", "")
        if "chunked" in te.lower():
            data = b""
            while True:
                line = self.rfile.readline(1024)
                if not line:
                    break
                try:
                    size = int(line.split(b";")[0].strip() or b"0", 16)
                except ValueError:
                    raise malformed("bad chunk")
                if size == 0:
                    while True:
                        t = self.rfile.readline(1024)
                        if t in (b"\r\n", b"\n", b""):
                            break
                    break
                data += self.rfile.read(size)
                self.rfile.readline(8)
            return data
        n = self.headers.get("Content-Length")
        if not n:
            return b""
        try:
            n = int(n)
        except ValueError:
            raise malformed("bad content length")
        if n < 0:
            raise malformed("bad content length")
        return self.rfile.read(n)

    def send_json(self, status, payload):
        if payload is None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if isinstance(payload, RawJson):
            data = payload.text.encode("utf-8")
        else:
            data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_error_body(self, e):
        self.send_json(e.status, {"error": {"code": e.code, "message": e.message}})

    def handle_any(self):
        try:
            try:
                raw = self.read_body()
                sp = urlsplit(self.path)
                fn, kind, params = route(self.command, sp.path)
                ctx = Ctx(self, self.command, sp.path,
                          parse_qs(sp.query, keep_blank_values=True), raw, self.headers)
                ctx.params = params
                ctx.pathkind = kind
                status, payload = fn(ctx)
                self.send_json(status, payload)
            except ApiError as e:
                self.send_error_body(e)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            traceback.print_exc(file=sys.stderr)
            try:
                self.send_error_body(ApiError(500, "internal_error", "internal error"))
            except Exception:
                self.close_connection = True

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = handle_any

    def do_HEAD(self):
        self.handle_any()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 512
    allow_reuse_address = True


def main():
    port = int(os.environ.get("PORT", "8080") or "8080")
    srv = Server(("0.0.0.0", port), Handler)
    srv.serve_forever()


if __name__ == "__main__":
    main()
