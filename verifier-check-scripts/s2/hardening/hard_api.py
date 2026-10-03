"""Stage-2 hardening probes over the API (first revision only)."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import World, call, fixture, user, k, seeded_auth, iso, burst, statuses, VIOLATIONS

def show(label, r):
    print(f"{label:66s} -> {r.status_code} {r.text[:110]!r}", flush=True)

base = World().login_all()
for label, exp in [("year 9999 offset -23:59", "9999-12-31T23:59:59-23:59"), ("year 0001 offset +23:59", "0001-01-01T00:00:00+23:59"),
                   ("year 9999 Z", "9999-12-31T23:59:59Z"), ("leap second", "2030-12-31T23:59:60+00:00"),
                   ("lowercase t and z", "2030-01-01t00:00:00z"), ("offset +24:00", "2030-01-01T00:00:00+24:00"),
                   ("offset -00:00", "2030-01-01T00:00:00-00:00"), ("9 fractional digits", "2030-01-01T00:00:00.123456789+00:00"),
                   ("year 10000", "10000-01-01T00:00:00+00:00"), ("space separator", "2030-01-01 00:00:00+00:00"),
                   ("offset without colon", "2030-01-01T00:00:00+0000"), ("60 days ahead", iso(60 * 86400))]:
    fx = fixture(auths=[{**seeded_auth("a1", "ada", "bob", 100), "expires_at": exp}])
    r = call("POST", "/_test/reset", body=fx); show(f"reset seeded expires_at {label}", r)
    if r.status_code == 204:
        w = World(fx, do_reset=False)
        for path in ("/me", "/authorizations"):
            rr = call("GET", path, w.t("ada")); print("     ", path, rr.status_code, rr.text[:150])
        show("      capture", w.capture("bob", "a1", body={"amount": 1, "final": False}))
        show("      export", call("GET", "/_test/export"))
        e = call("GET", "/_test/export")
        if e.status_code == 200: show("      re-import", call("POST", "/_test/import", raw=e.content))
for ttl in (10 ** 9, 10 ** 10, 10 ** 11, 10 ** 12, 10 ** 15, 10 ** 29, 2 ** 31, 315537897599, 315537897600):
    r = call("POST", "/_test/reset", body=fixture(ttl=ttl)); show(f"reset ttl {ttl}", r)
    if r.status_code == 204:
        w = World(fixture(), do_reset=False)
        a = w.authorize("ada", "bob", 5); show("      authorize", a)
        show("      list", call("GET", "/authorizations", w.t("ada")))
        show("      me", call("GET", "/me", w.t("ada")))
        e = call("GET", "/_test/export"); show("      export", e)
        if e.status_code == 200: show("      re-import", call("POST", "/_test/import", raw=e.content))
w = World(fixture(auths=[seeded_auth('a"q\'<i>&x', "ada", "bob", 100), seeded_auth("a b/c?d#e", "bob", "ada", 50)])).login_all()
from urllib.parse import quote
for aid in ('a"q\'<i>&x', "a b/c?d#e"):
    who = "bob" if aid.startswith('a"') else "ada"
    show(f"capture seeded id {aid!r}", call("POST", f"/authorizations/{quote(aid, safe='')}/capture", w.t(who), key=k(), body={"amount": 1, "final": False}))
    show(f"void seeded id {aid!r}", call("POST", f"/authorizations/{quote(aid, safe='')}/void", w.t("ada" if who == "bob" else "bob")))
e = call("GET", "/_test/export"); show("export with odd ids", e); show("re-import", call("POST", "/_test/import", raw=e.content))
# sweeping when the only requests are unauthenticated ones
w = World(fixture(ttl=1)).login_all(); a = w.new_auth("ada", "bob", 1000); time.sleep(1.5)
e = call("GET", "/_test/export"); st = e.json()["state"]
key = next(kk for kk in st if "auth" in kk and isinstance(st[kk], list))
print("export right after expiry, record:", {kk: v for kk, v in st[key][0].items() if kk in ("status", "amount", "captured_amount")})
show("import of that export", call("POST", "/_test/import", raw=e.content)); print("     me:", call("GET", "/me", w.t("ada")).text[:160])
# 50 in flight: expiry sweep racing writers
w = World(fixture(ttl=1)).login_all()
for rnd in range(3):
    rs = burst([(lambda: w.authorize("ada", "bob", 200)) if i % 3 else (lambda: w.pay("ada", "cy", 150)) for i in range(50)])
    print("burst with ttl=1", rnd, statuses(rs), "max", round(max(r.elapsed_s for r in rs), 3)); time.sleep(1.2)
    m = w.wallet("ada"); print("     wallet after expiry:", m["total"], m["available"], m["held"])
w.assert_conserved()
# Accept variants and odd UI requests
for acc in ("text/html, application/json", "application/json, text/html;q=0.1", "text/*", "*/*, text/html", "text/htmlx", "application/xhtml+xml, text/html"):
    r = call("GET", "/requests", w.t("ada"), headers={"Accept": acc}, kind="any"); print(f"GET /requests Accept {acc!r:45s} -> {r.status_code} {r.headers.get('content-type')}")
for path in ("/static/app.js?x=1", "/static/app.js/", "/static/app%2Ejs", "/static/APP.JS", "/index.html", "/ui/index.html", "/static/index.html", "/favicon.ico", "/robots.txt", "/login/", "/split/", "//", "/?", "/authorizations/"):
    r = call("GET", path, headers={"Accept": "text/html"}, kind="any"); print(f"GET {path:28s} -> {r.status_code} {r.headers.get('content-type')}")
r = call("GET", "/static/app.js", headers={"Range": "bytes=0-9", "If-None-Match": "*", "Accept-Encoding": "gzip, br"}, kind="any"); print("asset with Range/If-None-Match:", r.status_code, len(r.content), r.headers.get("content-encoding"), r.headers.get("cache-control"))
print("violations:", [(v["kind"], v["method"], v["path"][:50], v["status"]) for v in VIOLATIONS][:20])
