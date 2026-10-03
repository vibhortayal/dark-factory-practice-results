"""X / Y / C. Wallet, pay form, request form, activity feed, competing clients and uncertain outcomes."""
import json

import pytest
from playwright.sync_api import expect

from lib import PW, World, call, fixture, k, ok, soft, user


def post_bodies(u, path):
    return [(r.headers.get("idempotency-key"), json.loads(r.post_data or "null")) for r in u.sent("POST", path)]


# ---------------------------------------------------------------- X1 / X2 formatted amounts

@pytest.mark.parametrize("currency,minor,balance,text", [
    ("EUR", 2, 10000, "100.00 EUR"), ("EUR", 2, 5, "0.05 EUR"), ("EUR", 2, 0, "0.00 EUR"),
    ("EUR", 2, 123456789, "1234567.89 EUR"), ("EUR", 2, 2 ** 53 - 1, "90071992547409.91 EUR"),
    ("JPY", 0, 1200, "1200 JPY"), ("JPY", 0, 0, "0 JPY"), ("JPY", 0, 2 ** 53 - 1, "9007199254740991 JPY"),
    ("BHD", 3, 1234, "1.234 BHD"), ("BHD", 3, 5, "0.005 BHD"), ("BHD", 3, 2 ** 53 - 1, "9007199254740.991 BHD"),
    ("EUR", 2, 100, "1.00 EUR"), ("EUR", 2, 1000000, "10000.00 EUR"),
])
def test_x2_wallet_balance_format(ui, currency, minor, balance, text):
    World(fixture(users=[user("ada", balance), user("bob", 0)], currency=currency, minor=minor))
    u = ui("wide").login("ada").home()
    expect(u.t("wallet-balance")).to_have_text(text)
    assert u.t("wallet-balance").text_content().strip() == text
    assert u.t("wallet-balance").get_attribute("data-amount") == str(balance)
    expect(u.t("wallet-available")).to_have_text(text)
    assert u.t("wallet-available").get_attribute("data-amount") == str(balance)
    assert u.t("wallet-held").count() == 0, "wallet-held must be absent when nothing is held"


# ---------------------------------------------------------------- X3-X6 pay form

def test_x3_pay_form_elements(ui, vp):
    World()
    u = ui(vp).login("ada").home()
    for tid in ("pay-handle", "pay-amount", "pay-note", "pay-visibility", "pay-submit", "request-handle",
                "request-amount", "request-note", "request-submit", "wallet-refresh", "wallet-balance"):
        expect(u.t(tid)).to_be_visible()
    values = u.t("pay-visibility").locator("option").evaluate_all("els => els.map(e => e.value)")
    assert sorted(values) == ["private", "public"], values
    assert u.t("pay-visibility").input_value() == "public", "public is the default visibility"
    for tid in ("pay-error", "pay-uncertain", "request-error"):
        assert u.t(tid).count() == 0, f"{tid} present without an error"


@pytest.mark.parametrize("typed,minor_units", [("15.00", 1500), ("15", 1500), ("15.5", 1550), ("0.29", 29),
                                               ("1234567.89", 123456789), ("0.01", 1), ("10000000.00", 1000000000),
                                               ("0.07", 7), ("1.10", 110), ("4.35", 435), ("19.99", 1999)])
def test_x4_decimal_amounts_are_converted_exactly(ui, typed, minor_units):
    w = World(fixture(users=[user("ada", 5 * 10 ** 9), user("bob", 0)]))
    u = ui("wide").login("ada").home()
    u.fill_pay("bob", typed, "exact")
    u.t("pay-submit").click()
    expect(u.t("wallet-balance")).to_have_attribute("data-amount", str(5 * 10 ** 9 - minor_units))
    sent = post_bodies(u, "/payments")
    assert len(sent) == 1 and sent[0][1]["amount"] == minor_units and type(sent[0][1]["amount"]) is int, sent
    assert sent[0][1]["to_handle"] == "bob" and sent[0][1].get("note", "") == "exact"
    assert w.bal("bob") == minor_units
    assert u.t("pay-error").count() == 0


@pytest.mark.parametrize("typed", ["abc", "15.005", "", "1e3", "-5", "1,50", "15,00", "$15", "15 EUR", "1.2.3", "0x10",
                                   "１５", "NaN", "Infinity", "15.000", "--1", "1 000"])
def test_x4_invalid_amount_shows_error_and_sends_nothing(ui, typed):
    w = World()
    u = ui("wide").login("ada").home()
    u.fill_pay("bob", typed, "bad")
    u.t("pay-submit").click()
    expect(u.t("pay-error")).to_be_visible()
    assert u.t("pay-error").text_content().strip() != ""
    u.page.wait_for_timeout(300)
    assert u.sent("POST", "/payments") == [], f"{typed!r} was sent to the API: {post_bodies(u, '/payments')}"
    assert w.bal("ada") == 10000 and w.bal("bob") == 2500
    assert u.t("pay-uncertain").count() == 0
    # correcting the amount clears the error and pays
    u.t("pay-amount").fill("1.00")
    u.t("pay-submit").click()
    expect(u.t("wallet-balance")).to_have_text("99.00 EUR")
    expect(u.t("pay-error")).to_have_count(0)


@pytest.mark.parametrize("typed", ["15.", ".5", "+5", " 15.00 ", "0015.50"])
def test_x4_borderline_spellings_never_misconvert(ui, typed):
    """Not named by the specification: either refused with pay-error and nothing sent, or converted exactly."""
    w = World()
    u = ui("wide").login("ada").home()
    u.fill_pay("bob", typed, "edge")
    u.t("pay-submit").click()
    u.page.wait_for_timeout(700)
    sent = post_bodies(u, "/payments")
    expected = {"15.": 1500, ".5": 50, "+5": 500, " 15.00 ": 1500, "0015.50": 1550}[typed]
    if sent:
        assert sent[0][1]["amount"] == expected, sent
        soft(False, "borderline-amount-accepted", typed=typed)
    else:
        expect(u.t("pay-error")).to_be_visible()


@pytest.mark.parametrize("currency,minor,good,sent_amount,bad", [("JPY", 0, "1200", 1200, ["1.5", "1200.0", "12.00"]),
                                                                  ("BHD", 3, "1.234", 1234, ["1.2345", "0.0001"]),
                                                                  ("BHD", 3, "2.5", 2500, ["abc"])])
def test_x4_decimal_rule_follows_minor_units(ui, currency, minor, good, sent_amount, bad):
    w = World(fixture(users=[user("ada", 10 ** 7), user("bob", 0)], currency=currency, minor=minor))
    u = ui("wide").login("ada").home()
    for b in bad:
        u.fill_pay("bob", b)
        u.t("pay-submit").click()
        expect(u.t("pay-error")).to_be_visible()
        u.page.wait_for_timeout(200)
        assert u.sent("POST", "/payments") == [], f"{b!r} sent in {currency}"
    u.fill_pay("bob", good)
    u.t("pay-submit").click()
    expect(u.t("wallet-balance")).to_have_attribute("data-amount", str(10 ** 7 - sent_amount))
    assert post_bodies(u, "/payments")[0][1]["amount"] == sent_amount
    pid = w.activity("ada")[0]["payment_id"]
    unit = {0: f"{sent_amount} JPY", 3: f"{sent_amount // 1000}.{sent_amount % 1000:03d} BHD"}[minor]
    expect(u.t(f"activity-amount-{pid}")).to_have_text(unit)


def test_x5_pay_refusals(ui, vp):
    w = World()
    u = ui(vp).login("dan").home()
    expect(u.t("wallet-balance")).to_have_text("5.00 EUR")
    for handle, amount in (("ada", "5.01"), ("nobody_here", "1.00"), ("dan", "1.00"), ("ada", "0"), ("ada", "0.00"),
                           ("", "1.00"), ("ada", "10000000.01")):
        u.fill_pay(handle, amount, "refused")
        u.t("pay-submit").click()
        expect(u.t("pay-error")).to_be_visible()
        assert u.t("pay-error").text_content().strip() != "", (handle, amount)
        assert u.t("pay-uncertain").count() == 0
        expect(u.t("pay-handle")).to_have_value(handle)       # inputs are preserved after a refusal
        expect(u.t("pay-amount")).to_have_value(amount)
        expect(u.t("pay-note")).to_have_value("refused")
    assert w.bal("dan") == 500
    assert u.t("activity-list").locator("[data-testid^='activity-item-']").count() == 0
    u.fill_pay("ada", "5.00", "all of it", "private")
    u.t("pay-submit").click()
    expect(u.t("wallet-balance")).to_have_text("0.00 EUR")
    expect(u.t("pay-error")).to_have_count(0)
    pid = w.activity("dan")[0]["payment_id"]
    expect(u.t(f"activity-item-{pid}")).to_have_attribute("data-visibility", "private")


def test_x6_resubmitting_unchanged_form_pays_once(ui, vp):
    w = World()
    u = ui(vp).login("ada").home()
    u.fill_pay("bob", "15.00", "dinner", "public")
    u.t("pay-submit").click()
    expect(u.t("wallet-balance")).to_have_text("85.00 EUR")
    # the form keeps its values
    expect(u.t("pay-handle")).to_have_value("bob")
    expect(u.t("pay-amount")).to_have_value("15.00")
    expect(u.t("pay-note")).to_have_value("dinner")
    expect(u.t("pay-visibility")).to_have_value("public")
    for _ in range(3):
        u.t("pay-submit").click()
        u.page.wait_for_timeout(350)
    expect(u.t("wallet-balance")).to_have_text("85.00 EUR")
    assert u.t("pay-error").count() == 0 and u.t("pay-uncertain").count() == 0
    assert u.page.locator("[data-testid^='activity-item-']").count() == 1
    assert w.bal("ada") == 8500 and len(w.activity("ada")) == 1
    sent = post_bodies(u, "/payments")
    assert len({key for key, _ in sent}) == 1 and all(body == sent[0][1] for _, body in sent), \
        f"resubmissions must reuse key and body: {sent}"
    # changing a field makes a new payment
    u.t("pay-note").fill("dinner again")
    u.t("pay-submit").click()
    expect(u.t("wallet-balance")).to_have_text("70.00 EUR")
    u.t("pay-amount").fill("1.00")
    u.t("pay-submit").click()
    expect(u.t("wallet-balance")).to_have_text("69.00 EUR")
    u.t("pay-visibility").select_option("private")
    u.t("pay-submit").click()
    expect(u.t("wallet-balance")).to_have_text("68.00 EUR")
    u.t("pay-handle").fill("cy")
    u.t("pay-submit").click()
    expect(u.t("wallet-balance")).to_have_text("67.00 EUR")
    assert len(w.activity("ada")) == 5 and w.bal("cy") == 100
    keys = [key for key, _ in post_bodies(u, "/payments")]
    assert len(set(keys)) == 5, keys
    assert u.page.locator("[data-testid^='activity-item-']").count() == 5


def test_x6_double_click_and_rapid_clicks_pay_once(ui):
    w = World()
    u = ui("wide").login("ada").home()
    u.fill_pay("bob", "2.50", "twice?")
    u.t("pay-submit").dblclick()
    expect(u.t("wallet-balance")).to_have_text("97.50 EUR")
    u.t("pay-note").fill("burst")
    u.page.evaluate("""() => { const b = document.querySelector("[data-testid='pay-submit']");
                               for (let i = 0; i < 8; i++) b.click(); }""")
    expect(u.t("wallet-balance")).to_have_text("95.00 EUR")
    u.page.wait_for_timeout(600)
    assert w.bal("ada") == 9500 and len(w.activity("ada")) == 2
    expect(u.t("wallet-balance")).to_have_text("95.00 EUR")
    assert u.t("pay-error").count() == 0
    # the button works from the keyboard
    u.t("pay-note").fill("by keyboard")
    u.t("pay-submit").focus()
    u.page.keyboard.press("Enter")
    expect(u.t("wallet-balance")).to_have_text("92.50 EUR")


# ---------------------------------------------------------------- X7 request form

def test_x7_request_form(ui, vp):
    w = World()
    u = ui(vp).login("ada").home()
    for handle, amount in (("nobody_here", "1.00"), ("ada", "1.00"), ("bob", "abc"), ("bob", "1.005"), ("bob", "0")):
        u.t("request-handle").fill(handle)
        u.t("request-amount").fill(amount)
        u.t("request-note").fill("please")
        u.t("request-submit").click()
        expect(u.t("request-error")).to_be_visible()
        assert u.t("request-error").text_content().strip() != ""
    sent = [json.loads(r.post_data)["amount"] for r in u.sent("POST", "/requests")]
    assert all(a in (100, 0) for a in sent), f"malformed amounts must not be sent: {sent}"
    assert w.requests("ada") == []
    u.t("request-handle").fill("bob")
    u.t("request-amount").fill("12.5")
    u.t("request-note").fill("taxi 🚕")
    u.t("request-submit").click()
    expect(u.t("request-error")).to_have_count(0)
    u.page.wait_for_timeout(300)
    rq = w.requests("bob")
    assert len(rq) == 1 and (rq[0]["amount"], rq[0]["note"], rq[0]["requester_handle"]) == (1250, "taxi 🚕", "ada")
    assert w.bal("ada") == 10000
    u.t("request-submit").click()                      # unchanged form: no second request
    u.page.wait_for_timeout(400)
    assert len(w.requests("bob")) == 1
    u.goto("/requests")
    expect(u.t(f"request-item-{rq[0]['request_id']}")).to_have_attribute("data-status", "pending")
    assert u.t("outgoing-list").get_by_test_id(f"request-item-{rq[0]['request_id']}").count() == 1


# ---------------------------------------------------------------- Y activity feed

NOTES = ["coffee", "", "zażółć gęślą jaźń 😀👍🏽", "<img src=x onerror=window.__xss=1>", "<b>bold</b> & \"quoted\" 'single'",
         "</script><script>window.__xss=2</script>", "{{7*7}} ${7*7} #{7*7}", "W" * 200]


def test_y_feed_items(ui, vp):
    pays = [{"id": f"p_{i}", "from_user_id": "u_ada" if i % 2 == 0 else "u_bob",
             "to_user_id": "u_bob" if i % 2 == 0 else "u_ada", "amount": 100 + i, "note": note,
             "visibility": "private" if i % 3 == 0 else "public"} for i, note in enumerate(NOTES)]
    pays.append({"id": "p_hidden", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 7, "note": "not ada's",
                 "visibility": "private"})
    pays.append({"id": "p/odd id.1", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 8, "note": "odd id",
                 "visibility": "public"})
    w = World(fixture(payments=pays))
    u = ui(vp).login("ada").home()
    api = w.activity("ada")
    assert "p_hidden" not in [p["payment_id"] for p in api]
    expect(u.t("activity-list")).to_be_visible()
    expect(u.page.locator("[data-testid^='activity-item-']")).to_have_count(len(api))
    dom_order = u.t("activity-list").locator("[data-testid^='activity-item-']").evaluate_all(
        "els => els.map(e => e.getAttribute('data-testid'))")
    assert dom_order == [f"activity-item-{p['payment_id']}" for p in api], "feed is not newest first in the DOM"
    children = u.t("activity-list").evaluate(
        "el => Array.from(el.children).map(c => c.getAttribute('data-testid') || (c.querySelector('[data-testid^=\"activity-item-\"]') || {getAttribute(){return null}}).getAttribute('data-testid'))")
    assert [c for c in children if c] == dom_order, "the children of activity-list are not the items in order"
    assert u.t("empty-activity").count() == 0 or not u.t("empty-activity").is_visible()
    for p in api:
        pid = p["payment_id"]
        item = u.t(f"activity-item-{pid}")
        expect(item).to_have_attribute("data-visibility", p["visibility"])
        parties = u.t(f"activity-parties-{pid}").text_content()
        assert p["from_handle"] in parties and p["to_handle"] in parties, parties
        expect(u.t(f"activity-amount-{pid}")).to_have_text(f"{p['amount'] // 100}.{p['amount'] % 100:02d} EUR")
        assert u.t(f"activity-amount-{pid}").text_content().strip() == f"{p['amount'] // 100}.{p['amount'] % 100:02d} EUR"
        assert u.t(f"activity-note-{pid}").count() == 1, f"note element missing for {pid}"
        assert u.t(f"activity-note-{pid}").text_content() == p["note"], (pid, u.t(f"activity-note-{pid}").text_content())
    assert u.t("activity-item-p_hidden").count() == 0
    assert u.page.evaluate("window.__xss") is None, "a note was executed as markup"
    assert u.page.locator("[data-testid^='activity-note-'] img, [data-testid^='activity-note-'] b").count() == 0
    assert not u.errors, u.errors
    no_scroll = u.page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert no_scroll, "a 200-character note makes the page scroll sideways"


def test_y_whitespace_notes_keep_their_text(ui):
    notes = ["  two  spaces  ", "line\nbreak", "tab\there", " nbsp "]
    w = World()
    for n in notes:
        ok(w.pay("ada", "bob", 1, note=n), 201)
    u = ui("wide").login("ada").home()
    for p in w.activity("ada"):
        el = u.t(f"activity-note-{p['payment_id']}")
        expect(el).to_have_count(1)
        got = el.text_content()
        if got != p["note"]:
            soft(False, "whitespace-note-text-differs", note=p["note"], got=got)
            assert got.strip() == p["note"].strip() or " ".join(got.split()) == " ".join(p["note"].split()), (got, p["note"])


def test_y3_empty_feed_and_more_than_one_page(ui):
    w = World(fixture(users=[user("ada", 100000), user("bob", 0), user("cy", 0)]))
    u = ui("wide").login("cy").home()
    expect(u.t("empty-activity")).to_be_visible()
    assert u.page.locator("[data-testid^='activity-item-']").count() == 0
    assert u.t("activity-list").count() == 0 or u.t("activity-list").locator("[data-testid^='activity-item-']").count() == 0
    ok(w.pay("ada", "bob", 1, visibility="private"), 201)       # still nothing cy may see
    u.t("wallet-refresh").click()
    u.page.wait_for_timeout(400)
    expect(u.t("empty-activity")).to_be_visible()
    for i in range(60):
        ok(w.pay("ada", "bob", 1, note=f"n{i}"), 201)
    u.t("wallet-refresh").click()
    expect(u.page.locator("[data-testid^='activity-item-']")).to_have_count(60)
    expect(u.t("empty-activity")).to_have_count(0)
    assert u.t("activity-list").is_visible()


def test_y4_captures_and_settlements_in_the_feed(ui):
    w = World()
    a = w.new_auth("ada", "bob", 2000, note="hold note")
    st = ok(call("POST", "/settlements", w.t("op"), key=k(), body={"transfers": [
        {"from_handle": "ada", "to_handle": "cy", "amount": 300, "note": "settle"}]}), 201)
    u = ui("wide").login("ada").home()
    expect(u.t(f"activity-item-{st['payments'][0]['payment_id']}")).to_be_visible()
    expect(u.page.locator("[data-testid^='activity-item-']")).to_have_count(1)       # the open hold is not a feed item
    p = ok(w.capture("bob", a["authorization_id"], body={"amount": 1500}), 201)
    u.t("wallet-refresh").click()
    expect(u.t(f"activity-item-{p['payment_id']}")).to_be_visible()
    expect(u.t(f"activity-amount-{p['payment_id']}")).to_have_text("15.00 EUR")
    assert u.t(f"activity-note-{p['payment_id']}").text_content() == "hold note"
    expect(u.t("wallet-balance")).to_have_text("82.00 EUR")


# ---------------------------------------------------------------- C1 / C3 refresh and competing clients

def test_c1_refresh_keeps_the_form(ui, vp):
    w = World()
    u = ui(vp).login("ada").home()
    u.fill_pay("bob", "12.34", "kept note", "private")
    ok(w.pay("bob", "ada", 500, note="from elsewhere"), 201)
    w.new_auth("ada", "cy", 1000)
    u.t("wallet-refresh").click()
    expect(u.t("wallet-balance")).to_have_text("105.00 EUR")
    expect(u.t("wallet-available")).to_have_text("95.00 EUR")
    expect(u.t("wallet-held")).to_have_text("10.00 EUR")
    pid = w.activity("ada")[0]["payment_id"]
    expect(u.t(f"activity-item-{pid}")).to_be_visible()
    expect(u.t("pay-handle")).to_have_value("bob")
    expect(u.t("pay-amount")).to_have_value("12.34")
    expect(u.t("pay-note")).to_have_value("kept note")
    expect(u.t("pay-visibility")).to_have_value("private")
    assert u.sent("POST", "/payments") == []


def test_c3_balance_spent_elsewhere(ui, vp):
    w = World()
    u = ui(vp).login("ada").home()
    expect(u.t("wallet-balance")).to_have_text("100.00 EUR")
    spent = ok(w.pay("ada", "cy", 9500, note="spent by another client"), 201)
    u.fill_pay("bob", "50.00", "too late", "private")
    u.t("pay-submit").click()
    expect(u.t("pay-error")).to_be_visible()
    assert u.t("pay-uncertain").count() == 0
    expect(u.t("wallet-balance")).to_have_text("5.00 EUR")          # refreshed by the refusal itself
    expect(u.t(f"activity-item-{spent['payment_id']}")).to_be_visible()
    expect(u.t("pay-handle")).to_have_value("bob")
    expect(u.t("pay-amount")).to_have_value("50.00")
    expect(u.t("pay-note")).to_have_value("too late")
    expect(u.t("pay-visibility")).to_have_value("private")
    assert w.bal("bob") == 2500
    # the same unchanged form succeeds once money has arrived (the failed key is reusable)
    ok(w.pay("cy", "ada", 9500), 201)
    u.t("pay-submit").click()
    expect(u.t("wallet-balance")).to_have_text("50.00 EUR")
    expect(u.t("pay-error")).to_have_count(0)
    assert w.bal("bob") == 7500


# ---------------------------------------------------------------- C5 lost responses

def _lose(u, mode):
    """Route POST /payments once: 'after' forwards the request and drops the answer, 'before' drops it unsent."""
    state = {"left": 1, "seen": []}

    def handler(route):
        req = route.request
        state["seen"].append((req.headers.get("idempotency-key"), json.loads(req.post_data or "null")))
        if state["left"] > 0:
            state["left"] -= 1
            if mode == "after":
                route.fetch()
            elif mode == "garbled":
                resp = route.fetch()
                route.fulfill(status=resp.status, headers={"content-type": "application/json"}, body='{"payment_id": ')
                return
            route.abort("connectionreset" if mode != "timeout" else "timedout")
        else:
            route.continue_()

    u.page.route("**/payments", handler)
    return state


@pytest.mark.parametrize("mode", ["after", "before"])
def test_c5_lost_payment_response(ui, vp, mode):
    w = World()
    u = ui(vp).login("ada").home()
    state = _lose(u, mode)
    u.fill_pay("bob", "15.00", "uncertain", "private")
    u.t("pay-submit").click()
    expect(u.t("pay-uncertain")).to_be_visible()
    assert u.t("pay-uncertain").text_content().strip() != ""
    assert u.t("pay-error").count() == 0, "an unknown outcome was shown as a refusal"
    assert w.bal("ada") == (8500 if mode == "after" else 10000)
    expect(u.t("pay-handle")).to_have_value("bob")
    expect(u.t("pay-amount")).to_have_value("15.00")
    expect(u.t("pay-note")).to_have_value("uncertain")
    expect(u.t("pay-visibility")).to_have_value("private")
    u.shot(f"state-pay-uncertain-{vp}")
    u.t("pay-submit").click()                              # retry, unchanged
    expect(u.t("wallet-balance")).to_have_text("85.00 EUR")
    expect(u.t("pay-uncertain")).to_have_count(0)
    expect(u.t("pay-error")).to_have_count(0)
    assert len(state["seen"]) == 2
    assert state["seen"][0] == state["seen"][1], f"the retry changed key or body: {state['seen']}"
    assert state["seen"][0][0], "no Idempotency-Key on POST /payments"
    assert w.bal("ada") == 8500 and w.bal("bob") == 4000 and len(w.activity("ada")) == 1
    pid = w.activity("ada")[0]["payment_id"]
    expect(u.t(f"activity-item-{pid}")).to_be_visible()
    assert u.page.locator("[data-testid^='activity-item-']").count() == 1
    # one more unchanged submission is still the same payment
    u.t("pay-submit").click()
    u.page.wait_for_timeout(400)
    assert w.bal("ada") == 8500


def test_c5_unreadable_response_is_uncertain_not_refused(ui):
    w = World()
    u = ui("wide").login("ada").home()
    state = _lose(u, "garbled")
    u.fill_pay("bob", "3.00", "garbled")
    u.t("pay-submit").click()
    u.page.wait_for_timeout(800)
    if u.t("pay-uncertain").count() == 0:
        soft(False, "unreadable-success-body-not-uncertain", error=u.t("pay-error").count())
        assert u.t("pay-error").count() == 0, "an unreadable answer was shown as a confirmed refusal"
    u.t("pay-submit").click()
    expect(u.t("wallet-balance")).to_have_text("97.00 EUR")
    u.page.wait_for_timeout(300)
    assert w.bal("ada") == 9700 and len(w.activity("ada")) == 1
    assert u.t("pay-uncertain").count() == 0 and u.t("pay-error").count() == 0


def test_c5_changing_the_form_while_uncertain_is_a_new_payment(ui):
    w = World()
    u = ui("wide").login("ada").home()
    state = _lose(u, "before")
    u.fill_pay("bob", "4.00", "first try")
    u.t("pay-submit").click()
    expect(u.t("pay-uncertain")).to_be_visible()
    u.t("pay-amount").fill("6.00")
    u.t("pay-submit").click()
    expect(u.t("wallet-balance")).to_have_text("94.00 EUR")
    assert state["seen"][0][0] != state["seen"][1][0], "a changed form must not reuse the key"
    assert w.bal("ada") == 9400
    expect(u.t("pay-uncertain")).to_have_count(0)


def test_c5_refusal_after_uncertainty_is_shown_as_refusal(ui):
    w = World()
    u = ui("wide").login("dan").home()
    _lose(u, "before")
    u.fill_pay("ada", "5.00", "will be refused later")
    u.t("pay-submit").click()
    expect(u.t("pay-uncertain")).to_be_visible()
    ok(w.pay("dan", "cy", 500), 201)                       # another client empties the wallet
    u.t("pay-submit").click()
    expect(u.t("pay-error")).to_be_visible()
    expect(u.t("pay-uncertain")).to_have_count(0)
    expect(u.t("wallet-balance")).to_have_text("0.00 EUR")
