"""Stage-4 fix round 1: checks for the code that changed between 64e7f7b and 3df8b93 (import validation of stored
responses and of the links between them and the ledger)."""
import copy
import json
import random

import pytest

from lib import (BASE2, GET, POST, World, batch, build_model, call, check_batch, check_everything, correct, err, fixture, item,
                 k, now_f, ok, refund, revisions, soft, statement, user)
from test_fc_model4 import run_ops4
from test_w_model import HANDLES, random_fixture

ID_KEYS = ("payment_id", "request_id", "authorization_id", "settlement_id", "refund_of", "split_id", "correction_batch_id",
           "user_id", "from_user_id", "to_user_id", "requester_id", "payer_id", "batch_id", "id")


def setp(doc, path, value):
    cur = doc
    for x in path[:-1]:
        cur = cur[x]
    cur[path[-1]] = value


def id_paths(node, prefix=()):
    """Every position of an id-typed string member, also inside lists of ids."""
    if isinstance(node, dict):
        for kk, v in node.items():
            if kk in ID_KEYS and isinstance(v, str):
                yield prefix + (kk,)
            elif kk == "payment_ids" and isinstance(v, list):
                for i in range(len(v)):
                    yield prefix + (kk, i)
            else:
                yield from id_paths(v, prefix + (kk,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from id_paths(v, prefix + (i,))


def rich():
    """All ten idempotent paths, each with a stored response, plus later revisions on top of stored ones."""
    w = World().login_all()
    calls = []

    def rec(who, path, body, key):
        j = ok(POST(path, w.t(who), body, key=key), 201)
        calls.append((who, path, body, key, j))
        return j

    p = rec("ada", "/payments", {"to_handle": "bob", "amount": 100, "note": "n"}, "k-pay")
    p2 = rec("ada", "/payments", {"to_handle": "cy", "amount": 80, "visibility": "private"}, "k-pay2")
    rq = rec("bob", "/requests", {"payer_handle": "ada", "amount": 7}, "k-req")
    rec("ada", f"/requests/{rq['request_id']}/pay", {}, "k-reqpay")
    rec("ada", "/splits", {"amount": 10, "participant_handles": ["ada", "bob", "cy"]}, "k-split")
    st = rec("op", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 20},
                                                  {"from_handle": "cy", "to_handle": "dan", "amount": 10}]}, "k-st")
    a = rec("ada", "/authorizations", {"to_handle": "bob", "amount": 300}, "k-auth")
    rec("bob", f"/authorizations/{a['authorization_id']}/capture", {"amount": 100, "final": False}, "k-cap")
    rec("ada", f"/payments/{p['payment_id']}/corrections",
        {"expected_revision": 1, "amount": 90, "effective_at": p["created_at"], "reason": "single"}, "k-corr")
    rec("bob", f"/payments/{p['payment_id']}/refunds", {"amount": 5}, "k-refund")
    members = st["payments"]
    its = [item(p, 85, expected=2), item(p2, 70)] + [item(x, x["amount"]) for x in members]
    rec("op", "/correction-batches", {"corrections": its}, "k-batch")
    # later revisions on top of the stored ones: the stored responses must still import and replay
    ok(correct(w, "ada", p["payment_id"], 3, 88, p["created_at"], "after the batch"), 201)
    its2 = [item(p, 86, expected=4), item(p2, 71, expected=2)]
    rec("op", "/correction-batches", {"corrections": its2}, "k-batch2")
    snap = ok(statement(w, "ada", limit=3), 200)
    return w, calls, p, p2, snap


def replay_all(w, calls, base=None):
    for who, path, body, key, j in calls:
        r = call("POST", path, w.t(who), key=key, body=body, base=base or w.base)
        assert r.status_code == 200 and r.json() == j, f"replay {path}: {r.status_code} {r.text[:200]}"


def test_ff_finding_1_is_fixed():
    w = World().login_all()
    p = ok(w.pay("ada", "bob", 100), 201)
    its = [item(p, 60)]
    j = ok(batch(w, its, key="k-b"), 201)
    e = call("GET", "/_test/export").json()
    recs = [i for i, x in enumerate(e["state"]["idempotency"]) if isinstance(x.get("response"), dict) and "correction_batch_id" in x["response"]]
    assert len(recs) == 1
    base = ("state", "idempotency", recs[0], "response")
    before = w.snapshot()
    for loc in (base + ("correction_batch_id",), base + ("revisions", 0, "correction_batch_id")):
        for value in ("y" * 65, "y" * 300, "", "y" * 64, "cb_999", 5, ["cb_1"], {}, True):
            doc = copy.deepcopy(e)
            setp(doc, loc, value)
            err(call("POST", "/_test/import", body=doc), 422, "validation_failed", f"{loc[-1]} <- {str(value)[:12]!r}")
            assert call("GET", "/_test/export").json() == e, "a refused import changed the destination"
    assert w.snapshot() == before
    assert call("POST", "/_test/import", body=e).status_code == 204
    assert ok(batch(w, its, key="k-b"), 200) == j
    assert ok(revisions(w, "ada", p["payment_id"]), 200)["revisions"][1]["correction_batch_id"] == j["correction_batch_id"]


def test_ff_own_exports_with_every_stored_response_still_import_and_replay():
    w, calls, p, p2, snap = rich()
    e = call("GET", "/_test/export")
    snapshot = w.snapshot()
    assert call("POST", "/_test/import", raw=e.content).status_code == 204, "the unaltered export must import"
    assert call("GET", "/_test/export").json() == e.json()
    replay_all(w, calls)
    assert w.snapshot() == snapshot
    assert ok(statement(w, "ada", snapshot=snap["snapshot"], limit=3), 200)["entries"] == snap["entries"]
    if BASE2:
        World(fixture(users=[user("zed", 1)]), base=BASE2)
        assert call("POST", "/_test/import", raw=e.content, base=BASE2).status_code == 204
        replay_all(w, calls, base=BASE2)
    check_everything(w, build_model(w), random.Random(91), me_points=30, st_points=8)


def test_ff_invalid_ids_anywhere_in_the_state_are_refused():
    w, calls, p, p2, snap = rich()
    e = call("GET", "/_test/export").json()
    locs = list(id_paths(e["state"], ("state",)))
    assert len(locs) > 60, len(locs)
    wrong = []
    for loc in locs:
        for value in ("", "y" * 65, "y" * 300):
            doc = copy.deepcopy(e)
            setp(doc, loc, value)
            r = call("POST", "/_test/import", body=doc)
            if r.status_code != 422:
                wrong.append((loc, len(value), r.status_code))
                call("POST", "/_test/import", body=e)
    assert not wrong, f"{len(wrong)} of {len(locs) * 3} mutants with an invalid id were not refused: {wrong[:10]}"
    assert call("GET", "/_test/export").json() == e, "refused imports changed the destination"
    replay_all(w, calls)
    print(f"\n{len(locs)} id members, {len(locs) * 3} invalid-id mutants refused")


def test_ff_stored_responses_must_agree_with_the_ledger():
    w, calls, p, p2, snap = rich()
    e = call("GET", "/_test/export").json()
    idem = e["state"]["idempotency"]

    def record(pred):
        hits = [i for i, x in enumerate(idem) if pred(x)]
        assert hits, "no such stored response"
        return ("state", "idempotency", hits[0], "response")

    refund_rec = record(lambda x: isinstance(x.get("response"), dict) and x["response"].get("refund_of"))
    batch_rec = record(lambda x: isinstance(x.get("response"), dict) and "revisions" in x["response"])
    corr_rec = record(lambda x: x.get("path", "").endswith("/corrections"))
    other_batch = [x["response"]["correction_batch_id"] for x in idem if isinstance(x.get("response"), dict) and "revisions" in x["response"]]
    assert len(set(other_batch)) == 2
    cases = {
        "refund names another payment": (refund_rec + ("refund_of",), p2["payment_id"]),
        "refund names nothing": (refund_rec + ("refund_of",), None),
        "refund names an unknown payment": (refund_rec + ("refund_of",), "p_nope"),
        "batch id of the other batch": (batch_rec + ("correction_batch_id",), other_batch[1]),
        "revision's batch id of the other batch": (batch_rec + ("revisions", 0, "correction_batch_id"), other_batch[1]),
        "revision's batch id null": (batch_rec + ("revisions", 0, "correction_batch_id"), None),
        "batch revision amount": (batch_rec + ("revisions", 0, "amount"), 1),
        "batch revision number": (batch_rec + ("revisions", 0, "revision"), 2),
        "batch revision recorded_at": (batch_rec + ("revisions", 1, "recorded_at"), "2020-01-01T00:00:00+00:00"),
        "batch recorded_at": (batch_rec + ("recorded_at",), "2020-01-01T00:00:00+00:00"),
        "batch revision names another payment": (batch_rec + ("revisions", 0, "payment_id"), p2["payment_id"]),
        "single correction amount": (corr_rec + ("amount",), 1),
        "single correction reason": (corr_rec + ("reason",), "other"),
        "single correction batch id": (corr_rec + ("correction_batch_id",), other_batch[0]),
    }
    notes = []
    for name, (loc, value) in cases.items():
        doc = copy.deepcopy(e)
        setp(doc, loc, value)
        r = call("POST", "/_test/import", body=doc)
        assert r.status_code in (204, 422), f"{name}: {r.status_code} {r.text[:200]}"
        if r.status_code == 204:
            notes.append(name)
            x = call("GET", "/_test/export")
            assert x.status_code == 200 and call("POST", "/_test/import", raw=x.content).status_code == 204, name
            call("POST", "/_test/import", body=e)
        else:
            assert call("GET", "/_test/export").json() == e, f"{name}: a refused import changed the destination"
    soft(not notes, "stored-response-disagreeing-with-ledger-accepted", cases=notes)
    # the ledger side alone: a batch id changed in one member only breaks the batch's stored response
    locs = [("state", "payments", i, "corrections", j, "batch_id") for i, pay in enumerate(e["state"]["payments"])
            for j, c in enumerate(pay.get("corrections", [])) if c.get("batch_id")]
    assert len(locs) >= 5
    for loc in locs[:3]:
        for value in ("cb_other", None):
            doc = copy.deepcopy(e)
            setp(doc, loc, value)
            r = call("POST", "/_test/import", body=doc)
            assert r.status_code in (204, 422), r.text[:200]
            soft(r.status_code == 422, "ledger-batch-id-changed-under-a-stored-response-accepted", loc=str(loc[2:]), value=value)
            call("POST", "/_test/import", body=e)
    assert call("POST", "/_test/import", body=e).status_code == 204
    replay_all(w, calls)


@pytest.mark.parametrize("seed", [9101, 9202])
def test_ff_random_histories_still_export_and_import(seed):
    """The stricter validation must not refuse any state the service itself produced."""
    rng = random.Random(seed)
    fx, opening, base_t = random_fixture(rng)
    fx["users"].append(user("op", 0))
    fx["settlement_operator_ids"] = ["u_op"]
    w = World(fx).login_all()
    m = build_model(w)
    for chunk in range(4):
        run_ops4(w, m, rng, base_t, 25, [])
        e = call("GET", "/_test/export")
        r = call("POST", "/_test/import", raw=e.content)
        assert r.status_code == 204, f"seed {seed}, after {25 * (chunk + 1)} operations: own export refused: {r.status_code} {r.text[:200]}"
        if BASE2:
            assert call("POST", "/_test/import", raw=e.content, base=BASE2).status_code == 204
    check_everything(w, build_model(w), rng, me_points=30, st_points=8)
