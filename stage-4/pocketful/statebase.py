"""Small checks shared by fixture building and state validation."""
from .errors import invalid
from .validation import integral

MAX_BALANCE = 2 ** 53
MAX_ID = 64


def need(condition, message="invalid state"):
    if not condition:
        raise invalid(message)


def is_id(value):
    return isinstance(value, str) and 1 <= len(value) <= MAX_ID


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def known(table, key):
    """table[key] for a string key, else None (JSON values may be unhashable)."""
    return table.get(key) if isinstance(key, str) else None


def count(value, what, minimum=0, maximum=None):
    number = integral(value)
    need(number is not None and number >= minimum and (maximum is None or number <= maximum),
         f"{what} must be an integer")
    return number


def shallow(value, limit=32):
    """True when the JSON value nests at most `limit` levels (checked iteratively)."""
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, (dict, list)):
            if depth > limit:
                return False
            children = item.values() if isinstance(item, dict) else item
            stack.extend((child, depth + 1) for child in children)
    return True


def unique_ids(items, key, seen):
    for item in items:
        need(isinstance(item, dict) and is_id(item.get(key)), f"{key} must be an id")
        need(item[key] not in seen, f"duplicate id {item[key]}")
        seen.add(item[key])
