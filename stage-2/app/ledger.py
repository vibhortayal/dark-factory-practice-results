"""Money movement and record construction. Callers check balances first."""
from .store import new_id


def payment_data(state, sender, receiver, amount, note, visibility, stamp,
                 request_id=None, settlement_id=None, payment_id=None,
                 authorization_id=None) -> dict:
    return {
        "payment_id": payment_id or new_id("p_"),
        "from_user_id": sender["id"], "from_handle": sender["handle"],
        "to_user_id": receiver["id"], "to_handle": receiver["handle"],
        "amount": amount, "currency": state.currency, "note": note,
        "visibility": visibility, "request_id": request_id,
        "settlement_id": settlement_id, "authorization_id": authorization_id,
        "created_at": stamp.text,
    }


def transfer(state, sender, receiver, amount, note, visibility, stamp,
             request_id=None, settlement_id=None, authorization_id=None) -> dict:
    """Debit and credit together, record the payment, return its public body."""
    sender["balance"] -= amount
    receiver["balance"] += amount
    data = payment_data(state, sender, receiver, amount, note, visibility, stamp,
                        request_id, settlement_id, authorization_id=authorization_id)
    state.add_payment(data, stamp.ts)
    return dict(data)


def request_data(state, requester, payer, amount, note, stamp, status="pending",
                 payment_id=None, request_id=None) -> dict:
    return {
        "request_id": request_id or new_id("rq_"),
        "requester_id": requester["id"], "requester_handle": requester["handle"],
        "payer_id": payer["id"], "payer_handle": payer["handle"],
        "amount": amount, "currency": state.currency, "note": note,
        "status": status, "payment_id": payment_id, "created_at": stamp.text,
    }


def equal_split(amount: int, n: int) -> list:
    """Whole-unit shares summing to amount; the extra units go to the first shares."""
    base, extra = divmod(amount, n)
    return [base + (1 if i < extra else 0) for i in range(n)]
