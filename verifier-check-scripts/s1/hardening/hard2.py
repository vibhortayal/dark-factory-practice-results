"""Hardening probes, first revision only. Prints one line per probe: status and a body snippet."""
import json, os, socket, sys, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import BASE, World, call, fixture, user, k, burst, statuses
from urllib.parse import urlsplit

u = urlsplit(BASE); HOST, PORT = u.hostname, u.port

def raw(data: bytes, read=4096, timeout=5):
    s = socket.create_connection((HOST, PORT), timeout=timeout)
    try:
        s.sendall(data)
        try:
            out = s.recv(read)
        except Exception as e:
            out = f"<{type(e).__name__}>".encode()
    finally:
        s.close()
    return out.decode("latin-1")

def show(label, r):
    if isinstance(r, str):
        first = r.split("\r\n")[0]
        ct = [l for l in r.split("\r\n") if l.lower().startswith("content-type")]
        print(f"{label:58s} -> {first[:60]} | {ct[0] if ct else ''} | {r.split(chr(13)+chr(10)+chr(13)+chr(10))[-1][:70]!r}")
    else:
        print(f"{label:58s} -> {r.status_code} {r.text[:110]!r}")

w = World().login_all(); t = w.t("ada")
fx = fixture(users=[dict(user("ada", 5), handle="ada\n"), user("bob", 1)])
show("reset: handle 'ada\\n'", call("POST", "/_test/reset", body=fx))
fx = fixture(users=[dict(user("ada", 5), balance=1.0), user("bob", 1)])
show("reset: balance 0.99999999999999999999", call("POST", "/_test/reset", raw=json.dumps(fx).replace("1.0,", "0.99999999999999999999,")))
show("reset: users nested 3000 deep", call("POST", "/_test/reset", raw='{"currency":"EUR","minor_units":2,"users":' + "[" * 3000 + "]" * 3000 + "}"))
w = World().login_all(); t = w.t("ada")
show("payment: note nested 100000 deep", call("POST", "/payments", t, key=k(), raw='{"to_handle":"bob","amount":1,"note":' + "[" * 100000 + "]" * 100000 + "}"))
show("payment: unknown field nested 900 deep", call("POST", "/payments", t, key=k(), raw='{"to_handle":"bob","amount":1,"x":' + "[" * 900 + "]" * 900 + "}"))
show("  replay of the same (deep compare)", call("POST", "/payments", t, key="deep", raw='{"to_handle":"bob","amount":1,"x":' + "[" * 900 + "]" * 900 + "}"))
show("  replay of the same (deep compare) 2", call("POST", "/payments", t, key="deep", raw='{"to_handle":"bob","amount":1,"x":' + "[" * 900 + "]" * 900 + "}"))
show("export after deep body stored", call("GET", "/_test/export"))
e = call("GET", "/_test/export")
if e.status_code == 200:
    show("import of that export", call("POST", "/_test/import", raw=e.content))
show("note with NUL and lone surrogate", call("POST", "/payments", t, key=k(), raw='{"to_handle":"bob","amount":1,"note":"a\\u0000b\\ud800c"}'))
show("activity after that", call("GET", "/activity?limit=1", t))
show("signup email with lone surrogate", call("POST", "/auth/signup", raw='{"email":"x\\ud800y@example.com","password":"longenough1\\udfff","display_name":"\\ud800"}'))
show("login with that", call("POST", "/auth/login", raw='{"email":"x\\ud800y@example.com","password":"longenough1\\udfff"}'))
show("export with surrogates", call("GET", "/_test/export"))
# raw protocol-level probes
auth = f"Authorization: Bearer {t}\r\n"
show("raw: garbage request line", raw(b"GARBAGE\r\n\r\n"))
show("raw: HTTP/0.9 style 'GET /health'", raw(b"GET /health\r\n\r\n"))
show("raw: bad version HTTP/9.9", raw(b"GET /health HTTP/9.9\r\nHost: x\r\n\r\n"))
show("raw: HTTP/1.0 no Host", raw(b"GET /health HTTP/1.0\r\n\r\n"))
show("raw: lowercase method 'get'", raw(b"get /health HTTP/1.1\r\nHost: x\r\n\r\n"))
show("raw: URL 70000 bytes", raw(b"GET /health?x=" + b"a" * 70000 + b" HTTP/1.1\r\nHost: x\r\n\r\n"))
show("raw: URL 8000 bytes", raw(b"GET /health?x=" + b"a" * 8000 + b" HTTP/1.1\r\nHost: x\r\n\r\n"))
show("raw: 150 headers", raw(b"GET /health HTTP/1.1\r\nHost: x\r\n" + b"".join(b"X-H%d: 1\r\n" % i for i in range(150)) + b"\r\n"))
show("raw: one header of 70000 bytes", raw(b"GET /health HTTP/1.1\r\nHost: x\r\nX-Big: " + b"a" * 70000 + b"\r\n\r\n"))
show("raw: Content-Length: abc", raw(("POST /payments HTTP/1.1\r\nHost: x\r\n" + auth + "Idempotency-Key: a1\r\nContent-Length: abc\r\n\r\n").encode()))
show("raw: Content-Length: -5", raw(("POST /payments HTTP/1.1\r\nHost: x\r\n" + auth + "Idempotency-Key: a2\r\nContent-Length: -5\r\n\r\n").encode()))
show("raw: Content-Length: 99999999999", raw(("POST /payments HTTP/1.1\r\nHost: x\r\n" + auth + "Idempotency-Key: a3\r\nContent-Length: 99999999999\r\n\r\n").encode()))
body = b'{"to_handle":"bob","amount":1}'
show("raw: chunked valid body", raw(("POST /payments HTTP/1.1\r\nHost: x\r\n" + auth + "Idempotency-Key: c1\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n").encode() + b"%x\r\n" % len(body) + body + b"\r\n0\r\n\r\n"))
show("raw: chunk size 'zz'", raw(("POST /payments HTTP/1.1\r\nHost: x\r\n" + auth + "Idempotency-Key: c2\r\nTransfer-Encoding: chunked\r\n\r\n").encode() + b"zz\r\nabc\r\n0\r\n\r\n"))
show("raw: chunk size FFFFFFFFFFFFFFFFFFFFFFFF", raw(("POST /payments HTTP/1.1\r\nHost: x\r\n" + auth + "Idempotency-Key: c3\r\nTransfer-Encoding: chunked\r\n\r\n").encode() + b"FFFFFFFFFFFFFFFFFFFFFFFF\r\nabc\r\n0\r\n\r\n"))
show("raw: chunk size 7FFFFFFFFFFF (140 TB)", raw(("POST /payments HTTP/1.1\r\nHost: x\r\n" + auth + "Idempotency-Key: c4\r\nTransfer-Encoding: chunked\r\n\r\n").encode() + b"7FFFFFFFFFFF\r\nabc\r\n0\r\n\r\n", timeout=4))
show("raw: Expect 100-continue", raw(("POST /payments HTTP/1.1\r\nHost: x\r\n" + auth + "Idempotency-Key: e1\r\nContent-Type: application/json\r\nExpect: 100-continue\r\nContent-Length: %d\r\n\r\n" % len(body)).encode() + body))
show("raw: non-ASCII Idempotency-Key bytes", raw(("POST /payments HTTP/1.1\r\nHost: x\r\n" + auth).encode() + b"Idempotency-Key: k\xc3\xa9\xff\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n" % len(body) + body))
show("raw: non-ASCII Authorization bytes", raw(b"GET /me HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer \xff\xfe\xc3\xa9\r\n\r\n"))
show("raw: CONNECT", raw(b"CONNECT example.com:443 HTTP/1.1\r\nHost: x\r\n\r\n"))
show("health still ok", call("GET", "/health"))
