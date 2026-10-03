"""Booking policies: validation, selection by date, accepted-terms snapshots (spec stage 3)."""
from . import idempotency, timeutil
from .errors import ApiError, invalid, not_found
from .jsonutil import clone
from .state import STORE
from .validate import is_int


def policy_zero(rest):
    """The fixture's own rules as a policy (version 0)."""
    return {"policy_version": 0, "slot_minutes": rest["slot_minutes"],
            "reservation_duration_minutes": rest["reservation_duration_minutes"],
            "cancellation_cutoff_minutes": rest["cancellation_cutoff_minutes"],
            "opening_hours": clone(rest["opening_hours"]),
            "capacities": {t["id"]: t["capacity"] for t in rest["tables"]}}


def terms_of(policy):
    """Accepted-terms snapshot: the whole policy without `effective_from`."""
    return {k: clone(v) for k, v in policy.items() if k != "effective_from"}


def select_terms(data, rest, date):
    """Terms in force for a booking whose local start date is `date`: the greatest
    effective_from not later than it (ties: greatest version), else policy 0."""
    day = date.isoformat()
    best = None
    for p in data.policies.get(rest["id"], []):
        if p["effective_from"] <= day and (
                best is None or (p["effective_from"], p["policy_version"]) > (best["effective_from"], best["policy_version"])):
            best = p
    return terms_of(best) if best else policy_zero(rest)


def rules_view(rest, terms):
    """The restaurant as the given terms see it: same dict shape, so the scheduling
    functions work unchanged. Declared combinations and table identity never change."""
    view = dict(rest)
    for key in ("slot_minutes", "reservation_duration_minutes", "cancellation_cutoff_minutes", "opening_hours"):
        view[key] = terms[key]
    view["tables"] = [dict(t, capacity=terms["capacities"][t["id"]]) for t in rest["tables"]]
    return view


def _int(value, low, high, what):
    if not is_int(value) or not low <= value <= high:
        raise invalid(f"{what} must be an integer {low}..{high}")
    return value


def validate_policy(rest, body):
    date = body.get("effective_from")
    if not isinstance(date, str) or timeutil.parse_date(date) is None:
        raise invalid("effective_from must be a YYYY-MM-DD date")
    hours, seen = [], set()
    raw_hours = body.get("opening_hours")
    if not isinstance(raw_hours, list):
        raise invalid("opening_hours must be an array")
    for entry in raw_hours:
        if not isinstance(entry, dict) or entry.get("weekday") not in timeutil.WEEKDAYS \
                or entry["weekday"] in seen:
            raise invalid("opening_hours entries need a distinct weekday")
        seen.add(entry["weekday"])
        opens = timeutil.parse_hhmm(entry["opens"]) if isinstance(entry.get("opens"), str) else None
        closes = timeutil.parse_hhmm(entry["closes"]) if isinstance(entry.get("closes"), str) else None
        if opens is None or closes is None or closes <= opens:
            raise invalid("opens/closes must be HH:MM with closes later than opens")
        hours.append({"weekday": entry["weekday"], "opens": entry["opens"], "closes": entry["closes"]})
    caps = body.get("capacities")
    if not isinstance(caps, dict) or set(caps) != {t["id"] for t in rest["tables"]}:
        raise invalid("capacities must name exactly the restaurant's tables")
    return {
        "effective_from": date,
        "slot_minutes": _int(body.get("slot_minutes"), 1, 1440, "slot_minutes"),
        "reservation_duration_minutes": _int(body.get("reservation_duration_minutes"), 1, 1440,
                                             "reservation_duration_minutes"),
        "cancellation_cutoff_minutes": _int(body.get("cancellation_cutoff_minutes"), 0, 10080,
                                            "cancellation_cutoff_minutes"),
        "opening_hours": hours,
        "capacities": {t["id"]: _int(caps[t["id"]], 1, 100, "capacity") for t in rest["tables"]},
    }


def publish(req, restaurant_id):
    """POST /restaurants/{id}/policies. Order: 404, 403, idempotency, then validation."""
    data = STORE.data
    rest = data.restaurants.get(restaurant_id)
    if rest is None:
        raise not_found("no such restaurant")
    if req.user_id not in rest.get("manager_user_ids", []):
        raise ApiError(403, "forbidden", "only the restaurant's managers may publish policies")

    def produce(data, body):
        policy = validate_policy(rest, body)
        listing = data.policies.setdefault(rest["id"], [])
        policy["policy_version"] = len(listing) + 1
        listing.append(policy)
        data.rest_rev[rest["id"]] = data.rest_rev.get(rest["id"], 0) + 1
        return clone(policy)
    return idempotency.run(req, produce)


def list_policies(req, restaurant_id):
    data = STORE.data
    if restaurant_id not in data.restaurants:
        raise not_found("no such restaurant")
    return 200, {"policies": clone(data.policies.get(restaurant_id, []))}
