"""POST /settlements: operator-only atomic net settlement."""
from . import clock, idempotency, ledger
from .errors import conflict, forbidden, invalid
from .handlers_payments import parse_transfer
from .request import authenticate
from .store import LOCK, current
from .views import payment_view

MAX_TRANSFERS = 32


def create_settlement(req):
    with LOCK:
        store = current()
        user = authenticate(req, store)
        if user["id"] not in store.operators:
            raise forbidden("settlement operator permission required")

        def effect(body):
            transfers = body.get("transfers")
            if (not isinstance(transfers, list) or not 1 <= len(transfers) <= MAX_TRANSFERS
                    or not all(isinstance(t, dict) for t in transfers)):
                raise invalid("transfers must be 1 to 32 objects")
            parsed = [parse_transfer(store, t, "from_handle", "to_handle") for t in transfers]
            net = {}
            for sender, receiver, amount, _, _ in parsed:
                net[sender["id"]] = net.get(sender["id"], 0) - amount
                net[receiver["id"]] = net.get(receiver["id"], 0) + amount
            if any(store.balances[uid] + delta < 0 for uid, delta in net.items()):
                raise conflict("insufficient_funds", "settlement is not affordable")
            committed_at = clock.now()
            settlement_id = store.new_id("st_", store.settlements)
            payments = [ledger.record_payment(store, s, r, a, n, v, committed_at,
                                              settlement_id=settlement_id)
                        for s, r, a, n, v in parsed]
            store.settlements[settlement_id] = {
                "settlement_id": settlement_id, "committed_at": committed_at,
                "payment_ids": [p["payment_id"] for p in payments]}
            return {"settlement_id": settlement_id, "committed_at": committed_at,
                    "payments": [payment_view(p) for p in payments]}

        return idempotency.run(req, store, user, effect)
