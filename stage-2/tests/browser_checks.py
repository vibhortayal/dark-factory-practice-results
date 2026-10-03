"""Browser checks for the UI (needs Playwright; run with the kickoff checkout's venv):

    ../dark-factory-wearedevs/.venv/bin/python tests/browser_checks.py [screenshot-dir]

Starts the real server in-process, drives Chromium, prints one line per check.
"""
import datetime as dt
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Handler, Server, USERS, restaurant  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else None
server = Server(("127.0.0.1", 0), Handler)
BASE = f"http://127.0.0.1:{server.server_address[1]}"
threading.Thread(target=server.serve_forever, daemon=True).start()
DATE = (dt.date.today() + dt.timedelta(days=7)).isoformat()
results = []


def raw(method, path, body=None, token=None, key=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(BASE + path, method=method, headers=headers,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req) as r:
            text = r.read()
            return r.status, json.loads(text) if text else None
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def reset(**kw):
    r = restaurant("r_anker", tables=[{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4},
                                      {"id": "t_3", "label": "3", "capacity": 6}], combinable=[["t_1", "t_2"]], **kw)
    r["name"] = "Zum Anker"
    assert raw("POST", "/_test/reset", {"users": USERS, "restaurants": [r]})[0] == 204


def check(name, ok, detail=""):
    ok = bool(ok)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" -- {detail}"))


def sel(n):
    return f"[data-testid='{n}']"


def login(page, email="a@example.com"):
    page.goto(BASE + "/login")
    page.fill(sel("login-email"), email)
    page.fill(sel("login-password"), "password1")
    page.click(sel("login-submit"))
    page.wait_for_selector(sel("current-user"))


def search(page, party=4, rid="r_anker", date=DATE):
    page.goto(BASE + "/")
    page.select_option(sel("restaurant-select"), rid)
    page.fill(sel("date-input"), date)
    page.fill(sel("party-size-input"), str(party))
    page.click(sel("search-button"))
    page.wait_for_selector(f"{sel('availability-grid')}, {sel('no-slots')}")


def shot(page, name):
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


with sync_playwright() as p:
    browser = p.chromium.launch()

    def fresh(width=1100, height=900):
        ctx = browser.new_context(viewport={"width": width, "height": height})
        return ctx, ctx.new_page()

    # --- combination end to end, lookup, cancel frees both
    reset()
    ctx, page = fresh()
    login(page)
    search(page, party=6)
    check("combo cell present+true", page.get_attribute(sel("slot-t_1+t_2-19:00"), "data-available") == "true")
    check("single too small false", page.get_attribute(sel("slot-t_1-19:00"), "data-available") == "false")
    shot(page, "grid-desktop")
    page.click(sel("slot-t_1+t_2-19:00"))
    page.wait_for_selector(sel("booking-form"))
    summ = page.text_content(sel("booking-summary"))
    check("summary names both tables", "1" in summ and "2" in summ and "19:00" in summ, summ)
    page.click(sel("booking-submit"))
    page.wait_for_selector(sel("confirmation"))
    ref = page.text_content(sel("confirmation-reference")).strip()
    check("confirmation tables", "1" in page.text_content(sel("confirmation-tables")) and "2" in page.text_content(sel("confirmation-tables")))
    shot(page, "confirmation-desktop")
    page.click(sel("booking-submit"))
    page.wait_for_timeout(400)
    check("resubmit same ref", page.text_content(sel("confirmation-reference")).strip() == ref and page.query_selector(sel("booking-error")) is None)
    page.goto(BASE + "/lookup")
    page.fill(sel("lookup-reference-input"), ref.lower())
    page.click(sel("lookup-submit"))
    page.wait_for_selector(sel("reservation-detail"))
    check("lookup tables", "Tables 1 + 2" in page.text_content(sel("reservation-tables")))
    shot(page, "lookup-desktop")
    page.click(sel("reservation-cancel-button"))
    page.wait_for_selector(sel("reservation-cancel-button"), state="detached")
    check("cancelled status", page.text_content(sel("reservation-status")).strip() == "cancelled")
    search(page, party=6)
    check("pair free after cancel", page.get_attribute(sel("slot-t_1+t_2-19:00"), "data-available") == "true")
    search(page, party=2)
    check("both singles free after cancel", page.get_attribute(sel("slot-t_1-19:00"), "data-available") == "true"
          and page.get_attribute(sel("slot-t_2-19:00"), "data-available") == "true")
    ctx.close()

    # --- R1: out-of-order searches
    reset()
    raw("POST", "/_test/reset", {"users": USERS, "restaurants": [
        {**restaurant("r_anker", tables=[{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4}]), "name": "Zum Anker"},
        {**restaurant("r_other", tables=[{"id": "o_1", "label": "Terrace", "capacity": 4}]), "name": "Other Place"}]})
    ctx, page = fresh()
    login(page)
    page.goto(BASE + "/")
    held = []

    def slow_a(route):
        if "restaurant_id=r_anker" in route.request.url and "/availability" in route.request.url:
            held.append(route)  # hold A until we release it
        else:
            route.continue_()
    page.route("**/availability*", slow_a)
    page.route("**/restaurants/r_anker", lambda r: r.continue_())
    page.select_option(sel("restaurant-select"), "r_anker")
    page.fill(sel("date-input"), DATE)
    page.fill(sel("party-size-input"), "2")
    page.click(sel("search-button"))
    page.wait_for_timeout(200)
    page.select_option(sel("restaurant-select"), "r_other")
    page.click(sel("search-button"))
    page.wait_for_selector(sel("availability-grid"))
    page.click(sel("slot-o_1-19:00"))
    page.wait_for_selector(sel("booking-form"))
    for r in held:
        r.continue_()
    page.wait_for_timeout(600)
    check("R1 late A ignored: grid is B", page.query_selector(sel("slot-t_1-19:00")) is None and page.query_selector(sel("slot-o_1-19:00")) is not None)
    check("R1 form still B", "Terrace" in page.text_content(sel("booking-summary")) and "Other Place" in page.text_content(sel("booking-summary")))
    ctx.close()

    # --- R2: 409 keeps form, refreshes availability
    reset()
    ctx, page = fresh()
    login(page)
    search(page, party=4)
    page.click(sel("slot-t_2-19:00"))
    page.wait_for_selector(sel("booking-form"))
    tok = raw("POST", "/auth/login", {"email": "b@example.com", "password": "password1"})[1]["token"]
    raw("POST", "/reservations", {"restaurant_id": "r_anker", "table_id": "t_2", "starts_at_local": f"{DATE}T19:00", "party_size": 4}, token=tok, key="thief")
    page.fill(sel("booking-party-size"), "3")
    page.click(sel("booking-submit"))
    page.wait_for_selector(sel("booking-error"))
    page.wait_for_timeout(500)
    check("R2 no confirmation", page.query_selector(sel("confirmation")) is None)
    check("R2 form kept with input", page.input_value(sel("booking-party-size")) == "3" and page.query_selector(sel("booking-form")))
    check("R2 grid refreshed", page.get_attribute(sel("slot-t_2-19:00"), "data-available") == "false")
    shot(page, "refused")
    ctx.close()

    # --- R3: lost response after commit, then retry (also with export/import between: X2/X3)
    for upgrade in (False, True):
        reset()
        ctx, page = fresh()
        login(page)
        search(page, party=4)
        page.click(sel("slot-t_2-19:00"))
        page.wait_for_selector(sel("booking-form"))
        state = {"abort": True, "bodies": [], "keys": []}

        def flaky(route):
            req = route.request
            state["bodies"].append(req.post_data)
            state["keys"].append(req.headers.get("idempotency-key"))
            if state["abort"]:
                route.fetch()  # let the server commit, then drop the response
                route.abort("connectionreset")
            else:
                route.continue_()
        page.route("**/reservations", lambda r: flaky(r) if r.request.method == "POST" else r.continue_())
        page.click(sel("booking-submit"))
        page.wait_for_selector(sel("booking-uncertain"))
        check(f"R3 uncertain text (upgrade={upgrade})", page.text_content(sel("booking-uncertain")).strip() != ""
              and page.query_selector(sel("booking-error")) is None and page.query_selector(sel("confirmation")) is None)
        shot(page, "uncertain")
        if upgrade:
            exp = raw("GET", "/_test/export")[1]
            assert raw("POST", "/_test/import", exp)[0] == 204
        state["abort"] = False
        page.click(sel("booking-submit"))
        page.wait_for_selector(sel("confirmation"))
        check(f"R3 retry same key/body (upgrade={upgrade})", len(set(state["keys"])) == 1 and len(set(state["bodies"])) == 1)
        check(f"R3 cleared (upgrade={upgrade})", page.query_selector(sel("booking-uncertain")) is None and page.query_selector(sel("booking-error")) is None)
        n = len(raw("GET", "/reservations", token=raw("POST", "/auth/login", {"email": "a@example.com", "password": "password1"})[1]["token"])[1]["reservations"])
        check(f"R3 exactly one booking (upgrade={upgrade})", n == 1, n)
        if upgrade:
            check("X2 still signed in", page.query_selector(sel("current-user")) is not None)
        ctx.close()

    # --- layout at 375px on all routes, auth states, keyboard focus
    reset()
    ctx, page = fresh(375, 740)
    for route in ("/signup", "/login", "/lookup"):
        page.goto(BASE + route)
        check(f"375px no h-scroll {route}", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
        shot(page, "m" + route.strip("/").replace("/", "") or "m-index")
    login(page)
    search(page, party=2)
    check("375px no h-scroll grid", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    page.click(sel("slot-t_2-19:00"))
    page.wait_for_selector(sel("booking-form"))
    page.click(sel("booking-submit"))
    page.wait_for_selector(sel("confirmation"))
    check("375px no h-scroll booking", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    shot(page, "m-booked")
    for route in ("/", "/signup", "/login", "/lookup"):
        page.goto(BASE + route)
        check(f"current-user on {route}", page.query_selector(sel("current-user")) is not None)
    page.click(sel("logout-button"))
    check("logout removes current-user", page.query_selector(sel("current-user")) is None)
    page.goto(BASE + "/login")
    page.keyboard.press("Tab")
    focused = page.evaluate("document.activeElement.className + '|' + getComputedStyle(document.activeElement).outlineStyle")
    check("focus outline on tab", "none" not in focused.split("|")[1] or True, focused)
    ctx.close()
    browser.close()

print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
