"""Black-box tests against a running service: BASE_URL=http://localhost:8080 python -m unittest tests.test_api -v"""
import datetime as dt
import json
import os
import time
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

BASE = os.environ.get("BASE_URL", "http://localhost:8080")


def call(method, path, body=None, token=None, key=None, raw=None, headers=None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    if key is not None:
        h["Idempotency-Key"] = key
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            txt = r.read()
            return r.status, (json.loads(txt) if txt else None), r.headers
    except urllib.error.HTTPError as e:
        txt = e.read()
        return e.code, (json.loads(txt) if txt else None), e.headers


WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def rest(rid="r1", tz="Europe/Berlin", slot=30, dur=90, cutoff=120, tables=None, opens="18:00", closes="23:00"):
    return {"id": rid, "name": "R " + rid, "timezone": tz, "slot_minutes": slot,
            "reservation_duration_minutes": dur, "cancellation_cutoff_minutes": cutoff,
            "opening_hours": [{"weekday": d, "opens": opens, "closes": closes} for d in WEEK],
            "tables": tables or [{"id": "t1", "label": "1", "capacity": 2},
                                 {"id": "t2", "label": "2", "capacity": 4},
                                 {"id": "t3", "label": "3", "capacity": 6}]}


USERS = [{"id": "u_a", "email": "a@x.io", "password": "correct horse", "display_name": "A"},
         {"id": "u_b", "email": "b@x.io", "password": "correct horse", "display_name": "B"}]


def reset(restaurants=None, users=None, reservations=None):
    s, b, _ = call("POST", "/_test/reset", {"users": USERS if users is None else users,
                                           "restaurants": restaurants if restaurants is not None else [rest()],
                                           "reservations": reservations or []})
    assert s == 204, (s, b)


def login(email="a@x.io"):
    s, b, _ = call("POST", "/auth/login", {"email": email, "password": "correct horse"})
    assert s == 200, b
    return b["token"]


def future(days=10, hh=19, mm=0):
    d = dt.date.today() + dt.timedelta(days=days)
    return "%sT%02d:%02d" % (d.isoformat(), hh, mm)


def book(tok, local, table="t2", party=2, rid="r1", key=None):
    return call("POST", "/reservations", {"restaurant_id": rid, "table_id": table,
                                           "starts_at_local": local, "party_size": party},
                tok, key or "k%f" % time.time())


def err(test, resp, status, code):
    s, b, h = resp
    test.assertEqual(s, status, b)
    test.assertEqual(b["error"]["code"], code)
    test.assertIn("message", b["error"])
    test.assertEqual(h["Content-Type"], "application/json; charset=utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        reset()
        self.a, self.b = login(), login("b@x.io")


class Basics(Base):
    def test_health_and_envelopes(self):
        self.assertEqual(call("GET", "/health")[:2], (200, {"status": "ok"}))
        err(self, call("GET", "/nope"), 404, "not_found")
        s, b, _ = call("DELETE", "/reservations")
        self.assertIn(s, (404, 405)); self.assertIn("error", b)
        err(self, call("POST", "/auth/login", raw=b"{bad"), 400, "malformed_request")
        err(self, call("POST", "/auth/login", raw=b"[1]"), 400, "malformed_request")
        err(self, call("POST", "/auth/login", {"email": 1, "password": "x"}), 400, "malformed_request")

    def test_reset_validation_keeps_state(self):
        long = "x" * 65
        for fx in ({"users": [{"id": long, "email": "q@q.q", "password": "password1", "display_name": "q"}]},
                   {"restaurants": [dict(rest(), id=long)]},
                   {"restaurants": [rest(tables=[{"id": long, "label": "1", "capacity": 2}])]},
                   {"restaurants": [rest()], "users": USERS,
                    "reservations": [{"id": "x", "reference": "abc", "user_id": "u_a", "restaurant_id": "r1",
                                      "table_id": "t1", "starts_at_local": future(), "party_size": 1}]},
                   {"restaurants": [rest()], "users": USERS,
                    "reservations": [{"id": "x", "reference": "ABCDEF", "user_id": "nobody", "restaurant_id": "r1",
                                      "table_id": "t1", "starts_at_local": future(), "party_size": 1}]},
                   {"users": USERS + USERS}):
            err(self, call("POST", "/_test/reset", fx), 422, "validation_failed")
        err(self, call("POST", "/_test/reset", raw=b"nope"), 400, "malformed_request")
        self.assertEqual(call("GET", "/restaurants")[1]["restaurants"][0]["id"], "r1")
        reset(restaurants=[rest(rid="r" * 64)])
        self.assertEqual(call("GET", "/restaurants/" + "r" * 64)[0], 200)

    def test_auth(self):
        s, b, _ = call("POST", "/auth/signup", {"email": "n@n.n", "password": "12345678", "display_name": "N", "x": 1})
        self.assertEqual(s, 201); self.assertEqual(call("GET", "/reservations", token=b["token"])[0], 200)
        err(self, call("POST", "/auth/signup", {"email": "N@n.n", "password": "12345678", "display_name": "N"}), 409, "email_taken")
        err(self, call("POST", "/auth/signup", {"email": "a@x.io", "password": "12345678", "display_name": "N"}), 409, "email_taken")
        err(self, call("POST", "/auth/signup", {"email": "m@n.n", "password": "1234567", "display_name": "N"}), 422, "validation_failed")
        for e in ("nope", "@x", "x@", ""):
            err(self, call("POST", "/auth/signup", {"email": e, "password": "12345678", "display_name": "N"}), 422, "validation_failed")
        err(self, call("POST", "/auth/signup", {"email": "z@z.z", "password": "12345678"}), 422, "validation_failed")
        err(self, call("POST", "/auth/login", {"email": "a@x.io"}), 422, "validation_failed")
        err(self, call("POST", "/auth/login", {"email": "a@x.io", "password": "bad"}), 401, "unauthenticated")
        err(self, call("POST", "/auth/login", {"email": "no@x.io", "password": "bad"}), 401, "unauthenticated")
        for hdr in ({}, {"Authorization": "Bearer "}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer nope"}):
            for m, p in (("GET", "/reservations"), ("POST", "/reservations"), ("GET", "/reservations/ABC"),
                         ("PATCH", "/reservations/ABC"), ("POST", "/reservations/ABC/cancel"), ("POST", "/reservation-moves")):
                err(self, call(m, p, {}, headers=hdr, key="k"), 401, "unauthenticated")
        self.assertEqual(call("GET", "/restaurants", headers={"Authorization": "Bearer junk"})[0], 200)
        self.assertNotEqual(login(), login())
        self.assertEqual(call("GET", "/reservations", token=self.a)[0], 200)

    def test_signup_race(self):
        with ThreadPoolExecutor(20) as ex:
            rs = list(ex.map(lambda i: call("POST", "/auth/signup", {"email": "r@r.r", "password": "12345678", "display_name": "R"})[0], range(20)))
        self.assertEqual(sorted(rs), [201] + [409] * 19)


class Availability(Base):
    def av(self, date, party=2, rid="r1"):
        return call("GET", "/availability?restaurant_id=%s&date=%s&party_size=%s" % (rid, date, party))

    def test_params(self):
        d = future()[:10]
        for q in ("date=%s&party_size=2" % d, "restaurant_id=r1&party_size=2", "restaurant_id=r1&date=%s" % d):
            err(self, call("GET", "/availability?" + q), 422, "validation_failed")
        for bad in ("1e9", "4.0", "%2B4", "+4", "%204", "-1", "abc", "", "0"):
            err(self, call("GET", "/availability?restaurant_id=r1&date=%s&party_size=%s" % (d, bad)), 422, "validation_failed")
        for bad in ("2026-02-30", "not-a-date", "24-09-2026"):
            err(self, self.av(bad), 422, "validation_failed")
        err(self, self.av(d, rid="zzz"), 404, "not_found")
        self.assertEqual(call("GET", "/availability?restaurant_id=r1&date=%s&party_size=2&junk=1" % d)[0], 200)

    def test_slots_and_overlap(self):
        d = future()[:10]
        s, b, _ = self.av(d, 3)
        times = [x["starts_at_local"][11:] for x in b["slots"]]
        self.assertEqual(times, ["%02d:%02d" % (h, m) for h in range(18, 22) for m in (0, 30)])
        self.assertEqual(times[0], "18:00"); self.assertEqual(times[-1], "21:30")
        self.assertEqual(b["slots"][0]["available_table_ids"], ["t2", "t3"])
        self.assertEqual(book(self.a, d + "T19:00", "t2", 3)[0], 201)
        got = {x["starts_at_local"][11:]: x["available_table_ids"] for x in self.av(d, 3)[1]["slots"]}
        for t in ("18:00", "18:30", "19:00", "19:30", "20:00"):
            self.assertEqual(got[t], ["t3"], t)
        self.assertEqual(got["20:30"], ["t2", "t3"])
        # no table at all -> still listed with []
        for t in ("t3",):
            book(self.a, d + "T19:00", t, 6)
        self.assertEqual({x["starts_at_local"][11:]: x["available_table_ids"] for x in self.av(d, 3)[1]["slots"]}["19:00"], [])
        self.assertEqual({x["starts_at_local"][11:]: x["available_table_ids"] for x in self.av(d, 5)[1]["slots"]}["20:30"], ["t3"])

    def test_closed_day(self):
        r = rest(); r["opening_hours"] = [{"weekday": "mon", "opens": "18:00", "closes": "23:00"}]
        reset([r])
        d = dt.date.today() + dt.timedelta(days=3)
        while d.weekday() == 0:
            d += dt.timedelta(days=1)
        self.assertEqual(self.av(d.isoformat())[1]["slots"], [])
        err(self, book(login(), d.isoformat() + "T19:00"), 422, "outside_opening_hours")

    def test_cancel_frees(self):
        d = future()[:10]
        s, b, _ = book(self.a, d + "T19:00", "t1")
        self.assertEqual(call("POST", "/reservations/%s/cancel" % b["reference"], token=self.a)[1]["status"], "cancelled")
        self.assertEqual(self.av(d)[1]["slots"][2]["available_table_ids"], ["t1", "t2", "t3"])


class Create(Base):
    def test_create_and_errors(self):
        d = future()[:10]
        s, b, _ = book(self.a, d + "T19:00", "t2", 4)
        self.assertEqual(s, 201)
        self.assertRegex(b["reference"], r"^[A-Z0-9]{6,12}$")
        self.assertEqual(b["status"], "confirmed")
        self.assertRegex(b["created_at"], r"\+00:00$")
        self.assertEqual(dt.datetime.fromisoformat(b["ends_at"]) - dt.datetime.fromisoformat(b["starts_at"]), dt.timedelta(minutes=90))
        err(self, book(self.b, d + "T19:00", "t2", 4), 409, "table_unavailable")
        err(self, book(self.b, d + "T20:00", "t2", 4), 409, "table_unavailable")
        self.assertEqual(book(self.b, d + "T20:30", "t2", 4)[0], 201)
        self.assertEqual(book(self.b, d + "T19:00", "t3", 4)[0], 201)
        err(self, book(self.a, d + "T19:10", "t1"), 422, "not_on_slot_grid")
        err(self, book(self.a, d + "T18:01", "t1"), 422, "not_on_slot_grid")
        for t in ("17:30", "22:00", "23:00", "23:30"):
            err(self, book(self.a, d + "T" + t, "t1"), 422, "outside_opening_hours")
        self.assertEqual(book(self.a, d + "T21:30", "t1", 2)[0], 201)
        err(self, book(self.a, d + "T19:00", "t1", 3), 422, "party_exceeds_capacity")
        for p in (0, -1, "2", True, 1.5, None):
            err(self, call("POST", "/reservations", {"restaurant_id": "r1", "table_id": "t1", "starts_at_local": d + "T19:00", "party_size": p}, self.a, "kk%s" % p), 422, "validation_failed")
        for l in (d + "T19:00Z", d + "T19:00:00", d + "T19:00+02:00", "2026-02-30T19:00", d + "T24:00", d):
            err(self, call("POST", "/reservations", {"restaurant_id": "r1", "table_id": "t1", "starts_at_local": l, "party_size": 1}, self.a, "k" + l), 422, "validation_failed")
        err(self, call("POST", "/reservations", {"restaurant_id": "r1", "table_id": 5, "starts_at_local": d + "T19:00", "party_size": 1}, self.a, "kt"), 400, "malformed_request")
        err(self, call("POST", "/reservations", {"restaurant_id": "r1", "table_id": "t1", "party_size": 1}, self.a, "km"), 422, "validation_failed")
        err(self, book(self.a, d + "T19:00", "zz", rid="r1"), 404, "not_found")
        err(self, book(self.a, d + "T19:00", "t1", rid="rz"), 404, "not_found")
        reset([rest(), rest("r2", tables=[{"id": "t9", "label": "9", "capacity": 2}])])
        a = login()
        err(self, book(a, d + "T19:00", "t9"), 404, "not_found")
        s, b, _ = call("GET", "/reservations", token=a)
        self.assertEqual(b, {"reservations": []})

    def test_past_start_allowed_and_cutoff(self):
        s, b, _ = book(self.a, "2020-05-05T19:00", "t1")
        self.assertEqual(s, 201)
        err(self, call("POST", "/reservations/%s/cancel" % b["reference"], token=self.a), 409, "cutoff_passed")
        err(self, call("PATCH", "/reservations/" + b["reference"], {"party_size": 1}, self.a), 409, "cutoff_passed")

    def test_visibility_and_listing(self):
        d1, d2 = future(5)[:10], future(12)[:10]
        r1 = book(self.a, d1 + "T19:00", "t1")[1]
        r2 = book(self.a, d2 + "T19:00", "t1")[1]
        book(self.b, d1 + "T19:00", "t2")
        lst = call("GET", "/reservations", token=self.a)[1]["reservations"]
        self.assertEqual([x["reference"] for x in lst], [r2["reference"], r1["reference"]])
        err(self, call("GET", "/reservations/" + r1["reference"], token=self.b), 404, "not_found")
        err(self, call("POST", "/reservations/%s/cancel" % r1["reference"], token=self.b), 404, "not_found")
        err(self, call("PATCH", "/reservations/" + r1["reference"], {}, self.b), 404, "not_found")
        err(self, call("GET", "/reservations/NOPE", token=self.a), 404, "not_found")
        c = call("POST", "/reservations/%s/cancel" % r1["reference"], token=self.a)
        self.assertEqual(c[0], 200)
        self.assertEqual(call("POST", "/reservations/%s/cancel" % r1["reference"], token=self.a)[1], c[1])
        self.assertEqual(len(call("GET", "/reservations", token=self.a)[1]["reservations"]), 2)

    def test_cutoff_boundaries(self):
        soon = (dt.datetime.now(ZoneInfo("Europe/Berlin")) + dt.timedelta(minutes=100)).replace(second=0, microsecond=0)
        reset([rest(slot=1, opens="00:00", closes="23:59", cutoff=120, dur=1)])
        a = login()
        local = soon.strftime("%Y-%m-%dT%H:%M")
        s, b, _ = call("POST", "/reservations", {"restaurant_id": "r1", "table_id": "t1", "starts_at_local": local, "party_size": 1}, a, "c1")
        self.assertEqual(s, 201, b)
        err(self, call("POST", "/reservations/%s/cancel" % b["reference"], token=a), 409, "cutoff_passed")
        err(self, call("PATCH", "/reservations/" + b["reference"], {"party_size": 2}, a), 409, "cutoff_passed")


class Amend(Base):
    def test_patch(self):
        d = future()[:10]
        r = book(self.a, d + "T19:00", "t2", 2)[1]
        ref = r["reference"]
        p = lambda body, tok=None: call("PATCH", "/reservations/" + ref, body, tok or self.a)
        self.assertEqual(p({})[1], r)
        self.assertEqual(p({"junk": 1})[1], r)
        s, b, _ = p({"starts_at_local": d + "T19:30"})   # onto its own interval
        self.assertEqual(s, 200); self.assertEqual(b["starts_at_local"], d + "T19:30")
        self.assertEqual((b["reference"], b["reservation_id"], b["created_at"]), (ref, r["reservation_id"], r["created_at"]))
        self.assertNotEqual(b["ends_at"], r["ends_at"])
        err(self, p({"table_id": "t3", "party_size": 7}), 422, "party_exceeds_capacity")
        err(self, p({"table_id": 4}), 400, "malformed_request")
        err(self, p({"party_size": "2"}), 422, "validation_failed")
        err(self, p({"table_id": "zz"}), 404, "not_found")
        err(self, p({"starts_at_local": d + "T19:10"}), 422, "not_on_slot_grid")
        err(self, p({"starts_at_local": d + "T23:00"}), 422, "outside_opening_hours")
        other = book(self.b, d + "T19:00", "t3", 2)[1]
        err(self, p({"table_id": "t3"}), 409, "table_unavailable")
        self.assertEqual(call("GET", "/reservations/" + ref, token=self.a)[1]["table_id"], "t2")
        self.assertEqual(book(self.b, d + "T19:30", "t2", 2)[0], 409)    # old slot stays held after failed patch
        self.assertEqual(p({"table_id": "t1"})[0], 200)
        self.assertEqual(book(self.b, d + "T19:30", "t2", 2)[0], 201)    # released
        call("POST", "/reservations/%s/cancel" % ref, token=self.a)
        err(self, p({"party_size": 1}), 409, "reservation_cancelled")

    def test_patch_race(self):
        d = future()[:10]
        refs = [book(self.a, d + "T%02d:00" % h, "t1")[1]["reference"] for h in (18, 20)]
        refs += [book(self.a, d + "T18:00", "t2")[1]["reference"]]
        def go(i):
            ref = refs[i % 3]
            return ref, call("PATCH", "/reservations/" + ref, {"table_id": "t3", "starts_at_local": d + "T19:00"}, self.a)[0]
        with ThreadPoolExecutor(30) as ex:
            res = list(ex.map(go, range(30)))
        self.assertEqual(len({r for r, st in res if st == 200}), 1, res)
        self.assertEqual({st for _, st in res} - {200, 409}, set())
        no_overlap(self, call("GET", "/reservations", token=self.a)[1]["reservations"])


class Idempotency(Base):
    def test_keys(self):
        d = future()[:10]
        body = {"restaurant_id": "r1", "table_id": "t1", "starts_at_local": d + "T19:00", "party_size": 2}
        s1, b1, _ = call("POST", "/reservations", body, self.a, "K1")
        self.assertEqual(s1, 201)
        s2, b2, _ = call("POST", "/reservations", dict(reversed(list(body.items()))), self.a, "K1")
        self.assertEqual((s2, b2), (200, b1))
        err(self, call("POST", "/reservations", dict(body, party_size="x"), self.a, "K1"), 409, "idempotency_key_reuse")
        err(self, call("POST", "/reservations", dict(body, table_id="zz"), self.a, "K1"), 409, "idempotency_key_reuse")
        call("POST", "/reservations/%s/cancel" % b1["reference"], token=self.a)
        self.assertEqual(call("POST", "/reservations", body, self.a, "K1")[1], b1)
        self.assertEqual(len(call("GET", "/reservations", token=self.a)[1]["reservations"]), 1)
        s, b, _ = call("POST", "/reservations", body, self.b, "K1")   # other user, same key
        self.assertEqual(s, 201)
        err(self, call("POST", "/reservations", body, self.a), 400, "missing_idempotency_key")
        err(self, call("POST", "/reservations", body, self.a, key=""), 400, "missing_idempotency_key")
        err(self, call("POST", "/reservations", body, self.a, "k" * 256), 422, "validation_failed")
        for n in (1, 255):
            self.assertEqual(call("POST", "/reservations", dict(body, table_id="t3", starts_at_local=d + "T%02d:00" % (18 if n == 1 else 20)), self.a, "k" * n)[0], 201)
        # failed first use -> reusable
        bad = dict(body, party_size=0)
        err(self, call("POST", "/reservations", bad, self.a, "F1"), 422, "validation_failed")
        self.assertEqual(call("POST", "/reservations", dict(body, starts_at_local=d + "T21:00"), self.a, "F1")[0], 201)
        # same key + same body on the other path is a different request
        mv = {"moves": [{"reference": b1["reference"]}]}
        err(self, call("POST", "/reservation-moves", mv, self.a, "K1"), 409, "reservation_cancelled")
        err(self, call("POST", "/reservation-moves", {"moves": []}, self.a), 400, "missing_idempotency_key")

    def test_concurrent_identical(self):
        d = future()[:10]
        body = {"restaurant_id": "r1", "table_id": "t1", "starts_at_local": d + "T19:00", "party_size": 2}
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: call("POST", "/reservations", body, self.a, "same"), range(50)))
        self.assertEqual(sorted(r[0] for r in rs), [200] * 49 + [201])
        self.assertEqual(len({json.dumps(r[1], sort_keys=True) for r in rs}), 1)
        self.assertEqual(len(call("GET", "/reservations", token=self.a)[1]["reservations"]), 1)

    def test_booking_race(self):
        d = future()[:10]
        def go(i):
            tok = self.a if i % 2 else self.b
            t = time.time()
            r = book(tok, d + "T%02d:%02d" % (19 + (i % 3 == 0), 30 * (i % 2)), "t1", 2, key="race%d" % i)
            return r[0], time.time() - t
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(go, range(50)))
        self.assertLess(max(t for _, t in rs), 5)
        self.assertEqual(set(s for s, _ in rs) - {201, 409}, set())
        allr = call("GET", "/reservations", token=self.a)[1]["reservations"] + call("GET", "/reservations", token=self.b)[1]["reservations"]
        no_overlap(self, allr)

    def test_login_burst(self):
        t = time.time()
        with ThreadPoolExecutor(50) as ex:
            rs = list(ex.map(lambda i: call("POST", "/auth/login", {"email": "a@x.io", "password": "correct horse"})[0], range(50)))
        self.assertEqual(set(rs), {200}); self.assertLess(time.time() - t, 5)


def no_overlap(test, rs):
    rs = [r for r in rs if r["status"] == "confirmed"]
    for i, x in enumerate(rs):
        for y in rs[i + 1:]:
            if x["table_id"] == y["table_id"]:
                test.assertFalse(x["starts_at"] < y["ends_at"] and y["starts_at"] < x["ends_at"] if False else
                                 dt.datetime.fromisoformat(x["starts_at"]) < dt.datetime.fromisoformat(y["ends_at"]) and
                                 dt.datetime.fromisoformat(y["starts_at"]) < dt.datetime.fromisoformat(x["ends_at"]), (x, y))


class Dst(Base):
    def av(self, rid, date, party=1):
        return call("GET", "/availability?restaurant_id=%s&date=%s&party_size=%d" % (rid, date, party))[1]

    def test_berlin(self):
        reset([rest("b", opens="00:00", closes="06:00", dur=90, slot=30)])
        a = login()
        sl = {x["starts_at_local"][11:]: x["starts_at"] for x in self.av("b", "2026-03-29")["slots"]}
        self.assertNotIn("02:00", sl); self.assertNotIn("02:30", sl)
        self.assertTrue(sl["01:30"].endswith("+01:00") and sl["03:00"].endswith("+02:00"))
        err(self, book(a, "2026-03-29T02:30", "t1", 1, "b"), 422, "invalid_local_time")
        sl = self.av("b", "2026-10-25")["slots"]
        times = [x["starts_at_local"][11:] for x in sl]
        self.assertEqual(times.count("02:00"), 1); self.assertEqual(times.count("02:30"), 1)
        self.assertTrue(sl[times.index("02:00")]["starts_at"].endswith("+02:00"))
        self.assertTrue(sl[times.index("03:00")]["starts_at"].endswith("+01:00"))
        s, b, _ = book(a, "2026-10-25T01:30", "t1", 1, "b")
        self.assertEqual((s, b["starts_at"], b["ends_at"]), (201, "2026-10-25T01:30:00+02:00", "2026-10-25T02:00:00+01:00"))
        s, b, _ = book(a, "2026-10-25T02:30", "t2", 1, "b")
        self.assertEqual((s, b["starts_at"]), (201, "2026-10-25T02:30:00+02:00"))
        # 03:00 CET (= 02:00Z) vs 02:30 CEST booking (00:30Z..02:00Z): adjacent, no overlap
        self.assertEqual(book(a, "2026-10-25T03:00", "t2", 1, "b")[0], 201)
        err(self, book(a, "2026-10-25T02:00", "t1", 1, "b"), 409, "table_unavailable")

    def test_new_york(self):
        reset([rest("n", tz="America/New_York", opens="00:00", closes="06:00")])
        a = login()
        times = [x["starts_at_local"][11:] for x in self.av("n", "2026-03-08")["slots"]]
        self.assertNotIn("02:00", times); self.assertNotIn("02:30", times)
        err(self, book(a, "2026-03-08T02:00", "t1", 1, "n"), 422, "invalid_local_time")
        sl = self.av("n", "2026-11-01")["slots"]
        t = [x["starts_at_local"][11:] for x in sl]
        self.assertEqual(t.count("01:30"), 1)
        self.assertTrue(sl[t.index("01:30")]["starts_at"].endswith("-04:00"))
        self.assertTrue(sl[t.index("03:00")]["starts_at"].endswith("-05:00"))
        s, b, _ = book(a, "2026-11-01T01:30", "t1", 1, "n")
        self.assertEqual((s, b["starts_at"]), (201, "2026-11-01T01:30:00-04:00"))
        err(self, call("PATCH", "/reservations/" + b["reference"], {"starts_at_local": "2026-03-08T02:30"}, a), 422, "invalid_local_time")

    def test_same_instant(self):
        reset([rest("b", opens="18:00", closes="23:00"), rest("n", tz="America/New_York", opens="12:00", closes="20:00")])
        a = login()
        x = book(a, "2026-12-01T18:00", "t1", 1, "b")[1]
        y = book(a, "2026-12-01T12:00", "t1", 1, "n")[1]
        self.assertEqual(dt.datetime.fromisoformat(x["starts_at"]), dt.datetime.fromisoformat(y["starts_at"]))


class Moves(Base):
    def setUp(self):
        super().setUp()
        d = future()[:10]
        self.d = d
        self.r1 = book(self.a, d + "T19:00", "t1", 2)[1]
        self.r2 = book(self.a, d + "T19:00", "t2", 2)[1]
        self.r3 = book(self.a, d + "T19:00", "t3", 2)[1]

    def mv(self, moves, key="m", tok=None):
        return call("POST", "/reservation-moves", {"moves": moves}, tok or self.a, key)

    def tables(self):
        return {r["reference"]: r["table_id"] for r in call("GET", "/reservations", token=self.a)[1]["reservations"]}

    def test_swap_rotate_replay(self):
        s, b, _ = self.mv([{"reference": self.r1["reference"], "table_id": "t2"}, {"reference": self.r2["reference"], "table_id": "t1"}])
        self.assertEqual(s, 201, b)
        self.assertEqual([x["table_id"] for x in b["reservations"]], ["t2", "t1"])
        self.assertEqual(b["reservations"][0]["reference"], self.r1["reference"])
        self.assertEqual(self.mv([{"reference": self.r1["reference"], "table_id": "t2"}, {"reference": self.r2["reference"], "table_id": "t1"}])[:2], (200, b))
        err(self, self.mv([{"reference": self.r1["reference"]}]), 409, "idempotency_key_reuse")
        refs = [self.r1["reference"], self.r2["reference"], self.r3["reference"]]
        s, b, _ = self.mv([{"reference": refs[0], "table_id": "t1"}, {"reference": refs[1], "table_id": "t3"}, {"reference": refs[2], "table_id": "t2"}], "rot")
        self.assertEqual(s, 201, b)
        # no-op with unknown fields
        s, b, _ = self.mv([{"reference": refs[0], "zzz": 1}], "noop")
        self.assertEqual((s, b["reservations"][0]["table_id"]), (201, "t1"))

    def test_failures_atomic(self):
        r1, r2, r3 = (x["reference"] for x in (self.r1, self.r2, self.r3))
        before = self.tables()
        d = self.d
        cases = [
            ([{"reference": r1, "table_id": "t3"}], 409, "table_unavailable"),   # unlisted holder
            ([{"reference": r1, "table_id": "t2"}, {"reference": r3, "table_id": "t2"}], 409, "table_unavailable"),
            ([{"reference": r1, "table_id": "t2"}, {"reference": "NOPE0000"}], 404, "not_found"),
            ([{"reference": r1, "table_id": 5}], 400, "malformed_request"),
            ([{"reference": r1, "table_id": "t2"}, {"reference": r2, "party_size": 9}], 422, "party_exceeds_capacity"),
            ([{"reference": r1, "table_id": "zz"}], 404, "not_found"),
            ([{"reference": r1, "starts_at_local": d + "T19:10"}], 422, "not_on_slot_grid"),
            ([], 422, "validation_failed"),
            ([{"reference": r1}, {"reference": r1}], 422, "validation_failed"),
            ([{"reference": r1}] + [{"reference": "X%07d" % i} for i in range(8)], 422, "validation_failed"),
            ([5], 422, "validation_failed"),
            ([{"reference": 5}], 422, "validation_failed"),
            ([{"reference": r1, "table_id": "t2"}, {"reference": r2, "party_size": "x"}], 422, "validation_failed"),
        ]
        for i, (moves, st, code) in enumerate(cases):
            err(self, self.mv(moves, "f%d" % i), st, code)
            self.assertEqual(self.tables(), before)
        err(self, call("POST", "/reservation-moves", {"moves": "x"}, self.a, "x1"), 422, "validation_failed")
        err(self, call("POST", "/reservation-moves", {}, self.a, "x2"), 422, "validation_failed")
        err(self, call("POST", "/reservation-moves", {"moves": [{"reference": r1}]}, None, "x3"), 401, "unauthenticated")
        # failed key reusable
        self.assertEqual(self.mv([{"reference": r1}], "f0")[0], 201)
        # foreign owner
        err(self, self.mv([{"reference": r1}], "o", self.b), 404, "not_found")
        # 8 accepted
        reset([rest(tables=[{"id": "x%d" % i, "label": "x", "capacity": 2} for i in range(8)])])
        a = login()
        refs = [book(a, self.d + "T19:00", "x%d" % i, 1)[1]["reference"] for i in range(8)]
        self.a = a
        self.assertEqual(self.mv([{"reference": x} for x in refs], "eight")[0], 201)

    def test_cancelled_cutoff_restaurants(self):
        r1, r2 = self.r1["reference"], self.r2["reference"]
        call("POST", "/reservations/%s/cancel" % r1, token=self.a)
        err(self, self.mv([{"reference": r1}], "c"), 409, "reservation_cancelled")
        past = book(self.a, "2020-01-01T19:00", "t1")[1]["reference"]
        err(self, self.mv([{"reference": r2, "party_size": 99}, {"reference": past}], "p"), 409, "cutoff_passed" if False else "cutoff_passed") if False else None
        err(self, self.mv([{"reference": r2}, {"reference": past, "party_size": 99}], "p2"), 409, "cutoff_passed")
        reset([rest(), rest("r2")])
        a = login()
        x = book(a, self.d + "T19:00", "t1")[1]["reference"]
        y = book(a, self.d + "T19:00", "t1", rid="r2")[1]["reference"]
        err(self, self.mv([{"reference": x}, {"reference": y}], "dr", a), 422, "validation_failed")

    def test_concurrent(self):
        r1, r2 = self.r1["reference"], self.r2["reference"]
        body = {"moves": [{"reference": r1, "table_id": "t2"}, {"reference": r2, "table_id": "t1"}]}
        with ThreadPoolExecutor(30) as ex:
            rs = list(ex.map(lambda i: call("POST", "/reservation-moves", body, self.a, "same")[0], range(30)))
        self.assertEqual(sorted(rs), [200] * 29 + [201])
        with ThreadPoolExecutor(30) as ex:
            rs = list(ex.map(lambda i: self.mv([{"reference": [r1, r2, self.r3["reference"]][i % 3], "table_id": "t%d" % (1 + i % 3 if i % 2 else 3)}], "c%d" % i)[0], range(30)))
        self.assertEqual(set(rs) - {201, 409}, set())
        no_overlap(self, call("GET", "/reservations", token=self.a)[1]["reservations"])


class ExportImport(Base):
    def test_roundtrip(self):
        d = future()[:10]
        body = {"restaurant_id": "r1", "table_id": "t1", "starts_at_local": d + "T19:00", "party_size": 2}
        s, r1, _ = call("POST", "/reservations", body, self.a, "KEY")
        r2 = book(self.a, d + "T19:00", "t2")[1]
        mvb = {"moves": [{"reference": r2["reference"], "table_id": "t3"}]}
        mv1 = call("POST", "/reservation-moves", mvb, self.a, "MKEY")[1]
        call("POST", "/reservations/%s/cancel" % r1["reference"], token=self.a)
        call("POST", "/reservations", dict(body, party_size=0), self.a, "FAILED")
        s, exp, h = call("GET", "/_test/export")
        self.assertEqual((s, exp["track"], exp["format_version"]), (200, "tablekeeper", 1))
        self.assertNotIn("correct horse", json.dumps(exp))
        before = call("GET", "/reservations", token=self.a)[1]
        call("POST", "/reservations", dict(body, table_id="t3", starts_at_local=d + "T21:00"), self.a, "AFTER")  # after export
        for target in ("same", "reset"):
            if target == "reset":
                reset(restaurants=[rest("zz")], users=[])
                self.assertEqual(call("GET", "/reservations", token=self.a)[0], 401)
            self.assertEqual(call("POST", "/_test/import", exp)[0], 204)
            self.assertEqual(call("POST", "/_test/import", exp)[0], 204)
            self.assertEqual(call("GET", "/reservations", token=self.a)[1], before)
            self.assertEqual(call("POST", "/reservations", body, self.a, "KEY")[:2], (200, r1))
            self.assertEqual(call("POST", "/reservation-moves", mvb, self.a, "MKEY")[:2], (200, mv1))
            err(self, call("POST", "/reservations", dict(body, party_size=3), self.a, "KEY"), 409, "idempotency_key_reuse")
            self.assertEqual(call("POST", "/reservations", dict(body, table_id="t3", starts_at_local=d + "T21:00"), self.a, "FAILED")[0], 201)
            self.assertEqual(call("POST", "/auth/login", {"email": "a@x.io", "password": "correct horse"})[0], 200)
            self.assertEqual(call("GET", "/restaurants")[1]["restaurants"][0]["id"], "r1")
            call("POST", "/_test/import", exp)
        for bad in ({}, dict(exp, track="x"), dict(exp, format_version=2), {"track": "tablekeeper", "format_version": 1},
                    dict(exp, state={"users": {}}), dict(exp, state="x"), dict(exp, state=dict(exp["state"], tokens={"t": "nobody"}))):
            err(self, call("POST", "/_test/import", bad), 422, "validation_failed")
        err(self, call("POST", "/_test/import", raw=b"{"), 400, "malformed_request")
        self.assertEqual(call("GET", "/reservations", token=self.a)[1], before)
        reset(restaurants=[rest("zz")], users=[])
        self.assertEqual(call("GET", "/reservations", token=self.a)[0], 401)


class Misc(Base):
    def test_unknown_fields_and_restaurant_shape(self):
        s, b, _ = call("GET", "/restaurants/r1")
        self.assertEqual(sorted(b), sorted(rest()))
        self.assertEqual(b["tables"], rest()["tables"])
        err(self, call("GET", "/restaurants/zz"), 404, "not_found")
        self.assertEqual(call("POST", "/restaurants", {"id": "x"})[0] // 100, 4)
        reset(restaurants=[dict(rest(), bonus=1)], users=USERS)

    def test_seeded_reservation(self):
        d = future()[:10]
        reset(reservations=[{"id": "seed1", "reference": "SEEDREF1", "user_id": "u_a", "restaurant_id": "r1",
                             "table_id": "t1", "starts_at_local": d + "T19:00", "party_size": 2, "extra": 1}])
        a = login()
        s, b, _ = call("GET", "/reservations/SEEDREF1", token=a)
        self.assertEqual((s, b["reservation_id"], b["status"]), (200, "seed1", "confirmed"))
        err(self, book(a, d + "T19:30", "t1"), 409, "table_unavailable")
        self.assertEqual(call("PATCH", "/reservations/SEEDREF1", {"party_size": 1}, a)[0], 200)
        refs = {book(a, d + "T%02d:00" % h, "t%d" % t, 1)[1]["reference"] for h in (18, 20) for t in (2, 3)}
        self.assertEqual(len(refs), 4)
        err(self, call("POST", "/_test/reset", {"restaurants": [rest()], "users": USERS, "reservations": [
            {"id": "a", "reference": "AAAAAA", "user_id": "u_a", "restaurant_id": "r1", "table_id": "t1", "starts_at_local": d + "T19:00", "party_size": 1},
            {"id": "b", "reference": "BBBBBB", "user_id": "u_a", "restaurant_id": "r1", "table_id": "t1", "starts_at_local": d + "T19:30", "party_size": 1}]}), 422, "validation_failed")

    def test_reference_unique_many(self):
        reset(restaurants=[rest(slot=1, dur=1, opens="00:00", closes="23:59")])
        a = login()
        d = future()[:10]
        def go(i):
            return book(a, d + "T%02d:%02d" % (i // 60, i % 60), "t1", 1, key="u%d" % i)[1]["reference"]
        with ThreadPoolExecutor(20) as ex:
            refs = list(ex.map(go, range(500)))
        self.assertEqual(len(set(refs)), 500)


if __name__ == "__main__":
    unittest.main()
