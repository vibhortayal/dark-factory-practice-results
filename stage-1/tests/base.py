import re
import unittest

from .support import Api, fixture, user

RFC3339 = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)$")


class ApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = Api()

    @classmethod
    def tearDownClass(cls):
        cls.api.close()

    def setUp(self):
        self.reset()

    def reset(self, fx=None):
        self.api.reset(fx or fixture())
        self.tok = {h: self.api.login(h + "@example.com") for h in ("ada", "bob", "cy")}

    def call(self, method, path, body=None, who=None, token=None, key=None, **kw):
        token = token or (self.tok[who] if who else None)
        return self.api.call(method, path, body, token=token, key=key, **kw)

    def expect(self, status, code, result):
        s, b, _ = result
        self.assertEqual(s, status, b)
        if code:
            self.assertEqual(b["error"]["code"], code)
        return b

    def balance(self, who):
        return self.call("GET", "/me", who=who)[1]["balance"]

    def pay(self, who, to, amount, key, **extra):
        return self.call("POST", "/payments", dict(to_handle=to, amount=amount, **extra),
                         who=who, key=key)
