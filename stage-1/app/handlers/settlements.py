"""POST /settlements: all-or-nothing net settlement by an operator."""
from .. import clock, ledger
from ..errors import conflict, invalid, not_found
from ..store import new_id
from ..validation import parse_amount, parse_note, parse_visibility

MAX_TRANSFERS = 32


def _entry(state, item):
    """Validate one transfer; returns (sender, receiver, amount, note, visibility)."""
    if not isinstance(item, dict):
        raise invalid("each transfer must be an object")
    for field in ("from_handle", "to_handle"):
        if not isinstance(item.get(field), str):
            raise invalid("%s must be a string" % field)
    amount = parse_amount(item.get("amount"))
    note = parse_note(item)
    visibility = parse_visibility(item)
    if item["from_handle"] == item["to_handle"]:
        raise invalid("cannot transfer to the same wallet", "self_payment")
    sender = state.user_by_handle(item["from_handle"])
    receiver = state.user_by_handle(item["to_handle"])
    if sender is None or receiver is None:
        raise not_found("unknown handle in transfer")
    return sender, receiver, amount, note, visibility


def create(ctx):
    state = ctx.state
    transfers = ctx.body.get("transfers")
    if not isinstance(transfers, list) or not 1 <= len(transfers) <= MAX_TRANSFERS:
        raise invalid("transfers must be a list of 1 to %d objects" % MAX_TRANSFERS)
    entries = [_entry(state, item) for item in transfers]

    net = {}
    for sender, receiver, amount, _, _ in entries:
        net[sender["id"]] = net.get(sender["id"], 0) - amount
        net[receiver["id"]] = net.get(receiver["id"], 0) + amount
    if any(state.users[uid]["balance"] + delta < 0 for uid, delta in net.items()):
        raise conflict("insufficient_funds", "settlement is not affordable")

    stamp = clock.now()
    settlement_id = new_id("st_")
    payments = [ledger.transfer(state, s, r, amount, note, vis, stamp,
                                settlement_id=settlement_id)
                for s, r, amount, note, vis in entries]
    state.settlements.append({"settlement_id": settlement_id, "committed_at": stamp.text,
                              "payment_ids": [p["payment_id"] for p in payments]})
    return 201, {"settlement_id": settlement_id, "committed_at": stamp.text,
                 "payments": payments}
