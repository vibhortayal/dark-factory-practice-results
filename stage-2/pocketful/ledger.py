"""Moving money and building request/payment records. Caller holds store.lock."""
from . import holds
from .errors import insufficient_funds
from .store import store


def make_payment(sender, receiver, amount, note, visibility,
                 request_id=None, settlement_id=None, authorization_id=None,
                 created_at=None):
    """Record a payment and move its money. The funds check is the caller's job."""
    sender["balance"] -= amount
    receiver["balance"] += amount
    payment = {
        "payment_id": store.new_id("p"),
        "from_user_id": sender["id"], "from_handle": sender["handle"],
        "to_user_id": receiver["id"], "to_handle": receiver["handle"],
        "amount": amount, "currency": store.currency, "note": note,
        "visibility": visibility, "request_id": request_id,
        "settlement_id": settlement_id, "authorization_id": authorization_id,
        "created_at": created_at or store.stamp(),
    }
    store.state["payments"].append(payment)
    return dict(payment)


def pay(sender, receiver, amount, note, visibility, **links):
    if holds.available_of(sender) < amount:
        raise insufficient_funds()
    return make_payment(sender, receiver, amount, note, visibility, **links)


def make_request(requester, payer, amount, note, created_at):
    request = {
        "request_id": store.new_id("rq"),
        "requester_id": requester["id"], "requester_handle": requester["handle"],
        "payer_id": payer["id"], "payer_handle": payer["handle"],
        "amount": amount, "currency": store.currency, "note": note,
        "status": "pending", "payment_id": None, "created_at": created_at,
    }
    store.add_request(request)
    return request
