"""In-memory service state, the global lock, and state (de)serialisation.

All mutation happens while holding `LOCK`; every handler validates first and
mutates last, so a failed operation leaves no trace.
"""
import copy
import re
import secrets
import threading

from .jsonutil import as_integer

LOCK = threading.RLock()
HANDLE_RE = re.compile(r"[a-z0-9_]{1,20}")
STATUSES = ("pending", "paid", "declined", "cancelled")
VISIBILITIES = ("public", "private")


class Store:
    def __init__(self, currency="EUR", minor_units=2):
        self.currency = currency
        self.minor_units = minor_units
        self.users = {}        # id -> {id,email,password_hash,display_name,handle}
        self.by_handle = {}    # handle -> id
        self.by_email = {}     # email -> id
        self.balances = {}     # id -> int
        self.tokens = {}       # token -> user id
        self.payments = {}     # id -> payment dict (insertion order = creation order)
        self.requests = {}     # id -> request dict
        self.splits = {}
        self.settlements = {}
        self.operators = set()
        self.idem = {}         # (user_id, method, path, key) -> {body,status,response}

    # -- users ---------------------------------------------------------
    def add_user(self, user, balance):
        self.users[user["id"]] = user
        self.by_handle[user["handle"]] = user["id"]
        self.by_email[user["email"]] = user["id"]
        self.balances[user["id"]] = balance

    def user_by_handle(self, handle):
        uid = self.by_handle.get(handle)
        return self.users[uid] if uid else None

    # -- ids -----------------------------------------------------------
    def new_id(self, prefix, taken):
        while True:
            candidate = prefix + secrets.token_hex(6)
            if candidate not in taken:
                return candidate

    # -- serialisation -------------------------------------------------
    def dump(self):
        return copy.deepcopy({
            "currency": self.currency,
            "minor_units": self.minor_units,
            "users": [{**u, "balance": self.balances[u["id"]]} for u in self.users.values()],
            "tokens": self.tokens,
            "payments": list(self.payments.values()),
            "requests": list(self.requests.values()),
            "splits": list(self.splits.values()),
            "settlements": list(self.settlements.values()),
            "operators": sorted(self.operators),
            "idempotency": [
                {"user_id": k[0], "method": k[1], "path": k[2], "key": k[3], **rec}
                for k, rec in self.idem.items()],
        })


class StateError(ValueError):
    pass


def _check(cond, msg="invalid state"):
    if not cond:
        raise StateError(msg)


def _is_str(v):
    return isinstance(v, str)


def _is_amount(v):
    return type(v) is int and v >= 0


def load(data):
    """Rebuild a Store from `Store.dump()` output; raise StateError if invalid."""
    try:
        return _load(copy.deepcopy(data))
    except StateError:
        raise
    except Exception as exc:  # any shape problem is an invalid state
        raise StateError(str(exc)) from None


def _load(data):
    _check(isinstance(data, dict))
    _check(_is_str(data["currency"]) and data["currency"])
    _check(type(data["minor_units"]) is int and data["minor_units"] in (0, 2, 3))
    store = Store(data["currency"], data["minor_units"])
    for u in data["users"]:
        _check(all(_is_str(u[k]) for k in ("id", "email", "password_hash", "display_name", "handle")))
        _check(HANDLE_RE.fullmatch(u["handle"]) and len(u["id"]) <= 64)
        _check(u["id"] not in store.users and u["handle"] not in store.by_handle
               and u["email"] not in store.by_email)
        _check(type(u["balance"]) is int and u["balance"] >= 0)
        balance = u.pop("balance")
        store.add_user({k: u[k] for k in ("id", "email", "password_hash", "display_name", "handle")},
                       balance)
    _check(isinstance(data["tokens"], dict))
    for token, uid in data["tokens"].items():
        _check(uid in store.users)
        store.tokens[token] = uid
    for p in data["payments"]:
        _check(all(_is_str(p[k]) for k in ("payment_id", "from_handle", "to_handle", "currency",
                                           "note", "visibility", "created_at")))
        _check(store.users[p["from_user_id"]]["handle"] == p["from_handle"])
        _check(store.users[p["to_user_id"]]["handle"] == p["to_handle"])
        _check(_is_amount(p["amount"]) and p["visibility"] in VISIBILITIES)
        _check(p["request_id"] is None or _is_str(p["request_id"]))
        _check(p["settlement_id"] is None or _is_str(p["settlement_id"]))
        _check(p["payment_id"] not in store.payments)
        store.payments[p["payment_id"]] = p
    for r in data["requests"]:
        _check(all(_is_str(r[k]) for k in ("request_id", "requester_handle", "payer_handle",
                                           "currency", "note", "created_at")))
        _check(store.users[r["requester_id"]]["handle"] == r["requester_handle"])
        _check(store.users[r["payer_id"]]["handle"] == r["payer_handle"])
        _check(_is_amount(r["amount"]) and r["status"] in STATUSES)
        _check(r["payment_id"] is None or _is_str(r["payment_id"]))
        _check(r["request_id"] not in store.requests)
        store.requests[r["request_id"]] = r
    for s in data["splits"]:
        _check(_is_str(s["split_id"]) and isinstance(s["shares"], list))
        _check(s["split_id"] not in store.splits)
        store.splits[s["split_id"]] = s
    for s in data["settlements"]:
        _check(_is_str(s["settlement_id"]) and isinstance(s["payment_ids"], list))
        _check(s["settlement_id"] not in store.settlements)
        store.settlements[s["settlement_id"]] = s
    _check(isinstance(data["operators"], list) and all(_is_str(o) for o in data["operators"]))
    store.operators = set(data["operators"])
    for rec in data["idempotency"]:
        _check(rec["user_id"] in store.users and _is_str(rec["key"]) and _is_str(rec["path"]))
        _check(_is_str(rec["method"]) and as_integer(rec["status"]) is not None)
        store.idem[(rec["user_id"], rec["method"], rec["path"], rec["key"])] = {
            "body": rec["body"], "status": rec["status"], "response": rec["response"]}
    return store


class Holder:
    """Holds the current Store; replaced wholesale by reset and import."""
    store = Store()


def current():
    return Holder.store


def replace(store):
    Holder.store = store
