"""E. Authentication and handles."""
import json
import re

import pytest

from lib import GET, POST, PW, World, burst, call, check_payment, code_of, err, fixture, k, ok, soft, statuses, user

SECRET = "Pl41nt3xt-Marker-Zq9"


def signup(email, password="longenough1", display_name="New", **extra):
    return POST("/auth/signup", body={"email": email, "password": password, "display_name": display_name, **extra})


def test_e1_signup_shape_and_zero_balance():
    w = World(fixture(currency="BHD", minor=3))
    r = signup("newbie@example.com", display_name="Néw Bie 😀")
    j = ok(r, 201)
    assert set(j) >= {"user_id", "display_name", "token"}
    soft(set(j) == {"user_id", "display_name", "token"}, "signup-extra-keys", keys=sorted(j))
    assert j["display_name"] == "Néw Bie 😀" and isinstance(j["token"], str) and j["token"]
    assert isinstance(j["user_id"], str) and 1 <= len(j["user_id"]) <= 64
    me = ok(GET("/me", j["token"]), 200)
    assert me == {"user_id": j["user_id"], "display_name": "Néw Bie 😀", "handle": "newbie", "balance": 0,
                  "currency": "BHD", "minor_units": 3}
    # receives money and is asked for money immediately
    p = check_payment(ok(w.pay("ada", "newbie", 250), 201), to_user_id=j["user_id"], to_handle="newbie")
    q = w.new_request("ada", "newbie", 100, note="pay me back")
    assert q["payer_id"] == j["user_id"]
    assert ok(GET("/me", j["token"]), 200)["balance"] == 250
    assert [x["request_id"] for x in ok(GET("/requests?direction=incoming", j["token"]), 200)["requests"]] == [q["request_id"]]
    assert ok(POST(f"/requests/{q['request_id']}/pay", j["token"], {}, key=k()), 201)["amount"] == 100
    assert ok(POST("/payments", j["token"], {"to_handle": "bob", "amount": 150}, key=k()), 201)["from_handle"] == "newbie"
    err(POST("/payments", j["token"], {"to_handle": "bob", "amount": 1}, key=k()), 409, "insufficient_funds")
    assert p["payment_id"] in [x["payment_id"] for x in ok(GET("/activity", j["token"]), 200)["payments"]]
    # signup users are not operators
    err(POST("/settlements", j["token"], {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]},
             key=k()), 403, "forbidden")
    login = ok(POST("/auth/login", body={"email": "newbie@example.com", "password": "longenough1"}), 200)
    assert login["user_id"] == j["user_id"] and login["display_name"] == "Néw Bie 😀"


HANDLES = [
    ("A.B+c@x.io", "a_b_c"),
    ("mary-ann@example.com", "mary_ann"),
    ("UPPER9_x@example.com", "upper9_x"),
    ("abcdefghijklmnopqrstuvwxy@example.com", "abcdefghijklmnopqrst"),
    ("first.middle.last.name.long@example.com", "first_middle_last_na"),
    ("jürgen@example.com", "j_rgen"),
    ("o'neil!#$%&@example.com", "o_neil_____"),
    ("x@example.com", "x"),
    ("123@example.com", "123"),
    ("a..b@example.com", "a__b"),
    ("_under_@example.com", "_under_"),
    ("ÉCOLE@example.com", "_cole"),
]


@pytest.mark.parametrize("email,handle", HANDLES)
def test_e2_derived_handle(email, handle):
    World()
    j = ok(signup(email, handle="chosen_handle"), 201)
    me = ok(GET("/me", j["token"]), 200)
    assert me["handle"] == handle, f"{email} -> {me['handle']!r}, expected {handle!r}"
    assert re.fullmatch(r"[a-z0-9_]{1,20}", me["handle"])


def test_e3_email_taken():
    World()
    ok(signup("dup@example.com"), 201)
    err(signup("dup@example.com"), 409, "email_taken")
    err(signup("dup@example.com", password="otherpassword", display_name="Other"), 409, "email_taken")
    err(signup("ada@example.com"), 409, "email_taken")  # a seeded account's email
    ok(POST("/auth/login", body={"email": "dup@example.com", "password": "longenough1"}), 200)
    err(POST("/auth/login", body={"email": "dup@example.com", "password": "otherpassword"}), 401, "unauthenticated")


def test_e4_handle_taken_creates_no_account():
    w = World()
    first = ok(signup("a.b@x.io"), 201)
    r = signup("a_b@y.io")
    err(r, 409, "handle_taken")
    err(POST("/auth/login", body={"email": "a_b@y.io", "password": "longenough1"}), 401, "unauthenticated")
    err(signup("A+B@z.io"), 409, "handle_taken")
    err(signup("ada@other.example"), 409, "handle_taken")  # a seeded handle
    err(POST("/auth/login", body={"email": "ada@other.example", "password": "longenough1"}), 401, "unauthenticated")
    # truncation collision
    ok(signup("abcdefghijklmnopqrst_one@example.com"), 201)
    err(signup("abcdefghijklmnopqrst_two@example.com"), 409, "handle_taken")
    # the first account is untouched and money still sums up
    assert ok(GET("/me", first["token"]), 200)["handle"] == "a_b"
    w.assert_conserved()
    # the email of a failed signup is still free: nothing was created
    assert ok(GET("/me", w.t("ada")), 200)["handle"] == "ada"


def test_e5_password_and_email_rules():
    World()
    err(signup("p1@example.com", password="1234567"), 422, "validation_failed")
    err(signup("p1@example.com", password=""), 422, "validation_failed")
    err(POST("/auth/login", body={"email": "p1@example.com", "password": "1234567"}), 401, "unauthenticated")
    ok(signup("p1@example.com", password="12345678"), 201)
    ok(signup("p2@example.com", password="pässwörd"), 201)  # 8 characters, more bytes
    ok(signup("p3@example.com", password="x" * 100), 201)
    ok(POST("/auth/login", body={"email": "p3@example.com", "password": "x" * 100}), 200)
    for bad in ["nodomain", "@x.io", "a@", "", "@", "plain.address"]:
        err(signup(bad), 422, "validation_failed", repr(bad))
    # map clarification 2 (fix round 1): whitespace or control characters are not local@domain
    for bad in ["a b@example.com", "ws@exa mple.com", "nl\n@example.com", "tab\t@example.com", " lead@example.com",
                "trail@example.com ", "ctl\u0000@example.com", "cr@example.com\r",
                # fix round 2, Architect direction 5: Unicode categories Cc, Cf, Zs, Zl, Zp
                "del\u007f@example.com", "c1\u0085@example.com", "nbsp\u00a0@example.com", "zw\u200b@example.com",
                "ls@exa\u2028mple.com", "ps\u2029@example.com", "a@b\u0001c.com"]:
        err(signup(bad), 422, "validation_failed", repr(bad))
        err(POST("/auth/login", body={"email": bad, "password": "longenough1"}), (401, 422))
    ok(signup("empty.name@example.com", display_name=""), 201)  # an empty display_name stays accepted


def test_e6_login():
    w = World()
    j = ok(POST("/auth/login", body={"email": "ada@example.com", "password": PW}), 200)
    assert set(j) >= {"user_id", "display_name", "token"}
    assert j["user_id"] == "u_ada" and j["display_name"] == "Ada"
    assert ok(GET("/me", j["token"]), 200)["handle"] == "ada"
    err(POST("/auth/login", body={"email": "ada@example.com", "password": "wrong horse"}), 401, "unauthenticated")
    err(POST("/auth/login", body={"email": "ada@example.com", "password": PW + " "}), 401, "unauthenticated")
    err(POST("/auth/login", body={"email": "ada@example.com", "password": PW.upper()}), 401, "unauthenticated")
    err(POST("/auth/login", body={"email": "ghost@example.com", "password": PW}), 401, "unauthenticated")
    err(POST("/auth/login", body={"email": "ada", "password": PW}), (401, 422))
    err(POST("/auth/login", body={"email": "bob@example.com", "password": ""}), (401, 422))
    assert w.bal("ada") == 10000


def test_e7_multiple_tokens_all_valid():
    World()
    toks = [ok(POST("/auth/login", body={"email": "ada@example.com", "password": PW}), 200)["token"] for _ in range(5)]
    soft(len(set(toks)) == 5, "login-tokens-not-distinct", distinct=len(set(toks)))
    for t in toks:
        assert ok(GET("/me", t), 200)["handle"] == "ada"
    s = ok(signup("multi@example.com"), 201)
    l1 = ok(POST("/auth/login", body={"email": "multi@example.com", "password": "longenough1"}), 200)["token"]
    assert ok(GET("/me", s["token"]), 200) == ok(GET("/me", l1), 200)
    # all sessions act on the same wallet
    ok(POST("/payments", toks[0], {"to_handle": "bob", "amount": 100}, key=k()), 201)
    assert ok(GET("/me", toks[4]), 200)["balance"] == 9900
    rs = burst([lambda t=t: GET("/me", t) for t in toks * 10])
    assert statuses(rs) == {200: 50}


def test_e7_fifty_concurrent_logins_within_limit():
    World()
    rs = burst([lambda: POST("/auth/login", body={"email": "ada@example.com", "password": PW}) for _ in range(50)])
    assert statuses(rs) == {200: 50}
    assert max(r.elapsed_s for r in rs) <= 5.0, max(r.elapsed_s for r in rs)
    rs = burst([lambda i=i: POST("/auth/login", body={"email": "ada@example.com", "password": f"wrong{i}xxx"})
                for i in range(50)])
    assert statuses(rs) == {401: 50}


def test_e7_concurrent_signups():
    World()
    rs = burst([lambda: signup("race@example.com") for _ in range(20)])
    st = statuses(rs)
    assert st == {201: 1, 409: 19}, st
    assert all(code_of(r) in ("email_taken", "handle_taken") for r in rs if r.status_code == 409)
    rs = burst([lambda i=i: signup(f"racer_{i}@example.com") for i in range(50)])
    assert statuses(rs) == {201: 50}
    assert max(r.elapsed_s for r in rs) <= 5.0
    hs = {ok(GET("/me", r.json()["token"]), 200)["handle"] for r in rs}
    assert hs == {f"racer_{i}" for i in range(50)}
    assert len({r.json()["user_id"] for r in rs}) == 50
    # same derived handle, different emails, at once: exactly one account
    rs = burst([lambda i=i: signup(f"same.h@d{i}.example") for i in range(20)])
    assert statuses(rs) == {201: 1, 409: 19}
    assert all(code_of(r) == "handle_taken" for r in rs if r.status_code == 409)


def test_e9_no_plaintext_password_in_export():
    World(fixture(users=[user("ada", 5, password=SECRET), user("bob", 5)]))
    ok(signup("exp@example.com", password=SECRET + "-signup"), 201)
    ok(POST("/auth/login", body={"email": "ada@example.com", "password": SECRET}), 200)
    r = GET("/_test/export")
    assert r.status_code == 200
    text = r.text
    assert SECRET not in text, "plaintext password found in export"
    assert json.dumps(SECRET)[1:-1] not in text
    assert PW not in text, "plaintext password of bob found in export"


def test_e10_handle_stable():
    w = World()
    j = ok(signup("Stay.Put@example.com", display_name="S"), 201)
    assert ok(GET("/me", j["token"]), 200)["handle"] == "stay_put"
    ok(w.pay("ada", "stay_put", 10), 201)
    w.new_request("stay_put" if False else "ada", "stay_put", 5)
    ok(POST("/auth/login", body={"email": "Stay.Put@example.com", "password": "longenough1"}), 200)
    assert ok(GET("/me", j["token"]), 200)["handle"] == "stay_put"
    assert w.me("ada")["handle"] == "ada"
