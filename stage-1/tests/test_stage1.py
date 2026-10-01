"""Own tests for Pocketful stage 1, written from the specification.

Standard library only. Run against a live container:

    BASE_URL=http://127.0.0.1:18080 BASE_URL_B=http://127.0.0.1:18081 \
        python3 -m unittest discover -s tests -v

BASE_URL_B (a second container of the same image) is only needed for the
cross-container import test; that test is skipped without it.
"""
import concurrent.futures as cf
import http.client
import json
import os
import re
import time
import unittest
import urllib.parse
import uuid

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:18080")
BASE_B = os.environ.get("BASE_URL_B")
TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$")
PAYMENT_KEYS = {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
                "currency", "note", "visibility", "request_id", "settlement_id", "created_at"}
REQUEST_KEYS = {"request_id", "requester_id", "requester_handle", "payer_id", "payer_handle", "amount",
                "currency", "note", "status", "payment_id", "created_at"}


def key():
    return uuid.uuid4().hex


class Resp:
    def __init__(self, status, headers, raw):
        self.status, self.headers, self.raw = status, headers, raw
        try:
            self.json = json.loads(raw) if raw else None
        except ValueError:
            self.json = None

    @property
    def code(self):
        return self.json["error"]["code"]


def call(method, path, body=None, token=None, idem=None, raw=None, headers=None, base=None):
    u = urllib.parse.urlsplit(base or BASE)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=15)
    h = dict(headers or {})
    if token:
        h["Authorization"] = "Bearer " + token
    if idem is not None:
        h["Idempotency-Key"] = idem
    data = raw
    if raw is None and body is not None:
        data = json.dumps(body).encode()
    if data is not None:
        h.setdefault("Content-Type", "application/json")
    try:
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        return Resp(r.status, dict((k.lower(), v) for k, v in r.getheaders()), r.read())
    finally:
        c.close()


def user(handle, balance, uid=None, email=None):
    return {"id": uid or "u_" + handle, "email": email or handle + "@example.com", "password": "correct horse",
            "display_name": handle.title(), "handle": handle, "balance": balance}


def fixture(users=None, currency="EUR", minor_units=2, **extra):
    f = {"currency": currency, "minor_units": minor_units,
         "users": users if users is not None else [user("ada", 10000), user("bob", 2500), user("cy", 500)]}
    f.update(extra)
    return f


def reset(f=None, base=None):
    r = call("POST", "/_test/reset", f if f is not None else fixture(), base=base)
    assert r.status == 204, (r.status, r.raw)
    return r


def login(handle, base=None):
    r = call("POST", "/auth/login", {"email": handle + "@example.com", "password": "correct horse"}, base=base)
    assert r.status == 200, (r.status, r.raw)
    return r.json["token"]


def me(tok, base=None):
    return call("GET", "/me", token=tok, base=base).json


def pay(tok, to, amount, **kw):
    b = {"to_handle": to, "amount": amount}
    b.update(kw.pop("body", {}))
    return call("POST", "/payments", b, token=tok, idem=kw.pop("idem", key()), **kw)


def ask(tok, payer, amount, **extra):
    b = {"payer_handle": payer, "amount": amount}
    b.update(extra)
    return call("POST", "/requests", b, token=tok, idem=key())


def err(t, r, status, code):
    t.assertEqual((r.status, r.json and r.json.get("error", {}).get("code")), (status, code), r.raw[:300])
    t.assertIn("message", r.json["error"])


class Base(unittest.TestCase):
    def setUp(self):
        reset()
        self.ada, self.bob, self.cy = login("ada"), login("bob"), login("cy")

    def total(self):
        return sum(me(t)["balance"] for t in (self.ada, self.bob, self.cy))


# ------------------------------------------------------------------ D / R
class TestRuntime(Base):
    def test_d4_health_no_auth(self):
        r = call("GET", "/health")
        self.assertEqual((r.status, r.json), (200, {"status": "ok"}))

    def test_d7_content_type_everywhere(self):
        for r in (call("GET", "/health"), call("GET", "/nope"), call("GET", "/me"),
                  call("GET", "/me", token=self.ada), call("POST", "/payments", raw=b"{", token=self.ada, idem=key())):
            self.assertEqual(r.headers["content-type"], "application/json; charset=utf-8")
        r = call("POST", "/_test/reset", fixture())
        self.assertEqual((r.status, r.raw), (204, b""))

    def test_e1_unknown_route_and_method(self):
        err(self, call("GET", "/nope"), 404, "not_found")
        err(self, call("DELETE", "/me", token=self.ada), 404, "not_found")
        err(self, call("GET", "/payments", token=self.ada), 404, "not_found")

    def test_d8_timestamps(self):
        p = pay(self.ada, "bob", 5).json
        self.assertRegex(p["created_at"], TS_RE)
        self.assertTrue(p["created_at"].endswith("+00:00"))

    def test_d9_unknown_fields_and_query_ignored(self):
        r = call("POST", "/payments", {"to_handle": "bob", "amount": 5, "bogus": [1, 2], "x": None}, token=self.ada, idem=key())
        self.assertEqual(r.status, 201)
        r = call("GET", "/activity?direction=incoming&status=paid&zzz=1", token=self.ada)
        self.assertEqual(r.status, 200)

    def test_d10_ids_do_not_collide_with_fixture(self):
        f = fixture([user("ada", 1000, uid="u_1"), user("bob", 1000, uid="u_2")],
                    payments=[{"id": "p_1", "from_user_id": "u_1", "to_user_id": "u_2", "amount": 5, "note": "x", "visibility": "public"}],
                    requests=[{"id": "rq_1", "requester_id": "u_2", "payer_id": "u_1", "amount": 7, "note": "t", "status": "pending"}])
        reset(f)
        a = login("ada")
        ids = set()
        for _ in range(3):
            ids.add(pay(a, "bob", 1).json["payment_id"])
            ids.add(ask(a, "bob", 1).json["request_id"])
        r = call("POST", "/auth/signup", {"email": "zed@example.com", "password": "password1", "display_name": "Z"})
        ids.add(r.json["user_id"])
        self.assertTrue(ids.isdisjoint({"p_1", "rq_1", "u_1", "u_2"}), ids)
        self.assertEqual(len(ids), 7)
        for i in ids:
            self.assertLessEqual(len(i), 64)

    def test_d11_no_ui(self):
        for p in ("/", "/login", "/feed", "/index.html", "/static/app.js"):
            err(self, call("GET", p), 404, "not_found")

    def test_d6_hostile_input_never_5xx(self):
        cases = [b"", b"\xff\xfe\x00", b"[]", b"null", b"1", b'"x"', b"{" * 100000, b"[" * 100000, b'{"a":' * 5000 + b"1" + b"}" * 5000,
                 b'{"to_handle":"bob","amount":1e400}', b'{"to_handle":"bob","amount":-1e400}', b'{"amount":NaN}',
                 b'{"to_handle":"bob","amount":' + b"9" * 5000 + b"}", json.dumps({"to_handle": "bob", "amount": 1, "x": ["a"] * 100000}).encode(),
                 b'{"to_handle":"bob\xff","amount":1}', b'{"to_handle":"\\ud800","amount":1}']
        for raw in cases:
            for path in ("/payments", "/requests", "/splits", "/settlements", "/requests/x/pay", "/auth/signup", "/auth/login",
                         "/_test/reset", "/_test/import"):
                r = call("POST", path, raw=raw, token=self.ada, idem=key())
                self.assertLess(r.status, 500, (path, raw[:30], r.status))
        reset()
        r = call("POST", "/splits", {"amount": 10, "participant_handles": ["ada"] * 1000}, token=login("ada"), idem=key())
        self.assertEqual(r.status, 422)
        r = call("POST", "/splits", {"amount": 10, "participant_handles": ["h%d" % i for i in range(1000)]}, token=login("ada"), idem=key())
        self.assertEqual(r.status, 404)
        for q in ("limit=" + "9" * 5000, "offset=" + "9" * 5000, "limit=%FF", "x=%"):
            self.assertLess(call("GET", "/activity?" + q, token=login("ada")).status, 500)
        self.assertLess(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=login("ada"), idem="é" * 300).status, 500)


class TestReset(Base):
    def test_r1_reset_clears_everything(self):
        k = key()
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 5}, token=self.ada, idem=k).status, 201)
        reset()
        err(self, call("GET", "/me", token=self.ada), 401, "unauthenticated")
        a = login("ada")
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 5}, token=a, idem=k).status, 201)
        self.assertEqual(call("GET", "/activity", token=a).json["payments"][0]["amount"], 5)
        reset()
        self.assertEqual(call("GET", "/activity", token=login("ada")).json["payments"], [])
        reset(fixture([user("zed", 1)]))
        err(self, call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}), 401, "unauthenticated")
        self.assertEqual(me(login("zed"))["balance"], 1)

    def test_r3_r6_r7_seeded(self):
        f = fixture(payments=[
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
            {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 300, "note": "secret", "visibility": "private"}],
            requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
                      {"id": "rq_2", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 100, "note": "done", "status": "paid"},
                      {"id": "rq_3", "requester_id": "u_bob", "payer_id": "u_cy", "amount": 100, "note": "no", "status": "declined"}])
        reset(f)
        a, b, c = login("ada"), login("bob"), login("cy")
        self.assertEqual([me(a)["balance"], me(b)["balance"], me(c)["balance"]], [10000, 2500, 500])
        pa = call("GET", "/activity", token=a).json["payments"]
        self.assertEqual({p["payment_id"] for p in pa}, {"p_1", "p_2"})
        for p in pa:
            self.assertEqual(set(p), PAYMENT_KEYS)
            self.assertIsNone(p["request_id"])
            self.assertIsNone(p["settlement_id"])
            self.assertEqual(p["currency"], "EUR")
        self.assertEqual({p["payment_id"] for p in call("GET", "/activity", token=c).json["payments"]}, {"p_1"})
        self.assertEqual({r["request_id"] for r in call("GET", "/requests", token=c).json["requests"]}, {"rq_3"})
        self.assertEqual({r["request_id"] for r in call("GET", "/requests", token=a).json["requests"]}, {"rq_1", "rq_2"})
        err(self, call("POST", "/requests/rq_2/pay", {}, token=a, idem=key()), 409, "request_not_pending")
        err(self, call("POST", "/requests/rq_3/pay", {}, token=c, idem=key()), 409, "request_not_pending")
        self.assertEqual(call("POST", "/requests/rq_1/pay", {}, token=a, idem=key()).status, 201)
        self.assertEqual(me(a)["balance"], 8800)

    def test_r4_invalid_fixtures(self):
        reset()
        tok = login("ada")
        bad = [fixture([user("ada", -1)]), fixture([user("ada", 1.5)]), fixture([user("ada", "5")]), fixture(minor_units=4),
               fixture(currency=5), {"currency": "EUR", "minor_units": 2}, fixture([user("A!", 1)]),
               fixture([user("ada", 1), user("ada", 2, uid="u_x", email="x@example.com")]),
               fixture([user("ada", 1), user("bob", 2, uid="u_ada")]),
               fixture(payments=[{"id": "p", "from_user_id": "nope", "to_user_id": "u_ada", "amount": 1}])]
        for f in bad:
            r = call("POST", "/_test/reset", f)
            self.assertEqual(r.status, 422, (f, r.raw))
            self.assertEqual(r.code, "validation_failed")
        err(self, call("POST", "/_test/reset", raw=b"{nope"), 400, "malformed_request")
        err(self, call("POST", "/_test/reset", raw=b"[1]"), 400, "malformed_request")
        self.assertEqual(me(tok)["balance"], 10000)

    def test_r5_currencies(self):
        for cur, mu in (("JPY", 0), ("BHD", 3), ("EUR", 2)):
            reset(fixture(currency=cur, minor_units=mu))
            a = login("ada")
            m = me(a)
            self.assertEqual((m["currency"], m["minor_units"]), (cur, mu))
            self.assertEqual(pay(a, "bob", 5).json["currency"], cur)
            self.assertEqual(ask(a, "bob", 5).json["currency"], cur)
            self.assertEqual(call("POST", "/splits", {"amount": 9, "participant_handles": ["bob"]}, token=a, idem=key()).json["currency"], cur)

    def test_r8_operators_and_absent_lists(self):
        reset({"currency": "EUR", "minor_units": 2, "users": [user("ada", 10), user("bob", 10)], "settlement_operator_ids": ["u_ada"]})
        a, b = login("ada"), login("bob")
        s = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}
        self.assertEqual(call("POST", "/settlements", s, token=a, idem=key()).status, 201)
        err(self, call("POST", "/settlements", s, token=b, idem=key()), 403, "forbidden")

    def test_r10_exact_big_numbers(self):
        big = 2 ** 53
        reset(fixture([user("ada", big - 2000000000), user("bob", 0)]))
        a, b = login("ada"), login("bob")
        for _ in range(2):
            self.assertEqual(pay(a, "bob", 1000000000).status, 201)
        self.assertEqual(me(a)["balance"], big - 4000000000)
        self.assertEqual(me(b)["balance"], 2000000000)
        r = pay(a, "bob", 1)
        self.assertRegex(r.raw.decode(), r'"amount":1[,}]')
        reset(fixture([user("ada", big), user("bob", 1)]))
        self.assertEqual(me(login("ada"))["balance"], big)


# ------------------------------------------------------------------- E / A
class TestValidation(Base):
    def test_e2_e3_amount_note_visibility(self):
        for amt in (0, -1, 1000000001, 1.5, "100", True, False, None, [1], {"a": 1}, 1e400):
            r = call("POST", "/payments", raw=json.dumps({"to_handle": "bob", "amount": amt}).encode().replace(b"Infinity", b"1e400"),
                     token=self.ada, idem=key())
            err(self, r, 422, "validation_failed")
        for note in (None, 5, True, [], {}, "x" * 201):
            err(self, pay(self.ada, "bob", 5, body={"note": note}), 422, "validation_failed")
        for vis in ("Public", "", None, 1, "PRIVATE", "friends", True):
            err(self, pay(self.ada, "bob", 5, body={"visibility": vis}), 422, "validation_failed")
        err(self, pay(self.ada, "bob", 5, body={"amount": None}), 422, "validation_failed")
        self.assertEqual(self.total(), 13000)

    def test_e2_malformed(self):
        for body in (b"{", b"", b"[]", b'"s"', b"null", b"\xff"):
            err(self, call("POST", "/payments", raw=body, token=self.ada, idem=key()), 400, "malformed_request")
        err(self, call("POST", "/payments", {"to_handle": 5, "amount": 5}, token=self.ada, idem=key()), 400, "malformed_request")
        err(self, call("POST", "/requests", {"payer_handle": ["x"], "amount": 5}, token=self.ada, idem=key()), 400, "malformed_request")
        err(self, call("POST", "/splits", {"amount": 5, "participant_handles": "ada"}, token=self.ada, idem=key()), 400, "malformed_request")
        err(self, call("POST", "/splits", {"amount": 5, "participant_handles": ["bob", 3]}, token=self.ada, idem=key()), 400, "malformed_request")
        err(self, call("POST", "/auth/login", {"email": 1, "password": "x"}), 400, "malformed_request")
        err(self, call("POST", "/auth/signup", raw=b"zzz"), 400, "malformed_request")

    def test_e4_integral_numbers(self):
        for lit in ("1000", "1000.0", "1e3", "1E3", "1.0e3"):
            r = call("POST", "/payments", raw=('{"to_handle":"bob","amount":%s}' % lit).encode(), token=self.ada, idem=key())
            self.assertEqual((r.status, r.json["amount"]), (201, 1000), lit)
        r = call("POST", "/payments", raw=b'{"to_handle":"cy","amount":1e9}', token=self.ada, idem=key())
        err(self, r, 409, "insufficient_funds")  # valid amount, only short of funds
        reset(fixture([user("ada", 2000000000), user("bob", 0)]))
        r = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1e9}', token=login("ada"), idem=key())
        self.assertEqual(r.status, 201)

    def test_e5_missing_required(self):
        err(self, call("POST", "/payments", {"amount": 5}, token=self.ada, idem=key()), 422, "validation_failed")
        err(self, call("POST", "/payments", {"to_handle": "bob"}, token=self.ada, idem=key()), 422, "validation_failed")
        err(self, call("POST", "/requests", {"amount": 5}, token=self.ada, idem=key()), 422, "validation_failed")
        err(self, call("POST", "/splits", {"amount": 5}, token=self.ada, idem=key()), 422, "validation_failed")
        err(self, call("POST", "/settlements", {}, token=self.ada, idem=key()), 403, "forbidden")

    def test_e6_note_codepoints_and_verbatim(self):
        r = pay(self.ada, "bob", 1, body={"note": "😀" * 200})
        self.assertEqual(r.status, 201)
        self.assertEqual(r.json["note"], "😀" * 200)
        err(self, pay(self.ada, "bob", 1, body={"note": "😀" * 201}), 422, "validation_failed")
        err(self, pay(self.ada, "bob", 1, body={"note": "a" * 201}), 422, "validation_failed")
        self.assertEqual(pay(self.ada, "bob", 1, body={"note": "é" * 200}).status, 201)
        for note in ("  padded \t\n", "e\u0301 combining", '<b>&amp;"q"\'</b>', "日本語 🇯🇵 \u200b", "\\u00e9 \\n", ""):
            r = pay(self.ada, "bob", 1, body={"note": note})
            self.assertEqual(r.json["note"], note)
            feed = call("GET", "/activity?limit=1", token=self.bob).json["payments"][0]
            self.assertEqual(feed["note"], note)
        raw = br'{"to_handle":"bob","amount":1,"note":"caf\u00e9 \ud83d\ude00"}'
        r = call("POST", "/payments", raw=raw, token=self.ada, idem=key())
        self.assertEqual(r.json["note"], "café 😀")
        self.assertIn("café 😀".encode("utf-8"), r.raw)  # not \u-escaped, still valid either way
        r = call("POST", "/requests", {"payer_handle": "bob", "amount": 1, "note": "😀" * 200}, token=self.ada, idem=key())
        self.assertEqual(r.status, 201)
        err(self, ask(self.ada, "bob", 1, note="😀" * 201), 422, "validation_failed")

    def test_e7_idempotency_key_header(self):
        b = {"to_handle": "bob", "amount": 1}
        err(self, call("POST", "/payments", b, token=self.ada), 400, "missing_idempotency_key")
        err(self, call("POST", "/payments", b, token=self.ada, idem=""), 400, "missing_idempotency_key")
        err(self, call("POST", "/payments", b, token=self.ada, idem="k" * 256), 422, "validation_failed")
        err(self, call("POST", "/payments", b, token=self.ada, idem="k" * 10240), 422, "validation_failed")
        self.assertEqual(call("POST", "/payments", b, token=self.ada, idem="k" * 255).status, 201)
        self.assertEqual(call("POST", "/payments", b, token=self.ada, idem="k").status, 201)
        self.assertEqual(call("POST", "/payments", b, token=self.ada, idem="é" * 255).status, 201)
        err(self, call("POST", "/payments", b, token=self.ada, idem="é" * 256), 422, "validation_failed")
        for path, body in (("/requests", {"payer_handle": "bob", "amount": 1}), ("/splits", {"amount": 1, "participant_handles": ["bob"]}),
                           ("/requests/x/pay", {}), ("/settlements", {})):
            r = call("POST", path, body, token=self.ada, idem=None)
            self.assertIn(r.code, ("missing_idempotency_key", "forbidden"))
            if path != "/settlements":
                err(self, r, 400, "missing_idempotency_key")

    def test_e8_paging_params(self):
        for ep in ("/activity", "/requests"):
            for bad in ("limit=0", "limit=201", "limit=-1", "limit=1e9", "limit=4.0", "limit=%2B4", "limit=abc", "limit=", "limit=1.5",
                        "offset=-1", "offset=1e1", "offset=2.0", "offset=x", "offset=", "offset=+1"):
                err(self, call("GET", ep + "?" + bad, token=self.ada), 422, "validation_failed")
            for good in ("limit=1", "limit=200", "offset=0", "offset=5", "limit=50&offset=0"):
                self.assertEqual(call("GET", ep + "?" + good, token=self.ada).status, 200, good)

    def test_e9_auth_everywhere(self):
        eps = [("GET", "/me"), ("POST", "/payments"), ("POST", "/requests"), ("GET", "/requests"), ("POST", "/requests/x/pay"),
               ("POST", "/requests/x/decline"), ("POST", "/requests/x/cancel"), ("POST", "/splits"), ("GET", "/activity"),
               ("POST", "/settlements")]
        for m, p in eps:
            for h in (None, "Bearer", "Bearer nope", "Basic abc", "nope", "Bearer  "):
                r = call(m, p, {} if m == "POST" else None, headers={"Authorization": h} if h else None, idem=key())
                err(self, r, 401, "unauthenticated")


class TestAuth(Base):
    def signup(self, email, pw="correct horse", name="N", **extra):
        b = {"email": email, "password": pw, "display_name": name}
        b.update(extra)
        return call("POST", "/auth/signup", b)

    def test_a1_a2_signup_and_handle(self):
        r = self.signup("Ada.L+x@Example.com", handle="hacker")
        self.assertEqual(r.status, 201)
        self.assertEqual(set(r.json), {"user_id", "display_name", "token"})
        m = me(r.json["token"])
        self.assertEqual((m["handle"], m["balance"]), ("ada_l_x", 0))
        self.assertEqual(me(self.signup("a" * 30 + "@x.com").json["token"])["handle"], "a" * 20)
        self.assertEqual(me(self.signup("Q-é😀@x.com").json["token"])["handle"], "q___")
        self.assertEqual(me(self.signup("1_Z@x.com").json["token"])["handle"], "1_z")

    def test_a3_conflicts(self):
        self.assertEqual(self.signup("new@example.com").status, 201)
        err(self, self.signup("new@example.com"), 409, "email_taken")
        err(self, self.signup("ada@other.com"), 409, "handle_taken")
        err(self, call("POST", "/auth/login", {"email": "ada@other.com", "password": "correct horse"}), 401, "unauthenticated")
        err(self, self.signup("ada@example.com"), 409, "email_taken")
        with cf.ThreadPoolExecutor(20) as ex:
            rs = list(ex.map(lambda i: self.signup("race@example.com"), range(20)))
        self.assertEqual(sorted(r.status for r in rs), [201] + [409] * 19)

    def test_a4_validation(self):
        err(self, self.signup("v1@x.com", pw="short"), 422, "validation_failed")
        err(self, self.signup("v2@x.com", pw="1234567"), 422, "validation_failed")
        self.assertEqual(self.signup("v3@x.com", pw="12345678").status, 201)
        self.assertEqual(self.signup("v4@x.com", pw="é" * 8).status, 201)
        for e in ("plain", "@x.com", "a@", "a@@b", "a@b@c", ""):
            err(self, self.signup(e), 422, "validation_failed")
        err(self, call("POST", "/auth/signup", {"password": "12345678", "display_name": "x"}), 422, "validation_failed")
        err(self, call("POST", "/auth/signup", {"email": "q@x.com", "display_name": "x"}), 422, "validation_failed")
        err(self, call("POST", "/auth/signup", {"email": "q@x.com", "password": "12345678"}), 422, "validation_failed")
        err(self, call("POST", "/auth/login", {"email": "q@x.com"}), 422, "validation_failed")

    def test_a5_a6_login_tokens(self):
        err(self, call("POST", "/auth/login", {"email": "ada@example.com", "password": "wrong"}), 401, "unauthenticated")
        err(self, call("POST", "/auth/login", {"email": "none@example.com", "password": "correct horse"}), 401, "unauthenticated")
        r = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
        self.assertEqual((r.json["user_id"], r.json["display_name"]), ("u_ada", "Ada"))
        t2 = r.json["token"]
        t3 = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}).json["token"]
        self.assertEqual(len({self.ada, t2, t3}), 3)
        for t in (self.ada, t2, t3):
            self.assertEqual(me(t)["user_id"], "u_ada")
        s = self.signup("multi@example.com").json
        self.assertEqual(me(s["token"])["user_id"], s["user_id"])

    def test_d5_login_burst_and_large_reset(self):
        users = [user("u%d" % i, 100) for i in range(500)]
        t0 = time.time()
        reset(fixture(users))
        self.assertLess(time.time() - t0, 10)
        t0 = time.time()
        with cf.ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: call("POST", "/auth/login", {"email": "u%d@example.com" % i, "password": "correct horse"}), range(50)))
        self.assertTrue(all(r.status == 200 for r in rs))
        self.assertLess(time.time() - t0, 5)
        t0 = time.time()
        e = call("GET", "/_test/export")
        self.assertLess(time.time() - t0, 10)
        t0 = time.time()
        self.assertEqual(call("POST", "/_test/import", raw=e.raw).status, 204)
        self.assertLess(time.time() - t0, 10)

    def test_a7_no_plaintext(self):
        e = call("GET", "/_test/export")
        self.assertNotIn(b"correct horse", e.raw)
        self.signup("pw@example.com", pw="s3cretPassw0rd")
        self.assertNotIn(b"s3cretPassw0rd", call("GET", "/_test/export").raw)


# ----------------------------------------------------------------- payments
class TestPayments(Base):
    def test_m2_shape_and_balances(self):
        r = pay(self.ada, "bob", 1500, body={"note": "dinner"})
        self.assertEqual(r.status, 201)
        p = r.json
        self.assertEqual(set(p), PAYMENT_KEYS)
        self.assertEqual((p["from_user_id"], p["from_handle"], p["to_user_id"], p["to_handle"], p["amount"], p["currency"], p["note"],
                          p["visibility"], p["request_id"], p["settlement_id"]),
                         ("u_ada", "ada", "u_bob", "bob", 1500, "EUR", "dinner", "public", None, None))
        self.assertEqual((me(self.ada)["balance"], me(self.bob)["balance"]), (8500, 4000))
        d = pay(self.ada, "bob", 1).json
        self.assertEqual((d["note"], d["visibility"]), ("", "public"))

    def test_m3_m4_errors(self):
        err(self, pay(self.cy, "ada", 501), 409, "insufficient_funds")
        self.assertEqual(me(self.cy)["balance"], 500)
        self.assertEqual(call("GET", "/activity", token=self.cy).json["payments"], [])
        self.assertEqual(pay(self.cy, "ada", 500).status, 201)
        self.assertEqual(me(self.cy)["balance"], 0)
        err(self, pay(self.ada, "ada", 5), 422, "self_payment")
        for h in ("nobody", "", "ADA", "@ada", "a" * 21, "ada "):
            err(self, pay(self.ada, "bob", 5, body={"to_handle": h}), 404 if h not in ("ADA",) else 404, "not_found")
        self.assertEqual(self.total(), 13000)

    def test_m5_failed_payment_leaves_no_key(self):
        k = key()
        err(self, pay(self.cy, "ada", 501, idem=k), 409, "insufficient_funds")
        self.assertEqual(pay(self.ada, "cy", 1000).status, 201)
        r = pay(self.cy, "ada", 501, idem=k)
        self.assertEqual(r.status, 201)
        r2 = pay(self.cy, "ada", 501, idem=k)
        self.assertEqual((r2.status, r2.json), (200, r.json))
        self.assertEqual(me(self.ada)["balance"], 10000 - 1000 + 501)

    def test_m6_concurrent_drain(self):
        reset(fixture([user("ada", 1000), user("bob", 0)]))
        a = login("ada")
        with cf.ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: pay(a, "bob", 100), range(50)))
        self.assertEqual(sorted(set(r.status for r in rs)), [201, 409])
        self.assertEqual(sum(r.status == 201 for r in rs), 10)
        self.assertEqual((me(a)["balance"], me(login("bob"))["balance"]), (0, 1000))

    def test_m6_cycle_and_cross(self):
        users = [user("w%d" % i, 1000) for i in range(50)]
        reset(fixture(users))
        toks = [login("w%d" % i) for i in range(50)]

        def work(i):
            out = []
            for j in range(4):
                out.append(pay(toks[i], "w%d" % ((i + j + 1) % 50), 300 + 7 * j).status)
            return out
        with cf.ThreadPoolExecutor(50) as ex:
            res = list(ex.map(work, range(50)))
        self.assertTrue(all(s in (201, 409) for r in res for s in r))
        bals = [me(t)["balance"] for t in toks]
        self.assertEqual(sum(bals), 50000)
        self.assertGreaterEqual(min(bals), 0)

    def test_f1_f3_feed_matrix(self):
        pub = pay(self.ada, "bob", 10, body={"visibility": "public"}).json
        priv = pay(self.ada, "bob", 11, body={"visibility": "private"}).json
        ids = lambda t: [p["payment_id"] for p in call("GET", "/activity", token=t).json["payments"]]
        self.assertEqual(ids(self.ada), [priv["payment_id"], pub["payment_id"]])
        self.assertEqual(ids(self.bob), [priv["payment_id"], pub["payment_id"]])
        self.assertEqual(ids(self.cy), [pub["payment_id"]])
        self.assertEqual(call("GET", "/activity", token=self.bob).json["payments"], [priv, pub])
        r = call("GET", "/activity", token=self.cy).json
        self.assertEqual(r, {"payments": [pub], "has_more": False})

    def test_f2_paging(self):
        made = [pay(self.ada, "bob", 1 + i).json["payment_id"] for i in range(5)]
        newest_first = made[::-1]
        r = call("GET", "/activity?limit=2", token=self.cy).json
        self.assertEqual(([p["payment_id"] for p in r["payments"]], r["has_more"]), (newest_first[:2], True))
        r = call("GET", "/activity?limit=2&offset=4", token=self.cy).json
        self.assertEqual(([p["payment_id"] for p in r["payments"]], r["has_more"]), (newest_first[4:], False))
        r = call("GET", "/activity?limit=5", token=self.cy).json
        self.assertEqual((len(r["payments"]), r["has_more"]), (5, False))
        r = call("GET", "/activity?offset=5", token=self.cy).json
        self.assertEqual(r, {"payments": [], "has_more": False})
        r = call("GET", "/activity?offset=50000", token=self.cy).json
        self.assertEqual(r, {"payments": [], "has_more": False})
        self.assertEqual(len(call("GET", "/activity?limit=200", token=self.cy).json["payments"]), 5)


# ------------------------------------------------------------- idempotency
class TestIdempotency(Base):
    def test_i2_replay(self):
        k = key()
        b = {"to_handle": "bob", "amount": 100, "note": "x"}
        r1 = call("POST", "/payments", b, token=self.ada, idem=k)
        r2 = call("POST", "/payments", {"note": "x", "amount": 100.0, "to_handle": "bob"}, token=self.ada, idem=k)
        r3 = call("POST", "/payments", raw=b'{ "amount":1e2,"to_handle":"bob", "note":"x" }', token=self.ada, idem=k)
        self.assertEqual((r1.status, r2.status, r3.status), (201, 200, 200))
        self.assertEqual(r1.json, r2.json)
        self.assertEqual(r1.json, r3.json)
        self.assertEqual(me(self.ada)["balance"], 9900)
        self.assertEqual(len(call("GET", "/activity", token=self.ada).json["payments"]), 1)

    def test_i3_i6_reuse_and_precedence(self):
        k = key()
        b = {"to_handle": "bob", "amount": 100}
        self.assertEqual(call("POST", "/payments", b, token=self.ada, idem=k).status, 201)
        err(self, call("POST", "/payments", dict(b, amount=101), token=self.ada, idem=k), 409, "idempotency_key_reuse")
        err(self, call("POST", "/payments", dict(b, extra=1), token=self.ada, idem=k), 409, "idempotency_key_reuse")
        err(self, call("POST", "/payments", {"to_handle": "bob", "amount": -5}, token=self.ada, idem=k), 409, "idempotency_key_reuse")
        err(self, call("POST", "/payments", {"to_handle": 5}, token=self.ada, idem=k), 409, "idempotency_key_reuse")
        err(self, call("POST", "/payments", raw=b"[1]", token=self.ada, idem=k), 400, "malformed_request")
        err(self, call("POST", "/payments", raw=b"{", token=self.ada, idem=k), 400, "malformed_request")
        err(self, call("POST", "/payments", b, token=None, idem=k), 401, "unauthenticated")
        self.assertEqual(call("POST", "/payments", b, token=self.ada, idem=k).status, 200)

    def test_i4_scope(self):
        k = key()
        a = call("POST", "/payments", {"to_handle": "cy", "amount": 10}, token=self.ada, idem=k)
        b = call("POST", "/payments", {"to_handle": "cy", "amount": 10}, token=self.bob, idem=k)
        self.assertEqual((a.status, b.status), (201, 201))
        self.assertNotEqual(a.json["payment_id"], b.json["payment_id"])
        r = call("POST", "/requests", {"payer_handle": "cy", "amount": 10}, token=self.ada, idem=k)
        self.assertEqual(r.status, 201)
        s = call("POST", "/splits", {"amount": 10, "participant_handles": ["cy"]}, token=self.ada, idem=k)
        self.assertEqual(s.status, 201)
        r2 = call("POST", "/requests", {"payer_handle": "cy", "amount": 10}, token=self.ada, idem=k)
        self.assertEqual((r2.status, r2.json), (200, r.json))
        self.assertEqual(me(self.cy)["balance"], 500 + 20)

    def test_i5_failed_does_not_claim(self):
        k = key()
        rq = ask(self.bob, "cy", 800).json["request_id"]
        err(self, call("POST", "/requests/%s/pay" % rq, {}, token=self.cy, idem=k), 409, "insufficient_funds")
        err(self, call("POST", "/requests/%s/pay" % rq, {"visibility": "bad"}, token=self.cy, idem=k), 422, "validation_failed")
        self.assertEqual(pay(self.ada, "cy", 1000).status, 201)
        r = call("POST", "/requests/%s/pay" % rq, {}, token=self.cy, idem=k)
        self.assertEqual(r.status, 201)
        self.assertEqual(len([p for p in call("GET", "/activity", token=self.bob).json["payments"] if p["request_id"] == rq]), 1)

    def test_i6_replayed_pay_after_paid(self):
        rq = ask(self.bob, "ada", 1200).json["request_id"]
        k = key()
        a = call("POST", "/requests/%s/pay" % rq, {}, token=self.ada, idem=k)
        self.assertEqual(a.status, 201)
        b = call("POST", "/requests/%s/pay" % rq, {}, token=self.ada, idem=k)
        self.assertEqual((b.status, b.json), (200, a.json))
        err(self, call("POST", "/requests/%s/pay" % rq, {"visibility": "public"}, token=self.ada, idem=k), 409, "idempotency_key_reuse")
        err(self, call("POST", "/requests/%s/pay" % rq, {}, token=self.ada, idem=key()), 409, "request_not_pending")
        self.assertEqual((me(self.ada)["balance"], me(self.bob)["balance"]), (8800, 3700))

    def test_i2_replay_after_cancel_and_other_paths(self):
        k = key()
        r = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, token=self.bob, idem=k)
        rid = r.json["request_id"]
        self.assertEqual(call("POST", "/requests/%s/cancel" % rid, token=self.bob).json["status"], "cancelled")
        r2 = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, token=self.bob, idem=k)
        self.assertEqual((r2.status, r2.json), (200, r.json))
        self.assertEqual(r2.json["status"], "pending")
        ks = key()
        s = call("POST", "/splits", {"amount": 100, "participant_handles": ["bob", "ada", "cy"]}, token=self.ada, idem=ks)
        s2 = call("POST", "/splits", {"amount": 100, "participant_handles": ["bob", "ada", "cy"]}, token=self.ada, idem=ks)
        self.assertEqual((s.status, s2.status, s.json), (201, 200, s2.json))
        err(self, call("POST", "/splits", {"amount": 100, "participant_handles": ["ada", "bob", "cy"]}, token=self.ada, idem=ks),
            409, "idempotency_key_reuse")
        self.assertEqual(len(call("GET", "/requests?direction=outgoing&status=pending", token=self.ada).json["requests"]), 2)

    def test_i1_decline_cancel_need_no_key(self):
        rq = ask(self.bob, "ada", 5).json["request_id"]
        self.assertEqual(call("POST", "/requests/%s/decline" % rq, token=self.ada).status, 200)
        rq = ask(self.bob, "ada", 5).json["request_id"]
        self.assertEqual(call("POST", "/requests/%s/cancel" % rq, token=self.bob).status, 200)

    def test_i7_concurrent_identical(self):
        def burst(path, body, tok):
            k = key()
            with cf.ThreadPoolExecutor(50) as ex:
                return list(ex.map(lambda i: call("POST", path, body, token=tok, idem=k), range(50)))
        for path, body, tok in (("/payments", {"to_handle": "bob", "amount": 10}, self.ada),
                                ("/requests", {"payer_handle": "bob", "amount": 10}, self.ada),
                                ("/splits", {"amount": 10, "participant_handles": ["bob", "cy"]}, self.ada)):
            rs = burst(path, body, tok)
            self.assertEqual(sorted(r.status for r in rs), [200] * 49 + [201], path)
            self.assertEqual(len({json.dumps(r.json, sort_keys=True) for r in rs}), 1)
        self.assertEqual(me(self.ada)["balance"], 9990)
        rq = ask(self.bob, "ada", 100).json["request_id"]
        rs = burst("/requests/%s/pay" % rq, {}, self.ada)
        self.assertEqual(sorted(r.status for r in rs), [200] * 49 + [201])
        self.assertEqual(me(self.ada)["balance"], 9890)
        self.assertEqual(self.total(), 13000)


# ---------------------------------------------------------------- requests
class TestRequests(Base):
    def test_q1_q3(self):
        r = ask(self.bob, "ada", 1200, note="taxi")
        self.assertEqual(r.status, 201)
        q = r.json
        self.assertEqual(set(q), REQUEST_KEYS)
        self.assertEqual((q["requester_id"], q["requester_handle"], q["payer_id"], q["payer_handle"], q["amount"], q["note"], q["status"],
                          q["payment_id"]), ("u_bob", "bob", "u_ada", "ada", 1200, "taxi", "pending", None))
        self.assertEqual(ask(self.bob, "ada", 100).json["note"], "")
        self.assertEqual(ask(self.cy, "ada", 999999).status, 201)  # beyond payer balance? no, ada has 10000 -> still pending
        self.assertEqual(ask(self.ada, "cy", 5000).status, 201)  # beyond cy's balance
        err(self, ask(self.ada, "ada", 5), 422, "self_request")
        err(self, ask(self.ada, "nobody", 5), 404, "not_found")
        for amt in (0, -1, 1000000001, 1.5, "5", None, True):
            err(self, ask(self.ada, "bob", amt), 422, "validation_failed")
        self.assertEqual(self.total(), 13000)

    def test_q4_q5_pay(self):
        rid = ask(self.bob, "ada", 1200, note="taxi").json["request_id"]
        err(self, call("POST", "/requests/%s/pay" % rid, {}, token=self.bob, idem=key()), 403, "forbidden")
        err(self, call("POST", "/requests/%s/pay" % rid, {}, token=self.cy, idem=key()), 403, "forbidden")
        err(self, call("POST", "/requests/nope/pay", {}, token=self.ada, idem=key()), 404, "not_found")
        err(self, call("POST", "/requests/%s/pay" % rid, {"visibility": "x"}, token=self.ada, idem=key()), 422, "validation_failed")
        r = call("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, token=self.ada, idem=key())
        self.assertEqual(r.status, 201)
        p = r.json
        self.assertEqual(set(p), PAYMENT_KEYS)
        self.assertEqual((p["request_id"], p["note"], p["amount"], p["visibility"], p["from_handle"], p["to_handle"]),
                         (rid, "taxi", 1200, "private", "ada", "bob"))
        got = [x for x in call("GET", "/requests", token=self.bob).json["requests"] if x["request_id"] == rid][0]
        self.assertEqual((got["status"], got["payment_id"]), ("paid", p["payment_id"]))
        self.assertEqual(call("GET", "/activity", token=self.cy).json["payments"], [])
        self.assertIn(p, call("GET", "/activity", token=self.bob).json["payments"])
        err(self, call("POST", "/requests/%s/pay" % rid, {}, token=self.ada, idem=key()), 409, "request_not_pending")

    def test_q5_short_then_funded(self):
        rid = ask(self.ada, "cy", 800).json["request_id"]
        err(self, call("POST", "/requests/%s/pay" % rid, {}, token=self.cy, idem=key()), 409, "insufficient_funds")
        self.assertEqual(call("GET", "/requests?status=pending", token=self.cy).json["requests"][0]["status"], "pending")
        self.assertEqual(me(self.cy)["balance"], 500)
        pay(self.bob, "cy", 400)
        self.assertEqual(call("POST", "/requests/%s/pay" % rid, {}, token=self.cy, idem=key()).status, 201)
        self.assertEqual(me(self.cy)["balance"], 100)

    def test_q4_zero_and_exact_balance(self):
        rid = ask(self.ada, "cy", 500).json["request_id"]
        self.assertEqual(call("POST", "/requests/%s/pay" % rid, {}, token=self.cy, idem=key()).status, 201)
        self.assertEqual(me(self.cy)["balance"], 0)

    def test_q6_concurrent_pay_decline_cancel(self):
        rid = ask(self.bob, "ada", 100).json["request_id"]
        with cf.ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: call("POST", "/requests/%s/pay" % rid, {}, token=self.ada, idem=key()), range(50)))
        self.assertEqual(sorted(r.status for r in rs), [201] + [409] * 49)
        self.assertEqual(me(self.ada)["balance"], 9900)
        for _ in range(5):
            rid = ask(self.bob, "ada", 100).json["request_id"]
            before = me(self.ada)["balance"]

            def go(i):
                if i % 3 == 0:
                    return call("POST", "/requests/%s/pay" % rid, {}, token=self.ada, idem=key())
                if i % 3 == 1:
                    return call("POST", "/requests/%s/decline" % rid, token=self.ada)
                return call("POST", "/requests/%s/cancel" % rid, token=self.bob)
            with cf.ThreadPoolExecutor(30) as ex:
                rs = list(ex.map(go, range(30)))
            final = [r for r in call("GET", "/requests", token=self.ada).json["requests"] if r["request_id"] == rid][0]["status"]
            paid = sum(1 for i, r in enumerate(rs) if i % 3 == 0 and r.status == 201)
            self.assertEqual(me(self.ada)["balance"], before - 100 * paid)
            self.assertEqual(final == "paid", paid == 1)
            self.assertLessEqual(paid, 1)
            ok_decl = sum(1 for i, r in enumerate(rs) if i % 3 == 1 and r.status == 200)
            ok_canc = sum(1 for i, r in enumerate(rs) if i % 3 == 2 and r.status == 200)
            if final == "declined":
                self.assertEqual((paid, ok_canc), (0, 0))
            if final == "cancelled":
                self.assertEqual((paid, ok_decl), (0, 0))
            self.assertTrue(all(r.status in (200, 201, 409) for r in rs))
        self.assertEqual(self.total(), 13000)

    def test_q7_q8_decline_cancel(self):
        rid = ask(self.bob, "ada", 5).json["request_id"]
        err(self, call("POST", "/requests/%s/decline" % rid, token=self.bob), 403, "forbidden")
        err(self, call("POST", "/requests/%s/cancel" % rid, token=self.ada), 403, "forbidden")
        err(self, call("POST", "/requests/%s/cancel" % rid, token=self.cy), 403, "forbidden")
        err(self, call("POST", "/requests/zzz/decline", token=self.ada), 404, "not_found")
        err(self, call("POST", "/requests/zzz/cancel", token=self.ada), 404, "not_found")
        r = call("POST", "/requests/%s/decline" % rid, token=self.ada)
        self.assertEqual((r.status, r.json["status"], set(r.json)), (200, "declined", REQUEST_KEYS))
        self.assertEqual(call("POST", "/requests/%s/decline" % rid, token=self.ada).json["status"], "declined")
        err(self, call("POST", "/requests/%s/cancel" % rid, token=self.bob), 409, "request_not_pending")
        err(self, call("POST", "/requests/%s/pay" % rid, {}, token=self.ada, idem=key()), 409, "request_not_pending")
        rid = ask(self.bob, "ada", 5).json["request_id"]
        self.assertEqual(call("POST", "/requests/%s/cancel" % rid, token=self.bob).json["status"], "cancelled")
        self.assertEqual(call("POST", "/requests/%s/cancel" % rid, token=self.bob).json["status"], "cancelled")
        err(self, call("POST", "/requests/%s/decline" % rid, token=self.ada), 409, "request_not_pending")
        err(self, call("POST", "/requests/%s/pay" % rid, {}, token=self.ada, idem=key()), 409, "request_not_pending")
        rid = ask(self.bob, "ada", 5).json["request_id"]
        call("POST", "/requests/%s/pay" % rid, {}, token=self.ada, idem=key())
        err(self, call("POST", "/requests/%s/cancel" % rid, token=self.bob), 409, "request_not_pending")
        err(self, call("POST", "/requests/%s/decline" % rid, token=self.ada), 409, "request_not_pending")

    def test_q9_listing(self):
        ids = [ask(self.bob, "ada", 10 + i).json["request_id"] for i in range(4)]
        ids.append(ask(self.ada, "bob", 99).json["request_id"])
        other = ask(self.bob, "cy", 7).json["request_id"]
        call("POST", "/requests/%s/decline" % ids[0], token=self.ada)
        get = lambda t, q="": call("GET", "/requests" + q, token=t).json
        self.assertEqual([r["request_id"] for r in get(self.ada)["requests"]], ids[::-1])
        self.assertEqual([r["request_id"] for r in get(self.ada, "?direction=incoming")["requests"]], ids[:4][::-1])
        self.assertEqual([r["request_id"] for r in get(self.ada, "?direction=outgoing")["requests"]], [ids[4]])
        self.assertEqual({r["request_id"] for r in get(self.ada, "?status=declined")["requests"]}, {ids[0]})
        self.assertEqual(len(get(self.ada, "?status=pending&direction=incoming")["requests"]), 3)
        self.assertNotIn(other, [r["request_id"] for r in get(self.ada)["requests"]])
        self.assertEqual([r["request_id"] for r in get(self.cy)["requests"]], [other])
        r = get(self.ada, "?limit=2")
        self.assertEqual((len(r["requests"]), r["has_more"]), (2, True))
        r = get(self.ada, "?limit=2&offset=3")
        self.assertEqual((len(r["requests"]), r["has_more"]), (2, False))
        r = get(self.ada, "?limit=5")
        self.assertEqual((len(r["requests"]), r["has_more"]), (5, False))
        for q in ("direction=sideways", "status=open", "direction=", "status=PAID", "direction=Incoming"):
            err(self, call("GET", "/requests?" + q, token=self.ada), 422, "validation_failed")
        for t in (self.ada, self.bob, self.cy):
            for r in get(t)["requests"]:
                self.assertNotIn("visibility", r)
        self.assertEqual(call("GET", "/activity", token=self.ada).json["payments"], [])

    def test_q9_operator_sees_nothing_extra(self):
        reset(fixture(settlement_operator_ids=["u_cy"]))
        a, b, c = login("ada"), login("bob"), login("cy")
        rid = ask(b, "ada", 5).json["request_id"]
        self.assertEqual(call("GET", "/requests", token=c).json["requests"], [])
        err(self, call("POST", "/requests/%s/cancel" % rid, token=c), 403, "forbidden")
        err(self, call("POST", "/requests/%s/pay" % rid, {}, token=c, idem=key()), 403, "forbidden")


# ------------------------------------------------------------------ splits
class TestSplits(Base):
    def split(self, tok, amount, handles, **kw):
        b = {"amount": amount, "participant_handles": handles}
        b.update(kw)
        return call("POST", "/splits", b, token=tok, idem=key())

    def test_s1_s2_table(self):
        reset(fixture([user(h, 100) for h in ("ada", "bob", "cy", "dd", "ee")]))
        a = login("ada")
        for amount, n, shares in ((1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]), (999, 3, [333, 333, 333]),
                                  (5, 5, [1] * 5), (7, 2, [4, 3]), (1000000000, 3, [333333334, 333333333, 333333333])):
            hs = ["ada", "bob", "cy", "dd", "ee"][:n]
            r = self.split(a, amount, hs, note="dinner")
            self.assertEqual(r.status, 201, r.raw)
            self.assertEqual([s["amount"] for s in r.json["shares"]], shares)
            self.assertEqual([s["handle"] for s in r.json["shares"]], hs)
            self.assertEqual(sum(s["amount"] for s in r.json["shares"]), amount)
            self.assertEqual(set(r.json), {"split_id", "amount", "currency", "note", "shares", "requests", "created_at"})
            self.assertEqual([q["payer_handle"] for q in r.json["requests"]], hs[1:])
            self.assertEqual([q["amount"] for q in r.json["requests"]], shares[1:])
            for q in r.json["requests"]:
                self.assertEqual((q["status"], q["requester_handle"], q["note"], set(q)), ("pending", "ada", "dinner", REQUEST_KEYS))
        r = self.split(a, 10, ["cy", "ada", "bob"])
        self.assertEqual([s["amount"] for s in r.json["shares"]], [4, 3, 3])
        self.assertEqual([(q["payer_handle"], q["amount"]) for q in r.json["requests"]], [("cy", 4), ("bob", 3)])
        r = self.split(a, 10, ["bob", "cy"])  # caller omitted
        self.assertEqual([s["amount"] for s in r.json["shares"]], [5, 5])
        self.assertEqual(len(r.json["requests"]), 2)
        self.assertEqual(self.split(a, 10, ["bob", "cy", "dd"]).json["shares"][0]["amount"], 4)

    def test_s3_s4(self):
        r = self.split(self.ada, 1, ["bob", "cy", "ada"])
        self.assertEqual([s["amount"] for s in r.json["shares"]], [1, 0, 0])
        self.assertEqual([(q["payer_handle"], q["amount"]) for q in r.json["requests"]], [("bob", 1), ("cy", 0)])
        r = self.split(self.ada, 50, ["ada"])
        self.assertEqual((r.status, r.json["shares"], r.json["requests"]), (201, [{"handle": "ada", "amount": 50}], []))
        self.assertEqual((me(self.ada)["balance"], self.total()), (10000, 13000))
        self.assertEqual(call("GET", "/activity", token=self.ada).json["payments"], [])
        zero = [q for q in call("GET", "/requests", token=self.cy).json["requests"] if q["amount"] == 0][0]
        self.assertEqual(call("POST", "/requests/%s/pay" % zero["request_id"], {}, token=self.cy, idem=key()).status, 201)
        self.assertEqual(me(self.cy)["balance"], 500)

    def test_s5_errors(self):
        for amt in (0, -3, 1000000001, 2.5, "9", None, True):
            err(self, self.split(self.ada, amt, ["bob"]), 422, "validation_failed")
        err(self, self.split(self.ada, 10, []), 422, "validation_failed")
        err(self, self.split(self.ada, 10, ["bob", "bob"]), 422, "validation_failed")
        err(self, self.split(self.ada, 10, ["bob", "ghost"]), 404, "not_found")
        err(self, self.split(self.ada, 10, ["bob"], note="x" * 201), 422, "validation_failed")
        err(self, self.split(self.ada, 10, ["bob"], note=None), 422, "validation_failed")
        self.assertEqual(call("GET", "/requests", token=self.bob).json["requests"], [])
        r = self.split(self.ada, 10, ["bob", "ghost"])
        self.assertEqual(call("GET", "/requests", token=self.ada).json["requests"], [])

    def test_s6_paid_in_full_conserves(self):
        reset(fixture([user("ada", 1000), user("bob", 1000), user("cy", 1000)]))
        a, b, c = login("ada"), login("bob"), login("cy")
        for amt in (1000, 1, 10, 999, 7):
            r = self.split(a, amt, ["ada", "bob", "cy"])
            for q, tok in zip(r.json["requests"], (b, c)):
                self.assertEqual(call("POST", "/requests/%s/pay" % q["request_id"], {}, token=tok, idem=key()).status, 201)
        self.assertEqual(sum(me(t)["balance"] for t in (a, b, c)), 3000)


# --------------------------------------------------------------- settlements
class TestSettlements(unittest.TestCase):
    def setUp(self):
        reset(fixture([user("ada", 100), user("bob", 0), user("cy", 0), user("op", 0)], settlement_operator_ids=["u_op"]))
        self.ada, self.bob, self.cy, self.op = (login(h) for h in ("ada", "bob", "cy", "op"))

    def st(self, transfers, tok=None, idem=None):
        return call("POST", "/settlements", {"transfers": transfers}, token=tok or self.op, idem=idem or key())

    def bal(self):
        return [me(t)["balance"] for t in (self.ada, self.bob, self.cy, self.op)]

    def t(self, f, to, amount, **kw):
        return dict({"from_handle": f, "to_handle": to, "amount": amount}, **kw)

    def test_t1_auth(self):
        err(self, call("POST", "/settlements", {"transfers": []}, idem=key()), 401, "unauthenticated")
        err(self, self.st([self.t("ada", "bob", 1)], tok=self.ada), 403, "forbidden")
        err(self, call("POST", "/settlements", {"transfers": [self.t("ada", "bob", 1)]}, token=self.ada), 403, "forbidden")
        err(self, call("POST", "/settlements", {"transfers": [self.t("ada", "bob", 1)]}, token=self.op), 400, "missing_idempotency_key")

    def test_t2_shape(self):
        for body in ({}, {"transfers": "x"}, {"transfers": None}, {"transfers": []}, {"transfers": [1]}, {"transfers": [[]]},
                     {"transfers": [self.t("ada", "bob", 1)] * 33}, {"transfers": [None]}):
            err(self, call("POST", "/settlements", body, token=self.op, idem=key()), 422, "validation_failed")
        self.assertEqual(self.st([self.t("ada", "bob", 1, junk=1)]).status, 201)
        r = self.st([self.t("ada", "bob", 1)] * 32)
        self.assertEqual((r.status, len(r.json["payments"])), (201, 32))
        err(self, call("POST", "/settlements", {"transfers": [self.t("ada", "bob", 1)] * 33}, token=self.op, idem=key()), 422, "validation_failed")
        err(self, call("POST", "/settlements", raw=b"{", token=self.op, idem=key()), 400, "malformed_request")
        for bad in (self.t("ada", "bob", 0), self.t("ada", "bob", 1.5), self.t("ada", "bob", "1"), self.t("ada", "bob", 1, note=None),
                    self.t("ada", "bob", 1, note="x" * 201), self.t("ada", "bob", 1, visibility="Public"), {"from_handle": "ada", "amount": 1},
                    self.t("ada", "bob", 1000000001)):
            err(self, self.st([bad]), 422, "validation_failed")
        err(self, self.st([self.t(5, "bob", 1)]), 400, "malformed_request")

    def test_t3_entry_ordering(self):
        err(self, self.st([self.t("ada", "ghost", 1)]), 404, "not_found")
        err(self, self.st([self.t("ghost", "ada", 1)]), 404, "not_found")
        err(self, self.st([self.t("ada", "ada", 1)]), 422, "self_payment")
        err(self, self.st([self.t("ada", "bob", 5000), self.t("bob", "bob", 1)]), 422, "self_payment")
        err(self, self.st([self.t("ada", "bob", 5000), self.t("ada", "ghost", 1)]), 404, "not_found")
        err(self, self.st([self.t("ada", "ada", 1), self.t("ada", "ghost", 1)]), 422, "self_payment")
        err(self, self.st([self.t("ada", "ghost", 1), self.t("ada", "ada", 1)]), 404, "not_found")
        err(self, self.st([self.t("ada", "bob", 5000)]), 409, "insufficient_funds")
        self.assertEqual(self.bal(), [100, 0, 0, 0])

    def test_t4_net_semantics(self):
        r = self.st([self.t("ada", "bob", 100), self.t("bob", "cy", 50)])
        self.assertEqual(r.status, 201)
        self.assertEqual(self.bal(), [0, 50, 50, 0])
        r = self.st([self.t("ada", "bob", 100), self.t("bob", "ada", 100)])  # ada has 0 now, nets to zero
        self.assertEqual(r.status, 201)
        self.assertEqual(self.bal(), [0, 50, 50, 0])
        err(self, self.st([self.t("bob", "cy", 51)]), 409, "insufficient_funds")
        err(self, self.st([self.t("bob", "cy", 40), self.t("bob", "ada", 11)]), 409, "insufficient_funds")
        self.assertEqual(self.st([self.t("bob", "cy", 40), self.t("bob", "ada", 10), self.t("cy", "op", 90)]).status, 201)
        self.assertEqual(self.bal(), [10, 0, 0, 90])

    def test_t6_t7_response_and_visibility(self):
        k = key()
        r = self.st([self.t("ada", "bob", 60, note="a", visibility="private"), self.t("ada", "cy", 40), self.t("bob", "cy", 10, visibility="public")], idem=k)
        self.assertEqual(r.status, 201)
        j = r.json
        self.assertEqual(set(j), {"settlement_id", "committed_at", "payments"})
        self.assertRegex(j["committed_at"], TS_RE)
        self.assertEqual([(p["from_handle"], p["to_handle"], p["amount"], p["note"], p["visibility"]) for p in j["payments"]],
                         [("ada", "bob", 60, "a", "private"), ("ada", "cy", 40, "", "public"), ("bob", "cy", 10, "", "public")])
        for p in j["payments"]:
            self.assertEqual(set(p), PAYMENT_KEYS)
            self.assertEqual((p["settlement_id"], p["request_id"], p["created_at"]), (j["settlement_id"], None, j["committed_at"]))
        feed = lambda t: call("GET", "/activity", token=t).json["payments"]
        self.assertEqual(feed(self.op), [j["payments"][2], j["payments"][1]])
        self.assertEqual(feed(self.ada), [j["payments"][2], j["payments"][1], j["payments"][0]])
        self.assertEqual(feed(self.bob), [j["payments"][2], j["payments"][1], j["payments"][0]])
        self.assertEqual(feed(self.cy), [j["payments"][2], j["payments"][1]])
        r2 = self.st([self.t("ada", "bob", 60, note="a", visibility="private"), self.t("ada", "cy", 40), self.t("bob", "cy", 10, visibility="public")], idem=k)
        self.assertEqual((r2.status, r2.json), (200, j))
        err(self, self.st([self.t("ada", "bob", 1)], idem=k), 409, "idempotency_key_reuse")
        p = pay(self.ada, "bob", 0 + 1)
        self.assertEqual(p.status, 409)  # ada is empty now
        q = pay(self.bob, "cy", 1).json
        self.assertIsNone(q["settlement_id"])
        self.assertEqual(call("GET", "/requests", token=self.op).json["requests"], [])

    def test_t5_failure_claims_nothing_and_concurrent(self):
        k = key()
        err(self, self.st([self.t("ada", "bob", 101)], idem=k), 409, "insufficient_funds")
        self.assertEqual(call("GET", "/activity", token=self.ada).json["payments"], [])
        self.assertEqual(self.st([self.t("ada", "bob", 100)], idem=k).status, 201)
        reset(fixture([user("ada", 1000), user("bob", 1000), user("cy", 1000), user("op", 0)], settlement_operator_ids=["u_op"]))
        op = login("op")
        names = ["ada", "bob", "cy"]

        def go(i):
            ts = [self.t(names[i % 3], names[(i + 1) % 3], 300 + i), self.t(names[(i + 1) % 3], names[(i + 2) % 3], 200 + i)]
            return call("POST", "/settlements", {"transfers": ts}, token=op, idem=key()).status
        with cf.ThreadPoolExecutor(50) as ex:
            sts = list(ex.map(go, range(50)))
        self.assertTrue(set(sts) <= {201, 409})
        bs = [me(login(h))["balance"] for h in names]
        self.assertEqual(sum(bs), 3000)
        self.assertGreaterEqual(min(bs), 0)
        total_moved = len(call("GET", "/activity?limit=200", token=op).json["payments"])
        self.assertEqual(total_moved, 2 * sts.count(201))


# ----------------------------------------------------------- export/import
class TestExportImport(unittest.TestCase):
    def build_world(self):
        reset(fixture(settlement_operator_ids=["u_cy"]))
        a, b, c = login("ada"), login("bob"), login("cy")
        self.keys = {}
        k = self.keys["pay"] = key()
        p = call("POST", "/payments", {"to_handle": "bob", "amount": 100, "note": "ünï 😀", "visibility": "private"}, token=a, idem=k)
        k = self.keys["req"] = key()
        q = call("POST", "/requests", {"payer_handle": "ada", "amount": 50, "note": "taxi"}, token=b, idem=k)
        k = self.keys["pr"] = key()
        call("POST", "/requests/%s/pay" % q.json["request_id"], {"visibility": "public"}, token=a, idem=k)
        k = self.keys["split"] = key()
        call("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "bob", "cy"]}, token=a, idem=k)
        k = self.keys["st"] = key()
        call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 7}, {"from_handle": "bob", "to_handle": "cy", "amount": 3}]},
             token=c, idem=k)
        err(self, pay(c, "ada", 999999), 409, "insufficient_funds")
        self.failed_key = key()
        err(self, call("POST", "/payments", {"to_handle": "ada", "amount": 99999}, token=c, idem=self.failed_key), 409, "insufficient_funds")
        self.toks = (a, b, c)
        return p, q

    def snapshot(self, toks, base=None):
        out = []
        for t in toks:
            out.append((call("GET", "/me", token=t, base=base).json, call("GET", "/activity?limit=200", token=t, base=base).json,
                        call("GET", "/requests?limit=200", token=t, base=base).json))
        return out

    def test_x1_x2_x5_x6_x7_roundtrip(self):
        self.build_world()
        before = self.snapshot(self.toks)
        e = call("GET", "/_test/export")
        self.assertEqual(e.status, 200)
        doc = e.json
        self.assertEqual((doc["track"], doc["format_version"], isinstance(doc["state"], dict)), ("pocketful", 1, True))
        # snapshot independence: later writes do not alter the returned export
        pay(self.toks[0], "bob", 1)
        self.assertEqual(json.loads(e.raw), doc)
        reset(fixture([user("zed", 1)]))
        for path in (1, 2):  # import twice: replacement, not merge
            self.assertEqual(call("POST", "/_test/import", raw=e.raw).status, 204)
            self.assertEqual(self.snapshot(self.toks), before)
        err(self, call("GET", "/me", token="nope"), 401, "unauthenticated")
        self.assertEqual(call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}).status, 200)
        err(self, call("POST", "/auth/login", {"email": "zed@example.com", "password": "correct horse"}), 401, "unauthenticated")
        # idempotency preserved
        a, b, c = self.toks
        r = call("POST", "/payments", {"to_handle": "bob", "amount": 100, "note": "ünï 😀", "visibility": "private"}, token=a, idem=self.keys["pay"])
        self.assertEqual(r.status, 200)
        self.assertEqual(r.json["note"], "ünï 😀")
        r = call("POST", "/requests", {"payer_handle": "ada", "amount": 50, "note": "taxi"}, token=b, idem=self.keys["req"])
        self.assertEqual((r.status, r.json["request_id"] is not None), (200, True))
        rr = call("POST", "/requests/%s/pay" % r.json["request_id"], {"visibility": "public"}, token=a, idem=self.keys["pr"])
        self.assertEqual((rr.status, rr.json["request_id"]), (200, r.json["request_id"]))
        err(self, call("POST", "/requests/%s/pay" % r.json["request_id"], {}, token=a, idem=self.keys["pr"]), 409, "idempotency_key_reuse")
        self.assertEqual(call("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "bob", "cy"]}, token=a, idem=self.keys["split"]).status, 200)
        s = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 7}, {"from_handle": "bob", "to_handle": "cy", "amount": 3}]},
                 token=c, idem=self.keys["st"])
        self.assertEqual(s.status, 200)
        self.assertEqual(len({p["settlement_id"] for p in s.json["payments"]}), 1)
        self.assertEqual(call("POST", "/payments", {"to_handle": "ada", "amount": 99999}, token=c, idem=self.failed_key).status, 409)  # still short, still first-use
        # operator permission preserved
        self.assertEqual(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}, token=c, idem=key()).status, 201)
        err(self, call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}, token=a, idem=key()), 403, "forbidden")
        # settlement membership visible in feed
        self.assertTrue(any(p["settlement_id"] for p in call("GET", "/activity", token=a).json["payments"]))
        # new ids do not collide
        ids = {p["payment_id"] for t in self.toks for p in call("GET", "/activity?limit=200", token=t).json["payments"]}
        n = pay(a, "bob", 1).json["payment_id"]
        self.assertNotIn(n, ids)
        nr = ask(a, "bob", 1).json["request_id"]
        self.assertNotIn(nr, {x["request_id"] for x in call("GET", "/requests?limit=200", token=a).json["requests"] if x["request_id"] != nr})
        # reset clears imported state
        reset()
        err(self, call("GET", "/me", token=a), 401, "unauthenticated")
        self.assertEqual(call("GET", "/activity", token=login("ada")).json["payments"], [])
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 100, "note": "ünï 😀", "visibility": "private"},
                              token=login("ada"), idem=self.keys["pay"]).status, 201)

    def test_x1_export_during_writes_is_consistent(self):
        reset(fixture([user("ada", 5000), user("bob", 5000)]))
        a = login("ada")
        stop = []
        exports = []

        def writer(i):
            while not stop:
                pay(a, "bob", 3)
                pay(login("bob"), "ada", 2) if False else None

        def exporter():
            for _ in range(8):
                exports.append(call("GET", "/_test/export").raw)
        with cf.ThreadPoolExecutor(12) as ex:
            ws = [ex.submit(writer, i) for i in range(10)]
            ex.submit(exporter).result()
            stop.append(1)
            for w in ws:
                w.result()
        for raw in exports:
            doc = json.loads(raw)
            bal = sum(int(u["balance"]) for u in doc["state"]["users"])
            self.assertEqual(bal, 10000)
            moved = sum(p["amount"] for p in doc["state"]["payments"])
            ada = [u for u in doc["state"]["users"] if u["id"] == "u_ada"][0]
            self.assertEqual(int(ada["balance"]), 5000 - moved)
        reset()
        call("POST", "/_test/import", raw=exports[-1])
        self.assertEqual(sum(me(login(h))["balance"] for h in ("ada", "bob")), 10000)

    def test_x4_invalid_imports_leave_state(self):
        self.build_world()
        before = self.snapshot(self.toks)
        good = call("GET", "/_test/export").json
        err(self, call("POST", "/_test/import", raw=b"{nope"), 400, "malformed_request")
        err(self, call("POST", "/_test/import", raw=b"[]"), 400, "malformed_request")
        bads = [{}, {"track": "pocketful", "format_version": 1}, dict(good, track="other"), dict(good, format_version=2), dict(good, format_version="1"),
                {k: v for k, v in good.items() if k != "track"}, dict(good, state=None), dict(good, state={}), dict(good, state=[]),
                dict(good, state=dict(good["state"], users="x")), dict(good, state=dict(good["state"], users=[{"id": "x"}])),
                dict(good, state=dict(good["state"], tokens=[{"token": "t", "user_id": "ghost"}])),
                dict(good, state=dict(good["state"], payments=[{"payment_id": 5}])),
                dict(good, state=dict(good["state"], currency=5)),
                dict(good, state={k: v for k, v in good["state"].items() if k != "idempotency"})]
        for b in bads:
            err(self, call("POST", "/_test/import", b), 422, "validation_failed")
        self.assertEqual(self.snapshot(self.toks), before)

    @unittest.skipUnless(BASE_B, "BASE_URL_B (second container) not set")
    def test_x3_import_into_other_container(self):
        self.build_world()
        before = self.snapshot(self.toks)
        e = call("GET", "/_test/export")
        reset(fixture([user("other", 5)]), base=BASE_B)
        self.assertEqual(call("POST", "/_test/import", raw=e.raw, base=BASE_B).status, 204)
        self.assertEqual(self.snapshot(self.toks, base=BASE_B), before)
        a = self.toks[0]
        r = call("POST", "/payments", {"to_handle": "bob", "amount": 100, "note": "ünï 😀", "visibility": "private"}, token=a, idem=self.keys["pay"], base=BASE_B)
        self.assertEqual(r.status, 200)
        self.assertEqual(call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}, base=BASE_B).status, 200)
        err(self, call("POST", "/auth/login", {"email": "other@example.com", "password": "correct horse"}, base=BASE_B), 401, "unauthenticated")


class TestHandleBoundaries(Base):
    def test_r9_handles(self):
        reset(fixture([user("a_1", 10), user("z" * 20, 10), user("bob", 0)]))
        a = login("a_1")
        self.assertEqual(pay(a, "z" * 20, 5).status, 201)
        err(self, pay(a, "z" * 21, 5), 404, "not_found")
        r = call("POST", "/auth/signup", {"email": "n@example.com", "password": "password1", "display_name": "N"})
        self.assertEqual(me(r.json["token"])["balance"], 0)
        self.assertEqual(pay(a, "n", 5).status, 201)
        self.assertEqual(me(r.json["token"])["balance"], 5)
        self.assertEqual(ask(a, "n", 5).status, 201)
        self.assertEqual(call("GET", "/requests", token=r.json["token"]).json["requests"][0]["payer_handle"], "n")


if __name__ == "__main__":
    unittest.main()
