"""HTTP layer: routing, authentication, idempotency preconditions, JSON I/O."""
import hashlib
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit

from .service import Service
from .validation import ApiError, canon, malformed, parse_json, parse_object, parse_plain, invalid

MAX_BODY = 64 * 1024 * 1024  # /_test/* fixtures and exports
MAX_API_VALUES = 16384  # commas + brackets + braces in an API body (a 1000-handle split has ~1000)
MAX_API_BODY = 128 * 1024  # every other endpoint: ample for any valid request (a 1000-handle split is ~10 KB)
REQUEST_ACTION = re.compile(r"^/requests/([^/]+)/(pay|decline|cancel)$")
PATHS = {"/health": ("GET",), "/_test/reset": ("POST",), "/_test/export": ("GET",),
         "/_test/import": ("POST",), "/auth/signup": ("POST",), "/auth/login": ("POST",),
         "/me": ("GET",), "/payments": ("POST",), "/requests": ("GET", "POST"),
         "/splits": ("POST",), "/activity": ("GET",), "/settlements": ("POST",)}

sys.setswitchinterval(0.0005)  # keep small requests responsive next to large parses
sys.setrecursionlimit(12000)  # deep-but-valid JSON must parse, not 5xx
threading.stack_size(64 * 1024 * 1024)
LARGE_BODY = 16 * 1024  # bodies above this are parsed under a concurrency limit
MAX_JSON_VALUES = 3_000_000  # cheap upper bound on values in a reset/import document
large_api_bodies = threading.BoundedSemaphore(2)
large_test_bodies = threading.BoundedSemaphore(1)
svc = Service()


def parse_limited(raw, semaphore, parse):
    """Parse a body with at most N large bodies in flight, so memory stays bounded."""
    if len(raw) <= LARGE_BODY:
        return parse(raw)
    if len(raw) > 1024 * 1024:  # C-speed pre-scan: bound the size of the parsed tree
        if raw.count(b",") + raw.count(b"[") + raw.count(b"{") > MAX_JSON_VALUES:
            raise invalid("document has too many values")
    with semaphore:
        return parse(raw)


def dumps(obj):
    try:
        return json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except UnicodeEncodeError:
        return json.dumps(obj, ensure_ascii=True, allow_nan=False).encode("ascii")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 120
    disable_nagle_algorithm = True  # TCP_NODELAY on accepted sockets

    def log_message(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.respond(code, {"error": {"code": "malformed_request" if code < 500 else "internal_error",
                                      "message": message or "bad request"}})
        self.close_connection = True

    # -- plumbing -----------------------------------------------------------

    def too_large(self):
        self.close_connection = True  # the unread body would corrupt the next request
        return ApiError(413, "payload_too_large", "request body too large")

    def check_api_values(self):
        """Cheap C-speed bound on the number of JSON values in an API body, before parsing."""
        raw = self.raw
        if not self.path.startswith("/_test/") and len(raw) > 4096 and \
                raw.count(b",") + raw.count(b"[") + raw.count(b"{") > MAX_API_VALUES:
            raise ApiError(413, "payload_too_large", "request body has too many values")

    def read_body(self):
        limit = MAX_BODY if self.path.startswith("/_test/") else MAX_API_BODY
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            chunks, total = [], 0
            while True:
                size = int((self.rfile.readline(1024).split(b";")[0].strip() or b"0"), 16)
                if size == 0:
                    while self.rfile.readline(1024).strip():
                        pass
                    break
                total += size
                if total > limit:
                    raise self.too_large()
                chunks.append(self.rfile.read(size))
                self.rfile.readline(8)
            return b"".join(chunks)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise malformed("bad Content-Length")
        if length < 0:
            raise malformed("bad Content-Length")
        if length > limit:
            if length > MAX_BODY:
                raise self.too_large()
            remaining = length  # drain so the client can read the 413 on a healthy connection
            while remaining:
                chunk = self.rfile.read(min(remaining, 1 << 20))
                if not chunk:
                    break
                remaining -= len(chunk)
            raise ApiError(413, "payload_too_large", "request body too large")
        return self.rfile.read(length) if length else b""

    def respond(self, status, body=None, raw=None):
        payload = b"" if status == 204 else (raw if raw is not None else dumps(body))
        try:
            self.send_response(status)
            if status != 204:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self._headers_buffer.append(b"\r\n")  # what end_headers() does, minus its own write
            head = b"".join(self._headers_buffer)
            self._headers_buffer = []
            body = payload if self.command != "HEAD" else b""
            if len(body) <= 256 * 1024:  # one write: no Nagle/delayed-ACK stall on keep-alive
                self.wfile.write(head + body)
            else:
                self.wfile.write(head)
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def handle_any(self):
        try:
            try:
                self.raw = self.read_body()
                self.check_api_values()
                status, body, raw = self.route()
            except ApiError as e:
                status, body, raw = e.status, {"error": {"code": e.code, "message": e.message}}, None
            except (ValueError, OSError, RecursionError):
                status, body, raw = 400, {"error": {"code": "malformed_request",
                                                    "message": "bad request"}}, None
            except Exception as e:  # never leak a stack trace or break the connection
                sys.stderr.write("internal error: %r\n" % (e,))
                status, body, raw = 500, {"error": {"code": "internal_error",
                                                    "message": "internal error"}}, None
            self.respond(status, body, raw)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = handle_any

    # -- routing --------------------------------------------------------------

    def route(self):
        parts = urlsplit(self.path)
        path = unquote(parts.path)
        self.query = dict(reversed(parse_qsl(parts.query, keep_blank_values=True)))
        method = self.command
        m = REQUEST_ACTION.match(path)
        if m:
            allowed = ("POST",)
        elif path in PATHS:
            allowed = PATHS[path]
        else:
            raise ApiError(404, "not_found", "no such route")
        if method == "HEAD" and "GET" in allowed:
            method = "GET"
        if method not in allowed:
            raise ApiError(405, "method_not_allowed", "method not allowed")

        if path == "/health":
            return 200, {"status": "ok"}, None
        if path == "/_test/reset":
            return self.test_load(svc.reset, parse_json)
        if path == "/_test/export":
            return 200, None, svc.export()
        if path == "/_test/import":
            return self.test_load(svc.import_, parse_plain)
        if path == "/auth/signup":
            return 201, svc.signup(parse_object(self.raw)), None
        if path == "/auth/login":
            return 200, svc.login(parse_object(self.raw)), None

        token = self.bearer_token()
        if path in ("/payments", "/splits", "/settlements") or m and m.group(2) == "pay" \
                or (path == "/requests" and method == "POST"):
            return self.idempotent_route(path, m, token)
        with svc.lock:  # authenticate and act in one state generation
            return self.read_or_close(path, method, m, svc.resolve(token))

    def read_or_close(self, path, method, m, uid):
        if path == "/me":
            return 200, svc.me(uid), None
        if path == "/activity":
            return 200, svc.list_activity(uid, self.query), None
        if path == "/requests":
            return 200, svc.list_requests(uid, self.query), None
        rid, action = m.group(1), m.group(2)
        if action == "decline":
            return 200, svc.decline_request(uid, rid), None
        return 200, svc.cancel_request(uid, rid), None

    def test_load(self, load, parse):
        """POST /_test/reset and /_test/import: parse + validate + build, one large document at a
        time (bounds peak memory), nothing held under the state lock until the final swap."""
        raw = self.raw
        if len(raw) > 1024 * 1024 and \
                raw.count(b",") + raw.count(b"[") + raw.count(b"{") > MAX_JSON_VALUES:
            raise invalid("document has too many values")
        if len(raw) > LARGE_BODY:
            with large_test_bodies:
                load(parse(raw))
        else:
            load(parse(raw))
        return 204, None, None

    def bearer_token(self):
        header = self.headers.get("Authorization") or ""
        scheme, _, token = header.partition(" ")
        return token.strip() if scheme.lower() == "bearer" else None

    def idempotent_route(self, path, m, token):
        """The five idempotent write paths (§7).

        Order: 401 -> operator 403 -> key present -> key length -> body is an object
        -> claimed key (200/409) -> field validation. Body parsing and canonicalising
        happen OUTSIDE the state lock; the token is resolved again inside the lock
        that applies the operation, so a reset/import in between cannot be raced.
        """
        with svc.lock:
            uid = svc.resolve(token)
            if path == "/settlements" and not svc.is_operator(uid):
                raise ApiError(403, "forbidden", "settlement operators only")
        key = self.headers.get("Idempotency-Key")
        if key is None or key.strip() == "":
            raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header required")
        try:  # the header arrives latin-1 decoded; count characters, not bytes
            key = key.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        if len(key) > 255:
            raise invalid("Idempotency-Key longer than 255 characters")
        pay = m is not None
        def parse_and_digest(raw):
            body = {} if (pay and not raw.strip()) else parse_object(raw)
            # only a digest of the canonical body is kept with the idempotency record
            return body, hashlib.sha256(canon(body).encode("utf-8")).hexdigest()
        body, sig = parse_limited(self.raw, large_api_bodies, parse_and_digest)
        if pay:
            rid = m.group(1)
            operation = lambda u: svc.pay_request(u, rid, body)
        else:
            operation = lambda u: {"/payments": svc.create_payment, "/requests": svc.create_request,
                                   "/splits": svc.create_split,
                                   "/settlements": svc.create_settlement}[path](u, body)
        with svc.lock:
            uid = svc.resolve(token)
            if path == "/settlements" and not svc.is_operator(uid):
                raise ApiError(403, "forbidden", "settlement operators only")
            status, response = svc.idempotent(uid, "POST", path, key, sig, lambda: operation(uid))
        return status, response, None


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 512
    allow_reuse_address = True


def main():
    port = int(os.environ.get("PORT") or 8080)
    Server(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
