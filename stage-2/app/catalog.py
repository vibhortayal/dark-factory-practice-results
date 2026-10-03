"""Public read endpoints: restaurants and availability (spec §8)."""
from . import scheduling, timeutil
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
    rest = STORE.data.restaurants.get(rid)
    if rest is None:
        raise not_found("no such restaurant")
    data = STORE.data
    tz = timeutil.zone(rest["timezone"])
    slots = []
    for naive, start in scheduling.slots_for_day(rest, date):
        end = start + scheduling.duration(rest)
        free = [t["id"] for t in rest["tables"] if t["capacity"] >= party
                and scheduling.table_free(data, rest["id"], [t["id"]], start, end)]
        caps = {t["id"]: t["capacity"] for t in rest["tables"]}
        options = [{"table_ids": [t], "capacity": caps[t]} for t in free]
        for pair in scheduling.declared_pairs(rest):
            if caps[pair[0]] + caps[pair[1]] >= party and scheduling.table_free(
                    data, rest["id"], pair, start, end):
                options.append({"table_ids": list(pair), "capacity": caps[pair[0]] + caps[pair[1]]})
        slots.append({"starts_at_local": timeutil.local_text(naive),
                      "starts_at": timeutil.iso(start.astimezone(tz)), "available_table_ids": free,
                      "available_options": options})
    return 200, {"restaurant_id": rest["id"], "date": params["date"],
                 "timezone": rest["timezone"], "slots": slots}
