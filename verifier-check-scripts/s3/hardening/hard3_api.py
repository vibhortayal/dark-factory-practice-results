"""Stage-3 hardening (first revision only, 15 minutes by the clock). Prints findings; asserts nothing fatal."""
import sys, time, random
sys.path.insert(0, "/home/ubuntu/nightshift-claude-run-5/band-work/verifier/s3")
from fractions import Fraction
from lib import *
from test_r_time import sp, ago

F = []
def finding(name, **kw):
    F.append((name, kw)); print("FINDING", name, kw)
def chk(cond, name, **kw):
    if not cond: finding(name, **kw)
    return cond

# 29. odd payment ids on the new routes
odd = ["a/b", "sp ace", "ünï-😀", "x" * 64, "with?q=1&y", "per%25cent", "dot.dot..", "#hash", "p+plus", "semi;colon", "..", "revisions", "corrections"]
t = ago(2)
pays = [sp(pid, "ada", "bob", 10, fmt(t + i)) for i, pid in enumerate(odd)]
w = World(fixture(users=[user("ada", 10000 - 10 * len(odd)), user("bob", 2500 + 10 * len(odd)), user("cy", 0)], payments=pays, ops=[])).login_all()
for pid in odd:
    r = revisions(w, "ada", pid)
    if chk(r.status_code == 200 and r.json()["revisions"][0]["payment_id"] == pid, "odd-id-revisions", pid=pid, status=r.status_code, body=r.text[:120]):
        c = correct(w, "ada", pid, 1, 7, fmt(t), "odd")
        chk(c.status_code == 201 and c.json()["payment_id"] == pid, "odd-id-correction", pid=pid, status=c.status_code, body=c.text[:120])
        chk(revisions(w, "cy", pid).status_code == 404, "odd-id-third-party", pid=pid)
s = full_statement(w, "ada")
chk(sorted(e["payment"]["payment_id"] for e in s["entries"]) == sorted(odd), "odd-id-statement")
chk([e["payment"]["payment_id"] for e in s["entries"]] == sorted(odd), "tie-order-code-point", got=[e["payment"]["payment_id"] for e in s["entries"]])
m = build_model(w); check_everything(w, m, random.Random(1), me_points=10, st_points=5)
e = call("GET", "/_test/export"); chk(call("POST", "/_test/import", raw=e.content).status_code == 204, "odd-id-reimport")
# 28 / 18 paths and methods
for path in ("/statement/", "/payments//corrections", "/payments/a%2Fb/revisions/", "/payments/a/b/revisions", "/payments", "/payments/a%2Fb", "/me/", "/statement?snapshot=%"):
    for method in ("GET", "POST", "HEAD", "OPTIONS", "DELETE"):
        r = call(method, path, w.t("ada"), key=k() if method == "POST" else None, body={} if method == "POST" else lib._NO if False else {}, kind="any") if method == "POST" else call(method, path, w.t("ada"), kind="any")
        chk(r.status_code < 500, "5xx-path", path=path, method=method, status=r.status_code)

# 8. equal instants in different spellings; fractions with trailing zeros
w = World().login_all()
p = ok(w.pay("ada", "bob", 100), 201); c0 = inst(p["created_at"])
for sp_ in (fmt(c0) , fmt(c0, 330), fmt(c0, -720)):
    for extra in ("", "0", "000000000"):
        v = sp_
        if "." in sp_ and extra:
            i = max(sp_.rfind("+"), sp_.rfind("-")); v = sp_[:i] + extra + sp_[i:]
        b = ok(me_at(w, "ada", v), 200)
        chk(b["balance"] == 9900 and b["as_of"] == v, "spelling-of-equal-instant", v=v, body=b)
        st = ok(statement(w, "ada", **{"from": v}), 200)
        chk(len(st["entries"]) == 1, "from-inclusive-spelling", v=v)
        st = ok(statement(w, "ada", to=v), 200)
        chk(len(st["entries"]) == 0, "to-exclusive-spelling", v=v)

# 22. corrections that take money back race the receiver spending it
w = World(fixture(users=[user("ada", 100000), user("bob", 0), user("cy", 0), user("dan", 0)], ops=[])).login_all()
ps = [ok(w.pay("ada", "bob", 100), 201) for _ in range(25)]          # bob 2500
fns = [lambda p=p: correct(w, "ada", p["payment_id"], 1, 0, p["created_at"], "take back") for p in ps]
fns += [lambda i=i: w.pay("bob", "cy", 100) for i in range(15)] + [lambda i=i: w.authorize("bob", "dan", 100) for i in range(10)]
rs = burst(fns)
print("race statuses", statuses(rs), sorted({code_of(r) for r in rs if r.status_code >= 400}))
bw = w.wallet("bob"); chk(bw["available"] >= 0 and bw["total"] >= 0, "negative-after-race", bob=bw)
w.assert_conserved()
m = build_model(w)
od = m.overdraft(list(m.opening), now_f())
chk(od is None, "history-negative-after-race", od=od)
check_everything(w, m, random.Random(2), me_points=25, st_points=6)

# 11. reads during writes are internally consistent
w = World().login_all()
ps = [ok(w.pay("ada", "bob", 50), 201) for _ in range(8)]
bad = []
def reader():
    j = statement(w, "ada", limit=200).json()
    run = j["opening_balance"]
    for e in j["entries"]:
        run += e["delta"]
        if e["balance_after"] != run: bad.append(("walk", j))
    if run != j["closing_balance"]: bad.append(("closing", j["opening_balance"], run, j["closing_balance"]))
    return j
for rnd in range(3):
    fns = [reader for _ in range(25)] + [lambda i=i: correct(w, "ada", ps[i % 8]["payment_id"], rnd + 1, 10 + i, fmt(now_f() - 1 - i), "r") for i in range(8)] + [lambda: w.pay("ada", "bob", 3) for _ in range(17)]
    burst(fns)
chk(not bad, "inconsistent-statement-read", sample=str(bad[:2])[:400])
tot = [ok(me_at(w, h, fmt(now_f() - 2)), 200)["balance"] for h in w.handles()]
chk(sum(tot) == w.seeded_total(), "sum-as-of", tot=tot)

# 25. expiry by the clock and corrections; known_at without as_of
w = World(fixture(users=[user("ada", 100), user("bob", 0), user("cy", 0)], ttl=1, ops=[])).login_all()
p = ok(w.pay("ada", "cy", 10), 201)
a = w.new_auth("ada", "bob", 80)
r = correct(w, "ada", p["payment_id"], 1, 30, p["created_at"], "while held")
chk(r.status_code == 409 and code_of(r) == "insufficient_funds", "held-now", status=r.status_code, code=code_of(r))
time.sleep(1.3)
r = correct(w, "ada", p["payment_id"], 1, 30, p["created_at"], "after expiry, effective before the hold")
chk(r.status_code == 409 and code_of(r) == "historical_overdraft", "expired-hold-in-history", status=r.status_code, code=code_of(r), body=r.text[:200])
r = correct(w, "ada", p["payment_id"], 1, 30, a["expires_at"], "from the deadline")
chk(r.status_code == 201, "after-deadline", status=r.status_code, body=r.text[:200])
b = ok(me_at(w, "ada", None, a["created_at"]), 200)
chk((b["total"], b["held"]) == (90, 0), "known_at-only-after-expiry", body=b)   # only the hold's creation known; T = now >= deadline
b = ok(me_at(w, "ada", fmt(inst(a["expires_at"]) - US), a["created_at"]), 200)
chk((b["total"], b["held"]) == (90, 80), "known_at-before-payment-known", body=b)
check_everything(w, build_model(w), random.Random(3), me_points=30, st_points=6)

# 13. seeded created_at at the edges
for name, v, want in (("now-ish", fmt(now_f() - 1), (204,)), ("year 1", "0001-01-01T00:00:00Z", (204, 422)), ("utc year 0", "0001-01-01T00:00:00+05:00", (204, 422)),
                      ("year 9999 future", "9999-12-31T23:59:59Z", (422,)), ("long fraction", "2020-01-01T00:00:00." + "1" * 300 + "Z", (204, 422))):
    r = POST("/_test/reset", body=fixture(users=[user("ada", 90), user("bob", 10)], payments=[sp("p", "ada", "bob", 10, v)], ops=[]))
    chk(r.status_code in want, "seeded-created_at-edge", case=name, status=r.status_code, body=r.text[:150])
    if r.status_code == 204:
        w = World(fixture(users=[user("ada", 90), user("bob", 10)], payments=[sp("p", "ada", "bob", 10, v)], ops=[]), do_reset=False).login_all()
        for ep in ("/me", "/statement", "/activity", "/payments/p/revisions", "/me?as_of=2000-01-01T00%3A00%3A00Z"):
            chk(GET(ep, w.t("ada")).status_code == 200, "read-after-edge-seed", case=name, ep=ep)
        e = call("GET", "/_test/export"); chk(call("POST", "/_test/import", raw=e.content).status_code == 204, "edge-reimport", case=name)
        check_everything(w, build_model(w), random.Random(4), me_points=8, st_points=4)
# signup account re-timed before it existed
w = World().login_all()
su = w.signup("late.one@example.com")
p = ok(w.pay("ada", su["handle"], 500), 201)
p2 = ok(w.pay(su["handle"], "bob", 200), 201)
r = correct(w, su["handle"], p2["payment_id"], 1, 200, "2020-01-01T00:00:00Z", "before the account existed")
chk(r.status_code == 409 and code_of(r) == "historical_overdraft", "retime-before-account", status=r.status_code, code=code_of(r))
r = correct(w, "ada", p["payment_id"], 1, 500, "2020-01-01T00:00:00Z", "funding re-timed to before the account existed")
chk(r.status_code == 201, "fund-before-account", status=r.status_code, body=r.text[:200])
check_everything(w, build_model(w), random.Random(5), me_points=20, st_points=6)
print("VIOLATIONS", [(v["kind"], v.get("path"), v.get("status")) for v in VIOLATIONS][:20])
print("FINDINGS", len(F)); [print(" ", f) for f in F]
