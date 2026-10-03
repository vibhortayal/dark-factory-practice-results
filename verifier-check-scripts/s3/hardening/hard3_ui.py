import sys, re, json
sys.path.insert(0, "/home/ubuntu/nightshift-claude-run-5/band-work/verifier/s3")
from playwright.sync_api import sync_playwright, expect
from lib import *
from conftest import UI
F = []
def chk(cond, name, **kw):
    if not cond: F.append((name, kw)); print("FINDING", name, kw)
    return cond
with sync_playwright() as p:
    br = p.chromium.launch()
    for vp in ("narrow", "wide"):
        for cur, minor, typed, expect_amount in (("EUR", 2, "15.00", 1500), ("JPY", 0, "15", 15), ("JPY", 0, "15.5", None), ("BHD", 3, "1.234", 1234)):
            w = World(fixture(currency=cur, minor=minor))
            u = UI(br, vp); u.login("ada")
            held = []
            u.page.route(re.compile(r".*/me(\?.*)?$"), lambda route: held.append(route) if route.request.resource_type != "document" else route.continue_())
            u.page.goto("/", wait_until="domcontentloaded")
            u.page.wait_for_timeout(600)
            for form in ("pay", "request", "authorize"):
                chk(u.t(f"{form}-submit").count() == 1 and u.t(f"{form}-amount").is_visible(), "form-missing-while-loading", form=form, vp=vp)
            chk(u.t("wallet-refresh").count() == 1, "refresh-missing-while-loading")
            chk(u.page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), "sideways-scroll-while-loading", vp=vp)
            u.fill_pay("bob", typed, "early")
            u.requests.clear()
            u.t("pay-submit").click()
            u.t("pay-submit").click(timeout=1500) if u.t("pay-submit").is_enabled() else None
            u.page.wait_for_timeout(500)
            early = u.sent("POST", "/payments")
            for route in held: route.continue_()
            held.clear()
            u.page.unroute(re.compile(r".*/me(\?.*)?$"))
            u.page.wait_for_timeout(1500)
            posts = u.sent("POST", "/payments")
            bodies = [json.loads(r.post_data) for r in posts]
            keys = {r.headers.get("idempotency-key") for r in posts}
            feed = w.activity("ada")
            if expect_amount is None:
                chk(not posts and not feed and u.t("pay-error").count() == 1, "bad-amount-for-late-currency", cur=cur, posts=bodies, err=u.t("pay-error").count())
            else:
                chk(all(b["amount"] == expect_amount for b in bodies) and len(keys) <= 1 and len(feed) == 1 and feed[0]["amount"] == expect_amount,
                    "early-submit", cur=cur, typed=typed, bodies=bodies, keys=len(keys), feed=[f["amount"] for f in feed], early=len(early))
                chk(u.t("pay-error").count() == 0 and u.t("pay-uncertain").count() == 0, "early-submit-error-shown", cur=cur)
                chk(u.t("pay-amount").input_value() == typed and u.t("pay-handle").input_value() == "bob", "form-not-kept")
            chk(not u.errors, "script-error", errors=u.errors)
            u.close()
    # the first read fails for good: forms still usable after a refresh
    w = World()
    u = UI(br, "wide"); u.expect_5xx = True; u.login("ada")
    n = {"c": 0}
    def flaky(route):
        if route.request.resource_type == "document": return route.continue_()
        n["c"] += 1
        route.fulfill(status=500, content_type="application/json", body='{"error":{"code":"internal_error","message":"x"}}') if n["c"] <= 1 else route.continue_()
    u.page.route(re.compile(r".*/me(\?.*)?$"), flaky)
    u.page.goto("/", wait_until="domcontentloaded"); u.page.wait_for_timeout(800)
    u.fill_pay("bob", "2.50", "after a failed read")
    u.t("pay-submit").click(); u.page.wait_for_timeout(1500)
    feed = w.activity("ada")
    shown = (u.t("pay-error").count(), u.t("pay-uncertain").count())
    chk((len(feed) == 1 and feed[0]["amount"] == 250) or (len(feed) == 0 and shown[0] == 1), "submit-after-failed-first-read", feed=[f["amount"] for f in feed], shown=shown)
    u.t("wallet-refresh").click(); u.page.wait_for_timeout(800)
    chk(u.t("wallet-balance").count() == 1 and u.t("wallet-balance").text_content().strip() in ("100.00 EUR", "97.50 EUR"), "refresh-after-failed-read", text=u.t("wallet-balance").text_content() if u.t("wallet-balance").count() else None)
    chk(not u.errors, "script-error", errors=u.errors)
    br.close()
print("VIOLATIONS", [(v["kind"], v.get("path"), v.get("status"), v.get("body")) for v in VIOLATIONS][:10]); print("FINDINGS", len(F), F)
