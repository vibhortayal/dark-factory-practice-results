"""Holds on wallets: what is reserved, what is available, and clock expiry.

`available = total - held`, where `held` is the remaining amount of every open
authorization the user is paying. Callers hold `store.lock`.
"""
from .store import store


def held_of(user_id):
    return sum(a["remaining_amount"] for a in store.open_auths.values()
               if a["from_user_id"] == user_id)


def available_of(user):
    return user["balance"] - held_of(user["id"])


def close(authorization, status):
    """Leave `open`: the remainder is released, capture records are kept."""
    authorization["status"] = status
    authorization["remaining_amount"] = 0
    store.open_auths.pop(authorization["authorization_id"], None)


def sweep():
    """Mark every open authorization whose deadline has passed as expired (at store.now)."""
    now = store.now
    for aid, authorization in list(store.open_auths.items()):
        if store.expiries[aid] <= now:
            close(authorization, "expired")
