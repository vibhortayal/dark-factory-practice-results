"""Export and import of the whole service state (spec section 10)."""
from decimal import Decimal

from .errors import invalid
from . import clock, holds
from .fixture import derive_openings
from .store import State, claim_key
from .validation import HANDLE_RE

TRACK = "pocketful"
FORMAT_VERSION = 1


def export_document(state: State) -> dict:
    holds.expire_due(state)
    return {
        "track": TRACK, "format_version": FORMAT_VERSION,
        "state": {
            "currency": state.currency, "minor_units": state.minor_units,
            "users": list(state.users.values()), "tokens": dict(state.tokens),
            "payments": list(state.payments), "requests": list(state.requests.values()),
            "splits": list(state.splits), "settlements": list(state.settlements),
            "idempotency": list(state.idem.values()),
            "operators": sorted(state.operators), "seq": state.seq,
            "authorization_ttl_seconds": state.ttl,
            "authorizations": list(state.authorizations.values()),
            "opening": dict(state.opening),
            "statement_snapshots": list(state.snapshots.values()),
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
        d.setdefault("authorization_id", None)  # stage-1 exports predate this field
        state.index_payment({"seq": rec["seq"], "ts": rec["ts"], "data": d,
                             "revs": _revisions(rec, d)})
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
    ttl = raw.get("authorization_ttl_seconds", 600)
    _check(_is_int(ttl) and ttl >= 1, "authorization_ttl_seconds")
    state.ttl = ttl
    if "opening" in raw:
        opening = raw["opening"]
        _check(isinstance(opening, dict) and set(opening) == set(state.users)
               and all(_is_int(v) for v in opening.values()), "opening")
        state.opening = dict(opening)
    else:   # an earlier stage's export: nothing was ever corrected, so derive it
        derive_openings(state)
    for rec in _records(raw.get("authorizations", []), "authorizations"):
        d = rec["data"]
        _check(_is_int(rec.get("expires_ts")) and d["from_user_id"] in state.users
               and d["to_user_id"] in state.users and d["status"] in
               ("open", "captured", "voided", "expired")
               and _is_int(d["amount"]) and _is_int(d["captured_amount"])
               and _is_int(d["remaining_amount"]) and isinstance(d["payment_ids"], list)
               and d["authorization_id"] not in state.authorizations)
        d.setdefault("closed_at", None)
        state.authorizations[d["authorization_id"]] = {
            "seq": rec["seq"], "ts": rec["ts"], "expires_ts": rec["expires_ts"], "data": d,
            "hold": _hold(state, rec, d)}
    for frozen in raw.get("statement_snapshots", []):   # absent in earlier stages' exports
        _check(isinstance(frozen, dict) and isinstance(frozen["token"], str)
               and frozen["uid"] in state.users and _is_int(frozen["opening_balance"])
               and _is_int(frozen["closing_balance"]) and frozen["token"] not in state.snapshots
               and (frozen["known_at"] is None or isinstance(frozen["known_at"], str))
               and isinstance(frozen["entries"], list), "statement snapshot")
        for row in frozen["entries"]:
            _check(isinstance(row, list) and len(row) == 7 and row[0] in state.payment_index
                   and all(_is_int(row[i]) for i in (1, 2, 3, 4))
                   and isinstance(row[5], str) and isinstance(row[6], str), "statement snapshot entry")
        state.snapshots[frozen["token"]] = {k: frozen[k] for k in (
            "token", "uid", "opening_balance", "closing_balance", "entries", "known_at")}
    operators = raw["operators"]
    _check(isinstance(operators, list) and all(isinstance(o, str) for o in operators))
    state.operators = set(operators)
    _check(_is_int(raw["seq"]))
    state.seq = raw["seq"]
    return state


def _revisions(rec: dict, data: dict) -> list:
    """Revision history of an imported payment; an earlier stage's payment has only revision 1."""
    revs = rec.get("revs")
    if revs is None:
        stamp = clock.parse(data["created_at"])
        _check(stamp is not None, "payment created_at")
        return [{"revision": 1, "amount": data["amount"], "effective_at": data["created_at"],
                 "effective_ts": stamp.ts, "recorded_at": data["created_at"],
                 "recorded_ts": stamp.ts, "reason": ""}]
    _check(isinstance(revs, list) and revs, "revisions")
    for number, rev in enumerate(revs, 1):
        _check(isinstance(rev, dict) and rev["revision"] == number and _is_int(rev["amount"])
               and _is_int(rev["effective_ts"]) and _is_int(rev["recorded_ts"])
               and isinstance(rev["effective_at"], str) and isinstance(rev["recorded_at"], str)
               and isinstance(rev["reason"], str), "revision")
    return revs


def _hold(state: State, rec: dict, data: dict) -> dict:
    """Hold lifecycle of an imported authorization; an earlier stage's is reconstructed."""
    hold = rec.get("hold")
    if hold is not None:
        _check(isinstance(hold, dict) and (hold["start_ts"] is None or _is_int(hold["start_ts"]))
               and (hold["end_ts"] is None or _is_int(hold["end_ts"]))
               and all(_is_int(c[0]) and _is_int(c[1]) for c in hold["captures"]), "hold")
        return hold
    captures = []
    for pid in data["payment_ids"]:
        payment = state.payment_index.get(pid)
        _check(payment is not None, "capture payment")
        captures.append([payment["revs"][0]["effective_ts"], payment["data"]["amount"]])
    end = None
    if data["status"] == "captured" and captures:
        end = captures[-1][0]
    elif data["status"] == "expired":
        end = rec["expires_ts"]
    elif data["status"] == "voided":
        end = rec["ts"]   # the void time was not recorded before stage 3
    if data["status"] != "open":
        data["closed_at"] = clock.from_ts(end).text if end is not None else data["created_at"]
    return {"start_ts": rec["ts"], "captures": captures, "end_ts": end}
