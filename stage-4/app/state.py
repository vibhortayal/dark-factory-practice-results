"""In-memory service state and the one global lock guarding every access."""
import secrets
import string
import threading

LOCK = threading.RLock()
REF_ALPHABET = string.ascii_uppercase + string.digits


class Data:
    """Everything the service knows. Replaced wholesale by reset and import."""

    def __init__(self):
        self.users = {}          # user_id -> {id, email, display_name, password_hash}
        self.emails = {}         # lower-cased email -> user_id
        self.tokens = {}         # token -> user_id
        self.restaurants = {}    # restaurant_id -> fixture-shaped dict (insertion order)
        self.reservations = {}   # reference -> record (includes user_id)
        self.idem = {}           # (user_id, path, key) -> {body, status, response}
        self.policies = {}       # restaurant_id -> published policies, publication order
        self.rest_rev = {}       # restaurant_id -> internal revision counter (not exposed)
        self.series = {}         # series_id -> {id, user_id, interval_weeks, revision, occurrences}
        self.next_series = 1
        self.closures = {}       # restaurant_id -> applied closures [{table_id, from, to, plan_id}]
        self.plans = {}          # plan_id -> stored seating plan (preview and, once applied, receipt marker)
        self.next_plan = 1
        self.next_user = 1
        self.next_res = 1
        self._res_ids = None     # lazily built set of reservation ids in use

    # -- id generators; loop past anything already used (seeded or imported) --
    def new_user_id(self):
        while True:
            uid = f"u_{self.next_user}"
            self.next_user += 1
            if uid not in self.users:
                return uid

    def new_reservation_id(self):
        if self._res_ids is None:
            self._res_ids = {r["reservation_id"] for r in self.reservations.values()}
        while True:
            rid = f"res_{self.next_res}"
            self.next_res += 1
            if rid not in self._res_ids:
                self._res_ids.add(rid)
                return rid

    def rest_revision(self, restaurant_id):
        return self.rest_rev.get(restaurant_id, 0)

    def new_plan_id(self):
        while True:
            pid = f"plan_{self.next_plan}"
            self.next_plan += 1
            if pid not in self.plans:
                return pid

    def new_series_id(self):
        while True:
            sid = f"ser_{self.next_series}"
            self.next_series += 1
            if sid not in self.series:
                return sid

    def new_reference(self):
        while True:
            ref = "".join(secrets.choice(REF_ALPHABET) for _ in range(8))
            if ref not in self.reservations:
                return ref


class Store:
    """Holder whose `data` is swapped atomically (under LOCK) by reset/import."""

    def __init__(self):
        self.data = Data()


STORE = Store()
