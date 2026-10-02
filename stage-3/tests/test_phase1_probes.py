"""Raw-socket probes of request decoding: every one must get a proper HTTP/1.1
response with the JSON error body (or a 2xx), never a 5xx and never a bare drop."""
import json
import socket

from .helpers import World, server_port


def exchange(data, half_close=True):
    with socket.create_connection(("127.0.0.1", server_port()), timeout=10) as s:
        s.sendall(data)
        if half_close:
            s.shutdown(socket.SHUT_WR)
        reply = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            reply += chunk
    head, _, body = reply.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    assert lines[0].startswith(b"HTTP/1.1 "), reply[:200]
    headers = {l.split(b":", 1)[0].decode().lower(): l.split(b":", 1)[1].strip().decode()
               for l in lines[1:] if b":" in l}
    return int(lines[0].split()[1]), headers, body


def req(line, headers=(), body=b""):
    hs = b"".join(h + b"\r\n" for h in headers)
    return line + b" HTTP/1.1\r\nHost: x\r\nConnection: close\r\n" + hs + b"\r\n" + body


class Phase1Tests(World):
    def ok_or_json_error(self, data):
        status, headers, body = exchange(data)
        self.assertLess(status, 500, (data[:80], body[:200]))
        if status >= 400:
            self.assertEqual(headers.get("content-type"), "application/json; charset=utf-8", data[:80])
            self.assertIn("error", json.loads(body))
        return status

    def test_targets(self):
        auth = [b"Authorization: Bearer " + self.tok["ada"].encode()]
        for target in (b"http://[bad/health", b"http://[::1/me", b"http://[/", b"ftp://x/health",
                       b"*", b"x.example:443", b"me", b"//me", b"/me?%zz=%", b"/me?%ff%fe=1",
                       b"/%zz", b"/%", b"/%ff%fe", b"/me%00", b"/\xc3\xa9\xff", b"/me?q=\x00\xff",
                       b"/requests//pay", b"/requests/a%2Fb/pay", b"/requests/%C3%A9/pay",
                       b"/requests/" + b"a" * 70000 + b"/pay", b"/requests/" + b"%41" * 30000):
            self.ok_or_json_error(req(b"GET " + target, auth))
            self.ok_or_json_error(req(b"POST " + target, auth, b""))
        self.assertEqual(self.ok_or_json_error(req(b"GET http://ok.example/health")), 200)
        self.assertEqual(self.ok_or_json_error(req(b"GET http://ok.example/me", auth)), 200)

    def test_header_values(self):
        body = b'{"to_handle":"bob","amount":1}'
        tok = self.tok["ada"].encode()
        cases = [[b"Idempotency-Key: caf\xe9", b"Authorization: Bearer " + tok],
                 [b"Idempotency-Key: a\x00b", b"Authorization: Bearer " + tok],
                 [b"Idempotency-Key: k1", b"Idempotency-Key: k2", b"Authorization: Bearer " + tok],
                 [b"Idempotency-Key: k", b"Authorization: Bearer " + tok, b"Authorization: Bearer x"],
                 [b"Idempotency-Key: k", b"Authorization: Bearer \xff\xfe"]]
        for hs in cases:
            self.ok_or_json_error(req(b"POST /payments", hs + [b"Content-Length: %d" % len(body)], body))
        for cl in (b"-1", b"-99999999999999999999", b"99999999999999999999999", b"abc", b"", b"1e3", b"+5",
                   b"5, 6", b"\xff"):
            self.ok_or_json_error(req(b"POST /payments", [b"Authorization: Bearer " + tok,
                                                           b"Idempotency-Key: k", b"Content-Length: " + cl], body))
        # Content-Length larger / smaller than the body actually sent; duplicates
        for cl in (len(body) + 50, len(body) - 5):
            self.ok_or_json_error(req(b"POST /payments", [b"Authorization: Bearer " + tok,
                                                           b"Idempotency-Key: kz", b"Content-Length: %d" % cl], body))
        self.ok_or_json_error(req(b"POST /payments", [b"Authorization: Bearer " + tok, b"Idempotency-Key: kd",
                                                       b"Content-Length: 5", b"Content-Length: %d" % len(body)], body))

    def test_bodies(self):
        tok = b"Authorization: Bearer " + self.tok["ada"].encode()
        for i, body in enumerate((b"\xef\xbb\xbf" + b'{"to_handle":"bob","amount":1}', b"\xff\xfe\x00",
                                  b'{"to_handle":"b\xffob","amount":1}', b"\x00", b'{"a":"\xed\xa0\x80"}')):
            status = self.ok_or_json_error(req(b"POST /payments", [tok, b"Idempotency-Key: b%d" % i,
                                                                   b"Content-Length: %d" % len(body)], body))
            self.assertIn(status, (400, 404, 422), body)
        self.assertEqual(self.balance("ada"), 10000)

    def test_chunked(self):
        tok = b"Authorization: Bearer " + self.tok["ada"].encode()
        te = [tok, b"Idempotency-Key: ch1", b"Transfer-Encoding: chunked"]
        good = b'1e\r\n{"to_handle":"bob","amount":1}\r\n0\r\n\r\n'
        self.assertEqual(self.ok_or_json_error(req(b"POST /payments", te, good)), 201)
        for bad in (b"zz\r\nabc\r\n0\r\n\r\n", b"-5\r\nabc\r\n", b"ffffffffffffffff\r\nabc", b"5\r\nab",
                    b"\r\n", b"3\r\nabc\r\n", b"0x5\r\nhello\r\n0\r\n\r\n"):
            self.ok_or_json_error(req(b"POST /payments", te, bad))

    def test_bad_request_lines_get_http11_status_line(self):
        for line in (b"GET /me HTTP/9.9\r\nHost: x\r\n\r\n", b"GARBAGE\r\n\r\n", b"GET /me\r\n\r\n",
                     b"GET /me HTTP/2.0\r\n\r\n", b"A B C D\r\n\r\n", b"GET /me HTTP/1.1x\r\n\r\n"):
            status, headers, body = exchange(line)
            self.assertLess(status, 500, line)
            if status >= 400:
                self.assertEqual(headers.get("content-type"), "application/json; charset=utf-8", line)
                self.assertIn("error", json.loads(body))
        status, _, body = exchange(b"GET /me HTTP/9.9\r\n\r\n")
        self.assertEqual((status, json.loads(body)["error"]["code"]), (400, "malformed_request"))

    def test_unsupported_methods(self):
        for method in (b"PROPFIND", b"TRACE", b"CONNECT", b"BREW"):
            status, headers, body = exchange(req(method + b" /me"))
            self.assertLess(status, 500)
            self.assertEqual(headers.get("content-type"), "application/json; charset=utf-8")
        status, headers, body = exchange(req(b"HEAD /health"))
        self.assertEqual((status, body), (405, b""))  # HTTP forbids a body on HEAD
