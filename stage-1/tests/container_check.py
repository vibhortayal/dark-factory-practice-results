"""Black-box checks against a running container: reset/login timing at 200 users, 50-way bursts,
conservation under load, cross-container export/import. Usage: container_check.py PORT_A PORT_B"""
import concurrent.futures as cf
import json
import sys
import time
import urllib.error
import urllib.request


def call(port, method, path, body=None, token=None, key=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode())
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if key:
        req.add_header("Idempotency-Key", key)
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    return status, (json.loads(raw) if raw else None), time.time() - t


def main(a, b):
    n = 200
    fx = {"currency": "EUR", "minor_units": 2, "settlement_operator_ids": ["u0"],
          "users": [{"id": f"u{i}", "email": f"user{i}@x.com", "password": "correct horse",
                     "display_name": f"U{i}", "handle": f"user{i}", "balance": 100000} for i in range(n)]}
    fx["users"][0]["handle"] = "op"
    t = time.time()
    assert call(a, "POST", "/_test/reset", fx)[0] == 204
    print(f"reset {n} users: {time.time() - t:.2f}s")
    with cf.ThreadPoolExecutor(50) as ex:
        res = list(ex.map(lambda i: call(a, "POST", "/auth/login", {"email": f"user{i}@x.com", "password": "correct horse"}), range(50)))
    assert all(r[0] == 200 for r in res)
    print(f"50 concurrent logins max {max(r[2] for r in res):.2f}s")
    toks = [call(a, "POST", "/auth/login", {"email": f"user{i}@x.com", "password": "correct horse"})[1]["token"] for i in range(n)]
    handles = ["op"] + [f"user{i}" for i in range(1, n)]
    statuses, lat = [], []

    def burst(i):
        u, v = i % n, (i * 7 + 1) % n
        if u == v:
            v = (v + 1) % n
        r = call(a, "POST", "/payments", {"to_handle": handles[v], "amount": 1 + i % 50}, toks[u], f"b{i}")
        r2 = call(a, "GET", "/activity?limit=200", None, toks[u])
        r3 = call(a, "POST", "/splits", {"amount": 100, "participant_handles": [handles[u], handles[v]]}, toks[u], f"s{i}")
        return [r, r2, r3]
    with cf.ThreadPoolExecutor(50) as ex:
        for rs in ex.map(burst, range(1500)):
            for s, _, d in rs:
                statuses.append(s), lat.append(d)
    assert all(s < 500 for s in statuses), set(statuses)
    print(f"1500x3 mixed ops at 50 concurrency: max latency {max(lat):.2f}s, statuses {sorted(set(statuses))}")
    with cf.ThreadPoolExecutor(50) as ex:
        total = sum(ex.map(lambda i: call(a, "GET", "/me", None, toks[i])[1]["balance"], range(n)))
    assert total == n * 100000, total
    print("conservation ok", total)
    t = time.time()
    s, export, _ = call(a, "GET", "/_test/export")
    print(f"export {time.time() - t:.2f}s, {len(json.dumps(export)) // 1024} KiB")
    t = time.time()
    assert call(b, "POST", "/_test/import", export)[0] == 204
    print(f"import into container B {time.time() - t:.2f}s")
    for i in (0, 5, 100):
        assert call(a, "GET", "/me", None, toks[i])[1] == call(b, "GET", "/me", None, toks[i])[1]
        assert call(a, "GET", "/activity?limit=200", None, toks[i])[1] == call(b, "GET", "/activity?limit=200", None, toks[i])[1]
    s, body, _ = call(b, "POST", "/payments", {"to_handle": "user1", "amount": 1 + 0 % 50}, toks[0], "b0")
    assert s == 200 or s == 409, (s, body)
    print("cross-container import ok")


main(int(sys.argv[1]), int(sys.argv[2]))
