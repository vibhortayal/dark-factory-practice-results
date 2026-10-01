"""Domain logic and state for Pocketful.

All state lives in one dict (`self.state`, plain JSON-able data) guarded by a
single lock. Every write happens inside `with self.lock`, which is the one
serialisation point: balances, request state, idempotency records and export
snapshots are therefore trivially consistent.
"""
import copy
import hashlib
import hmac
import json
import math
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .validation import (HANDLE_RE, EMAIL_RE, STATUSES, ApiError, amount_of,
                         handle_field, int_param, invalid, malformed,
                         note_of, text_field, to_int, visibility_of)
from .validation import BigNumber

SCRYPT_N = 2 ** 11
SCRYPT_R = 8
SCRYPT_P = 1
TRACK = "pocketful"
FORMAT_VERSION = 1
MAX_SAFE = 2 ** 53
HANDLE_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def hash_password(password, salt=None):
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt,
                            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return {"alg": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P,
            "salt": salt.hex(), "hash": digest.hex()}


def verify_password(password, record):
    try:
        digest = hashlib.scrypt(password.encode("utf-8", "surrogatepass"),
                                salt=bytes.fromhex(record["salt"]),
                                n=record["n"], r=record["r"], p=record["p"], dklen=32)
    except Exception:
        return False
    return hmac.compare_digest(digest.hex(), record["hash"])


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds")


def parse_ts(value, fallback):
    """Timestamp from a fixture/imported string, normalised to (epoch, iso)."""
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp(), dt.isoformat()
        except ValueError:
            pass
    return fallback, iso(fallback)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def fixture_error(msg):
    return invalid("fixture: " + msg)


def build_state_from_fixture(fx):
    """Validate a reset fixture and build a fresh state dict (pure, no locking)."""
    if not isinstance(fx, dict):
        raise malformed("fixture must be a JSON object")
    currency = fx.get("currency", "EUR")
    minor_units = fx.get("minor_units", 2)
    if not isinstance(currency, str) or not currency:
        raise fixture_error("currency must be a string")
    if not is_int(minor_units) or minor_units not in (0, 2, 3):
        raise fixture_error("minor_units must be 0, 2 or 3")
    users_in = fx.get("users", [])
    payments_in = fx.get("payments", [])
    requests_in = fx.get("requests", [])
    ops_in = fx.get("settlement_operator_ids", [])
    for name, val in (("users", users_in), ("payments", payments_in),
                      ("requests", requests_in), ("settlement_operator_ids", ops_in)):
        if not isinstance(val, list):
            raise fixture_error(name + " must be an array")
    now = time.time()
    users, handles, emails = {}, set(), set()
    total = 0
    for u in users_in:
        if not isinstance(u, dict):
            raise fixture_error("user must be an object")
        for f in ("id", "email", "password", "display_name", "handle"):
            if not isinstance(u.get(f), str):
                raise fixture_error("user " + f + " must be a string")
        if not u["id"] or len(u["id"]) > 64:
            raise fixture_error("bad user id")
        if not HANDLE_RE.fullmatch(u["handle"]):
            raise fixture_error("bad handle")
        bal = to_int(u.get("balance", 0))
        if bal is None:
            raise fixture_error("balance must be an integer")
        if bal < 0:
            raise fixture_error("balance must not be negative")
        if bal > MAX_SAFE:
            raise fixture_error("balance beyond 2^53")
        email = u["email"].lower()
        if u["id"] in users or u["handle"] in handles or email in emails:
            raise fixture_error("duplicate user id, handle or email")
        handles.add(u["handle"])
        emails.add(email)
        total += bal
        users[u["id"]] = {"id": u["id"], "email": u["email"],
                          "display_name": u["display_name"], "handle": u["handle"],
                          "balance": bal, "pw": u["password"]}
    ops = []
    for o in ops_in:
        if not isinstance(o, str):
            raise fixture_error("operator id must be a string")
        if o not in ops:
            ops.append(o)
    state = new_state(currency, minor_units, total)
    state["users"] = users
    state["operators"] = ops
    ids = set()
    for p in payments_in:
        if not isinstance(p, dict):
            raise fixture_error("payment must be an object")
        pid = p.get("id")
        if not isinstance(pid, str) or not pid or len(pid) > 64 or pid in ids:
            raise fixture_error("bad payment id")
        ids.add(pid)
        if p.get("from_user_id") not in users or p.get("to_user_id") not in users:
            raise fixture_error("payment references an unknown user")
        amount = to_int(p.get("amount"))
        if amount is None or not 0 <= amount <= MAX_SAFE:
            raise fixture_error("payment amount")
        note = p.get("note", "")
        vis = p.get("visibility", "public")
        if not isinstance(note, str) or vis not in ("public", "private"):
            raise fixture_error("payment note/visibility")
        ts, created = parse_ts(p.get("created_at"), now)
        state["seq"] += 1
        state["payments"].append({
            "id": pid, "from": p["from_user_id"], "to": p["to_user_id"],
            "amount": amount, "note": note, "visibility": vis,
            "request_id": p.get("request_id") if isinstance(p.get("request_id"), str) else None,
            "settlement_id": None, "created_at": created, "ts": ts, "seq": state["seq"]})
    ids = set()
    for r in requests_in:
        if not isinstance(r, dict):
            raise fixture_error("request must be an object")
        rid = r.get("id")
        if not isinstance(rid, str) or not rid or len(rid) > 64 or rid in ids:
            raise fixture_error("bad request id")
        ids.add(rid)
        if r.get("requester_id") not in users or r.get("payer_id") not in users:
            raise fixture_error("request references an unknown user")
        amount = to_int(r.get("amount"))
        if amount is None or not 0 <= amount <= MAX_SAFE:
            raise fixture_error("request amount")
        note = r.get("note", "")
        status = r.get("status", "pending")
        if not isinstance(note, str) or status not in STATUSES:
            raise fixture_error("request note/status")
        ts, created = parse_ts(r.get("created_at"), now)
        state["seq"] += 1
        state["requests"].append({
            "id": rid, "requester_id": r["requester_id"], "payer_id": r["payer_id"],
            "amount": amount, "note": note, "status": status,
            "payment_id": r.get("payment_id") if isinstance(r.get("payment_id"), str) else None,
            "split_id": None, "created_at": created, "ts": ts, "seq": state["seq"]})
    hash_fixture_passwords(users)
    return state


def hash_fixture_passwords(users):
    """Replace each seeded plaintext password with its (per-user salted) scrypt record.

    Hashing runs on two threads (scrypt releases the GIL) and happens after the
    whole fixture has been validated, before the state is swapped in.
    """
    members = list(users.values())
    with ThreadPoolExecutor(2) as pool:
        for u, record in zip(members, pool.map(hash_password, [u["pw"] for u in members])):
            u["pw"] = record


def new_state(currency, minor_units, total):
    return {"currency": currency, "minor_units": minor_units, "seeded_total": total,
            "users": {}, "tokens": {}, "payments": [], "requests": [], "splits": [],
            "settlements": [], "operators": [], "idem": [],
            "counters": {"payment": 0, "request": 0, "split": 0, "settlement": 0, "user": 0},
            "seq": 0}


def reject_unsupported_numbers(root):
    """Imported state may only hold ordinary numbers (no over-long or non-finite ones),
    so that it always re-exports as strict JSON. Iterative: nesting cannot overflow."""
    stack = [root]
    while stack:
        v = stack.pop()
        if isinstance(v, BigNumber) or (isinstance(v, float) and not math.isfinite(v)):
            raise invalid("state: number out of range")
        if isinstance(v, dict):
            stack.extend(v.values())
        elif isinstance(v, list):
            stack.extend(v)


def _need(cond):
    if not cond:
        raise invalid("state: invalid")


def validate_state(st):
    """Structural and referential checks of an imported state; raises 422."""
    _need(isinstance(st, dict))
    _need(isinstance(st.get("currency"), str) and is_int(st.get("minor_units"))
          and st["minor_units"] in (0, 2, 3) and is_int(st.get("seeded_total"))
          and is_int(st.get("seq")))
    for k, t in (("users", dict), ("tokens", dict), ("payments", list), ("requests", list),
                 ("splits", list), ("settlements", list), ("operators", list),
                 ("idem", list), ("counters", dict)):
        _need(isinstance(st.get(k), t))
    handles, emails, total = set(), set(), 0
    for uid, u in st["users"].items():
        _need(isinstance(u, dict) and u.get("id") == uid)
        for f in ("email", "display_name", "handle"):
            _need(isinstance(u.get(f), str))
        _need(HANDLE_RE.fullmatch(u["handle"]) and is_int(u.get("balance")) and u["balance"] >= 0)
        pw = u.get("pw")
        _need(isinstance(pw, dict) and all(isinstance(pw.get(k), str) for k in ("salt", "hash"))
              and all(is_int(pw.get(k)) for k in ("n", "r", "p")))
        _need(u["handle"] not in handles and u["email"].lower() not in emails)
        handles.add(u["handle"])
        emails.add(u["email"].lower())
        total += u["balance"]
    _need(total == st["seeded_total"])
    for tok, uid in st["tokens"].items():
        _need(isinstance(tok, str) and uid in st["users"])
    for o in st["operators"]:
        _need(isinstance(o, str))
    pids, rids = set(), set()
    for p in st["payments"]:
        _need(isinstance(p, dict) and isinstance(p.get("id"), str) and p["id"] not in pids)
        pids.add(p["id"])
        _need(p.get("from") in st["users"] and p.get("to") in st["users"])
        _need(is_int(p.get("amount")) and isinstance(p.get("note"), str)
              and p.get("visibility") in ("public", "private")
              and isinstance(p.get("created_at"), str) and isinstance(p.get("ts"), (int, float)) and math.isfinite(p["ts"])
              and is_int(p.get("seq")))
        for k in ("request_id", "settlement_id"):
            _need(k in p and (p[k] is None or isinstance(p[k], str)))
    for r in st["requests"]:
        _need(isinstance(r, dict) and isinstance(r.get("id"), str) and r["id"] not in rids)
        rids.add(r["id"])
        _need(r.get("requester_id") in st["users"] and r.get("payer_id") in st["users"])
        _need(is_int(r.get("amount")) and isinstance(r.get("note"), str)
              and r.get("status") in STATUSES
              and isinstance(r.get("created_at"), str) and isinstance(r.get("ts"), (int, float)) and math.isfinite(r["ts"])
              and is_int(r.get("seq")))
        _need("payment_id" in r and (r["payment_id"] is None or isinstance(r["payment_id"], str)))
    for s in st["splits"]:
        _need(isinstance(s, dict) and isinstance(s.get("id"), str))
    for s in st["settlements"]:
        _need(isinstance(s, dict) and isinstance(s.get("id"), str))
    for e in st["idem"]:
        _need(isinstance(e, dict) and e.get("user") in st["users"]
              and all(isinstance(e.get(k), str) for k in ("method", "path", "key", "body"))
              and isinstance(e.get("response"), dict))
    for k in ("payment", "request", "split", "settlement", "user"):
        _need(is_int(st["counters"].get(k)))


class Service:
    def __init__(self):
        self.lock = threading.RLock()
        self.install(new_state("EUR", 2, 0))

    # ---- state management -------------------------------------------------

    def install(self, state):
        with self.lock:
            self.state = state
            self.by_handle = {u["handle"]: uid for uid, u in state["users"].items()}
            self.by_email = {u["email"].lower(): uid for uid, u in state["users"].items()}
            self.payments = {p["id"]: p for p in state["payments"]}
            self.requests = {r["id"]: r for r in state["requests"]}
            self.idem = {(e["user"], e["method"], e["path"], e["key"]): e
                         for e in state["idem"]}
            self.operators = set(state["operators"])

    def reset(self, fixture):
        try:
            state = build_state_from_fixture(fixture)
        except ApiError:
            raise
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError, RecursionError):
            raise fixture_error("structurally invalid")
        self.install(state)

    def export(self):
        with self.lock:
            blob = json.dumps({"track": TRACK, "format_version": FORMAT_VERSION,
                               "state": self.state}, ensure_ascii=True, allow_nan=False)
        return blob.encode("ascii")

    def import_(self, doc):
        if not isinstance(doc, dict):
            raise malformed("body must be a JSON object")
        if doc.get("track") != TRACK or not is_int(doc.get("format_version")) \
                or doc["format_version"] != FORMAT_VERSION or "state" not in doc:
            raise invalid("wrong or missing track/format_version/state")
        try:
            reject_unsupported_numbers(doc["state"])
            state = copy.deepcopy(doc["state"])
            validate_state(state)
        except ApiError:
            raise
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError, RecursionError):
            raise invalid("state: invalid")
        self.install(state)

    def next_id(self, kind, prefix, taken):
        c = self.state["counters"]
        while True:
            c[kind] += 1
            cand = "%s_%d" % (prefix, c[kind])
            if cand not in taken:
                return cand

    def next_seq(self):
        self.state["seq"] += 1
        return self.state["seq"]

    # ---- auth ---------------------------------------------------------------

    def issue_token(self, uid):
        tok = secrets.token_urlsafe(24)
        self.state["tokens"][tok] = uid
        return tok

    def signup(self, body):
        email = text_field(body, "email")
        password = text_field(body, "password")
        display_name = text_field(body, "display_name")
        if not EMAIL_RE.fullmatch(email) or email.count("@") != 1:
            raise invalid("email must look like local@domain")
        if len(password) < 8:
            raise invalid("password too short")
        local = email.split("@", 1)[0].lower()
        handle = "".join(c if c in HANDLE_CHARS else "_" for c in local)[:20]
        pw = hash_password(password)
        with self.lock:
            if email.lower() in self.by_email:
                raise ApiError(409, "email_taken", "email already registered")
            if handle in self.by_handle:
                raise ApiError(409, "handle_taken", "derived handle already taken")
            uid = self.next_id("user", "u", self.state["users"])
            self.state["users"][uid] = {"id": uid, "email": email,
                                        "display_name": display_name, "handle": handle,
                                        "balance": 0, "pw": pw}
            self.by_handle[handle] = uid
            self.by_email[email.lower()] = uid
            return {"user_id": uid, "display_name": display_name, "token": self.issue_token(uid)}

    def login(self, body):
        email = text_field(body, "email")
        password = text_field(body, "password")
        for attempt in range(4):
            last = attempt == 3
            with self.lock:
                uid = self.by_email.get(email.lower())
                rec = self.state["users"][uid] if uid else None
                if last:  # final pass: verify while holding the lock, so the answer is exact
                    return self._finish_login(uid, rec, password)
            if rec is None or not verify_password(password, rec["pw"]):
                raise ApiError(401, "unauthenticated", "invalid credentials")
            with self.lock:
                if self.state["users"].get(uid) is rec:
                    return {"user_id": uid, "display_name": rec["display_name"],
                            "token": self.issue_token(uid)}
            # state was replaced while hashing: re-evaluate against the new state

    def _finish_login(self, uid, rec, password):
        if rec is None or not verify_password(password, rec["pw"]):
            raise ApiError(401, "unauthenticated", "invalid credentials")
        return {"user_id": uid, "display_name": rec["display_name"], "token": self.issue_token(uid)}

    def me(self, uid):
        with self.lock:
            u = self._user(uid)
            return {"user_id": uid, "display_name": u["display_name"], "handle": u["handle"],
                    "balance": u["balance"], "currency": self.state["currency"],
                    "minor_units": self.state["minor_units"]}

    def _user(self, uid):
        """The caller's wallet; a token can outlive a reset/import that raced it."""
        u = self.state["users"].get(uid)
        if u is None:
            raise ApiError(401, "unauthenticated", "token no longer valid")
        return u

    def is_operator(self, uid):
        with self.lock:
            return uid in self.operators

    # ---- views ----------------------------------------------------------------

    def payment_view(self, p):
        users = self.state["users"]
        return {"payment_id": p["id"], "from_user_id": p["from"],
                "from_handle": users[p["from"]]["handle"], "to_user_id": p["to"],
                "to_handle": users[p["to"]]["handle"], "amount": p["amount"],
                "currency": self.state["currency"], "note": p["note"],
                "visibility": p["visibility"], "request_id": p["request_id"],
                "settlement_id": p["settlement_id"], "created_at": p["created_at"]}

    def request_view(self, r):
        users = self.state["users"]
        return {"request_id": r["id"], "requester_id": r["requester_id"],
                "requester_handle": users[r["requester_id"]]["handle"],
                "payer_id": r["payer_id"], "payer_handle": users[r["payer_id"]]["handle"],
                "amount": r["amount"], "currency": self.state["currency"],
                "note": r["note"], "status": r["status"], "payment_id": r["payment_id"],
                "created_at": r["created_at"]}

    # ---- idempotency ------------------------------------------------------------

    def resolve(self, token):
        """User id for a bearer token, or 401."""
        with self.lock:
            uid = self.state["tokens"].get(token) if token else None
        if uid is None or uid not in self.state["users"]:
            raise ApiError(401, "unauthenticated", "missing or invalid bearer token")
        return uid

    def idempotent(self, uid, method, path, key, sig, operation):
        """Run `operation()` once per (user, method, path, key).

        Returns (status, response). Only successful operations are recorded.
        """
        with self.lock:
            self._user(uid)
            entry = self.idem.get((uid, method, path, key))
            if entry is not None:
                if entry["body"] == sig:
                    return 200, entry["response"]
                raise ApiError(409, "idempotency_key_reuse",
                               "idempotency key used with a different body")
            response = operation()
            entry = {"user": uid, "method": method, "path": path, "key": key,
                     "body": sig, "response": response}
            self.state["idem"].append(entry)
            self.idem[(uid, method, path, key)] = entry
            return 201, response

    # ---- money --------------------------------------------------------------------

    def _lookup(self, handle):
        uid = self.by_handle.get(handle)
        if uid is None:
            raise ApiError(404, "not_found", "no such user")
        return uid

    def _move(self, frm, to, amount, note, visibility, request_id=None,
              settlement_id=None, created=None):
        """Record one payment; caller has checked funds. Must hold the lock."""
        users = self.state["users"]
        users[frm]["balance"] -= amount
        users[to]["balance"] += amount
        ts = created if created is not None else time.time()
        pid = self.next_id("payment", "p", self.payments)
        p = {"id": pid, "from": frm, "to": to, "amount": amount, "note": note,
             "visibility": visibility, "request_id": request_id,
             "settlement_id": settlement_id, "created_at": iso(ts), "ts": ts,
             "seq": self.next_seq()}
        self.state["payments"].append(p)
        self.payments[pid] = p
        return p

    def create_payment(self, uid, body):
        to_handle = handle_field(body, "to_handle")
        amount = amount_of(body.get("amount"), "amount" in body)
        note = note_of(body)
        vis = visibility_of(body)
        with self.lock:
            me = self.state["users"][uid]
            if to_handle == me["handle"]:
                raise ApiError(422, "self_payment", "cannot pay yourself")
            to = self._lookup(to_handle)
            if me["balance"] < amount:
                raise ApiError(409, "insufficient_funds", "balance too low")
            return self.payment_view(self._move(uid, to, amount, note, vis))

    def _new_request(self, requester, payer, amount, note, split_id=None):
        rid = self.next_id("request", "rq", self.requests)
        ts = time.time()
        r = {"id": rid, "requester_id": requester, "payer_id": payer, "amount": amount,
             "note": note, "status": "pending", "payment_id": None, "split_id": split_id,
             "created_at": iso(ts), "ts": ts, "seq": self.next_seq()}
        self.state["requests"].append(r)
        self.requests[rid] = r
        return r

    def create_request(self, uid, body):
        payer_handle = handle_field(body, "payer_handle")
        amount = amount_of(body.get("amount"), "amount" in body)
        note = note_of(body)
        with self.lock:
            if payer_handle == self.state["users"][uid]["handle"]:
                raise ApiError(422, "self_request", "cannot request from yourself")
            payer = self._lookup(payer_handle)
            return self.request_view(self._new_request(uid, payer, amount, note))

    def pay_request(self, uid, rid, body):
        vis = visibility_of(body)
        with self.lock:
            r = self._request_for(rid)
            if r["payer_id"] != uid:
                raise ApiError(403, "forbidden", "only the payer may pay")
            if r["status"] != "pending":
                raise ApiError(409, "request_not_pending", "request is not pending")
            if self.state["users"][uid]["balance"] < r["amount"]:
                raise ApiError(409, "insufficient_funds", "balance too low")
            p = self._move(uid, r["requester_id"], r["amount"], r["note"], vis,
                           request_id=rid)
            r["status"] = "paid"
            r["payment_id"] = p["id"]
            return self.payment_view(p)

    def _request_for(self, rid):
        r = self.requests.get(rid)
        if r is None:
            raise ApiError(404, "not_found", "no such request")
        return r

    def _close_request(self, uid, rid, party, target):
        with self.lock:
            r = self._request_for(rid)
            if r[party] != uid:
                raise ApiError(403, "forbidden", "not permitted for this request")
            if r["status"] == "pending":
                r["status"] = target
            elif r["status"] != target:
                raise ApiError(409, "request_not_pending", "request is not pending")
            return self.request_view(r)

    def decline_request(self, uid, rid):
        return self._close_request(uid, rid, "payer_id", "declined")

    def cancel_request(self, uid, rid):
        return self._close_request(uid, rid, "requester_id", "cancelled")

    def _page(self, items, query):
        limit = int_param(query, "limit", 50, 1, 200)
        offset = int_param(query, "offset", 0, 0)
        return items[offset:offset + limit], len(items) > offset + limit

    def list_requests(self, uid, query):
        direction = query.get("direction")
        if direction is not None and direction not in ("incoming", "outgoing"):
            raise invalid("bad direction")
        status = query.get("status")
        if status is not None and status not in STATUSES:
            raise invalid("bad status")
        int_param(query, "limit", 50, 1, 200)
        int_param(query, "offset", 0, 0)
        with self.lock:
            mine = [r for r in self.state["requests"]
                    if ((r["payer_id"] == uid and direction != "outgoing")
                        or (r["requester_id"] == uid and direction != "incoming"))
                    and (status is None or r["status"] == status)]
            mine.sort(key=lambda r: (r["ts"], r["seq"]), reverse=True)
            page, more = self._page(mine, query)
            return {"requests": [self.request_view(r) for r in page], "has_more": more}

    def list_activity(self, uid, query):
        int_param(query, "limit", 50, 1, 200)
        int_param(query, "offset", 0, 0)
        with self.lock:
            vis = [p for p in self.state["payments"]
                   if p["visibility"] == "public" or p["from"] == uid or p["to"] == uid]
            vis.sort(key=lambda p: (p["ts"], p["seq"]), reverse=True)
            page, more = self._page(vis, query)
            return {"payments": [self.payment_view(p) for p in page], "has_more": more}

    # ---- splits ---------------------------------------------------------------------

    def create_split(self, uid, body):
        if "participant_handles" not in body:
            raise invalid("participant_handles is required")
        handles = body["participant_handles"]
        if not isinstance(handles, list) or not all(isinstance(h, str) for h in handles):
            raise malformed("participant_handles must be an array of strings")
        if not handles or len(set(handles)) != len(handles):
            raise invalid("participant_handles empty or duplicated")
        amount = amount_of(body.get("amount"), "amount" in body)
        note = note_of(body)
        n = len(handles)
        base, extra = divmod(amount, n)
        shares = [base + (1 if i < extra else 0) for i in range(n)]
        with self.lock:
            ids = [self.by_handle.get(h) for h in handles]
            if any(i is None for i in ids):
                raise ApiError(404, "not_found", "unknown participant handle")
            sid = self.next_id("split", "sp", {s["id"] for s in self.state["splits"]})
            reqs = [self._new_request(uid, pid, share, note, sid)
                    for pid, share in zip(ids, shares) if pid != uid]
            created = reqs[0]["created_at"] if reqs else iso(time.time())
            self.state["splits"].append({"id": sid, "amount": amount, "note": note,
                                         "request_ids": [r["id"] for r in reqs],
                                         "created_at": created})
            return {"split_id": sid, "amount": amount, "currency": self.state["currency"],
                    "note": note,
                    "shares": [{"handle": h, "amount": s} for h, s in zip(handles, shares)],
                    "requests": [self.request_view(r) for r in reqs],
                    "created_at": created}

    # ---- settlements ------------------------------------------------------------------

    def create_settlement(self, uid, body):
        transfers = body.get("transfers")
        if not isinstance(transfers, list) or not 1 <= len(transfers) <= 32 \
                or not all(isinstance(t, dict) for t in transfers):
            raise invalid("transfers must be 1..32 objects")
        with self.lock:
            checked = []
            for t in transfers:
                frm_h = handle_field(t, "from_handle")
                to_h = handle_field(t, "to_handle")
                amount = amount_of(t.get("amount"), "amount" in t)
                note = note_of(t)
                vis = visibility_of(t)
                if frm_h == to_h:
                    raise ApiError(422, "self_payment", "cannot transfer to the same wallet")
                checked.append((self._lookup(frm_h), self._lookup(to_h), amount, note, vis))
            net = {}
            for frm, to, amount, _, _ in checked:
                net[frm] = net.get(frm, 0) - amount
                net[to] = net.get(to, 0) + amount
            users = self.state["users"]
            if any(users[w]["balance"] + d < 0 for w, d in net.items()):
                raise ApiError(409, "insufficient_funds", "settlement is not affordable")
            ts = time.time()
            sid = self.next_id("settlement", "st", {s["id"] for s in self.state["settlements"]})
            made = [self._move(frm, to, amount, note, vis, settlement_id=sid, created=ts)
                    for frm, to, amount, note, vis in checked]
            self.state["settlements"].append({"id": sid, "committed_at": iso(ts),
                                              "payment_ids": [p["id"] for p in made]})
            return {"settlement_id": sid, "committed_at": iso(ts),
                    "payments": [self.payment_view(p) for p in made]}
