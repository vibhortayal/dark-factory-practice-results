"""§7 idempotency on POST /reservations (the moves path is covered again in c_moves)."""
import json as _json

from vlib import *


@check("D3", "§5/§7 'Header absent or empty -> 400 missing_idempotency_key'", "POST /reservations and /reservation-moves without / with empty key")
def _():
    reset(fixture(reservations=[seed("res_s1", "SEED01", "u_ada", "r_anker", "t_1", f"{FUT}T19:00")]))
    ada = tok("u_ada")
    expect(call("POST", "/reservations", json_body=body(), token=ada), 400, "missing_idempotency_key")
    expect(call("POST", "/reservations", json_body=body(), token=ada, key=""), 400, "missing_idempotency_key")
    mv = {"moves": [{"reference": "SEED01", "table_id": "t_3"}]}
    expect(call("POST", "/reservation-moves", json_body=mv, token=ada), 400, "missing_idempotency_key")
    expect(call("POST", "/reservation-moves", json_body=mv, token=ada, key=""), 400, "missing_idempotency_key")
    l = my_list(ada)
    assert len(l) == 1 and l[0]["table_id"] == "t_1", l


@check("D12", "§5 shared ranges 'Idempotency-Key 1 to 255 characters, otherwise 422' / §7", "1 and 255 accepted, 256 -> 422, on both keyed paths")
def _():
    reset(fixture(reservations=[seed("res_s1", "SEED01", "u_ada", "r_anker", "t_1", f"{FUT}T19:00")]))
    ada = tok("u_ada")
    expect(book(ada, local=f"{FUT}T18:00", key="k"), 201)
    expect(book(ada, local=f"{FUT}T19:30", key="K" * 255), 201)
    expect(book(ada, local=f"{FUT}T21:00", key="K" * 256), 422, "validation_failed")
    expect(book(ada, local=f"{FUT}T21:00", key="K" * 1000), 422, "validation_failed")
    assert len(my_list(ada)) == 3
    expect(moves(ada, [{"reference": "SEED01", "table_id": "t_3"}], key="M" * 256), 422, "validation_failed")
    assert expect(get_res(ada, "SEED01"), 200).json["table_id"] == "t_1"
    expect(moves(ada, [{"reference": "SEED01", "table_id": "t_3"}], key="M" * 255), 201)
    expect(moves(ada, [{"reference": "SEED01", "table_id": "t_1"}], key="m"), 201)


@check("F1F2", "§7 'First use -> 201' / 'Replay: same key, same body -> 200, body identical ... as a JSON value'", "replay returns the original and changes nothing")
def _():
    reset()
    ada = tok("u_ada")
    k = newkey()
    a = expect(book(ada, key=k), 201)
    for _i in range(3):
        b = expect(book(ada, key=k), 200)
        assert b.json == a.json, (a.json, b.json)
    assert len(my_list(ada)) == 1
    # second session of the same user: the key is scoped to the user, not the token
    b = expect(book(tok("u_ada"), key=k), 200)
    assert b.json == a.json


@check("F3", "§7 '\"Same body\" means the same JSON value after parsing - key order and whitespace do not matter'", "reordered / re-spaced body is a replay")
def _():
    reset()
    ada = tok("u_ada")
    k = newkey()
    a = expect(book(ada, key=k), 201)
    raw = ('{\n  "party_size": 2,\n\t"starts_at_local":   "%sT19:00", "table_id":"t_2",\r\n "restaurant_id" : "r_anker" }\n' % FUT).encode()
    b = expect(call("POST", "/reservations", raw=raw, token=ada, key=k), 200)
    assert b.json == a.json
    assert len(my_list(ada)) == 1


@check("F4", "§7 'Same key, different body -> 409 idempotency_key_reuse' / 'even when that new body would otherwise be invalid'",
       "different valid body, invalid bodies, wrong types, unknown ids, extra unknown field")
def _():
    reset()
    ada = tok("u_ada")
    k = newkey()
    a = expect(book(ada, key=k), 201)
    variants = [body(tid="t_3"), body(party=3), body(local=f"{FUT}T20:30"), body(party="x"), body(party=0),
                body(tid="t_nope"), body(rid="r_nope"), body(local="garbage"), body(tid=5), {}, {"restaurant_id": "r_anker"},
                body(note="unknown field makes a different JSON value"), body(local=f"{FUT}T19:15"), body(party=99)]
    for v in variants:
        expect(call("POST", "/reservations", json_body=v, token=ada, key=k), 409, "idempotency_key_reuse")
    assert len(my_list(ada)) == 1
    expect(cancel(ada, a.json["reference"]), 200)  # resource changed: still a reuse, and the replay still works
    expect(call("POST", "/reservations", json_body=body(tid="t_3"), token=ada, key=k), 409, "idempotency_key_reuse")
    assert expect(book(ada, key=k), 200).json == a.json


@check("F5", "§7 'The key is scoped to the authenticated user ... no interaction between them'", "two users, one key string")
def _():
    reset()
    ada, bob = tok("u_ada"), tok("u_bob")
    k = "shared-key"
    a = expect(book(ada, tid="t_2", key=k), 201)
    b = expect(call("POST", "/reservations", json_body=body(tid="t_3"), token=bob, key=k), 201)  # different body: no 409
    assert b.json["reference"] != a.json["reference"]
    assert expect(book(ada, tid="t_2", key=k), 200).json == a.json
    assert expect(call("POST", "/reservations", json_body=body(tid="t_3"), token=bob, key=k), 200).json == b.json
    # same key and same body as ada's, sent by a third user: a first use that meets the taken table
    expect(call("POST", "/auth/signup", json_body={"email": "cy@example.com", "password": "cy staple 77", "display_name": "Cy"}), 201)
    cy = login("cy@example.com", "cy staple 77")
    expect(book(cy, tid="t_2", key=k), 409, "table_unavailable")


@check("F6", "§7 'The same key with the same body on a different path is a different request, not a replay, and must succeed normally'",
       "one key and one body on POST /reservations then POST /reservation-moves")
def _():
    reset(fixture(reservations=[seed("res_s1", "SEED01", "u_ada", "r_anker", "t_1", f"{FUT}T19:00")]))
    ada = tok("u_ada")
    k = newkey()
    b = body(tid="t_2", moves=[{"reference": "SEED01", "table_id": "t_3"}])
    a = expect(call("POST", "/reservations", json_body=b, token=ada, key=k), 201).json
    assert_res_shape(a, table_id="t_2")
    m = expect(call("POST", "/reservation-moves", json_body=b, token=ada, key=k), 201).json
    assert [x["reference"] for x in m["reservations"]] == ["SEED01"] and m["reservations"][0]["table_id"] == "t_3", m
    assert expect(call("POST", "/reservations", json_body=b, token=ada, key=k), 200).json == a
    assert expect(call("POST", "/reservation-moves", json_body=b, token=ada, key=k), 200).json == m
    assert len(my_list(ada)) == 2


@check("F7", "§7 'Key reused after the original request failed with 4xx -> Treated as a first use'", "after 422, 404 and 409 failures; same and different body")
def _():
    reset()
    ada, bob = tok("u_ada"), tok("u_bob")
    k = newkey()
    expect(book(ada, party=9, key=k), 422, "party_exceeds_capacity")
    expect(book(ada, party=9, key=k), 422, "party_exceeds_capacity")
    expect(book(ada, tid="t_nope", key=k), 404, "not_found")
    expect(call("POST", "/reservations", json_body=body(party="x"), token=ada, key=k), 422, "validation_failed")
    first = expect(book(ada, key=k), 201)
    assert expect(book(ada, key=k), 200).json == first.json
    # 409 table_unavailable, then the same body succeeds once the table is free
    k2 = newkey()
    expect(book(bob, key=k2), 409, "table_unavailable")
    expect(cancel(ada, first.json["reference"]), 200)
    second = expect(book(bob, key=k2), 201)
    assert expect(book(bob, key=k2), 200).json == second.json
    assert len(my_list(bob)) == 1 and len(my_list(ada)) == 1


@check("F8", "§7 'A successful replay returns the original response, even after the resource changes or is cancelled. It makes no further state changes'",
       "replay after PATCH and after cancel")
def _():
    reset()
    ada, bob = tok("u_ada"), tok("u_bob")
    k = newkey()
    a = expect(book(ada, key=k), 201).json
    expect(patch(ada, a["reference"], {"table_id": "t_3", "party_size": 4}), 200)
    assert expect(book(ada, key=k), 200).json == a
    cur = expect(get_res(ada, a["reference"]), 200).json
    assert cur["table_id"] == "t_3" and cur["party_size"] == 4, cur
    expect(cancel(ada, a["reference"]), 200)
    assert expect(book(ada, key=k), 200).json == a
    assert expect(get_res(ada, a["reference"]), 200).json["status"] == "cancelled"
    assert len(my_list(ada)) == 1
    # the replay did not re-occupy t_2 or t_3
    expect(book(bob, tid="t_2"), 201)
    expect(book(bob, tid="t_3"), 201)


@check("F10", "§7 'After the body has been parsed as a JSON object and the caller authenticated, idempotency is resolved before endpoint-specific field validation'",
       "unparseable body with a used key is 400, unauthenticated is 401, otherwise 409")
def _():
    reset()
    ada = tok("u_ada")
    k = newkey()
    expect(book(ada, key=k), 201)
    expect(call("POST", "/reservations", raw=b'{"restaurant_id": ', token=ada, key=k), 400, "malformed_request")
    expect(call("POST", "/reservations", json_body=body(tid="t_3"), key=k), 401, "unauthenticated")
    expect(call("POST", "/reservations", json_body=body(party=True), token=ada, key=k), 409, "idempotency_key_reuse")


@check("F11", "§1 'Retries and rejected requests must not create duplicate or partial bookings'", "reservation count after a mix of failures and replays")
def _():
    reset()
    ada = tok("u_ada")
    k = newkey()
    ok = expect(book(ada, key=k), 201).json
    for b in [body(party=0), body(party=9), body(local=f"{FUT}T19:15"), body(local=f"{FUT}T23:00"), body(tid="zz"),
              body(local=f"{FUT}T19:30"), {}, body(tid=7)]:
        r = call("POST", "/reservations", json_body=b, token=ada, key=newkey())
        assert 400 <= r.status < 500, r
    for _i in range(5):
        expect(book(ada, key=k), 200)
    l = my_list(ada)
    assert [x["reference"] for x in l] == [ok["reference"]], l
    s = slots("r_anker", FUT, 2)
    assert s[f"{FUT}T20:30"]["available_table_ids"] == ["t_1", "t_2", "t_3"]
    assert s[f"{FUT}T19:00"]["available_table_ids"] == ["t_1", "t_3"]
