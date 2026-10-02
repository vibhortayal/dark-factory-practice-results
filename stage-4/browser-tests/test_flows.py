import json
import time

import pytest

from conftest import BASE, call, fixture, log_in, login_token, reset, sel, user


def amount(page, name="wallet-balance"):
    return page.get_attribute(sel(name), "data-amount")


def fill_pay(page, handle="bob", amt="15.00", note=""):
    page.goto("/")
    page.wait_for_selector(sel("pay-submit"))
    page.fill(sel("pay-handle"), handle)
    page.fill(sel("pay-amount"), amt)
    page.fill(sel("pay-note"), note)


def test_available_is_the_headline_and_held_is_secondary(page):
    reset(fixture(authorizations=[{"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000,
                                   "note": "deposit", "visibility": "public", "status": "open",
                                   "expires_at": "2099-01-01T00:00:00+00:00"}]))
    log_in(page)
    page.goto("/")
    page.wait_for_selector(sel("wallet-available"))
    assert page.text_content(sel("wallet-available")) == "80.00 EUR"
    assert amount(page, "wallet-available") == "8000"
    assert page.text_content(sel("wallet-balance")) == "100.00 EUR"
    assert page.text_content(sel("wallet-held")) == "20.00 EUR"
    sizes = page.evaluate("""() => ['wallet-available','wallet-balance','wallet-held'].map(t =>
        parseFloat(getComputedStyle(document.querySelector(`[data-testid=${t}]`)).fontSize))""")
    assert sizes[0] > sizes[1] and sizes[0] > sizes[2]
    page.goto("/authorizations")
    page.wait_for_selector(sel("authorization-item-a_1"))
    assert page.text_content(sel("wallet-held")) == "20.00 EUR"
    assert page.text_content(sel("authorization-expires-a_1")) == "2099-01-01T00:00:00+00:00"
    assert page.query_selector(sel("authorization-void-a_1"))
    assert page.query_selector(sel("authorization-capture-a_1")) is None


def test_no_held_element_without_holds(page):
    reset()
    log_in(page)
    page.goto("/")
    page.wait_for_selector(sel("wallet-balance"))
    assert page.query_selector(sel("wallet-held")) is None
    assert amount(page, "wallet-available") == amount(page) == "10000"


@pytest.mark.parametrize("cur,mu,bal,text", [("JPY", 0, 1200, "1200 JPY"), ("BHD", 3, 1000, "1.000 BHD"), ("EUR", 2, 5, "0.05 EUR")])
def test_formats(page, cur, mu, bal, text):
    reset(fixture(currency=cur, minor_units=mu, users=[user("ada", "ada", "Ada", bal)]))
    log_in(page)
    page.goto("/")
    page.wait_for_selector(sel("wallet-balance"))
    assert page.text_content(sel("wallet-balance")) == text


def test_decimal_rules(page):
    reset()
    log_in(page)
    sent = []
    page.on("request", lambda r: sent.append(r.url) if r.method == "POST" and "/payments" in r.url else None)
    for bad in ["15.005", "abc", "", "-5", "1e3", "1,5", "15."]:
        fill_pay(page, amt=bad)
        page.click(sel("pay-submit"))
        page.wait_for_selector(sel("pay-error"))
    assert sent == []
    fill_pay(page, amt="15")
    page.click(sel("pay-submit"))
    page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='8500']")
    page.fill(sel("pay-amount"), " 15.5 ")
    page.click(sel("pay-submit"))
    page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='6950']")
    assert page.query_selector(sel("pay-error")) is None


def test_jpy_rejects_decimals(page):
    reset(fixture(currency="JPY", minor_units=0))
    log_in(page)
    fill_pay(page, amt="15.5")
    page.click(sel("pay-submit"))
    page.wait_for_selector(sel("pay-error"))


def test_notes_are_text_not_markup(page):
    reset()
    log_in(page)
    fill_pay(page, amt="1.00", note="<b>&amp;</b><img src=x onerror=alert(1)>")
    page.click(sel("pay-submit"))
    page.wait_for_selector(sel("activity-list"))
    pid = page.get_attribute("[data-testid^='activity-item-']", "data-testid").replace("activity-item-", "")
    assert page.text_content(sel(f"activity-note-{pid}")) == "<b>&amp;</b><img src=x onerror=alert(1)>"
    assert page.query_selector(f"{sel('activity-list')} img") is None


def test_lost_response_is_uncertain_then_retried_once(page):
    reset()
    log_in(page)
    fill_pay(page)
    seen = []

    def lose(route):
        seen.append((route.request.headers.get("idempotency-key"), route.request.post_data))
        route.fetch()          # the service commits...
        route.abort()          # ...and the response never arrives

    page.route("**/payments", lose)
    page.click(sel("pay-submit"))
    page.wait_for_selector(sel("pay-uncertain"))
    assert page.text_content(sel("pay-uncertain")).strip() != ""
    assert page.query_selector(sel("pay-error")) is None
    page.unroute("**/payments")
    page.click(sel("pay-submit"))
    page.wait_for_selector(sel("pay-uncertain"), state="detached")
    page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='8500']")
    assert page.query_selector(sel("pay-error")) is None
    status, me = call("GET", "/me", token=login_token("ada"))
    assert me["balance"] == 8500
    assert len(page.query_selector_all("[data-testid^='activity-item-']")) == 1
    assert len(seen) == 1


def test_unknown_outcome_on_5xx_is_uncertain(page):
    reset()
    log_in(page)
    fill_pay(page)
    page.route("**/payments", lambda r: r.fulfill(status=503, body="oops"))
    page.click(sel("pay-submit"))
    page.wait_for_selector(sel("pay-uncertain"))
    assert page.query_selector(sel("pay-error")) is None


def test_double_submit_and_changed_form(page):
    reset()
    log_in(page)
    fill_pay(page)
    page.click(sel("pay-submit"))
    page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='8500']")
    assert page.input_value(sel("pay-handle")) == "bob" and page.input_value(sel("pay-amount")) == "15.00"
    page.click(sel("pay-submit"))
    page.wait_for_timeout(500)
    assert amount(page) == "8500" and page.query_selector(sel("pay-error")) is None
    page.fill(sel("pay-note"), "again")
    page.click(sel("pay-submit"))
    page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='7000']")
    # request form retains and replays too
    page.fill(sel("request-handle"), "bob")
    page.fill(sel("request-amount"), "3.00")
    page.click(sel("request-submit"))
    page.wait_for_timeout(400)
    page.click(sel("request-submit"))
    page.wait_for_timeout(400)
    _, rq = call("GET", "/requests", token=login_token("ada"))
    assert len(rq["requests"]) == 1


def test_refused_payment_keeps_inputs_and_refreshes(page):
    reset()
    log_in(page)
    fill_pay(page, amt="60.00", note="n")
    call("POST", "/payments", {"to_handle": "cy", "amount": 9000}, token=login_token("ada"), key="drain")
    page.click(sel("pay-submit"))
    page.wait_for_selector(sel("pay-error"))
    page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='1000']")
    assert page.input_value(sel("pay-amount")) == "60.00" and page.input_value(sel("pay-note")) == "n"
    assert page.query_selector(f"[data-testid^='activity-item-']")


def test_latest_refresh_wins(page):
    reset()
    log_in(page)
    page.goto("/")
    page.wait_for_selector(sel("wallet-refresh"))
    fill = page.fill
    fill(sel("pay-handle"), "keepme")
    state = {"n": 0}

    def slow_first(route):
        state["n"] += 1
        mine = state["n"]
        resp = route.fetch()          # stale data: read now...
        if mine == 1:
            time.sleep(1.5)          # ...delivered after the later refresh
        route.fulfill(response=resp)

    page.route("**/me", slow_first)
    page.route("**/activity**", lambda r: r.continue_())
    page.click(sel("wallet-refresh"))
    page.wait_for_timeout(200)
    call("POST", "/payments", {"to_handle": "bob", "amount": 1000}, token=login_token("ada"), key="x1")
    page.click(sel("wallet-refresh"))
    page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='9000']")
    page.wait_for_timeout(2200)
    assert amount(page) == "9000" and amount(page, "wallet-available") == "9000"
    assert page.input_value(sel("pay-handle")) == "keepme"


def test_request_cancelled_elsewhere_shows_error_and_drops_the_stale_button(page):
    reset()
    bob = login_token("bob")
    _, rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, token=bob, key="r1")
    rid = rq["request_id"]
    log_in(page)
    page.goto("/requests")
    page.wait_for_selector(sel(f"request-pay-{rid}"))
    call("POST", f"/requests/{rid}/cancel", token=bob)
    page.click(sel(f"request-pay-{rid}"))
    page.wait_for_selector(sel("request-error"))
    page.wait_for_selector(f"{sel('request-item-' + rid)}[data-status='cancelled']")
    assert page.query_selector(sel(f"request-pay-{rid}")) is None


def test_authorize_capture_void_flow(page):
    reset()
    log_in(page)
    page.goto("/authorizations")
    page.wait_for_selector(sel("empty-authorizations"))
    page.fill(sel("authorize-handle"), "bob")
    page.fill(sel("authorize-amount"), "20.00")
    page.select_option(sel("authorize-visibility"), "private")
    page.click(sel("authorize-submit"))
    page.wait_for_selector(f"{sel('wallet-held')}")
    assert page.text_content(sel("wallet-held")) == "20.00 EUR"
    assert page.text_content(sel("wallet-available")) == "80.00 EUR"
    assert page.text_content(sel("wallet-balance")) == "100.00 EUR"
    aid = page.get_attribute("[data-testid^='authorization-item-']", "data-testid").replace("authorization-item-", "")
    assert page.query_selector(sel(f"authorization-void-{aid}"))
    page.fill(sel("authorize-amount"), "99.00")
    page.click(sel("authorize-submit"))
    page.wait_for_selector(sel("authorize-error"))
    # Bob captures part of it
    page2 = page.context.browser.new_context(base_url=BASE).new_page()
    page2.goto("/login")
    page2.fill(sel("login-email"), "bob@example.com")
    page2.fill(sel("login-password"), "correct horse")
    page2.click(sel("login-submit"))
    page2.wait_for_selector(sel("current-user"))
    page2.goto("/authorizations")
    page2.wait_for_selector(sel(f"authorization-capture-amount-{aid}"))
    assert page2.input_value(sel(f"authorization-capture-amount-{aid}")) == "20.00"
    assert page2.query_selector(sel(f"authorization-void-{aid}")) is None
    page2.fill(sel(f"authorization-capture-amount-{aid}"), "15.00")
    page2.click(sel(f"authorization-capture-{aid}"))
    page2.wait_for_selector(f"{sel('authorization-item-' + aid)}[data-status='captured']")
    assert page2.text_content(sel(f"authorization-captured-{aid}")) == "15.00 EUR"
    assert page2.text_content(sel(f"authorization-amount-{aid}")) == "20.00 EUR"
    assert page2.query_selector(sel(f"authorization-capture-{aid}")) is None
    assert page2.text_content(sel("wallet-balance")) == "40.00 EUR"
    # a second hold is voided by the payer
    page.goto("/authorizations")
    page.fill(sel("authorize-handle"), "bob")
    page.fill(sel("authorize-amount"), "5.00")
    page.click(sel("authorize-submit"))
    page.wait_for_selector(sel("wallet-held"))
    void = page.query_selector("[data-testid^='authorization-void-']")
    void.click()
    page.wait_for_selector(sel("wallet-held"), state="detached")
    assert page.text_content(sel("wallet-available")) == "85.00 EUR"


def test_capture_refusals_show_error_and_refresh(page):
    reset(fixture(authorization_ttl_seconds=1))
    ada = login_token("ada")
    _, a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, token=ada, key="k")
    aid = a["authorization_id"]
    log_in(page, "bob")
    page.goto("/authorizations")
    page.wait_for_selector(sel(f"authorization-capture-{aid}"))
    page.fill(sel(f"authorization-capture-amount-{aid}"), "10.005")
    page.click(sel(f"authorization-capture-{aid}"))
    page.wait_for_selector(sel("authorization-error"))
    time.sleep(1.2)
    page.fill(sel(f"authorization-capture-amount-{aid}"), "10.00")
    page.click(sel(f"authorization-capture-{aid}"))
    page.wait_for_selector(f"{sel('authorization-item-' + aid)}[data-status='expired']")
    assert page.query_selector(sel("authorization-error"))
    assert page.query_selector(sel(f"authorization-capture-{aid}")) is None


def test_split_preview_and_submit(page):
    for cur, mu, amt, handles, expect in [
        ("EUR", 2, "10.00", "ada,bob,cy", ["3.34 EUR", "3.33 EUR", "3.33 EUR"]),
        ("EUR", 2, "0.01", "cy, bob ,ada", ["0.01 EUR", "0.00 EUR", "0.00 EUR"]),
        ("JPY", 0, "10", "ada,bob,cy", ["4 JPY", "3 JPY", "3 JPY"]),
        ("BHD", 3, "1", "ada,bob,cy", ["0.334 BHD", "0.333 BHD", "0.333 BHD"]),
    ]:
        reset(fixture(currency=cur, minor_units=mu))
        log_in(page)
        page.goto("/split")
        page.fill(sel("split-amount"), amt)
        page.fill(sel("split-handles"), handles)
        order = [h.strip() for h in handles.split(",")]
        shares = [page.text_content(sel(f"split-share-{h}")) for h in order]
        assert shares == expect, (cur, shares)
        page.click(sel("split-submit"))
        page.wait_for_selector("[data-testid='split-success']")
        page.click(sel("split-submit"))
        page.wait_for_timeout(300)
        _, rq = call("GET", "/requests", token=login_token("ada"))
        assert len(rq["requests"]) == 2
        page.evaluate("localStorage.clear()")


def test_auth_flows_and_errors(page):
    reset()
    page.goto("/login")
    page.fill(sel("login-email"), "ada@example.com")
    page.fill(sel("login-password"), "wrong")
    page.click(sel("login-submit"))
    page.wait_for_selector(sel("auth-error"))
    page.goto("/signup")
    assert page.query_selector(sel("auth-error")) is None
    page.fill(sel("signup-email"), "ada@other.com")
    page.fill(sel("signup-password"), "longenough")
    page.fill(sel("signup-display-name"), "Other")
    page.click(sel("signup-submit"))
    page.wait_for_selector(sel("auth-error"))
    page.fill(sel("signup-email"), "new.person@other.com")
    page.click(sel("signup-submit"))
    page.wait_for_selector(sel("current-user"))
    assert page.text_content(sel("current-handle")) == "new_person"
    page.goto("/login")
    page.wait_for_selector(sel("login-submit"))
    assert "Other" in page.text_content(sel("current-user"))
    page.click(sel("logout-button"))
    page.wait_for_selector(sel("login-submit"))
    page.goto("/requests")
    page.wait_for_selector(sel("login-submit"))


def test_unknown_token_signs_out(page):
    reset()
    log_in(page)
    reset()                      # the service forgets the token
    page.goto("/")
    page.wait_for_selector(sel("login-submit"))
    assert page.evaluate("localStorage.getItem('pocketful.token')") is None


def test_upgrade_without_reload(page):
    """Export, reset and import while the page stays open: still signed in, retry replays."""
    reset()
    log_in(page)
    fill_pay(page)
    page.route("**/payments", lambda r: (r.fetch(), r.abort()))
    page.click(sel("pay-submit"))
    page.wait_for_selector(sel("pay-uncertain"))
    page.unroute("**/payments")
    _, snap = call("GET", "/_test/export")
    reset(fixture())   # unrelated state in between
    status, _ = call("POST", "/_test/import", snap)
    assert status == 204
    call("POST", "/payments", {"to_handle": "cy", "amount": 100}, token=login_token("ada"), key="elsewhere")
    page.click(sel("pay-submit"))
    page.wait_for_selector(sel("pay-uncertain"), state="detached")
    page.wait_for_selector(f"{sel('wallet-balance')}[data-amount='8400']")
    assert page.query_selector(sel("pay-error")) is None
    assert page.query_selector(sel("current-user"))
    # a pending request from before is still payable
    page.goto("/requests")
    page.wait_for_selector(sel("empty-requests"))


def test_stage1_payload_shape_is_tolerated(page):
    reset()
    log_in(page)
    old_me = {"user_id": "u_ada", "display_name": "Ada", "handle": "ada", "balance": 10000, "currency": "EUR", "minor_units": 2}
    page.route("**/me", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(old_me)))
    page.goto("/")
    page.wait_for_selector(sel("wallet-available"))
    assert amount(page, "wallet-available") == "10000" and page.query_selector(sel("wallet-held")) is None


def test_added_test_ids_stay_out_of_the_specified_item_families(page):
    """A request whose id is `visibility` must still own `request-pay-visibility` alone."""
    reset(fixture(requests=[{"id": "visibility", "requester_id": "u_bob", "payer_id": "u_ada",
                             "amount": 100, "note": "n", "status": "pending"}]))
    log_in(page)
    page.goto("/requests")
    page.wait_for_selector(sel("request-item-visibility"))
    tags = page.evaluate("Array.from(document.querySelectorAll('[data-testid=\"request-pay-visibility\"]')).map(e => e.tagName)")
    assert tags == ["BUTTON"]
    ids = page.evaluate("Array.from(document.querySelectorAll('[data-testid]')).map(e => e.dataset.testid)")
    assert len(ids) == len(set(ids)), "a test id appears twice"


def test_loading_states_are_visible_while_the_first_read_is_slow(page):
    reset()
    log_in(page)
    held = []

    def hold(route):
        if route.request.resource_type == "fetch" and not route.request.url.endswith("/me"):
            held.append(route)          # the read is neither answered nor failed: still loading
        else:
            route.continue_()

    page.route("**/*", hold)
    for route, hint in [("/", "Loading activity"), ("/requests", "Loading requests"), ("/authorizations", "Loading holds")]:
        page.goto(route)
        page.wait_for_selector(".loading-block")
        assert hint in page.inner_text(".loading-block")
        assert page.query_selector(".skeleton-line")
        for r in held:
            r.continue_()
        held.clear()
        page.wait_for_selector(".loading-block", state="detached")


def test_feed_row_with_a_huge_amount_stays_readable_at_375(browser):
    reset(fixture(users=[user("ada", "ada", "Ada", 9_000_000_000_000), user("bob", "bob", "Bob", 0), user("cy", "cy", "Cy", 0)],
                  payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1_000_000_000,
                             "note": "A normal sentence for a note", "visibility": "public"}]))
    ctx = browser.new_context(base_url=BASE, viewport={"width": 375, "height": 800})
    pg = ctx.new_page()
    log_in(pg)
    pg.goto("/")
    pg.wait_for_selector(sel("activity-note-p_1"))
    widths = pg.evaluate("""() => { const n = document.querySelector('[data-testid=activity-note-p_1]').getBoundingClientRect().width;
        return [n, document.documentElement.scrollWidth, document.documentElement.clientWidth]; }""")
    assert widths[0] > 200 and widths[1] == widths[2]
    ctx.close()
