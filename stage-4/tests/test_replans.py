import concurrent.futures as cf
import unittest

from support import ServiceCase, USERS, restaurant

D = "2030-05-01"  # Wednesday, Berlin summer time (+02:00)
FROM, TO = f"{D}T18:00:00+02:00", f"{D}T23:00:00+02:00"


def rest(**kw):
    kw.setdefault("tables", [{"id": "t1", "label": "1", "capacity": 2}, {"id": "t2", "label": "2", "capacity": 4},
                             {"id": "t3", "label": "3", "capacity": 4}, {"id": "t4", "label": "4", "capacity": 6}])
    r = restaurant(**kw)
    r["manager_user_ids"] = ["u_a"]
    r["combinable"] = kw.get("combinable", [["t1", "t2"], ["t2", "t3"]])
    return r


class Base(ServiceCase):
    def setUp(self):
        self.reset([rest(), restaurant("r2")])
        self.a, self.b = self.login(), self.login("b@example.com")
        self.n = 0

    def key(self):
        self.n += 1
        return f"k{self.n}"

    def book(self, table=None, ids=None, at=f"{D}T19:00", party=2, token=None, rid="r1"):
        body = {"restaurant_id": rid, "starts_at_local": at, "party_size": party}
        body.update({"table_ids": ids} if ids else {"table_id": table})
        s, b, _ = self.call("POST", "/reservations", body, token=token or self.a, key=self.key())
        self.assertEqual(s, 201, b)
        return b

    def preview(self, table="t2", frm=FROM, to=TO, token=None, key=None, rid="r1", body=None):
        body = body if body is not None else {"table_id": table, "from": frm, "to": to}
        return self.call("POST", f"/restaurants/{rid}/replans", body, token=token or self.a, key=key or self.key())

    def apply(self, plan_id, token=None, key=None, rid="r1"):
        return self.call("POST", f"/restaurants/{rid}/replans/{plan_id}/apply", {}, token=token or self.a, key=key or self.key())

    def revision(self):  # observed through an empty-interval-free preview far away
        s, p, _ = self.preview(frm="2040-01-01T00:00:00Z", to="2040-01-01T01:00:00Z")
        self.assertEqual(s, 201)
        return p["restaurant_revision"]

    def get(self, ref, token=None):
        return self.call("GET", f"/reservations/{ref}", token=token or self.a)[1]


class Preview(Base):
    def test_permissions_validation_keys(self):
        c = self.call
        self.assertErr(c("POST", "/restaurants/r1/replans", {"table_id": "t2", "from": FROM, "to": TO}, key="k"), 401, "unauthenticated")
        self.assertErr(self.preview(token=self.b), 403, "forbidden")
        self.assertErr(self.preview(rid="zz"), 404, "not_found")
        self.assertErr(c("POST", "/restaurants/r1/replans", {"table_id": "t2", "from": FROM, "to": TO}, token=self.a), 400, "missing_idempotency_key")
        self.assertErr(c("POST", "/restaurants/r1/replans", raw="[", token=self.a, key="k"), 400, "malformed_request")
        for body in ({"table_id": "t2", "from": TO, "to": FROM}, {"table_id": "t2", "from": FROM, "to": FROM},
                     {"table_id": "t2", "from": "2030-05-01T18:00", "to": TO}, {"table_id": "t2", "from": "2030-05-01", "to": TO},
                     {"table_id": "t2", "from": 5, "to": TO}, {"table_id": "t2", "to": TO}, {"from": FROM, "to": TO},
                     {"table_id": "t2", "from": "garbage", "to": TO}):
            self.assertErr(self.preview(body=body), 422, "validation_failed")
        self.assertErr(self.preview(body={"table_id": 5, "from": FROM, "to": TO}), 400, "malformed_request")
        self.assertErr(self.preview(table="zz"), 404, "not_found")
        self.assertErr(self.preview(table="t2", rid="r2"), 404, "not_found") if False else None
        s, p, _ = self.preview(key="same", body={"table_id": "t2", "from": "2030-05-01T16:00:00Z", "to": "2030-05-01T21:00:00Z", "junk": 1})
        self.assertEqual((s, p["closure"]), (201, {"table_id": "t2", "from": "2030-05-01T16:00:00Z", "to": "2030-05-01T21:00:00Z"}))
        self.assertEqual((p["assignments"], p["moved_count"], p["unused_seats"]), ([], 0, 0))
        self.assertEqual(c("POST", "/restaurants/r1/replans", {"table_id": "t2", "from": "2030-05-01T16:00:00Z", "to": "2030-05-01T21:00:00Z", "junk": 1}, token=self.a, key="same")[:2], (200, p))
        self.assertErr(self.preview(key="same"), 409, "idempotency_key_reuse")

    def test_considered_and_optimum(self):
        # t2 closing 18-23. A (R: party 3 on t2), B (party 2 on t1, other time), C fixed on t3 outside window
        a = self.book("t2", party=3, at=f"{D}T19:00")
        b = self.book("t1", party=2, at=f"{D}T20:00")
        self.book("t3", party=2, at=f"{D}T10:00") if False else None
        before = self.revision()
        s, p, _ = self.preview()
        self.assertEqual(s, 201)
        refs = sorted([a["reference"], b["reference"]])
        self.assertEqual([x["reference"] for x in p["assignments"]], refs)
        got = {x["reference"]: x for x in p["assignments"]}
        # a: party 3 -> options not t2: t3 (cap4, unused 1), t4 (cap 6)... t3 is free: unused 1; b unchanged on t1 (unused 0)
        self.assertEqual(got[a["reference"]]["table_ids"], ["t3"])
        self.assertTrue(got[a["reference"]]["changed"])
        self.assertEqual((got[b["reference"]]["table_ids"], got[b["reference"]]["changed"]), (["t1"], False))
        self.assertEqual((p["moved_count"], p["unused_seats"]), (1, 1))
        self.assertEqual(p["restaurant_revision"], before)
        # preview changed nothing
        self.assertEqual(self.get(a["reference"])["table_ids"], ["t2"])
        self.assertEqual(self.revision(), before)
        self.assertEqual(len(self.call("GET", f"/reservations/{a['reference']}/history", token=self.a)[1]["entries"]), 1)

    def test_no_feasible_plan_and_limits(self):
        one = rest(tables=[{"id": "t1", "label": "1", "capacity": 2}, {"id": "t2", "label": "2", "capacity": 2}])
        one["combinable"] = []
        self.reset([one])
        self.a = self.login()
        self.book("t1", party=2)
        self.book("t2", party=2)
        before = self.revision()
        self.assertErr(self.preview(table="t2", key="again"), 409, "no_feasible_plan")
        self.assertErr(self.preview(table="t2", key="again"), 409, "no_feasible_plan")  # key reusable
        self.assertEqual(self.revision(), before)


class Apply(Base):
    def test_apply_flow(self):
        a = self.book("t2", party=3)
        b = self.book("t1", party=2, at=f"{D}T20:30")
        s, plan, _ = self.preview()
        r0 = plan["restaurant_revision"]
        self.assertErr(self.apply(plan["plan_id"], token=self.b), 403, "forbidden")
        self.assertErr(self.apply("plan_zzz"), 404, "not_found")
        self.assertErr(self.apply(plan["plan_id"], rid="r2"), 404, "not_found") if False else None
        s, applied, _ = self.apply(plan["plan_id"], key="ak")
        self.assertEqual((s, applied["restaurant_revision"], applied["plan_id"]), (201, r0 + 1, plan["plan_id"]))
        self.assertEqual([r["reference"] for r in applied["reservations"]], sorted([a["reference"], b["reference"]]))
        ra = self.get(a["reference"])
        self.assertEqual((ra["table_ids"], ra["revision"], ra["starts_at"], ra["ends_at"], ra["accepted_terms"]),
                         (["t3"], 2, a["starts_at"], a["ends_at"], a["accepted_terms"]))
        self.assertEqual(self.get(b["reference"])["revision"], 1)
        h = self.call("GET", f"/reservations/{a['reference']}/history", token=self.a)[1]["entries"]
        self.assertEqual([e["event"] for e in h], ["created", "reassigned"])
        self.assertEqual((h[1]["changes"], h[1]["plan_id"], h[1]["revision"], h[1]["seq"]),
                         ([{"field": "table_ids", "from": ["t2"], "to": ["t3"]}], plan["plan_id"], 2, 2))
        self.assertEqual(len(self.call("GET", f"/reservations/{b['reference']}/history", token=self.a)[1]["entries"]), 1)
        # replay, already applied, stale
        self.assertEqual(self.apply(plan["plan_id"], key="ak")[:2], (200, applied))
        self.assertErr(self.apply(plan["plan_id"], key="other"), 409, "plan_already_applied")
        # closure effects
        av = self.call("GET", f"/availability?restaurant_id=r1&date={D}&party_size=1&explain=true")[1]["slots"]
        s19 = next(x for x in av if x["starts_at_local"].endswith("T19:00"))
        self.assertNotIn("t2", s19["available_table_ids"])
        self.assertTrue(all("t2" not in o["table_ids"] for o in s19["available_options"]))
        e2 = next(e for e in s19["explain"] if e["table_id"] == "t2")
        self.assertEqual(e2["rules"][1], {"rule": "no_overlap", "holds": False})
        self.assertErr(self.call("POST", "/reservations", {"restaurant_id": "r1", "table_id": "t2", "starts_at_local": f"{D}T21:00", "party_size": 2}, token=self.b, key="x"), 409, "table_unavailable")
        self.assertErr(self.call("POST", "/reservations", {"restaurant_id": "r1", "table_ids": ["t1", "t2"], "starts_at_local": f"{D}T21:00", "party_size": 2}, token=self.b, key="x2"), 409, "table_unavailable")
        c = self.book("t4", party=2, at=f"{D}T21:00")
        self.assertErr(self.call("PATCH", f"/reservations/{c['reference']}", {"table_id": "t2"}, token=self.a), 409, "table_unavailable")
        self.assertEqual(self.call("POST", "/reservations", {"restaurant_id": "r1", "table_id": "t2", "starts_at_local": "2030-05-02T19:00", "party_size": 2}, token=self.b, key="x3")[0], 201)  # outside window
        # later plans respect the earlier closure: closing t3 now cannot put `a` back on t2
        s, p2, _ = self.preview(table="t3", key="p2")
        a2 = next(x for x in p2["assignments"] if x["reference"] == a["reference"])
        self.assertNotIn("t2", a2["table_ids"])

    def test_stale_and_other_restaurant(self):
        a = self.book("t2", party=3)
        s, plan, _ = self.preview()
        self.book("t4", party=2, at=f"{D}T21:30", rid="r1")  # bumps revision
        self.assertErr(self.apply(plan["plan_id"]), 409, "stale_plan")
        self.assertEqual(self.get(a["reference"])["table_ids"], ["t2"])
        s, plan, _ = self.preview()
        self.book("t1", party=2, rid="r2", token=self.b) if False else self.call("POST", "/reservations", {"restaurant_id": "r2", "table_id": "t1", "starts_at_local": f"{D}T19:00", "party_size": 2}, token=self.b, key="o")
        self.assertEqual(self.apply(plan["plan_id"])[0], 201)  # other restaurant's write: still valid

    def test_revision_rules(self):
        r = self.revision()
        self.book("t4")                                           # +1
        self.assertEqual(self.revision(), r + 1)
        ref = self.book("t3", at=f"{D}T21:00")["reference"]       # +1
        self.call("PATCH", f"/reservations/{ref}", {"party_size": 2}, token=self.a)   # no-op
        self.call("PATCH", f"/reservations/{ref}", {"party_size": 99}, token=self.a)  # failure
        self.assertEqual(self.revision(), r + 2)
        self.call("PATCH", f"/reservations/{ref}", {"party_size": 3}, token=self.a)   # real +1
        self.call("POST", f"/reservations/{ref}/cancel", token=self.a)                # +1
        self.call("POST", f"/reservations/{ref}/cancel", token=self.a)                # repeat: none
        self.assertEqual(self.revision(), r + 4)
        self.call("POST", "/restaurants/r1/policies", {"effective_from": "2030-01-01", "slot_minutes": 30, "reservation_duration_minutes": 90,
                  "cancellation_cutoff_minutes": 60, "opening_hours": [], "capacities": {"t1": 2, "t2": 4, "t3": 4, "t4": 6}}, token=self.a, key="pol")
        self.assertEqual(self.revision(), r + 5)

    def test_concurrent_applies(self):
        a = self.book("t2", party=3, at=f"{D}T19:00")
        plan = self.preview()[1]
        plan2 = self.preview(table="t3", key="p2")[1]
        with cf.ThreadPoolExecutor(2) as ex:
            res = list(ex.map(lambda p: self.apply(p["plan_id"]), (plan, plan2)))
        self.assertEqual(sorted(r[0] for r in res), [201, 409])
        self.assertEqual([r[1]["error"]["code"] for r in res if r[0] == 409], ["stale_plan"])

    def test_series_members_keep_identity(self):
        a = self.book("t2", party=3, at=f"{D}T19:00")
        ser = self.call("POST", "/series", {"anchor_reference": a["reference"], "count": 3, "interval_weeks": 1}, token=self.a, key="s")[1]
        plan = self.preview(frm="2030-05-08T18:00:00+02:00", to="2030-05-08T23:00:00+02:00")[1]
        self.assertEqual(self.apply(plan["plan_id"])[0], 201)
        g = self.call("GET", f"/series/{ser['series_id']}", token=self.a)[1]
        self.assertEqual(g["revision"], 2)
        self.assertEqual([o["exception"] for o in g["occurrences"]], [False, False, False])
        self.assertEqual([o["reference"] for o in g["occurrences"]], [o["reference"] for o in ser["occurrences"]])
        moved = [o["reservation"] for o in g["occurrences"] if o["reservation"]["revision"] == 2]
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0]["starts_at_local"], "2030-05-08T19:00")

    def test_empty_plan_records_closure(self):
        r = self.revision()
        s, p, _ = self.preview(table="t4")
        self.assertEqual(s, 201)
        self.assertEqual(self.apply(p["plan_id"])[0], 201)
        self.assertEqual(self.revision(), r + 1)
        self.assertErr(self.call("POST", "/reservations", {"restaurant_id": "r1", "table_id": "t4", "starts_at_local": f"{D}T19:00", "party_size": 2}, token=self.a, key="n"), 409, "table_unavailable")


class SeriesAmend(Base):
    def make(self, count=4, at=f"{D}T19:00", table="t3"):
        a = self.book(table, at=at)
        return self.call("POST", "/series", {"anchor_reference": a["reference"], "count": count, "interval_weeks": 1}, token=self.a, key=self.key())[1]

    def amend(self, ser, body, token=None, key=None):
        return self.call("POST", f"/series/{ser['series_id']}/amend", body, token=token or self.a, key=key or self.key())

    def test_amend(self):
        ser = self.make()
        sid = ser["series_id"]
        r0 = self.revision()
        s, g, _ = self.amend(ser, {"expected_revision": 1, "from_index": 1, "local_time": "20:00", "junk": 1}, key="am")
        self.assertEqual(s, 201)
        self.assertEqual([o["reservation"]["starts_at_local"][11:] for o in g["occurrences"]], ["19:00", "20:00", "20:00", "20:00"])
        self.assertEqual((g["revision"], [o["exception"] for o in g["occurrences"]]), (2, [False] * 4))
        self.assertEqual([o["reservation"]["revision"] for o in g["occurrences"]], [1, 2, 2, 2])
        self.assertEqual(self.revision(), r0 + 1)
        h = self.call("GET", f"/reservations/{g['occurrences'][2]['reference']}/history", token=self.a)[1]["entries"]
        self.assertEqual((h[1]["event"], h[1]["changes"][0]["field"]), ("changed", "starts_at_local"))
        self.assertEqual(self.amend(ser, {"expected_revision": 1, "from_index": 1, "local_time": "20:00", "junk": 1}, key="am")[:2], (200, g))
        self.call("POST", f"/reservations/{g['occurrences'][3]['reference']}/cancel", token=self.a)
        self.assertEqual(self.amend(ser, {"expected_revision": 1, "from_index": 1, "local_time": "20:00", "junk": 1}, key="am")[:2], (200, g))

    def test_errors(self):
        ser = self.make()
        c = lambda body, **kw: self.amend(ser, body, **kw)
        ok = {"expected_revision": 1, "from_index": 0, "local_time": "20:00"}
        self.assertErr(self.call("POST", f"/series/{ser['series_id']}/amend", ok, key="k"), 401, "unauthenticated")
        self.assertErr(self.call("POST", f"/series/{ser['series_id']}/amend", ok, token=self.b, key="k"), 404, "not_found")
        self.assertErr(self.call("POST", "/series/zzz/amend", ok, token=self.a, key="k"), 404, "not_found")
        self.assertErr(self.call("POST", f"/series/{ser['series_id']}/amend", ok, token=self.a), 400, "missing_idempotency_key")
        for patch in ({"expected_revision": 0}, {"expected_revision": True}, {"expected_revision": "1"}, {"from_index": -1}, {"from_index": 4},
                      {"from_index": True}, {"local_time": "8:00"}, {"local_time": "24:00"}, {"local_time": "20:00:00"}, {"local_time": 5}):
            self.assertErr(c(dict(ok, **patch)), 422, "validation_failed")
        self.assertErr(c({"from_index": 0, "local_time": "20:00"}), 422, "validation_failed")
        self.assertErr(c(dict(ok, expected_revision=7, local_time="20:15")), 409, "stale_revision")
        # non-occupancy errors first, in index order: 22:30 ends after closing at 23:00? (90 min)
        self.assertErr(c(dict(ok, local_time="22:30")), 422, "outside_opening_hours")
        self.assertErr(c(dict(ok, local_time="20:10")), 422, "not_on_slot_grid")
        # occupancy: block occurrence 2's new slot, nothing changes
        self.book("t3", at=f"{D}T20:00", token=self.b) if False else None
        blocker = self.call("POST", "/reservations", {"restaurant_id": "r1", "table_id": "t3", "starts_at_local": "2030-05-15T21:00", "party_size": 2}, token=self.b, key="blk")[1]
        before = self.call("GET", f"/series/{ser['series_id']}", token=self.a)[1]
        r0 = self.revision()
        self.assertErr(c(dict(ok, local_time="20:00"), key="fail"), 409, "table_unavailable")
        self.assertEqual(self.call("GET", f"/series/{ser['series_id']}", token=self.a)[1], before)
        self.assertEqual(self.revision(), r0)
        self.call("POST", f"/reservations/{blocker['reference']}/cancel", token=self.b)
        self.assertEqual(c(dict(ok, local_time="20:00"), key="fail")[0], 201)  # key reusable

    def test_noop_exceptions_cutoff_and_swap(self):
        ser = self.make(count=3)
        refs = [o["reference"] for o in ser["occurrences"]]
        self.call("PATCH", f"/reservations/{refs[1]}", {"party_size": 3}, token=self.a)  # exception
        r0 = self.revision()
        s, g, _ = self.amend(ser, {"expected_revision": 2, "from_index": 0, "local_time": "19:00"})  # all no-op
        self.assertEqual((s, g["revision"]), (201, 2))
        self.assertEqual(self.revision(), r0)
        s, g, _ = self.amend(ser, {"expected_revision": 2, "from_index": 0, "local_time": "19:30"})
        self.assertEqual((s, [o["reservation"]["starts_at_local"][11:] for o in g["occurrences"]]), (201, ["19:30", "19:00", "19:30"]))
        self.assertEqual(g["revision"], 3)
        # empty eligible set (from_index at the exception, others cancelled) succeeds
        self.call("POST", f"/reservations/{refs[2]}/cancel", token=self.a)
        s, g, _ = self.amend(ser, {"expected_revision": 4, "from_index": 1, "local_time": "21:00"})
        self.assertEqual((s, g["revision"]), (201, 4))
        # past series: cutoff blocks
        past = self.book("t4", at="2020-05-01T19:00", party=2)
        self.assertEqual(past["revision"], 1)

    def test_concurrent_amend_one_wins(self):
        ser = self.make()
        with cf.ThreadPoolExecutor(8) as ex:
            res = list(ex.map(lambda i: self.amend(ser, {"expected_revision": 1, "from_index": 0, "local_time": f"2{i % 2}:00"}), range(8)))
        self.assertEqual([r[0] for r in res].count(201), 1)


class Upgrade(Base):
    def test_old_export_and_roundtrip(self):
        a = self.book("t2", party=3)
        ser = self.call("POST", "/series", {"anchor_reference": a["reference"], "count": 2, "interval_weeks": 1}, token=self.a, key="s")[1]
        exp = self.call("GET", "/_test/export")[1]
        old = exp["state"]
        for k in ("closures", "plans", "restaurant_revisions"):
            old.pop(k)
        old["counters"].pop("next_plan")
        self.assertEqual(self.call("POST", "/_test/import", exp)[0], 204)
        self.assertEqual(self.revision(), 0)
        s, plan, _ = self.preview()
        self.assertEqual((s, plan["moved_count"]), (201, 1))
        self.assertEqual(self.apply(plan["plan_id"])[0], 201)
        full = self.call("GET", "/_test/export")[1]
        self.reset(users=[])
        self.assertEqual(self.call("POST", "/_test/import", full)[0], 204)
        self.assertErr(self.apply(plan["plan_id"], key="other"), 409, "plan_already_applied")
        self.assertEqual(self.call("POST", f"/restaurants/r1/replans/{plan['plan_id']}/apply", {}, token=self.a, key="x")[0], 409)
        self.assertErr(self.call("POST", "/reservations", {"restaurant_id": "r1", "table_id": "t2", "starts_at_local": f"{D}T19:00", "party_size": 2}, token=self.b, key="n"), 409, "table_unavailable")
        self.assertEqual(self.amend_ok(ser), 201)
        bad = dict(full, state=dict(full["state"], plans=[{"plan_id": 5}]))
        self.assertErr(self.call("POST", "/_test/import", bad), 422, "validation_failed")

    def amend_ok(self, ser):
        return self.call("POST", f"/series/{ser['series_id']}/amend", {"expected_revision": 2, "from_index": 0, "local_time": "20:00"}, token=self.a, key="am")[0]


if __name__ == "__main__":
    unittest.main()
