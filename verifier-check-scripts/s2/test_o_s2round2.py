"""O. Stage-2 fix round 2: checks for the read-ordering code that changed between 54ab7a9 and 4a9c357.
A read is 'withheld' by fetching its answer at once (old state) and delivering it later, as success, 500 or abort."""
import json
import re

import pytest
from playwright.sync_api import expect

from lib import PW, World, call, fixture, k, ok, seeded_auth, user


class Hold:
    def __init__(self, u, pattern):
        self.u, self.on, self.items, self.pat = u, True, [], re.compile(pattern)
        u.page.route(self.pat, self._handler)

    def _handler(self, route):
        req = route.request
        if self.on and req.method == "GET" and req.resource_type != "document":
            self.items.append((route, route.fetch()))
        else:
            route.continue_()

    def wait(self, n=1):
        for _ in range(40):
            if len(self.items) >= n:
                return
            self.u.page.wait_for_timeout(100)
        raise AssertionError(f"the page sent {len(self.items)} matching reads, expected {n}")

    def deliver(self, how):
        for route, resp in self.items:
            if how == "success":
                route.fulfill(response=resp)
            elif how == "500":
                route.fulfill(status=500, content_type="application/json", body='{"error":{"code":"internal_error","message":"x"}}')
            else:
                route.abort("connectionreset")
        self.items = []


def wallet(u):
    held = u.t("wallet-held")
    return (u.t("wallet-balance").text_content().strip(), u.t("wallet-available").text_content().strip(),
            held.text_content().strip() if held.count() else None)


def feed(u):
    return u.page.locator("[data-testid^='activity-item-']").evaluate_all("els => els.map(e => e.getAttribute('data-testid'))")


@pytest.mark.parametrize("first", ["page-load", "refresh-click", "own-payment"])
@pytest.mark.parametrize("second", ["refresh-click", "own-payment"])
@pytest.mark.parametrize("how", ["success", "500", "abort"])
def test_o_home_newest_read_stays(ui, first, second, how):
    w = World()
    u = ui("wide")
    u.expect_5xx = True
    u.login("ada")
    h = Hold(u, r".*/(me|activity)(\?.*)?$")
    if first == "page-load":
        u.page.goto("/", wait_until="domcontentloaded")
        h.wait(1)
    else:
        h.on = False
        u.goto("/")
        expect(u.t("wallet-balance")).to_have_text("100.00 EUR")
        h.on = True
        if first == "refresh-click":
            u.t("wallet-refresh").click()
        else:
            u.fill_pay("bob", "1.00", "first action")
            u.t("pay-submit").click()
        h.wait(1)
    u.page.wait_for_timeout(400)
    h.on = False
    # another client moves money and places a hold
    ok(w.pay("ada", "cy", 2500, note="elsewhere"), 201)
    w.new_auth("ada", "dan", 1000)
    expect(u.t("wallet-refresh")).to_be_visible()
    if second == "refresh-click":
        u.t("wallet-refresh").click()
    else:
        if first == "own-payment":
            expect(u.t("pay-submit")).to_be_enabled(timeout=20000)
        if first == "page-load":
            # while the first read is pending the screen is in its loading state and has no pay form yet
            # (no statement requires one); an explicit refresh completes the screen, then the payment follows
            u.t("wallet-refresh").click()
            expect(u.t("wallet-balance")).to_have_text("75.00 EUR", timeout=20000)
        u.fill_pay("bob", "2.00", "second action")
        u.t("pay-submit").click()
    paid = (100 if first == "own-payment" else 0) + (200 if second == "own-payment" else 0)
    total = 10000 - 2500 - paid
    money = lambda n: f"{n // 100}.{n % 100:02d} EUR"  # noqa: E731
    expect(u.t("wallet-balance")).to_have_text(money(total), timeout=20000)
    expect(u.t("wallet-available")).to_have_text(money(total - 1000))
    expect(u.t("wallet-held")).to_have_text("10.00 EUR")
    api = [f"activity-item-{p['payment_id']}" for p in w.activity("ada")]
    expect(u.page.locator("[data-testid^='activity-item-']")).to_have_count(len(api))
    h.deliver(how)                       # the earlier answers arrive last
    u.page.wait_for_timeout(1000)
    assert wallet(u) == (money(total), money(total - 1000), "10.00 EUR"), f"{first} -> {second}, earlier read delivered as {how}"
    assert u.amount("wallet-balance") == total and u.amount("wallet-available") == total - 1000
    assert feed(u) == api
    expect(u.t("wallet-refresh")).to_be_visible()
    assert w.wallet("ada")["total"] == total
    assert not u.errors, u.errors


@pytest.mark.parametrize("how", ["success", "abort"])
def test_o_only_the_feed_read_is_late(ui, vp, how):
    w = World()
    u = ui(vp).login("ada")
    h = Hold(u, r".*/activity(\?.*)?$")
    u.page.goto("/", wait_until="domcontentloaded")
    h.wait(1)
    expect(u.t("wallet-balance")).to_have_text("100.00 EUR")      # the wallet does not wait for the feed
    h.on = False
    p = ok(w.pay("bob", "ada", 500, note="new"), 201)
    u.t("wallet-refresh").click()
    expect(u.t(f"activity-item-{p['payment_id']}")).to_be_visible()
    expect(u.t("wallet-balance")).to_have_text("105.00 EUR")
    h.deliver(how)
    u.page.wait_for_timeout(900)
    expect(u.t(f"activity-item-{p['payment_id']}")).to_be_visible()
    assert feed(u) == [f"activity-item-{p['payment_id']}"]
    assert u.t("empty-activity").count() == 0 or not u.t("empty-activity").is_visible()
    expect(u.t("wallet-balance")).to_have_text("105.00 EUR")
    assert not u.errors, u.errors


@pytest.mark.parametrize("how", ["success", "500", "abort"])
def test_o_requests_list_newest_read_stays(ui, how):
    reqs = [{"id": "rq_a", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 100, "note": "", "status": "pending"},
            {"id": "rq_b", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 200, "note": "", "status": "pending"},
            {"id": "rq_out", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 300, "note": "", "status": "pending"}]
    w = World(fixture(requests=reqs))
    u = ui("wide")
    u.expect_5xx = True
    u.login("ada")
    h = Hold(u, r".*/requests(\?.*)?$")
    u.page.goto("/requests", wait_until="domcontentloaded")
    h.wait(1)
    u.page.wait_for_timeout(400)
    h.on = False
    # elsewhere: one request is cancelled by its requester, a new one arrives
    assert ok(call("POST", "/requests/rq_a/cancel", w.t("bob")), 200)["status"] == "cancelled"
    new = w.new_request("cy", "ada", 400)
    # the page reads again (a full navigation is one of the allowed mechanisms for the user; here: reload)
    u.page.evaluate("() => { const b = document.querySelector(\"[data-testid='wallet-refresh']\"); if (b) b.click(); }")
    u.page.wait_for_timeout(300)
    if u.t("request-item-rq_b").count() == 0:
        # no list yet (its first read is still withheld): act through the API-independent path, a reload
        u.page.goto("/requests", wait_until="domcontentloaded")
    expect(u.t("request-item-rq_a")).to_have_attribute("data-status", "cancelled", timeout=15000)
    expect(u.t(f"request-item-{new['request_id']}")).to_be_visible()
    u.t("request-decline-rq_b").click()
    expect(u.t("request-item-rq_b")).to_have_attribute("data-status", "declined")
    h.deliver(how)
    u.page.wait_for_timeout(1000)
    by = {r["request_id"]: r["status"] for r in w.requests("ada")}
    for rid, status in by.items():
        expect(u.t(f"request-item-{rid}")).to_have_attribute("data-status", status)
    assert u.t("request-pay-rq_a").count() == 0 and u.t("request-pay-rq_b").count() == 0
    assert u.page.locator("[data-testid^='request-item-']").count() == len(by)
    assert not u.errors, u.errors


@pytest.mark.parametrize("how", ["success", "500", "abort"])
def test_o_authorizations_newest_read_stays(ui, how):
    w = World(fixture(auths=[seeded_auth("a_in", "bob", "ada", 1000), seeded_auth("a_out", "ada", "cy", 2000)]))
    u = ui("wide")
    u.expect_5xx = True
    u.login("ada")
    u.goto("/authorizations")
    expect(u.t("authorization-item-a_in")).to_have_attribute("data-status", "open")
    h = Hold(u, r".*/(me|authorizations)(\?.*)?$")
    u.t("authorization-capture-amount-a_in").fill("4.00")
    u.t("authorization-capture-a_in").click()            # own action: its refresh reads are withheld
    h.wait(1)
    u.page.wait_for_timeout(500)
    h.on = False
    assert ok(w.void("ada", "a_out"), 200)["status"] == "voided"      # elsewhere
    u.fill_pay("dan", "3.00", "new hold", prefix="authorize")
    u.t("authorize-submit").click()                      # a second own action reads the newest state
    expect(u.t("authorization-item-a_out")).to_have_attribute("data-status", "voided", timeout=20000)
    expect(u.t("authorization-item-a_in")).to_have_attribute("data-status", "captured")
    api = w.auths("ada")
    expect(u.page.locator("[data-testid^='authorization-item-']")).to_have_count(len(api))
    m = w.wallet("ada")
    money = lambda n: f"{n // 100}.{n % 100:02d} EUR"  # noqa: E731
    h.deliver(how)
    u.page.wait_for_timeout(1000)
    for a in api:
        expect(u.t(f"authorization-item-{a['authorization_id']}")).to_have_attribute("data-status", a["status"])
    assert u.t("authorization-void-a_out").count() == 0 and u.t("authorization-capture-a_in").count() == 0
    if u.t("wallet-available").count():
        assert wallet(u) == (money(m["total"]), money(m["available"]), money(m["held"]) if m["held"] else None)
    assert (m["total"], m["held"]) == (10400, 300)
    assert not u.errors, u.errors


def test_o_late_boot_read_on_other_screens_keeps_the_header(ui):
    w = World()
    u = ui("wide").login("ada")
    for path, marker in (("/requests", "empty-requests"), ("/split", "split-amount"), ("/authorizations", "empty-authorizations")):
        h = Hold(u, r".*/me(\?.*)?$")
        u.page.goto(path, wait_until="domcontentloaded")
        h.wait(1)
        h.deliver("success")
        expect(u.t("current-user")).to_be_visible()
        expect(u.t("current-handle")).to_have_text("ada")
        expect(u.t(marker)).to_be_visible()
        u.page.unroute(h.pat)
    assert not u.errors, u.errors
