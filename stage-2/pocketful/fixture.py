"""A reset fixture -> a validated state dict (spec stage-1 §4, stage-2 Model)."""
from concurrent.futures import ThreadPoolExecutor

from .errors import invalid
from .passwords import hash_password
from .statebase import MAX_BALANCE, count, is_id, is_int, known, need
from .statecheck import DEFAULT_TTL, check_state
from .timefmt import normalise_iso, parse_iso
from .validation import AUTH_STATUSES, HANDLE_RE, STATUSES, VISIBILITIES, integral


def _fixture_list(fixture, name):
    value = fixture.get(name, [])
    need(isinstance(value, list), f"{name} must be an array")
    need(all(isinstance(v, dict) for v in value), f"{name} entries must be objects")
    return value


def _fixture_users(entries):
    users = {}
    for entry in entries:
        uid, handle = entry.get("id"), entry.get("handle")
        need(is_id(uid), "user id must be a string of 1 to 64 characters")
        need(isinstance(handle, str) and HANDLE_RE.fullmatch(handle), "invalid handle")
        for field in ("email", "password"):
            need(isinstance(entry.get(field), str), f"user {field} must be a string")
        display = entry.get("display_name", handle)
        need(isinstance(display, str), "display_name must be a string")
        balance = count(entry.get("balance"), "balance", 0, MAX_BALANCE)
        need(uid not in users, "duplicate user id")
        users[uid] = {"id": uid, "email": entry["email"], "display_name": display,
                      "handle": handle, "balance": balance, "_password": entry["password"]}
    need(len({u["handle"] for u in users.values()}) == len(users), "duplicate handle")
    need(len({u["email"] for u in users.values()}) == len(users), "duplicate email")
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
    need(stamp is not None, "created_at must be an RFC 3339 timestamp with an offset")
    return stamp


def _optional_id(entry, name):
    value = entry.get(name)
    need(value is None or is_id(value), f"{name} must be an id or null")
    return value


def _text_and_visibility(entry, what):
    note = entry.get("note", "")
    need(isinstance(note, str), f"{what} note must be a string")
    visibility = entry.get("visibility", "public")
    need(isinstance(visibility, str) and visibility in VISIBILITIES, f"{what} visibility")
    return note, visibility


def _fixture_payments(entries, users, currency, now):
    out = []
    for e in entries:
        sender, receiver = known(users, e.get("from_user_id")), known(users, e.get("to_user_id"))
        need(sender and receiver, "payment references an unknown user")
        note, visibility = _text_and_visibility(e, "payment")
        out.append({
            "payment_id": e.get("id"), "from_user_id": sender["id"], "from_handle": sender["handle"],
            "to_user_id": receiver["id"], "to_handle": receiver["handle"],
            "amount": count(e.get("amount"), "payment amount", 0, MAX_BALANCE),
            "currency": currency, "note": note, "visibility": visibility,
            "request_id": _optional_id(e, "request_id"),
            "settlement_id": _optional_id(e, "settlement_id"),
            "authorization_id": _optional_id(e, "authorization_id"), "created_at": _created(e, now)})
    return out


def _fixture_requests(entries, users, currency, now):
    out = []
    for e in entries:
        requester, payer = known(users, e.get("requester_id")), known(users, e.get("payer_id"))
        need(requester and payer, "request references an unknown user")
        note = e.get("note", "")
        need(isinstance(note, str), "request note must be a string")
        status = e.get("status", "pending")
        need(isinstance(status, str) and status in STATUSES, "request status")
        out.append({
            "request_id": e.get("id"), "requester_id": requester["id"],
            "requester_handle": requester["handle"], "payer_id": payer["id"],
            "payer_handle": payer["handle"],
            "amount": count(e.get("amount"), "request amount", 0, MAX_BALANCE),
            "currency": currency, "note": note, "status": status,
            "payment_id": _optional_id(e, "payment_id"), "created_at": _created(e, now)})
    return out


def _fixture_authorizations(entries, users, currency, now):
    out = []
    for e in entries:
        payer, receiver = known(users, e.get("from_user_id")), known(users, e.get("to_user_id"))
        need(payer and receiver and payer is not receiver, "authorization parties")
        note, visibility = _text_and_visibility(e, "authorization")
        status = e.get("status", "open")
        need(isinstance(status, str) and status in AUTH_STATUSES, "authorization status")
        expires = normalise_iso(e.get("expires_at"))
        need(expires is not None, "expires_at must be an RFC 3339 timestamp with an offset")
        amount = count(e.get("amount"), "authorization amount", 1, MAX_BALANCE)
        default_captured = amount if status == "captured" else 0
        captured = count(e.get("captured_amount", default_captured), "captured_amount", 0, amount)
        payment_ids = e.get("payment_ids", [])
        need(isinstance(payment_ids, list) and all(isinstance(i, str) for i in payment_ids), "payment_ids")
        out.append({
            "authorization_id": e.get("id"), "from_user_id": payer["id"], "from_handle": payer["handle"],
            "to_user_id": receiver["id"], "to_handle": receiver["handle"], "amount": amount,
            "captured_amount": captured, "remaining_amount": amount - captured if status == "open" else 0,
            "currency": currency, "note": note, "visibility": visibility, "status": status,
            "expires_at": expires, "payment_id": _optional_id(e, "payment_id"),
            "payment_ids": list(payment_ids), "created_at": _created(e, now)})
    return out


def _by_time(items):
    return sorted(items, key=lambda item: parse_iso(item["created_at"]))  # stable


def _ttl(fixture):
    if "authorization_ttl_seconds" not in fixture:
        return DEFAULT_TTL
    ttl = integral(fixture["authorization_ttl_seconds"])
    need(ttl is not None and ttl >= 1, "authorization_ttl_seconds must be a positive integer")
    return ttl


def build_state(fixture, now):
    """Turn a reset fixture into a validated state dict."""
    try:
        return _build_state(fixture, now)
    except (KeyError, TypeError, AttributeError, ValueError):
        raise invalid("fixture is not valid")


def _build_state(fixture, now):
    currency = fixture.get("currency", "EUR")
    need(isinstance(currency, str) and currency, "currency must be a string")
    minor_units = fixture.get("minor_units", 2)
    need(is_int(minor_units) and minor_units in (0, 2, 3), "minor_units must be 0, 2 or 3")
    need(isinstance(fixture.get("users"), list), "users must be an array")
    ttl = _ttl(fixture)
    users = _fixture_users(_fixture_list(fixture, "users"))
    operators = fixture.get("settlement_operator_ids", [])
    need(isinstance(operators, list) and all(known(users, o) for o in operators),
         "settlement_operator_ids must name seeded users")
    payments = _fixture_payments(_fixture_list(fixture, "payments"), users, currency, now)
    requests = _fixture_requests(_fixture_list(fixture, "requests"), users, currency, now)
    authorizations = _fixture_authorizations(_fixture_list(fixture, "authorizations"), users, currency, now)
    _hash_all(users)
    state = {"currency": currency, "minor_units": minor_units, "authorization_ttl_seconds": ttl,
             "users": users, "tokens": {}, "payments": _by_time(payments),
             "requests": _by_time(requests), "authorizations": _by_time(authorizations),
             "splits": [], "settlements": [], "operators": list(dict.fromkeys(operators)),
             "idempotency": []}
    return check_state(state)
