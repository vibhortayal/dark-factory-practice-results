"""POST /payments/{id}/refunds: the receiver sends money back, as a new payment."""
from .. import ledger
from ..errors import ApiError, forbidden, not_found
from ..idempotency import run_idempotent
from ..store import store
from ..validation import parse_amount


def create_refund(req):
    payment_id = req.params[0]
    return run_idempotent(req, lambda body: _refund(req.user_id, payment_id, body))


def _refund(user_id, payment_id, body):
    amount = parse_amount(body)
    payment = store.payments_by_id.get(payment_id)
    if payment is None:
        raise not_found("no such payment")
    if payment["to_user_id"] != user_id:
        raise forbidden("only the receiver may refund a payment")
    if payment.get("refund_of"):
        raise ApiError(422, "invalid_refund_target", "a refund cannot be refunded")
    cap = store.state["revisions"][payment_id][-1]["amount"]
    if store.refunded_total(payment_id) + amount > cap:
        raise ApiError(422, "refund_exceeds_payment", "refunds would exceed the payment's amount")
    # the refunder's AVAILABLE funds pay for it (ledger.pay: insufficient_funds)
    return ledger.pay(store.user(user_id), store.user(payment["from_user_id"]), amount,
                      payment["note"], payment["visibility"], refund_of=payment_id)
