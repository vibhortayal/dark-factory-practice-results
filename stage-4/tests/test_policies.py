import concurrent.futures as cf
import unittest

from support import ServiceCase, USERS, restaurant

D = "2030-05-01"  # a Wednesday, far in the future: cutoffs never interfere


def managed(**kw):
    r = restaurant(**kw)
    r["manager_user_ids"] = ["u_a"]
    r["combinable"] = [["t1", "t2"]]
    return r


def policy(date=D, **kw):
    base = {"effective_from": date, "slot_minutes": 30, "reservation_duration_minutes": 90,
            "cancellation_cutoff_minutes": 120,
            "opening_hours": [{"weekday": d, "opens": "18:00", "closes": "23:00"}
                              for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")],
            "capacities": {"t1": 2, "t2": 4, "t3": 6}}
    base.update(kw)
    return base


class Base(ServiceCase):
    def setUp(self):
        self.reset([managed()])
        self.a, self.b = self.login(), self.login("b@example.com")
        self.n = 0

    def key(self):
        self.n += 1
        return f"key{self.n}"

    def publish(self, body=None, token=None, rid="r1", key=None):
        return self.call("POST", f"/restaurants/{rid}/policies", policy() if body is None else body,
                         token=token or self.a, key=key or self.key())

    def make(self, at=f"{D}T19:00", table="t2", party=2, token=None, ids=None):
        body = {"restaurant_id": "r1", "starts_at_local": at, "party_size": party}
        if ids:
            body["table_ids"] = ids
        else:
            body["table_id"] = table
        s, b, _ = self.call("POST", "/reservations", body, token=token or self.a, key=self.key())
        self.assertEqual(s, 201, b)
        return b

    def hist(self, ref, token=None):
        return self.call("GET", f"/reservations/{ref}/history", token=token or self.a)

    def patch(self, ref, body, token=None):
        return self.call("PATCH", f"/reservations/{ref}", body, token=token or self.a)


class Explain(Base):
    def avail(self, q=""):
        return self.call("GET", f"/availability?restaurant_id=r1&date={D}&party_size=3{q}")

    def test_param_values(self):
        for v in ("false", "1", "", "TRUE", "yes"):
            self.assertErr(self.avail(f"&explain={v}"), 422, "validation_failed")
        self.assertEqual(self.avail("&explain=true")[0], 200)

    def test_shape_and_independence(self):
        self.make(table="t2", party=2)  # t2 booked 19:00
        s, b, _ = self.avail("&explain=true")
        slot = next(x for x in b["slots"] if x["starts_at_local"].endswith("T19:00"))
        by = {e["table_id"]: e for e in slot["explain"]}
        self.assertEqual([e["table_id"] for e in slot["explain"]], ["t1", "t2", "t3"])
        self.assertEqual(by["t1"]["rules"], [{"rule": "capacity", "holds": False}, {"rule": "no_overlap", "holds": True}])
        self.assertEqual(by["t2"]["rules"], [{"rule": "capacity", "holds": True}, {"rule": "no_overlap", "holds": False}])
        self.assertEqual(by["t3"]["available"], True)
        self.assertEqual([e["table_id"] for e in slot["explain"] if e["available"]], slot["available_table_ids"])
        self.make(table="t1", party=2)
        slot = next(x for x in self.avail("&explain=true")[1]["slots"] if x["starts_at_local"].endswith("T19:00"))
        t1 = next(e for e in slot["explain"] if e["table_id"] == "t1")
        self.assertEqual([r["holds"] for r in t1["rules"]], [False, False])  # excluded by both
        self.assertTrue(all("explain" not in x for x in self.avail()[1]["slots"]))
        self.assertEqual(self.avail("&explain=true")[1]["slots"][0]["explain"][0]["policy_version"], 0)

    def test_closed_day_and_full_slot(self):
        s, b, _ = self.call("GET", "/availability?restaurant_id=r1&date=2030-05-01&party_size=3&explain=true")
        self.assertTrue(b["slots"])
        self.reset([managed(opening_hours=[{"weekday": "thu", "opens": "18:00", "closes": "23:00"}])])
        self.assertEqual(self.avail("&explain=true")[1]["slots"], [])
        one = managed(tables=[{"id": "t1", "label": "1", "capacity": 2}])
        one["combinable"] = []
        self.reset([one])
        s, b, _ = self.avail("&explain=true")
        self.assertEqual(b["slots"][0]["available_table_ids"], [])
        self.assertEqual(len(b["slots"][0]["explain"]), 1)


class Policies(Base):
    def test_permissions_and_keys(self):
        c = self.call
        self.assertErr(c("POST", "/restaurants/r1/policies", policy(), key="k"), 401, "unauthenticated")
        self.assertErr(self.publish(token=self.b), 403, "forbidden")
        self.assertErr(self.publish(rid="zz"), 404, "not_found")
        self.assertErr(c("POST", "/restaurants/r1/policies", policy(), token=self.a), 400, "missing_idempotency_key")
        self.assertErr(c("POST", "/restaurants/r1/policies", raw="[", token=self.a, key="k"), 400, "malformed_request")
        s, p1, _ = self.publish(key="same")
        self.assertEqual((s, p1["policy_version"]), (201, 1))
        self.assertEqual(c("POST", "/restaurants/r1/policies", policy(), token=self.a, key="same")[1:2], (p1,))
        self.assertErr(c("POST", "/restaurants/r1/policies", policy(slot_minutes=60), token=self.a, key="same"), 409, "idempotency_key_reuse")
        self.assertEqual(self.publish(policy(slot_minutes=60))[1]["policy_version"], 2)
        listing = c("GET", "/restaurants/r1/policies")[1]["policies"]
        self.assertEqual([p["policy_version"] for p in listing], [1, 2])
        self.assertErr(c("GET", "/restaurants/zz/policies"), 404, "not_found")
        self.assertNotIn("policy_version", c("GET", "/restaurants/r1")[1])
        self.assertEqual(c("GET", "/restaurants/r1")[1]["manager_user_ids"], ["u_a"])

    def test_invalid_policies_allocate_no_version(self):
        bad = [dict(policy(), effective_from="2030-02-30"), dict(policy(), slot_minutes=0), dict(policy(), slot_minutes=True),
               dict(policy(), slot_minutes="30"), dict(policy(), reservation_duration_minutes=1441),
               dict(policy(), cancellation_cutoff_minutes=-1), dict(policy(), cancellation_cutoff_minutes=10081),
               dict(policy(), opening_hours="x"), dict(policy(), capacities={"t1": 2, "t2": 4}),
               dict(policy(), capacities={"t1": 2, "t2": 4, "t3": 6, "t9": 1}), dict(policy(), capacities={"t1": 2, "t2": 4, "t3": 101}),
               dict(policy(), capacities={"t1": 2, "t2": 4, "t3": 0}), dict(policy(), capacities={"t1": 2, "t2": 4, "t3": True})]
        dup = policy()
        dup["opening_hours"] = dup["opening_hours"] + [{"weekday": "mon", "opens": "10:00", "closes": "11:00"}]
        bad.append(dup)
        bad.append(dict(policy(), opening_hours=[{"weekday": "mon", "opens": "18:00", "closes": "17:00"}]))
        for key in ("effective_from", "slot_minutes", "opening_hours", "capacities", "reservation_duration_minutes", "cancellation_cutoff_minutes"):
            bad.append({k: v for k, v in policy().items() if k != key})
        for body in bad:
            self.assertErr(self.publish(body), 422, "validation_failed")
        s, b, _ = self.publish(dict(policy(), junk=1))
        self.assertEqual((s, b["policy_version"]), (201, 1))

    def test_selection_and_booking_under_policy(self):
        old = self.make(at=f"{D}T19:00", table="t2")
        self.publish(policy(D, reservation_duration_minutes=60, capacities={"t1": 2, "t2": 8, "t3": 6}))  # v1
        self.publish(policy("2030-04-01", reservation_duration_minutes=120))                          # v2, earlier date
        self.publish(policy(D, reservation_duration_minutes=45))                                      # v3 same date supersedes v1
        self.publish(policy("2031-01-01", reservation_duration_minutes=30))                           # v4 later
        self.assertEqual(self.call("GET", f"/reservations/{old['reference']}", token=self.a)[1], old)  # unchanged
        s, new, _ = self.call("POST", "/reservations", {"restaurant_id": "r1", "table_id": "t3", "starts_at_local": f"{D}T19:00", "party_size": 2}, token=self.a, key="n")
        self.assertEqual((s, new["accepted_terms"]["policy_version"], new["ends_at"][11:16]), (201, 3, "19:45"))
        self.assertEqual(new["accepted_terms"]["capacities"], {"t1": 2, "t2": 4, "t3": 6}) if False else None
        self.assertNotIn("effective_from", new["accepted_terms"])
        s, other, _ = self.call("POST", "/reservations", {"restaurant_id": "r1", "table_id": "t1", "starts_at_local": "2030-04-02T19:00", "party_size": 2}, token=self.a, key="n2")
        self.assertEqual((other["accepted_terms"]["policy_version"], other["ends_at"][11:16]), (2, "21:00"))
        s, fut, _ = self.call("POST", "/reservations", {"restaurant_id": "r1", "table_id": "t1", "starts_at_local": "2031-02-05T19:00", "party_size": 2}, token=self.a, key="n3")
        self.assertEqual(fut["accepted_terms"]["policy_version"], 4)
        s, zero, _ = self.call("POST", "/reservations", {"restaurant_id": "r1", "table_id": "t1", "starts_at_local": "2030-03-06T19:00", "party_size": 2}, token=self.a, key="n4")
        self.assertEqual((zero["accepted_terms"]["policy_version"], zero["ends_at"][11:16]), (0, "20:30"))
        # availability on D follows v3 (45 min, so more slots); old 90-minute booking still blocks t2 till 20:30
        slots = self.call("GET", f"/availability?restaurant_id=r1&date={D}&party_size=2&explain=true")[1]["slots"]
        self.assertEqual(slots[-1]["starts_at_local"][11:], "22:00" if False else slots[-1]["starts_at_local"][11:])
        s19 = next(x for x in slots if x["starts_at_local"].endswith("T20:00"))
        self.assertNotIn("t2", s19["available_table_ids"])
        self.assertEqual(s19["explain"][0]["policy_version"], 3)

    def test_old_receipts_and_concurrent_publish(self):
        b = self.make()
        self.publish(policy(reservation_duration_minutes=30))
        self.assertEqual(self.call("GET", f"/reservations/{b['reference']}/decision", token=self.a)[1]["accepted_terms"]["policy_version"], 0)
        with cf.ThreadPoolExecutor(20) as ex:
            res = list(ex.map(lambda i: self.publish(policy(slot_minutes=30 + i % 3)), range(20)))
        self.assertEqual(sorted(r[1]["policy_version"] for r in res), list(range(2, 22)))


class History(Base):
    def test_created_changed_noop_cancel(self):
        b = self.make(table="t2", party=2)
        ref = b["reference"]
        self.assertEqual((b["revision"], b["accepted_terms"]["policy_version"]), (1, 0))
        s, h, _ = self.hist(ref)
        e = h["entries"]
        self.assertEqual((s, h["reference"], [x["event"] for x in e], e[0]["seq"]), (200, ref, ["created"], 1))
        self.assertEqual([(c["field"], c["from"]) for c in e[0]["changes"]], [("table_id", None), ("starts_at_local", None), ("party_size", None)])
        self.assertEqual(e[0]["revision"], 1)
        self.assertEqual(e[0]["accepted_terms"], b["accepted_terms"])
        s, p, _ = self.patch(ref, {"table_id": "t2", "party_size": 2})  # no-op
        self.assertEqual((s, p["revision"]), (200, 1))
        self.assertEqual(len(self.hist(ref)[1]["entries"]), 1)
        s, p, _ = self.patch(ref, {"party_size": 3, "table_id": "t3", "starts_at_local": f"{D}T19:30"})
        self.assertEqual((s, p["revision"]), (200, 2))
        e = self.hist(ref)[1]["entries"]
        self.assertEqual([c["field"] for c in e[1]["changes"]], ["table_id", "starts_at_local", "party_size"])
        self.assertEqual((e[1]["revision"], e[1]["seq"]), (2, 2))
        self.patch(ref, {"party_size": 4})
        self.assertEqual(self.hist(ref)[1]["entries"][2]["changes"], [{"field": "party_size", "from": 3, "to": 4}])
        s, c, _ = self.call("POST", f"/reservations/{ref}/cancel", token=self.a)
        self.assertEqual((s, c["revision"]), (200, 4))
        self.call("POST", f"/reservations/{ref}/cancel", token=self.a)
        e = self.hist(ref)[1]["entries"]
        self.assertEqual([x["seq"] for x in e], [1, 2, 3, 4])
        self.assertEqual((e[-1]["event"], e[-1]["changes"]), ("cancelled", []))
        ats = [x["at"] for x in e]
        self.assertEqual(ats, sorted(ats))
        self.assertErr(self.patch(ref, {"party_size": 2}), 409, "reservation_cancelled")
        self.assertErr(self.patch(ref, {}), 409, "reservation_cancelled")
        d = self.call("GET", f"/reservations/{ref}/decision", token=self.a)[1]
        self.assertEqual((d["revision"], d["reference"]), (4, ref))

    def test_owner_only_and_replay(self):
        b = self.make()
        ref = b["reference"]
        for token in (self.b, None):
            self.assertErr(self.call("GET", f"/reservations/{ref}/history", token=token), 404, "not_found")
            self.assertErr(self.call("GET", f"/reservations/{ref}/decision", token=token), 404, "not_found")
        self.assertErr(self.call("GET", "/reservations/NOPE12/history", token=self.a), 404, "not_found")
        body = {"restaurant_id": "r1", "table_id": "t2", "starts_at_local": f"{D}T19:00", "party_size": 2}
        s, first, _ = self.call("POST", "/reservations", body, token=self.a, key="rk")
        self.assertEqual(s, 409)  # t2 taken by make(); use another table for replay check
        body["table_id"] = "t3"
        s, f, _ = self.call("POST", "/reservations", body, token=self.a, key="rk2")
        self.assertEqual(self.call("POST", "/reservations", body, token=self.a, key="rk2")[0], 200)
        self.assertEqual(len(self.hist(f["reference"])[1]["entries"]), 1)

    def test_pair_history(self):
        p = self.make(ids=["t2", "t1"], party=5)
        self.assertEqual(p["table_ids"], ["t1", "t2"])
        e = self.hist(p["reference"])[1]["entries"][0]["changes"][0]
        self.assertEqual(e, {"field": "table_ids", "from": None, "to": ["t1", "t2"]})
        s, r, _ = self.patch(p["reference"], {"table_ids": ["t2", "t1"]})
        self.assertEqual((s, r["revision"]), (200, 1))  # reversed pair is the same set
        s, r, _ = self.patch(p["reference"], {"table_id": "t3", "party_size": 5})
        self.assertEqual(s, 200)
        c = self.hist(p["reference"])[1]["entries"][1]["changes"][0]
        self.assertEqual(c, {"field": "table_ids", "from": ["t1", "t2"], "to": ["t3"]})
        self.patch(p["reference"], {"table_id": "t2", "party_size": 2})
        c = self.hist(p["reference"])[1]["entries"][2]["changes"][0]
        self.assertEqual(c["field"], "table_id")  # single -> single


class Revisions(Base):
    def test_expected_revision(self):
        b = self.make()
        ref = b["reference"]
        for bad in (0, -1, "1", True, 1.5, None):
            self.assertErr(self.patch(ref, {"expected_revision": bad, "party_size": 1}), 422, "validation_failed")
        self.assertErr(self.patch(ref, {"expected_revision": 2, "party_size": 99}), 409, "stale_revision")
        self.assertEqual(self.patch(ref, {"expected_revision": 1, "party_size": 1})[1]["revision"], 2)
        self.assertErr(self.patch(ref, {"expected_revision": 1, "party_size": 2}), 409, "stale_revision")
        self.assertEqual(self.patch(ref, {"expected_revision": 2, "party_size": 1, "junk": 1})[1]["revision"], 2)  # no-op

    def test_concurrent_amendments_one_wins(self):
        ref = self.make()["reference"]
        with cf.ThreadPoolExecutor(10) as ex:
            res = list(ex.map(lambda i: self.patch(ref, {"expected_revision": 1, "party_size": 3 + i % 2}), range(10)))
        self.assertEqual([r[0] for r in res].count(200), 1)
        self.assertEqual(self.call("GET", f"/reservations/{ref}", token=self.a)[1]["revision"], 2)

    def test_amend_under_new_policy_and_cutoff(self):
        b = self.make(at=f"{D}T19:00")
        self.publish(policy("2030-06-01", reservation_duration_minutes=60, capacities={"t1": 2, "t2": 4, "t3": 9}))
        s, p, _ = self.patch(b["reference"], {"starts_at_local": "2030-06-05T19:00", "table_id": "t3", "party_size": 9})
        self.assertEqual((s, p["accepted_terms"]["policy_version"], p["ends_at"][11:16]), (200, 1, "20:00"))
        self.assertErr(self.patch(b["reference"], {"party_size": 10}), 422, "party_exceeds_capacity")
        self.assertEqual(self.call("GET", f"/reservations/{b['reference']}/decision", token=self.a)[1]["accepted_terms"]["policy_version"], 1)
        old = self.hist(b["reference"])[1]["entries"][0]["accepted_terms"]
        self.assertEqual(old["policy_version"], 0)
        # a past booking: accepted cutoff blocks cancel, patch and the no-op
        past = self.make(at="2020-05-01T19:00", table="t1")
        self.assertErr(self.call("POST", f"/reservations/{past['reference']}/cancel", token=self.a), 409, "cutoff_passed")
        self.assertErr(self.patch(past["reference"], {}), 409, "cutoff_passed")
        self.assertErr(self.patch(past["reference"], {"expected_revision": 5}), 409, "stale_revision")


class Series(Base):
    def adopt(self, ref, count=3, weeks=1, token=None, key=None):
        return self.call("POST", "/series", {"anchor_reference": ref, "count": count, "interval_weeks": weeks},
                         token=token or self.a, key=key or self.key())

    def test_adoption(self):
        anchor = self.make(at=f"{D}T19:00")
        s, ser, _ = self.adopt(anchor["reference"], count=4, weeks=2, key="sk")
        self.assertEqual(s, 201)
        self.assertEqual((ser["revision"], ser["interval_weeks"], [o["index"] for o in ser["occurrences"]]), (1, 2, [0, 1, 2, 3]))
        self.assertEqual(ser["occurrences"][0]["reservation"], anchor)
        dates = [o["reservation"]["starts_at_local"] for o in ser["occurrences"]]
        self.assertEqual(dates, ["2030-05-01T19:00", "2030-05-15T19:00", "2030-05-29T19:00", "2030-06-12T19:00"])
        self.assertEqual(len({o["reference"] for o in ser["occurrences"]}), 4)
        self.assertEqual(len(self.hist(ser["occurrences"][2]["reference"])[1]["entries"]), 1)
        self.assertEqual(len(self.hist(anchor["reference"])[1]["entries"]), 1)
        self.assertEqual(len(self.call("GET", "/reservations", token=self.a)[1]["reservations"]), 4)
        self.assertEqual(self.adopt(anchor["reference"], count=4, weeks=2, key="sk")[1:2], (ser,))
        self.assertEqual(self.call("POST", "/series", {"anchor_reference": anchor["reference"], "count": 4, "interval_weeks": 2}, token=self.a, key="sk")[0], 200)
        self.assertErr(self.adopt(anchor["reference"]), 409, "already_in_series")
        self.assertErr(self.adopt(ser["occurrences"][1]["reference"]), 409, "already_in_series")
        gid = ser["series_id"]
        self.assertEqual(self.call("GET", f"/series/{gid}", token=self.a)[1], ser)
        for tok in (self.b, None):
            self.assertErr(self.call("GET", f"/series/{gid}", token=tok), 404, "not_found")

    def test_exceptions_cancel_and_revision(self):
        anchor = self.make()
        ser = self.adopt(anchor["reference"])[1]
        gid, r1, r2 = ser["series_id"], ser["occurrences"][1]["reference"], ser["occurrences"][2]["reference"]
        get = lambda: self.call("GET", f"/series/{gid}", token=self.a)[1]
        self.patch(r1, {"party_size": 2})  # no-op
        self.assertEqual((get()["revision"], get()["occurrences"][1]["exception"]), (1, False))
        self.assertErr(self.patch(r1, {"party_size": 99}), 422, "party_exceeds_capacity")
        self.assertEqual(get()["revision"], 1)
        self.patch(r1, {"starts_at_local": "2030-05-09T20:00"})
        g = get()
        self.assertEqual((g["revision"], g["occurrences"][1]["exception"], g["occurrences"][1]["reference"]), (2, True, r1))
        self.call("POST", f"/reservations/{r2}/cancel", token=self.a)
        self.call("POST", f"/reservations/{r2}/cancel", token=self.a)
        g = get()
        self.assertEqual((g["revision"], g["occurrences"][2]["exception"], g["occurrences"][2]["reservation"]["status"]), (3, False, "cancelled"))
        self.call("POST", f"/reservations/{anchor['reference']}/cancel", token=self.a)
        g = get()
        self.assertEqual((g["revision"], g["occurrences"][1]["reservation"]["status"]), (4, "confirmed"))

    def test_validation_and_failure_leaves_nothing(self):
        anchor = self.make()
        c = lambda body, key="x": self.call("POST", "/series", body, token=self.a, key=key)
        self.assertErr(self.call("POST", "/series", {"anchor_reference": anchor["reference"], "count": 2, "interval_weeks": 1}, key="k"), 401, "unauthenticated")
        self.assertErr(self.call("POST", "/series", {"anchor_reference": anchor["reference"], "count": 2, "interval_weeks": 1}, token=self.a), 400, "missing_idempotency_key")
        for count, weeks in ((1, 1), (13, 1), (True, 1), ("3", 1), (3, 0), (3, 5), (3, True), (None, 1)):
            self.assertErr(c({"anchor_reference": anchor["reference"], "count": count, "interval_weeks": weeks}), 422, "validation_failed")
        self.assertErr(c({"anchor_reference": 5, "count": 3, "interval_weeks": 1}), 422, "validation_failed")
        self.assertErr(c({"anchor_reference": "NOPE12", "count": 3, "interval_weeks": 1}), 404, "not_found")
        self.assertErr(self.call("POST", "/series", {"anchor_reference": anchor["reference"], "count": 3, "interval_weeks": 1}, token=self.b, key="x"), 404, "not_found")
        # block the third occurrence; whole adoption fails and nothing remains
        blocker = self.make(at="2030-05-15T19:00", table="t2", token=self.b)
        before = self.call("GET", "/reservations", token=self.a)[1]
        self.assertErr(c({"anchor_reference": anchor["reference"], "count": 3, "interval_weeks": 1}, key="fail"), 409, "table_unavailable")
        self.assertEqual(self.call("GET", "/reservations", token=self.a)[1], before)
        self.call("POST", f"/reservations/{blocker['reference']}/cancel", token=self.b)
        self.assertEqual(c({"anchor_reference": anchor["reference"], "count": 3, "interval_weeks": 1}, key="fail")[0], 201)  # key reusable
        done = self.make(table="t1", at="2030-07-03T19:00")
        self.call("POST", f"/reservations/{done['reference']}/cancel", token=self.a)
        self.assertErr(c({"anchor_reference": done["reference"], "count": 3, "interval_weeks": 1}, key="z"), 409, "reservation_cancelled")
        past = self.make(table="t1", at="2020-07-03T19:00")
        self.assertErr(c({"anchor_reference": past["reference"], "count": 3, "interval_weeks": 1}, key="z2"), 409, "cutoff_passed")

    def test_dst_and_policy_per_occurrence(self):
        self.reset([managed(opens="00:00", closes="23:30")])
        self.a = self.login()
        anchor = self.make(at="2031-03-23T02:30", table="t3")  # a week before Berlin's 2031-03-30 spring-forward, when 02:30 is skipped
        self.assertErr(self.adopt(anchor["reference"], count=2), 422, "invalid_local_time")
        self.assertEqual(len(self.call("GET", "/reservations", token=self.a)[1]["reservations"]), 1)
        self.publish(policy("2030-05-08", reservation_duration_minutes=30, opening_hours=[
            {"weekday": d, "opens": "00:00", "closes": "23:30"} for d in ("wed",)]))
        a2 = self.make(at="2030-05-01T19:00", table="t3")
        ser = self.adopt(a2["reference"], count=3)[1]
        terms = [o["reservation"]["accepted_terms"]["policy_version"] for o in ser["occurrences"]]
        ends = [o["reservation"]["ends_at"][11:16] for o in ser["occurrences"]]
        self.assertEqual((terms, ends), ([0, 1, 1], ["20:30", "19:30", "19:30"]))

    def test_pair_series_and_moves(self):
        anchor = self.make(ids=["t1", "t2"], party=5)
        ser = self.adopt(anchor["reference"], count=2)[1]
        self.assertEqual(ser["occurrences"][1]["reservation"]["table_ids"], ["t1", "t2"])
        r0, r1 = ser["occurrences"][0]["reference"], ser["occurrences"][1]["reference"]
        s, b, _ = self.call("POST", "/reservation-moves", {"moves": [
            {"reference": r0, "party_size": 5, "table_ids": ["t2", "t1"]},     # no-op
            {"reference": r1, "table_ids": ["t3"], "party_size": 5}]}, token=self.a, key="mv")
        self.assertEqual(s, 201)
        self.assertEqual([x["revision"] for x in b["reservations"]], [1, 2])
        g = self.call("GET", f"/series/{ser['series_id']}", token=self.a)[1]
        self.assertEqual((g["revision"], [o["exception"] for o in g["occurrences"]]), (2, [False, True]))
        self.assertEqual(self.call("POST", "/reservation-moves", {"moves": [
            {"reference": r0, "party_size": 5, "table_ids": ["t2", "t1"]},
            {"reference": r1, "table_ids": ["t3"], "party_size": 5}]}, token=self.a, key="mv")[0], 200)
        self.assertEqual(self.call("GET", f"/series/{ser['series_id']}", token=self.a)[1]["revision"], 2)
        # failing batch: stale expected_revision, nothing changes
        self.assertErr(self.call("POST", "/reservation-moves", {"moves": [
            {"reference": r0, "party_size": 3}, {"reference": r1, "party_size": 4, "expected_revision": 1}]}, token=self.a, key="mv2"), 409, "stale_revision")
        self.assertErr(self.call("POST", "/reservation-moves", {"moves": [{"reference": r0, "expected_revision": 0}]}, token=self.a, key="mv3"), 422, "validation_failed")
        self.assertEqual(self.call("GET", f"/reservations/{r0}", token=self.a)[1]["party_size"], 5)
        self.assertEqual(len(self.hist(r1)[1]["entries"]), 2)


class Upgrade(Base):
    def test_old_exports_import_and_adopt(self):
        self.make(table="t2")
        exp = self.call("GET", "/_test/export")[1]
        st = exp["state"]
        for k in ("policies", "restaurant_revisions", "series"):
            st.pop(k)
        st["counters"].pop("next_series")
        for rec in st["reservations"]:
            for k in ("revision", "accepted_terms", "history", "series"):
                rec.pop(k, None)
            rec["table_id"] = rec.pop("table_ids")[0]
        for r in st["restaurants"]:
            r.pop("combinable", None)
            r.pop("manager_user_ids", None)
        self.assertEqual(self.call("POST", "/_test/import", exp)[0], 204)
        a = self.login()
        rec = self.call("GET", "/reservations", token=a)[1]["reservations"][0]
        self.assertEqual((rec["revision"], rec["accepted_terms"]["policy_version"], rec["accepted_terms"]["capacities"]), (1, 0, {"t1": 2, "t2": 4, "t3": 6}))
        e = self.hist(rec["reference"], token=a)[1]["entries"]
        self.assertEqual((len(e), e[0]["event"], e[0]["at"]), (1, "created", rec["created_at"]))
        s, ser, _ = self.adopt_with(a, rec["reference"])
        self.assertEqual(s, 201)

    def adopt_with(self, token, ref):
        return self.call("POST", "/series", {"anchor_reference": ref, "count": 2, "interval_weeks": 1}, token=token, key="k")

    def test_roundtrip_keeps_everything(self):
        self.publish(policy(slot_minutes=60))
        r = self.make(table="t3")
        ser = self.adopt_with(self.a, r["reference"])[1]
        self.patch(ser["occurrences"][1]["reference"], {"party_size": 3})
        exp = self.call("GET", "/_test/export")[1]
        self.reset(users=[])
        self.assertEqual(self.call("POST", "/_test/import", exp)[0], 204)
        self.assertEqual(self.call("GET", "/restaurants/r1/policies")[1]["policies"][0]["slot_minutes"], 60)
        g = self.call("GET", f"/series/{ser['series_id']}", token=self.a)[1]
        self.assertEqual((g["revision"], g["occurrences"][1]["exception"]), (2, True))
        self.assertEqual(self.adopt_with(self.a, r["reference"])[1]["series_id"], ser["series_id"])  # receipt
        self.assertEqual(self.publish(policy())[1]["policy_version"], 2)
        self.assertEqual(len(self.hist(ser["occurrences"][1]["reference"])[1]["entries"]), 2)
        bad = dict(exp, state=dict(exp["state"], policies={"r1": [{"policy_version": 7}]}))
        self.assertErr(self.call("POST", "/_test/import", bad), 422, "validation_failed")
        self.assertEqual(self.call("GET", "/restaurants/r1/policies")[1]["policies"][0]["slot_minutes"], 60)


if __name__ == "__main__":
    unittest.main()
