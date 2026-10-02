"""Validation of an internal state dict (what import accepts, what export emits).

`check_state` is the single gate every loaded state passes. A stage-1 export is
upgraded in place: missing stage-2 keys get their defaults. Anything invalid is
422 validation_failed, before any live state is touched.
"""
from .errors import invalid
from .stateupgrade import upgrade_state
from .statebase import MAX_BALANCE, is_id, is_int, known, need, shallow, unique_ids
from .timefmt import parse_iso
from .validation import AUTH_STATUSES, HANDLE_RE, STATUSES, VISIBILITIES

DEFAULT_TTL = 600


def _check_users(state, seen):
    handles, emails = set(), set()
    for uid, user in state["users"].items():
        need(is_id(uid) and isinstance(user, dict) and user.get("id") == uid, "user id")
        need(isinstance(user.get("handle"), str) and HANDLE_RE.fullmatch(user["handle"]), "handle")
        need(isinstance(user.get("email"), str), "email")
        need(isinstance(user.get("display_name"), str), "display_name")
        need(isinstance(user.get("password_hash"), str), "password_hash")
        need(is_int(user.get("balance")) and 0 <= user["balance"] <= MAX_BALANCE, "balance")
        need(user["handle"] not in handles and user["email"] not in emails, "duplicate user")
        handles.add(user["handle"])
        emails.add(user["email"])
        seen.add(uid)
    users = state["users"]
    for token, uid in state["tokens"].items():
        need(isinstance(token, str) and known(users, uid), "token")
    need(all(known(users, uid) for uid in state["operators"]), "operators")


def _check_payments(state, seen):
    users = state["users"]
    for p in state["payments"]:
        need(isinstance(p, dict), "payment")
        p.setdefault("authorization_id", None)  # stage-1 exports have none
    unique_ids(state["payments"], "payment_id", seen)
    for p in state["payments"]:
        need(known(users, p.get("from_user_id")) and known(users, p.get("to_user_id")), "payment parties")
        need(p["from_handle"] == users[p["from_user_id"]]["handle"]
             and p["to_handle"] == users[p["to_user_id"]]["handle"], "payment handles")
        need(is_int(p.get("amount")) and p["amount"] >= 0, "payment amount")
        need(isinstance(p.get("note"), str) and p.get("visibility") in VISIBILITIES, "payment")
        need(p.get("currency") == state["currency"], "payment currency")
        for link in ("request_id", "settlement_id", "authorization_id"):
            need(p.get(link) is None or isinstance(p[link], str), link)
        need(parse_iso(p.get("created_at")) is not None, "created_at")


def _check_requests(state, seen):
    users = state["users"]
    for r in state["requests"]:
        need(isinstance(r, dict), "request")
    unique_ids(state["requests"], "request_id", seen)
    for r in state["requests"]:
        need(known(users, r.get("requester_id")) and known(users, r.get("payer_id")), "request parties")
        need(r["requester_handle"] == users[r["requester_id"]]["handle"]
             and r["payer_handle"] == users[r["payer_id"]]["handle"], "request handles")
        need(is_int(r.get("amount")) and r["amount"] >= 0, "request amount")
        need(isinstance(r.get("note"), str) and r.get("status") in STATUSES, "request")
        need(r.get("currency") == state["currency"], "request currency")
        need(r.get("payment_id") is None or isinstance(r["payment_id"], str), "payment_id")
        need(parse_iso(r.get("created_at")) is not None, "created_at")


def check_authorizations(state, seen, now):
    """Shape of every authorization, and open unexpired holds within each balance."""
    users, held = state["users"], {}
    unique_ids(state["authorizations"], "authorization_id", seen)
    for a in state["authorizations"]:
        need(known(users, a.get("from_user_id")) and known(users, a.get("to_user_id")), "authorization parties")
        need(a["from_user_id"] != a["to_user_id"], "authorization parties")
        need(a["from_handle"] == users[a["from_user_id"]]["handle"]
             and a["to_handle"] == users[a["to_user_id"]]["handle"], "authorization handles")
        need(is_int(a.get("amount")) and 1 <= a["amount"] <= MAX_BALANCE, "authorization amount")
        need(is_int(a.get("captured_amount")) and 0 <= a["captured_amount"] <= a["amount"], "captured_amount")
        need(isinstance(a.get("note"), str) and a.get("visibility") in VISIBILITIES, "authorization")
        need(a.get("currency") == state["currency"] and a.get("status") in AUTH_STATUSES, "authorization")
        need(is_int(a.get("remaining_amount")), "remaining_amount")
        need(a["remaining_amount"] == (a["amount"] - a["captured_amount"] if a["status"] == "open" else 0),
             "remaining_amount does not match status")
        need(a.get("payment_id") is None or isinstance(a["payment_id"], str), "payment_id")
        ids = a.get("payment_ids")
        need(isinstance(ids, list) and all(isinstance(i, str) for i in ids), "payment_ids")
        expires = parse_iso(a.get("expires_at"))
        need(expires is not None and parse_iso(a.get("created_at")) is not None, "authorization times")
        need((a["status"] == "open") == (a.get("closed_at") is None), "closed_at does not match status")
        need(a.get("closed_at") is None or parse_iso(a["closed_at"]) is not None, "closed_at")
        if a["status"] == "open" and expires > now:
            held[a["from_user_id"]] = held.get(a["from_user_id"], 0) + a["remaining_amount"]
    for uid, total in held.items():
        need(total <= users[uid]["balance"], "open holds exceed a balance")


def _check_idempotency(state):
    keys = set()
    for rec in state["idempotency"]:
        need(isinstance(rec, dict), "idempotency record")
        for name in ("user_id", "path", "key", "fingerprint"):
            need(isinstance(rec.get(name), str), "idempotency record")
        need(known(state["users"], rec["user_id"]) and isinstance(rec.get("response"), dict)
             and shallow(rec["response"]), "idempotency record")
        ident = (rec["user_id"], rec["path"], rec["key"])
        need(ident not in keys, "duplicate idempotency record")
        keys.add(ident)


def _check_history(state):
    users = state["users"]
    need(isinstance(state.get("revisions"), dict) and isinstance(state.get("opening_balances"), dict)
         and isinstance(state.get("snapshots"), dict), "history")
    payments = {p["payment_id"]: p for p in state["payments"]}
    need(set(state["revisions"]) == set(payments), "every payment needs a revision history")
    for pid, revs in state["revisions"].items():
        need(isinstance(revs, list) and revs, "revisions")
        previous = None
        for number, rev in enumerate(revs, start=1):
            need(isinstance(rev, dict) and rev.get("payment_id") == pid and rev.get("revision") == number, "revision")
            need(is_int(rev.get("amount")) and 0 <= rev["amount"] <= MAX_BALANCE, "revision amount")
            need(isinstance(rev.get("reason"), str), "revision reason")
            effective, recorded = parse_iso(rev.get("effective_at")), parse_iso(rev.get("recorded_at"))
            need(effective is not None and recorded is not None, "revision times")
            need(previous is None or recorded > previous, "recorded_at must strictly increase")
            previous = recorded
    for uid, value in state["opening_balances"].items():
        need(known(users, uid) is not None and is_int(value), "opening balance")
    need(all(uid in state["opening_balances"] for uid in users), "opening balance missing")
    for token, snap in state["snapshots"].items():
        need(isinstance(token, str) and isinstance(snap, dict) and snap.get("token") == token, "snapshot")
        need(known(users, snap.get("user_id")) is not None, "snapshot user")
        need(parse_iso(snap.get("to_at")) is not None and parse_iso(snap.get("known_at")) is not None, "snapshot")
        need(snap.get("from_at") is None or parse_iso(snap["from_at"]) is not None, "snapshot")
        need(snap.get("known_echo") is None or isinstance(snap["known_echo"], str), "snapshot")


def check_state(state, now):
    """Validate an internal state dict (as produced by Store.dump); `now` is the
    operation's instant. Older exports are upgraded in place first."""
    need(isinstance(state, dict), "state must be an object")
    state.setdefault("authorizations", [])
    upgrade_state(state)
    state.setdefault("authorization_ttl_seconds", DEFAULT_TTL)
    for key, kind in (("users", dict), ("tokens", dict), ("payments", list), ("requests", list),
                      ("splits", list), ("settlements", list), ("operators", list),
                      ("idempotency", list), ("authorizations", list)):
        need(isinstance(state.get(key), kind), f"state.{key} is missing or the wrong type")
    need(isinstance(state.get("currency"), str) and state["currency"], "currency")
    need(state.get("minor_units") in (0, 2, 3) and is_int(state["minor_units"]), "minor_units")
    ttl = state["authorization_ttl_seconds"]
    need(is_int(ttl) and ttl >= 1, "authorization_ttl_seconds")
    seen = set()
    _check_users(state, seen)
    _check_payments(state, seen)
    _check_requests(state, seen)
    unique_ids(state["splits"], "split_id", seen)
    unique_ids(state["settlements"], "settlement_id", seen)
    check_authorizations(state, seen, now)
    _check_idempotency(state)
    _check_history(state)
    return state


def check_export(document, now):
    """Validate a whole export envelope and return its state."""
    need(isinstance(document, dict), "export must be an object")
    need(document.get("track") == "pocketful", "wrong track")
    need(is_int(document.get("format_version")) and document["format_version"] == 1,
         "unsupported format_version")
    need("state" in document, "state is missing")
    try:
        return check_state(document["state"], now)
    except (KeyError, TypeError, AttributeError, ValueError):
        raise invalid("invalid state")
