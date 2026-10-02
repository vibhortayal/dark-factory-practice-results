"""The in-memory state and its single lock.

All state lives in one JSON-shaped dict (`state`), which is exactly what export
returns and import accepts. Lookup indexes are rebuilt from it on every load.
Callers hold `store.lock` for anything that reads or changes state.
"""
import json
import secrets
import threading

from .errors import unauthenticated

EMPTY_STATE = {
    "currency": "EUR", "minor_units": 2,
    "users": {}, "tokens": {}, "payments": [], "requests": [],
    "splits": [], "settlements": [], "operators": [], "idempotency": [],
}


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.load(json.loads(json.dumps(EMPTY_STATE)))

    # ---- whole-state operations ----
    def load(self, state):
        """Replace everything with an already validated state dict."""
        with self.lock:
            self.state = state
            self.by_handle = {u["handle"]: u for u in state["users"].values()}
            self.by_email = {u["email"]: u for u in state["users"].values()}
            self.requests_by_id = {r["request_id"]: r for r in state["requests"]}
            self.idem = {(r["user_id"], r["path"], r["key"]): r for r in state["idempotency"]}
            self.ids = set(state["users"])
            for name, key in (("payments", "payment_id"), ("requests", "request_id"),
                              ("splits", "split_id"), ("settlements", "settlement_id")):
                self.ids.update(item[key] for item in state[name])

    def dump(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    # ---- lookups ----
    @property
    def currency(self):
        return self.state["currency"]

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

    def new_id(self, prefix):
        while True:
            candidate = f"{prefix}_{secrets.token_hex(8)}"
            if candidate not in self.ids:
                self.ids.add(candidate)
                return candidate

    # ---- mutations ----
    def add_user(self, user):
        self.state["users"][user["id"]] = user
        self.by_handle[user["handle"]] = user
        self.by_email[user["email"]] = user
        self.ids.add(user["id"])

    def issue_token(self, user_id):
        token = secrets.token_urlsafe(32)
        self.state["tokens"][token] = user_id
        return token

    def add_request(self, request):
        self.state["requests"].append(request)
        self.requests_by_id[request["request_id"]] = request

    def record_idempotent(self, user_id, path, key, fingerprint, response):
        record = {"user_id": user_id, "path": path, "key": key,
                  "fingerprint": fingerprint, "response": json.loads(json.dumps(response))}
        self.state["idempotency"].append(record)
        self.idem[(user_id, path, key)] = record


store = Store()
