"""Idempotency-Key handling for the two write paths that need it (spec §7).

Order: body parsed as a JSON object, caller authenticated (done by the router),
key presence/length, then replay lookup, and only then endpoint validation.
Records are scoped to (user, path, key); only successful (201) outcomes are kept,
so a key used by a request that failed with 4xx is a first use next time.
"""
from .errors import ApiError, invalid
from .jsonutil import canonical, clone
from .state import STORE


def run(req, produce):
    """`produce(data, body)` returns the 201 payload or raises ApiError."""
    body = req.json_object()
    key = req.headers.get("idempotency-key")
    if key is None or key == "":
        raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header is required")
    if len(key) > 255:
        raise invalid("Idempotency-Key must be 1 to 255 characters")
    data = STORE.data
    slot = (req.user_id, req.path, key)
    wanted = canonical(body)
    seen = data.idem.get(slot)
    if seen is not None:
        if seen["body"] != wanted:
            raise ApiError(409, "idempotency_key_reuse",
                           "Idempotency-Key was used with a different request body")
        return 200, clone(seen["response"])
    response = produce(data, body)
    data.idem[slot] = {"body": wanted, "status": 201, "response": clone(response)}
    return 201, response
