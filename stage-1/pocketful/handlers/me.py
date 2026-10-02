"""GET /me."""
from ..store import store


def get_me(req):
    with store.lock:
        user = store.user(req.user_id)
        return 200, {"user_id": user["id"], "display_name": user["display_name"],
                     "handle": user["handle"], "balance": user["balance"],
                     "currency": store.currency, "minor_units": store.minor_units}
