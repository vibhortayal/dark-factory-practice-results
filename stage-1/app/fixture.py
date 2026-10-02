"""Validate a reset fixture and build a fresh Store from it."""
from concurrent.futures import ThreadPoolExecutor

from . import clock, passwords
from .errors import invalid, malformed
from .jsonutil import as_integer
from .store import HANDLE_RE, STATUSES, VISIBILITIES, Store

_USER_STRINGS = ("id", "email", "password", "display_name", "handle")


def _need(cond, message="invalid fixture"):
    if not cond:
        raise invalid(message)


def _typed(cond, message):
    """Wrong JSON type is 400 malformed_request (spec section 5)."""
    if not cond:
        raise malformed(message)


def _list(fixture, name):
    value = fixture.get(name, [])
    _typed(isinstance(value, list), f"{name} must be an array")
    _typed(all(isinstance(item, dict) for item in value), f"{name} must hold objects")
    return value


def _uint(value, message):
    number = as_integer(value)
    _need(number is not None and number >= 0, message)
    return number


def _text(item, name, default=None):
    value = item.get(name, default)
    _typed(isinstance(value, str), f"{name} must be a string")
    return value


def build(fixture):
    """Return a populated Store; raise ApiError (400/422) for a bad fixture."""
    if not isinstance(fixture, dict):
        raise malformed("fixture must be a JSON object")
    currency = fixture.get("currency")
    _typed("currency" not in fixture or isinstance(currency, str), "currency must be a string")
    _need(currency, "currency is required")
    raw_units = fixture.get("minor_units")
    _typed("minor_units" not in fixture or (isinstance(raw_units, (int, float)) and not isinstance(raw_units, bool)),
           "minor_units must be a number")
    minor_units = as_integer(raw_units)
    _need(minor_units in (0, 2, 3), "minor_units must be 0, 2 or 3")
    store = Store(currency, minor_units)
    _need("users" in fixture, "users is required")
    users = _list(fixture, "users")
    parsed = []
    for u in users:
        for name in _USER_STRINGS:
            _typed(name not in u or isinstance(u[name], str), f"user {name} must be a string")
            _need(name in u, f"user {name} is required")
        _need(HANDLE_RE.fullmatch(u["handle"]) and 0 < len(u["id"]) <= 64, "bad user id/handle")
        _need(u["id"] not in store.users and u["handle"] not in store.by_handle
              and u["email"] not in store.by_email, "duplicate user id, handle or email")
        balance = as_integer(u.get("balance", 0))
        _need(balance is not None and balance >= 0, "balance must be a non-negative integer")
        store.users[u["id"]] = None  # reserve for duplicate detection
        store.by_handle[u["handle"]] = u["id"]
        store.by_email[u["email"]] = u["id"]
        parsed.append((u, balance))
    with ThreadPoolExecutor(max_workers=4) as pool:
        hashes = list(pool.map(lambda pair: passwords.hash_password(pair[0]["password"]), parsed))
    store.users.clear(), store.by_handle.clear(), store.by_email.clear()
    for (u, balance), pw_hash in zip(parsed, hashes):
        store.add_user({"id": u["id"], "email": u["email"], "password_hash": pw_hash,
                        "display_name": u["display_name"], "handle": u["handle"]}, balance)

    created_at = clock.now()
    for p in _list(fixture, "payments"):
        sender, receiver = _party(store, p, "from_user_id"), _party(store, p, "to_user_id")
        visibility = p.get("visibility", "public")
        _need(isinstance(visibility, str) and visibility in VISIBILITIES, "bad visibility")
        pid = _text(p, "id", "") or store.new_id("p_", store.payments)
        _need(pid not in store.payments and len(pid) <= 64, "duplicate or long payment id")
        store.payments[pid] = {
            "payment_id": pid, "from_user_id": sender["id"], "from_handle": sender["handle"],
            "to_user_id": receiver["id"], "to_handle": receiver["handle"],
            "amount": _uint(p.get("amount"), "payment amount must be a non-negative integer"),
            "currency": currency, "note": _text(p, "note", ""), "visibility": visibility,
            "request_id": None, "settlement_id": None, "created_at": created_at}
    for r in _list(fixture, "requests"):
        requester, payer = _party(store, r, "requester_id"), _party(store, r, "payer_id")
        status = r.get("status", "pending")
        _need(isinstance(status, str) and status in STATUSES, "bad request status")
        rid = _text(r, "id", "") or store.new_id("rq_", store.requests)
        _need(rid not in store.requests and len(rid) <= 64, "duplicate or long request id")
        store.requests[rid] = {
            "request_id": rid, "requester_id": requester["id"],
            "requester_handle": requester["handle"], "payer_id": payer["id"],
            "payer_handle": payer["handle"],
            "amount": _uint(r.get("amount"), "request amount must be a non-negative integer"),
            "currency": currency, "note": _text(r, "note", ""), "status": status,
            "payment_id": None, "created_at": created_at, "split_id": None}
    operators = fixture.get("settlement_operator_ids", [])
    _typed(isinstance(operators, list) and all(isinstance(o, str) for o in operators),
           "settlement_operator_ids must be an array of strings")
    store.operators = set(operators)
    return store


def _party(store, item, field):
    uid = item.get(field)
    _need(field in item, f"{field} is required")
    _typed(isinstance(uid, str), f"{field} must be a string")
    _need(uid in store.users, f"{field} must name a seeded user")
    return store.users[uid]


