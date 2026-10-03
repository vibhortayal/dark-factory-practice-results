"""Rows V-AC: timestamps, `as_of`/`known_at` views, statements, snapshots."""
import threading
import time
from datetime import datetime, timedelta, timezone

from .base import ApiTestCase
from .support import Api, fixture, user

P1 = "2026-01-01T10:00:00+00:00"
P2 = "2026-01-02T10:00:00+00:00"


def seeded(**extra):
    """ada 10000, bob 2500, cy 500 after: p1 ada->bob 500, p2 bob->ada 200, p3 cy->bob 100 (tied with p2).
    Openings: ada 10300, bob 2100, cy 600."""
    return fixture(payments=[
        {"id": "p1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "a", "created_at": P1},
        {"id": "p2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 200, "note": "b", "created_at": P2},
        {"id": "p3", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 100, "visibility": "private", "created_at": P2},
    ], **extra)


class HistoryBase(ApiTestCase):
    def setUp(self):
        self.reset(seeded())

    def me(self, who="ada", **q):
        s, b, _ = self.call("GET", "/me", who=who, query=None) if False else self.api.call(
            "GET", "/me?" + "&".join("%s=%s" % kv for kv in q.items()), token=self.tok[who])
        return s, b

    def stmt(self, who="ada", **q):
        qs = "&".join("%s=%s" % (k, v) for k, v in q.items())
        s, b, _ = self.api.call("GET", "/statement" + ("?" + qs if qs else ""), token=self.tok[who])
        return s, b

    def correct(self, pid, rev, amount, eff, reason="fix", who="ada", key=None):
        key = key or "c-%s-%d-%d-%s" % (pid, rev, amount, eff)
        return self.call("POST", "/payments/%s/corrections" % pid,
                         {"expected_revision": rev, "amount": amount, "effective_at": eff, "reason": reason},
                         who=who, key=key)


def enc(text):
    return text.replace("+", "%2B")


class TimestampTests(HistoryBase):
    def test_seeded_and_api_payments(self):
        feed = self.call("GET", "/activity", who="ada")[1]["payments"]
        self.assertEqual({p["payment_id"]: p["created_at"] for p in feed}, {"p1": P1, "p2": P2})
        new = self.pay("ada", "bob", 5, "k")[1]
        self.assertGreater(datetime.fromisoformat(new["created_at"]), datetime.fromisoformat(P2))
        self.assertIsNotNone(datetime.fromisoformat(new["created_at"]).tzinfo)
        feed = self.call("GET", "/activity", who="ada")[1]["payments"]
        self.assertEqual(feed[0]["payment_id"], new["payment_id"])
        self.assertEqual(self.balance("ada"), 10000 - 5)

    def test_reset_time_default_and_errors(self):
        fx = fixture(payments=[{"id": "p1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500}])
        self.reset(fx)
        first = self.call("GET", "/activity", who="ada")[1]["payments"][0]
        later = self.pay("ada", "bob", 1, "k")[1]
        self.assertLess(datetime.fromisoformat(first["created_at"]), datetime.fromisoformat(later["created_at"]))
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        for bad in (future, "2026-01-01", "2026-01-01T10:00:00", "garbage", 5):
            fx["payments"][0]["created_at"] = bad
            self.expect(422, "validation_failed", self.api.call("POST", "/_test/reset", fx))
        self.assertEqual(self.balance("ada"), 10000 - 1)  # state intact
        fx["payments"][0]["created_at"] = "2026-01-01T12:00:00+02:00"
        self.reset(fx)
        self.assertEqual(self.call("GET", "/activity", who="ada")[1]["payments"][0]["created_at"], "2026-01-01T12:00:00+02:00")

    def test_every_payment_endpoint_has_created_at(self):
        self.reset(fixture(settlement_operator_ids=["u_cy"]))
        p = self.pay("ada", "bob", 5, "a")[1]
        rid = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, who="bob", key="r")[1]["request_id"]
        q = self.call("POST", "/requests/%s/pay" % rid, {}, who="ada", key="rp")[1]
        aid = self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, who="ada", key="au")[1]["authorization_id"]
        c = self.call("POST", "/authorizations/%s/capture" % aid, {}, who="bob", key="cp")[1]
        s = self.call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}, who="cy", key="st")[1]
        for pay in (p, q, c, s["payments"][0]):
            self.assertIsNotNone(datetime.fromisoformat(pay["created_at"]).tzinfo)
        self.assertEqual(s["payments"][0]["created_at"], s["committed_at"])


class AsOfTests(HistoryBase):
    def test_opening_and_boundaries(self):
        self.assertEqual(self.me(as_of=enc("2025-12-31T00:00:00+00:00"))[1]["balance"], 10300)
        self.assertEqual(self.me(as_of=enc("2026-01-01T09:59:59+00:00"))[1]["balance"], 10300)
        self.assertEqual(self.me(as_of=enc(P1))[1]["balance"], 9800)           # exactly at: counts
        self.assertEqual(self.me(as_of=enc("2026-01-01T10:00:00.000001+00:00"))[1]["balance"], 9800)
        self.assertEqual(self.me(as_of=enc("2026-01-02T09:59:59.999999+00:00"))[1]["balance"], 9800)
        self.assertEqual(self.me(as_of=enc(P2))[1]["balance"], 10000)
        self.assertEqual(self.me(as_of="2027-01-01T00:00:00Z")[1]["balance"], 10000)
        self.assertEqual(self.me("bob", as_of=enc(P2))[1]["balance"], 2500)
        self.assertEqual(self.me("bob", as_of=enc(P1))[1]["balance"], 2600)
        self.assertEqual(self.me("cy", as_of=enc("2026-01-01T00:00:00+00:00"))[1]["balance"], 600)

    def test_offsets_and_equivalence(self):
        self.assertEqual(self.me(as_of=enc("2026-01-01T12:00:00+02:00"))[1]["balance"], 9800)
        self.assertEqual(self.me(as_of="2026-01-01T10:00:00Z")[1]["balance"], 9800)
        self.assertEqual(self.me(as_of=enc("2026-01-01T05:00:00-05:00"))[1]["balance"], 9800)
        # a raw "+" (decoded to a space by query parsing) is repaired
        self.assertEqual(self.me(as_of="2026-01-01T10:00:00+00:00")[1]["balance"], 9800)

    def test_echo_and_invalid(self):
        s, b = self.me(as_of=enc(P1))
        self.assertEqual((b["as_of"], "known_at" in b), (P1, False))
        self.assertEqual((b["total"], b["available"], b["held"], b["balance"]), (9800, 9800, 0, 9800))
        s, b = self.me(as_of="2026-01-01T10:00:00.5Z", known_at="2030-01-01T00:00:00Z")
        self.assertEqual((b["as_of"], b["known_at"]), ("2026-01-01T10:00:00.5Z", "2030-01-01T00:00:00Z"))
        s, b = self.me()
        self.assertNotIn("as_of", b)
        self.assertNotIn("known_at", b)
        for name in ("as_of", "known_at"):
            for bad in ("", "2026-01-01", "2026-01-01T10:00:00", "yesterday", "2026-13-01T00:00:00Z",
                        "2026-01-01T10:00:00%2B25:00", "2026-01-01%2010:00:00Z", "1767261600"):
                self.expect(422, "validation_failed", self.api.call("GET", "/me?%s=%s" % (name, bad), token=self.tok["ada"]))

    def test_conservation_in_every_view(self):
        instants = ["2025-12-01T00:00:00Z", P1, "2026-01-01T10:00:01Z", P2, "2030-01-01T00:00:00Z"]
        for t in instants:
            total = sum(self.me(w, as_of=enc(t))[1]["balance"] for w in ("ada", "bob", "cy"))
            self.assertEqual(total, 13000, t)


class StatementTests(HistoryBase):
    def test_full_statement(self):
        s, b = self.stmt()
        self.assertEqual(s, 200)
        self.assertEqual((b["opening_balance"], b["closing_balance"], b["has_more"]), (10300, 10000, False))
        self.assertEqual([(e["payment"]["payment_id"], e["delta"], e["balance_after"]) for e in b["entries"]],
                         [("p1", -500, 9800), ("p2", 200, 10000)])
        e = b["entries"][0]
        self.assertEqual((e["revision"], e["effective_at"], e["recorded_at"], e["payment"]["amount"]), (1, P1, P1, 500))
        self.assertIn("snapshot", b)
        self.assertNotIn("known_at", b)

    def test_only_own_payments_and_private(self):
        _, b = self.stmt("cy")
        self.assertEqual([e["payment"]["payment_id"] for e in b["entries"]], ["p3"])
        _, b = self.stmt("bob")      # sees the private payment it received, ties by id
        self.assertEqual([e["payment"]["payment_id"] for e in b["entries"]], ["p1", "p2", "p3"])
        self.assertEqual([e["balance_after"] for e in b["entries"]], [2600, 2400, 2500])
        self.assertEqual((b["opening_balance"], b["closing_balance"]), (2100, 2500))

    def test_window_half_open(self):
        _, b = self.stmt(**{"from": enc(P1), "to": enc(P2)})
        self.assertEqual([e["payment"]["payment_id"] for e in b["entries"]], ["p1"])
        self.assertEqual((b["opening_balance"], b["closing_balance"]), (10300, 9800))
        _, b = self.stmt(**{"from": enc(P2)})
        self.assertEqual([e["payment"]["payment_id"] for e in b["entries"]], ["p2"])
        self.assertEqual((b["opening_balance"], b["closing_balance"]), (9800, 10000))
        _, b = self.stmt(**{"from": enc("2026-01-01T10:00:00.000001+00:00"), "to": enc("2026-01-02T09:00:00+00:00")})
        self.assertEqual((b["entries"], b["opening_balance"], b["closing_balance"]), ([], 9800, 9800))
        _, b = self.stmt(to=enc("2025-01-01T00:00:00Z"))
        self.assertEqual((b["entries"], b["opening_balance"], b["closing_balance"]), ([], 10300, 10300))

    def test_pagination_does_not_change_balances(self):
        _, whole = self.stmt("bob")
        got = []
        for offset in range(0, 4):
            _, page = self.stmt("bob", limit=1, offset=offset)
            self.assertEqual((page["opening_balance"], page["closing_balance"]), (2100, 2500))
            got += page["entries"]
            self.assertEqual(page["has_more"], offset < 2)
        self.assertEqual([e["balance_after"] for e in got], [e["balance_after"] for e in whole["entries"]])
        _, beyond = self.stmt("bob", offset=50)
        self.assertEqual((beyond["entries"], beyond["has_more"], beyond["closing_balance"]), ([], False, 2500))
        for q in ({"limit": 0}, {"limit": 201}, {"offset": -1}, {"limit": "1e1"}):
            self.expect(422, "validation_failed", (self.stmt("bob", **q)[0], self.stmt("bob", **q)[1], None))

    def test_invalid_params_and_ignored(self):
        for q in ({"from": "2026-01-01"}, {"to": ""}, {"known_at": "x"}, {"from": enc(P2), "to": enc(P1)}):
            self.assertEqual(self.stmt(**q)[0], 422, q)
        self.assertEqual(self.stmt(color="red")[0], 200)
        self.assertEqual(self.api.call("GET", "/statement")[0], 401)

    def test_new_payments_and_non_movements(self):
        aid = self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, who="ada", key="a")[1]["authorization_id"]
        self.call("POST", "/authorizations/%s/void" % aid, who="ada")
        a2 = self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, who="ada", key="a2")[1]["authorization_id"]
        cap = self.call("POST", "/authorizations/%s/capture" % a2, {"amount": 40}, who="bob", key="c")[1]
        _, b = self.stmt()
        self.assertEqual(len(b["entries"]), 3)
        last = b["entries"][-1]
        self.assertEqual((last["payment"]["payment_id"], last["payment"]["authorization_id"], last["delta"]),
                         (cap["payment_id"], a2, -40))
        self.assertEqual(b["closing_balance"], 9960)
        self.assertEqual(b["opening_balance"] + sum(e["delta"] for e in b["entries"]), b["closing_balance"])

    def test_snapshot_pages_frozen_result(self):
        _, first = self.stmt("bob")
        token = first["snapshot"]
        self.call("POST", "/payments", {"to_handle": "bob", "amount": 7}, who="ada", key="later")
        self.correct("p1", 1, 100, P1)
        _, again = self.stmt("bob", snapshot=token, limit=2, offset=0)
        self.assertEqual(again["entries"], first["entries"][:2])
        self.assertTrue(again["has_more"])
        _, last = self.stmt("bob", snapshot=token, limit=2, offset=2)
        self.assertEqual((last["entries"], last["has_more"], last["closing_balance"]), (first["entries"][2:], False, 2500))
        _, fresh = self.stmt("bob")
        self.assertNotEqual(fresh["closing_balance"], first["closing_balance"])
        for extra in ({"from": enc(P1)}, {"to": enc(P2)}, {"known_at": "2030-01-01T00:00:00Z"}):
            self.assertEqual(self.stmt("bob", snapshot=token, **extra)[0], 422)
        self.assertEqual(self.stmt("bob", snapshot=token, junk=1)[0], 200)
        self.assertEqual(self.stmt("ada", snapshot=token)[0], 404)
        self.assertEqual(self.stmt("bob", snapshot="nope")[0], 404)
        self.assertEqual(self.stmt("bob", snapshot=token, limit=0)[0], 422)
        self.api.reset(seeded())
        self.tok = {h: self.api.login(h + "@example.com") for h in ("ada", "bob", "cy")}
        self.assertEqual(self.stmt("bob", snapshot=token)[0], 404)
