"""Idempotent write paths (spec section 7).

Check order: key header (400/422) -> body parses as object (400) -> claimed key
(replay 200 / reuse 409) -> the endpoint's own validation and effects. A record
is stored only when the endpoint succeeded, so failed keys stay reusable.
"""
import copy

from .errors import ApiError, conflict, invalid
from .jsonutil import json_equal, parse_object


def read_key(req):
    key = req.header("Idempotency-Key")
    if key is None or key == "":
        raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header is required")
    try:  # http.server decodes headers as latin-1; recover the UTF-8 text
        key = key.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    if len(key) > 255:
        raise invalid("Idempotency-Key must be 1 to 255 characters")
    return key


def run(req, store, user, effect, allow_empty_body=False):
    """Run `effect(body) -> response dict` once per (user, method, path, key)."""
    key = read_key(req)
    body = parse_object(req.raw_body, allow_empty=allow_empty_body)
    slot = (user["id"], req.method, req.path, key)
    record = store.idem.get(slot)
    if record is not None:
        if json_equal(record["body"], body):
            return 200, copy.deepcopy(record["response"])
        raise conflict("idempotency_key_reuse", "key already used with a different body")
    response = effect(body)
    store.idem[slot] = {"body": copy.deepcopy(body), "status": 201,
                        "response": copy.deepcopy(response)}
    return 201, response
