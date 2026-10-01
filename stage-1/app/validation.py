"""Request validation helpers and the API error type."""
import json
import math
import re

HANDLE_RE = re.compile(r"^[a-z0-9_]{1,20}$")
DIGITS_RE = re.compile(r"^[0-9]+$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")
MAX_AMOUNT = 1_000_000_000
MAX_NOTE = 200
STATUSES = ("pending", "paid", "declined", "cancelled")


class ApiError(Exception):
    def __init__(self, status, code, message=""):
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code


def malformed(msg="malformed request"):
    return ApiError(400, "malformed_request", msg)


def invalid(msg="validation failed"):
    return ApiError(422, "validation_failed", msg)


def _reject_constant(name):
    raise ValueError("non-finite constant " + name)


NUMBER_RE = re.compile(r"^(-?)([0-9]+)(?:\.([0-9]+))?(?:[eE]([+-]?[0-9]+))?$")
EXPAND_LIMIT = 4000  # integral values up to this many digits compare as plain integers


def num_canon(text):
    """Exact canonical form of a JSON number literal, computed symbolically.

    10, 10.0, 1e1 and 1.0e+1 give the same form; -0, 0 and 0e5 give the same
    form; any two literals with different values differ. Exponents are never
    expanded beyond EXPAND_LIMIT digits, so 1e999999999 is cheap.
    """
    m = NUMBER_RE.match(text)
    if not m:
        return "x" + text
    sign, whole, frac, exp_text = m.groups()
    frac = frac or ""
    if exp_text and len(exp_text.lstrip("+-0")) > 4000:
        return "x" + text  # exponent with thousands of digits: keep the literal
    exp = int(exp_text) if exp_text else 0
    digits = (whole + frac).lstrip("0")
    exp -= len(frac)
    if not digits:
        return "n0"
    stripped = digits.rstrip("0")
    exp += len(digits) - len(stripped)
    digits = stripped
    if exp >= 0 and len(digits) + exp <= EXPAND_LIMIT:
        return "n" + sign + digits + "0" * exp
    return "b" + sign + digits + "e" + str(exp)


class BigNumber:
    """An integer literal too long to convert to int; kept as its exact text."""
    __slots__ = ("text",)

    def __init__(self, literal):
        self.text = literal


class ExactNumber(float):
    """A JSON number with a fraction or exponent: the double for convenience,
    plus the literal text so comparisons and validation use the exact value."""

    def __new__(cls, text):
        obj = super().__new__(cls, text)
        obj.text = text if isinstance(text, str) else repr(float(text))
        return obj


def to_int(value):
    """The exact integer value of a parsed JSON number, or None if it is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, ExactNumber):
        canon_text = num_canon(value.text)
        return int(canon_text[1:]) if canon_text.startswith("n") else None
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value == int(value) else None
    return None


def _parse_int(text):
    if len(text) > EXPAND_LIMIT:
        return BigNumber(text)
    return int(text)


def parse_json(raw):
    """Parse a request body; raises malformed() when it is not valid JSON."""
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_reject_constant,
                          parse_int=_parse_int, parse_float=ExactNumber)
    except Exception:
        raise malformed("body is not valid JSON")


def parse_object(raw):
    value = parse_json(raw)
    if not isinstance(value, dict):
        raise malformed("body must be a JSON object")
    return value


def _scalar(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return "n" + str(v)
    if isinstance(v, ExactNumber):
        return num_canon(v.text)
    if isinstance(v, BigNumber):
        return num_canon(v.text)
    if isinstance(v, float):
        return num_canon(repr(v))
    return json.dumps(v, ensure_ascii=True)


def canon(value):
    """Canonical text of a parsed JSON value: equal JSON values give equal text.

    Booleans stay distinct from numbers; integral numbers are the same whether
    written 1000, 1000.0 or 1e3. Iterative, so nesting depth cannot overflow
    the interpreter stack.
    """
    out, stack = [], [(False, value)]
    while stack:
        literal, v = stack.pop()
        if literal:
            out.append(v)
        elif isinstance(v, list):
            stack.append((True, "]"))
            for i in range(len(v) - 1, -1, -1):
                stack.append((False, v[i]))
                if i:
                    stack.append((True, ","))
            out.append("[")
        elif isinstance(v, dict):
            stack.append((True, "}"))
            keys = sorted(v)
            for i in range(len(keys) - 1, -1, -1):
                stack.append((False, v[keys[i]]))
                stack.append((True, json.dumps(keys[i], ensure_ascii=True) + ":"))
                if i:
                    stack.append((True, ","))
            out.append("{")
        else:
            out.append(_scalar(v))
    return "".join(out)


def amount_of(value, present=True):
    """Validate an amount (§4): integral JSON number in 1..1e9."""
    if not present:
        raise invalid("amount is required")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("amount must be an integer")
    value = to_int(value)
    if value is None:
        raise invalid("amount must be an integer")
    if value < 1 or value > MAX_AMOUNT:
        raise invalid("amount out of range")
    return value


def note_of(body):
    note = body.get("note", "")
    if not isinstance(note, str):
        raise invalid("note must be a string")
    if len(note) > MAX_NOTE:
        raise invalid("note too long")
    return note


def visibility_of(body):
    vis = body.get("visibility", "public")
    if not isinstance(vis, str) or vis not in ("public", "private"):
        raise invalid("visibility must be public or private")
    return vis


def handle_field(body, name):
    """Required handle string: wrong type is 400, missing is 422."""
    if name not in body:
        raise invalid(name + " is required")
    value = body[name]
    if not isinstance(value, str):
        raise malformed(name + " must be a string")
    return value


def text_field(body, name):
    return handle_field(body, name)


def int_param(query, name, default, lo, hi=None):
    """Integer query parameter: plain decimal digits only."""
    if name not in query:
        return default
    raw = query[name]
    if not DIGITS_RE.fullmatch(raw) or not raw.isascii():
        raise invalid(name + " must be a plain integer")
    raw = raw.lstrip("0") or "0"
    value = int(raw) if len(raw) <= 18 else 10 ** 18
    if value < lo or (hi is not None and value > hi):
        raise invalid(name + " out of range")
    return value
