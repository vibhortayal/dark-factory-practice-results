"""POST /splits: equal shares and one pending request per other participant."""
from .. import ledger
from ..errors import invalid, not_found
from ..idempotency import run_idempotent
from ..store import store
from ..timefmt import now_iso
from ..validation import handle_list_field, parse_amount, parse_note


def equal_shares(amount, count):
    base, extra = divmod(amount, count)
    return [base + (1 if i < extra else 0) for i in range(count)]


def create_split(req):
    return run_idempotent(req, lambda body: _execute(req.user_id, body))


def _execute(user_id, body):
    handles = handle_list_field(body, "participant_handles")
    amount = parse_amount(body)
    note = parse_note(body)
    if not handles or len(set(handles)) != len(handles):
        raise invalid("participant_handles must be non-empty and free of duplicates")
    participants = []
    for handle in handles:
        user = store.by_handle.get(handle)
        if user is None:
            raise not_found(f"no user has the handle {handle[:30]!r}")
        participants.append(user)
    caller = store.user(user_id)
    shares = equal_shares(amount, len(participants))
    created_at = now_iso()
    requests = [dict(ledger.make_request(caller, user, share, note, created_at))
                for user, share in zip(participants, shares) if user["id"] != user_id]
    split = {"split_id": store.new_id("sp"), "amount": amount, "currency": store.currency,
             "note": note,
             "shares": [{"handle": u["handle"], "amount": s} for u, s in zip(participants, shares)],
             "requests": requests, "created_at": created_at}
    store.state["splits"].append({**split, "requests": [r["request_id"] for r in requests],
                                  "requester_id": user_id})
    return split
