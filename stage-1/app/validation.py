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


def parse_json(raw):
    """Parse a request body; raises malformed() when it is not valid JSON."""
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except Exception:
        raise malformed("body is not valid JSON")


def parse_object(raw):
    value = parse_json(raw)
    if not isinstance(value, dict):
        raise malformed("body must be a JSON object")
    return value


def canon(value):
    """Canonical form of a parsed JSON value: equal JSON values give equal text.

    Booleans stay distinct from numbers; integral numbers are the same
    whether written 1000, 1000.0 or 1e3.
    """
    def tr(v):
        if v is None:
            return None
        if isinstance(v, bool):
            return ["b", v]
        if isinstance(v, int):
            return ["n", str(v)]
        if isinstance(v, float):
            if math.isfinite(v) and v == int(v):
                return ["n", str(int(v))]
            return ["f", repr(v)]
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            return ["l", [tr(x) for x in v]]
        if isinstance(v, dict):
            return ["o", {k: tr(x) for k, x in v.items()}]
        return ["?", repr(v)]
    return json.dumps(tr(value), sort_keys=True, ensure_ascii=True)


def amount_of(value, present=True):
    """Validate an amount (§4): integral JSON number in 1..1e9."""
    if not present:
        raise invalid("amount is required")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("amount must be an integer")
    if isinstance(value, float):
        if not math.isfinite(value) or value != int(value):
            raise invalid("amount must be an integer")
        value = int(value)
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
    if len(raw) > 12:
        raise invalid(name + " out of range")
    value = int(raw)
    if value < lo or (hi is not None and value > hi):
        raise invalid(name + " out of range")
    return value
