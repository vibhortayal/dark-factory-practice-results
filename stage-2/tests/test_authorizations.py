"""Rows S, T: holds, captures, voids, expiry, and the stage-2 fixture additions."""
import time
from datetime import datetime, timedelta, timezone

from .base import ApiTestCase
from .support import fixture, user


def seeded_auth(aid, amount, status="open", hours=3, frm="u_ada", to="u_bob", **extra):
    when = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds")
    return dict(id=aid, from_user_id=frm, to_user_id=to, amount=amount, note="seed",
                visibility="public", status=status, expires_at=when, **extra)


class AuthBase(ApiTestCase):
    def authorize(self, who="ada", to="bob", amount=2000, key="a1", **extra):
        return self.call("POST", "/authorizations", dict(to_handle=to, amount=amount, **extra), who=who, key=key)

    def hold(self, **kw):
        s, b, _ = self.authorize(**kw)
        self.assertEqual(s, 201, b)
        return b

    def capture(self, aid, body=None, who="bob", key="c1"):
        return self.call("POST", "/authorizations/%s/capture" % aid, body if body is not None else {}, who=who, key=key)

    def me(self, who):
        return self.call("GET", "/me", who=who)[1]


class AuthorizationTests(AuthBase):
    def test_create_shape_and_me(self):
        b = self.hold(visibility="private", note="deposit")
        self.assertEqual(set(b), {"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
                                  "amount", "captured_amount", "remaining_amount", "currency", "note", "visibility",
                                  "status", "expires_at", "payment_id", "payment_ids", "created_at"})
        self.assertEqual((b["status"], b["captured_amount"], b["remaining_amount"], b["payment_id"], b["payment_ids"]),
                         ("open", 0, 2000, None, []))
        delta = datetime.fromisoformat(b["expires_at"]) - datetime.fromisoformat(b["created_at"])
        self.assertEqual(delta, timedelta(seconds=600))
        me = self.me("ada")
        self.assertEqual((me["balance"], me["total"], me["available"], me["held"]), (10000, 10000, 8000, 2000))
        self.assertEqual(self.me("bob")["held"], 0)
        self.assertEqual(self.call("GET", "/activity", who="ada")[1]["payments"], [])

    def test_create_errors(self):
        self.expect(409, "insufficient_funds", self.authorize(amount=10001, key="e1"))
        self.hold(amount=10000, key="e2")
        self.expect(409, "insufficient_funds", self.authorize(amount=1, key="e3"))
        for bad in (0, "5", 1.5, 1000000001, True, None):
            self.expect(422, "validation_failed", self.authorize(who="bob", amount=bad, key="e4"))
        self.expect(422, "self_payment", self.authorize(who="bob", to="bob", key="e5"))
        self.expect(422, "validation_failed", self.authorize(who="bob", key="e6", note="x" * 201))
        self.expect(422, "validation_failed", self.authorize(who="bob", key="e7", visibility="x"))
        self.expect(404, "not_found", self.authorize(who="bob", to="ghost", key="e8"))

    def test_held_funds_cannot_be_spent(self):
        self.hold(amount=9000)
        self.expect(409, "insufficient_funds", self.pay("ada", "bob", 1001, "p1"))
        self.assertEqual(self.pay("ada", "bob", 1000, "p2")[0], 201)
        rid = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 1}, who="bob", key="r")[1]["request_id"]
        self.expect(409, "insufficient_funds", self.call("POST", "/requests/%s/pay" % rid, {}, who="ada", key="rp"))
        self.expect(409, "insufficient_funds", self.authorize(amount=1, key="a2"))
        self.api.reset(fixture(users=[user("ada", 1000), user("bob", 0), user("cy", 0)], settlement_operator_ids=["u_bob"]))
        self.tok = {h: self.api.login(h + "@example.com") for h in ("ada", "bob", "cy")}
        self.hold(amount=900)
        s = lambda amount, key: self.call("POST", "/settlements", {"transfers": [
            {"from_handle": "ada", "to_handle": "cy", "amount": amount}]}, who="bob", key=key)
        self.expect(409, "insufficient_funds", s(101, "s1"))
        self.assertEqual(s(100, "s2")[0], 201)

    def test_capture_final_default(self):
        aid = self.hold(note="deposit", visibility="private")["authorization_id"]
        s, pay, _ = self.capture(aid, {"amount": 1500})
        self.assertEqual(s, 201)
        self.assertEqual((pay["authorization_id"], pay["request_id"], pay["amount"], pay["note"], pay["visibility"],
                          pay["from_handle"], pay["to_handle"]), (aid, None, 1500, "deposit", "private", "ada", "bob"))
        self.assertEqual((self.balance("ada"), self.balance("bob")), (8500, 4000))
        me = self.me("ada")
        self.assertEqual((me["available"], me["held"]), (8500, 0))
        a = self.call("GET", "/authorizations", who="bob")[1]["authorizations"][0]
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_id"], a["payment_ids"]),
                         ("captured", 1500, 0, pay["payment_id"], [pay["payment_id"]]))
        self.expect(409, "authorization_not_open", self.capture(aid, {}, key="c2"))
        feed = self.call("GET", "/activity", who="cy")[1]["payments"]
        self.assertEqual(feed, [])  # private
        self.assertEqual(len(self.call("GET", "/activity", who="ada")[1]["payments"]), 1)

    def test_capture_default_amount_and_body_identity(self):
        aid = self.hold()["authorization_id"]
        s, pay, _ = self.capture(aid, {}, key="K")
        self.assertEqual((s, pay["amount"]), (201, 2000))
        self.assertEqual(self.capture(aid, {}, key="K")[:2], (200, pay))
        self.expect(409, "idempotency_key_reuse", self.capture(aid, {"amount": 2000}, key="K"))
        self.assertEqual(self.balance("bob"), 4500)
        # captures spend the reserved money even when available is zero
        aid2 = self.hold(amount=8000, key="a2")["authorization_id"]
        self.assertEqual(self.me("ada")["available"], 0)
        self.assertEqual(self.capture(aid2, {}, key="K2")[0], 201)

    def test_extended_capture(self):
        aid = self.hold()["authorization_id"]
        s, p1, _ = self.capture(aid, {"amount": 700, "final": False}, key="c1")
        self.assertEqual(s, 201)
        a = self.call("GET", "/authorizations?status=open", who="ada")[1]["authorizations"][0]
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"]), ("open", 700, 1300))
        self.assertEqual(self.me("ada")["held"], 1300)
        s, p2, _ = self.capture(aid, {"amount": 300, "final": False}, key="c2")
        self.expect(422, "capture_exceeds_authorization", self.capture(aid, {"amount": 1001, "final": False}, key="c3"))
        s, p3, _ = self.capture(aid, {"amount": 1000, "final": False}, key="c4")  # entire remainder closes it
        a = self.call("GET", "/authorizations", who="ada")[1]["authorizations"][0]
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_id"]),
                         ("captured", 2000, 0, p3["payment_id"]))
        self.assertEqual(a["payment_ids"], [p1["payment_id"], p2["payment_id"], p3["payment_id"]])
        self.assertEqual((self.me("ada")["held"], self.balance("bob")), (0, 4500))

    def test_final_capture_releases_remainder(self):
        aid = self.hold()["authorization_id"]
        self.capture(aid, {"amount": 500, "final": False}, key="c1")
        self.assertEqual(self.capture(aid, {"amount": 100}, key="c2")[0], 201)
        me = self.me("ada")
        self.assertEqual((me["held"], me["available"], me["total"]), (0, 9400, 9400))
        self.expect(409, "authorization_not_open", self.capture(aid, {"amount": 1}, key="c3"))

    def test_capture_errors(self):
        aid = self.hold()["authorization_id"]
        self.expect(403, "forbidden", self.capture(aid, {}, who="ada"))
        self.expect(403, "forbidden", self.capture(aid, {}, who="cy"))
        self.expect(404, "not_found", self.capture("nope", {}))
        for bad in (0, -1, "5", 1.5, None, True):
            self.expect(422, "validation_failed", self.capture(aid, {"amount": bad}, key="b"))
        self.expect(400, "malformed_request", self.capture(aid, {"amount": 5, "final": "yes"}, key="b"))
        self.expect(422, "capture_exceeds_authorization", self.capture(aid, {"amount": 2001}, key="b"))
        self.expect(422, "capture_exceeds_authorization", self.capture(aid, {"amount": 10 ** 12}, key="b"))
        self.assertEqual(self.capture(aid, {"amount": 2000}, key="b")[0], 201)

    def test_void(self):
        aid = self.hold()["authorization_id"]
        self.expect(403, "forbidden", self.call("POST", "/authorizations/%s/void" % aid, who="bob"))
        self.expect(403, "forbidden", self.call("POST", "/authorizations/%s/void" % aid, who="cy"))
        self.expect(404, "not_found", self.call("POST", "/authorizations/zz/void", who="ada"))
        for _ in range(2):
            b = self.call("POST", "/authorizations/%s/void" % aid, who="ada")
            self.assertEqual((b[0], b[1]["status"], b[1]["remaining_amount"]), (200, "voided", 0))
        self.assertEqual(self.me("ada")["available"], 10000)
        self.expect(409, "authorization_not_open", self.capture(aid, {}))
        aid2 = self.hold(key="a2")["authorization_id"]
        self.capture(aid2, {}, key="c")
        self.expect(409, "authorization_not_open", self.call("POST", "/authorizations/%s/void" % aid2, who="ada"))

    def test_void_partially_captured_keeps_records(self):
        aid = self.hold()["authorization_id"]
        p = self.capture(aid, {"amount": 600, "final": False})[1]
        a = self.call("POST", "/authorizations/%s/void" % aid, who="ada")[1]
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_ids"]),
                         ("voided", 600, 0, [p["payment_id"]]))
        self.assertEqual(self.me("ada")["available"], 9400)

    def test_list_filters(self):
        a1 = self.hold(key="1")["authorization_id"]
        a2 = self.hold(to="cy", amount=100, key="2")["authorization_id"]
        self.capture(a1, {}, key="c")
        self.assertEqual([a["authorization_id"] for a in self.call("GET", "/authorizations", who="ada")[1]["authorizations"]], [a2, a1])
        self.assertEqual(len(self.call("GET", "/authorizations?direction=incoming", who="ada")[1]["authorizations"]), 0)
        self.assertEqual(len(self.call("GET", "/authorizations?direction=outgoing&status=open", who="ada")[1]["authorizations"]), 1)
        self.assertEqual(len(self.call("GET", "/authorizations?direction=incoming", who="bob")[1]["authorizations"]), 1)
        self.assertEqual(self.call("GET", "/authorizations", who="cy")[1]["authorizations"][0]["authorization_id"], a2)
        page = self.call("GET", "/authorizations?limit=1", who="ada")[1]
        self.assertEqual((len(page["authorizations"]), page["has_more"]), (1, True))
        for q in ("direction=x", "status=nope", "limit=0", "offset=-1", "limit=1e2"):
            self.expect(422, "validation_failed", self.call("GET", "/authorizations?" + q, who="ada"))
        self.expect(401, "unauthenticated", self.api.call("GET", "/authorizations"))

    def test_idempotency_and_concurrency(self):
        a = self.authorize(key="K")
        self.assertEqual(self.authorize(key="K")[:2], (200, a[1]))
        self.expect(409, "idempotency_key_reuse", self.authorize(amount=5, key="K"))
        self.expect(400, "missing_idempotency_key", self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 1}, who="ada"))
        self.expect(422, "validation_failed", self.authorize(key="x" * 256))
        self.assertEqual(self.authorize(key="x" * 255, amount=1)[0], 201)
        self.expect(409, "insufficient_funds", self.authorize(amount=999999, key="F"))
        self.assertEqual(self.authorize(amount=10, key="F")[0], 201)  # failed key reusable
        self.assertEqual(self.authorize(who="bob", to="ada", key="K")[0], 201)  # per-user scope
        self.expect(400, "missing_idempotency_key", self.call("POST", "/authorizations/%s/capture" % a[1]["authorization_id"], {}, who="bob"))
        self.expect(422, "validation_failed", self.capture(a[1]["authorization_id"], {}, key="y" * 256))

    def test_concurrent_captures_never_exceed(self):
        import threading
        aid = self.hold()["authorization_id"]
        res = []
        threads = [threading.Thread(target=lambda i=i: res.append(self.capture(aid, {"amount": 300, "final": False}, key="k%d" % i)))
                   for i in range(20)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(r[0] for r in res).count(201), 6)
        self.assertEqual(self.balance("ada") + self.balance("bob") + self.balance("cy"), 13000)
        self.assertEqual(self.me("ada")["held"], 200)
        res.clear()
        same = [threading.Thread(target=lambda: res.append(self.capture(aid, {"amount": 200}, key="same"))) for _ in range(20)]
        [t.start() for t in same]
        [t.join() for t in same]
        self.assertEqual(sorted(r[0] for r in res), [200] * 19 + [201])


class ExpiryAndFixtureTests(AuthBase):
    def test_expiry_by_clock(self):
        self.reset(fixture(authorization_ttl_seconds=1))
        aid = self.hold()["authorization_id"]
        self.assertEqual(self.me("ada")["held"], 2000)
        time.sleep(1.3)
        a = self.call("GET", "/authorizations", who="ada")[1]["authorizations"][0]
        self.assertEqual((a["status"], a["remaining_amount"]), ("expired", 0))
        self.assertEqual(self.me("ada")["available"], 10000)
        self.assertEqual(self.call("GET", "/authorizations?status=open", who="ada")[1]["authorizations"], [])
        self.assertEqual(len(self.call("GET", "/authorizations?status=expired", who="ada")[1]["authorizations"]), 1)
        self.expect(409, "authorization_expired", self.capture(aid, {}))
        self.expect(409, "authorization_not_open", self.call("POST", "/authorizations/%s/void" % aid, who="ada"))

    def test_expiry_keeps_partial_captures(self):
        self.reset(fixture(authorization_ttl_seconds=2))
        aid = self.hold()["authorization_id"]
        p = self.capture(aid, {"amount": 400, "final": False})[1]
        time.sleep(2.3)
        a = self.call("GET", "/authorizations", who="bob")[1]["authorizations"][0]
        self.assertEqual((a["status"], a["captured_amount"], a["payment_ids"]), ("expired", 400, [p["payment_id"]]))
        self.assertEqual(self.me("ada")["available"], 9600)

    def test_ttl_validation(self):
        for bad in (0, -5, 1.5, "60", None, True):
            self.expect(422, "validation_failed", self.api.call("POST", "/_test/reset", fixture(authorization_ttl_seconds=bad)))
        self.reset(fixture(authorization_ttl_seconds=45))
        a = self.hold()
        self.assertEqual(datetime.fromisoformat(a["expires_at"]) - datetime.fromisoformat(a["created_at"]), timedelta(seconds=45))

    def test_seeded_authorizations(self):
        fx = fixture(authorizations=[
            seeded_auth("a_open", 2000),
            seeded_auth("a_past", 3000, hours=-3),
            seeded_auth("a_cap", 500, status="captured"),
            seeded_auth("a_void", 400, status="voided"),
            seeded_auth("a_exp", 400, status="expired"),
        ])
        self.reset(fx)
        me = self.me("ada")
        self.assertEqual((me["total"], me["held"], me["available"]), (10000, 2000, 8000))
        by_id = {a["authorization_id"]: a for a in self.call("GET", "/authorizations", who="bob")[1]["authorizations"]}
        self.assertEqual({k: v["status"] for k, v in by_id.items()},
                         {"a_open": "open", "a_past": "expired", "a_cap": "captured", "a_void": "voided", "a_exp": "expired"})
        self.assertEqual(by_id["a_open"]["remaining_amount"], 2000)
        self.assertEqual(self.expect(200, None, self.call("GET", "/authorizations?direction=incoming&status=open", who="bob"))
                         ["authorizations"][0]["authorization_id"], "a_open")
        self.assertEqual(self.call("GET", "/authorizations", who="cy")[1]["authorizations"], [])
        self.assertEqual(self.capture("a_open", {"amount": 2000})[0], 201)

    def test_seeded_holds_over_balance_rejected(self):
        over = fixture(authorizations=[seeded_auth("a1", 6000), seeded_auth("a2", 4001)])
        self.expect(422, "validation_failed", self.api.call("POST", "/_test/reset", over))
        self.assertEqual(self.balance("ada"), 10000)  # previous state intact
        self.reset(fixture(authorizations=[seeded_auth("a1", 6000), seeded_auth("a2", 4000)]))
        self.assertEqual(self.me("ada")["available"], 0)
        # an expired hold does not count against the balance
        self.reset(fixture(authorizations=[seeded_auth("a1", 99999, hours=-2)]))
        self.assertEqual(self.me("ada")["held"], 0)

    def test_export_import_roundtrip_with_authorizations(self):
        self.reset(fixture(authorization_ttl_seconds=900))
        a = self.hold(key="KA")
        p = self.capture(a["authorization_id"], {"amount": 100, "final": False}, key="KC")
        doc = self.api.call("GET", "/_test/export")[1]
        from .support import Api
        other = Api()
        try:
            self.assertEqual(other.call("POST", "/_test/import", doc)[0], 204)
            t = self.tok["ada"]
            self.assertEqual(other.call("GET", "/me", token=t)[1]["held"], 1900)
            self.assertEqual(other.call("POST", "/authorizations", {"to_handle": "bob", "amount": 2000}, token=t, key="KA")[0], 200)
            self.assertEqual(other.call("POST", "/authorizations/%s/capture" % a["authorization_id"], {"amount": 100, "final": False},
                                        token=self.tok["bob"], key="KC")[1], p[1])
            new = other.call("POST", "/authorizations", {"to_handle": "cy", "amount": 1}, token=t, key="N")[1]
            self.assertEqual(datetime.fromisoformat(new["expires_at"]) - datetime.fromisoformat(new["created_at"]), timedelta(seconds=900))
        finally:
            other.close()

    def test_import_of_stage1_export(self):
        self.reset()
        self.pay("ada", "bob", 100, "K")
        doc = self.api.call("GET", "/_test/export")[1]
        for key in ("authorizations", "authorization_ttl_seconds"):
            doc["state"].pop(key, None)
        for rec in doc["state"]["payments"]:
            rec["data"].pop("authorization_id", None)
        self.assertEqual(self.api.call("POST", "/_test/import", doc)[0], 204)
        self.assertEqual(self.me("ada")["available"], 9900)
        self.assertEqual(self.call("GET", "/activity", who="ada")[1]["payments"][0]["authorization_id"], None)
        self.assertEqual(self.authorize(key="n")[0], 201)

    def test_stage_one_paths_and_ui_routes(self):
        for path in ("/", "/requests", "/split", "/signup", "/login", "/authorizations"):
            s, _, r = self.api.call("GET", path, headers={"Accept": "text/html,application/xhtml+xml"})
            self.assertEqual((s, r.getheader("Content-Type")), (200, "text/html; charset=utf-8"), path)
        self.expect(401, "unauthenticated", self.api.call("GET", "/requests"))
        self.expect(401, "unauthenticated", self.api.call("GET", "/authorizations", headers={"Accept": "application/json"}))
        self.assertEqual(self.call("GET", "/requests", who="ada")[1], {"requests": [], "has_more": False})
        self.assertEqual(self.api.call("GET", "/ui/js/main.js")[2].getheader("Content-Type"), "text/javascript; charset=utf-8")
        self.assertEqual(self.api.call("GET", "/ui/%2e%2e/server.py")[0], 404)
