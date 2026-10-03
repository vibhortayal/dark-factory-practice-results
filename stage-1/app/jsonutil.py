"""JSON helpers: canonical form for 'same body' comparison and copying."""
import json


def canonical(value):
    """Stable text form of a parsed JSON value; key order and whitespace do not matter."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def clone(value):
    return json.loads(json.dumps(value))
