"""Public read endpoints: restaurants and availability (spec §8, stage 2 options, stage 3 explain)."""
from . import policies, scheduling, timeutil
from .errors import invalid, not_found
from .jsonutil import clone
from .state import STORE
from .validate import query_int


def list_restaurants(req):
    return 200, {"restaurants": [{"id": r["id"], "name": r["name"], "timezone": r["timezone"]}
                                 for r in STORE.data.restaurants.values()]}


def get_restaurant(req, restaurant_id):
    rest = STORE.data.restaurants.get(restaurant_id)
    if rest is None:
        raise not_found("no such restaurant")
    return 200, clone(rest)


def _explanation(table, party, free, version):
    fits, clear = party <= table["capacity"], free
    return {"table_id": table["id"], "policy_version": version, "available": fits and clear,
            "rules": [{"rule": "capacity", "holds": fits}, {"rule": "no_overlap", "holds": clear}]}


def availability(req):
    params = req.query
    rid = params.get("restaurant_id")
    if not rid:
        raise invalid("restaurant_id is required")
    if not params.get("date"):
        raise invalid("date is required")
    party = query_int(params, "party_size")
    if party < 1:
        raise invalid("party_size must be at least 1")
    date = timeutil.parse_date(params["date"])
    if date is None:
        raise invalid("date must be a valid YYYY-MM-DD")
    if "explain" in params and params["explain"] != "true":
        raise invalid("explain accepts only the value true")
    explain = "explain" in params
    rest = STORE.data.restaurants.get(rid)
    if rest is None:
        raise not_found("no such restaurant")
    data = STORE.data
    terms = policies.select_terms(data, rest, date)
    view = policies.rules_view(rest, terms)
    tz = timeutil.zone(rest["timezone"])
    caps = {t["id"]: t["capacity"] for t in view["tables"]}
    slots = []
    for naive, start in scheduling.slots_for_day(view, date):
        end = start + scheduling.duration(view)
        clear = {t["id"]: scheduling.table_free(data, rest["id"], [t["id"]], start, end) for t in view["tables"]}
        free = [t["id"] for t in view["tables"] if t["capacity"] >= party and clear[t["id"]]]
        options = [{"table_ids": [t], "capacity": caps[t]} for t in free]
        for pair in scheduling.declared_pairs(view):
            if caps[pair[0]] + caps[pair[1]] >= party and clear[pair[0]] and clear[pair[1]]:
                options.append({"table_ids": list(pair), "capacity": caps[pair[0]] + caps[pair[1]]})
        slot = {"starts_at_local": timeutil.local_text(naive),
                "starts_at": timeutil.iso(start.astimezone(tz)),
                "available_table_ids": free, "available_options": options}
        if explain:
            slot["explain"] = [_explanation(t, party, clear[t["id"]], terms["policy_version"])
                               for t in view["tables"]]
        slots.append(slot)
    return 200, {"restaurant_id": rest["id"], "date": params["date"],
                 "timezone": rest["timezone"], "slots": slots}
