"""Authorization holds: what is reserved, what is spendable, and clock expiry.

An open authorization reserves its remaining amount on the payer's wallet. Expiry is
evaluated lazily: `expire_due` runs under the global lock before every authenticated
request, export and reset, so every read sees the clock-correct status.
"""
from . import clock


def open_holds(state):
    return [rec for rec in state.authorizations.values() if rec["data"]["status"] == "open"]


def held_of(state, uid: str) -> int:
    return sum(rec["data"]["remaining_amount"] for rec in open_holds(state)
               if rec["data"]["from_user_id"] == uid)


def available(state, user: dict) -> int:
    return user["balance"] - held_of(state, user["id"])


def expire_due(state, now_ts=None):
    """Close every open authorization whose deadline has passed, releasing its remainder."""
    now_ts = clock.now().ts if now_ts is None else now_ts
    for rec in open_holds(state):
        if rec["expires_ts"] <= now_ts:
            rec["data"]["status"] = "expired"
            rec["data"]["remaining_amount"] = 0


def auth_data(state, payer, payee, amount, note, visibility, created, expires, **overrides) -> dict:
    data = {
        "authorization_id": None,
        "from_user_id": payer["id"], "from_handle": payer["handle"],
        "to_user_id": payee["id"], "to_handle": payee["handle"],
        "amount": amount, "captured_amount": 0, "remaining_amount": amount,
        "currency": state.currency, "note": note, "visibility": visibility,
        "status": "open", "expires_at": expires.text, "payment_id": None,
        "payment_ids": [], "created_at": created.text,
    }
    data.update(overrides)
    return data
