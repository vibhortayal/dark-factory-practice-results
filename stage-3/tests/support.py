"""Test helpers: run the real server on a free port and talk to it over HTTP."""
import http.client
import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.server import Handler, Server  # noqa: E402

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def restaurant(rid="r1", tz="Europe/Berlin", opens="18:00", closes="23:00", tables=None, **kw):
    base = {"id": rid, "name": "R", "timezone": tz, "slot_minutes": 30,
            "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
            "opening_hours": [{"weekday": d, "opens": opens, "closes": closes} for d in DAYS],
            "tables": tables or [{"id": "t1", "label": "1", "capacity": 2},
                                 {"id": "t2", "label": "2", "capacity": 4},
                                 {"id": "t3", "label": "3", "capacity": 6}]}
    base.update(kw)
    return base


USERS = [{"id": "u_a", "email": "a@example.com", "password": "password1", "display_name": "A"},
         {"id": "u_b", "email": "b@example.com", "password": "password1", "display_name": "B"}]


class ServiceCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, method, path, body=None, token=None, key=None, raw=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = dict(headers or {})
        if token:
            hdrs["Authorization"] = f"Bearer {token}"
        if key is not None:
            hdrs["Idempotency-Key"] = key
        data = raw if raw is not None else (None if body is None else json.dumps(body))
        if data is not None:
            hdrs["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        text = resp.read().decode()
        conn.close()
        ctype = resp.getheader("Content-Type") or ""
        return resp.status, (json.loads(text) if text and "json" in ctype else None), resp

    def reset(self, restaurants=None, reservations=None, users=None):
        status, _, _ = self.call("POST", "/_test/reset", {
            "users": USERS if users is None else users,
            "restaurants": restaurants if restaurants is not None else [restaurant()],
            "reservations": reservations or []})
        self.assertEqual(status, 204)

    def login(self, email="a@example.com"):
        status, body, _ = self.call("POST", "/auth/login", {"email": email, "password": "password1"})
        self.assertEqual(status, 200)
        return body["token"]

    def book(self, token, key, at="2030-05-01T19:00", table="t2", party=2, rid="r1"):
        return self.call("POST", "/reservations", {
            "restaurant_id": rid, "table_id": table, "starts_at_local": at,
            "party_size": party}, token=token, key=key)

    def assertErr(self, result, status, code):
        self.assertEqual((result[0], (result[1] or {}).get("error", {}).get("code")),
                         (status, code), result[1])
