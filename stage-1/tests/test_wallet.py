"""Rows G, H: payments, requests, splits, feed, rounding."""
from .base import ApiTestCase
from .support import fixture, user
from app.ledger import equal_split


class PaymentTests(ApiTestCase):
    def test_payment_shape_and_balances(self):
        s, b, _ = self.pay("ada", "bob", 1500, "k", note="dinner", visibility="private")
        self.assertEqual(s, 201)
        self.assertEqual(set(b), {"payment_id", "from_user_id", "from_handle", "to_user_id",
                                  "to_handle", "amount", "currency", "note", "visibility",
                                  "request_id", "settlement_id", "created_at"})
        self.assertEqual((b["request_id"], b["settlement_id"]), (None, None))
        self.assertEqual((self.balance("ada"), self.balance("bob")), (8500, 4000))

    def test_errors_leave_no_trace(self):
        self.expect(409, "insufficient_funds", self.pay("cy", "ada", 501, "k"))
        self.expect(422, "self_payment", self.pay("ada", "ada", 5, "k2"))
        self.expect(404, "not_found", self.pay("ada", "nobody", 5, "k3"))
        self.assertEqual((self.balance("cy"), self.balance("ada")), (500, 10000))
        self.assertEqual(self.call("GET", "/activity", who="ada")[1]["payments"], [])
        self.assertEqual(self.pay("cy", "ada", 500, "k4")[0], 201)
        self.assertEqual(self.balance("cy"), 0)


class RequestTests(ApiTestCase):
    def make(self, who="bob", payer="ada", amount=1200, key="r1"):
        s, b, _ = self.call("POST", "/requests", {"payer_handle": payer, "amount": amount, "note": "taxi"},
                            who=who, key=key)
        self.assertEqual(s, 201, b)
        return b

    def test_create_shape_and_errors(self):
        b = self.make()
        self.assertEqual((b["status"], b["payment_id"], b["requester_handle"], b["payer_handle"]),
                         ("pending", None, "bob", "ada"))
        self.expect(422, "self_request", self.call("POST", "/requests", {"payer_handle": "bob", "amount": 5}, who="bob", key="x"))
        self.expect(404, "not_found", self.call("POST", "/requests", {"payer_handle": "zz", "amount": 5}, who="bob", key="y"))
        self.expect(422, "validation_failed", self.call("POST", "/requests", {"payer_handle": "ada", "amount": 0}, who="bob", key="z"))
        self.make(who="ada", payer="cy", amount=99999, key="big")  # not balance checked

    def test_pay_flow(self):
        rid = self.make()["request_id"]
        self.expect(403, "forbidden", self.call("POST", "/requests/%s/pay" % rid, {}, who="bob", key="p"))
        self.expect(403, "forbidden", self.call("POST", "/requests/%s/pay" % rid, {}, who="cy", key="p"))
        self.expect(404, "not_found", self.call("POST", "/requests/nope/pay", {}, who="ada", key="p"))
        s, pay, _ = self.call("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, who="ada", key="p")
        self.assertEqual((s, pay["request_id"], pay["visibility"], pay["amount"]), (201, rid, "private", 1200))
        req = self.call("GET", "/requests", who="bob")[1]["requests"][0]
        self.assertEqual((req["status"], req["payment_id"]), ("paid", pay["payment_id"]))
        self.assertEqual((self.balance("ada"), self.balance("bob")), (8800, 3700))
        self.expect(409, "request_not_pending", self.call("POST", "/requests/%s/pay" % rid, {}, who="ada", key="p2"))
        s, again, _ = self.call("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, who="ada", key="p")
        self.assertEqual((s, again), (200, pay))
        self.assertEqual(self.balance("ada"), 8800)
        self.expect(409, "request_not_pending", self.call("POST", "/requests/%s/decline" % rid, who="ada"))
        self.expect(409, "request_not_pending", self.call("POST", "/requests/%s/cancel" % rid, who="bob"))

    def test_pay_empty_body_and_bad_visibility(self):
        rid = self.make()["request_id"]
        self.expect(422, "validation_failed", self.call("POST", "/requests/%s/pay" % rid, {"visibility": "x"}, who="ada", key="a"))
        s, pay, _ = self.api.call("POST", "/requests/%s/pay" % rid, token=self.tok["ada"], key="b")
        self.assertEqual((s, pay["visibility"]), (201, "public"))

    def test_insufficient_then_payable_later(self):
        rid = self.make(who="ada", payer="cy", amount=800)["request_id"]
        self.expect(409, "insufficient_funds", self.call("POST", "/requests/%s/pay" % rid, {}, who="cy", key="p"))
        self.assertEqual(self.call("GET", "/requests", who="cy")[1]["requests"][0]["status"], "pending")
        self.assertEqual(self.pay("bob", "cy", 300, "top")[0], 201)
        self.assertEqual(self.call("POST", "/requests/%s/pay" % rid, {}, who="cy", key="p")[0], 201)

    def test_decline_cancel(self):
        r1 = self.make(key="a")["request_id"]
        self.expect(403, "forbidden", self.call("POST", "/requests/%s/decline" % r1, who="bob"))
        self.expect(403, "forbidden", self.call("POST", "/requests/%s/cancel" % r1, who="ada"))
        self.expect(404, "not_found", self.call("POST", "/requests/zz/decline", who="ada"))
        self.expect(404, "not_found", self.call("POST", "/requests/zz/cancel", who="ada"))
        for _ in range(2):
            self.assertEqual(self.call("POST", "/requests/%s/decline" % r1, who="ada")[1]["status"], "declined")
        self.expect(409, "request_not_pending", self.call("POST", "/requests/%s/cancel" % r1, who="bob"))
        self.expect(409, "request_not_pending", self.call("POST", "/requests/%s/pay" % r1, {}, who="ada", key="p"))
        r2 = self.make(key="b")["request_id"]
        for _ in range(2):
            self.assertEqual(self.call("POST", "/requests/%s/cancel" % r2, who="bob")[1]["status"], "cancelled")
        self.expect(409, "request_not_pending", self.call("POST", "/requests/%s/decline" % r2, who="ada"))

    def test_list_filters_and_paging(self):
        ids = [self.make(key="k%d" % i, amount=10 + i)["request_id"] for i in range(5)]
        self.make(who="ada", payer="cy", key="other")
        self.call("POST", "/requests/%s/cancel" % ids[0], who="bob")
        body = self.call("GET", "/requests?direction=incoming&status=pending", who="ada")[1]
        self.assertEqual(len(body["requests"]), 4)
        self.assertEqual(self.call("GET", "/requests?direction=outgoing", who="ada")[1]["requests"][0]["payer_handle"], "cy")
        both = self.call("GET", "/requests", who="ada")[1]["requests"]
        self.assertEqual(len(both), 6)
        self.assertEqual(len(self.call("GET", "/requests", who="cy")[1]["requests"]), 1)
        page = self.call("GET", "/requests?limit=2&offset=0", who="ada")[1]
        self.assertEqual((len(page["requests"]), page["has_more"]), (2, True))
        page = self.call("GET", "/requests?limit=2&offset=4", who="ada")[1]
        self.assertEqual((len(page["requests"]), page["has_more"]), (2, False))
        self.assertEqual(both[0]["payer_handle"], "cy")  # newest first
        self.expect(422, "validation_failed", self.call("GET", "/requests?direction=sideways", who="ada"))
        self.expect(422, "validation_failed", self.call("GET", "/requests?status=nope", who="ada"))


class SplitTests(ApiTestCase):
    def split(self, who, amount, handles, key="s", note="dinner"):
        return self.call("POST", "/splits", {"amount": amount, "participant_handles": handles, "note": note},
                         who=who, key=key)

    def test_rounding_table(self):
        for amount, n, shares in ((1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
                                  (999, 3, [333] * 3), (5, 5, [1] * 5)):
            self.assertEqual(equal_split(amount, n), shares)

    def test_split_shape_and_order(self):
        s, b, _ = self.split("ada", 1000, ["cy", "ada", "bob"])
        self.assertEqual(s, 201)
        self.assertEqual(b["shares"], [{"handle": "cy", "amount": 334}, {"handle": "ada", "amount": 333},
                                       {"handle": "bob", "amount": 333}])
        self.assertEqual([(r["payer_handle"], r["amount"], r["requester_handle"]) for r in b["requests"]],
                         [("cy", 334, "ada"), ("bob", 333, "ada")])
        s, b, _ = self.split("ada", 1000, ["ada", "bob", "cy"], key="s2")
        self.assertEqual([x["amount"] for x in b["shares"]], [334, 333, 333])
        self.assertEqual(len(b["requests"]), 2)
        self.assertEqual(self.balance("ada"), 10000)

    def test_caller_omitted_and_caller_only(self):
        b = self.split("ada", 1, ["bob", "cy", "ada"], key="a")[1]
        self.assertEqual([x["amount"] for x in b["shares"]], [1, 0, 0])
        b = self.split("ada", 7, ["bob", "cy"], key="b")[1]
        self.assertEqual([x["amount"] for x in b["shares"]], [4, 3])
        b = self.split("ada", 700, ["ada"], key="c")[1]
        self.assertEqual((b["requests"], b["shares"]), ([], [{"handle": "ada", "amount": 700}]))

    def test_zero_share_request_payable(self):
        b = self.split("ada", 1, ["ada", "bob", "cy"])[1]
        zero = b["requests"][0]
        self.assertEqual(zero["amount"], 0)
        self.assertEqual(self.call("POST", "/requests/%s/pay" % zero["request_id"], {}, who="bob", key="z")[0], 201)

    def test_errors(self):
        self.expect(422, "validation_failed", self.split("ada", 0, ["bob"], "e1"))
        self.expect(422, "validation_failed", self.split("ada", 5, [], "e2"))
        self.expect(422, "validation_failed", self.split("ada", 5, ["bob", "bob"], "e3"))
        self.expect(422, "validation_failed", self.split("ada", 5, ["bob"], "e4", note="x" * 201))
        self.expect(404, "not_found", self.split("ada", 5, ["bob", "ghost"], "e5"))
        self.expect(400, "malformed_request", self.call("POST", "/splits", {"amount": 5, "participant_handles": "bob"}, who="ada", key="e6"))
        self.expect(422, "validation_failed", self.call("POST", "/splits", {"amount": 5}, who="ada", key="e7"))

    def test_no_balance_check_and_payments_conserve(self):
        self.api.reset(fixture(users=[user("ada", 0), user("bob", 100), user("cy", 100)]))
        self.tok = {h: self.api.login(h + "@example.com") for h in ("ada", "bob", "cy")}
        b = self.split("ada", 999999, ["ada", "bob", "cy"])[1]
        self.assertEqual(sum(s["amount"] for s in b["shares"]), 999999)
        self.assertEqual(self.balance("ada") + self.balance("bob") + self.balance("cy"), 200)


class FeedTests(ApiTestCase):
    def test_visibility_rule(self):
        self.pay("ada", "bob", 5, "a", visibility="private")
        self.pay("ada", "bob", 6, "b", visibility="public")
        self.call("POST", "/requests", {"payer_handle": "ada", "amount": 9}, who="bob", key="r")
        self.call("POST", "/splits", {"amount": 9, "participant_handles": ["bob"]}, who="ada", key="sp")
        for who, expected in (("ada", [6, 5]), ("bob", [6, 5]), ("cy", [6])):
            body = self.call("GET", "/activity", who=who)[1]
            self.assertEqual([p["amount"] for p in body["payments"]], expected)
            self.assertFalse(body["has_more"])
        priv = self.call("GET", "/activity", who="bob")[1]["payments"][1]
        self.assertEqual(priv["visibility"], "private")
        self.assertEqual(self.call("GET", "/requests", who="cy")[1]["requests"], [])

    def test_paging(self):
        for i in range(5):
            self.pay("ada", "bob", i + 1, "k%d" % i)
        page = self.call("GET", "/activity?limit=2&offset=1", who="cy")[1]
        self.assertEqual(([p["amount"] for p in page["payments"]], page["has_more"]), ([4, 3], True))
        page = self.call("GET", "/activity?limit=2&offset=4", who="cy")[1]
        self.assertEqual(([p["amount"] for p in page["payments"]], page["has_more"]), ([1], False))
