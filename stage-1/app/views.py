"""Public JSON shapes for payments, requests and users."""


def payment_view(p):
    return {
        "payment_id": p["payment_id"], "from_user_id": p["from_user_id"],
        "from_handle": p["from_handle"], "to_user_id": p["to_user_id"],
        "to_handle": p["to_handle"], "amount": p["amount"], "currency": p["currency"],
        "note": p["note"], "visibility": p["visibility"], "request_id": p["request_id"],
        "settlement_id": p["settlement_id"], "created_at": p["created_at"],
    }


def request_view(r):
    return {
        "request_id": r["request_id"], "requester_id": r["requester_id"],
        "requester_handle": r["requester_handle"], "payer_id": r["payer_id"],
        "payer_handle": r["payer_handle"], "amount": r["amount"], "currency": r["currency"],
        "note": r["note"], "status": r["status"], "payment_id": r["payment_id"],
        "created_at": r["created_at"],
    }
