"""Idempotent write paths (spec §7).

The order of checks is fixed here: key header, body parse, claimed-key
resolution, and only then the endpoint's own validation inside `execute`.
A key is claimed only when `execute` succeeds, so 4xx failures leave it free.
"""
import json

from .errors import ApiError, invalid
from .store import store


def canonical(value):
    """A string equal for equal JSON values (1, 1.0 and 1e3 are one number)."""
    def norm(v):
        if isinstance(v, dict):
            return {k: norm(x) for k, x in v.items()}
        if isinstance(v, list):
            return [norm(x) for x in v]
        if isinstance(v, float) and v == v and abs(v) != float("inf") and v.is_integer():
            return int(v)
        return v
    return json.dumps(norm(value), sort_keys=True, ensure_ascii=True)


def run_idempotent(req, execute, allow_empty_body=False):
    """Run `execute(body)` under the store lock; return (status, response)."""
    key = req.header("Idempotency-Key")
    if key is None or key == "":
        raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header is required")
    if len(key) > 255:
        raise invalid("Idempotency-Key must be 1 to 255 characters")
    body = req.json_body(allow_empty=allow_empty_body)
    fingerprint = canonical(body)
    with store.lock:
        claimed = store.idem.get((req.user_id, req.path, key))
        if claimed is not None:
            if claimed["fingerprint"] != fingerprint:
                raise ApiError(409, "idempotency_key_reuse", "key was used with a different body")
            return 200, claimed["response"]
        response = execute(body)
        store.record_idempotent(req.user_id, req.path, key, fingerprint, response)
        return 201, response
