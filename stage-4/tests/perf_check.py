"""History-heavy load against a running container: python3 tests/perf_check.py URL"""
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = sys.argv[1].rstrip("/")


def call(method, path, body=None, token=None, key=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if key:
        req.add_header("Idempotency-Key", key)
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    return status, (json.loads(raw) if raw else None), time.time() - start


now = datetime.now(timezone.utc)
users = [{"id": f"u{i}", "email": f"u{i}@x.io", "password": "correct horse", "display_name": f"U{i}", "handle": f"u{i}",
          "balance": 10 ** 7} for i in range(3)]
payments = [{"id": f"p{i}", "from_user_id": f"u{i % 3}", "to_user_id": f"u{(i + 1) % 3}", "amount": 1 + i % 50,
             "created_at": (now - timedelta(seconds=6000 - i)).isoformat()} for i in range(5000)]
status, _, took = call("POST", "/_test/reset", {"users": users, "payments": payments})
print(f"reset with 5000 payments: {status} in {took:.2f}s")
assert status == 204 and took < 10
tok = [call("POST", "/auth/login", {"email": f"u{i}@x.io", "password": "correct horse"})[1]["token"] for i in range(3)]
results, lock = [], threading.Lock()


def worker(i):
    t = tok[i % 3]
    kind = i % 5
    if kind == 0:
        r = call("GET", "/statement?limit=200", token=t)
    elif kind == 1:
        r = call("GET", "/me?as_of=" + urllib.parse.quote((now - timedelta(seconds=3000)).isoformat()), token=t)
    elif kind == 2:
        r = call("POST", "/payments", {"to_handle": f"u{(i + 1) % 3}", "amount": 5}, t, f"w{i}")
    elif kind == 3:
        s = call("GET", "/statement?limit=1", token=t)
        r = call("GET", f"/statement?snapshot={s[1]['snapshot']}&limit=50&offset=10", token=t)
    else:
        r = call("POST", "/payments/p%d/corrections" % (i * 3 % 5000), {"expected_revision": 1, "amount": 2,
                 "effective_at": (now - timedelta(seconds=1)).isoformat(), "reason": "perf"}, tok[(i * 3 % 5000) % 3], f"c{i}")
    with lock:
        results.append((kind, r[0], r[2]))


threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
begin = time.time()
[t.start() for t in threads]
[t.join() for t in threads]
print(f"50 mixed requests in {time.time() - begin:.2f}s; slowest {max(r[2] for r in results):.2f}s; statuses {sorted({(k, s) for k, s, _ in results})}")
assert max(r[2] for r in results) < 5 and all(s < 500 for _, s, _ in results)
total = 0
for i in range(3):
    total += call("GET", "/me", token=tok[i])[1]["balance"]
print("sum of balances", total, "expected", 3 * 10 ** 7)
assert total == 3 * 10 ** 7
print("OK")
