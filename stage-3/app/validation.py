"""Field-level validation shared by every endpoint (spec section 5)."""
import re
from decimal import Decimal

from .errors import invalid, malformed

MAX_AMOUNT = 1_000_000_000
MAX_NOTE = 200
HANDLE_RE = re.compile(r"^[a-z0-9_]{1,20}$")
_DIGITS = re.compile(r"[0-9]+")


def parse_amount(value, maximum: "int | None" = MAX_AMOUNT) -> int:
    """Integral numeric value in 1..maximum; strings, booleans, null are invalid."""
    if isinstance(value, bool) or value is None:
        raise invalid("amount must be an integer")
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise invalid("amount must be an integer")
    elif not isinstance(value, int):
        raise invalid("amount must be an integer")
    if value < 1 or (maximum is not None and value > maximum):
        raise invalid("amount must be a positive integer within range")
    return int(value)


def parse_note(body: dict) -> str:
    if "note" not in body:
        return ""
    note = body["note"]
    if not isinstance(note, str):
        raise invalid("note must be a string")
    if len(note) > MAX_NOTE:
        raise invalid("note must be at most %d characters" % MAX_NOTE)
    return note


def parse_visibility(body: dict) -> str:
    if "visibility" not in body:
        return "public"
    vis = body["visibility"]
    if not isinstance(vis, str) or vis not in ("public", "private"):
        raise invalid("visibility must be 'public' or 'private'")
    return vis


def require_string(body: dict, field: str) -> str:
    """Missing field is 422; a non-string value is a wrong JSON type (400)."""
    if field not in body:
        raise invalid("%s is required" % field)
    value = body[field]
    if not isinstance(value, str):
        raise malformed("%s must be a string" % field)
    return value


def parse_query_int(query: dict, name: str, default: int, low: int, high=None) -> int:
    if name not in query:
        return default
    text = query[name]
    if not _DIGITS.fullmatch(text):
        raise invalid("%s must be plain decimal digits" % name)
    n = int(text)
    if n < low or (high is not None and n > high):
        raise invalid("%s out of range" % name)
    return n


def parse_page(query: dict):
    return (parse_query_int(query, "limit", 50, 1, 200),
            parse_query_int(query, "offset", 0, 0))
