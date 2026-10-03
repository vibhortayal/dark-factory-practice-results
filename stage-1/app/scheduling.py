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


def plan_slot(restaurant, table, naive, party_size):
    """Check a requested start against the restaurant rules, in the documented order:
    invalid_local_time, not_on_slot_grid, outside_opening_hours, party_exceeds_capacity.
    Returns (start, end) as UTC instants."""
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
    if party_size > table["capacity"]:
        raise ApiError(422, "party_exceeds_capacity", "party exceeds table capacity")
    return start, end


def interval(record):
    return datetime.fromisoformat(record["starts_at"]), datetime.fromisoformat(record["ends_at"])


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open intervals [start, end) on absolute instants."""
    return a_start < b_end and b_start < a_end


def table_free(data, restaurant_id, table_id, start, end, ignore=()):
    """True when no confirmed reservation (other than those in `ignore`, a set of
    references) occupies the table during [start, end)."""
    for ref, rec in data.reservations.items():
        if (rec["status"] != "confirmed" or ref in ignore
                or rec["restaurant_id"] != restaurant_id or rec["table_id"] != table_id):
            continue
        s, e = interval(rec)
        if overlaps(start, end, s, e):
            return False
    return True
