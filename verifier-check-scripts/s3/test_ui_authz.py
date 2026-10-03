"""R. Authorisation UI: wallet numbers, authorise form, the /authorizations screen."""
import json
import time

import pytest
from playwright.sync_api import expect

from lib import PW, World, call, fixture, iso, k, ok, seeded_auth, soft, user


def seeded():
    auths = [
        seeded_auth("a_out_open", "ada", "bob", 2000, note="deposit"),
        seeded_auth("a_out_cap", "ada", "bob", 700, status="captured", expires_in=-7200),
        seeded_auth("a_out_void", "ada", "cy", 800, status="voided"),
        seeded_auth("a_out_exp", "ada", "cy", 900, status="expired", expires_in=-7200),
        seeded_auth("a_out_clock", "ada", "cy", 950, status="open", expires_in=-3700),
        seeded_auth("a_in_open", "bob", "ada", 1000, note="incoming", visibility="private"),
        seeded_auth("a_in_void", "bob", "ada", 300, status="voided"),
        seeded_auth("a/odd id.3", "cy", "ada", 5, expires_in=9000),
        seeded_auth("a_not_adas", "bob", "cy", 100),
    ]
    users = [user("ada", 10000), user("bob", 2500), user("cy", 100), user("dan", 500), user("op", 0)]
    return World(fixture(users=users, auths=auths)), auths


def form_page(u):
    """The page carrying the authorise form: the specification names the test ids, not the page."""
    for path in ("/authorizations", "/"):
        u.goto(path)
        expect(u.t("current-user")).to_be_visible()
        u.page.wait_for_timeout(300)
        if u.t("authorize-submit").count() > 0:
            return path
    raise AssertionError("authorize-submit is on neither /authorizations nor /")


def test_r1_wallet_numbers_right_after_reset(ui, vp):
    w, _ = seeded()
    u = ui(vp).login("ada").home()
    expect(u.t("wallet-balance")).to_have_text("100.00 EUR")
    assert u.amount("wallet-balance") == 10000
    expect(u.t("wallet-available")).to_have_text("80.00 EUR")
    assert u.amount("wallet-available") == 8000
    expect(u.t("wallet-held")).to_have_text("20.00 EUR")
    assert u.amount("wallet-held") == 2000
    for tid in ("wallet-balance", "wallet-available", "wallet-held"):
        expect(u.t(tid)).to_be_visible()
    # V2: available is the headline number
    def style(tid, prop, conv):
        for _ in range(20):                      # the wallet may be re-rendered while it is being measured
            v = u.page.evaluate("([t, p]) => { const e = document.querySelector(`[data-testid='${t}']`);"
                                " return e ? getComputedStyle(e)[p] : ''; }", [tid, prop])
            if v:
                return conv(v)
            u.page.wait_for_timeout(100)
        raise AssertionError(f"no computed {prop} for {tid}")

    size = lambda tid: style(tid, "fontSize", lambda v: float(v.replace("px", "")))  # noqa: E731
    weight = lambda tid: style(tid, "fontWeight", int)  # noqa: E731
    assert size("wallet-available") >= size("wallet-balance") and size("wallet-available") >= size("wallet-held")
    assert size("wallet-available") > size("wallet-balance") or weight("wallet-available") > weight("wallet-balance"), \
        "available is not presented more prominently than the total"
    u.shot(f"route-home-with-hold-{vp}")
    # a user without holds: held is absent, available equals the total
    v = ui(vp).login("dan").home()
    expect(v.t("wallet-available")).to_have_text("5.00 EUR")
    expect(v.t("wallet-balance")).to_have_text("5.00 EUR")
    assert v.t("wallet-held").count() == 0
    # paying against the available amount
    u.fill_pay("cy", "80.01", "more than available")
    u.t("pay-submit").click()
    expect(u.t("pay-error")).to_be_visible()
    u.t("pay-amount").fill("80.00")
    u.t("pay-submit").click()
    expect(u.t("wallet-available")).to_have_text("0.00 EUR")
    expect(u.t("wallet-balance")).to_have_text("20.00 EUR")
    expect(u.t("wallet-held")).to_have_text("20.00 EUR")


def test_r2_authorise_form(ui, vp):
    w = World()
    u = ui(vp).login("ada")
    path = form_page(u)
    for tid in ("authorize-handle", "authorize-amount", "authorize-note", "authorize-visibility", "authorize-submit"):
        expect(u.t(tid)).to_be_visible()
    values = u.t("authorize-visibility").locator("option").evaluate_all("els => els.map(e => e.value)")
    assert sorted(values) == ["private", "public"], values
    assert u.t("authorize-error").count() == 0
    # refusals: decimal rule without a request, then server refusals
    for bad in ("abc", "20.005", "", "1e2"):
        u.fill_pay("bob", bad, "hold", prefix="authorize")
        u.t("authorize-submit").click()
        expect(u.t("authorize-error")).to_be_visible()
    u.page.wait_for_timeout(200)
    assert u.sent("POST", "/authorizations") == []
    for handle, amount in (("bob", "100.01"), ("nobody_here", "1.00"), ("ada", "1.00"), ("bob", "0")):
        u.fill_pay(handle, amount, "hold", prefix="authorize")
        u.t("authorize-submit").click()
        expect(u.t("authorize-error")).to_be_visible()
        assert u.t("authorize-error").text_content().strip() != ""
    assert w.wallet("ada")["held"] == 0
    # success
    u.fill_pay("bob", "20.00", "deposit", "private", prefix="authorize")
    u.t("authorize-submit").click()
    expect(u.t("authorize-error")).to_have_count(0)
    u.page.wait_for_timeout(400)
    m = w.wallet("ada")
    assert (m["total"], m["available"], m["held"]) == (10000, 8000, 2000)
    a = w.auths("ada")[0]
    assert (a["amount"], a["note"], a["visibility"], a["to_handle"], a["status"]) == (2000, "deposit", "private", "bob", "open")
    sent = [(r.headers.get("idempotency-key"), json.loads(r.post_data)) for r in u.sent("POST", "/authorizations")]
    assert sent[-1][0] and sent[-1][1]["amount"] == 2000
    # unchanged form: no second hold; changed form: a second hold
    u.t("authorize-submit").click()
    u.page.wait_for_timeout(400)
    assert w.wallet("ada")["held"] == 2000 and len(w.auths("ada")) == 1
    u.t("authorize-amount").fill("5")
    u.t("authorize-submit").click()
    u.page.wait_for_timeout(400)
    assert w.wallet("ada")["held"] == 2500 and len(w.auths("ada")) == 2
    # the same page shows the new state without a reload (wallet numbers and/or the list, whichever it carries)
    if u.t("wallet-held").count():
        expect(u.t("wallet-held")).to_have_text("25.00 EUR")
        expect(u.t("wallet-available")).to_have_text("75.00 EUR")
    if path == "/authorizations":
        expect(u.t(f"authorization-item-{a['authorization_id']}")).to_have_attribute("data-status", "open")
    u.goto("/")
    expect(u.t("wallet-held")).to_have_text("25.00 EUR")
    expect(u.t("wallet-available")).to_have_text("75.00 EUR")
    expect(u.t("wallet-balance")).to_have_text("100.00 EUR")
    assert u.page.locator("[data-testid^='activity-item-']").count() == 0      # holds are not feed items


def test_r3_r4_authorization_list(ui, vp):
    w, auths = seeded()
    u = ui(vp).login("ada").goto("/authorizations")
    expect(u.t("authorization-list")).to_be_visible()
    api = w.auths("ada")
    assert len(api) == 8
    expect(u.page.locator("[data-testid^='authorization-item-']")).to_have_count(8)
    dom = u.t("authorization-list").locator("[data-testid^='authorization-item-']").evaluate_all(
        "els => els.map(e => e.getAttribute('data-testid'))")
    assert dom == [f"authorization-item-{a['authorization_id']}" for a in api], "not newest first in the DOM"
    assert u.t("authorization-item-a_not_adas").count() == 0
    for a in api:
        aid = a["authorization_id"]
        expect(u.t(f"authorization-item-{aid}")).to_have_attribute("data-status", a["status"])
        expect(u.t(f"authorization-amount-{aid}")).to_have_text(f"{a['amount'] // 100}.{a['amount'] % 100:02d} EUR")
        assert u.t(f"authorization-expires-{aid}").text_content().strip() == a["expires_at"], aid
        captured = u.t(f"authorization-captured-{aid}")
        if a["status"] == "captured":
            expect(captured).to_have_text(f"{a['captured_amount'] // 100}.{a['captured_amount'] % 100:02d} EUR")
        else:
            assert captured.count() == 0, f"authorization-captured present on a {a['status']} authorisation"
        incoming_open = a["status"] == "open" and a["to_handle"] == "ada"
        outgoing_open = a["status"] == "open" and a["from_handle"] == "ada"
        assert u.t(f"authorization-capture-{aid}").count() == (1 if incoming_open else 0), aid
        assert u.t(f"authorization-capture-amount-{aid}").count() == (1 if incoming_open else 0), aid
        assert u.t(f"authorization-void-{aid}").count() == (1 if outgoing_open else 0), aid
    assert {a["authorization_id"]: a["status"] for a in api}["a_out_clock"] == "expired"
    expect(u.t("authorization-capture-amount-a_in_open")).to_have_value("10.00")
    expect(u.t("authorization-capture-amount-a/odd id.3")).to_have_value("0.05")
    assert u.t("authorization-error").count() == 0
    assert u.t("empty-authorizations").count() == 0 or not u.t("empty-authorizations").is_visible()
    assert u.page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert not u.errors, u.errors
    u.shot(f"route-authorizations-{vp}")


def test_r4_r5_capture_and_void_through_the_ui(ui, vp):
    w, _ = seeded()
    u = ui(vp).login("ada").goto("/authorizations")
    # partial final capture of an incoming hold
    u.t("authorization-capture-amount-a_in_open").fill("7.50")
    u.t("authorization-capture-a_in_open").click()
    expect(u.t("authorization-item-a_in_open")).to_have_attribute("data-status", "captured")
    expect(u.t("authorization-captured-a_in_open")).to_have_text("7.50 EUR")
    expect(u.t("authorization-capture-a_in_open")).to_have_count(0)
    expect(u.t("authorization-capture-amount-a_in_open")).to_have_count(0)
    a, b = w.wallet("ada"), w.wallet("bob")
    assert a["total"] == 10750 and (b["total"], b["held"]) == (1750, 100)
    caps = u.sent_like("POST", "/capture")
    assert len(caps) == 1 and caps[0].headers.get("idempotency-key")
    body = json.loads(caps[0].post_data)
    assert body.get("amount") == 750 and body.get("final", True) is True, body
    # default amount: the pre-filled remainder
    u.t("authorization-capture-a/odd id.3").click()
    expect(u.t("authorization-item-a/odd id.3")).to_have_attribute("data-status", "captured")
    expect(u.t("authorization-captured-a/odd id.3")).to_have_text("0.05 EUR")
    assert w.wallet("cy")["total"] == 95
    # void an outgoing hold
    u.t("authorization-void-a_out_open").click()
    expect(u.t("authorization-item-a_out_open")).to_have_attribute("data-status", "voided")
    expect(u.t("authorization-void-a_out_open")).to_have_count(0)
    assert w.wallet("ada")["held"] == 0
    assert u.t("authorization-error").count() == 0
    if u.t("wallet-available").count():
        expect(u.t("wallet-available")).to_have_text("107.55 EUR")
        expect(u.t("wallet-held")).to_have_count(0)
    u.goto("/")
    expect(u.t("wallet-available")).to_have_text("107.55 EUR")
    expect(u.t("wallet-balance")).to_have_text("107.55 EUR")
    assert u.t("wallet-held").count() == 0
    expect(u.page.locator("[data-testid^='activity-item-']")).to_have_count(2)   # the two captures, as payments


def test_r4_refused_capture_and_void(ui, vp):
    w, _ = seeded()
    u = ui(vp).login("ada").goto("/authorizations")
    for bad in ("abc", "10.005", "", "10.01", "0"):
        u.t("authorization-capture-amount-a_in_open").fill(bad)
        u.t("authorization-capture-a_in_open").click()
        expect(u.t("authorization-error")).to_be_visible()
        assert u.t("authorization-error").text_content().strip() != "", bad
    sent = [json.loads(r.post_data or "{}") for r in u.sent_like("POST", "/capture")]
    assert all(type(b.get("amount", 1)) is int for b in sent), f"a malformed capture amount was sent: {sent}"
    assert w.wallet("ada")["total"] == 10000
    expect(u.t("authorization-item-a_in_open")).to_have_attribute("data-status", "open")
    # the payer voids elsewhere while the capture button is still shown
    assert ok(w.void("bob", "a_in_open"), 200)["status"] == "voided"
    u.t("authorization-capture-amount-a_in_open").fill("10.00")
    u.t("authorization-capture-a_in_open").click()
    expect(u.t("authorization-error")).to_be_visible()
    expect(u.t("authorization-item-a_in_open")).to_have_attribute("data-status", "voided")
    expect(u.t("authorization-capture-a_in_open")).to_have_count(0)
    u.shot(f"state-authorization-error-{vp}")
    # the receiver captures elsewhere while the void button is still shown
    ok(w.capture("bob", "a_out_open"), 201)
    u.t("authorization-void-a_out_open").click()
    expect(u.t("authorization-error")).to_be_visible()
    expect(u.t("authorization-item-a_out_open")).to_have_attribute("data-status", "captured")
    expect(u.t("authorization-void-a_out_open")).to_have_count(0)
    expect(u.t("authorization-captured-a_out_open")).to_have_text("20.00 EUR")


def test_r4_empty_authorizations_and_expiry_in_the_ui(ui, vp):
    w = World(fixture(ttl=6))
    u = ui(vp).login("cy").goto("/authorizations")
    expect(u.t("empty-authorizations")).to_be_visible()
    assert u.page.locator("[data-testid^='authorization-item-']").count() == 0
    u.shot(f"state-empty-authorizations-{vp}")
    a = w.new_auth("ada", "cy", 500)
    t0 = time.time()
    u.goto("/authorizations")
    expect(u.t(f"authorization-item-{a['authorization_id']}")).to_have_attribute("data-status", "open")
    expect(u.t(f"authorization-capture-{a['authorization_id']}")).to_be_visible()
    v = ui(vp).login("ada").home()
    expect(v.t("wallet-held")).to_have_text("5.00 EUR")
    time.sleep(max(0, 6.7 - (time.time() - t0)))
    # the hold has expired by the clock: either the page has caught up on its own, or the stale capture button
    # now refuses and the list catches up
    if u.t(f"authorization-capture-{a['authorization_id']}").count():
        try:
            u.t(f"authorization-capture-{a['authorization_id']}").click(timeout=1500)
            expect(u.t("authorization-error")).to_be_visible()
        except Exception:  # noqa: BLE001 - the button went away between the check and the click
            pass
    expect(u.t(f"authorization-item-{a['authorization_id']}")).to_have_attribute("data-status", "expired")
    expect(u.t(f"authorization-capture-{a['authorization_id']}")).to_have_count(0)
    v.t("wallet-refresh").click()
    expect(v.t("wallet-held")).to_have_count(0)
    expect(v.t("wallet-available")).to_have_text("100.00 EUR")
    assert w.wallet("cy")["total"] == 0


def test_r_more_than_one_page_of_authorizations(ui):
    w = World(fixture(users=[user("ada", 100000), user("bob", 0)]))
    for i in range(55):
        w.new_auth("ada", "bob", 1)
    u = ui("wide").login("bob").goto("/authorizations")
    expect(u.page.locator("[data-testid^='authorization-item-']")).to_have_count(55)
    expect(u.page.locator("[data-testid^='authorization-capture-amount-']")).to_have_count(55)
