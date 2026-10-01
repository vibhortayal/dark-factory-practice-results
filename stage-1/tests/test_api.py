"""Black-box tests: start the server as a subprocess and talk HTTP.

Run from stage-1/:  python3 -m unittest discover -s tests -v
"""
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RFC3339 = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)$")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Resp:
    def __init__(self, status, headers, raw):
        self.status, self.headers, self.raw = status, headers, raw
        self.json = json.loads(raw) if raw else None


def call(port, method, path, body=None, token=None, key=None, raw=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    h = dict(headers or {})
    if token:
        h["Authorization"] = "Bearer " + token
    if key is not None:
        h["Idempotency-Key"] = key
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    if data is not None:
        h["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=h)
    r = conn.getresponse()
    out = r.read()
    conn.close()
    return Resp(r.status, dict(r.getheaders()), out)


def user(handle, balance, **kw):
    return dict({"id": "u_" + handle, "email": handle + "@example.com", "password": "correct horse",
                 "display_name": handle.title(), "handle": handle, "balance": balance}, **kw)


def fixture(**kw):
    fx = {"currency": "EUR", "minor_units": 2,
          "users": [user("ada", 10000), user("bob", 2500), user("cy", 500)]}
    fx.update(kw)
    return fx


class Base(unittest.TestCase):
    proc = None

    @classmethod
    def setUpClass(cls):
        for _ in range(5):  # another process may grab the port between probe and bind
            cls.port = free_port()
            cls.proc = subprocess.Popen([sys.executable, "-m", "app"], cwd=ROOT,
                                        env=dict(os.environ, PORT=str(cls.port)))
            for _ in range(100):
                if cls.proc.poll() is not None:
                    break
                try:
                    if call(cls.port, "GET", "/health").status == 200:
                        return
                except OSError:
                    time.sleep(0.1)
            cls.proc.kill()
            cls.proc.wait()
        raise RuntimeError("server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait()

    def req(self, *a, **k):
        return call(self.port, *a, **k)

    def reset(self, fx=None):
        r = self.req("POST", "/_test/reset", fx or fixture())
        self.assertEqual(r.status, 204, r.raw)

    def login(self, handle, password="correct horse"):
        r = self.req("POST", "/auth/login", {"email": handle + "@example.com", "password": password})
        self.assertEqual(r.status, 200, r.raw)
        return r.json["token"]

    def setUp(self):
        self.reset()
        self.ada, self.bob, self.cy = (self.login(h) for h in ("ada", "bob", "cy"))

    def post(self, path, body, token, key=None, **kw):
        return self.req("POST", path, body, token=token, key=key or uuid.uuid4().hex, **kw)

    def err(self, r, status, code):
        self.assertEqual(r.status, status, r.raw)
        self.assertEqual(set(r.json), {"error"})
        self.assertEqual(r.json["error"]["code"], code)
        self.assertIsInstance(r.json["error"]["message"], str)

    def bal(self, token):
        return self.req("GET", "/me", token=token).json["balance"]

    def total(self):
        return sum(self.bal(t) for t in (self.ada, self.bob, self.cy))


PAYMENT_KEYS = {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
                "currency", "note", "visibility", "request_id", "settlement_id", "created_at"}
REQUEST_KEYS = {"request_id", "requester_id", "requester_handle", "payer_id", "payer_handle",
                "amount", "currency", "note", "status", "payment_id", "created_at"}


class TestRuntimeAndReset(Base):
    def test_health_and_content_type(self):
        r = self.req("GET", "/health")
        self.assertEqual(r.json, {"status": "ok"})
        self.assertEqual(r.headers["Content-Type"], "application/json; charset=utf-8")
        e = self.req("GET", "/me")
        self.err(e, 401, "unauthenticated")
        self.assertEqual(e.headers["Content-Type"], "application/json; charset=utf-8")

    def test_unknown_route_and_method(self):
        self.err(self.req("GET", "/nope"), 404, "not_found")
        self.assertEqual(self.req("DELETE", "/payments", token=self.ada).status, 405)
        self.assertEqual(self.req("DELETE", "/payments", token=self.ada).json["error"]["code"],
                         "method_not_allowed")

    def test_reset_invalidates_tokens_and_sets_balances(self):
        self.reset(fixture(users=[user("ada", 7)]))
        self.err(self.req("GET", "/me", token=self.ada), 401, "unauthenticated")
        self.assertEqual(self.bal(self.login("ada")), 7)

    def test_currencies(self):
        for cur, mu in (("JPY", 0), ("BHD", 3), ("EUR", 2)):
            self.reset(fixture(currency=cur, minor_units=mu))
            tok = self.login("ada")
            me = self.req("GET", "/me", token=tok).json
            self.assertEqual((me["currency"], me["minor_units"]), (cur, mu))
            p = self.post("/payments", {"to_handle": "bob", "amount": 5}, tok).json
            self.assertEqual(p["currency"], cur)

    def test_seed_negative_balance_rejected_state_kept(self):
        self.err(self.req("POST", "/_test/reset", fixture(users=[user("zed", -1)])), 422,
                 "validation_failed")
        self.assertEqual(self.bal(self.ada), 10000)

    def test_bad_fixtures(self):
        self.err(self.req("POST", "/_test/reset", raw=b"{nope"), 400, "malformed_request")
        for bad in ([], {"users": "x"}, {"users": [1]}, {"users": [user("a", 1), user("a", 1)]},
                    {"minor_units": 5}, {"users": [user("ada", 1)], "payments": [{"id": "p"}]},
                    {"users": [user("ada", 1)], "requests": [{"id": "r", "requester_id": "x"}]}):
            r = self.req("POST", "/_test/reset", bad)
            self.assertIn(r.status, (400, 422), bad)
            self.assertIn("error", r.json)
        self.assertEqual(self.bal(self.ada), 10000)

    def test_seeded_payments_requests_and_defaults(self):
        fx = fixture(
            payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
                       "note": "coffee", "visibility": "private"}],
            requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200,
                       "note": "taxi", "status": "pending"},
                      {"id": "rq_2", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1,
                       "note": "", "status": "declined"}],
            settlement_operator_ids=["u_ada"])
        self.reset(fx)
        ada, bob, cy = self.login("ada"), self.login("bob"), self.login("cy")
        self.assertEqual(self.bal(ada), 10000)
        act = self.req("GET", "/activity", token=bob).json["payments"]
        self.assertEqual([p["payment_id"] for p in act], ["p_1"])
        self.assertEqual(set(act[0]), PAYMENT_KEYS)
        self.assertIsNone(act[0]["settlement_id"])
        self.assertEqual(self.req("GET", "/activity", token=cy).json["payments"], [])
        self.assertEqual(len(self.req("GET", "/requests", token=ada).json["requests"]), 2)
        self.assertEqual(self.req("GET", "/requests", token=cy).json["requests"], [])
        self.err(self.post("/requests/rq_2/pay", {}, ada), 409, "request_not_pending")
        r = self.post("/requests/rq_1/pay", {}, ada)
        self.assertEqual(r.status, 201)
        self.assertEqual(r.json["request_id"], "rq_1")
        # optional sections
        self.reset({"currency": "EUR", "minor_units": 2, "users": [user("ada", 1)]})


class TestAuth(Base):
    def test_signup_login(self):
        r = self.req("POST", "/auth/signup", {"email": "Foo.Bar+x@example.com",
                                              "password": "12345678", "display_name": "F"})
        self.assertEqual(r.status, 201)
        self.assertEqual(set(r.json), {"user_id", "display_name", "token"})
        me = self.req("GET", "/me", token=r.json["token"]).json
        self.assertEqual((me["handle"], me["balance"]), ("foo_bar_x", 0))
        r2 = self.req("POST", "/auth/login", {"email": "Foo.Bar+x@example.com", "password": "12345678"})
        r3 = self.req("POST", "/auth/login", {"email": "Foo.Bar+x@example.com", "password": "12345678"})
        self.assertNotEqual(r2.json["token"], r3.json["token"])
        for t in (r.json["token"], r2.json["token"], r3.json["token"]):
            self.assertEqual(self.req("GET", "/me", token=t).status, 200)
        self.assertEqual(self.post("/payments", {"to_handle": "foo_bar_x", "amount": 5},
                                   self.ada).status, 201)

    def test_handle_truncation(self):
        r = self.req("POST", "/auth/signup", {"email": "a" * 25 + "@example.com",
                                              "password": "12345678", "display_name": "F"})
        self.assertEqual(self.req("GET", "/me", token=r.json["token"]).json["handle"], "a" * 20)

    def test_conflicts(self):
        body = {"email": "ada@example.com", "password": "12345678", "display_name": "x"}
        self.err(self.req("POST", "/auth/signup", body), 409, "email_taken")
        body["email"] = "Ada@other.org"
        self.err(self.req("POST", "/auth/signup", body), 409, "handle_taken")
        self.err(self.req("POST", "/auth/login", {"email": "Ada@other.org", "password": "12345678"}),
                 401, "unauthenticated")

    def test_validation(self):
        ok = {"email": "q@example.com", "password": "12345678", "display_name": "Q"}
        self.assertEqual(self.req("POST", "/auth/signup", dict(ok, password="1234567")).status, 422)
        for e in ("plain", "@x.com", "a@", "a@b@c"):
            self.err(self.req("POST", "/auth/signup", dict(ok, email=e)), 422, "validation_failed")
        self.err(self.req("POST", "/auth/signup", {"email": "q@example.com"}), 422, "validation_failed")
        for k in ("email", "password", "display_name"):
            self.err(self.req("POST", "/auth/signup", dict(ok, **{k: 5})), 400, "malformed_request")
        self.assertEqual(self.req("POST", "/auth/signup", ok).status, 201)

    def test_login_failures(self):
        self.err(self.req("POST", "/auth/login", {"email": "ada@example.com", "password": "bad"}),
                 401, "unauthenticated")
        self.err(self.req("POST", "/auth/login", {"email": "no@example.com", "password": "bad"}),
                 401, "unauthenticated")

    def test_concurrent_signup(self):
        body = {"email": "dup@example.com", "password": "12345678", "display_name": "D"}
        with ThreadPoolExecutor(10) as ex:
            rs = list(ex.map(lambda _: self.req("POST", "/auth/signup", body), range(10)))
        self.assertEqual(sorted(r.status for r in rs), [201] + [409] * 9)
        body = {"email": "x.y@example.com", "password": "12345678", "display_name": "D"}
        body2 = dict(body, email="x_y@example.com")
        with ThreadPoolExecutor(10) as ex:
            rs = list(ex.map(lambda i: self.req("POST", "/auth/signup", body if i % 2 else body2),
                             range(10)))
        self.assertEqual(sorted(r.status for r in rs), [201] + [409] * 9)

    def test_every_endpoint_needs_token(self):
        for m, p in (("GET", "/me"), ("GET", "/activity"), ("GET", "/requests"),
                     ("POST", "/payments"), ("POST", "/requests"), ("POST", "/splits"),
                     ("POST", "/settlements"), ("POST", "/requests/x/pay"),
                     ("POST", "/requests/x/decline"), ("POST", "/requests/x/cancel")):
            for h in (None, {"Authorization": "Bearer nope"}, {"Authorization": "Basic abc"},
                      {"Authorization": "Bearer"}):
                self.err(self.req(m, p, {} if m == "POST" else None, headers=h, key="k"),
                         401, "unauthenticated")

    def test_password_not_plaintext_in_export(self):
        self.assertNotIn(b"correct horse", self.req("GET", "/_test/export").raw)


class TestPayments(Base):
    def test_shape_and_defaults(self):
        r = self.post("/payments", {"to_handle": "bob", "amount": 1500, "note": "dinner"}, self.ada)
        self.assertEqual(r.status, 201)
        self.assertEqual(set(r.json), PAYMENT_KEYS)
        j = r.json
        self.assertEqual((j["from_handle"], j["to_handle"], j["visibility"], j["request_id"],
                          j["settlement_id"], j["currency"]), ("ada", "bob", "public", None, None, "EUR"))
        self.assertRegex(j["created_at"], RFC3339)
        self.assertLessEqual(len(j["payment_id"]), 64)
        self.assertEqual(self.post("/payments", {"to_handle": "bob", "amount": 1}, self.ada).json["note"], "")
        self.assertEqual((self.bal(self.ada), self.bal(self.bob)), (8499, 4001))

    def test_unknown_fields_and_query_ignored(self):
        r = self.req("POST", "/payments?x=1", {"to_handle": "bob", "amount": 1, "zzz": [1]},
                     token=self.ada, key="k1")
        self.assertEqual(r.status, 201)
        self.assertEqual(self.req("GET", "/activity?foo=bar", token=self.ada).status, 200)
        self.assertEqual(self.req("GET", "/requests?foo=bar", token=self.ada).status, 200)

    def test_funds(self):
        self.err(self.post("/payments", {"to_handle": "ada", "amount": 501}, self.cy), 409, "insufficient_funds")
        self.assertEqual(self.bal(self.cy), 500)
        self.assertEqual(self.post("/payments", {"to_handle": "ada", "amount": 500}, self.cy).status, 201)
        self.assertEqual(self.bal(self.cy), 0)

    def test_amount_matrix(self):
        def amt(v):
            return self.req("POST", "/payments", raw=b'{"to_handle":"bob","amount":%s}' % v,
                            token=self.ada, key=uuid.uuid4().hex)
        for bad in (b"0", b"-5", b"10.5", b'"100"', b"true", b"false", b"null", b"1000000001",
                    b"[1]", b"{}", b"1e400", b"1e10", b"99999999999999999999999"):
            self.err(amt(bad), 422, "validation_failed")
        for good in (b"1000", b"1000.0", b"1e3"):
            r = amt(good)
            self.assertEqual(r.status, 201, good)
            self.assertEqual(r.json["amount"], 1000)
            self.assertIn(b'"amount": 1000,', r.raw)
        self.err(self.post("/payments", {"to_handle": "bob"}, self.ada), 422, "validation_failed")
        self.reset(fixture(users=[user("ada", 2_000_000_000), user("bob", 0)]))
        ada = self.login("ada")
        self.assertEqual(self.post("/payments", {"to_handle": "bob", "amount": 1000000000}, ada).status, 201)

    def test_self_and_unknown(self):
        self.err(self.post("/payments", {"to_handle": "ada", "amount": 5}, self.ada), 422, "self_payment")
        self.err(self.post("/payments", {"to_handle": "nobody", "amount": 5}, self.ada), 404, "not_found")
        self.err(self.post("/payments", {"to_handle": "BOB", "amount": 5}, self.ada), 404, "not_found")
        self.err(self.post("/payments", {"to_handle": "b o b!", "amount": 5}, self.ada), 404, "not_found")
        self.err(self.post("/payments", {"to_handle": 5, "amount": 5}, self.ada), 400, "malformed_request")
        self.err(self.post("/payments", {"to_handle": None, "amount": 5}, self.ada), 400, "malformed_request")
        self.err(self.post("/payments", {"amount": 5}, self.ada), 422, "validation_failed")
        self.err(self.post("/payments", {"to_handle": "bob", "amount": 5, "note": None}, self.ada), 422,
                 "validation_failed")

    def test_note_rules(self):
        for ok in ("x" * 200, "😀" * 200, "  <b>hi</b> \n\t&amp; ünï ", ""):
            r = self.post("/payments", {"to_handle": "bob", "amount": 1, "note": ok}, self.ada)
            self.assertEqual(r.status, 201)
            self.assertEqual(r.json["note"], ok)
        raw = '{"to_handle":"bob","amount":1,"note":"caf\u00e9 \\ud83d\\ude00"}'.encode("utf-8")
        r = self.req("POST", "/payments", raw=raw, token=self.ada, key="u1")
        self.assertEqual(r.json["note"], "café 😀")
        self.assertIn("café 😀".encode(), r.raw)
        for bad in ("x" * 201, "😀" * 201, 5, True, ["a"], {}):
            self.err(self.post("/payments", {"to_handle": "bob", "amount": 1, "note": bad}, self.ada),
                     422, "validation_failed")

    def test_visibility(self):
        for bad in ("friends", "", None, 1, True, "PUBLIC"):
            self.err(self.post("/payments", {"to_handle": "bob", "amount": 1, "visibility": bad}, self.ada),
                     422, "validation_failed")

    def test_body_types(self):
        for raw in (b"{nope", b"", b"[]", b"5", b'"x"', b"null", b"\xff\xfe"):
            self.err(self.req("POST", "/payments", raw=raw, token=self.ada, key="k"), 400, "malformed_request")

    def test_overspend_parallel(self):
        self.reset(fixture(users=[user("ada", 1000), user("bob", 0)]))
        ada = self.login("ada")
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda _: self.post("/payments", {"to_handle": "bob", "amount": 100}, ada),
                             range(50)))
        self.assertEqual(sorted(r.status for r in rs), [201] * 10 + [409] * 40)
        self.assertEqual((self.bal(ada), self.bal(self.login("bob"))), (0, 1000))

    def test_opposing_transfers(self):
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: self.post("/payments", {"to_handle": "bob" if i % 2 else "ada",
                                                                "amount": 7},
                                                 self.ada if i % 2 else self.bob), range(200)))
        self.assertTrue(all(r.status == 201 for r in rs))
        self.assertEqual(self.total(), 13000)


class TestIdempotency(Base):
    def endpoints(self):
        """(path, body, token, setup) per idempotent path; each succeeds on first use."""
        self.reset(fixture(users=[user("ada", 10000), user("bob", 2500), user("cy", 500)],
                           settlement_operator_ids=["u_ada"],
                           requests=[{"id": "rq_a", "requester_id": "u_bob", "payer_id": "u_ada",
                                      "amount": 100, "note": "", "status": "pending"}]))
        ada = self.ada = self.login("ada")
        self.bob, self.cy = self.login("bob"), self.login("cy")
        return [("/payments", {"to_handle": "bob", "amount": 10}, {"to_handle": "bob", "amount": 11}, ada),
                ("/requests", {"payer_handle": "bob", "amount": 10}, {"payer_handle": "bob", "amount": 11}, ada),
                ("/requests/rq_a/pay", {"visibility": "private"}, {}, ada),
                ("/splits", {"amount": 30, "participant_handles": ["ada", "bob"]},
                 {"amount": 31, "participant_handles": ["ada", "bob"]}, ada),
                ("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 5}]},
                 {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 6}]}, ada)]

    def test_missing_key_all_paths(self):
        for path, body, _, tok in self.endpoints():
            r = self.req("POST", path, body, token=tok)
            self.err(r, 400, "missing_idempotency_key")
            self.err(self.req("POST", path, body, token=tok, key=""), 400, "missing_idempotency_key")

    def test_first_replay_reuse_all_paths(self):
        for path, body, other, tok in self.endpoints():
            first = self.req("POST", path, body, token=tok, key="K1")
            self.assertEqual(first.status, 201, (path, first.raw))
            before = self.total()
            bal = self.bal(tok)
            again = self.req("POST", path, body, token=tok, key="K1")
            self.assertEqual(again.status, 200, path)
            self.assertEqual(again.json, first.json)
            self.assertEqual(self.bal(tok), bal)
            self.err(self.req("POST", path, other, token=tok, key="K1"), 409, "idempotency_key_reuse")
            self.err(self.req("POST", path, {"x": [1]}, token=tok, key="K1"), 409, "idempotency_key_reuse")
            self.assertEqual(self.total(), before)

    def test_concurrent_all_paths(self):
        for path, body, _, tok in self.endpoints():
            before = self.bal(tok)
            with ThreadPoolExecutor(20) as ex:
                rs = list(ex.map(lambda _: self.req("POST", path, body, token=tok, key="CK"), range(20)))
            self.assertEqual(sorted(r.status for r in rs), [200] * 19 + [201], path)
            self.assertTrue(all(r.json == rs[0].json for r in rs))
            self.assertEqual(self.req("POST", path, body, token=tok, key="CK").json, rs[0].json)
            if path == "/payments":
                self.assertEqual(self.bal(tok), before - 10)
            if path == "/settlements":
                self.assertEqual(self.bal(tok), before - 5)

    def test_key_semantics(self):
        a = {"to_handle": "bob", "amount": 10, "note": "n"}
        self.assertEqual(self.req("POST", "/payments", raw=b'{"to_handle":"bob","amount":10,"note":"n"}',
                                  token=self.ada, key="K").status, 201)
        r = self.req("POST", "/payments", raw=b'{ "note" : "n", "amount": 1e1, "to_handle":"bob"}',
                     token=self.ada, key="K")
        self.assertEqual(r.status, 200)
        # unknown extra field -> different JSON value
        self.err(self.req("POST", "/payments", dict(a, extra=1), token=self.ada, key="K"), 409, "idempotency_key_reuse")
        # invalid body with claimed key -> 409 (before field validation)
        self.err(self.req("POST", "/payments", {"amount": "bad"}, token=self.ada, key="K"), 409, "idempotency_key_reuse")
        # per-user scope
        self.assertEqual(self.post("/payments", {"to_handle": "ada", "amount": 10, "note": "n"}, self.bob, key="K").status, 201)
        # same key on another path
        self.assertEqual(self.req("POST", "/requests", {"payer_handle": "bob", "amount": 10}, token=self.ada, key="K").status, 201)

    def test_pay_paths_distinct_and_replay_after_change(self):
        ids = []
        for i in range(2):
            ids.append(self.post("/requests", {"payer_handle": "ada", "amount": 10}, self.bob).json["request_id"])
        a = self.req("POST", "/requests/%s/pay" % ids[0], {}, token=self.ada, key="PK")
        b = self.req("POST", "/requests/%s/pay" % ids[1], {}, token=self.ada, key="PK")
        self.assertEqual((a.status, b.status), (201, 201))
        again = self.req("POST", "/requests/%s/pay" % ids[0], {}, token=self.ada, key="PK")
        self.assertEqual((again.status, again.json), (200, a.json))
        self.err(self.req("POST", "/requests/%s/pay" % ids[0], {"visibility": "public"}, token=self.ada, key="PK"),
                 409, "idempotency_key_reuse")
        # empty body equals {}
        self.assertEqual(self.req("POST", "/requests/%s/pay" % ids[1], token=self.ada, key="PK").status, 200)
        # replay of a successful request after it was cancelled by someone else (resource changed)
        rq = self.post("/requests", {"payer_handle": "ada", "amount": 10}, self.bob, key="CR")
        self.assertEqual(self.req("POST", "/requests/%s/cancel" % rq.json["request_id"], token=self.bob).status, 200)
        self.assertEqual(self.post("/requests", {"payer_handle": "ada", "amount": 10}, self.bob, key="CR").json, rq.json)

    def test_failure_does_not_claim_key(self):
        self.err(self.post("/payments", {"to_handle": "ada", "amount": 600}, self.cy, key="F"), 409, "insufficient_funds")
        self.assertEqual(self.post("/payments", {"to_handle": "ada", "amount": 100}, self.bob, key="Z").status, 201)
        self.assertEqual(self.post("/payments", {"to_handle": "ada", "amount": 600}, self.bob, key="F").status, 201)
        self.assertEqual(self.post("/payments", {"to_handle": "ada", "amount": 600}, self.cy, key="F2").status, 409)
        self.err(self.post("/payments", {"to_handle": "zz", "amount": 1}, self.ada, key="G"), 404, "not_found")
        self.assertEqual(self.post("/payments", {"to_handle": "bob", "amount": 1}, self.ada, key="G").status, 201)
        self.assertEqual(len(self.req("GET", "/activity", token=self.ada).json["payments"]), 3)

    def test_key_length(self):
        body = {"to_handle": "bob", "amount": 1}
        self.assertEqual(self.post("/payments", body, self.ada, key="k" * 255).status, 201)
        self.err(self.post("/payments", body, self.ada, key="k" * 256), 422, "validation_failed")
        self.assertEqual(self.post("/payments", body, self.ada, key="é" * 255).status, 201)
        self.err(self.post("/payments", body, self.ada, key="é" * 256), 422, "validation_failed")

    def test_precedence(self):
        # 401 before 400 missing key; key checked before body parse
        self.err(self.req("POST", "/payments", raw=b"{bad"), 401, "unauthenticated")
        self.err(self.req("POST", "/payments", raw=b"{bad", token=self.ada), 400, "missing_idempotency_key")
        self.err(self.req("POST", "/payments", raw=b"{bad", token=self.ada, key="k" * 300), 422, "validation_failed")
        self.err(self.req("POST", "/payments", raw=b"{bad", token=self.ada, key="a"), 400, "malformed_request")


class TestRequests(Base):
    def ask(self, payer="ada", amount=1200, tok=None, **kw):
        return self.post("/requests", dict({"payer_handle": payer, "amount": amount}, **kw), tok or self.bob)

    def test_create_shape(self):
        r = self.ask(note="taxi")
        self.assertEqual(r.status, 201)
        self.assertEqual(set(r.json), REQUEST_KEYS)
        j = r.json
        self.assertEqual((j["requester_handle"], j["payer_handle"], j["status"], j["payment_id"], j["note"]),
                         ("bob", "ada", "pending", None, "taxi"))
        self.assertRegex(j["created_at"], RFC3339)
        self.assertEqual(self.ask(amount=10 ** 9).status, 201)  # exceeding balance is fine

    def test_create_errors(self):
        self.err(self.ask("bob"), 422, "self_request")
        self.err(self.ask("zz"), 404, "not_found")
        for bad in (0, "5", True, None, 1.5, 10 ** 9 + 1):
            self.err(self.ask(amount=bad), 422, "validation_failed")
        self.err(self.ask(note="x" * 201), 422, "validation_failed")
        self.err(self.ask(note=None), 422, "validation_failed")
        self.err(self.post("/requests", {"payer_handle": 1, "amount": 5}, self.bob), 400, "malformed_request")
        self.err(self.post("/requests", {"amount": 5}, self.bob), 422, "validation_failed")

    def test_pay_flow(self):
        rid = self.ask(amount=1200).json["request_id"]
        r = self.post("/requests/%s/pay" % rid, {"visibility": "private"}, self.ada)
        self.assertEqual(r.status, 201)
        self.assertEqual(set(r.json), PAYMENT_KEYS)
        self.assertEqual((r.json["request_id"], r.json["visibility"], r.json["from_handle"], r.json["to_handle"]),
                         (rid, "private", "ada", "bob"))
        self.assertEqual((self.bal(self.ada), self.bal(self.bob)), (8800, 3700))
        shown = self.req("GET", "/requests?status=paid", token=self.bob).json["requests"][0]
        self.assertEqual((shown["status"], shown["payment_id"]), ("paid", r.json["payment_id"]))
        self.err(self.post("/requests/%s/pay" % rid, {}, self.ada), 409, "request_not_pending")
        # private payment: hidden from third party, visible to both parties
        self.assertEqual(self.req("GET", "/activity", token=self.cy).json["payments"], [])
        for t in (self.ada, self.bob):
            self.assertEqual(self.req("GET", "/activity", token=t).json["payments"][0]["visibility"], "private")

    def test_pay_default_public_and_bad_vis(self):
        rid = self.ask(amount=5).json["request_id"]
        self.err(self.post("/requests/%s/pay" % rid, {"visibility": None}, self.ada), 422, "validation_failed")
        self.err(self.post("/requests/%s/pay" % rid, {"visibility": "x"}, self.ada), 422, "validation_failed")
        self.assertEqual(self.post("/requests/%s/pay" % rid, {}, self.ada).json["visibility"], "public")

    def test_pay_errors(self):
        rid = self.ask(amount=1200, payer="cy").json["request_id"]
        self.err(self.post("/requests/%s/pay" % rid, {}, self.bob), 403, "forbidden")
        self.err(self.post("/requests/%s/pay" % rid, {}, self.ada), 403, "forbidden")
        self.err(self.post("/requests/nope/pay", {}, self.cy), 404, "not_found")
        self.err(self.post("/requests/%s/pay" % rid, {}, self.cy), 409, "insufficient_funds")
        self.assertEqual(self.req("GET", "/requests?status=pending", token=self.cy).json["requests"][0]["status"],
                         "pending")
        self.post("/payments", {"to_handle": "cy", "amount": 700}, self.ada)
        self.assertEqual(self.post("/requests/%s/pay" % rid, {}, self.cy).status, 201)

    def test_decline_cancel(self):
        for action, party, other in (("decline", self.ada, self.bob), ("cancel", self.bob, self.ada)):
            rid = self.ask().json["request_id"]
            self.err(self.req("POST", "/requests/%s/%s" % (rid, action), token=other), 403, "forbidden")
            self.err(self.req("POST", "/requests/%s/%s" % (rid, action), token=self.cy), 403, "forbidden")
            self.err(self.req("POST", "/requests/zz/%s" % action, token=party), 404, "not_found")
            for _ in range(2):
                r = self.req("POST", "/requests/%s/%s" % (rid, action), token=party)
                self.assertEqual(r.status, 200)
                self.assertEqual(r.json["status"], {"decline": "declined", "cancel": "cancelled"}[action])
                self.assertEqual(set(r.json), REQUEST_KEYS)
            self.err(self.post("/requests/%s/pay" % rid, {}, self.ada), 409, "request_not_pending")
            self.err(self.req("POST", "/requests/%s/%s" % (rid, "cancel" if action == "decline" else "decline"),
                              token=self.bob if action == "decline" else self.ada), 409, "request_not_pending")
        rid = self.ask(amount=5).json["request_id"]
        self.post("/requests/%s/pay" % rid, {}, self.ada)
        self.err(self.req("POST", "/requests/%s/cancel" % rid, token=self.bob), 409, "request_not_pending")
        self.err(self.req("POST", "/requests/%s/decline" % rid, token=self.ada), 409, "request_not_pending")

    def test_concurrent_pay_and_decline(self):
        rid = self.ask(amount=100).json["request_id"]

        def act(i):
            if i < 20:
                return self.post("/requests/%s/pay" % rid, {}, self.ada)
            if i < 25:
                return self.req("POST", "/requests/%s/decline" % rid, token=self.ada)
            return self.req("POST", "/requests/%s/cancel" % rid, token=self.bob)
        with ThreadPoolExecutor(30) as ex:
            rs = list(ex.map(act, range(30)))
        final = self.req("GET", "/requests", token=self.bob).json["requests"][0]["status"]
        paid = [r for r in rs[:20] if r.status == 201]
        self.assertEqual(len(paid), 1 if final == "paid" else 0)
        self.assertEqual(self.bal(self.ada), 10000 - (100 if final == "paid" else 0))
        self.assertEqual(self.total(), 13000)

    def test_list_filters_and_paging(self):
        ids = [self.ask(amount=i + 1).json["request_id"] for i in range(5)]
        self.post("/requests", {"payer_handle": "bob", "amount": 3}, self.ada)
        self.post("/requests", {"payer_handle": "cy", "amount": 3}, self.ada)
        out = self.req("GET", "/requests?direction=outgoing", token=self.bob).json["requests"]
        self.assertEqual([r["request_id"] for r in out], ids[::-1])
        self.assertEqual(len(self.req("GET", "/requests", token=self.bob).json["requests"]), 6)
        self.assertEqual(len(self.req("GET", "/requests?direction=incoming", token=self.bob).json["requests"]), 1)
        self.assertEqual(len(self.req("GET", "/requests", token=self.cy).json["requests"]), 1)
        self.req("POST", "/requests/%s/cancel" % ids[0], token=self.bob)
        self.assertEqual(len(self.req("GET", "/requests?status=cancelled", token=self.bob).json["requests"]), 1)
        p = self.req("GET", "/requests?direction=outgoing&limit=2&offset=1", token=self.bob).json
        self.assertEqual([r["request_id"] for r in p["requests"]], ids[::-1][1:3])
        self.assertTrue(p["has_more"])
        p = self.req("GET", "/requests?direction=outgoing&limit=2&offset=3", token=self.bob).json
        self.assertFalse(p["has_more"])
        self.assertEqual(len(p["requests"]), 2)
        self.assertEqual(self.req("GET", "/requests?limit=200&offset=999", token=self.bob).json,
                         {"requests": [], "has_more": False})

    def test_query_validation(self):
        for path in ("/requests", "/activity"):
            for q in ("limit=0", "limit=201", "limit=1e2", "limit=4.0", "limit=%2B4", "limit=-1", "limit=",
                      "limit=abc", "offset=-1", "offset=1.0", "offset=", "offset=x", "limit=%204"):
                self.err(self.req("GET", path + "?" + q, token=self.ada), 422, "validation_failed")
            for q in ("limit=1", "limit=200", "offset=0", "limit=50&offset=5"):
                self.assertEqual(self.req("GET", path + "?" + q, token=self.ada).status, 200)
        for q in ("direction=sideways", "status=open", "direction=", "status=", "direction=INCOMING"):
            self.err(self.req("GET", "/requests?" + q, token=self.ada), 422, "validation_failed")

    def test_requests_never_leak(self):
        self.reset(fixture(settlement_operator_ids=["u_cy"]))
        ada, bob, cy = self.login("ada"), self.login("bob"), self.login("cy")
        self.post("/requests", {"payer_handle": "ada", "amount": 5}, bob)
        self.assertEqual(self.req("GET", "/activity", token=ada).json["payments"], [])
        self.assertEqual(self.req("GET", "/requests", token=cy).json["requests"], [])
        self.err(self.post("/requests/%s/pay" % self.req("GET", "/requests", token=ada).json["requests"][0]["request_id"],
                           {}, cy), 403, "forbidden")


class TestSplits(Base):
    def split(self, amount, handles, tok=None, **kw):
        return self.post("/splits", dict({"amount": amount, "participant_handles": handles}, **kw), tok or self.ada)

    def test_equal_split_table(self):
        users = [user("ada", 10), user("u1", 0), user("u2", 0), user("u3", 0), user("u4", 0)]
        self.reset(fixture(users=users))
        ada = self.login("ada")
        for amount, n, shares in ((1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
                                  (999, 3, [333] * 3), (5, 5, [1] * 5)):
            hs = ["ada", "u1", "u2", "u3", "u4"][:n]
            r = self.split(amount, hs, ada)
            self.assertEqual(r.status, 201, r.raw)
            self.assertEqual([s["amount"] for s in r.json["shares"]], shares)
            self.assertEqual([s["handle"] for s in r.json["shares"]], hs)
            self.assertEqual([q["amount"] for q in r.json["requests"]], shares[1:])
            self.assertEqual([q["payer_handle"] for q in r.json["requests"]], hs[1:])
        r = self.split(10, ["u2", "ada", "u1"], ada)
        self.assertEqual([s["amount"] for s in r.json["shares"]], [4, 3, 3])
        self.assertEqual([q["amount"] for q in r.json["requests"]], [4, 3])

    def test_shape_and_requests_visible(self):
        r = self.split(1200, ["ada", "bob", "cy"], note="dinner")
        j = r.json
        self.assertEqual(set(j), {"split_id", "amount", "currency", "note", "shares", "requests", "created_at"})
        self.assertEqual(len(j["requests"]), 2)
        self.assertTrue(all(q["requester_handle"] == "ada" and q["status"] == "pending" and q["note"] == "dinner"
                            and set(q) == REQUEST_KEYS for q in j["requests"]))
        self.assertEqual(len(self.req("GET", "/requests", token=self.bob).json["requests"]), 1)
        self.assertEqual(self.req("GET", "/activity", token=self.bob).json["payments"], [])
        for q in j["requests"]:
            tok = self.bob if q["payer_handle"] == "bob" else self.cy
            self.assertEqual(self.post("/requests/%s/pay" % q["request_id"], {}, tok).status, 201)
        self.assertEqual(self.total(), 13000)

    def test_only_caller_and_zero_share(self):
        r = self.split(77, ["ada"])
        self.assertEqual((r.status, r.json["requests"], r.json["shares"]), (201, [], [{"handle": "ada", "amount": 77}]))
        r = self.split(1, ["bob", "ada", "cy"])
        self.assertEqual([q["amount"] for q in r.json["requests"]], [1, 0])

    def test_errors(self):
        self.err(self.split(10, []), 422, "validation_failed")
        self.err(self.split(10, ["bob", "bob"]), 422, "validation_failed")
        self.err(self.split(10, ["bob", "zz"]), 404, "not_found")
        self.assertEqual(self.req("GET", "/requests", token=self.bob).json["requests"], [])
        for bad in (0, "5", True, None, 2.5):
            self.err(self.split(bad, ["bob"]), 422, "validation_failed")
        self.err(self.split(10, ["bob"], note="x" * 201), 422, "validation_failed")
        self.err(self.post("/splits", {"amount": 10}, self.ada), 422, "validation_failed")
        self.err(self.split(10, "bob"), 400, "malformed_request")
        self.err(self.split(10, ["bob", 5]), 400, "malformed_request")
        self.err(self.split(10, None), 400, "malformed_request")

    def test_many_handles(self):
        r = self.split(10, ["h%d" % i for i in range(1000)])
        self.err(r, 404, "not_found")
        r = self.split(10, ["bob"] + ["h%d" % i for i in range(1000)])
        self.err(r, 404, "not_found")


class TestActivity(Base):
    def test_visibility_rules(self):
        self.post("/payments", {"to_handle": "bob", "amount": 1, "note": "pub"}, self.ada)
        self.post("/payments", {"to_handle": "bob", "amount": 2, "note": "priv", "visibility": "private"}, self.ada)
        self.post("/payments", {"to_handle": "cy", "amount": 3, "note": "priv2", "visibility": "private"}, self.bob)

        def notes(t):
            return [p["note"] for p in self.req("GET", "/activity", token=t).json["payments"]]
        self.assertEqual(notes(self.ada), ["priv", "pub"])
        self.assertEqual(notes(self.bob), ["priv2", "priv", "pub"])
        self.assertEqual(notes(self.cy), ["priv2", "pub"])
        for t in (self.ada, self.bob, self.cy):
            for p in self.req("GET", "/activity", token=t).json["payments"]:
                self.assertEqual(set(p), PAYMENT_KEYS)

    def test_paging(self):
        for i in range(5):
            self.post("/payments", {"to_handle": "bob", "amount": i + 1}, self.ada)
        r = self.req("GET", "/activity?limit=2&offset=1&direction=x", token=self.ada).json
        self.assertEqual([p["amount"] for p in r["payments"]], [4, 3])
        self.assertTrue(r["has_more"])
        r = self.req("GET", "/activity?limit=2&offset=3", token=self.ada).json
        self.assertEqual(([p["amount"] for p in r["payments"]], r["has_more"]), ([2, 1], False))


class TestSettlements(Base):
    def setUp(self):
        self.reset(fixture(users=[user("ada", 100), user("bob", 0), user("cy", 0), user("dee", 50)],
                           settlement_operator_ids=["u_dee"]))
        self.ada, self.bob, self.cy, self.dee = (self.login(h) for h in ("ada", "bob", "cy", "dee"))

    def settle(self, transfers, tok=None, key=None):
        return self.post("/settlements", {"transfers": transfers}, tok or self.dee, key=key)

    @staticmethod
    def t(f, to, amount, **kw):
        return dict({"from_handle": f, "to_handle": to, "amount": amount}, **kw)

    def test_permissions(self):
        self.err(self.req("POST", "/settlements", {"transfers": []}, key="k"), 401, "unauthenticated")
        self.err(self.settle([self.t("ada", "bob", 1)], self.ada), 403, "forbidden")
        self.err(self.req("POST", "/settlements", {"transfers": [self.t("ada", "bob", 1)]}, token=self.dee),
                 400, "missing_idempotency_key")

    def test_net_affordability_and_shape(self):
        r = self.settle([self.t("ada", "bob", 100, note="n1"), self.t("bob", "cy", 100, visibility="private"),
                         self.t("cy", "ada", 10, extra="ignored")])
        self.assertEqual(r.status, 201, r.raw)
        j = r.json
        self.assertEqual(set(j), {"settlement_id", "committed_at", "payments"})
        self.assertRegex(j["committed_at"], RFC3339)
        self.assertEqual([p["amount"] for p in j["payments"]], [100, 100, 10])
        for p in j["payments"]:
            self.assertEqual(set(p), PAYMENT_KEYS)
            self.assertEqual((p["settlement_id"], p["request_id"], p["created_at"]),
                             (j["settlement_id"], None, j["committed_at"]))
        self.assertEqual([p["note"] for p in j["payments"]], ["n1", "", ""])
        self.assertEqual([p["visibility"] for p in j["payments"]], ["public", "private", "public"])
        self.assertEqual((self.bal(self.ada), self.bal(self.bob), self.bal(self.cy)), (10, 0, 90))
        # operator dee is a party to none: sees only the public ones
        vis = self.req("GET", "/activity", token=self.dee).json["payments"]
        self.assertEqual(sorted(p["amount"] for p in vis), [10, 100])
        self.assertEqual({p["settlement_id"] for p in vis}, {j["settlement_id"]})
        self.assertEqual(len(self.req("GET", "/activity", token=self.bob).json["payments"]), 3)
        self.assertEqual(self.req("GET", "/requests", token=self.dee).json["requests"], [])

    def test_insufficient_and_atomic(self):
        self.err(self.settle([self.t("ada", "bob", 50), self.t("bob", "cy", 60)]), 409, "insufficient_funds")
        self.err(self.settle([self.t("ada", "bob", 101)]), 409, "insufficient_funds")
        self.assertEqual((self.bal(self.ada), self.bal(self.bob)), (100, 0))
        self.assertEqual(self.req("GET", "/activity", token=self.ada).json["payments"], [])
        # a failed settlement claims no key
        self.assertEqual(self.settle([self.t("ada", "bob", 50)], key="same").status, 201)

    def test_entry_error_precedence(self):
        self.err(self.settle([self.t("ada", "bob", 500), self.t("ada", "zz", 1)]), 404, "not_found")
        self.err(self.settle([self.t("ada", "bob", 500), self.t("ada", "ada", 1)]), 422, "self_payment")
        self.err(self.settle([self.t("ada", "zz", 1), self.t("ada", "bob", 0)]), 404, "not_found")
        self.err(self.settle([self.t("ada", "bob", 0), self.t("ada", "zz", 1)]), 422, "validation_failed")
        self.err(self.settle([self.t("ada", "bob", 1, note=None)]), 422, "validation_failed")
        self.err(self.settle([self.t("ada", "bob", 1, visibility="x")]), 422, "validation_failed")
        self.err(self.settle([self.t("ada", "bob", "1")]), 422, "validation_failed")
        self.err(self.settle([self.t("ada", "bob", True)]), 422, "validation_failed")
        self.assertEqual(self.bal(self.ada), 100)

    def test_batch_shape(self):
        ok = self.t("ada", "bob", 1)
        for bad in (None, "x", {}, [], [ok] * 33, [ok, 5], [None], [[]]):
            self.err(self.post("/settlements", {} if bad is None else {"transfers": bad}, self.dee), 422,
                     "validation_failed")
        self.assertEqual(self.settle([ok] * 32).status, 201)
        self.err(self.post("/settlements", [1], self.dee), 400, "malformed_request")

    def test_replay_and_concurrency(self):
        body = [self.t("ada", "bob", 10)]
        a = self.settle(body, key="S")
        b = self.settle(body, key="S")
        self.assertEqual((a.status, b.status, a.json), (201, 200, b.json))
        self.err(self.settle([self.t("ada", "bob", 11)], key="S"), 409, "idempotency_key_reuse")
        self.assertEqual(self.bal(self.ada), 90)

    def test_concurrent_with_payments_conserves(self):
        def work(i):
            if i % 3 == 0:
                return self.settle([self.t("ada", "bob", 3), self.t("bob", "cy", 2)])
            if i % 3 == 1:
                return self.post("/payments", {"to_handle": "ada", "amount": 2}, self.bob)
            return self.post("/payments", {"to_handle": "cy", "amount": 2}, self.ada)
        with ThreadPoolExecutor(40) as ex:
            rs = list(ex.map(work, range(120)))
        self.assertTrue(all(r.status in (201, 409) for r in rs))
        self.assertEqual(sum(self.bal(t) for t in (self.ada, self.bob, self.cy, self.dee)), 150)


class TestExportImport(Base):
    def populate(self):
        self.reset(fixture(settlement_operator_ids=["u_ada"],
                           requests=[{"id": "rq_s", "requester_id": "u_bob", "payer_id": "u_ada",
                                      "amount": 100, "note": "", "status": "pending"}]))
        self.ada, self.bob, self.cy = (self.login(h) for h in ("ada", "bob", "cy"))
        self.sig = Base.sig_calls = {}
        s = self.sig
        s["pay"] = self.req("POST", "/payments", {"to_handle": "bob", "amount": 10, "note": "é"}, token=self.ada, key="P")
        s["req"] = self.req("POST", "/requests", {"payer_handle": "cy", "amount": 9}, token=self.bob, key="R")
        s["payreq"] = self.req("POST", "/requests/rq_s/pay", {"visibility": "private"}, token=self.ada, key="PR")
        s["split"] = self.req("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "bob"]}, token=self.ada, key="SP")
        s["settle"] = self.req("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 5}]},
                               token=self.ada, key="ST")
        self.err(self.req("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 6}, token=self.cy, key="FAILED"),
                 409, "insufficient_funds")
        for r in s.values():
            self.assertEqual(r.status, 201, r.raw)
        self.snapshot = {t: (self.req("GET", "/me", token=tok).json, self.req("GET", "/activity", token=tok).json,
                             self.req("GET", "/requests", token=tok).json)
                         for t, tok in (("ada", self.ada), ("bob", self.bob), ("cy", self.cy))}

    def test_roundtrip(self):
        self.populate()
        exp = self.req("GET", "/_test/export")
        self.assertEqual(exp.status, 200)
        self.assertEqual((exp.json["track"], exp.json["format_version"]), ("pocketful", 1))
        self.assertIsInstance(exp.json["state"], dict)
        self.assertNotIn(b"correct horse", exp.raw)
        # mutate, reset to something else
        self.post("/payments", {"to_handle": "bob", "amount": 1}, self.ada)
        self.reset(fixture(users=[user("zed", 5)]))
        zed = self.login("zed")
        for _ in range(2):
            self.assertEqual(self.req("POST", "/_test/import", raw=exp.raw).status, 204)
            snap = {t: (self.req("GET", "/me", token=tok).json, self.req("GET", "/activity", token=tok).json,
                        self.req("GET", "/requests", token=tok).json)
                    for t, tok in (("ada", self.ada), ("bob", self.bob), ("cy", self.cy))}
            self.assertEqual(snap, self.snapshot)
        self.err(self.req("GET", "/me", token=zed), 401, "unauthenticated")
        self.assertEqual(self.bal(self.login("ada")), self.snapshot["ada"][0]["balance"])
        s = self.sig
        for path, body, tok, key in (
                ("/payments", {"to_handle": "bob", "amount": 10, "note": "é"}, self.ada, "P"),
                ("/requests", {"payer_handle": "cy", "amount": 9}, self.bob, "R"),
                ("/requests/rq_s/pay", {"visibility": "private"}, self.ada, "PR"),
                ("/splits", {"amount": 10, "participant_handles": ["ada", "bob"]}, self.ada, "SP"),
                ("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 5}]}, self.ada, "ST")):
            r = self.req("POST", path, body, token=tok, key=key)
            self.assertEqual(r.status, 200, path)
            name = {"/payments": "pay", "/requests": "req", "/requests/rq_s/pay": "payreq",
                    "/splits": "split", "/settlements": "settle"}[path]
            self.assertEqual(r.json, s[name].json)
            self.err(self.req("POST", path, {"amount": 12345}, token=tok, key=key), 409, "idempotency_key_reuse")
        self.assertEqual(self.bal(self.ada), self.snapshot["ada"][0]["balance"])
        # failed key still reusable
        self.assertEqual(self.req("POST", "/payments", {"to_handle": "ada", "amount": 1}, token=self.cy, key="FAILED").status, 201)
        # reset clears imported state
        self.reset()
        self.err(self.req("GET", "/me", token=self.ada), 401, "unauthenticated")
        self.assertEqual(self.req("GET", "/activity", token=self.login("ada")).json["payments"], [])

    def test_export_is_snapshot_and_import_validation(self):
        self.populate()
        exp = self.req("GET", "/_test/export")
        self.post("/payments", {"to_handle": "bob", "amount": 1}, self.ada)
        self.assertEqual(self.req("POST", "/_test/import", raw=exp.raw).status, 204)
        self.assertEqual(len(self.req("GET", "/activity", token=self.ada).json["payments"]),
                         len(self.snapshot["ada"][1]["payments"]))
        self.err(self.req("POST", "/_test/import", raw=b"{bad"), 400, "malformed_request")
        doc = exp.json
        for bad in ({}, {"track": "pocketful", "format_version": 1}, dict(doc, track="x"),
                    dict(doc, format_version=2), dict(doc, state=5), dict(doc, state={}),
                    dict(doc, state=dict(doc["state"], users={"u": 1})),
                    dict(doc, state=dict(doc["state"], seeded_total=1)),
                    dict(doc, state=dict(doc["state"], tokens={"t": "nobody"})),
                    [], 5):
            self.err(self.req("POST", "/_test/import", bad), 422 if isinstance(bad, dict) else 400,
                     "validation_failed" if isinstance(bad, dict) else "malformed_request")
        self.assertEqual(self.bal(self.ada), self.snapshot["ada"][0]["balance"])

    def test_import_into_fresh_process(self):
        self.populate()
        exp = self.req("GET", "/_test/export")
        port = free_port()
        p = subprocess.Popen([sys.executable, "-m", "app"], cwd=ROOT, env=dict(os.environ, PORT=str(port)))
        try:
            for _ in range(100):
                try:
                    call(port, "GET", "/health")
                    break
                except OSError:
                    time.sleep(0.1)
            self.assertEqual(call(port, "POST", "/_test/import", raw=exp.raw).status, 204)
            self.assertEqual(call(port, "GET", "/me", token=self.ada).json, self.snapshot["ada"][0])
            self.assertEqual(call(port, "POST", "/payments", {"to_handle": "bob", "amount": 10, "note": "é"},
                                  token=self.ada, key="P").status, 200)
            self.assertEqual(call(port, "POST", "/auth/login", {"email": "ada@example.com",
                                                                 "password": "correct horse"}).status, 200)
        finally:
            p.terminate()
            p.wait()

    def test_consistent_under_load_and_timing(self):
        users = [user("u%d" % i, 1000) for i in range(50)]
        self.reset(fixture(users=users))
        toks = [self.login("u%d" % i) for i in range(5)]
        stop = threading.Event()
        errors = []

        def writer(n):
            i = 0
            while not stop.is_set():
                i += 1
                r = self.post("/payments", {"to_handle": "u%d" % ((n + i) % 50 or 1), "amount": 3},
                              toks[n]) if (n + i) % 50 != n else None
                if r is not None and r.status >= 500:
                    errors.append(r.status)
        ts = [threading.Thread(target=writer, args=(n,)) for n in range(5)]
        [t.start() for t in ts]
        exports = []
        for _ in range(5):
            exports.append(self.req("GET", "/_test/export").raw)
            time.sleep(0.05)
        stop.set()
        [t.join() for t in ts]
        self.assertEqual(errors, [])
        for raw in exports:
            doc = json.loads(raw)
            self.assertEqual(sum(u["balance"] for u in doc["state"]["users"].values()), 50000)
            self.assertEqual(self.req("POST", "/_test/import", raw=raw).status, 204)
        # populated state: thousands of records within the 10 s budget
        big = fixture(users=users, payments=[{"id": "p%d" % i, "from_user_id": "u_u0", "to_user_id": "u_u1",
                                              "amount": 1, "note": "n"} for i in range(5000)])
        t0 = time.time()
        self.reset(big)
        raw = self.req("GET", "/_test/export").raw
        self.assertEqual(self.req("POST", "/_test/import", raw=raw).status, 204)
        self.assertLess(time.time() - t0, 10)


class TestMisc(Base):
    def test_ids_and_seeded_ids(self):
        self.assertEqual(self.req("GET", "/me", token=self.ada).json["user_id"], "u_ada")
        r = self.post("/payments", {"to_handle": "bob", "amount": 1}, self.ada).json
        self.assertTrue(r["payment_id"] and len(r["payment_id"]) <= 64)
        self.reset(fixture(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5}]))
        ada = self.login("ada")
        ids = {self.post("/payments", {"to_handle": "bob", "amount": 1}, ada).json["payment_id"] for _ in range(3)}
        self.assertNotIn("p_1", ids)
        self.assertEqual(len(ids), 3)

    def test_fuzz_no_5xx(self):
        values = [None, True, False, 0, -1, 1.5, "", "x", "ada", [], [None], {}, {"a": 1}, 10 ** 30, 1e400]
        fields = ["to_handle", "payer_handle", "amount", "note", "visibility", "participant_handles",
                  "transfers", "email", "password", "display_name"]
        paths = ["/payments", "/requests", "/splits", "/settlements", "/requests/x/pay", "/auth/signup",
                 "/auth/login"]
        self.reset(fixture(settlement_operator_ids=["u_ada"]))
        ada = self.login("ada")
        n = 0
        for path in paths:
            for f in fields:
                for v in values:
                    body = json.dumps({f: v}).replace("1e400", "1e400").encode()
                    r = self.req("POST", path, raw=body, token=ada, key="fuzz%d" % n)
                    n += 1
                    self.assertLess(r.status, 500, (path, f, v, r.raw))
                    if r.status >= 400:
                        self.assertIn("error", r.json)
        for path in ("/payments", "/requests", "/splits", "/settlements", "/auth/login", "/_test/reset", "/_test/import"):
            for raw in (b"", b"{", b"[[[[[[[[[[[[[[[[" * 5000, b"\x00", b'{"a":NaN}', b'{"amount":Infinity}'):
                r = self.req("POST", path, raw=raw, token=ada, key="x")
                self.assertLess(r.status, 500, (path, raw[:20]))
        self.assertEqual(self.bal(ada), 10000)

    def test_load_50_in_flight(self):
        def hit(i):
            if i % 2:
                return self.post("/payments", {"to_handle": "bob", "amount": 1}, self.ada)
            return self.req("GET", "/activity", token=self.bob)
        t0 = time.time()
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(hit, range(500)))
        self.assertTrue(all(r.status < 500 for r in rs))
        self.assertLess(time.time() - t0, 30)
        self.assertEqual(self.total(), 13000)


class TestRegressions(Base):
    def test_login_racing_reset_never_leaks_or_5xx(self):
        for rnd in range(30):
            self.reset({"users": [user("a", 1, id="u1", email="a@x.io", password="passwordA")]})
            other = {"users": [user("b", 2, id="u1" if rnd % 2 else "zz", email="b@x.io", password="passwordB")]}
            with ThreadPoolExecutor(8) as ex:
                logins = [ex.submit(self.req, "POST", "/auth/login", {"email": "a@x.io", "password": "passwordA"})
                          for _ in range(6)]
                time.sleep(0.004)
                rs = ex.submit(self.req, "POST", "/_test/reset", other)
                self.assertEqual(rs.result().status, 204)
                results = [f.result() for f in logins]
            for r in results:
                self.assertLess(r.status, 500)
                if r.status == 200:
                    me = self.req("GET", "/me", token=r.json["token"])
                    self.assertEqual(me.status, 401, me.raw)
                    self.assertEqual(self.req("POST", "/payments", {"to_handle": "b", "amount": 1},
                                              token=r.json["token"], key="k").status, 401)

    def test_login_overlapping_import_or_reset_of_same_account_succeeds(self):
        exp = self.req("GET", "/_test/export").raw
        for rnd in range(15):
            with ThreadPoolExecutor(8) as ex:
                logins = [ex.submit(self.req, "POST", "/auth/login",
                                    {"email": "ada@example.com", "password": "correct horse"}) for _ in range(4)]
                time.sleep(0.003)
                if rnd % 2:
                    imp = ex.submit(self.req, "POST", "/_test/import", raw=exp)
                else:
                    imp = ex.submit(self.req, "POST", "/_test/reset", fixture())
                self.assertEqual(imp.result().status, 204)
                results = [f.result() for f in logins]
            for r in results:
                self.assertEqual(r.status, 200, r.raw)

    def test_overlong_numbers_compare_by_value_for_idempotency(self):
        def body(x):
            return b'{"to_handle":"bob","amount":1,"x":' + x + b"}"
        big1, big2 = b"1" + b"0" * 4300, b"1" + b"0" * 4299 + b"1"
        for i, (a, b, same) in enumerate(((big1, big2, False), (b"1e400", b"2e400", False),
                                          (b"1e400", b"10e399", True), (b"1e-400", b"2e-400", False),
                                          (b"1e999999999999999999999", b"1e999999999999999999998", False))):
            key = "big%d" % i
            self.assertEqual(self.req("POST", "/payments", raw=body(a), token=self.ada, key=key).status, 201)
            self.assertEqual(self.req("POST", "/payments", raw=body(a), token=self.ada, key=key).status, 200)
            r = self.req("POST", "/payments", raw=body(b), token=self.ada, key=key)
            if same:
                self.assertEqual(r.status, 200)
            else:
                self.err(r, 409, "idempotency_key_reuse")
        self.assertEqual(self.req("POST", "/_test/import", raw=self.req("GET", "/_test/export").raw).status, 204)

    def test_authenticated_write_racing_reset_is_never_applied_to_new_state(self):
        for rnd in range(15):
            self.reset()
            old = self.login("ada")
            with ThreadPoolExecutor(10) as ex:
                writes = [ex.submit(self.req, "POST", "/payments", {"to_handle": "bob", "amount": 1},
                                    token=old, key="w%d" % i) for i in range(8)]
                reads = [ex.submit(self.req, "GET", "/me", token=old) for _ in range(4)]
                time.sleep(0.002)
                self.assertEqual(ex.submit(self.req, "POST", "/_test/reset", fixture()).result().status, 204)
                rs = [f.result() for f in writes + reads]
            self.assertTrue(all(r.status in (200, 201, 401) for r in rs))
            fresh = self.login("ada")
            self.assertEqual(self.bal(fresh), 10000)
            self.assertEqual(self.req("GET", "/activity", token=fresh).json["payments"], [])
            self.err(self.req("GET", "/me", token=old), 401, "unauthenticated")

    def test_export_is_strict_json_after_overlong_numbers(self):
        def strict(raw):
            def refuse(c):
                raise AssertionError("non-JSON constant " + c)
            return json.loads(raw, parse_constant=refuse)
        bodies = {}
        for i, x in enumerate((b"1" + b"0" * 4300, b"1e400", b"-1e999", b"1e-400")):
            bodies[i] = b'{"to_handle":"bob","amount":1,"x":' + x + b"}"
            self.assertEqual(self.req("POST", "/payments", raw=bodies[i], token=self.ada, key="s%d" % i).status, 201)
        exp = self.req("GET", "/_test/export")
        strict(exp.raw)
        self.assertEqual(self.req("POST", "/_test/import", raw=exp.raw).status, 204)
        strict(self.req("GET", "/_test/export").raw)
        for i, raw in bodies.items():
            self.assertEqual(self.req("POST", "/payments", raw=raw, token=self.ada, key="s%d" % i).status, 200)
            changed = raw.replace(b'"amount":1,', b'"amount":2,')
            self.err(self.req("POST", "/payments", raw=changed, token=self.ada, key="s%d" % i), 409,
                     "idempotency_key_reuse")
        for path in ("/activity", "/requests", "/me"):
            strict(self.req("GET", path, token=self.ada).raw)

    def test_login_retry_budget_exhausted_still_answers_correctly(self):
        sys.path.insert(0, ROOT)
        from app import service as svc_mod
        svc = svc_mod.Service()
        fx = fixture()
        svc.reset(fx)
        real = svc_mod.verify_password
        calls = []

        def churn(password, record):
            ok = real(password, record)
            if not svc.lock._is_owned():
                calls.append(1)
                svc.reset(fx)  # replace the state while the login is hashing
            return ok
        svc_mod.verify_password = churn
        try:
            good = svc.login({"email": "ada@example.com", "password": "correct horse"})
            self.assertEqual(good["user_id"], "u_ada")
            self.assertGreaterEqual(len(calls), 3)
            with self.assertRaises(svc_mod.ApiError) as cm:
                svc.login({"email": "ada@example.com", "password": "wrong password"})
            self.assertEqual(cm.exception.status, 401)
        finally:
            svc_mod.verify_password = real

    def test_numbers_compare_by_exact_value_for_idempotency(self):
        zeros = lambda d, n: d + b"0" * n
        cases = [(zeros(b"1", 4300), zeros(b"2", 4300), False), (b"1" * 4001, b"1" * 4002, False),
                 (b"1e400", b"1e500", False), (zeros(b"1", 4300), b"1e4300", True),
                 (b"9007199254740993", b"9007199254740993.0", True), (b"1" * 3999, b"1" * 3998 + b"2", False),
                 (b"10", b"1e1", True), (b"true", b"1", False), (b"-0", b"0", True), (b"0e5", b"-0.0", True),
                 (b"0.1", b"0.1000000000000000055511151231257827", False), (b"1", b"1.0000000000000001", False),
                 (b"1e1", b"10.0", True), (b"1.0e+1", b"10", True),
                 (b"1e999999999", b"1e999999998", False), (b"1e999999999", b"10e999999998", True),
                 (b"1e999999999999999999999999999", b"1e999999999999999999999999998", False),
                 (b"-1e999", b"1e999", False), (b"1e-400", b"2e-400", False), (b"[1.0]", b"[1]", True)]
        for i, (a, b, same) in enumerate(cases):
            key = "n%d" % i
            raw = lambda x: b'{"to_handle":"bob","amount":1,"x":' + x + b"}"
            t0 = time.time()
            self.assertEqual(self.req("POST", "/payments", raw=raw(a), token=self.ada, key=key).status, 201, a[:20])
            r = self.req("POST", "/payments", raw=raw(b), token=self.ada, key=key)
            if same:
                self.assertEqual(r.status, 200, (a[:20], b[:20]))
            else:
                self.err(r, 409, "idempotency_key_reuse")
            self.assertLess(time.time() - t0, 2)
        big = b"1" + b"7" * 400000 + b".5"  # huge literal stays fast
        t0 = time.time()
        self.assertEqual(self.req("POST", "/payments", raw=b'{"to_handle":"bob","amount":1,"x":' + big + b"}",
                                  token=self.ada, key="huge").status, 201)
        self.assertLess(time.time() - t0, 3)
        self.assertEqual(self.req("POST", "/_test/import", raw=self.req("GET", "/_test/export").raw).status, 204)

    def test_amount_is_valid_iff_exact_integer_in_range(self):
        self.reset(fixture(users=[user("ada", 5 * 10 ** 9), user("bob", 0)]))
        ada = self.login("ada")
        for lit, ok in ((b"0.9999999999999999999999", False), (b"1000000000.0", True), (b"1e3", True),
                        (b"1000.0", True), (b"10.5", False), (b"1e400", False), (b"1.0000000000000000001", False),
                        (b"1000000000.0000000000000001", False), (b"1000000001.0", False), (b"0.0", False),
                        (b"100e-2", True), (b"1e-0", True)):
            r = self.req("POST", "/payments", raw=b'{"to_handle":"bob","amount":' + lit + b"}", token=ada,
                         key=uuid.uuid4().hex)
            self.assertEqual(r.status, 201 if ok else 422, lit)
        fx = fixture(users=[user("ada", 10000.0), user("bob", 1e3)])
        raw = json.dumps(fx)
        self.assertEqual(self.req("POST", "/_test/reset", raw=raw.encode()).status, 204)
        self.assertEqual(self.bal(self.login("ada")), 10000)
        self.err(self.req("POST", "/_test/reset", raw=json.dumps(fixture(users=[user("a", 1.5)])).encode()),
                 422, "validation_failed")

    MiB = 1024 * 1024

    def shapes(self):
        base = b'{"to_handle":"bob","amount":1,"x":'
        n = self.MiB - len(base) - 1 - 16
        return {"one number of ~1M digits": base + b"9" * n + b"}",
                "500k small numbers": base + b"[" + b"1," * (n // 2 - 2) + b"1]}",
                "350k empty arrays": base + b"[" + b"[]," * (n // 3 - 2) + b"[]]}",
                "nesting to depth 9000": base + b"[" * 9000 + b"]" * 9000 + b"}",
                "1 MiB string": base + b'"' + b"z" * (n - 2) + b'"}'}

    def test_one_mib_bodies_answer_fast_and_never_block_others(self):
        shapes = self.shapes()
        for name, raw in shapes.items():
            self.assertLessEqual(len(raw), self.MiB, name)
            t0 = time.time()
            r = self.req("POST", "/payments", raw=raw, token=self.ada, key="alone-" + name)
            self.assertEqual(r.status, 201, (name, r.raw[:80]))
            self.assertLess(time.time() - t0, 1.0, name)
            self.assertEqual(self.req("POST", "/payments", raw=raw, token=self.ada,
                                      key="alone-" + name).status, 200)
        stop, worst = [], [0.0]

        def poll():
            while not stop:
                t0 = time.time()
                self.assertEqual(self.req("GET", "/me", token=self.ada).status, 200)
                worst[0] = max(worst[0], time.time() - t0)
                time.sleep(0.005)
        with ThreadPoolExecutor(10) as ex:
            watcher = ex.submit(poll)
            jobs = [ex.submit(self.req, "POST", "/payments", raw=shapes[name], token=self.ada,
                              key="conc-%d" % i)
                    for i, name in enumerate(list(shapes) * 2)][:8]
            results = [j.result() for j in jobs]
            stop.append(1)
            watcher.result()
        self.assertTrue(all(r.status == 201 for r in results))
        print("worst GET /me latency during 8 concurrent 1 MiB bodies: %.3fs" % worst[0])
        self.assertLess(worst[0], 0.5)

    def test_oversize_bodies_get_413(self):
        base = b'{"to_handle":"bob","amount":1,"x":'
        r = self.req("POST", "/payments", raw=base + b"9" * (self.MiB + 10) + b"}", token=self.ada, key="o1")
        self.err(r, 413, "payload_too_large")
        for cl in ("99999999", "9" * 2000, "9" * 5000):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            conn.putrequest("POST", "/payments")
            conn.putheader("Content-Length", cl)
            conn.putheader("Authorization", "Bearer " + self.ada)
            conn.putheader("Idempotency-Key", "cl")
            conn.endheaders()
            resp = conn.getresponse()
            self.assertIn(resp.status, (400, 413), cl)
            json.loads(resp.read())
            conn.close()
        self.assertEqual(self.req("GET", "/health").status, 200)

    def test_reset_and_import_bounds(self):
        # a document of tiny values beyond the value bound is refused without exhausting memory
        raw = b'{"users":[],"zz":[' + b"1," * 3_100_000 + b"1]}"
        self.err(self.req("POST", "/_test/reset", raw=raw), 422, "validation_failed")
        self.err(self.req("POST", "/_test/import", raw=raw), 422, "validation_failed")
        # a large but acceptable fixture still works, and unknown values are not stored
        fx = fixture()
        fx["junk"] = [1] * 1_000_000
        self.assertEqual(self.req("POST", "/_test/reset", fx).status, 204)
        self.assertNotIn(b"junk", self.req("GET", "/_test/export").raw)

    def test_import_rejects_numbers_that_cannot_round_trip(self):
        import copy as cp
        self.post("/payments", {"to_handle": "bob", "amount": 5, "note": "n"}, self.ada, key="k1")
        self.post("/splits", {"amount": 10, "participant_handles": ["ada", "bob"], "note": "s"}, self.ada, key="k2")
        exp = self.req("GET", "/_test/export").raw.decode()
        doc = json.loads(exp)
        targets = [("splits", 0, "note"), ("payments", 0, "extra"), (None, None, "extra"),
                   ("idem", 0, "response")]
        for lit in ("1e400", "-1e999", "1" + "0" * 4300):
            for where, idx, field in targets:
                d = cp.deepcopy(doc)
                holder = d["state"] if where is None else d["state"][where][idx]
                if field == "response":
                    holder = holder["response"]
                    field = "note"
                holder[field] = "@@"
                text = json.dumps(d).replace('"@@"', lit)
                r = self.req("POST", "/_test/import", raw=text.encode())
                self.err(r, 422, "validation_failed")
        self.assertEqual(self.req("GET", "/_test/export").raw.decode(), exp)
        # closed schema: even an ordinary finite number in an unknown field is refused
        d = cp.deepcopy(doc)
        d["state"]["extra"] = 1.5
        self.err(self.req("POST", "/_test/import", d), 422, "validation_failed")
        self.assertEqual(self.req("GET", "/_test/export").raw.decode(), exp)
        # the unchanged export imports and re-exports byte-identically; replay still works
        self.assertEqual(self.req("POST", "/_test/import", raw=exp.encode()).status, 204)
        self.assertEqual(self.req("GET", "/_test/export").raw.decode(), exp)
        self.assertEqual(self.req("POST", "/payments", {"to_handle": "bob", "amount": 5, "note": "n"},
                                  token=self.ada, key="k1").status, 200)

    def test_import_closed_schema_unknown_keys_and_types_at_every_level(self):
        import copy as cp
        self.populate()
        doc = self.req("GET", "/_test/export").json
        exp = self.req("GET", "/_test/export").raw
        s = doc["state"]
        paths = [[], ["users", "u_ada"], ["users", "u_ada", "pw"], ["payments", 0], ["requests", 0],
                 ["splits", 0], ["settlements", 0], ["idem", 0], ["idem", 0, "response"], ["counters"]]
        for i, entry in enumerate(s["idem"]):
            if entry["response"].get("requests"):
                paths.append(["idem", i, "response", "requests", 0])
            if entry["response"].get("payments"):
                paths.append(["idem", i, "response", "payments", 0])
        for path in paths:
            d = cp.deepcopy(doc)
            node = d["state"]
            for step in path:
                node = node[step]
            node["unknown_key"] = 1
            self.err(self.req("POST", "/_test/import", d), 422, "validation_failed")
        wrong = [(["users", "u_ada", "balance"], "5"), (["users", "u_ada", "balance"], 5.5),
                 (["payments", 0, "amount"], True), (["payments", 0, "ts"], "x"),
                 (["seq"], None), (["idem", 0, "body"], 5), (["idem", 0, "response", "amount"], "1"),
                 (["counters", "payment"], 1.5)]
        for path, val in wrong:
            d = cp.deepcopy(doc)
            node = d["state"]
            for step in path[:-1]:
                node = node[step]
            node[path[-1]] = val
            self.err(self.req("POST", "/_test/import", d), 422, "validation_failed")
        self.assertEqual(self.req("GET", "/_test/export").raw, exp)

    def test_export_import_export_identical_after_all_five_paths(self):
        self.populate()
        exp = self.req("GET", "/_test/export").raw
        self.assertEqual(self.req("POST", "/_test/import", raw=exp).status, 204)
        self.assertEqual(self.req("GET", "/_test/export").raw, exp)

    def test_deep_nesting_unknown_field(self):
        for depth in (10, 950, 1000, 5000):
            raw = b'{"to_handle":"bob","amount":1,"x":' + b"[" * depth + b"]" * depth + b"}"
            key = "deep%d" % depth
            r = self.req("POST", "/payments", raw=raw, token=self.ada, key=key)
            self.assertEqual(r.status, 201, (depth, r.raw[:80]))
            self.assertEqual(self.req("POST", "/payments", raw=raw, token=self.ada, key=key).status, 200)
            raw2 = b'{"to_handle":"bob","amount":1,"x":' + b'{"a":' * depth + b"1" + b"}" * depth + b"}"
            self.assertEqual(self.req("POST", "/payments", raw=raw2, token=self.ada, key=key + "o").status, 201)
        exp = self.req("GET", "/_test/export")
        self.assertEqual(self.req("POST", "/_test/import", raw=exp.raw).status, 204)
        for depth in (20000, 200000):
            raw = b'{"to_handle":"bob","amount":1,"x":' + b"[" * depth + b"]" * depth + b"}"
            self.assertLess(self.req("POST", "/payments", raw=raw, token=self.ada, key="huge").status, 500)
            self.assertLess(self.req("POST", "/_test/reset", raw=raw).status, 500)
            self.assertLess(self.req("POST", "/_test/import", raw=raw).status, 500)
        self.assertEqual(self.req("GET", "/health").status, 200)

    def test_reset_structural_garbage_is_4xx(self):
        base = fixture(payments=[{"id": "p", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1}],
                       requests=[{"id": "r", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1,
                                  "status": "pending"}])
        import copy as cp
        bad = []
        for path in (("payments", 0, "from_user_id"), ("payments", 0, "to_user_id"),
                     ("requests", 0, "requester_id"), ("requests", 0, "payer_id")):
            for v in ([], {}, None, 5, True):
                fx = cp.deepcopy(base)
                fx[path[0]][path[1]][path[2]] = v
                bad.append(fx)
        for raw_val in ("1e400", "-1e400", "1e999999"):
            for where in ("user", "payment", "request"):
                text = json.dumps(base)
                if where == "user":
                    text = text.replace('"balance": 10000', '"balance": ' + raw_val)
                else:
                    text = text.replace('"amount": 1,', '"amount": ' + raw_val + ',', 1 if where == "payment" else 2)
                bad.append(text.encode())
        for fx in bad:
            r = self.req("POST", "/_test/reset", raw=fx if isinstance(fx, bytes) else json.dumps(fx).encode())
            self.assertIn(r.status, (400, 422), fx)
            self.assertIn("error", r.json)
        self.assertEqual(self.bal(self.ada), 10000)

    def test_import_invalid_state_is_422_and_harmless(self):
        import copy as cp
        self.post("/payments", {"to_handle": "bob", "amount": 5}, self.ada, key="a")
        self.post("/requests", {"payer_handle": "bob", "amount": 5}, self.ada, key="b")
        exp = self.req("GET", "/_test/export").json
        mutations = [
            lambda d: d["state"]["payments"][0].__setitem__("from", []),
            lambda d: d["state"]["requests"][0].__setitem__("payer_id", {}),
            lambda d: d["state"]["idem"][0].__setitem__("user", []),
            lambda d: d["state"]["tokens"].__setitem__("t", []),
            lambda d: d["state"]["payments"][0].pop("request_id"),
            lambda d: d["state"]["payments"][0].pop("settlement_id"),
            lambda d: d["state"]["requests"][0].pop("payment_id"),
            lambda d: d.__setitem__("format_version", True),
            lambda d: d.__setitem__("format_version", 1.5),
            lambda d: d.__setitem__("track", ["pocketful"]),
            lambda d: d["state"]["users"]["u_ada"].__setitem__("balance", True),
            lambda d: d["state"]["users"]["u_ada"].__setitem__("pw", None),
            lambda d: d["state"]["counters"].pop("payment"),
        ]
        for mut in mutations:
            d = cp.deepcopy(exp)
            mut(d)
            r = self.req("POST", "/_test/import", d)
            self.err(r, 422, "validation_failed")
        self.assertEqual(self.bal(self.ada), 9995)
        self.assertEqual(self.req("GET", "/activity", token=self.ada).status, 200)
        self.assertEqual(self.req("GET", "/requests", token=self.ada).status, 200)

    def test_huge_integer_literals(self):
        digits = b"1" + b"0" * 4300
        self.err(self.req("POST", "/payments", raw=b'{"to_handle":"bob","amount":' + digits + b"}",
                          token=self.ada, key="h1"), 422, "validation_failed")
        self.err(self.req("POST", "/payments", raw=b'{"to_handle":"bob","amount":-' + digits + b"}",
                          token=self.ada, key="h2"), 422, "validation_failed")
        raw = b'{"to_handle":"bob","amount":1,"x":' + digits + b"}"
        self.assertEqual(self.req("POST", "/payments", raw=raw, token=self.ada, key="h3").status, 201)
        self.assertEqual(self.req("POST", "/payments", raw=raw, token=self.ada, key="h3").status, 200)
        self.assertEqual(self.req("POST", "/_test/import", raw=self.req("GET", "/_test/export").raw).status, 204)

    def test_large_offset(self):
        for path in ("/activity", "/requests"):
            for off in ("1000000000000", "9" * 40, "0" * 30 + "7"):
                r = self.req("GET", path + "?offset=" + off, token=self.ada)
                self.assertEqual(r.status, 200, (path, off))
                self.assertFalse(r.json["has_more"])
        self.err(self.req("GET", "/activity?limit=" + "9" * 40, token=self.ada), 422, "validation_failed")

    def test_reset_speed_many_users(self):
        for n in (1000, 2000):
            fx = fixture(users=[user("w%d" % i, 10, ) for i in range(n)])
            t0 = time.time()
            self.assertEqual(self.req("POST", "/_test/reset", fx).status, 204)
            took = time.time() - t0
            print("reset %d users: %.2fs" % (n, took))
            self.assertLess(took, 10)
        tok = self.login("w5")
        self.assertEqual(self.bal(tok), 10)
        exp = self.req("GET", "/_test/export")
        t0 = time.time()
        self.assertEqual(self.req("POST", "/_test/import", raw=exp.raw).status, 204)
        self.assertLess(time.time() - t0, 3)


TestRegressions.populate = TestExportImport.populate


if __name__ == "__main__":
    unittest.main()
