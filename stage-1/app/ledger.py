"""Moving money: the only place balances and payment records are written."""


def record_payment(store, sender, receiver, amount, note, visibility, created_at,
                   request_id=None, settlement_id=None):
    """Debit/credit and append the payment. Caller has already checked funds."""
    store.balances[sender["id"]] -= amount
    store.balances[receiver["id"]] += amount
    payment = {
        "payment_id": store.new_id("p_", store.payments),
        "from_user_id": sender["id"], "from_handle": sender["handle"],
        "to_user_id": receiver["id"], "to_handle": receiver["handle"],
        "amount": amount, "currency": store.currency, "note": note,
        "visibility": visibility, "request_id": request_id,
        "settlement_id": settlement_id, "created_at": created_at,
    }
    store.payments[payment["payment_id"]] = payment
    return payment


def record_request(store, requester, payer, amount, note, created_at, split_id=None):
    request = {
        "request_id": store.new_id("rq_", store.requests),
        "requester_id": requester["id"], "requester_handle": requester["handle"],
        "payer_id": payer["id"], "payer_handle": payer["handle"],
        "amount": amount, "currency": store.currency, "note": note,
        "status": "pending", "payment_id": None, "created_at": created_at,
        "split_id": split_id,
    }
    store.requests[request["request_id"]] = request
    return request


