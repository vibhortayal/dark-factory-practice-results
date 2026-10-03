"""Build a State from a reset fixture (spec section 4)."""
from decimal import Decimal

from . import clock, holds, ledger
from .errors import invalid, malformed
from .passwords import hash_password
from .store import State
from .validation import HANDLE_RE

DEFAULT_MINOR_UNITS = {"EUR": 2, "JPY": 0, "BHD": 3}
STATUSES = ("pending", "paid", "declined", "cancelled")


def _int(value, what, minimum=None) -> int:
    if isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("%s must be an integer" % what)
    if minimum is not None and value < minimum:
        raise invalid("%s must be at least %d" % (what, minimum))
    return value


def _str(value, what, default=None) -> str:
    if value is None and default is not None:
        return default
    if not isinstance(value, str):
        raise invalid("%s must be a string" % what)
    return value


def _list(fx, name) -> list:
    value = fx.get(name, [])
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise invalid("%s must be a list of objects" % name)
    return value


def _stamp(item, base):
    parsed = clock.parse(item.get("created_at")) if "created_at" in item else None
    return parsed or base


def build_state(fx) -> State:
    if not isinstance(fx, dict):
        raise malformed("fixture must be a JSON object")
    state = State()
    state.currency = _str(fx.get("currency"), "currency", "EUR")
    if "minor_units" in fx:
        state.minor_units = _int(fx["minor_units"], "minor_units")
    elif state.currency in DEFAULT_MINOR_UNITS:
        state.minor_units = DEFAULT_MINOR_UNITS[state.currency]
    if state.minor_units not in (0, 2, 3):
        raise invalid("minor_units must be 0, 2 or 3")
    base = clock.now()

    for item in _list(fx, "users"):
        uid = _str(item.get("id"), "user id")
        handle = _str(item.get("handle"), "handle")
        email = _str(item.get("email"), "email")
        if not uid or len(uid) > 64 or not HANDLE_RE.match(handle) or not email:
            raise invalid("invalid user identity")
        if uid in state.users or handle in state.handles or email.lower() in state.emails:
            raise invalid("duplicate user id, handle or email")
        balance = _int(item.get("balance", 0), "balance", 0)
        password = _str(item.get("password"), "password")
        state.add_user({"id": uid, "email": email,
                        "display_name": _str(item.get("display_name"), "display_name", handle),
                        "handle": handle, "balance": balance,
                        "pw_hash": hash_password(password)})

    seen = set()
    for item in _list(fx, "payments"):
        pid = _str(item.get("id"), "payment id")
        sender = state.users.get(item.get("from_user_id"))
        receiver = state.users.get(item.get("to_user_id"))
        if pid in seen or sender is None or receiver is None:
            raise invalid("payment references unknown users or repeats an id")
        seen.add(pid)
        visibility = item.get("visibility", "public")
        if visibility not in ("public", "private"):
            raise invalid("payment visibility must be public or private")
        stamp = _stamp(item, base)
        data = ledger.payment_data(state, sender, receiver,
                                   _int(item.get("amount"), "payment amount", 0),
                                   _str(item.get("note"), "note", ""), visibility, stamp,
                                   request_id=item.get("request_id"), payment_id=pid)
        state.add_payment(data, stamp.ts)

    for item in _list(fx, "requests"):
        rid = _str(item.get("id"), "request id")
        requester = state.users.get(item.get("requester_id"))
        payer = state.users.get(item.get("payer_id"))
        status = item.get("status", "pending")
        if rid in state.requests or requester is None or payer is None or status not in STATUSES:
            raise invalid("request references unknown users, repeats an id or has a bad status")
        stamp = _stamp(item, base)
        data = ledger.request_data(state, requester, payer,
                                   _int(item.get("amount"), "request amount", 0),
                                   _str(item.get("note"), "note", ""), stamp, status,
                                   item.get("payment_id"), rid)
        state.add_request(data, stamp.ts)

    if "authorization_ttl_seconds" in fx:
        ttl = fx["authorization_ttl_seconds"]
        if ttl is None:
            raise invalid("authorization_ttl_seconds must be a positive integer")
        state.ttl = _int(ttl, "authorization_ttl_seconds", 1)
    _seed_authorizations(state, _list(fx, "authorizations"), base)
    operators = fx.get("settlement_operator_ids", [])
    if not isinstance(operators, list) or not all(isinstance(o, str) for o in operators):
        raise invalid("settlement_operator_ids must be a list of strings")
    state.operators = set(operators)
    return state


AUTH_STATUSES = ("open", "captured", "voided", "expired")


def _seed_authorizations(state, items, base):
    for item in items:
        aid = _str(item.get("id"), "authorization id")
        payer = state.users.get(item.get("from_user_id"))
        payee = state.users.get(item.get("to_user_id"))
        status = item.get("status", "open")
        if aid in state.authorizations or payer is None or payee is None \
                or status not in AUTH_STATUSES:
            raise invalid("authorization references unknown users, repeats an id or has a bad status")
        visibility = item.get("visibility", "public")
        if visibility not in ("public", "private"):
            raise invalid("authorization visibility must be public or private")
        amount = _int(item.get("amount"), "authorization amount", 0)
        created = _stamp(item, base)
        if "expires_at" in item:
            expires = clock.parse(item["expires_at"])
            if expires is None:
                raise invalid("expires_at must be an RFC 3339 timestamp")
        else:
            expires = clock.from_ts(created.ts + state.ttl * 1_000_000)
        captured = _int(item.get("captured_amount", amount if status == "captured" else 0),
                        "captured_amount", 0)
        if captured > amount:
            raise invalid("captured_amount exceeds the authorized amount")
        payment_ids = item.get("payment_ids")
        if payment_ids is None:
            payment_ids = [item["payment_id"]] if item.get("payment_id") else []
        if not isinstance(payment_ids, list):
            raise invalid("payment_ids must be a list")
        is_open = status == "open"
        data = holds.auth_data(
            state, payer, payee, amount, _str(item.get("note"), "note", ""), visibility,
            created, expires, authorization_id=aid, status=status, captured_amount=captured,
            remaining_amount=amount - captured if is_open else 0,
            payment_id=payment_ids[-1] if payment_ids else None, payment_ids=payment_ids)
        state.add_authorization(data, created.ts, expires.ts)
    if state.authorizations:
        holds.expire_due(state, clock.now().ts)
        for user in state.users.values():
            if holds.held_of(state, user["id"]) > user["balance"]:
                raise invalid("open holds exceed the wallet balance")
