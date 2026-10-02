"""Balances and statements as a pure function of stored history.

Every payment has revisions; a *view* is (T, K): K = what was known (revisions
recorded at or before K, nothing if none yet), T = the instant looked at (a
revision counts when its effective time is at or before T). `/me?as_of`,
`/statement` and the historical-overdraft check all use `movements`, so they
cannot disagree.
"""
from collections import namedtuple

from . import holds
from .errors import ApiError
from .store import store

Movement = namedtuple("Movement", "effective pid delta revision effective_at recorded_at amount")


def movements(user_id, known=None, override=None):
    """The user's selected movements sorted by (effective instant, payment id).

    `override` maps payment id -> (amount, effective datetime, effective text): a
    candidate correction treated as the latest revision, for the overdraft check.
    """
    out = []
    revisions = store.state["revisions"]
    for pid in store.user_payments.get(user_id, ()):
        payment = store.payments_by_id[pid]
        revs, times = revisions[pid], store.revision_times[pid]
        if override and pid in override:
            amount, effective, effective_at = override[pid]
            number, recorded_at = len(revs) + 1, None
        else:
            index = None
            for i in range(len(revs) - 1, -1, -1):
                if known is None or times[i][0] <= known:
                    index = i
                    break
            if index is None:
                continue
            rev = revs[index]
            amount, effective, effective_at = rev["amount"], times[index][1], rev["effective_at"]
            number, recorded_at = rev["revision"], rev["recorded_at"]
        delta = -amount if payment["from_user_id"] == user_id else amount
        out.append(Movement(effective, pid, delta, number, effective_at, recorded_at, amount))
    out.sort(key=lambda m: (m.effective, m.pid))
    return out


def total_at(user_id, at, known=None):
    return store.opening_balance(user_id) + sum(m.delta for m in movements(user_id, known) if m.effective <= at)


def statement(user_id, start, end, known):
    """(opening, entries, closing) for the half-open window [start, end); start may be None."""
    running = store.opening_balance(user_id)
    opening = None
    entries = []
    for m in movements(user_id, known):
        if m.effective >= end:
            break
        if start is not None and m.effective < start:
            running += m.delta
            continue
        if opening is None:
            opening = running
        running += m.delta
        entries.append((m, running))
    if opening is None:
        opening = running
    return opening, entries, running


def check_no_overdraft(user_ids, override):
    """409 historical_overdraft if, under the latest revisions plus `override`, any of the
    users' total or available is negative at a past effective-time or hold-event boundary.
    All movements of one instant are applied together."""
    for uid in user_ids:
        steps = [(m.effective, m.delta, 0) for m in movements(uid, None, override)]
        for a in store.auths_by_payer.get(uid, ()):
            steps.extend((t, 0, dh) for t, dh in holds.hold_steps(a))
        steps.sort(key=lambda s: s[0])
        total, held, i = store.opening_balance(uid), 0, 0
        while i < len(steps) and steps[i][0] <= store.now:
            instant = steps[i][0]
            while i < len(steps) and steps[i][0] == instant:
                total, held, i = total + steps[i][1], held + steps[i][2], i + 1
            if total < 0 or total - held < 0:
                raise ApiError(409, "historical_overdraft", "the correction would overdraw a wallet in the past")
