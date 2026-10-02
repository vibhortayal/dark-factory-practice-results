"""JSON parsing, serialising and value-level helpers (numbers, equality)."""
import json
import math

from .errors import malformed


def _reject_constant(name):
    raise ValueError(name)


def parse(raw):
    """Parse request bytes into a JSON value or raise 400 malformed_request."""
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise malformed("body is not valid JSON") from None


def parse_object(raw, allow_empty=False):
    if allow_empty and not raw.strip():
        return {}
    value = parse(raw)
    if not isinstance(value, dict):
        raise malformed("body must be a JSON object")
    return value


def dumps(obj):
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except UnicodeEncodeError:  # lone surrogates cannot be UTF-8 encoded
        return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def as_integer(value):
    """Return the exact int for an integral JSON number, else None (bools excluded)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def json_equal(a, b):
    """JSON-value equality: numbers by value, booleans distinct from numbers."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict):
        return (isinstance(b, dict) and a.keys() == b.keys()
                and all(json_equal(v, b[k]) for k, v in a.items()))
    if isinstance(a, list):
        return (isinstance(b, list) and len(a) == len(b)
                and all(json_equal(x, y) for x, y in zip(a, b)))
    return type(a) is type(b) and a == b
