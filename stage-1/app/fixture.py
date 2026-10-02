"""POST /_test/reset: validate a fixture and build a fresh state from it."""
import re
from concurrent.futures import ThreadPoolExecutor

from .accounts import hash_password, valid_email
from .errors import invalid, malformed
from .scheduling import find_table, overlaps
from .store import empty_state
from .timeutil import WEEKDAYS, parse_hhmm, parse_local, resolve_local, utc_stamp, valid_zone

MAX_ID = 64
REF_RE = re.compile(r"^[A-Z0-9]{6,12}$")


def need(obj, name, kind):
    """Required field: missing -> 422, wrong JSON type -> 400."""
    if name not in obj:
        raise invalid("%s is required" % name)
    return typed(obj, name, kind)


def typed(obj, name, kind):
    value = obj[name]
    if kind is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise malformed("%s must be an integer" % name)
    elif not isinstance(value, kind):
        raise malformed("%s has the wrong type" % name)
    return value


def need_id(obj, name="id"):
    value = need(obj, name, str)
    if not value or len(value) > MAX_ID:
        raise invalid("%s must be 1 to %d characters" % (name, MAX_ID))
    return value


def objects(value, name):
    if not isinstance(value, list):
        raise malformed("%s must be an array" % name)
    for item in value:
        if not isinstance(item, dict):
            raise malformed("%s entries must be objects" % name)
    return value


def build_restaurant(obj):
    rest = {"id": need_id(obj), "name": need(obj, "name", str), "timezone": need(obj, "timezone", str)}
    if not valid_zone(rest["timezone"]):
        raise invalid("unknown timezone")
    for name, low, high in (("slot_minutes", 1, 1440), ("reservation_duration_minutes", 1, 100000),
                            ("cancellation_cutoff_minutes", 0, 10 ** 9)):
        rest[name] = need(obj, name, int)
        if not low <= rest[name] <= high:
            raise invalid("%s out of range" % name)
    hours = []
    for entry in objects(need(obj, "opening_hours", list), "opening_hours"):
        day = need(entry, "weekday", str)
        opens, closes = need(entry, "opens", str), need(entry, "closes", str)
        o, c = parse_hhmm(opens), parse_hhmm(closes)
        if day not in WEEKDAYS or o is None or c is None or c <= o:
            raise invalid("invalid opening_hours entry")
        hours.append({"weekday": day, "opens": opens, "closes": closes})
    rest["opening_hours"] = hours
    tables, seen = [], set()
    for t in objects(need(obj, "tables", list), "tables"):
        tid = need_id(t)
        capacity = need(t, "capacity", int)
        label = typed(t, "label", str) if "label" in t else tid
        if tid in seen or capacity < 1:
            raise invalid("duplicate table id or capacity below 1")
        seen.add(tid)
        tables.append({"id": tid, "label": label, "capacity": capacity})
    rest["tables"] = tables
    return rest


def build_seed_reservation(store_view, obj, created_at):
    rest = store_view["restaurants"].get(need(obj, "restaurant_id", str))
    table_id = need(obj, "table_id", str)
    party = need(obj, "party_size", int)
    local = need(obj, "starts_at_local", str)
    if rest is None or find_table(rest, table_id) is None or party < 1:
        raise invalid("seeded reservation names an unknown restaurant/table or bad party_size")
    start_ts = resolve_local(rest["timezone"], parse_local(local))
    if start_ts is None:
        raise invalid("seeded reservation has a nonexistent local time")
    ref = need(obj, "reference", str)
    if not REF_RE.match(ref):
        raise invalid("reference must be 6 to 12 characters of A-Z0-9")
    status = typed(obj, "status", str) if "status" in obj else "confirmed"
    if status not in ("confirmed", "cancelled"):
        raise invalid("bad seeded status")
    return {"reservation_id": need_id(obj), "reference": ref, "user_id": need_id(obj, "user_id"),
            "restaurant_id": rest["id"], "table_id": table_id, "party_size": party,
            "status": status, "starts_at_local": local, "start_ts": start_ts,
            "end_ts": start_ts + rest["reservation_duration_minutes"] * 60,
            "created_at": created_at}


def check_no_overlaps(reservations):
    by_table = {}
    for r in reservations.values():
        if r["status"] == "confirmed":
            by_table.setdefault((r["restaurant_id"], r["table_id"]), []).append(r)
    for group in by_table.values():
        group.sort(key=lambda r: r["start_ts"])
        for a, b in zip(group, group[1:]):
            if overlaps(a["start_ts"], a["end_ts"], b["start_ts"], b["end_ts"]):
                raise invalid("overlapping confirmed reservations on one table")


def build_state(body):
    """Return a complete new state dict, or raise 400/422 without side effects."""
    users_in = objects(body.get("users", []), "users")
    rests_in = objects(body.get("restaurants", []), "restaurants")
    res_in = objects(body.get("reservations", []), "reservations")
    state = empty_state()
    pending = []
    for u in users_in:
        uid = need_id(u)
        email = need(u, "email", str)
        password = need(u, "password", str)
        name = need(u, "display_name", str)
        if not valid_email(email) or uid in state["users"] or any(
                email.lower() == p["email"].lower() for p in state["users"].values()):
            raise invalid("invalid or duplicate seeded user")
        state["users"][uid] = {"id": uid, "email": email, "display_name": name,
                               "password_hash": None}
        pending.append((uid, password))
    for r in rests_in:
        rest = build_restaurant(r)
        if rest["id"] in state["restaurants"]:
            raise invalid("duplicate restaurant id")
        state["restaurants"][rest["id"]] = rest
    created_at = utc_stamp()
    for r in res_in:
        rec = build_seed_reservation(state, r, created_at)
        if rec["user_id"] not in state["users"]:
            raise invalid("seeded reservation names an unknown user")
        if rec["reservation_id"] in state["reservations"] or any(
                x["reference"] == rec["reference"] for x in state["reservations"].values()):
            raise invalid("duplicate reservation id or reference")
        state["reservations"][rec["reservation_id"]] = rec
    check_no_overlaps(state["reservations"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        hashes = list(pool.map(lambda p: hash_password(p[1]), pending))
    for (uid, _), h in zip(pending, hashes):
        state["users"][uid]["password_hash"] = h
    return state
