from .helpers import World, call, user, fixture


class FeedTests(World):
    def test_visibility_rule(self):
        pub = self.post("ada", "/payments", {"to_handle": "bob", "amount": 1, "note": "pub"}).json
        prv = self.post("ada", "/payments", {"to_handle": "bob", "amount": 2, "visibility": "private"}).json
        ids = lambda who: [p["payment_id"] for p in self.get(who, "/activity").json["payments"]]
        self.assertEqual(ids("ada"), [prv["payment_id"], pub["payment_id"]])
        self.assertEqual(ids("bob"), [prv["payment_id"], pub["payment_id"]])
        self.assertEqual(ids("cy"), [pub["payment_id"]])

    def test_paging(self):
        for _ in range(3):
            self.post("ada", "/payments", {"to_handle": "bob", "amount": 1})
        p = self.get("cy", "/activity?limit=3").json
        self.assertEqual((len(p["payments"]), p["has_more"]), (3, False))
        p = self.get("cy", "/activity?limit=2&offset=1&direction=zzz").json
        self.assertEqual((len(p["payments"]), p["has_more"]), (2, False))
        self.assertErr(self.get("cy", "/activity?limit=0"), 422, "validation_failed")

    def test_seeded(self):
        extra = {"payments": [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
                               "note": "coffee", "visibility": "private"},
                              {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 5,
                               "visibility": "public"}],
                 "requests": [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200,
                               "note": "taxi", "status": "pending"}]}
        self.assertEqual(call("POST", "/_test/reset", fixture(**extra)).status, 204)
        tok = call("POST", "/auth/login", {"email": "cy@example.com", "password": "correct horse"}).json["token"]
        pays = call("GET", "/activity", token=tok).json["payments"]
        self.assertEqual([p["payment_id"] for p in pays], ["p_2"])
        self.assertEqual(call("GET", "/me", token=tok).json["balance"], 500)
        tok = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}).json["token"]
        self.assertEqual([p["payment_id"] for p in call("GET", "/activity", token=tok).json["payments"]], ["p_2", "p_1"])
        self.assertEqual(call("GET", "/requests", token=tok).json["requests"][0]["request_id"], "rq_1")


class AuthTests(World):
    def test_signup_login(self):
        r = call("POST", "/auth/signup", {"email": "Ab.C-d+e@x.io", "password": "12345678", "display_name": "Q"})
        self.assertEqual(r.status, 201)
        me = call("GET", "/me", token=r.json["token"]).json
        self.assertEqual((me["handle"], me["balance"]), ("ab_c_d_e", 0))
        r2 = call("POST", "/auth/login", {"email": "Ab.C-d+e@x.io", "password": "12345678"})
        self.assertEqual(r2.status, 200)
        self.assertEqual(call("GET", "/me", token=r.json["token"]).status, 200)
        r = call("POST", "/auth/signup", {"email": "x" * 30 + "@x.io", "password": "12345678", "display_name": "Q"})
        self.assertEqual(call("GET", "/me", token=r.json["token"]).json["handle"], "x" * 20)

    def test_signup_errors(self):
        s = lambda **b: call("POST", "/auth/signup", {"email": "n@x.io", "password": "12345678", "display_name": "N", **b})
        self.assertErr(s(email="ada@example.com"), 409, "email_taken")
        self.assertErr(s(email="ADA@other.io"), 409, "handle_taken")
        self.assertErr(call("POST", "/auth/login", {"email": "ADA@other.io", "password": "12345678"}), 401, "unauthenticated")
        self.assertErr(s(password="1234567"), 422, "validation_failed")
        for bad in ("noat", "@x.io", "a@"):
            self.assertErr(s(email=bad), 422, "validation_failed")
        self.assertErr(s(email=1), 400, "malformed_request")
        self.assertErr(call("POST", "/auth/signup", {"email": "n@x.io", "password": "12345678"}), 422, "validation_failed")
        self.assertEqual(s().status, 201)

    def test_login_errors(self):
        self.assertErr(call("POST", "/auth/login", {"email": "ada@example.com", "password": "nope nope"}), 401, "unauthenticated")
        self.assertErr(call("POST", "/auth/login", {"email": "no@example.com", "password": "nope nope"}), 401, "unauthenticated")

    def test_auth_required_everywhere(self):
        for method, path in (("GET", "/me"), ("POST", "/payments"), ("POST", "/requests"), ("GET", "/requests"),
                             ("POST", "/requests/x/pay"), ("POST", "/requests/x/decline"), ("POST", "/requests/x/cancel"),
                             ("POST", "/splits"), ("POST", "/settlements"), ("GET", "/activity")):
            for hdr in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Token abc"}, {"Authorization": "Bearer"}):
                r = call(method, path, {}, key="k", headers=hdr)
                self.assertErr(r, 401, "unauthenticated")

    def test_unknown_routes_and_methods(self):
        self.assertErr(call("GET", "/nothing"), 404, "not_found")
        self.assertEqual(call("DELETE", "/me").status, 405)
        self.assertIsNotNone(call("DELETE", "/me").code)

    def test_reset_clears_everything(self):
        old = self.tok["ada"]
        call("POST", "/_test/reset", fixture(users=[user("u_z", "zed", 7)]))
        self.assertErr(call("GET", "/me", token=old), 401, "unauthenticated")
        self.assertErr(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=old, key="k"), 401, "unauthenticated")

    def test_reset_validation_changes_nothing(self):
        self.assertErr(call("POST", "/_test/reset", fixture(users=[user("u_z", "zed", -1)])), 422, "validation_failed")
        self.assertErr(call("POST", "/_test/reset", fixture(minor_units=5)), 422, "validation_failed")
        self.assertErr(call("POST", "/_test/reset", fixture(users=[user("u_z", "zed", 1), user("u_z", "yo", 1)])), 422, "validation_failed")
        self.assertErr(call("POST", "/_test/reset", raw=b"{"), 400, "malformed_request")
        self.assertEqual(self.balance("ada"), 10000)

    def test_currencies(self):
        for cur, mu in (("JPY", 0), ("BHD", 3), ("EUR", 2)):
            call("POST", "/_test/reset", fixture(currency=cur, minor_units=mu, users=[user("u_z", "zed", 2 ** 53)]))
            tok = call("POST", "/auth/login", {"email": "zed@example.com", "password": "correct horse"}).json["token"]
            me = call("GET", "/me", token=tok).json
            self.assertEqual((me["currency"], me["minor_units"], me["balance"]), (cur, mu, 2 ** 53))
