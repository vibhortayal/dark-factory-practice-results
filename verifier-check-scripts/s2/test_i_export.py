"""I. Export / import (§10). Needs a second, fresh container of the same image in BASE2."""
import copy
import json

import pytest

from lib import BASE, BASE2, GET, POST, PW, World, burst, call, code_of, err, fixture, k, ok, soft, statuses, user

pytestmark = pytest.mark.skipif(False, reason="never skipped")


def need_base2():
    assert BASE2, "BASE2 (second container) is not set: this check cannot run, which counts as a failure"
    return BASE2


SEED_P = [{"id": "p_seed_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee ☕",
           "visibility": "public"},
          {"id": "p_seed_2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 70, "note": "", "visibility": "private"}]
SEED_R = [{"id": "rq_seed_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
          {"id": "rq_seed_2", "requester_id": "u_cy", "payer_id": "u_ada", "amount": 5, "note": "", "status": "declined"}]


def build(base=None):
    """A state touching every feature. Returns the world and a log of idempotent calls."""
    w = World(fixture(payments=copy.deepcopy(SEED_P), requests=copy.deepcopy(SEED_R)), base=base).login_all()
    done, failed = [], []

    def rec(who, path, body, expect=201):
        key = k()
        r = call("POST", path, w.t(who), key=key, body=body, base=w.base)
        if expect == 201:
            assert r.status_code == 201, r.text
            done.append({"who": who, "path": path, "key": key, "body": body, "resp": r.json()})
        else:
            assert r.status_code == expect, r.text
            failed.append({"who": who, "path": path, "key": key, "body": body})
        return r.json()

    su = w.signup("late.comer@example.com", display_name="Late")
    rec("ada", "/payments", {"to_handle": "bob", "amount": 100, "note": "pub 😀"})
    rec("ada", "/payments", {"to_handle": "cy", "amount": 250, "note": "prv", "visibility": "private"})
    rec("ada", "/payments", {"to_handle": "late_comer", "amount": 33})
    q1 = rec("bob", "/requests", {"payer_handle": "ada", "amount": 40, "note": "r1"})
    q2 = rec("bob", "/requests", {"payer_handle": "cy", "amount": 99999, "note": "too much"})
    q3 = rec("cy", "/requests", {"payer_handle": "dan", "amount": 7})
    q4 = rec("dan", "/requests", {"payer_handle": "ada", "amount": 8})
    rec("ada", f"/requests/{q1['request_id']}/pay", {"visibility": "private"})
    rec("ada", "/requests/rq_seed_1/pay", {})
    assert call("POST", f"/requests/{q3['request_id']}/decline", w.t("dan"), base=w.base).status_code == 200
    assert call("POST", f"/requests/{q4['request_id']}/cancel", w.t("dan"), base=w.base).status_code == 200
    s = rec("ada", "/splits", {"amount": 100, "participant_handles": ["ada", "bob", "cy"], "note": "split"})
    rec("bob", f"/requests/{s['requests'][0]['request_id']}/pay", {})
    rec("op", "/settlements", {"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 100, "note": "s-pub"},
        {"from_handle": "bob", "to_handle": "dan", "amount": 50, "visibility": "private", "note": "s-prv"},
        {"from_handle": "cy", "to_handle": "ada", "amount": 10}]})
    # failures: their keys must stay unused
    rec("cy", "/payments", {"to_handle": "ada", "amount": 10 ** 9}, expect=409)
    rec("ada", "/payments", {"to_handle": "ghost", "amount": 1}, expect=404)
    rec("ada", "/requests", {"payer_handle": "bob", "amount": 0}, expect=422)
    rec("cy", f"/requests/{q2['request_id']}/pay", {}, expect=409)
    rec("ada", "/splits", {"amount": 5, "participant_handles": []}, expect=422)
    rec("op", "/settlements", {"transfers": [{"from_handle": "cy", "to_handle": "ada", "amount": 10 ** 9}]}, expect=409)
    tokens = {h: w.t(h) for h in w.handles()}
    extra_login = call("POST", "/auth/login", body={"email": "ada@example.com", "password": PW}, base=w.base).json()["token"]
    tokens["ada#2"] = extra_login
    return w, done, failed, tokens, su


def export(base=None):
    r = call("GET", "/_test/export", base=base)
    assert r.status_code == 200, r.text[:200]
    return r.json()


def imp(doc, base=None, raw=None):
    if raw is not None:
        return call("POST", "/_test/import", raw=raw, base=base)
    return call("POST", "/_test/import", body=doc, base=base)


def snap(w, tokens, base):
    return w.snapshot(tokens=tokens, base=base)


def test_i1_export_shape_no_auth():
    w, *_ = build()
    r = GET("/_test/export")
    j = ok(r, 200)
    assert j["track"] == "pocketful"
    assert j["format_version"] == 1 and type(j["format_version"]) is int
    assert isinstance(j["state"], dict) and j["state"]
    soft(set(j) == {"track", "format_version", "state"}, "export-extra-keys", keys=sorted(j))
    assert ok(GET("/_test/export", headers={"Authorization": "Bearer bogus"}), 200)["track"] == "pocketful"


def test_i1_export_is_read_only_and_repeatable():
    w, done, failed, tokens, su = build()
    before = snap(w, tokens, BASE)
    e1 = export()
    e2 = export()
    assert snap(w, tokens, BASE) == before
    soft(e1 == e2, "two-exports-differ-without-writes")


def test_i2_import_same_container_roundtrip_and_repeat():
    w, done, failed, tokens, su = build()
    before = snap(w, tokens, BASE)
    e = export()
    r = imp(e)
    assert r.status_code == 204 and r.content == b"", r.text[:200]
    assert snap(w, tokens, BASE) == before
    for _ in range(3):
        assert imp(e).status_code == 204
    assert snap(w, tokens, BASE) == before, "repeated import duplicated or changed something"
    soft(export() == e, "export-import-export-differs")


def test_i1_import_restores_snapshot_time_state():
    w, done, failed, tokens, su = build()
    before = snap(w, tokens, BASE)
    e = export()
    frozen = json.dumps(e, sort_keys=True)
    # writes after the export
    ok(w.pay("ada", "bob", 77, note="after export"), 201)
    w.new_request("bob", "ada", 3)
    late = w.signup("after.export@example.com")
    newtok = ok(POST("/auth/login", body={"email": "bob@example.com", "password": PW}), 200)["token"]
    assert snap(w, tokens, BASE) != before
    assert json.dumps(e, sort_keys=True) == frozen
    assert imp(e).status_code == 204
    assert snap(w, tokens, BASE) == before
    err(GET("/me", late["token"]), 401, "unauthenticated")  # created after the export: gone
    err(GET("/me", newtok), 401, "unauthenticated")
    err(POST("/auth/login", body={"email": "after.export@example.com", "password": "longenough1"}), 401, "unauthenticated")


def test_i3_i4_i5_import_into_fresh_container():
    b2 = need_base2()
    w, done, failed, tokens, su = build()
    before = snap(w, tokens, BASE)
    e = export()
    # destination holds unrelated data and credentials
    other = World(fixture(users=[user("zed", 999), user("ada", 1, id="u_other_ada", email="ada@other.example"),
                                 user("yan", 5)], currency="JPY", minor=0, ops=["u_zed"]), base=b2)
    ztok = other.t("zed")
    okr = call("POST", "/payments", ztok, key="dest-key", body={"to_handle": "yan", "amount": 9, "note": "dest"}, base=b2)
    assert okr.status_code == 201
    r = imp(e, base=b2)
    assert r.status_code == 204, r.text[:300]
    # I2.3 replacement, not merge
    err(call("GET", "/me", ztok, base=b2), 401, "unauthenticated")
    err(call("POST", "/auth/login", body={"email": "zed@example.com", "password": PW}, base=b2), 401, "unauthenticated")
    err(call("POST", "/auth/login", body={"email": "ada@other.example", "password": PW}, base=b2), 401, "unauthenticated")
    # I3/I4 everything readable is identical with the same tokens
    after = snap(w, tokens, b2)
    assert after == before
    assert all("dest" != p["note"] for p in after["ada"]["activity"][1]["payments"])
    assert after["ada"]["me"][1]["currency"] == "EUR" and after["ada"]["me"][1]["minor_units"] == 2
    # password login for seeded and signed-up accounts
    for email, pw in [("ada@example.com", PW), ("op@example.com", PW), ("late.comer@example.com", "longenough1")]:
        j = call("POST", "/auth/login", body={"email": email, "password": pw}, base=b2)
        assert j.status_code == 200, f"{email}: {j.text[:200]}"
        assert call("GET", "/me", j.json()["token"], base=b2).status_code == 200
    err(call("POST", "/auth/login", body={"email": "ada@example.com", "password": "wrong horse"}, base=b2), 401)
    assert call("GET", "/me", su["token"], base=b2).json()["handle"] == "late_comer"
    err(call("POST", "/auth/signup", body={"email": "late.comer@example.com", "password": "longenough1",
                                           "display_name": "x"}, base=b2), 409, "email_taken")
    # I5 replays of every completed idempotent request
    for d in done:
        r = call("POST", d["path"], tokens[d["who"]], key=d["key"], body=d["body"], base=b2)
        assert r.status_code == 200, f"replay {d['path']} after import: {r.status_code} {r.text[:200]}"
        assert r.json() == d["resp"], f"replay body differs on {d['path']}"
        r = call("POST", d["path"], tokens[d["who"]], key=d["key"], body={**d["body"], "changed": 1}, base=b2)
        err(r, 409, "idempotency_key_reuse", d["path"])
    assert snap(w, tokens, b2) == before, "replays after import changed state"
    # keys of failed requests remain first-use
    w2 = World(w.fx, base=b2, do_reset=False)
    w2.tok = {h: t for h, t in tokens.items() if "#" not in h and h != "late_comer"}
    w2.extra = {"late_comer": tokens["late_comer"]}
    f = {x["path"] + str(i): x for i, x in enumerate(failed)}
    fk = [x for x in failed if x["path"] == "/payments" and x["who"] == "ada"][0]
    r = call("POST", "/payments", tokens["ada"], key=fk["key"], body={"to_handle": "bob", "amount": 1}, base=b2)
    assert r.status_code == 201, f"failed key not reusable after import: {r.status_code} {r.text[:200]}"
    fr = [x for x in failed if x["path"] == "/requests"][0]
    assert call("POST", "/requests", tokens["ada"], key=fr["key"], body={"payer_handle": "bob", "amount": 2},
                base=b2).status_code == 201
    fs = [x for x in failed if x["path"] == "/splits"][0]
    assert call("POST", "/splits", tokens["ada"], key=fs["key"], body={"amount": 5, "participant_handles": ["bob"]},
                base=b2).status_code == 201
    fst = [x for x in failed if x["path"] == "/settlements"][0]
    r = call("POST", "/settlements", tokens["op"], key=fst["key"],
             body={"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 2}]}, base=b2)
    assert r.status_code == 201, r.text[:200]
    # operator permission preserved, and only for the operator
    err(call("POST", "/settlements", tokens["ada"], key=k(),
             body={"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 2}]}, base=b2), 403, "forbidden")
    # new ids never collide with imported ones
    old_p = {p["payment_id"] for h in before for p in before[h]["activity"][1]["payments"]}
    old_r = {q["request_id"] for h in before for q in before[h]["requests"][1]["requests"]}
    newp = call("POST", "/payments", tokens["ada"], key=k(), body={"to_handle": "bob", "amount": 1}, base=b2).json()
    newq = call("POST", "/requests", tokens["ada"], key=k(), body={"payer_handle": "bob", "amount": 1}, base=b2).json()
    newst = r.json()
    assert newp["payment_id"] not in old_p and newq["request_id"] not in old_r
    assert not ({p["payment_id"] for p in newst["payments"]} & old_p)
    old_settlements = {p["settlement_id"] for h in before for p in before[h]["activity"][1]["payments"]} - {None}
    assert newst["settlement_id"] not in old_settlements and len(old_settlements) == 1
    s3 = call("POST", "/auth/signup", body={"email": "post.import@example.com", "password": "longenough1",
                                            "display_name": "P"}, base=b2)
    assert s3.status_code == 201
    old_users = {before[h]["me"][1]["user_id"] for h in before}
    assert s3.json()["user_id"] not in old_users
    # pending imported request is still live; money is conserved in the destination
    q2 = [q for q in before["cy"]["requests"][1]["requests"] if q["note"] == "too much"][0]
    err(call("POST", f"/requests/{q2['request_id']}/pay", tokens["cy"], key=k(), body={}, base=b2), 409, "insufficient_funds")
    assert call("POST", f"/requests/{q2['request_id']}/cancel", tokens["bob"], base=b2).json()["status"] == "cancelled"
    total = sum(call("GET", "/me", tokens[h], base=b2).json()["balance"] for h in ("ada", "bob", "cy", "dan", "op", "late_comer"))
    assert total == w.seeded_total()
    # the source container is unaffected by what happened in the destination
    assert snap(w, tokens, BASE) == before


def test_i1_export_under_concurrent_writes_is_consistent():
    b2 = need_base2()
    w = World(fixture(users=[user("ada", 100000), user("bob", 100000), user("cy", 100000)])).login_all()
    tokens = {h: w.t(h) for h in w.handles()}
    ring = [("ada", "bob"), ("bob", "cy"), ("cy", "ada")]
    exports = []
    for _ in range(3):
        fns = [lambda i=i: w.pay(ring[i % 3][0], ring[i % 3][1], 1 + i * 7) for i in range(46)]
        fns[10:10] = [lambda: call("GET", "/_test/export")]
        fns[25:25] = [lambda: call("GET", "/_test/export")]
        fns[40:40] = [lambda: call("GET", "/_test/export")]
        fns.append(lambda: call("GET", "/_test/export"))
        rs = burst(fns)
        exports += [r.json() for r in rs if r.request.url.path == "/_test/export"]
        assert all(r.status_code in (200, 201) for r in rs), statuses(rs)
    assert len(exports) == 12
    for e in exports:
        assert imp(e, base=b2).status_code == 204
        bals = [call("GET", "/me", tokens[h], base=b2).json()["balance"] for h in ("ada", "bob", "cy")]
        assert sum(bals) == 300000 and min(bals) >= 0, f"export taken mid-burst is inconsistent: {bals}"
        # every payment in the snapshot is reflected in the balances
        feed = call("GET", "/activity?limit=200", tokens["ada"], base=b2).json()["payments"]
        delta = {"ada": 0, "bob": 0, "cy": 0}
        for p in feed:
            delta[p["from_handle"]] -= p["amount"]
            delta[p["to_handle"]] += p["amount"]
        if len(feed) < 200:
            assert [100000 + delta[h] for h in ("ada", "bob", "cy")] == bals, "payments and balances disagree in an export"
    w.assert_conserved()


BAD_ENVELOPES = {
    "missing_track": lambda e: {kk: v for kk, v in e.items() if kk != "track"},
    "missing_format_version": lambda e: {kk: v for kk, v in e.items() if kk != "format_version"},
    "missing_state": lambda e: {kk: v for kk, v in e.items() if kk != "state"},
    "empty_object": lambda e: {},
    "wrong_track": lambda e: {**e, "track": "tablekeeper"},
    "track_case": lambda e: {**e, "track": "Pocketful"},
    "track_null": lambda e: {**e, "track": None},
    "version_2": lambda e: {**e, "format_version": 2},
    "version_0": lambda e: {**e, "format_version": 0},
    "version_string": lambda e: {**e, "format_version": "1"},
    "version_null": lambda e: {**e, "format_version": None},
    "version_true": lambda e: {**e, "format_version": True},
    "version_1_5": lambda e: {**e, "format_version": 1.5},
    "state_null": lambda e: {**e, "state": None},
    "state_list": lambda e: {**e, "state": []},
    "state_string": lambda e: {**e, "state": "x"},
    "state_number": lambda e: {**e, "state": 5},
    "state_empty": lambda e: {**e, "state": {}},
    "state_only": lambda e: e["state"],
    "fixture_instead": lambda e: fixture(),
}


@pytest.fixture(scope="module")
def dest():
    w, done, failed, tokens, su = build()
    return w, tokens, snap(w, tokens, BASE), export()


@pytest.mark.parametrize("name", list(BAD_ENVELOPES))
def test_i6_invalid_import_envelope_422(dest, name):
    w, tokens, before, e = dest
    r = imp(BAD_ENVELOPES[name](copy.deepcopy(e)))
    unchanged = snap(w, tokens, BASE) == before
    if not unchanged:
        imp(e)
    assert unchanged, f"destination changed after rejected import {name} ({r.status_code})"
    err(r, (422, 400) if name in ("version_string", "version_null", "version_true", "track_null") else 422,
        ("validation_failed", "malformed_request"), name)
    assert r.status_code == 422 or code_of(r) == "malformed_request"


@pytest.mark.parametrize("raw", [b"", b"{", b"not json", b'{"track": "pocketful", "format_version": 1, "state": {',
                                 b"\xff\xfe"])
def test_i6_unparseable_import_400(dest, raw):
    w, tokens, before, e = dest
    err(imp(None, raw=raw), 400, "malformed_request")
    assert snap(w, tokens, BASE) == before


@pytest.mark.parametrize("raw", ["[]", '"x"', "5", "null"])
def test_i6_non_object_import(dest, raw):
    w, tokens, before, e = dest
    r = imp(None, raw=raw)
    err(r, (400, 422), ("malformed_request", "validation_failed"))
    assert snap(w, tokens, BASE) == before


def test_i6_corrupted_state_rejected_without_change(dest):
    w, tokens, before, e = dest
    state = e["state"]
    results = {}
    for key in list(state):
        for label, bad in (("wrong-type", "corrupt" if not isinstance(state[key], str) else 12345),
                           ("null", None), ("removed", "__remove__")):
            doc = copy.deepcopy(e)
            if bad == "__remove__":
                del doc["state"][key]
            else:
                doc["state"][key] = bad
            r = imp(doc)
            assert r.status_code < 500
            changed = snap(w, tokens, BASE) != before
            results[f"{key}:{label}"] = (r.status_code, changed)
            if r.status_code == 204 or changed:
                assert imp(e).status_code == 204  # restore for the next case
            else:
                err(r, (422, 400), ("validation_failed", "malformed_request"), f"{key}:{label}")
    accepted = {kk: v for kk, v in results.items() if v[0] == 204}
    changed_on_reject = {kk: v for kk, v in results.items() if v[0] != 204 and v[1]}
    assert not changed_on_reject, f"rejected import changed the destination: {changed_on_reject}"
    wrong_type_accepted = {kk: v for kk, v in accepted.items() if kk.endswith(":wrong-type")}
    assert not wrong_type_accepted, f"corrupted state accepted with 204: {wrong_type_accepted}"
    soft(not accepted, "import-accepts-state-with-null-or-missing-part", cases=sorted(accepted))


def test_i6_unknown_envelope_field_ignored(dest):
    w, tokens, before, e = dest
    r = imp({**e, "exported_by": "verifier", "extra": {"a": 1}})
    assert r.status_code == 204, r.text[:200]
    assert snap(w, tokens, BASE) == before


def test_i7_reset_clears_imported_state():
    w, done, failed, tokens, su = build()
    e = export()
    World(fixture(users=[user("zed", 1)]))
    assert imp(e).status_code == 204
    assert call("GET", "/me", tokens["ada"]).status_code == 200
    w3 = World(fixture(users=[user("zed", 1), user("ada", 3)]))
    for h, t in tokens.items():
        err(GET("/me", t), 401, "unauthenticated", h)
    assert w3.bal("ada") == 3 and w3.activity("ada") == [] and w3.requests("ada") == []
    d = done[0]
    r = POST(d["path"], w3.t("ada"), d["body"], key=d["key"])
    assert r.status_code in (201, 404), r.text  # first use again (bob no longer exists -> 404), never a 200 replay
    err(POST("/auth/login", body={"email": "late.comer@example.com", "password": "longenough1"}), 401, "unauthenticated")


def test_i7_export_import_timing_with_larger_state():
    users = [user(f"user_{i:02d}", 100000) for i in range(60)]
    w = World(fixture(users=users, ops=["u_user_00"]))
    for rnd in range(6):
        rs = burst([lambda i=i: w.pay(f"user_{i:02d}", f"user_{(i + rnd + 1) % 50:02d}", 1 + i, note=f"n{i}")
                    for i in range(50)])
        assert statuses(rs) == {201: 50}
    r = call("GET", "/_test/export")
    assert r.status_code == 200 and r.elapsed_s <= 10.0, r.elapsed_s
    r2 = imp(r.json())
    assert r2.status_code == 204 and r2.elapsed_s <= 10.0, r2.elapsed_s
    w.assert_conserved()
    assert len(w.activity("user_00")) == 200
