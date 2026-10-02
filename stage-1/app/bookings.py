"""Create, read, list, cancel and amend reservations."""
import secrets

from . import idempotency
from .errors import conflict, invalid, malformed, not_found
from .scheduling import check_booking, ensure_free
from .timeutil import parse_local, utc_stamp
from .views import reservation_view

MAX_ID = 64
_REF_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
AMEND_FIELDS = ("table_id", "starts_at_local", "party_size")


def parse_fields(body, names, required):
    """Type (400) then presence/format (422) checks. Returns the fields present."""
    for name in names:
        if name in body and name != "party_size" and not isinstance(body[name], str):
            raise malformed("%s must be a string" % name)
    out = {}
    for name in names:
        if name not in body:
            if required:
                raise invalid("%s is required" % name)
            continue
        value = body[name]
        if name == "party_size":
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise invalid("party_size must be an integer of at least 1")
        elif name == "starts_at_local":
            value = parse_local(value)
        elif len(value) > MAX_ID:
            raise invalid("%s is too long" % name)
        out[name] = value
    return out


def _new_reference(store):
    while True:
        ref = "".join(secrets.choice(_REF_ALPHABET) for _ in range(8))
        if ref not in store.by_ref:
            return ref


def _local_text(naive):
    return naive.strftime("%Y-%m-%dT%H:%M")


def create(store, user_id, key, body):
    rkey = idempotency.record_key(user_id, "POST", "/reservations", key)
    with store.lock:
        replay = idempotency.lookup(store, rkey, body)
        if replay is not None:
            return 200, replay
        f = parse_fields(body, ("restaurant_id", "table_id", "starts_at_local", "party_size"), True)
        rest = store.data["restaurants"].get(f["restaurant_id"])
        if rest is None:
            raise not_found("unknown restaurant")
        start_ts, end_ts = check_booking(rest, f["table_id"], f["starts_at_local"], f["party_size"])
        ensure_free(store, rest["id"], f["table_id"], start_ts, end_ts)
        rid = store.next_id("reservation", "res_", store.data["reservations"])
        rec = {"reservation_id": rid, "reference": _new_reference(store), "user_id": user_id,
               "restaurant_id": rest["id"], "table_id": f["table_id"],
               "party_size": f["party_size"], "status": "confirmed",
               "starts_at_local": _local_text(f["starts_at_local"]),
               "start_ts": start_ts, "end_ts": end_ts, "created_at": utc_stamp()}
        store.data["reservations"][rid] = rec
        store.by_ref[rec["reference"]] = rec
        response = reservation_view(store, rec)
        idempotency.remember(store, rkey, body, response)
        return 201, response


def owned(store, user_id, reference):
    rec = store.by_ref.get(reference)
    if rec is None or rec["user_id"] != user_id:
        raise not_found("no such reservation")
    return rec


def list_for(store, user_id):
    with store.lock:
        mine = [r for r in store.data["reservations"].values() if r["user_id"] == user_id]
        mine.sort(key=lambda r: (-r["start_ts"], r["reservation_id"]))
        return {"reservations": [reservation_view(store, r) for r in mine]}


def get(store, user_id, reference):
    with store.lock:
        return reservation_view(store, owned(store, user_id, reference))


def cutoff_passed(store, rec, now):
    cutoff = store.data["restaurants"][rec["restaurant_id"]]["cancellation_cutoff_minutes"]
    return now >= rec["start_ts"] - cutoff * 60


def require_amendable(store, rec, now):
    if rec["status"] == "cancelled":
        raise conflict("reservation_cancelled", "reservation is cancelled")
    if cutoff_passed(store, rec, now):
        raise conflict("cutoff_passed", "within the cancellation cutoff")


def cancel(store, user_id, reference, now):
    with store.lock:
        rec = owned(store, user_id, reference)
        if rec["status"] != "cancelled":
            if cutoff_passed(store, rec, now):
                raise conflict("cutoff_passed", "within the cancellation cutoff")
            rec["status"] = "cancelled"
        return reservation_view(store, rec)


def plan_amendment(store, rec, fields):
    """Validate merged values; return the new values (without touching state)."""
    rest = store.data["restaurants"][rec["restaurant_id"]]
    table_id = fields.get("table_id", rec["table_id"])
    party = fields.get("party_size", rec["party_size"])
    if "starts_at_local" in fields:
        naive = fields["starts_at_local"]
    else:
        naive = parse_local(rec["starts_at_local"])
    start_ts, end_ts = check_booking(rest, table_id, naive, party)
    return {"table_id": table_id, "party_size": party, "starts_at_local": _local_text(naive),
            "start_ts": start_ts, "end_ts": end_ts}


def amend(store, user_id, reference, body, now):
    with store.lock:
        rec = owned(store, user_id, reference)
        require_amendable(store, rec, now)
        fields = parse_fields(body, AMEND_FIELDS, False)
        if fields:
            new = plan_amendment(store, rec, fields)
            ensure_free(store, rec["restaurant_id"], new["table_id"], new["start_ts"],
                        new["end_ts"], ignore=(rec["reservation_id"],))
            rec.update(new)
        return reservation_view(store, rec)
