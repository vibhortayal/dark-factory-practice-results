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
EXPAND_LIMIT = 4300  # integers up to this many digits are plain ints (CPython conversion limit)


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


def parse_plain(raw):
    """Plain C parse for our own export format (imports): ordinary floats, no hooks."""
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except json.JSONDecodeError:
        raise malformed("body is not valid JSON")
    except RecursionError:
        raise malformed("body is nested too deeply")
    except ValueError:  # includes undecodable bytes and integers beyond the conversion limit
        raise invalid("document contains an unsupported value")


def parse_object(raw):
    value = parse_json(raw)
    if not isinstance(value, dict):
        raise malformed("body must be a JSON object")
    return value


def _slow_canon(value):
    """Canonical text with an explicit stack (no recursion limit, no stand-in objects).

    Used when the body holds literal-keeping numbers (BigNumber) or is nested too deeply for
    the C encoder. Output format is exactly the compact JSON the C encoder writes
    (sorted keys, "," and ":" separators, ensure_ascii strings, plain integers), with one
    addition: a literal-keeping number that is not a small integer is written as the
    unquoted token ~<num_canon>~. See canon() for why this is injective.
    """
    out = []
    app = out.append
    dumps = json.dumps
    stack = []
    it, closer, first = iter((value,)), "", True
    while True:
        for item in it:
            if not first:
                app(",")
            first = False
            if type(item) is tuple:  # (key, value) pair of an object
                app(dumps(item[0], ensure_ascii=True))
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
            elif kind is BigNumber:
                c = num_canon(item.text)
                app(c[1:] if c.startswith("n") else "~" + c + "~")
            else:  # int, str, bool, None
                app(dumps(item, ensure_ascii=True))
        else:
            if not stack:
                return "".join(out)
            app(closer)
            it, closer, first = stack.pop()


def canon(value):
    """Canonical text of a parsed JSON value: two JSON values have equal text iff they are equal.

    Why this is injective: the text is compact JSON (sorted keys, ensure_ascii strings, plain
    integers) in which the only non-JSON syntax is the unquoted token ~...~ for a number that
    is not a plain integer (fraction, exponent beyond the integer range, or more than 4300 digits).
    Every client string is written quoted by json.dumps, so a client can never produce an
    unquoted ~ token; a client cannot forge a number stand-in with an object or a string. The text
    can therefore be parsed back uniquely to the value (with numbers identified by their exact
    value via num_canon, which maps each real number to one form: integral values up to 4300 digits
    are written as plain integers, so 1, 1.0 and 1e0 agree). Booleans are true/false (never 1/0),
    {} and [] differ, key order is normalised, and a duplicate key keeps its last value exactly as the
    parser does. The C encoder is used when no literal-keeping number is present (it raises
    TypeError on the first BigNumber); both paths write identical text for the same value, and the
    text is deterministic across processes (no secrets), so digests survive export/import.
    """
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False)
    except (TypeError, RecursionError):  # BigNumber present, or nesting too deep for the C encoder
        return _slow_canon(value)


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
