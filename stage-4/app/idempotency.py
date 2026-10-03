"""Idempotency-key handling for the five idempotent write paths (spec section 7)."""
import copy

from .errors import conflict, invalid, missing_key
from .jsonutil import canonical
from .store import claim_key

MAX_KEY = 255


def read_key(headers) -> str:
    key = headers.get("Idempotency-Key")
    if key is None or key == "":
        raise missing_key()
    if len(key) > MAX_KEY:
        raise invalid("Idempotency-Key must be 1 to %d characters" % MAX_KEY)
    return key


def run(ctx, request, key, handler):
    """Replay, reject or execute-and-record. Only 2xx outcomes are recorded."""
    state = ctx.state
    claim = claim_key(ctx.user["id"], request.method, request.path, key)
    body_text = canonical(ctx.body)
    record = state.idem.get(claim)
    if record is not None:
        if record["body"] != body_text:
            raise conflict("idempotency_key_reuse", "key already used with a different body")
        return 200, copy.deepcopy(record["response"])
    status, payload = handler(ctx)
    state.idem[claim] = {"uid": ctx.user["id"], "method": request.method,
                         "path": request.path, "key": key, "body": body_text,
                         "status": status, "response": copy.deepcopy(payload)}
    return status, payload
