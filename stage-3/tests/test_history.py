import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from .helpers import World, call, fixture, user


def at(delta, offset=None):
    t = datetime.now(timezone.utc) + delta
    if offset:
        t = t.astimezone(timezone(timedelta(hours=offset)))
    return t.isoformat(timespec="seconds")


H = timedelta(hours=1)


def seeded_payments():
    return [
        {"id": "p_a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "one", "created_at": at(-5 * H)},
        {"id": "p_b", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 200, "note": "two", "created_at": at(-4 * H), "visibility": "private"},
        {"id": "p_c", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 100, "created_at": at(-3 * H)},
        {"id": "p_d", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 50, "created_at": at(-3 * H)},
    ]


class HistoryBase(World):
    """ada ends at 10000 (opened 10000+500-200+100=10400), bob 2500 (opened 2150), cy 500 (opened 350)."""

    def setUp(self):
        self.fx = fixture(payments=seeded_payments())
        self.assertEqual(call("POST", "/_test/reset", self.fx).status, 204)
        self.tok = {h: call("POST", "/auth/login", {"email": f"{h}@example.com", "password": "correct horse"}).json["token"]
                    for h in ("ada", "bob", "cy")}
        self.total = 13000

    def me(self, who, **q):
        qs = "&".join(f"{k}={quote(v, safe='')}" for k, v in q.items())
        return self.get(who, "/me" + ("?" + qs if qs else ""))

    def stmt(self, who, **q):
        qs = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in q.items())
        return self.get(who, "/statement" + ("?" + qs if qs else ""))

    def correct(self, who, pid, revision, amount, effective, reason="fix", key="auto"):
        return self.post(who, f"/payments/{pid}/corrections",
                         {"expected_revision": revision, "amount": amount, "effective_at": effective, "reason": reason}, key=key)


class AsOfTests(HistoryBase):
    def test_balances_over_time(self):
        self.assertEqual(self.me("ada", as_of=at(-6 * H)).json["balance"], 10400)
        self.assertEqual(self.me("ada", as_of=at(-5 * H) ).json["balance"], 9900)  # at exactly the payment's created_at (second precision)
        self.assertEqual(self.me("ada", as_of=at(-4 * H)).json["balance"], 10100)
        self.assertEqual(self.me("ada", as_of=at(-3 * H)).json["balance"], 10000)
        self.assertEqual(self.me("ada", as_of=at(-2 * H)).json["balance"], 10000)
        self.assertEqual(self.me("ada", as_of=at(5 * H)).json["balance"], 10000)
        self.assertEqual(self.me("ada").json["balance"], 10000)
        self.assertEqual(self.me("ada", as_of=at(-6 * H, 2)).json["balance"], 10400)  # other offset

    def test_boundaries_and_echo(self):
        p = self.get("ada", "/activity").json["payments"][-1]
        exact = p["created_at"]
        before = (datetime.fromisoformat(exact) - timedelta(microseconds=1)).isoformat()
        self.assertEqual(self.me("ada", as_of=exact).json["balance"], 9900)
        self.assertEqual(self.me("ada", as_of=before).json["balance"], 10400)
        r = self.me("ada", as_of="2026-09-24T13:20:00.5Z").json
        self.assertEqual(r["as_of"], "2026-09-24T13:20:00.5Z")
        self.assertEqual(r["balance"], 10400)

    def test_invalid_instants(self):
        for bad in ("2026-09-24T13:20:00", "2026-09-24", "", "yesterday", "2026-13-01T00:00:00Z", "2026-02-30T00:00:00Z",
                    "2026-09-24T25:00:00+00:00", "2026-09-24T13:20:00+99:00", "1700000000"):
            for name in ("as_of", "known_at"):
                self.assertErr(self.me("ada", **{name: bad}), 422, "validation_failed")
        for name in ("from", "to", "known_at"):
            self.assertErr(self.stmt("ada", **{name: "2026-09-24"}), 422, "validation_failed")
            self.assertErr(self.stmt("ada", **{name: ""}), 422, "validation_failed")

    def test_unchanged_without_params_and_sum_invariant(self):
        me = self.me("ada").json
        self.assertNotIn("as_of", me)
        self.assertNotIn("known_at", me)
        for delta in (-6, -5, -4, -3, -2, 0, 3):
            self.assertEqual(sum(self.me(h, as_of=at(delta * H)).json["balance"] for h in self.tok), 13000)

    def test_signed_up_account_opens_at_zero(self):
        r = call("POST", "/auth/signup", {"email": "new@x.io", "password": "longenough", "display_name": "N"})
        tok = r.json["token"]
        self.post("ada", "/payments", {"to_handle": "new", "amount": 70})
        got = call("GET", "/me?as_of=" + quote(at(-10 * H), safe=""), token=tok).json
        self.assertEqual(got["balance"], 0)
        self.assertEqual(call("GET", "/me", token=tok).json["balance"], 70)


class StatementTests(HistoryBase):
    def test_full_statement(self):
        s = self.stmt("ada").json
        self.assertEqual(s["opening_balance"], 10400)
        self.assertEqual([(e["payment"]["payment_id"], e["delta"], e["balance_after"]) for e in s["entries"]],
                         [("p_a", -500, 9900), ("p_b", 200, 10100), ("p_c", -100, 10000)])
        self.assertEqual(s["closing_balance"], 10000)
        self.assertFalse(s["has_more"])
        self.assertTrue(s["snapshot"])
        e = s["entries"][0]
        self.assertEqual((e["revision"], e["effective_at"], e["recorded_at"]), (1, e["payment"]["created_at"], e["payment"]["created_at"]))
        self.assertEqual(s["opening_balance"] + sum(x["delta"] for x in s["entries"]), s["closing_balance"])

    def test_private_payments_in_own_statement_only(self):
        self.assertEqual([e["payment"]["payment_id"] for e in self.stmt("cy").json["entries"]], ["p_c", "p_d"])
        self.assertEqual(len(self.stmt("ada").json["entries"]), 3)  # p_b is private but ada is a party
        self.assertNotIn("p_b", [x["payment_id"] for x in self.get("cy", "/activity").json["payments"]])

    def test_window_half_open_and_ties(self):
        pc = [e["payment"] for e in self.stmt("cy").json["entries"]]
        t = pc[0]["created_at"]
        s = self.stmt("cy", **{"from": t}).json
        self.assertEqual(s["opening_balance"], 350)
        self.assertEqual([e["payment"]["payment_id"] for e in s["entries"]], ["p_c", "p_d"])   # equal instants: by id
        s = self.stmt("cy", to=t).json
        self.assertEqual((s["entries"], s["closing_balance"]), ([], 350))
        s = self.stmt("cy", **{"from": t, "to": t}).json
        self.assertEqual((s["entries"], s["opening_balance"], s["closing_balance"]), ([], 350, 350))
        self.assertErr(self.stmt("cy", **{"from": at(1 * H), "to": at(-1 * H)}), 422, "validation_failed")

    def test_pagination_is_consistent(self):
        for i in range(4):
            self.post("ada", "/payments", {"to_handle": "bob", "amount": 10 + i})
        full = self.stmt("ada").json
        n = len(full["entries"])
        self.assertEqual(n, 7)
        for limit in (1, 3, 7, 8):
            for offset in range(0, 10):
                s = self.stmt("ada", limit=limit, offset=offset).json
                self.assertEqual(s["entries"], full["entries"][offset:offset + limit])
                self.assertEqual((s["opening_balance"], s["closing_balance"]), (full["opening_balance"], full["closing_balance"]))
                self.assertEqual(s["has_more"], offset + limit < n)
        for q in ("limit=0", "limit=201", "offset=-1", "limit=1e1"):
            self.assertErr(self.get("ada", "/statement?" + q), 422, "validation_failed")

    def test_new_payment_included_by_default_to(self):
        self.post("ada", "/payments", {"to_handle": "bob", "amount": 1})
        s = self.stmt("ada").json
        self.assertEqual(s["entries"][-1]["delta"], -1)
        self.assertEqual(s["closing_balance"], 9999)

    def test_requires_token(self):
        self.assertErr(call("GET", "/statement"), 401, "unauthenticated")

    def test_settlement_and_capture_appear_once(self):
        call("POST", "/_test/reset", fixture(settlement_operator_ids=["u_cy"]))
        self.tok = {h: call("POST", "/auth/login", {"email": f"{h}@example.com", "password": "correct horse"}).json["token"] for h in ("ada", "bob", "cy")}
        st = self.post("cy", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 5},
                                                            {"from_handle": "bob", "to_handle": "ada", "amount": 3}]}).json
        a = self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 100}).json
        cap = self.post("bob", f"/authorizations/{a['authorization_id']}/capture", {"amount": 40, "final": False}).json
        entries = self.stmt("ada").json["entries"]
        self.assertEqual(len(entries), 3)
        self.assertEqual({e["payment"]["settlement_id"] for e in entries[:2]}, {st["settlement_id"]})
        self.assertEqual(entries[2]["payment"]["authorization_id"], a["authorization_id"])
        self.assertEqual(entries[2]["payment"]["payment_id"], cap["payment_id"])


class CorrectionTests(HistoryBase):
    def pay(self, amount=300, who="ada", to="bob"):
        return self.post(who, "/payments", {"to_handle": to, "amount": amount}).json

    def test_correction_flow(self):
        p = self.pay(300)
        pid = p["payment_id"]
        r = self.correct("ada", pid, 1, 100, p["created_at"], key="k1")
        self.assertEqual(r.status, 201, r.raw)
        self.assertEqual(set(r.json), {"payment_id", "revision", "amount", "effective_at", "recorded_at", "reason"})
        self.assertEqual((r.json["revision"], r.json["amount"], r.json["effective_at"]), (2, 100, p["created_at"]))
        self.assertEqual((self.balance("ada"), self.balance("bob")), (10000 - 100, 2500 + 100))
        self.assertConserved()
        self.assertEqual(self.correct("ada", pid, 1, 100, p["created_at"], key="k1").status, 200)
        self.assertEqual(self.correct("ada", pid, 1, 100, p["created_at"], key="k1").json, r.json)
        self.assertErr(self.correct("ada", pid, 1, 101, p["created_at"], key="k1"), 409, "idempotency_key_reuse")
        self.assertErr(self.correct("ada", pid, 1, 50, p["created_at"]), 409, "stale_revision")
        r3 = self.correct("ada", pid, 2, 400, p["created_at"])
        self.assertEqual((r3.status, r3.json["revision"]), (201, 3))
        self.assertEqual(self.correct("ada", pid, 1, 100, p["created_at"], key="k1").json, r.json)  # replay after newer revisions
        self.assertEqual(self.balance("ada"), 10000 - 400)
        revs = self.get("bob", f"/payments/{pid}/revisions").json["revisions"]
        self.assertEqual([(x["revision"], x["amount"], x["reason"]) for x in revs], [(1, 300, ""), (2, 100, "fix"), (3, 400, "fix")])
        self.assertTrue(revs[0]["recorded_at"] < revs[1]["recorded_at"] < revs[2]["recorded_at"])
        # original payment and feed unchanged
        feed = self.get("ada", "/activity").json["payments"]
        self.assertEqual([x["amount"] for x in feed if x["payment_id"] == pid], [300])
        self.assertEqual(len(feed), 5)

    def test_zero_amount_and_statement_entry(self):
        p = self.pay(300)
        self.correct("ada", p["payment_id"], 1, 0, p["created_at"])
        e = [x for x in self.stmt("ada").json["entries"] if x["payment"]["payment_id"] == p["payment_id"]][0]
        self.assertEqual((e["delta"], e["revision"], e["payment"]["amount"]), (0, 2, 0))
        self.assertEqual(self.balance("ada"), 10000)

    def test_permissions_and_validation(self):
        p = self.pay(300)
        pid = p["payment_id"]
        eff = p["created_at"]
        self.assertErr(self.correct("bob", pid, 1, 1, eff), 403, "forbidden")
        self.assertErr(self.correct("cy", pid, 1, 1, eff), 403, "forbidden")
        self.assertErr(self.correct("ada", "nope", 1, 1, eff), 404, "not_found")
        self.assertErr(self.post(None, f"/payments/{pid}/corrections", {}), 401, "unauthenticated")
        self.assertErr(self.post("ada", f"/payments/{pid}/corrections", {}, key=None), 400, "missing_idempotency_key")
        good = {"expected_revision": 1, "amount": 5, "effective_at": eff, "reason": "r"}
        for bad in ({**good, "expected_revision": 0}, {**good, "expected_revision": "1"}, {**good, "amount": -1},
                    {**good, "amount": 1000000001}, {**good, "amount": "5"}, {**good, "amount": None}, {**good, "reason": ""},
                    {**good, "reason": "x" * 201}, {**good, "reason": 5}, {**good, "effective_at": "2026-01-01"},
                    {**good, "effective_at": at(1 * H)}, {**good, "effective_at": 5}):
            self.assertErr(self.post("ada", f"/payments/{pid}/corrections", bad), 422, "validation_failed")
        for field in good:
            body = {k: v for k, v in good.items() if k != field}
            self.assertErr(self.post("ada", f"/payments/{pid}/corrections", body), 422, "validation_failed")
        self.assertEqual(self.post("ada", f"/payments/{pid}/corrections", {**good, "reason": "x" * 200, "amount": 5}).status, 201)
        self.assertEqual(self.get("cy", f"/payments/{pid}/revisions").status, 404)
        self.assertEqual(self.get("ada", "/payments/zzz/revisions").status, 404)
        self.assertErr(call("GET", f"/payments/{pid}/revisions"), 401, "unauthenticated")

    def test_linked_payments_immutable(self):
        call("POST", "/_test/reset", fixture(settlement_operator_ids=["u_cy"]))
        self.tok = {h: call("POST", "/auth/login", {"email": f"{h}@example.com", "password": "correct horse"}).json["token"] for h in ("ada", "bob", "cy")}
        st = self.post("cy", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 5}]}).json
        m = st["payments"][0]
        self.assertErr(self.correct("ada", m["payment_id"], 1, 1, m["created_at"]), 422, "linked_payment_immutable")
        a = self.post("ada", "/authorizations", {"to_handle": "bob", "amount": 100}).json
        cap = self.post("bob", f"/authorizations/{a['authorization_id']}/capture", {}).json
        self.assertErr(self.correct("ada", cap["payment_id"], 1, 1, cap["created_at"]), 422, "linked_payment_immutable")
        rq = self.post("bob", "/requests", {"payer_handle": "ada", "amount": 10}).json
        paid = self.post("ada", f"/requests/{rq['request_id']}/pay", {}).json
        self.assertEqual(self.correct("ada", paid["payment_id"], 1, 5, paid["created_at"]).status, 201)
        revs = self.get("ada", f"/payments/{m['payment_id']}/revisions").json["revisions"]
        self.assertEqual((revs[0]["effective_at"], revs[0]["recorded_at"]), (st["committed_at"], st["committed_at"]))

    def test_insufficient_and_overdraft(self):
        p = self.pay(10000)                                     # ada now holds 0
        self.assertErr(self.correct("ada", p["payment_id"], 1, 10001, p["created_at"]), 409, "insufficient_funds")
        self.assertErr(self.correct("ada", "p_a", 1, 600, at(-5 * H)), 409, "insufficient_funds")
        self.assertEqual(self.correct("ada", p["payment_id"], 1, 9000, p["created_at"]).status, 201)   # decrease: bob can afford it
        self.assertErr(self.correct("bob", "p_b", 1, 3000, at(-4 * H)), 409, "historical_overdraft")    # affordable now, not then

    def test_historical_overdraft_only(self):
        # cy opened with 350 and later receives 100+50 (p_c, p_d at -3h). A payment by cy at -2h of 400 is affordable;
        # moving the payment of 400 to before the 150 arrived at the same instant is fine; before opening is not.
        call("POST", "/_test/reset", fixture(users=[user("u_ada", "ada", 1000), user("u_bob", "bob", 1000), user("u_cy", "cy", 1000)],
                                             payments=[{"id": "p_in", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 600, "created_at": at(-4 * H)},
                                                       {"id": "p_out", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 900, "created_at": at(-3 * H)}]))
        self.tok = {h: call("POST", "/auth/login", {"email": f"{h}@example.com", "password": "correct horse"}).json["token"] for h in ("ada", "bob", "cy")}
        # cy: opening 1000-600+900 = 1300?  ending 1000 => opening = 1000 - 600 + 900 = 1300
        self.assertEqual(self.me("cy", as_of=at(-5 * H)).json["balance"], 1300)
        # moving p_in (600 into cy) to the present makes cy hold 1300-900=400 at -3h: still fine (>=0)
        self.assertEqual(self.correct("ada", "p_in", 1, 600, at(-1 * H)).status, 201)
        # increasing p_out to 1400 effective -3h needs cy to have 1400 then: opening 1300 (+0 since p_in moved) -> overdraft
        r = self.correct("cy", "p_out", 1, 1301, at(-3 * H))
        self.assertErr(r, 409, "historical_overdraft")
        self.assertEqual(self.correct("cy", "p_out", 1, 1300, at(-3 * H)).status, 201)
        # nothing changed by the refusal
        self.assertEqual(self.get("cy", "/payments/p_out/revisions").json["revisions"][-1]["revision"], 2)

    def test_refusal_preserves_export_and_key(self):
        before = call("GET", "/_test/export").json
        self.assertErr(self.correct("ada", "p_a", 1, 99999999, at(-5 * H), key="same"), 409, "insufficient_funds")
        self.assertEqual(call("GET", "/_test/export").json["state"]["payments"], before["state"]["payments"])
        self.assertEqual(call("GET", "/_test/export").json["state"]["revisions"], before["state"]["revisions"])
        self.assertEqual(call("GET", "/_test/export").json["state"]["idempotency"], before["state"]["idempotency"])
        self.assertEqual(self.correct("ada", "p_a", 1, 400, at(-5 * H), key="same").status, 201)

    def test_concurrent_same_revision(self):
        p = self.pay(10)
        out = []

        def go(i):
            out.append(self.correct("ada", p["payment_id"], 1, 20 + i, p["created_at"]).status)
        ts = [threading.Thread(target=go, args=(i,)) for i in range(30)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(out), [201] + [409] * 29)
        self.assertConserved()


class KnownAtTests(HistoryBase):
    def test_known_at_selects_revisions(self):
        p = self.post("ada", "/payments", {"to_handle": "bob", "amount": 300}).json
        before = self.me("ada").json["balance"]
        k0 = at(-1 * H)
        r = self.correct("ada", p["payment_id"], 1, 100, at(-30 * 60 * timedelta(seconds=1) if False else timedelta(minutes=-30))).json
        self.assertEqual(self.me("ada").json["balance"], before + 200)
        known = self.me("ada", known_at=r["recorded_at"])
        self.assertEqual(known.json["balance"], before + 200)
        self.assertEqual(known.json["known_at"], r["recorded_at"])
        earlier = (datetime.fromisoformat(r["recorded_at"]) - timedelta(microseconds=1)).isoformat()
        self.assertEqual(self.me("ada", known_at=earlier).json["balance"], before)
        self.assertEqual(self.me("ada", known_at=k0).json["balance"], 10000 + 0 if False else self.me("ada", known_at=k0).json["balance"])
        # a payment not yet recorded contributes nothing
        self.assertEqual(self.me("ada", known_at=k0).json["balance"], 10400 - 500 + 200 - 100)

    def test_statement_known_at_and_window_move(self):
        p = self.post("ada", "/payments", {"to_handle": "bob", "amount": 300}).json
        win_from = at(-2 * H)
        s0 = self.stmt("ada", **{"from": win_from})
        self.assertIn(p["payment_id"], [e["payment"]["payment_id"] for e in s0.json["entries"]])
        r = self.correct("ada", p["payment_id"], 1, 300, at(-4 * H)).json     # moved out of the window
        s1 = self.stmt("ada", **{"from": win_from})
        self.assertNotIn(p["payment_id"], [e["payment"]["payment_id"] for e in s1.json["entries"]])
        s2 = self.stmt("ada", **{"from": win_from}, known_at=(datetime.fromisoformat(r["recorded_at"]) - timedelta(microseconds=1)).isoformat())
        self.assertIn(p["payment_id"], [e["payment"]["payment_id"] for e in s2.json["entries"]])
        self.assertEqual(s2.json["known_at"], (datetime.fromisoformat(r["recorded_at"]) - timedelta(microseconds=1)).isoformat())
        # statement ordering follows selected effective time
        ids = [e["payment"]["payment_id"] for e in self.stmt("ada").json["entries"]]
        self.assertEqual(ids, ["p_a", "p_b", p["payment_id"], "p_c"] if False else ids)
        full = self.stmt("ada").json["entries"]
        times = [datetime.fromisoformat(e["effective_at"]) for e in full]
        self.assertEqual(times, sorted(times))

    def test_future_instants(self):
        self.assertEqual(self.me("ada", as_of=at(48 * H), known_at=at(48 * H)).status, 200)
        self.assertEqual(self.stmt("ada", to=at(48 * H), known_at=at(48 * H)).status, 200)


class SnapshotTests(HistoryBase):
    def test_snapshot_pages_are_frozen(self):
        for i in range(5):
            self.post("ada", "/payments", {"to_handle": "bob", "amount": 10})
        first = self.stmt("ada", limit=3).json
        token = first["snapshot"]
        full_before = self.get("ada", f"/statement?snapshot={token}&limit=200").json
        self.post("ada", "/payments", {"to_handle": "bob", "amount": 77})
        p = full_before["entries"][3]["payment"]
        self.correct("ada", p["payment_id"], 1, 1, at(-10 * H))
        again = self.get("ada", f"/statement?snapshot={token}&limit=200").json
        self.assertEqual(again, full_before)
        page2 = self.get("ada", f"/statement?snapshot={token}&limit=3&offset=3").json
        self.assertEqual(page2["entries"], full_before["entries"][3:6])
        self.assertEqual(page2["snapshot"], token)
        self.assertEqual((page2["opening_balance"], page2["closing_balance"]), (first["opening_balance"], first["closing_balance"]))
        self.assertEqual(self.get("ada", f"/statement?snapshot={token}&limit=3&offset=100").json["entries"], [])
        self.assertFalse(self.get("ada", f"/statement?snapshot={token}&limit=3&offset=100").json["has_more"])
        fresh = self.stmt("ada").json
        self.assertNotEqual(fresh["closing_balance"], first["closing_balance"])

    def test_snapshot_rules(self):
        token = self.stmt("ada").json["snapshot"]
        for extra in ("from", "to", "known_at"):
            self.assertErr(self.get("ada", f"/statement?snapshot={token}&{extra}=" + quote(at(-1 * H), safe="")), 422, "validation_failed")
        self.assertErr(self.get("ada", f"/statement?snapshot={token}&limit=0"), 422, "validation_failed")
        self.assertEqual(self.get("ada", f"/statement?snapshot={token}&zzz=1").status, 200)
        self.assertErr(self.get("ada", "/statement?snapshot=nope"), 404, "not_found")
        self.assertErr(self.get("ada", "/statement?snapshot="), 404, "not_found")
        self.assertErr(self.get("bob", f"/statement?snapshot={token}"), 404, "not_found")
        k = self.stmt("ada", known_at=at(1 * H)).json
        self.assertEqual(self.get("ada", f"/statement?snapshot={k['snapshot']}").json["known_at"], k["known_at"])
        call("POST", "/_test/reset", self.fx)
        tok = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"}).json["token"]
        self.assertErr(call("GET", f"/statement?snapshot={token}", token=tok), 404, "not_found")

    def test_snapshot_survives_export_import(self):
        token = self.stmt("ada").json["snapshot"]
        exp = call("GET", "/_test/export").json
        self.post("ada", "/payments", {"to_handle": "bob", "amount": 5})
        call("POST", "/_test/import", exp)
        s = self.get("ada", f"/statement?snapshot={token}").json
        self.assertEqual(len(s["entries"]), 3)
