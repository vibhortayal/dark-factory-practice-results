"""C2 / V / U5 / K3. Refresh ordering, layout at four widths, labels, focus, contrast, loading state, screenshots."""
import json
import re

import pytest
from playwright.sync_api import expect

from lib import PW, World, call, fixture, k, ok, seeded_auth, soft, user

ROUTES = ["/", "/requests", "/split", "/authorizations", "/signup", "/login"]
LONG = "W" * 200


def rich_world():
    """Long names, long notes, large amounts, every status: the content that stresses a layout."""
    users = [user("ada", 2 ** 53 - 10 ** 12, display_name="Adalheidis Wolfeschlegelsteinhausen-Bergerdorff"),
             user("bob_with_a_long_hand", 10 ** 11, display_name="Bob"), user("cy", 0), user("dan", 500), user("op", 0)]
    b = "u_bob_with_a_long_hand"
    pays = [{"id": f"p_{i}", "from_user_id": "u_ada" if i % 2 else b, "to_user_id": b if i % 2 else "u_ada",
             "amount": [999999999, 1, 123456, 5][i % 4], "note": [LONG, "", "coffee ☕ with a friend", "x " * 100][i % 4],
             "visibility": "private" if i % 3 == 0 else "public"} for i in range(8)]
    reqs = [{"id": f"rq_{i}", "requester_id": b if i % 2 else "u_ada", "payer_id": "u_ada" if i % 2 else b,
             "amount": [1000000000, 0, 1250, 99][i % 4], "note": [LONG, "", "taxi", "y" * 60][i % 4],
             "status": ["pending", "paid", "declined", "cancelled", "pending", "pending"][i % 6]} for i in range(8)]
    auths = [seeded_auth("a_1", "ada", "bob_with_a_long_hand", 10 ** 9, note=LONG),
             seeded_auth("a_2", "bob_with_a_long_hand", "ada", 250000, note="deposit", visibility="private"),
             seeded_auth("a_3", "ada", "cy", 700, status="captured", expires_in=-7200),
             seeded_auth("a_4", "ada", "cy", 800, status="voided"),
             seeded_auth("a_5", "ada", "cy", 900, status="open", expires_in=-3700)]
    return World(fixture(users=users, payments=pays, requests=reqs, auths=auths))


# ---------------------------------------------------------------- C2 latest refresh wins

def test_c2_latest_refresh_wins(ui, vp):
    w = World()
    u = ui(vp).login("ada").home()
    expect(u.t("wallet-balance")).to_have_text("100.00 EUR")
    held, hold = [], {"on": True}

    def handler(route):
        if hold["on"] and route.request.method == "GET":
            held.append((route, route.fetch()))          # the old state is read now and delivered later
        else:
            route.continue_()

    u.page.route(re.compile(r".*/(me|activity)(\?.*)?$"), handler)
    u.t("wallet-refresh").click()                          # refresh 1: its answers are held back
    for _ in range(30):
        if held:
            break
        u.page.wait_for_timeout(100)
    assert held, "wallet-refresh did not read /me or /activity"
    u.page.wait_for_timeout(300)
    hold["on"] = False
    p = ok(w.pay("bob", "ada", 500, note="arrived in between"), 201)
    a = w.new_auth("ada", "cy", 1000)
    u.t("wallet-refresh").click()                          # refresh 2: answered at once with the new state
    expect(u.t("wallet-balance")).to_have_text("105.00 EUR")
    expect(u.t("wallet-available")).to_have_text("95.00 EUR")
    expect(u.t(f"activity-item-{p['payment_id']}")).to_be_visible()
    for route, resp in held:                               # the delayed answers of refresh 1 arrive last
        route.fulfill(response=resp)
    u.page.wait_for_timeout(900)
    expect(u.t("wallet-balance")).to_have_text("105.00 EUR")
    expect(u.t("wallet-available")).to_have_text("95.00 EUR")
    expect(u.t("wallet-held")).to_have_text("10.00 EUR")
    expect(u.t(f"activity-item-{p['payment_id']}")).to_be_visible()
    assert u.amount("wallet-balance") == 10500


def test_c2_stale_initial_load_does_not_overwrite_a_refresh(ui):
    w = World()
    u = ui("wide").login("ada")
    held, hold = [], {"on": True}

    def handler(route):
        if hold["on"] and route.request.method == "GET":
            held.append((route, route.fetch()))
        else:
            route.continue_()

    u.page.route(re.compile(r".*/(me|activity)(\?.*)?$"), handler)
    u.page.goto("/", wait_until="domcontentloaded")
    for _ in range(40):
        if held:
            break
        u.page.wait_for_timeout(100)
    u.page.wait_for_timeout(300)
    hold["on"] = False
    ok(w.pay("ada", "bob", 2500), 201)
    if u.t("wallet-refresh").count() == 0 or not u.t("wallet-refresh").is_visible():
        for route, resp in held:
            route.fulfill(response=resp)
        soft(False, "refresh-button-not-usable-while-first-load-pending")
        return
    u.t("wallet-refresh").click()
    expect(u.t("wallet-balance")).to_have_text("75.00 EUR")
    for route, resp in held:
        route.fulfill(response=resp)
    u.page.wait_for_timeout(900)
    expect(u.t("wallet-balance")).to_have_text("75.00 EUR")


# ---------------------------------------------------------------- V5 no horizontal scrolling

@pytest.mark.parametrize("width", [375, 768, 1280, 1920])
def test_v5_no_horizontal_scroll(ui, width):
    rich_world()
    u = ui({"width": width, "height": 800}).login("ada")
    for path in ROUTES:
        u.goto(path)
        expect(u.t("current-user")).to_be_visible()
        u.page.wait_for_timeout(500)
        dims = u.page.evaluate("""() => ({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
                                         bw: document.body.scrollWidth, iw: window.innerWidth})""")
        assert dims["sw"] <= dims["cw"] + 1, f"{path} at {width}px scrolls sideways: {dims}"
        wide = u.page.evaluate("""() => Array.from(document.querySelectorAll('[data-testid]')).filter(e => {
            const r = e.getBoundingClientRect(); return r.width > 0 && (r.right > window.innerWidth + 1 || r.left < -1); })
            .map(e => e.getAttribute('data-testid')).slice(0, 8)""")
        assert not wide, f"{path} at {width}px: elements outside the viewport: {wide}"
        u.shot(f"rich-{path.strip('/') or 'home'}-{width}")
    # signed out, at this width
    v = ui({"width": width, "height": 800})
    for path in ("/login", "/signup"):
        v.goto(path)
        v.page.wait_for_timeout(300)
        d = v.page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
        assert d[0] <= d[1] + 1, f"{path} signed out at {width}px scrolls sideways"


# ---------------------------------------------------------------- V6 labels, focus, contrast

INPUTS = {
    "/login": ["login-email", "login-password"],
    "/signup": ["signup-email", "signup-password", "signup-display-name"],
    "/": ["pay-handle", "pay-amount", "pay-note", "pay-visibility", "request-handle", "request-amount", "request-note"],
    "/split": ["split-amount", "split-handles", "split-note"],
}

LABEL_JS = """(el) => {
  const vis = n => { if (!n) return false; const s = getComputedStyle(n), r = n.getBoundingClientRect();
                     return s.display !== 'none' && s.visibility !== 'hidden' && parseFloat(s.opacity) > 0.1 && r.width > 1 && r.height > 1; };
  const texts = [];
  for (const l of (el.labels || [])) if (vis(l) && l.textContent.trim()) texts.push(l.textContent.trim());
  const by = el.getAttribute('aria-labelledby');
  if (by) for (const id of by.split(/\\s+/)) { const n = document.getElementById(id); if (vis(n) && n.textContent.trim()) texts.push(n.textContent.trim()); }
  return texts;
}"""


@pytest.mark.parametrize("vpname", ["narrow", "wide"])
def test_v6_inputs_have_visible_labels(ui, vpname):
    w = World(fixture(auths=[seeded_auth("a_in", "bob", "ada", 1000)]))
    u = ui(vpname)
    missing = []
    for path in ("/login", "/signup"):
        u.goto(path)
        for tid in INPUTS[path]:
            expect(u.t(tid)).to_be_visible()
            if not u.t(tid).evaluate(LABEL_JS):
                missing.append(f"{path} {tid}")
    u.login("ada")
    for path in ("/", "/split"):
        u.goto(path)
        expect(u.t("current-user")).to_be_visible()
        for tid in INPUTS[path]:
            expect(u.t(tid)).to_be_visible()
            if not u.t(tid).evaluate(LABEL_JS):
                missing.append(f"{path} {tid}")
    for path in ("/authorizations", "/"):
        u.goto(path)
        u.page.wait_for_timeout(300)
        if u.t("authorize-submit").count():
            for tid in ("authorize-handle", "authorize-amount", "authorize-note", "authorize-visibility"):
                if not u.t(tid).evaluate(LABEL_JS):
                    missing.append(f"{path} {tid}")
            break
    u.goto("/authorizations")
    expect(u.t("authorization-capture-amount-a_in")).to_be_visible()
    if not u.t("authorization-capture-amount-a_in").evaluate(LABEL_JS):
        missing.append("/authorizations authorization-capture-amount-a_in")
    assert not missing, f"inputs without a visible label: {missing}"


FOCUS_JS = """() => {
  const e = document.activeElement; if (!e || e === document.body) return null;
  const s = getComputedStyle(e);
  const outline = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0;
  const shadow = s.boxShadow && s.boxShadow !== 'none';
  return {id: e.getAttribute('data-testid') || e.tagName + ':' + (e.textContent || '').trim().slice(0, 20),
          outline, shadow, border: s.borderColor, bg: s.backgroundColor};
}"""


def test_v6_keyboard_focus_is_apparent(ui):
    World()
    u = ui("wide").login("ada")
    problems, reached = [], set()
    for path in ("/", "/requests", "/split", "/authorizations"):
        u.goto(path)
        expect(u.t("current-user")).to_be_visible()
        u.page.evaluate("document.activeElement && document.activeElement.blur()")
        for _ in range(45):
            u.page.keyboard.press("Tab")
            info = u.page.evaluate(FOCUS_JS)
            if not info:
                continue
            reached.add(info["id"])
            if not (info["outline"] or info["shadow"]):
                # compare with the unfocused look: a changed border or background also counts
                problems.append((path, info["id"]))
    weak = sorted(set(problems))
    assert {"pay-handle", "pay-amount", "pay-submit", "request-submit", "wallet-refresh", "logout-button",
            "split-amount", "split-handles", "split-submit"} <= reached, f"not reachable with Tab: {sorted(reached)}"
    assert not weak, f"focused elements without an outline or focus ring: {weak[:12]}"


CONTRAST_JS = """() => {
  const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
                       const p = m[1].split(',').map(x => parseFloat(x)); return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
                     return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const over = (top, under) => ({r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a),
                                 b: top.b * top.a + under.b * (1 - top.a), a: 1});
  const bgOf = el => { let layers = []; let n = el; let image = false;
    while (n && n.nodeType === 1) { const s = getComputedStyle(n); const c = parse(s.backgroundColor);
      if (s.backgroundImage && s.backgroundImage !== 'none') image = true;
      if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; } n = n.parentElement; }
    let base = {r: 255, g: 255, b: 255, a: 1};
    for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base);
    return {bg: base, image}; };
  const out = [];
  const seen = new Set();
  const els = Array.from(document.querySelectorAll('body *')).filter(e => {
    if (e.closest('svg')) return false;
    const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    if (r.width < 2 || r.height < 2 || s.visibility === 'hidden' || s.display === 'none' || parseFloat(s.opacity) < 0.05) return false;
    return Array.from(e.childNodes).some(n => n.nodeType === 3 && n.textContent.trim().length > 0)
           || ((e.tagName === 'INPUT' || e.tagName === 'SELECT' || e.tagName === 'TEXTAREA') && e.type !== 'hidden'); });
  for (const e of els) {
    const s = getComputedStyle(e); const fg0 = parse(s.color); if (!fg0) continue;
    const {bg, image} = bgOf(e); if (image) continue;
    const fg = over(fg0, bg);
    const l1 = lum(fg), l2 = lum(bg); const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const size = parseFloat(s.fontSize); const bold = parseInt(s.fontWeight) >= 700;
    const large = size >= 24 || (bold && size >= 18.66);
    const need = large ? 3 : 4.5;
    if (ratio < need) { const key = (e.getAttribute('data-testid') || e.tagName) + '|' + s.color + '|' + ratio.toFixed(2);
      if (!seen.has(key)) { seen.add(key); out.push({el: e.getAttribute('data-testid') || e.tagName.toLowerCase(),
        text: (e.textContent || e.value || '').trim().slice(0, 30), ratio: +ratio.toFixed(2), need, color: s.color,
        disabled: !!e.disabled}); } }
  }
  return out;
}"""


@pytest.mark.parametrize("vpname", ["narrow", "wide"])
def test_v6_text_contrast(ui, vpname):
    rich_world()
    u = ui(vpname)
    low = {}
    for path in ("/login", "/signup"):
        u.goto(path)
        u.page.wait_for_timeout(300)
        low[path + " (signed out)"] = u.page.evaluate(CONTRAST_JS)
    u.login("ada")
    for path in ROUTES:
        u.goto(path)
        expect(u.t("current-user")).to_be_visible()
        u.page.wait_for_timeout(400)
        low[path] = u.page.evaluate(CONTRAST_JS)
    bad = {p: [x for x in v if not x["disabled"]] for p, v in low.items()}
    bad = {p: v for p, v in bad.items() if v}
    assert not bad, "text below WCAG AA contrast: " + json.dumps(bad, ensure_ascii=False)[:1800]


# ---------------------------------------------------------------- V7 / V4 loading and state screenshots

def test_v7_loading_state_is_not_a_wrong_number(ui, vp):
    w = World()
    u = ui(vp).login("ada")
    held = []
    pat = re.compile(r".*/(me|activity|requests|authorizations)(\?.*)?$")

    def handler(route):
        req = route.request
        if req.method == "GET" and "text/html" not in (req.headers.get("accept") or ""):
            held.append((route, route.fetch()))
        else:
            route.continue_()

    u.page.route(pat, handler)
    u.page.goto("/", wait_until="domcontentloaded")
    u.page.wait_for_timeout(900)
    assert held, "the home screen read nothing from the API"
    # while nothing has been read, the page should not present a made-up balance or an empty feed
    shown = u.t("wallet-balance").text_content().strip() if u.t("wallet-balance").count() else ""
    soft(shown in ("", "100.00 EUR") or not re.fullmatch(r"\d+(\.\d+)? EUR", shown), "loading-shows-a-wrong-balance",
         shown=shown, viewport=vp)
    soft(u.t("empty-activity").count() == 0 or not u.t("empty-activity").is_visible(), "loading-claims-empty-feed",
         viewport=vp)
    u.shot(f"state-loading-home-{vp}")
    for route, resp in held:
        route.fulfill(response=resp)
    held.clear()
    u.page.unroute(pat)
    expect(u.t("wallet-balance")).to_have_text("100.00 EUR")
    assert not u.errors, u.errors


def test_v_screenshots_for_review(ui, vp):
    """Writes the screenshots the visual rows (V1-V4, V7) are judged from. Always reaches the end."""
    rich_world()
    u = ui(vp)
    for path in ("/login", "/signup"):
        u.goto(path)
        u.page.wait_for_timeout(300)
        u.shot(f"route-{path.strip('/')}-signed-out-{vp}")
    u.goto("/login")
    u.t("login-email").fill("ada@example.com")
    u.t("login-password").fill("wrong horse")
    u.t("login-submit").click()
    expect(u.t("auth-error")).to_be_visible()
    u.shot(f"state-auth-error-{vp}")
    u.login("ada")
    for path in ROUTES:
        u.goto(path)
        expect(u.t("current-user")).to_be_visible()
        u.page.wait_for_timeout(500)
        u.shot(f"route-{path.strip('/') or 'home'}-{vp}")
        u.page.screenshot(path=u.shot(f"fold-{path.strip('/') or 'home'}-{vp}"), full_page=False)
    u.goto("/")
    u.fill_pay("cy", "999999999999.00", "refused")
    u.t("pay-submit").click()
    expect(u.t("pay-error")).to_be_visible()
    u.shot(f"state-pay-error-{vp}")
    u.fill_pay("cy", "1.00", "success", "private")
    u.t("pay-submit").click()
    u.page.wait_for_timeout(700)
    u.shot(f"state-pay-success-{vp}")
    u.t("pay-submit").focus()
    u.page.keyboard.press("Shift+Tab")
    u.page.keyboard.press("Tab")
    u.page.screenshot(path=u.shot(f"state-focus-{vp}"), full_page=False)
    u.goto("/split")
    u.t("split-amount").fill("10.00")
    u.t("split-handles").fill("ada, bob_with_a_long_hand, cy")
    u.page.wait_for_timeout(300)
    u.shot(f"state-split-preview-{vp}")
    u.t("split-handles").fill("ada, nobody_here")
    u.t("split-submit").click()
    u.page.wait_for_timeout(500)
    u.shot(f"state-split-error-{vp}")
    v = ui(vp).login("cy")
    for path in ("/", "/requests", "/authorizations"):
        v.goto(path)
        v.page.wait_for_timeout(500)
        v.shot(f"state-empty-{path.strip('/') or 'home'}-{vp}")


# ---------------------------------------------------------------- U5 markup safety beyond notes

def test_u5_user_text_is_never_markup(ui):
    evil = "<img src=x onerror=window.__xss=1><script>window.__xss=2</script>"
    users = [user("ada", 10000, display_name=evil), user("bob", 100, display_name="Bob <b>bold</b>")]
    reqs = [{"id": "rq_x", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 5, "note": evil, "status": "pending"}]
    auths = [seeded_auth("a_x", "bob", "ada", 5, note=evil)]
    pays = [{"id": "p_x", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 5, "note": evil, "visibility": "public"}]
    World(fixture(users=users, requests=reqs, auths=auths, payments=pays))
    u = ui("wide").login("ada")
    for path in ROUTES:
        u.goto(path)
        expect(u.t("current-user")).to_be_visible()
        u.page.wait_for_timeout(400)
        assert u.page.evaluate("window.__xss") is None, f"user text was executed on {path}"
        assert u.page.locator("img[src='x']").count() == 0, f"user text became markup on {path}"
    u.goto("/")
    assert evil in u.t("current-user").text_content()
    assert u.t("activity-note-p_x").text_content() == evil
    assert not u.errors, u.errors
