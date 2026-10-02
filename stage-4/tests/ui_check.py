"""Browser checks against running containers (Playwright + Chromium).

    <python with playwright> tests/ui_check.py STAGE2_URL [STAGE1_URL] [screenshot-dir]

Covers the UI rows: amount input, double submit, out-of-order refresh, competing
clients, lost responses, authorizations, upgrade from a stage-1 service, layout.
"""
import json
import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

S2 = sys.argv[1].rstrip("/")
S1 = sys.argv[2].rstrip("/") if len(sys.argv) > 2 else None
SHOTS = sys.argv[3] if len(sys.argv) > 3 else None
PASSWORD = "correct horse"


def api(base, method, path, body=None, token=None, key=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if key:
        req.add_header("Idempotency-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else None)


def user(handle, balance, name=None):
    return {"id": f"u_{handle}", "email": f"{handle}@example.com", "password": PASSWORD,
            "display_name": name or handle.title(), "handle": handle, "balance": balance}


def fixture(currency="EUR", mu=2, extra=None, **kw):
    fx = {"currency": currency, "minor_units": mu,
          "users": [user("ada", 10000), user("bob", 2500), user("cy", 500)]}
    fx.update(kw)
    return fx


def reset(fx, base=S2):
    assert api(base, "POST", "/_test/reset", fx)[0] == 204


def token(handle, base=S2):
    return api(base, "POST", "/auth/login", {"email": f"{handle}@example.com", "password": PASSWORD})[1]["token"]


def sel(name):
    return f"[data-testid='{name}']"


def log_in(page, handle="ada", base=S2):
    page.goto(base + "/login")
    page.fill(sel("login-email"), f"{handle}@example.com")
    page.fill(sel("login-password"), PASSWORD)
    page.click(sel("login-submit"))
    page.wait_for_selector(sel("current-user"))


def amount_of(page, name="wallet-balance"):
    return int(page.get_attribute(sel(name), "data-amount"))


def wait_amount(page, name, value, timeout=5000):
    page.wait_for_selector(f"{sel(name)}[data-amount='{value}']", timeout=timeout)


RESULTS = []


def scenario(fn):
    def run(browser):
        ctx = browser.new_context(base_url=S2, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        started = time.time()
        try:
            fn(page, ctx, browser)
            RESULTS.append((fn.__name__, "pass", f"{time.time() - started:.1f}s"))
        except Exception as exc:  # noqa: BLE001
            RESULTS.append((fn.__name__, "FAIL", repr(exc)[:600]))
            if SHOTS:
                try:
                    page.screenshot(path=f"{SHOTS}/FAIL-{fn.__name__}.png", full_page=True)
                except Exception:
                    pass
        finally:
            ctx.close()
    run.__name__ = fn.__name__
    SCENARIOS.append(run)
    return fn


SCENARIOS = []


@scenario
def auth_flows(page, ctx, browser):
    reset(fixture())
    page.goto("/")  # signed out: leads to /login
    page.wait_for_selector(sel("login-submit"))
    assert page.url.endswith("/login")
    assert page.query_selector(sel("auth-error")) is None
    page.fill(sel("login-email"), "ada@example.com")
    page.fill(sel("login-password"), "wrong password")
    page.click(sel("login-submit"))
    page.wait_for_selector(sel("auth-error"))
    assert page.query_selector(sel("current-user")) is None
    page.fill(sel("login-password"), PASSWORD)
    page.click(sel("login-submit"))
    page.wait_for_selector(sel("current-user"))
    assert page.url.rstrip("/") == S2.rstrip("/"), page.url
    assert page.text_content(sel("current-handle")) == "ada"
    for route in ("/", "/requests", "/split", "/authorizations", "/signup", "/login"):
        page.goto(route)
        page.wait_for_selector(sel("current-user"))
        assert page.text_content(sel("current-handle")) == "ada"
    page.goto("/signup")
    for field, value in (("email", "ada@other.io"), ("password", "longenough"), ("display-name", "Dup")):
        page.fill(sel(f"signup-{field}"), value)
    page.click(sel("signup-submit"))
    page.wait_for_selector(sel("auth-error"))  # handle_taken
    page.fill(sel("signup-email"), "ada@example.com")
    page.click(sel("signup-submit"))
    page.wait_for_selector(sel("auth-error"))  # email_taken
    page.fill(sel("signup-email"), "new.person@x.io")
    page.fill(sel("signup-password"), "short")
    page.click(sel("signup-submit"))
    page.wait_for_selector(sel("auth-error"))
    page.fill(sel("signup-password"), "longenough")
    page.click(sel("signup-submit"))
    page.wait_for_function("document.querySelector(\"[data-testid='current-handle']\")?.textContent === 'new_person'")
    page.click(sel("logout-button"))
    page.wait_for_selector(sel("current-user"), state="detached")
    page.goto("/requests")
    page.wait_for_selector(sel("login-submit"))


@scenario
def api_html_negotiation(page, ctx, browser):
    reset(fixture())
    t = token("ada")
    for path in ("/requests", "/authorizations"):
        req = urllib.request.Request(S2 + path, headers={"Accept": "text/html"})
        body = urllib.request.urlopen(req).read().decode()
        assert "<!doctype html>" in body.lower() and "/static/js/app.js" in body
        status, data = api(S2, "GET", path, token=t)
        assert status == 200 and isinstance(data, dict)
        assert api(S2, "GET", path)[0] == 401


@scenario
def formats_and_amount_input(page, ctx, browser):
    for cur, mu, want in (("JPY", 0, "10000 JPY"), ("BHD", 3, "10.000 BHD"), ("EUR", 2, "100.00 EUR")):
        reset(fixture(cur, mu, users=[user("ada", 10000), user("bob", 5)]))
        log_in(page)
        page.goto("/")
        page.wait_for_selector(sel("wallet-balance"))
        assert page.text_content(sel("wallet-balance")).strip() == want, page.text_content(sel("wallet-balance"))
        assert page.text_content(sel("wallet-available")).strip() == want
        assert page.query_selector(sel("wallet-held")) is None
    reset(fixture(users=[user("ada", 500000000), user("bob", 5)]))
    log_in(page)
    page.goto("/")
    page.wait_for_selector(sel("pay-submit"))
    sent = []
    page.on("request", lambda r: sent.append(r) if r.method == "POST" and "/payments" in r.url else None)
    page.fill(sel("pay-handle"), "bob")
    for text in ("15.005", "abc", "1,5", "15.", "-3", "1e3", ""):
        page.fill(sel("pay-amount"), text)
        page.click(sel("pay-submit"))
        page.wait_for_selector(sel("pay-error"))
    assert not sent, "no request may be sent for a bad amount"
    expected = {"15": 1500, "15.00": 1500, "15.5": 1550, "0.29": 29, "1.10": 110, "1000000.00": 100000000, ".5": 50}
    for text, minor in expected.items():
        page.fill(sel("pay-amount"), text)
        page.click(sel("pay-submit"))
        page.wait_for_function(f"document.querySelector(\"[data-testid='pay-success']\")")
        assert json.loads(sent[-1].post_data)["amount"] == minor, (text, sent[-1].post_data)
    reset(fixture("JPY", 0))
    log_in(page)
    page.goto("/")
    page.fill(sel("pay-handle"), "bob")
    page.fill(sel("pay-amount"), "10.0")
    page.click(sel("pay-submit"))
    page.wait_for_selector(sel("pay-error"))


@scenario
def pay_double_submit_and_request_forms(page, ctx, browser):
    reset(fixture())
    log_in(page)
    page.goto("/")
    page.fill(sel("pay-handle"), "bob")
    page.fill(sel("pay-amount"), "15.00")
    page.fill(sel("pay-note"), "dinner <b>&</b> \U0001F600")
    page.select_option(sel("pay-visibility"), "private")
    page.click(sel("pay-submit"))
    page.click(sel("pay-submit"))
    wait_amount(page, "wallet-balance", 8500)
    page.click(sel("pay-submit"))
    page.wait_for_timeout(500)
    assert amount_of(page) == 8500 and page.query_selector(sel("pay-error")) is None
    assert page.input_value(sel("pay-amount")) == "15.00" and page.input_value(sel("pay-handle")) == "bob"
    items = page.query_selector_all(f"{sel('activity-list')} > *")
    assert len(items) == 1
    pid = items[0].get_attribute("data-testid").replace("activity-item-", "")
    assert page.text_content(sel(f"activity-note-{pid}")) == "dinner <b>&</b> \U0001F600"
    assert page.get_attribute(sel(f"activity-item-{pid}"), "data-visibility") == "private"
    assert "ada" in page.text_content(sel(f"activity-parties-{pid}")) and "bob" in page.text_content(sel(f"activity-parties-{pid}"))
    assert page.query_selector(f"{sel('activity-note-' + pid)} b") is None
    page.fill(sel("pay-amount"), "20.00")
    page.click(sel("pay-submit"))
    wait_amount(page, "wallet-balance", 6500)
    # request form double click, authorize form double click
    page.fill(sel("request-handle"), "cy")
    page.fill(sel("request-amount"), "3.00")
    page.click(sel("request-submit"))
    page.click(sel("request-submit"))
    page.fill(sel("authorize-handle"), "bob")
    page.fill(sel("authorize-amount"), "10.00")
    page.click(sel("authorize-submit"))
    page.click(sel("authorize-submit"))
    page.wait_for_selector(sel("wallet-held"))
    assert amount_of(page, "wallet-held") == 1000 and amount_of(page, "wallet-available") == 5500
    assert amount_of(page, "wallet-balance") == 6500
    assert len(api(S2, "GET", "/requests", token=token("cy"))[1]["requests"]) == 1
    assert len(api(S2, "GET", "/authorizations", token=token("ada"))[1]["authorizations"]) == 1
    page.fill(sel("request-amount"), "99999999999")
    page.click(sel("request-submit"))
    page.wait_for_selector(sel("request-error"))
    page.fill(sel("request-handle"), "ada")
    page.fill(sel("request-amount"), "1")
    page.click(sel("request-submit"))
    page.wait_for_selector(sel("request-error"))


@scenario
def refresh_latest_wins(page, ctx, browser):
    reset(fixture())
    log_in(page)
    page.goto("/")
    wait_amount(page, "wallet-balance", 10000)
    calls = []

    def handler(route):
        calls.append(1)
        n = len(calls)
        resp = route.fetch()
        if n == 1:       # the first read is held back and arrives last, with stale data
            time.sleep(1.5)
        route.fulfill(response=resp)
    page.route("**/me", handler)
    page.click(sel("wallet-refresh"))           # slow, will return the old balance (10000)
    api(S2, "POST", "/payments", {"to_handle": "bob", "amount": 300}, token=token("ada"), key="x1")
    page.wait_for_timeout(100)
    page.click(sel("wallet-refresh"))           # fast, newer (9700)
    wait_amount(page, "wallet-balance", 9700)
    page.wait_for_timeout(2500)
    assert amount_of(page) == 9700, "an earlier, later-arriving read overwrote the newer one"
    page.unroute("**/me")


@scenario
def competing_spend_and_cancelled_request(page, ctx, browser):
    reset(fixture())
    log_in(page, "cy")
    page.goto("/")
    wait_amount(page, "wallet-balance", 500)
    page.fill(sel("pay-handle"), "bob")
    page.fill(sel("pay-amount"), "4.00")
    page.fill(sel("pay-note"), "keep me")
    api(S2, "POST", "/payments", {"to_handle": "bob", "amount": 300}, token=token("cy"), key="c1")
    page.click(sel("pay-submit"))
    page.wait_for_selector(sel("pay-error"))
    wait_amount(page, "wallet-balance", 200)
    assert page.input_value(sel("pay-amount")) == "4.00" and page.input_value(sel("pay-note")) == "keep me"
    assert page.query_selector(sel("pay-uncertain")) is None
    # request cancelled elsewhere
    rid = api(S2, "POST", "/requests", {"payer_handle": "cy", "amount": 100}, token=token("bob"), key="r1")[1]["request_id"]
    page.goto("/requests")
    page.wait_for_selector(sel(f"request-pay-{rid}"))
    api(S2, "POST", f"/requests/{rid}/cancel", token=token("bob"))
    page.click(sel(f"request-pay-{rid}"))
    page.wait_for_selector(sel("request-error"))
    page.wait_for_selector(f"{sel('request-item-' + rid)}[data-status='cancelled']")
    assert page.query_selector(sel(f"request-pay-{rid}")) is None
    # insufficient funds on pay
    big = api(S2, "POST", "/requests", {"payer_handle": "cy", "amount": 90000}, token=token("bob"), key="r2")[1]["request_id"]
    page.click(sel("request-error")) if False else None
    page.reload()
    page.click(sel(f"request-pay-{big}"))
    page.wait_for_selector(sel("request-error"))
    assert page.get_attribute(sel(f"request-item-{big}"), "data-status") == "pending"


@scenario
def lost_response_is_uncertain_and_retry_pays_once(page, ctx, browser):
    reset(fixture())
    log_in(page)
    page.goto("/")
    wait_amount(page, "wallet-balance", 10000)
    state = {"lose": True, "keys": [], "bodies": []}

    def handler(route):
        req = route.request
        if req.method == "POST":
            state["keys"].append(req.headers.get("idempotency-key"))
            state["bodies"].append(req.post_data)
            if state["lose"]:
                route.fetch()      # the server commits...
                route.abort()      # ...and the response is lost
                return
        route.continue_()
    page.route("**/payments", handler)
    page.fill(sel("pay-handle"), "bob")
    page.fill(sel("pay-amount"), "15.00")
    page.click(sel("pay-submit"))
    page.wait_for_selector(sel("pay-uncertain"))
    assert page.text_content(sel("pay-uncertain")).strip() != ""
    assert page.query_selector(sel("pay-error")) is None
    assert api(S2, "GET", "/me", token=token("ada"))[1]["balance"] == 8500
    state["lose"] = False
    page.click(sel("pay-submit"))
    wait_amount(page, "wallet-balance", 8500)
    page.wait_for_selector(sel("pay-uncertain"), state="detached")
    assert page.query_selector(sel("pay-error")) is None
    assert len(set(state["keys"])) == 1 and len(set(state["bodies"])) == 1, state
    assert len(page.query_selector_all(f"{sel('activity-list')} > *")) == 1
    assert api(S2, "GET", "/me", token=token("ada"))[1]["balance"] == 8500
    # 5xx is also unknown, not a confirmed rejection
    page.fill(sel("pay-amount"), "1.00")
    page.unroute("**/payments")
    page.route("**/payments", lambda route: route.fulfill(status=502, body="bad gateway"))
    page.click(sel("pay-submit"))
    page.wait_for_selector(sel("pay-uncertain"))


@scenario
def split_preview_and_submit(page, ctx, browser):
    reset(fixture())
    log_in(page)
    page.goto("/split")
    table = [("10.00", "ada,bob,cy", ["3.34", "3.33", "3.33"]), ("0.01", "ada,bob,cy", ["0.01", "0.00", "0.00"]),
             ("0.10", "ada, bob ,cy", ["0.04", "0.03", "0.03"]), ("9.99", "ada,bob,cy", ["3.33"] * 3),
             ("0.05", "ada,bob,cy,x1,x2", ["0.01"] * 5), ("10.00", "cy,bob,ada", ["3.34", "3.33", "3.33"])]
    for amount, handles, shares in table:
        page.fill(sel("split-amount"), amount)
        page.fill(sel("split-handles"), handles)
        names = [h.strip() for h in handles.split(",")]
        got = [page.text_content(sel(f"split-share-{n}")).strip() for n in names]
        assert got == [f"{s} EUR" for s in shares], (amount, handles, got)
    page.fill(sel("split-amount"), "10.00")
    page.fill(sel("split-handles"), "ada,bob,cy")
    page.click(sel("split-submit"))
    page.click(sel("split-submit"))
    page.wait_for_selector(sel("split-success"))
    got = api(S2, "GET", "/requests", token=token("bob"))[1]["requests"]
    assert [r["amount"] for r in got] == [333], got
    assert len(api(S2, "GET", "/requests", token=token("ada"))[1]["requests"]) == 2
    page.fill(sel("split-handles"), "ada,nobody")
    page.click(sel("split-submit"))
    page.wait_for_selector(sel("split-error"))
    page.fill(sel("split-handles"), "")
    page.click(sel("split-submit"))
    page.wait_for_selector(sel("split-error"))
    page.fill(sel("split-handles"), "bob,bob")
    page.click(sel("split-submit"))
    page.wait_for_selector(sel("split-error"))


def iso(seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + seconds))


@scenario
def authorizations_screen(page, ctx, browser):
    reset(fixture(authorizations=[
        {"id": "a_open", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit",
         "visibility": "public", "status": "open", "expires_at": iso(7200)},
        {"id": "a_old", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "status": "open", "expires_at": iso(-7200)},
        {"id": "a_cap", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 300, "status": "captured", "expires_at": iso(7200)}]))
    log_in(page)
    page.goto("/")
    page.wait_for_selector(sel("wallet-held"))
    assert amount_of(page, "wallet-balance") == 10000 and amount_of(page, "wallet-available") == 8000
    page.goto("/authorizations")
    page.wait_for_selector(sel("authorization-list"))
    ids = page.eval_on_selector_all(f"{sel('authorization-list')} > *", "els => els.map(e => e.getAttribute('data-testid'))")
    assert ids == ["authorization-item-a_cap", "authorization-item-a_old", "authorization-item-a_open"], ids
    assert page.get_attribute(sel("authorization-item-a_old"), "data-status") == "expired"
    assert page.query_selector(sel("authorization-void-a_old")) is None
    assert page.text_content(sel("authorization-captured-a_cap")).strip() == "3.00 EUR"
    assert page.query_selector(sel("authorization-captured-a_open")) is None
    assert page.text_content(sel("authorization-amount-a_open")).strip() == "20.00 EUR"
    assert page.text_content(sel("authorization-expires-a_open")).strip().endswith("+00:00")
    assert page.query_selector(sel("authorization-capture-a_open")) is None, "ada is the payer"
    page.click(sel("authorization-void-a_open"))
    page.wait_for_selector(f"{sel('authorization-item-a_open')}[data-status='voided']")
    assert amount_of(page, "wallet-available") == 10000 and page.query_selector(sel("wallet-held")) is None
    # new hold from the form on this page
    page.fill(sel("authorize-handle"), "bob")
    page.fill(sel("authorize-amount"), "25.00")
    page.click(sel("authorize-submit"))
    page.wait_for_selector(sel("wallet-held"))
    page.fill(sel("authorize-amount"), "900.00")
    page.click(sel("authorize-submit"))
    page.wait_for_selector(sel("authorize-error"))
    # bob collects
    page.context.clear_cookies()
    page.evaluate("localStorage.clear()")
    log_in(page, "bob")
    page.goto("/authorizations")
    page.wait_for_selector(sel("authorization-list"))
    new_id = [i for i in page.eval_on_selector_all(f"{sel('authorization-list')} > *", "els => els.map(e => e.getAttribute('data-testid'))")
              if "open" not in i and "_a_" not in i and i.endswith(("a_cap", "a_old")) is False and i != "authorization-item-a_open"][0].replace("authorization-item-", "")
    assert page.input_value(sel(f"authorization-capture-amount-{new_id}")) == "25.00"
    assert page.query_selector(sel(f"authorization-void-{new_id}")) is None
    page.fill(sel(f"authorization-capture-amount-{new_id}"), "26.00")
    page.click(sel(f"authorization-capture-{new_id}"))
    page.wait_for_selector(sel("authorization-error"))
    page.fill(sel(f"authorization-capture-amount-{new_id}"), "10.005")
    page.click(sel(f"authorization-capture-{new_id}"))
    page.wait_for_selector(sel("authorization-error"))
    page.fill(sel(f"authorization-capture-amount-{new_id}"), "10.00")
    page.check(f"#keep-{new_id}")
    page.click(sel(f"authorization-capture-{new_id}"))
    page.wait_for_function(f"document.querySelector(\"[data-testid='authorization-capture-amount-{new_id}']\")?.value === '15.00'")
    assert page.get_attribute(sel(f"authorization-item-{new_id}"), "data-status") == "open"
    page.fill(sel(f"authorization-capture-amount-{new_id}"), "15.00")
    page.uncheck(f"#keep-{new_id}")
    page.click(sel(f"authorization-capture-{new_id}"))
    page.wait_for_selector(f"{sel('authorization-item-' + new_id)}[data-status='captured']")
    assert page.text_content(sel(f"authorization-captured-{new_id}")).strip() == "25.00 EUR"
    assert amount_of(page, "wallet-balance") == 2500 + 2500
    page.goto("/")
    page.wait_for_selector(sel(f"activity-item-{api(S2, 'GET', '/authorizations', token=token('bob'))[1]['authorizations'][0]['payment_ids'][0]}"))


@scenario
def empty_states(page, ctx, browser):
    reset(fixture())
    log_in(page, "cy")
    for route, test_id in (("/", "empty-activity"), ("/requests", "empty-requests"), ("/authorizations", "empty-authorizations")):
        page.goto(route)
        page.wait_for_selector(sel(test_id))
    assert page.query_selector(sel("incoming-list")) is not None or True
    page.goto("/requests")
    page.wait_for_selector(sel("incoming-list"), state="attached")
    page.wait_for_selector(sel("outgoing-list"), state="attached")


@scenario
def layout_all_widths(page, ctx, browser):
    long_note = "w" * 180
    reset(fixture(users=[user("ada", 9007199254740000, "A" * 60), user("a" * 20, 5, "Averylongname Averylongname"), user("cy", 5)]))
    ta = token("ada")
    api(S2, "POST", "/payments", {"to_handle": "a" * 20, "amount": 123456789, "note": long_note}, token=ta, key="n1")
    api(S2, "POST", "/requests", {"payer_handle": "ada", "amount": 1, "note": long_note}, token=token("a" * 20), key="n2")
    api(S2, "POST", "/authorizations", {"to_handle": "a" * 20, "amount": 1000000000, "note": long_note}, token=ta, key="n3")
    log_in(page)
    for width, height in ((375, 800), (768, 900), (1280, 900), (1920, 1000)):
        page.set_viewport_size({"width": width, "height": height})
        for route, anchor in (("/", "pay-submit"), ("/requests", "incoming-list"), ("/split", "split-submit"),
                              ("/authorizations", "authorize-submit"), ("/login", "login-submit"), ("/signup", "signup-submit")):
            page.goto(route)
            page.wait_for_selector(sel(anchor))
            page.wait_for_timeout(250)
            over = page.evaluate("document.documentElement.scrollWidth - innerWidth")
            assert over <= 0, (width, route, over)
            if SHOTS:
                page.screenshot(path=f"{SHOTS}/{route.strip('/') or 'home'}-{width}.png", full_page=True)
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto("/")
    page.wait_for_selector(sel("wallet-available"))
    sizes = page.evaluate("""() => ['wallet-available','wallet-balance'].map(t =>
        parseFloat(getComputedStyle(document.querySelector(`[data-testid='${t}']`)).fontSize))""")
    assert sizes[0] > sizes[1] * 1.8, sizes


@scenario
def a11y_labels_focus_keyboard(page, ctx, browser):
    reset(fixture())
    log_in(page)
    for route in ("/", "/requests", "/split", "/authorizations", "/login", "/signup"):
        page.goto(route)
        page.wait_for_selector("form, ul, [data-testid]")
        page.wait_for_timeout(300)
        missing = page.evaluate("""() => [...document.querySelectorAll('input:not([type=hidden]), select, textarea')]
            .filter(el => !(el.labels && el.labels.length)).map(el => el.outerHTML.slice(0, 80))""")
        assert not missing, (route, missing)
    page.goto("/")
    page.wait_for_selector(sel("pay-handle"))
    page.fill(sel("pay-handle"), "bob")
    page.fill(sel("pay-amount"), "1.00")
    page.press(sel("pay-amount"), "Enter")
    wait_amount(page, "wallet-balance", 9900)
    page.focus(sel("pay-handle"))
    outline = page.evaluate("getComputedStyle(document.activeElement).outlineStyle + ' ' + getComputedStyle(document.activeElement).outlineWidth")
    assert outline.startswith("solid") and not outline.endswith(" 0px"), outline
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    focused = page.evaluate("document.activeElement.tagName")
    assert focused in ("INPUT", "SELECT", "BUTTON")


@scenario
def upgrade_from_stage1(page, ctx, browser):
    if not S1:
        raise Exception("needs a stage-1 url")
    target = {"base": S1}
    reset(fixture(), S1)
    api(S1, "POST", "/requests", {"payer_handle": "ada", "amount": 700, "note": "taxi"}, token=token("bob", S1), key="rq")
    rid = api(S1, "GET", "/requests", token=token("bob", S1))[1]["requests"][0]["request_id"]
    lose = {"on": False, "n": 0}

    def proxy(route):
        req = route.request
        if req.resource_type == "document" or "/static/" in req.url:
            route.continue_()
            return
        url = req.url.replace(S2, target["base"])
        # the page's own origin is the stage-2 image (UI); data comes from whichever service is current
        resp = route.fetch(url=url)
        if lose["on"] and req.method == "POST" and req.url.endswith("/payments"):
            lose["n"] += 1
            route.abort()
            return
        route.fulfill(response=resp)
    page.route("**/*", proxy)
    log_in(page)                                   # token issued by the stage-1 service
    page.goto("/")
    wait_amount(page, "wallet-balance", 10000)
    assert amount_of(page, "wallet-available") == 10000   # stage-1 /me has no available: falls back
    lose["on"] = True
    page.fill(sel("pay-handle"), "bob")
    page.fill(sel("pay-amount"), "15.00")
    page.click(sel("pay-submit"))
    page.wait_for_selector(sel("pay-uncertain"))
    lose["on"] = False
    assert api(S1, "GET", "/me", token=token("ada", S1))[1]["balance"] == 8500
    snapshot = api(S1, "GET", "/_test/export")[1]
    reset(fixture(), S2)  # destination has other data; import replaces it
    assert api(S2, "POST", "/_test/import", snapshot)[0] == 204
    target["base"] = S2
    page.click(sel("pay-submit"))                  # retry with the same key and body
    page.wait_for_selector(sel("pay-uncertain"), state="detached")
    wait_amount(page, "wallet-balance", 8500)
    assert page.query_selector(sel("pay-error")) is None
    assert api(S2, "GET", "/me", token=token("ada", S2))[1]["balance"] == 8500
    assert len(page.query_selector_all(f"{sel('activity-list')} > *")) == 1
    assert page.input_value(sel("pay-amount")) == "15.00"
    page.click(sel("wallet-refresh"))
    page.goto("/requests")
    page.wait_for_selector(sel(f"request-pay-{rid}"))
    page.click(sel(f"request-pay-{rid}"))
    page.wait_for_selector(f"{sel('request-item-' + rid)}[data-status='paid']")
    assert api(S2, "GET", "/me", token=token("ada", S2))[1]["balance"] == 7800
    page.goto("/authorizations")
    page.wait_for_selector(sel("empty-authorizations"))
    # the page also works when it talks to a stage-1 shaped service for authorizations
    page.unroute("**/*")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for run in SCENARIOS:
            run(browser)
        browser.close()
    width = max(len(n) for n, _, _ in RESULTS)
    for name, status, info in RESULTS:
        print(f"{status:5} {name:{width}}  {info}")
    bad = [r for r in RESULTS if r[1] != "pass"]
    print(f"{len(RESULTS) - len(bad)} passed, {len(bad)} failed")
    sys.exit(1 if bad else 0)


main()
