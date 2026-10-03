import sys
sys.path.insert(0, "/home/ubuntu/nightshift-claude-run-5/band-work/verifier/s4")
from playwright.sync_api import sync_playwright, expect
from lib import *
from conftest import UI
F = []
def chk(cond, name, **kw):
    if not cond: F.append((name, kw)); print("FINDING", name, kw)
with sync_playwright() as pw:
    br = pw.chromium.launch()
    for vp in ("narrow", "wide"):
        w = World().login_all()
        p = ok(w.pay("ada", "bob", 1000, note="dinner <b>x</b>", visibility="private"), 201)
        rf = ok(refund(w, "bob", p["payment_id"], 250), 201)
        ok(correct(w, "ada", p["payment_id"], 1, 800, p["created_at"], "less"), 201)
        ok(batch(w, [item(p, 700, expected=2)]), 201)
        u = UI(br, vp); u.login("ada"); u.goto("/")
        expect(u.t("wallet-balance")).to_have_text("95.50 EUR")
        expect(u.t(f"activity-item-{rf['payment_id']}")).to_be_visible()
        chk(u.t(f"activity-amount-{rf['payment_id']}").text_content().strip() == "2.50 EUR", "refund-amount")
        chk(u.t(f"activity-amount-{p['payment_id']}").text_content().strip() == "10.00 EUR", "original-amount-in-feed", got=u.t(f"activity-amount-{p['payment_id']}").text_content())
        chk(u.t(f"activity-note-{rf['payment_id']}").text_content() == "dinner <b>x</b>", "refund-note")
        chk(u.t(f"activity-item-{rf['payment_id']}").get_attribute("data-visibility") == "private", "refund-visibility")
        txt = u.t(f"activity-parties-{rf['payment_id']}").text_content()
        chk("ada" in txt and "bob" in txt, "refund-parties", txt=txt)
        ids = u.page.locator("[data-testid^='activity-item-']").evaluate_all("els => els.map(e => e.getAttribute('data-testid'))")
        chk(ids == [f"activity-item-{rf['payment_id']}", f"activity-item-{p['payment_id']}"], "feed-order", ids=ids)
        chk(u.page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), "sideways", vp=vp)
        u.shot(f"refund-feed-{vp}")
        chk(not u.errors, "script-error", e=u.errors)
        u.close()
    br.close()
print("VIOLATIONS", VIOLATIONS[:5]); print("FINDINGS", len(F), F)
