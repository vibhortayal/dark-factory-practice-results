"""POST /correction-batches: an operator corrects several payments in one atomic step.

Precedence (first failure wins): item shape; per item in input order: validation,
404, linked_payment_immutable, stale_revision, refund_exceeds_payment; settlement
completeness; identical effective instants inside a settlement; resulting current
available funds; historical total/available at every boundary.
"""
from collections import defaultdict

from .. import history, holds
from ..errors import ApiError, forbidden, insufficient_funds, invalid, not_found
from ..idempotency import run_idempotent
from ..store import store
from .corrections import check_target, new_revision, parse_fields

MAX_ITEMS = 32


def create_batch(req):
    with store.lock:   # a permission check only: the operation begins in run_idempotent
        if req.user_id not in store.state["operators"]:
            raise forbidden("correction batches require an operator")
    return run_idempotent(req, _execute)


def _shape(body):
    items = body.get("corrections")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise invalid(f"corrections must be an array of 1 to {MAX_ITEMS} objects")
    if not all(isinstance(item, dict) for item in items):
        raise invalid("each correction must be an object")
    ids = [item.get("payment_id") for item in items]
    if not all(isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
        raise invalid("each correction needs a distinct payment_id")
    return items


def _item(item):
    """Validate one item; returns its proposal."""
    expected, amount, effective, effective_text, reason = parse_fields(item)
    payment = store.payments_by_id.get(item["payment_id"])
    if payment is None:
        raise not_found("no such payment")
    revisions = check_target(payment, expected, amount, allow_settlement=True)
    return {"payment": payment, "revisions": revisions, "amount": amount, "effective": effective,
            "effective_text": effective_text, "reason": reason}


def _check_settlements(proposals):
    included = {p["payment"]["payment_id"] for p in proposals}
    groups = {}
    for p in proposals:
        sid = p["payment"]["settlement_id"]
        if sid:
            groups.setdefault(sid, []).append(p)
    members = {s["settlement_id"]: s["payment_ids"] for s in store.state["settlements"]}
    for sid in groups:
        if not set(members.get(sid, ())) <= included:
            raise ApiError(422, "incomplete_settlement", "every member of a corrected settlement must be included")
    for sid, group in groups.items():
        if len({p["effective"] for p in group}) > 1:
            raise invalid("members of one settlement must share one effective instant")


def _execute(body):
    items = _shape(body)
    proposals = [_item(item) for item in items]
    _check_settlements(proposals)
    net = defaultdict(int)
    for p in proposals:
        diff = p["amount"] - p["revisions"][-1]["amount"]
        net[p["payment"]["from_user_id"]] -= diff
        net[p["payment"]["to_user_id"]] += diff
    if any(delta < 0 and holds.available_of(store.user(uid)) + delta < 0 for uid, delta in net.items()):
        raise insufficient_funds()
    override = {p["payment"]["payment_id"]: (p["amount"], p["effective"], p["effective_text"]) for p in proposals}
    history.check_no_overdraft(list(net), override)
    for uid, delta in net.items():
        store.user(uid)["balance"] += delta
    batch_id = store.new_id("cb")
    recorded_at = store.stamp()
    revisions = []
    for p in proposals:
        revision = new_revision(p["payment"]["payment_id"], p["revisions"], p["amount"],
                                p["effective_text"], p["reason"], batch_id)
        store.add_revision(revision)
        revisions.append(dict(revision))
    return {"correction_batch_id": batch_id, "recorded_at": recorded_at, "revisions": revisions}
