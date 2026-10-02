"""Bring an older (stage-1 or stage-2) exported state up to the current shape.

Fills only what is missing, tolerating malformed input (check_state rejects it
afterwards). Rules for history that older exports cannot carry:
  * every payment gets revision 1 with effective_at = recorded_at = created_at;
  * a user's opening balance = balance minus the net effect of all payments;
  * a hold closed by a final capture is closed at that capture's time, an expired
    one at expires_at, and a voided one (void time not recorded) at its last
    capture's time or, with no capture, at its creation.
"""


def _payments(state):
    items = state.get("payments")
    return [p for p in items if isinstance(p, dict)] if isinstance(items, list) else []


def _derive_revisions(state):
    state["revisions"] = {
        p["payment_id"]: [{"payment_id": p["payment_id"], "revision": 1, "amount": p.get("amount"),
                           "effective_at": p.get("created_at"), "recorded_at": p.get("created_at"),
                           "reason": ""}]
        for p in _payments(state) if isinstance(p.get("payment_id"), str)}


def _derive_openings(state):
    users = state.get("users")
    if not isinstance(users, dict):
        return
    openings = {}
    for uid, user in users.items():
        if isinstance(user, dict) and isinstance(user.get("balance"), int):
            openings[uid] = user["balance"]
    for p in _payments(state):
        amount = p.get("amount")
        if isinstance(amount, int) and p.get("from_user_id") in openings and p.get("to_user_id") in openings:
            openings[p["from_user_id"]] += amount
            openings[p["to_user_id"]] -= amount
    state["opening_balances"] = openings


def _derive_closed_at(state):
    by_id = {p.get("payment_id"): p for p in _payments(state)}
    for a in state.get("authorizations") or []:
        if not isinstance(a, dict) or "closed_at" in a:
            continue
        status = a.get("status")
        if status == "open":
            a["closed_at"] = None
        elif status == "expired":
            a["closed_at"] = a.get("expires_at")
        else:
            ids = a.get("payment_ids")
            last = by_id.get(ids[-1]) if isinstance(ids, list) and ids else None
            a["closed_at"] = last.get("created_at") if last else a.get("created_at")


def upgrade_state(state):
    if not isinstance(state, dict):
        return state
    if "revisions" not in state:
        _derive_revisions(state)
    if "opening_balances" not in state:
        _derive_openings(state)
    state.setdefault("snapshots", {})
    _derive_closed_at(state)
    return state
