"""POST /payments."""
from .. import clock, ledger
from ..errors import conflict, invalid, not_found
from ..validation import parse_amount, parse_note, parse_visibility, require_string


def create(ctx):
    body, state, user = ctx.body, ctx.state, ctx.user
    to_handle = require_string(body, "to_handle")
    amount = parse_amount(body.get("amount"))
    note = parse_note(body)
    visibility = parse_visibility(body)
    if to_handle == user["handle"]:
        raise invalid("cannot pay yourself", "self_payment")
    receiver = state.user_by_handle(to_handle)
    if receiver is None:
        raise not_found("no user with that handle")
    if user["balance"] < amount:
        raise conflict("insufficient_funds", "balance is below the amount")
    return 201, ledger.transfer(state, user, receiver, amount, note, visibility, clock.now())
