"""HTTP plumbing: decode a request (phase 1), route it (phase 2), write JSON.

Phase 1 (`_decode`) turns bytes into a `Request` and nothing else; whatever
goes wrong there, of any exception type, is a 4xx with the §5 body. Only phase 2
(the routed handler) has a catch-all for unexpected errors, and no client input
should be able to reach it.

Documented limits: request line and each header line 64 KiB, at most 100
headers (http.server), body 64 MiB, 30 s to receive a request. Each excess is
answered with a JSON error body.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit

from .errors import ApiError
from .handlers.ui import Raw
from .request import Request
from .router import dispatch

MAX_BODY = 64 * 1024 * 1024
LINE_LIMIT = 65537
BAD_REQUEST = 400
IDLE_SECONDS = 120


def _malformed(message):
    return ApiError(BAD_REQUEST, "malformed_request", message)


def _too_big():
    return ApiError(422, "validation_failed", "request is too large")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = IDLE_SECONDS  # idle keep-alive connections close after this

    def log_message(self, *args):
        pass

    # ---- phase 1: decode ----
    def _read_chunked(self):
        chunks, total = [], 0
        while True:
            size = int(self.rfile.readline(LINE_LIMIT).split(b";")[0].strip() or b"0", 16)
            if size < 0:
                raise _malformed("bad chunk size")
            total += size
            if total > MAX_BODY:
                raise _too_big()
            if size == 0:
                while self.rfile.readline(LINE_LIMIT).strip():
                    pass
                return b"".join(chunks)
            data = self.rfile.read(size)
            if len(data) != size:
                raise _malformed("truncated chunk")
            chunks.append(data)
            self.rfile.readline(LINE_LIMIT)

    def _read_body(self):
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            return self._read_chunked()
        length = int((self.headers.get("Content-Length") or "0").strip())
        if length < 0:
            raise _malformed("negative Content-Length")
        if length > MAX_BODY:
            raise _too_big()
        raw = self.rfile.read(length) if length else b""
        if len(raw) != length:
            raise _malformed("body shorter than Content-Length")
        return raw

    def _decode(self):
        target = urlsplit(self.path)  # absolute-form, "*" and odd targets all land here
        query = {}
        for name, value in parse_qsl(target.query, keep_blank_values=True):
            query.setdefault(name, value)
        raw = self._read_body()
        return Request(self.command, unquote(target.path), query, self.headers, raw)

    # ---- responses ----
    def send_error(self, code, message=None, explain=None):
        """Protocol-level refusals (oversized line/header, bad request line)."""
        if code in (413, 414, 431):      # oversized body, URL or header: out of range
            status, name = 422, "validation_failed"
        elif code in (405, 501):         # a method this service does not serve
            status, name = 405, "method_not_allowed"
        else:                            # bad request line, HTTP version, ...
            status, name = (code if 400 <= code < 500 else 400), "malformed_request"
        self.close_connection = True
        self._send(status, {"error": {"code": name, "message": message or "bad request"}})

    def _send(self, status, payload):
        self.request_version = "HTTP/1.1"  # never fall back to header-less HTTP/0.9
        if isinstance(payload, Raw):
            body, content_type = payload.body, payload.content_type
        else:
            body = b"" if payload is None else json.dumps(payload).encode("utf-8")
            content_type = "application/json; charset=utf-8"
        self.send_response(status)
        if body:
            self.send_header("Content-Type", content_type)
            if isinstance(payload, Raw):
                self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Keep-Alive", f"timeout={IDLE_SECONDS - 10}")
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    @staticmethod
    def _error_body(err):
        return err.status, {"error": {"code": err.code, "message": err.message}}

    def _handle(self):
        self.request_version = "HTTP/1.1"
        try:
            try:
                req = self._decode()
            except ApiError as err:
                self.close_connection = True  # the body may be half-read
                status, payload = self._error_body(err)
            except Exception:  # phase 1 failures are always the client's
                self.close_connection = True
                status, payload = self._error_body(_malformed("request could not be decoded"))
            else:
                try:
                    status, payload = dispatch(req)
                except ApiError as err:
                    status, payload = self._error_body(err)
                except RecursionError:
                    status, payload = self._error_body(_malformed("body is nested too deeply"))
                except Exception as err:  # unexpected: log, answer 500, never leak
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
