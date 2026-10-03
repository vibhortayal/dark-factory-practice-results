"""GET /statement: windowed statements with balances, and stable paging through snapshots."""
import copy
import secrets

from .. import clock, history
from ..errors import invalid, not_found
from ..validation import parse_page

# Tokens last until reset. These bounds only protect memory and the 10 s export limit; an ordinary
# test run never reaches them (the oldest snapshots would be dropped beyond them).
MAX_SNAPSHOTS = 50_000
MAX_SNAPSHOT_ENTRIES = 600_000


def _instant(query, name):
    if name not in query:
        return None
    stamp = clock.parse_query(query[name])
    if stamp is None:
        raise invalid("%s must be an RFC 3339 instant with an offset" % name)
    return stamp


def _page(state, frozen, limit, offset):
    entries = []
    for pid, amount, delta, balance_after, revision, effective_at, recorded_at in \
            frozen["entries"][offset:offset + limit]:
        payment = dict(state.payment_index[pid]["data"])
        payment["amount"] = amount
        entries.append({"payment": payment, "delta": delta, "balance_after": balance_after,
                        "revision": revision, "effective_at": effective_at,
                        "recorded_at": recorded_at})
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
    # entries are stored as compact rows: [payment id, amount, delta, balance after, revision,
    # effective_at, recorded_at]
    rows = [[e["payment_id"], e["amount"], e["delta"], e["balance_after"], e["revision"],
             e["effective_at"], e["recorded_at"]] for e in built["entries"]]
    frozen = {"token": token, "uid": uid, "opening_balance": built["opening_balance"],
              "closing_balance": built["closing_balance"], "entries": rows,
              "known_at": None if known is None else known.text}
    state.snapshots[token] = frozen
    kept = sum(len(f["entries"]) for f in state.snapshots.values())
    while len(state.snapshots) > 1 and (len(state.snapshots) > MAX_SNAPSHOTS or kept > MAX_SNAPSHOT_ENTRIES):
        kept -= len(state.snapshots.pop(next(iter(state.snapshots)))["entries"])
    return 200, _page(state, frozen, limit, offset)
