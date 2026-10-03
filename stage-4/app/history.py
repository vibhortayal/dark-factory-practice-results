"""Temporal ledger views: balances, holds and statements as of an instant, as known at an instant.

Terms: T = the effective-time cut-off (`as_of`), K = the knowledge cut-off (`known_at`). A payment's
*selected revision* under K is its latest revision recorded at or before K; none means the payment
contributes nothing. Selected revisions take effect at their own effective time. All instants are
integer microseconds.
"""
INF = 1 << 62


def selected(rec: dict, k_ts: int):
    for rev in reversed(rec["revs"]):
        if rev["recorded_ts"] <= k_ts:
            return rev
    return None


def signed(rec: dict, uid: str, amount: int) -> int:
    data = rec["data"]
    if data["from_user_id"] == data["to_user_id"]:
        return 0
    return -amount if data["from_user_id"] == uid else amount


def total_at(state, uid: str, t_ts: int, k_ts: int) -> int:
    total = state.opening[uid]
    for rec in state.pay_by_user.get(uid, ()):
        rev = selected(rec, k_ts)
        if rev is not None and rev["effective_ts"] <= t_ts:
            total += signed(rec, uid, rev["amount"])
    return total


def hold_at(rec: dict, t_ts: int, k_ts: int) -> int:
    """The amount an authorization reserved at T, using only events known at K.

    Creation and captures are known at their own time; a void or final capture is known from its
    time; the expiry deadline is known once creation is. An unknown closing event leaves the hold
    in place until its deadline."""
    hold = rec["hold"]
    start = hold["start_ts"]
    if start is None or t_ts < start or k_ts < start:
        return 0
    end = rec["expires_ts"]
    if hold["end_ts"] is not None and hold["end_ts"] <= k_ts:
        end = min(end, hold["end_ts"])
    if t_ts >= end:
        return 0
    taken = sum(amount for ts, amount in hold["captures"] if ts <= t_ts and ts <= k_ts)
    return rec["data"]["amount"] - taken


def held_at(state, uid: str, t_ts: int, k_ts: int) -> int:
    return sum(hold_at(rec, t_ts, k_ts) for rec in state.authorizations.values()
               if rec["data"]["from_user_id"] == uid)


def money_view(state, uid: str, t_ts: int, k_ts: int) -> dict:
    total = total_at(state, uid, t_ts, k_ts)
    held = held_at(state, uid, t_ts, k_ts)
    return {"balance": total, "total": total, "available": total - held, "held": held}


def statement_rows(state, uid: str, k_ts: int):
    """(effective_ts, payment id, record, selected revision, delta) in statement order."""
    rows = []
    for rec in state.pay_by_user.get(uid, ()):
        rev = selected(rec, k_ts)
        if rev is not None:
            rows.append((rev["effective_ts"], rec["data"]["payment_id"], rec, rev,
                         signed(rec, uid, rev["amount"])))
    rows.sort(key=lambda row: (row[0], row[1]))
    return rows


def build_statement(state, uid: str, from_ts, to_ts: int, k_ts: int) -> dict:
    """The full window [from, to): opening, closing and every entry with its balance after it."""
    balance = state.opening[uid]
    entries = []
    opening = balance if from_ts is None else None
    for eff_ts, pid, rec, rev, delta in statement_rows(state, uid, k_ts):
        if from_ts is not None and eff_ts < from_ts:
            balance += delta
            continue
        if opening is None:
            opening = balance
        if eff_ts >= to_ts:
            break
        balance += delta
        entries.append({"payment_id": pid, "amount": rev["amount"], "delta": delta,
                        "balance_after": balance, "revision": rev["revision"],
                        "effective_at": rev["effective_at"], "recorded_at": rev["recorded_at"]})
    if opening is None:
        opening = balance
    return {"opening_balance": opening, "entries": entries, "closing_balance": balance}


def overdrawn(state, uid: str, now_ts: int) -> bool:
    """True if, under the latest revisions, total or available is negative at any past boundary.

    Events at one instant are combined before the check."""
    events = []
    for rec in state.pay_by_user.get(uid, ()):
        rev = rec["revs"][-1]
        events.append((rev["effective_ts"], signed(rec, uid, rev["amount"]), 0))
    for rec in state.authorizations.values():
        hold = rec["hold"]
        if rec["data"]["from_user_id"] != uid or hold["start_ts"] is None:
            continue
        end = min(rec["expires_ts"], hold["end_ts"] if hold["end_ts"] is not None else INF)
        if end <= hold["start_ts"]:
            continue    # closed before it began (a seeded hold already past its deadline)
        remaining = rec["data"]["amount"]
        events.append((hold["start_ts"], 0, remaining))
        for ts, amount in sorted(hold["captures"]):
            if ts <= end:
                events.append((ts, 0, -amount))
                remaining -= amount
        if remaining > 0:
            events.append((end, 0, -remaining))
    events.sort(key=lambda e: e[0])
    total, held, i = state.opening[uid], 0, 0
    while i < len(events) and events[i][0] <= now_ts:
        ts = events[i][0]
        while i < len(events) and events[i][0] == ts:
            total += events[i][1]
            held += events[i][2]
            i += 1
        if total < 0 or total - held < 0:
            return True
    return False
