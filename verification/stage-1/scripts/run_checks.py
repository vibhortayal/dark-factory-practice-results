"""Runner: python run_checks.py [--list] [id-prefix ...]   (env TK_BASE, TK_BASE2, TK_OUT)"""
import json
import os
import sys
import time
import traceback

import vlib
import c_runtime, c_auth, c_idem, c_avail, c_resv, c_dst, c_moves, c_export, c_conc, c_fuzz  # noqa: F401,E401

args = [a for a in sys.argv[1:] if not a.startswith("--")]
if "--list" in sys.argv:
    for cid, clause, title, _fn in vlib.CHECKS:
        print(f"- **{cid}** — {clause} — {title}")
    sys.exit(0)

out = os.environ.get("TK_OUT")
if out:
    os.makedirs(out, exist_ok=True)
results = []
t00 = time.time()
for cid, clause, title, fn in vlib.CHECKS:
    if args and not any(cid.startswith(a) for a in args):
        continue
    n0 = len(vlib.LOG)
    t0 = time.time()
    try:
        fn()
        st, detail = "PASS", ""
    except AssertionError as e:
        st, detail = "FAIL", str(e)
    except Exception:
        st, detail = "ERROR", traceback.format_exc()
    results.append({"id": cid, "clause": clause, "title": title, "status": st, "detail": detail,
                    "requests": len(vlib.LOG) - n0, "seconds": round(time.time() - t0, 2)})
    print(f"{st:5} {cid:8} {title}  [{len(vlib.LOG) - n0} req, {time.time() - t0:.1f}s]")
    if st != "PASS":
        print("      " + detail.replace("\n", "\n      ")[:3000])

# global checks over the whole request log
def glob(cid, clause, title, key):
    bad = [e for e in vlib.LOG if key in e["problems"]]
    st = "PASS" if not bad else "FAIL"
    detail = "" if not bad else f"{len(bad)} request(s); first: " + json.dumps(bad[:5])[:2500]
    results.append({"id": cid, "clause": clause, "title": title, "status": st, "detail": detail, "requests": 0, "seconds": 0})
    print(f"{st:5} {cid:8} {title}  [{len(bad)} offending of {len(vlib.LOG)}]")
    if bad:
        print("      " + detail)

if not args:
    glob("G-5XX", "§5 'Requests must not produce 5xx responses, including under concurrent load'", "no 5xx (or transport failure) in the whole run", "5xx")
    glob("G-ENVELOPE", "§5 'Every 4xx and 5xx response carries this body'", "error envelope {error:{code,message}} on every 4xx/5xx", "envelope")
    glob("G-CTYPE", "§3.4 'Requests and responses are application/json; charset=utf-8'", "content type of every response that has a body", "ctype")
    glob("G-204", "§3.3 / §10 '204 No Content'", "no 204 response carries a body", "204-with-body")
    glob("G-TIME", "§2 'Per-request timeout 5 s (10 s for POST /_test/reset)' / §10 'Test control calls have a 10-second timeout'", "every request within its limit", "slow")

npass = sum(1 for r in results if r["status"] == "PASS")
el = sorted(e["elapsed"] for e in vlib.LOG) or [0]
codes = {}
for e in vlib.LOG:
    codes[e["status"]] = codes.get(e["status"], 0) + 1
print(f"\nCHECKS {npass} passed, {len(results) - npass} failed, of {len(results)}; {len(vlib.LOG)} requests in {time.time() - t00:.0f}s; "
      f"slowest {el[-1]:.2f}s; status tally {dict(sorted(codes.items()))}")
if out:
    json.dump(results, open(os.path.join(out, "results.json"), "w"), indent=1)
    with open(os.path.join(out, "requests.jsonl"), "w") as f:
        for e in vlib.LOG:
            f.write(json.dumps(e) + "\n")
sys.exit(0 if npass == len(results) else 1)
