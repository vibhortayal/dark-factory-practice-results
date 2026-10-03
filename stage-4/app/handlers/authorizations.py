"""Authorizations: hold funds now, capture later (create, capture, void, list)."""
import copy

from .. import clock, holds, ledger
from ..errors import conflict, forbidden, invalid, malformed, not_found
from ..store import new_id
from ..validation import (parse_amount, parse_note, parse_page, parse_visibility,
                          require_string)

STATUSES = ("open", "captured", "voided", "expired")


def create(ctx):
    body, state, user = ctx.body, ctx.state, ctx.user
    to_handle = require_string(body, "to_handle")
    amount = parse_amount(body.get("amount"))
    note = parse_note(body)
    visibility = parse_visibility(body)
    if to_handle == user["handle"]:
        raise invalid("cannot authorize a payment to yourself", "self_payment")
    payee = state.user_by_handle(to_handle)
    if payee is None:
        raise not_found("no user with that handle")
    if holds.available(state, user) < amount:
        raise conflict("insufficient_funds", "available balance is below the amount")
    created = clock.now()
    expires = clock.from_ts(created.ts + state.ttl * 1_000_000)
    data = holds.auth_data(state, user, payee, amount, note, visibility, created, expires,
                           authorization_id=new_id("a_"))
    state.add_authorization(data, created.ts, expires.ts)
    return 201, copy.deepcopy(data)


def _find(ctx, authorization_id):
    rec = ctx.state.authorizations.get(authorization_id)
    if rec is None:
        raise not_found("no such authorization")
    return rec["data"]


def _capture_options(body):
    amount = parse_amount(body["amount"], maximum=None) if "amount" in body else None
    final = body.get("final", True)
    if not isinstance(final, bool):
        raise malformed("final must be a boolean")
    return amount, final


def capture(ctx):
    state, user = ctx.state, ctx.user
    data = _find(ctx, ctx.params[0])
    if data["to_user_id"] != user["id"]:
        raise forbidden("only the receiver may capture")
    amount, final = _capture_options(ctx.body)
    if data["status"] == "expired":
        raise conflict("authorization_expired", "authorization has expired")
    if data["status"] != "open":
        raise conflict("authorization_not_open", "authorization is not open")
    remaining = data["remaining_amount"]
    amount = remaining if amount is None else amount
    if amount > remaining:
        raise invalid("amount exceeds the uncaptured remainder", "capture_exceeds_authorization")
    payer = state.users[data["from_user_id"]]
    stamp = clock.now()
    rec = state.authorizations[data["authorization_id"]]
    payment = ledger.transfer(state, payer, user, amount, data["note"], data["visibility"],
                              stamp, authorization_id=data["authorization_id"])
    rec["hold"]["captures"].append([stamp.ts, amount])
    data["captured_amount"] += amount
    data["payment_id"] = payment["payment_id"]
    data["payment_ids"].append(payment["payment_id"])
    data["remaining_amount"] = remaining - amount
    if final or data["remaining_amount"] == 0:
        data["status"] = "captured"
        data["remaining_amount"] = 0
        data["closed_at"] = stamp.text
        rec["hold"]["end_ts"] = stamp.ts
    return 201, payment


def void(ctx):
    data = _find(ctx, ctx.params[0])
    if data["from_user_id"] != ctx.user["id"]:
        raise forbidden("only the payer may void")
    if data["status"] == "open":
        stamp = clock.now()
        data["status"] = "voided"
        data["remaining_amount"] = 0
        data["closed_at"] = stamp.text
        ctx.state.authorizations[data["authorization_id"]]["hold"]["end_ts"] = stamp.ts
    elif data["status"] != "voided":
        raise conflict("authorization_not_open", "authorization is not open")
    return 200, copy.deepcopy(data)


def list_authorizations(ctx):
    query, uid = ctx.query, ctx.user["id"]
    direction = query.get("direction")
    if direction not in (None, "incoming", "outgoing"):
        raise invalid("direction must be incoming or outgoing")
    status = query.get("status")
    if status is not None and status not in STATUSES:
        raise invalid("unknown status")
    limit, offset = parse_page(query)
    matches = []
    for rec in ctx.state.authorizations.values():
        d = rec["data"]
        payer, payee = d["from_user_id"] == uid, d["to_user_id"] == uid
        if direction == "outgoing" and not payer:
            continue
        if direction == "incoming" and not payee:
            continue
        if not (payer or payee) or (status is not None and d["status"] != status):
            continue
        matches.append(rec)
    matches.sort(key=lambda r: (r["ts"], r["seq"]), reverse=True)
    page = matches[offset:offset + limit]
    return 200, {"authorizations": [copy.deepcopy(r["data"]) for r in page],
                 "has_more": offset + limit < len(matches)}
