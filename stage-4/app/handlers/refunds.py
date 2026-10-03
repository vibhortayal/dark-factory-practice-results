"""POST /payments/{id}/refunds: the receiver sends part or all of a payment back."""
from .. import clock, holds, ledger
from ..errors import conflict, forbidden, invalid, not_found
from ..validation import parse_amount


def refund(ctx):
    state, user = ctx.state, ctx.user
    rec = state.payment_index.get(ctx.params[0])
    if rec is None:
        raise not_found("no such payment")
    data = rec["data"]
    if data["to_user_id"] != user["id"]:
        raise forbidden("only the receiver may refund a payment")
    if data.get("refund_of") is not None:
        raise invalid("a refund cannot be refunded", "invalid_refund_target")
    if "amount" not in ctx.body:
        raise invalid("amount is required")
    amount = parse_amount(ctx.body["amount"])
    corrected = rec["revs"][-1]["amount"]
    if state.refunds.get(data["payment_id"], 0) + amount > corrected:
        raise invalid("refunds would exceed the payment's current amount", "refund_exceeds_payment")
    if holds.available(state, user) < amount:
        raise conflict("insufficient_funds", "available balance is below the amount")
    sender = state.users[data["from_user_id"]]
    return 201, ledger.transfer(state, user, sender, amount, data["note"], data["visibility"],
                                clock.now(), refund_of=data["payment_id"])
