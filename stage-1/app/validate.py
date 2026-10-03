"""Shared request-field validation helpers (spec §5 type/format rules)."""
import re

from .errors import invalid, malformed

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")
DIGITS_RE = re.compile(r"^[0-9]{1,18}$")
MAX_ID = 64


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def require_str(body, name):
    """Required string field: absent -> 422, present but not a string -> 400."""
    if name not in body:
        raise invalid(f"{name} is required")
    value = body[name]
    if not isinstance(value, str):
        raise malformed(f"{name} must be a string")
    return value


def optional_str(body, name):
    if name not in body:
        return None
    if not isinstance(body[name], str):
        raise malformed(f"{name} must be a string")
    return body[name]


def party_size(value):
    """party_size must be an integer >= 1; anything else is 422."""
    if not is_int(value) or value < 1:
        raise invalid("party_size must be an integer >= 1")
    return value


def query_int(params, name):
    """Required integer query parameter written as plain decimal digits."""
    raw = params.get(name)
    if raw is None or raw == "":
        raise invalid(f"{name} is required")
    if not DIGITS_RE.match(raw):
        raise invalid(f"{name} must be plain decimal digits")
    return int(raw)


def check_id_length(value, what):
    if not isinstance(value, str) or not value or len(value) > MAX_ID:
        raise invalid(f"{what} must be a non-empty string of at most {MAX_ID} characters")
    return value
