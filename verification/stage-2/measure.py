"""Measure card widths on /requests and /authorizations (layout finding repro)."""
import sys
import checks1 as c1
from checks1 import basefx, k
from checks2 import authfx
from ui import reqfx, q, PW
from playwright.sync_api import sync_playwright
base = sys.argv[1]
S = c1.Sess(base)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for w in (375, 768, 1280, 1920):
        for path, fx, sel in (("/requests", reqfx(), '[data-testid="request-item-rq_1"]'), ("/authorizations", authfx(), '[data-testid="authorization-item-a_1"]')):
            S.reset(fx)
            pg = b.new_context(viewport={"width": w, "height": 800}).new_page()
            pg.goto(base + "/login")
            pg.locator(q("login-email")).fill("ada@example.com"); pg.locator(q("login-password")).fill(PW); pg.locator(q("login-submit")).click()
            pg.wait_for_selector(q("current-user")); pg.goto(base + path); pg.wait_for_selector(sel)
            box = pg.locator(sel).bounding_box()
            main = pg.evaluate("() => { const m = document.querySelector('.area-main').getBoundingClientRect(); const s = document.querySelector('.area-summary').getBoundingClientRect(); return {main_w: Math.round(m.width), main_x: Math.round(m.x), summary_x: Math.round(s.x), summary_y: Math.round(s.y), summary_w: Math.round(s.width), main_y: Math.round(m.y)} }")
            print(f"viewport {w} {path}: item width {round(box['width'])} px at x={round(box['x'])}; {main}")
    b.close()
