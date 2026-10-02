"""GET /me, optionally as of an instant and as known at an instant."""
from .. import history, holds
from ..store import store
from ..validation import query_instant


def get_me(req):
    as_of, as_of_dt = query_instant(req.query, "as_of")
    known_at, known_dt = query_instant(req.query, "known_at")
    with store.locked():
        user = store.user(req.user_id)
        if as_of is None and known_at is None:
            total, held = user["balance"], holds.held_of(user["id"])
        else:
            at = as_of_dt or store.now
            known = known_dt or store.now
            total = history.total_at(user["id"], at, known)
            held = holds.held_total_at(user["id"], at, known)
        body = {"user_id": user["id"], "display_name": user["display_name"],
                "handle": user["handle"], "balance": total,
                "total": total, "available": total - held, "held": held,
                "currency": store.currency, "minor_units": store.minor_units}
        if as_of is not None:
            body["as_of"] = as_of
        if known_at is not None:
            body["known_at"] = known_at
        return 200, body
