"""Pocketful stage 1: payments and settlements. Single process, stdlib only.

All state lives in memory behind one lock; every mutating operation validates fully
before it changes anything, so each operation is atomic.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

HANDLE_RE = re.compile(r"^[a-z0-9_]{1,20}\Z")
DIGITS_RE = re.compile(r"[0-9]+\Z")
MAX_AMOUNT = 1_000_000_000
MAX_BALANCE = 2 ** 53
MAX_BODY = 16 * 1024 * 1024
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
STATUSES = ("pending", "paid", "declined", "cancelled")
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 13, 8, 1

LOCK = threading.RLock()


class ApiError(Exception):
    def __init__(self, status, code, message=""):
        super().__init__(message or code)
        self.status, self.code, self.message = status, code, message or code


def bad(msg="validation failed"):
    return ApiError(422, "validation_failed", msg)


def malformed(msg="malformed request"):
    return ApiError(400, "malformed_request", msg)


# ---------------------------------------------------------------- helpers

def _reject_constant(name):
    raise ValueError("bad constant")


def _parse_int(s):
    return int(s) if len(s) <= 40 else Decimal(s)


def parse_json(raw):
    try:
        text = raw.decode("utf-8")
        return json.loads(text, parse_float=Decimal, parse_int=_parse_int,
                          parse_constant=_reject_constant)
    except (ValueError, RecursionError, UnicodeError):
        raise malformed("unparseable body")


def is_integral(d):
    if d.as_tuple().exponent >= 0:
        return True
    return d == d.to_integral_value()


def _conv(o):
    if isinstance(o, Decimal):
        if is_integral(o) and o.adjusted() <= 100:
            return int(o)
        try:
            return "D" + str(o.normalize())
        except ArithmeticError:
            return "D" + str(o)
    raise TypeError


def fingerprint(body):
    try:
        s = json.dumps(body, sort_keys=True, ensure_ascii=True, default=_conv,
                       separators=(",", ":"))
    except RecursionError:
        raise malformed("too deep")
    return hashlib.sha256(s.encode("ascii")).hexdigest()


def to_int(v, lo, hi):
    """Integral JSON number (not bool) within [lo, hi] -> int, else None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        n = v
    elif isinstance(v, Decimal):
        try:
            if not is_integral(v):
                return None
        except Exception:
            return None
        if v < lo or v > hi:
            return None
        n = int(v)
    else:
        return None
    return n if lo <= n <= hi else None


def fmt_ts(us):
    return (EPOCH + timedelta(microseconds=us)).isoformat(timespec="microseconds")


def parse_ts(s):
    if not isinstance(s, str):
        raise bad("created_at must be a string")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        raise bad("invalid created_at")
    if d.tzinfo is None:
        raise bad("created_at needs an offset")
    delta = d - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def hash_password(pw):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode("utf-8", "surrogatepass"), salt=salt, n=SCRYPT_N,
                       r=SCRYPT_R, p=SCRYPT_P)
    return "scrypt$%d$%d$%d$%s$%s" % (SCRYPT_N, SCRYPT_R, SCRYPT_P, salt.hex(), h.hex())


def verify_password(pw, stored):
    try:
        _, n, r, p, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode("utf-8", "surrogatepass"),
                             salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(got.hex(), h)
    except Exception:
        return False


def strip(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------- state

class State:
    def __init__(self):
        self.currency = "EUR"
        self.minor_units = 2
        self.users = {}        # id -> user record
        self.by_email = {}
        self.by_handle = {}
        self.tokens = {}       # token -> user id
        self.payments = []     # payment records, creation order
        self.requests = {}     # id -> request record (insertion ordered)
        self.idem = {}         # (user id, key, path) -> {"fp", "resp"}
        self.operators = set()
        self.counters = {"p": 0, "rq": 0, "sp": 0, "st": 0, "u": 0, "seq": 0}
        self.last_us = 0
        self.pay_ids = set()

    def tick(self):
        self.last_us = max(time.time_ns() // 1000, self.last_us + 1)
        return self.last_us

    def next_seq(self):
        self.counters["seq"] += 1
        return self.counters["seq"]

    def new_id(self, prefix, taken):
        while True:
            self.counters[prefix] += 1
            i = "%s_%d" % (prefix, self.counters[prefix])
            if i not in taken:
                return i

    def add_user(self, rec):
        self.users[rec["id"]] = rec
        self.by_email[rec["email"]] = rec
        self.by_handle[rec["handle"]] = rec

    def export(self):
        return {
            "currency": self.currency,
            "minor_units": self.minor_units,
            "users": list(self.users.values()),
            "tokens": dict(self.tokens),
            "payments": list(self.payments),
            "requests": list(self.requests.values()),
            "idempotency": [[k[0], k[1], k[2], v["fp"], v["resp"]]
                            for k, v in self.idem.items()],
            "operators": sorted(self.operators),
            "counters": dict(self.counters),
            "last_us": self.last_us,
        }


STATE = State()


def build_from_export(st):
    """Validate an exported state object and build a State (raises on any defect)."""
    if not isinstance(st, dict):
        raise ValueError("state")
    s = State()
    s.currency = st["currency"]
    s.minor_units = st["minor_units"]
    if not isinstance(s.currency, str) or not s.currency:
        raise ValueError("currency")
    if s.minor_units not in (0, 2, 3) or isinstance(s.minor_units, bool):
        raise ValueError("minor_units")
    for u in st["users"]:
        rec = {"id": u["id"], "email": u["email"], "display_name": u["display_name"],
               "handle": u["handle"], "balance": u["balance"], "pw": u["pw"]}
        if not all(isinstance(rec[k], str) for k in ("id", "email", "display_name",
                                                     "handle", "pw")):
            raise ValueError("user")
        if not HANDLE_RE.match(rec["handle"]):
            raise ValueError("handle")
        if type(rec["balance"]) is not int or rec["balance"] < 0:
            raise ValueError("balance")
        if rec["id"] in s.users or rec["email"] in s.by_email \
                or rec["handle"] in s.by_handle:
            raise ValueError("duplicate user")
        s.add_user(rec)
    for tok, uid in st["tokens"].items():
        if not isinstance(tok, str) or uid not in s.users:
            raise ValueError("token")
        s.tokens[tok] = uid
    for p in st["payments"]:
        rec = dict(p)
        for k in ("payment_id", "from_user_id", "to_user_id", "from_handle",
                  "to_handle", "currency", "note", "visibility", "created_at"):
            if not isinstance(rec[k], str):
                raise ValueError(k)
        if rec["from_user_id"] not in s.users or rec["to_user_id"] not in s.users:
            raise ValueError("payment user")
        if type(rec["amount"]) is not int or type(rec["_ts"]) is not int \
                or type(rec["_seq"]) is not int:
            raise ValueError("payment num")
        if rec["visibility"] not in ("public", "private"):
            raise ValueError("visibility")
        rec["request_id"], rec["settlement_id"]
        s.payments.append(rec)
    for r in st["requests"]:
        rec = dict(r)
        for k in ("request_id", "requester_id", "payer_id", "requester_handle",
                  "payer_handle", "currency", "note", "status", "created_at"):
            if not isinstance(rec[k], str):
                raise ValueError(k)
        if rec["requester_id"] not in s.users or rec["payer_id"] not in s.users:
            raise ValueError("request user")
        if rec["status"] not in STATUSES or type(rec["amount"]) is not int \
                or type(rec["_ts"]) is not int or type(rec["_seq"]) is not int:
            raise ValueError("request")
        rec["payment_id"]
        s.requests[rec["request_id"]] = rec
    for uid, key, path, fp, resp in st["idempotency"]:
        if not (isinstance(uid, str) and isinstance(key, str) and isinstance(path, str)
                and isinstance(fp, str) and isinstance(resp, dict)):
            raise ValueError("idem")
        s.idem[(uid, key, path)] = {"fp": fp, "resp": resp}
    for o in st["operators"]:
        if o not in s.users:
            raise ValueError("operator")
        s.operators.add(o)
    for k in s.counters:
        v = st["counters"][k]
        if type(v) is not int or v < 0:
            raise ValueError("counter")
        s.counters[k] = v
    s.last_us = st["last_us"]
    if type(s.last_us) is not int:
        raise ValueError("last_us")
    return s


def build_from_fixture(fx):
    if not isinstance(fx, dict):
        raise bad("fixture must be an object")
    cur = fx.get("currency")
    if not isinstance(cur, str) or not cur:
        raise bad("currency")
    mu = fx.get("minor_units")
    mu = to_int(mu, 0, 3)
    if mu not in (0, 2, 3):
        raise bad("minor_units")
    users = fx.get("users")
    if not isinstance(users, list):
        raise bad("users")
    s = State()
    s.currency, s.minor_units = cur, mu
    pending_hash = []
    for u in users:
        if not isinstance(u, dict):
            raise bad("user")
        for k in ("id", "email", "password", "display_name", "handle"):
            if not isinstance(u.get(k), str):
                raise bad("user " + k)
        if not u["id"] or len(u["id"]) > 64 or not HANDLE_RE.match(u["handle"]):
            raise bad("user id/handle")
        bal = u.get("balance", 0)
        if isinstance(bal, bool) or not isinstance(bal, (int, Decimal)):
            raise bad("balance")
        if bal < 0:
            raise bad("negative balance")
        bal = to_int(bal, 0, MAX_BALANCE)
        if bal is None:
            raise bad("balance")
        if u["id"] in s.users or u["email"] in s.by_email or u["handle"] in s.by_handle:
            raise bad("duplicate user")
        rec = {"id": u["id"], "email": u["email"], "display_name": u["display_name"],
               "handle": u["handle"], "balance": bal, "pw": None}
        s.add_user(rec)
        pending_hash.append((rec, u["password"]))
    ops = fx.get("settlement_operator_ids", [])
    if not isinstance(ops, list):
        raise bad("settlement_operator_ids")
    for o in ops:
        if not isinstance(o, str) or o not in s.users:
            raise bad("operator id")
        s.operators.add(o)
    base = time.time_ns() // 1000
    n = 0

    def seeded_time(item):
        nonlocal n
        n += 1
        if "created_at" in item:
            return item["created_at"], parse_ts(item["created_at"])
        return fmt_ts(base + n), base + n

    def common(item, what):
        if not isinstance(item, dict):
            raise bad(what)
        for k in ("id", "amount"):
            if k not in item:
                raise bad(what + " " + k)
        if not isinstance(item["id"], str) or not item["id"] or len(item["id"]) > 64:
            raise bad(what + " id")
        amt = to_int(item["amount"], 1, MAX_BALANCE)
        if amt is None:
            raise bad(what + " amount")
        note = item.get("note", "")
        if not isinstance(note, str):
            raise bad(what + " note")
        return amt, note

    pays = fx.get("payments", [])
    if not isinstance(pays, list):
        raise bad("payments")
    for p in pays:
        amt, note = common(p, "payment")
        vis = p.get("visibility", "public")
        if vis not in ("public", "private") or not isinstance(vis, str):
            raise bad("visibility")
        fu, tu = s.users.get(p.get("from_user_id")), s.users.get(p.get("to_user_id"))
        if not fu or not tu or p["id"] in s.pay_ids:
            raise bad("payment parties")
        s.pay_ids.add(p["id"])
        cat, ts = seeded_time(p)
        s.payments.append({
            "payment_id": p["id"], "from_user_id": fu["id"], "from_handle": fu["handle"],
            "to_user_id": tu["id"], "to_handle": tu["handle"], "amount": amt,
            "currency": cur, "note": note, "visibility": vis, "request_id": None,
            "settlement_id": None, "created_at": cat, "_ts": ts, "_seq": s.next_seq()})
    reqs = fx.get("requests", [])
    if not isinstance(reqs, list):
        raise bad("requests")
    for r in reqs:
        amt, note = common(r, "request")
        status = r.get("status", "pending")
        if not isinstance(status, str) or status not in STATUSES:
            raise bad("status")
        rq, py = s.users.get(r.get("requester_id")), s.users.get(r.get("payer_id"))
        if not rq or not py or r["id"] in s.requests:
            raise bad("request parties")
        pid = r.get("payment_id")
        if not isinstance(pid, str):
            pid = None
        cat, ts = seeded_time(r)
        s.requests[r["id"]] = {
            "request_id": r["id"], "requester_id": rq["id"],
            "requester_handle": rq["handle"], "payer_id": py["id"],
            "payer_handle": py["handle"], "amount": amt, "currency": cur, "note": note,
            "status": status, "payment_id": pid, "created_at": cat,
            "_ts": ts, "_seq": s.next_seq()}
    s.last_us = max(s.last_us, base + n)
    with ThreadPoolExecutor(max_workers=4) as ex:
        hashes = list(ex.map(lambda t: hash_password(t[1]), pending_hash))
    for (rec, _), h in zip(pending_hash, hashes):
        rec["pw"] = h
    return s


# ---------------------------------------------------------------- domain ops

def get_user_by_handle(s, handle):
    u = s.by_handle.get(handle)
    if u is None:
        raise ApiError(404, "not_found", "no such handle")
    return u


def read_amount(body, key="amount"):
    if key not in body:
        raise bad("amount required")
    a = to_int(body[key], 1, MAX_AMOUNT)
    if a is None:
        raise bad("invalid amount")
    return a


def read_note(body):
    if "note" not in body:
        return ""
    n = body["note"]
    if not isinstance(n, str) or len(n) > 200:
        raise bad("invalid note")
    return n


def read_visibility(body):
    if "visibility" not in body:
        return "public"
    v = body["visibility"]
    if not isinstance(v, str) or v not in ("public", "private"):
        raise bad("invalid visibility")
    return v


def read_handle(body, key):
    if key not in body:
        raise bad(key + " required")
    h = body[key]
    if not isinstance(h, str):
        raise malformed(key + " must be a string")
    return h


def check_handle_types(body, keys):
    for k in keys:
        if k in body and not isinstance(body[k], str):
            raise malformed(k + " must be a string")
    for k in keys:
        if k not in body:
            raise bad(k + " required")


def new_payment(s, sender, receiver, amount, note, vis, request_id, settlement_id, ts):
    sender["balance"] -= amount
    receiver["balance"] += amount
    pid = s.new_id("p", s.pay_ids)
    s.pay_ids.add(pid)
    rec = {"payment_id": pid, "from_user_id": sender["id"],
           "from_handle": sender["handle"], "to_user_id": receiver["id"],
           "to_handle": receiver["handle"], "amount": amount, "currency": s.currency,
           "note": note, "visibility": vis, "request_id": request_id,
           "settlement_id": settlement_id, "created_at": fmt_ts(ts), "_ts": ts,
           "_seq": s.next_seq()}
    s.payments.append(rec)
    return rec


def new_request(s, requester, payer, amount, note, ts):
    rid = s.new_id("rq", s.requests)
    rec = {"request_id": rid, "requester_id": requester["id"],
           "requester_handle": requester["handle"], "payer_id": payer["id"],
           "payer_handle": payer["handle"], "amount": amount, "currency": s.currency,
           "note": note, "status": "pending", "payment_id": None,
           "created_at": fmt_ts(ts), "_ts": ts, "_seq": s.next_seq()}
    s.requests[rid] = rec
    return rec


def op_payment(s, user, body):
    amount = read_amount(body)
    note = read_note(body)
    vis = read_visibility(body)
    check_handle_types(body, ["to_handle"])
    to = get_user_by_handle(s, body["to_handle"])
    if to["id"] == user["id"]:
        raise ApiError(422, "self_payment", "cannot pay yourself")
    if user["balance"] < amount:
        raise ApiError(409, "insufficient_funds", "insufficient funds")
    return strip(new_payment(s, user, to, amount, note, vis, None, None, s.tick()))


def op_request(s, user, body):
    amount = read_amount(body)
    note = read_note(body)
    check_handle_types(body, ["payer_handle"])
    payer = get_user_by_handle(s, body["payer_handle"])
    if payer["id"] == user["id"]:
        raise ApiError(422, "self_request", "cannot request from yourself")
    return strip(new_request(s, user, payer, amount, note, s.tick()))


def op_pay(s, user, body, rid):
    vis = read_visibility(body)
    req = s.requests.get(rid)
    if req is None:
        raise ApiError(404, "not_found", "no such request")
    if req["payer_id"] != user["id"]:
        raise ApiError(403, "forbidden", "not the payer")
    if req["status"] != "pending":
        raise ApiError(409, "request_not_pending", "request is not pending")
    if user["balance"] < req["amount"]:
        raise ApiError(409, "insufficient_funds", "insufficient funds")
    requester = s.users[req["requester_id"]]
    pay = new_payment(s, user, requester, req["amount"], req["note"], vis,
                      rid, None, s.tick())
    req["status"] = "paid"
    req["payment_id"] = pay["payment_id"]
    return strip(pay)


def split_shares(amount, n):
    base, extra = divmod(amount, n)
    return [base + 1 if i < extra else base for i in range(n)]


def op_split(s, user, body):
    amount = read_amount(body)
    note = read_note(body)
    if "participant_handles" not in body:
        raise bad("participant_handles required")
    ph = body["participant_handles"]
    if not isinstance(ph, list) or not all(isinstance(h, str) for h in ph):
        raise malformed("participant_handles must be a list of strings")
    if not ph or len(set(ph)) != len(ph):
        raise bad("participant_handles empty or duplicate")
    users = [get_user_by_handle(s, h) for h in ph]
    shares = split_shares(amount, len(ph))
    ts = s.tick()
    sid = s.new_id("sp", ())
    reqs = [strip(new_request(s, user, u, sh, note, ts))
            for u, sh in zip(users, shares) if u["id"] != user["id"]]
    return {"split_id": sid, "amount": amount, "currency": s.currency, "note": note,
            "shares": [{"handle": h, "amount": a} for h, a in zip(ph, shares)],
            "requests": reqs, "created_at": fmt_ts(ts)}


def op_settlement(s, user, body):
    if "transfers" not in body:
        raise bad("transfers required")
    tr = body["transfers"]
    if not isinstance(tr, list) or not 1 <= len(tr) <= 32:
        raise bad("transfers must be a list of 1..32")
    if not all(isinstance(t, dict) for t in tr):
        raise bad("transfer must be an object")
    parsed = []
    for t in tr:
        amount = read_amount(t)
        note = read_note(t)
        vis = read_visibility(t)
        check_handle_types(t, ["from_handle", "to_handle"])
        fu = get_user_by_handle(s, t["from_handle"])
        tu = get_user_by_handle(s, t["to_handle"])
        if fu["id"] == tu["id"]:
            raise ApiError(422, "self_payment", "cannot pay yourself")
        parsed.append((fu, tu, amount, note, vis))
    delta = {}
    for fu, tu, amount, _, _ in parsed:
        delta[fu["id"]] = delta.get(fu["id"], 0) - amount
        delta[tu["id"]] = delta.get(tu["id"], 0) + amount
    for uid, d in delta.items():
        if s.users[uid]["balance"] + d < 0:
            raise ApiError(409, "insufficient_funds", "insufficient funds")
    ts = s.tick()
    sid = s.new_id("st", ())
    pays = [strip(new_payment(s, fu, tu, a, n, v, None, sid, ts))
            for fu, tu, a, n, v in parsed]
    return {"settlement_id": sid, "committed_at": fmt_ts(ts), "payments": pays}


def idempotent(s, user, key, path, body, fn):
    fp = fingerprint(body)
    ik = (user["id"], key, path)
    rec = s.idem.get(ik)
    if rec is not None:
        if rec["fp"] != fp:
            raise ApiError(409, "idempotency_key_reuse", "key reused with another body")
        return 200, rec["resp"]
    resp = fn()
    s.idem[ik] = {"fp": fp, "resp": resp}
    return 201, resp


def paginate(items, q):
    limit, offset = 50, 0
    if "limit" in q:
        v = q["limit"]
        if not DIGITS_RE.match(v) or len(v) > 12 or not 1 <= int(v) <= 200:
            raise bad("invalid limit")
        limit = int(v)
    if "offset" in q:
        v = q["offset"]
        if not DIGITS_RE.match(v) or len(v) > 12:
            raise bad("invalid offset")
        offset = int(v)
    items.sort(key=lambda r: (r["_ts"], r["_seq"]), reverse=True)
    page = items[offset:offset + limit]
    return [strip(r) for r in page], offset + limit < len(items)


# ---------------------------------------------------------------- routing

def authenticate(s, headers):
    h = headers.get("Authorization")
    if h:
        parts = h.split(" ")
        if len(parts) == 2 and parts[0].lower() == "bearer":
            uid = s.tokens.get(parts[1])
            if uid is not None:
                return s.users[uid]
    raise ApiError(401, "unauthenticated", "missing or invalid token")


def read_object(raw, allow_empty=False):
    if allow_empty and not raw.strip():
        return {}
    body = parse_json(raw)
    if not isinstance(body, dict):
        raise malformed("body must be a JSON object")
    return body


def idem_key(headers):
    k = headers.get("Idempotency-Key")
    if k is None or k.strip() == "":
        raise ApiError(400, "missing_idempotency_key", "Idempotency-Key required")
    k = k.strip()
    if len(k) > 255:
        raise bad("Idempotency-Key too long")
    return k


def handle_signup(raw):
    body = read_object(raw)
    for k in ("email", "password", "display_name"):
        if k in body and not isinstance(body[k], str):
            raise malformed(k + " must be a string")
    for k in ("email", "password", "display_name"):
        if k not in body:
            raise bad(k + " required")
    email, pw, name = body["email"], body["password"], body["display_name"]
    local, sep, domain = email.partition("@")
    if not sep or not local or not domain or "@" in domain:
        raise bad("invalid email")
    if len(pw) < 8:
        raise bad("password too short")
    handle = "".join(c if c in "abcdefghijklmnopqrstuvwxyz0123456789_" else "_"
                     for c in local.lower())[:20]
    pw_hash = hash_password(pw)
    with LOCK:
        s = STATE
        if email in s.by_email:
            raise ApiError(409, "email_taken", "email already registered")
        if handle in s.by_handle:
            raise ApiError(409, "handle_taken", "handle already taken")
        uid = s.new_id("u", s.users)
        s.add_user({"id": uid, "email": email, "display_name": name, "handle": handle,
                    "balance": 0, "pw": pw_hash})
        token = secrets.token_urlsafe(32)
        s.tokens[token] = uid
    return 201, {"user_id": uid, "display_name": name, "token": token}


def handle_login(raw):
    body = read_object(raw)
    for k in ("email", "password"):
        if k in body and not isinstance(body[k], str):
            raise malformed(k + " must be a string")
    for k in ("email", "password"):
        if k not in body:
            raise bad(k + " required")
    with LOCK:
        u = STATE.by_email.get(body["email"])
        stored = u["pw"] if u else None
    ok = verify_password(body["password"], stored) if stored else False
    if not ok:
        if not stored:
            hash_password("x")  # keep timing alike
        raise ApiError(401, "unauthenticated", "invalid credentials")
    with LOCK:
        if STATE.users.get(u["id"]) is not u:
            raise ApiError(401, "unauthenticated", "invalid credentials")
        token = secrets.token_urlsafe(32)
        STATE.tokens[token] = u["id"]
        return 200, {"user_id": u["id"], "display_name": u["display_name"],
                     "token": token}


def handle_reset(raw):
    fx = parse_json(raw)
    new = build_from_fixture(fx)
    global STATE
    with LOCK:
        STATE = new
    return 204, None


def handle_export():
    with LOCK:
        text = json.dumps({"track": "pocketful", "format_version": 1,
                           "state": STATE.export()}, ensure_ascii=True)
    return 200, text


def handle_import(raw):
    obj = parse_json(raw)
    if not isinstance(obj, dict) or obj.get("track") != "pocketful":
        raise bad("wrong track")
    fv = obj.get("format_version")
    if type(fv) is not int or fv != 1:
        raise bad("wrong format_version")
    if "state" not in obj:
        raise bad("state required")
    # numbers inside state were parsed with Decimal for floats; exports only hold ints
    try:
        new = build_from_export(obj["state"])
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise bad("invalid state")
    global STATE
    with LOCK:
        STATE = new
    return 204, None


PAY_RE = re.compile(r"^/requests/([^/]+)/(pay|decline|cancel)\Z")


def dispatch(method, rawpath, headers, raw):
    parts = urlsplit(rawpath)
    path = parts.path
    qd = parse_qs(parts.query, keep_blank_values=True, errors="replace")
    q = {k: v[-1] for k, v in qd.items()}

    def only(*methods):
        if method not in methods:
            raise ApiError(405, "method_not_allowed", "method not allowed")

    if path == "/health":
        only("GET")
        return 200, {"status": "ok"}
    if path == "/_test/reset":
        only("POST")
        return handle_reset(raw)
    if path == "/_test/export":
        only("GET")
        return handle_export()
    if path == "/_test/import":
        only("POST")
        return handle_import(raw)
    if path == "/auth/signup":
        only("POST")
        return handle_signup(raw)
    if path == "/auth/login":
        only("POST")
        return handle_login(raw)

    known = {"/me": ("GET",), "/payments": ("POST",), "/requests": ("GET", "POST"),
             "/splits": ("POST",), "/activity": ("GET",), "/settlements": ("POST",)}
    m = PAY_RE.match(path)
    if path in known:
        only(*known[path])
    elif m:
        only("POST")
    else:
        raise ApiError(404, "not_found", "no such route")

    with LOCK:
        s = STATE
        user = authenticate(s, headers)
        if path == "/me":
            return 200, {"user_id": user["id"], "display_name": user["display_name"],
                         "handle": user["handle"], "balance": user["balance"],
                         "currency": s.currency, "minor_units": s.minor_units}
        if path == "/activity":
            uid = user["id"]
            items = [p for p in s.payments if p["visibility"] == "public"
                     or p["from_user_id"] == uid or p["to_user_id"] == uid]
            page, more = paginate(items, q)
            return 200, {"payments": page, "has_more": more}
        if path == "/requests" and method == "GET":
            direction, status = q.get("direction"), q.get("status")
            if direction is not None and direction not in ("incoming", "outgoing"):
                raise bad("invalid direction")
            if status is not None and status not in STATUSES:
                raise bad("invalid status")
            uid = user["id"]
            items = []
            for r in s.requests.values():
                inc, out = r["payer_id"] == uid, r["requester_id"] == uid
                if direction == "incoming" and not inc:
                    continue
                if direction == "outgoing" and not out:
                    continue
                if not (inc or out) or (status and r["status"] != status):
                    continue
                items.append(r)
            page, more = paginate(items, q)
            return 200, {"requests": page, "has_more": more}
        if m and m.group(2) in ("decline", "cancel"):
            r = s.requests.get(unquote(m.group(1)))
            if r is None:
                raise ApiError(404, "not_found", "no such request")
            decline = m.group(2) == "decline"
            if r["payer_id" if decline else "requester_id"] != user["id"]:
                raise ApiError(403, "forbidden", "not permitted")
            target = "declined" if decline else "cancelled"
            if r["status"] == "pending":
                r["status"] = target
            elif r["status"] != target:
                raise ApiError(409, "request_not_pending", "request is not pending")
            return 200, strip(r)

        # idempotent write paths
        if path == "/settlements" and user["id"] not in s.operators:
            raise ApiError(403, "forbidden", "operator required")
        key = idem_key(headers)
        body = read_object(raw, allow_empty=bool(m))
        if path == "/payments":
            fn = lambda: op_payment(s, user, body)
        elif path == "/requests":
            fn = lambda: op_request(s, user, body)
        elif path == "/splits":
            fn = lambda: op_split(s, user, body)
        elif path == "/settlements":
            fn = lambda: op_settlement(s, user, body)
        else:
            rid = unquote(m.group(1))
            fn = lambda: op_pay(s, user, body, rid)
        return idempotent(s, user, key, path, body, fn)


# ---------------------------------------------------------------- http server

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 120

    def log_message(self, *a):
        pass

    def _send(self, status, payload):
        if payload is None:
            data = b""
        elif isinstance(payload, str):
            data = payload.encode("utf-8")
        else:
            data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        try:
            self.send_response(status)
            if status != 204:
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            if data:
                self.wfile.write(data)
        except (OSError, ValueError):
            self.close_connection = True

    def _error(self, status, code, message):
        self._send(status, {"error": {"code": code, "message": message}})

    def send_error(self, code, message=None, explain=None):
        if code == 501:
            code, ecode = 405, "method_not_allowed"
        elif code == 404:
            ecode = "not_found"
        else:
            ecode = "malformed_request"
            code = 400 if code >= 500 or code in (408, 414, 431) else code
        self.close_connection = True
        self._error(code, ecode, message or "bad request")

    def _read_body(self):
        te = (self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in te:
            chunks, total = [], 0
            while True:
                line = self.rfile.readline(65537).strip()
                size = int(line.split(b";")[0], 16)
                if size == 0:
                    while self.rfile.readline(65537).strip():
                        pass
                    break
                total += size
                if total > MAX_BODY:
                    raise ValueError("too big")
                chunks.append(self.rfile.read(size))
                self.rfile.readline(65537)
            return b"".join(chunks)
        cl = self.headers.get("Content-Length")
        if cl is None:
            return b""
        n = int(cl)
        if n < 0 or n > MAX_BODY:
            raise ValueError("bad length")
        return self.rfile.read(n) if n else b""

    def _handle(self):
        try:
            raw = self._read_body()
        except (ValueError, OSError):
            self.close_connection = True
            return self._error(400, "malformed_request", "bad body framing")
        try:
            status, payload = dispatch(self.command, self.path, self.headers, raw)
        except ApiError as e:
            return self._error(e.status, e.code, e.message)
        except RecursionError:
            return self._error(400, "malformed_request", "too deeply nested")
        except Exception as e:  # never leak a 5xx for odd input
            sys.stderr.write("internal error: %r\n" % (e,))
            return self._error(500, "internal_error", "internal error")
        self._send(status, payload)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _handle


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 512
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        pass


def main():
    sys.setrecursionlimit(3000)
    threading.stack_size(16 * 1024 * 1024)
    port = int(os.environ.get("PORT") or 8080)
    srv = Server(("0.0.0.0", port), Handler)
    srv.serve_forever()


if __name__ == "__main__":
    main()
