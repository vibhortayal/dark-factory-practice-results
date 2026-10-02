"""In-memory state. One global lock makes every mutation atomic.

State layout (plain JSON-able data, so export is a deep copy):
  users:        {user_id: {id, email, display_name, password_hash}}
  tokens:       {sha256(token): user_id}
  restaurants:  {id: fixture-shaped restaurant}
  reservations: {reservation_id: record}  (record has epoch start_ts/end_ts)
  idempotency:  {json([user_id, method, path, key]): {body, status, response}}
  counters:     {user, reservation}
"""
import threading


def empty_state():
    return {"users": {}, "tokens": {}, "restaurants": {}, "reservations": {},
            "idempotency": {}, "counters": {"user": 0, "reservation": 0}}


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.data = empty_state()
        self.by_ref = {}
        self.by_email = {}

    def replace(self, data):
        """Swap in a fully built state and rebuild derived indexes."""
        with self.lock:
            self.data = data
            self.by_ref = {r["reference"]: r for r in data["reservations"].values()}
            self.by_email = {u["email"].lower(): u for u in data["users"].values()}

    def next_id(self, kind, prefix, taken):
        counters = self.data["counters"]
        while True:
            counters[kind] += 1
            candidate = "%s%d" % (prefix, counters[kind])
            if candidate not in taken:
                return candidate
