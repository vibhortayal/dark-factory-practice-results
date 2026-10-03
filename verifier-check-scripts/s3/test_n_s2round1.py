"""N. Stage-2 fix round 1: checks for the code that changed between 3ba3276 and 54ab7a9
(tolerant reads and independent panels in the pages, Accept parsing, icon, capture without a body)."""
import json
import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from lib import BASE, BASE1, PW, World, call, check_payment, err, fixture, k, ok, seeded_auth, soft, user
from test_ui_upgrade import to_stage1

ROUTES = ["/", "/requests", "/split", "/authorizations", "/signup", "/login"]


# ---------------------------------------------------------------- finding 1: the pages on stage-1 answers

def stage1_world():
    assert BASE1, "BASE1 (a container of the accepted stage-1 image) is not set"
    pays = [{"id": "p_seed_pub", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 500, "note": "coffee ☕", "visibility": "public"},
            {"id": "p_seed_prv", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 70, "note": "", "visibility": "private"}]
    reqs = [{"id": "rq_in", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
            {"id": "rq_out", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 300, "note": "", "status": "pending"},
            {"id": "rq_done", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 5, "note": "", "status": "declined"}]
    return World(fixture(payments=pays, requests=reqs), base=BASE1)


@pytest.mark.parametrize("vpname", ["narrow", "wide"])
def test_n1_every_screen_works_on_stage1_answers(ui, vpname):
    old = stage1_world()
    World(fixture(users=[user("zed", 1)]))
    u = ui(vpname)
    to_stage1(u, {"on": True, "lose": 0, "payments": []})
    u.login("ada")
    for path in ROUTES:
        u.goto(path)
        expect(u.t("current-user")).to_be_visible()
        expect(u.t("current-handle")).to_have_text("ada")
        u.page.wait_for_timeout(700)
        assert not u.errors, f"script error on {path} against stage-1 answers: {u.errors}"
        assert u.t("page-error").count() == 0, f"error banner on {path}"
    # home: balance, available, no held, feed, refresh, pay
    u.goto("/")
    expect(u.t("wallet-balance")).to_have_text("100.00 EUR")
    assert u.amount("wallet-balance") == 10000
    expect(u.t("wallet-available")).to_have_text("100.00 EUR")
    assert u.t("wallet-held").count() == 0
    api = old.activity("ada")
    expect(u.page.locator("[data-testid^='activity-item-']")).to_have_count(2)
    dom = u.t("activity-list").locator("[data-testid^='activity-item-']").evaluate_all("els => els.map(e => e.getAttribute('data-testid'))")
    assert dom == [f"activity-item-{p['payment_id']}" for p in api]
    expect(u.t("activity-amount-p_seed_pub")).to_have_text("5.00 EUR")
    assert u.t("activity-note-p_seed_pub").text_content() == "coffee ☕"
    expect(u.t("activity-item-p_seed_prv")).to_have_attribute("data-visibility", "private")
    u.fill_pay("bob", "15.5", "on stage 1")
    u.t("pay-submit").click()
    expect(u.t("wallet-balance")).to_have_text("84.50 EUR")
    expect(u.t("wallet-available")).to_have_text("84.50 EUR")
    expect(u.page.locator("[data-testid^='activity-item-']")).to_have_count(3)
    u.t("pay-submit").click()
    u.page.wait_for_timeout(400)
    assert old.bal("ada") == 8450
    u.fill_pay("bob", "500.00", "too much")
    u.t("pay-submit").click()
    expect(u.t("pay-error")).to_be_visible()
    ok(old.pay("bob", "ada", 100), 201)
    u.t("wallet-refresh").click()
    expect(u.t("wallet-balance")).to_have_text("85.50 EUR")
    # requests and split
    u.goto("/requests")
    expect(u.t("request-item-rq_in")).to_have_attribute("data-status", "pending")
    expect(u.t("request-amount-rq_in")).to_have_text("12.00 EUR")
    assert u.t("incoming-list").get_by_test_id("request-item-rq_in").count() == 1
    assert u.t("outgoing-list").get_by_test_id("request-item-rq_out").count() == 1
    u.t("request-cancel-rq_out").click()
    expect(u.t("request-item-rq_out")).to_have_attribute("data-status", "cancelled")
    u.t("request-pay-rq_in").click()
    expect(u.t("request-item-rq_in")).to_have_attribute("data-status", "paid")
    assert old.bal("ada") == 7350
    u.goto("/split")
    u.t("split-amount").fill("10.00")
    u.t("split-handles").fill("ada,bob,cy")
    expect(u.t("split-share-ada")).to_have_text("3.34 EUR")
    u.t("split-submit").click()
    expect(u.t("split-error")).to_have_count(0)
    u.page.wait_for_timeout(400)
    assert len([r for r in old.requests("ada") if r["note"] == "" and r["amount"] == 333]) == 2
    # the authorisation screen has no counterpart on stage 1: a message, the chrome, no script error
    u.goto("/authorizations")
    expect(u.t("current-user")).to_be_visible()
    u.page.wait_for_timeout(700)
    assert u.page.locator("main").inner_text().strip() != ""
    assert u.page.locator("[data-testid^='authorization-item-']").count() == 0
    assert not u.errors, u.errors
    assert u.page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


# ---------------------------------------------------------------- tolerant reads and independent panels

ME_VARIANTS = {
    "stage-1 shape": lambda m: {kk: v for kk, v in m.items() if kk not in ("total", "available", "held")},
    "no held": lambda m: {kk: v for kk, v in m.items() if kk != "held"},
    "no available": lambda m: {kk: v for kk, v in m.items() if kk != "available"},
    "no total": lambda m: {kk: v for kk, v in m.items() if kk != "total"},
    "extra members": lambda m: {**m, "tier": "gold", "limits": {"daily": 5}},
}


@pytest.mark.parametrize("name", list(ME_VARIANTS))
def test_n1_me_with_missing_or_extra_members(ui, name):
    w = World()
    ok(w.pay("bob", "ada", 500, note="feed item"), 201)
    u = ui("wide").login("ada")

    def handler(route):
        resp = route.fetch()
        body = ME_VARIANTS[name](resp.json()) if resp.status == 200 else resp.json()
        route.fulfill(status=resp.status, content_type="application/json; charset=utf-8", body=json.dumps(body))

    u.page.route(re.compile(r".*/me(\?.*)?$"), handler)
    u.goto("/")
    expect(u.t("wallet-balance")).to_have_text("105.00 EUR")
    expect(u.t("wallet-available")).to_have_text("105.00 EUR")
    expect(u.page.locator("[data-testid^='activity-item-']")).to_have_count(1)
    u.fill_pay("bob", "5.00", "still works")
    u.t("pay-submit").click()
    expect(u.t("wallet-balance")).to_have_text("100.00 EUR")
    assert not u.errors, u.errors


@pytest.mark.parametrize("broken,kind", [("activity", "abort"), ("activity", "500"), ("activity", "null"), ("activity", "html"),
                                         ("me", "abort"), ("me", "500"), ("me", "array")])
def test_n1_one_failed_read_does_not_take_the_screen_down(ui, broken, kind):
    w = World(fixture(auths=[seeded_auth("a1", "ada", "bob", 2000)]))
    ok(w.pay("bob", "ada", 500, note="feed item"), 201)
    u = ui("wide")
    u.expect_5xx = True
    u.login("ada")
    state = {"on": True}

    def handler(route):
        if not state["on"] or route.request.resource_type == "document":
            route.continue_()
        elif kind == "abort":
            route.abort("connectionreset")
        elif kind == "500":
            route.fulfill(status=500, content_type="application/json", body='{"error":{"code":"internal_error","message":"x"}}')
        elif kind == "null":
            route.fulfill(status=200, content_type="application/json", body="null")
        elif kind == "array":
            route.fulfill(status=200, content_type="application/json", body="[1, 2]")
        else:
            route.fulfill(status=200, content_type="text/html", body="<html><body>proxy error</body></html>")

    u.page.route(re.compile(r".*/%s(\?.*)?$" % broken), handler)
    u.goto("/")
    u.page.wait_for_timeout(1200)
    assert not u.errors, f"script error with {broken} {kind}: {u.errors}"
    expect(u.t("current-user")).to_be_visible()
    expect(u.t("wallet-refresh")).to_be_visible()
    if broken == "activity":
        expect(u.t("wallet-balance")).to_have_text("105.00 EUR")
        expect(u.t("wallet-available")).to_have_text("85.00 EUR")
        expect(u.t("wallet-held")).to_have_text("20.00 EUR")
        assert u.page.locator("[data-testid^='activity-item-']").count() == 0
        assert u.t("empty-activity").count() == 0 or not u.t("empty-activity").is_visible(), \
            "a failed feed read is presented as an empty feed"
    else:
        shown = u.t("wallet-balance").text_content().strip() if u.t("wallet-balance").count() else ""
        assert shown in ("", "105.00 EUR") or not re.fullmatch(r"[0-9.]+ EUR", shown), f"a made-up balance {shown!r} is shown"
    # the next refresh, with the read working again, recovers everything
    state["on"] = False
    u.t("wallet-refresh").click()
    expect(u.t("wallet-balance")).to_have_text("105.00 EUR")
    expect(u.t("wallet-available")).to_have_text("85.00 EUR")
    expect(u.page.locator("[data-testid^='activity-item-']")).to_have_count(1)
    assert not u.errors, u.errors


@pytest.mark.parametrize("path,endpoint,item", [("/requests", "requests", "request-item-rq1"),
                                                 ("/authorizations", "authorizations", "authorization-item-a1")])
@pytest.mark.parametrize("kind", ["abort", "null", "items-not-objects", "missing-members"])
def test_n1_list_screens_tolerate_bad_reads(ui, path, endpoint, item, kind):
    reqs = [{"id": "rq1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 700, "note": "", "status": "pending"}]
    w = World(fixture(requests=reqs, auths=[seeded_auth("a1", "bob", "ada", 2000)]))
    u = ui("wide").login("ada")
    state = {"on": True}

    def handler(route):
        req = route.request
        if not state["on"] or req.method != "GET" or req.resource_type == "document":
            route.continue_()
        elif kind == "abort":
            route.abort("connectionreset")
        elif kind == "null":
            route.fulfill(status=200, content_type="application/json", body="null")
        elif kind == "items-not-objects":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({endpoint: [5, "x", None, []], "has_more": False}))
        else:
            resp = route.fetch()
            data = resp.json()
            for it in data.get(endpoint, []):
                for kk in ("note", "created_at", "payment_id", "payment_ids", "captured_amount", "remaining_amount", "currency"):
                    it.pop(kk, None)
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    u.page.route(re.compile(r".*/%s(\?.*)?$" % endpoint), handler)
    u.goto(path)
    u.page.wait_for_timeout(1200)
    assert not u.errors, f"script error on {path} with {kind}: {u.errors}"
    expect(u.t("current-user")).to_be_visible()
    state["on"] = False
    u.goto(path)
    expect(u.t(item)).to_be_visible()
    assert not u.errors, u.errors


def test_n1_no_error_banner_and_refresh_present_in_normal_use(ui, vp):
    w = World(fixture(auths=[seeded_auth("a1", "ada", "bob", 2000)]))
    u = ui(vp).login("ada")
    for path in ROUTES:
        u.goto(path)
        expect(u.t("current-user")).to_be_visible()
        u.page.wait_for_timeout(500)
        assert u.t("page-error").count() == 0, path
    # T3: the refresh button is there while the first read is still pending
    held = []
    pat = re.compile(r".*/(me|activity)(\?.*)?$")
    u.page.route(pat, lambda route: held.append((route, route.fetch())) if route.request.method == "GET"
                 and route.request.resource_type != "document" else route.continue_())
    u.page.goto("/", wait_until="domcontentloaded")
    u.page.wait_for_timeout(700)
    expect(u.t("wallet-refresh")).to_be_visible()
    for route, resp in held:
        route.fulfill(response=resp)
    held.clear()
    u.page.unroute(pat)
    expect(u.t("wallet-available")).to_have_text("80.00 EUR")
    assert not u.errors, u.errors


# ---------------------------------------------------------------- notes T2, T4, T5 over HTTP

@pytest.fixture(scope="module")
def w():
    return World().login_all()


@pytest.mark.parametrize("accept,html", [
    ("text/html", True), ("TEXT/HTML", True), ("text/html; charset=utf-8", True), ("text/html;level=1", True),
    ("application/json, text/html;q=0.8", True), ("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", True),
    ("application/xhtml+xml , text/html ; q=0.5", True), ("text/html;q=1.0", True),
    ("text/htmlx", False), ("xtext/html", False), ("text/html;q=0", False), ("text/html;q=0.0", False), ("*/*", False),
    ("text/*", False), ("application/json", False), ("text/plain, application/json", False), ("", False),
    ("text/html-fragment", False), ("application/vnd.text/html", False), ("q=1, application/json", False),
])
@pytest.mark.parametrize("path", ["/requests", "/authorizations"])
def test_n4_accept_is_parsed_as_media_ranges(w, path, accept, html):
    r = call("GET", path, headers={"Accept": accept}, kind="any")
    assert r.status_code < 500
    if html:
        assert r.status_code == 200 and r.headers["content-type"].lower().startswith("text/html"), \
            f"{path} Accept {accept!r}: {r.status_code} {r.headers.get('content-type')}"
    else:
        err(r, 401, "unauthenticated", f"{path} Accept {accept!r}")
        j = ok(call("GET", path, w.t("ada"), headers={"Accept": accept}), 200)
        assert "has_more" in j


@pytest.mark.parametrize("accept", ["text/html;q=abc", "text/html;q=", "text/html;q=-1", "text/html;q=2", ";;;,,,", "text/html;q=1e999",
                                    "text/html;" + "x=1;" * 500, ",".join(["a/b"] * 2000)])
def test_n4_odd_accept_headers_never_5xx(w, accept):
    for path in ("/requests", "/authorizations", "/", "/me"):
        r = call("GET", path, w.t("ada"), headers={"Accept": accept}, kind="any")
        assert r.status_code == 200, f"{path} Accept {accept[:30]!r}: {r.status_code}"


def test_n5_icon_and_favicon(w):
    r = call("GET", "/static/icon.svg", kind="any")
    assert r.status_code == 200 and "svg" in r.headers["content-type"] and b"<svg" in r.content
    assert "http://" not in r.text.replace("http://www.w3.org", "") and "https://" not in r.text
    r = call("GET", "/favicon.ico", kind="any")
    assert r.status_code in (200, 204) and (r.status_code == 200 or r.content == b"")
    for method in ("HEAD", "POST", "DELETE"):
        assert call(method, "/favicon.ico", kind="any").status_code < 500
    for path in ROUTES:
        text = call("GET", path, headers={"Accept": "text/html"}, kind="any").text
        assert 'rel="icon"' in text and "/static/icon.svg" in text


def test_n2_capture_without_a_body(w):
    a = w.new_auth("ada", "bob", 900, note="no body", visibility="private")
    path = f"/authorizations/{a['authorization_id']}/capture"
    key = k()
    r = call("POST", path, w.t("bob"), key=key)
    p = check_payment(ok(r, 201), amount=900, authorization_id=a["authorization_id"], note="no body", visibility="private")
    assert ok(call("POST", path, w.t("bob"), key=key), 200) == p
    assert ok(call("POST", path, w.t("bob"), key=key, raw="{}"), 200) == p            # no body and {} are one body
    assert ok(call("POST", path, w.t("bob"), key=key, raw="  \n "), 200) == p
    err(call("POST", path, w.t("bob"), key=key, raw='{"amount": 900}'), 409, "idempotency_key_reuse")
    err(call("POST", path, w.t("bob"), key=k()), 409, "authorization_not_open")
    assert w.wallet("bob")["total"] == 3400 and w.wallet("ada")["held"] == 0
    # the other bodies still need to be JSON objects
    b = w.new_auth("ada", "bob", 10)
    path = f"/authorizations/{b['authorization_id']}/capture"
    err(call("POST", path, w.t("bob"), key=k(), raw="[]"), (400, 422))
    err(call("POST", path, w.t("bob"), key=k(), raw="nope"), 400, "malformed_request")
    err(call("POST", path, w.t("ada"), key=k()), 403, "forbidden")
    err(call("POST", path, key=k()), 401, "unauthenticated")
    err(call("POST", path, w.t("bob")), 400, "missing_idempotency_key")
    # stays refused without a body where a body is required
    err(call("POST", "/authorizations", w.t("ada"), key=k()), (400, 422))
    err(call("POST", "/payments", w.t("ada"), key=k()), (400, 422))
    # export / import keep the body-less capture replayable
    e = call("GET", "/_test/export")
    assert call("POST", "/_test/import", raw=e.content).status_code == 204
    first = f"/authorizations/{a['authorization_id']}/capture"
    assert ok(call("POST", first, w.t("bob"), key=key), 200) == p
