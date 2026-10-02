"""Pocketful stage 1: payments and settlements. HTTP JSON API, standard library only."""
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import threading
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote

MAX_AMOUNT = 1_000_000_000
MAX_NOTE = 200
HANDLE_RE = re.compile(r"^[a-z0-9_]{1,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")
DIGITS_RE = re.compile(r"[0-9]+", re.ASCII)
STATUSES = ("pending", "paid", "declined", "cancelled")
SCRYPT_N, SCRYPT_R, SCRYPT_P = 8192, 8, 1  # signups
SEED_SCRYPT_N = 1024  # fixture users: keeps a large reset inside its 10 s budget
MAX_BODY = 128 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, status, code, message=""):
        super().__init__(message or code)
        self.status, self.code, self.message = status, code, message or code


def bad(code="validation_failed", message="invalid request", status=422):
    return ApiError(status, code, message)


def malformed(message="malformed request"):
    return ApiError(400, "malformed_request", message)


# ---------------------------------------------------------------- helpers

def now():
    return datetime.now(timezone.utc)


def fmt_ts(dt):
    return dt.replace(microsecond=0).isoformat()


def parse_ts(value):
    if value is None:
        return now()
    if not isinstance(value, str):
        raise bad(message="bad timestamp")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise bad(message="bad timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def hash_password(password, n=SCRYPT_N):
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt,
                        n=n, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (n, SCRYPT_R, SCRYPT_P, salt.hex(), dk.hex())


def check_password(password, stored):
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=bytes.fromhex(salt),
                             n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, bytes.fromhex(dk))
    except (ValueError, TypeError):
        return False


def canon(v):
    """Hashable canonical form of a parsed JSON value (numbers by value, bools distinct)."""
    if isinstance(v, bool):
        return ("b", v)
    if isinstance(v, (int, Decimal)):
        return ("n", v)  # int and Decimal hash and compare by numeric value
    if v is None:
        return ("z",)
    if isinstance(v, str):
        return ("s", v)
    if isinstance(v, list):
        return ("a", tuple(canon(x) for x in v))
    if isinstance(v, dict):
        return ("o", frozenset((k, canon(x)) for k, x in v.items()))
    raise ValueError("unsupported")


def _parse_float(s):
    return Decimal(s)  # exact: no binary rounding of number literals


def _parse_int(s):
    return int(s) if len(s) <= 4000 else Decimal(s)


def _parse_constant(s):
    raise ValueError("bad constant")


def parse_json(raw):
    try:
        text = raw.decode("utf-8")
        return json.loads(text, parse_float=_parse_float, parse_int=_parse_int, parse_constant=_parse_constant)
    except (ValueError, RecursionError, UnicodeDecodeError, MemoryError):
        raise malformed("body is not valid JSON")


def parse_object(raw, empty_ok=False):
    if not raw.strip():
        if empty_ok:
            return {}
        raise malformed("body required")
    v = parse_json(raw)
    if not isinstance(v, dict):
        raise malformed("body must be a JSON object")
    return v


def as_amount(v, allow_zero=False):
    if isinstance(v, bool) or not isinstance(v, (int, Decimal)):
        raise bad(message="amount must be an integer")
    if v < (0 if allow_zero else 1) or v > MAX_AMOUNT:
        raise bad(message="amount out of range")
    if isinstance(v, Decimal):
        if v != v.to_integral_value():
            raise bad(message="amount must be integral")
        v = int(v)
    return v


def get_amount(body, key="amount"):
    if key not in body:
        raise bad(message="amount required")
    return as_amount(body[key])


def get_note(body):
    if "note" not in body:
        return ""
    n = body["note"]
    if not isinstance(n, str):
        raise bad(message="note must be a string")
    if len(n) > MAX_NOTE:
        raise bad(message="note too long")
    return n


def get_visibility(body):
    if "visibility" not in body:
        return "public"
    v = body["visibility"]
    if v not in ("public", "private") or not isinstance(v, str):
        raise bad(message="visibility must be public or private")
    return v


def get_handle(body, key, typed_400=True):
    if key not in body:
        raise bad(message=key + " required")
    h = body[key]
    if not isinstance(h, str):
        if typed_400:
            raise malformed(key + " must be a string")
        raise bad(message=key + " must be a string")
    return h


def derive_handle(email):
    local = email.split("@", 1)[0].lower()
    return re.sub(r"[^a-z0-9_]", "_", local)[:20]


def paging(query):
    limit, offset = 50, 0
    if "limit" in query:
        s = query["limit"]
        if not DIGITS_RE.fullmatch(s) or len(s) > 12 or not 1 <= int(s) <= 200:
            raise bad(message="limit must be 1..200")
        limit = int(s)
    if "offset" in query:
        s = query["offset"]
        if not DIGITS_RE.fullmatch(s) or len(s) > 4000:
            raise bad(message="offset must be a non-negative integer")
        offset = int(s)
    return limit, offset


# ---------------------------------------------------------------- state

class State:
    def __init__(self, currency="EUR", minor_units=2):
        self.currency = currency
        self.minor_units = minor_units
        self.users = {}
        self.by_handle = {}
        self.by_email = {}
        self.tokens = {}
        self.operators = set()
        self.payments = []
        self.pay_by_id = {}
        self.requests = []
        self.req_by_id = {}
        self.splits = []
        self.settlements = []
        self.idem = {}
        self.seq = 0

    # -- construction
    def add_user(self, u):
        if u["id"] in self.users or u["handle"] in self.by_handle or u["email"].lower() in self.by_email:
            raise bad(message="duplicate user id, handle or email")
        self.users[u["id"]] = u
        self.by_handle[u["handle"]] = u
        self.by_email[u["email"].lower()] = u

    def add_payment(self, p):
        if p["id"] in self.pay_by_id:
            raise bad(message="duplicate payment id")
        self.payments.append(p)
        self.pay_by_id[p["id"]] = p

    def add_request(self, r):
        if r["id"] in self.req_by_id:
            raise bad(message="duplicate request id")
        self.requests.append(r)
        self.req_by_id[r["id"]] = r

    def new_id(self, prefix, taken):
        while True:
            self.seq += 1
            i = "%s_%d" % (prefix, self.seq)
            if i not in taken:
                return i

    # -- views
    def pay_out(self, p):
        f, t = self.users[p["from"]], self.users[p["to"]]
        return {
            "payment_id": p["id"], "from_user_id": f["id"], "from_handle": f["handle"],
            "to_user_id": t["id"], "to_handle": t["handle"], "amount": p["amount"],
            "currency": self.currency, "note": p["note"], "visibility": p["visibility"],
            "request_id": p["request_id"], "settlement_id": p["settlement_id"],
            "created_at": fmt_ts(p["ts"]),
        }

    def req_out(self, r):
        a, b = self.users[r["requester"]], self.users[r["payer"]]
        return {
            "request_id": r["id"], "requester_id": a["id"], "requester_handle": a["handle"],
            "payer_id": b["id"], "payer_handle": b["handle"], "amount": r["amount"],
            "currency": self.currency, "note": r["note"], "status": r["status"],
            "payment_id": r["payment_id"], "created_at": fmt_ts(r["ts"]),
        }

    def make_payment(self, sender, receiver, amount, note, visibility, ts,
                     request_id=None, settlement_id=None):
        sender["balance"] -= amount
        receiver["balance"] += amount
        p = {"id": self.new_id("p", self.pay_by_id), "from": sender["id"], "to": receiver["id"],
             "amount": amount, "note": note, "visibility": visibility,
             "request_id": request_id, "settlement_id": settlement_id, "ts": ts}
        self.add_payment(p)
        return p

    # -- export / import
    def to_json(self):
        def ts(r):
            d = dict(r)
            d["ts"] = r["ts"].isoformat()
            return d
        return {
            "currency": self.currency, "minor_units": self.minor_units,
            "users": list(self.users.values()),
            "tokens": dict(self.tokens),
            "operators": sorted(self.operators),
            "payments": [ts(p) for p in self.payments],
            "requests": [ts(r) for r in self.requests],
            "splits": [ts(s) for s in self.splits],
            "settlements": [ts(s) for s in self.settlements],
            "idempotency": [{"user": k[0], "method": k[1], "path": k[2], "key": k[3],
                             "body": v["raw"], "response": v["response"]}
                            for k, v in self.idem.items()],
            "seq": self.seq,
        }


def req_str(d, key, maxlen=None):
    v = d.get(key)
    if not isinstance(v, str):
        raise bad(message="%s must be a string" % key)
    if maxlen is not None and len(v) > maxlen:
        raise bad(message="%s too long" % key)
    return v


def req_int(d, key, minimum=0):
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, Decimal)):
        raise bad(message="%s must be an integer" % key)
    if isinstance(v, Decimal):
        if v.adjusted() > 40 or v != v.to_integral_value():
            raise bad(message="%s must be an integer" % key)
        v = int(v)
    if v < minimum:
        raise bad(message="%s out of range" % key)
    return v


def check_currency(d):
    cur = d.get("currency")
    mu = d.get("minor_units")
    if not isinstance(cur, str) or not cur:
        raise bad(message="currency required")
    if isinstance(mu, bool) or not isinstance(mu, int) or mu not in (0, 2, 3):
        raise bad(message="minor_units must be 0, 2 or 3")
    return cur, mu


def build_from_fixture(fx, pool):
    if not isinstance(fx, dict):
        raise bad(message="fixture must be an object")
    cur, mu = check_currency(fx)
    st = State(cur, mu)
    users = fx.get("users", [])
    if not isinstance(users, list):
        raise bad(message="users must be an array")
    pending = []
    for u in users:
        if not isinstance(u, dict):
            raise bad(message="user must be an object")
        uid = req_str(u, "id", 64)
        email = req_str(u, "email")
        pw = req_str(u, "password")
        dn = req_str(u, "display_name")
        handle = u["handle"] if "handle" in u else derive_handle(email)
        if not isinstance(handle, str) or not HANDLE_RE.match(handle):
            raise bad(message="bad handle")
        bal = req_int(u, "balance", 0)
        rec = {"id": uid, "email": email, "display_name": dn, "handle": handle,
               "balance": bal, "pw": None}
        st.add_user(rec)
        pending.append((rec, pw))
    hashes = list(pool.map(lambda x: hash_password(x[1], SEED_SCRYPT_N), pending))
    for (rec, _), h in zip(pending, hashes):
        rec["pw"] = h
    ops = fx.get("settlement_operator_ids", [])
    if not isinstance(ops, list):
        raise bad(message="settlement_operator_ids must be an array")
    for o in ops:
        if not isinstance(o, str) or o not in st.users:
            raise bad(message="unknown operator")
        st.operators.add(o)
    pays = fx.get("payments", [])
    reqs = fx.get("requests", [])
    if not isinstance(pays, list) or not isinstance(reqs, list):
        raise bad(message="payments and requests must be arrays")
    for p in pays:
        if not isinstance(p, dict):
            raise bad(message="payment must be an object")
        f, t = p.get("from_user_id"), p.get("to_user_id")
        if f not in st.users or t not in st.users:
            raise bad(message="payment references unknown user")
        vis = p.get("visibility", "public")
        if vis not in ("public", "private"):
            raise bad(message="bad visibility")
        note = p.get("note", "")
        if not isinstance(note, str):
            raise bad(message="bad note")
        st.add_payment({"id": req_str(p, "id", 64), "from": f, "to": t,
                        "amount": req_int(p, "amount", 0), "note": note, "visibility": vis,
                        "request_id": None, "settlement_id": None, "ts": parse_ts(p.get("created_at"))})
    for r in reqs:
        if not isinstance(r, dict):
            raise bad(message="request must be an object")
        a, b = r.get("requester_id"), r.get("payer_id")
        if a not in st.users or b not in st.users:
            raise bad(message="request references unknown user")
        status = r.get("status", "pending")
        if status not in STATUSES:
            raise bad(message="bad status")
        note = r.get("note", "")
        if not isinstance(note, str):
            raise bad(message="bad note")
        pid = r.get("payment_id")
        if pid is not None and not isinstance(pid, str):
            raise bad(message="bad payment_id")
        st.add_request({"id": req_str(r, "id", 64), "requester": a, "payer": b,
                        "amount": req_int(r, "amount", 0), "note": note, "status": status,
                        "payment_id": pid if status == "paid" else None,
                        "ts": parse_ts(r.get("created_at"))})
    return st


def build_from_export(obj, pool=None):
    if not isinstance(obj, dict):
        raise bad(message="export must be an object")
    if obj.get("track") != "pocketful" or "format_version" not in obj or "state" not in obj:
        raise bad(message="not a pocketful export")
    ver = obj["format_version"]
    if isinstance(ver, bool) or ver != 1:
        raise bad(message="unsupported format_version")
    d = obj["state"]
    if not isinstance(d, dict):
        raise bad(message="state must be an object")
    try:
        return _load_state(d)
    except ApiError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise bad(message="invalid state")


def _load_state(d):
    cur, mu = check_currency(d)
    st = State(cur, mu)
    for u in d["users"]:
        rec = {"id": req_str(u, "id", 64), "email": req_str(u, "email"),
               "display_name": req_str(u, "display_name"), "handle": req_str(u, "handle"),
               "balance": req_int(u, "balance", 0), "pw": req_str(u, "pw")}
        if not HANDLE_RE.match(rec["handle"]):
            raise bad(message="bad handle")
        st.add_user(rec)
    for tok, uid in d["tokens"].items():
        if uid not in st.users or not isinstance(tok, str):
            raise bad(message="bad token")
        st.tokens[tok] = uid
    for o in d["operators"]:
        if o not in st.users:
            raise bad(message="bad operator")
        st.operators.add(o)
    for p in d["payments"]:
        if p["from"] not in st.users or p["to"] not in st.users:
            raise bad(message="bad payment")
        if p["visibility"] not in ("public", "private") or not isinstance(p["note"], str):
            raise bad(message="bad payment")
        st.add_payment({"id": req_str(p, "id", 64), "from": p["from"], "to": p["to"],
                        "amount": req_int(p, "amount", 0), "note": p["note"],
                        "visibility": p["visibility"], "request_id": p["request_id"],
                        "settlement_id": p["settlement_id"], "ts": parse_ts(p["ts"])})
    for r in d["requests"]:
        if r["requester"] not in st.users or r["payer"] not in st.users or r["status"] not in STATUSES:
            raise bad(message="bad request")
        if not isinstance(r["note"], str):
            raise bad(message="bad request")
        st.add_request({"id": req_str(r, "id", 64), "requester": r["requester"], "payer": r["payer"],
                        "amount": req_int(r, "amount", 0), "note": r["note"], "status": r["status"],
                        "payment_id": r["payment_id"], "ts": parse_ts(r["ts"])})
    for s in d["splits"]:
        s = dict(s)
        s["ts"] = parse_ts(s["ts"])
        st.splits.append(s)
    for s in d["settlements"]:
        s = dict(s)
        s["ts"] = parse_ts(s["ts"])
        st.settlements.append(s)
    for e in d["idempotency"]:
        if e["user"] not in st.users or not isinstance(e["key"], str):
            raise bad(message="bad idempotency record")
        json.dumps(e["response"])
        st.idem[(e["user"], e["method"], e["path"], e["key"])] = {
            "canon": canon(parse_json(e["body"].encode("utf-8"))), "raw": e["body"],
            "response": e["response"]}
    st.seq = req_int(d, "seq", 0)
    return st


# ---------------------------------------------------------------- service

LOCK = threading.RLock()
POOL = ThreadPoolExecutor(max_workers=4)
S = State()


def authenticate(headers):
    h = headers.get("Authorization", "")
    parts = h.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise ApiError(401, "unauthenticated", "missing or malformed bearer token")
    with LOCK:
        uid = S.tokens.get(parts[1].strip())
        if uid is None:
            raise ApiError(401, "unauthenticated", "unknown token")
        return uid


def idem_key(headers):
    k = headers.get("Idempotency-Key")
    if k is None or k == "":
        raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header required")
    try:
        k = k.encode("latin-1").decode("utf-8")  # header bytes arrive latin-1 decoded
    except (UnicodeError, ValueError):
        pass
    if len(k) > 255:
        raise bad(message="Idempotency-Key too long")
    return k


def idempotent(uid, method, path, key, body, raw, fn):
    """Run fn(st, user, body) once per (user, method, path, key). Caller holds LOCK."""
    ik = (uid, method, path, key)
    rec = S.idem.get(ik)
    try:
        c = canon(body)
    except RecursionError:
        raise malformed("body nested too deeply")
    if rec is not None:
        if rec["canon"] == c:
            return 200, rec["response"]
        raise ApiError(409, "idempotency_key_reuse", "key already used with a different body")
    resp = fn(S, S.users[uid], body)
    S.idem[ik] = {"canon": c, "raw": raw, "response": resp}
    return 201, resp


def lookup_handle(st, h):
    u = st.by_handle.get(h)
    if u is None:
        raise ApiError(404, "not_found", "no such handle")
    return u


# -- auth

def h_signup(headers, query, raw):
    body = parse_object(raw)
    for k in ("email", "password", "display_name"):
        if k in body and not isinstance(body[k], str):
            raise malformed(k + " must be a string")
    for k in ("email", "password", "display_name"):
        if k not in body:
            raise bad(message=k + " required")
    email, pw, dn = body["email"], body["password"], body["display_name"]
    if not EMAIL_RE.match(email):
        raise bad(message="invalid email")
    if len(pw) < 8:
        raise bad(message="password too short")
    handle = derive_handle(email)

    def taken():
        if email.lower() in S.by_email:
            raise ApiError(409, "email_taken", "email already registered")
        if handle in S.by_handle:
            raise ApiError(409, "handle_taken", "derived handle already taken")

    with LOCK:
        taken()
    pwh = hash_password(pw)
    with LOCK:
        taken()
        uid = S.new_id("u", S.users)
        S.add_user({"id": uid, "email": email, "display_name": dn, "handle": handle,
                    "balance": 0, "pw": pwh})
        tok = secrets.token_urlsafe(32)
        S.tokens[tok] = uid
    return 201, {"user_id": uid, "display_name": dn, "token": tok}


def h_login(headers, query, raw):
    body = parse_object(raw)
    for k in ("email", "password"):
        if k in body and not isinstance(body[k], str):
            raise malformed(k + " must be a string")
    for k in ("email", "password"):
        if k not in body:
            raise bad(message=k + " required")
    with LOCK:
        u = S.by_email.get(body["email"].lower())
        stored = u["pw"] if u else None
    if stored is None or not check_password(body["password"], stored):
        raise ApiError(401, "unauthenticated", "wrong email or password")
    with LOCK:
        if S.users.get(u["id"]) is not u:
            raise ApiError(401, "unauthenticated", "wrong email or password")
        tok = secrets.token_urlsafe(32)
        S.tokens[tok] = u["id"]
        return 200, {"user_id": u["id"], "display_name": u["display_name"], "token": tok}


def h_me(headers, query, raw):
    with LOCK:
        u = S.users[authenticate(headers)]
        return 200, {"user_id": u["id"], "display_name": u["display_name"], "handle": u["handle"],
                     "balance": u["balance"], "currency": S.currency, "minor_units": S.minor_units}


# -- payments

def write_prelude(headers, raw, empty_ok=False, operator=False):
    uid = authenticate(headers)
    if operator:
        with LOCK:
            if uid not in S.operators:
                raise ApiError(403, "forbidden", "operator only")
    key = idem_key(headers)
    body = parse_object(raw, empty_ok)
    return uid, key, body, raw.decode("utf-8") if raw.strip() else "{}"


def h_payments(headers, query, raw):
    uid, key, body, raw = write_prelude(headers, raw)

    def run(st, user, body):
        to_h = get_handle(body, "to_handle")
        amount = get_amount(body)
        note = get_note(body)
        vis = get_visibility(body)
        to = lookup_handle(st, to_h)
        if to["id"] == user["id"]:
            raise bad("self_payment", "cannot pay yourself")
        if user["balance"] < amount:
            raise ApiError(409, "insufficient_funds", "insufficient funds")
        p = st.make_payment(user, to, amount, note, vis, now())
        return st.pay_out(p)

    with LOCK:
        return idempotent(uid, "POST", "/payments", key, body, raw, run)


def h_request_create(headers, query, raw):
    uid, key, body, raw = write_prelude(headers, raw)

    def run(st, user, body):
        ph = get_handle(body, "payer_handle")
        amount = get_amount(body)
        note = get_note(body)
        payer = lookup_handle(st, ph)
        if payer["id"] == user["id"]:
            raise bad("self_request", "cannot request from yourself")
        r = {"id": st.new_id("rq", st.req_by_id), "requester": user["id"], "payer": payer["id"],
             "amount": amount, "note": note, "status": "pending", "payment_id": None, "ts": now()}
        st.add_request(r)
        return st.req_out(r)

    with LOCK:
        return idempotent(uid, "POST", "/requests", key, body, raw, run)


def h_pay(headers, query, raw, rid):
    uid, key, body, raw = write_prelude(headers, raw, empty_ok=True)

    def run(st, user, body):
        vis = get_visibility(body)
        r = st.req_by_id.get(rid)
        if r is None:
            raise ApiError(404, "not_found", "no such request")
        if r["payer"] != user["id"]:
            raise ApiError(403, "forbidden", "only the payer may pay")
        if r["status"] != "pending":
            raise ApiError(409, "request_not_pending", "request is not pending")
        if user["balance"] < r["amount"]:
            raise ApiError(409, "insufficient_funds", "insufficient funds")
        p = st.make_payment(user, st.users[r["requester"]], r["amount"], r["note"], vis, now(),
                            request_id=r["id"])
        r["status"] = "paid"
        r["payment_id"] = p["id"]
        return st.pay_out(p)

    with LOCK:
        return idempotent(uid, "POST", "/requests/" + rid + "/pay", key, body, raw, run)


def h_transition(headers, query, raw, rid, action):
    uid = authenticate(headers)
    with LOCK:
        r = S.req_by_id.get(rid)
        if r is None:
            raise ApiError(404, "not_found", "no such request")
        if action == "decline":
            if r["payer"] != uid:
                raise ApiError(403, "forbidden", "only the payer may decline")
            target = "declined"
        else:
            if r["requester"] != uid:
                raise ApiError(403, "forbidden", "only the requester may cancel")
            target = "cancelled"
        if r["status"] == "pending":
            r["status"] = target
        elif r["status"] != target:
            raise ApiError(409, "request_not_pending", "request is not pending")
        return 200, S.req_out(r)


def newest_first(items):
    return sorted(enumerate(items), key=lambda t: (t[1]["ts"], t[0]), reverse=True)


def h_requests_list(headers, query, raw):
    uid = authenticate(headers)
    limit, offset = paging(query)
    direction = query.get("direction")
    status = query.get("status")
    if direction is not None and direction not in ("incoming", "outgoing"):
        raise bad(message="bad direction")
    if status is not None and status not in STATUSES:
        raise bad(message="bad status")
    with LOCK:
        rows = []
        for _, r in newest_first(S.requests):
            if direction == "incoming":
                ok = r["payer"] == uid
            elif direction == "outgoing":
                ok = r["requester"] == uid
            else:
                ok = uid in (r["payer"], r["requester"])
            if ok and (status is None or r["status"] == status):
                rows.append(r)
        page = rows[offset:offset + limit]
        return 200, {"requests": [S.req_out(r) for r in page], "has_more": offset + limit < len(rows)}


def h_activity(headers, query, raw):
    uid = authenticate(headers)
    limit, offset = paging(query)
    with LOCK:
        rows = [p for _, p in newest_first(S.payments)
                if p["visibility"] == "public" or uid in (p["from"], p["to"])]
        page = rows[offset:offset + limit]
        return 200, {"payments": [S.pay_out(p) for p in page], "has_more": offset + limit < len(rows)}


def shares_for(amount, n):
    base, extra = divmod(amount, n)
    return [base + 1 if i < extra else base for i in range(n)]


def h_splits(headers, query, raw):
    uid, key, body, raw = write_prelude(headers, raw)

    def run(st, user, body):
        amount = get_amount(body)
        if "participant_handles" not in body:
            raise bad(message="participant_handles required")
        hs = body["participant_handles"]
        if not isinstance(hs, list) or any(not isinstance(h, str) for h in hs):
            raise malformed("participant_handles must be an array of strings")
        note = get_note(body)
        if not hs or len(set(hs)) != len(hs):
            raise bad(message="participant_handles must be non-empty and unique")
        users = [lookup_handle(st, h) for h in hs]
        shares = shares_for(amount, len(hs))
        ts = now()
        reqs = []
        for u, share in zip(users, shares):
            if u["id"] == user["id"]:
                continue
            r = {"id": st.new_id("rq", st.req_by_id), "requester": user["id"], "payer": u["id"],
                 "amount": share, "note": note, "status": "pending", "payment_id": None, "ts": ts}
            st.add_request(r)
            reqs.append(r)
        sid = st.new_id("sp", {s["id"] for s in st.splits})
        st.splits.append({"id": sid, "ts": ts})
        return {"split_id": sid, "amount": amount, "currency": st.currency, "note": note,
                "shares": [{"handle": h, "amount": a} for h, a in zip(hs, shares)],
                "requests": [st.req_out(r) for r in reqs], "created_at": fmt_ts(ts)}

    with LOCK:
        return idempotent(uid, "POST", "/splits", key, body, raw, run)


def h_settlements(headers, query, raw):
    uid, key, body, raw = write_prelude(headers, raw, operator=True)

    def run(st, user, body):
        transfers = body.get("transfers")
        if not isinstance(transfers, list) or not 1 <= len(transfers) <= 32:
            raise bad(message="transfers must be an array of 1..32 objects")
        if any(not isinstance(t, dict) for t in transfers):
            raise bad(message="transfers must contain objects")
        parsed = []
        for t in transfers:
            fh = get_handle(t, "from_handle", typed_400=False)
            th = get_handle(t, "to_handle", typed_400=False)
            amount = get_amount(t)
            note = get_note(t)
            vis = get_visibility(t)
            f = lookup_handle(st, fh)
            to = lookup_handle(st, th)
            if f["id"] == to["id"]:
                raise bad("self_payment", "self transfer")
            parsed.append((f, to, amount, note, vis))
        delta = {}
        for f, to, amount, _, _ in parsed:
            delta[f["id"]] = delta.get(f["id"], 0) - amount
            delta[to["id"]] = delta.get(to["id"], 0) + amount
        for u, d in delta.items():
            if st.users[u]["balance"] + d < 0:
                raise ApiError(409, "insufficient_funds", "settlement is not affordable")
        ts = now()
        sid = st.new_id("st", {s["id"] for s in st.settlements})
        pays = [st.make_payment(f, to, amount, note, vis, ts, settlement_id=sid)
                for f, to, amount, note, vis in parsed]
        st.settlements.append({"id": sid, "ts": ts})
        return {"settlement_id": sid, "committed_at": fmt_ts(ts),
                "payments": [st.pay_out(p) for p in pays]}

    with LOCK:
        return idempotent(uid, "POST", "/settlements", key, body, raw, run)


# -- test control

def h_reset(headers, query, raw):
    fx = parse_object(raw)
    st = build_from_fixture(fx, POOL)
    global S
    with LOCK:
        S = st
    return 204, None


def h_export(headers, query, raw):
    with LOCK:
        data = {"track": "pocketful", "format_version": 1, "state": S.to_json()}
        text = json.dumps(data)
    return 200, text


def h_import(headers, query, raw):
    obj = parse_object(raw)
    st = build_from_export(obj)
    global S
    with LOCK:
        S = st
    return 204, None


def h_health(headers, query, raw):
    return 200, {"status": "ok"}


ROUTES = {
    "/health": {"GET": h_health},
    "/_test/reset": {"POST": h_reset},
    "/_test/export": {"GET": h_export},
    "/_test/import": {"POST": h_import},
    "/auth/signup": {"POST": h_signup},
    "/auth/login": {"POST": h_login},
    "/me": {"GET": h_me},
    "/payments": {"POST": h_payments},
    "/requests": {"GET": h_requests_list, "POST": h_request_create},
    "/splits": {"POST": h_splits},
    "/activity": {"GET": h_activity},
    "/settlements": {"POST": h_settlements},
}
REQ_ACTION = re.compile(r"^/requests/([^/]+)/(pay|decline|cancel)$")


def dispatch(method, path, query, headers, raw):
    routes = ROUTES.get(path)
    if routes is not None:
        fn = routes.get(method)
        if fn is None:
            raise ApiError(405, "method_not_allowed", "method not allowed")
        return fn(headers, query, raw)
    m = REQ_ACTION.match(path)
    if m:
        if method != "POST":
            raise ApiError(405, "method_not_allowed", "method not allowed")
        rid, action = unquote(m.group(1)), m.group(2)
        if action == "pay":
            return h_pay(headers, query, raw, rid)
        return h_transition(headers, query, raw, rid, action)
    raise ApiError(404, "not_found", "no such route")


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 60
    server_version = "pocketful"
    sys_version = ""

    def log_message(self, *a):
        pass

    def send_error(self, code, message=None, explain=None):
        status = code if code in (400, 404, 405, 408, 413, 414, 431) else 400
        self.close_connection = True
        self._send(status, json.dumps({"error": {"code": "malformed_request" if status == 400
                                                 else "not_found" if status == 404 else "malformed_request",
                                                 "message": message or "bad request"}}).encode())

    def _send(self, status, payload, extra=None):
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if payload and self.command != "HEAD":
                self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.close_connection = True

    def _read_body(self):
        te = self.headers.get("Transfer-Encoding", "")
        if "chunked" in te.lower():
            chunks, total = [], 0
            while True:
                line = self.rfile.readline(1024).strip().split(b";")[0]
                size = int(line or b"0", 16)
                if size == 0:
                    while self.rfile.readline(1024).strip():
                        pass
                    break
                total += size
                if total > MAX_BODY:
                    raise ApiError(413, "malformed_request", "body too large")
                chunks.append(self.rfile.read(size))
                self.rfile.readline(8)
            return b"".join(chunks)
        cl = self.headers.get("Content-Length")
        if cl is None:
            return b""
        n = int(cl)
        if n < 0:
            raise ValueError
        if n > MAX_BODY:
            raise ApiError(413, "malformed_request", "body too large")
        return self.rfile.read(n)

    def handle_any(self):
        try:
            try:
                raw = self._read_body()
            except ApiError:
                raise
            except (ValueError, OSError):
                self.close_connection = True
                raise malformed("bad request framing")
            path, _, qs = self.path.partition("?")
            query = {}
            for k, v in parse_qsl(qs, keep_blank_values=True):
                query.setdefault(k, v)
            status, payload = dispatch(self.command, path, query, self.headers, raw)
            if payload is None:
                self._send(status, b"")
            elif isinstance(payload, str):
                self._send(status, payload.encode())
            else:
                self._send(status, json.dumps(payload).encode())
        except ApiError as e:
            extra = {"Allow": "GET, POST"} if e.status == 405 else None
            self._send(e.status, json.dumps(
                {"error": {"code": e.code, "message": e.message}}).encode(), extra)
        except Exception as e:  # never leak a 5xx for hostile input we can classify
            self._send(500, json.dumps(
                {"error": {"code": "internal_error", "message": type(e).__name__}}).encode())

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = handle_any


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 512
    allow_reuse_address = True


def main():
    port = int(os.environ.get("PORT") or 8080)
    Server(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
