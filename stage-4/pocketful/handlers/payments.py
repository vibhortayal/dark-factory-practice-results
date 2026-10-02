"""POST /payments."""
from .. import ledger
from ..errors import ApiError, not_found
from ..idempotency import run_idempotent
from ..store import store
from ..validation import parse_amount, parse_note, parse_visibility, string_field


def create_payment(req):
    return run_idempotent(req, lambda body: _execute(req.user_id, body))


def _execute(user_id, body):
    to_handle = string_field(body, "to_handle")
    amount = parse_amount(body)
    note = parse_note(body)
    visibility = parse_visibility(body)
    sender = store.user(user_id)
    if to_handle == sender["handle"]:
        raise ApiError(422, "self_payment", "cannot pay yourself")
    receiver = store.by_handle.get(to_handle)
    if receiver is None:
        raise not_found("no user has that handle")
    return ledger.pay(sender, receiver, amount, note, visibility)
