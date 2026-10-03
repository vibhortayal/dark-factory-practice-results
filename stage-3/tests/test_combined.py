import concurrent.futures as cf
import unittest

from support import ServiceCase, restaurant, USERS


def combo_restaurant(**kw):
    return restaurant(tables=[{"id": "t1", "label": "1", "capacity": 2},
                              {"id": "t2", "label": "2", "capacity": 4},
                              {"id": "t3", "label": "3", "capacity": 4},
                              {"id": "t4", "label": "4", "capacity": 6}],
                      combinable=[["t1", "t2"], ["t3", "t2"]], **kw)


class Combined(ServiceCase):
    def setUp(self):
        self.reset([combo_restaurant()])
        self.a, self.b = self.login(), self.login("b@example.com")

    def post(self, ids, key, at="2030-05-01T19:00", party=6, token=None, one=False):
        body = {"restaurant_id": "r1", "starts_at_local": at, "party_size": party}
        if one:
            body["table_id"] = ids[0]
        else:
            body["table_ids"] = ids
        return self.call("POST", "/reservations", body, token=token or self.a, key=key)

    def test_fixture_validation(self):
        base = combo_restaurant()
        for comb, status in (("x", 400), ([["t1"]], 422), ([["t1", "t2", "t3"]], 422), ([["t1", "t1"]], 422),
                             ([["t1", "zz"]], 422), ([[1, 2]], 400), ([5], 400), ([["t1", "t2"], ["t2", "t1"]], 204)):
            s, b, _ = self.call("POST", "/_test/reset", {"restaurants": [dict(base, combinable=comb)]})
            self.assertEqual(s, status, comb)
        self.reset([combo_restaurant()])
        self.assertEqual(self.call("GET", "/restaurants/r1")[1]["combinable"], [["t1", "t2"], ["t3", "t2"]])

    def test_availability_options(self):
        s, b, _ = self.call("GET", "/availability?restaurant_id=r1&date=2030-05-01&party_size=6")
        slot = b["slots"][0]
        self.assertEqual(slot["available_table_ids"], ["t4"])
        self.assertEqual(slot["available_options"], [
            {"table_ids": ["t4"], "capacity": 6}, {"table_ids": ["t1", "t2"], "capacity": 6},
            {"table_ids": ["t3", "t2"], "capacity": 8}])
        s, b, _ = self.call("GET", "/availability?restaurant_id=r1&date=2030-05-01&party_size=2")
        self.assertEqual([o["table_ids"] for o in b["slots"][0]["available_options"]],
                         [["t1"], ["t2"], ["t3"], ["t4"], ["t1", "t2"], ["t3", "t2"]])
        self.post(["t2", "t1"], "k")  # order-insensitive; occupies both
        s, b, _ = self.call("GET", "/availability?restaurant_id=r1&date=2030-05-01&party_size=2")
        self.assertEqual([o["table_ids"] for o in b["slots"][0]["available_options"]], [["t3"], ["t4"]])
        self.assertEqual(b["slots"][0]["available_table_ids"], ["t3", "t4"])

    def test_create_shapes_and_errors(self):
        s, b, _ = self.post(["t2", "t1"], "k1")
        self.assertEqual((s, b["table_ids"]), (201, ["t1", "t2"]))
        self.assertNotIn("table_id", b)
        self.assertErr(self.post(["t2"], "k2", party=2, one=True), 409, "table_unavailable")
        self.assertErr(self.post(["t3", "t4"], "k3"), 422, "combination_not_allowed")
        self.assertErr(self.post(["t1", "t3"], "k4"), 422, "combination_not_allowed")
        self.assertErr(self.post(["t1", "t2", "t3"], "k5"), 422, "combination_not_allowed")
        self.assertErr(self.post(["t3", "t2"], "k6", party=9), 422, "party_exceeds_capacity")
        self.assertErr(self.post(["t3", "t3"], "k7"), 422, "validation_failed")
        self.assertErr(self.post([], "k8"), 422, "validation_failed")
        self.assertErr(self.call("POST", "/reservations", {"restaurant_id": "r1", "table_ids": "t3", "starts_at_local": "2030-05-01T19:00", "party_size": 2}, token=self.a, key="k9"), 400, "malformed_request")
        self.assertErr(self.post([1], "k10"), 400, "malformed_request")
        self.assertErr(self.post(["zz", "t1"], "k11"), 404, "not_found")
        self.assertErr(self.post(["zz", "t1", "t2"], "k12"), 404, "not_found")
        body = {"restaurant_id": "r1", "starts_at_local": "2030-05-01T19:00", "party_size": 2, "table_id": "t3", "table_ids": ["t3"]}
        self.assertErr(self.call("POST", "/reservations", body, token=self.a, key="k13"), 422, "validation_failed")
        del body["table_id"], body["table_ids"]
        self.assertErr(self.call("POST", "/reservations", body, token=self.a, key="k14"), 422, "validation_failed")
        s, b, _ = self.post(["t3"], "k15", party=2, one=True)
        self.assertEqual((s, b["table_id"], b["table_ids"]), (201, "t3", ["t3"]))
        # precedence: combination error beats time errors; time errors beat capacity
        self.assertErr(self.post(["t1", "t3"], "k16", at="2030-05-01T19:10"), 422, "combination_not_allowed")
        self.assertErr(self.post(["t1", "t2"], "k17", at="2030-05-01T19:10", party=9), 422, "not_on_slot_grid")

    def test_cancel_frees_all_and_list_get(self):
        ref = self.post(["t1", "t2"], "k1")[1]["reference"]
        self.assertErr(self.post(["t2"], "k2", party=2, one=True), 409, "table_unavailable")
        s, c, _ = self.call("POST", f"/reservations/{ref}/cancel", token=self.a)
        self.assertEqual((s, c["table_ids"]), (200, ["t1", "t2"]))
        self.assertEqual(self.post(["t1"], "k3", party=2, one=True)[0], 201)
        self.assertEqual(self.post(["t2"], "k4", party=2, one=True)[0], 201)
        lst = self.call("GET", "/reservations", token=self.a)[1]["reservations"]
        self.assertTrue(all("table_ids" in r for r in lst))

    def test_patch(self):
        s, r, _ = self.post(["t1"], "k1", party=2, one=True)
        ref = r["reference"]
        p = lambda body: self.call("PATCH", f"/reservations/{ref}", body, token=self.a)
        s, b, _ = p({"table_ids": ["t1", "t2"], "party_size": 6})
        self.assertEqual((s, b["table_ids"], "table_id" in b), (200, ["t1", "t2"], False))
        s, b, _ = p({"table_ids": ["t3", "t2"]})  # shares t2 with itself
        self.assertEqual((s, b["table_ids"]), (200, ["t3", "t2"]))
        self.assertErr(p({"table_ids": ["t1", "t3"]}), 422, "combination_not_allowed")
        self.assertErr(p({"table_id": "t1", "table_ids": ["t1"]}), 422, "validation_failed")
        self.assertErr(p({"table_ids": ["t1"]}), 422, "party_exceeds_capacity")
        self.assertEqual(self.call("GET", f"/reservations/{ref}", token=self.a)[1]["table_ids"], ["t3", "t2"])
        self.assertEqual(self.post(["t1"], "k2", party=2, one=True, token=self.b)[0], 201)
        self.assertErr(p({"table_ids": ["t1", "t2"]}), 409, "table_unavailable")
        s, b, _ = p({"table_id": "t4"})
        self.assertEqual((s, b["table_id"], b["table_ids"], b["reference"]), (200, "t4", ["t4"], ref))

    def test_moves_with_pairs(self):
        r1 = self.post(["t1", "t2"], "k1")[1]["reference"]
        r2 = self.post(["t4"], "k2", party=6, one=True, at="2030-05-01T19:00")[1]["reference"]
        mv = lambda moves, key: self.call("POST", "/reservation-moves", {"moves": moves}, token=self.a, key=key)
        self.assertErr(mv([{"reference": r2, "table_ids": ["t3", "t2"]}], "m1"), 409, "table_unavailable")
        s, b, _ = mv([{"reference": r1, "table_ids": ["t4"]}, {"reference": r2, "table_ids": ["t3", "t2"]}], "m2")
        self.assertEqual((s, [x["table_ids"] for x in b["reservations"]]), (201, [["t4"], ["t3", "t2"]]))
        self.assertEqual(b["reservations"][0]["table_id"], "t4")
        self.assertNotIn("table_id", b["reservations"][1])
        self.assertErr(mv([{"reference": r1, "table_ids": ["t3", "t2"]}], "m3"), 409, "table_unavailable")
        self.assertErr(mv([{"reference": r1, "table_ids": ["t1", "t3"]}], "m4"), 422, "combination_not_allowed")

    def test_concurrent_overlap_never_happens(self):
        reqs = [(["t1", "t2"], False), (["t3", "t2"], False), (["t2"], True), (["t1"], True), (["t3"], True)] * 10
        with cf.ThreadPoolExecutor(50) as ex:
            res = list(ex.map(lambda i: self.post(reqs[i][0], f"c{i}", party=2, one=reqs[i][1],
                                                  token=self.a if i % 2 else self.b), range(50)))
        self.assertTrue(all(r[0] in (201, 409) for r in res))
        confirmed = self.call("GET", "/reservations", token=self.a)[1]["reservations"] + \
            self.call("GET", "/reservations", token=self.b)[1]["reservations"]
        used = [t for r in confirmed for t in r["table_ids"]]
        self.assertEqual(len(used), len(set(used)))  # same slot: no table twice

    def test_seeded_and_stage1_style_import(self):
        seed = [{"id": "s1", "reference": "SEED01", "user_id": "u_a", "restaurant_id": "r1", "table_ids": ["t1", "t2"],
                 "starts_at_local": "2030-05-01T19:00", "party_size": 5},
                {"id": "s2", "reference": "SEED02", "user_id": "u_a", "restaurant_id": "r1", "table_id": "t4", "status": "cancelled",
                 "starts_at_local": "2030-05-01T19:00", "party_size": 5}]
        self.reset([combo_restaurant()], reservations=seed)
        a = self.login()
        self.assertEqual(self.call("GET", "/reservations/SEED01", token=a)[1]["table_ids"], ["t1", "t2"])
        self.assertEqual(self.call("GET", "/reservations/SEED02", token=a)[1]["status"], "cancelled")
        self.assertEqual(self.post(["t4"], "k", party=5, one=True, token=a)[0], 201)
        self.assertErr(self.post(["t1"], "k2", party=2, one=True, token=a), 409, "table_unavailable")
        # a stage-1 style export: table_id only, no combinable, receipts stored verbatim
        exp = self.call("GET", "/_test/export")[1]
        st = exp["state"]
        for rec in st["reservations"]:
            rec["table_id"] = rec.pop("table_ids")[0] if len(rec["table_ids"]) == 1 else rec["table_ids"][0]
        for r in st["restaurants"]:
            r.pop("combinable", None)
        old = {"reservation_id": "x", "table_id": "t4"}
        st["idempotency"][0]["response"] = old
        self.assertEqual(self.call("POST", "/_test/import", exp)[0], 204)
        s, b, _ = self.post(["t4"], "k", party=5, one=True, token=a)
        self.assertEqual((s, b), (200, old))
        self.assertEqual(self.call("GET", "/reservations", token=a)[1]["reservations"][0]["table_ids"] [0] in ("t1", "t4"), True)

    def test_screens_are_html_and_api_404_is_json(self):
        for path in ("/", "/signup", "/login", "/lookup"):
            s, _, r = self.call("GET", path)
            conn_type = r.getheader("Content-Type")
            self.assertEqual((s, conn_type.split(";")[0]), (200, "text/html"), path)
        self.assertErr(self.call("GET", "/nope"), 404, "not_found")
        s, _, r = self.call("GET", "/assets/app.css")
        self.assertEqual((s, r.getheader("Content-Type").split(";")[0]), (200, "text/css"))
        self.assertEqual(self.call("GET", "/assets/evil.js")[0], 404)


if __name__ == "__main__":
    unittest.main()
