"""Opening hours, slot grid, capacity and table-occupancy rules."""
from .errors import ApiError, conflict, invalid, not_found
from .timeutil import WEEKDAYS, local_at, parse_hhmm, resolve_local


def windows_for(restaurant, weekday):
    name = WEEKDAYS[weekday]
    out = []
    for entry in restaurant["opening_hours"]:
        if entry["weekday"] == name:
            out.append((parse_hhmm(entry["opens"]), parse_hhmm(entry["closes"])))
    return out


def find_table(restaurant, table_id):
    for table in restaurant["tables"]:
        if table["id"] == table_id:
            return table
    return None


def check_slot(restaurant, naive):
    """Validate a local start time; return (start_ts, end_ts) in epoch seconds.

    Order: nonexistent local time, slot grid, opening hours (wall-clock minutes).
    """
    start_ts = resolve_local(restaurant["timezone"], naive)
    if start_ts is None:
        raise invalid("that local time does not exist (DST gap)", "invalid_local_time")
    minute = naive.hour * 60 + naive.minute
    duration = restaurant["reservation_duration_minutes"]
    wins = windows_for(restaurant, naive.weekday())
    if wins and not any((minute - o) % restaurant["slot_minutes"] == 0 for o, _ in wins):
        raise invalid("not on the slot grid", "not_on_slot_grid")
    if not any(o <= minute and minute + duration <= c for o, c in wins):
        raise invalid("outside opening hours", "outside_opening_hours")
    return start_ts, start_ts + duration * 60


def check_booking(restaurant, table_id, naive, party_size):
    """Rules shared by create, PATCH and moves, after type/format validation."""
    table = find_table(restaurant, table_id)
    if table is None:
        raise not_found("unknown table for this restaurant")
    start_ts, end_ts = check_slot(restaurant, naive)
    if party_size > table["capacity"]:
        raise invalid("party exceeds table capacity", "party_exceeds_capacity")
    return start_ts, end_ts


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def has_conflict(store, restaurant_id, table_id, start_ts, end_ts, ignore=()):
    for r in store.data["reservations"].values():
        if (r["status"] == "confirmed" and r["table_id"] == table_id
                and r["restaurant_id"] == restaurant_id and r["reservation_id"] not in ignore
                and overlaps(start_ts, end_ts, r["start_ts"], r["end_ts"])):
            return True
    return False


def ensure_free(store, restaurant_id, table_id, start_ts, end_ts, ignore=()):
    if has_conflict(store, restaurant_id, table_id, start_ts, end_ts, ignore):
        raise conflict("table_unavailable", "the table is taken for an overlapping interval")


def slots_for_date(restaurant, date):
    """[(local naive datetime, start_ts)] for every bookable slot of a local date."""
    import datetime as dt
    slots = {}
    duration = restaurant["reservation_duration_minutes"]
    step = restaurant["slot_minutes"]
    for opens, closes in windows_for(restaurant, date.weekday()):
        minute = opens
        while minute + duration <= closes:
            naive = dt.datetime.combine(date, dt.time(minute // 60, minute % 60))
            ts = resolve_local(restaurant["timezone"], naive)
            if ts is not None:
                slots[naive] = ts
            minute += step
    return sorted(slots.items())
