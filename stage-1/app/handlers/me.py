"""GET /me."""


def get_me(ctx):
    user = ctx.user
    return 200, {"user_id": user["id"], "display_name": user["display_name"],
                 "handle": user["handle"], "balance": user["balance"],
                 "currency": ctx.state.currency, "minor_units": ctx.state.minor_units}
