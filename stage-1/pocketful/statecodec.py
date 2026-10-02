"""Fixtures (reset) and exported state (import) -> a validated state dict.

Both raise 422 validation_failed on anything invalid, before any live state
is touched. `check_state` is the single gate every loaded state passes.
"""
from concurrent.futures import ThreadPoolExecutor

from .errors import invalid
from .passwords import hash_password
from .timefmt import normalise_iso, parse_iso
from .validation import HANDLE_RE, STATUSES, VISIBILITIES, integral

MAX_BALANCE = 2 ** 53
MAX_ID = 64


def _need(condition, message="invalid state"):
    if not condition:
        raise invalid(message)


def _is_id(value):
    return isinstance(value, str) and 1 <= len(value) <= MAX_ID


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _unique_ids(items, key, seen):
    for item in items:
        _need(isinstance(item, dict) and _is_id(item.get(key)), f"{key} must be an id")
        _need(item[key] not in seen, f"duplicate id {item[key]}")
        seen.add(item[key])


# ---------------------------------------------------------------- state gate
def check_state(state):
    """Validate an internal state dict (as produced by Store.dump)."""
    _need(isinstance(state, dict), "state must be an object")
    for key, kind in (("users", dict), ("tokens", dict), ("payments", list), ("requests", list),
                      ("splits", list), ("settlements", list), ("operators", list),
                      ("idempotency", list)):
        _need(isinstance(state.get(key), kind), f"state.{key} is missing or the wrong type")
    _need(isinstance(state.get("currency"), str) and state["currency"], "currency")
    _need(state.get("minor_units") in (0, 2, 3) and _is_int(state["minor_units"]), "minor_units")
    handles, emails, seen = set(), set(), set()
    for uid, user in state["users"].items():
        _need(_is_id(uid) and isinstance(user, dict) and user.get("id") == uid, "user id")
        _need(isinstance(user.get("handle"), str) and HANDLE_RE.fullmatch(user["handle"]), "handle")
        _need(isinstance(user.get("email"), str), "email")
        _need(isinstance(user.get("display_name"), str), "display_name")
        _need(isinstance(user.get("password_hash"), str), "password_hash")
        _need(_is_int(user.get("balance")) and 0 <= user["balance"] <= MAX_BALANCE, "balance")
        _need(user["handle"] not in handles and user["email"] not in emails, "duplicate user")
        handles.add(user["handle"])
        emails.add(user["email"])
        seen.add(uid)
    users = state["users"]
    for token, uid in state["tokens"].items():
        _need(isinstance(token, str) and uid in users, "token")
    _need(all(uid in users for uid in state["operators"]), "operators")
    for p in state["payments"]:
        _need(isinstance(p, dict), "payment")
    _unique_ids(state["payments"], "payment_id", seen)
    for p in state["payments"]:
        _need(p.get("from_user_id") in users and p.get("to_user_id") in users, "payment parties")
        _need(p["from_handle"] == users[p["from_user_id"]]["handle"]
              and p["to_handle"] == users[p["to_user_id"]]["handle"], "payment handles")
        _need(_is_int(p.get("amount")) and p["amount"] >= 0, "payment amount")
        _need(isinstance(p.get("note"), str) and p.get("visibility") in VISIBILITIES, "payment")
        _need(p.get("currency") == state["currency"], "payment currency")
        _need(p.get("request_id") is None or isinstance(p["request_id"], str), "request_id")
        _need(p.get("settlement_id") is None or isinstance(p["settlement_id"], str), "settlement_id")
        _need(parse_iso(p.get("created_at")) is not None, "created_at")
    for r in state["requests"]:
        _need(isinstance(r, dict), "request")
    _unique_ids(state["requests"], "request_id", seen)
    for r in state["requests"]:
        _need(r.get("requester_id") in users and r.get("payer_id") in users, "request parties")
        _need(r["requester_handle"] == users[r["requester_id"]]["handle"]
              and r["payer_handle"] == users[r["payer_id"]]["handle"], "request handles")
        _need(_is_int(r.get("amount")) and r["amount"] >= 0, "request amount")
        _need(isinstance(r.get("note"), str) and r.get("status") in STATUSES, "request")
        _need(r.get("currency") == state["currency"], "request currency")
        _need(r.get("payment_id") is None or isinstance(r["payment_id"], str), "payment_id")
        _need(parse_iso(r.get("created_at")) is not None, "created_at")
    _unique_ids(state["splits"], "split_id", seen)
    _unique_ids(state["settlements"], "settlement_id", seen)
    keys = set()
    for rec in state["idempotency"]:
        _need(isinstance(rec, dict), "idempotency record")
        for name in ("user_id", "path", "key", "fingerprint"):
            _need(isinstance(rec.get(name), str), "idempotency record")
        _need(rec["user_id"] in users and isinstance(rec.get("response"), dict), "idempotency record")
        ident = (rec["user_id"], rec["path"], rec["key"])
        _need(ident not in keys, "duplicate idempotency record")
        keys.add(ident)
    return state


def check_export(document):
    """Validate a whole export envelope and return its state."""
    _need(isinstance(document, dict), "export must be an object")
    _need(document.get("track") == "pocketful", "wrong track")
    _need(_is_int(document.get("format_version")) and document["format_version"] == 1,
          "unsupported format_version")
    _need("state" in document, "state is missing")
    try:
        return check_state(document["state"])
    except (KeyError, TypeError, AttributeError, ValueError):
        raise invalid("invalid state")


# ------------------------------------------------------------------- fixture
def _fixture_list(fixture, name):
    value = fixture.get(name, [])
    _need(isinstance(value, list), f"{name} must be an array")
    _need(all(isinstance(v, dict) for v in value), f"{name} entries must be objects")
    return value


def _count(value, what, minimum=0, maximum=None):
    number = integral(value)
    _need(number is not None and number >= minimum and (maximum is None or number <= maximum),
          f"{what} must be an integer")
    return number


def _fixture_users(entries):
    users = {}
    for entry in entries:
        uid, handle = entry.get("id"), entry.get("handle")
        _need(_is_id(uid), "user id must be a string of 1 to 64 characters")
        _need(isinstance(handle, str) and HANDLE_RE.fullmatch(handle), "invalid handle")
        for field in ("email", "password"):
            _need(isinstance(entry.get(field), str), f"user {field} must be a string")
        display = entry.get("display_name", handle)
        _need(isinstance(display, str), "display_name must be a string")
        balance = _count(entry.get("balance"), "balance", 0, MAX_BALANCE)
        _need(uid not in users, "duplicate user id")
        users[uid] = {"id": uid, "email": entry["email"], "display_name": display,
                      "handle": handle, "balance": balance, "_password": entry["password"]}
    _need(len({u["handle"] for u in users.values()}) == len(users), "duplicate handle")
    _need(len({u["email"] for u in users.values()}) == len(users), "duplicate email")
    return users


def _hash_all(users):
    with ThreadPoolExecutor(max_workers=2) as pool:
        hashes = list(pool.map(hash_password, [u["_password"] for u in users.values()]))
    for user, hashed in zip(users.values(), hashes):
        del user["_password"]
        user["password_hash"] = hashed


def _created(entry, now):
    if "created_at" not in entry:
        return now
    stamp = normalise_iso(entry["created_at"])
    _need(stamp is not None, "created_at must be an RFC 3339 timestamp with an offset")
    return stamp


def _optional_id(entry, name):
    value = entry.get(name)
    _need(value is None or _is_id(value), f"{name} must be an id or null")
    return value


def _fixture_payments(entries, users, currency, now):
    out = []
    for e in entries:
        sender, receiver = users.get(e.get("from_user_id")), users.get(e.get("to_user_id"))
        _need(sender and receiver, "payment references an unknown user")
        visibility = e.get("visibility", "public")
        _need(visibility in VISIBILITIES and isinstance(visibility, str), "payment visibility")
        note = e.get("note", "")
        _need(isinstance(note, str), "payment note must be a string")
        out.append({
            "payment_id": e.get("id"), "from_user_id": sender["id"], "from_handle": sender["handle"],
            "to_user_id": receiver["id"], "to_handle": receiver["handle"],
            "amount": _count(e.get("amount"), "payment amount", 0, MAX_BALANCE),
            "currency": currency, "note": note, "visibility": visibility,
            "request_id": _optional_id(e, "request_id"),
            "settlement_id": _optional_id(e, "settlement_id"), "created_at": _created(e, now)})
    return out


def _fixture_requests(entries, users, currency, now):
    out = []
    for e in entries:
        requester, payer = users.get(e.get("requester_id")), users.get(e.get("payer_id"))
        _need(requester and payer, "request references an unknown user")
        note = e.get("note", "")
        _need(isinstance(note, str), "request note must be a string")
        status = e.get("status", "pending")
        _need(status in STATUSES and isinstance(status, str), "request status")
        out.append({
            "request_id": e.get("id"), "requester_id": requester["id"],
            "requester_handle": requester["handle"], "payer_id": payer["id"],
            "payer_handle": payer["handle"],
            "amount": _count(e.get("amount"), "request amount", 0, MAX_BALANCE),
            "currency": currency, "note": note, "status": status,
            "payment_id": _optional_id(e, "payment_id"), "created_at": _created(e, now)})
    return out


def _by_time(items):
    return sorted(items, key=lambda item: parse_iso(item["created_at"]))  # stable


def build_state(fixture, now):
    """Turn a reset fixture into a validated state dict."""
    currency = fixture.get("currency", "EUR")
    _need(isinstance(currency, str) and currency, "currency must be a string")
    minor_units = fixture.get("minor_units", 2)
    _need(_is_int(minor_units) and minor_units in (0, 2, 3), "minor_units must be 0, 2 or 3")
    _need(isinstance(fixture.get("users"), list), "users must be an array")
    users = _fixture_users(_fixture_list(fixture, "users"))
    operators = fixture.get("settlement_operator_ids", [])
    _need(isinstance(operators, list) and all(o in users for o in operators),
          "settlement_operator_ids must name seeded users")
    payments = _fixture_payments(_fixture_list(fixture, "payments"), users, currency, now)
    requests = _fixture_requests(_fixture_list(fixture, "requests"), users, currency, now)
    _hash_all(users)
    state = {"currency": currency, "minor_units": minor_units, "users": users, "tokens": {},
             "payments": _by_time(payments), "requests": _by_time(requests), "splits": [],
             "settlements": [], "operators": list(dict.fromkeys(operators)), "idempotency": []}
    return check_state(state)
