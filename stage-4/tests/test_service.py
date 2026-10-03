import concurrent.futures as cf
import re
import unittest

from support import ServiceCase, restaurant, USERS


class Basics(ServiceCase):
    def test_health_and_json_headers_and_error_shape(self):
        self.reset()
        s, b, r = self.call("GET", "/health")
        self.assertEqual((s, b), (200, {"status": "ok"}))
        self.assertEqual(r.getheader("Content-Type"), "application/json; charset=utf-8")
        for method, path in (("GET", "/nope"), ("DELETE", "/health"), ("GET", "/reservations")):
            s, b, r = self.call(method, path)
            self.assertIn(s, (401, 404, 405))
            self.assertEqual(set(b["error"]), {"code", "message"})
            self.assertEqual(r.getheader("Content-Type"), "application/json; charset=utf-8")

    def test_reset_replaces_everything_and_validates_ids(self):
        self.reset()
        tok = self.login()
        self.reset()
        self.assertErr(self.call("GET", "/reservations", token=tok), 401, "unauthenticated")
        bad = restaurant("x" * 65)
        s, b, _ = self.call("POST", "/_test/reset", {"restaurants": [bad]})
        self.assertEqual((s, b["error"]["code"]), (422, "validation_failed"))
        self.assertErr(self.call("POST", "/_test/reset", raw="{nope"), 400, "malformed_request")
        self.assertErr(self.call("POST", "/_test/reset", raw="[]"), 400, "malformed_request")

    def test_reset_type_vs_range_errors(self):
        r = restaurant()
        cases = [({"users": "x"}, 400), ({"restaurants": {}}, 400), ({"reservations": 5}, 400),
                 ({"users": ["x"]}, 400), ({"users": [{"id": "u", "email": 5, "password": "password1"}]}, 400),
                 ({"restaurants": [dict(r, slot_minutes="30")]}, 400),
                 ({"restaurants": [dict(r, id=7)]}, 400),
                 ({"restaurants": [dict(r, tables=[{"id": "t", "capacity": "2"}])]}, 400),
                 ({"restaurants": [r], "reservations": [{"reference": "ABCDEF", "restaurant_id": [], "table_id": "t1"}]}, 400),
                 ({"restaurants": [dict(r, slot_minutes=0)]}, 422),
                 ({"restaurants": [dict(r, id="x" * 65)]}, 422),
                 ({"restaurants": [dict(r, slot_minutes=1.5)]}, 422)]
        for body, status in cases:
            s, b, _ = self.call("POST", "/_test/reset", body)
            self.assertEqual(s, status, body)
            self.assertEqual(b["error"]["code"], "malformed_request" if status == 400 else "validation_failed")

    def test_seeded_party_size_is_always_422(self):
        seed = {"id": "x1", "reference": "ABCDEF", "user_id": "u_a", "restaurant_id": "r1",
                "table_id": "t1", "starts_at_local": "2030-05-01T19:00"}
        for party in ("4", True, 0, 1.5, None):
            s, b, _ = self.call("POST", "/_test/reset", {"users": USERS, "restaurants": [restaurant()],
                                                         "reservations": [dict(seed, party_size=party)]})
            self.assertEqual((s, b["error"]["code"]), (422, "validation_failed"), party)
        self.reset(reservations=[dict(seed, party_size=2)])

    def test_auth_rules(self):
        self.reset()
        c = self.call
        s, b, _ = c("POST", "/auth/signup", {"email": "n@x.io", "password": "longenough", "display_name": "N"})
        self.assertEqual(s, 201)
        self.assertTrue(b["token"] and b["user_id"])
        self.assertErr(c("POST", "/auth/signup", {"email": "N@X.io", "password": "longenough", "display_name": "N"}), 409, "email_taken")
        self.assertErr(c("POST", "/auth/signup", {"email": "q@x.io", "password": "short", "display_name": "N"}), 422, "validation_failed")
        self.assertErr(c("POST", "/auth/signup", {"email": "nodomain", "password": "longenough", "display_name": "N"}), 422, "validation_failed")
        self.assertErr(c("POST", "/auth/signup", {"email": "q@x.io", "password": "longenough"}), 422, "validation_failed")
        self.assertErr(c("POST", "/auth/signup", {"email": 5, "password": "longenough", "display_name": "N"}), 400, "malformed_request")
        self.assertErr(c("POST", "/auth/login", {"email": "a@example.com", "password": "bad"}), 401, "unauthenticated")
        self.assertErr(c("POST", "/auth/login", {"email": "zz@example.com", "password": "password1"}), 401, "unauthenticated")
        t1, t2 = self.login(), self.login()
        self.assertNotEqual(t1, t2)
        for t in (t1, t2):
            self.assertEqual(c("GET", "/reservations", token=t)[0], 200)
        for hdr in ({}, {"Authorization": "Bearer"}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer nope"}):
            self.assertErr(c("GET", "/reservations", headers=hdr), 401, "unauthenticated")

    def test_availability_validation_and_dst(self):
        self.reset([restaurant(opens="00:00", closes="23:30")])
        base = "/availability?restaurant_id=r1&party_size=2&date="
        for q in ("/availability?date=2030-05-01&party_size=2",
                  "/availability?restaurant_id=r1&party_size=2",
                  "/availability?restaurant_id=r1&date=2030-05-01",
                  base + "2030-02-30", base + "garbage",
                  "/availability?restaurant_id=r1&date=2030-05-01&party_size=",
                  "/availability?restaurant_id=r1&date=2030-05-01&party_size=0"):
            self.assertErr(self.call("GET", q), 422, "validation_failed")
        for bad in ("1e9", "4.0", "%2B4", "-1", "abc"):
            self.assertErr(self.call("GET", f"/availability?restaurant_id=r1&date=2030-05-01&party_size={bad}"), 422, "validation_failed")
        self.assertErr(self.call("GET", "/availability?restaurant_id=zz&date=2030-05-01&party_size=2"), 404, "not_found")
        times = lambda d: [x["starts_at_local"][11:] for x in self.call("GET", base + d)[1]["slots"]]
        spring = times("2026-03-29")
        self.assertNotIn("02:00", spring)
        self.assertNotIn("02:30", spring)
        self.assertIn("03:00", spring)
        fall = self.call("GET", base + "2026-10-25")[1]["slots"]
        locs = [x["starts_at_local"] for x in fall]
        self.assertEqual(len(locs), len(set(locs)))
        two = next(x for x in fall if x["starts_at_local"].endswith("T02:00"))
        self.assertTrue(two["starts_at"].endswith("+02:00"))
        self.assertTrue(next(x for x in fall if x["starts_at_local"].endswith("T03:00"))["starts_at"].endswith("+01:00"))

    def test_closed_day_and_unknown_params(self):
        r = restaurant(opening_hours=[{"weekday": "thu", "opens": "18:00", "closes": "23:00"}])
        self.reset([r])
        s, b, _ = self.call("GET", "/availability?restaurant_id=r1&date=2030-05-02&party_size=2&junk=1")
        self.assertEqual(s, 200)
        self.assertEqual(len(b["slots"]), 8)
        self.assertEqual(self.call("GET", "/availability?restaurant_id=r1&date=2030-05-01&party_size=2")[1]["slots"], [])
        tok = self.login()
        self.assertErr(self.book(tok, "k", at="2030-05-01T19:00"), 422, "outside_opening_hours")
        s, b, _ = self.call("GET", "/restaurants/r1")
        self.assertEqual(sorted(b), sorted(r))


class Booking(ServiceCase):
    def setUp(self):
        self.reset()
        self.a, self.b = self.login(), self.login("b@example.com")

    def test_create_shape_and_errors(self):
        s, b, _ = self.book(self.a, "k1")
        self.assertEqual(s, 201)
        self.assertRegex(b["reference"], r"^[A-Z0-9]{6,12}$")
        self.assertEqual((b["status"], b["starts_at"], b["ends_at"]), ("confirmed", "2030-05-01T19:00:00+02:00", "2030-05-01T20:30:00+02:00"))
        self.assertRegex(b["created_at"], r"[+-]\d\d:\d\d$")
        self.assertErr(self.book(self.a, "k2", at="2030-05-01T20:00"), 409, "table_unavailable")
        self.assertEqual(self.book(self.a, "k3", at="2030-05-01T20:30")[0], 201)
        self.assertErr(self.book(self.a, "k4", at="2030-05-01T19:10", table="t3"), 422, "not_on_slot_grid")
        self.assertErr(self.book(self.a, "k5", at="2030-05-01T22:00", table="t3"), 422, "outside_opening_hours")
        self.assertErr(self.book(self.a, "k6", at="2030-05-01T17:30", table="t3"), 422, "outside_opening_hours")
        self.assertErr(self.book(self.a, "k7", table="t1", party=3), 422, "party_exceeds_capacity")
        self.assertErr(self.book(self.a, "k8", rid="zz"), 404, "not_found")
        self.assertErr(self.book(self.a, "k9", table="zz"), 404, "not_found")
        for party in (0, -1, "2", True, 1.5, None):
            self.assertErr(self.book(self.a, "kp", party=party, table="t3"), 422, "validation_failed")
        for at in ("2030-05-01T19:00Z", "2030-05-01T19:00:00", "2030-13-01T19:00", "x"):
            self.assertErr(self.book(self.a, "kq", at=at, table="t3"), 422, "validation_failed")
        self.assertErr(self.call("POST", "/reservations", {"restaurant_id": 1, "table_id": "t1", "starts_at_local": "2030-05-01T19:00", "party_size": 2}, token=self.a, key="kz"), 400, "malformed_request")
        self.assertErr(self.call("POST", "/reservations", raw="[1]", token=self.a, key="kz"), 400, "malformed_request")

    def test_spring_forward_booking(self):
        self.reset([restaurant(opens="00:00", closes="23:30")])
        self.a = self.login()
        self.assertErr(self.book(self.a, "k", at="2026-03-29T02:30"), 422, "invalid_local_time")
        s, b, _ = self.book(self.a, "k2", at="2026-03-29T03:00")
        self.assertEqual((s, b["starts_at"]), (201, "2026-03-29T03:00:00+02:00"))

    def test_fall_back_ends_at_and_overlap_on_instants(self):
        self.reset([restaurant(opens="00:00", closes="23:30")])
        self.a = self.login()
        s, b, _ = self.book(self.a, "k", at="2026-10-25T01:30")
        self.assertEqual((s, b["ends_at"]), (201, "2026-10-25T02:00:00+01:00"))
        # 02:00 first occurrence (+02:00) starts 30 real minutes after 01:30 -> overlaps
        self.assertErr(self.book(self.a, "k2", at="2026-10-25T02:00"), 409, "table_unavailable")
        s, b, _ = self.book(self.a, "k3", at="2026-10-25T02:30", table="t3")
        self.assertEqual(s, 201)

    def test_idempotency_matrix(self):
        body = {"restaurant_id": "r1", "table_id": "t2", "starts_at_local": "2030-05-01T19:00", "party_size": 2}
        c = self.call
        self.assertErr(c("POST", "/reservations", body, token=self.a), 400, "missing_idempotency_key")
        self.assertErr(c("POST", "/reservations", body, token=self.a, key=""), 400, "missing_idempotency_key")
        self.assertErr(c("POST", "/reservations", body, token=self.a, key="x" * 256), 422, "validation_failed")
        s1, b1, _ = c("POST", "/reservations", body, token=self.a, key="x" * 255)
        self.assertEqual(s1, 201)
        reordered = '{"party_size":2,  "starts_at_local":"2030-05-01T19:00","table_id":"t2","restaurant_id":"r1"}'
        s2, b2, _ = c("POST", "/reservations", raw=reordered, token=self.a, key="x" * 255)
        self.assertEqual((s2, b2), (200, b1))
        self.assertErr(c("POST", "/reservations", {"junk": 1}, token=self.a, key="x" * 255), 409, "idempotency_key_reuse")
        self.assertEqual(c("POST", "/reservations/%s/cancel" % b1["reference"], token=self.a)[0], 200)
        self.assertEqual(c("POST", "/reservations", body, token=self.a, key="x" * 255)[1], b1)
        # other user, same key: independent (table is free now)
        self.assertEqual(c("POST", "/reservations", body, token=self.b, key="x" * 255)[0], 201)
        # same key, same body, different path -> new request
        s, b, _ = c("POST", "/reservation-moves", {"moves": [{"reference": b1["reference"]}]}, token=self.a, key="x" * 255)
        self.assertErr((s, b), 409, "reservation_cancelled")
        # failed first use does not burn the key
        bad = dict(body, table_id="zz")
        self.assertErr(c("POST", "/reservations", bad, token=self.a, key="fk"), 404, "not_found")
        self.assertEqual(c("POST", "/reservations", dict(body, starts_at_local="2030-05-01T21:00"), token=self.a, key="fk")[0], 201)
        # 409 reuse wins over invalid new body; no token -> 401 first
        self.assertErr(c("POST", "/reservations", {"party_size": "bad"}, token=self.a, key="fk"), 409, "idempotency_key_reuse")
        self.assertErr(c("POST", "/reservations", body, key="fk"), 401, "unauthenticated")

    def test_concurrent_identical_and_racing(self):
        body = {"restaurant_id": "r1", "table_id": "t2", "starts_at_local": "2030-05-01T19:00", "party_size": 2}
        with cf.ThreadPoolExecutor(50) as ex:
            res = list(ex.map(lambda _: self.call("POST", "/reservations", body, token=self.a, key="same"), range(50)))
        self.assertEqual(sorted(r[0] for r in res).count(201), 1)
        self.assertEqual({r[0] for r in res}, {200, 201})
        self.assertEqual(len({r[1]["reference"] for r in res}), 1)
        self.assertEqual(len(self.call("GET", "/reservations", token=self.a)[1]["reservations"]), 1)
        self.reset()
        a = self.login()
        with cf.ThreadPoolExecutor(50) as ex:
            res = list(ex.map(lambda i: self.book(a, f"race{i}"), range(50)))
        self.assertEqual(sorted(r[0] for r in res), [201] + [409] * 49)

    def test_patch_order_cancelled_cutoff_then_fields(self):
        past = self.book(self.a, "kp", at="2020-05-01T19:00", table="t3")[1]["reference"]
        self.assertErr(self.call("PATCH", f"/reservations/{past}", {"party_size": 0}, token=self.a), 409, "cutoff_passed")
        self.assertErr(self.call("PATCH", f"/reservations/{past}", {"party_size": 0}, token=self.b), 404, "not_found")
        self.assertErr(self.call("PATCH", f"/reservations/{past}", raw="[", token=self.a), 400, "malformed_request")
        ok = self.book(self.a, "kf")[1]["reference"]
        self.assertErr(self.call("PATCH", f"/reservations/{ok}", {"party_size": 0}, token=self.a), 422, "validation_failed")

    def test_list_get_cancel_patch(self):
        s, r1, _ = self.book(self.a, "k1", at="2030-05-01T19:00")
        s, r2, _ = self.book(self.a, "k2", at="2030-05-02T19:00")
        ref = r1["reference"]
        lst = self.call("GET", "/reservations", token=self.a)[1]["reservations"]
        self.assertEqual([x["reference"] for x in lst], [r2["reference"], ref])
        self.assertEqual(self.call("GET", "/reservations", token=self.b)[1], {"reservations": []})
        self.assertErr(self.call("GET", f"/reservations/{ref}", token=self.b), 404, "not_found")
        self.assertErr(self.call("PATCH", f"/reservations/{ref}", {"party_size": 3}, token=self.b), 404, "not_found")
        # patch into own overlapping slot, same table
        s, p, _ = self.call("PATCH", f"/reservations/{ref}", {"starts_at_local": "2030-05-01T19:30", "party_size": 4}, token=self.a)
        self.assertEqual((s, p["reference"], p["reservation_id"], p["party_size"]), (200, ref, r1["reservation_id"], 4))
        self.assertEqual(p["starts_at"], "2030-05-01T19:30:00+02:00")
        # failed patch leaves original
        self.assertErr(self.call("PATCH", f"/reservations/{ref}", {"party_size": 7}, token=self.a), 422, "party_exceeds_capacity")
        self.assertErr(self.call("PATCH", f"/reservations/{ref}", {"starts_at_local": "2030-05-02T19:00"}, token=self.a), 409, "table_unavailable")
        self.assertEqual(self.call("GET", f"/reservations/{ref}", token=self.a)[1], p)
        self.assertEqual(self.call("PATCH", f"/reservations/{ref}", {}, token=self.a)[1], p)
        s, c1, _ = self.call("POST", f"/reservations/{ref}/cancel", token=self.a)
        self.assertEqual((s, c1["status"]), (200, "cancelled"))
        self.assertEqual(self.call("POST", f"/reservations/{ref}/cancel", token=self.a)[1], c1)
        self.assertErr(self.call("PATCH", f"/reservations/{ref}", {"party_size": 2}, token=self.a), 409, "reservation_cancelled")
        # freed
        slots = self.call("GET", "/availability?restaurant_id=r1&date=2030-05-01&party_size=4")[1]["slots"]
        self.assertIn("t2", next(x for x in slots if x["starts_at_local"].endswith("T19:30"))["available_table_ids"])

    def test_cutoff_and_past(self):
        s, past, _ = self.book(self.a, "kp", at="2020-05-01T19:00")
        self.assertEqual(s, 201)  # past start is not rejected
        ref = past["reference"]
        self.assertErr(self.call("POST", f"/reservations/{ref}/cancel", token=self.a), 409, "cutoff_passed")
        self.assertErr(self.call("PATCH", f"/reservations/{ref}", {"party_size": 1}, token=self.a), 409, "cutoff_passed")

    def test_seeded_reservations(self):
        seed = {"id": "res_seed", "reference": "BOOK01", "user_id": "u_a", "restaurant_id": "r1",
                "table_id": "t2", "starts_at_local": "2030-05-01T19:00", "party_size": 2}
        self.reset(reservations=[seed])
        a = self.login()
        self.assertEqual(self.call("GET", "/reservations/BOOK01", token=a)[1]["status"], "confirmed")
        self.assertErr(self.book(a, "k"), 409, "table_unavailable")
        s, b, _ = self.book(a, "k2", at="2030-05-01T21:00")
        self.assertNotEqual(b["reference"], "BOOK01")
        self.assertNotEqual(b["reservation_id"], "res_seed")


class Moves(ServiceCase):
    def setUp(self):
        self.reset([restaurant(), restaurant("r2")])
        self.a, self.b = self.login(), self.login("b@example.com")
        self.r1 = self.book(self.a, "k1", table="t1", at="2030-05-01T19:00")[1]
        self.r2 = self.book(self.a, "k2", table="t2", at="2030-05-01T19:00")[1]
        self.blocker = self.book(self.b, "kb", table="t3", at="2030-05-01T19:00")[1]

    def mv(self, moves, key="m1", token=None):
        return self.call("POST", "/reservation-moves", {"moves": moves}, token=token or self.a, key=key)

    def test_swap_and_replay_and_order(self):
        s, b, _ = self.mv([{"reference": self.r1["reference"], "table_id": "t2", "party_size": 2},
                           {"reference": self.r2["reference"], "table_id": "t1", "party_size": 2}])
        self.assertEqual(s, 201)
        self.assertEqual([x["reference"] for x in b["reservations"]], [self.r1["reference"], self.r2["reference"]])
        self.assertEqual([x["table_id"] for x in b["reservations"]], ["t2", "t1"])
        self.assertEqual(b["reservations"][0]["created_at"], self.r1["created_at"])
        self.call("POST", f"/reservations/{self.r1['reference']}/cancel", token=self.a)
        s2, b2, _ = self.mv([{"reference": self.r1["reference"], "table_id": "t2", "party_size": 2},
                             {"reference": self.r2["reference"], "table_id": "t1", "party_size": 2}])
        self.assertEqual((s2, b2), (200, b))

    def test_atomic_failure_changes_nothing(self):
        before = self.call("GET", "/reservations", token=self.a)[1]
        self.assertErr(self.mv([{"reference": self.r1["reference"], "table_id": "t2", "party_size": 2},
                                {"reference": self.r2["reference"], "table_id": "t3"}]), 409, "table_unavailable")
        self.assertErr(self.mv([{"reference": self.r1["reference"], "table_id": "t3"}]), 409, "table_unavailable")
        self.assertEqual(self.call("GET", "/reservations", token=self.a)[1], before)
        # key not burned: a valid move with same key now works
        self.assertEqual(self.mv([{"reference": self.r1["reference"], "party_size": 1}], key="m1")[0], 201)

    def test_cutoff_precedes_later_field_errors(self):
        past = self.book(self.a, "kp", at="2020-05-01T19:00", table="t3")[1]["reference"]
        for moves in ([{"reference": past, "party_size": 0}],
                      [{"reference": past}, {"reference": self.r2["reference"], "party_size": 0}],
                      [{"reference": past, "starts_at_local": "2030-05-01T19:00:00"}]):
            self.assertErr(self.mv(moves, key="mq"), 409, "cutoff_passed")
        self.assertErr(self.mv([{"reference": self.r2["reference"], "party_size": 0}], key="mr"), 422, "validation_failed")

    def test_two_into_one_table_conflict(self):
        self.assertErr(self.mv([{"reference": self.r1["reference"], "table_id": "t2"},
                                {"reference": self.r2["reference"], "table_id": "t2"}]), 409, "table_unavailable")

    def test_shape_and_ownership(self):
        r1 = self.r1["reference"]
        for moves in ([], [{"reference": r1}] * 2, [{"reference": 5}], ["x"], "nope", [{"reference": r1}] * 0 + [{"reference": f"R{i}"} for i in range(9)]):
            self.assertErr(self.mv(moves), 422, "validation_failed")
        self.assertErr(self.mv([{"reference": "NOPE99"}]), 404, "not_found")
        self.assertErr(self.mv([{"reference": self.blocker["reference"]}]), 404, "not_found")
        self.assertErr(self.call("POST", "/reservation-moves", {"moves": []}, key="k"), 401, "unauthenticated")
        self.assertErr(self.call("POST", "/reservation-moves", {"moves": [{"reference": r1}]}, token=self.a), 400, "missing_idempotency_key")
        other = self.book(self.a, "ko", rid="r2", table="t2", at="2030-05-03T19:00")[1]
        self.assertErr(self.mv([{"reference": r1}, {"reference": other["reference"]}]), 422, "validation_failed")

    def test_cancelled_and_cutoff_and_noop(self):
        self.call("POST", f"/reservations/{self.r1['reference']}/cancel", token=self.a)
        self.assertErr(self.mv([{"reference": self.r1["reference"]}]), 409, "reservation_cancelled")
        past = self.book(self.a, "kp", at="2020-05-01T19:00", table="t3")[1]
        self.assertErr(self.mv([{"reference": past["reference"], "party_size": 1}], key="mp"), 409, "cutoff_passed")
        self.assertErr(self.mv([{"reference": self.r2["reference"], "table_id": "zz"}], key="m3"), 404, "not_found")
        s, b, _ = self.mv([{"reference": self.r2["reference"]}], key="m4")
        self.assertEqual((s, b["reservations"][0]), (201, self.r2))


class ExportImport(ServiceCase):
    def test_roundtrip_preserves_everything(self):
        self.reset()
        a = self.login()
        s, r1, _ = self.book(a, "k1")
        s, mv, _ = self.call("POST", "/reservation-moves", {"moves": [{"reference": r1["reference"], "party_size": 3}]}, token=a, key="mk")
        s, exp, _ = self.call("GET", "/_test/export")
        self.assertEqual((s, exp["track"], exp["format_version"]), (200, "tablekeeper", 1))
        self.assertNotIn("password1", str(exp))
        self.reset(users=[])  # destroy
        self.assertErr(self.call("GET", "/reservations", token=a), 401, "unauthenticated")
        self.assertEqual(self.call("POST", "/_test/import", exp)[0], 204)
        self.assertEqual(self.call("POST", "/_test/import", exp)[0], 204)
        self.assertEqual(self.call("GET", f"/reservations/{r1['reference']}", token=a)[1]["party_size"], 3)
        body = {"restaurant_id": "r1", "table_id": "t2", "starts_at_local": "2030-05-01T19:00", "party_size": 2}
        self.assertEqual(self.call("POST", "/reservations", body, token=a, key="k1")[1], r1)
        self.assertEqual(self.call("POST", "/reservation-moves", {"moves": [{"reference": r1["reference"], "party_size": 3}]}, token=a, key="mk")[1], mv)
        self.assertEqual(self.call("POST", "/auth/login", {"email": "a@example.com", "password": "password1"})[0], 200)
        s, n, _ = self.book(a, "k9", at="2030-05-04T19:00")
        self.assertNotIn(n["reference"], r1["reference"])
        self.assertNotEqual(n["reservation_id"], r1["reservation_id"])
        # export is a snapshot
        before = self.call("GET", "/_test/export")[1]
        self.book(a, "k10", at="2030-05-05T19:00")
        self.assertNotEqual(before, self.call("GET", "/_test/export")[1])
        self.reset()
        self.assertErr(self.call("GET", "/reservations", token=a), 401, "unauthenticated")

    def test_bad_imports_leave_state(self):
        self.reset()
        a = self.login()
        good = self.call("GET", "/_test/export")[1]
        self.assertErr(self.call("POST", "/_test/import", raw="{x"), 400, "malformed_request")
        for bad in ({}, {"track": "tablekeeper"}, dict(good, track="other"), dict(good, format_version=2),
                    dict(good, state=5), dict(good, state={}), dict(good, state=dict(good["state"], users="x")),
                    {k: v for k, v in good.items() if k != "state"}):
            self.assertErr(self.call("POST", "/_test/import", bad), 422, "validation_failed")
        self.assertEqual(self.call("GET", "/reservations", token=a)[0], 200)


if __name__ == "__main__":
    unittest.main()
