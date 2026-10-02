"""JSON shapes returned by the API."""
from .timeutil import iso_at


def reservation_view(store, r):
    tz = store.data["restaurants"][r["restaurant_id"]]["timezone"]
    return {
        "reservation_id": r["reservation_id"],
        "reference": r["reference"],
        "restaurant_id": r["restaurant_id"],
        "table_id": r["table_id"],
        "party_size": r["party_size"],
        "status": r["status"],
        "starts_at_local": r["starts_at_local"],
        "starts_at": iso_at(tz, r["start_ts"]),
        "ends_at": iso_at(tz, r["end_ts"]),
        "created_at": r["created_at"],
    }


def restaurant_view(rest):
    return {k: rest[k] for k in (
        "id", "name", "timezone", "slot_minutes", "reservation_duration_minutes",
        "cancellation_cutoff_minutes", "opening_hours", "tables")}
