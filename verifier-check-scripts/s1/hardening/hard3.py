import json, os, sys, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import BASE, World, call, fixture, user, k, burst, statuses, VIOLATIONS

def show(label, r):
    print(f"{label:62s} -> {r.status_code} {r.text[:100]!r}", flush=True)

w = World().login_all(); t = w.t("ada")
for depth in (20, 100, 200, 300, 400, 600):
    body = '{"to_handle":"bob","amount":1,"x":' + "[" * depth + "]" * depth + "}"
    key = f"deep{depth}"
    a = call("POST", "/payments", t, key=key, raw=body); b = call("POST", "/payments", t, key=key, raw=body)
    print(f"nested depth {depth}: first {a.status_code}, replay {b.status_code}", flush=True)
for depth in (100, 300, 600):
    body = '{"to_handle":"bob","amount":1,"x":' + '{"a":' * depth + "1" + "}" * depth + "}"
    key = f"deepobj{depth}"
    a = call("POST", "/payments", t, key=key, raw=body); b = call("POST", "/payments", t, key=key, raw=body)
    print(f"nested objects depth {depth}: first {a.status_code}, replay {b.status_code}", flush=True)
q = w.new_request("bob", "ada", 5); rid = q["request_id"]
enc = rid.replace("_", "%5F")
a = call("POST", f"/requests/{rid}/pay", t, key="enc1", body={})
show("pay (plain path)", a)
show("replay through percent-encoded path of the same request", call("POST", f"/requests/{enc}/pay", t, key="enc1", body={}))
show("duplicate JSON keys amount 0 then 5", call("POST", "/payments", t, key=k(), raw='{"to_handle":"bob","amount":0,"amount":5}'))
show("display_name empty on signup", call("POST", "/auth/signup", body={"email": "e1@example.com", "password": "longenough1", "display_name": ""}))
show("email with spaces/newline on signup", call("POST", "/auth/signup", body={"email": "a b\n@exa mple.com", "password": "longenough1", "display_name": "x"}))
# resets and imports racing with traffic, 50 in flight
w = World().login_all()
e = call("GET", "/_test/export").json()
toks = {h: w.t(h) for h in w.handles()}
def traffic(i):
    h = ["ada", "bob", "dan", "op"][i % 4]
    kind = i % 5
    if kind == 0: return call("POST", "/payments", toks[h], key=k(), body={"to_handle": "cy", "amount": 1})
    if kind == 1: return call("GET", "/activity", toks[h])
    if kind == 2: return call("POST", "/requests", toks[h], key=k(), body={"payer_handle": "cy", "amount": 1})
    if kind == 3: return call("POST", "/auth/login", body={"email": f"{h}@example.com", "password": "correct horse"})
    return call("GET", "/_test/export")
for rnd in range(3):
    fns = [lambda i=i: traffic(i) for i in range(40)]
    fns += [lambda: call("POST", "/_test/import", body=e) for _ in range(5)]
    fns += [lambda: call("POST", "/_test/reset", body=w.fx) for _ in range(5)]
    rs = burst(fns)
    print("race round", rnd, statuses(rs), "max s", round(max(r.elapsed_s for r in rs), 3), flush=True)
rs = burst([lambda: call("POST", "/_test/reset", body=w.fx) for _ in range(50)])
print("50 concurrent resets", statuses(rs), "max s", round(max(r.elapsed_s for r in rs), 3), flush=True)
big = fixture(users=[user(f"user_{i:03d}", 10) for i in range(500)])
r = call("POST", "/_test/reset", body=big); print("reset 500 users", r.status_code, round(r.elapsed_s, 2), flush=True)
# tampered import states
w = World().login_all(); ok = w.pay("ada", "bob", 5); e = call("GET", "/_test/export").json(); before = w.snapshot()
def tamper(label, fn):
    d = copy.deepcopy(e); fn(d["state"]); r = call("POST", "/_test/import", body=d)
    same = w.snapshot() == before if r.status_code != 204 else None
    reads = [call("GET", p, w.tok["ada"]).status_code for p in ("/me", "/activity", "/requests")] if r.status_code == 204 else None
    print(f"import tamper {label:44s} -> {r.status_code} unchanged={same} reads={reads}", flush=True)
    if r.status_code == 204: call("POST", "/_test/import", body=e)
tamper("user balance -1", lambda s: s["users"][0].__setitem__("balance", -1))
tamper("user balance 1.5", lambda s: s["users"][0].__setitem__("balance", 1.5))
tamper("user balance '5'", lambda s: s["users"][0].__setitem__("balance", "5"))
tamper("token -> unknown user", lambda s: s["tokens"].__setitem__("tok", "u_ghost"))
tamper("payment from unknown user", lambda s: s["payments"][0].__setitem__("from_user_id", "u_ghost"))
tamper("payment amount -5", lambda s: s["payments"][0].__setitem__("amount", -5))
tamper("payment amount 2.5", lambda s: s["payments"][0].__setitem__("amount", 2.5))
tamper("payment visibility 'x'", lambda s: s["payments"][0].__setitem__("visibility", "x"))
tamper("payment request_id 5", lambda s: s["payments"][0].__setitem__("request_id", 5))
tamper("payment created_at 'yesterday'", lambda s: s["payments"][0].__setitem__("created_at", "yesterday"))
tamper("duplicate user handle", lambda s: s["users"][1].__setitem__("handle", s["users"][0]["handle"]))
tamper("operator unknown", lambda s: s["operators"].append("u_ghost"))
tamper("minor_units 7", lambda s: s.__setitem__("minor_units", 7))
tamper("user pw_hash 'x'", lambda s: s["users"][0].__setitem__("pw_hash", "x"))
tamper("idempotency response null", lambda s: s["idempotency"][0].__setitem__("response", None))
tamper("users balance sum changed (+1000)", lambda s: s["users"][0].__setitem__("balance", s["users"][0]["balance"] + 1000))
tamper("user id 100 chars", lambda s: (s["tokens"].clear(), s["payments"].clear(), s["idempotency"].clear(), s["operators"].clear(), s["users"][0].__setitem__("id", "u" * 100)))
print("violations recorded:", [(v["kind"], v["method"], v["path"][:40], v["status"]) for v in VIOLATIONS][:20])
print("health", call("GET", "/health").status_code)
