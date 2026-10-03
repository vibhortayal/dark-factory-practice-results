"""POST /splits."""
from .. import clock, ledger
from ..errors import invalid, malformed, not_found
from ..store import new_id
from ..validation import parse_amount, parse_note


def create(ctx):
    body, state, user = ctx.body, ctx.state, ctx.user
    if "participant_handles" not in body:
        raise invalid("participant_handles is required")
    handles = body["participant_handles"]
    if not isinstance(handles, list) or not all(isinstance(h, str) for h in handles):
        raise malformed("participant_handles must be a list of strings")
    amount = parse_amount(body.get("amount"))
    note = parse_note(body)
    if not handles or len(set(handles)) != len(handles):
        raise invalid("participant_handles must be non-empty and unique")
    users = []
    for handle in handles:
        found = state.user_by_handle(handle)
        if found is None:
            raise not_found("unknown handle: " + handle[:40])
        users.append(found)

    stamp = clock.now()
    amounts = ledger.equal_split(amount, len(users))
    requests, request_ids = [], []
    for person, share in zip(users, amounts):
        if person["id"] == user["id"]:
            continue
        data = ledger.request_data(state, user, person, share, note, stamp)
        state.add_request(data, stamp.ts)
        requests.append(dict(data))
        request_ids.append(data["request_id"])
    split_id = new_id("sp_")
    state.splits.append({"split_id": split_id, "request_ids": request_ids})
    return 201, {"split_id": split_id, "amount": amount, "currency": state.currency,
                 "note": note,
                 "shares": [{"handle": u["handle"], "amount": a}
                            for u, a in zip(users, amounts)],
                 "requests": requests, "created_at": stamp.text}
