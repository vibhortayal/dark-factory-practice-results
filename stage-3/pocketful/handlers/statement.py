"""GET /statement: a paginated statement with stable snapshots."""
import secrets

from .. import history
from ..errors import invalid, not_found
from ..store import store
from ..timefmt import fmt, parse_iso
from ..validation import page_params, query_instant


def _entry(move, balance_after):
    payment = dict(store.payments_by_id[move.pid], amount=move.amount)
    return {"payment": payment, "delta": move.delta, "balance_after": balance_after,
            "revision": move.revision, "effective_at": move.effective_at, "recorded_at": move.recorded_at}


def _render(user_id, snap, limit, offset):
    start = parse_iso(snap["from_at"]) if snap["from_at"] else None
    opening, entries, closing = history.statement(
        user_id, start, parse_iso(snap["to_at"]), parse_iso(snap["known_at"]))
    page = [_entry(m, after) for m, after in entries[offset:offset + limit]]
    body = {"opening_balance": opening, "entries": page, "closing_balance": closing,
            "has_more": offset + limit < len(entries), "snapshot": snap["token"]}
    if snap["known_echo"] is not None:
        body["known_at"] = snap["known_echo"]
    return body


def get_statement(req):
    limit, offset = page_params(req.query)
    query = req.query
    if "snapshot" in query:
        if any(name in query for name in ("from", "to", "known_at")):
            raise invalid("from, to and known_at cannot accompany a snapshot")
        with store.locked():
            snap = store.state["snapshots"].get(query["snapshot"])
            if snap is None or snap["user_id"] != req.user_id:
                raise not_found("unknown snapshot")
            return 200, _render(req.user_id, snap, limit, offset)
    _, start = query_instant(query, "from")
    _, end = query_instant(query, "to")
    known_echo, known = query_instant(query, "known_at")
    with store.locked():
        end = end or store.now
        if start is not None and start > end:
            raise invalid("from must not be later than to")
        known = min(known, store.now) if known is not None else store.now   # freeze what is known now
        token = secrets.token_hex(16)
        snap = {"token": token, "user_id": req.user_id, "from_at": fmt(start) if start else None,
                "to_at": fmt(end), "known_at": fmt(known), "known_echo": known_echo}
        store.state["snapshots"][token] = snap
        return 200, _render(req.user_id, snap, limit, offset)
