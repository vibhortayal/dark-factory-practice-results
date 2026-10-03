"""Z / S / C4. Requests screen and split screen in a real browser."""
import json

import pytest
from playwright.sync_api import expect

from lib import PW, World, call, fixture, k, ok, shares, soft, user


def seeded_requests():
    reqs = [
        {"id": "rq_in_pending", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
        {"id": "rq_in_paid", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 10, "note": "a", "status": "paid"},
        {"id": "rq_in_declined", "requester_id": "u_cy", "payer_id": "u_ada", "amount": 11, "note": "b", "status": "declined"},
        {"id": "rq_in_cancelled", "requester_id": "u_cy", "payer_id": "u_ada", "amount": 12, "note": "c", "status": "cancelled"},
        {"id": "rq_in_zero", "requester_id": "u_dan", "payer_id": "u_ada", "amount": 0, "note": "zero share", "status": "pending"},
        {"id": "rq_out_pending", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 1300, "note": "d", "status": "pending"},
        {"id": "rq_out_paid", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 14, "note": "e", "status": "paid"},
        {"id": "rq_out_declined", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 15, "note": "f", "status": "declined"},
        {"id": "rq_out_cancelled", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 16, "note": "g", "status": "cancelled"},
        {"id": "rq/odd id.9", "requester_id": "u_ada", "payer_id": "u_dan", "amount": 17, "note": "odd", "status": "pending"},
        {"id": "rq_not_adas", "requester_id": "u_bob", "payer_id": "u_cy", "amount": 99, "note": "x", "status": "pending"},
    ]
    return World(fixture(requests=reqs)), reqs


def money(n):
    return f"{n // 100}.{n % 100:02d} EUR"


def test_z1_z2_lists_statuses_and_buttons(ui, vp):
    w, reqs = seeded_requests()
    u = ui(vp).login("ada").goto("/requests")
    expect(u.t("incoming-list")).to_be_visible()
    expect(u.t("outgoing-list")).to_be_visible()
    mine = [r for r in reqs if "u_ada" in (r["requester_id"], r["payer_id"])]
    expect(u.page.locator("[data-testid^='request-item-']")).to_have_count(len(mine))
    for r in mine:
        rid = r["id"]
        incoming = r["payer_id"] == "u_ada"
        item = u.t(f"request-item-{rid}")
        expect(item).to_have_attribute("data-status", r["status"])
        holder = u.t("incoming-list" if incoming else "outgoing-list")
        other = u.t("outgoing-list" if incoming else "incoming-list")
        assert holder.get_by_test_id(f"request-item-{rid}").count() == 1, f"{rid} is not in the right list"
        assert other.get_by_test_id(f"request-item-{rid}").count() == 0, f"{rid} is in the wrong list"
        expect(u.t(f"request-amount-{rid}")).to_have_text(money(r["amount"]))
        pending = r["status"] == "pending"
        assert u.t(f"request-pay-{rid}").count() == (1 if incoming and pending else 0), rid
        assert u.t(f"request-decline-{rid}").count() == (1 if incoming and pending else 0), rid
        assert u.t(f"request-cancel-{rid}").count() == (1 if (not incoming) and pending else 0), rid
    assert u.t("request-item-rq_not_adas").count() == 0
    assert u.t("request-error").count() == 0
    assert u.t("empty-requests").count() == 0 or not u.t("empty-requests").is_visible()
    assert u.page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert not u.errors, u.errors


def test_z3_pay_decline_cancel_without_reload(ui, vp):
    w, reqs = seeded_requests()
    u = ui(vp).login("ada").goto("/requests")
    u.t("request-pay-rq_in_pending").click()
    expect(u.t("request-item-rq_in_pending")).to_have_attribute("data-status", "paid")
    expect(u.t("request-pay-rq_in_pending")).to_have_count(0)
    expect(u.t("request-decline-rq_in_pending")).to_have_count(0)
    assert w.bal("ada") == 8800 and w.bal("bob") == 3700
    u.t("request-pay-rq_in_zero").click()
    expect(u.t("request-item-rq_in_zero")).to_have_attribute("data-status", "paid")
    u.t("request-cancel-rq_out_pending").click()
    expect(u.t("request-item-rq_out_pending")).to_have_attribute("data-status", "cancelled")
    expect(u.t("request-cancel-rq_out_pending")).to_have_count(0)
    u.t("request-cancel-rq/odd id.9").click()
    expect(u.t("request-item-rq/odd id.9")).to_have_attribute("data-status", "cancelled")
    assert u.t("request-error").count() == 0
    by = {r["request_id"]: r["status"] for r in w.requests("ada")}
    assert (by["rq_in_pending"], by["rq_in_zero"], by["rq_out_pending"], by["rq/odd id.9"]) == ("paid", "paid", "cancelled", "cancelled")
    # the pay request carried a key, and an empty or visibility-only body
    pays = u.sent_like("POST", "/pay")
    assert pays and all(r.headers.get("idempotency-key") for r in pays)
    w2, _ = seeded_requests()
    v = ui(vp).login("ada").goto("/requests")
    v.t("request-decline-rq_in_pending").click()
    expect(v.t("request-item-rq_in_pending")).to_have_attribute("data-status", "declined")
    expect(v.t("request-pay-rq_in_pending")).to_have_count(0)
    assert w2.bal("ada") == 10000


def test_z3_double_click_pays_once(ui):
    w, _ = seeded_requests()
    u = ui("wide").login("ada").goto("/requests")
    u.t("request-pay-rq_in_pending").dblclick()
    expect(u.t("request-item-rq_in_pending")).to_have_attribute("data-status", "paid")
    u.page.wait_for_timeout(400)
    assert w.bal("ada") == 8800 and len(w.activity("ada")) == 1
    assert u.t("request-error").count() == 0


def test_z3_refused_pay_shows_request_error(ui, vp):
    reqs = [{"id": "rq_big", "requester_id": "u_bob", "payer_id": "u_dan", "amount": 501, "note": "", "status": "pending"}]
    w = World(fixture(requests=reqs))
    u = ui(vp).login("dan").goto("/requests")
    u.t("request-pay-rq_big").click()
    expect(u.t("request-error")).to_be_visible()
    assert u.t("request-error").text_content().strip() != ""
    expect(u.t("request-item-rq_big")).to_have_attribute("data-status", "pending")
    expect(u.t("request-pay-rq_big")).to_have_count(1)       # still payable later
    assert w.bal("dan") == 500
    ok(w.pay("ada", "dan", 1), 201)
    u.t("request-pay-rq_big").click()
    expect(u.t("request-item-rq_big")).to_have_attribute("data-status", "paid")
    expect(u.t("request-error")).to_have_count(0)
    assert w.bal("dan") == 0


def test_c4_request_cancelled_elsewhere(ui, vp):
    w, _ = seeded_requests()
    u = ui(vp).login("ada").goto("/requests")
    expect(u.t("request-pay-rq_in_pending")).to_be_visible()
    assert ok(call("POST", "/requests/rq_in_pending/cancel", w.t("bob")), 200)["status"] == "cancelled"
    u.t("request-pay-rq_in_pending").click()
    expect(u.t("request-error")).to_be_visible()
    expect(u.t("request-pay-rq_in_pending")).to_have_count(0)                     # the stale button is gone
    expect(u.t("request-item-rq_in_pending")).to_have_attribute("data-status", "cancelled")
    assert w.bal("ada") == 10000
    u.shot(f"state-request-error-{vp}")
    # declining something paid elsewhere, cancelling something declined elsewhere
    w2, _ = seeded_requests()
    v = ui(vp).login("ada").goto("/requests")
    expect(v.t("request-cancel-rq_out_pending")).to_be_visible()
    assert ok(call("POST", "/requests/rq_out_pending/decline", w2.t("cy")), 200)["status"] == "declined"
    v.t("request-cancel-rq_out_pending").click()
    expect(v.t("request-error")).to_be_visible()
    expect(v.t("request-item-rq_out_pending")).to_have_attribute("data-status", "declined")
    expect(v.t("request-cancel-rq_out_pending")).to_have_count(0)


def test_z4_empty_requests(ui, vp):
    w = World()
    u = ui(vp).login("ada").goto("/requests")
    expect(u.t("empty-requests")).to_be_visible()
    assert u.page.locator("[data-testid^='request-item-']").count() == 0
    u.shot(f"state-empty-requests-{vp}")
    w.new_request("bob", "ada", 500)
    u.goto("/requests")
    expect(u.page.locator("[data-testid^='request-item-']")).to_have_count(1)
    assert u.t("empty-requests").count() == 0 or not u.t("empty-requests").is_visible()
    expect(u.t("incoming-list")).to_be_visible()
    expect(u.t("outgoing-list")).to_have_count(1)


def test_z_more_than_one_page_of_requests(ui):
    w = World()
    for i in range(55):
        w.new_request("bob", "ada", 1 + i)
    u = ui("wide").login("ada").goto("/requests")
    expect(u.page.locator("[data-testid^='request-item-']")).to_have_count(55)


# ---------------------------------------------------------------- S split

SIX = ["ada", "bob", "cy", "dan", "eve", "fay"]


def split_world(currency="EUR", minor=2):
    return World(fixture(users=[user(h, 10 ** 12) for h in SIX], currency=currency, minor=minor))


def fmt(n, minor, cur):
    if minor == 0:
        return f"{n} {cur}"
    return f"{n // 10 ** minor}.{n % 10 ** minor:0{minor}d} {cur}"


@pytest.mark.parametrize("typed,minor_amount,handles", [
    ("10.00", 1000, "ada,bob,cy"), ("0.01", 1, "ada,bob,cy"), ("0.10", 10, "ada,bob,cy"), ("9.99", 999, "ada,bob,cy"),
    ("0.05", 5, "ada,bob,cy,dan,eve"), ("10", 1000, "cy,bob,ada"), ("10.00", 1000, "bob,cy,dan"), ("0.07", 7, "bob,cy,dan,eve,fay,ada"),
    ("1", 100, "ada"), ("10000000.00", 10 ** 9, "bob, cy ,dan"), ("0.02", 2, "bob,cy,dan,eve,fay"), ("12.5", 1250, "bob"),
])
def test_s2_preview_matches_the_server(ui, typed, minor_amount, handles):
    w = split_world()
    u = ui("wide").login("ada").goto("/split")
    for tid in ("split-amount", "split-handles", "split-note", "split-submit"):
        expect(u.t(tid)).to_be_visible()
    u.t("split-amount").fill(typed)
    u.t("split-handles").fill(handles)
    u.t("split-note").fill("dinner")
    hs = [h.strip() for h in handles.split(",")]
    expected = shares(minor_amount, len(hs))
    expect(u.t("split-preview")).to_be_visible()
    for h, share in zip(hs, expected):
        expect(u.t(f"split-share-{h}")).to_have_text(fmt(share, 2, "EUR"))
        assert u.t("split-preview").get_by_test_id(f"split-share-{h}").count() == 1, "the share is not inside split-preview"
    assert u.t("split-preview").locator("[data-testid^='split-share-']").count() == len(hs)
    u.page.wait_for_timeout(250)
    assert u.sent("POST", "/splits") == [], "the preview must be shown before anything is posted"
    assert all(w.requests(h) == [] for h in SIX)
    with u.page.expect_response(lambda r: r.url.endswith("/splits") and r.request.method == "POST") as info:
        u.t("split-submit").click()
    resp = info.value
    assert resp.status == 201, resp.text()
    body = resp.json()
    sent = json.loads(resp.request.post_data)
    assert sent["amount"] == minor_amount and sent["participant_handles"] == hs and sent.get("note", "") == "dinner"
    assert [(x["handle"], x["amount"]) for x in body["shares"]] == list(zip(hs, expected)), "preview and split differ"
    assert resp.request.headers.get("idempotency-key")
    assert u.t("split-error").count() == 0
    for h, share in zip(hs, expected):
        if h != "ada":
            got = [r for r in w.requests(h) if r["requester_handle"] == "ada"]
            assert len(got) == 1 and got[0]["amount"] == share
    u.t("split-submit").click()                    # unchanged form: no second split
    u.page.wait_for_timeout(400)
    assert len(w.requests("ada")) == len([h for h in hs if h != "ada"])


@pytest.mark.parametrize("currency,minor,typed,amount", [("JPY", 0, "1000", 1000), ("BHD", 3, "1.000", 1000), ("JPY", 0, "1", 1)])
def test_s2_preview_in_other_currencies(ui, currency, minor, typed, amount):
    split_world(currency, minor)
    u = ui("wide").login("ada").goto("/split")
    u.t("split-amount").fill(typed)
    u.t("split-handles").fill("ada,bob,cy")
    for h, share in zip(["ada", "bob", "cy"], shares(amount, 3)):
        expect(u.t(f"split-share-{h}")).to_have_text(fmt(share, minor, currency))


def test_s2_preview_follows_edits(ui, vp):
    split_world()
    u = ui(vp).login("ada").goto("/split")
    u.t("split-amount").fill("10.00")
    u.t("split-handles").fill("ada,bob,cy")
    expect(u.t("split-share-ada")).to_have_text("3.34 EUR")
    u.t("split-handles").fill("cy,bob,ada")
    expect(u.t("split-share-cy")).to_have_text("3.34 EUR")
    expect(u.t("split-share-ada")).to_have_text("3.33 EUR")
    u.t("split-amount").fill("0.01")
    expect(u.t("split-share-cy")).to_have_text("0.01 EUR")
    expect(u.t("split-share-bob")).to_have_text("0.00 EUR")
    u.t("split-handles").fill("cy,bob")
    expect(u.t("split-share-ada")).to_have_count(0)
    expect(u.t("split-preview").locator("[data-testid^='split-share-']")).to_have_count(2)
    assert u.sent("POST", "/splits") == []
    assert u.page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_s3_split_refusals(ui, vp):
    w = split_world()
    u = ui(vp).login("ada").goto("/split")
    cases = [("10.00", "bob,ghost_user"), ("10.00", "bob,bob"), ("10.00", ""), ("10.005", "bob,cy"), ("abc", "bob,cy"),
             ("0", "bob,cy"), ("10000000.01", "bob,cy"), ("", "bob,cy")]
    for typed, handles in cases:
        u.t("split-amount").fill(typed)
        u.t("split-handles").fill(handles)
        u.t("split-note").fill("n")
        u.t("split-submit").click()
        expect(u.t("split-error")).to_be_visible()
        assert u.t("split-error").text_content().strip() != "", (typed, handles)
    sent = [json.loads(r.post_data) for r in u.sent("POST", "/splits")]
    assert all(type(b.get("amount")) is int for b in sent), f"a malformed amount was sent: {sent}"
    assert all(w.requests(h) == [] for h in SIX), "a refused split created requests"
    u.t("split-amount").fill("10.00")
    u.t("split-handles").fill("bob,cy")
    u.t("split-submit").click()
    expect(u.t("split-error")).to_have_count(0)
    u.page.wait_for_timeout(300)
    assert len(w.requests("ada")) == 2
