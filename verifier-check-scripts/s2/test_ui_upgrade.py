"""M2-M4. A browser that was signed in against the stage-1 service keeps working after the stage-1 export is
imported into stage 2. Before the upgrade the page's API calls are answered by the stage-1 container; the pages
themselves always come from the stage-2 service (stage 1 has no screens)."""
import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from lib import BASE, BASE1, PW, World, call, fixture, k, ok, soft, user


def to_stage1(u, state):
    """Answer the page's API calls from the stage-1 container; optionally lose the answer of POST /payments."""

    def handler(route):
        req = route.request
        accept = req.headers.get("accept") or ""
        path = urlsplit(req.url).path
        is_page = req.resource_type == "document" or ("text/html" in accept and req.method == "GET")
        is_asset = req.resource_type in ("script", "stylesheet", "image", "font")
        if is_page or is_asset or not state["on"]:
            route.continue_()
            return
        target = BASE1 + path + (("?" + urlsplit(req.url).query) if urlsplit(req.url).query else "")
        if req.method == "POST" and path == "/payments":
            state["payments"].append((req.headers.get("idempotency-key"), json.loads(req.post_data or "null")))
            if state["lose"] > 0:
                state["lose"] -= 1
                route.fetch(url=target)          # stage 1 commits the payment ...
                route.abort("connectionreset")   # ... and the browser never hears about it
                return
        resp = route.fetch(url=target)
        route.fulfill(response=resp)

    u.allow_origin = "{0.scheme}://{0.netloc}".format(urlsplit(BASE1))
    u.page.route("**/*", handler)


@pytest.mark.parametrize("vpname", ["narrow", "wide"])
def test_m2_m3_m4_browser_survives_the_upgrade(ui, vpname):
    assert BASE1, "BASE1 (a container of the accepted stage-1 image) is not set"
    reqs = [{"id": "rq_keep", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]
    fx = fixture(requests=reqs)
    old = World(fx, base=BASE1)                                   # the stage-1 service the user is working with
    World(fixture(users=[user("zed", 1)]))                        # the stage-2 service starts with unrelated state
    u = ui(vpname)
    state = {"on": True, "lose": 1, "payments": []}
    to_stage1(u, state)
    u.login("ada")                                                # the token comes from stage 1
    u.goto("/")
    expect(u.t("pay-submit")).to_be_visible()
    u.page.wait_for_timeout(700)
    # finding 1 of the first stage-2 verdict: before the upgrade the screen shows balance and feed from stage-1 answers
    expect(u.t("wallet-balance")).to_have_text("100.00 EUR")
    expect(u.t("wallet-available")).to_have_text("100.00 EUR")
    assert u.t("wallet-held").count() == 0
    expect(u.t("empty-activity")).to_be_visible()
    assert not u.errors, u.errors
    u.fill_pay("bob", "15.00", "before the upgrade", "private")
    u.t("pay-submit").click()
    expect(u.t("pay-uncertain")).to_be_visible()                  # stage 1 committed, the answer was lost
    assert u.t("pay-error").count() == 0
    assert old.bal("ada") == 8500
    original = old.activity("ada")[0]
    # ---- the upgrade, between two browser requests
    e = call("GET", "/_test/export", base=BASE1)
    r = call("POST", "/_test/import", raw=e.content)
    assert r.status_code == 204, f"stage-2 import of the stage-1 export: {r.status_code} {r.text[:200]}"
    state["on"] = False                                           # from now on the page talks to stage 2
    # ---- same page, no reload: the unchanged form is retried with the same key and body
    u.requests.clear()
    u.t("pay-submit").click()
    expect(u.t("pay-uncertain")).to_have_count(0)
    expect(u.t("pay-error")).to_have_count(0)
    expect(u.t("wallet-balance")).to_have_text("85.00 EUR")      # the imported balance: the money moved once
    retry = [r for r in u.requests if r.method == "POST" and urlsplit(r.url).path == "/payments"]
    assert len(retry) == 1
    assert (retry[0].headers.get("idempotency-key"), json.loads(retry[0].post_data)) == state["payments"][0], \
        "the retry after the upgrade did not keep key and body"
    expect(u.t(f"activity-item-{original['payment_id']}")).to_be_visible()     # the original payment, recovered
    assert u.page.locator("[data-testid^='activity-item-']").count() == 1
    new = World(fx, do_reset=False)
    new.tok = dict(old.tok)
    assert new.bal("ada") == 8500 and new.bal("bob") == 4000
    assert [p["payment_id"] for p in new.activity("ada")] == [original["payment_id"]]
    # M2: still signed in, on this page and after navigating
    expect(u.t("current-user")).to_be_visible()
    expect(u.t("current-handle")).to_have_text("ada")
    # M3: the pending request from before the upgrade is payable on the request screen
    u.goto("/requests")
    expect(u.t("current-user")).to_be_visible()
    expect(u.t("request-item-rq_keep")).to_have_attribute("data-status", "pending")
    u.t("request-pay-rq_keep").click()
    expect(u.t("request-item-rq_keep")).to_have_attribute("data-status", "paid")
    assert u.t("request-error").count() == 0
    assert new.bal("ada") == 7300
    # the stage-2 additions work for the upgraded account
    u.goto("/")
    expect(u.t("wallet-available")).to_have_text("73.00 EUR")
    assert u.t("wallet-held").count() == 0
    u.goto("/authorizations")
    expect(u.t("empty-authorizations")).to_be_visible()
    assert not u.errors, u.errors
