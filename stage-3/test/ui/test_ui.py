"""Browser tests for the stage-2 screens, written from the specification.

BASE_URL=http://127.0.0.1:18080 <kickoff venv>/bin/python -m pytest -q test_ui.py
"""
import json
import re
import time

import pytest
from playwright.sync_api import expect

from common import BASE, api, fixture, reset, iso, token_for, with_session, ui_login, user

T = lambda page, tid: page.get_by_test_id(tid)  # noqa: E731


def amount_of(page, tid):
    return T(page, tid).get_attribute("data-amount")


def seed_basic():
    reset(fixture(
        payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"}],
        requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}],
    ))


# ---------------------------------------------------------------- L: routes, M: session

def test_routes_signed_out_redirect_and_forms(page):
    reset()
    for route in ("/", "/requests", "/split", "/authorizations"):
        page.goto(BASE + route)
        page.wait_for_url("**/login")
        expect(T(page, "login-submit")).to_be_visible()
        expect(T(page, "current-user")).to_have_count(0)
        expect(T(page, "auth-error")).to_have_count(0)
    page.goto(BASE + "/signup")
    for tid in ("signup-email", "signup-password", "signup-display-name", "signup-submit"):
        expect(T(page, tid)).to_be_visible()
    expect(T(page, "auth-error")).to_have_count(0)


def test_every_route_signed_in_shows_user_and_handle(page):
    reset()
    ui_login(page, "ada")
    for route in ("/", "/requests", "/split", "/authorizations", "/login", "/signup"):
        page.goto(BASE + route)
        expect(T(page, "current-user")).to_contain_text("Ada")
        expect(T(page, "current-handle")).to_have_text("ada")
        assert T(page, "current-handle").text_content() == "ada"
    # login and signup still render their forms when signed in
    page.goto(BASE + "/login")
    expect(T(page, "login-submit")).to_be_visible()
    page.goto(BASE + "/signup")
    expect(T(page, "signup-submit")).to_be_visible()


def test_login_success_lands_on_home_and_session_survives_reload_and_logout(page):
    reset()
    ui_login(page, "ada")
    assert page.url.rstrip("/") == BASE
    page.reload()
    expect(T(page, "wallet-balance")).to_have_text("100.00 EUR")
    page.goto(BASE + "/requests")
    expect(T(page, "current-user")).to_be_visible()
    T(page, "logout-button").click()
    page.wait_for_url("**/login")
    expect(T(page, "current-user")).to_have_count(0)
    page.goto(BASE + "/")
    page.wait_for_url("**/login")


def test_auth_errors_present_only_on_error_and_clear(page):
    reset()
    page.goto(BASE + "/login")
    expect(T(page, "auth-error")).to_have_count(0)
    T(page, "login-email").fill("ada@example.com")
    T(page, "login-password").fill("wrong password")
    T(page, "login-submit").click()
    expect(T(page, "auth-error")).to_be_visible()
    assert T(page, "auth-error").text_content().strip()
    T(page, "login-password").fill("correct horse")
    T(page, "login-submit").click()
    T(page, "wallet-balance").wait_for()
    # signup failures
    page.goto(BASE + "/signup")
    def attempt(email, password, name="N"):
        T(page, "signup-email").fill(email)
        T(page, "signup-password").fill(password)
        T(page, "signup-display-name").fill(name)
        T(page, "signup-submit").click()
        expect(T(page, "auth-error")).to_be_visible()
    attempt("ada@example.com", "longenough")          # email taken
    attempt("ada@other.io", "longenough")             # handle taken
    attempt("new@example.com", "short")               # short password
    attempt("not-an-email", "longenough")             # bad email
    T(page, "signup-email").fill("fresh@example.com")
    T(page, "signup-password").fill("longenough")
    T(page, "signup-submit").click()
    expect(T(page, "wallet-balance")).to_have_text("0.00 EUR")
    expect(T(page, "current-handle")).to_have_text("fresh")


# ---------------------------------------------------------------- N: wallet and pay form

def test_wallet_formats_for_each_currency(page):
    for cur, units, balance, want in (("EUR", 2, 10005, "100.05 EUR"), ("JPY", 0, 1200, "1200 JPY"), ("BHD", 3, 1500, "1.500 BHD"), ("EUR", 2, 5, "0.05 EUR")):
        reset({"currency": cur, "minor_units": units, "users": [user("u_ada", "ada", balance), user("u_bob", "bob", 0)]})
        page.goto(BASE + "/login")
        page.evaluate("t => localStorage.setItem('pocketful.session', JSON.stringify({token: t}))", token_for("ada"))
        page.goto(BASE + "/")
        expect(T(page, "wallet-balance")).to_have_text(want)
        assert amount_of(page, "wallet-balance") == str(balance)
        expect(T(page, "wallet-available")).to_have_text(want)
        expect(T(page, "wallet-held")).to_have_count(0)


@pytest.mark.parametrize("typed,minor", [("15.00", 1500), ("15", 1500), ("15.5", 1550), (" 2 ", 200), ("0.29", 29)])
def test_pay_decimal_input_submits_minor_units(page, typed, minor):
    seed_basic()
    with_session(page, "ada")
    page.goto(BASE + "/")
    bodies = []
    page.on("request", lambda r: bodies.append(r.post_data) if r.method == "POST" and r.url.endswith("/payments") else None)
    T(page, "pay-handle").fill("bob")
    T(page, "pay-amount").fill(typed)
    T(page, "pay-submit").click()
    expect(T(page, "pay-success")).to_be_visible()
    assert json.loads(bodies[0])["amount"] == minor


@pytest.mark.parametrize("typed", ["15.005", "abc", "", "-1", "1e3", ".5", "5.", "1,000"])
def test_bad_amount_shows_error_and_sends_nothing(page, typed):
    seed_basic()
    with_session(page, "ada")
    page.goto(BASE + "/")
    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    for prefix, handle in (("pay", "bob"), ("request", "bob"), ("authorize", "bob")):
        T(page, f"{prefix}-handle").fill(handle)
        T(page, f"{prefix}-amount").fill(typed)
        T(page, f"{prefix}-submit").click()
        expect(T(page, f"{prefix}-error")).to_be_visible()
    assert posts == []


def test_jpy_rejects_any_fraction(page):
    reset({"currency": "JPY", "minor_units": 0, "users": [user("u_ada", "ada", 5000), user("u_bob", "bob", 0)]})
    with_session(page, "ada")
    page.goto(BASE + "/")
    T(page, "pay-handle").fill("bob")
    T(page, "pay-amount").fill("100.0")
    T(page, "pay-submit").click()
    expect(T(page, "pay-error")).to_be_visible()
    T(page, "pay-amount").fill("100")
    T(page, "pay-submit").click()
    expect(T(page, "wallet-balance")).to_have_text("4900 JPY")
    expect(T(page, "pay-error")).to_have_count(0)


def test_pay_success_keeps_form_and_unchanged_resubmit_pays_once(page):
    seed_basic()
    with_session(page, "ada")
    page.goto(BASE + "/")
    keys = []
    page.on("request", lambda r: keys.append(r.headers.get("idempotency-key")) if r.method == "POST" and r.url.endswith("/payments") else None)
    T(page, "pay-handle").fill("bob")
    T(page, "pay-amount").fill("15.00")
    T(page, "pay-note").fill("dinner <b>x</b>")
    T(page, "pay-visibility").select_option("private")
    T(page, "pay-submit").click()
    expect(T(page, "wallet-balance")).to_have_text("85.00 EUR")
    expect(T(page, "wallet-available")).to_have_text("85.00 EUR")
    assert T(page, "pay-handle").input_value() == "bob"
    assert T(page, "pay-amount").input_value() == "15.00"
    assert T(page, "pay-note").input_value() == "dinner <b>x</b>"
    assert T(page, "pay-visibility").input_value() == "private"
    expect(T(page, "pay-error")).to_have_count(0)
    items = page.locator("[data-testid^='activity-item-']")
    expect(items).to_have_count(2)
    T(page, "pay-submit").click()
    T(page, "pay-submit").click()
    page.wait_for_timeout(600)
    expect(T(page, "wallet-balance")).to_have_text("85.00 EUR")
    expect(items).to_have_count(2)
    expect(T(page, "pay-error")).to_have_count(0)
    assert len(set(keys)) == 1 and len(keys) >= 1
    # the private payment carries its visibility and note verbatim as text
    item = page.locator("[data-testid^='activity-item-'][data-visibility='private']")
    expect(item).to_have_count(1)
    assert item.locator("[data-testid^='activity-note-']").text_content() == "dinner <b>x</b>"
    assert item.locator("b").count() == 0


@pytest.mark.parametrize("field,value", [("pay-handle", "cy"), ("pay-amount", "16.00"), ("pay-note", "changed"), ("pay-visibility", "private")])
def test_changing_any_field_is_a_new_payment(page, field, value):
    seed_basic()
    with_session(page, "ada")
    page.goto(BASE + "/")
    seen = []
    page.on("request", lambda r: seen.append((r.headers.get("idempotency-key"), r.post_data)) if r.method == "POST" and r.url.endswith("/payments") else None)
    T(page, "pay-handle").fill("bob")
    T(page, "pay-amount").fill("1.00")
    T(page, "pay-submit").click()
    expect(T(page, "pay-success")).to_be_visible()
    if field == "pay-visibility":
        T(page, field).select_option(value)
    else:
        T(page, field).fill(value)
    T(page, "pay-submit").click()
    expect(T(page, "wallet-balance")).to_have_text(re.compile(r"9[78]\.\d\d EUR|8\d\.\d\d EUR"))
    page.wait_for_timeout(300)
    assert len(seen) == 2 and seen[0][0] != seen[1][0]
    status, me = api("GET", "/me", token=token_for("ada"))
    assert me["balance"] == 10000 - 100 - (1600 if field == "pay-amount" else 100)


def test_double_click_sends_one_payment(page):
    seed_basic()
    with_session(page, "ada")
    page.goto(BASE + "/")
    T(page, "pay-handle").fill("bob")
    T(page, "pay-amount").fill("10.00")
    T(page, "pay-submit").dblclick()
    page.wait_for_timeout(800)
    expect(T(page, "wallet-balance")).to_have_text("90.00 EUR")
    status, feed = api("GET", "/activity", token=token_for("ada"))
    assert len([p for p in feed["payments"] if p["amount"] == 1000]) == 1


def test_refused_payments_show_pay_error_and_preserve_inputs(page):
    seed_basic()
    with_session(page, "ada")
    page.goto(BASE + "/")
    for handle, amount in (("ghost", "1.00"), ("ada", "1.00"), ("bob", "0")):
        T(page, "pay-handle").fill(handle)
        T(page, "pay-amount").fill(amount)
        T(page, "pay-note").fill("keep me")
        T(page, "pay-submit").click()
        expect(T(page, "pay-error")).to_be_visible()
        expect(T(page, "pay-uncertain")).to_have_count(0)
        assert T(page, "pay-note").input_value() == "keep me"
        assert T(page, "pay-handle").input_value() == handle


def test_request_form(page):
    seed_basic()
    with_session(page, "ada")
    page.goto(BASE + "/")
    T(page, "request-handle").fill("bob")
    T(page, "request-amount").fill("12.50")
    T(page, "request-note").fill("lunch")
    T(page, "request-submit").click()
    expect(T(page, "request-success")).to_be_visible()
    expect(T(page, "request-error")).to_have_count(0)
    T(page, "request-submit").click()  # unchanged: replay, not a second request
    page.wait_for_timeout(500)
    status, out = api("GET", "/requests?direction=outgoing", token=token_for("ada"))
    assert len(out["requests"]) == 1 and out["requests"][0]["amount"] == 1250
    for handle, amount in (("ghost", "1"), ("ada", "1"), ("bob", "0")):
        T(page, "request-handle").fill(handle)
        T(page, "request-amount").fill(amount)
        T(page, "request-submit").click()
        expect(T(page, "request-error")).to_be_visible()


# ---------------------------------------------------------------- P: feed

def test_feed_content_order_visibility_and_text_rendering(page):
    nasty = "<img src=x onerror=\"window.__pwned=1\"> &amp; <b>x</b>  "
    reset(fixture(payments=[
        {"id": "p_a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": nasty, "visibility": "public", "created_at": "2026-01-01T10:00:00+00:00"},
        {"id": "p_b", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1234, "note": " 🍝 é ", "visibility": "private", "created_at": "2026-01-02T10:00:00+00:00"},
        {"id": "p_c", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 99, "note": "", "visibility": "private", "created_at": "2026-01-03T10:00:00+00:00"},
        {"id": "p_d", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 7, "note": "open", "visibility": "public", "created_at": "2026-01-04T10:00:00+00:00"},
    ]))
    with_session(page, "ada")
    page.goto(BASE + "/")
    expect(T(page, "activity-list")).to_be_visible()
    ids = page.evaluate("[...document.querySelectorAll('[data-testid=activity-list] > [data-testid^=activity-item-]')].map(e => e.dataset.testid)")
    assert ids == ["activity-item-p_d", "activity-item-p_b", "activity-item-p_a"]   # newest first; p_c is private between others
    expect(T(page, "activity-item-p_b")).to_have_attribute("data-visibility", "private")
    expect(T(page, "activity-item-p_a")).to_have_attribute("data-visibility", "public")
    expect(T(page, "activity-amount-p_b")).to_have_text("12.34 EUR")
    parties = T(page, "activity-parties-p_a").text_content()
    assert "ada" in parties and "bob" in parties
    assert T(page, "activity-note-p_a").text_content() == nasty
    assert T(page, "activity-note-p_b").text_content() == " 🍝 é "
    assert page.evaluate("window.__pwned") is None
    assert page.locator("[data-testid=activity-list] img, [data-testid=activity-list] b").count() == 0


def test_empty_feed(page):
    reset()
    with_session(page, "cy")
    page.goto(BASE + "/")
    expect(T(page, "empty-activity")).to_be_visible()
    expect(T(page, "activity-list")).to_have_count(0)


def test_feed_shows_newest_200_with_load_more(page):
    pays = [{"id": f"p_{i:03d}", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1, "note": f"n{i}", "visibility": "public", "created_at": f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00"} for i in range(230)]
    reset(fixture(payments=pays))
    with_session(page, "ada")
    page.goto(BASE + "/")
    expect(page.locator("[data-testid^='activity-item-']")).to_have_count(200)
    T(page, "activity-more").click()
    expect(page.locator("[data-testid^='activity-item-']")).to_have_count(230)


# ---------------------------------------------------------------- Q: requests and split

def test_requests_screen_lists_actions_and_refresh(page):
    reset(fixture(requests=[
        {"id": "rq_in", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
        {"id": "rq_out", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 800, "note": "lunch", "status": "pending"},
        {"id": "rq_paid", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 300, "note": "", "status": "paid"},
        {"id": "rq_dec", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 50, "note": "", "status": "declined"},
        {"id": "rq_can", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 60, "note": "", "status": "cancelled"},
    ]))
    with_session(page, "ada")
    page.goto(BASE + "/requests")
    expect(T(page, "incoming-list")).to_be_visible()
    expect(T(page, "outgoing-list")).to_be_visible()
    expect(T(page, "empty-requests")).to_have_count(0)
    expect(T(page, "request-item-rq_in")).to_have_attribute("data-status", "pending")
    expect(T(page, "request-amount-rq_in")).to_have_text("12.00 EUR")
    for tid, n in (("request-pay-rq_in", 1), ("request-decline-rq_in", 1), ("request-cancel-rq_out", 1), ("request-pay-rq_out", 0), ("request-cancel-rq_in", 0), ("request-pay-rq_paid", 0), ("request-decline-rq_dec", 0), ("request-cancel-rq_can", 0), ("request-decline-rq_paid", 0)):
        expect(T(page, tid)).to_have_count(n)
    T(page, "request-cancel-rq_out").click()
    expect(T(page, "request-item-rq_out")).to_have_attribute("data-status", "cancelled")
    expect(T(page, "request-cancel-rq_out")).to_have_count(0)
    T(page, "request-pay-rq_in").click()
    expect(T(page, "request-item-rq_in")).to_have_attribute("data-status", "paid")
    expect(T(page, "request-pay-rq_in")).to_have_count(0)
    status, me = api("GET", "/me", token=token_for("ada"))
    assert me["balance"] == 8800
    with_session(page, "bob")
    page.goto(BASE + "/requests")
    T(page, "request-item-rq_dec").wait_for()


def test_requests_empty_and_both_containers_present(page):
    reset()
    with_session(page, "cy")
    page.goto(BASE + "/requests")
    expect(T(page, "incoming-list")).to_be_attached()
    expect(T(page, "outgoing-list")).to_be_attached()
    expect(T(page, "empty-requests")).to_be_visible()


def test_request_pay_visibility_selector_and_refusals(page):
    reset(fixture(requests=[
        {"id": "rq_a", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 100, "note": "", "status": "pending"},
        {"id": "rq_big", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 999999, "note": "", "status": "pending"},
    ]))
    with_session(page, "ada")
    page.goto(BASE + "/requests")
    T(page, "request-visibility-rq_a").select_option("private")
    T(page, "request-pay-rq_a").click()
    expect(T(page, "request-item-rq_a")).to_have_attribute("data-status", "paid")
    status, feed = api("GET", "/activity", token=token_for("cy"))
    assert feed["payments"] == []
    T(page, "request-pay-rq_big").click()
    expect(T(page, "request-error")).to_be_visible()
    expect(T(page, "request-item-rq_big")).to_have_attribute("data-status", "pending")


def test_stale_request_controls_refresh_after_refusal(page):
    reset(fixture(requests=[
        {"id": "rq_x", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 100, "note": "", "status": "pending"},
        {"id": "rq_y", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 100, "note": "", "status": "pending"},
        {"id": "rq_z", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 100, "note": "", "status": "pending"},
    ]))
    with_session(page, "ada")
    page.goto(BASE + "/requests")
    T(page, "request-pay-rq_x").wait_for()
    bob = token_for("bob")
    assert api("POST", "/requests/rq_x/cancel", token=bob)[0] == 200
    T(page, "request-pay-rq_x").click()
    expect(T(page, "request-error")).to_be_visible()
    expect(T(page, "request-pay-rq_x")).to_have_count(0)
    expect(T(page, "request-item-rq_x")).to_have_attribute("data-status", "cancelled")
    assert api("POST", "/requests/rq_y/cancel", token=bob)[0] == 200
    T(page, "request-decline-rq_y").click()
    expect(T(page, "request-error")).to_be_visible()
    expect(T(page, "request-decline-rq_y")).to_have_count(0)
    assert api("POST", "/requests/rq_z/decline", token=bob)[0] == 200
    T(page, "request-cancel-rq_z").click()
    expect(T(page, "request-error")).to_be_visible()
    expect(T(page, "request-cancel-rq_z")).to_have_count(0)


def preview_shares(page):
    return page.evaluate("[...document.querySelectorAll('[data-testid=split-preview] [data-testid^=split-share-]')].map(e => [e.dataset.testid.slice(12), e.textContent])")


def test_split_preview_matches_rule_and_submission(page):
    reset(fixture(users=[user("u_ada", "ada", 10000), user("u_bob", "bob", 0), user("u_cy", "cy", 0)]))
    with_session(page, "ada")
    page.goto(BASE + "/split")
    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    expect(T(page, "split-preview")).to_be_visible()
    T(page, "split-amount").fill("10.00")
    T(page, "split-handles").fill("ada, bob , cy")
    assert preview_shares(page) == [["ada", "3.34 EUR"], ["bob", "3.33 EUR"], ["cy", "3.33 EUR"]]
    T(page, "split-handles").fill("cy,bob,ada")
    assert preview_shares(page) == [["cy", "3.34 EUR"], ["bob", "3.33 EUR"], ["ada", "3.33 EUR"]]
    T(page, "split-amount").fill("0.01")
    assert [s[1] for s in preview_shares(page)] == ["0.01 EUR", "0.00 EUR", "0.00 EUR"]
    assert posts == []
    T(page, "split-amount").fill("10.00")
    T(page, "split-handles").fill("ada, bob, cy")
    T(page, "split-note").fill("pizza")
    T(page, "split-submit").click()
    expect(T(page, "split-success")).to_be_visible()
    status, out = api("GET", "/requests?direction=outgoing", token=token_for("ada"))
    assert sorted((r["payer_handle"], r["amount"]) for r in out["requests"]) == [("bob", 333), ("cy", 333)]
    page.goto(BASE + "/requests")
    expect(page.locator("[data-testid=outgoing-list] [data-testid^=request-item-]")).to_have_count(2)


def test_split_preview_jpy_and_errors(page):
    reset({"currency": "JPY", "minor_units": 0, "users": [user("u_ada", "ada", 100), user("u_bob", "bob", 0), user("u_cy", "cy", 0)]})
    with_session(page, "ada")
    page.goto(BASE + "/split")
    T(page, "split-amount").fill("1000")
    T(page, "split-handles").fill("ada,bob,cy")
    assert preview_shares(page) == [["ada", "334 JPY"], ["bob", "333 JPY"], ["cy", "333 JPY"]]
    for amount, handles in (("abc", "bob"), ("1000", ""), ("1000", "bob,bob"), ("1000", "ghost"), ("1000.5", "bob"), ("0", "bob")):
        T(page, "split-amount").fill(amount)
        T(page, "split-handles").fill(handles)
        T(page, "split-submit").click()
        expect(T(page, "split-error")).to_be_visible()
        expect(T(page, "split-success")).to_have_count(0)


# ---------------------------------------------------------------- R: competing clients, uncertainty

def test_refresh_keeps_form_and_latest_refresh_wins(page):
    seed_basic()
    token = with_session(page, "ada")
    page.goto(BASE + "/")
    expect(T(page, "wallet-balance")).to_have_text("100.00 EUR")
    T(page, "pay-handle").fill("bob")
    T(page, "pay-amount").fill("1.00")
    page.route(re.compile(r".*/(me|activity)(\?.*)?$"), lambda route: held_handler(route))
    calls = {"me": [], "act": []}
    def held_handler(route):
        kind = "me" if route.request.url.split("?")[0].endswith("/me") else "act"
        if not calls[kind]:
            calls[kind].append((route, route.fetch()))
        else:
            route.continue_()
    T(page, "wallet-refresh").click()                         # refresh #1: delayed responses (balance 100.00)
    page.wait_for_timeout(200)
    assert api("POST", "/payments", {"to_handle": "cy", "amount": 4000}, token=token, key="other-client")[0] == 201
    T(page, "wallet-refresh").click()                         # refresh #2: answered at once (balance 60.00)
    expect(T(page, "wallet-balance")).to_have_text("60.00 EUR")
    for kind in ("me", "act"):
        route, resp = calls[kind][0]
        route.fulfill(response=resp)                          # the stale answers arrive late, out of order
    page.wait_for_timeout(500)
    expect(T(page, "wallet-balance")).to_have_text("60.00 EUR")
    expect(T(page, "wallet-available")).to_have_text("60.00 EUR")
    assert page.locator("[data-testid^='activity-item-']").count() == 2
    assert T(page, "pay-handle").input_value() == "bob" and T(page, "pay-amount").input_value() == "1.00"


def test_balance_spent_elsewhere_gives_refusal_and_refreshes(page):
    seed_basic()
    token = with_session(page, "ada")
    page.goto(BASE + "/")
    expect(T(page, "wallet-balance")).to_have_text("100.00 EUR")
    assert api("POST", "/payments", {"to_handle": "cy", "amount": 10000}, token=token, key="drain")[0] == 201
    T(page, "pay-handle").fill("bob")
    T(page, "pay-amount").fill("5.00")
    T(page, "pay-note").fill("late")
    T(page, "pay-submit").click()
    expect(T(page, "pay-error")).to_be_visible()
    expect(T(page, "pay-uncertain")).to_have_count(0)
    expect(T(page, "wallet-balance")).to_have_text("0.00 EUR")
    expect(page.locator("[data-testid^='activity-item-']")).to_have_count(2)
    assert (T(page, "pay-handle").input_value(), T(page, "pay-amount").input_value(), T(page, "pay-note").input_value()) == ("bob", "5.00", "late")


@pytest.mark.parametrize("mode", ["abort-before", "abort-after-commit", "server-500", "unparseable", "http-200-html"])
def test_lost_response_is_uncertain_and_retry_pays_once(page, mode):
    seed_basic()
    token = with_session(page, "ada")
    page.goto(BASE + "/")
    expect(T(page, "wallet-balance")).to_have_text("100.00 EUR")
    seen = []
    def lose(route):
        seen.append((route.request.headers.get("idempotency-key"), route.request.post_data))
        if mode == "abort-before":
            route.abort()
        elif mode == "abort-after-commit":
            route.fetch()
            route.abort()
        elif mode == "server-500":
            route.fulfill(status=500, content_type="application/json", body='{"error":{"code":"boom","message":"boom"}}')
        elif mode == "unparseable":
            route.fetch()
            route.fulfill(status=201, content_type="application/json", body="{not json")
        else:
            route.fetch()
            route.fulfill(status=200, content_type="text/html", body="<html>gateway</html>")
    page.route("**/payments", lose)
    T(page, "pay-handle").fill("bob")
    T(page, "pay-amount").fill("30.00")
    T(page, "pay-note").fill("retry me")
    T(page, "pay-submit").click()
    expect(T(page, "pay-uncertain")).to_be_visible()
    assert T(page, "pay-uncertain").text_content().strip()
    expect(T(page, "pay-error")).to_have_count(0)
    assert T(page, "pay-amount").input_value() == "30.00"
    page.unroute("**/payments")
    page.on("request", lambda r: seen.append((r.headers.get("idempotency-key"), r.post_data)) if r.method == "POST" and r.url.endswith("/payments") else None)
    T(page, "pay-submit").click()
    expect(T(page, "pay-success")).to_be_visible()
    expect(T(page, "pay-uncertain")).to_have_count(0)
    expect(T(page, "pay-error")).to_have_count(0)
    expect(T(page, "wallet-balance")).to_have_text("70.00 EUR")
    assert len(seen) == 2 and seen[0] == seen[1], seen
    status, feed = api("GET", "/activity", token=token_for("ada"))
    assert len([p for p in feed["payments"] if p["note"] == "retry me"]) == 1
    expect(page.locator("[data-testid^='activity-item-']")).to_have_count(2)


def test_refusal_envelope_is_error_not_uncertain(page):
    seed_basic()
    with_session(page, "ada")
    page.goto(BASE + "/")
    page.route("**/payments", lambda r: r.fulfill(status=422, content_type="application/json", body='{"error":{"code":"validation_failed","message":"nope"}}'))
    T(page, "pay-handle").fill("bob")
    T(page, "pay-amount").fill("1.00")
    T(page, "pay-submit").click()
    expect(T(page, "pay-error")).to_be_visible()
    expect(T(page, "pay-uncertain")).to_have_count(0)


def test_hung_request_times_out_as_uncertain(page):
    seed_basic()
    with_session(page, "ada")
    page.goto(BASE + "/")
    page.route("**/payments", lambda r: None)       # never answered
    T(page, "pay-handle").fill("bob")
    T(page, "pay-amount").fill("1.00")
    T(page, "pay-submit").click()
    expect(T(page, "pay-submit")).to_be_disabled()
    page.wait_for_timeout(500)
    expect(T(page, "pay-uncertain")).to_be_visible(timeout=13000)
    expect(T(page, "pay-error")).to_have_count(0)
    expect(T(page, "pay-submit")).to_be_enabled()
