import json, os, sys, time, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from lib import World, call, fixture, user, k, PW, VIOLATIONS
from conftest import UI
with sync_playwright() as p:
    b = p.chromium.launch()
    w = World(); u = UI(b, "wide"); u.login("ada").home()
    held = []
    u.page.route("**/payments", lambda r: held.append(r))
    u.fill_pay("bob", "2.00", "never answered"); u.t("pay-submit").click()
    t0 = time.time(); seen = None
    while time.time() - t0 < 40:
        u.page.wait_for_timeout(1000)
        if u.t("pay-uncertain").count() or u.t("pay-error").count():
            seen = round(time.time() - t0, 1); break
    print("payment never answered: after", seen, "s -> pay-uncertain", u.t("pay-uncertain").count(), "pay-error", u.t("pay-error").count(), "submit disabled", u.t("pay-submit").is_disabled(), "requests held", len(held), flush=True)
    u.page.unroute("**/payments")
    for r in held:
        try: r.abort()
        except Exception: pass
    if not u.t("pay-submit").is_disabled():
        u.t("pay-submit").click(); u.page.wait_for_timeout(900)
        print("   retry: balance", u.t("wallet-balance").text_content(), "ada", w.bal("ada"), "uncertain", u.t("pay-uncertain").count())
    u.close()
    # request pay whose answer is lost after commit
    reqs = [{"id": "rq1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 700, "note": "", "status": "pending"}]
    w = World(fixture(requests=reqs)); u = UI(b, "wide"); u.login("ada").goto("/requests")
    st = {"n": 0, "seen": []}
    def h(route):
        st["seen"].append((route.request.headers.get("idempotency-key"), route.request.post_data)); st["n"] += 1
        if st["n"] == 1: route.fetch(); route.abort("connectionreset")
        else: route.continue_()
    u.page.route("**/requests/rq1/pay", h)
    u.t("request-pay-rq1").click(); u.page.wait_for_timeout(900)
    print("request pay answer lost: request-error", u.t("request-error").count(), "uncertain elems", u.page.locator("[data-testid$='-uncertain']").evaluate_all("els => els.map(e => e.getAttribute('data-testid'))"), "status", u.t("request-item-rq1").get_attribute("data-status"), "pay button", u.t("request-pay-rq1").count(), "ada", w.bal("ada"), flush=True)
    if u.t("request-pay-rq1").count():
        u.t("request-pay-rq1").click(); u.page.wait_for_timeout(900)
    print("   after retry: status", u.t("request-item-rq1").get_attribute("data-status"), "request-error", u.t("request-error").count(), "ada", w.bal("ada"), "same key", len({s[0] for s in st["seen"]}) == 1, st["seen"])
    # logout leaves no token behind
    u.t("logout-button").click(); u.page.wait_for_timeout(500)
    print("after logout: localStorage", u.page.evaluate("JSON.stringify(Object.assign({}, localStorage))")[:200], "sessionStorage", u.page.evaluate("JSON.stringify(Object.assign({}, sessionStorage))")[:120], "cookies", u.context.cookies())
    u.close(); b.close()
print("violations:", [(v["kind"], v.get("path", "")[:60]) for v in VIOLATIONS])
