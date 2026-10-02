"""Field and query validation shared by the handlers (spec §5, §8)."""
import math
import re

from .errors import invalid, malformed

MAX_AMOUNT = 1_000_000_000
MAX_NOTE = 200
HANDLE_RE = re.compile(r"[a-z0-9_]{1,20}")
DIGITS_RE = re.compile(r"[0-9]+")
VISIBILITIES = ("public", "private")
STATUSES = ("pending", "paid", "declined", "cancelled")
MISSING = object()


def integral(value):
    """The integer a JSON number stands for, or None (booleans are not numbers)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def parse_amount(body, minimum=1):
    value = integral(body.get("amount"))
    if value is None or value < minimum or value > MAX_AMOUNT:
        raise invalid(f"amount must be an integer from {minimum} to {MAX_AMOUNT}")
    return value


def parse_note(body):
    note = body.get("note", "")
    if not isinstance(note, str) or len(note) > MAX_NOTE:
        raise invalid(f"note must be a string of at most {MAX_NOTE} characters")
    return note


def parse_visibility(body):
    visibility = body.get("visibility", "public")
    if visibility not in VISIBILITIES or not isinstance(visibility, str):
        raise invalid("visibility must be public or private")
    return visibility


def string_field(body, name):
    """Required string: absent is 422, any other JSON type is 400."""
    value = body.get(name, MISSING)
    if value is MISSING:
        raise invalid(f"{name} is required")
    if not isinstance(value, str):
        raise malformed(f"{name} must be a string")
    return value


def handle_list_field(body, name):
    value = body.get(name, MISSING)
    if value is MISSING:
        raise invalid(f"{name} is required")
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise malformed(f"{name} must be an array of strings")
    return value


def query_int(query, name, default, minimum, maximum=None):
    raw = query.get(name)
    if raw is None:
        return default
    if not DIGITS_RE.fullmatch(raw):
        raise invalid(f"{name} must be plain decimal digits")
    value = int(raw)
    if value < minimum or (maximum is not None and value > maximum):
        raise invalid(f"{name} is out of range")
    return value


def page_params(query):
    return query_int(query, "limit", 50, 1, 200), query_int(query, "offset", 0, 0)


def query_enum(query, name, allowed):
    raw = query.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise invalid(f"{name} must be one of {', '.join(allowed)}")
    return raw
