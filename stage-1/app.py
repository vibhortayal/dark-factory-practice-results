"""Pocketful stage 1: payments, requests, splits, feed, settlements.

Standard library only. All state lives in memory behind one lock, so every
operation (including idempotent replays) is atomic and serialised.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit

MAX_AMOUNT = 1_000_000_000
MAX_BALANCE = 2 ** 53
HANDLE_RE = re.compile(r"^[a-z0-9_]{1,20}$")
DIGITS_RE = re.compile(r"[0-9]+")
STATUSES = ("pending", "paid", "declined", "cancelled")
VISIBILITIES = ("public", "private")
MAX_BODY = 32 * 1024 * 1024

# scrypt cost: affordable for a reset with many users inside 10 s on 2 vCPU.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 4096, 8, 1

LOCK = threading.RLock()


class ApiError(Exception):
    def __init__(self, status, code, message=""):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message or code


def malformed(msg="malformed request"):
    return ApiError(400, "malformed_request", msg)


def invalid(msg="validation failed"):
    return ApiError(422, "validation_failed", msg)


# ---------------------------------------------------------------- helpers

def now_str(dt=None):
    return (dt or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def hash_password(password):
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt, n=SCRYPT_N,
                       r=SCRYPT_R, p=SCRYPT_P, maxmem=64 * 1024 * 1024)
    return "scrypt$%d$%d$%d$%s$%s" % (SCRYPT_N, SCRYPT_R, SCRYPT_P, salt.hex(), h.hex())


def verify_password(password, encoded):
    try:
        alg, n, r, p, salt, exp = encoded.split("$")
        if alg != "scrypt":
            return False
        h = hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=bytes.fromhex(salt),
                           n=int(n), r=int(r), p=int(p), maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(h.hex(), exp)
    except (ValueError, TypeError, AttributeError):
        return False


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def json_eq(a, b):
    """Equality of parsed JSON values; booleans are not numbers."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_eq(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_eq(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def _bad_constant(name):
    raise ValueError("bad constant " + name)


def parse_json(raw):
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_bad_constant)
    except (ValueError, RecursionError, UnicodeDecodeError):
        raise malformed("body is not valid JSON")


def parse_object(raw, allow_empty=False):
    if allow_empty and not raw.strip():
        return {}
    body = parse_json(raw)
    if not isinstance(body, dict):
        raise malformed("body must be a JSON object")
    return body


def check_amount(v, lo=1):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid("amount must be an integer")
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")) or not v.is_integer():
            raise invalid("amount must be an integer")
        v = int(v)
    if v < lo or v > MAX_AMOUNT:
        raise invalid("amount out of range")
    return v


def check_note(body):
    if "note" not in body:
        return ""
    n = body["note"]
    if not isinstance(n, str):
        raise invalid("note must be a string")
    if len(n) > 200:
        raise invalid("note too long")
    return n


def check_visibility(body):
    if "visibility" not in body:
        return "public"
    v = body["visibility"]
    if not isinstance(v, str) or v not in VISIBILITIES:
        raise invalid("visibility must be public or private")
    return v


def need_handle(body, field):
    if field not in body:
        raise invalid("%s is required" % field)
    v = body[field]
    if not isinstance(v, str):
        raise malformed("%s must be a string" % field)
    return v


def parse_int_param(q, name, default, lo):
    if name not in q:
        return default
    s = q[name]
    if not DIGITS_RE.fullmatch(s):
        raise invalid("%s must be plain decimal digits" % name)
    v = int(s)
    if v < lo:
        raise invalid("%s out of range" % name)
    return v


def page_params(q):
    limit = parse_int_param(q, "limit", 50, 1)
    if limit > 200:
        raise invalid("limit out of range")
    offset = parse_int_param(q, "offset", 0, 0)
    return limit, offset


# ------------------------------------------------------------------ state

class Store:
    def __init__(self):
        self.load({"currency": "EUR", "minor_units": 2, "users": [], "tokens": {}, "payments": [],
                   "requests": [], "splits": [], "settlements": [], "idempotency": [],
                   "operators": [], "counters": {}})

    def load(self, st):
        """Install a validated state dict (JSON-shaped) as the live state."""
        self.currency = st["currency"]
        self.minor_units = st["minor_units"]
        self.users = {u["id"]: u for u in st["users"]}
        self.by_handle = {u["handle"]: u for u in st["users"]}
        self.by_email = {u["email"]: u for u in st["users"]}
        self.tokens = dict(st["tokens"])
        self.payments = list(st["payments"])
        self.payments_by_id = {p["id"]: p for p in self.payments}
        self.requests = list(st["requests"])
        self.requests_by_id = {r["id"]: r for r in self.requests}
        self.splits = list(st["splits"])
        self.settlements = list(st["settlements"])
        self.idem = {}
        for e in st["idempotency"]:
            self.idem[(e["user_id"], e["method"], e["path"], e["key"])] = e
        self.operators = list(st["operators"])
        self.counters = dict(st["counters"])

    def export(self):
        st = {
            "currency": self.currency, "minor_units": self.minor_units,
            "users": list(self.users.values()), "tokens": self.tokens,
            "payments": self.payments, "requests": self.requests,
            "splits": self.splits, "settlements": self.settlements,
            "idempotency": list(self.idem.values()), "operators": self.operators,
            "counters": self.counters,
        }
        return json.loads(json.dumps(st))  # deep, atomic copy (caller holds the lock)

    def new_id(self, prefix, taken):
        while True:
            n = self.counters.get(prefix, 0) + 1
            self.counters[prefix] = n
            cand = "%s_%d" % (prefix, n)
            if cand not in taken:
                return cand

    # --- views
    def payment_view(self, p):
        f, t = self.users[p["from_user_id"]], self.users[p["to_user_id"]]
        return {
            "payment_id": p["id"], "from_user_id": f["id"], "from_handle": f["handle"],
            "to_user_id": t["id"], "to_handle": t["handle"], "amount": p["amount"],
            "currency": self.currency, "note": p["note"], "visibility": p["visibility"],
            "request_id": p.get("request_id"), "settlement_id": p.get("settlement_id"),
            "created_at": p["created_at"],
        }

    def request_view(self, r):
        a, b = self.users[r["requester_id"]], self.users[r["payer_id"]]
        return {
            "request_id": r["id"], "requester_id": a["id"], "requester_handle": a["handle"],
            "payer_id": b["id"], "payer_handle": b["handle"], "amount": r["amount"],
            "currency": self.currency, "note": r["note"], "status": r["status"],
            "payment_id": r.get("payment_id"), "created_at": r["created_at"],
        }

    def lookup_handle(self, h):
        u = self.by_handle.get(h) if HANDLE_RE.match(h) else None
        if u is None:
            raise ApiError(404, "not_found", "no such user")
        return u

    def move(self, p_from, p_to, amount, note, visibility, request_id=None,
             settlement_id=None, created_at=None):
        p_from["balance"] -= amount
        p_to["balance"] += amount
        pid = self.new_id("p", self.payments_by_id)
        rec = {"id": pid, "from_user_id": p_from["id"], "to_user_id": p_to["id"],
               "amount": amount, "note": note, "visibility": visibility,
               "request_id": request_id, "settlement_id": settlement_id,
               "created_at": created_at or now_str()}
        self.payments.append(rec)
        self.payments_by_id[pid] = rec
        return rec


S = Store()


# ------------------------------------------------- fixture / state checks

def _str(v, maxlen=None, nonempty=True):
    if not isinstance(v, str) or (nonempty and not v) or (maxlen and len(v) > maxlen):
        raise invalid("bad string field")
    return v


def _email_ok(e):
    return isinstance(e, str) and e.count("@") == 1 and all(e.split("@"))


def _bal(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if not is_int(v) or v < 0 or v > MAX_BALANCE:
        raise invalid("bad balance")
    return v


def _money(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if not is_int(v) or v < 0 or v > MAX_BALANCE:
        raise invalid("bad amount")
    return v


def build_fixture(fx):
    """Validate a reset fixture and return (state dict, password list to hash)."""
    if not isinstance(fx, dict):
        raise malformed("fixture must be an object")
    cur = fx.get("currency")
    if not isinstance(cur, str) or not cur:
        raise invalid("currency required")
    mu = fx.get("minor_units")
    if not is_int(mu) or mu not in (0, 2, 3):
        raise invalid("minor_units must be 0, 2 or 3")
    users_in = fx.get("users")
    if not isinstance(users_in, list):
        raise invalid("users required")
    users, ids, handles, emails, pws = [], set(), set(), set(), []
    for u in users_in:
        if not isinstance(u, dict):
            raise invalid("user must be an object")
        uid = _str(u.get("id"), 64)
        email = u.get("email")
        if not _email_ok(email):
            raise invalid("bad email")
        pw = u.get("password")
        if not isinstance(pw, str):
            raise invalid("bad password")
        dn = u.get("display_name")
        if not isinstance(dn, str):
            raise invalid("bad display_name")
        h = u.get("handle")
        if not isinstance(h, str) or not HANDLE_RE.match(h):
            raise invalid("bad handle")
        bal = _bal(u.get("balance"))
        if uid in ids or h in handles or email in emails:
            raise invalid("duplicate user id, handle or email")
        ids.add(uid), handles.add(h), emails.add(email)
        users.append({"id": uid, "email": email, "pw_hash": None, "display_name": dn,
                      "handle": h, "balance": bal})
        pws.append(pw)
    base = datetime.now(timezone.utc)

    def listing(name):
        v = fx.get(name)
        if v is None:
            return []
        if not isinstance(v, list):
            raise invalid("%s must be an array" % name)
        return v

    payments, pids = [], set()
    pin = listing("payments")
    for i, p in enumerate(pin):
        if not isinstance(p, dict):
            raise invalid("payment must be an object")
        pid = _str(p.get("id"), 64)
        if pid in pids:
            raise invalid("duplicate payment id")
        pids.add(pid)
        if p.get("from_user_id") not in ids or p.get("to_user_id") not in ids:
            raise invalid("payment refers to unknown user")
        note = p.get("note", "")
        vis = p.get("visibility", "public")
        if not isinstance(note, str) or vis not in VISIBILITIES or not isinstance(vis, str):
            raise invalid("bad payment note or visibility")
        payments.append({"id": pid, "from_user_id": p["from_user_id"], "to_user_id": p["to_user_id"],
                         "amount": _money(p.get("amount")), "note": note, "visibility": vis,
                         "request_id": None, "settlement_id": None,
                         "created_at": now_str(base - timedelta(seconds=len(pin) - i))})
    requests, rids = [], set()
    rin = listing("requests")
    for i, r in enumerate(rin):
        if not isinstance(r, dict):
            raise invalid("request must be an object")
        rid = _str(r.get("id"), 64)
        if rid in rids:
            raise invalid("duplicate request id")
        rids.add(rid)
        if r.get("requester_id") not in ids or r.get("payer_id") not in ids:
            raise invalid("request refers to unknown user")
        note = r.get("note", "")
        st = r.get("status", "pending")
        if not isinstance(note, str) or not isinstance(st, str) or st not in STATUSES:
            raise invalid("bad request note or status")
        requests.append({"id": rid, "requester_id": r["requester_id"], "payer_id": r["payer_id"],
                         "amount": _money(r.get("amount")), "note": note, "status": st,
                         "payment_id": None,
                         "created_at": now_str(base - timedelta(seconds=len(rin) - i))})
    ops = fx.get("settlement_operator_ids")
    if ops is None:
        ops = []
    if not isinstance(ops, list) or any(not isinstance(o, str) or o not in ids for o in ops):
        raise invalid("bad settlement_operator_ids")
    state = {"currency": cur, "minor_units": mu, "users": users, "tokens": {}, "payments": payments,
             "requests": requests, "splits": [], "settlements": [], "idempotency": [],
             "operators": list(dict.fromkeys(ops)), "counters": {}}
    return state, pws


_POOL = ThreadPoolExecutor(max_workers=max(2, os.cpu_count() or 2))


def do_reset(fx):
    state, pws = build_fixture(fx)
    for u, h in zip(state["users"], _POOL.map(hash_password, pws)):
        u["pw_hash"] = h
    with LOCK:
        S.load(state)


def validate_state(st):
    """Validate an imported state; raises ApiError(422) on any problem."""
    try:
        return _validate_state(st)
    except ApiError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        raise invalid("invalid state")


def _validate_state(st):
    if not isinstance(st, dict):
        raise invalid("state must be an object")
    if not isinstance(st["currency"], str) or st["minor_units"] not in (0, 2, 3) \
            or not is_int(st["minor_units"]):
        raise invalid("bad currency")
    users, ids, handles, emails = [], set(), set(), set()
    for u in st["users"]:
        if not (isinstance(u["id"], str) and isinstance(u["email"], str)
                and isinstance(u["pw_hash"], str) and isinstance(u["display_name"], str)
                and isinstance(u["handle"], str) and HANDLE_RE.match(u["handle"])
                and is_int(u["balance"]) and 0 <= u["balance"] <= MAX_BALANCE):
            raise invalid("bad user")
        if u["id"] in ids or u["handle"] in handles or u["email"] in emails:
            raise invalid("duplicate user")
        ids.add(u["id"]), handles.add(u["handle"]), emails.add(u["email"])
        users.append({k: u[k] for k in ("id", "email", "pw_hash", "display_name", "handle", "balance")})
    tokens = st["tokens"]
    if not isinstance(tokens, dict) or any(v not in ids for v in tokens.values()):
        raise invalid("bad tokens")
    payments, pids = [], set()
    for p in st["payments"]:
        if not (isinstance(p["id"], str) and p["from_user_id"] in ids and p["to_user_id"] in ids
                and is_int(p["amount"]) and isinstance(p["note"], str)
                and p["visibility"] in VISIBILITIES and isinstance(p["created_at"], str)):
            raise invalid("bad payment")
        if p["id"] in pids:
            raise invalid("duplicate payment")
        pids.add(p["id"])
        payments.append({k: p.get(k) for k in ("id", "from_user_id", "to_user_id", "amount", "note",
                                                "visibility", "request_id", "settlement_id", "created_at")})
    requests, rids = [], set()
    for r in st["requests"]:
        if not (isinstance(r["id"], str) and r["requester_id"] in ids and r["payer_id"] in ids
                and is_int(r["amount"]) and isinstance(r["note"], str)
                and r["status"] in STATUSES and isinstance(r["created_at"], str)):
            raise invalid("bad request")
        if r["id"] in rids:
            raise invalid("duplicate request")
        rids.add(r["id"])
        requests.append({k: r.get(k) for k in ("id", "requester_id", "payer_id", "amount", "note",
                                                "status", "payment_id", "created_at")})
    splits = []
    for s in st["splits"]:
        if not (isinstance(s["id"], str) and isinstance(s["shares"], list)
                and isinstance(s["request_ids"], list)):
            raise invalid("bad split")
        splits.append(json.loads(json.dumps(s)))
    settlements = []
    for s in st["settlements"]:
        if not (isinstance(s["id"], str) and isinstance(s["payment_ids"], list)):
            raise invalid("bad settlement")
        settlements.append(json.loads(json.dumps(s)))
    idem, seen = [], set()
    for e in st["idempotency"]:
        if not (isinstance(e["user_id"], str) and isinstance(e["method"], str)
                and isinstance(e["path"], str) and isinstance(e["key"], str)
                and e["status"] == 201 and isinstance(e["body"], (dict, list, str, int, float, bool, type(None)))):
            raise invalid("bad idempotency record")
        k = (e["user_id"], e["method"], e["path"], e["key"])
        if k in seen:
            raise invalid("duplicate idempotency record")
        seen.add(k)
        idem.append({"user_id": e["user_id"], "method": e["method"], "path": e["path"],
                     "key": e["key"], "body": e["body"], "status": 201, "response": e["response"]})
    ops = st["operators"]
    if not isinstance(ops, list) or any(o not in ids for o in ops):
        raise invalid("bad operators")
    counters = st["counters"]
    if not isinstance(counters, dict) or any(not is_int(v) for v in counters.values()):
        raise invalid("bad counters")
    return {"currency": st["currency"], "minor_units": st["minor_units"], "users": users,
            "tokens": dict(tokens), "payments": payments, "requests": requests, "splits": splits,
            "settlements": settlements, "idempotency": idem, "operators": list(ops),
            "counters": dict(counters)}


# -------------------------------------------------------------- endpoints

def authenticate(headers):
    h = headers.get("Authorization") or ""
    parts = h.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ApiError(401, "unauthenticated", "missing or malformed bearer token")
    uid = S.tokens.get(parts[1].strip())
    if uid is None or uid not in S.users:
        raise ApiError(401, "unauthenticated", "unknown token")
    return S.users[uid]


def idempotent(user, method, path, headers, raw, fn, allow_empty=False):
    """Shared §7 flow. Caller holds LOCK and has authenticated `user`."""
    key = headers.get("Idempotency-Key")
    if key is None or key == "":
        raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header required")
    if len(key) > 255:
        raise invalid("Idempotency-Key too long")
    body = parse_object(raw, allow_empty)
    k = (user["id"], method, path, key)
    rec = S.idem.get(k)
    if rec is not None:
        if json_eq(rec["body"], body):
            return 200, json.loads(json.dumps(rec["response"]))
        raise ApiError(409, "idempotency_key_reuse", "key already used with a different body")
    status, resp = fn(body)
    S.idem[k] = {"user_id": user["id"], "method": method, "path": path, "key": key,
                 "body": body, "status": 201, "response": json.loads(json.dumps(resp))}
    return 201, resp


def signup(raw):
    body = parse_object(raw)
    for f in ("email", "password", "display_name"):
        if f not in body:
            raise invalid("%s is required" % f)
        if not isinstance(body[f], str):
            raise malformed("%s must be a string" % f)
    email, pw, dn = body["email"], body["password"], body["display_name"]
    if not _email_ok(email) or len(pw) < 8:
        raise invalid("bad email or password")
    local = email.split("@")[0]
    handle = re.sub(r"[^a-z0-9_]", "_", local.lower())[:20]
    pw_hash = hash_password(pw)
    with LOCK:
        if email in S.by_email:
            raise ApiError(409, "email_taken", "email already registered")
        if handle in S.by_handle:
            raise ApiError(409, "handle_taken", "handle already taken")
        uid = S.new_id("u", S.users)
        u = {"id": uid, "email": email, "pw_hash": pw_hash, "display_name": dn,
             "handle": handle, "balance": 0}
        S.users[uid] = u
        S.by_handle[handle] = u
        S.by_email[email] = u
        token = secrets.token_hex(24)
        S.tokens[token] = uid
        return 201, {"user_id": uid, "display_name": dn, "token": token}


def login(raw):
    body = parse_object(raw)
    for f in ("email", "password"):
        if f not in body:
            raise invalid("%s is required" % f)
        if not isinstance(body[f], str):
            raise malformed("%s must be a string" % f)
    with LOCK:
        u = S.by_email.get(body["email"])
        pw_hash = u["pw_hash"] if u else None
    if u is None or not verify_password(body["password"], pw_hash):
        raise ApiError(401, "unauthenticated", "wrong email or password")
    with LOCK:
        token = secrets.token_hex(24)
        S.tokens[token] = u["id"]
        return 200, {"user_id": u["id"], "display_name": u["display_name"], "token": token}


def me(user):
    return 200, {"user_id": user["id"], "display_name": user["display_name"],
                 "handle": user["handle"], "balance": user["balance"],
                 "currency": S.currency, "minor_units": S.minor_units}


def create_payment(user, body):
    to_h = need_handle(body, "to_handle")
    if "amount" not in body:
        raise invalid("amount is required")
    amount = check_amount(body["amount"])
    note = check_note(body)
    vis = check_visibility(body)
    to = S.lookup_handle(to_h)
    if to["id"] == user["id"]:
        raise ApiError(422, "self_payment", "cannot pay yourself")
    if user["balance"] < amount:
        raise ApiError(409, "insufficient_funds", "insufficient funds")
    return 201, S.payment_view(S.move(user, to, amount, note, vis))


def new_request_record(requester, payer, amount, note, created_at=None):
    rid = S.new_id("rq", S.requests_by_id)
    rec = {"id": rid, "requester_id": requester["id"], "payer_id": payer["id"], "amount": amount,
           "note": note, "status": "pending", "payment_id": None, "created_at": created_at or now_str()}
    S.requests.append(rec)
    S.requests_by_id[rid] = rec
    return rec


def create_request(user, body):
    ph = need_handle(body, "payer_handle")
    if "amount" not in body:
        raise invalid("amount is required")
    amount = check_amount(body["amount"])
    note = check_note(body)
    payer = S.lookup_handle(ph)
    if payer["id"] == user["id"]:
        raise ApiError(422, "self_request", "cannot request from yourself")
    return 201, S.request_view(new_request_record(user, payer, amount, note))


def pay_request(user, rid, body):
    vis = check_visibility(body)
    r = S.requests_by_id.get(rid)
    if r is None:
        raise ApiError(404, "not_found", "no such request")
    if r["payer_id"] != user["id"]:
        raise ApiError(403, "forbidden", "only the payer may pay")
    if r["status"] != "pending":
        raise ApiError(409, "request_not_pending", "request is not pending")
    if user["balance"] < r["amount"]:
        raise ApiError(409, "insufficient_funds", "insufficient funds")
    to = S.users[r["requester_id"]]
    p = S.move(user, to, r["amount"], r["note"], vis, request_id=r["id"])
    r["status"] = "paid"
    r["payment_id"] = p["id"]
    return 201, S.payment_view(p)


def close_request(user, rid, new_status, role):
    r = S.requests_by_id.get(rid)
    if r is None:
        raise ApiError(404, "not_found", "no such request")
    if r[role] != user["id"]:
        raise ApiError(403, "forbidden", "not permitted")
    if r["status"] == "pending":
        r["status"] = new_status
    elif r["status"] != new_status:
        raise ApiError(409, "request_not_pending", "request is not pending")
    return 200, S.request_view(r)


def list_requests(user, q):
    direction = q.get("direction")
    if direction is not None and direction not in ("incoming", "outgoing"):
        raise invalid("bad direction")
    status = q.get("status")
    if status is not None and status not in STATUSES:
        raise invalid("bad status")
    limit, offset = page_params(q)
    uid = user["id"]
    out, skipped, more = [], 0, False
    for r in reversed(S.requests):
        if direction == "incoming":
            ok = r["payer_id"] == uid
        elif direction == "outgoing":
            ok = r["requester_id"] == uid
        else:
            ok = r["payer_id"] == uid or r["requester_id"] == uid
        if not ok or (status is not None and r["status"] != status):
            continue
        if skipped < offset:
            skipped += 1
        elif len(out) < limit:
            out.append(S.request_view(r))
        else:
            more = True
            break
    return 200, {"requests": out, "has_more": more}


def activity(user, q):
    limit, offset = page_params(q)
    uid = user["id"]
    out, skipped, more = [], 0, False
    for p in reversed(S.payments):
        if not (p["visibility"] == "public" or p["from_user_id"] == uid or p["to_user_id"] == uid):
            continue
        if skipped < offset:
            skipped += 1
        elif len(out) < limit:
            out.append(S.payment_view(p))
        else:
            more = True
            break
    return 200, {"payments": out, "has_more": more}


def create_split(user, body):
    if "amount" not in body:
        raise invalid("amount is required")
    amount = check_amount(body["amount"])
    note = check_note(body)
    if "participant_handles" not in body:
        raise invalid("participant_handles is required")
    hs = body["participant_handles"]
    if not isinstance(hs, list) or any(not isinstance(h, str) for h in hs):
        raise malformed("participant_handles must be an array of strings")
    if not hs or len(set(hs)) != len(hs):
        raise invalid("participant_handles empty or duplicated")
    people = [S.lookup_handle(h) for h in hs]
    n = len(people)
    base, rem = divmod(amount, n)
    created = now_str()
    shares, reqs = [], []
    for i, p in enumerate(people):
        share = base + (1 if i < rem else 0)
        shares.append({"handle": p["handle"], "amount": share})
        if p["id"] != user["id"]:
            reqs.append(new_request_record(user, p, share, note, created))
    sid = S.new_id("sp", {s["id"] for s in S.splits})
    S.splits.append({"id": sid, "requester_id": user["id"], "amount": amount, "note": note,
                     "shares": shares, "request_ids": [r["id"] for r in reqs], "created_at": created})
    return 201, {"split_id": sid, "amount": amount, "currency": S.currency, "note": note,
                 "shares": shares, "requests": [S.request_view(r) for r in reqs],
                 "created_at": created}


def create_settlement(user, body):
    ts = body.get("transfers")
    if not isinstance(ts, list) or not 1 <= len(ts) <= 32 or any(not isinstance(t, dict) for t in ts):
        raise invalid("transfers must be an array of 1 to 32 objects")
    parsed = []
    for t in ts:
        fh = need_handle(t, "from_handle")
        th = need_handle(t, "to_handle")
        if "amount" not in t:
            raise invalid("amount is required")
        amount = check_amount(t["amount"])
        note = check_note(t)
        vis = check_visibility(t)
        f = S.lookup_handle(fh)
        to = S.lookup_handle(th)
        if f["id"] == to["id"]:
            raise ApiError(422, "self_payment", "cannot transfer to the same wallet")
        parsed.append((f, to, amount, note, vis))
    delta = {}
    for f, to, amount, _, _ in parsed:
        delta[f["id"]] = delta.get(f["id"], 0) - amount
        delta[to["id"]] = delta.get(to["id"], 0) + amount
    for uid, d in delta.items():
        if S.users[uid]["balance"] + d < 0:
            raise ApiError(409, "insufficient_funds", "settlement is not affordable")
    sid = S.new_id("st", {s["id"] for s in S.settlements})
    committed = now_str()
    members = [S.move(f, to, amount, note, vis, settlement_id=sid, created_at=committed)
               for f, to, amount, note, vis in parsed]
    S.settlements.append({"id": sid, "committed_at": committed, "payment_ids": [m["id"] for m in members]})
    return 201, {"settlement_id": sid, "committed_at": committed,
                 "payments": [S.payment_view(m) for m in members]}


# ----------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "pocketful"

    def log_message(self, *a):
        pass

    def read_body(self):
        te = (self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in te:
            data = b""
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline().strip():
                        pass
                    break
                data += self.rfile.read(size)
                self.rfile.readline()
                if len(data) > MAX_BODY:
                    raise malformed("body too large")
            return data
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise malformed("bad Content-Length")
        if n < 0 or n > MAX_BODY:
            raise malformed("bad Content-Length")
        return self.rfile.read(n) if n else b""

    def send_json(self, status, obj=None):
        if status == 204:
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_any(self, method):
        close = False
        try:
            try:
                raw = self.read_body()
            except (ValueError, OSError) as e:
                close = True
                raise e if isinstance(e, ApiError) else malformed("bad body framing")
            parts = urlsplit(self.path)
            path = parts.path
            q = {}
            for k, v in parse_qsl(parts.query, keep_blank_values=True):
                q.setdefault(k, v)
            status, obj = self.route(method, path, q, raw)
        except ApiError as e:
            status, obj = e.status, {"error": {"code": e.code, "message": e.message}}
        except Exception as e:  # never leak a 5xx for a bug in one request path
            status, obj = 500, {"error": {"code": "internal_error", "message": "internal error"}}
            print("internal error:", repr(e), flush=True)
        if close:
            self.close_connection = True
        try:
            self.send_json(status, obj)
        except OSError:
            self.close_connection = True

    do_GET = lambda self: self.handle_any("GET")
    do_POST = lambda self: self.handle_any("POST")
    do_PUT = lambda self: self.handle_any("PUT")
    do_PATCH = lambda self: self.handle_any("PATCH")
    do_DELETE = lambda self: self.handle_any("DELETE")

    def route(self, method, path, q, raw):
        H = self.headers
        segs = [unquote(s) for s in path.split("/")[1:]]
        if path == "/health":
            self.need(method, "GET")
            return 200, {"status": "ok"}
        if path == "/_test/reset":
            self.need(method, "POST")
            do_reset(parse_json(raw))
            return 204, None
        if path == "/_test/export":
            self.need(method, "GET")
            with LOCK:
                state = S.export()
            return 200, {"track": "pocketful", "format_version": 1, "state": state}
        if path == "/_test/import":
            self.need(method, "POST")
            doc = parse_json(raw)
            if not isinstance(doc, dict) or doc.get("track") != "pocketful" \
                    or not is_int(doc.get("format_version")) or doc.get("format_version") != 1 \
                    or "state" not in doc:
                raise invalid("not a pocketful format 1 export")
            state = validate_state(doc["state"])
            with LOCK:
                S.load(state)
            return 204, None
        if path == "/auth/signup":
            self.need(method, "POST")
            return signup(raw)
        if path == "/auth/login":
            self.need(method, "POST")
            return login(raw)
        known = {"/me": "GET", "/payments": "POST", "/requests": None, "/splits": "POST",
                 "/activity": "GET", "/settlements": "POST"}
        pay_like = len(segs) == 3 and segs[0] == "requests" and segs[2] in ("pay", "decline", "cancel")
        if path not in known and not pay_like:
            raise ApiError(404, "not_found", "no such route")
        if path in known and known[path]:
            self.need(method, known[path])
        elif path == "/requests":
            if method not in ("GET", "POST"):
                raise ApiError(405, "method_not_allowed", "method not allowed")
        elif method != "POST":
            raise ApiError(405, "method_not_allowed", "method not allowed")
        with LOCK:
            user = authenticate(H)
            if path == "/me":
                return me(user)
            if path == "/activity":
                return activity(user, q)
            if path == "/requests" and method == "GET":
                return list_requests(user, q)
            if path == "/payments":
                return idempotent(user, method, path, H, raw, lambda b: create_payment(user, b))
            if path == "/requests":
                return idempotent(user, method, path, H, raw, lambda b: create_request(user, b))
            if path == "/splits":
                return idempotent(user, method, path, H, raw, lambda b: create_split(user, b))
            if path == "/settlements":
                if user["id"] not in S.operators:
                    raise ApiError(403, "forbidden", "settlement operator required")
                return idempotent(user, method, path, H, raw, lambda b: create_settlement(user, b))
            rid, action = segs[1], segs[2]
            if action == "pay":
                return idempotent(user, method, path, H, raw,
                                  lambda b: pay_request(user, rid, b), allow_empty=True)
            if action == "decline":
                return close_request(user, rid, "declined", "payer_id")
            return close_request(user, rid, "cancelled", "requester_id")

    @staticmethod
    def need(method, allowed):
        if method != allowed:
            raise ApiError(405, "method_not_allowed", "method not allowed")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 512
    allow_reuse_address = True


def main():
    port = int(os.environ.get("PORT") or 8080)
    Server(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
