"""Screenshots of every screen at 375px and 1280px, signed out and populated.

Usage: BASE_URL=http://127.0.0.1:18080 python shots.py <output-dir>
"""
import os
import sys
from playwright.sync_api import sync_playwright
from common import BASE, api, fixture, reset, iso, token_for, with_session, ui_login

out = sys.argv[1]
os.makedirs(out, exist_ok=True)

LONG = "Dinner at the very long named restaurant " + "x" * 80 + " 🍝 thanks for the lovely evening"
fx = fixture(
    payments=[
        {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
        {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1234, "note": LONG, "visibility": "private"},
        {"id": "p_3", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 99, "note": "", "visibility": "public"},
    ],
    requests=[
        {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
        {"id": "rq_2", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 800, "note": LONG, "status": "pending"},
        {"id": "rq_3", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 300, "note": "lunch", "status": "paid"},
        {"id": "rq_4", "requester_id": "u_cy", "payer_id": "u_ada", "amount": 50, "note": "gum", "status": "declined"},
    ],
    authorizations=[
        {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit", "visibility": "public", "status": "open", "expires_at": iso(7200)},
        {"id": "a_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 700, "note": "deposit back", "visibility": "private", "status": "open", "expires_at": iso(7200)},
        {"id": "a_3", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 400, "captured_amount": 400, "note": "done", "visibility": "public", "status": "captured", "expires_at": iso(7200), "payment_id": "p_1"},
        {"id": "a_4", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 100, "note": "old", "visibility": "public", "status": "open", "expires_at": iso(-7200)},
    ],
)

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width, height, tag in ((375, 800, "m"), (1280, 900, "d")):
        ctx = browser.new_context(viewport={"width": width, "height": height})
        page = ctx.new_page()
        reset()
        for route in ("/login", "/signup"):
            page.goto(BASE + route)
            page.wait_for_selector("form")
            page.screenshot(path=f"{out}/{tag}-signed-out{route.replace('/', '-')}.png", full_page=True)
        page.goto(BASE + "/login")
        page.get_by_test_id("login-email").fill("ada@example.com")
        page.get_by_test_id("login-password").fill("nope nope")
        page.get_by_test_id("login-submit").click()
        page.get_by_test_id("auth-error").wait_for()
        page.screenshot(path=f"{out}/{tag}-login-error.png", full_page=True)
        # empty wallet
        reset()
        with_session(page, "cy")
        for route, name in (("/", "home-empty"), ("/requests", "requests-empty"), ("/split", "split-empty"), ("/authorizations", "auth-empty")):
            page.goto(BASE + route)
            page.get_by_test_id("current-user").wait_for()
            page.wait_for_timeout(500)
            page.screenshot(path=f"{out}/{tag}-{name}.png", full_page=True)
        # populated
        reset(fx)
        with_session(page, "ada")
        for route, name in (("/", "home"), ("/requests", "requests"), ("/split", "split"), ("/authorizations", "authorizations")):
            page.goto(BASE + route)
            page.get_by_test_id("current-user").wait_for()
            page.wait_for_timeout(500)
            if route == "/split":
                page.get_by_test_id("split-amount").fill("10.00")
                page.get_by_test_id("split-handles").fill("ada, bob, cy")
            page.screenshot(path=f"{out}/{tag}-{name}.png", full_page=True)
            overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            print(tag, route, "overflow", overflow)
        # states: refused, uncertain, success on home
        page.goto(BASE + "/")
        page.get_by_test_id("wallet-balance").wait_for()
        page.get_by_test_id("pay-handle").fill("bob")
        page.get_by_test_id("pay-amount").fill("999999.00")
        page.get_by_test_id("pay-submit").click()
        page.get_by_test_id("pay-error").wait_for()
        page.screenshot(path=f"{out}/{tag}-home-refused.png", full_page=True)
        page.route("**/payments", lambda r: r.abort())
        page.get_by_test_id("pay-amount").fill("1.00")
        page.get_by_test_id("pay-submit").click()
        page.get_by_test_id("pay-uncertain").wait_for()
        page.screenshot(path=f"{out}/{tag}-home-uncertain.png", full_page=True)
        page.unroute("**/payments")
        page.get_by_test_id("pay-submit").click()
        page.get_by_test_id("pay-success").wait_for()
        page.screenshot(path=f"{out}/{tag}-home-success.png", full_page=True)
        ctx.close()
    browser.close()
