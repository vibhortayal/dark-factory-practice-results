"""GET /me."""
from .. import holds, operation
from ..store import store


def get_me(req):
    with store.lock:
        operation.begin()
        user = store.user(req.user_id)
        held = holds.held_of(user["id"])
        return 200, {"user_id": user["id"], "display_name": user["display_name"],
                     "handle": user["handle"], "balance": user["balance"],
                     "total": user["balance"], "available": user["balance"] - held, "held": held,
                     "currency": store.currency, "minor_units": store.minor_units}
