"""§5 'Requests must not produce 5xx responses' and 'Every 4xx and 5xx response carries this body'.

Ordinary-size malformed inputs only. Each response must be < 500; the envelope and content type are
asserted over the whole request log by the runner (G-ENVELOPE, G-CTYPE)."""
import copy

from vlib import *


def no5(r):
    assert r.status < 500, f"5xx: {r!r}"
    if r.status >= 400:
        e = r.json.get("error") if isinstance(r.json, dict) else None
        assert isinstance(e, dict) and isinstance(e.get("code"), str) and isinstance(e.get("message"), str), f"no envelope: {r!r}"
    return r


JUNK = [None, True, False, 0, -1, 1.5, 10 ** 30, "", " ", "x" * 300, "ünïcödé ✓ 日本", [], [1], {}, {"a": {"b": [None]}}, "null", "\u0000", "'; DROP TABLE x;--"]


@check("A8a", "§5 no 5xx / envelope", "every field of every JSON endpoint replaced by junk values of each JSON type")
def _():
    reset(fixture(reservations=[seed("res_s1", "SEED01", "u_ada", "r_anker", "t_1", f"{FUT}T19:00")]))
    ada = tok("u_ada")
    targets = [("POST", "/auth/signup", {"email": "f@example.com", "password": "fuzz password", "display_name": "F"}, False),
               ("POST", "/auth/login", {"email": EMAIL["u_ada"], "password": PW["u_ada"]}, False),
               ("POST", "/reservations", body(tid="t_3"), True),
               ("PATCH", "/reservations/SEED01", {"table_id": "t_1", "starts_at_local": f"{FUT}T19:00", "party_size": 2}, True),
               ("POST", "/reservation-moves", {"moves": [{"reference": "SEED01", "table_id": "t_1"}]}, True)]
    n = 0
    for m, p, good, auth in targets:
        for f in good:
            for v in JUNK:
                b = dict(good)
                b[f] = v
                no5(call(m, p, json_body=b, token=ada if auth else None, key=newkey()))
                n += 1
    for v in JUNK:
        for f in ("reference", "table_id", "starts_at_local", "party_size"):
            item = {"reference": "SEED01"}
            item[f] = v
            no5(moves(ada, [item]))
    for v in JUNK:   # whole body
        for m, p, _g, auth in targets:
            no5(call(m, p, json_body=v, token=ada if auth else None, key=newkey()))
    expect(call("GET", "/health"), 200)
    assert n > 200


@check("A8b", "§5 no 5xx / envelope", "raw bodies, odd headers, odd paths, methods and query strings")
def _():
    reset(fixture(reservations=[seed("res_s1", "SEED01", "u_ada", "r_anker", "t_1", f"{FUT}T19:00")]))
    ada = tok("u_ada")
    raws = [b"", b" ", b"{", b"}", b"[", b'{"a":1}{"b":2}', b'{"party_size": 1e400}', b'{"party_size": NaN}', b"\xff\xfe\xfd",
            b'{"restaurant_id": "r_anker", "restaurant_id": "r_ny"}', b"[" * 60 + b"]" * 60, b'{"a": "' + b"\\ud800" + b'"}',
            b"\xef\xbb\xbf{}", b'{"party_size": 2,}', b"null", b"12", b'"str"', b"<xml/>", b"a=1&b=2"]
    for p, m in [("/reservations", "POST"), ("/reservation-moves", "POST"), ("/reservations/SEED01", "PATCH"),
                 ("/reservations/SEED01/cancel", "POST"), ("/auth/signup", "POST"), ("/auth/login", "POST"),
                 ("/_test/import", "POST")]:
        for raw in raws:
            no5(call(m, p, raw=raw, token=ada, key=newkey()))
            no5(call(m, p, raw=raw, token=ada, key=newkey(), ctype="text/plain"))
    # reset with raw junk is checked last because it may legitimately succeed for some JSON values
    paths = ["/", "/nope", "/reservations/", "/reservations//cancel", "/reservations/" + "A" * 300, "/reservations/%00", "/reservations/%2F",
             "/reservations/SEED01/cancel/extra", "/restaurants/", "/restaurants/" + "r" * 65, "/restaurants/%F0%9F%8D%95",
             "/restaurants/r_anker/tables", "/availability/", "/_test", "/_test/nope", "/auth", "/health/", "/RESERVATIONS", "/reservations/seed01"]
    for p in paths:
        for m in ("GET", "POST", "PATCH", "PUT", "DELETE"):
            no5(call(m, p, token=ada, key=newkey()))
    for m in ("PUT", "DELETE", "PATCH", "POST"):
        for p in ("/health", "/restaurants", "/restaurants/r_anker", "/availability", "/reservations/SEED01", "/_test/export"):
            if (m, p) != ("PATCH", "/reservations/SEED01"):
                no5(call(m, p, token=ada, key=newkey()))
    for h in ({"Authorization": "Bearer " + "x" * 500}, {"Authorization": "Bearer a b c"}, {"Idempotency-Key": "k y!#$%&'()*+,-./:;<=>?@[]^_`{|}~"},
              {"Content-Type": "application/xml"}, {"Accept": "text/html"}):
        no5(call("POST", "/reservations", json_body=body(tid="t_3"), headers=dict({"Authorization": f"Bearer {ada}",
                                                                                     "Idempotency-Key": newkey()}, **h)))
    qs = [{"restaurant_id": "r_anker", "date": FUT, "party_size": "9" * 30}, {"restaurant_id": "", "date": "", "party_size": ""},
          {"restaurant_id": "r_anker", "date": "0000-00-00", "party_size": "2"}, {"restaurant_id": "r_anker", "date": "9999-12-31", "party_size": "2"},
          {"restaurant_id": "r_anker", "date": "0001-01-01", "party_size": "2"}, {"restaurant_id": "r" * 65, "date": FUT, "party_size": "2"},
          {"restaurant_id": "r_anker", "date": FUT, "party_size": "٤"}, {"restaurant_id": "r_anker", "date": FUT, "party_size": "2", "date ": "x"}]
    for q in qs:
        no5(call("GET", "/availability", params=q))
    no5(call("GET", "/availability?restaurant_id=r_anker&date=%s&party_size=2&party_size=3&date=%s" % (FUT, FUT2)))
    no5(call("GET", "/availability?%zz=1&restaurant_id=r_anker"))
    for d in ("9999-12-31T19:00", "0001-01-01T19:00", "1900-01-02T19:00", "2038-01-19T19:00"):
        no5(book(ada, tid="t_3", local=d))
    for raw in raws:
        no5(call("POST", "/_test/reset", raw=raw))
    reset()
    expect(call("GET", "/health"), 200)


@check("A8c", "§5 no 5xx / envelope; §3.3 reset", "fixtures with wrong types or impossible values: no 5xx at reset or on the requests that follow")
def _():
    base = fixture(reservations=[seed("res_s1", "SEED01", "u_ada", "r_anker", "t_1", f"{FUT}T19:00")])

    def variant(path, v):
        fx = copy.deepcopy(base)
        cur = fx
        for k in path[:-1]:
            cur = cur[k]
        cur[path[-1]] = v
        return fx

    variants = []
    for top in ("users", "restaurants", "reservations"):
        for v in (None, 5, "x", {"a": 1}, [5], [None], [[]], [{}]):
            variants.append(variant((top,), v))
    R0 = ("restaurants", 0)
    for f, vals in [("timezone", ["Mars/Phobos", "", 5, None, "europe/berlin", "+02:00"]),
                    ("slot_minutes", [0, -30, "30", 1.5, None, 10 ** 12]),
                    ("reservation_duration_minutes", [0, -90, "90", None, 10 ** 12]),
                    ("cancellation_cutoff_minutes", [-1, "120", None, 10 ** 12]),
                    ("opening_hours", [None, "x", [None], [{}], [{"weekday": "xyz", "opens": "18:00", "closes": "23:00"}],
                                       [{"weekday": "tue", "opens": "25:00", "closes": "26:00"}],
                                       [{"weekday": "tue", "opens": "23:00", "closes": "18:00"}],
                                       [{"weekday": "tue", "opens": 18, "closes": 23}],
                                       [{"weekday": "tue", "opens": "18:00", "closes": "23:00"}, {"weekday": "tue", "opens": "10:00", "closes": "12:00"}]]),
                    ("tables", [None, "x", [None], [{}], [{"id": "t_1", "label": "1", "capacity": 0}], [{"id": "t_1", "label": "1", "capacity": "4"}],
                                [{"id": "t_1", "label": 1, "capacity": -2}], [table("t_1", 4), table("t_1", 2)]]),
                    ("id", [None, 5, "", "r_ny"]), ("name", [None, 5])]:
        for v in vals:
            variants.append(variant(R0 + (f,), v))
    for f, vals in [("id", [None, 5, "", "u_bob"]), ("email", [None, 5, "nope", EMAIL["u_bob"]]), ("password", [None, 5, "", "short"]),
                    ("display_name", [None, 5])]:
        for v in vals:
            variants.append(variant(("users", 0, f), v))
    for f, vals in [("id", [None, 5, ""]), ("reference", [None, 5, ""]), ("user_id", [None, 5, "u_nope"]), ("restaurant_id", [None, "r_nope"]),
                    ("table_id", [None, "t_nope", "n_1"]), ("starts_at_local", [None, 5, "x", "2026-03-29T02:30", f"{FUT}T03:00", f"{FUT}T19:10"]),
                    ("party_size", [None, 0, -1, "2", 99, 1.5])]:
        for v in vals:
            variants.append(variant(("reservations", 0, f), v))
    two = copy.deepcopy(base)
    two["reservations"].append(seed("res_s2", "SEED02", "u_bob", "r_anker", "t_1", f"{FUT}T19:30"))   # overlaps SEED01
    variants.append(two)
    accepted = 0
    for fx in variants:
        r = no5(call("POST", "/_test/reset", json_body=fx))
        assert r.status in (204, 400, 422), r
        if r.status == 204:
            accepted += 1
        # whatever was accepted must be servable
        rs = no5(call("GET", "/restaurants"))
        if rs.status == 200:
            for x in rs.json["restaurants"]:
                no5(call("GET", f"/restaurants/{x['id']}"))
                no5(avail(x["id"], FUT, 2))
                no5(avail(x["id"], "2026-03-29", 2))
        lg = call("POST", "/auth/login", json_body={"email": EMAIL["u_ada"], "password": PW["u_ada"]})
        no5(lg)
        if lg.status == 200:
            t = lg.json["token"]
            no5(call("GET", "/reservations", token=t))
            no5(get_res(t, "SEED01"))
            no5(book(t, tid="t_2"))
            no5(patch(t, "SEED01", {"party_size": 1}))
            no5(moves(t, [{"reference": "SEED01", "table_id": "t_3"}]))
            no5(cancel(t, "SEED01"))
        no5(call("GET", "/_test/export"))
    reset()
    expect(call("GET", "/health"), 200)
