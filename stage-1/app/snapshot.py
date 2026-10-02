"""GET /_test/export and POST /_test/import."""
import copy

from .errors import ApiError, invalid
from .fixture import REF_RE, build_restaurant, check_no_overlaps
from .scheduling import find_table
from .store import empty_state

TRACK = "tablekeeper"
FORMAT_VERSION = 1


def export_state(store):
    with store.lock:
        return {"track": TRACK, "format_version": FORMAT_VERSION,
                "state": copy.deepcopy(store.data)}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _check(cond):
    if not cond:
        raise ValueError("bad state")


def _rebuild(state):
    """Validate an exported state and return a clean copy. Raises on any defect."""
    _check(isinstance(state, dict))
    out = empty_state()
    for uid, u in state["users"].items():
        _check(isinstance(u, dict) and u["id"] == uid and len(uid) <= 64)
        _check(all(isinstance(u[k], str) for k in ("email", "display_name", "password_hash")))
        _check(u["password_hash"].startswith("scrypt$"))
        out["users"][uid] = {k: u[k] for k in ("id", "email", "display_name", "password_hash")}
    _check(len({u["email"].lower() for u in out["users"].values()}) == len(out["users"]))
    for rid, r in state["restaurants"].items():
        _check(isinstance(r, dict) and r["id"] == rid)
        out["restaurants"][rid] = build_restaurant(r)
    for digest, uid in state["tokens"].items():
        _check(isinstance(digest, str) and uid in out["users"])
        out["tokens"][digest] = uid
    refs = set()
    for rid, r in state["reservations"].items():
        _check(isinstance(r, dict) and r["reservation_id"] == rid and len(rid) <= 64)
        rest = out["restaurants"][r["restaurant_id"]]
        _check(find_table(rest, r["table_id"]) is not None and r["user_id"] in out["users"])
        _check(isinstance(r["reference"], str) and REF_RE.match(r["reference"]))
        _check(r["reference"] not in refs)
        refs.add(r["reference"])
        _check(r["status"] in ("confirmed", "cancelled"))
        _check(_is_int(r["party_size"]) and r["party_size"] >= 1)
        _check(_is_int(r["start_ts"]) and _is_int(r["end_ts"]) and r["end_ts"] > r["start_ts"])
        _check(isinstance(r["starts_at_local"], str) and isinstance(r["created_at"], str))
        out["reservations"][rid] = {k: r[k] for k in (
            "reservation_id", "reference", "user_id", "restaurant_id", "table_id", "party_size",
            "status", "starts_at_local", "start_ts", "end_ts", "created_at")}
    check_no_overlaps(out["reservations"])
    for key, rec in state["idempotency"].items():
        _check(isinstance(key, str) and isinstance(rec["body"], str))
        _check(rec["status"] == 201 and isinstance(rec["response"], dict))
        out["idempotency"][key] = {"body": rec["body"], "status": 201,
                                   "response": copy.deepcopy(rec["response"])}
    counters = state["counters"]
    _check(_is_int(counters["user"]) and _is_int(counters["reservation"]))
    out["counters"] = {"user": counters["user"], "reservation": counters["reservation"]}
    return out


def import_state(store, body):
    if (body.get("track") != TRACK or body.get("format_version") != FORMAT_VERSION
            or isinstance(body.get("format_version"), bool) or "state" not in body):
        raise invalid("export must carry track 'tablekeeper', format_version 1 and a state")
    try:
        data = _rebuild(body["state"])
    except (ApiError, KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise invalid("state is invalid") from None
    store.replace(data)
