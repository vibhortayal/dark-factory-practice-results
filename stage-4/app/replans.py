"""Seating changes after a table closure: preview a plan, apply it (spec stage 4).

Order for both endpoints (router: body 400, 401): 404 restaurant, 403 non-manager,
idempotency key, replay/reuse, then
  preview: 422 field validation, 404 unknown table, 422 planning_limit, 409 no_feasible_plan;
  apply:   404 unknown / foreign plan, 409 plan_already_applied, 409 stale_plan.
A plan stores the restaurant revision it was computed at; applying it re-checks nothing but that
revision (plus a cheap safety re-verification), then commits closure and moves in one locked step.
"""
import re
from datetime import datetime

from . import idempotency, planner, records, scheduling
from .bookings import own  # noqa: F401  (re-exported for symmetry with other handlers)
from .errors import ApiError, invalid, malformed, not_found
from .jsonutil import clone
from .state import STORE

INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$")


def _instant(value, what):
    if not isinstance(value, str) or not INSTANT_RE.match(value):
        raise invalid(f"{what} must be an RFC 3339 instant with an explicit offset")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise invalid(f"{what} is not a valid instant")


def _manager_restaurant(req, restaurant_id):
    rest = STORE.data.restaurants.get(restaurant_id)
    if rest is None:
        raise not_found("no such restaurant")
    if req.user_id not in rest.get("manager_user_ids", []):
        raise ApiError(403, "forbidden", "only the restaurant's managers may change seating")
    return rest


def _options(rest, rec):
    """Every single table then declared pair this booking could sit at under its own
    accepted terms: [(rank, table_ids, capacity)] before closure/conflict filtering."""
    caps = rec["accepted_terms"]["capacities"]
    sets = [(t["id"],) for t in rest["tables"]] + [tuple(p) for p in scheduling.declared_pairs(rest)]
    return [(rank, ids, sum(caps[t] for t in ids)) for rank, ids in enumerate(sets)
            if all(t in caps for t in ids)]


def _plan(data, rest, table_id, start, end):
    considered = sorted((r for r in data.reservations.values()
                         if r["restaurant_id"] == rest["id"] and r["status"] == "confirmed"
                         and scheduling.overlaps(start, end, *scheduling.interval(r))),
                        key=lambda r: r["reference"])
    refs = {r["reference"] for r in considered}
    fixed = [r for r in data.reservations.values()
             if r["restaurant_id"] == rest["id"] and r["status"] == "confirmed" and r["reference"] not in refs]
    bookings = []
    for rec in considered:
        s, e = scheduling.interval(rec)
        usable = []
        for rank, ids, cap in _options(rest, rec):
            if cap < rec["party_size"] or table_id in ids:
                continue
            if scheduling.closed(data, rest["id"], ids, s, e):
                continue
            if any(set(ids) & set(f["table_ids"]) and scheduling.overlaps(s, e, *scheduling.interval(f))
                   for f in fixed):
                continue
            usable.append((rank, ids, cap))
        bookings.append(planner.Booking(rec["reference"], s, e, rec["party_size"], rec["table_ids"], usable))
    try:
        solution = planner.solve(bookings)
    except planner.PlanningLimit:
        raise ApiError(422, "planning_limit", "the seating problem is too large to plan")
    if solution is None:
        raise ApiError(409, "no_feasible_plan", "no seating arrangement keeps every booking")
    assignments, moved, unused = [], 0, 0
    for rec, b in zip(considered, bookings):
        ids = list(solution[rec["reference"]])
        changed = set(ids) != set(rec["table_ids"])
        moved += changed
        unused += next(cap for _, o, cap in b.options if list(o) == ids) - rec["party_size"]
        assignments.append({"reference": rec["reference"], "table_ids": ids, "changed": changed})
    return assignments, moved, unused


def preview(req, restaurant_id):
    rest = _manager_restaurant(req, restaurant_id)

    def produce(data, body):
        table_id = body.get("table_id")
        if "table_id" in body and not isinstance(table_id, str):
            raise malformed("table_id must be a string")
        if "table_id" not in body or "from" not in body or "to" not in body:
            raise invalid("table_id, from and to are required")
        start, end = _instant(body["from"], "from"), _instant(body["to"], "to")
        if not start < end:
            raise invalid("from must be earlier than to")
        if table_id not in {t["id"] for t in rest["tables"]}:
            raise not_found("no such table")
        assignments, moved, unused = _plan(data, rest, table_id, start, end)
        plan = {"plan_id": data.new_plan_id(), "restaurant_id": rest["id"],
                "restaurant_revision": data.rest_revision(rest["id"]),
                "closure": {"table_id": table_id, "from": body["from"], "to": body["to"]},
                "assignments": assignments, "moved_count": moved, "unused_seats": unused,
                "applied": False}
        data.plans[plan["plan_id"]] = plan
        return {k: clone(plan[k]) for k in ("plan_id", "restaurant_revision", "closure", "assignments",
                                             "moved_count", "unused_seats")}
    return idempotency.run(req, produce)


def apply(req, restaurant_id, plan_id):
    rest = _manager_restaurant(req, restaurant_id)

    def produce(data, body):
        plan = data.plans.get(plan_id)
        if plan is None or plan["restaurant_id"] != rest["id"]:
            raise not_found("no such plan")
        if plan["applied"]:
            raise ApiError(409, "plan_already_applied", "that plan has already been applied")
        if plan["restaurant_revision"] != data.rest_revision(rest["id"]):
            raise ApiError(409, "stale_plan", "the restaurant has changed since the plan was made")
        moves = [(data.reservations[a["reference"]], a["table_ids"]) for a in plan["assignments"] if a["changed"]]
        # The revision guarantees nothing changed; re-verify cheaply rather than trust it blindly.
        moving = {rec["reference"] for rec, _ in moves}
        closure = plan["closure"]
        data.closures.setdefault(rest["id"], []).append(
            {"table_id": closure["table_id"], "from": closure["from"], "to": closure["to"], "plan_id": plan_id})
        for rec, ids in moves:
            if not scheduling.table_free(data, rest["id"], ids, *scheduling.interval(rec), ignore=moving):
                data.closures[rest["id"]].pop()
                raise ApiError(409, "stale_plan", "the plan no longer fits")
        series_hit = set()
        for rec, ids in moves:
            before = list(rec["table_ids"])
            rec["table_ids"] = list(ids)
            rec["revision"] += 1
            records.add_history(rec, "reassigned", [{"field": "table_ids", "from": before, "to": list(ids)}],
                                plan_id=plan_id)
            if rec.get("series"):
                series_hit.add(rec["series"]["id"])
        for sid in series_hit:
            data.series[sid]["revision"] += 1
        plan["applied"] = True
        records.bump_restaurant(data, rest["id"])
        return {"plan_id": plan_id, "restaurant_revision": data.rest_revision(rest["id"]),
                "reservations": [records.public(data.reservations[a["reference"]]) for a in plan["assignments"]]}
    return idempotency.run(req, produce)
