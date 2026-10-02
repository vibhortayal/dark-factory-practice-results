import re
import threading
import uuid

from .helpers import World, call

TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$")


class PaymentTests(World):
    def test_shape_and_money(self):
        r = self.post("ada", "/payments", {"to_handle": "bob", "amount": 1500, "note": "dinner"})
        self.assertEqual(r.status, 201)
        self.assertEqual(set(r.json), {"payment_id", "from_user_id", "from_handle", "to_user_id",
                                       "to_handle", "amount", "currency", "note", "visibility",
                                       "request_id", "settlement_id", "authorization_id", "created_at"})
        self.assertRegex(r.json["created_at"], TS)
        self.assertEqual((r.json["visibility"], r.json["request_id"]), ("public", None))
        self.assertEqual(self.balance("ada"), 8500)
        self.assertEqual(self.balance("bob"), 4000)
        self.assertEqual(r.headers["Content-Type"], "application/json; charset=utf-8")

    def test_amount_forms(self):
        for amount in (1000, 1000.0, "1e3"):
            body = '{"to_handle":"bob","amount":%s}' % ("1e3" if amount == "1e3" else json_dump(amount))
            self.assertEqual(self.post("ada", "/payments", raw=body.encode()).status, 201)
        for bad in ("0", "-1", "1000000001", "1.5", '"5"', "true", "null", "[]"):
            r = self.post("ada", "/payments", raw=('{"to_handle":"bob","amount":%s}' % bad).encode())
            self.assertErr(r, 422, "validation_failed")
        self.assertEqual(self.post("bob", "/payments", {"to_handle": "cy", "amount": 1}).status, 201)

    def test_rejections(self):
        self.assertErr(self.post("ada", "/payments", {"to_handle": "ada", "amount": 1}), 422, "self_payment")
        self.assertErr(self.post("ada", "/payments", {"to_handle": "ADA", "amount": 1}), 404, "not_found")
        self.assertErr(self.post("ada", "/payments", {"to_handle": "zed", "amount": 1}), 404, "not_found")
        self.assertErr(self.post("ada", "/payments", {"to_handle": 5, "amount": 1}), 400, "malformed_request")
        self.assertErr(self.post("ada", "/payments", {"amount": 1}), 422, "validation_failed")
        self.assertErr(self.post("ada", "/payments", {"to_handle": "bob", "amount": 1, "note": None}), 422, "validation_failed")
        self.assertErr(self.post("ada", "/payments", {"to_handle": "bob", "amount": 1, "visibility": "Public"}), 422, "validation_failed")
        self.assertErr(self.post("ada", "/payments", {"to_handle": "bob", "amount": 1, "note": "x" * 201}), 422, "validation_failed")
        self.assertEqual(self.post("ada", "/payments", {"to_handle": "bob", "amount": 1, "note": "\U0001F600" * 200}).status, 201)
        self.assertErr(self.post("ada", "/payments", {"to_handle": "bob", "amount": 1, "note": "\U0001F600" * 201}), 422, "validation_failed")
        self.assertErr(self.post("ada", "/payments", raw=b"[1]"), 400, "malformed_request")
        self.assertErr(self.post("ada", "/payments", raw=b"{nope"), 400, "malformed_request")
        self.assertErr(self.post("ada", "/payments", {"to_handle": "bob", "amount": 10001}), 409, "insufficient_funds")
        self.assertErr(self.post(None, "/payments", {"to_handle": "bob", "amount": 1}), 401, "unauthenticated")

    def test_exact_balance_leaves_zero(self):
        self.assertEqual(self.post("cy", "/payments", {"to_handle": "bob", "amount": 500}).status, 201)
        self.assertEqual(self.balance("cy"), 0)
        self.assertConserved()

    def test_note_verbatim(self):
        note = "  <script>é\u0301 \U0001F600 "
        r = self.post("ada", "/payments", {"to_handle": "bob", "amount": 1, "note": note})
        self.assertEqual(r.json["note"], note)

    def test_overdraft_race(self):
        results = []

        def go():
            results.append(self.post("cy", "/payments", {"to_handle": "bob", "amount": 100}).status)
        threads = [threading.Thread(target=go) for _ in range(30)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(results), [201] * 5 + [409] * 25)
        self.assertEqual(self.balance("cy"), 0)
        self.assertConserved()


class IdempotencyTests(World):
    def test_replay_and_reuse(self):
        body = {"to_handle": "bob", "amount": 100}
        a = self.post("ada", "/payments", body, key="k")
        b = self.post("ada", "/payments", {"amount": 100.0, "to_handle": "bob"}, key="k")
        self.assertEqual((a.status, b.status), (201, 200))
        self.assertEqual(a.json, b.json)
        self.assertEqual(self.balance("ada"), 9900)
        self.assertErr(self.post("ada", "/payments", {"to_handle": "bob", "amount": 101}, key="k"), 409, "idempotency_key_reuse")
        self.assertErr(self.post("ada", "/payments", {"to_handle": "bob", "amount": "bad"}, key="k"), 409, "idempotency_key_reuse")
        # other user, other path
        self.assertEqual(self.post("bob", "/payments", {"to_handle": "cy", "amount": 100}, key="k").status, 201)
        self.assertEqual(self.post("ada", "/requests", {"payer_handle": "bob", "amount": 100}, key="k").status, 201)

    def test_key_rules(self):
        self.assertErr(self.post("ada", "/payments", {"to_handle": "bob", "amount": 1}, key=None), 400, "missing_idempotency_key")
        self.assertErr(self.post("ada", "/payments", {"to_handle": "bob", "amount": 1}, key=""), 400, "missing_idempotency_key")
        self.assertErr(self.post("ada", "/payments", {"to_handle": "bob", "amount": 1}, key="k" * 256), 422, "validation_failed")
        self.assertEqual(self.post("ada", "/payments", {"to_handle": "bob", "amount": 1}, key="k" * 255).status, 201)

    def test_failed_key_is_reusable(self):
        self.assertErr(self.post("cy", "/payments", {"to_handle": "bob", "amount": 900}, key="f"), 409, "insufficient_funds")
        self.assertEqual(self.post("cy", "/payments", {"to_handle": "bob", "amount": 100}, key="f").status, 201)

    def test_concurrent_identical(self):
        results = []

        def go():
            results.append(self.post("ada", "/payments", {"to_handle": "bob", "amount": 100}, key="same").status)
        threads = [threading.Thread(target=go) for _ in range(40)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(results), [200] * 39 + [201])
        self.assertEqual(self.balance("ada"), 9900)


def json_dump(v):
    import json
    return json.dumps(v)
