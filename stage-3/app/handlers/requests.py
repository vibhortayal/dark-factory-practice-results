"""Money requests: create, pay, decline, cancel, list."""
from .. import clock, holds, ledger
from ..errors import conflict, forbidden, invalid, not_found
from ..validation import (parse_amount, parse_note, parse_page, parse_visibility,
                          require_string)

STATUSES = ("pending", "paid", "declined", "cancelled")


def create(ctx):
    body, state, user = ctx.body, ctx.state, ctx.user
    payer_handle = require_string(body, "payer_handle")
    amount = parse_amount(body.get("amount"))
    note = parse_note(body)
    if payer_handle == user["handle"]:
        raise invalid("cannot request money from yourself", "self_request")
    payer = state.user_by_handle(payer_handle)
    if payer is None:
        raise not_found("no user with that handle")
    stamp = clock.now()
    data = ledger.request_data(state, user, payer, amount, note, stamp)
    state.add_request(data, stamp.ts)
    return 201, dict(data)


def _find(ctx, request_id):
    rec = ctx.state.requests.get(request_id)
    if rec is None:
        raise not_found("no such request")
    return rec["data"]


def pay(ctx):
    state, user = ctx.state, ctx.user
    data = _find(ctx, ctx.params[0])
    if data["payer_id"] != user["id"]:
        raise forbidden("only the payer may pay a request")
    visibility = parse_visibility(ctx.body)
    if data["status"] != "pending":
        raise conflict("request_not_pending", "request is not pending")
    if holds.available(state, user) < data["amount"]:
        raise conflict("insufficient_funds", "balance is below the amount")
    requester = state.users[data["requester_id"]]
    payment = ledger.transfer(state, user, requester, data["amount"], data["note"],
                              visibility, clock.now(), request_id=data["request_id"])
    data["status"] = "paid"
    data["payment_id"] = payment["payment_id"]
    return 201, payment


def _close(ctx, party_field, target, what):
    data = _find(ctx, ctx.params[0])
    if data[party_field] != ctx.user["id"]:
        raise forbidden("only the %s may do this" % what)
    if data["status"] == "pending":
        data["status"] = target
    elif data["status"] != target:
        raise conflict("request_not_pending", "request is not pending")
    return 200, dict(data)


def decline(ctx):
    return _close(ctx, "payer_id", "declined", "payer")


def cancel(ctx):
    return _close(ctx, "requester_id", "cancelled", "requester")


def list_requests(ctx):
    query, uid = ctx.query, ctx.user["id"]
    direction = query.get("direction")
    if direction not in (None, "incoming", "outgoing"):
        raise invalid("direction must be incoming or outgoing")
    status = query.get("status")
    if status is not None and status not in STATUSES:
        raise invalid("unknown status")
    limit, offset = parse_page(query)
    matches = []
    for rec in ctx.state.requests.values():
        d = rec["data"]
        mine_in, mine_out = d["payer_id"] == uid, d["requester_id"] == uid
        if direction == "incoming" and not mine_in:
            continue
        if direction == "outgoing" and not mine_out:
            continue
        if not (mine_in or mine_out) or (status is not None and d["status"] != status):
            continue
        matches.append(rec)
    matches.sort(key=lambda r: (r["ts"], r["seq"]), reverse=True)
    page = matches[offset:offset + limit]
    return 200, {"requests": [dict(r["data"]) for r in page],
                 "has_more": offset + limit < len(matches)}
