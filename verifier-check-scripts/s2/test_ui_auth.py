"""W / U3. Signup, login, logout and the signed-in chrome, in a real browser at 375 px and 1280 px."""
import pytest
from playwright.sync_api import expect

from lib import PW, World, call, fixture, k, ok, soft, user

ROUTES = ["/", "/requests", "/split", "/authorizations", "/signup", "/login"]


def test_w2_login_and_chrome_on_every_route(ui, vp):
    World(fixture(users=[user("ada", 10000, display_name="Ada Lovelace"), user("bob", 0)]))
    u = ui(vp)
    u.goto("/login")
    for tid in ("login-email", "login-password", "login-submit"):
        expect(u.t(tid)).to_be_visible()
    assert u.t("auth-error").count() == 0, "auth-error must be present only when there is an error"
    assert u.t("current-user").count() == 0
    u.t("login-email").fill("ada@example.com")
    u.t("login-password").fill(PW)
    u.t("login-submit").click()
    expect(u.t("current-user")).to_be_visible()
    for path in ROUTES:                                     # W5 / U3: full page loads keep the session
        u.goto(path)
        expect(u.t("current-user")).to_be_visible()
        expect(u.t("current-user")).to_contain_text("Ada Lovelace")
        expect(u.t("current-handle")).to_have_text("ada")
        assert u.t("current-handle").text_content().strip() == "ada", path
        expect(u.t("logout-button")).to_be_visible()
        assert u.t("auth-error").count() == 0, path
    assert not u.errors, u.errors


def test_w1_signup_signs_in(ui, vp):
    w = World()
    u = ui(vp)
    u.goto("/signup")
    for tid in ("signup-email", "signup-password", "signup-display-name", "signup-submit"):
        expect(u.t(tid)).to_be_visible()
    assert u.t("auth-error").count() == 0
    u.t("signup-email").fill("New.Person+tag@example.com")
    u.t("signup-password").fill("longenough1")
    u.t("signup-display-name").fill("Néw Pérson")
    u.t("signup-submit").click()
    expect(u.t("current-user")).to_be_visible()
    expect(u.t("current-user")).to_contain_text("Néw Pérson")
    expect(u.t("current-handle")).to_have_text("new_person_tag")
    u.goto("/")
    expect(u.t("wallet-balance")).to_have_text("0.00 EUR")
    assert u.amount("wallet-balance") == 0
    expect(u.t("empty-activity")).to_be_visible()
    # the account really exists and can be paid
    ok(w.pay("ada", "new_person_tag", 250), 201)
    u.t("wallet-refresh").click()
    expect(u.t("wallet-balance")).to_have_text("2.50 EUR")


def test_w3_auth_error_only_when_there_is_one(ui, vp):
    World()
    u = ui(vp)
    u.goto("/login")
    u.t("login-email").fill("ada@example.com")
    u.t("login-password").fill("wrong horse")
    u.t("login-submit").click()
    expect(u.t("auth-error")).to_be_visible()
    assert u.t("auth-error").text_content().strip() != ""
    assert u.t("current-user").count() == 0
    u.t("login-email").fill("ghost@example.com")
    u.t("login-password").fill(PW)
    u.t("login-submit").click()
    expect(u.t("auth-error")).to_be_visible()
    u.t("login-email").fill("ada@example.com")
    u.t("login-password").fill(PW)
    u.t("login-submit").click()
    expect(u.t("current-user")).to_be_visible()
    expect(u.t("auth-error")).to_have_count(0)
    # signup refusals
    u2 = ui(vp)
    u2.goto("/signup")
    cases = [("ada@example.com", "longenough1", "X"),            # email taken
             ("a.d.a@other.example", "short", "X"),             # password too short
             ("not-an-email", "longenough1", "X"),              # not local@domain
             ("ada@elsewhere.example", "longenough1", "X")]     # derived handle taken
    for email, pw, name in cases:
        u2.t("signup-email").fill(email)
        u2.t("signup-password").fill(pw)
        u2.t("signup-display-name").fill(name)
        u2.t("signup-submit").click()
        expect(u2.t("auth-error")).to_be_visible()
        assert u2.t("auth-error").text_content().strip() != "", email
        assert u2.t("current-user").count() == 0, email
    u2.t("signup-email").fill("fresh.one@example.com")
    u2.t("signup-password").fill("longenough1")
    u2.t("signup-display-name").fill("Fresh")
    u2.t("signup-submit").click()
    expect(u2.t("current-user")).to_be_visible()
    expect(u2.t("auth-error")).to_have_count(0)


def test_w4_logout(ui, vp):
    World()
    u = ui(vp).login("ada")
    u.goto("/")
    expect(u.t("wallet-balance")).to_be_visible()
    u.t("logout-button").click()
    expect(u.t("current-user")).to_have_count(0)
    for path in ("/", "/requests", "/split", "/authorizations"):
        u.goto(path)
        u.page.wait_for_timeout(400)
        assert u.t("current-user").count() == 0, f"still signed in on {path} after logout"
        assert u.t("wallet-balance").count() == 0 or not u.t("wallet-balance").is_visible() or \
            u.t("wallet-balance").text_content().strip() == "", f"{path} shows a balance while signed out"
        soft(u.t("login-email").count() > 0, "signed-out-screen-not-leading-to-login", path=path, url=u.page.url)
    # a second browser context was never signed in
    v = ui(vp)
    v.goto("/")
    v.page.wait_for_timeout(400)
    assert v.t("current-user").count() == 0
    # and signing in again works
    u.login("bob")
    expect(u.t("current-handle")).to_have_text("bob")


def test_u3_navigation_is_the_same_on_every_route(ui, vp):
    World()
    u = ui(vp).login("ada")
    seen = {}
    for path in ("/", "/requests", "/split", "/authorizations"):
        u.goto(path)
        expect(u.t("current-user")).to_be_visible()
        hrefs = u.page.evaluate("""() => Array.from(document.querySelectorAll('a[href]'))
            .map(a => new URL(a.getAttribute('href'), location.href).pathname)""")
        seen[path] = set(hrefs)
        for target in ("/", "/requests", "/split", "/authorizations"):
            assert target in seen[path], f"{path} has no link to {target} (links: {sorted(seen[path])})"
    # the links work by clicking, at this viewport
    u.goto("/")
    for target, marker in (("/requests", "incoming-list"), ("/split", "split-amount"),
                           ("/authorizations", "authorization-list"), ("/", "pay-submit")):
        link = u.page.locator(f"a[href='{target}']").first
        if not link.is_visible():
            # a collapsed menu at narrow widths: open the first visible toggle
            toggles = u.page.locator("button[aria-controls], button[aria-expanded], summary")
            for i in range(toggles.count()):
                if toggles.nth(i).is_visible():
                    toggles.nth(i).click()
                    break
        expect(link).to_be_visible()
        link.click()
        if marker == "authorization-list":
            expect(u.page.locator("[data-testid='authorization-list'], [data-testid='empty-authorizations']").first).to_be_visible()
        else:
            expect(u.t(marker)).to_be_visible()
        expect(u.t("current-handle")).to_have_text("ada")


def test_w_login_by_keyboard(ui):
    World()
    u = ui("wide")
    u.goto("/login")
    u.t("login-email").focus()
    u.page.keyboard.type("ada@example.com")
    u.page.keyboard.press("Tab")
    focused = u.page.evaluate("document.activeElement && document.activeElement.getAttribute('data-testid')")
    assert focused == "login-password", f"Tab from the email field lands on {focused!r}"
    u.page.keyboard.type(PW)
    u.page.keyboard.press("Enter")
    expect(u.t("current-user")).to_be_visible()
