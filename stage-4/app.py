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
import time
import bisect
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

MAX_AMOUNT = 1_000_000_000
MAX_BALANCE = 2 ** 53
HANDLE_RE = re.compile(r"[a-z0-9_]{1,20}")
STATUSES = ("pending", "paid", "declined", "cancelled")
AUTH_STATUSES = ("open", "captured", "voided", "expired")
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 12, 8, 1
FIXTURE_SCRYPT_N = 2 ** 9  # seeded users: keep a 5000-user reset well inside 10 s
MAX_BODY = 8 * 1024 * 1024
MAX_TEST_BODY = 512 * 1024 * 1024  # reset/import bodies carry whole states (an export grows with history)
DISCARD_CAP = 1024 * 1024 * 1024   # an oversized body is read and thrown away up to here, then answered


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


_NUM_RE = re.compile(r"(-?)([0-9]*)(?:\.([0-9]*))?(?:[eE]([+-]?)([0-9]+))?")


def huge_class(text):
    """Classify a JSON number too large for Decimal by its value: zero, neg, frac or posint."""
    m = _NUM_RE.fullmatch(text)
    if not m:
        return "frac"
    sign, whole, frac, esign, edigits = m.groups()
    frac = frac or ""
    digits = (whole or "") + frac
    if not digits.strip("0"):
        return "zero"
    if sign:
        return "neg"
    exp = 0
    if edigits:
        exp = 10 ** 9 if len(edigits) > 9 else int(edigits)
        if esign == "-":
            exp = -exp
    exp -= len(frac)
    stripped = digits.rstrip("0")
    exp += len(digits) - len(stripped)  # trailing zeros of the mantissa are integral
    return "posint" if exp >= 0 else "frac"


def fx_int(v):
    """Integral number (1000, 1000.0, 1e3) -> int, else None."""
    if isinstance(v, Huge):
        return 0 if huge_class(v.text) == "zero" else None
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


EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_clock = {"last": 0}


def real_now_us():
    return time.time_ns() // 1000


def tick():
    """A server instant (integer microseconds), strictly increasing across the whole service."""
    n = real_now_us()
    v = n if n > _clock["last"] else _clock["last"] + 1
    _clock["last"] = v
    return v


def read_instant():
    """The instant a read begins: everything recorded so far is known. A read consumes its
    instant, so anything recorded afterwards is strictly later."""
    v = max(real_now_us(), _clock["last"])
    _clock["last"] = v
    return v


def us_to_str(us):
    return (EPOCH + timedelta(microseconds=us)).isoformat(timespec="microseconds")


_INSTANT_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})"
                         r"(?:\.([0-9]+))?([Zz]|[+-][0-9]{2}:[0-9]{2})")


def instant_us(s):
    """RFC 3339 instant with an offset -> integer microseconds since the epoch, else None."""
    if not isinstance(s, str):
        return None
    m = _INSTANT_RE.fullmatch(s)
    if not m:
        return None
    y, mo, d, h, mi, sec, frac, off = m.groups()
    try:
        if off in ("Z", "z"):
            tz = timezone.utc
        else:
            oh, om = int(off[1:3]), int(off[4:6])
            if oh > 23 or om > 59:
                return None
            tz = timezone((-1 if off[0] == "-" else 1) * timedelta(hours=oh, minutes=om))
        dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec), 0, tzinfo=tz)
    except ValueError:
        return None
    return (dt - EPOCH) // timedelta(microseconds=1) + int(((frac or "") + "000000")[:6])


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
        self.counters = {"p": 0, "rq": 0, "sp": 0, "st": 0, "u": 0, "a": 0, "cb": 0}
        # ledger (stage 3): revisions per payment, per-user indexes, cached timelines, snapshots
        self.revs = {}             # payment id -> [(n, amount, eff_us, rec_us, eff_str, rec_str, reason)]
        self.user_payments = {}    # user id -> [payment ids]
        self.pay_order = []        # (created_us, seq, payment id), ascending
        self.auths_by_payer = {}   # user id -> [authorization dicts]
        self.tl_ver = {}           # user id -> version, bumped when a payment of the user changes
        self.tl_cache = {}         # user id -> (version, timeline)
        self.snapshots = {}        # token -> {uid, from_us, to_us, k_us, known}
        self.max_us = 0
        self.pin_order = []        # timelines currently pinned by snapshots (bounded)
        self.refunded = {}         # payment id -> sum of its refunds
        self.batches = {}          # correction batch id -> True (ids seen in revisions)

    # -- ledger helpers
    def index_payment(self, p):
        pid = p["payment_id"]
        for uid in {p["from_user_id"], p["to_user_id"]}:
            self.user_payments.setdefault(uid, []).append(pid)
            self.tl_ver[uid] = self.tl_ver.get(uid, 0) + 1
        key = (p["created_us"], p["seq"], pid)
        if not self.pay_order or key >= self.pay_order[-1]:
            self.pay_order.append(key)
        else:
            bisect.insort(self.pay_order, key)

    def index_auth(self, a):
        self.auths_by_payer.setdefault(a["from_user_id"], []).append(a)

    # -- ids
    def new_id(self, kind, table):
        while True:
            self.counters[kind] += 1
            i = "%s_%010d" % (kind, self.counters[kind])  # fixed width: string order is creation order
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
            "payments": [{k: v for k, v in p.items() if k != "created_us"} for p in self.payments.values()],
            "requests": [dict(r) for r in self.requests.values()],
            "splits": copy.deepcopy(list(self.splits.values())),
            "settlements": copy.deepcopy(list(self.settlements.values())),
            "idempotency": [{"user_id": k[0], "key": k[1], "path": k[2], "body": v["body"],
                             "response": copy.deepcopy(v["response"])}
                            for k, v in self.idem.items()],
            "operators": list(self.operators),
            "counters": dict(self.counters),
            "authorizations": [dict(a, payment_ids=list(a["payment_ids"]),
                                    caps=[list(c) for c in a["caps"]],
                                    close=list(a["close"]) if a["close"] else None)
                               for a in self.authorizations.values()],
            "authorization_ttl_seconds": self.ttl,
            "revisions": {pid: [list(r) for r in rs] for pid, rs in self.revs.items()},
            "snapshots": [dict({a: b for a, b in v.items() if not a.startswith("_")}, token=k)
                          for k, v in self.snapshots.items()],
            "clock_us": _clock["last"],
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
            need("opening" not in u or is_int(u["opening"]))
            rec["opening"] = u.get("opening")
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
            need(p.get("refund_of") is None or is_str(p["refund_of"]))
            p = dict(p, authorization_id=p.get("authorization_id"), refund_of=p.get("refund_of"))
            need(isinstance(p["seq"], int) and p["payment_id"] not in s.payments)
            cu = instant_us(p["created_at"])
            need(cu is not None)
            p["created_us"] = cu
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
        need(isinstance(c, dict) and all(is_int(c.get(k, 0 if k in ("a", "cb") else None))
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
            cu, eu = instant_us(a["created_at"]), instant_us(a["expires_at"])
            need(cu is not None and eu is not None)
            rec = {k: a[k] for k in ("authorization_id", "from_user_id", "to_user_id", "amount",
                                     "captured_amount", "note", "visibility", "status",
                                     "expires_at", "created_at", "seq")}
            rec["payment_ids"] = list(a["payment_ids"])
            rec["created_us"], rec["expires_us"] = cu, eu
            if "caps" in a:
                caps, close = a["caps"], a.get("close")
                need(isinstance(caps, list) and all(isinstance(c, list) and len(c) == 2 and is_int(c[0])
                                                    and is_int(c[1]) and c[1] >= 1 for c in caps))
                need(close is None or (isinstance(close, list) and len(close) == 2 and is_int(close[0])
                                       and close[1] in ("void", "capture", "expire")))
                need(a.get("closed_at") is None or is_str(a["closed_at"]))
                need(isinstance(a.get("seeded_closed"), bool))
                need((rec["status"] == "open") == (a.get("closed_at") is None))
                need(rec["status"] != "open" or close is None)
                rec["caps"] = [list(c) for c in caps]
                rec["close"] = list(close) if close else None
                rec["closed_at"] = a.get("closed_at")
                rec["seeded_closed"] = a["seeded_closed"]
            else:
                # An older export: rebuild the lifecycle from what that state recorded.
                caps = []
                for pid in rec["payment_ids"]:
                    need(pid in s.payments)
                    caps.append([s.payments[pid]["created_us"], s.payments[pid]["amount"]])
                rec["caps"] = caps
                rec["seeded_closed"] = False
                last_t = caps[-1][0] if caps else cu
                if rec["status"] == "open":
                    rec["close"], rec["closed_at"] = None, None
                elif rec["status"] == "expired":
                    rec["close"], rec["closed_at"] = [eu, "expire"], rec["expires_at"]
                else:
                    kind = "capture" if rec["status"] == "captured" else "void"
                    rec["close"], rec["closed_at"] = [last_t, kind], us_to_str(last_t)
            s.authorizations[rec["authorization_id"]] = rec
            s.index_auth(rec)
            if rec["status"] == "open":
                s.open_auths[rec["authorization_id"]] = rec
        # ledger: revisions (an older export has none: revision 1 from created_at) and openings
        revs = d.get("revisions")
        need(revs is None or isinstance(revs, dict))
        max_us = [0]
        for pid, p in s.payments.items():
            if revs is None:
                rl = [(1, p["amount"], p["created_us"], p["created_us"], p["created_at"], p["created_at"], "", None)]
            else:
                raw = revs[pid]
                need(isinstance(raw, list) and raw)
                rl, last = [], None
                for i, r in enumerate(raw, start=1):
                    need(isinstance(r, list) and len(r) in (7, 8) and r[0] == i and is_int(r[1])
                         and 0 <= r[1] <= MAX_AMOUNT and is_str(r[4]) and is_str(r[5]) and is_str(r[6])
                         and len(r[6]) <= 200 and (i > 1 or r[6] == ""))
                    r = list(r) + [None] * (8 - len(r))   # stage-3 exports carry no batch ids
                    need(r[7] is None or (is_str(r[7]) and 0 < len(r[7]) <= 64 and i > 1))
                    if r[7] is not None:
                        s.batches[r[7]] = True
                    eu, ru = instant_us(r[4]), instant_us(r[5])
                    need(eu is not None and ru is not None and r[2] == eu and r[3] == ru)
                    need(last is None or ru > last)
                    last = ru
                    rl.append(tuple(r))
                need(rl[0][1] == p["amount"] and rl[0][2] == p["created_us"] and rl[0][3] == p["created_us"])
            max_us[0] = max(max_us[0], p["created_us"], rl[-1][3])
            s.revs[pid] = rl
            s.index_payment(p)
            if p["refund_of"] is not None:
                need(p["refund_of"] in s.payments and s.payments[p["refund_of"]]["refund_of"] is None
                     and p["settlement_id"] is None and p["authorization_id"] is None and p["request_id"] is None)
                s.refunded[p["refund_of"]] = s.refunded.get(p["refund_of"], 0) + p["amount"]
                need(s.payments[p["refund_of"]]["to_user_id"] == p["from_user_id"]
                     and s.payments[p["refund_of"]]["from_user_id"] == p["to_user_id"])
        net = {}
        for pid, p in s.payments.items():
            if p["from_user_id"] != p["to_user_id"]:
                amt = s.revs[pid][-1][1]
                net[p["from_user_id"]] = net.get(p["from_user_id"], 0) - amt
                net[p["to_user_id"]] = net.get(p["to_user_id"], 0) + amt
        for uid, u in s.users.items():
            if u["opening"] is None:
                u["opening"] = u["balance"] - net.get(uid, 0)
            else:
                need(u["opening"] + net.get(uid, 0) == u["balance"])
        for a in s.authorizations.values():
            max_us[0] = max([max_us[0], a["created_us"]] + [c[0] for c in a["caps"]]
                            + ([a["close"][0]] if a["close"] else []))
        for sn in d.get("snapshots", []):
            need(isinstance(sn, dict) and is_str(sn.get("token")) and 0 < len(sn["token"]) <= 64
                 and sn.get("uid") in s.users and (sn.get("from_us") is None or is_int(sn["from_us"]))
                 and is_int(sn.get("to_us")) and is_int(sn.get("k_us"))
                 and (sn.get("known") is None or is_str(sn["known"])))
            need(sn["token"] not in s.snapshots and (sn["from_us"] is None or sn["from_us"] <= sn["to_us"]))
            s.snapshots[sn["token"]] = {k: sn[k] for k in ("uid", "from_us", "to_us", "k_us", "known")}
        clk = d.get("clock_us", 0)
        need(is_int(clk))
        s.max_us = max(max_us[0], clk)
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
        base_us = tick()
        now_us = read_instant()
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
            if p.get("created_at") is None:
                cu, created = base_us, us_to_str(base_us)
            else:
                created = p["created_at"]
                cu = instant_us(created)
                need(cu is not None, "payment created_at must be an RFC 3339 instant with an offset")
                need(cu <= now_us, "payment created_at is in the future")
            s.counters["p"] += 1
            s.payments[pid] = {
                "payment_id": pid, "from_user_id": p["from_user_id"],
                "to_user_id": p["to_user_id"], "amount": amt, "note": note,
                "visibility": vis, "request_id": rid, "settlement_id": None,
                "authorization_id": None, "refund_of": None, "created_at": created, "created_us": cu,
                "seq": s.counters["p"]}
            s.revs[pid] = [(1, amt, cu, cu, created, created, "", None)]
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
            exp_us = instant_us(exp)
            need(exp_us is not None, "authorization expires_at must be an RFC 3339 instant with an offset")
            exp_dt = EPOCH + timedelta(microseconds=exp_us)
            cap = a.get("captured_amount")
            if cap is None:
                cap = amt if status == "captured" else 0
            else:
                cap = fx_int(cap)
                need(is_int(cap) and 0 <= cap <= amt, "authorization captured_amount")
            pid = a.get("payment_id")
            need(pid is None or isinstance(pid, str), "authorization payment_id")
            if a.get("created_at") is None:
                created_us = base_us + i
                created = us_to_str(created_us)
            else:
                created = a["created_at"]
                created_us = instant_us(created)
                need(created_us is not None, "authorization created_at must be an RFC 3339 instant with an offset")
            if status == "open" and exp_dt <= now:
                status = "expired"
            s.counters["a"] += 1
            closed_at = a.get("closed_at")
            need(closed_at is None or (isinstance(closed_at, str) and instant_us(closed_at) is not None),
                 "authorization closed_at")
            if status == "open":
                closed_at = None
            elif closed_at is None:
                closed_at = exp if status == "expired" else created
            rec = {"authorization_id": aid, "from_user_id": a["from_user_id"],
                   "to_user_id": a["to_user_id"], "amount": amt, "captured_amount": cap,
                   "note": note, "visibility": vis, "status": status, "expires_at": exp,
                   "payment_ids": [pid] if pid else [], "created_at": created,
                   "seq": s.counters["a"], "created_us": created_us, "expires_us": exp_us,
                   "caps": [[created_us, cap]] if (cap and status == "open") else [],
                   "close": None, "closed_at": closed_at, "seeded_closed": status != "open"}
            s.authorizations[aid] = rec
            s.index_auth(rec)
            if status == "open":
                s.open_auths[aid] = rec
        net = {}
        for pid, p in s.payments.items():
            s.index_payment(p)
            if p["from_user_id"] != p["to_user_id"]:
                net[p["from_user_id"]] = net.get(p["from_user_id"], 0) - p["amount"]
                net[p["to_user_id"]] = net.get(p["to_user_id"], 0) + p["amount"]
        for uid, u in s.users.items():
            u["opening"] = u["balance"] - net.get(uid, 0)
        s.max_us = max([base_us + len(auths)] + [p["created_us"] for p in s.payments.values()])
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
        "refund_of": p.get("refund_of"),
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


def move(sender, receiver, amount, note, visibility, request_id, settlement_id, created_us,
         authorization_id=None, refund_of=None):
    """One payment: debit, credit, revision 1 at its instant. `created_us` comes from tick()."""
    st = STATE
    sender["balance"] -= amount
    receiver["balance"] += amount
    pid = st.new_id("p", st.payments)
    created = us_to_str(created_us)
    p = {"payment_id": pid, "from_user_id": sender["id"], "to_user_id": receiver["id"],
         "amount": amount, "note": note, "visibility": visibility, "request_id": request_id,
         "settlement_id": settlement_id, "authorization_id": authorization_id,
         "refund_of": refund_of, "created_at": created, "created_us": created_us, "seq": next_seq()}
    st.payments[pid] = p
    st.revs[pid] = [(1, amount, created_us, created_us, created, created, "", None)]
    st.index_payment(p)
    return p


def sweep():
    """Close open authorizations whose deadline has passed (called on every request)."""
    st = STATE
    if not st.open_auths:
        return
    now = real_now_us()
    for aid in [k for k, a in st.open_auths.items() if a["expires_us"] <= now]:
        a = st.open_auths.pop(aid)
        a["status"] = "expired"
        a["close"] = [a["expires_us"], "expire"]
        a["closed_at"] = a["expires_at"]


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
        "closed_at": a["closed_at"],
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
    p = move(user, to, amount, note, vis, None, None, tick())
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
    t = tick()
    exp = t + st.ttl * 1_000_000
    a = {"authorization_id": aid, "from_user_id": user["id"], "to_user_id": to["id"],
         "amount": amount, "captured_amount": 0, "note": note, "visibility": vis,
         "status": "open", "expires_at": us_to_str(exp), "payment_ids": [],
         "created_at": us_to_str(t), "seq": next_seq(), "created_us": t, "expires_us": exp,
         "caps": [], "close": None, "closed_at": None, "seeded_closed": False}
    st.authorizations[aid] = a
    st.index_auth(a)
    st.open_auths[aid] = a
    return authorization_view(a)


def capture_amount(v):
    """A capture is an integer >= 1; exceeding the remainder (any size) is a different error."""
    n = None
    if is_int(v):
        n = v
    elif isinstance(v, Decimal) and v.is_finite() and v == v.to_integral_value():
        n = int(v) if v.adjusted() <= 30 else (10 ** 31 if v > 0 else None)
    elif isinstance(v, Huge):
        n = 10 ** 31 if huge_class(v.text) == "posint" else None
    if n is None or n < 1:
        raise err(422, "validation_failed", "amount must be an integer of at least 1")
    return n


def make_capture(aid):
    def do_capture(user, body):
        a = STATE.authorizations.get(aid)
        if a is None:
            raise err(404, "not_found", "no such authorization")
        if a["to_user_id"] != user["id"]:
            raise err(403, "forbidden", "only the receiver may capture")
        if "final" in body and not isinstance(body["final"], bool):
            raise err(400, "malformed_request", "final must be a boolean")
        amount = capture_amount(body["amount"]) if "amount" in body else None
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
        t = tick()
        p = move(payer, receiver, amount, a["note"], a["visibility"], None, None, t, aid)
        a["captured_amount"] += amount
        a["payment_ids"].append(p["payment_id"])
        a["caps"].append([t, amount])
        if body.get("final", True) or a["captured_amount"] >= a["amount"]:
            a["status"] = "captured"
            a["close"] = [t, "capture"]
            a["closed_at"] = p["created_at"]
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
    t = tick()
    a["status"] = "voided"
    a["close"] = [t, "void"]
    a["closed_at"] = us_to_str(t)
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
                 r["request_id"], None, tick())
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
    t_us = tick()
    committed = us_to_str(t_us)
    payments = [payment_view(move(s, r, a, n, v, None, sid, t_us))
                for s, r, a, n, v in parsed]
    resp = {"settlement_id": sid, "committed_at": committed, "payments": payments}
    st.settlements[sid] = {"settlement_id": sid, "response": resp}
    return resp



# -- ledger: historical views, statements, corrections (stage 3)

def parse_query(qs):
    """Percent-decoding only: a literal '+' (as in a +02:00 offset) stays a '+'."""
    out = {}
    for part in qs.split("&"):
        if not part:
            continue
        k, _, v = part.partition("=")
        out.setdefault(unquote(k.replace("+", " ")), []).append(unquote(v))
    return out


def query_instant(query, name):
    """None when absent; (text, microseconds) when valid; 422 when present but not an instant."""
    if name not in query:
        return None
    text = query[name][0]
    us = instant_us(text)
    if us is None:
        raise err(422, "validation_failed", "%s must be an RFC 3339 instant with an offset" % name)
    return text, us


def timeline_for(uid, k_us):
    """The caller's money movements under the revisions recorded at or before k_us, ordered by
    effective time then payment id, with the balance after each. Cached while nothing changed."""
    st = STATE
    full = k_us >= _clock["last"]
    ver = st.tl_ver.get(uid, 0)
    if full:
        hit = st.tl_cache.get(uid)
        if hit is not None and hit[0] == ver:
            return hit[1]
    entries = []
    for pid in st.user_payments.get(uid, ()):
        revs = st.revs[pid]
        r = revs[-1] if full else next((x for x in reversed(revs) if x[3] <= k_us), None)
        if r is None:
            continue
        p = st.payments[pid]
        if p["from_user_id"] == p["to_user_id"]:
            delta = 0
        else:
            delta = -r[1] if p["from_user_id"] == uid else r[1]
        entries.append((r[2], pid, delta, r))
    entries.sort(key=lambda e: (e[0], e[1]))
    opening = st.users[uid]["opening"]
    after, run = [], opening
    for e in entries:
        run += e[2]
        after.append(run)
    tl = {"effs": [e[0] for e in entries], "entries": entries, "after": after, "opening": opening}
    if full:
        st.tl_cache[uid] = (ver, tl)
    return tl


def balance_at(tl, t_us):
    i = bisect.bisect_right(tl["effs"], t_us)
    return tl["after"][i - 1] if i else tl["opening"]


def hold_at(a, t_us, k_us):
    """What authorization `a` holds at instant t_us as known at k_us."""
    if a["seeded_closed"] or k_us < a["created_us"] or t_us < a["created_us"]:
        return 0
    lim = min(t_us, k_us)
    if a["close"] is not None and a["close"][1] != "expire" and a["close"][0] <= lim:
        return 0
    if t_us >= a["expires_us"]:
        return 0  # once creation is known, so is the deadline
    return a["amount"] - sum(c[1] for c in a["caps"] if c[0] <= lim)


def held_at(uid, t_us, k_us):
    return sum(hold_at(a, t_us, k_us) for a in STATE.auths_by_payer.get(uid, ()))


def hold_deltas(a, now_us):
    """Changes of held money caused by authorization `a`, as (instant, delta), all <= now."""
    if a["seeded_closed"]:
        return []
    out = [(a["created_us"], a["amount"])]
    cap = 0
    for t, amt in a["caps"]:
        cap += amt
        out.append((t, -amt))
    if a["close"] is not None:
        t, kind = a["close"]
        if kind != "expire" or t <= now_us:
            rel = a["amount"] - cap
            if rel > 0:
                out.append((t, -rel))
    elif a["expires_us"] <= now_us:
        out.append((a["expires_us"], -(a["amount"] - cap)))
    return out


def me_temporal(user, query, base):
    as_of = query_instant(query, "as_of")
    known = query_instant(query, "known_at")
    if as_of is None and known is None:
        return base
    read = read_instant()
    t_us = as_of[1] if as_of else read
    k_us = min(known[1], read) if known else read
    uid = user["id"]
    total = balance_at(timeline_for(uid, k_us), t_us)
    held = held_at(uid, t_us, k_us)
    out = dict(base, balance=total, total=total, available=total - held, held=held)
    if as_of:
        out["as_of"] = as_of[0]
    if known:
        out["known_at"] = known[0]
    return out


def statement_entry(tl, idx, uid):
    t, pid, delta, r = tl["entries"][idx]
    pv = payment_view(STATE.payments[pid])
    pv["amount"] = r[1]
    return {"payment": pv, "delta": delta, "balance_after": tl["after"][idx],
            "revision": r[0], "effective_at": r[4], "recorded_at": r[5]}


MAX_PINNED = 24


def pin_timeline(token, snap, tl):
    """Snapshots reuse one frozen timeline object per version; only a bounded number of distinct
    timelines stay pinned, the rest are rebuilt from the append-only log on demand."""
    st = STATE
    toks = tl.setdefault("tokens", set())
    if not toks:
        st.pin_order.append(tl)
        while len(st.pin_order) > MAX_PINNED:
            old = st.pin_order.pop(0)
            for t in old.pop("tokens", ()):
                sn = st.snapshots.get(t)
                if sn is not None:
                    sn.pop("_tl", None)
    toks.add(token)
    snap["_tl"] = tl


def statement_page(token, snap, limit, offset):
    tl = snap.get("_tl")
    if tl is None:  # frozen view, rebuilt from the append-only log (e.g. after an import)
        tl = timeline_for(snap["uid"], snap["k_us"])
        pin_timeline(token, snap, tl)
    i0 = 0 if snap["from_us"] is None else bisect.bisect_left(tl["effs"], snap["from_us"])
    i1 = bisect.bisect_left(tl["effs"], snap["to_us"])
    i1 = max(i0, i1)
    opening = tl["after"][i0 - 1] if i0 else tl["opening"]
    closing = tl["after"][i1 - 1] if i1 else tl["opening"]
    lo = i0 + offset
    hi = min(i1, lo + limit)
    entries = [statement_entry(tl, i, snap["uid"]) for i in range(lo, hi)] if lo < i1 else []
    out = {"opening_balance": opening, "entries": entries, "closing_balance": closing,
           "has_more": lo + limit < i1, "snapshot": token}
    if snap["known"] is not None:
        out["known_at"] = snap["known"]
    return out


def get_statement(user, query):
    st = STATE
    snap_tok = query["snapshot"][0] if "snapshot" in query else None
    if snap_tok is not None and any(k in query for k in ("from", "to", "known_at")):
        raise err(422, "validation_failed", "only limit and offset may accompany a snapshot")
    limit, offset = parse_page(query)
    if snap_tok is not None:
        snap = st.snapshots.get(snap_tok)
        if snap is None or snap["uid"] != user["id"]:
            raise err(404, "not_found", "no such snapshot")
        return statement_page(snap_tok, snap, limit, offset)
    frm, to, known = query_instant(query, "from"), query_instant(query, "to"), query_instant(query, "known_at")
    if frm is not None and to is not None and frm[1] > to[1]:
        raise err(422, "validation_failed", "from must not be later than to")
    read = read_instant()
    snap = {"uid": user["id"], "from_us": frm[1] if frm else None,
            "to_us": to[1] if to else read + 1,
            "k_us": min(known[1], read) if known else read, "known": known[0] if known else None}
    token = secrets.token_urlsafe(16)
    st.snapshots[token] = snap
    pin_timeline(token, snap, timeline_for(snap["uid"], snap["k_us"]))
    return statement_page(token, snap, limit, offset)


def revision_view(pid, r):
    return {"payment_id": pid, "revision": r[0], "amount": r[1], "effective_at": r[4],
            "recorded_at": r[5], "reason": r[6], "correction_batch_id": r[7]}


def list_revisions(user, pid):
    st = STATE
    p = st.payments.get(pid)
    if p is None or user["id"] not in (p["from_user_id"], p["to_user_id"]):
        raise err(404, "not_found", "no such payment")
    return {"revisions": [revision_view(pid, r) for r in st.revs[pid]]}


def int_value(v):
    """An integral JSON number (any spelling) as an int, else None."""
    if is_int(v):
        return v
    if isinstance(v, Decimal) and v.is_finite() and v.adjusted() <= 30 and v == v.to_integral_value():
        return int(v)
    if isinstance(v, Huge):
        return 0 if huge_class(v.text) == "zero" else None
    return None


def would_overdraw(overrides, uids):
    """After the proposed revisions (overrides: payment id -> (amount, effective instant)), does
    any wallet in `uids` go negative (total or available) at an effective-time or hold-event
    boundary? Boundaries before every changed instant are untouched and not examined."""
    st = STATE
    now = read_instant()
    for uid in uids:
        lo = None
        for q in st.user_payments.get(uid, ()):
            if q in overrides:
                old = st.revs[q][-1]
                m = min(old[2], overrides[q][1])
                lo = m if lo is None else min(lo, m)
        if lo is None:
            continue
        ev = {}
        for q in st.user_payments.get(uid, ()):
            p = st.payments[q]
            if p["from_user_id"] == p["to_user_id"]:
                continue
            r = st.revs[q][-1]
            amt, eff = overrides[q] if q in overrides else (r[1], r[2])
            ev[eff] = ev.get(eff, 0) + (-amt if p["from_user_id"] == uid else amt)
        hv = {}
        for a in st.auths_by_payer.get(uid, ()):
            for t, d in hold_deltas(a, now):
                hv[t] = hv.get(t, 0) + d
        total, held = st.users[uid]["opening"], 0
        for t in sorted(set(ev) | set(hv)):
            total += ev.get(t, 0)
            held += hv.get(t, 0)
            if t >= lo and (total < 0 or total - held < 0):
                return True
    return False


def correction_fields(item):
    """Validate the ordinary correction fields of a dict; returns (expected, amount, text, us, reason)."""
    exp_rev = int_value(item.get("expected_revision"))
    amount = int_value(item.get("amount"))
    reason = item.get("reason")
    eff_text = item.get("effective_at")
    eff_us = instant_us(eff_text)
    if exp_rev is None or exp_rev < 1:
        raise err(422, "validation_failed", "expected_revision must be a positive integer")
    if amount is None or not 0 <= amount <= MAX_AMOUNT:
        raise err(422, "validation_failed", "amount must be an integer from 0 to 1000000000")
    if not isinstance(reason, str) or not 1 <= len(reason) <= 200:
        raise err(422, "validation_failed", "reason must be a string of 1 to 200 characters")
    if eff_us is None or eff_us > read_instant():
        raise err(422, "validation_failed", "effective_at must be an RFC 3339 instant, not later than now")
    return exp_rev, amount, eff_text, eff_us, reason


def immutable_payment(p):
    """Captures and refund payments can never be corrected."""
    return p["authorization_id"] is not None or p.get("refund_of") is not None


def check_item_state(pid, p, exp_rev, amount):
    """stale_revision, then refund_exceeds_payment (a correction cannot go below what was refunded)."""
    latest = STATE.revs[pid][-1]
    if exp_rev != latest[0]:
        raise err(409, "stale_revision", "the payment has a newer revision")
    if amount < STATE.refunded.get(pid, 0):
        raise err(422, "refund_exceeds_payment", "the payment has already been refunded for more than that")
    return latest


def apply_revision(pid, latest, amount, eff_us, eff_text, reason, rec, batch_id):
    st = STATE
    p = st.payments[pid]
    rev = (latest[0] + 1, amount, eff_us, rec, eff_text, us_to_str(rec), reason, batch_id)
    st.revs[pid].append(rev)
    diff = amount - latest[1]
    st.users[p["from_user_id"]]["balance"] -= diff
    st.users[p["to_user_id"]]["balance"] += diff
    for uid in {p["from_user_id"], p["to_user_id"]}:
        st.tl_ver[uid] = st.tl_ver.get(uid, 0) + 1
    return rev


def make_correction(pid):
    def do_correction(user, body):
        st = STATE
        p = st.payments.get(pid)
        if p is None:
            raise err(404, "not_found", "no such payment")
        if p["from_user_id"] != user["id"]:
            raise err(403, "forbidden", "only the original sender may correct a payment")
        if p["settlement_id"] is not None or immutable_payment(p):
            raise err(422, "linked_payment_immutable", "settlement members, captures and refunds cannot be corrected here")
        exp_rev, amount, eff_text, eff_us, reason = correction_fields(body)
        latest = check_item_state(pid, p, exp_rev, amount)
        diff = amount - latest[1]
        sender, receiver = st.users[p["from_user_id"]], st.users[p["to_user_id"]]
        if diff > 0 and available_of(sender) < diff:
            raise err(409, "insufficient_funds", "insufficient funds")
        if diff < 0 and available_of(receiver) < -diff:
            raise err(409, "insufficient_funds", "insufficient funds")
        if sender["id"] != receiver["id"] and would_overdraw({pid: (amount, eff_us)}, (sender["id"], receiver["id"])):
            raise err(409, "historical_overdraft", "the correction would overdraw a wallet in the past")
        rev = apply_revision(pid, latest, amount, eff_us, eff_text, reason, tick(), None)
        return revision_view(pid, rev)
    return do_correction


def make_refund(pid):
    def do_refund(user, body):
        st = STATE
        p = st.payments.get(pid)
        if p is None:
            raise err(404, "not_found", "no such payment")
        if p["to_user_id"] != user["id"]:
            raise err(403, "forbidden", "only the original receiver may refund a payment")
        if p.get("refund_of") is not None:
            raise err(422, "invalid_refund_target", "a refund cannot be refunded")
        amount = to_amount(body.get("amount"))
        remainder = st.revs[pid][-1][1] - st.refunded.get(pid, 0)
        if amount > remainder:
            raise err(422, "refund_exceeds_payment", "refunds would exceed the payment")
        if available_of(user) < amount:
            raise err(409, "insufficient_funds", "insufficient funds")
        receiver = st.users[p["from_user_id"]]
        r = move(user, receiver, amount, p["note"], p["visibility"], None, None, tick(), None, pid)
        st.refunded[pid] = st.refunded.get(pid, 0) + amount
        return payment_view(r)
    return do_refund


def do_batch(user, body):
    st = STATE
    if user["id"] not in st.operators:
        raise err(403, "forbidden", "operators only")
    items = body.get("corrections")
    if not isinstance(items, list) or not 1 <= len(items) <= 32 or not all(isinstance(i, dict) for i in items):
        raise err(422, "validation_failed", "corrections must be a list of 1 to 32 objects")
    ids = [i.get("payment_id") for i in items if isinstance(i.get("payment_id"), str)]
    if len(set(ids)) != len(ids):
        raise err(422, "validation_failed", "payment_ids must be distinct")
    planned = []   # (pid, latest, amount, eff_us, eff_text, reason)
    for item in items:
        pid = item.get("payment_id")
        if not isinstance(pid, str):
            raise err(422, "validation_failed", "payment_id must be a string")
        fields = correction_fields(item)
        p = st.payments.get(pid)
        if p is None:
            raise err(404, "not_found", "no such payment")
        if immutable_payment(p):
            raise err(422, "linked_payment_immutable", "captures and refunds cannot be corrected")
        exp_rev, amount, eff_text, eff_us, reason = fields
        latest = check_item_state(pid, p, exp_rev, amount)
        planned.append((pid, latest, amount, eff_us, eff_text, reason))
    # settlement completeness, then identical effective instants within a settlement
    in_batch = {pl[0]: pl for pl in planned}
    by_settlement = {}
    for pid, *_ in planned:
        sid = st.payments[pid]["settlement_id"]
        if sid is not None:
            by_settlement.setdefault(sid, []).append(pid)
    for sid, got in by_settlement.items():
        members = [q["payment_id"] for q in st.settlements[sid]["response"]["payments"]]
        if any(m not in in_batch for m in members):
            raise err(422, "incomplete_settlement", "every member of a settlement must be corrected together")
    for sid, got in by_settlement.items():
        if len({in_batch[g][3] for g in got}) > 1:
            raise err(422, "validation_failed", "members of one settlement need the same effective instant")
    # combined current affordability
    delta = {}
    for pid, latest, amount, eff_us, _, _ in planned:
        p = st.payments[pid]
        if p["from_user_id"] == p["to_user_id"]:
            continue
        diff = amount - latest[1]
        delta[p["from_user_id"]] = delta.get(p["from_user_id"], 0) - diff
        delta[p["to_user_id"]] = delta.get(p["to_user_id"], 0) + diff
    for uid, d in delta.items():
        if d < 0 and available_of(st.users[uid]) + d < 0:
            raise err(409, "insufficient_funds", "insufficient funds")
    overrides = {pid: (amount, eff_us) for pid, _, amount, eff_us, _, _ in planned}
    if would_overdraw(overrides, sorted(delta)):
        raise err(409, "historical_overdraft", "the corrections would overdraw a wallet in the past")
    rec = tick()
    bid = st.new_id("cb", st.batches)
    st.batches[bid] = True
    revs = [revision_view(pid, apply_revision(pid, latest, amount, eff_us, eff_text, reason, rec, bid))
            for pid, latest, amount, eff_us, eff_text, reason in planned]
    return {"correction_batch_id": bid, "recorded_at": us_to_str(rec), "revisions": revs}


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
    st = STATE
    out, skipped, more = [], 0, False
    for _, _, pid in reversed(st.pay_order):
        p = st.payments[pid]
        if p["visibility"] != "public" and uid not in (p["from_user_id"], p["to_user_id"]):
            continue
        if skipped < offset:
            skipped += 1
        elif len(out) < limit:
            out.append(p)
        else:
            more = True
            break
    return {"payments": [payment_view(p) for p in out], "has_more": more}


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
           "password_hash": pwh, "opening": 0}
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
PAY_PATH = re.compile(r"/payments/([^/]+)/(corrections|revisions|refunds)")
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
        if close or self.close_connection:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if data and self.command != "HEAD":
            self.wfile.write(data)

    def _body_limit(self):
        return MAX_TEST_BODY if self.path.startswith("/_test/") else MAX_BODY

    def _discard(self, n):
        """Read and drop up to n bytes so the client can still receive our answer."""
        left = min(n, DISCARD_CAP)
        while left > 0:
            got = self.rfile.read(min(left, 1 << 20))
            if not got:
                break
            left -= len(got)

    def _too_large(self):
        self.close_connection = True
        return err(413, "payload_too_large", "the request body is too large")

    def _read_body(self):
        limit = self._body_limit()
        te = self.headers.get("Transfer-Encoding", "")
        if "chunked" in te.lower():
            chunks, total, over = [], 0, False
            while True:
                line = self.rfile.readline(1024)
                size = int(line.split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline(1024).strip():
                        pass
                    break
                total += size
                if total > DISCARD_CAP:
                    raise self._too_large()
                if over or total > limit:
                    over = True
                    self._discard(size)
                else:
                    chunks.append(self.rfile.read(size))
                self.rfile.readline(8)
            if over:
                raise self._too_large()
            return b"".join(chunks)
        n = self.headers.get("Content-Length")
        if not n:
            return b""
        n = int(n)
        if n < 0:
            self.close_connection = True
            raise err(400, "malformed_request", "bad content length")
        if n > limit:
            self._discard(n)
            raise self._too_large()
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
        query = parse_query(parts.query)
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
        pm = PAY_PATH.fullmatch(path)
        known = (method, path) in {("GET", "/me"), ("GET", "/activity"), ("GET", "/requests"),
                                   ("GET", "/statement"),
                                   ("GET", "/authorizations"), ("POST", "/authorizations"),
                                   ("POST", "/payments"), ("POST", "/requests"),
                                   ("POST", "/splits"), ("POST", "/settlements"),
                                   ("POST", "/correction-batches")}
        pay_ok = bool(pm) and ((method == "POST" and pm.group(2) in ("corrections", "refunds"))
                               or (method == "GET" and pm.group(2) == "revisions"))
        if not known and not ((m or am) and method == "POST") and not pay_ok:
            raise err(404, "not_found", "no such route")

        if method == "GET":
            with LOCK:
                user = authenticate(h)
                if path == "/me":
                    st = STATE
                    held = held_of(user["id"])
                    return 200, me_temporal(user, query, {
                        "user_id": user["id"], "display_name": user["display_name"],
                        "handle": user["handle"], "balance": user["balance"],
                        "total": user["balance"], "available": user["balance"] - held,
                        "held": held, "currency": st.currency, "minor_units": st.minor_units})
                if path == "/statement":
                    return 200, get_statement(user, query)
                if pm:
                    return 200, list_revisions(user, pm.group(1))
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
            elif pm:
                handler = (make_refund if pm.group(2) == "refunds" else make_correction)(pm.group(1))
            else:
                handler = {"/payments": do_payment, "/requests": do_request,
                           "/splits": do_split, "/settlements": do_settlement,
                           "/authorizations": do_authorization, "/correction-batches": do_batch}[path]
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
            _clock["last"] = max(_clock["last"], new.max_us)
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
            _clock["last"] = max(_clock["last"], new.max_us)
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
