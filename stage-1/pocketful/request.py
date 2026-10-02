"""A parsed HTTP request as the handlers see it."""
import json

from .errors import malformed


def _reject_constant(name):
    raise ValueError(name)


class Request:
    def __init__(self, method, path, query, headers, raw):
        self.method = method
        self.path = path
        self.query = query
        self.headers = headers
        self.raw = raw
        self.params = ()
        self.user_id = None

    def header(self, name):
        return self.headers.get(name)

    def json_body(self, allow_empty=False):
        """The body as a JSON object; anything else is 400 malformed_request."""
        if not self.raw.strip():
            if allow_empty:
                return {}
            raise malformed("a JSON body is required")
        try:
            value = json.loads(self.raw.decode("utf-8"), parse_constant=_reject_constant)
        except (ValueError, RecursionError):
            raise malformed("body is not valid JSON")
        if not isinstance(value, dict):
            raise malformed("body must be a JSON object")
        return value
