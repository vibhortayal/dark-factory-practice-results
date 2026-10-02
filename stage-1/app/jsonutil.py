"""JSON parsing and value-level canonicalisation."""
import json

from .errors import malformed


def _reject_constant(name):
    raise ValueError("non-finite number " + name)


def parse_json(raw):
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (ValueError, RecursionError):  # includes UnicodeDecodeError
        raise malformed("request body is not valid JSON") from None


def parse_object(raw):
    value = parse_json(raw)
    if not isinstance(value, dict):
        raise malformed("request body must be a JSON object")
    return value


def _norm(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def canonical(value):
    """String that is equal for equal JSON values (key order, whitespace, 1 vs 1.0)."""
    return json.dumps(_norm(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
