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
        self.opening = {}        # user id -> balance before any payment moved
        self.payment_index = {}  # payment id -> record
        self.pay_by_user = {}    # user id -> payment records they sent or received
        self.snapshots = {}      # statement snapshot token -> frozen statement
        self.ttl = 600           # authorization lifetime in seconds
        self.authorizations = {} # authorization id -> record
        self.seq = 0

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def add_user(self, user: dict):
        self.users[user["id"]] = user
        self.handles[user["handle"]] = user["id"]
        self.emails[user["email"].lower()] = user["id"]
        self.opening[user["id"]] = user["balance"]

    def user_by_handle(self, handle: str):
        uid = self.handles.get(handle)
        return self.users[uid] if uid is not None else None

    def add_payment(self, data: dict, ts: int):
        """Record a payment with its revision 1 (effective and recorded when it moved money)."""
        revision = {"revision": 1, "amount": data["amount"], "effective_at": data["created_at"],
                    "effective_ts": ts, "recorded_at": data["created_at"], "recorded_ts": ts,
                    "reason": ""}
        self.index_payment({"seq": self.next_seq(), "ts": ts, "data": data, "revs": [revision]})

    def index_payment(self, rec: dict):
        self.payments.append(rec)
        self.payment_index[rec["data"]["payment_id"]] = rec
        for uid in {rec["data"]["from_user_id"], rec["data"]["to_user_id"]}:
            self.pay_by_user.setdefault(uid, []).append(rec)

    def add_authorization(self, data: dict, ts: int, expires_ts: int, start_ts="created"):
        """`hold` is the lifecycle used for historical views: when funds were first reserved,
        each capture (time, amount) and when the hold closed. start_ts None = never held."""
        start = ts if start_ts == "created" else start_ts
        self.authorizations[data["authorization_id"]] = {
            "seq": self.next_seq(), "ts": ts, "expires_ts": expires_ts, "data": data,
            "hold": {"start_ts": start, "captures": [], "end_ts": None}}

    def add_request(self, data: dict, ts: int):
        self.requests[data["request_id"]] = {"seq": self.next_seq(), "ts": ts, "data": data}


def claim_key(uid: str, method: str, path: str, key: str) -> str:
    return "\x00".join((uid, method, path, key))


class Holder:
    """Owns the current State and the lock that serialises every state access."""

    def __init__(self):
        self.lock = threading.RLock()
        self.state = State()
