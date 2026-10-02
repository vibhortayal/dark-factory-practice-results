"""Pocketful stage 1: payments, requests, splits, feed, settlements.

Standard library only. All state lives in memory behind one lock, so every
operation (including idempotent replays) is atomic and serialised.
"""
import hashlib
import base64
import heapq
import hmac
import json
import os
import re
import secrets
import sys
import traceback
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit

MAX_AMOUNT = 1_000_000_000
MAX_BALANCE = 2 ** 53
HANDLE_RE = re.compile(r"[a-z0-9_]{1,20}")
TS_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)")
MAX_DEPTH = 901  # object + 900 nested arrays
sys.setrecursionlimit(3000)
DIGITS_RE = re.compile(r"[0-9]+")
STATUSES = ("pending", "paid", "declined", "cancelled")
VISIBILITIES = ("public", "private")
MAX_BODY = 32 * 1024 * 1024  # /_test/* (state exports can be large)
MAX_API_BODY = 1024 * 1024
DEFAULT_TTL = 600
AUTH_STATUSES = ("open", "captured", "voided", "expired")

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


# ------------------------------------------------- instants and the service clock
# An instant is compared as a key (seconds since 0001-01-01T00:00:00Z, fraction digits without trailing zeros).
# Python compares such tuples exactly: no float and no rounding, fractions of any length.
EPOCH1 = 62135596800  # seconds from 0001-01-01 to 1970-01-01
INST_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]+))?([Zz]|[+-][0-9]{2}:[0-9]{2})", re.ASCII)
MAX_SECS = (date(9999, 12, 31).toordinal() - 1) * 86400 + 86399
INF_KEY = (MAX_SECS + 1, "")


def parse_instant(text):
    """Strict RFC 3339 instant with an offset (decision G-1) -> comparable key; ValueError otherwise."""
    if not isinstance(text, str):
        raise ValueError("not a string")
    m = INST_RE.fullmatch(text)
    if m is None:
        raise ValueError("bad instant")
    y, mo, d, hh, mi, ss = (int(m.group(i)) for i in range(1, 7))
    day = date(y, mo, d)
    if hh > 23 or mi > 59 or ss > 59:
        raise ValueError("bad time")
    zone = m.group(8)
    off = 0
    if zone not in ("Z", "z"):
        oh, om = int(zone[1:3]), int(zone[4:6])
        if oh > 23 or om > 59:
            raise ValueError("bad offset")
        off = (oh * 3600 + om * 60) * (-1 if zone[0] == "-" else 1)
    secs = (day.toordinal() - 1) * 86400 + hh * 3600 + mi * 60 + ss - off
    if secs < 0 or secs > MAX_SECS:
        raise ValueError("out of range")
    return (secs, (m.group(7) or "").rstrip("0"))


def valid_instant(text):
    try:
        parse_instant(text)
        return True
    except (ValueError, OverflowError):
        return False


def micro_key(m):
    secs, us = divmod(m, 1000000)
    return (secs, ("%06d" % us).rstrip("0"))


def micro_iso(m):
    """Instant text (always +00:00, microseconds) of a clock value; ValueError beyond year 9999."""
    secs, us = divmod(m, 1000000)
    if secs < 0 or secs > MAX_SECS:
        raise ValueError("out of range")
    day = date.fromordinal(secs // 86400 + 1)
    rem = secs % 86400
    return "%04d-%02d-%02dT%02d:%02d:%02d.%06d+00:00" % (day.year, day.month, day.day, rem // 3600, rem % 3600 // 60, rem % 60, us)


def real_micro():
    return time.time_ns() // 1000 + EPOCH1 * 1000000


def key_text(k):
    return "-" if k is None else "%d.%s" % (k[0], k[1])


def key_from_text(t):
    if t == "-":
        return None
    secs, _, frac = t.partition(".")
    return (int(secs), frac)


def parse_ts(text):
    """Epoch seconds of an RFC 3339 timestamp with offset."""
    return datetime.fromisoformat(text).timestamp()


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


def _total_default(o):
    """Safety net: no value may ever turn an encode into a 5xx."""
    if isinstance(o, BigNum):
        try:
            return float(o.text)
        except (ValueError, OverflowError):
            return 0
    return str(o)


def dumps(o, **kw):
    return json.dumps(o, default=_total_default, **kw)


class BigNum:
    """A JSON number that is not a small exact integer, kept as a canonical text."""
    def __init__(self, text):
        self.text = text


NUM_RE = re.compile(r"(-?)([0-9]+)(?:\.([0-9]+))?(?:[eE]([+-]?)([0-9]+))?")


def lex_number(text):
    """Classify a JSON number literal lexically (no arithmetic on unbounded digit strings).

    Returns an exact int when the value is an integer of at most 30 digits,
    otherwise a BigNum whose text is a canonical form (equal values share a text).
    """
    m = NUM_RE.fullmatch(text)
    if m is None:
        return BigNum("?" + text)
    sign, ip, fp, esign, ed = m.groups()
    digits = (ip + (fp or "")).lstrip("0")
    if not digits:
        return 0
    frac_len = len(fp or "")
    stripped = digits.rstrip("0")
    adjust = (len(digits) - len(stripped)) - frac_len  # exponent contribution of the mantissa
    ed = (ed or "0").lstrip("0") or "0"
    if len(ed) <= 12:
        e = (-int(ed) if esign == "-" else int(ed)) + adjust
        if e >= 0 and len(stripped) + e <= 30:
            v = int(stripped) * 10 ** e
            return -v if sign else v
        return BigNum("%s%se%d" % (sign, stripped, e))
    return BigNum("%s%se%s%sH%d" % (sign, stripped, esign or "+", ed, adjust))


def has_bignum(v):
    """True if a parsed value holds a number that is not a small exact integer (iterative)."""
    stack = [v]
    while stack:
        x = stack.pop()
        if isinstance(x, (BigNum, float)):
            return True
        if isinstance(x, dict):
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
    return False


def check_depth(v):
    """Reject bodies nested deeper than MAX_DEPTH (iterative)."""
    stack = [(v, 1)]
    while stack:
        x, d = stack.pop()
        if isinstance(x, (dict, list)):
            if d > MAX_DEPTH:
                raise malformed("body nested too deeply")
            stack.extend((c, d + 1) for c in (x.values() if isinstance(x, dict) else x))
    return v


def json_eq(a, b):
    """Equality of parsed JSON values; booleans are not numbers. Iterative (bodies may nest deeply)."""
    stack = [(a, b)]
    while stack:
        a, b = stack.pop()
        if isinstance(a, bool) or isinstance(b, bool):
            if not (isinstance(a, bool) and isinstance(b, bool) and a == b):
                return False
        elif isinstance(a, BigNum) or isinstance(b, BigNum):
            if not (isinstance(a, BigNum) and isinstance(b, BigNum) and a.text == b.text):
                return False
        elif isinstance(a, dict) and isinstance(b, dict):
            if a.keys() != b.keys():
                return False
            stack.extend((a[k], b[k]) for k in a)
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                return False
            stack.extend(zip(a, b))
        elif type(a) is not type(b) or a != b:
            return False
    return True


def _bad_constant(name):
    raise ValueError("bad constant " + name)


def parse_json(raw):
    try:
        return check_depth(json.loads(raw.decode("utf-8"), parse_constant=_bad_constant,
                                      parse_int=lex_number, parse_float=lex_number))
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
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid("amount must be an integer")
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
    s = s.lstrip("0") or "0"
    v = int(s) if len(s) <= 30 else 10 ** 30
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

def key_micro_floor(k):
    """Clock value (microseconds) of an instant key, truncated: used to continue the clock after loaded state."""
    return k[0] * 1000000 + int((k[1] + "000000")[:6])


class Store:
    def __init__(self):
        self.clock_last = 0
        self.load({"currency": "EUR", "minor_units": 2, "users": [], "tokens": {}, "payments": [],
                   "requests": [], "splits": [], "settlements": [], "idempotency": [],
                   "operators": [], "counters": {}, "authorizations": [], "ttl": DEFAULT_TTL,
                   "secret": secrets.token_hex(16), "snapshots": {}})

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
        self.ttl = st["ttl"]
        self.auths = list(st["authorizations"])
        self.auths_by_id = {a["id"]: a for a in self.auths}
        self.secret = st["secret"]
        self.snapshots = dict(st["snapshots"])
        # ledger indexes (derived, never exported)
        self.pinfo = {}
        self.by_user = {uid: [] for uid in self.users}
        last = getattr(self, "clock_last", 0)
        for p in self.payments:
            ck = parse_instant(p["created_at"])
            revs = [(1, p["amount"], ck, ck, p["created_at"], p["created_at"], "")]
            for c in p.get("corrections", []):
                revs.append((c["revision"], c["amount"], parse_instant(c["effective_at"]), parse_instant(c["recorded_at"]),
                             c["effective_at"], c["recorded_at"], c["reason"]))
            self.pinfo[p["id"]] = {"created": ck, "revs": revs}
            self.by_user[p["from_user_id"]].append(p["id"])
            self.by_user[p["to_user_id"]].append(p["id"])
            last = max(last, key_micro_floor(ck), key_micro_floor(revs[-1][3]))
        self.by_payer = {uid: [] for uid in self.users}
        self.exp_key = {}
        self.held = {}
        self.heap = []
        for a in self.auths:
            ek = parse_instant(a["expires_at"])
            self.exp_key[a["id"]] = ek
            self.by_payer[a["from_user_id"]].append(a["id"])
            last = max(last, key_micro_floor(parse_instant(a["created_at"])))
            if a.get("closed_at"):
                last = max(last, key_micro_floor(parse_instant(a["closed_at"])))
            if a["status"] == "open":
                self.held[a["from_user_id"]] = self.held.get(a["from_user_id"], 0) + a["amount"] - a["captured_amount"]
                heapq.heappush(self.heap, (ek, a["id"]))
        self.clock_last = last  # the clock continues after the latest instant in the state

    # --- the service clock (decision G-2): strictly increasing microseconds
    def tick(self):
        m = max(real_micro(), self.clock_last + 1)
        self.clock_last = m
        return m

    def now_key(self):
        return micro_key(max(real_micro(), self.clock_last))

    # --- authorizations (holds)
    def sweep(self, now=None):
        """Expire every open authorization whose deadline has passed (lazy, called on every read/write)."""
        now = self.now_key() if now is None else now
        while self.heap and self.heap[0][0] <= now:
            _, aid = heapq.heappop(self.heap)
            a = self.auths_by_id.get(aid)
            if a is not None and a["status"] == "open":
                self.release(a)
                a["status"] = "expired"
                a["closed_at"] = a["expires_at"]

    def release(self, a):
        """Release the uncaptured remainder of an open authorization from the payer's hold."""
        uid = a["from_user_id"]
        self.held[uid] = self.held.get(uid, 0) - (a["amount"] - a["captured_amount"])
        if self.held[uid] == 0:
            del self.held[uid]

    def held_of(self, uid):
        return self.held.get(uid, 0)

    def available(self, user):
        return user["balance"] - self.held.get(user["id"], 0)

    def auth_view(self, a):
        f, t = self.users[a["from_user_id"]], self.users[a["to_user_id"]]
        ids = a["payment_ids"]
        return {
            "authorization_id": a["id"], "from_user_id": f["id"], "from_handle": f["handle"],
            "to_user_id": t["id"], "to_handle": t["handle"], "amount": a["amount"],
            "captured_amount": a["captured_amount"],
            "remaining_amount": (a["amount"] - a["captured_amount"]) if a["status"] == "open" else 0,
            "currency": self.currency, "note": a["note"], "visibility": a["visibility"],
            "status": a["status"], "expires_at": a["expires_at"],
            "payment_id": ids[-1] if ids else None, "payment_ids": list(ids),
            "created_at": a["created_at"], "closed_at": a.get("closed_at"),
        }

    def export(self):
        st = {
            "currency": self.currency, "minor_units": self.minor_units,
            "users": list(self.users.values()), "tokens": self.tokens,
            "payments": self.payments, "requests": self.requests,
            "splits": self.splits, "settlements": self.settlements,
            "idempotency": [{k: v for k, v in e.items() if k != "body"} for e in self.idem.values()],
            "operators": self.operators,
            "counters": self.counters, "authorizations": self.auths, "ttl": self.ttl,
            "secret": self.secret, "snapshots": self.snapshots,
        }
        self.sweep()
        return json.loads(dumps(st))  # deep, atomic copy (caller holds the lock)

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
            "authorization_id": p.get("authorization_id"), "created_at": p["created_at"],
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
        u = self.by_handle.get(h) if HANDLE_RE.fullmatch(h) else None
        if u is None:
            raise ApiError(404, "not_found", "no such user")
        return u

    def move(self, p_from, p_to, amount, note, visibility, request_id=None,
             settlement_id=None, created_at=None, authorization_id=None):
        p_from["balance"] -= amount
        p_to["balance"] += amount
        pid = self.new_id("p", self.payments_by_id)
        rec = {"id": pid, "from_user_id": p_from["id"], "to_user_id": p_to["id"],
               "amount": amount, "note": note, "visibility": visibility,
               "request_id": request_id, "settlement_id": settlement_id,
               "authorization_id": authorization_id, "corrections": [],
               "created_at": created_at or micro_iso(self.tick())}
        self.payments.append(rec)
        self.payments_by_id[pid] = rec
        ck = parse_instant(rec["created_at"])
        self.pinfo[pid] = {"created": ck, "revs": [(1, amount, ck, ck, rec["created_at"], rec["created_at"], "")]}
        self.by_user.setdefault(p_from["id"], []).append(pid)
        self.by_user.setdefault(p_to["id"], []).append(pid)
        return rec


S = Store()


# ------------------------------------------------- fixture / state checks

def _str(v, maxlen=None, nonempty=True):
    if not isinstance(v, str) or (nonempty and not v) or (maxlen and len(v) > maxlen):
        raise invalid("bad string field")
    return v


_BAD_EMAIL_CATS = ("Cc", "Cf", "Zs", "Zl", "Zp", "Cs", "Co", "Cn")


def _email_ok(e):
    if not isinstance(e, str) or e.count("@") != 1:
        return False
    local, domain = e.split("@")
    return bool(local) and bool(domain) and not any(
        unicodedata.category(c) in _BAD_EMAIL_CATS for c in e)


def _ref(v, ids):
    return isinstance(v, str) and v in ids


def _bal(v):
    if not is_int(v) or v < 0 or v > MAX_BALANCE:
        raise invalid("bad balance")
    return v


def _money(v):
    if not is_int(v) or v < 0 or v > MAX_BALANCE:
        raise invalid("bad amount")
    return v


def build_fixture(fx, reset_m):
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
        if not isinstance(h, str) or not HANDLE_RE.fullmatch(h):
            raise invalid("bad handle")
        bal = _bal(u.get("balance"))
        if uid in ids or h in handles or email in emails:
            raise invalid("duplicate user id, handle or email")
        ids.add(uid), handles.add(h), emails.add(email)
        users.append({"id": uid, "email": email, "pw_hash": None, "display_name": dn,
                      "handle": h, "balance": bal})
        pws.append(pw)
    base = datetime.now(timezone.utc)
    reset_text = micro_iso(reset_m)
    now_k = micro_key(reset_m)

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
        if not _ref(p.get("from_user_id"), ids) or not _ref(p.get("to_user_id"), ids):
            raise invalid("payment refers to unknown user")
        note = p.get("note", "")
        vis = p.get("visibility", "public")
        if not isinstance(note, str) or vis not in VISIBILITIES or not isinstance(vis, str):
            raise invalid("bad payment note or visibility")
        created = p.get("created_at", reset_text)
        try:
            ck = parse_instant(created)
        except ValueError:
            raise invalid("bad payment created_at")
        if ck > now_k:
            raise invalid("a seeded payment cannot be created in the future")
        payments.append({"id": pid, "from_user_id": p["from_user_id"], "to_user_id": p["to_user_id"],
                         "amount": _money(p.get("amount")), "note": note, "visibility": vis,
                         "request_id": None, "settlement_id": None, "authorization_id": None, "corrections": [],
                         "created_at": created, "_k": (ck, i)})
    payments.sort(key=lambda p: p["_k"])
    for p in payments:
        del p["_k"]
    net = {}
    for p in payments:
        net[p["to_user_id"]] = net.get(p["to_user_id"], 0) + p["amount"]
        net[p["from_user_id"]] = net.get(p["from_user_id"], 0) - p["amount"]
    for u in users:
        u["opening"] = u["balance"] - net.get(u["id"], 0)
    requests, rids = [], set()
    rin = listing("requests")
    for i, r in enumerate(rin):
        if not isinstance(r, dict):
            raise invalid("request must be an object")
        rid = _str(r.get("id"), 64)
        if rid in rids:
            raise invalid("duplicate request id")
        rids.add(rid)
        if not _ref(r.get("requester_id"), ids) or not _ref(r.get("payer_id"), ids):
            raise invalid("request refers to unknown user")
        note = r.get("note", "")
        st = r.get("status", "pending")
        if not isinstance(note, str) or not isinstance(st, str) or st not in STATUSES:
            raise invalid("bad request note or status")
        requests.append({"id": rid, "requester_id": r["requester_id"], "payer_id": r["payer_id"],
                         "amount": _money(r.get("amount")), "note": note, "status": st,
                         "payment_id": None,
                         "created_at": now_str(base - timedelta(seconds=len(rin) - i))})
    ttl = fx.get("authorization_ttl_seconds", DEFAULT_TTL)
    if not is_int(ttl) or ttl < 1:
        raise invalid("authorization_ttl_seconds must be a positive integer")
    try:
        micro_iso(reset_m + ttl * 1000000)
    except (OverflowError, ValueError):
        raise invalid("authorization_ttl_seconds too large")
    auths, aids, holds = [], set(), {}
    ain = listing("authorizations")
    for i, a in enumerate(ain):
        if not isinstance(a, dict):
            raise invalid("authorization must be an object")
        aid = _str(a.get("id"), 64)
        if aid in aids:
            raise invalid("duplicate authorization id")
        aids.add(aid)
        if not _ref(a.get("from_user_id"), ids) or not _ref(a.get("to_user_id"), ids) \
                or a["from_user_id"] == a["to_user_id"]:
            raise invalid("authorization refers to unknown or identical users")
        amount = a.get("amount")
        if not is_int(amount) or not 1 <= amount <= MAX_AMOUNT:
            raise invalid("bad authorization amount")
        note = a.get("note", "")
        vis = a.get("visibility", "public")
        st = a.get("status", "open")
        if not isinstance(note, str) or len(note) > 200 or not isinstance(vis, str) or vis not in VISIBILITIES \
                or not isinstance(st, str) or st not in AUTH_STATUSES:
            raise invalid("bad authorization note, visibility or status")
        exp = a.get("expires_at")
        try:
            exp_k = parse_instant(exp)
        except ValueError:
            raise invalid("bad expires_at")
        acreated = a.get("created_at", reset_text)
        try:
            ack = parse_instant(acreated)
        except ValueError:
            raise invalid("bad authorization created_at")
        if ack > now_k:
            raise invalid("a seeded authorization cannot be created in the future")
        if st == "open" and exp_k > now_k:
            holds[a["from_user_id"]] = holds.get(a["from_user_id"], 0) + amount
        # a closed seeded hold has no lifecycle to reconstruct (G-12): it holds nothing at any instant
        closed = None
        if st != "open":
            closed = exp if (st == "expired" and exp_k <= now_k) else reset_text
        auths.append({"id": aid, "from_user_id": a["from_user_id"], "to_user_id": a["to_user_id"],
                      "amount": amount, "captured_amount": amount if st == "captured" else 0,
                      "note": note, "visibility": vis, "status": st, "expires_at": exp, "payment_ids": [],
                      "created_at": acreated, "closed_at": closed, "tracked": st == "open" and exp_k > ack})
    balances = {u["id"]: u["balance"] for u in users}
    if any(h > balances[uid] for uid, h in holds.items()):
        raise invalid("seeded holds exceed a balance")
    ops = fx.get("settlement_operator_ids")
    if ops is None:
        ops = []
    if not isinstance(ops, list) or any(not isinstance(o, str) or o not in ids for o in ops):
        raise invalid("bad settlement_operator_ids")
    state = {"currency": cur, "minor_units": mu, "users": users, "tokens": {}, "payments": payments,
             "requests": requests, "splits": [], "settlements": [], "idempotency": [],
             "operators": list(dict.fromkeys(ops)), "counters": {},
             "authorizations": auths, "ttl": ttl, "secret": secrets.token_hex(16), "snapshots": {}}
    return state, pws


_POOL = ThreadPoolExecutor(max_workers=max(2, os.cpu_count() or 2))


def do_reset(fx):
    with LOCK:
        reset_m = S.tick()
    try:
        state, pws = build_fixture(fx, reset_m)
    except (TypeError, ValueError, AttributeError, KeyError, RecursionError):
        raise invalid("invalid fixture")
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
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, RecursionError):
        raise invalid("invalid state")


def need(cond):
    if not cond:
        raise invalid("invalid state")


def _ts(v):
    return isinstance(v, str) and valid_instant(v)


def _opt_ref(v, pool):
    return v is None or (isinstance(v, str) and v in pool)


def _payment_shape(r, ctx):
    ids, pids, rids, _, sids, aids = ctx
    r = dict(r) if isinstance(r, dict) else r
    if isinstance(r, dict) and "authorization_id" not in r:
        r["authorization_id"] = None  # responses stored by a stage-1 service predate the field
    need(isinstance(r, dict) and isinstance(r["payment_id"], str) and r["payment_id"] in pids
         and _ref(r["from_user_id"], ids) and _ref(r["to_user_id"], ids)
         and isinstance(r["from_handle"], str) and HANDLE_RE.fullmatch(r["from_handle"])
         and isinstance(r["to_handle"], str) and HANDLE_RE.fullmatch(r["to_handle"])
         and is_int(r["amount"]) and 0 <= r["amount"] <= MAX_BALANCE
         and isinstance(r["currency"], str) and isinstance(r["note"], str) and len(r["note"]) <= 200
         and isinstance(r["visibility"], str) and r["visibility"] in VISIBILITIES
         and _opt_ref(r["request_id"], rids) and _opt_ref(r["settlement_id"], sids)
         and _opt_ref(r["authorization_id"], aids) and _ts(r["created_at"]))
    return {k: r[k] for k in ("payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
                              "currency", "note", "visibility", "request_id", "settlement_id",
                              "authorization_id", "created_at")}


def _request_shape(r, ctx):
    ids, pids, rids, _, _, _ = ctx
    need(isinstance(r, dict) and isinstance(r["request_id"], str) and r["request_id"] in rids
         and _ref(r["requester_id"], ids) and _ref(r["payer_id"], ids)
         and isinstance(r["requester_handle"], str) and HANDLE_RE.fullmatch(r["requester_handle"])
         and isinstance(r["payer_handle"], str) and HANDLE_RE.fullmatch(r["payer_handle"])
         and is_int(r["amount"]) and 0 <= r["amount"] <= MAX_BALANCE
         and isinstance(r["currency"], str) and isinstance(r["note"], str) and len(r["note"]) <= 200
         and isinstance(r["status"], str) and r["status"] in STATUSES
         and _opt_ref(r["payment_id"], pids) and _ts(r["created_at"]))
    return {k: r[k] for k in ("request_id", "requester_id", "requester_handle", "payer_id", "payer_handle",
                              "amount", "currency", "note", "status", "payment_id", "created_at")}


def _auth_shape(r, ctx):
    ids, pids, _, _, _, aids = ctx
    r = dict(r) if isinstance(r, dict) else r
    if isinstance(r, dict) and "closed_at" not in r:
        r["closed_at"] = None  # responses stored by an earlier stage predate the field
    need(isinstance(r, dict) and (r["closed_at"] is None or _ts(r["closed_at"])))
    need(isinstance(r, dict) and isinstance(r["authorization_id"], str) and r["authorization_id"] in aids
         and _ref(r["from_user_id"], ids) and _ref(r["to_user_id"], ids)
         and isinstance(r["from_handle"], str) and HANDLE_RE.fullmatch(r["from_handle"])
         and isinstance(r["to_handle"], str) and HANDLE_RE.fullmatch(r["to_handle"])
         and is_int(r["amount"]) and 0 <= r["amount"] <= MAX_BALANCE
         and is_int(r["captured_amount"]) and 0 <= r["captured_amount"] <= MAX_BALANCE
         and is_int(r["remaining_amount"]) and 0 <= r["remaining_amount"] <= MAX_BALANCE
         and isinstance(r["currency"], str) and isinstance(r["note"], str) and len(r["note"]) <= 200
         and isinstance(r["visibility"], str) and r["visibility"] in VISIBILITIES
         and isinstance(r["status"], str) and r["status"] in AUTH_STATUSES
         and _ts(r["expires_at"]) and _ts(r["created_at"])
         and _opt_ref(r["payment_id"], pids) and isinstance(r["payment_ids"], list)
         and all(isinstance(x, str) and x in pids for x in r["payment_ids"]))
    return {k: (list(r[k]) if k == "payment_ids" else r[k])
            for k in ("authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
                      "captured_amount", "remaining_amount", "currency", "note", "visibility", "status",
                      "expires_at", "payment_id", "payment_ids", "created_at", "closed_at")}


def _response_shape(path, r, ctx):
    """Whitelist a stored idempotent response by the shape its path produces."""
    if path == "/authorizations":
        return _auth_shape(r, ctx)
    if re.fullmatch(r"/payments/.+/corrections", path, re.S):
        need(isinstance(r, dict) and isinstance(r["payment_id"], str) and r["payment_id"] in ctx[1]
             and is_int(r["revision"]) and r["revision"] >= 2 and is_int(r["amount"]) and 0 <= r["amount"] <= MAX_AMOUNT
             and _ts(r["effective_at"]) and _ts(r["recorded_at"]) and isinstance(r["reason"], str)
             and 1 <= len(r["reason"]) <= 200)
        return {k: r[k] for k in ("payment_id", "revision", "amount", "effective_at", "recorded_at", "reason")}
    if path == "/payments" or re.fullmatch(r"/requests/.+/pay", path, re.S) \
            or re.fullmatch(r"/authorizations/.+/capture", path, re.S):
        return _payment_shape(r, ctx)
    if path == "/requests":
        return _request_shape(r, ctx)
    if path == "/splits":
        need(isinstance(r, dict) and isinstance(r["split_id"], str) and r["split_id"] in ctx[3]
             and is_int(r["amount"]) and 0 <= r["amount"] <= MAX_BALANCE and isinstance(r["currency"], str)
             and isinstance(r["note"], str) and len(r["note"]) <= 200 and _ts(r["created_at"])
             and isinstance(r["shares"], list) and isinstance(r["requests"], list))
        shares = []
        for sh in r["shares"]:
            need(isinstance(sh, dict) and isinstance(sh["handle"], str) and HANDLE_RE.fullmatch(sh["handle"])
                 and is_int(sh["amount"]) and 0 <= sh["amount"] <= MAX_BALANCE)
            shares.append({"handle": sh["handle"], "amount": sh["amount"]})
        return {"split_id": r["split_id"], "amount": r["amount"], "currency": r["currency"], "note": r["note"],
                "shares": shares, "requests": [_request_shape(x, ctx) for x in r["requests"]],
                "created_at": r["created_at"]}
    if path == "/settlements":
        need(isinstance(r, dict) and isinstance(r["settlement_id"], str) and r["settlement_id"] in ctx[4]
             and _ts(r["committed_at"]) and isinstance(r["payments"], list))
        return {"settlement_id": r["settlement_id"], "committed_at": r["committed_at"],
                "payments": [_payment_shape(x, ctx) for x in r["payments"]]}
    raise invalid("unknown idempotent path")


def _id(v):
    return isinstance(v, str) and 0 < len(v) <= 64


def _opt_id(v):
    return v is None or _id(v)


def _validate_state(st):
    if not isinstance(st, dict):
        raise invalid("state must be an object")
    if not isinstance(st["currency"], str) or not is_int(st["minor_units"]) \
            or st["minor_units"] not in (0, 2, 3):
        raise invalid("bad currency")
    users, ids, handles, emails = [], set(), set(), set()
    for u in st["users"]:
        if not (_id(u["id"]) and _email_ok(u["email"])
                and isinstance(u["pw_hash"], str) and isinstance(u["display_name"], str)
                and isinstance(u["handle"], str) and HANDLE_RE.fullmatch(u["handle"])
                and is_int(u["balance"]) and 0 <= u["balance"] <= MAX_BALANCE):
            raise invalid("bad user")
        if u["id"] in ids or u["handle"] in handles or u["email"] in emails:
            raise invalid("duplicate user")
        ids.add(u["id"]), handles.add(u["handle"]), emails.add(u["email"])
        rec = {k: u[k] for k in ("id", "email", "pw_hash", "display_name", "handle", "balance")}
        if "opening" in u:
            need(is_int(u["opening"]) and -MAX_BALANCE <= u["opening"] <= MAX_BALANCE)
            rec["opening"] = u["opening"]
        users.append(rec)
    tokens = st["tokens"]
    if not isinstance(tokens, dict) or any(not isinstance(v, str) or v not in ids for v in tokens.values()):
        raise invalid("bad tokens")
    payments, pids = [], set()
    for p in st["payments"]:
        if not (_id(p["id"]) and _ref(p["from_user_id"], ids) and _ref(p["to_user_id"], ids)
                and is_int(p["amount"]) and 0 <= p["amount"] <= MAX_BALANCE
                and isinstance(p["note"], str) and len(p["note"]) <= 200
                and p["visibility"] in VISIBILITIES and isinstance(p["visibility"], str)
                and _ts(p["created_at"])
                and _opt_id(p.get("request_id")) and _opt_id(p.get("settlement_id"))
                and _opt_id(p.get("authorization_id"))):
            raise invalid("bad payment")
        if p["id"] in pids:
            raise invalid("duplicate payment")
        pids.add(p["id"])
        rec = {k: p.get(k) for k in ("id", "from_user_id", "to_user_id", "amount", "note",
                                      "visibility", "request_id", "settlement_id", "authorization_id",
                                      "created_at")}
        rec["corrections"] = []
        prev_rec = parse_instant(p["created_at"])
        for n, c in enumerate(p.get("corrections", []), start=2):
            need(isinstance(c, dict) and c["revision"] == n and is_int(c["amount"]) and 0 <= c["amount"] <= MAX_AMOUNT
                 and _ts(c["effective_at"]) and _ts(c["recorded_at"]) and isinstance(c["reason"], str)
                 and 1 <= len(c["reason"]) <= 200)
            rk = parse_instant(c["recorded_at"])
            need(rk > prev_rec)
            prev_rec = rk
            rec["corrections"].append({"revision": n, "amount": c["amount"], "effective_at": c["effective_at"],
                                       "recorded_at": c["recorded_at"], "reason": c["reason"]})
        payments.append(rec)
    # chronological order by created_at (stable), so every list keeps its meaning
    payments.sort(key=lambda p: parse_instant(p["created_at"]))
    net = {}
    for p in payments:
        net[p["to_user_id"]] = net.get(p["to_user_id"], 0) + p["amount"]
        net[p["from_user_id"]] = net.get(p["from_user_id"], 0) - p["amount"]
    for u in users:
        if "opening" not in u:  # an export of an earlier stage: the opening balance is what was held before anything moved
            u["opening"] = u["balance"] - net.get(u["id"], 0)
    requests, rids = [], set()
    for r in st["requests"]:
        if not (_id(r["id"]) and _ref(r["requester_id"], ids) and _ref(r["payer_id"], ids)
                and is_int(r["amount"]) and 0 <= r["amount"] <= MAX_BALANCE
                and isinstance(r["note"], str) and len(r["note"]) <= 200
                and isinstance(r["status"], str) and r["status"] in STATUSES
                and _ts(r["created_at"])
                and _opt_id(r.get("payment_id"))):
            raise invalid("bad request")
        if r["id"] in rids:
            raise invalid("duplicate request")
        rids.add(r["id"])
        requests.append({k: r.get(k) for k in ("id", "requester_id", "payer_id", "amount", "note",
                                                "status", "payment_id", "created_at")})
    if any(p["request_id"] is not None and p["request_id"] not in rids for p in payments) \
            or any(r["payment_id"] is not None and r["payment_id"] not in pids for r in requests):
        raise invalid("dangling reference")
    sids_split = set()
    splits = []
    for s in st["splits"]:
        need(_id(s["id"]) and s["id"] not in sids_split and _ref(s["requester_id"], ids)
             and _money(s["amount"]) is not None and isinstance(s["note"], str)
             and isinstance(s["shares"], list) and isinstance(s["request_ids"], list)
             and all(isinstance(x, str) and x in rids for x in s["request_ids"])
             and _ts(s["created_at"]))
        shares = []
        for sh in s["shares"]:
            need(isinstance(sh["handle"], str) and HANDLE_RE.fullmatch(sh["handle"]))
            shares.append({"handle": sh["handle"], "amount": _money(sh["amount"])})
        sids_split.add(s["id"])
        splits.append({"id": s["id"], "requester_id": s["requester_id"], "amount": s["amount"],
                       "note": s["note"], "shares": shares, "request_ids": list(s["request_ids"]),
                       "created_at": s["created_at"]})
    settlements, sids = [], set()
    for s in st["settlements"]:
        need(_id(s["id"]) and s["id"] not in sids and isinstance(s["payment_ids"], list)
             and all(isinstance(x, str) and x in pids for x in s["payment_ids"])
             and _ts(s["committed_at"]))
        sids.add(s["id"])
        settlements.append({"id": s["id"], "committed_at": s["committed_at"],
                            "payment_ids": list(s["payment_ids"])})
    need(all(p["settlement_id"] is None or p["settlement_id"] in sids for p in payments))
    ttl = st.get("ttl", DEFAULT_TTL)
    need(is_int(ttl) and ttl >= 1)
    try:
        micro_iso(real_micro() + ttl * 1000000)
    except (OverflowError, ValueError):
        raise invalid("ttl too large")
    auths, aids, holds = [], set(), {}
    for a in st.get("authorizations", []):
        need(_id(a["id"]) and a["id"] not in aids and _ref(a["from_user_id"], ids) and _ref(a["to_user_id"], ids)
             and a["from_user_id"] != a["to_user_id"]
             and is_int(a["amount"]) and 1 <= a["amount"] <= MAX_AMOUNT
             and is_int(a["captured_amount"]) and 0 <= a["captured_amount"] <= a["amount"]
             and isinstance(a["note"], str) and len(a["note"]) <= 200
             and isinstance(a["visibility"], str) and a["visibility"] in VISIBILITIES
             and isinstance(a["status"], str) and a["status"] in AUTH_STATUSES
             and _ts(a["expires_at"]) and _ts(a["created_at"])
             and isinstance(a["payment_ids"], list) and len(set(a["payment_ids"])) == len(a["payment_ids"])
             and all(isinstance(x, str) and x in pids for x in a["payment_ids"]))
        aids.add(a["id"])
        if a["status"] == "open":
            holds[a["from_user_id"]] = holds.get(a["from_user_id"], 0) + a["amount"] - a["captured_amount"]
        rec = {k: (list(a[k]) if k == "payment_ids" else a[k])
               for k in ("id", "from_user_id", "to_user_id", "amount", "captured_amount", "note",
                         "visibility", "status", "expires_at", "payment_ids", "created_at")}
        ck, ek = parse_instant(a["created_at"]), parse_instant(a["expires_at"])
        if "closed_at" in a or "tracked" in a:
            need(a.get("closed_at") is None or _ts(a["closed_at"]))
            need(isinstance(a.get("tracked"), bool))
            need((a["status"] == "open") == (a["closed_at"] is None))
            rec["closed_at"], rec["tracked"] = a["closed_at"], a["tracked"]
        else:
            # an export of stage 2: derive the lifecycle from what it carries (decision G-12)
            pay_by_id = {p["id"]: p for p in payments}
            last_cap = pay_by_id[a["payment_ids"][-1]]["created_at"] if a["payment_ids"] else None
            closed = None
            if last_cap is not None and parse_instant(last_cap) < ck:
                last_cap = a["created_at"]
            if a["status"] == "captured":
                closed = last_cap or a["created_at"]
            elif a["status"] == "voided":
                closed = last_cap or a["created_at"]
            elif a["status"] == "expired":
                closed = a["expires_at"]
            rec["closed_at"] = closed
            rec["tracked"] = ek > ck and (a["status"] in ("open", "expired", "voided") or bool(a["payment_ids"])) \
                and not (a["status"] == "captured" and not a["payment_ids"]) \
                and not (a["status"] == "voided" and not a["payment_ids"])
        auths.append(rec)
    bal = {u["id"]: u["balance"] for u in users}
    need(all(h <= bal[uid] for uid, h in holds.items()))
    need(all(p["authorization_id"] is None or p["authorization_id"] in aids for p in payments))
    ctx = (ids, pids, rids, sids_split, sids, aids)
    idem, seen = [], set()
    for e in st["idempotency"]:
        need(_ref(e["user_id"], ids) and e["method"] == "POST" and isinstance(e["path"], str)
             and isinstance(e["key"], str) and 1 <= len(e["key"]) <= 255 and e["status"] == 201
             and isinstance(e["body_raw"], str))
        response = _response_shape(e["path"], e["response"], ctx)
        try:
            parsed_body = parse_json(e["body_raw"].encode("utf-8"))
        except ApiError:
            raise invalid("bad idempotency body")
        need(isinstance(parsed_body, dict))
        k = (e["user_id"], e["method"], e["path"], e["key"])
        need(k not in seen)
        seen.add(k)
        idem.append({"user_id": e["user_id"], "method": "POST", "path": e["path"], "key": e["key"],
                     "body": parsed_body, "body_raw": e["body_raw"], "status": 201, "response": response})
    ops = st["operators"]
    if not isinstance(ops, list) or any(not isinstance(o, str) or o not in ids for o in ops):
        raise invalid("bad operators")
    counters = st["counters"]
    if not isinstance(counters, dict) or any(not is_int(v) for v in counters.values()):
        raise invalid("bad counters")
    secret = st.get("secret")
    if secret is None:
        secret = secrets.token_hex(16)
    need(isinstance(secret, str) and 8 <= len(secret) <= 128)
    snaps = st.get("snapshots", {})
    need(isinstance(snaps, dict) and all(isinstance(k, str) and isinstance(v, str) and len(v) <= 20000 for k, v in snaps.items()))
    for v in snaps.values():
        arr = json.loads(v)
        need(isinstance(arr, list) and len(arr) == 4 and all(isinstance(x, str) for x in arr))
        for x in arr[1:]:
            key_from_text(x)
    return {"currency": st["currency"], "minor_units": st["minor_units"], "users": users,
            "tokens": dict(tokens), "payments": payments, "requests": requests, "splits": splits,
            "settlements": settlements, "idempotency": idem, "operators": list(ops),
            "counters": dict(counters), "authorizations": auths, "ttl": ttl, "secret": secret,
            "snapshots": dict(snaps)}


def prove_state(state):
    """Import is only accepted if the candidate exports and that export validates again."""
    try:
        tmp = Store()
        tmp.load(state)
        text = dumps(tmp.export())
        again = parse_json(text.encode("utf-8"))
        if has_bignum(again):
            raise invalid("state is not plain")
        validate_state(again)
    except ApiError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise invalid("state does not survive an export round trip")


# -------------------------------------------------------------- endpoints

def authenticate(headers):
    S.sweep()
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
            return 200, json.loads(dumps(rec["response"]))
        raise ApiError(409, "idempotency_key_reuse", "key already used with a different body")
    status, resp = fn(body)
    S.idem[k] = {"user_id": user["id"], "method": method, "path": path, "key": key,
                 "body": body, "body_raw": raw.decode("utf-8") if raw.strip() else "{}", "status": 201, "response": json.loads(dumps(resp))}
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
        u["opening"] = 0
        S.by_user[uid] = []
        S.by_payer[uid] = []
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
                 "handle": user["handle"], "balance": user["balance"], "total": user["balance"],
                 "available": S.available(user), "held": S.held_of(user["id"]),
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
    if S.available(user) < amount:
        raise ApiError(409, "insufficient_funds", "insufficient funds")
    return 201, S.payment_view(S.move(user, to, amount, note, vis))


def new_request_record(requester, payer, amount, note, created_at=None):
    rid = S.new_id("rq", S.requests_by_id)
    rec = {"id": rid, "requester_id": requester["id"], "payer_id": payer["id"], "amount": amount,
           "note": note, "status": "pending", "payment_id": None, "created_at": created_at or micro_iso(S.tick())}
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
    if S.available(user) < r["amount"]:
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
    created = micro_iso(S.tick())
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
        if S.users[uid]["balance"] + d - S.held_of(uid) < 0:
            raise ApiError(409, "insufficient_funds", "settlement is not affordable")
    sid = S.new_id("st", {s["id"] for s in S.settlements})
    committed = micro_iso(S.tick())
    members = [S.move(f, to, amount, note, vis, settlement_id=sid, created_at=committed)
               for f, to, amount, note, vis in parsed]
    S.settlements.append({"id": sid, "committed_at": committed, "payment_ids": [m["id"] for m in members]})
    return 201, {"settlement_id": sid, "committed_at": committed,
                 "payments": [S.payment_view(m) for m in members]}


def bignum_kind(b):
    """Classify a BigNum: 'neg', 'frac' or 'huge' (a positive integer beyond 30 digits)."""
    t = b.text
    if t.startswith("-"):
        return "neg"
    m = re.fullmatch(r"([0-9]+)e(?:(\+|-)?([0-9]+))(?:H(-?[0-9]+))?", t)
    if m is None:
        return "frac"
    if t.find("e-") >= 0:
        return "frac"
    return "huge"


# ----------------------------------------------------------------- ledger
# One model answers every historical question. total(u, T, K) is the opening balance plus the selected
# revision of every payment of u whose effective time is <= T, where a payment's selected revision under K is
# its latest revision recorded <= K. held(u, T, K) is the sum of the open remainders of u's authorizations,
# simulated from the lifecycle events that are known by K. Current values are the same functions at (now, now).

def selected(pid, K):
    """Latest revision of a payment recorded at or before K (None when K is INF: the latest)."""
    revs = S.pinfo[pid]["revs"]
    if K is None:
        return revs[-1]
    for r in reversed(revs):
        if r[3] <= K:
            return r
    return None


def total_at(uid, T, K):
    bal = S.users[uid]["opening"]
    for pid in S.by_user.get(uid, ()):
        r = selected(pid, K)
        if r is not None and (T is None or r[2] <= T):
            p = S.payments_by_id[pid]
            bal += r[1] if p["to_user_id"] == uid else -r[1]
    return bal


def hold_events(a):
    """Lifecycle events of an authorization: (time key, order, kind, amount, closing)."""
    ev = []
    pids = a["payment_ids"]
    born = parse_instant(a["created_at"])  # imported earlier-stage data can carry coarser times: nothing precedes creation
    for i, pid in enumerate(pids):
        p = S.payments_by_id[pid]
        ev.append((max(S.pinfo[pid]["created"], born), 1, "cap", p["amount"], a["status"] == "captured" and i == len(pids) - 1))
    if a["status"] == "voided" and a.get("closed_at"):
        ev.append((max(parse_instant(a["closed_at"]), born), 2, "void", 0, True))
    ev.append((max(S.exp_key[a["id"]], born), 3, "expiry", 0, True))
    ev.sort(key=lambda e: (e[0], e[1]))
    return ev


def hold_steps(a, T, K):
    """Yield (time key, new remainder) for each change of the hold of `a`, for events up to T known by K."""
    if not a.get("tracked", True):
        return
    created = parse_instant(a["created_at"])
    if created > T or (K is not None and created > K):
        return
    remaining = a["amount"]
    yield created, remaining
    for t, _, kind, amount, closing in hold_events(a):
        if t > T:
            break
        if kind != "expiry" and K is not None and t > K:
            continue  # not known yet; the deadline itself is known as soon as the hold exists
        new = 0 if (closing or kind != "cap") else max(0, remaining - amount)
        if new != remaining:
            remaining = new
            yield t, remaining


def held_at(uid, T, K):
    total = 0
    for aid in S.by_payer.get(uid, ()):
        rem = 0
        for _, rem in hold_steps(S.auths_by_id[aid], T, K):
            pass
        total += rem
    return total


def money_view(uid, T, K):
    total = total_at(uid, T, K)
    held = held_at(uid, T, K)
    return {"balance": total, "total": total, "available": total - held, "held": held}


def ledger_ok(uid, override=None):
    """No boundary up to now may leave total or available negative (latest revisions; same-instant movements combined)."""
    events = []
    for pid in S.by_user.get(uid, ()):
        if override is not None and override[0] == pid:
            r = override[1]
        else:
            r = S.pinfo[pid]["revs"][-1]
        p = S.payments_by_id[pid]
        events.append((r[2], r[1] if p["to_user_id"] == uid else -r[1], 0))
    for aid in S.by_payer.get(uid, ()):
        prev = 0
        for t, rem in hold_steps(S.auths_by_id[aid], INF_KEY, None):
            events.append((t, 0, rem - prev))
            prev = rem
    events.sort(key=lambda e: e[0])
    now = S.now_key()
    total, held = S.users[uid]["opening"], 0
    i = 0
    while i < len(events):
        t = events[i][0]
        if t > now:
            break
        while i < len(events) and events[i][0] == t:
            total += events[i][1]
            held += events[i][2]
            i += 1
        if total < 0 or total - held < 0:
            return False
    return True


# ---- query instants and snapshots

def query_instant(q, name):
    if name not in q:
        return None, None
    try:
        return q[name], parse_instant(q[name])
    except ValueError:
        raise invalid("%s must be an RFC 3339 instant with an offset" % name)


def make_token(uid, frm, to, cut):
    payload = json.dumps([uid, key_text(frm), key_text(to), key_text(cut)], separators=(",", ":")).encode("utf-8")
    sig = hmac.new(S.secret.encode(), payload, hashlib.sha256).digest()[:12]
    tok = "s" + base64.urlsafe_b64encode(payload + sig).decode().rstrip("=")
    if len(tok) <= 190:
        return tok
    sid = S.new_id("snap", S.snapshots)
    S.snapshots[sid] = payload.decode("utf-8")
    return "r" + sid


def read_token(uid, tok):
    try:
        if tok.startswith("r"):
            payload = S.snapshots[tok[1:]].encode("utf-8")
        elif tok.startswith("s"):
            raw = base64.urlsafe_b64decode(tok[1:] + "=" * (-len(tok[1:]) % 4))
            payload, sig = raw[:-12], raw[-12:]
            want = hmac.new(S.secret.encode(), payload, hashlib.sha256).digest()[:12]
            if not hmac.compare_digest(sig, want):
                raise KeyError
        else:
            raise KeyError
        u, f, t, c = json.loads(payload.decode("utf-8"))
        if u != uid:
            raise KeyError
        return key_from_text(f), key_from_text(t), key_from_text(c)
    except (KeyError, ValueError, TypeError, UnicodeError):
        raise ApiError(404, "not_found", "unknown snapshot")


def me_temporal(user, q):
    now = S.now_key()
    as_text, as_key = query_instant(q, "as_of")
    kn_text, kn_key = query_instant(q, "known_at")
    T = as_key if as_key is not None else now
    K = min(kn_key, now) if kn_key is not None else now
    out = {"user_id": user["id"], "display_name": user["display_name"], "handle": user["handle"]}
    out.update(money_view(user["id"], T, K))
    out["currency"] = S.currency
    out["minor_units"] = S.minor_units
    if as_text is not None:
        out["as_of"] = as_text
    if kn_text is not None:
        out["known_at"] = kn_text
    return 200, out


def statement_window(uid, frm, to, cut):
    """The full window: (opening_balance, entries, closing_balance); entries are not yet paged."""
    opening = S.users[uid]["opening"]
    before_from = opening
    window = []
    for pid in S.by_user.get(uid, ()):
        r = selected(pid, cut)
        if r is None:
            continue
        eff = r[2]
        if to is not None and eff >= to:
            continue
        p = S.payments_by_id[pid]
        d = r[1] if p["to_user_id"] == uid else -r[1]
        if frm is not None and eff < frm:
            before_from += d
        else:
            window.append((eff, pid, r, d))
    window.sort(key=lambda e: (e[0], e[1]))
    start = before_from if frm is not None else opening
    run = start
    entries = []
    for eff, pid, r, d in window:
        run += d
        view = S.payment_view(S.payments_by_id[pid])
        view["amount"] = r[1]
        entries.append({"payment": view, "delta": d, "balance_after": run, "revision": r[0],
                        "effective_at": r[4], "recorded_at": r[5]})
    return start, entries, run


def statement(user, q):
    limit, offset = page_params(q)
    if "snapshot" in q:
        if any(k in q for k in ("from", "to", "known_at")):
            raise invalid("only limit and offset may accompany a snapshot")
        tok = q["snapshot"]
        frm, to, cut = read_token(user["id"], tok)
    else:
        now = S.tick()
        nk = micro_key(now)
        _, frm = query_instant(q, "from")
        _, to = query_instant(q, "to")
        _, kn = query_instant(q, "known_at")
        if to is None:
            to = nk
        if frm is not None and frm > to:
            raise invalid("from must not be later than to")
        cut = min(kn, nk) if kn is not None else nk
        tok = make_token(user["id"], frm, to, cut)
    opening, entries, closing = statement_window(user["id"], frm, to, cut)
    page = entries[offset:offset + limit]
    return 200, {"opening_balance": opening, "entries": page, "closing_balance": closing,
                 "has_more": offset + limit < len(entries), "snapshot": tok}


# ---- corrections

def check_correction_body(body):
    for f in ("expected_revision", "amount", "effective_at", "reason"):
        if f not in body:
            raise invalid("%s is required" % f)
    er, amount, eff, reason = body["expected_revision"], body["amount"], body["effective_at"], body["reason"]
    if not is_int(er) or er < 1:
        raise invalid("expected_revision must be a positive integer")
    if not is_int(amount) or not 0 <= amount <= MAX_AMOUNT:
        raise invalid("amount must be an integer from 0 to 1000000000")
    if not isinstance(reason, str) or not 1 <= len(reason) <= 200:
        raise invalid("reason must be 1 to 200 characters")
    try:
        ek = parse_instant(eff)
    except ValueError:
        raise invalid("effective_at must be an RFC 3339 instant with an offset")
    return er, amount, eff, ek, reason


def correct_payment(user, pid, body):
    er, amount, eff, ek, reason = check_correction_body(body)
    now_m = S.tick()
    if ek > micro_key(now_m):
        raise invalid("effective_at must not be later than now")
    p = S.payments_by_id.get(pid)
    if p is None:
        raise ApiError(404, "not_found", "no such payment")
    if p["from_user_id"] != user["id"]:
        raise ApiError(403, "forbidden", "only the sender may correct a payment")
    if p.get("settlement_id") or p.get("authorization_id"):
        raise ApiError(422, "linked_payment_immutable", "this payment is linked and cannot be corrected")
    info = S.pinfo[pid]
    latest = info["revs"][-1]
    if er != latest[0]:
        raise ApiError(409, "stale_revision", "the payment has a newer revision")
    diff = amount - latest[1]
    sender, receiver = S.users[p["from_user_id"]], S.users[p["to_user_id"]]
    if diff > 0 and S.available(sender) < diff:
        raise ApiError(409, "insufficient_funds", "insufficient funds")
    if diff < 0 and S.available(receiver) < -diff:
        raise ApiError(409, "insufficient_funds", "insufficient funds")
    rec_text = micro_iso(now_m)
    new = (latest[0] + 1, amount, ek, micro_key(now_m), eff, rec_text, reason)
    for u in (sender, receiver):
        if not ledger_ok(u["id"], (pid, new)):
            raise ApiError(409, "historical_overdraft", "the correction would overdraw a wallet at some point in time")
    sender["balance"] -= diff
    receiver["balance"] += diff
    p.setdefault("corrections", []).append({"revision": new[0], "amount": amount, "effective_at": eff,
                                            "recorded_at": rec_text, "reason": reason})
    info["revs"].append(new)
    return 201, {"payment_id": pid, "revision": new[0], "amount": amount, "effective_at": eff,
                 "recorded_at": rec_text, "reason": reason}


def list_revisions(user, pid):
    p = S.payments_by_id.get(pid)
    if p is None or user["id"] not in (p["from_user_id"], p["to_user_id"]):
        raise ApiError(404, "not_found", "no such payment")
    out = [{"payment_id": pid, "revision": r[0], "amount": r[1], "effective_at": r[4], "recorded_at": r[5], "reason": r[6]}
           for r in S.pinfo[pid]["revs"]]
    return 200, {"revisions": out}


def create_authorization(user, body):
    to_h = need_handle(body, "to_handle")
    if "amount" not in body:
        raise invalid("amount is required")
    amount = check_amount(body["amount"])
    note = check_note(body)
    vis = check_visibility(body)
    to = S.lookup_handle(to_h)
    if to["id"] == user["id"]:
        raise ApiError(422, "self_payment", "cannot authorize a payment to yourself")
    if S.available(user) < amount:
        raise ApiError(409, "insufficient_funds", "insufficient available funds")
    created_m = S.tick()
    aid = S.new_id("a", S.auths_by_id)
    rec = {"id": aid, "from_user_id": user["id"], "to_user_id": to["id"], "amount": amount,
           "captured_amount": 0, "note": note, "visibility": vis, "status": "open",
           "expires_at": micro_iso(created_m + S.ttl * 1000000), "payment_ids": [],
           "created_at": micro_iso(created_m), "closed_at": None, "tracked": True}
    S.auths.append(rec)
    S.auths_by_id[aid] = rec
    S.by_payer.setdefault(user["id"], []).append(aid)
    S.exp_key[aid] = parse_instant(rec["expires_at"])
    S.held[user["id"]] = S.held.get(user["id"], 0) + amount
    heapq.heappush(S.heap, (S.exp_key[aid], aid))
    return 201, S.auth_view(rec)


def capture_authorization(user, aid, body):
    final = True
    capture = None
    if "amount" in body:
        v = body["amount"]
        if isinstance(v, BigNum):
            if bignum_kind(v) != "huge":
                raise invalid("amount must be a positive integer")
            capture = "huge"
        elif isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise invalid("amount must be a positive integer")
        else:
            capture = v
    if "final" in body:
        if not isinstance(body["final"], bool):
            raise malformed("final must be a boolean")
        final = body["final"]
    S.sweep()
    a = S.auths_by_id.get(aid)
    if a is None:
        raise ApiError(404, "not_found", "no such authorization")
    if a["to_user_id"] != user["id"]:
        raise ApiError(403, "forbidden", "only the receiver may capture")
    if a["status"] == "expired":
        raise ApiError(409, "authorization_expired", "authorization expired")
    if a["status"] != "open":
        raise ApiError(409, "authorization_not_open", "authorization is not open")
    remaining = a["amount"] - a["captured_amount"]
    amount = remaining if capture is None else capture
    if amount == "huge" or amount > remaining:
        raise ApiError(422, "capture_exceeds_authorization", "amount exceeds the remaining hold")
    payer, payee = S.users[a["from_user_id"]], S.users[a["to_user_id"]]
    p = S.move(payer, payee, amount, a["note"], a["visibility"], authorization_id=a["id"])
    a["captured_amount"] += amount
    a["payment_ids"].append(p["id"])
    if final or a["captured_amount"] == a["amount"]:
        # the whole old remainder (captured part included) leaves the hold; the rest is released
        S.held[payer["id"]] = S.held.get(payer["id"], 0) - remaining
        if S.held[payer["id"]] == 0:
            del S.held[payer["id"]]
        a["status"] = "captured"
        a["closed_at"] = p["created_at"]
    else:
        S.held[payer["id"]] = S.held.get(payer["id"], 0) - amount
    return 201, S.payment_view(p)


def void_authorization(user, aid):
    a = S.auths_by_id.get(aid)
    if a is None:
        raise ApiError(404, "not_found", "no such authorization")
    if a["from_user_id"] != user["id"]:
        raise ApiError(403, "forbidden", "only the payer may void")
    if a["status"] == "open":
        S.release(a)
        a["status"] = "voided"
        a["closed_at"] = micro_iso(S.tick())
    elif a["status"] != "voided":
        raise ApiError(409, "authorization_not_open", "authorization is not open")
    return 200, S.auth_view(a)


def list_authorizations(user, q):
    direction = q.get("direction")
    if direction is not None and direction not in ("incoming", "outgoing"):
        raise invalid("bad direction")
    status = q.get("status")
    if status is not None and status not in AUTH_STATUSES:
        raise invalid("bad status")
    limit, offset = page_params(q)
    uid = user["id"]
    out, skipped, more = [], 0, False
    for a in reversed(S.auths):
        if direction == "outgoing":
            ok = a["from_user_id"] == uid
        elif direction == "incoming":
            ok = a["to_user_id"] == uid
        else:
            ok = a["from_user_id"] == uid or a["to_user_id"] == uid
        if not ok or (status is not None and a["status"] != status):
            continue
        if skipped < offset:
            skipped += 1
        elif len(out) < limit:
            out.append(S.auth_view(a))
        else:
            more = True
            break
    return 200, {"authorizations": out, "has_more": more}


# --------------------------------------------------------------------- UI

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
UI_TITLES = {"/": "Wallet", "/requests": "Requests", "/split": "Split a bill", "/signup": "Create account",
             "/login": "Sign in", "/authorizations": "Authorizations"}
ASSETS = {"/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/static/icon.svg": ("icon.svg", "image/svg+xml"),
          "/static/app.css": ("app.css", "text/css; charset=utf-8")}


class Raw:
    """A non-JSON response body (the UI shell and its assets)."""
    def __init__(self, ctype, data):
        self.ctype, self.data = ctype, data


def _load_ui():
    with open(os.path.join(UI_DIR, "index.html"), encoding="utf-8") as f:
        shell = f.read()
    pages = {p: Raw("text/html; charset=utf-8", shell.replace("{{TITLE}}", t).encode("utf-8"))
             for p, t in UI_TITLES.items()}
    assets = {}
    for p, (name, ctype) in ASSETS.items():
        with open(os.path.join(UI_DIR, name), "rb") as f:
            assets[p] = Raw(ctype, f.read())
    return pages, assets


UI_PAGES, UI_ASSETS = _load_ui()


def accepts_html(header):
    """True when one media range of the Accept header is exactly text/html with a q that is not 0."""
    for part in (header or "").split(","):
        bits = [b.strip() for b in part.split(";")]
        if bits[0].lower() != "text/html":
            continue
        q = 1.0
        for b in bits[1:]:
            if b.lower().startswith("q="):
                try:
                    q = float(b[2:])
                except ValueError:
                    q = 1.0
        if q > 0:
            return True
    return False


def ui_response(path, headers):
    """HTML for UI routes (shared routes only when the client asks for text/html), else None."""
    if path == "/favicon.ico":
        return 204, None
    if path in UI_ASSETS:
        return 200, UI_ASSETS[path]
    if path in UI_PAGES:
        if path in ("/requests", "/authorizations") and not accepts_html(headers.get("Accept")):
            return None
        return 200, UI_PAGES[path]
    return None


# ----------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "pocketful"

    def log_message(self, *a):
        pass

    def read_body(self):
        limit = MAX_BODY if self.path.startswith("/_test/") else MAX_API_BODY
        te = (self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in te:
            data = b""
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if size < 0 or size > limit or len(data) + size > limit:
                    raise malformed("body too large")
                if size == 0:
                    while self.rfile.readline().strip():
                        pass
                    break
                data += self.rfile.read(size)
                self.rfile.readline()
            return data
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise malformed("bad Content-Length")
        if n < 0 or n > limit:
            raise malformed("bad Content-Length")
        return self.rfile.read(n) if n else b""

    def send_json(self, status, obj=None):
        if isinstance(obj, Raw):
            self.send_response(status)
            self.send_header("Content-Type", obj.ctype)
            self.send_header("Content-Length", str(len(obj.data)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(obj.data)
            return
        if status == 204:
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def handle_any(self, method):
        close = False
        try:
            try:
                raw = self.read_body()
            except ApiError:
                close = True
                raise
            except (ValueError, OSError):
                close = True
                raise malformed("bad body framing")
            try:
                parts = urlsplit(self.path)
            except ValueError:
                raise malformed("bad request target")
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
            traceback.print_exc()
        if close:
            self.close_connection = True
        try:
            self.send_json(status, obj)
        except OSError:
            self.close_connection = True

    def __getattr__(self, name):
        # any HTTP method reaches handle_any, which answers with the JSON error body
        if name.startswith("do_"):
            return lambda: self.handle_any(name[3:])
        raise AttributeError(name)

    def send_error(self, code, message=None, explain=None):
        """Replace the built-in HTML error pages with the §5 JSON error body (never a 5xx)."""
        status = 400 if code >= 500 else code
        err = {400: "malformed_request", 404: "not_found"}.get(status, "malformed_request")
        data = dumps({"error": {"code": err, "message": message or "bad request"}}).encode("ascii")
        self.close_connection = True
        self.request_version = "HTTP/1.1"  # always answer with a status line and headers
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
        except OSError:
            pass

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
            if has_bignum(doc["state"]):
                raise invalid("state may only hold plain integers, strings, booleans, null, arrays and objects")
            state = validate_state(doc["state"])
            prove_state(state)
            with LOCK:
                S.load(state)
            return 204, None
        if path == "/auth/signup":
            self.need(method, "POST")
            return signup(raw)
        if path == "/auth/login":
            self.need(method, "POST")
            return login(raw)
        if method == "GET":
            ui = ui_response(path, H)
            if ui is not None:
                return ui
        known = {"/me": "GET", "/payments": "POST", "/requests": None, "/splits": "POST",
                 "/activity": "GET", "/settlements": "POST", "/authorizations": None, "/statement": "GET"}
        pay_like = len(segs) == 3 and segs[0] == "requests" and segs[2] in ("pay", "decline", "cancel")
        auth_like = len(segs) == 3 and segs[0] == "authorizations" and segs[2] in ("capture", "void")
        corr_like = len(segs) == 3 and segs[0] == "payments" and segs[2] in ("corrections", "revisions")
        if path not in known and not pay_like and not auth_like and not corr_like:
            raise ApiError(404, "not_found", "no such route")
        if corr_like:
            self.need(method, "POST" if segs[2] == "corrections" else "GET")
        elif path in known and known[path]:
            self.need(method, known[path])
        elif path in ("/requests", "/authorizations"):
            if method not in ("GET", "POST"):
                raise ApiError(405, "method_not_allowed", "method not allowed")
        elif method != "POST":
            raise ApiError(405, "method_not_allowed", "method not allowed")
        with LOCK:
            user = authenticate(H)
            if path == "/me":
                if "as_of" in q or "known_at" in q:
                    return me_temporal(user, q)
                return me(user)
            if path == "/statement":
                return statement(user, q)
            if corr_like:
                pid = segs[1]
                if segs[2] == "revisions":
                    return list_revisions(user, pid)
                return idempotent(user, method, "/payments/" + pid + "/corrections", H, raw,
                                  lambda b: correct_payment(user, pid, b))
            if path == "/activity":
                return activity(user, q)
            if path == "/requests" and method == "GET":
                return list_requests(user, q)
            if path == "/authorizations" and method == "GET":
                return list_authorizations(user, q)
            if path == "/authorizations":
                return idempotent(user, method, path, H, raw, lambda b: create_authorization(user, b))
            if auth_like:
                aid = segs[1]
                if segs[2] == "capture":
                    return idempotent(user, method, "/authorizations/" + aid + "/capture", H, raw,
                                      lambda b: capture_authorization(user, aid, b), allow_empty=True)
                return void_authorization(user, aid)
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
                return idempotent(user, method, "/requests/" + rid + "/pay", H, raw,
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

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError, BrokenPipeError)):
            return  # a client that resets, aborts or stalls a connection is not a service error
        print("unexpected error in connection thread:", repr(exc), flush=True)
        traceback.print_exc()
        sys.stdout.flush()
    request_queue_size = 512
    allow_reuse_address = True


def main():
    port = int(os.environ.get("PORT") or 8080)
    Server(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
