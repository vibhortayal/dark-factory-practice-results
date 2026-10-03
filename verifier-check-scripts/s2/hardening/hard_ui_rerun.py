"""Stage-2 hardening probes in the browser (first revision only)."""
import json, os, sys, time, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from lib import World, call, fixture, user, k, seeded_auth, iso, PW, VIOLATIONS
from conftest import UI

def gets(u, path): return len([r for r in u.requests if r.method == "GET" and urlsplit(r.url).path == path])

with sync_playwright() as p:
    b = p.chromium.launch()
    # 1. holds expiring far in the future: does the page's expiry timer overflow and spin?
    for days in (1, 20, 30, 60, 3650):
        w = World(fixture(auths=[seeded_auth("a1", "ada", "bob", 100, expires_in=days * 86400), seeded_auth("a2", "bob", "ada", 100, expires_in=days * 86400)]))
        for path in ("/", "/authorizations"):
            u = UI(b, "wide"); u.login("ada"); u.goto(path); u.page.wait_for_timeout(600)
            n0 = (gets(u, "/me"), gets(u, "/authorizations"), gets(u, "/activity")); u.page.wait_for_timeout(3000)
            n1 = (gets(u, "/me"), gets(u, "/authorizations"), gets(u, "/activity"))
            print(f"hold expiring in {days:5d} days, page {path:16s}: API reads in 3 idle seconds (me, authorizations, activity): {tuple(b_ - a_ for a_, b_ in zip(n0, n1))} errors={u.errors}", flush=True)
            u.close()
    # 2. the service is reset while a page is signed in
    w = World(); u = UI(b, "wide"); u.login("ada").home(); World(fixture(users=[user("zed", 1)]))
    u.t("wallet-refresh").click(); u.page.wait_for_timeout(1200)
    print("after reset + refresh: url", urlsplit(u.page.url).path, "current-user", u.t("current-user").count(), "login form", u.t("login-email").count(), "balance", u.t("wallet-balance").count(), "errors", u.errors, flush=True)
    u.fill_pay("bob", "1.00", "x") if u.t("pay-submit").count() else None
    if u.t("pay-submit").count():
        u.t("pay-submit").click(); u.page.wait_for_timeout(800)
        print("   pay after reset: pay-error", u.t("pay-error").count(), "pay-uncertain", u.t("pay-uncertain").count(), "url", urlsplit(u.page.url).path)
    u.close()
    # 3. reads fail (network) on each screen: is there an error state, and no script error?
    w = World(); u = UI(b, "narrow"); u.login("ada")
    u.page.route(re.compile(r".*/(me|activity|requests|authorizations)(\?.*)?$"), lambda r: r.abort("connectionreset") if r.request.resource_type != "document" else r.continue_())
    for path in ("/", "/requests", "/authorizations", "/split"):
        u.goto(path); u.page.wait_for_timeout(900)
        txt = u.page.inner_text("main") if u.page.locator("main").count() else u.page.inner_text("body")
        print(f"reads aborted on {path:16s}: text {txt[:170]!r} errors={u.errors}", flush=True)
        u.shot(f"hard-read-failure-{path.strip('/') or 'home'}")
    u.close()
    # 4. reads answer 500 / garbage
    w = World(); u = UI(b, "wide"); u.expect_5xx = True; u.login("ada")
    u.page.route(re.compile(r".*/me(\?.*)?$"), lambda r: r.fulfill(status=500, content_type="application/json", body='{"error":{"code":"internal_error","message":"x"}}') if r.request.resource_type != "document" else r.continue_())
    u.goto("/"); u.page.wait_for_timeout(900)
    print("GET /me 500 on home: balance", u.t("wallet-balance").count(), "text", u.page.inner_text("main")[:120].replace("\n", " | "), "errors", u.errors, flush=True)
    u.close()
    # 5. ids and handles with markup and quotes on every list
    odd = ['a"q\'<i>&x', "sp ace/slash?q#h", "<img src=x onerror=window.__xss=1>", "x" * 64, "ünï😀"]
    pays = [{"id": i, "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 5, "note": i, "visibility": "public"} for i in odd]
    reqs = [{"id": i, "requester_id": "u_bob", "payer_id": "u_ada", "amount": 5, "note": i, "status": "pending"} for i in odd]
    auths = [seeded_auth(i, "bob", "ada", 5, note=i) for i in odd]
    w = World(fixture(payments=pays, requests=reqs, auths=auths)); u = UI(b, "wide"); u.login("ada")
    u.goto("/"); u.page.wait_for_timeout(600)
    print("odd ids feed:", [u.t(f"activity-item-{i}").count() for i in odd], "xss", u.page.evaluate("window.__xss"), flush=True)
    u.goto("/requests"); u.page.wait_for_timeout(600)
    print("odd ids requests:", [u.t(f"request-item-{i}").count() for i in odd], [u.t(f"request-pay-{i}").count() for i in odd])
    for i in odd[:3]:
        u.t(f"request-pay-{i}").click(); u.page.wait_for_timeout(500)
    print("   paid:", [u.t(f"request-item-{i}").get_attribute("data-status") for i in odd], "request-error", u.t("request-error").count())
    u.goto("/authorizations"); u.page.wait_for_timeout(600)
    print("odd ids authorizations:", [u.t(f"authorization-item-{i}").count() for i in odd], [u.t(f"authorization-capture-amount-{i}").count() for i in odd])
    for i in odd[:3]:
        u.t(f"authorization-capture-{i}").click(); u.page.wait_for_timeout(500)
    print("   captured:", [u.t(f"authorization-item-{i}").get_attribute("data-status") for i in odd], "authorization-error", u.t("authorization-error").count(), "xss", u.page.evaluate("window.__xss"), "errors", u.errors, flush=True)
    u.close()
    # 6. typing while a refresh lands; submit while a refresh is pending; two forms at once
    w = World(); u = UI(b, "wide"); u.login("ada").home()
    u.fill_pay("bob", "1.00", "a"); u.t("request-handle").fill("bob"); u.t("request-amount").fill("2.00")
    u.page.evaluate("""() => { document.querySelector("[data-testid='pay-submit']").click(); document.querySelector("[data-testid='request-submit']").click();
                               document.querySelector("[data-testid='wallet-refresh']").click(); document.querySelector("[data-testid='pay-submit']").click(); }""")
    u.page.wait_for_timeout(1200)
    print("pay + request + refresh at once: ada", w.bal("ada"), "requests", len(w.requests("ada")), "balance text", u.t("wallet-balance").text_content(), "pay-error", u.t("pay-error").count(), "request-error", u.t("request-error").count(), "values", u.t("pay-amount").input_value(), u.t("request-amount").input_value(), "errors", u.errors, flush=True)
    u.close()
    b.close()
print("violations:", [(v["kind"], v.get("path", "")[:60], v.get("body", "")[:80]) for v in VIOLATIONS][:20])
