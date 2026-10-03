"""HTTP transport: threaded stdlib server, JSON in/out, uniform error bodies."""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

from .errors import ApiError
from .router import Request, dispatch
from .web import Raw

MAX_BODY = 8 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 60
    server_version = "tablekeeper"

    def log_message(self, *args):  # keep container logs quiet
        pass

    def _read_body(self):
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            chunks = []
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline().strip():
                        pass
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
            return b"".join(chunks)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(400, "malformed_request", "body too large")
        return self.rfile.read(length) if length > 0 else b""

    def _send(self, status, payload):
        if isinstance(payload, Raw):
            body, ctype = payload.body, payload.content_type
        else:
            body = b"" if payload is None else json.dumps(payload).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", ctype)
            if isinstance(payload, Raw):
                self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _handle(self):
        try:
            try:
                raw = self._read_body()
            except ValueError:
                raise ApiError(400, "malformed_request", "bad request framing")
            parts = urlsplit(self.path)
            query = {}
            for k, v in parse_qsl(parts.query, keep_blank_values=True):
                query.setdefault(k, v)
            headers = {k.lower(): v for k, v in self.headers.items()}
            status, payload = dispatch(Request(self.command, parts.path, query, headers, raw))
        except ApiError as err:
            status, payload = err.status, {"error": {"code": err.code, "message": err.message}}
        except Exception as err:  # never leak a traceback; log and answer in the error shape
            print(f"internal error: {err!r}", file=sys.stderr, flush=True)
            status, payload = 500, {"error": {"code": "internal_error",
                                              "message": "internal error"}}
        self._send(status, payload)

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = do_HEAD = _handle


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 512
    allow_reuse_address = True


def main():
    port = int(os.environ.get("PORT") or 8080)
    Server(("0.0.0.0", port), Handler).serve_forever()
