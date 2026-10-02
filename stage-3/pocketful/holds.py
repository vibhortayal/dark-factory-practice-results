"""Holds on wallets: what is reserved, what is available, and their history.

`available = total - held`. Currently `held` is the remaining amount of every open
authorization the user is paying (`held_of`). For a historical view (T, K) --
T = the instant looked at, K = what was known by then -- `held_at` replays the
authorization's lifecycle: it holds from creation, shrinks with each capture, and
is released at its release time. Events other than clock expiry are known at their
own time; once creation is known the expiry deadline is known too.
Callers hold `store.locked()`.
"""
from .store import store
from .timefmt import parse_iso


def held_of(user_id):
    return sum(a["remaining_amount"] for a in store.open_auths.values()
               if a["from_user_id"] == user_id)


def available_of(user):
    return user["balance"] - held_of(user["id"])


def close(authorization, status):
    """Leave `open`: the remainder is released, capture records are kept."""
    authorization["status"] = status
    authorization["remaining_amount"] = 0
    authorization["closed_at"] = authorization["expires_at"] if status == "expired" else store.stamp()
    store.open_auths.pop(authorization["authorization_id"], None)


def sweep():
    """Mark every open authorization whose deadline has passed as expired (at store.now)."""
    now = store.now
    for aid, authorization in list(store.open_auths.items()):
        if store.expiries[aid] <= now:
            close(authorization, "expired")


# ---- history ----
def captures(authorization):
    """[(instant, amount)] of every capture of this authorization."""
    out = []
    for pid in authorization["payment_ids"]:
        payment = store.payments_by_id.get(pid)
        if payment is not None:
            out.append((store.created_dt[pid], payment["amount"]))
    return out


def release_time(authorization, known=None):
    """When the remainder stops being held, given what is known (all, if known is None)."""
    expires = store.expiries[authorization["authorization_id"]]
    if authorization["status"] in ("captured", "voided") and authorization.get("closed_at"):
        closed = parse_iso(authorization["closed_at"])
        if known is None or closed <= known:
            return min(closed, expires)
    return expires


def held_at(authorization, at, known=None):
    horizon = at if known is None else min(at, known)
    if parse_iso(authorization["created_at"]) > horizon or release_time(authorization, known) <= at:
        return 0
    return authorization["amount"] - sum(x for t, x in captures(authorization) if t <= horizon)


def held_total_at(user_id, at, known=None):
    return sum(held_at(a, at, known) for a in store.auths_by_payer.get(user_id, ()))


def hold_steps(authorization):
    """[(instant, change in held)] over the whole (fully known) lifecycle."""
    created = parse_iso(authorization["created_at"])
    release = release_time(authorization)
    if release <= created:
        return []
    caps = sorted(captures(authorization))
    steps = [(created, authorization["amount"])] + [(t, -x) for t, x in caps]
    remaining = authorization["amount"] - sum(x for t, x in caps if t <= release)
    if remaining > 0:
        steps.append((release, -remaining))
    return steps
