"""Shared request-field validation (types, amount, note, visibility, handles, query ints)."""
import re

from .errors import invalid, malformed
from .jsonutil import as_integer

MAX_AMOUNT = 1_000_000_000
MAX_NOTE = 200
_DIGITS = re.compile(r"[0-9]+")


def handles(body, names):
    """Fetch required string fields: wrong type -> 400 first, then missing -> 422."""
    for name in names:
        if name in body and not isinstance(body[name], str):
            raise malformed(f"{name} must be a string")
    for name in names:
        if name not in body:
            raise invalid(f"{name} is required")
    return [body[n] for n in names]


def amount(body, minimum=1):
    if "amount" not in body:
        raise invalid("amount is required")
    value = as_integer(body["amount"])
    if value is None or value < minimum or value > MAX_AMOUNT:
        raise invalid(f"amount must be an integer from {minimum} to {MAX_AMOUNT}")
    return value


def note(body):
    if "note" not in body:
        return ""
    value = body["note"]
    if not isinstance(value, str) or len(value) > MAX_NOTE:
        raise invalid("note must be a string of at most 200 characters")
    return value


def visibility(body):
    if "visibility" not in body:
        return "public"
    value = body["visibility"]
    if value not in ("public", "private") or not isinstance(value, str):
        raise invalid("visibility must be public or private")
    return value


def query_int(query, name, default, minimum, maximum=None):
    if name not in query:
        return default
    text = query[name]
    if not _DIGITS.fullmatch(text) or not text.isascii():
        raise invalid(f"{name} must be plain decimal digits")
    value = int(text) if len(text) <= 18 else 10 ** 18
    if value < minimum or (maximum is not None and value > maximum):
        raise invalid(f"{name} out of range")
    return value


def page_params(query):
    return query_int(query, "limit", 50, 1, 200), query_int(query, "offset", 0, 0)


def paginate(items, limit, offset):
    """Slice a newest-first list and report whether items exist beyond the page."""
    return items[offset:offset + limit], offset + limit < len(items)
