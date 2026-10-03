"""Payment corrections (append-only revisions) and the revision history."""
from decimal import Decimal

from .. import clock, history, holds
from ..errors import conflict, forbidden, invalid, not_found
from ..validation import MAX_AMOUNT


def _whole(value, low, high=None):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            return None
    elif not isinstance(value, int):
        return None
    if value < low or (high is not None and value > high):
        return None
    return int(value)


def _fields(body, now_ts):
    for name in ("expected_revision", "amount", "effective_at", "reason"):
        if name not in body:
            raise invalid("%s is required" % name)
    expected = _whole(body["expected_revision"], 1)
    amount = _whole(body["amount"], 0, MAX_AMOUNT)
    reason = body["reason"]
    effective = clock.parse(body["effective_at"])
    if expected is None:
        raise invalid("expected_revision must be a positive integer")
    if amount is None:
        raise invalid("amount must be an integer from 0 to %d" % MAX_AMOUNT)
    if not isinstance(reason, str) or not 1 <= len(reason) <= 200:
        raise invalid("reason must be 1 to 200 characters")
    if effective is None:
        raise invalid("effective_at must be an RFC 3339 instant with an offset")
    if effective.ts > now_ts:
        raise invalid("effective_at must not be in the future")
    return expected, amount, effective, reason


def _public(payment_id, rev):
    return {"payment_id": payment_id, "revision": rev["revision"], "amount": rev["amount"],
            "effective_at": rev["effective_at"], "recorded_at": rev["recorded_at"],
            "reason": rev["reason"], "correction_batch_id": rev.get("correction_batch_id")}


def check_refund_floor(state, payment_id, amount):
    """A correction cannot reduce a payment below what has already been refunded."""
    if amount < state.refunds.get(payment_id, 0):
        raise invalid("the amount is below what was already refunded", "refund_exceeds_payment")


def correct(ctx):
    state, user = ctx.state, ctx.user
    rec = state.payment_index.get(ctx.params[0])
    if rec is None:
        raise not_found("no such payment")
    data = rec["data"]
    if data["from_user_id"] != user["id"]:
        raise forbidden("only the sender may correct a payment")
    now = clock.now()
    expected, amount, effective, reason = _fields(ctx.body, now.ts)
    if data["settlement_id"] is not None or data["authorization_id"] is not None \
            or data.get("refund_of") is not None:
        raise invalid("settlement members, captures and refunds cannot be corrected",
                      "linked_payment_immutable")
    current = rec["revs"][-1]
    if expected != current["revision"]:
        raise conflict("stale_revision", "the payment has a newer revision")
    check_refund_floor(state, data["payment_id"], amount)
    sender, receiver = state.users[data["from_user_id"]], state.users[data["to_user_id"]]
    diff = amount - current["amount"]
    payer = sender if diff > 0 else receiver     # who is debited by the change
    if diff != 0 and holds.available(state, payer) < abs(diff):
        raise conflict("insufficient_funds", "the wallet cannot cover the change")
    recorded = clock.now()
    revision = {"revision": current["revision"] + 1, "amount": amount,
                "effective_at": effective.text, "effective_ts": effective.ts,
                "recorded_at": recorded.text, "recorded_ts": recorded.ts, "reason": reason,
                "correction_batch_id": None}
    rec["revs"].append(revision)
    if history.overdrawn(state, sender["id"], recorded.ts) or history.overdrawn(state, receiver["id"], recorded.ts):
        rec["revs"].pop()
        raise conflict("historical_overdraft", "the correction would overdraw a wallet in the past")
    sender["balance"] -= diff
    receiver["balance"] += diff
    return 201, _public(data["payment_id"], revision)


def revisions(ctx):
    rec = ctx.state.payment_index.get(ctx.params[0])
    if rec is None or ctx.user["id"] not in (rec["data"]["from_user_id"], rec["data"]["to_user_id"]):
        raise not_found("no such payment")
    return 200, {"revisions": [_public(rec["data"]["payment_id"], rev) for rev in rec["revs"]]}
