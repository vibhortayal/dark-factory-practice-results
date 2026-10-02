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


class HostileInputTests(World):
    def test_no_5xx(self):
        bodies = [b"", b"null", b"[]", b'"x"', b"1", b"[" * 100000, b'{"a":' * 50000, b"\xff\xfe",
                  b'{"amount": NaN}', b'{"amount": 1e999, "to_handle": "bob"}',
                  b'{"to_handle": "bob", "amount": 1' + b"0" * 5000 + b"}"]
        for path in ("/payments", "/requests", "/splits", "/settlements", "/requests/x/pay",
                     "/auth/signup", "/auth/login", "/_test/reset", "/_test/import"):
            for raw in bodies:
                for who in ("ada", None):
                    r = self.post(who, path, raw=raw, key="k" * 10000)
                    self.assertLess(r.status, 500, (path, raw[:20], r.raw))
                    self.assertTrue(r.json is None or "error" in r.json or r.status < 300)
        self.assertEqual(self.balance("ada"), 10000)


class VerifierFindingTests(World):
    """B1-B4 and notes N1, N2 from the stage-1 BLOCK verdict."""

    def test_b1_wrong_typed_ids_in_fixture(self):
        u = [user("u_ada", "ada", 1)]
        bad = [fixture(users=u, settlement_operator_ids=[["u_ada"]]),
               fixture(users=u, settlement_operator_ids=[{"id": "u_ada"}]),
               fixture(users=u, payments=[{"id": "p", "from_user_id": [1], "to_user_id": "u_ada", "amount": 1}]),
               fixture(users=u, payments=[{"id": "p", "from_user_id": "u_ada", "to_user_id": {}, "amount": 1}]),
               fixture(users=u, requests=[{"id": "r", "requester_id": [], "payer_id": "u_ada", "amount": 1}]),
               fixture(users=u, requests=[{"id": "r", "requester_id": "u_ada", "payer_id": {"a": 1}, "amount": 1}])]
        for fx in bad:
            self.assertErr(call("POST", "/_test/reset", fx), 422, "validation_failed")
        self.assertEqual(self.balance("ada"), 10000)

    def test_b2_huge_limit_and_offset(self):
        huge = "9" * 5000
        self.assertErr(self.get("ada", "/requests?limit=" + huge), 422, "validation_failed")
        self.assertErr(self.get("ada", "/activity?limit=" + huge), 422, "validation_failed")
        r = self.get("ada", "/activity?offset=" + huge)
        self.assertEqual((r.status, r.json["payments"]), (200, []))

    def test_b3_huge_amount(self):
        huge = "9" * 5000
        for path, body in (("/payments", '{"to_handle":"bob","amount":%s}'),
                           ("/requests", '{"payer_handle":"bob","amount":%s}'),
                           ("/splits", '{"participant_handles":["bob"],"amount":%s}')):
            self.assertErr(self.post("ada", path, raw=(body % huge).encode()), 422, "validation_failed")
        t = '{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":%s}]}' % huge
        self.fixture_extra  # settlements need an operator; non-operator is 403 first
        self.assertErr(self.post("ada", "/settlements", raw=t.encode()), 403, "forbidden")

    def test_b4_oversized_header(self):
        r = self.post("ada", "/payments", {"to_handle": "bob", "amount": 1}, key="k" * 65520)
        self.assertErr(r, 422, "validation_failed")
        self.assertEqual(r.headers["Content-Type"], "application/json; charset=utf-8")

    def test_n1_deeply_nested_unknown_field(self):
        deep = '{"to_handle":"bob","amount":1,"x":' + "[" * 990 + "]" * 990 + "}"
        self.assertEqual(self.post("ada", "/payments", raw=deep.encode()).status, 201)
        too_deep = '{"to_handle":"bob","amount":1,"x":' + "[" * 100000 + "}"
        self.assertErr(self.post("ada", "/payments", raw=too_deep.encode()), 400, "malformed_request")
        self.assertErr(call("POST", "/_test/reset", raw=too_deep.encode()), 400, "malformed_request")

    def test_huge_numbers_everywhere(self):
        for amount in ("1e999999", "0." + "0" * 5000 + "1", "-" + "9" * 5000):
            r = self.post("ada", "/payments", raw=('{"to_handle":"bob","amount":%s}' % amount).encode())
            self.assertErr(r, 422, "validation_failed")
        r = self.post("ada", "/payments", raw=('{"to_handle":"bob","amount":1,"x":%s}' % ("9" * 5000)).encode())
        self.assertEqual(r.status, 201)
        self.assertErr(call("POST", "/_test/reset", raw=('{"users":[{"id":"a","email":"a@x.io","password":"p","handle":"a","balance":%s}]}' % ("9" * 5000)).encode()), 422, "validation_failed")

    def test_http_layer_errors_carry_json(self):
        import socket
        from .helpers import server_port

        def raw_exchange(data):
            with socket.create_connection(("127.0.0.1", server_port()), timeout=10) as s:
                s.sendall(data)
                chunks = b""
                while True:
                    c = s.recv(65536)
                    if not c:
                        return chunks
                    chunks += c
                    if b"\r\n\r\n" in chunks and b"}" in chunks:
                        return chunks
        cases = [b"PROPFIND /me HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n",
                 b"GET /activity?x=" + b"a" * 70000 + b" HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n",
                 b"GET /me HTTP/1.1\r\nHost: x\r\n" + b"".join(b"H%d: v\r\n" % i for i in range(150)) + b"Connection: close\r\n\r\n",
                 b"POST /payments HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\nConnection: close\r\n\r\n"]
        for data in cases:
            reply = raw_exchange(data)
            head, _, body = reply.partition(b"\r\n\r\n")
            status = int(head.split()[1])
            self.assertTrue(400 <= status < 500, (data[:30], head))
            self.assertIn(b"application/json; charset=utf-8", head)
            self.assertIn(b'"error"', body)

    def test_b5_malformed_absolute_target(self):
        import socket
        from .helpers import server_port
        for target in (b"http://[bad/health", b"http://[::1/me", b"http://["):
            with socket.create_connection(("127.0.0.1", server_port()), timeout=10) as s:
                s.sendall(b"GET " + target + b" HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
                reply = b""
                while True:
                    c = s.recv(65536)
                    if not c:
                        break
                    reply += c
            self.assertIn(b" 400 ", reply.split(b"\r\n")[0])
            self.assertIn(b"malformed_request", reply)
        self.assertEqual(call("GET", "/health").status, 200)

    def test_n9_leading_zero_numbers(self):
        self.assertEqual(self.get("ada", "/activity?limit=" + "0" * 17 + "50").status, 200)
        self.assertEqual(self.get("ada", "/activity?offset=" + "0" * 30).status, 200)
        self.assertErr(self.get("ada", "/activity?limit=" + "0" * 30), 422, "validation_failed")
