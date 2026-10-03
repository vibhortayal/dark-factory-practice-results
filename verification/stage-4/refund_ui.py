"""Manual check: the wallet feed renders with a refund payment in it (375 and 1280 px)."""
import sys
import checks1 as c1
from checks1 import basefx, k, PW
from ui import q
from playwright.sync_api import sync_playwright
base, out = sys.argv[1], sys.argv[2]
S = c1.Sess(base)
S.reset(basefx(payments=[], requests=[]))
p = S.call("POST", "/payments", {"to_handle": "bob", "amount": 1000, "note": "gift"}, as_="ada", key=k()).j
r = S.call("POST", f"/payments/{p['payment_id']}/refunds", {"amount": 250}, as_="bob", key=k()).j
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for w in (375, 1280):
        pg = b.new_context(viewport={"width": w, "height": 800}).new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/login")
        pg.locator(q("login-email")).fill("ada@example.com"); pg.locator(q("login-password")).fill(PW); pg.locator(q("login-submit")).click()
        pg.wait_for_selector(q(f"activity-item-{r['payment_id']}"))
        amt = pg.locator(q(f"activity-amount-{r['payment_id']}")).inner_text().strip()
        parties = pg.locator(q(f"activity-parties-{r['payment_id']}")).inner_text().strip()
        order = pg.eval_on_selector_all('[data-testid^="activity-item-"]', "els => els.map(e => e.getAttribute('data-testid'))")
        bal = pg.locator(q("wallet-balance")).inner_text().strip()
        noscroll = pg.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
        print(f"viewport {w}: refund item amount {amt!r}, parties {parties!r}, newest first {order[0].endswith(r['payment_id'])}, balance {bal!r}, no h-scroll {noscroll}, page errors {errs}")
        pg.screenshot(path=f"{out}/refund-feed-{w}.png", full_page=True)
    b.close()
