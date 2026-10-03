"""Rows Z, AB, AC: corrections, revisions, historical overdraft, hold history, import across stages."""
import json
import threading
import time
from datetime import datetime, timedelta, timezone

from .base import ApiTestCase
from .support import Api, fixture, user
from .test_history import HistoryBase, P1, P2, enc, seeded

T0, T1, T2 = "2025-12-31T10:00:00+00:00", "2026-01-01T10:00:00+00:00", "2026-01-02T10:00:00+00:00"


def overdraft_fixture(**extra):
    """ada opening 0: +500@T0 (q0 from bob), -400@T1 (q1 to cy), +1000@T2 (q2 from bob) = 1100."""
    return fixture(users=[user("ada", 1100), user("bob", 1500), user("cy", 400)], payments=[
        {"id": "q0", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 500, "created_at": T0},
        {"id": "q1", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 400, "created_at": T1},
        {"id": "q2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1000, "created_at": T2},
    ], **extra)


class CorrectionTests(HistoryBase):
    def test_decrease_moves_between_same_wallets(self):
        s, b, _ = self.correct("p1", 1, 300, P1, "wrong amount")
        self.assertEqual(s, 201)
        self.assertEqual((b["payment_id"], b["revision"], b["amount"], b["effective_at"], b["reason"]), ("p1", 2, 300, P1, "wrong amount"))
        self.assertGreater(datetime.fromisoformat(b["recorded_at"]), datetime.fromisoformat(P2))
        self.assertEqual((self.balance("ada"), self.balance("bob"), self.balance("cy")), (10200, 2300, 500))
        self.assertEqual(self.me(as_of=enc(P1))[1]["balance"], 10000)              # opening 10300 - 300
        self.assertEqual(self.me(as_of=enc("2025-12-31T00:00:00Z"))[1]["balance"], 10300)  # opening unchanged
        # known before the correction: original amount; known before the payment: nothing
        self.assertEqual(self.me(as_of=enc(P1), known_at="2026-01-05T00:00:00Z")[1]["balance"], 9800)
        self.assertEqual(self.me(known_at="2025-12-31T00:00:00Z")[1]["balance"], 10300)
        self.assertEqual(self.me(known_at="2026-01-01T09:00:00Z", as_of="2030-01-01T00:00:00Z")[1]["balance"], 10300)
        s, b = self.stmt()
        self.assertEqual([(e["payment"]["payment_id"], e["payment"]["amount"], e["revision"], e["delta"]) for e in b["entries"]],
                         [("p1", 300, 2, -300), ("p2", 200, 1, 200)])
        self.assertEqual((b["opening_balance"], b["closing_balance"]), (10300, 10200))
        s, old = self.stmt(known_at="2026-01-05T00:00:00Z")
        self.assertEqual((old["entries"][0]["payment"]["amount"], old["entries"][0]["revision"], old["closing_balance"], old["known_at"]),
                         (500, 1, 10000, "2026-01-05T00:00:00Z"))
        self.assertEqual(self.stmt("bob")[1]["closing_balance"], 2300 + 0)

    def test_increase_zero_and_effective_shift(self):
        self.assertEqual(self.correct("p1", 1, 700, P1)[0], 201)       # ada pays 200 more
        self.assertEqual((self.balance("ada"), self.balance("bob")), (9800, 2700))
        s, b, _ = self.correct("p1", 2, 0, "2026-01-01T09:00:00+00:00", "reverse")
        self.assertEqual(s, 201)
        self.assertEqual((self.balance("ada"), self.balance("bob")), (10500, 2000))
        _, st = self.stmt(**{"from": enc("2026-01-01T09:30:00+00:00")})
        self.assertEqual([e["payment"]["payment_id"] for e in st["entries"]], ["p2"])   # moved out of the window
        _, st = self.stmt(**{"from": enc("2026-01-01T08:00:00+00:00"), "to": enc("2026-01-01T09:30:00+00:00")})
        self.assertEqual([(e["payment"]["payment_id"], e["delta"], e["revision"]) for e in st["entries"]], [("p1", 0, 3)])
        self.assertEqual(self.me(as_of=enc("2026-01-01T09:30:00+00:00"))[1]["balance"], 10300)
        revs = self.call("GET", "/payments/p1/revisions", who="bob")[1]["revisions"]
        self.assertEqual([(r["revision"], r["amount"], r["reason"]) for r in revs], [(1, 500, ""), (2, 700, "fix"), (3, 0, "reverse")])
        self.assertEqual((revs[0]["effective_at"], revs[0]["recorded_at"]), (P1, P1))
        times = [datetime.fromisoformat(r["recorded_at"]) for r in revs]
        self.assertEqual(times, sorted(set(times)))

    def test_same_amount_is_a_valid_revision(self):
        self.assertEqual(self.correct("p1", 1, 500, P1)[1]["revision"], 2)
        self.assertEqual((self.balance("ada"), self.balance("bob")), (10000, 2500))

    def test_permissions_and_lookup(self):
        self.expect(403, "forbidden", self.correct("p1", 1, 1, P1, who="bob"))
        self.expect(403, "forbidden", self.correct("p1", 1, 1, P1, who="cy"))
        self.expect(404, "not_found", self.correct("nope", 1, 1, P1))
        self.expect(401, "unauthenticated", self.api.call("POST", "/payments/p1/corrections", {}, key="k"))
        self.expect(401, "unauthenticated", self.api.call("GET", "/payments/p1/revisions"))
        self.expect(404, "not_found", self.call("GET", "/payments/p1/revisions", who="cy"))   # public, not a party
        self.expect(404, "not_found", self.call("GET", "/payments/nope/revisions", who="ada"))
        self.assertEqual(len(self.call("GET", "/payments/p1/revisions", who="ada")[1]["revisions"]), 1)

    def test_validation_matrix(self):
        base = {"expected_revision": 1, "amount": 400, "effective_at": P1, "reason": "x"}
        bad = [{"expected_revision": 0}, {"expected_revision": -1}, {"expected_revision": "1"}, {"expected_revision": 1.5},
               {"expected_revision": True}, {"amount": -1}, {"amount": 1000000001}, {"amount": "5"}, {"amount": 1.5},
               {"amount": None}, {"effective_at": "2026-01-01"}, {"effective_at": "2026-01-01T10:00:00"},
               {"effective_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}, {"effective_at": 5},
               {"reason": ""}, {"reason": "r" * 201}, {"reason": 5}, {"reason": None}]
        for i, change in enumerate(bad):
            self.expect(422, "validation_failed", self.call("POST", "/payments/p1/corrections", dict(base, **change), who="ada", key="v%d" % i))
        for name in base:
            partial = {k: v for k, v in base.items() if k != name}
            self.expect(422, "validation_failed", self.call("POST", "/payments/p1/corrections", partial, who="ada", key="m"))
        self.expect(400, "malformed_request", self.call("POST", "/payments/p1/corrections", who="ada", key="m", raw=b"[1]"))
        for ok, key in (({"amount": 1000000000, "reason": "r" * 200}, "ok1"),):   # bounds are inclusive (needs funds: ada has 10300)
            pass
        self.assertEqual(self.call("POST", "/payments/p1/corrections", dict(base, amount=0), who="ada", key="z")[0], 201)
        self.assertEqual(self.balance("ada"), 10500)
        now = datetime.now(timezone.utc).isoformat()   # "not later than now": a past instant today passes
        self.assertEqual(self.call("POST", "/payments/p1/corrections", dict(base, expected_revision=2, effective_at=now, amount=1),
                                   who="ada", key="now")[0], 201)

    def test_stale_and_concurrent(self):
        self.assertEqual(self.correct("p1", 1, 400, P1)[0], 201)
        self.expect(409, "stale_revision", self.correct("p1", 1, 300, P1))
        self.expect(409, "stale_revision", self.correct("p1", 5, 300, P1))
        results = []
        threads = [threading.Thread(target=lambda i=i: results.append(self.correct("p1", 2, 100 + i, P1, key="race%d" % i))) for i in range(20)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(r[0] for r in results), [201] + [409] * 19)
        self.assertEqual(len(self.call("GET", "/payments/p1/revisions", who="ada")[1]["revisions"]), 3)
        total = sum(self.balance(w) for w in ("ada", "bob", "cy"))
        self.assertEqual(total, 13000)

    def test_idempotency(self):
        s1, b1, _ = self.correct("p1", 1, 400, P1, key="K")
        self.assertEqual(s1, 201)
        self.assertEqual(self.correct("p1", 2, 300, P1, key="K2")[0], 201)
        s, b, _ = self.correct("p1", 1, 400, P1, key="K")
        self.assertEqual((s, b), (200, b1))
        self.expect(409, "idempotency_key_reuse", self.correct("p1", 1, 401, P1, key="K"))
        self.expect(400, "missing_idempotency_key", self.call("POST", "/payments/p1/corrections", {}, who="ada"))
        self.expect(422, "validation_failed", self.correct("p1", 3, 1, P1, key="x" * 256))
        self.assertEqual(self.correct("p1", 3, 1, P1, key="x" * 255)[0], 201)
        # a failed key is not claimed
        self.expect(422, "validation_failed", self.correct("p1", 4, 1, P1, reason="", key="F"))
        self.assertEqual(self.correct("p1", 4, 2, P1, key="F")[0], 201)
        # per user and per path
        self.assertEqual(self.correct("p2", 1, 5, P2, who="bob", key="K")[0], 201)

    def test_originals_unchanged(self):
        p = self.pay("ada", "bob", 100, "orig")[1]
        self.assertEqual(self.correct(p["payment_id"], 1, 40, p["created_at"])[0], 201)
        s, replay, _ = self.api.call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=self.tok["ada"], key="orig")
        self.assertEqual((s, replay), (200, p))
        feed = self.call("GET", "/activity", who="cy")[1]["payments"]
        self.assertEqual([x["amount"] for x in feed if x["payment_id"] == p["payment_id"]], [100])
        self.assertEqual(len(feed), 4)   # p1, p2, p3 and the new payment: corrections add no feed items
        self.assertEqual(self.balance("ada"), 10000 - 40)

    def test_request_paid_is_correctable_linked_are_not(self):
        self.reset(seeded(settlement_operator_ids=["u_cy"]))
        rid = self.call("POST", "/requests", {"payer_handle": "ada", "amount": 50}, who="bob", key="r")[1]["request_id"]
        paid = self.call("POST", "/requests/%s/pay" % rid, {}, who="ada", key="rp")[1]
        self.assertEqual(self.correct(paid["payment_id"], 1, 20, paid["created_at"])[0], 201)
        st = self.call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]}, who="cy", key="st")[1]
        member = st["payments"][0]
        self.expect(422, "linked_payment_immutable", self.correct(member["payment_id"], 1, 5, member["created_at"], who="ada"))
        revs = self.call("GET", "/payments/%s/revisions" % member["payment_id"], who="ada")[1]["revisions"]
        self.assertEqual((revs[0]["effective_at"], revs[0]["recorded_at"]), (st["committed_at"], st["committed_at"]))
        aid = self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 30}, who="ada", key="au")[1]["authorization_id"]
        cap = self.call("POST", "/authorizations/%s/capture" % aid, {}, who="bob", key="cp")[1]
        self.expect(422, "linked_payment_immutable", self.correct(cap["payment_id"], 1, 5, cap["created_at"], who="ada"))
        self.expect(403, "forbidden", self.correct(cap["payment_id"], 1, 5, cap["created_at"], who="bob"))
        self.expect(422, "validation_failed", self.correct(cap["payment_id"], 0, 5, cap["created_at"], who="ada"))  # validation first

    def test_insufficient_funds_and_noop_on_failure(self):
        self.reset(fixture(users=[user("ada", 1000), user("bob", 50), user("cy", 0)], payments=[
            {"id": "x1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "created_at": P1}]))
        self.tok = {h: self.api.login(h + "@example.com") for h in ("ada", "bob", "cy")}
        before = self.api.call("GET", "/_test/export")[1]
        self.expect(409, "insufficient_funds", self.correct("x1", 1, 2000, P1))          # sender cannot cover +1900
        self.assertEqual(self.balance("ada"), 1000)
        self.assertEqual(self.correct("x1", 1, 1100, P1)[0], 201)                      # +1000 exactly affordable
        self.assertEqual(self.balance("ada"), 0)
        self.assertEqual(self.pay("bob", "cy", 1000, "spend")[0], 201)                       # bob is down to 50
        self.expect(409, "insufficient_funds", self.correct("x1", 2, 100, P1, key="back"))  # a decrease debits bob
        self.assertEqual(len(self.call("GET", "/payments/x1/revisions", who="ada")[1]["revisions"]), 2)
        self.assertEqual(self.balance("bob"), 50)
        self.assertEqual(before["state"]["payments"][0]["revs"], self.api.call("GET", "/_test/export")[1]["state"]["payments"][0]["revs"][:1])


class HistoricalOverdraftTests(ApiTestCase):
    def setUp(self):
        self.reset(overdraft_fixture())

    def reset(self, fx):
        self.api.reset(fx)
        self.tok = {h: self.api.login(h + "@example.com") for h in ("ada", "bob", "cy")}

    def correct(self, pid, rev, amount, eff, who, key=None, **kw):
        return self.call("POST", "/payments/%s/corrections" % pid,
                         {"expected_revision": rev, "amount": amount, "effective_at": eff, "reason": "r"},
                         who=who, key=key or "k-%s-%d-%d-%s" % (pid, rev, amount, eff))

    def revcount(self, pid, who):
        return len(self.call("GET", "/payments/%s/revisions" % pid, who=who)[1]["revisions"])

    def test_past_negative_is_rejected_and_changes_nothing(self):
        self.expect(409, "historical_overdraft", self.correct("q0", 1, 300, T0, "bob"))   # ada at T1 would be -100
        self.assertEqual((self.balance("ada"), self.balance("bob")), (1100, 1500))
        self.assertEqual(self.revcount("q0", "bob"), 1)
        self.assertEqual(self.api.call("GET", "/statement", token=self.tok["ada"])[1]["closing_balance"], 1100)
        self.assertEqual(self.correct("q0", 1, 300, T0, "bob", key="k-q0-1-300-%s" % T0)[0], 409)   # key was not claimed
        self.assertEqual(self.correct("q0", 1, 900, T0, "bob")[0], 201)
        self.assertEqual((self.balance("ada"), self.balance("bob")), (1500, 1100))

    def test_increase_before_funding_and_precedence(self):
        self.expect(409, "historical_overdraft", self.correct("q1", 1, 800, T1, "ada"))        # ada at T1: 500-800
        self.expect(409, "insufficient_funds", self.correct("q1", 1, 5000, T1, "ada"))         # current shortfall wins
        self.expect(409, "historical_overdraft", self.correct("q1", 1, 400, "2025-12-31T09:00:00+00:00", "ada"))  # before funding
        self.assertEqual(self.revcount("q1", "ada"), 1)

    def test_same_instant_movements_combine(self):
        s, b, _ = self.correct("q1", 1, 400, T0, "ada")      # -400 now lands at T0 together with +500
        self.assertEqual(s, 201)
        st = self.api.call("GET", "/statement", token=self.tok["ada"])[1]
        self.assertEqual([e["payment"]["payment_id"] for e in st["entries"]], ["q0", "q1", "q2"])
        self.assertEqual([e["balance_after"] for e in st["entries"]], [500, 100, 1100])
        self.assertEqual(self.correct("q1", 2, 500, T0, "ada")[0], 201)                       # 500-500 = 0 is not negative

    def test_hold_history_blocks_available_negative(self):
        aid = self.call("POST", "/authorizations", {"to_handle": "cy", "amount": 1000}, who="ada", key="h")[1]["authorization_id"]
        self.call("POST", "/payments", {"to_handle": "ada", "amount": 1500}, who="bob", key="more")
        self.assertEqual(self.correct("q2", 1, 0, T2, "bob")[0], 409)     # at hold start: 100 total - 1000 held < 0 (total never negative)
        self.assertEqual(self.revcount("q2", "bob"), 1)
        self.assertEqual(self.call("POST", "/authorizations/%s/void" % aid, who="ada")[0], 200)
        # history is immutable: the hold existed, so the past still overdraws even after the void
        self.assertEqual(self.correct("q2", 1, 0, T2, "bob", key="after-void")[0], 409)
        self.assertEqual(self.correct("q2", 1, 900, T2, "bob", key="ok")[0], 201)       # 100 + 900 covers the 1000 hold


class HoldHistoryTests(ApiTestCase):
    def setUp(self):
        self.api.reset(fixture())
        self.tok = {h: self.api.login(h + "@example.com") for h in ("ada", "bob", "cy")}

    @staticmethod
    def shift(text, **delta):
        return (datetime.fromisoformat(text) + timedelta(**delta)).isoformat()

    def view(self, as_of=None, known_at=None, who="ada"):
        q = []
        if as_of:
            q.append("as_of=" + enc(as_of))
        if known_at:
            q.append("known_at=" + enc(known_at))
        s, b, _ = self.api.call("GET", "/me?" + "&".join(q), token=self.tok[who])
        self.assertEqual(s, 200, b)
        return {k: b[k] for k in ("balance", "total", "available", "held")}

    def test_timeline(self):
        a = self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 2000}, who="ada", key="a")[1]
        tc = a["created_at"]
        self.assertIsNone(a["closed_at"])
        cap = self.call("POST", "/authorizations/%s/capture" % a["authorization_id"], {"amount": 700, "final": False}, who="bob", key="c")[1]
        tk = cap["created_at"]
        void = self.call("POST", "/authorizations/%s/void" % a["authorization_id"], who="ada")[1]
        tv = void["closed_at"]
        self.assertIsNotNone(tv)
        self.assertEqual(void["status"], "voided")
        self.assertEqual(self.view(self.shift(tc, microseconds=-1)), dict(balance=10000, total=10000, available=10000, held=0))
        self.assertEqual(self.view(tc), dict(balance=10000, total=10000, available=8000, held=2000))
        self.assertEqual(self.view(self.shift(tk, microseconds=-1)), dict(balance=10000, total=10000, available=8000, held=2000))
        self.assertEqual(self.view(tk), dict(balance=9300, total=9300, available=8000, held=1300))
        self.assertEqual(self.view(self.shift(tv, microseconds=-1)), dict(balance=9300, total=9300, available=8000, held=1300))
        self.assertEqual(self.view(tv), dict(balance=9300, total=9300, available=9300, held=0))
        self.assertEqual(self.view(self.shift(tv, days=2)), dict(balance=9300, total=9300, available=9300, held=0))
        # knowledge: the void is not known at tk, so the hold stays until its deadline
        self.assertEqual(self.view(tv, known_at=tk), dict(balance=9300, total=9300, available=8000, held=1300))
        self.assertEqual(self.view(self.shift(tc, seconds=700), known_at=tk), dict(balance=9300, total=9300, available=9300, held=0))
        self.assertEqual(self.view(tv, known_at=self.shift(tc, microseconds=-1)), dict(balance=10000, total=10000, available=10000, held=0))
        self.assertEqual(self.view(known_at=tc), dict(balance=10000, total=10000, available=8000, held=2000))   # as_of = now
        self.assertEqual(self.view(who="bob", as_of=tk)["balance"], 2500 + 700)
        s, b, _ = self.call("GET", "/me", who="ada")
        self.assertEqual((b["held"], b["available"], b["total"]), (0, 9300, 9300))

    def test_final_capture_expiry_and_statement(self):
        a = self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, who="ada", key="a")[1]
        cap = self.call("POST", "/authorizations/%s/capture" % a["authorization_id"], {"amount": 400}, who="bob", key="c")[1]
        closed = self.call("GET", "/authorizations", who="ada")[1]["authorizations"][0]
        self.assertEqual((closed["status"], closed["closed_at"]), ("captured", cap["created_at"]))
        self.assertEqual(self.view(cap["created_at"]), dict(balance=9600, total=9600, available=9600, held=0))
        self.assertEqual(self.view(self.shift(cap["created_at"], microseconds=-1)), dict(balance=10000, total=10000, available=9000, held=1000))
        st = self.api.call("GET", "/statement", token=self.tok["ada"])[1]
        self.assertEqual([(e["payment"]["authorization_id"], e["delta"]) for e in st["entries"]], [(a["authorization_id"], -400)])

    def test_expiry_closed_at(self):
        self.api.reset(fixture(authorization_ttl_seconds=1))
        self.tok = {h: self.api.login(h + "@example.com") for h in ("ada", "bob", "cy")}
        a = self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, who="ada", key="a")[1]
        time.sleep(1.3)
        got = self.call("GET", "/authorizations", who="ada")[1]["authorizations"][0]
        self.assertEqual((got["status"], got["closed_at"]), ("expired", a["expires_at"]))
        self.assertEqual(self.view(self.shift(a["created_at"], microseconds=500000))["held"], 1000)
        self.assertEqual(self.view(a["expires_at"])["held"], 0)

    def test_seeded_holds(self):
        soon = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(timespec="seconds")
        self.api.reset(fixture(authorizations=[
            {"id": "ao", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "status": "open", "expires_at": soon},
            {"id": "ac", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 900, "status": "captured", "expires_at": soon}]))
        self.tok = {h: self.api.login(h + "@example.com") for h in ("ada", "bob", "cy")}
        self.assertEqual(self.view("2020-01-01T00:00:00+00:00")["held"], 0)
        self.assertEqual(self.view(self.shift(datetime.now(timezone.utc).isoformat(), seconds=1))["held"], 2000)
        auths = {x["authorization_id"]: x for x in self.call("GET", "/authorizations", who="ada")[1]["authorizations"]}
        self.assertIsNone(auths["ao"]["closed_at"])
        self.assertIsNotNone(auths["ac"]["closed_at"])


class ImportAcrossStagesTests(HistoryBase):
    def strip_to_stage2(self, doc):
        doc = json.loads(json.dumps(doc))
        st = doc["state"]
        st.pop("opening", None)
        for rec in st["payments"]:
            rec.pop("revs", None)
            rec["data"].pop("authorization_id", None)
        for rec in st["authorizations"]:
            rec.pop("hold", None)
            rec["data"].pop("closed_at", None)
        return doc

    def strip_to_stage1(self, doc):
        doc = self.strip_to_stage2(doc)
        for key in ("authorizations", "authorization_ttl_seconds"):
            doc["state"].pop(key, None)
        return doc

    def test_stage1_and_stage2_exports_import(self):
        self.reset(seeded(settlement_operator_ids=["u_cy"]))
        self.pay("ada", "bob", 50, "k1")
        a = self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, who="ada", key="a")[1]["authorization_id"]
        self.call("POST", "/authorizations/%s/capture" % a, {"amount": 30}, who="bob", key="c")
        a2 = self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, who="ada", key="a2")[1]["authorization_id"]
        self.call("POST", "/authorizations/%s/void" % a2, who="ada")
        a3 = self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, who="ada", key="a3")[1]["authorization_id"]
        full = self.api.call("GET", "/_test/export")[1]
        stmt = self.stmt()[1]
        for doc in (self.strip_to_stage2(full), self.strip_to_stage1(full)):
            if "authorizations" not in doc["state"]:
                pass
            other = Api()
            try:
                self.assertEqual(other.call("POST", "/_test/import", doc)[0], 204)
                t = self.tok["ada"]
                _, got, _ = other.call("GET", "/statement", token=t)
                self.assertEqual((got["opening_balance"], got["closing_balance"]), (stmt["opening_balance"], stmt["closing_balance"]) if "authorizations" in doc["state"] else (got["opening_balance"], got["closing_balance"]))
                self.assertEqual(got["opening_balance"], 10300)
                self.assertEqual(other.call("GET", "/me?as_of=2026-01-01T00:00:00Z", token=t)[1]["balance"], 10300)
                _, revs, _ = other.call("GET", "/payments/p1/revisions", token=t)
                self.assertEqual([(r["revision"], r["amount"], r["reason"]) for r in revs["revisions"]], [(1, 500, "")])
                s, c, _ = other.call("POST", "/payments/p1/corrections", {"expected_revision": 1, "amount": 400, "effective_at": P1, "reason": "r"}, token=t, key="n")
                self.assertEqual(s, 201)
                self.assertEqual(other.call("GET", "/_test/export")[0], 200)
                if "authorizations" in doc["state"]:
                    me = other.call("GET", "/me", token=t)[1]
                    self.assertEqual((me["held"], me["available"]), (100, me["total"] - 100))
                    auths = {x["authorization_id"]: x for x in other.call("GET", "/authorizations", token=t)[1]["authorizations"]}
                    self.assertIsNone(auths[a3]["closed_at"])
                    self.assertIsNotNone(auths[a]["closed_at"])
                    self.assertIsNotNone(auths[a2]["closed_at"])
                    self.assertEqual(other.call("POST", "/payments", {"to_handle": "bob", "amount": 50}, token=t, key="k1")[0], 200)  # replay survives
            finally:
                other.close()

    def test_stage3_roundtrip(self):
        self.reset(seeded())
        self.correct("p1", 1, 300, P1, key="K")
        self.call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, who="ada", key="a")
        doc = self.api.call("GET", "/_test/export")[1]
        before = self.stmt()[1]
        other = Api()
        try:
            self.assertEqual(other.call("POST", "/_test/import", doc)[0], 204)
            self.assertEqual(other.call("POST", "/_test/import", doc)[0], 204)
            t = self.tok["ada"]
            got = other.call("GET", "/statement", token=t)[1]
            got.pop("snapshot"); before.pop("snapshot")
            self.assertEqual(got, before)
            s, b, _ = other.call("POST", "/payments/p1/corrections", {"expected_revision": 1, "amount": 300, "effective_at": P1, "reason": "fix"}, token=t, key="K")
            self.assertEqual((s, b["revision"]), (200, 2))
            self.assertEqual(other.call("POST", "/payments/p1/corrections", {"expected_revision": 2, "amount": 250, "effective_at": P1, "reason": "again"}, token=t, key="K2")[0], 201)
            self.assertEqual(other.call("GET", "/me?as_of=2025-01-01T00:00:00Z", token=t)[1]["balance"], 10300)
            bad = json.loads(json.dumps(doc))
            bad["state"]["payments"][0]["revs"] = [{"revision": 2}]
            self.assertEqual(other.call("POST", "/_test/import", bad)[0], 422)
        finally:
            other.close()
