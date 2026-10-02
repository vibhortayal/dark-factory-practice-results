"""Public endpoints: restaurants and availability."""
import re

from .errors import invalid, not_found
from .scheduling import overlaps, slots_for_date
from .timeutil import iso_at, parse_date
from .views import restaurant_view

_INT_RE = re.compile(r"^[0-9]{1,18}$")


def query_int(value, name, minimum=1):
    if value is None or not _INT_RE.match(value):
        raise invalid("%s must be plain decimal digits" % name)
    n = int(value)
    if n < minimum:
        raise invalid("%s must be at least %d" % (name, minimum))
    return n


def list_restaurants(store):
    with store.lock:
        return {"restaurants": [{"id": r["id"], "name": r["name"], "timezone": r["timezone"]}
                                for r in store.data["restaurants"].values()]}


def get_restaurant(store, rid):
    with store.lock:
        rest = store.data["restaurants"].get(rid)
        if rest is None:
            raise not_found("unknown restaurant")
        return restaurant_view(rest)


def availability(store, query):
    rid = query.get("restaurant_id")
    date_text = query.get("date")
    party_text = query.get("party_size")
    if not rid or not date_text or party_text is None or party_text == "":
        raise invalid("restaurant_id, date and party_size are required")
    date = parse_date(date_text)
    party = query_int(party_text, "party_size")
    with store.lock:
        rest = store.data["restaurants"].get(rid)
        if rest is None:
            raise not_found("unknown restaurant")
        duration = rest["reservation_duration_minutes"] * 60
        busy = {}
        for r in store.data["reservations"].values():
            if r["restaurant_id"] == rid and r["status"] == "confirmed":
                busy.setdefault(r["table_id"], []).append((r["start_ts"], r["end_ts"]))
        tz = rest["timezone"]
        slots = []
        for naive, ts in slots_for_date(rest, date):
            free = [t["id"] for t in rest["tables"]
                    if t["capacity"] >= party
                    and not any(overlaps(ts, ts + duration, s, e) for s, e in busy.get(t["id"], ()))]
            slots.append({"starts_at_local": naive.strftime("%Y-%m-%dT%H:%M"),
                          "starts_at": iso_at(tz, ts), "available_table_ids": free})
        return {"restaurant_id": rid, "date": date_text, "timezone": tz, "slots": slots}
