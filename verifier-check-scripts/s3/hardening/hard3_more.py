import sys, time, random, re
sys.path.insert(0, "/home/ubuntu/nightshift-claude-run-5/band-work/verifier/s3")
from lib import *
import lib
F = []
def chk(cond, name, **kw):
    if not cond: F.append((name, kw)); print("FINDING", name, kw)
    return cond
# C. tampered snapshot tokens
w = World().login_all()
ps = [ok(w.pay("ada", "bob", 10 + i), 201) for i in range(5)]
first = ok(statement(w, "ada", limit=2), 200); tok = first["snapshot"]
print("token:", tok[:80], len(tok))
alphabet = "ABCxyz019_-=.+/"
n200 = 0
for i in range(len(tok)):
    for ch in (alphabet[i % len(alphabet)], "A", "0"):
        if ch == tok[i]: continue
        t2 = tok[:i] + ch + tok[i + 1:]
        r = statement(w, "ada", snapshot=t2, limit=2)
        if r.status_code == 200:
            n200 += 1
            chk(r.json()["entries"] == first["entries"] and r.json()["closing_balance"] == first["closing_balance"], "tampered-token-other-data", i=i, ch=ch)
        else:
            chk(r.status_code == 404, "tampered-token-status", i=i, ch=ch, status=r.status_code)
print("tampered tokens answered 200 (same data):", n200)
tb = ok(statement(w, "bob", limit=2), 200)["snapshot"]
for cut in range(1, len(tok), 7):
    r = statement(w, "ada", snapshot=tok[:cut] + tb[cut:], limit=2)
    chk(r.status_code in (404,) or (r.status_code == 200 and r.json()["entries"] == first["entries"]), "spliced-token", cut=cut, status=r.status_code)
r = call("GET", "/statement?" + q(snapshot=tok), w.t("ada"), base=lib.BASE2)
chk(r.status_code in (401, 404), "token-on-other-container", status=r.status_code)
# long windows make long tokens (registry fallback): from/to with 150-digit fractions
longf = "2020-01-01T00:00:00." + "1" * 150 + "Z"; longt = "2030-01-01T00:00:00." + "7" * 150 + "+05:30"
big = ok(statement(w, "ada", **{"from": longf, "to": longt, "known_at": longt, "limit": 2}), 200)
print("long-window token length", len(big["snapshot"]))
ok(w.pay("ada", "bob", 500), 201)
pg = ok(statement(w, "ada", snapshot=big["snapshot"], limit=2), 200)
chk(pg["entries"] == big["entries"] and pg["closing_balance"] == big["closing_balance"], "long-token-frozen")
e = call("GET", "/_test/export"); chk(call("POST", "/_test/import", raw=e.content).status_code == 204, "reimport-with-registry-token")
pg = statement(w, "ada", snapshot=big["snapshot"], limit=2)
chk(pg.status_code == 200 and pg.json()["entries"] == big["entries"], "long-token-after-import", status=pg.status_code)
# G. many first reads: memory stays flat, old tokens keep working
import subprocess
def mem():
    return subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", "nsv3-a"], capture_output=True, text=True).stdout.strip()
m0 = mem()
toks = []
for i in range(4000):
    r = statement(w, "ada" if i % 2 else "bob", limit=1, **({"from": longf, "to": longt} if i % 10 == 0 else {}))
    if i % 400 == 0: toks.append(("ada" if i % 2 else "bob", r.json()["snapshot"], r.json()))
print("memory before/after 4000 first reads:", m0, "->", mem())
for h, t, j in toks:
    r = statement(w, h, snapshot=t, limit=1)
    chk(r.status_code == 200 and r.json()["entries"] == j["entries"], "old-token-after-many-reads", status=r.status_code)
e = call("GET", "/_test/export"); print("export size after 4000 reads:", len(e.content), "elapsed", round(e.elapsed_s, 3))
chk(call("POST", "/_test/import", raw=e.content).status_code == 204, "reimport-after-many-reads")
print("VIOLATIONS", [(v["kind"], v.get("path"), v.get("status")) for v in VIOLATIONS][:20]); print("FINDINGS", len(F), F)
