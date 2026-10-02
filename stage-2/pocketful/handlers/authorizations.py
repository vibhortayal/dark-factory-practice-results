"""Authorizations: hold money now, capture it later (or void / let it expire)."""
from .. import holds, ledger, operation
from ..errors import ApiError, forbidden, insufficient_funds, invalid, malformed, not_found
from ..idempotency import run_idempotent
from ..store import store
from ..validation import (AUTH_STATUSES, integral, page_params, parse_amount, parse_note,
                          parse_visibility, query_enum, string_field)


def _view(authorization):
    return {**authorization, "payment_ids": list(authorization["payment_ids"])}


def create_authorization(req):
    return run_idempotent(req, lambda body: _create(req.user_id, body))


def _create(user_id, body):
    to_handle = string_field(body, "to_handle")
    amount = parse_amount(body)
    note = parse_note(body)
    visibility = parse_visibility(body)
    payer = store.user(user_id)
    if to_handle == payer["handle"]:
        raise ApiError(422, "self_payment", "cannot authorize a payment to yourself")
    receiver = store.by_handle.get(to_handle)
    if receiver is None:
        raise not_found("no user has that handle")
    if holds.available_of(payer) < amount:
        raise insufficient_funds()
    authorization = {
        "authorization_id": store.new_id("a"),
        "from_user_id": payer["id"], "from_handle": payer["handle"],
        "to_user_id": receiver["id"], "to_handle": receiver["handle"],
        "amount": amount, "captured_amount": 0, "remaining_amount": amount,
        "currency": store.currency, "note": note, "visibility": visibility, "status": "open",
        "expires_at": store.stamp(store.authorization_ttl),
        "payment_id": None, "payment_ids": [], "created_at": store.stamp(),
    }
    store.add_authorization(authorization)
    return _view(authorization)


def capture_authorization(req):
    authorization_id = req.params[0]
    return run_idempotent(req, lambda body: _capture(req.user_id, authorization_id, body),
                          allow_empty_body=True)


def _capture_fields(body):
    final = body.get("final", True)
    if not isinstance(final, bool):
        raise malformed("final must be a boolean")
    if "amount" not in body:
        return None, final
    amount = integral(body["amount"])
    if amount is None or amount < 1:
        raise invalid("amount must be a positive integer")
    return amount, final


def _capture(user_id, authorization_id, body):
    amount, final = _capture_fields(body)
    authorization = store.auth_by_id.get(authorization_id)
    if authorization is None:
        raise not_found("no such authorization")
    if authorization["to_user_id"] != user_id:
        raise forbidden("only the receiver may capture")
    if authorization["status"] == "expired":
        raise ApiError(409, "authorization_expired", "authorization has expired")
    if authorization["status"] != "open":
        raise ApiError(409, "authorization_not_open", "authorization is not open")
    remaining = authorization["remaining_amount"]
    amount = remaining if amount is None else amount
    if amount > remaining:
        raise ApiError(422, "capture_exceeds_authorization", "amount exceeds what is still held")
    payment = ledger.make_payment(
        store.user(authorization["from_user_id"]), store.user(user_id), amount,
        authorization["note"], authorization["visibility"], authorization_id=authorization_id)
    authorization["captured_amount"] += amount
    authorization["payment_id"] = payment["payment_id"]
    authorization["payment_ids"].append(payment["payment_id"])
    authorization["remaining_amount"] = remaining - amount
    if final or authorization["remaining_amount"] == 0:
        holds.close(authorization, "captured")
    return payment


def void_authorization(req):
    with store.lock:
        operation.begin()
        authorization = store.auth_by_id.get(req.params[0])
        if authorization is None:
            raise not_found("no such authorization")
        if authorization["from_user_id"] != req.user_id:
            raise forbidden("only the payer may void")
        if authorization["status"] == "open":
            holds.close(authorization, "voided")
        elif authorization["status"] != "voided":
            raise ApiError(409, "authorization_not_open", "authorization is not open")
        return 200, _view(authorization)


def list_authorizations(req):
    limit, offset = page_params(req.query)
    direction = query_enum(req.query, "direction", ("incoming", "outgoing"))
    status = query_enum(req.query, "status", AUTH_STATUSES)
    uid = req.user_id

    def wanted(a):
        if direction == "outgoing":
            ok = a["from_user_id"] == uid
        elif direction == "incoming":
            ok = a["to_user_id"] == uid
        else:
            ok = uid in (a["from_user_id"], a["to_user_id"])
        return ok and (status is None or a["status"] == status)

    with store.lock:
        operation.begin()
        matches = [a for a in reversed(store.state["authorizations"]) if wanted(a)]
        page = [_view(a) for a in matches[offset:offset + limit]]
        return 200, {"authorizations": page, "has_more": offset + limit < len(matches)}
