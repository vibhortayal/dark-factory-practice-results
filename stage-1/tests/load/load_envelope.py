"""Measure the operating envelope against a running service (see RUN.md).

    python3 tests/load/load_envelope.py http://127.0.0.1:8080 [container-name]

With a container name (the container must be started with --cpus 2 --memory 2g
--memory-swap 2g) peak memory is read from its cgroup. Prints one line per measurement.
"""
import http.client
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

URL = urlsplit(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080")
CONTAINER = sys.argv[2] if len(sys.argv) > 2 else None


def call(method, path, body=None, token=None, key=None, raw=None, timeout=120):
    conn = http.client.HTTPConnection(URL.hostname, URL.port, timeout=timeout)
    h = {}
    if token:
        h["Authorization"] = "Bearer " + token
    if key:
        h["Idempotency-Key"] = key
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    t0 = time.time()
    try:
        conn.request(method, path, data, h)
        r = conn.getresponse()
        out = r.read()
        return r.status, time.time() - t0, out
    except Exception as e:  # dropped connection etc.
        return "ERR:" + type(e).__name__, time.time() - t0, b""
    finally:
        conn.close()


def peak_mib():
    if not CONTAINER:
        return "n/a"
    out = subprocess.check_output(["docker", "exec", CONTAINER, "cat", "/sys/fs/cgroup/memory.peak"])
    return int(out) // 2 ** 20


def user(i, password="correct horse", balance=10 ** 9):
    return {"id": "u%d" % i, "email": "e%d@x.io" % i, "password": password, "display_name": "U%d" % i,
            "handle": "h%d" % i, "balance": balance}


def reset(users, **extra):
    t0 = time.time()
    status, took, out = call("POST", "/_test/reset", dict({"users": users}, **extra))
    return status, took


def login(i, password="correct horse"):
    return json.loads(call("POST", "/auth/login", {"email": "e%d@x.io" % i, "password": password})[2])["token"]


def report(name, rs, extra=""):
    codes = {}
    for s, _, _ in rs:
        codes[str(s)] = codes.get(str(s), 0) + 1
    print("%-52s statuses %s slowest %.2fs %s peak MiB %s" % (name, codes, max(t for _, t, _ in rs), extra, peak_mib()),
          flush=True)


def burst(n, fn):
    with ThreadPoolExecutor(n) as ex:
        return list(ex.map(fn, range(n)))


def polled(fn, n):
    """Run n concurrent calls while polling GET /me; returns (results, worst /me latency)."""
    stop, worst = [], [0.0]
    tok = login(0)

    def poll():
        while not stop:
            worst[0] = max(worst[0], call("GET", "/me", token=tok)[1])
            time.sleep(0.01)
    th = threading.Thread(target=poll)
    th.start()
    rs = burst(n, fn)
    stop.append(1)
    th.join()
    return rs, worst[0]


def shapes():
    base = b'{"to_handle":"h1","amount":1,"x":'
    cap = 128 * 1024
    n = cap - len(base) - 17
    return {"one number of ~128K digits": base + b"9" * n + b"}",
            "16k small ints": base + b"[" + b"1," * 16000 + b"1]}",
            "16k floats": base + b"[" + b"1.5," * 16000 + b"1.5]}",
            "16k exponent floats": base + b"[" + b"1.25e3," * 16000 + b"1.25e3]}",
            "8k empty arrays": base + b"[" + b"[]," * 8000 + b"[]]}",
            "8k small objects": base + b"[" + b'{"a":1},' * 8000 + b'{"a":1}]}',
            "nesting depth 9000": base + b"[" * 9000 + b"]" * 9000 + b"}",
            "128 KiB string": base + b'"' + b"z" * (n - 2) + b'"}'}


def main():
    print("== E1: 50 concurrent worst-shape API bodies at the cap")
    print("reset", reset([user(0), user(1, balance=0)]))
    tok = login(0)
    for name, raw in shapes().items():
        rs, worst = polled(lambda i: call("POST", "/payments", raw=raw, token=tok, key="%s-%d" % (name, i)), 50)
        report("50 x " + name, rs, "GET /me max %.2fs" % worst)
    for name, raw in (("too many values (17k)", b'{"x":[' + b"1," * 17000 + b"1]}"),
                      ("over 128 KiB", b'{"x":"' + b"z" * (129 * 1024) + b'"}')):
        rs = burst(50, lambda i: call("POST", "/payments", raw=raw, token=tok, key="rej-%d" % i))
        report("50 x rejected: " + name, rs)

    print("== E5: password hashing")
    for n_users in (3000, 20000):
        print("reset %d users, one password: %s" % (n_users, reset([user(i) for i in range(n_users)])))
    print("reset 500 users, 500 distinct passwords: %s" % (reset([user(i, "pw-%d" % i) for i in range(500)]),))
    t0 = time.time()
    call("POST", "/auth/login", {"email": "e1@x.io", "password": "pw-1"})
    print("single login %.3fs" % (time.time() - t0))
    rs = burst(50, lambda i: call("POST", "/auth/login", {"email": "e%d@x.io" % i, "password": "pw-%d" % i}))
    report("50 concurrent logins", rs)
    rs = burst(50, lambda i: call("POST", "/auth/signup", {"email": "s%d@x.io" % i, "password": "12345678",
                                                           "display_name": "S"}))
    report("50 concurrent signups", rs)

    print("== E6/E2: maximum-size splits on a fresh 3000-user state")
    print("reset", reset([user(i) for i in range(3000)]))
    tok = login(0)
    handles = ["h%d" % i for i in range(3000)]
    note = "n" * 200
    rs, worst = polled(lambda i: call("POST", "/splits", {"amount": 10 ** 6, "participant_handles": handles,
                                                          "note": note}, token=tok, key="big-split-%d" % i), 50)
    report("50 x split with 3000 participants", rs, "GET /me max %.2fs" % worst)

    print("== E2: fill the state to the 40 MiB budget")
    users = [user(i) for i in range(20)]
    print("reset", reset(users, settlement_operator_ids=["u0"]))
    toks = [login(i) for i in range(20)]
    note = "x" * 200
    stop = []
    count = [0]
    lock = threading.Lock()

    def filler(w):
        i = 0
        while not stop:
            i += 1
            s, _, _ = call("POST", "/payments", {"to_handle": "h%d" % ((w + 1) % 20), "amount": 1, "note": note},
                           token=toks[w], key="fill-%d-%d" % (w, i))
            if s == 429:
                stop.append(1)
                return
            if s != 201:
                print("unexpected", s)
                stop.append(1)
                return
            with lock:
                count[0] += 1
    t0 = time.time()
    ts = [threading.Thread(target=filler, args=(w,)) for w in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    print("filled with %d payments in %.0fs until 429 capacity_exceeded" % (count[0], time.time() - t0), flush=True)
    s, took, exp = call("GET", "/_test/export")
    print("export: status %s %.2fs size %.1f MiB (budget 40 MiB, allowed <= 48 MiB) peak MiB %s" % (
        s, took, len(exp) / 2 ** 20, peak_mib()), flush=True)
    assert len(exp) <= 48 * 2 ** 20

    print("== E3: exports and imports at the budget")
    rs = burst(10, lambda i: call("GET", "/_test/export"))
    report("10 concurrent exports", rs, "all identical: %s" % (len({r[2] for r in rs}) == 1))
    s, took, _ = call("POST", "/_test/import", raw=exp)
    s2, took2, exp2 = call("GET", "/_test/export")
    print("import %s %.2fs; re-export identical: %s (%.2fs)" % (s, took, exp2 == exp, took2), flush=True)
    rs = burst(4, lambda i: call("POST", "/_test/import", raw=exp))
    report("4 concurrent imports of the full export", rs)

    print("== E6: reads at the full budget")
    tok = login(0)
    for path in ("/activity", "/activity?offset=0&limit=200", "/activity?offset=30000&limit=50",
                 "/requests", "/requests?offset=30000"):
        rs = burst(50, lambda i: call("GET", path, token=tok))
        report("50 x GET " + path, rs)
    rs = burst(50, lambda i: call("POST", "/splits", {"amount": 10, "participant_handles": ["h0", "h1", "h2"]},
                                  token=tok, key="full-split-%d" % i))
    report("50 x split at capacity", rs)
    ops = [{"from_handle": "h0", "to_handle": "h%d" % (1 + j % 19), "amount": 1} for j in range(32)]
    rs = burst(50, lambda i: call("POST", "/settlements", {"transfers": ops}, token=tok, key="full-st-%d" % i))
    report("50 x 32-entry settlement at capacity (not operator: 403)", rs)


main()
