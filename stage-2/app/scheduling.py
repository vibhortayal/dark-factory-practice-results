"""Opening hours, the slot grid and occupancy: the rules shared by availability,
booking, amendment and moves."""
from datetime import datetime, timedelta

from . import timeutil
from .errors import ApiError


def hours_for(restaurant, date):
    """The opening-hours entry for a local date, or None if closed."""
    key = timeutil.weekday_key(date)
    for entry in restaurant["opening_hours"]:
        if entry["weekday"] == key:
            return entry
    return None


def duration(restaurant):
    return timedelta(minutes=restaurant["reservation_duration_minutes"])


def _midnight(date):
    return datetime(date.year, date.month, date.day)


def day_bounds(restaurant, date, entry):
    """(opens_minutes, opens_instant, closes_instant) for one local day."""
    tz = timeutil.zone(restaurant["timezone"])
    opens = timeutil.parse_hhmm(entry["opens"])
    closes = timeutil.parse_hhmm(entry["closes"])
    closes_at = timeutil.instant_of_wall(tz, _midnight(date) + timedelta(minutes=closes))
    opens_at = timeutil.instant_of_wall(tz, _midnight(date) + timedelta(minutes=opens))
    return opens, opens_at, closes_at


def slots_for_day(restaurant, date):
    """[(naive_local, start_instant)] for every bookable slot that day, in order."""
    entry = hours_for(restaurant, date)
    if entry is None:
        return []
    tz = timeutil.zone(restaurant["timezone"])
    opens, _, closes_at = day_bounds(restaurant, date, entry)
    closes = timeutil.parse_hhmm(entry["closes"])
    out, minute = [], opens
    while minute < closes:
        naive = _midnight(date) + timedelta(minutes=minute)
        start = timeutil.resolve_local(tz, naive)
        if start is not None:
            if start + duration(restaurant) > closes_at:
                break
            out.append((naive, start))
        minute += restaurant["slot_minutes"]
    return out


def declared_pairs(restaurant):
    return [tuple(p) for p in restaurant.get("combinable", [])]


def canonical_tables(restaurant, ids):
    """Check a table set is bookable as a unit and return it in canonical order:
    a single table, or a declared pair in `combinable` order."""
    if len(ids) == 1:
        return list(ids)
    if len(ids) == 2:
        for pair in declared_pairs(restaurant):
            if set(pair) == set(ids):
                return list(pair)
    raise ApiError(422, "combination_not_allowed", "those tables cannot be combined")


def plan_slot(restaurant, tables, naive, party_size):
    """Check a requested booking against the restaurant rules, in the documented order:
    combination_not_allowed, invalid_local_time, not_on_slot_grid, outside_opening_hours,
    party_exceeds_capacity. `tables` are table dicts that exist in the restaurant.
    Returns (start, end, table_ids) with UTC instants and canonical table order."""
    ids = canonical_tables(restaurant, [t["id"] for t in tables])
    tz = timeutil.zone(restaurant["timezone"])
    start = timeutil.resolve_local(tz, naive)
    if start is None:
        raise ApiError(422, "invalid_local_time", "that local time does not exist")
    date = naive.date()
    entry = hours_for(restaurant, date)
    if entry is None:
        raise ApiError(422, "outside_opening_hours", "the restaurant is closed that day")
    opens, opens_at, closes_at = day_bounds(restaurant, date, entry)
    minute = naive.hour * 60 + naive.minute
    if (minute - opens) % restaurant["slot_minutes"] != 0:
        raise ApiError(422, "not_on_slot_grid", "start is not on the slot grid")
    end = start + duration(restaurant)
    if start < opens_at or end > closes_at:
        raise ApiError(422, "outside_opening_hours", "outside opening hours")
    if party_size > sum(t["capacity"] for t in tables):
        raise ApiError(422, "party_exceeds_capacity", "party exceeds table capacity")
    return start, end, ids


def interval(record):
    return datetime.fromisoformat(record["starts_at"]), datetime.fromisoformat(record["ends_at"])


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open intervals [start, end) on absolute instants."""
    return a_start < b_end and b_start < a_end


def table_free(data, restaurant_id, table_ids, start, end, ignore=()):
    """True when no confirmed reservation (other than those in `ignore`, a set of
    references) occupies any of `table_ids` during [start, end)."""
    wanted = set(table_ids)
    for ref, rec in data.reservations.items():
        if (rec["status"] != "confirmed" or ref in ignore
                or rec["restaurant_id"] != restaurant_id or not wanted.intersection(rec["table_ids"])):
            continue
        s, e = interval(rec)
        if overlaps(start, end, s, e):
            return False
    return True
