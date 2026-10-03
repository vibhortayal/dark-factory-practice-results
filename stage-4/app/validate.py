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


def table_selection(body, required):
    """The table set named by `table_id` (one table) or `table_ids` (a list), as a list.

    Both keys together -> 422. Wrong JSON types -> 400. Empty list or duplicates -> 422.
    Absent: 422 when `required`, else None (the caller keeps the current tables).
    """
    one, many = "table_id" in body, "table_ids" in body
    if one and many:
        raise invalid("send table_id or table_ids, not both")
    if one:
        if not isinstance(body["table_id"], str):
            raise malformed("table_id must be a string")
        return [body["table_id"]]
    if many:
        ids = body["table_ids"]
        if not isinstance(ids, list) or not all(isinstance(t, str) for t in ids):
            raise malformed("table_ids must be an array of strings")
        if not ids:
            raise invalid("table_ids must not be empty")
        if len(set(ids)) != len(ids):
            raise invalid("duplicate table id")
        return list(ids)
    if required:
        raise invalid("table_id or table_ids is required")
    return None
