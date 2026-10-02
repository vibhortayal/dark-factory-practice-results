"""Idempotent write paths (spec §7).

The order of checks is fixed here: key header, body parse, claimed-key
resolution, and only then the endpoint's own validation inside `execute`.
A key is claimed only when `execute` succeeds, so 4xx failures leave it free.
"""
import json

from .errors import ApiError, invalid
from . import operation
from .store import store


def canonical(value):
    """A string equal for equal JSON values (1, 1.0 and 1e3 are one number).

    Iterative, so any nesting depth the JSON parser accepts is handled.
    """
    out = []
    stack = [(False, value)]  # (is_literal, item)
    while stack:
        literal, item = stack.pop()
        if literal:
            out.append(item)
        elif isinstance(item, dict):
            out.append("{")
            stack.append((True, "}"))
            for i, key in reversed(list(enumerate(sorted(item)))):
                stack.append((False, item[key]))
                stack.append((True, ("," if i else "") + json.dumps(key) + ":"))
        elif isinstance(item, list):
            out.append("[")
            stack.append((True, "]"))
            for i in range(len(item) - 1, -1, -1):
                stack.append((False, item[i]))
                if i:
                    stack.append((True, ","))
        else:
            if isinstance(item, float) and item == item and abs(item) != float("inf") and item.is_integer():
                item = int(item)
            out.append(json.dumps(item))
    return "".join(out)


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
        operation.begin()
        claimed = store.idem.get((req.user_id, req.path, key))
        if claimed is not None:
            if claimed["fingerprint"] != fingerprint:
                raise ApiError(409, "idempotency_key_reuse", "key was used with a different body")
            return 200, claimed["response"]
        response = execute(body)
        store.record_idempotent(req.user_id, req.path, key, fingerprint, response)
        return 201, response
