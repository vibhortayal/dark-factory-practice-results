"""GET /activity."""
from ..validation import parse_page


def feed(ctx):
    uid = ctx.user["id"]
    limit, offset = parse_page(ctx.query)
    visible = [rec for rec in ctx.state.payments
               if rec["data"]["visibility"] == "public"
               or uid in (rec["data"]["from_user_id"], rec["data"]["to_user_id"])]
    visible.sort(key=lambda r: (r["ts"], r["seq"]), reverse=True)
    page = visible[offset:offset + limit]
    return 200, {"payments": [dict(r["data"]) for r in page],
                 "has_more": offset + limit < len(visible)}
