"""POST /correction-batches: an operator corrects several payments atomically."""
from .. import clock, history, holds
from ..errors import conflict, invalid, not_found
from ..store import new_id
from .corrections import _fields, _public, check_refund_floor

MAX_ITEMS = 32


def _settlement_members(state, settlement_id):
    for record in state.settlements:
        if record["settlement_id"] == settlement_id:
            return record["payment_ids"]
    return []


def _plan_item(state, item, now_ts):
    """Item errors, in the spec's order: validation, unknown payment, immutable, stale, refund floor."""
    payment_id = item.get("payment_id")
    if not isinstance(payment_id, str) or not payment_id:
        raise invalid("payment_id is required")
    expected, amount, effective, reason = _fields(item, now_ts)
    rec = state.payment_index.get(payment_id)
    if rec is None:
        raise not_found("no such payment")
    data = rec["data"]
    if data["authorization_id"] is not None or data.get("refund_of") is not None:
        raise invalid("captures and refunds cannot be corrected", "linked_payment_immutable")
    current = rec["revs"][-1]
    if expected != current["revision"]:
        raise conflict("stale_revision", "the payment has a newer revision")
    check_refund_floor(state, payment_id, amount)
    return rec, amount, effective, reason


def _check_settlements(state, plan):
    included = {}
    for rec, _, effective, _ in plan:
        settlement_id = rec["data"]["settlement_id"]
        if settlement_id is not None:
            included.setdefault(settlement_id, []).append((rec["data"]["payment_id"], effective.ts))
    for settlement_id, members in included.items():
        if set(_settlement_members(state, settlement_id)) - {pid for pid, _ in members}:
            raise invalid("every member of a settlement must be corrected together", "incomplete_settlement")
    for members in included.values():
        if len({ts for _, ts in members}) > 1:
            raise invalid("members of one settlement must share one effective instant")


def create(ctx):
    state = ctx.state
    items = ctx.body.get("corrections")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS \
            or not all(isinstance(item, dict) for item in items):
        raise invalid("corrections must be a list of 1 to %d objects" % MAX_ITEMS)
    ids = [item["payment_id"] for item in items if isinstance(item.get("payment_id"), str)]
    if len(set(ids)) != len(ids):
        raise invalid("payment_ids must be distinct")
    now = clock.now()
    plan = [_plan_item(state, item, now.ts) for item in items]
    _check_settlements(state, plan)

    net = {}
    for rec, amount, _, _ in plan:
        diff = amount - rec["revs"][-1]["amount"]
        net[rec["data"]["from_user_id"]] = net.get(rec["data"]["from_user_id"], 0) - diff
        net[rec["data"]["to_user_id"]] = net.get(rec["data"]["to_user_id"], 0) + diff
    if any(delta < 0 and holds.available(state, state.users[uid]) + delta < 0
           for uid, delta in net.items()):
        raise conflict("insufficient_funds", "the combined change is not affordable")

    recorded = clock.now()
    batch_id = new_id("cb_")
    added = []
    for rec, amount, effective, reason in plan:
        revision = {"revision": rec["revs"][-1]["revision"] + 1, "amount": amount,
                    "effective_at": effective.text, "effective_ts": effective.ts,
                    "recorded_at": recorded.text, "recorded_ts": recorded.ts, "reason": reason,
                    "correction_batch_id": batch_id}
        rec["revs"].append(revision)
        added.append((rec, revision))
    if any(history.overdrawn(state, uid, recorded.ts) for uid in net):
        for rec, _ in added:
            rec["revs"].pop()
        raise conflict("historical_overdraft", "the corrections would overdraw a wallet in the past")
    for uid, delta in net.items():
        state.users[uid]["balance"] += delta
    return 201, {"correction_batch_id": batch_id, "recorded_at": recorded.text,
                 "revisions": [_public(rec["data"]["payment_id"], revision) for rec, revision in added]}
