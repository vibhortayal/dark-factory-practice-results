import threading
import time
from datetime import datetime, timedelta, timezone

from .helpers import World, call, fixture, user


def iso(delta):
    return (datetime.now(timezone.utc) + delta).isoformat(timespec="seconds")


class AuthBase(World):
    def authorize(self, who="ada", to="bob", amount=2000, **kw):
        return self.post(who, "/authorizations", {"to_handle": to, "amount": amount, **kw})

    def capture(self, who, aid, body=None, **kw):
        return self.post(who, f"/authorizations/{aid}/capture", body if body is not None else {}, **kw)

    def me(self, who):
        return self.get(who, "/me").json


class HoldTests(AuthBase):
    def test_me_fields_and_hold(self):
        me = self.me("ada")
        self.assertEqual((me["balance"], me["total"], me["available"], me["held"]), (10000,) * 3 + (0,))
        r = self.authorize()
        self.assertEqual(r.status, 201, r.raw)
        a = r.json
        self.assertEqual(a["status"], "open")
        self.assertEqual((a["captured_amount"], a["remaining_amount"], a["payment_id"], a["payment_ids"]), (0, 2000, None, []))
        self.assertEqual(set(a), {"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
                                  "captured_amount", "remaining_amount", "currency", "note", "visibility", "status",
                                  "expires_at", "payment_id", "payment_ids", "created_at"})
        me = self.me("ada")
        self.assertEqual((me["balance"], me["total"], me["available"], me["held"]), (10000, 10000, 8000, 2000))
        self.assertEqual(self.get("ada", "/activity").json["payments"], [])
        self.assertEqual(self.me("bob")["held"], 0)
        self.assertConserved()

    def test_held_funds_cannot_be_spent(self):
        self.authorize(who="bob", to="ada", amount=2000)  # bob: 2500 total, 500 available
        self.assertErr(self.post("bob", "/payments", {"to_handle": "cy", "amount": 501}), 409, "insufficient_funds")
        self.assertEqual(self.post("bob", "/payments", {"to_handle": "cy", "amount": 500}).status, 201)
        self.assertErr(self.authorize(who="bob", to="cy", amount=1), 409, "insufficient_funds")
        rq = self.post("cy", "/requests", {"payer_handle": "bob", "amount": 1}).json
        self.assertErr(self.post("bob", f"/requests/{rq['request_id']}/pay", {}), 409, "insufficient_funds")

    def test_settlement_net_uses_available(self):
        call("POST", "/_test/reset", fixture(settlement_operator_ids=["u_cy"]))
        tok = {h: call("POST", "/auth/login", {"email": f"{h}@example.com", "password": "correct horse"}).json["token"]
               for h in ("ada", "bob", "cy")}
        call("POST", "/authorizations", {"to_handle": "ada", "amount": 2000}, token=tok["bob"], key="k")
        t = [{"from_handle": "bob", "to_handle": "ada", "amount": 501}]
        r = call("POST", "/settlements", {"transfers": t}, token=tok["cy"], key="s1")
        self.assertErr(r, 409, "insufficient_funds")
        t[0]["amount"] = 500
        self.assertEqual(call("POST", "/settlements", {"transfers": t}, token=tok["cy"], key="s2").status, 201)

    def test_create_rejections(self):
        self.assertErr(self.authorize(amount=10001), 409, "insufficient_funds")
        self.assertEqual(self.authorize(amount=10000).status, 201)
        self.assertErr(self.authorize(amount=1), 409, "insufficient_funds")
        self.assertErr(self.authorize(who="cy", to="cy", amount=1), 422, "self_payment")
        self.assertErr(self.authorize(to="ghost", amount=1), 404, "not_found")
        self.assertErr(self.authorize(who="bob", amount=0), 422, "validation_failed")
        self.assertErr(self.authorize(who="bob", amount=1, visibility="x"), 422, "validation_failed")
        self.assertErr(self.authorize(who="bob", amount=1, note="x" * 201), 422, "validation_failed")
        self.assertErr(self.post("bob", "/authorizations", {"to_handle": "ada", "amount": 1}, key=None), 400, "missing_idempotency_key")

    def test_idempotency(self):
        a = self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 100}, key="k")
        b = self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 100}, key="k")
        self.assertEqual((a.status, b.status, a.json), (201, 200, b.json))
        self.assertEqual(self.me("ada")["held"], 100)
        self.assertErr(self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 101}, key="k"), 409, "idempotency_key_reuse")
        aid = a.json["authorization_id"]
        c = self.capture("bob", aid, {}, key="c")
        d = self.capture("bob", aid, {}, key="c")
        self.assertEqual((c.status, d.status, c.json), (201, 200, d.json))
        self.assertErr(self.capture("bob", aid, {"amount": 100}, key="c"), 409, "idempotency_key_reuse")
        self.assertErr(self.capture("bob", aid, {}, key=None), 400, "missing_idempotency_key")
        self.assertEqual(self.balance("ada"), 9900)


class CaptureTests(AuthBase):
    def test_final_capture_releases_remainder(self):
        aid = self.authorize(note="deposit", visibility="private").json["authorization_id"]
        r = self.capture("bob", aid, {"amount": 1500})
        self.assertEqual(r.status, 201, r.raw)
        p = r.json
        self.assertEqual((p["amount"], p["authorization_id"], p["request_id"], p["note"], p["visibility"],
                          p["from_handle"], p["to_handle"]), (1500, aid, None, "deposit", "private", "ada", "bob"))
        me = self.me("ada")
        self.assertEqual((me["total"], me["held"], me["available"]), (8500, 0, 8500))
        a = self.get("ada", "/authorizations").json["authorizations"][0]
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_id"], a["payment_ids"]),
                         ("captured", 1500, 0, p["payment_id"], [p["payment_id"]]))
        self.assertErr(self.capture("bob", aid, {"amount": 1}), 409, "authorization_not_open")
        self.assertEqual(len(self.get("cy", "/activity").json["payments"]), 0)  # private
        self.assertEqual(len(self.get("bob", "/activity").json["payments"]), 1)
        self.assertConserved()

    def test_empty_body_captures_all(self):
        aid = self.authorize().json["authorization_id"]
        self.assertEqual(self.post("bob", f"/authorizations/{aid}/capture", raw=b"").json["amount"], 2000)

    def test_extended_mode(self):
        aid = self.authorize().json["authorization_id"]
        r1 = self.capture("bob", aid, {"amount": 700, "final": False}).json
        a = self.get("bob", "/authorizations?direction=incoming").json["authorizations"][0]
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"]), ("open", 700, 1300))
        self.assertEqual(self.me("ada")["held"], 1300)
        r2 = self.capture("bob", aid, {"amount": 800, "final": False}).json
        self.assertErr(self.capture("bob", aid, {"amount": 501, "final": False}), 422, "capture_exceeds_authorization")
        r3 = self.capture("bob", aid, {"amount": 500, "final": False})
        self.assertEqual(r3.status, 201)
        a = self.get("bob", "/authorizations").json["authorizations"][0]
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_id"]),
                         ("captured", 2000, 0, r3.json["payment_id"]))
        self.assertEqual(a["payment_ids"], [r1["payment_id"], r2["payment_id"], r3.json["payment_id"]])
        self.assertEqual(self.me("ada")["total"], 8000)

    def test_final_capture_after_partial_releases(self):
        aid = self.authorize().json["authorization_id"]
        self.capture("bob", aid, {"amount": 700, "final": False})
        self.capture("bob", aid, {"amount": 100})
        me = self.me("ada")
        self.assertEqual((me["total"], me["held"]), (9200, 0))

    def test_rejections(self):
        aid = self.authorize().json["authorization_id"]
        self.assertErr(self.capture("ada", aid), 403, "forbidden")
        self.assertErr(self.capture("cy", aid), 403, "forbidden")
        self.assertErr(self.capture("bob", "nope"), 404, "not_found")
        self.assertErr(self.capture("cy", "nope"), 404, "not_found")
        for bad in ("0", "-1", '"5"', "true", "null", "1.5"):
            r = self.post("bob", f"/authorizations/{aid}/capture", raw=('{"amount":%s}' % bad).encode())
            self.assertErr(r, 422, "validation_failed")
        self.assertErr(self.capture("bob", aid, {"final": "yes"}), 400, "malformed_request")
        self.assertErr(self.capture("bob", aid, {"amount": 2001}), 422, "capture_exceeds_authorization")
        self.assertErr(self.capture("bob", aid, {"amount": 10 ** 12}), 422, "capture_exceeds_authorization")
        self.assertEqual(self.capture("bob", aid, {"amount": 2000}).status, 201)

    def test_concurrent_captures_never_exceed(self):
        aid = self.authorize().json["authorization_id"]
        out = []

        def go():
            out.append(self.capture("bob", aid, {"amount": 300, "final": False}).status)
        ts = [threading.Thread(target=go) for _ in range(20)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(out), [201] * 6 + [422] * 14)
        self.assertEqual(self.me("ada")["held"], 200)
        self.assertConserved()

    def test_capture_vs_void_race(self):
        for _ in range(10):
            aid = self.authorize(amount=100).json["authorization_id"]
            out = {}
            t1 = threading.Thread(target=lambda: out.update(c=self.capture("bob", aid).status))
            t2 = threading.Thread(target=lambda: out.update(v=self.post("ada", f"/authorizations/{aid}/void", None, key=None).status))
            t1.start(); t2.start(); t1.join(); t2.join()
            a = [x for x in self.get("ada", "/authorizations").json["authorizations"] if x["authorization_id"] == aid][0]
            self.assertIn(a["status"], ("captured", "voided"))
            self.assertEqual((out["c"], out["v"]), (201, 409) if a["status"] == "captured" else (409, 200))
            self.assertEqual(self.me("ada")["held"], 0)
        self.assertConserved()


class VoidListTests(AuthBase):
    def test_void(self):
        aid = self.authorize().json["authorization_id"]
        path = f"/authorizations/{aid}/void"
        self.assertErr(self.post("bob", path, None, key=None), 403, "forbidden")
        self.assertErr(self.post("cy", path, None, key=None), 403, "forbidden")
        self.assertErr(self.post("ada", "/authorizations/zz/void", None, key=None), 404, "not_found")
        r = self.post("ada", path, None, key=None)
        self.assertEqual((r.status, r.json["status"], r.json["remaining_amount"]), (200, "voided", 0))
        self.assertEqual(self.post("ada", path, None, key=None).status, 200)
        self.assertEqual(self.me("ada")["available"], 10000)
        self.assertErr(self.capture("bob", aid), 409, "authorization_not_open")

    def test_void_after_capture_conflicts_and_partial_void(self):
        a1 = self.authorize().json["authorization_id"]
        self.capture("bob", a1)
        self.assertErr(self.post("ada", f"/authorizations/{a1}/void", None, key=None), 409, "authorization_not_open")
        a2 = self.authorize().json["authorization_id"]
        p = self.capture("bob", a2, {"amount": 500, "final": False}).json
        r = self.post("ada", f"/authorizations/{a2}/void", None, key=None).json
        self.assertEqual((r["status"], r["captured_amount"], r["remaining_amount"], r["payment_ids"]), ("voided", 500, 0, [p["payment_id"]]))
        self.assertEqual(self.me("ada")["total"], 7500)

    def test_list_filters(self):
        a = self.authorize().json["authorization_id"]
        b = self.authorize(who="bob", to="ada", amount=10).json["authorization_id"]
        self.post("ada", f"/authorizations/{a}/void", None, key=None)
        ids = lambda who, q="": [x["authorization_id"] for x in self.get(who, "/authorizations" + q).json["authorizations"]]
        self.assertEqual(ids("ada"), [b, a])
        self.assertEqual(ids("ada", "?direction=outgoing"), [a])
        self.assertEqual(ids("ada", "?direction=incoming"), [b])
        self.assertEqual(ids("ada", "?status=open"), [b])
        self.assertEqual(ids("ada", "?status=voided"), [a])
        self.assertEqual(ids("cy"), [])
        for q in ("?status=nope", "?direction=x", "?limit=0", "?offset=-1"):
            self.assertErr(self.get("ada", "/authorizations" + q), 422, "validation_failed")
        page = self.get("ada", "/authorizations?limit=1").json
        self.assertEqual((len(page["authorizations"]), page["has_more"]), (1, True))


class ExpiryAndFixtureTests(World):
    def reset(self, **extra):
        self.assertEqual(call("POST", "/_test/reset", fixture(**extra)).status, 204)
        self.tok = {h: call("POST", "/auth/login", {"email": f"{h}@example.com", "password": "correct horse"}).json["token"]
                    for h in ("ada", "bob", "cy")}

    def seeded(self, **kw):
        base = {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit",
                "visibility": "public", "status": "open", "expires_at": iso(timedelta(hours=2))}
        return {**base, **kw}

    def test_seeded_holds(self):
        self.reset(authorizations=[self.seeded()])
        me = self.get("ada", "/me").json
        self.assertEqual((me["balance"], me["available"], me["held"]), (10000, 8000, 2000))
        a = self.get("bob", "/authorizations").json["authorizations"][0]
        self.assertEqual((a["authorization_id"], a["status"], a["remaining_amount"], a["payment_ids"]), ("a_1", "open", 2000, []))
        self.assertEqual(self.post("bob", "/authorizations/a_1/capture", {"amount": 1500}).status, 201)

    def test_seeded_expired_and_other_statuses(self):
        self.reset(authorizations=[self.seeded(id="a_old", expires_at=iso(-timedelta(hours=3))),
                                   self.seeded(id="a_cap", status="captured"), self.seeded(id="a_void", status="voided"),
                                   self.seeded(id="a_exp", status="expired")])
        self.assertEqual(self.get("ada", "/me").json["held"], 0)
        statuses = {a["authorization_id"]: a["status"] for a in self.get("ada", "/authorizations").json["authorizations"]}
        self.assertEqual(statuses, {"a_old": "expired", "a_cap": "captured", "a_void": "voided", "a_exp": "expired"})
        self.assertErr(self.post("bob", "/authorizations/a_old/capture", {}), 409, "authorization_expired")
        self.assertErr(self.post("bob", "/authorizations/a_exp/capture", {}), 409, "authorization_expired")
        self.assertErr(self.post("bob", "/authorizations/a_cap/capture", {}), 409, "authorization_not_open")
        self.assertErr(self.post("ada", "/authorizations/a_old/void", None, key=None), 409, "authorization_not_open")

    def test_fixture_rejections_change_nothing(self):
        self.reset()
        bad = [dict(authorizations=[self.seeded(amount=10001)]),
               dict(authorizations=[self.seeded(), self.seeded(id="a_2", amount=8001)]),
               dict(authorizations=[self.seeded(to_user_id="u_zz")]),
               dict(authorizations=[self.seeded(status="weird")]),
               dict(authorizations=[self.seeded(expires_at="soon")]),
               dict(authorizations=[self.seeded(amount=0)]),
               dict(authorizations=[self.seeded(to_user_id="u_ada")]),
               dict(authorization_ttl_seconds=0), dict(authorization_ttl_seconds="5"), dict(authorization_ttl_seconds=-1),
               dict(authorization_ttl_seconds=True)]
        for extra in bad:
            self.assertEqual(call("POST", "/_test/reset", fixture(**extra)).status, 422, extra)
        self.assertEqual(self.get("ada", "/me").json["balance"], 10000)
        self.reset(authorizations=[self.seeded(amount=10000)])  # equal to balance is fine
        self.assertEqual(self.get("ada", "/me").json["available"], 0)
        self.reset(authorizations=[self.seeded(amount=20000, expires_at=iso(-timedelta(hours=2)))])  # expired: not counted

    def test_ttl_and_clock_expiry(self):
        self.reset(authorization_ttl_seconds=2)
        a = self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 100}).json
        created, expires = (datetime.fromisoformat(a[k]) for k in ("created_at", "expires_at"))
        self.assertEqual(expires - created, timedelta(seconds=2))
        self.assertEqual(self.get("ada", "/me").json["held"], 100)
        time.sleep(max(0, (expires - datetime.now(timezone.utc)).total_seconds()) + 0.3)
        me = self.get("ada", "/me").json
        self.assertEqual((me["held"], me["available"]), (0, 10000))
        self.assertEqual(self.get("ada", "/authorizations?status=expired").json["authorizations"][0]["status"], "expired")
        self.assertEqual(self.get("ada", "/authorizations?status=open").json["authorizations"], [])
        self.assertErr(self.post("bob", f"/authorizations/{a['authorization_id']}/capture", {}), 409, "authorization_expired")

    def test_partial_then_expiry_keeps_records(self):
        self.reset(authorization_ttl_seconds=1)
        a = self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 100}).json
        p = self.post("bob", f"/authorizations/{a['authorization_id']}/capture", {"amount": 40, "final": False}).json
        time.sleep(2.2)
        got = self.get("bob", "/authorizations").json["authorizations"][0]
        self.assertEqual((got["status"], got["captured_amount"], got["remaining_amount"], got["payment_ids"]),
                         ("expired", 40, 0, [p["payment_id"]]))
        me = self.get("ada", "/me").json
        self.assertEqual((me["total"], me["held"]), (9960, 0))

    def test_export_import_roundtrip_and_stage1_upgrade(self):
        self.reset(authorization_ttl_seconds=900)
        a = self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 500}, key="ak").json
        c = self.post("bob", f"/authorizations/{a['authorization_id']}/capture", {"amount": 100, "final": False}, key="ck")
        exp = call("GET", "/_test/export")
        call("POST", "/_test/reset", fixture())
        self.assertEqual(call("POST", "/_test/import", exp.json).status, 204)
        self.assertEqual(call("GET", "/_test/export").json, exp.json)
        got = self.get("ada", "/authorizations").json["authorizations"][0]
        self.assertEqual((got["authorization_id"], got["created_at"], got["remaining_amount"]), (a["authorization_id"], a["created_at"], 400))
        again = self.post("bob", f"/authorizations/{a['authorization_id']}/capture", {"amount": 100, "final": False}, key="ck")
        self.assertEqual((again.status, again.json), (200, c.json))
        # a stage-1 style export (no stage-2 keys) imports with defaults
        old = call("GET", "/_test/export").json
        for key in ("authorizations", "authorization_ttl_seconds"):
            del old["state"][key]
        for p in old["state"]["payments"]:
            del p["authorization_id"]
        self.assertEqual(call("POST", "/_test/import", old).status, 204)
        self.assertEqual(self.get("ada", "/authorizations").json["authorizations"], [])
        self.assertEqual(self.get("ada", "/activity").json["payments"][0]["authorization_id"], None)
        self.assertEqual(self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 1}).json["amount"], 1)
        bad = call("GET", "/_test/export").json
        bad["state"]["authorizations"][0]["remaining_amount"] = 99999
        self.assertEqual(call("POST", "/_test/import", bad).status, 422)

    def test_payments_race_authorizations(self):
        self.reset()
        out = []

        def go(i):
            if i % 2:
                out.append(call("POST", "/payments", {"to_handle": "cy", "amount": 100}, token=self.tok["bob"], key=f"p{i}").status)
            else:
                out.append(call("POST", "/authorizations", {"to_handle": "cy", "amount": 100}, token=self.tok["bob"], key=f"a{i}").status)
        ts = [threading.Thread(target=go, args=(i,)) for i in range(40)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        me = self.get("bob", "/me").json
        self.assertEqual(out.count(201), 25)  # 2500 / 100
        self.assertEqual(me["available"], 0)
        self.assertGreaterEqual(me["available"], 0)
        self.assertEqual(sum(self.get(h, "/me").json["total"] for h in self.tok), 13000)


class ClockTests(World):
    FIXED = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00$"

    def test_clock_never_goes_backwards(self):
        from datetime import datetime, timedelta, timezone
        from pocketful import clock

        class Stub:
            values = iter([datetime(2026, 10, 2, 12, 0, 5, tzinfo=timezone.utc),
                           datetime(2026, 10, 2, 12, 0, 4, tzinfo=timezone.utc),
                           datetime(2026, 10, 2, 12, 0, 5, tzinfo=timezone.utc)])

            @classmethod
            def now(cls, tz=None):
                return next(cls.values)
        real, last = clock.datetime, clock._last
        clock.datetime, clock._last = Stub, None
        try:
            a, b, c = clock.tick(), clock.tick(), clock.tick()
        finally:
            clock.datetime, clock._last = real, last
        self.assertLess(a, b)
        self.assertLess(b, c)
        self.assertEqual(b - a, timedelta(microseconds=1))

    def test_fixed_width_and_exact_lifetime(self):
        import re
        for i in range(300):
            a = self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 1}).json
            self.assertRegex(a["created_at"], self.FIXED)
            self.assertRegex(a["expires_at"], self.FIXED)
            life = datetime.fromisoformat(a["expires_at"]) - datetime.fromisoformat(a["created_at"])
            self.assertEqual(life, timedelta(seconds=600))
        p = self.post("ada", "/payments", {"to_handle": "bob", "amount": 1}).json
        self.assertRegex(p["created_at"], self.FIXED)

    def test_timestamps_monotonic_across_writes(self):
        stamps = []
        for i in range(50):
            stamps.append(self.post("ada", "/payments", {"to_handle": "bob", "amount": 1}).json["created_at"])
        self.assertEqual(stamps, sorted(stamps))
        self.assertEqual(len(set(stamps)), 50)

    def test_ttl_one_open_then_expired_and_capture_not_before_authorization(self):
        call("POST", "/_test/reset", fixture(authorization_ttl_seconds=1))
        self.tok = {h: call("POST", "/auth/login", {"email": f"{h}@example.com", "password": "correct horse"}).json["token"]
                    for h in ("ada", "bob", "cy")}
        a = self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 100}).json
        time.sleep(0.4)
        r = self.post("bob", f"/authorizations/{a['authorization_id']}/capture", {"amount": 10, "final": False})
        self.assertEqual(r.status, 201, r.raw)
        self.assertGreaterEqual(r.json["created_at"], a["created_at"])
        time.sleep(0.8)
        self.assertEqual(self.get("ada", "/authorizations").json["authorizations"][0]["status"], "expired")
        self.assertErr(self.post("ada", f"/authorizations/{a['authorization_id']}/void", None, key=None), 409, "authorization_not_open")
        self.assertErr(self.post("bob", f"/authorizations/{a['authorization_id']}/capture", {"amount": 10}), 409, "authorization_expired")

    def test_settlement_members_share_committed_at(self):
        call("POST", "/_test/reset", fixture(settlement_operator_ids=["u_cy"]))
        tok = call("POST", "/auth/login", {"email": "cy@example.com", "password": "correct horse"}).json["token"]
        r = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1},
                                                        {"from_handle": "bob", "to_handle": "cy", "amount": 1}]}, token=tok, key="s")
        self.assertEqual({p["created_at"] for p in r.json["payments"]}, {r.json["committed_at"]})
        self.assertRegex(r.json["committed_at"], self.FIXED)

    def test_imported_whole_second_timestamps_are_kept(self):
        exp = call("GET", "/_test/export").json
        self.post("ada", "/payments", {"to_handle": "bob", "amount": 1})
        exp = call("GET", "/_test/export").json
        exp["state"]["payments"][0]["created_at"] = "2026-09-24T13:10:00+02:00"
        self.assertEqual(call("POST", "/_test/import", exp).status, 204)
        self.assertEqual(self.get("ada", "/activity").json["payments"][0]["created_at"], "2026-09-24T13:10:00+02:00")
