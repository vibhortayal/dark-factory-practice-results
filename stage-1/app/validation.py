"""Request validation helpers and the API error type."""
import json
import math
import re
from functools import lru_cache

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
EXPAND_LIMIT = 4300  # integers up to this many digits are plain ints (CPython conversion limit)


@lru_cache(maxsize=8192)
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
    """A JSON number kept as its literal text: an integer with more than 4300 digits, or
    a number with a fraction/exponent. Comparison and validation use num_canon(text),
    never a double."""
    __slots__ = ("text",)

    def __init__(self, literal):
        self.text = literal


def to_int(value):
    """The exact integer value of a parsed JSON number, or None if it is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, BigNumber):
        canon_text = num_canon(value.text)
        return int(canon_text[1:]) if canon_text.startswith("n") else None
    return None


def _parse_int(text):
    if len(text.lstrip("-")) > EXPAND_LIMIT:
        return BigNumber(text)
    return int(text)


def _number_default(obj):
    """json.dumps hook: canonical stand-in for a literal-keeping number."""
    if isinstance(obj, BigNumber):
        c = num_canon(obj.text)
        return int(c[1:]) if c.startswith("n") else {"\x00num": c}
    raise TypeError("unserialisable")


def parse_json(raw):
    """Parse a request body; raises malformed() when it is not valid JSON.

    Integers use the C parser (fast); only a literal beyond CPython's 4300-digit limit
    triggers a second pass that keeps over-long integers as BigNumber.
    """
    try:
        text = raw.decode("utf-8")
        try:
            return json.loads(text, parse_constant=_reject_constant, parse_float=BigNumber)
        except json.JSONDecodeError:
            raise
        except ValueError:  # integer literal over the conversion limit
            return json.loads(text, parse_constant=_reject_constant, parse_float=BigNumber,
                              parse_int=_parse_int)
    except Exception:
        raise malformed("body is not valid JSON")


def parse_object(raw):
    value = parse_json(raw)
    if not isinstance(value, dict):
        raise malformed("body must be a JSON object")
    return value


def _canon_deep(value):
    """Iterative canonical text (explicit stack): used only for extreme nesting."""
    out = []
    app = out.append
    stack = []
    it, closer, first = iter((value,)), "", True
    while True:
        for item in it:
            if not first:
                app(",")
            first = False
            if type(item) is tuple:  # (key, value) pair of an object
                app(json.dumps(item[0], ensure_ascii=True))
                app(":")
                item = item[1]
            kind = type(item)
            if kind is list:
                stack.append((it, closer, first))
                app("[")
                it, closer, first = iter(item), "]", True
                break
            elif kind is dict:
                stack.append((it, closer, first))
                app("{")
                it, closer, first = iter(sorted(item.items())), "}", True
                break
            elif isinstance(item, BigNumber):
                app("n" + str(_number_default(item)))
            else:
                app(json.dumps(item, ensure_ascii=True))
        else:
            if not stack:
                return "".join(out)
            app(closer)
            it, closer, first = stack.pop()


def canon(value):
    """Canonical text of a parsed JSON value: equal JSON values give equal text.

    Booleans stay distinct from numbers; numbers are compared by exact value
    (num_canon). Normally the C encoder does the work (sorted keys, no whitespace);
    for nesting so deep that it overflows the interpreter stack the explicit-stack
    version gives a (deterministic) canonical text instead.
    """
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False, default=_number_default)
    except RecursionError:
        return _canon_deep(value)


def amount_of(value, present=True):
    """Validate an amount (§4): integral JSON number in 1..1e9."""
    if not present:
        raise invalid("amount is required")
    if isinstance(value, bool) or not isinstance(value, (int, BigNumber)):
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
