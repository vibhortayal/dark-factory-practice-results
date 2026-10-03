"""Stage-4 hardening (first revision only, 15 minutes by the clock)."""
import sys, time, random, copy, json
sys.path.insert(0, "/home/ubuntu/nightshift-claude-run-5/band-work/verifier/s4")
from fractions import Fraction
from lib import *
import lib
from test_r_time import sp, ago
F = []
def chk(cond, name, **kw):
    if not cond: F.append((name, kw)); print("FINDING", name, kw)
    return cond
def paths(node, pred, prefix=()):
    if isinstance(node, dict):
        for kk, v in node.items():
            if pred(kk, v): yield prefix + (kk,)
            yield from paths(v, pred, prefix + (kk,))
    elif isinstance(node, list):
        for i, v in enumerate(node): yield from paths(v, pred, prefix + (i,))
def setp(doc, path, value):
    cur = doc
    for x in path[:-1]: cur = cur[x]
    cur[path[-1]] = value

# 1. import validation of the stage-4 members (extent of the correction_batch_id finding)
w = World().login_all()
p = ok(w.pay("ada", "bob", 100), 201)
q = ok(w.pay("ada", "cy", 50), 201)
rf = ok(refund(w, "bob", p["payment_id"], 10, key="k-rf"), 201)
bj = ok(batch(w, [item(p, 60), item(q, 40)], key="k-b"), 201)
e = call("GET", "/_test/export").json()
targets = list(paths(e, lambda kk, v: kk in ("refund_of", "batch_id", "correction_batch_id") and v is not None))
print("non-null stage-4 members in the export:", len(targets))
accepted = []
for loc in targets:
    for value in ("y" * 300, "y" * 65, "", "p_nope", q["payment_id"], rf["payment_id"]):
        doc = copy.deepcopy(e); setp(doc, loc, value)
        r = call("POST", "/_test/import", body=doc)
        chk(r.status_code in (204, 422), "import-status", loc=loc, status=r.status_code)
        if r.status_code == 204:
            accepted.append((loc[1:], value[:12], len(value)))
            x = call("GET", "/_test/export"); chk(x.status_code == 200 and call("POST", "/_test/import", raw=x.content).status_code == 204, "reexport", loc=loc)
            for h in ("ada", "bob", "cy"):
                for ep in ("/me", "/activity?limit=200", "/statement?limit=200", f"/payments/{p['payment_id']}/revisions"):
                    chk(GET(ep, w.t(h)).status_code < 500, "5xx-after-mutant", ep=ep)
            call("POST", "/payments/%s/refunds" % p["payment_id"], w.t("bob"), key="k-rf", body={"amount": 10})
            call("POST", "/correction-batches", w.t("op"), key="k-b", body={"corrections": [item(p, 60), item(q, 40)]})
        call("POST", "/_test/import", body=e)
print("ACCEPTED MUTANTS:"); [print("  ", a) for a in accepted]

# 2. new routes: methods, odd ids
odd = ["a/b", "sp ace", "ünï-😀", "with?q=1&y", "per%25cent", "#hash", "..", "refunds", "corrections"]
t = ago(2)
pays = [sp(pid, "ada", "bob", 10, fmt(t + i)) for i, pid in enumerate(odd)]
w = World(fixture(users=[user("ada", 10000 - 10 * len(odd)), user("bob", 2500 + 10 * len(odd)), user("cy", 0), user("op", 0)], payments=pays)).login_all()
for pid in odd:
    r = refund(w, "bob", pid, 3)
    chk(r.status_code == 201 and r.json()["refund_of"] == pid, "odd-id-refund", pid=pid, status=r.status_code, body=r.text[:100])
its = [{"payment_id": pid, "expected_revision": 1, "amount": 5, "effective_at": fmt(t), "reason": "odd"} for pid in odd]
r = batch(w, its); chk(r.status_code == 201, "odd-id-batch", status=r.status_code, body=r.text[:150])
chk(w.bal("bob") == 2500 + 5 * len(odd) - 3 * len(odd), "odd-balance", bal=w.bal("bob"))
check_everything(w, build_model(w), random.Random(1), me_points=10, st_points=4)
for path in ("/correction-batches/", "/correction-batches/cb_1", "/payments//refunds", "/payments/a%2Fb/refunds/", "/payments/a%2Fb/refunds/x"):
    for method in ("GET", "POST", "HEAD", "OPTIONS", "DELETE", "PUT"):
        r = call(method, path, w.t("op"), kind="any") if method != "POST" else call(method, path, w.t("op"), key=k(), body={}, kind="any")
        chk(r.status_code < 500, "5xx-path", path=path, method=method, status=r.status_code)

# 3. refunds race the refunder spending and holding the money; the same key on three paths
w = World(fixture(users=[user("ada", 5000), user("bob", 0), user("cy", 0), user("dan", 0), user("op", 0)])).login_all()
ps = [ok(w.pay("ada", "bob", 100), 201) for _ in range(20)]          # bob 2000
fns = [lambda p=p: refund(w, "bob", p["payment_id"], 100) for p in ps] + [lambda: w.pay("bob", "cy", 100) for _ in range(15)] + \
      [lambda: w.authorize("bob", "dan", 100) for _ in range(15)]
rs = burst(fns); print("race", statuses(rs), sorted({code_of(r) for r in rs if r.status_code >= 400}))
bw = w.wallet("bob"); chk(bw["available"] >= 0 and statuses(rs).get(201) == 20, "refund-race", bob=bw, st=statuses(rs))
w.assert_conserved()
m = build_model(w); chk(m.overdraft(list(m.opening), now_f()) is None, "history-after-race")
key = k()
p = ok(w.pay("ada", "bob", 100), 201)
ok(w.pay("cy", "bob", 100) if w.bal("cy") >= 100 else w.pay("ada", "bob", 100), 201)
r1 = correct(w, "ada", p["payment_id"], 1, 90, p["created_at"], key=key)
r2 = call("POST", f"/payments/{p['payment_id']}/refunds", w.t("ada"), key=key, body={"expected_revision": 1, "amount": 90, "effective_at": p["created_at"], "reason": "fix"})
chk(r1.status_code == 201 and r2.status_code == 403, "same-key-other-path", a=r1.status_code, b=r2.status_code)
r3 = refund(w, "bob", p["payment_id"], 5, key=key); r4 = call("POST", "/correction-batches", w.t("op"), key=key, body={"amount": 5})
chk(r3.status_code == 201 and r4.status_code == 422, "same-key-three-paths", a=r3.status_code, b=r4.status_code)

# 4. views around a batch's shared recorded_at; a settlement re-timed as a whole; batch that would overdraw a third wallet
w = World(fixture(users=[user("ada", 1000), user("bob", 0), user("cy", 0), user("op", 0)])).login_all()
st = ok(POST("/settlements", w.t("op"), {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 300}, {"from_handle": "bob", "to_handle": "cy", "amount": 300}]}, key=k()), 201)
m0, m1 = st["payments"]; tc = inst(st["committed_at"])
time.sleep(0.05)
x = ok(w.pay("cy", "ada", 250), 201)
its = [item(m0, 100), item(m1, 300)]
r = batch(w, its); chk(r.status_code == 409 and code_of(r) == "insufficient_funds", "batch-net-shortfall", status=r.status_code, code=code_of(r))   # bob would return 200 and has 0
its = [item(m0, 100), item(m1, 100)]                # cy must return 200 and has 50
r = batch(w, its); chk(r.status_code == 409 and code_of(r) == "insufficient_funds", "batch-third-wallet", status=r.status_code, code=code_of(r))
its = [item(m0, 250), item(m1, 250)]                # cy returns 50: today fine; in history cy paid 250 out of 250: fine
j = ok(batch(w, its), 201); rec = inst(j["recorded_at"])
for h, before, after in (("ada", 950, 1000), ("bob", 0, 0), ("cy", 50, 0)):
    a = ok(me_at(w, h, None, fmt(rec - US)), 200)["balance"]; b = ok(me_at(w, h, None, fmt(rec)), 200)["balance"]
    chk((a, b) == (before, after), "known_at-around-batch", h=h, got=(a, b), want=(before, after))
its = [item(m0, 250, expected=2, effective_at=fmt(inst(x["created_at"]) + US)), item(m1, 250, expected=2, effective_at=fmt(inst(x["created_at"]) + US, 120))]
r = batch(w, its); chk(r.status_code == 409 and code_of(r) == "historical_overdraft", "settlement-retimed-after-spending", status=r.status_code, code=code_of(r))
its = [item(m0, 250, expected=2, effective_at=x["created_at"]), item(m1, 250, expected=2, effective_at=fmt(inst(x["created_at"]), 120))]
r = batch(w, its); chk(r.status_code == 201, "settlement-retimed-to-the-spending-instant", status=r.status_code, body=r.text[:200])
check_everything(w, build_model(w), random.Random(2), me_points=40, st_points=10)

# 5. refunds and holds: a refund of a capture does not touch the authorisation or expired holds; refund then correction history
w = World(fixture(users=[user("ada", 1000), user("bob", 0), user("cy", 0), user("op", 0)], ttl=1)).login_all()
a = w.new_auth("ada", "bob", 600)
c = ok(w.capture("bob", a["authorization_id"], body={"amount": 200, "final": False}), 201)
r = refund(w, "bob", c["payment_id"], 200); chk(r.status_code == 201, "refund-of-nonfinal-capture", status=r.status_code)
au = w.auth("ada", a["authorization_id"]); chk((au["status"], au["captured_amount"], au["remaining_amount"]) == ("open", 200, 400), "auth-after-refund", au=au)
chk(w.wallet("ada")["held"] == 400 and w.wallet("ada")["total"] == 1000, "wallet-after-refund", wal=w.wallet("ada"))
time.sleep(1.2)
au = w.auth("ada", a["authorization_id"]); chk(au["status"] == "expired" and au["captured_amount"] == 200, "expired-after-refund", au=au)
r = refund(w, "bob", c["payment_id"], 1); chk(r.status_code == 422 and code_of(r) == "refund_exceeds_payment", "refund-over-capture", status=r.status_code)
check_everything(w, build_model(w), random.Random(3), me_points=30, st_points=6)
print("VIOLATIONS", [(v["kind"], v.get("path"), v.get("status"), str(v.get("value"))[:20]) for v in VIOLATIONS][:20]); print("FINDINGS", len(F)); [print("  ", f) for f in F]
