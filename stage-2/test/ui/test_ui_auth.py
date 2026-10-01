"""Browser tests: holds (authorizations), upgrade from stage 1, product quality checks."""
import json
import re
import time

import pytest
from playwright.sync_api import expect

from common import BASE, api, fixture, reset, iso, token_for, with_session, ui_login, user

T = lambda page, tid: page.get_by_test_id(tid)  # noqa: E731


def holds_fixture(**extra):
    return fixture(authorizations=[
        {"id": "a_out", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit", "visibility": "public", "status": "open", "expires_at": iso(7200)},
        {"id": "a_in", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 700, "note": "back", "visibility": "private", "status": "open", "expires_at": "2099-01-01T00:00:00Z"},
        {"id": "a_cap", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 400, "captured_amount": 400, "status": "captured", "expires_at": iso(7200), "payment_id": "p_x"},
        {"id": "a_void", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 100, "status": "voided", "expires_at": iso(7200)},
        {"id": "a_exp", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 100, "status": "open", "expires_at": iso(-7200)},
    ], **extra)


def test_wallet_headline_available_and_held_visibility(page):
    reset(holds_fixture())
    with_session(page, "ada")
    page.goto(BASE + "/")
    expect(T(page, "wallet-available")).to_have_text("80.00 EUR")
    expect(T(page, "wallet-balance")).to_have_text("100.00 EUR")
    expect(T(page, "wallet-held")).to_have_text("20.00 EUR")
    assert T(page, "wallet-available").get_attribute("data-amount") == "8000"
    assert T(page, "wallet-balance").get_attribute("data-amount") == "10000"
    assert T(page, "wallet-held").get_attribute("data-amount") == "2000"
    # the headline is the largest number and comes first
    sizes = page.evaluate("['wallet-available','wallet-balance','wallet-held'].map(t => parseFloat(getComputedStyle(document.querySelector(`[data-testid=${t}]`)).fontSize))")
    assert sizes[0] > sizes[1] and sizes[0] > sizes[2]
    order = page.evaluate("(() => { const a = document.querySelector('[data-testid=wallet-available]'), b = document.querySelector('[data-testid=wallet-balance]'); return !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING); })()")
    assert order
    with_session(page, "cy")
    page.goto(BASE + "/")
    expect(T(page, "wallet-held")).to_have_count(0)
    expect(T(page, "wallet-available")).to_have_text("0.00 EUR")


def test_authorize_from_home_updates_available_and_held(page):
    reset(fixture())
    with_session(page, "ada")
    page.goto(BASE + "/")
    T(page, "authorize-handle").fill("bob")
    T(page, "authorize-amount").fill("25.50")
    T(page, "authorize-note").fill("hold it")
    T(page, "authorize-visibility").select_option("private")
    T(page, "authorize-submit").click()
    expect(T(page, "wallet-available")).to_have_text("74.50 EUR")
    expect(T(page, "wallet-balance")).to_have_text("100.00 EUR")
    expect(T(page, "wallet-held")).to_have_text("25.50 EUR")
    expect(T(page, "authorize-error")).to_have_count(0)
    # nothing in the feed until a capture
    expect(T(page, "empty-activity")).to_be_visible()
    T(page, "authorize-amount").fill("90.00")
    T(page, "authorize-submit").click()
    expect(T(page, "authorize-error")).to_be_visible()
    assert T(page, "authorize-note").input_value() == "hold it"
    # a held amount cannot fund a payment either
    T(page, "pay-handle").fill("bob")
    T(page, "pay-amount").fill("80.00")
    T(page, "pay-submit").click()
    expect(T(page, "pay-error")).to_be_visible()


def test_authorizations_screen_items_controls_and_states(page):
    reset(holds_fixture())
    with_session(page, "ada")
    page.goto(BASE + "/authorizations")
    expect(T(page, "authorization-list")).to_be_visible()
    expect(T(page, "empty-authorizations")).to_have_count(0)
    ids = page.evaluate("[...document.querySelectorAll('[data-testid=authorization-list] > [data-testid^=authorization-item-]')].map(e => e.dataset.testid.replace('authorization-item-', ''))")
    assert set(ids) == {"a_out", "a_in", "a_cap", "a_void", "a_exp"}
    for i, st in (("a_out", "open"), ("a_in", "open"), ("a_cap", "captured"), ("a_void", "voided"), ("a_exp", "expired")):
        expect(T(page, f"authorization-item-{i}")).to_have_attribute("data-status", st)
    expect(T(page, "authorization-amount-a_out")).to_have_text("20.00 EUR")
    # captured amount only on captured; expiry text is the RFC 3339 string verbatim
    expect(T(page, "authorization-captured-a_cap")).to_have_text("4.00 EUR")
    for i in ("a_out", "a_in", "a_void", "a_exp"):
        expect(T(page, f"authorization-captured-{i}")).to_have_count(0)
    status, listing = api("GET", "/authorizations?limit=200", token=token_for("ada"))
    for a in listing["authorizations"]:
        expect(T(page, f"authorization-expires-{a['authorization_id']}")).to_have_text(a["expires_at"])
    assert T(page, "authorization-expires-a_in").text_content() == "2099-01-01T00:00:00Z"
    # controls: capture only on incoming open, void only on outgoing open
    expect(T(page, "authorization-capture-a_in")).to_have_count(1)
    assert T(page, "authorization-capture-amount-a_in").input_value() == "7.00"
    expect(T(page, "authorization-void-a_out")).to_have_count(1)
    for tid in ("authorization-capture-a_out", "authorization-capture-amount-a_out", "authorization-void-a_in", "authorization-capture-a_cap", "authorization-void-a_cap", "authorization-void-a_void", "authorization-void-a_exp", "authorization-capture-a_exp", "authorization-capture-a_void"):
        expect(T(page, tid)).to_have_count(0)
    # wallet summary is shown and refreshes
    expect(T(page, "wallet-available")).to_have_text("80.00 EUR")
    expect(T(page, "wallet-held")).to_have_text("20.00 EUR")
    T(page, "authorization-void-a_out").click()
    expect(T(page, "authorization-item-a_out")).to_have_attribute("data-status", "voided")
    expect(T(page, "wallet-held")).to_have_count(0)
    expect(T(page, "wallet-available")).to_have_text("100.00 EUR")
    T(page, "authorization-capture-amount-a_in").fill("3.00")
    T(page, "authorization-capture-a_in").click()
    expect(T(page, "authorization-item-a_in")).to_have_attribute("data-status", "captured")
    expect(T(page, "authorization-captured-a_in")).to_have_text("3.00 EUR")
    expect(T(page, "wallet-balance")).to_have_text("103.00 EUR")


def test_capture_keep_rest_on_hold_and_errors(page):
    reset(holds_fixture())
    with_session(page, "ada")
    page.goto(BASE + "/authorizations")
    box = page.locator("#capture-rest-a_in")
    assert not box.is_checked()
    box.check()
    T(page, "authorization-capture-amount-a_in").fill("2.00")
    T(page, "authorization-capture-a_in").click()
    expect(T(page, "authorization-item-a_in")).to_have_attribute("data-status", "open")
    expect(T(page, "authorization-capture-amount-a_in")).to_have_value("5.00")
    # errors: exceeds, bad input (no request), refused when closed elsewhere
    T(page, "authorization-capture-amount-a_in").fill("9.00")
    T(page, "authorization-capture-a_in").click()
    expect(T(page, "authorization-error")).to_be_visible()
    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    T(page, "authorization-capture-amount-a_in").fill("1.005")
    T(page, "authorization-capture-a_in").click()
    expect(T(page, "authorization-error")).to_be_visible()
    assert posts == []
    assert api("POST", "/authorizations/a_in/void", token=token_for("bob"))[0] == 200
    T(page, "authorization-capture-amount-a_in").fill("1.00")
    T(page, "authorization-capture-a_in").click()
    expect(T(page, "authorization-error")).to_be_visible()
    expect(T(page, "authorization-capture-a_in")).to_have_count(0)    # stale control gone after the refresh
    expect(T(page, "authorization-item-a_in")).to_have_attribute("data-status", "voided")


def test_void_refused_when_already_captured_elsewhere(page):
    reset(holds_fixture())
    with_session(page, "ada")
    page.goto(BASE + "/authorizations")
    T(page, "authorization-void-a_out").wait_for()
    assert api("POST", "/authorizations/a_out/capture", {}, token=token_for("bob"), key="k-cap")[0] == 201
    T(page, "authorization-void-a_out").click()
    expect(T(page, "authorization-error")).to_be_visible()
    expect(T(page, "authorization-void-a_out")).to_have_count(0)
    expect(T(page, "authorization-item-a_out")).to_have_attribute("data-status", "captured")


def test_authorize_on_authorizations_screen_and_empty_state(page):
    reset(fixture())
    with_session(page, "ada")
    page.goto(BASE + "/authorizations")
    expect(T(page, "authorization-list")).to_be_attached()
    expect(T(page, "empty-authorizations")).to_be_visible()
    T(page, "authorize-handle").fill("bob")
    T(page, "authorize-amount").fill("10")
    T(page, "authorize-submit").click()
    expect(page.locator("[data-testid^='authorization-item-']")).to_have_count(1)
    expect(T(page, "empty-authorizations")).to_have_count(0)
    expect(T(page, "wallet-held")).to_have_text("10.00 EUR")
    T(page, "authorize-submit").click()   # unchanged -> replay, no second hold
    page.wait_for_timeout(500)
    expect(page.locator("[data-testid^='authorization-item-']")).to_have_count(1)


def test_clock_expired_hold_shows_expired_without_controls(page):
    reset(fixture(authorization_ttl_seconds=2))
    token = with_session(page, "ada")
    status, a = api("POST", "/authorizations", {"to_handle": "bob", "amount": 500}, token=token, key="short")
    assert status == 201
    page.goto(BASE + "/authorizations")
    expect(T(page, f"authorization-void-{a['authorization_id']}")).to_have_count(1)
    expect(T(page, "wallet-held")).to_have_text("5.00 EUR")
    time.sleep(2.2)
    page.reload()
    expect(T(page, f"authorization-item-{a['authorization_id']}")).to_have_attribute("data-status", "expired")
    expect(T(page, f"authorization-void-{a['authorization_id']}")).to_have_count(0)
    expect(T(page, "wallet-held")).to_have_count(0)
    expect(T(page, "wallet-available")).to_have_text("100.00 EUR")


# ---------------------------------------------------------------- R8-R10: upgrade without reload

def import_from(stage1_base, fx_users=None):
    import urllib.request
    with urllib.request.urlopen(stage1_base + "/_test/export") as r:
        export = json.loads(r.read())
    return export


def s1(stage1, method, path, body=None, token=None, key=None):
    import urllib.request, urllib.error
    req = urllib.request.Request(stage1 + path, data=json.dumps(body).encode() if body is not None else None, method=method)
    req.add_header("Content-Type", "application/json")
    if token: req.add_header("Authorization", "Bearer " + token)
    if key: req.add_header("Idempotency-Key", key)
    try:
        with urllib.request.urlopen(req) as r:
            text = r.read().decode(); return r.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as e:
        text = e.read().decode(); return e.code, (json.loads(text) if text else None)


def test_upgrade_keeps_session_requests_and_retry_identity(page, stage1):
    # state lives in a real stage-1 service; the browser talks to stage 2
    assert s1(stage1, "POST", "/_test/reset", fixture(requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]))[0] == 204
    status, login = s1(stage1, "POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
    token = login["token"]
    # the browser is signed in on stage 2 before the upgrade; a payment's response is lost *after*
    # it committed on the old service (the request is redirected to stage 1, then dropped)
    reset(fixture())
    page.goto(BASE + "/login")
    page.evaluate("t => localStorage.setItem('pocketful.session', JSON.stringify({token: t}))", token)
    api("POST", "/_test/import", s1_export(stage1, token))        # first import so this session is valid here
    page.goto(BASE + "/")
    expect(T(page, "wallet-balance")).to_have_text("100.00 EUR")
    seen = []
    def lose_at_old_service(route):
        req = route.request
        seen.append((req.headers.get("idempotency-key"), req.post_data))
        resp = route.fetch(url=stage1 + "/payments")
        assert resp.status == 201, resp.text()
        route.abort()
    page.route("**/payments", lose_at_old_service)
    T(page, "pay-handle").fill("bob")
    T(page, "pay-amount").fill("30.00")
    T(page, "pay-note").fill("lost then upgraded")
    T(page, "pay-submit").click()
    expect(T(page, "pay-uncertain")).to_be_visible()
    page.unroute("**/payments")
    # upgrade: stage-1 export (taken after the lost payment committed there) is imported into stage 2
    status, export = s1(stage1, "GET", "/_test/export")
    assert export["state"]["schema_version"] == 1
    assert api("POST", "/_test/import", export)[0] == 204
    page.on("request", lambda r: seen.append((r.headers.get("idempotency-key"), r.post_data)) if r.method == "POST" and r.url.endswith("/payments") else None)
    # no reload: still signed in, the unchanged form retries with the same key and body
    T(page, "pay-submit").click()
    expect(T(page, "pay-success")).to_be_visible()
    expect(T(page, "pay-uncertain")).to_have_count(0)
    expect(T(page, "wallet-balance")).to_have_text("70.00 EUR")
    assert len(seen) == 2 and seen[0] == seen[1]
    status, feed = api("GET", "/activity", token=token)
    mine = [p for p in feed["payments"] if p["note"] == "lost then upgraded"]
    assert len(mine) == 1 and mine[0]["authorization_id"] is None
    expect(page.locator("[data-testid^='activity-item-']")).to_have_count(1)
    # the session survived, and the pending request is still payable from the screen
    expect(T(page, "current-user")).to_contain_text("Ada")
    page.goto(BASE + "/requests")
    T(page, "request-pay-rq_1").click()
    expect(T(page, "request-item-rq_1")).to_have_attribute("data-status", "paid")
    status, me = api("GET", "/me", token=token)
    assert me["balance"] == 10000 - 3000 - 1200


def s1_export(stage1, token):
    status, export = s1(stage1, "GET", "/_test/export")
    assert status == 200
    return export


def test_stage2_import_between_requests_keeps_browser_session(page):
    reset(holds_fixture())
    with_session(page, "ada")
    page.goto(BASE + "/")
    expect(T(page, "wallet-held")).to_have_text("20.00 EUR")
    status, export = api("GET", "/_test/export")
    reset(fixture())            # destination had other data; import replaces it, tokens come with the export
    assert api("POST", "/_test/import", export)[0] == 204
    T(page, "wallet-refresh").click()
    expect(T(page, "wallet-held")).to_have_text("20.00 EUR")
    expect(T(page, "current-user")).to_be_visible()
    page.reload()
    expect(T(page, "current-user")).to_contain_text("Ada")


# ---------------------------------------------------------------- W / K3: product quality

LONG = "wrapping-note-" + "x" * 150 + " 🍝"


def long_fixture():
    return holds_fixture(
        payments=[{"id": "p_l", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 123456789, "note": LONG, "visibility": "private"}],
        requests=[{"id": "rq_l", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 5, "note": LONG, "status": "pending"}],
    )


@pytest.mark.parametrize("width", [375, 1280])
def test_no_horizontal_scroll_on_any_route(browser, width):
    ctx = browser.new_context(viewport={"width": width, "height": 800})
    page = ctx.new_page()
    reset(long_fixture())
    with_session(page, "ada")
    for route in ("/", "/requests", "/split", "/authorizations", "/login", "/signup"):
        page.goto(BASE + route)
        page.wait_for_load_state("networkidle")
        if route == "/split":
            T(page, "split-amount").fill("123456.78")
            T(page, "split-handles").fill("ada," + ",".join(f"someone_with_a_long_handle{i}" for i in range(3)))
        over = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert over <= 0, (route, width, over)
    ctx.close()


def test_labels_alerts_focus_and_keyboard_submit(page):
    reset(long_fixture())
    with_session(page, "ada")
    for route in ("/", "/split", "/authorizations", "/login", "/signup"):
        page.goto(BASE + route)
        page.wait_for_load_state("networkidle")
        missing = page.evaluate("[...document.querySelectorAll('input:not([type=hidden]), select, textarea')].filter(e => !e.labels || e.labels.length === 0).map(e => e.dataset.testid || e.id)")
        assert missing == [], (route, missing)
    page.goto(BASE + "/")
    # errors are announced
    T(page, "pay-submit").click()
    expect(T(page, "pay-error")).to_have_attribute("role", "alert")
    # keyboard focus is clearly visible
    T(page, "pay-handle").focus()
    page.keyboard.press("Tab")
    ring = page.evaluate("(() => { const s = getComputedStyle(document.activeElement); return [s.outlineStyle, parseFloat(s.outlineWidth)]; })()")
    assert ring[0] != "none" and ring[1] >= 2
    # Enter submits the form
    T(page, "pay-handle").fill("bob")
    T(page, "pay-amount").fill("1.00")
    T(page, "pay-amount").press("Enter")
    expect(T(page, "pay-success")).to_be_visible()
    # navigation is consistent on every signed-in route
    for route in ("/", "/requests", "/split", "/authorizations"):
        page.goto(BASE + route)
        links = page.evaluate("[...document.querySelectorAll('nav a')].map(a => a.getAttribute('href'))")
        assert links == ["/", "/requests", "/split", "/authorizations"]
    # uncertain, refused and success are visibly distinct
    page.goto(BASE + "/")
    colors = {}
    for kind in ("error", "uncertain", "success"):
        page.evaluate("(k) => { const p = document.createElement('p'); p.className = 'alert alert-' + k; p.id = 'probe-' + k; p.textContent = 'x'; document.body.append(p); }", kind)
        colors[kind] = page.evaluate("(k) => { const s = getComputedStyle(document.getElementById('probe-' + k)); return [s.backgroundColor, s.color, s.borderLeftColor, s.borderTopStyle].join('|'); }", kind)
    assert len(set(colors.values())) == 3


def test_busy_state_while_write_in_flight(page):
    reset(fixture())
    with_session(page, "ada")
    page.goto(BASE + "/")
    gate = []
    page.route("**/payments", lambda r: gate.append(r))
    T(page, "pay-handle").fill("bob")
    T(page, "pay-amount").fill("1.00")
    T(page, "pay-submit").click()
    expect(T(page, "pay-submit")).to_be_disabled()
    expect(T(page, "pay-submit")).to_have_attribute("aria-busy", "true")
    gate[0].continue_()
    expect(T(page, "pay-success")).to_be_visible()
    expect(T(page, "pay-submit")).to_be_enabled()


def test_loading_state_is_visible_before_data(page):
    reset(fixture())
    with_session(page, "ada")
    gate = []
    page.route("**/activity*", lambda r: gate.append(r))
    page.goto(BASE + "/")
    expect(page.get_by_text("Loading activity")).to_be_visible()
    gate[0].continue_()
    expect(T(page, "empty-activity")).to_be_visible()


def test_k3_everything_is_served_from_the_image(browser):
    ctx = browser.new_context()
    page = ctx.new_page()
    seen, failed = [], []
    page.on("request", lambda r: seen.append(r.url))
    page.on("requestfailed", lambda r: failed.append(r.url))
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    reset(holds_fixture())
    with_session(page, "ada")
    for route in ("/", "/requests", "/split", "/authorizations", "/login", "/signup"):
        page.goto(BASE + route)
        page.wait_for_load_state("networkidle")
    assert all(u.startswith(BASE) or u.startswith("data:") for u in seen), [u for u in seen if not u.startswith(BASE)]
    assert failed == [] and errors == [], (failed, errors)
    ctx.close()
