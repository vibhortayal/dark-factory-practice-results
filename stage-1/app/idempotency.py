"""Idempotency-Key handling for the two keyed write paths (call under store.lock)."""
import copy
import json

from .errors import ApiError, conflict, invalid
from .jsonutil import canonical

MAX_KEY = 255


def read_key(headers):
    key = headers.get("Idempotency-Key")
    if key is None or key == "":
        raise ApiError("Idempotency-Key header is required", "missing_idempotency_key", 400)
    if len(key) > MAX_KEY:
        raise invalid("Idempotency-Key must be 1 to 255 characters")
    return key


def record_key(user_id, method, path, key):
    return json.dumps([user_id, method, path, key])


def lookup(store, rkey, body):
    """Return the stored response for a replay, None for a first use; 409 on a different body."""
    rec = store.data["idempotency"].get(rkey)
    if rec is None:
        return None
    if rec["body"] != canonical(body):
        raise conflict("idempotency_key_reuse", "key already used with a different body")
    return copy.deepcopy(rec["response"])


def remember(store, rkey, body, response):
    store.data["idempotency"][rkey] = {"body": canonical(body), "status": 201,
                                       "response": copy.deepcopy(response)}
