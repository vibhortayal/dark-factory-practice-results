"""POST /settlements: operator-only atomic batches of transfers."""
from collections import defaultdict

from .. import holds, ledger
from ..errors import ApiError, forbidden, insufficient_funds, invalid, not_found
from ..idempotency import run_idempotent
from ..store import store
from ..validation import parse_amount, parse_note, parse_visibility, string_field

MAX_TRANSFERS = 32


def create_settlement(req):
    with store.locked():
        if req.user_id not in store.state["operators"]:
            raise forbidden("settlements require an operator")
    return run_idempotent(req, _execute)


def _entry(entry):
    """Validate one transfer; returns (sender, receiver, amount, note, visibility)."""
    if not isinstance(entry, dict):
        raise invalid("each transfer must be an object")
    from_handle = string_field(entry, "from_handle")
    to_handle = string_field(entry, "to_handle")
    amount = parse_amount(entry)
    note = parse_note(entry)
    visibility = parse_visibility(entry)
    if from_handle == to_handle:
        raise ApiError(422, "self_payment", "a transfer needs two different wallets")
    sender, receiver = store.by_handle.get(from_handle), store.by_handle.get(to_handle)
    if sender is None or receiver is None:
        raise not_found("no user has that handle")
    return sender, receiver, amount, note, visibility


def _execute(body):
    transfers = body.get("transfers")
    if not isinstance(transfers, list) or not 1 <= len(transfers) <= MAX_TRANSFERS:
        raise invalid(f"transfers must be an array of 1 to {MAX_TRANSFERS} objects")
    parsed = [_entry(entry) for entry in transfers]  # first bad entry decides
    net = defaultdict(int)
    for sender, receiver, amount, _, _ in parsed:
        net[sender["id"]] -= amount
        net[receiver["id"]] += amount
    if any(holds.available_of(store.user(uid)) + delta < 0 for uid, delta in net.items()):
        raise insufficient_funds()
    settlement_id = store.new_id("st")
    committed_at = store.stamp()
    payments = [ledger.make_payment(s, r, amount, note, vis,
                                    settlement_id=settlement_id, created_at=committed_at)
                for s, r, amount, note, vis in parsed]
    store.state["settlements"].append({"settlement_id": settlement_id,
                                       "payment_ids": [p["payment_id"] for p in payments],
                                       "committed_at": committed_at})
    return {"settlement_id": settlement_id, "committed_at": committed_at, "payments": payments}
