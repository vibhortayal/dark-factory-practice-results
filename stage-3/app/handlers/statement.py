"""GET /statement: windowed statements with balances, and stable paging through snapshots."""
import copy
import secrets

from .. import clock, history
from ..errors import invalid, not_found
from ..validation import parse_page

MAX_SNAPSHOTS = 5000          # oldest snapshots are dropped beyond these bounds
MAX_SNAPSHOT_ENTRIES = 300_000


def _instant(query, name):
    if name not in query:
        return None
    stamp = clock.parse_query(query[name])
    if stamp is None:
        raise invalid("%s must be an RFC 3339 instant with an offset" % name)
    return stamp


def _page(state, frozen, limit, offset):
    entries = []
    for e in frozen["entries"][offset:offset + limit]:
        payment = dict(state.payment_index[e["payment_id"]]["data"])
        payment["amount"] = e["amount"]
        entries.append({"payment": payment, "delta": e["delta"], "balance_after": e["balance_after"],
                        "revision": e["revision"], "effective_at": e["effective_at"],
                        "recorded_at": e["recorded_at"]})
    body = {"opening_balance": frozen["opening_balance"], "entries": entries,
            "closing_balance": frozen["closing_balance"],
            "has_more": offset + limit < len(frozen["entries"]), "snapshot": frozen["token"]}
    if frozen["known_at"] is not None:
        body["known_at"] = frozen["known_at"]
    return body


def get_statement(ctx):
    state, uid, query = ctx.state, ctx.user["id"], ctx.query
    limit, offset = parse_page(query)
    if "snapshot" in query:
        if any(name in query for name in ("from", "to", "known_at")):
            raise invalid("only limit and offset may accompany a snapshot")
        frozen = state.snapshots.get(query["snapshot"])
        if frozen is None or frozen["uid"] != uid:
            raise not_found("unknown snapshot")
        return 200, _page(state, frozen, limit, offset)
    start, end, known = _instant(query, "from"), _instant(query, "to"), _instant(query, "known_at")
    now_ts = clock.now().ts
    to_ts = now_ts if end is None else end.ts
    if start is not None and start.ts > to_ts:
        raise invalid("from must not be after to")
    built = history.build_statement(state, uid, None if start is None else start.ts, to_ts,
                                    now_ts if known is None else known.ts)
    token = "snap_" + secrets.token_urlsafe(18)
    frozen = dict(built, token=token, uid=uid, known_at=None if known is None else known.text)
    state.snapshots[token] = frozen
    kept = sum(len(f["entries"]) for f in state.snapshots.values())
    while len(state.snapshots) > 1 and (len(state.snapshots) > MAX_SNAPSHOTS or kept > MAX_SNAPSHOT_ENTRIES):
        kept -= len(state.snapshots.pop(next(iter(state.snapshots)))["entries"])
    return 200, _page(state, frozen, limit, offset)
