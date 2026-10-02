"""POST /requests, GET /requests, and pay / decline / cancel on one request."""
from . import clock, fields, idempotency, ledger
from .errors import conflict, forbidden, invalid, not_found
from .request import authenticate
from .store import LOCK, STATUSES, current
from .views import payment_view, request_view


def create_request(req):
    with LOCK:
        store = current()
        user = authenticate(req, store)

        def effect(body):
            (payer_handle,) = fields.handles(body, ("payer_handle",))
            amount = fields.amount(body)
            note = fields.note(body)
            payer = store.user_by_handle(payer_handle)
            if payer is None:
                raise not_found("no such user")
            if payer["id"] == user["id"]:
                raise invalid("cannot request money from yourself", code="self_request")
            return request_view(ledger.record_request(store, user, payer, amount, note,
                                                      clock.now()))

        return idempotency.run(req, store, user, effect)


def list_requests(req):
    with LOCK:
        store = current()
        user = authenticate(req, store)
        uid = user["id"]
        direction = req.query.get("direction")
        status = req.query.get("status")
        if direction not in (None, "incoming", "outgoing"):
            raise invalid("direction must be incoming or outgoing")
        if status is not None and status not in STATUSES:
            raise invalid("unknown status")
        limit, offset = fields.page_params(req.query)
        items = []
        for r in reversed(store.requests.values()):
            incoming, outgoing = r["payer_id"] == uid, r["requester_id"] == uid
            if direction == "incoming" and not incoming:
                continue
            if direction == "outgoing" and not outgoing:
                continue
            if not (incoming or outgoing) or (status and r["status"] != status):
                continue
            items.append(request_view(r))
        page, more = fields.paginate(items, limit, offset)
        return 200, {"requests": page, "has_more": more}


def _find(store, req):
    request = store.requests.get(req.params["id"])
    if request is None:
        raise not_found("no such request")
    return request


def pay(req):
    with LOCK:
        store = current()
        user = authenticate(req, store)

        def effect(body):
            visibility = fields.visibility(body)
            request = _find(store, req)
            if request["payer_id"] != user["id"]:
                raise forbidden("only the payer may pay this request")
            if request["status"] != "pending":
                raise conflict("request_not_pending", "request is not pending")
            if store.balances[user["id"]] < request["amount"]:
                raise conflict("insufficient_funds", "balance too low")
            receiver = store.users[request["requester_id"]]
            payment = ledger.record_payment(
                store, user, receiver, request["amount"], request["note"], visibility,
                clock.now(), request_id=request["request_id"])
            request["status"] = "paid"
            request["payment_id"] = payment["payment_id"]
            return payment_view(payment)

        return idempotency.run(req, store, user, effect, allow_empty_body=True)


def _transition(req, role_field, target, role_message):
    with LOCK:
        store = current()
        user = authenticate(req, store)
        request = _find(store, req)
        if request[role_field] != user["id"]:
            raise forbidden(role_message)
        if request["status"] == "pending":
            request["status"] = target
        elif request["status"] != target:
            raise conflict("request_not_pending", "request is not pending")
        return 200, request_view(request)


def decline(req):
    return _transition(req, "payer_id", "declined", "only the payer may decline")


def cancel(req):
    return _transition(req, "requester_id", "cancelled", "only the requester may cancel")
