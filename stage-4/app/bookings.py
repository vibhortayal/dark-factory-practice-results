"""Reservations: create, read, list, cancel, amend (spec §8) and atomic moves (§11),
under dated booking policies (stage 3).

Every function runs under the global lock (taken by the router), so checks and
writes form one atomic step: a failed request changes nothing.

Booking error precedence (documented choice): body shape (400/422, incl. both table keys,
empty or duplicate table set) -> unknown restaurant/table (404) -> combination_not_allowed
-> invalid_local_time -> not_on_slot_grid -> outside_opening_hours -> party_exceeds_capacity
-> table_unavailable (409). The checks use the policy selected by the booking's local start date.
PATCH: unparseable body (400) -> 404 (not the caller's) -> expected_revision shape (422) ->
stale_revision (409) -> reservation_cancelled -> cutoff_passed (the booking's accepted cutoff)
-> field validation -> the booking checks above -> table_unavailable. Moves apply the same order
per booking in input order, then check occupancy over the whole batch.
"""
from datetime import timedelta

from . import idempotency, policies, records, scheduling, timeutil
from .errors import ApiError, invalid, not_found
from .records import public
from .state import STORE
from .validate import is_int, optional_str, party_size, require_str, table_selection

MAX_MOVES = 8


def _local(text):
    naive = timeutil.parse_local(text)
    if naive is None:
        raise invalid("starts_at_local must be a bare local YYYY-MM-DDTHH:MM")
    return naive


def lookup_target(data, restaurant_id, table_ids):
    """The restaurant and its table dicts for `table_ids`; 404 if any is unknown."""
    rest = data.restaurants.get(restaurant_id)
    by_id = {t["id"]: t for t in rest["tables"]} if rest else {}
    if rest is None or any(t not in by_id for t in table_ids):
        raise not_found("no such restaurant or table")
    return rest, [by_id[t] for t in table_ids]


def plan(data, rest, table_ids, naive, party):
    """Check a booking against the policy of its local start date.
    Returns (start, end, canonical_table_ids, terms)."""
    terms = policies.select_terms(data, rest, naive.date())
    view = policies.rules_view(rest, terms)
    by_id = {t["id"]: t for t in view["tables"]}
    start, end, ids = scheduling.plan_slot(view, [by_id[t] for t in table_ids], naive, party)
    return start, end, ids, terms


def _create(user_id):
    def produce(data, body):
        rid = require_str(body, "restaurant_id")
        wanted = table_selection(body, required=True)
        local = require_str(body, "starts_at_local")
        if "party_size" not in body:
            raise invalid("party_size is required")
        party = party_size(body["party_size"])
        naive = _local(local)
        rest, _ = lookup_target(data, rid, wanted)
        start, end, ids, terms = plan(data, rest, wanted, naive, party)
        if not scheduling.table_free(data, rest["id"], ids, start, end):
            raise ApiError(409, "table_unavailable", "a table is taken at that time")
        rec = records.new_record(data, user_id, rest, ids, start, end, naive, party, terms)
        records.bump_restaurant(data, rest["id"])
        return public(rec)
    return produce


def create(req):
    return idempotency.run(req, _create(req.user_id))


def own(data, user_id, reference):
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
    return 200, public(own(STORE.data, req.user_id, reference))


def check_cutoff(rec):
    """The accepted cancellation cutoff, against the booking's current start."""
    start, _ = scheduling.interval(rec)
    cutoff = rec["accepted_terms"]["cancellation_cutoff_minutes"]
    if timeutil.now_utc() >= start - timedelta(minutes=cutoff):
        raise ApiError(409, "cutoff_passed", "too close to the start to change this booking")


def cancel(req, reference):
    data = STORE.data
    rec = own(data, req.user_id, reference)
    if rec["status"] == "cancelled":
        return 200, public(rec)
    check_cutoff(rec)
    rec["status"] = "cancelled"
    rec["revision"] += 1
    records.add_history(rec, "cancelled", [])
    records.bump_restaurant(data, rec["restaurant_id"])
    records.bump_series(data, rec)
    return 200, public(rec)


def _expected_revision(body):
    """Optional `expected_revision`: a positive integer, else 422."""
    if "expected_revision" not in body:
        return None
    value = body["expected_revision"]
    if not is_int(value) or value < 1:
        raise invalid("expected_revision must be a positive integer")
    return value


def _check_revision(rec, expected):
    if expected is not None and expected != rec["revision"]:
        raise ApiError(409, "stale_revision", "the reservation has changed since you read it")


def parse_changes(item):
    """Optional PATCH-style fields. Wrong JSON type -> 400, bad value -> 422."""
    changes = {}
    tables = table_selection(item, required=False)
    local = optional_str(item, "starts_at_local")
    if tables is not None:
        changes["tables"] = tables
    if local is not None:
        changes["naive"] = _local(local)
    if "party_size" in item:
        changes["party"] = party_size(item["party_size"])
    return changes


def resolve(data, rec, changes):
    """None for a no-op, else (table_ids, start, end, naive, party, terms) after every
    non-occupancy check against the policy of the resulting start date."""
    rest = data.restaurants[rec["restaurant_id"]]
    wanted = changes.get("tables", rec["table_ids"])
    current = timeutil.parse_local(rec["starts_at_local"])
    naive = changes.get("naive") or current
    party = changes.get("party", rec["party_size"])
    lookup_target(data, rest["id"], wanted)
    if set(wanted) == set(rec["table_ids"]) and naive == current and party == rec["party_size"]:
        return None
    start, end, ids, terms = plan(data, rest, wanted, naive, party)
    return ids, start, end, naive, party, terms


def apply_change(rec, rest, change):
    """Commit one real amendment: new fields, end time and terms, revision +1, history."""
    ids, start, end, naive, party, terms = change
    tz = timeutil.zone(rest["timezone"])
    before = records.fields_of(rec)
    rec["table_ids"] = list(ids)
    rec["party_size"] = party
    rec["starts_at_local"] = timeutil.local_text(naive)
    rec["starts_at"] = timeutil.iso(start.astimezone(tz))
    rec["ends_at"] = timeutil.iso(end.astimezone(tz))
    rec["accepted_terms"] = terms
    rec["revision"] += 1
    records.add_history(rec, "changed", records.diff(before, records.fields_of(rec)))


def amend(req, reference):
    data = STORE.data
    body = req.json_object()
    rec = own(data, req.user_id, reference)
    expected = _expected_revision(body)
    _check_revision(rec, expected)
    if rec["status"] == "cancelled":
        raise ApiError(409, "reservation_cancelled", "the reservation is cancelled")
    check_cutoff(rec)
    change = resolve(data, rec, parse_changes(body))
    if change is None:
        return 200, public(rec)
    ids, start, end = change[0], change[1], change[2]
    if not scheduling.table_free(data, rec["restaurant_id"], ids, start, end, ignore={rec["reference"]}):
        raise ApiError(409, "table_unavailable", "a table is taken at that time")
    apply_change(rec, data.restaurants[rec["restaurant_id"]], change)
    records.bump_restaurant(data, rec["restaurant_id"])
    records.bump_series(data, rec)
    records.mark_exception(data, rec)
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
        recs = [own(data, user_id, item["reference"]) for item in moves]
        if len({r["restaurant_id"] for r in recs}) != 1:
            raise invalid("all bookings must belong to the same restaurant")
        rest = data.restaurants[recs[0]["restaurant_id"]]
        changes = []
        for rec, item in zip(recs, moves):
            _check_revision(rec, _expected_revision(item))
            if rec["status"] == "cancelled":
                raise ApiError(409, "reservation_cancelled", "the reservation is cancelled")
            check_cutoff(rec)
            changes.append(resolve(data, rec, parse_changes(item)))  # None = no-op
        outcome = []  # (table_ids, start, end) each booking will occupy afterwards
        for rec, change in zip(recs, changes):
            outcome.append(tuple(change[:3]) if change else
                           (rec["table_ids"], *scheduling.interval(rec)))
        listed = {r["reference"] for r in recs}
        for i, (ids, start, end) in enumerate(outcome):
            clash = not scheduling.table_free(data, rest["id"], ids, start, end, ignore=listed)
            clash = clash or any(set(ids) & set(other[0]) and scheduling.overlaps(start, end, other[1], other[2])
                                 for j, other in enumerate(outcome) if j != i)
            if clash:
                raise ApiError(409, "table_unavailable", "a resulting booking would overlap")
        real = [(rec, change) for rec, change in zip(recs, changes) if change]
        series_hit = set()
        for rec, change in real:
            apply_change(rec, rest, change)
            records.mark_exception(data, rec)
            if rec.get("series"):
                series_hit.add(rec["series"]["id"])
        for sid in series_hit:
            data.series[sid]["revision"] += 1
        if real:
            records.bump_restaurant(data, rest["id"])
        return {"reservations": [public(r) for r in recs]}
    return produce


def moves(req):
    return idempotency.run(req, _moves(req.user_id))
