"""HTTP transport: threaded stdlib server on 0.0.0.0:$PORT."""
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .errors import ApiError
from .router import Request, dispatch
from .store import Store

MAX_BODY = 64 * 1024 * 1024
STORE = Store()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "tablekeeper"

    def log_message(self, *args):
        pass

    def _read_body(self):
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            chunks = []
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline().strip():
                        pass
                    return b"".join(chunks)
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > MAX_BODY:
            raise ValueError("bad length")
        return self.rfile.read(length) if length else b""

    def _send(self, status, body):
        payload = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if body is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _handle(self):
        try:
            try:
                raw = self._read_body()
            except ValueError:
                self.close_connection = True
                raise ApiError("unreadable request body", "malformed_request", 400)
            parts = urllib.parse.urlsplit(self.path)
            query = {}
            for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
                query.setdefault(k, v)
            req = Request(self.command, urllib.parse.unquote(parts.path), query, self.headers, raw)
            status, body = dispatch(STORE, req)
        except ApiError as e:
            status, body = e.status, {"error": {"code": e.code, "message": e.message}}
        except Exception as e:  # last resort: still a well-formed envelope
            sys.stderr.write("internal error: %r\n" % (e,))
            status, body = 500, {"error": {"code": "internal_error", "message": "internal error"}}
        self._send(status, body)

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = do_HEAD = do_OPTIONS = _handle


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 512
    allow_reuse_address = True


def main():
    port = int(os.environ.get("PORT") or 8080)
    Server(("0.0.0.0", port), Handler).serve_forever()
