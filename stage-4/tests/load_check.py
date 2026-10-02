"""Black-box load/limits check against a running container.

    python3 tests/load_check.py http://127.0.0.1:8080 [second-base-url]

Resets with 400 users, then runs 50-way bursts of logins, signups, payments and
pays, timing each request (limit 5 s; reset/export/import 10 s), and checks the
balance sum. With a second URL it also exports here and imports there.
"""
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = sys.argv[1].rstrip("/")


def call(base, method, path, body=None, token=None, key=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if key:
        req.add_header("Idempotency-Key", key)
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    return status, (json.loads(raw) if raw else None), time.time() - start


def burst(fn, n=50):
    with ThreadPoolExecutor(n) as pool:
        out = list(pool.map(fn, range(n)))
    return out


users = [{"id": f"u{i}", "email": f"u{i}@x.io", "password": "correct horse", "display_name": f"U{i}",
          "handle": f"u{i}", "balance": 1000} for i in range(400)]
status, _, took = call(BASE, "POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": users})
print(f"reset 400 users: {status} in {took:.2f}s")
assert status == 204 and took < 10

logins = burst(lambda i: call(BASE, "POST", "/auth/login", {"email": f"u{i}@x.io", "password": "correct horse"}))
print("50 logins:", {s for s, _, _ in logins}, f"max {max(t for *_, t in logins):.2f}s")
assert all(s == 200 for s, _, _ in logins) and max(t for *_, t in logins) < 5
tokens = [b["token"] for _, b, _ in logins]

signups = burst(lambda i: call(BASE, "POST", "/auth/signup",
                               {"email": f"new{i}@y.io", "password": "longenough", "display_name": "N"}))
print("50 signups:", {s for s, _, _ in signups}, f"max {max(t for *_, t in signups):.2f}s")
assert all(s == 201 for s, _, _ in signups) and max(t for *_, t in signups) < 5

pays = burst(lambda i: call(BASE, "POST", "/payments", {"to_handle": "u399", "amount": 1000},
                            token=tokens[i], key=f"k{i}"))
print("50 payments:", sorted({s for s, _, _ in pays}), f"max {max(t for *_, t in pays):.2f}s")
race = burst(lambda i: call(BASE, "POST", "/payments", {"to_handle": "u399", "amount": 600},
                            token=tokens[0], key=f"r{i}"))
print("overdraft race statuses:", sorted(s for s, _, _ in race))
assert sum(s == 201 for s, _, _ in race) == 0 and all(s == 409 for s, _, _ in race)

total = 0
for i in range(400):
    _, b, _ = call(BASE, "POST", "/auth/login", {"email": f"u{i}@x.io", "password": "correct horse"})
    total += call(BASE, "GET", "/me", token=b["token"])[1]["balance"]
print("balance sum", total, "expected", 400 * 1000)
assert total == 400 * 1000

status, exported, took = call(BASE, "GET", "/_test/export")
print(f"export: {status} in {took:.2f}s")
assert status == 200 and took < 10
if len(sys.argv) > 2:
    other = sys.argv[2].rstrip("/")
    status, _, took = call(other, "POST", "/_test/import", exported)
    print(f"import into second container: {status} in {took:.2f}s")
    assert status == 204
    assert call(other, "GET", "/_test/export")[1] == exported
    status, body, _ = call(other, "POST", "/payments", {"to_handle": "u399", "amount": 1000},
                           token=tokens[1], key="k1")
    print("replay after import:", status)
    assert status == 200
print("OK")
