"""JSON parsing (exact numbers), canonical form for idempotency, and encoding."""
import json
from decimal import Decimal

from .errors import malformed


def _reject_constant(name):
    raise ValueError("non-finite number " + name)


def parse_json(raw: bytes):
    """Parse a request body. Floats stay exact as Decimal; NaN/Infinity are rejected."""
    try:
        return json.loads(raw.decode("utf-8"), parse_float=Decimal,
                          parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise malformed("body is not valid JSON") from None


def parse_object(raw: bytes):
    value = parse_json(raw)
    if not isinstance(value, dict):
        raise malformed("body must be a JSON object")
    return value


def _number(d: Decimal) -> str:
    sign, digits, exp = d.as_tuple()
    digits = list(digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exp += 1
    if digits == [0]:
        return "0"
    return ("-" if sign else "") + "".join(map(str, digits)) + "e" + str(exp)


def canonical(value) -> str:
    """A string equal for two bodies iff they are the same JSON value."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, Decimal)):
        return _number(Decimal(value))
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ",".join(canonical(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + ":" + canonical(value[k])
                              for k in sorted(value)) + "}"
    raise TypeError("unsupported JSON value")


def dumps(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii")
