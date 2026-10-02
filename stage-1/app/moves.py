"""POST /reservation-moves: change several bookings atomically."""
from . import idempotency
from .bookings import AMEND_FIELDS, owned, parse_fields, plan_amendment, require_amendable
from .errors import invalid
from .errors import conflict
from .scheduling import overlaps
from .views import reservation_view

MAX_MOVES = 8


def _shape(body):
    items = body.get("moves")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_MOVES:
        raise invalid("moves must be a list of 1 to %d objects" % MAX_MOVES)
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise invalid("each move must be an object")
        ref = item.get("reference")
        if not isinstance(ref, str) or not ref:
            raise invalid("each move needs a string reference")
        if ref in seen:
            raise invalid("references must be distinct")
        seen.add(ref)
    return items


def _check_occupancy(store, recs, plans):
    listed = {r["reservation_id"] for r in recs}
    final = [(r, p) for r, p in zip(recs, plans)]
    for i, (rec, plan) in enumerate(final):
        for other in store.data["reservations"].values():
            if (other["status"] == "confirmed" and other["reservation_id"] not in listed
                    and other["restaurant_id"] == rec["restaurant_id"]
                    and other["table_id"] == plan["table_id"]
                    and overlaps(plan["start_ts"], plan["end_ts"], other["start_ts"], other["end_ts"])):
                raise conflict("table_unavailable", "table taken by an unlisted booking")
        for other_rec, other_plan in final[i + 1:]:
            if (other_plan["table_id"] == plan["table_id"]
                    and overlaps(plan["start_ts"], plan["end_ts"],
                                 other_plan["start_ts"], other_plan["end_ts"])):
                raise conflict("table_unavailable", "moves overlap each other")


def move(store, user_id, key, body, now):
    rkey = idempotency.record_key(user_id, "POST", "/reservation-moves", key)
    with store.lock:
        replay = idempotency.lookup(store, rkey, body)
        if replay is not None:
            return 200, replay
        items = _shape(body)
        recs = [owned(store, user_id, item["reference"]) for item in items]
        if len({r["restaurant_id"] for r in recs}) != 1:
            raise invalid("all bookings must belong to the same restaurant")
        plans = []
        for item, rec in zip(items, recs):
            require_amendable(store, rec, now)
            fields = parse_fields(item, AMEND_FIELDS, False)
            if fields:
                plans.append(plan_amendment(store, rec, fields))
            else:
                plans.append({k: rec[k] for k in (
                    "table_id", "party_size", "starts_at_local", "start_ts", "end_ts")})
        _check_occupancy(store, recs, plans)
        for rec, plan in zip(recs, plans):
            rec.update(plan)
        response = {"reservations": [reservation_view(store, r) for r in recs]}
        idempotency.remember(store, rkey, body, response)
        return 201, response
