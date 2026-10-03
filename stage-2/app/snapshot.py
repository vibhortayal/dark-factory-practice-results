"""Building Data from a reset fixture (§4) and from an export (§10), and exporting."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfoNotFoundError

from . import auth, timeutil, validate
from .errors import invalid, malformed
from .jsonutil import clone
from .state import Data
from .validate import MAX_ID, is_int, party_size

REFERENCE_RE = re.compile(r"^[A-Z0-9]{6,12}$")
STATUSES = ("confirmed", "cancelled")


def _obj(value, what):
    if not isinstance(value, dict):
        raise malformed(f"{what} must be an object")
    return value


def _list(value, what):
    if not isinstance(value, list):
        raise malformed(f"{what} must be an array")
    return value


def _id(value, what):
    if not isinstance(value, str):
        raise malformed(f"{what} must be a string")
    if not value or len(value) > MAX_ID:
        raise invalid(f"{what} must be 1 to {MAX_ID} characters")
    return value


def _str(value, what):
    if not isinstance(value, str):
        raise malformed(f"{what} must be a string")
    return value


def _posint(value, what, minimum=1):
    """Wrong JSON type -> 400; a number that is not an integer or is too small -> 422."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise malformed(f"{what} must be an integer")
    if not is_int(value) or value < minimum:
        raise invalid(f"{what} must be an integer >= {minimum}")
    return value


def normalize_restaurant(raw):
    raw = _obj(raw, "restaurant")
    rid = _id(raw.get("id"), "restaurant id")
    tzname = _str(raw.get("timezone"), "timezone")
    try:
        timeutil.zone(tzname)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise invalid("unknown timezone")
    hours = []
    for entry in _list(raw.get("opening_hours", []), "opening_hours"):
        entry = _obj(entry, "opening hours entry")
        if _str(entry.get("weekday"), "weekday") not in timeutil.WEEKDAYS:
            raise invalid("weekday must be one of mon..sun")
        opens = timeutil.parse_hhmm(_str(entry.get("opens"), "opens"))
        closes = timeutil.parse_hhmm(_str(entry.get("closes"), "closes"))
        if opens is None or closes is None or closes <= opens:
            raise invalid("opens/closes must be HH:MM with closes later than opens")
        hours.append({"weekday": entry["weekday"], "opens": entry["opens"],
                      "closes": entry["closes"]})
    tables, seen = [], set()
    for t in _list(raw.get("tables", []), "tables"):
        t = _obj(t, "table")
        tid = _id(t.get("id"), "table id")
        if tid in seen:
            raise invalid("duplicate table id")
        seen.add(tid)
        label = t.get("label", tid)
        tables.append({"id": tid, "label": _str(label, "label"),
                       "capacity": _posint(t.get("capacity"), "capacity")})
    combinable, seen_pairs = [], set()
    for pair in _list(raw.get("combinable", []), "combinable"):
        pair = _list(pair, "combinable entry")
        ids = [_str(t, "combinable table id") for t in pair]
        if len(ids) != 2 or ids[0] == ids[1] or not set(ids) <= seen:
            raise invalid("combinable entries are pairs of two different table ids of this restaurant")
        if frozenset(ids) not in seen_pairs:
            seen_pairs.add(frozenset(ids))
            combinable.append(ids)
    out = {
        "id": rid,
        "name": _str(raw.get("name", rid), "name"),
        "timezone": tzname,
        "slot_minutes": _posint(raw.get("slot_minutes"), "slot_minutes"),
        "reservation_duration_minutes": _posint(raw.get("reservation_duration_minutes"),
                                                "reservation_duration_minutes"),
        "cancellation_cutoff_minutes": _posint(raw.get("cancellation_cutoff_minutes"),
                                               "cancellation_cutoff_minutes", 0),
        "opening_hours": hours,
        "tables": tables,
    }
    if "combinable" in raw:  # echoed in the fixture's shape; absent stays absent
        out["combinable"] = combinable
    return out


def _add_user(data, uid, email, display_name, password_hash):
    key = email.lower()
    if uid in data.users or key in data.emails:
        raise invalid("duplicate user id or email")
    data.users[uid] = {"id": uid, "email": email, "display_name": display_name,
                       "password_hash": password_hash}
    data.emails[key] = uid


def _seed_reservation(data, raw, now_iso):
    raw = _obj(raw, "reservation")
    ref = _id(raw.get("reference"), "reference")
    if not REFERENCE_RE.match(ref):
        raise invalid("reference must be 6 to 12 characters of A-Z0-9")
    if ref in data.reservations:
        raise invalid("duplicate reference")
    rest = data.restaurants.get(_id(raw.get("restaurant_id"), "restaurant_id"))
    table_ids = validate.table_selection(raw, required=True)
    known = {t["id"] for t in rest["tables"]} if rest else set()
    if rest is None or not set(table_ids) <= known or len(table_ids) > 2:
        raise invalid("reservation names an unknown restaurant or table")
    naive = timeutil.parse_local(_str(raw.get("starts_at_local"), "starts_at_local"))
    if naive is None:
        raise invalid("starts_at_local must be YYYY-MM-DDTHH:MM")
    tz = timeutil.zone(rest["timezone"])
    start = timeutil.resolve_local(tz, naive)
    if start is None:
        raise invalid("starts_at_local does not exist")
    end = start + timedelta(minutes=rest["reservation_duration_minutes"])
    status = raw.get("status", "confirmed")
    if status not in STATUSES:
        raise invalid("bad status")
    created = raw.get("created_at")
    data.reservations[ref] = {
        "reservation_id": _id(raw.get("id", raw.get("reservation_id")), "reservation id"),
        "reference": ref,
        "restaurant_id": rest["id"],
        "table_ids": table_ids,
        "party_size": party_size(raw.get("party_size")),  # §5: any bad party_size is 422
        "status": status,
        "starts_at_local": timeutil.local_text(naive),
        "starts_at": timeutil.iso(start.astimezone(tz)),
        "ends_at": timeutil.iso(end.astimezone(tz)),
        "created_at": created if isinstance(created, str) else now_iso,
        "user_id": _id(raw.get("user_id"), "user_id"),
    }


def from_fixture(body):
    """Validate a reset fixture and return fresh Data (never touches live state)."""
    body = _obj(body, "fixture")
    data = Data()
    users = []
    for u in _list(body.get("users", []), "users"):
        u = _obj(u, "user")
        users.append((_id(u.get("id"), "user id"), _str(u.get("email"), "email"),
                      _str(u.get("display_name", ""), "display_name"),
                      _str(u.get("password"), "password")))
    for r in _list(body.get("restaurants", []), "restaurants"):
        rest = normalize_restaurant(r)
        if rest["id"] in data.restaurants:
            raise invalid("duplicate restaurant id")
        data.restaurants[rest["id"]] = rest
    now_iso = timeutil.iso(timeutil.now_utc())
    ids = set()
    for r in _list(body.get("reservations", []), "reservations"):
        _seed_reservation(data, r, now_iso)
    for rec in data.reservations.values():
        if rec["reservation_id"] in ids:
            raise invalid("duplicate reservation id")
        ids.add(rec["reservation_id"])
    # hash last, so a rejected fixture never pays for hashing (scrypt releases the GIL)
    with ThreadPoolExecutor(max_workers=4) as pool:
        hashes = list(pool.map(lambda u: auth.hash_password(u[3]), users))
    for (uid, email, name, _), hashed in zip(users, hashes):
        _add_user(data, uid, email, name, hashed)
    return data


def export_state(data):
    return clone({
        "users": list(data.users.values()),
        "tokens": [[t, u] for t, u in data.tokens.items()],
        "restaurants": list(data.restaurants.values()),
        "reservations": list(data.reservations.values()),
        "idempotency": [{"user_id": u, "path": p, "key": k, **rec}
                        for (u, p, k), rec in data.idem.items()],
        "counters": {"next_user": data.next_user, "next_res": data.next_res},
    })


RES_FIELDS = ("reservation_id", "reference", "restaurant_id", "status",
              "starts_at_local", "starts_at", "ends_at", "created_at", "user_id")


def from_state(state):
    """Rebuild Data from an export; any structural problem raises 422."""
    state = _obj(state, "state")
    data = Data()
    for u in _list(state.get("users"), "users"):
        u = _obj(u, "user")
        _add_user(data, _id(u.get("id"), "user id"), _str(u.get("email"), "email"),
                  _str(u.get("display_name"), "display_name"),
                  _str(u.get("password_hash"), "password_hash"))
    for rest in _list(state.get("restaurants"), "restaurants"):
        rest = normalize_restaurant(rest)
        data.restaurants[rest["id"]] = rest
    for t in _list(state.get("tokens"), "tokens"):
        if not (isinstance(t, list) and len(t) == 2 and isinstance(t[0], str)
                and t[1] in data.users):
            raise invalid("bad token entry")
        data.tokens[t[0]] = t[1]
    rids = set()
    for rec in _list(state.get("reservations"), "reservations"):
        rec = _obj(rec, "reservation")
        for f in RES_FIELDS:
            _str(rec.get(f), f)
        _posint(rec.get("party_size"), "party_size")
        rec = dict(rec)
        if "table_ids" not in rec:  # stage-1 export: one table
            rec["table_ids"] = [_id(rec.pop("table_id", None), "table_id")]
        rec.pop("table_id", None)
        ids = rec["table_ids"]
        if not (isinstance(ids, list) and 1 <= len(ids) <= 2 and all(isinstance(t, str) for t in ids)):
            raise invalid("bad table_ids")
        rest = data.restaurants.get(rec["restaurant_id"])
        if (rest is None or rec["status"] not in STATUSES
                or not set(ids) <= {t["id"] for t in rest["tables"]}
                or rec["reference"] in data.reservations
                or rec["reservation_id"] in rids or rec["user_id"] not in data.users):
            raise invalid("inconsistent reservation")
        for f in ("starts_at", "ends_at"):
            try:
                datetime.fromisoformat(rec[f])
            except ValueError:
                raise invalid(f"bad {f}")
        rids.add(rec["reservation_id"])
        data.reservations[rec["reference"]] = rec
    for item in _list(state.get("idempotency"), "idempotency"):
        item = _obj(item, "idempotency record")
        if not is_int(item.get("status")) or not isinstance(item.get("response"), (dict, list)):
            raise invalid("bad idempotency record")
        data.idem[(_str(item.get("user_id"), "user_id"), _str(item.get("path"), "path"),
                   _str(item.get("key"), "key"))] = {
            "body": _str(item.get("body"), "body"), "status": item["status"],
            "response": clone(item["response"])}
    counters = _obj(state.get("counters"), "counters")
    data.next_user = _posint(counters.get("next_user"), "next_user")
    data.next_res = _posint(counters.get("next_res"), "next_res")
    return data
