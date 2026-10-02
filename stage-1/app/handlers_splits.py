"""POST /splits."""
from . import clock, fields, idempotency, ledger
from .errors import invalid, malformed, not_found
from .money import equal_shares
from .request import authenticate
from .store import LOCK, current
from .views import request_view


def _participants(body):
    value = body.get("participant_handles")
    if "participant_handles" in body and not isinstance(value, list):
        raise malformed("participant_handles must be an array")
    if isinstance(value, list) and not all(isinstance(h, str) for h in value):
        raise malformed("participant_handles must contain strings")
    if "participant_handles" not in body:
        raise invalid("participant_handles is required")
    if not value or len(set(value)) != len(value):
        raise invalid("participant_handles must be non-empty and unique")
    return value


def create_split(req):
    with LOCK:
        store = current()
        user = authenticate(req, store)

        def effect(body):
            participants = _participants(body)
            amount = fields.amount(body)
            note = fields.note(body)
            users = []
            for handle in participants:
                found = store.user_by_handle(handle)
                if found is None:
                    raise not_found("no such user")
                users.append(found)
            shares = equal_shares(amount, len(users))
            created_at = clock.now()
            split_id = store.new_id("sp_", store.splits)
            requests = [
                ledger.record_request(store, user, other, share, note, created_at, split_id)
                for other, share in zip(users, shares) if other["id"] != user["id"]]
            split = {
                "split_id": split_id, "amount": amount, "currency": store.currency,
                "note": note,
                "shares": [{"handle": h, "amount": s} for h, s in zip(participants, shares)],
                "requests": [r["request_id"] for r in requests], "created_at": created_at,
            }
            store.splits[split_id] = split
            return {**{k: split[k] for k in ("split_id", "amount", "currency", "note", "shares")},
                    "requests": [request_view(r) for r in requests], "created_at": created_at}

        return idempotency.run(req, store, user, effect)
