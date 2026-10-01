"""Capacity accounting: a proven upper bound of the bytes a write adds to the export.

The export serialises the state with json.dumps(..., ensure_ascii=True) (default separators), so
a client string costs its JSON-escaped length (an emoji 12 bytes, a control character 6), never its
character count. Each cost below is built from prototype objects serialised with the SAME options,
filled with the maximum plausible size for every server-controlled field (ids 20 characters,
handles 20, currency 16, timestamps, counters), plus the exact escaped length of every client-
controlled string once per place it is stored. Fields that can change later (request status up to
"cancelled", payment_id) are charged at their maximum at creation. Reset and import measure the
real serialisation instead (see Service). tests/test_api.py checks len(export) <= accounted size
after adversarial workloads.
"""
import json


def _dl(obj):
    return len(json.dumps(obj, ensure_ascii=True))


def json_len(text):
    """Serialised length of a client string (quotes and escapes included)."""
    return len(json.dumps(text, ensure_ascii=True))


_ID = "i" * 20
_H = "h" * 20
_CUR = "c" * 16
_TS = "2026-01-01T00:00:00.000+00:00"
_AMT = 10 ** 10
_BIG = 10 ** 13
_FLT = 1234567890.1234567
_SLACK = 128  # per operation: container punctuation and rounding

_PAY_REC = _dl({"id": _ID, "from": "", "to": "", "amount": _AMT, "note": "", "visibility": "private",
                "request_id": None, "settlement_id": _ID, "created_at": _TS, "ts": _FLT, "seq": _BIG})
_PAY_VIEW = _dl({"payment_id": _ID, "from_user_id": "", "from_handle": _H, "to_user_id": "", "to_handle": _H,
                 "amount": _AMT, "currency": _CUR, "note": "", "visibility": "private", "request_id": None,
                 "settlement_id": _ID, "created_at": _TS})
_REQ_REC = _dl({"id": _ID, "requester_id": "", "payer_id": "", "amount": _AMT, "note": "",
                "status": "cancelled", "payment_id": _ID, "split_id": _ID, "created_at": _TS, "ts": _FLT,
                "seq": _BIG})
_REQ_VIEW = _dl({"request_id": _ID, "requester_id": "", "requester_handle": _H, "payer_id": "",
                 "payer_handle": _H, "amount": _AMT, "currency": _CUR, "note": "", "status": "cancelled",
                 "payment_id": _ID, "created_at": _TS})
_IDEM = _dl({"user": "", "method": "POST", "path": "", "key": "", "body": "0" * 64, "response": None})
_SPLIT_REC = _dl({"id": _ID, "amount": _AMT, "note": "", "request_ids": [], "created_at": _TS})
_SPLIT_RESP = _dl({"split_id": _ID, "amount": _AMT, "currency": _CUR, "note": "", "shares": [],
                   "requests": [], "created_at": _TS})
_SETTLE_REC = _dl({"id": _ID, "committed_at": _TS, "payment_ids": []})
_SETTLE_RESP = _dl({"settlement_id": _ID, "committed_at": _TS, "payments": []})
_SHARE = _dl({"handle": _H, "amount": _AMT})
_USER = _dl({"id": _ID, "email": "", "display_name": "", "handle": _H, "balance": _AMT,
             "pw": {"alg": "scrypt+hmac-sha256", "n": 16384, "r": 8, "p": 1, "load_salt": "0" * 32,
                    "user_salt": "0" * 32, "hash": "0" * 64}})
_TOKEN = 48 + 4  # token characters (urlsafe, <= 48), quotes, ": " and ", "
_ITEM = len(_ID) + 6  # a quoted id inside a list


def token_cost(uid):
    return _TOKEN + json_len(uid) + _SLACK


def signup_cost(email, display_name):
    return _USER + json_len(email) + json_len(display_name) + _TOKEN + len(_ID) + _SLACK


def _payment(frm, to, note):
    """Record + receipt view of one payment (no idempotency entry)."""
    return _PAY_REC + _PAY_VIEW + 2 * (json_len(frm) + json_len(to)) + 2 * json_len(note) + 2


def payment_cost(frm, to, note, key, request_id=None):
    """A standalone payment or a request payment: record + view + idempotency entry."""
    cost = _payment(frm, to, note) + _IDEM + json_len(frm) + json_len(key) + len("/payments") + _SLACK
    if request_id is not None:  # request_id in the record, the view and the key's path
        cost += 3 * json_len(request_id) + len("/requests//pay")
    return cost


def _request(requester, payer, note):
    return _REQ_REC + _REQ_VIEW + 2 * (json_len(requester) + json_len(payer)) + 2 * json_len(note) + 2


def request_cost(requester, payer, note, key):
    return _request(requester, payer, note) + _IDEM + json_len(requester) + json_len(key) \
        + len("/requests") + _SLACK


def split_cost(caller, note, key, payers, participants):
    """payers: ids of the participants other than the caller; participants: number of handles."""
    cost = _SPLIT_REC + _SPLIT_RESP + _IDEM + json_len(caller) + json_len(key) + len("/splits") \
        + 2 * json_len(note) + participants * (_SHARE + 2) + _SLACK
    for payer in payers:
        cost += _request(caller, payer, note) + _ITEM
    return cost


def settlement_cost(caller, key, members):
    """members: (from_id, to_id, note) per transfer."""
    cost = _SETTLE_REC + _SETTLE_RESP + _IDEM + json_len(caller) + json_len(key) + len("/settlements") \
        + _SLACK
    for frm, to, note in members:
        cost += _payment(frm, to, note) + _ITEM
    return cost
