"""Reservation records: API view, history, revisions and series bookkeeping.

A stored record carries, besides its stage-2 fields, `revision`, `accepted_terms`
(the policy snapshot it was accepted under), `history` (list of entries) and, when
adopted into a recurring agreement, `series` = {"id", "index"}. The owner, history
and series link are internal; `public` produces the API view.
"""
from . import timeutil
from .jsonutil import clone

HIDDEN = ("user_id", "table_ids", "history", "series")


def public(rec):
    """API view: `table_ids` always, `table_id` only for a single table."""
    out = {k: v for k, v in rec.items() if k not in HIDDEN}
    out["table_ids"] = list(rec["table_ids"])
    if len(rec["table_ids"]) == 1:
        out["table_id"] = rec["table_ids"][0]
    out["accepted_terms"] = clone(rec["accepted_terms"])
    return out


def fields_of(rec):
    return {"table_ids": list(rec["table_ids"]), "starts_at_local": rec["starts_at_local"],
            "party_size": rec["party_size"]}


def diff(before, after):
    """History `changes` between two field sets (`before` None for creation).

    Tables are reported as `table_id` for single-to-single and as `table_ids` (complete
    lists) when either side is a pair; order is table(s), starts_at_local, party_size."""
    changes = []
    old = before["table_ids"] if before else None
    new = after["table_ids"]
    if before is None or set(old) != set(new):
        if len(new) == 2 or (old is not None and len(old) == 2):
            changes.append({"field": "table_ids", "from": None if old is None else list(old), "to": list(new)})
        else:
            changes.append({"field": "table_id", "from": None if old is None else old[0], "to": new[0]})
    for field in ("starts_at_local", "party_size"):
        old_value = None if before is None else before[field]
        if before is None or old_value != after[field]:
            changes.append({"field": field, "from": old_value, "to": after[field]})
    return changes


def add_history(rec, event, changes, at=None):
    rec["history"].append({
        "seq": len(rec["history"]) + 1, "at": at or timeutil.iso(timeutil.now_utc()),
        "event": event, "changes": changes, "revision": rec["revision"],
        "accepted_terms": clone(rec["accepted_terms"])})


def init_seeded(rec, terms):
    """Give a record without stage-3 data its starting point: revision 1, the given
    terms, and a single `created` history entry at its creation time."""
    rec["revision"] = 1
    rec["accepted_terms"] = clone(terms)
    rec["history"] = []
    add_history(rec, "created", diff(None, fields_of(rec)), at=rec["created_at"])


def new_record(data, user_id, rest, ids, start, end, naive, party, terms):
    tz = timeutil.zone(rest["timezone"])
    now = timeutil.iso(timeutil.now_utc())
    ref = data.new_reference()
    rec = {
        "reservation_id": data.new_reservation_id(), "reference": ref,
        "restaurant_id": rest["id"], "table_ids": list(ids), "party_size": party,
        "status": "confirmed", "starts_at_local": timeutil.local_text(naive),
        "starts_at": timeutil.iso(start.astimezone(tz)), "ends_at": timeutil.iso(end.astimezone(tz)),
        "created_at": now, "user_id": user_id,
    }
    init_seeded(rec, terms)
    data.reservations[ref] = rec
    return rec


def bump_restaurant(data, restaurant_id):
    data.rest_rev[restaurant_id] = data.rest_rev.get(restaurant_id, 0) + 1


def series_of(data, rec):
    link = rec.get("series")
    return data.series.get(link["id"]) if link else None


def bump_series(data, rec):
    s = series_of(data, rec)
    if s:
        s["revision"] += 1


def mark_exception(data, rec):
    s = series_of(data, rec)
    if s:
        s["occurrences"][rec["series"]["index"]]["exception"] = True
