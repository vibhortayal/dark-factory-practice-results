"""HTTP transport: reads requests, calls the router, writes JSON responses."""
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit

from .errors import ApiError, malformed
from .jsonutil import dumps
from .request import Request
from .routes import dispatch

MAX_BODY = 16 * 1024 * 1024
_CODES = {404: "not_found"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "pocketful"

    def log_message(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        """Framework-level errors (bad request line, oversize headers) use the error body."""
        self.close_connection = True
        status = 404 if code in (405, 501) else (code if code >= 400 else 400)  # unknown method
        err = _CODES.get(status) or ("malformed_request" if status < 500 else "internal_error")
        self._send(status, {"error": {"code": err, "message": message or "bad request"}})

    def _read_body(self):
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            chunks, total = [], 0
            while True:
                size_line = self.rfile.readline(65537).split(b";")[0].strip()
                size = int(size_line or b"0", 16)
                if size == 0:
                    while self.rfile.readline(65537).strip():
                        pass
                    return b"".join(chunks)
                total += size
                if total > MAX_BODY:
                    raise ValueError("too large")
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > MAX_BODY:
            raise ValueError("bad length")
        return self.rfile.read(length) if length else b""

    def _handle(self):
        try:
            try:
                raw = self._read_body()
            except (ValueError, OSError):
                self.close_connection = True
                raise malformed("unreadable or oversized request body") from None
            parts = urlsplit(self.path)
            query = {}
            for key, value in parse_qsl(parts.query, keep_blank_values=True):
                query.setdefault(key, value)
            req = Request(self.command, unquote(parts.path), query, self.headers, raw)
            status, payload = dispatch(req)
        except ApiError as err:
            status, payload = err.status, err.body()
        except Exception:
            traceback.print_exc(file=sys.stderr)
            status, payload = 500, {"error": {"code": "internal_error", "message": "internal error"}}
        self._send(status, payload)

    def _send(self, status, payload):
        body = b"" if payload is None else dumps(payload)
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _handle


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256
    allow_reuse_address = True
