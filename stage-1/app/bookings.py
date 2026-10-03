"""Reservations: create, read, list, cancel, amend (spec §8) and atomic moves (§11).

Every function runs under the global lock (taken by the router), so checks and
writes form one atomic step: a failed request changes nothing.

Booking error precedence (documented choice): body shape (400/422) -> unknown
restaurant/table (404) -> invalid_local_time -> not_on_slot_grid ->
outside_opening_hours -> party_exceeds_capacity -> table_unavailable (409).
Amend/move: 404 (not the caller's) -> reservation_cancelled -> cutoff_passed -> field
validation -> semantic checks above; moves apply this per booking in input order, then
occupancy.
"""
from datetime import timedelta

from . import idempotency, scheduling, timeutil
from .errors import ApiError, invalid, malformed, not_found
from .state import STORE
from .validate import optional_str, party_size, require_str

MAX_MOVES = 8


def public(rec):
    return {k: v for k, v in rec.items() if k != "user_id"}


def _local(text):
    naive = timeutil.parse_local(text)
    if naive is None:
        raise invalid("starts_at_local must be a bare local YYYY-MM-DDTHH:MM")
    return naive


def _lookup_target(data, restaurant_id, table_id):
    rest = data.restaurants.get(restaurant_id)
    table = next((t for t in rest["tables"] if t["id"] == table_id), None) if rest else None
    if table is None:
        raise not_found("no such restaurant or table")
    return rest, table


def _record(data, user_id, rest, table, start, end, naive, party):
    tz = timeutil.zone(rest["timezone"])
    ref = data.new_reference()
    rec = {
        "reservation_id": data.new_reservation_id(), "reference": ref,
        "restaurant_id": rest["id"], "table_id": table["id"], "party_size": party,
        "status": "confirmed", "starts_at_local": timeutil.local_text(naive),
        "starts_at": timeutil.iso(start.astimezone(tz)),
        "ends_at": timeutil.iso(end.astimezone(tz)),
        "created_at": timeutil.iso(timeutil.now_utc()), "user_id": user_id,
    }
    data.reservations[ref] = rec
    return rec


def _create(user_id):
    def produce(data, body):
        rid = require_str(body, "restaurant_id")
        tid = require_str(body, "table_id")
        local = require_str(body, "starts_at_local")
        if "party_size" not in body:
            raise invalid("party_size is required")
        party = party_size(body["party_size"])
        naive = _local(local)
        rest, table = _lookup_target(data, rid, tid)
        start, end = scheduling.plan_slot(rest, table, naive, party)
        if not scheduling.table_free(data, rest["id"], table["id"], start, end):
            raise ApiError(409, "table_unavailable", "the table is taken at that time")
        return public(_record(data, user_id, rest, table, start, end, naive, party))
    return produce


def create(req):
    return idempotency.run(req, _create(req.user_id))


def _own(data, user_id, reference):
    rec = data.reservations.get(reference)
    if rec is None or rec["user_id"] != user_id:
        raise not_found("no such reservation")
    return rec


def list_mine(req):
    data = STORE.data
    mine = [r for r in data.reservations.values() if r["user_id"] == req.user_id]
    mine.sort(key=lambda r: (scheduling.interval(r)[0], r["reservation_id"]), reverse=True)
    return 200, {"reservations": [public(r) for r in mine]}


def get_one(req, reference):
    return 200, public(_own(STORE.data, req.user_id, reference))


def _check_cutoff(rec, rest):
    start, _ = scheduling.interval(rec)
    if timeutil.now_utc() >= start - timedelta(minutes=rest["cancellation_cutoff_minutes"]):
        raise ApiError(409, "cutoff_passed", "too close to the start to change this booking")


def cancel(req, reference):
    data = STORE.data
    rec = _own(data, req.user_id, reference)
    if rec["status"] == "cancelled":
        return 200, public(rec)
    _check_cutoff(rec, data.restaurants[rec["restaurant_id"]])
    rec["status"] = "cancelled"
    return 200, public(rec)


def _parse_changes(item):
    """Optional PATCH-style fields. Wrong JSON type -> 400, bad value -> 422."""
    changes = {}
    table_id = optional_str(item, "table_id")
    local = optional_str(item, "starts_at_local")
    if table_id is not None:
        changes["table_id"] = table_id
    if local is not None:
        changes["naive"] = _local(local)
    if "party_size" in item:
        changes["party"] = party_size(item["party_size"])
    return changes


def _resolve(data, rec, changes):
    """Resulting (table, start, end, naive, party) of applying `changes` to `rec`,
    after all non-occupancy checks. Unchanged bookings keep their stored values."""
    rest = data.restaurants[rec["restaurant_id"]]
    table_id = changes.get("table_id", rec["table_id"])
    naive = changes.get("naive") or timeutil.parse_local(rec["starts_at_local"])
    party = changes.get("party", rec["party_size"])
    _, table = _lookup_target(data, rest["id"], table_id)
    if (table_id, naive, party) == (rec["table_id"], timeutil.parse_local(rec["starts_at_local"]),
                                    rec["party_size"]):
        start, end = scheduling.interval(rec)
    else:
        start, end = scheduling.plan_slot(rest, table, naive, party)
    return table, start, end, naive, party


def _commit(rec, rest, table, start, end, naive, party):
    tz = timeutil.zone(rest["timezone"])
    rec["table_id"] = table["id"]
    rec["party_size"] = party
    rec["starts_at_local"] = timeutil.local_text(naive)
    rec["starts_at"] = timeutil.iso(start.astimezone(tz))
    rec["ends_at"] = timeutil.iso(end.astimezone(tz))


def amend(req, reference):
    data = STORE.data
    rec = _own(data, req.user_id, reference)
    body = req.json_object()
    if rec["status"] == "cancelled":
        raise ApiError(409, "reservation_cancelled", "the reservation is cancelled")
    _check_cutoff(rec, data.restaurants[rec["restaurant_id"]])
    changes = _parse_changes(body)
    table, start, end, naive, party = _resolve(data, rec, changes)
    if not scheduling.table_free(data, rec["restaurant_id"], table["id"], start, end,
                                 ignore={rec["reference"]}):
        raise ApiError(409, "table_unavailable", "the table is taken at that time")
    _commit(rec, data.restaurants[rec["restaurant_id"]], table, start, end, naive, party)
    return 200, public(rec)


# ---- atomic moves -----------------------------------------------------------

def _parse_moves(body):
    moves = body.get("moves")
    if not isinstance(moves, list) or not 1 <= len(moves) <= MAX_MOVES:
        raise invalid(f"moves must be an array of 1 to {MAX_MOVES} objects")
    refs = set()
    for item in moves:
        if not isinstance(item, dict) or not isinstance(item.get("reference"), str) \
                or not item["reference"]:
            raise invalid("each move needs a string reference")
        if item["reference"] in refs:
            raise invalid("duplicate reference in moves")
        refs.add(item["reference"])
    return moves


def _moves(user_id):
    def produce(data, body):
        moves = _parse_moves(body)
        recs = [_own(data, user_id, item["reference"]) for item in moves]
        if len({r["restaurant_id"] for r in recs}) != 1:
            raise invalid("all bookings must belong to the same restaurant")
        rest = data.restaurants[recs[0]["restaurant_id"]]
        results = []
        for rec, item in zip(recs, moves):
            if rec["status"] == "cancelled":
                raise ApiError(409, "reservation_cancelled", "the reservation is cancelled")
            _check_cutoff(rec, rest)
            changes = _parse_changes(item)  # after this booking's cutoff, before the next booking
            results.append(_resolve(data, rec, changes))
        listed = {r["reference"] for r in recs}
        for i, (table, start, end, _, _) in enumerate(results):
            clash = not scheduling.table_free(data, rest["id"], table["id"], start, end,
                                              ignore=listed)
            clash = clash or any(
                table["id"] == other[0]["id"] and scheduling.overlaps(start, end, other[1], other[2])
                for j, other in enumerate(results) if j != i)
            if clash:
                raise ApiError(409, "table_unavailable", "a resulting booking would overlap")
        for rec, result in zip(recs, results):
            _commit(rec, rest, *result)
        return {"reservations": [public(r) for r in recs]}
    return produce


def moves(req):
    return idempotency.run(req, _moves(req.user_id))
