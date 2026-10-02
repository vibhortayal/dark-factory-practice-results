"""GET /me, POST /payments, GET /activity."""
from . import clock, fields, idempotency, ledger
from .errors import conflict, invalid, not_found
from .request import authenticate
from .store import LOCK, current
from .views import payment_view


def me(req):
    with LOCK:
        store = current()
        user = authenticate(req, store)
        return 200, {"user_id": user["id"], "display_name": user["display_name"],
                     "handle": user["handle"], "balance": store.balances[user["id"]],
                     "currency": store.currency, "minor_units": store.minor_units}


def parse_transfer(store, entry, sender_field, receiver_field, sender=None):
    """Validate one payment-like entry; return (sender, receiver, amount, note, visibility)."""
    names = (receiver_field,) if sender else (sender_field, receiver_field)
    values = fields.handles(entry, names)
    amount = fields.amount(entry)
    note = fields.note(entry)
    visibility = fields.visibility(entry)
    if sender is None:
        sender = store.user_by_handle(values[0])
        if sender is None:
            raise not_found("no such user")
    receiver = store.user_by_handle(values[-1])
    if receiver is None:
        raise not_found("no such user")
    if receiver["id"] == sender["id"]:
        raise invalid("cannot pay yourself", code="self_payment")
    return sender, receiver, amount, note, visibility


def create_payment(req):
    with LOCK:
        store = current()
        user = authenticate(req, store)

        def effect(body):
            sender, receiver, amount, note, visibility = parse_transfer(
                store, body, "from_handle", "to_handle", sender=user)
            if store.balances[sender["id"]] < amount:
                raise conflict("insufficient_funds", "balance too low")
            return payment_view(ledger.record_payment(
                store, sender, receiver, amount, note, visibility, clock.now()))

        return idempotency.run(req, store, user, effect)


def activity(req):
    with LOCK:
        store = current()
        user = authenticate(req, store)
        limit, offset = fields.page_params(req.query)
        uid = user["id"]
        visible = [payment_view(p) for p in reversed(store.payments.values())
                   if p["visibility"] == "public" or uid in (p["from_user_id"], p["to_user_id"])]
        page, more = fields.paginate(visible, limit, offset)
        return 200, {"payments": page, "has_more": more}
