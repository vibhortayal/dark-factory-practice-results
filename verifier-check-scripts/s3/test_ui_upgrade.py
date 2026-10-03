"""M2-M4 / L5. A browser that was signed in before an export/import upgrade keeps working afterwards, without reload.
Three ways of putting the browser in front of the earlier service:
  stage1-api   stage-3 pages, API calls answered by the accepted stage-1 container until the import
  stage2-api   stage-3 pages, API calls answered by the accepted stage-2 container until the import
  stage2-pages the page is loaded from the accepted stage-2 container (its own script); after the import every
               request of that browser is answered by the stage-3 service"""
import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from lib import BASE, BASE1, BASEP2, PW, World, call, fixture, k, ok, soft, user


def reroute(u, state):
    """state['api'] / state['pages']: base URL that answers API calls / pages and assets (None = the page's origin)."""

    def handler(route):
        req = route.request
        accept = req.headers.get("accept") or ""
        sp = urlsplit(req.url)
        is_page = req.resource_type == "document" or ("text/html" in accept and req.method == "GET")
        is_asset = req.resource_type in ("script", "stylesheet", "image", "font")
        base = state["pages"] if (is_page or is_asset) else state["api"]
        target = (base + sp.path + (("?" + sp.query) if sp.query else "")) if base else None
        if req.method == "POST" and sp.path == "/payments":
            state["payments"].append((req.headers.get("idempotency-key"), json.loads(req.post_data or "null")))
            if state["lose"] > 0:
                state["lose"] -= 1
                route.fetch(url=target) if target else route.fetch()   # the service commits the payment ...
                route.abort("connectionreset")                          # ... and the browser never hears about it
                return
        if target is None:
            route.continue_()
        else:
            route.fulfill(response=route.fetch(url=target))

    u.page.route("**/*", handler)


def to_stage1(u, state):
    """The stage-2 form of the helper (used by test_n_s2round1): API calls go to the stage-1 container while state['on']."""

    class View(dict):
        def __getitem__(self, key):
            if key == "api":
                return BASE1 if state["on"] else None
            if key == "pages":
                return None
            return state[key]

        def __setitem__(self, key, value):
            state[key] = value

    reroute(u, View())


MODES = {"stage1-api": lambda: (BASE1, BASE, {"api": BASE1, "pages": None}, {"api": None, "pages": None}),
         "stage2-api": lambda: (BASEP2, BASE, {"api": BASEP2, "pages": None}, {"api": None, "pages": None}),
         "stage2-pages": lambda: (BASEP2, BASEP2, {"api": None, "pages": None}, {"api": BASE, "pages": BASE})}


@pytest.mark.parametrize("vpname", ["narrow", "wide"])
@pytest.mark.parametrize("mode", sorted(MODES))
def test_m2_m3_m4_browser_survives_the_upgrade(ui, vpname, mode):
    assert BASE1 and BASEP2, "BASE1 / BASEP2 (containers of the accepted stage-1 and stage-2 images) are not set"
    SRC, page_base, before, after = MODES[mode]()
    reqs = [{"id": "rq_keep", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]
    fx = fixture(requests=reqs)
    old = World(fx, base=SRC)                                     # the earlier service the user is working with
    World(fixture(users=[user("zed", 1)]))                        # the stage-3 service starts with unrelated state
    u = ui(vpname, base=page_base)
    state = {"lose": 1, "payments": [], **before}
    reroute(u, state)
    u.login("ada")                                                # the token comes from the earlier service
    u.goto("/")
    expect(u.t("pay-submit")).to_be_visible()
    u.page.wait_for_timeout(700)
    expect(u.t("wallet-balance")).to_have_text("100.00 EUR")
    expect(u.t("wallet-available")).to_have_text("100.00 EUR")
    assert u.t("wallet-held").count() == 0
    expect(u.t("empty-activity")).to_be_visible()
    assert not u.errors, u.errors
    u.fill_pay("bob", "15.00", "before the upgrade", "private")
    u.t("pay-submit").click()
    expect(u.t("pay-uncertain")).to_be_visible()                  # the earlier service committed, the answer was lost
    assert u.t("pay-error").count() == 0
    assert old.bal("ada") == 8500
    original = old.activity("ada")[0]
    # ---- the upgrade, between two browser requests
    e = call("GET", "/_test/export", base=SRC)
    r = call("POST", "/_test/import", raw=e.content)
    assert r.status_code == 204, f"stage-3 import of the {mode} export: {r.status_code} {r.text[:200]}"
    state.update(after)                                           # from now on the browser talks to stage 3
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
