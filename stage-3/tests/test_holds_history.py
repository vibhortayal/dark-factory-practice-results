import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from .helpers import World, call, fixture, user
from .test_history import H, at


def plus(ts, **kw):
    return (datetime.fromisoformat(ts) + timedelta(**kw)).isoformat()


class HoldHistoryTests(World):
    def view(self, who, as_of=None, known_at=None):
        q = []
        if as_of:
            q.append("as_of=" + quote(as_of, safe=""))
        if known_at:
            q.append("known_at=" + quote(known_at, safe=""))
        return self.get(who, "/me" + ("?" + "&".join(q) if q else "")).json

    def test_lifecycle_views(self):
        a = self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 2000}).json
        aid = a["authorization_id"]
        self.assertIsNone(a["closed_at"])
        time.sleep(0.05)
        cap = self.post("bob", f"/authorizations/{aid}/capture", {"amount": 500, "final": False}).json
        time.sleep(0.05)
        v = self.post("ada", f"/authorizations/{aid}/void", None, key=None).json
        self.assertEqual(v["status"], "voided")
        self.assertRegex(v["closed_at"], r"\.\d{6}\+00:00$")
        t0, t1, t2 = a["created_at"], cap["created_at"], v["closed_at"]
        got = lambda ts, **kw: self.view("ada", ts, **kw)
        self.assertEqual(got(plus(t0, microseconds=-1))["held"], 0)
        self.assertEqual(got(t0)["held"], 2000)
        self.assertEqual((got(t0)["total"], got(t0)["available"]), (10000, 8000))
        self.assertEqual(got(plus(t1, microseconds=-1))["held"], 2000)
        w = got(t1)
        self.assertEqual((w["held"], w["total"], w["available"], w["balance"]), (1500, 9500, 8000, 9500))
        self.assertEqual(got(plus(t2, microseconds=-1))["held"], 1500)
        self.assertEqual(got(t2)["held"], 0)
        self.assertEqual((got(t2)["total"], got(t2)["available"]), (9500, 9500))
        # K before the void: the void is unknown, the hold is released only at its deadline
        early = plus(t2, microseconds=-1)
        self.assertEqual(self.view("ada", t2, early)["held"], 1500)
        self.assertEqual(self.view("ada", plus(a["expires_at"], seconds=1), early)["held"], 0)
        # K before the capture: the capture is unknown (no movement, no reduction)
        before_cap = plus(t1, microseconds=-1)
        z = self.view("ada", t2, before_cap)
        self.assertEqual((z["total"], z["held"]), (10000, 2000))
        # beyond now: closed already
        self.assertEqual(self.view("ada", plus(t2, hours=5))["held"], 0)
        # current equals the computed view of "now"
        cur = self.view("ada")
        now_view = self.view("ada", datetime.now(timezone.utc).isoformat(), None)
        self.assertEqual({k: cur[k] for k in ("total", "held", "available")}, {k: now_view[k] for k in ("total", "held", "available")})

    def test_expiry_and_open_hold_future(self):
        call("POST", "/_test/reset", fixture(authorization_ttl_seconds=1))
        self.tok = {h: call("POST", "/auth/login", {"email": f"{h}@example.com", "password": "correct horse"}).json["token"] for h in ("ada", "bob", "cy")}
        a = self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 300}).json
        self.assertEqual(self.view("ada", plus(a["expires_at"], microseconds=-1))["held"], 300)
        self.assertEqual(self.view("ada", a["expires_at"])["held"], 0)
        time.sleep(1.3)
        got = self.get("ada", "/authorizations").json["authorizations"][0]
        self.assertEqual((got["status"], got["closed_at"]), ("expired", a["expires_at"]))

    def test_final_capture_closed_at(self):
        a = self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 100}).json
        cap = self.post("bob", f"/authorizations/{a['authorization_id']}/capture", {"amount": 30}).json
        got = self.get("ada", "/authorizations").json["authorizations"][0]
        self.assertEqual(got["closed_at"], cap["created_at"])
        self.assertEqual(self.view("ada", plus(cap["created_at"], microseconds=-1))["held"], 100)
        self.assertEqual(self.view("ada", cap["created_at"])["held"], 0)

    def test_seeded_holds(self):
        exp = at(2 * H)
        call("POST", "/_test/reset", fixture(authorizations=[
            {"id": "a_open", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "status": "open", "expires_at": exp},
            {"id": "a_old", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "status": "voided", "expires_at": exp},
            {"id": "a_exp", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "status": "expired", "expires_at": at(-2 * H)}]))
        self.tok = {h: call("POST", "/auth/login", {"email": f"{h}@example.com", "password": "correct horse"}).json["token"] for h in ("ada", "bob", "cy")}
        auths = {x["authorization_id"]: x for x in self.get("ada", "/authorizations").json["authorizations"]}
        self.assertIsNone(auths["a_open"]["closed_at"])
        self.assertEqual(auths["a_exp"]["closed_at"], at(-2 * H))
        self.assertRegex(auths["a_old"]["closed_at"], r"^\d{4}-")
        created = auths["a_open"]["created_at"]
        self.assertEqual(self.view("ada", plus(created, microseconds=-1))["held"], 0)
        self.assertEqual(self.view("ada", created)["held"], 2000)
        self.assertEqual(self.view("ada")["held"], 2000)
        self.assertEqual(self.view("ada", at(10 * H))["held"], 0)    # open hold expires at its deadline
        self.assertEqual(self.view("ada", at(1 * H, 0))["held"], 2000)
        # supplied created_at
        call("POST", "/_test/reset", fixture(authorizations=[
            {"id": "a1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1000, "status": "open", "expires_at": exp, "created_at": at(-1 * H)}]))
        self.tok["ada"] = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}).json["token"]
        self.assertEqual(self.view("ada", at(-30 * timedelta(minutes=1)))["held"], 1000)
        self.assertEqual(self.view("ada", at(-2 * H))["held"], 0)

    def test_correction_blocked_by_hold(self):
        # ada's history: opened 1000, paid bob 300 at -2h.  A hold of 700 now leaves available 0 now.
        call("POST", "/_test/reset", fixture(users=[user("u_ada", "ada", 700), user("u_bob", "bob", 500), user("u_cy", "cy", 0)],
                                             payments=[{"id": "p1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 300, "created_at": at(-2 * H)}]))
        self.tok = {h: call("POST", "/auth/login", {"email": f"{h}@example.com", "password": "correct horse"}).json["token"] for h in ("ada", "bob", "cy")}
        self.assertEqual(self.post("ada", "/authorizations", {"to_handle": "cy", "amount": 700}).status, 201)
        # a decrease debits bob (affordable) but moves 100 back to ada: fine
        self.assertEqual(self.post("ada", "/payments/p1/corrections", {"expected_revision": 1, "amount": 200, "effective_at": at(-2 * H), "reason": "r"}).status, 201)
        # an increase needs ada's available (0 now): insufficient_funds takes precedence
        r = self.post("ada", "/payments/p1/corrections", {"expected_revision": 2, "amount": 350, "effective_at": at(-2 * H), "reason": "r"})
        self.assertErr(r, 409, "insufficient_funds")
