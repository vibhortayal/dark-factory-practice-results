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
        self.next_user = 1
        self.next_res = 1

    # -- id generators; loop past anything already used (seeded or imported) --
    def new_user_id(self):
        while True:
            uid = f"u_{self.next_user}"
            self.next_user += 1
            if uid not in self.users:
                return uid

    def new_reservation_id(self):
        used = {r["reservation_id"] for r in self.reservations.values()}
        while True:
            rid = f"res_{self.next_res}"
            self.next_res += 1
            if rid not in used:
                return rid

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
