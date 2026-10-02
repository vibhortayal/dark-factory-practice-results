"""GET /activity: payments that are public, or where the caller is a party."""
from ..store import store
from ..validation import page_params


def get_activity(req):
    limit, offset = page_params(req.query)
    uid = req.user_id
    with store.locked():
        visible = [p for p in reversed(store.state["payments"])
                   if p["visibility"] == "public" or uid in (p["from_user_id"], p["to_user_id"])]
        page = [dict(p) for p in visible[offset:offset + limit]]
        return 200, {"payments": page, "has_more": offset + limit < len(visible)}
