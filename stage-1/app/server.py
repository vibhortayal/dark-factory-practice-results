"""HTTP plumbing: socket handling, body reading, JSON responses."""
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

from .errors import ApiError, malformed
from .jsonutil import dumps
from .router import Request, dispatch
from .store import Holder

MAX_BODY = 64 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 60
    holder = Holder()

    def log_message(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.close_connection = True
        self._write(code, dumps({"error": {"code": "malformed_request" if code == 400
                                           else "http_error",
                                           "message": message or "http error"}}))

    def _write(self, status, payload):
        if status == 204:
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _read_body(self) -> bytes:
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            return self._read_chunked()
        length = self.headers.get("Content-Length")
        if length is None:
            return b""
        if not length.isascii() or not length.isdigit() or int(length) > MAX_BODY:
            self.close_connection = True
            raise malformed("invalid Content-Length")
        return self.rfile.read(int(length))

    def _read_chunked(self) -> bytes:
        chunks, total = [], 0
        try:
            while True:
                size = int(self.rfile.readline(1024).split(b";")[0].strip() or b"x", 16)
                if size == 0:
                    while self.rfile.readline(1024).strip():
                        pass
                    return b"".join(chunks)
                total += size
                if total > MAX_BODY:
                    raise ValueError
                chunks.append(self.rfile.read(size))
                self.rfile.readline(4)
        except ValueError:
            self.close_connection = True
            raise malformed("invalid chunked body") from None

    def _handle(self):
        try:
            parts = urlsplit(self.path)
            query = {}
            for name, value in parse_qsl(parts.query, keep_blank_values=True):
                query.setdefault(name, value)
            raw = self._read_body()
            status, payload = dispatch(self.holder, Request(
                self.command, parts.path, query, self.headers, raw))
            if isinstance(payload, dict):
                payload = dumps(payload)
        except ApiError as err:
            status, payload = err.status, dumps(err.body())
        except Exception as err:  # last resort: never leak a traceback
            print("internal error: %r" % (err,), file=sys.stderr)
            status = 500
            payload = dumps({"error": {"code": "internal_error", "message": "internal error"}})
        self._write(status, payload)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _handle


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 256


def make_server(port: int, host: str = "0.0.0.0") -> Server:
    return Server((host, port), Handler)


def main():
    try:
        port = int(os.environ.get("PORT", "8080"))
    except ValueError:
        port = 8080
    make_server(port).serve_forever()
