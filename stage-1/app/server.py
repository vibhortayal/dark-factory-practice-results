"""HTTP layer: routing, authentication, idempotency preconditions, JSON I/O."""
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit

from .service import Service
from .validation import ApiError, malformed, parse_json, parse_object, invalid

MAX_BODY = 64 * 1024 * 1024
REQUEST_ACTION = re.compile(r"^/requests/([^/]+)/(pay|decline|cancel)$")
PATHS = {"/health": ("GET",), "/_test/reset": ("POST",), "/_test/export": ("GET",),
         "/_test/import": ("POST",), "/auth/signup": ("POST",), "/auth/login": ("POST",),
         "/me": ("GET",), "/payments": ("POST",), "/requests": ("GET", "POST"),
         "/splits": ("POST",), "/activity": ("GET",), "/settlements": ("POST",)}

sys.setrecursionlimit(12000)  # deep-but-valid JSON must parse, not 5xx
threading.stack_size(64 * 1024 * 1024)
svc = Service()


def dumps(obj):
    try:
        return json.dumps(obj, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        return json.dumps(obj, ensure_ascii=True).encode("ascii")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 120

    def log_message(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.respond(code, {"error": {"code": "malformed_request" if code < 500 else "internal_error",
                                      "message": message or "bad request"}})
        self.close_connection = True

    # -- plumbing -----------------------------------------------------------

    def read_body(self):
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            chunks, total = [], 0
            while True:
                size = int((self.rfile.readline(1024).split(b";")[0].strip() or b"0"), 16)
                if size == 0:
                    while self.rfile.readline(1024).strip():
                        pass
                    break
                total += size
                if total > MAX_BODY:
                    raise ApiError(413, "malformed_request", "body too large")
                chunks.append(self.rfile.read(size))
                self.rfile.readline(8)
            return b"".join(chunks)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise malformed("bad Content-Length")
        if length < 0:
            raise malformed("bad Content-Length")
        if length > MAX_BODY:
            raise ApiError(413, "malformed_request", "body too large")
        return self.rfile.read(length) if length else b""

    def respond(self, status, body=None, raw=None):
        payload = b"" if status == 204 else (raw if raw is not None else dumps(body))
        try:
            self.send_response(status)
            if status != 204:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD" and payload:
                self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def handle_any(self):
        try:
            try:
                self.raw = self.read_body()
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
            svc.reset(parse_json(self.raw))
            return 204, None, None
        if path == "/_test/export":
            return 200, None, svc.export()
        if path == "/_test/import":
            svc.import_(parse_json(self.raw))
            return 204, None, None
        if path == "/auth/signup":
            return 201, svc.signup(parse_object(self.raw)), None
        if path == "/auth/login":
            return 200, svc.login(parse_object(self.raw)), None

        uid = self.authenticate()
        if path == "/me":
            return 200, svc.me(uid), None
        if path == "/activity":
            return 200, svc.list_activity(uid, self.query), None
        if path == "/requests" and method == "GET":
            return 200, svc.list_requests(uid, self.query), None
        if path == "/payments":
            return self.idempotent(uid, path, svc.create_payment)
        if path == "/requests":
            return self.idempotent(uid, path, svc.create_request)
        if path == "/splits":
            return self.idempotent(uid, path, svc.create_split)
        if path == "/settlements":
            if not svc.is_operator(uid):
                raise ApiError(403, "forbidden", "settlement operators only")
            return self.idempotent(uid, path, svc.create_settlement)
        rid, action = m.group(1), m.group(2)
        if action == "pay":
            return self.idempotent(uid, path, lambda u, b: svc.pay_request(u, rid, b),
                                   empty_ok=True)
        if action == "decline":
            return 200, svc.decline_request(uid, rid), None
        return 200, svc.cancel_request(uid, rid), None

    def authenticate(self):
        header = self.headers.get("Authorization") or ""
        scheme, _, token = header.partition(" ")
        uid = svc.user_for_token(token.strip()) if scheme.lower() == "bearer" and token.strip() else None
        if uid is None:
            raise ApiError(401, "unauthenticated", "missing or invalid bearer token")
        return uid

    def idempotent(self, uid, path, operation, empty_ok=False):
        key = self.headers.get("Idempotency-Key")
        if key is None or key.strip() == "":
            raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header required")
        try:  # the header arrives latin-1 decoded; count characters, not bytes
            key = key.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        if len(key) > 255:
            raise invalid("Idempotency-Key longer than 255 characters")
        body = {} if (empty_ok and not self.raw.strip()) else parse_object(self.raw)
        status, response = svc.idempotent(uid, "POST", path, key, body,
                                          lambda: operation(uid, body))
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
