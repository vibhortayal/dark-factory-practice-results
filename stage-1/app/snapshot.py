"""Export and import of the whole service state (spec section 10)."""
from decimal import Decimal

from .errors import invalid
from .store import State, claim_key
from .validation import HANDLE_RE

TRACK = "pocketful"
FORMAT_VERSION = 1


def export_document(state: State) -> dict:
    return {
        "track": TRACK, "format_version": FORMAT_VERSION,
        "state": {
            "currency": state.currency, "minor_units": state.minor_units,
            "users": list(state.users.values()), "tokens": dict(state.tokens),
            "payments": list(state.payments), "requests": list(state.requests.values()),
            "splits": list(state.splits), "settlements": list(state.settlements),
            "idempotency": list(state.idem.values()),
            "operators": sorted(state.operators), "seq": state.seq,
        },
    }


def _is_int(v) -> bool:
    return type(v) is int


def _check(cond, what="invalid state"):
    if not cond:
        raise invalid(what)


def _records(items, kind):
    _check(isinstance(items, list), kind + " must be a list")
    for rec in items:
        _check(isinstance(rec, dict) and _is_int(rec.get("seq")) and _is_int(rec.get("ts"))
               and isinstance(rec.get("data"), dict), kind + " record malformed")
    return items


def import_document(doc) -> State:
    """Validate an export document and build the State it describes."""
    _check(isinstance(doc, dict), "export must be an object")
    _check(doc.get("track") == TRACK, "wrong track")
    version = doc.get("format_version")
    _check(isinstance(version, (int, Decimal)) and not isinstance(version, bool)
           and version == FORMAT_VERSION, "unsupported format_version")
    raw = doc.get("state")
    _check(isinstance(raw, dict), "state must be an object")
    try:
        return _build(raw)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise invalid("state is not a valid export") from None


def _build(raw: dict) -> State:
    state = State()
    state.currency = raw["currency"]
    state.minor_units = raw["minor_units"]
    _check(isinstance(state.currency, str) and state.minor_units in (0, 2, 3)
           and _is_int(state.minor_units))
    _check(isinstance(raw["users"], list))
    for u in raw["users"]:
        _check(isinstance(u, dict) and all(isinstance(u[k], str) for k in
               ("id", "email", "display_name", "handle", "pw_hash")))
        _check(_is_int(u["balance"]) and u["balance"] >= 0 and HANDLE_RE.match(u["handle"]))
        _check(u["id"] not in state.users and u["handle"] not in state.handles
               and u["email"].lower() not in state.emails)
        state.add_user({k: u[k] for k in
                        ("id", "email", "display_name", "handle", "balance", "pw_hash")})
    tokens = raw["tokens"]
    _check(isinstance(tokens, dict) and all(isinstance(t, str) and uid in state.users
                                            for t, uid in tokens.items()))
    state.tokens = dict(tokens)
    for rec in _records(raw["payments"], "payments"):
        d = rec["data"]
        _check(d["from_user_id"] in state.users and d["to_user_id"] in state.users
               and _is_int(d["amount"]) and isinstance(d["payment_id"], str))
        state.payments.append({"seq": rec["seq"], "ts": rec["ts"], "data": d})
    for rec in _records(raw["requests"], "requests"):
        d = rec["data"]
        _check(d["requester_id"] in state.users and d["payer_id"] in state.users
               and _is_int(d["amount"]) and d["status"] in
               ("pending", "paid", "declined", "cancelled")
               and d["request_id"] not in state.requests)
        state.requests[d["request_id"]] = {"seq": rec["seq"], "ts": rec["ts"], "data": d}
    for kind, items in (("splits", raw["splits"]), ("settlements", raw["settlements"])):
        _check(isinstance(items, list) and all(isinstance(i, dict) for i in items), kind)
    state.splits = list(raw["splits"])
    state.settlements = list(raw["settlements"])
    for rec in raw["idempotency"]:
        _check(isinstance(rec, dict) and all(isinstance(rec[k], str) for k in
               ("uid", "method", "path", "key", "body")) and _is_int(rec["status"])
               and isinstance(rec["response"], dict) and rec["uid"] in state.users)
        state.idem[claim_key(rec["uid"], rec["method"], rec["path"], rec["key"])] = rec
    operators = raw["operators"]
    _check(isinstance(operators, list) and all(isinstance(o, str) for o in operators))
    state.operators = set(operators)
    _check(_is_int(raw["seq"]))
    state.seq = raw["seq"]
    return state
