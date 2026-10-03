"""Rows A, C, D, E: runtime contract, reset, errors, authentication."""
import json

from .base import RFC3339, ApiTestCase
from .support import fixture, user


class RuntimeTests(ApiTestCase):
    def test_health_and_content_type(self):
        s, b, r = self.api.call("GET", "/health")
        self.assertEqual((s, b), (200, {"status": "ok"}))
        self.assertEqual(r.getheader("Content-Type"), "application/json; charset=utf-8")

    def test_me_shape_and_timestamps(self):
        s, b, r = self.call("GET", "/me", who="ada")
        self.assertEqual(b, {"user_id": "u_ada", "display_name": "Ada", "handle": "ada",
                             "balance": 10000, "total": 10000, "available": 10000, "held": 0,
                             "currency": "EUR", "minor_units": 2})
        p = self.pay("ada", "bob", 5, "k")[1]
        self.assertRegex(p["created_at"], RFC3339)
        self.assertLessEqual(len(p["payment_id"]), 64)

    def test_unknown_route_and_method_have_error_body(self):
        self.expect(404, "not_found", self.api.call("GET", "/nope"))
        s, b, _ = self.api.call("DELETE", "/me")
        self.assertEqual(s, 405)
        self.assertIn("code", b["error"])

    def test_malformed_and_unknown_fields(self):
        self.expect(400, "malformed_request",
                    self.call("POST", "/payments", who="ada", key="k", raw=b"{nope"))
        self.expect(400, "malformed_request",
                    self.call("POST", "/payments", who="ada", key="k", raw=b"[1]"))
        self.expect(400, "malformed_request",
                    self.call("POST", "/payments", {"to_handle": 5, "amount": 1}, who="ada", key="k"))
        s, b, _ = self.call("POST", "/payments",
                            {"to_handle": "bob", "amount": 1, "extra": [1]}, who="ada", key="k2")
        self.assertEqual(s, 201)
        s, _, _ = self.call("GET", "/me?foo=bar", who="ada")
        self.assertEqual(s, 200)

    def test_missing_required_field_422(self):
        self.expect(422, "validation_failed",
                    self.call("POST", "/payments", {"amount": 5}, who="ada", key="k"))
        self.expect(422, "validation_failed",
                    self.call("POST", "/splits", {"amount": 5}, who="ada", key="k"))

    def test_amount_matrix(self):
        for bad in ("5", True, None, 0, -1, 1.5, 1000000001, [], {}, 1e10):
            self.expect(422, "validation_failed", self.pay("ada", "bob", bad, "k-bad"))
        for good, key in ((1, "a"), (1000000000, "b")):
            self.assertEqual(self.pay("ada", "bob", good, key)[0] if good == 1 else 409, 201 if good == 1 else 409)
        self.api.reset(fixture(users=[user("ada", 5000), user("bob", 0)]))
        t = self.api.login("ada@example.com")
        for i, raw in enumerate((b'{"to_handle":"bob","amount":1000.0}',
                                 b'{"to_handle":"bob","amount":1e3}')):
            s, b, _ = self.api.call("POST", "/payments", token=t, key="n%d" % i, raw=raw)
            self.assertEqual((s, b["amount"]), (201, 1000))
        self.expect(422, "validation_failed", self.api.call(
            "POST", "/payments", token=t, key="n9", raw=b'{"to_handle":"bob","amount":1000.5}'))

    def test_note_rules(self):
        for bad in (None, 5, "x" * 201):
            self.expect(422, "validation_failed", self.pay("ada", "bob", 1, "kn", note=bad))
        fancy = " héllo 😀 <b>&amp;</b>\n "
        for note, key in (("x" * 200, "ok1"), (fancy, "ok2")):
            s, b, _ = self.pay("ada", "bob", 1, key, note=note)
            self.assertEqual((s, b["note"]), (201, note))
        self.assertEqual(self.pay("ada", "bob", 1, "ok3", note="é" * 200)[0], 201)

    def test_visibility_rules(self):
        for bad in ("friends", 1, None, True, "PUBLIC"):
            self.expect(422, "validation_failed", self.pay("ada", "bob", 1, "kv", visibility=bad))
        self.assertEqual(self.pay("ada", "bob", 1, "kd")[1]["visibility"], "public")

    def test_query_int_rules(self):
        for path in ("/activity", "/requests"):
            for bad in ("1e9", "4.0", "+4", "-1", "abc", "", "%D9%A3"):
                self.expect(422, "validation_failed", self.call("GET", path + "?limit=" + bad, who="ada"))
                self.expect(422, "validation_failed", self.call("GET", path + "?offset=" + bad, who="ada"))
            for bad in ("0", "201"):
                self.expect(422, "validation_failed", self.call("GET", path + "?limit=" + bad, who="ada"))
            for good in ("1", "200"):
                self.assertEqual(self.call("GET", path + "?limit=" + good, who="ada")[0], 200)
            self.assertEqual(self.call("GET", path + "?offset=0&limit=50", who="ada")[0], 200)

    def test_unauthenticated_everywhere(self):
        for method, path in (("GET", "/me"), ("POST", "/payments"), ("POST", "/requests"),
                             ("GET", "/requests"), ("POST", "/requests/x/pay"),
                             ("POST", "/requests/x/decline"), ("POST", "/requests/x/cancel"),
                             ("POST", "/splits"), ("GET", "/activity"), ("POST", "/settlements")):
            self.expect(401, "unauthenticated", self.api.call(method, path, {}, key="k"))
            self.expect(401, "unauthenticated", self.api.call(method, path, {}, token="bogus", key="k"))
            self.expect(401, "unauthenticated", self.api.call(
                method, path, raw=b"{bad", headers={"Authorization": "Basic abc"}))

    def test_reset_replaces_everything(self):
        old = self.tok["ada"]
        self.pay("ada", "bob", 5, "k")
        self.api.reset(fixture(users=[user("ada", 1), user("zed", 2)]))
        self.expect(401, "unauthenticated", self.call("GET", "/me", token=old))
        self.assertEqual(self.api.call("GET", "/_test/export")[1]["state"]["payments"], [])
        self.expect(401, "unauthenticated", self.api.call(
            "POST", "/auth/login", {"email": "bob@example.com", "password": "correct horse"}))

    def test_reset_errors_keep_state(self):
        bad = fixture(users=[user("ada", -1)])
        self.expect(422, "validation_failed", self.api.call("POST", "/_test/reset", bad))
        self.expect(400, "malformed_request", self.api.call("POST", "/_test/reset", raw=b"{{"))
        self.assertEqual(self.balance("ada"), 10000)

    def test_currencies(self):
        for cur, mu in (("JPY", 0), ("BHD", 3), ("EUR", 2)):
            self.api.reset(fixture(currency=cur, minor_units=mu))
            t = self.api.login("ada@example.com")
            me = self.api.call("GET", "/me", token=t)[1]
            self.assertEqual((me["currency"], me["minor_units"]), (cur, mu))
            self.assertEqual(self.api.call("POST", "/payments", {"to_handle": "bob", "amount": 1},
                                           token=t, key="k")[1]["currency"], cur)

    def test_seeded_state_visible(self):
        fx = fixture(payments=[
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
             "note": "coffee", "visibility": "public"},
            {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5,
             "note": "secret", "visibility": "private"}],
            requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
                       "amount": 1200, "note": "taxi", "status": "pending"}])
        self.reset(fx)
        self.assertEqual(self.balance("ada"), 10000)
        ada = self.call("GET", "/activity", who="ada")[1]["payments"]
        cy = self.call("GET", "/activity", who="cy")[1]["payments"]
        self.assertEqual({p["payment_id"] for p in ada}, {"p_1", "p_2"})
        self.assertEqual([p["payment_id"] for p in cy], ["p_1"])
        self.assertIsNone(cy[0]["settlement_id"])
        self.assertEqual(self.call("GET", "/requests", who="ada")[1]["requests"][0]["status"], "pending")
        self.assertEqual(self.call("GET", "/requests", who="cy")[1]["requests"], [])

    def test_operators_default_and_big_balance(self):
        big = 2 ** 53 - 1
        self.api.reset(fixture(users=[user("ada", big), user("bob", 0)],
                               settlement_operator_ids=["u_ada"]))
        t = self.api.login("ada@example.com")
        self.assertEqual(self.api.call("POST", "/payments", {"to_handle": "bob", "amount": 1},
                                       token=t, key="k")[0], 201)
        self.assertEqual(self.api.call("GET", "/me", token=t)[1]["balance"], big - 1)


class AuthTests(ApiTestCase):
    def signup(self, email, pw="longenough", name="N"):
        return self.api.call("POST", "/auth/signup", {"email": email, "password": pw, "display_name": name})

    def test_signup_login_flow(self):
        s, b, _ = self.signup("New.User@x.com")
        self.assertEqual(s, 201)
        me = self.call("GET", "/me", token=b["token"])[1]
        self.assertEqual((me["balance"], me["handle"]), (0, "new_user"))
        s, lb, _ = self.api.call("POST", "/auth/login", {"email": "New.User@x.com", "password": "longenough"})
        self.assertEqual((s, lb["user_id"]), (200, b["user_id"]))
        self.assertNotEqual(lb["token"], b["token"])
        self.assertEqual(self.call("GET", "/me", token=lb["token"])[0], 200)
        self.assertEqual(self.call("GET", "/me", token=b["token"])[0], 200)
        self.assertEqual(self.pay("ada", "new_user", 10, "k")[0], 201)

    def test_handle_derivation(self):
        _, b, _ = self.signup("A.b-C+tag@x.com")
        self.assertEqual(self.call("GET", "/me", token=b["token"])[1]["handle"], "a_b_c_tag")
        _, b, _ = self.signup("x" * 25 + "@x.com")
        self.assertEqual(self.call("GET", "/me", token=b["token"])[1]["handle"], "x" * 20)

    def test_conflicts(self):
        self.expect(409, "email_taken", self.signup("ada@example.com"))
        self.expect(409, "handle_taken", self.signup("ada@other.org"))
        self.expect(401, "unauthenticated", self.api.call(
            "POST", "/auth/login", {"email": "ada@other.org", "password": "longenough"}))
        self.assertEqual(self.signup("dup@x.com")[0], 201)
        self.expect(409, "email_taken", self.signup("dup@x.com"))
        self.expect(409, "handle_taken", self.signup("dup@y.com"))

    def test_validation(self):
        self.expect(422, "validation_failed", self.signup("a@b.com", "1234567"))
        self.assertEqual(self.signup("eight@b.com", "12345678")[0], 201)
        for bad in ("nolocal", "@x.com", "a@", "a@b@c", "a b@c.com", ""):
            self.expect(422, "validation_failed", self.signup(bad))
        self.expect(400, "malformed_request", self.api.call(
            "POST", "/auth/signup", {"email": 1, "password": "longenough", "display_name": "x"}))
        self.expect(422, "validation_failed", self.api.call(
            "POST", "/auth/signup", {"email": "q@q.com", "password": "longenough"}))

    def test_login_failures(self):
        self.expect(401, "unauthenticated", self.api.call(
            "POST", "/auth/login", {"email": "ada@example.com", "password": "wrong horse"}))
        self.expect(401, "unauthenticated", self.api.call(
            "POST", "/auth/login", {"email": "zzz@example.com", "password": "correct horse"}))

    def test_password_not_plaintext_in_export(self):
        self.signup("p@x.com", "supersecret1")
        text = json.dumps(self.api.call("GET", "/_test/export")[1])
        self.assertNotIn("supersecret1", text)
        self.assertNotIn("correct horse", text)
