"""GET /me, current or as of an instant and as known at an instant."""
from .. import clock, history, holds
from ..errors import invalid


def _instant(query, name):
    if name not in query:
        return None
    stamp = clock.parse_query(query[name])
    if stamp is None:
        raise invalid("%s must be an RFC 3339 instant with an offset" % name)
    return stamp


def get_me(ctx):
    state, user, query = ctx.state, ctx.user, ctx.query
    as_of, known_at = _instant(query, "as_of"), _instant(query, "known_at")
    body = {"user_id": user["id"], "display_name": user["display_name"], "handle": user["handle"]}
    if as_of is None and known_at is None:
        held = holds.held_of(state, user["id"])
        body.update(balance=user["balance"], total=user["balance"],
                    available=user["balance"] - held, held=held)
    else:
        now_ts = clock.now().ts
        body.update(history.money_view(
            state, user["id"], now_ts if as_of is None else as_of.ts,
            now_ts if known_at is None else known_at.ts))
    body.update(currency=state.currency, minor_units=state.minor_units)
    if as_of is not None:
        body["as_of"] = as_of.text
    if known_at is not None:
        body["known_at"] = known_at.text
    return 200, body
