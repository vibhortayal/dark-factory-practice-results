"""§10 export and import. Uses a second, independent container (TK_BASE2)."""
import copy

from vlib import *


def need_b():
    assert BASE2, "TK_BASE2 (second container) is not set - cross-container import cannot be checked"
    return BASE2


def build(base=None):
    """A state with every kind of record §10 lists. Returns handles for later comparison."""
    sv = [seed("res_s1", "SEED01", "u_ada", "r_anker", "t_1", f"{FUT}T19:00"),
          seed("res_s2", "SEED02", "u_ada", "r_anker", "t_3", f"{FUT}T21:00")]
    reset(fixture(reservations=sv), base=base)
    st = {"tok": {}, "keys": {}, "resp": {}, "body": {}}
    st["tok"]["ada"] = tok("u_ada", base=base)
    st["tok"]["ada2"] = tok("u_ada", base=base)
    st["tok"]["bob"] = tok("u_bob", base=base)
    su = expect(call("POST", "/auth/signup", json_body={"email": "carol@example.com", "password": "carol pass 1",
                                                        "display_name": "Carol"}, base=base), 201).json
    st["tok"]["carol"] = su["token"]
    st["carol_id"] = su["user_id"]
    T = st["tok"]
    # keyed create
    st["keys"]["create"] = newkey()
    st["body"]["create"] = body(tid="t_2", local=f"{FUT}T19:00", party=4)
    st["resp"]["create"] = expect(call("POST", "/reservations", json_body=st["body"]["create"], token=T["ada"],
                                       key=st["keys"]["create"], base=base), 201).json
    # a cancelled booking and an amended one
    b = book_ok(T["bob"], tid="t_3", local=f"{FUT}T18:00", base=base)
    expect(cancel(T["bob"], b["reference"], base=base), 200)
    c = book_ok(T["carol"], tid="t_2", local=f"{FUT2}T19:00", base=base)
    expect(patch(T["carol"], c["reference"], {"party_size": 3, "table_id": "t_3"}, base=base), 200)
    # keyed batch (swap-like move)
    st["keys"]["moves"] = newkey()
    st["body"]["moves"] = [{"reference": "SEED01", "table_id": "t_3"}, {"reference": "SEED02", "table_id": "t_1"}]
    st["resp"]["moves"] = expect(moves(T["ada"], st["body"]["moves"], key=st["keys"]["moves"], base=base), 201).json
    # failed keyed requests on both paths
    st["keys"]["failed"] = newkey()
    expect(call("POST", "/reservations", json_body=body(tid="t_1", local=f"{FUT2}T21:00", party=9), token=T["ada"], key=st["keys"]["failed"], base=base), 422, "party_exceeds_capacity")
    st["keys"]["failed_moves"] = newkey()
    expect(moves(T["ada"], [{"reference": "SEED01", "party_size": 99}], key=st["keys"]["failed_moves"], base=base), 422, "party_exceeds_capacity")
    return st


def export(base=None):
    r = expect(call("GET", "/_test/export", base=base), 200)
    return r.json


def do_import(doc, base=None):
    r = call("POST", "/_test/import", json_body=doc, base=base)
    expect(r, 204)
    assert r.content == b"", r
    return r


@check("K1", "§10 'Return 200 from export with a JSON object containing track: \"tablekeeper\", format_version: 1 and state (an implementation-defined JSON object)'",
       "export document shape; unauthenticated; read-only")
def _():
    st = build()
    before = observe(st["tok"], dates=(FUT, FUT2))
    e = export()
    assert isinstance(e, dict) and e.get("track") == "tablekeeper" and e.get("format_version") == 1 \
        and type(e.get("format_version")) is int and isinstance(e.get("state"), dict), str(e)[:300]
    export()
    assert observe(st["tok"], dates=(FUT, FUT2)) == before, "export changed state"


@check("K2K4K9", "§10 'Import takes that entire object and atomically replaces the service's state, returning 204 ... No dependency on the source process' / 'Preserve accounts and hashed-password login, existing bearer tokens, fixture configuration, reservations, references'",
       "export from container A, import into container B: tokens, logins, restaurants, availability and every reservation identical")
def _():
    b = need_b()
    st = build()
    T = st["tok"]
    before = observe(T, dates=(FUT, FUT2, PAST))
    e = export()
    # B starts with unrelated data that must disappear
    reset(fixture(users=[user("u_old", "old@example.com", "old password")],
                  restaurants=[restaurant("r_old", "Old", tables=[table("o_1", 4)])],
                  reservations=[seed("res_o", "OLDREF", "u_old", "r_old", "o_1", f"{FUT}T19:00")]), base=b)
    old_tok = login("old@example.com", "old password", base=b)
    old_key = newkey()
    expect(book(old_tok, "r_old", "o_1", f"{FUT}T21:00", key=old_key, base=b), 201)
    do_import(e, base=b)
    after = observe(T, base=b, dates=(FUT, FUT2, PAST))
    for k in before:
        assert after[k] == before[k], f"differs after import: {k}\n A: {before[k]}\n B: {after[k]}"
    for k, t in T.items():
        assert before["list:" + k][0] == 200
    # hashed-password login for seeded and signed-up accounts
    j = expect(call("POST", "/auth/login", json_body={"email": EMAIL["u_ada"], "password": PW["u_ada"]}, base=b), 200).json
    assert j["user_id"] == "u_ada"
    j = expect(call("POST", "/auth/login", json_body={"email": "carol@example.com", "password": "carol pass 1"}, base=b), 200).json
    assert j["user_id"] == st["carol_id"]
    expect(call("POST", "/auth/login", json_body={"email": EMAIL["u_ada"], "password": "wrong password"}, base=b), 401, "unauthenticated")
    expect(call("POST", "/auth/signup", json_body={"email": "carol@example.com", "password": "carol pass 1", "display_name": "C"}, base=b), 409, "email_taken")
    # K3: replacement, not merge
    expect(call("GET", "/reservations", token=old_tok, base=b), 401, "unauthenticated")
    expect(call("POST", "/auth/login", json_body={"email": "old@example.com", "password": "old password"}, base=b), 401, "unauthenticated")
    expect(call("GET", "/restaurants/r_old", base=b), 404, "not_found")
    expect(get_res(T["ada"], "OLDREF", base=b), 404, "not_found")
    # K3: repeating the import duplicates nothing
    do_import(e, base=b)
    again = observe(T, base=b, dates=(FUT, FUT2, PAST))
    assert again == after, "second import changed the state"
    # K5 / L15: completed idempotent requests and their original responses
    r = call("POST", "/reservations", json_body=st["body"]["create"], token=T["ada"], key=st["keys"]["create"], base=b)
    assert expect(r, 200).json == st["resp"]["create"], (r.json, st["resp"]["create"])
    r = moves(T["ada2"], st["body"]["moves"], key=st["keys"]["moves"], base=b)
    assert expect(r, 200).json == st["resp"]["moves"], (r.json, st["resp"]["moves"])
    expect(call("POST", "/reservations", json_body=body(tid="t_1", local=f"{FUT2}T21:00"), token=T["ada"],
                key=st["keys"]["create"], base=b), 409, "idempotency_key_reuse")
    expect(moves(T["ada"], [{"reference": "SEED01"}], key=st["keys"]["moves"], base=b), 409, "idempotency_key_reuse")
    assert observe(T, base=b, dates=(FUT, FUT2, PAST)) == after, "replays changed state on B"
    # K6: failed request keys remain reusable
    n = expect(call("POST", "/reservations", json_body=body(tid="t_1", local=f"{FUT2}T21:00"), token=T["ada"],
                    key=st["keys"]["failed"], base=b), 201).json
    expect(moves(T["ada"], [{"reference": "SEED01", "party_size": 3}], key=st["keys"]["failed_moves"], base=b), 201)
    # identities are not regenerated or reissued: the new booking collides with nothing imported
    known = [x for k in T for x in before["list:" + k][1]["reservations"]]
    assert n["reference"] not in [x["reference"] for x in known] and n["reservation_id"] not in [x["reservation_id"] for x in known], n
    nu = expect(call("POST", "/auth/signup", json_body={"email": "dora@example.com", "password": "dora pass 1", "display_name": "D"}, base=b), 201).json
    assert nu["user_id"] not in ("u_ada", "u_bob", st["carol_id"]) and nu["token"] not in T.values(), nu
    assert_no_overlap(list(T.values()), base=b)
    # source container A is unaffected by anything done on B
    assert observe(T, dates=(FUT, FUT2, PAST)) == before


@check("K8", "§10 'Export is an atomic, read-only snapshot; subsequent source writes do not change it' / 'Reset continues to clear all state, including imported state'",
       "writes after export, then import of the earlier export restores the earlier state on the same container; reset afterwards clears it")
def _():
    st = build()
    T = st["tok"]
    before = observe(T, dates=(FUT, FUT2))
    e = export()
    frozen = copy.deepcopy(e)
    later = book_ok(T["bob"], tid="t_2", local=f"{FUT}T21:00")
    expect(cancel(T["ada"], st["resp"]["create"]["reference"]), 200)
    late_user = expect(call("POST", "/auth/signup", json_body={"email": "late@example.com", "password": "late pass 1", "display_name": "L"}), 201).json
    late_key = newkey()
    expect(book(T["bob"], tid="t_1", local=f"{FUT2}T18:00", key=late_key), 201)
    assert observe(T, dates=(FUT, FUT2)) != before
    assert e == frozen
    reset(fixture(users=[], restaurants=[], reservations=[]))
    expect(call("GET", "/reservations", token=T["ada"]), 401, "unauthenticated")
    do_import(e)
    assert observe(T, dates=(FUT, FUT2)) == before, "state after import differs from the state at export time"
    expect(get_res(T["bob"], later["reference"]), 404, "not_found")
    expect(call("GET", "/reservations", token=late_user["token"]), 401, "unauthenticated")
    expect(call("POST", "/auth/login", json_body={"email": "late@example.com", "password": "late pass 1"}), 401, "unauthenticated")
    # a key completed only after the export is unknown again: different body is a first use
    expect(book(T["bob"], tid="t_1", local=f"{FUT2}T19:30", key=late_key), 201)
    assert expect(call("POST", "/reservations", json_body=st["body"]["create"], token=T["ada"], key=st["keys"]["create"]), 200).json == st["resp"]["create"]
    # K10: reset clears imported state, tokens and keys
    reset()
    for t in T.values():
        expect(call("GET", "/reservations", token=t), 401, "unauthenticated")
    ada = tok("u_ada")
    assert my_list(ada) == []
    expect(call("POST", "/reservations", json_body=body(tid="t_3"), token=ada, key=st["keys"]["create"]), 201)
    expect(call("POST", "/auth/login", json_body={"email": "carol@example.com", "password": "carol pass 1"}), 401, "unauthenticated")


@check("K7", "§10 'Invalid JSON follows §5; missing fields, wrong track/version or an invalid state give 422 validation_failed without changing the destination'",
       "each invalid import leaves tokens, restaurants, reservations and keys as they were")
def _():
    st = build()
    T = st["tok"]
    before = observe(T, dates=(FUT, FUT2))
    e = export()
    expect(call("POST", "/_test/import", raw=b'{"track": "tablekeeper", '), 400, "malformed_request")
    expect(call("POST", "/_test/import", raw=b"not json at all"), 400, "malformed_request")
    bad = []
    for k in ("track", "format_version", "state"):
        d = copy.deepcopy(e)
        del d[k]
        bad.append(d)
    bad.append({})
    bad.append(dict(e, track="pocketful"))
    bad.append(dict(e, track=""))
    bad.append(dict(e, track="Tablekeeper"))
    bad.append(dict(e, format_version=2))
    bad.append(dict(e, format_version=0))
    garbled = {k: 12345 for k in e["state"]}
    assert garbled, "export state is an empty object; cannot garble"
    bad.append(dict(e, state=garbled))
    for d in bad:
        expect(call("POST", "/_test/import", json_body=d), 422, "validation_failed")
        assert observe(T, dates=(FUT, FUT2)) == before, f"destination changed by rejected import {str(d)[:120]}"
    # wrong JSON type of a top-level field: §5 allows 400 (wrong type) or §10's 422; either way nothing changes
    for d in (dict(e, state="x"), dict(e, state=[1]), dict(e, state=None), dict(e, format_version="1"), dict(e, track=5), [e], "x"):
        r = expect_in(call("POST", "/_test/import", json_body=d), (400, 422))
        assert r.code in ("malformed_request", "validation_failed"), r
        assert observe(T, dates=(FUT, FUT2)) == before
    assert expect(call("POST", "/reservations", json_body=st["body"]["create"], token=T["ada"], key=st["keys"]["create"]), 200).json == st["resp"]["create"]
    do_import(e)
    assert observe(T, dates=(FUT, FUT2)) == before
