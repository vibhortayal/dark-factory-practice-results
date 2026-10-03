"""GET /me."""
from .. import holds


def get_me(ctx):
    user = ctx.user
    held = holds.held_of(ctx.state, user["id"])
    return 200, {"user_id": user["id"], "display_name": user["display_name"],
                 "handle": user["handle"], "balance": user["balance"],
                 "total": user["balance"], "available": user["balance"] - held, "held": held,
                 "currency": ctx.state.currency, "minor_units": ctx.state.minor_units}
