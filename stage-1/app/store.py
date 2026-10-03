"""In-memory service state and the global lock guarding it.

All records are plain JSON-serialisable dicts so export/import is a straight dump.
Payments and requests are stored as {"seq", "ts", "data"}; `data` is the public shape.
"""
import secrets
import threading


def new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(8)


class State:
    def __init__(self):
        self.currency = "EUR"
        self.minor_units = 2
        self.users = {}          # user id -> {id,email,display_name,handle,balance,pw_hash}
        self.handles = {}        # handle -> user id
        self.emails = {}         # lower-case email -> user id
        self.tokens = {}         # bearer token -> user id
        self.payments = []       # records, insertion order
        self.requests = {}       # request id -> record
        self.splits = []         # {"split_id", "request_ids"}
        self.settlements = []    # {"settlement_id", "committed_at", "payment_ids"}
        self.idem = {}           # claim key -> {uid,method,path,key,body,status,response}
        self.operators = set()
        self.seq = 0

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def add_user(self, user: dict):
        self.users[user["id"]] = user
        self.handles[user["handle"]] = user["id"]
        self.emails[user["email"].lower()] = user["id"]

    def user_by_handle(self, handle: str):
        uid = self.handles.get(handle)
        return self.users[uid] if uid is not None else None

    def add_payment(self, data: dict, ts: int):
        self.payments.append({"seq": self.next_seq(), "ts": ts, "data": data})

    def add_request(self, data: dict, ts: int):
        self.requests[data["request_id"]] = {"seq": self.next_seq(), "ts": ts, "data": data}


def claim_key(uid: str, method: str, path: str, key: str) -> str:
    return "\x00".join((uid, method, path, key))


class Holder:
    """Owns the current State and the lock that serialises every state access."""

    def __init__(self):
        self.lock = threading.RLock()
        self.state = State()
