"""HTTP plumbing: parse a request, dispatch it, write the JSON response."""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit

from .errors import ApiError
from .request import Request
from .router import dispatch

# Documented limits: request line and each header line 64 KiB and at most 100
# headers (http.server), body 64 MiB. Each excess is answered with a JSON error.
MAX_BODY = 64 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _read_body(self):
        try:
            if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
                return self._read_chunked()
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "malformed_request", "bad Content-Length or chunk framing")
        if length > MAX_BODY:
            raise ApiError(422, "validation_failed", "body too large")
        return self.rfile.read(length) if length > 0 else b""

    def _read_chunked(self):
        chunks, total = [], 0
        while True:
            size = int(self.rfile.readline(65537).split(b";")[0].strip() or b"0", 16)
            total += size
            if total > MAX_BODY:
                raise ApiError(422, "validation_failed", "body too large")
            if size == 0:
                while self.rfile.readline(65537).strip():
                    pass
                return b"".join(chunks)
            chunks.append(self.rfile.read(size))
            self.rfile.readline(65537)

    def send_error(self, code, message=None, explain=None):
        """Protocol-level refusals (oversized line/header) still use the §5 body."""
        if code in (413, 414, 431):      # oversized body, URL or header: out of range
            status, name = 422, "validation_failed"
        elif code in (405, 501):         # a method this service does not serve
            status, name = 405, "method_not_allowed"
        else:                            # bad request line, HTTP version, ...
            status, name = (code if 400 <= code < 500 else 400), "malformed_request"
        self.close_connection = True
        self._send(status, {"error": {"code": name, "message": message or "bad request"}})

    def _send(self, status, payload):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        if body:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _handle(self):
        try:
            try:
                raw = self._read_body()
                parts = urlsplit(self.path)
                query = {}
                for name, value in parse_qsl(parts.query, keep_blank_values=True):
                    query.setdefault(name, value)
                req = Request(self.command, unquote(parts.path), query, self.headers, raw)
                status, payload = dispatch(req)
            except ApiError as err:
                status, payload = err.status, {"error": {"code": err.code, "message": err.message}}
            except RecursionError:
                status, payload = 400, {"error": {"code": "malformed_request",
                                                  "message": "unreadable request"}}
            except Exception as err:  # never leak a traceback; log and answer 500
                print(f"internal error: {err!r}", file=sys.stderr, flush=True)
                status, payload = 500, {"error": {"code": "internal_error",
                                                  "message": "internal error"}}
            self._send(status, payload)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _handle


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256
    allow_reuse_address = True


def make_server(port, host="0.0.0.0"):
    return Server((host, port), Handler)


def main():
    port = int(os.environ.get("PORT") or 8080)
    make_server(port).serve_forever()
