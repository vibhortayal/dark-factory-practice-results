"""Exports of earlier stages import into stage 3 with history reconstructed.

    python3 tests/upgrade_check.py STAGE3_URL STAGE2_URL STAGE1_URL
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

S3, S2, S1 = (u.rstrip("/") for u in sys.argv[1:4])
PW = "correct horse"


def api(base, method, path, body=None, token=None, key=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if key:
        req.add_header("Idempotency-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else None)


def user(h, b):
    return {"id": f"u_{h}", "email": f"{h}@example.com", "password": PW, "display_name": h.title(), "handle": h, "balance": b}


def login(base, h):
    return api(base, "POST", "/auth/login", {"email": f"{h}@example.com", "password": PW})[1]["token"]


def q(**kw):
    return "?" + urllib.parse.urlencode(kw)


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        check.failed += 1


check.failed = 0


def scenario(old, with_holds):
    fx = {"currency": "EUR", "minor_units": 2, "settlement_operator_ids": ["u_cy"], "authorization_ttl_seconds": 3,
          "users": [user("ada", 10000), user("bob", 2500), user("cy", 500)],
          "payments": [{"id": "p_seed", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee"}]}
    assert api(old, "POST", "/_test/reset", fx)[0] == 204
    ada, bob, cy = (login(old, h) for h in ("ada", "bob", "cy"))
    p1 = api(old, "POST", "/payments", {"to_handle": "bob", "amount": 300}, ada, "k1")[1]
    st = api(old, "POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 5}]}, cy, "ks")[1]
    rq = api(old, "POST", "/requests", {"payer_handle": "ada", "amount": 40}, bob, "kr")[1]
    paid = api(old, "POST", f"/requests/{rq['request_id']}/pay", {}, ada, "kp")[1]
    holds = {}
    if with_holds:
        a1 = api(old, "POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, ada, "ka1")[1]
        c1 = api(old, "POST", f"/authorizations/{a1['authorization_id']}/capture", {"amount": 200, "final": False}, bob, "kc1")[1]
        api(old, "POST", f"/authorizations/{a1['authorization_id']}/void", None, ada)
        a2 = api(old, "POST", "/authorizations", {"to_handle": "bob", "amount": 700}, ada, "ka2")[1]
        c2 = api(old, "POST", f"/authorizations/{a2['authorization_id']}/capture", {"amount": 100}, bob, "kc2")[1]
        a3 = api(old, "POST", "/authorizations", {"to_handle": "cy", "amount": 50}, ada, "ka3")[1]
        a4 = api(old, "POST", "/authorizations", {"to_handle": "cy", "amount": 60}, ada, "ka4")[1]
        api(old, "POST", f"/authorizations/{a4['authorization_id']}/void", None, ada)
        time.sleep(3.3)    # a3 expires
        holds = {"a1": a1, "c1": c1, "a2": a2, "c2": c2, "a3": a3, "a4": a4}
    exported = api(old, "GET", "/_test/export")[1]
    before = {h: api(old, "GET", "/me", None, t)[1] for h, t in (("ada", ada), ("bob", bob), ("cy", cy))}
    assert api(S3, "POST", "/_test/import", exported)[0] == 204
    ada3, bob3, cy3 = (login(S3, h) for h in ("ada", "bob", "cy"))
    tok = {"ada": ada3, "bob": bob3, "cy": cy3}
    for h in tok:
        me = api(S3, "GET", "/me", None, tok[h])[1]
        check(me["balance"] == before[h]["balance"], f"{old[-5:]} /me balance of {h} preserved ({me['balance']})")
    check(api(S3, "GET", "/me", None, ada)[0] == 200, "old bearer token still valid")
    check(api(S3, "POST", "/payments", {"to_handle": "bob", "amount": 300}, ada, "k1")[1] == p1, "payment replay after import is 200 with the original body")
    revs = api(S3, "GET", f"/payments/{p1['payment_id']}/revisions", None, ada3)[1]["revisions"]
    check(len(revs) == 1 and revs[0]["effective_at"] == p1["created_at"] == revs[0]["recorded_at"], "revision 1 reconstructed")
    stmt = api(S3, "GET", "/statement", None, ada3)[1]
    check(stmt["opening_balance"] + sum(e["delta"] for e in stmt["entries"]) == stmt["closing_balance"], "statement arithmetic closes")
    check(stmt["opening_balance"] == 10000 + 500 - 0 if False else stmt["opening_balance"] == 10000 + 500, "opening balance = ending balance minus the net effect of the seeded payment (only that one is before the import)... ")
    check(stmt["closing_balance"] == before["ada"]["balance"], "closing balance equals the current balance")
    long_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    check(api(S3, "GET", "/me" + q(as_of=long_ago), None, ada3)[1]["balance"] == stmt["opening_balance"], "as_of before everything -> opening balance")
    check(sum(api(S3, "GET", "/me" + q(as_of=long_ago), None, t)[1]["balance"] for t in tok.values()) == 13000, "sum over users in an old view is the seeded total")
    r = api(S3, "POST", f"/payments/{p1['payment_id']}/corrections",
            {"expected_revision": 1, "amount": 100, "effective_at": p1["created_at"], "reason": "ok"}, ada3, "kc")
    check(r[0] == 201, "an imported payment can be corrected")
    check(api(S3, "POST", f"/payments/{st['payment_id']}/corrections" if False else f"/payments/{st['payments'][0]['payment_id']}/corrections",
              {"expected_revision": 1, "amount": 1, "effective_at": p1["created_at"], "reason": "x"}, ada3, "ks2")[1]["error"]["code"] == "linked_payment_immutable",
          "an imported settlement member is immutable")
    if with_holds:
        auths = {a["authorization_id"]: a for a in api(S3, "GET", "/authorizations", None, ada3)[1]["authorizations"]}
        a1, a2, a3, a4 = (auths[holds[k]["authorization_id"]] for k in ("a1", "a2", "a3", "a4"))
        check(a1["closed_at"] == holds["c1"]["created_at"], "voided hold with a capture: closed at its last capture's time")
        check(a2["closed_at"] == holds["c2"]["created_at"], "final-captured hold: closed at that capture's time")
        check(a3["closed_at"] == a3["expires_at"] and a3["status"] == "expired", "expired hold: closed at expires_at")
        check(a4["closed_at"] == a4["created_at"], "voided hold with no capture: closed at its creation")
        for key, a, want in (("a1", a1, 1000), ("a4", a4, 50)):    # a4 itself holds nothing; a3 (50) is still open then
            v = api(S3, "GET", "/me" + q(as_of=a["created_at"]), None, ada3)[1]
            check(v["held"] == want and v["available"] >= 0, f"{key}: held {v['held']} at its creation (expected {want})")
        v = api(S3, "GET", "/me" + q(as_of=datetime.now(timezone.utc).isoformat()), None, ada3)[1]
        check(v["held"] == 0 and v["available"] == v["total"], "current view releases everything")
    check(api(S3, "GET", "/_test/export")[0] == 200, "stage-3 export works after upgrade")


scenario(S1, False)
scenario(S2, True)
print("FAILED" if check.failed else "OK")
sys.exit(1 if check.failed else 0)
