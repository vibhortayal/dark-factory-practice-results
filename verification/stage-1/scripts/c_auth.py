"""§6 authentication and the §5 general error table."""
from vlib import *

SU = {"email": "new@example.com", "password": "correct horse", "display_name": "New"}


def signup(**over):
    b = dict(SU)
    b.update(over)
    return call("POST", "/auth/signup", json_body=b)


@check("E1", "§6 POST /auth/signup", "201 {user_id, display_name, token}; token usable at once")
def _():
    reset()
    j = expect(signup(), 201).json
    assert isinstance(j["user_id"], str) and j["display_name"] == "New" and isinstance(j["token"], str) and j["token"], j
    assert my_list(j["token"]) == []
    expect(book(j["token"]), 201)


@check("E2", "§6 POST /auth/login", "200 {user_id, display_name, token} for a signed-up account")
def _():
    reset()
    s = expect(signup(), 201).json
    j = expect(call("POST", "/auth/login", json_body={"email": SU["email"], "password": SU["password"]}), 200).json
    assert j["user_id"] == s["user_id"] and j["display_name"] == "New" and j["token"], j
    expect(call("GET", "/reservations", token=j["token"]), 200)


@check("E3", "§6 'Email already registered -> 409 email_taken'", "duplicate of a signed-up and of a seeded email")
def _():
    reset()
    expect(signup(), 201)
    expect(signup(password="another password", display_name="Other"), 409, "email_taken")
    expect(signup(email=EMAIL["u_ada"]), 409, "email_taken")
    # the first account is untouched
    expect(call("POST", "/auth/login", json_body={"email": SU["email"], "password": SU["password"]}), 200)
    expect(call("POST", "/auth/login", json_body={"email": SU["email"], "password": "another password"}), 401, "unauthenticated")


@check("E4", "§6 'Password shorter than 8 characters -> 422'", "7 characters rejected, 8 accepted, empty rejected")
def _():
    reset()
    expect(signup(password="1234567"), 422, "validation_failed")
    expect(signup(password=""), 422, "validation_failed")
    expect(call("POST", "/auth/login", json_body={"email": SU["email"], "password": "1234567"}), 401, "unauthenticated")
    expect(signup(password="12345678"), 201)
    expect(call("POST", "/auth/login", json_body={"email": SU["email"], "password": "12345678"}), 200)


@check("E5", "§6 'email not of the form local@domain -> 422'", "no @, empty local part, empty domain, empty string")
def _():
    reset()
    for e in ["nodomain", "@example.com", "local@", "", "@"]:
        expect(signup(email=e), 422, "validation_failed")
    expect(signup(email="a@b"), 201)


@check("E6", "§5 validation_failed 'A required field ... is missing' / malformed_request 'a field of the wrong JSON type'",
       "signup/login: missing field -> 422; wrong JSON type -> 400; unparseable -> 400")
def _():
    reset()
    for f in ("email", "password", "display_name"):
        b = dict(SU)
        del b[f]
        expect(call("POST", "/auth/signup", json_body=b), 422, "validation_failed")
    for f in ("email", "password"):
        b = {"email": EMAIL["u_ada"], "password": PW["u_ada"]}
        del b[f]
        expect(call("POST", "/auth/login", json_body=b), 422, "validation_failed")
    for f, v in (("email", 17), ("password", 1234567890), ("display_name", 5), ("email", ["a@b.c"]),
                 ("password", True), ("display_name", {"a": 1})):
        expect(signup(**{f: v}), 400, "malformed_request")
    for f, v in (("email", 17), ("password", 1234567890)):
        b = {"email": EMAIL["u_ada"], "password": PW["u_ada"]}
        b[f] = v
        expect(call("POST", "/auth/login", json_body=b), 400, "malformed_request")
    for path in ("/auth/signup", "/auth/login"):
        expect(call("POST", path, raw=b'{"email": "a@b.c", '), 400, "malformed_request")
        expect(call("POST", path, raw=b"not json"), 400, "malformed_request")
    # nothing was created by the rejected signups
    expect(call("POST", "/auth/login", json_body={"email": SU["email"], "password": SU["password"]}), 401, "unauthenticated")


@check("E7", "§6 'Wrong password or unknown email on login -> 401 unauthenticated'", "both cases")
def _():
    reset()
    expect(call("POST", "/auth/login", json_body={"email": EMAIL["u_ada"], "password": "wrong password"}), 401, "unauthenticated")
    expect(call("POST", "/auth/login", json_body={"email": "nobody@example.com", "password": "correct horse"}), 401, "unauthenticated")
    expect(call("POST", "/auth/login", json_body={"email": EMAIL["u_ada"], "password": PW["u_bob"]}), 401, "unauthenticated")


@check("E8", "§6 exceptions list / §8 'public - no bearer token'", "public endpoints answer without a token")
def _():
    reset()
    expect(call("GET", "/health"), 200)
    expect(call("GET", "/restaurants"), 200)
    expect(call("GET", "/restaurants/r_anker"), 200)
    expect(avail("r_anker", FUT, 2), 200)
    expect(call("GET", "/_test/export"), 200)


@check("E9", "§5 401 'Missing, malformed or unknown bearer token' / §6 'Every other endpoint requires a bearer token'",
       "each protected endpoint x {missing, wrong scheme, no token after Bearer, unknown token} -> 401 unauthenticated")
def _():
    reset(fixture(reservations=[seed("res_s1", "SEED01", "u_ada", "r_anker", "t_2", f"{FUT}T19:00")]))
    eps = [("GET", "/reservations", None), ("POST", "/reservations", body(tid="t_3")),
           ("GET", "/reservations/SEED01", None), ("PATCH", "/reservations/SEED01", {"party_size": 1}),
           ("POST", "/reservations/SEED01/cancel", None),
           ("POST", "/reservation-moves", {"moves": [{"reference": "SEED01", "table_id": "t_3"}]})]
    auths = [None, "Token abc", "Bearer", "Bearer not-a-real-token", "Basic dTpw", "not-a-real-token"]
    for m, p, b in eps:
        for a in auths:
            h = {"Idempotency-Key": newkey()}
            if a is not None:
                h["Authorization"] = a
            r = call(m, p, headers=h) if b is None else call(m, p, json_body=b, headers=h)
            expect(r, 401, "unauthenticated")
    ada = tok("u_ada")
    g = expect(get_res(ada, "SEED01"), 200).json
    assert g["status"] == "confirmed" and g["table_id"] == "t_2" and g["party_size"] == 2, g
    assert len(my_list(ada)) == 1


@check("E10", "§6 'Tokens do not expire. An account may have multiple valid tokens and concurrent sessions'", "several tokens valid together")
def _():
    reset()
    s = expect(signup(), 201).json
    toks = [s["token"]] + [login(SU["email"], SU["password"]) for _ in range(3)]
    for t in toks:
        expect(call("GET", "/reservations", token=t), 200)
    made = book_ok(toks[0])
    for t in toks:
        assert [x["reference"] for x in my_list(t)] == [made["reference"]]


@check("E11", "§6 'Plaintext password storage is not permitted'", "no plaintext password in the export document (code read covers the hash function)")
def _():
    reset(fixture(users=[user("u_ada", password="Zq7-plain-SECRET-ada"), user("u_bob")]))
    expect(signup(password="Zq7-plain-SECRET-new"), 201)
    text = expect(call("GET", "/_test/export"), 200).text
    assert "Zq7-plain-SECRET" not in text, "plaintext password found in export"
    expect(call("POST", "/auth/login", json_body={"email": EMAIL["u_ada"], "password": "Zq7-plain-SECRET-ada"}), 200)


@check("B9a", "§3.4 'Unknown fields in a request body are ignored'", "signup and login with extra fields")
def _():
    reset()
    expect(signup(role="admin", extra={"a": [1]}), 201)
    expect(call("POST", "/auth/login", json_body={"email": SU["email"], "password": SU["password"], "remember": True}), 200)


@check("D6", "§5 404 not_found / every 4xx carries the envelope", "unknown resources -> 404 not_found; unknown routes and methods answer 4xx with the envelope")
def _():
    reset()
    ada = tok("u_ada")
    expect(call("GET", "/restaurants/r_nope"), 404, "not_found")
    expect(get_res(ada, "NOPE99"), 404, "not_found")
    expect(cancel(ada, "NOPE99"), 404, "not_found")
    expect(patch(ada, "NOPE99", {"party_size": 2}), 404, "not_found")
    for m, p in [("GET", "/nope"), ("GET", "/"), ("DELETE", "/reservations/NOPE99"), ("PUT", "/health"),
                 ("POST", "/restaurants"), ("GET", "/auth/login"), ("GET", "/reservation-moves")]:
        r = call(m, p, token=ada)
        assert 400 <= r.status < 500, r
        assert isinstance(r.json.get("error", {}).get("code"), str), r
