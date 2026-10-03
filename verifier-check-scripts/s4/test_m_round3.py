"""M. Fix round 3: checks for the code that changed between df4b305 and 43ecb3c
(import: plain-state rule, whitelisted records and responses, round-trip proof; total encoder)."""
import copy
import json

import pytest

import zlib

from lib import BASE2, GET, POST, World, call, check_payment, err, fixture, k, ok, soft, user


def export():
    r = call("GET", "/_test/export")
    assert r.status_code == 200, r.text[:200]
    return r


# ---------------------------------------------------------------- S1

@pytest.mark.parametrize("value", ["0.25", "1" + "0" * 30, "1e40", "-0.5", "1e99999999999999999999"])
def test_m_s1_number_in_stored_response_is_rejected(value):
    w = World(fixture(users=[user("ada", 100), user("bob", 0)])).login_all()
    j = ok(w.pay("ada", "bob", 5, key="k1"), 201)
    e = export().json()
    before = w.snapshot()
    doc = copy.deepcopy(e)
    doc["state"]["idempotency"][0]["response"]["extra"] = "@@"
    raw = json.dumps(doc).replace('"@@"', value)
    r = call("POST", "/_test/import", raw=raw)
    err(r, 422, "validation_failed", value)
    assert w.snapshot() == before
    assert export().json() == e
    assert ok(w.pay("ada", "bob", 5, key="k1"), 200) == j


# ---------------------------------------------------------------- reachable states still round-trip

ODD_IDS = ["a/b", "sp ace", "ünï-cødé-😀", "x" * 64, "with?query=1&y", "per%25cent", "dot.dot..", "rq_1", "#hash", "nl\nid"]


def test_m_states_with_odd_fixture_ids_round_trip_and_replay():
    assert BASE2, "BASE2 (second container) is not set"
    users = [user("ada", 5000, id="user/ada 1"), user("bob", 100, id="ü" * 64), user("cy", 0, id="c?y#")]
    reqs = [{"id": rid, "requester_id": "ü" * 64, "payer_id": "user/ada 1", "amount": 3 + i, "note": f"n{i}",
             "status": "pending"} for i, rid in enumerate(ODD_IDS)]
    pays = [{"id": "p/" + rid[:60], "from_user_id": "c?y#", "to_user_id": "ü" * 64, "amount": 1, "note": "",
             "visibility": "private" if i % 2 else "public"} for i, rid in enumerate(ODD_IDS)]
    w = World(fixture(users=users, payments=pays, requests=reqs, ops=["c?y#"])).login_all()
    done = []
    for i, rid in enumerate(ODD_IDS):
        from urllib.parse import quote
        path = f"/requests/{quote(rid, safe='')}/pay"
        key = f"key-{i}"
        r = call("POST", path, w.t("ada"), key=key, body={})
        p = check_payment(ok(r, 201, f"pay {rid!r}"), request_id=rid, amount=3 + i, from_user_id="user/ada 1")
        assert ok(call("POST", path, w.t("ada"), key=key, body={}), 200) == p
        done.append((path, key, p))
    s = ok(POST("/splits", w.t("ada"), {"amount": 1, "participant_handles": ["bob", "cy", "ada"]}, key="sp"), 201)
    z = ok(call("POST", f"/requests/{s['requests'][1]['request_id']}/pay", w.t("cy"), key="zero", body={}), 201)
    assert z["amount"] == 0
    st = ok(POST("/settlements", w.t("cy"), {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 2,
                                                             "visibility": "private"}]}, key="st"), 201)
    su = w.signup("İstanbul.Ünï@example.com", display_name="İ")
    pp = ok(w.pay("ada", su["handle"], 7, key="to-new"), 201)
    q = ok(POST("/requests", su["token"], {"payer_handle": "ada", "amount": 2}, key="rq-new"), 201)
    snap = w.snapshot()
    e = export()
    for base in (None, BASE2):
        if base:
            World(fixture(users=[user("zed", 1)]), base=base)
        r = call("POST", "/_test/import", raw=e.content, base=base)
        assert r.status_code == 204, f"import of own export -> {r.status_code} {r.text[:200]}"
        tokens = {h: w.t(h) for h in w.handles()}
        assert w.snapshot(tokens=tokens, base=base) == snap
        for path, key, p in done:
            r = call("POST", path, w.t("ada"), key=key, body={}, base=base)
            assert r.status_code == 200 and r.json() == p, f"{path}: {r.status_code} {r.text[:120]}"
        assert call("POST", "/splits", w.t("ada"), key="sp", base=base,
                    body={"amount": 1, "participant_handles": ["bob", "cy", "ada"]}).json() == s
        assert call("POST", "/settlements", w.t("cy"), key="st", base=base,
                    body={"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 2,
                                         "visibility": "private"}]}).json() == st
        assert call("POST", "/payments", w.t("ada"), key="to-new", base=base,
                    body={"to_handle": su["handle"], "amount": 7}).json() == pp
        assert call("POST", "/requests", su["token"], key="rq-new", base=base,
                    body={"payer_handle": "ada", "amount": 2}).json() == q
        assert w.snapshot(tokens=tokens, base=base) == snap
        again = call("GET", "/_test/export", base=base)
        assert again.status_code == 200
        assert call("POST", "/_test/import", raw=again.content, base=base).status_code == 204


def test_m_seeded_non_pending_requests_and_many_keys_round_trip():
    reqs = [{"id": f"rq_{s}", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 0 if s == "paid" else 5,
             "note": "", "status": s} for s in ("pending", "paid", "declined", "cancelled")]
    w = World(fixture(requests=reqs)).login_all()
    keys = []
    for i in range(40):
        key = "k" * (1 + i * 6) if i < 40 else k()
        keys.append((key, ok(w.pay("ada", "bob", 1, key=key, note="😀" * 200, visibility="private"), 201)))
    k255 = "z" * 255
    keys.append((k255, ok(w.pay("ada", "bob", 1, key=k255, note="😀" * 200, visibility="private"), 201)))
    snap = w.snapshot()
    e = export()
    assert call("POST", "/_test/import", raw=e.content).status_code == 204
    assert w.snapshot() == snap
    for key, j in keys:
        assert ok(w.pay("ada", "bob", 1, key=key, note="😀" * 200, visibility="private"), 200) == j
    soft(export().json() == e.json(), "export-import-export-differs")


# ---------------------------------------------------------------- mutation sweep over the changed validators

VALUES = ["0.25", "1" + "0" * 30, "-1", "null", '"x"', "[]", "{}", "true", '"' + "y" * 300 + '"']


def _paths(node, prefix=()):
    """Every member position inside a JSON tree, as a tuple of keys/indexes."""
    if isinstance(node, dict):
        for kk, v in node.items():
            yield prefix + (kk,)
            yield from _paths(v, prefix + (kk,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield prefix + (i,)
            yield from _paths(v, prefix + (i,))


def _set(doc, path, value):
    cur = doc
    for p in path[:-1]:
        cur = cur[p]
    cur[path[-1]] = value


KNOWN_SECTIONS = ["idempotency", "splits", "settlements", "payments", "requests", "users", "tokens", "operators",
                  "counters", "authorizations"]


@pytest.mark.parametrize("section", KNOWN_SECTIONS + ["everything_else"])
def test_m_mutants_of_import_never_5xx_and_never_poison(section):
    w = World().login_all()
    calls = [("/payments", "ada", {"to_handle": "bob", "amount": 5, "note": "n"}, "k-pay"),
             ("/requests", "bob", {"payer_handle": "ada", "amount": 7}, "k-req"),
             ("/splits", "ada", {"amount": 10, "participant_handles": ["ada", "bob", "cy"]}, "k-split"),
             ("/settlements", "op", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 2},
                                                   {"from_handle": "cy", "to_handle": "dan", "amount": 1}]}, "k-st")]
    for path, who, body, key in calls:
        ok(POST(path, w.t(who), body, key=key), 201)
    # stage 2: authorisations in several states, with keys on both new paths
    a1 = ok(POST("/authorizations", w.t("ada"), {"to_handle": "bob", "amount": 300, "note": "hold"}, key="k-auth"), 201)
    calls.append(("/authorizations", "ada", {"to_handle": "bob", "amount": 300, "note": "hold"}, "k-auth"))
    cap = (f"/authorizations/{a1['authorization_id']}/capture", "bob", {"amount": 100, "final": False}, "k-cap")
    ok(POST(cap[0], w.t("bob"), cap[2], key="k-cap"), 201)
    calls.append(cap)
    a2 = ok(POST("/authorizations", w.t("ada"), {"to_handle": "cy", "amount": 50}, key="k-auth2"), 201)
    ok(POST(f"/authorizations/{a2['authorization_id']}/void", w.t("ada")), 200)
    rid = w.requests("ada", "direction=incoming&status=pending&limit=200")[-1]["request_id"]
    calls.append((f"/requests/{rid}/pay", "ada", {"visibility": "private"}, "k-payreq"))
    ok(POST(calls[-1][0], w.t("ada"), calls[-1][2], key="k-payreq"), 201)
    # stage 3: a corrected payment (two revisions, an idempotency record on the eighth path) and a statement snapshot
    first_pay = [p for p in w.activity("ada") if p["note"] == "n"][0]
    corr = (f"/payments/{first_pay['payment_id']}/corrections", "ada",
            {"expected_revision": 1, "amount": 3, "effective_at": first_pay["created_at"], "reason": "sweep"}, "k-corr")
    ok(POST(corr[0], w.t("ada"), corr[2], key="k-corr"), 201)
    calls.append(corr)
    snap_token = ok(GET("/statement?limit=2", w.t("ada")), 200)["snapshot"]
    # stage 4: a refund and a correction batch over a whole settlement, with keys on both new paths
    rf = (f"/payments/{first_pay['payment_id']}/refunds", "bob", {"amount": 1}, "k-refund")
    ok(POST(rf[0], w.t("bob"), rf[2], key="k-refund"), 201)
    calls.append(rf)
    mem = [p for p in w.activity("ada") + w.activity("cy") if p.get("settlement_id")]
    mem = list({p["payment_id"]: p for p in mem}.values())
    bt = ("/correction-batches", "op", {"corrections": [
        {"payment_id": p["payment_id"], "expected_revision": 1, "amount": p["amount"], "effective_at": p["created_at"],
         "reason": "sweep batch"} for p in mem]}, "k-batch")
    ok(POST(bt[0], w.t("op"), bt[2], key="k-batch"), 201)
    calls.append(bt)
    good = export()
    e = good.json()
    base_snapshot = w.snapshot()
    if section == "everything_else":
        # stage 3: whatever parts of the state the named sections above do not cover (revisions, snapshots, clocks ...)
        named = {next((kk for kk in e["state"] if kk == sname or sname[:4] in kk), None) for sname in KNOWN_SECTIONS}
        rest = [kk for kk in e["state"] if kk not in named]
        positions = [pos for kk in rest for pos in ([("state", kk)] + list(_paths(e["state"][kk], ("state", kk))))]
        skey = "everything_else"
        if not positions:
            soft(False, "export-state-has-no-part-outside-the-named-sections")
            return
    else:
        skey = section if section in e["state"] else next((kk for kk in e["state"] if section[:4] in kk), None)
        assert skey is not None, f"export state has no section for {section}: {sorted(e['state'])}"
        positions = list(_paths(e["state"][skey], ("state", skey)))
    assert positions, f"export has no {section}"
    accepted = rejected = 0
    for pos in positions:
        for vi, value in enumerate(VALUES):
            if (zlib.crc32(repr((pos, vi)).encode()) % 3) and len(positions) * len(VALUES) > 400:
                continue  # sample large sections; every position still gets several values across the run
            doc = copy.deepcopy(e)
            _set(doc, pos, "@@MUT@@")
            raw = json.dumps(doc).replace('"@@MUT@@"', value)
            r = call("POST", "/_test/import", raw=raw)
            assert r.status_code in (204, 422), f"{pos} <- {value[:20]}: {r.status_code} {r.text[:120]}"
            if r.status_code == 422:
                rejected += 1
                continue
            accepted += 1
            x = call("GET", "/_test/export")
            assert x.status_code == 200, f"{pos} <- {value[:20]}: export after accepted import -> {x.status_code}"
            assert call("POST", "/_test/import", raw=x.content).status_code == 204, f"{pos} <- {value[:20]}: re-import"
            for path, who, body, key in calls:
                rr = POST(path, w.tok[who], body, key=key)
                assert rr.status_code < 500, f"{pos} <- {value[:20]}: replay {path} -> {rr.status_code}"
            for h, tk in w.tok.items():
                for ep in ("/me", "/activity?limit=200", "/requests?limit=200", "/authorizations?limit=200",
                           "/statement?limit=200", "/me?as_of=2020-01-01T00%3A00%3A00Z&known_at=2999-01-01T00%3A00%3A00Z",
                           f"/statement?snapshot={snap_token}", f"/payments/{first_pay['payment_id']}/revisions"):
                    assert GET(ep, tk).status_code < 500, f"{pos} <- {value[:20]}: GET {ep} is a server error"
            assert call("POST", "/_test/import", raw=good.content).status_code == 204
    # the destination is what it was, and rejected imports changed nothing on the way
    assert w.snapshot() == base_snapshot
    soft(export().json() == e, "export-import-export-differs")
    assert rejected > 0
    print(f"\n{section}: {len(positions)} positions, {accepted} accepted, {rejected} rejected")
