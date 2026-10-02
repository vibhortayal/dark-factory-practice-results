"""The in-memory state and its single lock.

All state lives in one JSON-shaped dict (`state`), which is exactly what export
returns and import accepts. Lookup indexes (and parsed-time caches) are rebuilt
from it on every load.

Use `with store.locked():` for anything that reads or changes state. Entering
the lock for the first time in an operation reads the clock once and applies
clock expiry (`store.on_begin`, set by `operation.py`), so no handler can forget
to begin the operation.
"""
import json
import secrets
import threading
from datetime import timedelta
from contextlib import contextmanager

from .errors import unauthenticated
from .timefmt import fmt, parse_iso

EMPTY_STATE = {
    "currency": "EUR", "minor_units": 2,
    "users": {}, "tokens": {}, "payments": [], "requests": [],
    "splits": [], "settlements": [], "operators": [], "idempotency": [],
    "authorizations": [], "authorization_ttl_seconds": 600,
    "revisions": {}, "opening_balances": {}, "snapshots": {},
}


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.depth = 0
        self.now = None        # the instant of the operation in progress
        self.on_begin = None   # called when an operation takes the lock
        self.load(json.loads(json.dumps(EMPTY_STATE)))

    @contextmanager
    def locked(self):
        with self.lock:
            self.depth += 1
            try:
                if self.depth == 1 and self.on_begin is not None:
                    self.on_begin()
                yield self
            finally:
                self.depth -= 1

    # ---- whole-state operations ----
    def load(self, state):
        """Replace everything with an already validated state dict."""
        with self.lock:
            self.state = state
            self.by_handle = {u["handle"]: u for u in state["users"].values()}
            self.by_email = {u["email"]: u for u in state["users"].values()}
            self.requests_by_id = {r["request_id"]: r for r in state["requests"]}
            self.idem = {(r["user_id"], r["path"], r["key"]): r for r in state["idempotency"]}
            self.auth_by_id = {a["authorization_id"]: a for a in state["authorizations"]}
            self.open_auths = {a["authorization_id"]: a for a in state["authorizations"]
                               if a["status"] == "open"}
            self.expiries = {a["authorization_id"]: parse_iso(a["expires_at"])
                             for a in state["authorizations"]}
            self.auths_by_payer = {}
            for a in state["authorizations"]:
                self.auths_by_payer.setdefault(a["from_user_id"], []).append(a)
            self.payments_by_id = {p["payment_id"]: p for p in state["payments"]}
            self.user_payments = {}
            for p in state["payments"]:
                for uid in {p["from_user_id"], p["to_user_id"]}:
                    self.user_payments.setdefault(uid, []).append(p["payment_id"])
            self.refunds_by_target = {}
            for p in state["payments"]:
                if p.get("refund_of"):
                    self.refunds_by_target.setdefault(p["refund_of"], []).append(p)
            self.created_dt = {p["payment_id"]: parse_iso(p["created_at"]) for p in state["payments"]}
            self.revision_times = {pid: [(parse_iso(r["recorded_at"]), parse_iso(r["effective_at"]))
                                         for r in revs] for pid, revs in state["revisions"].items()}
            self.ids = set(state["users"])
            self.ids.update(r["correction_batch_id"] for revs in state["revisions"].values()
                            for r in revs if r.get("correction_batch_id"))
            for name, key in (("payments", "payment_id"), ("requests", "request_id"),
                              ("splits", "split_id"), ("settlements", "settlement_id"),
                              ("authorizations", "authorization_id")):
                self.ids.update(item[key] for item in state[name])

    def dump(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    # ---- lookups ----
    def stamp(self, plus_seconds=0):
        """The current operation's instant (plus an offset) as a fixed-width timestamp."""
        return fmt(self.now + timedelta(seconds=plus_seconds))

    @property
    def currency(self):
        return self.state["currency"]

    @property
    def authorization_ttl(self):
        return self.state["authorization_ttl_seconds"]

    @property
    def minor_units(self):
        return self.state["minor_units"]

    def user(self, user_id):
        user = self.state["users"].get(user_id)
        if user is None:
            raise unauthenticated("account no longer exists")
        return user

    def user_for_token(self, token):
        user_id = self.state["tokens"].get(token)
        return self.state["users"].get(user_id) if user_id is not None else None

    def opening_balance(self, user_id):
        return self.state["opening_balances"].get(user_id, 0)

    def new_id(self, prefix):
        while True:
            candidate = f"{prefix}_{secrets.token_hex(8)}"
            if candidate not in self.ids:
                self.ids.add(candidate)
                return candidate

    # ---- mutations ----
    def add_user(self, user):
        self.state["users"][user["id"]] = user
        self.state["opening_balances"][user["id"]] = 0   # new accounts open at zero
        self.by_handle[user["handle"]] = user
        self.by_email[user["email"]] = user
        self.ids.add(user["id"])

    def issue_token(self, user_id):
        token = secrets.token_urlsafe(32)
        self.state["tokens"][token] = user_id
        return token

    def add_payment(self, payment):
        """Record a payment with its revision 1 (effective = recorded = created_at)."""
        pid = payment["payment_id"]
        self.state["payments"].append(payment)
        self.payments_by_id[pid] = payment
        for uid in {payment["from_user_id"], payment["to_user_id"]}:
            self.user_payments.setdefault(uid, []).append(pid)
        if payment.get("refund_of"):
            self.refunds_by_target.setdefault(payment["refund_of"], []).append(payment)
        self.created_dt[pid] = parse_iso(payment["created_at"])
        self.state["revisions"][pid] = [{
            "payment_id": pid, "revision": 1, "amount": payment["amount"],
            "effective_at": payment["created_at"], "recorded_at": payment["created_at"], "reason": "",
            "correction_batch_id": None}]
        self.revision_times[pid] = [(self.created_dt[pid], self.created_dt[pid])]

    def refunded_total(self, payment_id):
        return sum(p["amount"] for p in self.refunds_by_target.get(payment_id, ()))

    def add_revision(self, revision):
        pid = revision["payment_id"]
        self.state["revisions"][pid].append(revision)
        self.revision_times[pid].append((parse_iso(revision["recorded_at"]), parse_iso(revision["effective_at"])))

    def add_request(self, request):
        self.state["requests"].append(request)
        self.requests_by_id[request["request_id"]] = request

    def add_authorization(self, authorization):
        self.state["authorizations"].append(authorization)
        aid = authorization["authorization_id"]
        self.auth_by_id[aid] = authorization
        self.expiries[aid] = parse_iso(authorization["expires_at"])
        self.auths_by_payer.setdefault(authorization["from_user_id"], []).append(authorization)
        if authorization["status"] == "open":
            self.open_auths[aid] = authorization

    def record_idempotent(self, user_id, path, key, fingerprint, response):
        record = {"user_id": user_id, "path": path, "key": key,
                  "fingerprint": fingerprint, "response": json.loads(json.dumps(response))}
        self.state["idempotency"].append(record)
        self.idem[(user_id, path, key)] = record


store = Store()
