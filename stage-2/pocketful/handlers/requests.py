"""Money requests: create, pay, decline, cancel, list."""
from .. import ledger
from ..errors import ApiError, forbidden, not_found, request_not_pending
from ..idempotency import run_idempotent
from ..store import store
from ..validation import (STATUSES, page_params, parse_amount, parse_note,
                          parse_visibility, query_enum, string_field)


def create_request(req):
    return run_idempotent(req, lambda body: _create(req.user_id, body))


def _create(user_id, body):
    payer_handle = string_field(body, "payer_handle")
    amount = parse_amount(body)
    note = parse_note(body)
    requester = store.user(user_id)
    if payer_handle == requester["handle"]:
        raise ApiError(422, "self_request", "cannot request money from yourself")
    payer = store.by_handle.get(payer_handle)
    if payer is None:
        raise not_found("no user has that handle")
    return dict(ledger.make_request(requester, payer, amount, note, store.stamp()))


def pay_request(req):
    request_id = req.params[0]
    return run_idempotent(req, lambda body: _pay(req.user_id, request_id, body),
                          allow_empty_body=True)


def _pay(user_id, request_id, body):
    visibility = parse_visibility(body)
    request = store.requests_by_id.get(request_id)
    if request is None:
        raise not_found("no such request")
    if request["payer_id"] != user_id:
        raise forbidden("only the payer may pay a request")
    if request["status"] != "pending":
        raise request_not_pending()
    payer = store.user(user_id)
    receiver = store.user(request["requester_id"])
    payment = ledger.pay(payer, receiver, request["amount"], request["note"], visibility,
                         request_id=request_id)
    request["status"] = "paid"
    request["payment_id"] = payment["payment_id"]
    return payment


def _transition(req, party_key, target):
    with store.lock:
        request = store.requests_by_id.get(req.params[0])
        if request is None:
            raise not_found("no such request")
        if request[party_key] != req.user_id:
            raise forbidden("not permitted for this request")
        if request["status"] == "pending":
            request["status"] = target
        elif request["status"] != target:
            raise request_not_pending()
        return 200, dict(request)


def decline_request(req):
    return _transition(req, "payer_id", "declined")


def cancel_request(req):
    return _transition(req, "requester_id", "cancelled")


def list_requests(req):
    limit, offset = page_params(req.query)
    direction = query_enum(req.query, "direction", ("incoming", "outgoing"))
    status = query_enum(req.query, "status", STATUSES)
    uid = req.user_id

    def wanted(r):
        if direction == "incoming":
            ok = r["payer_id"] == uid
        elif direction == "outgoing":
            ok = r["requester_id"] == uid
        else:
            ok = uid in (r["payer_id"], r["requester_id"])
        return ok and (status is None or r["status"] == status)

    with store.lock:
        matches = [r for r in reversed(store.state["requests"]) if wanted(r)]
        page = [dict(r) for r in matches[offset:offset + limit]]
        return 200, {"requests": page, "has_more": offset + limit < len(matches)}
