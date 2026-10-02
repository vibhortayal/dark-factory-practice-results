"""POST /payments/{id}/corrections and GET /payments/{id}/revisions."""
from .. import history, holds
from ..errors import ApiError, forbidden, insufficient_funds, invalid, not_found
from ..idempotency import run_idempotent
from ..store import store
from ..timefmt import parse_rfc3339
from ..validation import MAX_AMOUNT, integral


def _fields(body):
    """All four fields are required; anything invalid, of any type, is 422."""
    revision = integral(body.get("expected_revision"))
    amount = integral(body.get("amount"))
    reason = body.get("reason")
    effective = parse_rfc3339(body.get("effective_at"))
    if revision is None or revision < 1:
        raise invalid("expected_revision must be a positive integer")
    if amount is None or not 0 <= amount <= MAX_AMOUNT:
        raise invalid(f"amount must be an integer from 0 to {MAX_AMOUNT}")
    if not isinstance(reason, str) or not 1 <= len(reason) <= 200:
        raise invalid("reason must be a string of 1 to 200 characters")
    if effective is None:
        raise invalid("effective_at must be an RFC 3339 instant with an offset")
    if effective > store.now:
        raise invalid("effective_at must not be in the future")
    return revision, amount, effective, body["effective_at"], reason


def create_correction(req):
    payment_id = req.params[0]
    return run_idempotent(req, lambda body: _correct(req.user_id, payment_id, body))


def _correct(user_id, payment_id, body):
    expected, amount, effective, effective_text, reason = _fields(body)
    payment = store.payments_by_id.get(payment_id)
    if payment is None:
        raise not_found("no such payment")
    if payment["from_user_id"] != user_id:
        raise forbidden("only the sender may correct a payment")
    if payment["settlement_id"] or payment["authorization_id"]:
        raise ApiError(422, "linked_payment_immutable", "settlement members and captures cannot be corrected")
    revisions = store.state["revisions"][payment_id]
    if expected != len(revisions):
        raise ApiError(409, "stale_revision", "the payment has a newer revision")
    diff = amount - revisions[-1]["amount"]
    sender, receiver = store.user(payment["from_user_id"]), store.user(payment["to_user_id"])
    debited = sender if diff > 0 else receiver
    if diff != 0 and holds.available_of(debited) < abs(diff):
        raise insufficient_funds()
    history.check_no_overdraft([sender["id"], receiver["id"]], {payment_id: (amount, effective, effective_text)})
    sender["balance"] -= diff
    receiver["balance"] += diff
    revision = {"payment_id": payment_id, "revision": len(revisions) + 1, "amount": amount,
                "effective_at": effective_text, "recorded_at": store.stamp(), "reason": reason}
    store.add_revision(revision)
    return dict(revision)


def list_revisions(req):
    with store.locked():
        payment = store.payments_by_id.get(req.params[0])
        if payment is None or req.user_id not in (payment["from_user_id"], payment["to_user_id"]):
            raise not_found("no such payment")
        return 200, {"revisions": [dict(r) for r in store.state["revisions"][payment["payment_id"]]]}
