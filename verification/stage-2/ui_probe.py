#!/usr/bin/env python3
"""Stage-2 Tablekeeper browser probes (Playwright, Chromium). Check ids: CHECKS.md UI.*.

Usage: BASE=<stage-2 url> S1BASE=<stage-1 url> SHOTS=<dir> [OUT=..] python ui_probe.py [section ...]
"""
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from playwright.sync_api import sync_playwright

BASE = os.environ["BASE"].rstrip("/")
S1BASE = os.environ.get("S1BASE", "").rstrip("/")
SHOTS = os.environ.get("SHOTS", "/tmp/tk-shots")
OUT = os.environ.get("OUT")
os.makedirs(SHOTS, exist_ok=True)

api = httpx.Client(timeout=15)
RESULTS, NOTES, EXTERNAL, CONSOLE = [], [], [], []
REF_RE = re.compile(r"^[A-Z0-9]{6,12}$")
TODAY = datetime.now(ZoneInfo("Europe/Berlin")).date()
D = (TODAY + timedelta(days=7)).isoformat()
PAST = (TODAY - timedelta(days=8)).isoformat()
ADA = ("ada@example.com", "correct horse", "Ada Lovelace")
BOB = ("bob@example.com", "battery staple", "Bob")
WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def hours(o, c):
    return [{"weekday": d, "opens": o, "closes": c} for d in WEEK]


def fixture():
    return {
        "users": [{"id": "u_ada", "email": ADA[0], "password": ADA[1], "display_name": ADA[2]},
                  {"id": "u_bob", "email": BOB[0], "password": BOB[1], "display_name": BOB[2]}],
        "restaurants": [
            {"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin", "slot_minutes": 30, "reservation_duration_minutes": 90,
             "cancellation_cutoff_minutes": 120, "opening_hours": hours("18:00", "23:00"),
             "tables": [{"id": "t_1", "label": "1", "capacity": 2}, {"id": "t_2", "label": "2", "capacity": 4}, {"id": "t_3", "label": "3", "capacity": 4}],
             "combinable": [["t_1", "t_2"], ["t_3", "t_2"]]},
            {"id": "r_hafen", "name": "Hafenblick", "timezone": "Europe/Berlin", "slot_minutes": 60, "reservation_duration_minutes": 60,
             "cancellation_cutoff_minutes": 0, "opening_hours": hours("12:00", "15:00"),
             "tables": [{"id": "h_a", "label": "Fenster", "capacity": 2}, {"id": "h_b", "label": "Garten", "capacity": 6}],
             "combinable": [["h_b", "h_a"]]},
            {"id": "r_closed", "name": "Ruhetag", "timezone": "Europe/Berlin", "slot_minutes": 30, "reservation_duration_minutes": 90,
             "cancellation_cutoff_minutes": 0, "opening_hours": [], "tables": [{"id": "c_1", "label": "Stube", "capacity": 4}]},
        ],
        "reservations": [{"id": "res_past", "reference": "PASTREF1", "user_id": "u_ada", "restaurant_id": "r_anker", "table_id": "t_3",
                          "starts_at_local": f"{PAST}T19:00", "party_size": 2}],
    }


def fixture_s1():
    f = fixture()
    for r in f["restaurants"]:
        r.pop("combinable", None)
    return f


# ---------------------------------------------------------------- framework
def check(cid, row, desc, ok, detail=""):
    ok = bool(ok)
    RESULTS.append(dict(id=cid, row=row, desc=desc, ok=ok, detail="" if ok else str(detail)[:600]))
    print(("PASS " if ok else "FAIL ") + f"{cid} [{row}] {desc}" + ("" if ok else f" :: {str(detail)[:600]}"), flush=True)
    return ok


def note(cid, desc, detail=""):
    NOTES.append(dict(id=cid, desc=desc, detail=str(detail)[:500]))
    print(f"NOTE {cid} {desc} :: {str(detail)[:500]}", flush=True)


def reset(base=None, fx=None):
    r = api.post((base or BASE) + "/_test/reset", json=fx or fixture())
    assert r.status_code == 204, f"reset failed {r.status_code} {r.text[:200]}"


def token(user=ADA, base=None):
    return api.post((base or BASE) + "/auth/login", json={"email": user[0], "password": user[1]}).json()["token"]


def server_list(user=ADA, base=None):
    r = api.get((base or BASE) + "/reservations", headers={"Authorization": f"Bearer {token(user, base)}"})
    return r.json()["reservations"]


def api_book(user, rid, tids, hhmm, party, day=None):
    return api.post(BASE + "/reservations", headers={"Authorization": f"Bearer {token(user)}", "Idempotency-Key": os.urandom(8).hex()},
                    json={"restaurant_id": rid, "table_ids": tids, "starts_at_local": f"{day or D}T{hhmm}", "party_size": party})


def api_slot(rid, hhmm, party, day=None):
    j = api.get(BASE + f"/availability?restaurant_id={rid}&date={day or D}&party_size={party}").json()
    return next((s for s in j["slots"] if s["starts_at_local"].endswith(hhmm)), None), j["slots"]


def S(tid):
    return f'[data-testid="{tid}"]'


def count(page, tid):
    return page.locator(S(tid)).count()


def vis(page, tid):
    loc = page.locator(S(tid))
    return loc.count() > 0 and loc.first.is_visible()


def text(page, tid):
    loc = page.locator(S(tid))
    return (loc.first.text_content() or "").strip() if loc.count() else ""


def wait_vis(page, tid, ms=6000):
    try:
        page.locator(S(tid)).first.wait_for(state="visible", timeout=ms)
        return True
    except Exception:
        return False


def wait_gone(page, tid, ms=6000):
    try:
        page.wait_for_function("t => { const e = document.querySelector(`[data-testid=\"${t}\"]`); return !e || e.offsetParent === null && getComputedStyle(e).position !== 'fixed'; }", arg=tid, timeout=ms)
        return True
    except Exception:
        return not vis(page, tid)


def wait_attr(page, tid, attr, value, ms=6000):
    try:
        page.wait_for_function("([t, a, v]) => { const e = document.querySelector(`[data-testid=\"${t}\"]`); return e && e.getAttribute(a) === v; }", arg=[tid, attr, value], timeout=ms)
        return True
    except Exception:
        return False


class Ctx:
    """One browser context (fresh storage) with request recording."""

    def __init__(self, browser, width=1280, height=900):
        self.ctx = browser.new_context(viewport={"width": width, "height": height})
        self.page = self.ctx.new_page()
        self.posts = []   # (url, idempotency-key, body) for POST /reservations
        self.page.on("request", self._req)
        self.page.on("console", lambda m: CONSOLE.append(m.text) if m.type == "error" else None)
        self.page.on("pageerror", lambda e: CONSOLE.append(f"pageerror: {e}"))

    def _req(self, r):
        u = r.url
        if not (u.startswith(BASE) or u.startswith("data:") or u.startswith("about:") or u.startswith("blob:")):
            EXTERNAL.append(u)
        if r.method == "POST" and urlsplit(u).path == "/reservations":
            self.posts.append((u, r.headers.get("idempotency-key"), r.post_data))

    def close(self):
        self.ctx.close()


def ui_login(page, user=ADA):
    page.goto(BASE + "/login")
    page.fill(S("login-email"), user[0])
    page.fill(S("login-password"), user[1])
    page.click(S("login-submit"))
    return wait_vis(page, "current-user")


def search(page, rid, party, day=None, goto=True, wait=True):
    if goto and urlsplit(page.url).path != "/":
        page.goto(BASE + "/")
    page.wait_for_selector(f'{S("restaurant-select")} option[value="{rid}"]', state="attached", timeout=6000)
    page.select_option(S("restaurant-select"), rid)
    page.fill(S("date-input"), day or D)
    page.fill(S("party-size-input"), str(party))
    if wait:
        with page.expect_response(lambda r: "/availability" in r.url, timeout=8000):
            page.click(S("search-button"))
        page.wait_for_timeout(250)
    else:
        page.click(S("search-button"))


def cells(page):
    return page.eval_on_selector_all('[data-testid^="slot-"]', "els => els.map(e => [e.getAttribute('data-testid'), e.getAttribute('data-available')])")


def shot(page, name):
    try:
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)
    except Exception as e:
        note("SHOT", f"screenshot {name} failed", e)


# ---------------------------------------------------------------- sections
def u_routes(browser):
    for i, path in enumerate(["/", "/signup", "/login", "/lookup"]):
        r = api.get(BASE + path)
        check(f"UI.U1{'abcd'[i]}", "U1", f"GET {path} -> 200 text/html", r.status_code == 200 and r.headers.get("content-type", "").lower().startswith("text/html") and "<" in r.text, f"{r.status_code} {r.headers.get('content-type')}")
    r = api.get(BASE + "/no/such/route")
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
    check("UI.U1e", "U1", "unknown path still JSON 404 with error body", r.status_code == 404 and isinstance(j, dict) and j.get("error", {}).get("code") == "not_found", f"{r.status_code} {r.text[:120]}")
    r = api.get(BASE + "/restaurants")
    check("UI.U1f", "U1", "API /restaurants still application/json; charset=utf-8", r.headers.get("content-type", "").lower().replace(" ", "") == "application/json;charset=utf-8", r.headers.get("content-type"))


def u_auth(browser):
    reset()
    c = Ctx(browser)
    pg = c.page
    pg.goto(BASE + "/login")
    pg.wait_for_selector(S("login-submit"))
    check("UI.U3a", "U3", "login screen has login-email, login-password, login-submit", all(vis(pg, t) for t in ("login-email", "login-password", "login-submit")))
    check("UI.U4a", "U4", "auth-error absent from the DOM on a fresh /login; current-user absent when signed out", count(pg, "auth-error") == 0 and count(pg, "current-user") == 0, f"auth-error={count(pg, 'auth-error')} current-user={count(pg, 'current-user')}")
    pg.fill(S("login-email"), ADA[0])
    pg.fill(S("login-password"), "wrong password")
    pg.click(S("login-submit"))
    ok = wait_vis(pg, "auth-error")
    check("UI.U4b", "U3/U4", "bad login shows a nonempty auth-error and does not sign in", ok and text(pg, "auth-error") and count(pg, "current-user") == 0, text(pg, "auth-error"))
    shot(pg, "login-error-desktop")
    pg.fill(S("login-password"), ADA[1])
    pg.click(S("login-submit"))
    ok = wait_vis(pg, "current-user")
    check("UI.U3b", "U3/U5", "good login -> current-user contains the display name", ok and ADA[2] in text(pg, "current-user"), text(pg, "current-user"))
    pg.wait_for_timeout(300)
    check("UI.U4c", "U4", "auth-error gone after a successful login", count(pg, "auth-error") == 0 or not vis(pg, "auth-error"), count(pg, "auth-error"))
    bad = []
    for path in ["/", "/signup", "/login", "/lookup"]:
        pg.goto(BASE + path)
        if not (wait_vis(pg, "current-user", 4000) and ADA[2] in text(pg, "current-user") and vis(pg, "logout-button")):
            bad.append(path)
    check("UI.U5a", "U5", "current-user (with display name) and logout-button visible on all four routes when signed in", not bad, bad)
    pg.goto(BASE + "/")
    wait_vis(pg, "logout-button")
    pg.click(S("logout-button"))
    gone = wait_gone(pg, "current-user")
    bad = []
    for path in ["/", "/lookup"]:
        pg.goto(BASE + path)
        pg.wait_for_timeout(400)
        if vis(pg, "current-user"):
            bad.append(path)
    check("UI.U5b", "U5", "logout-button signs out: current-user gone, also after navigation", gone and not bad, bad)
    c.close()
    c = Ctx(browser)
    pg = c.page
    pg.goto(BASE + "/signup")
    pg.wait_for_selector(S("signup-submit"))
    check("UI.U2a", "U2", "signup screen has signup-email, signup-password, signup-display-name, signup-submit; no auth-error initially",
          all(vis(pg, t) for t in ("signup-email", "signup-password", "signup-display-name", "signup-submit")) and count(pg, "auth-error") == 0)
    pg.fill(S("signup-email"), "grace@example.com")
    pg.fill(S("signup-password"), "short")
    pg.fill(S("signup-display-name"), "Grace Hopper")
    pg.click(S("signup-submit"))
    ok = wait_vis(pg, "auth-error", 4000)
    check("UI.U4d", "U4", "signup with a 5-character password shows auth-error (or is blocked) and does not sign in", count(pg, "current-user") == 0 and (ok or True), "")
    if not ok:
        note("UI.U4d", "short password produced no auth-error element (possibly native form validation)", "")
    pg.fill(S("signup-password"), "long enough password")
    pg.click(S("signup-submit"))
    ok = wait_vis(pg, "current-user")
    check("UI.U2b", "U2", "signup signs the user in: current-user contains the display name", ok and "Grace Hopper" in text(pg, "current-user"), text(pg, "current-user"))
    r = api.post(BASE + "/auth/login", json={"email": "grace@example.com", "password": "long enough password"})
    check("UI.U2c", "U2", "the account exists on the server", r.status_code == 200, r.status_code)
    c.close()
    c = Ctx(browser)
    pg = c.page
    pg.goto(BASE + "/signup")
    pg.fill(S("signup-email"), ADA[0])
    pg.fill(S("signup-password"), "another password")
    pg.fill(S("signup-display-name"), "Impostor")
    pg.click(S("signup-submit"))
    ok = wait_vis(pg, "auth-error")
    check("UI.U4e", "U4", "signup with a registered email shows a nonempty auth-error", ok and text(pg, "auth-error") and count(pg, "current-user") == 0, text(pg, "auth-error"))
    c.close()


def u_grid(browser):
    reset()
    c = Ctx(browser)
    pg = c.page
    ui_login(pg)
    pg.goto(BASE + "/")
    pg.wait_for_selector(f'{S("restaurant-select")} option[value="r_anker"]', state="attached")
    check("UI.G1a", "G1", "search screen has restaurant-select, date-input, party-size-input, search-button", all(vis(pg, t) for t in ("restaurant-select", "date-input", "party-size-input", "search-button")))
    optv = pg.eval_on_selector_all(f'{S("restaurant-select")} option', "els => els.map(e => [e.value, e.textContent.trim()])")
    vals = [v for v, _ in optv if v]
    check("UI.G1b", "G1", "restaurant-select option values are exactly the restaurant ids", sorted(vals) == ["r_anker", "r_closed", "r_hafen"], optv)
    names = dict(optv)
    check("UI.G1c", "G1/Q1", "options show the restaurant names", all(n in (names.get(i) or "") for i, n in (("r_anker", "Zum Anker"), ("r_hafen", "Hafenblick"))), optv)
    check("UI.G1d", "G1", "date-input is a date field and party-size-input a number field",
          pg.get_attribute(S("date-input"), "type") == "date" and pg.get_attribute(S("party-size-input"), "type") == "number", f"{pg.get_attribute(S('date-input'), 'type')} {pg.get_attribute(S('party-size-input'), 'type')}")
    api_book(BOB, "r_anker", ["t_2"], "19:30", 2)
    for cid, party in (("UI.G2a", 2), ("UI.G2b", 4), ("UI.G2c", 6)):
        search(pg, "r_anker", party)
        got = dict(cells(pg))
        _, sl = api_slot("r_anker", "19:00", party)
        want, combos = {}, {}
        for s in sl:
            hh = s["starts_at_local"][-5:]
            for t in ("t_1", "t_2", "t_3"):
                want[f"slot-{t}-{hh}"] = "true" if t in s["available_table_ids"] else "false"
            for o in s["available_options"]:
                if len(o["table_ids"]) == 2:
                    combos[f"slot-{'+'.join(o['table_ids'])}-{hh}"] = "true"
        singles = {k: v for k, v in got.items() if "+" not in k}
        check(cid, "G2", f"party {party}: one cell per table per slot ({len(want)}), data-available equals available_table_ids membership; availability-grid visible",
              singles == want and vis(pg, "availability-grid"), {k: (singles.get(k), v) for k, v in want.items() if singles.get(k) != v} or f"extra={set(singles) - set(want)}")
        gotc = {k: v for k, v in got.items() if "+" in k}
        wrong = [k for k, v in combos.items() if gotc.get(k) != "true"] + [k for k, v in gotc.items() if v == "true" and k not in combos]
        rev = [k for k in gotc if k.startswith("slot-t_2+")]
        check(cid.replace("G2", "UC1"), "UC1", f"party {party}: combination cells slot-t_1+t_2-/slot-t_3+t_2- are available exactly for pairs in available_options ({len(combos)}); no reversed-id testid",
              not wrong and not rev and all(v in ("true", "false") for v in gotc.values()), f"wrong={wrong[:4]} reversed={rev[:2]}")
        if party == 2:
            shot(pg, "grid-desktop-party2")
        if party == 6:
            shot(pg, "grid-desktop-party6-combos")
    search(pg, "r_closed", 2)
    ok = wait_vis(pg, "no-slots", 4000)
    check("UI.G3a", "G3", "day without slots: no-slots visible and no slot cells shown", ok and not [k for k, _ in cells(pg) if pg.locator(S(k)).first.is_visible()], cells(pg)[:3])
    shot(pg, "no-slots-desktop")
    search(pg, "r_anker", 4)
    check("UI.G3b", "G3", "searching an open day afterwards: grid back, no-slots gone", vis(pg, "slot-t_2-19:00") and not vis(pg, "no-slots"), f"no-slots visible={vis(pg, 'no-slots')}")
    pg.click(S("slot-t_1-19:00"), force=True, timeout=3000)
    pg.wait_for_timeout(400)
    check("UI.G4a", "G4", "click on an unavailable cell does nothing (no booking form)", not vis(pg, "booking-form"), "")
    pg.click(S("slot-t_3-19:00"))
    ok = wait_vis(pg, "booking-form")
    sm = text(pg, "booking-summary")
    check("UI.G4b", "G4/F1", "click on an available cell opens the booking form: summary has table label and 19:00, party prefilled with 4, submit button present",
          ok and "19:00" in sm and "3" in sm and pg.input_value(S("booking-party-size")) == "4" and vis(pg, "booking-submit") and pg.get_attribute(S("booking-party-size"), "type") == "number", sm)
    shot(pg, "form-open-desktop")
    search(pg, "r_hafen", 2)
    pg.click(S("slot-h_a-12:00"))
    wait_vis(pg, "booking-form")
    sm = text(pg, "booking-summary")
    check("UI.F1a", "F1/Q1", "booking-summary shows the table label 'Fenster' and the local start time 12:00", "Fenster" in sm and "12:00" in sm, sm)
    c.close()
    # signed out
    c = Ctx(browser)
    pg = c.page
    search(pg, "r_anker", 2)
    pg.click(S("slot-t_1-19:00"))
    pg.wait_for_timeout(800)
    at_login = urlsplit(pg.url).path == "/login"
    check("UI.G5", "G5", "signed out: click on an available cell shows auth-error or navigates to /login", at_login or vis(pg, "auth-error"), f"url={pg.url} auth-error={vis(pg, 'auth-error')}")
    c.close()


def u_booking(browser):
    reset()
    c = Ctx(browser)
    pg = c.page
    ui_login(pg)
    search(pg, "r_anker", 4)
    pg.click(S("slot-t_2-19:00"))
    wait_vis(pg, "booking-form")
    check("UI.K1a", "K1", "no confirmation before submitting", not vis(pg, "confirmation") and not vis(pg, "booking-error"), "")
    pg.click(S("booking-submit"))
    ok = wait_vis(pg, "confirmation")
    refv = text(pg, "confirmation-reference")
    det = text(pg, "confirmation-details")
    sl = server_list()
    mine = [x for x in sl if x["reference"] != "PASTREF1"]
    check("UI.K1b", "K1", "confirmation shown; confirmation-reference is exactly the server's reference", ok and REF_RE.match(refv or "") and [x["reference"] for x in mine] == [refv], f"ui={refv!r} server={[x['reference'] for x in mine]}")
    check("UI.K1c", "K1", "confirmation-details contains restaurant name, table label and local start time", all(x in det for x in ("Zum Anker", "2", "19:00")), det)
    check("UI.K1d", "K1", "the reservation on the server is the selected one (t_2, 19:00, party 4)", mine and mine[0]["table_ids"] == ["t_2"] and mine[0]["starts_at_local"] == f"{D}T19:00" and mine[0]["party_size"] == 4, mine)
    check("UI.UC2s", "UC2", "single booking: confirmation-tables (if shown) contains the table label", count(pg, "confirmation-tables") == 0 or "2" in text(pg, "confirmation-tables"), text(pg, "confirmation-tables"))
    check("UI.F2a", "F2", "booking form stays on screen after success; no booking-error", vis(pg, "booking-form") and vis(pg, "booking-submit") and not vis(pg, "booking-error"), "")
    shot(pg, "confirmation-desktop")
    pg.click(S("booking-submit"))
    pg.wait_for_timeout(1200)
    mine2 = [x for x in server_list() if x["reference"] != "PASTREF1"]
    check("UI.F2b", "F2", "resubmitting the unchanged form: same confirmation-reference, no booking-error, still one reservation", text(pg, "confirmation-reference") == refv and not vis(pg, "booking-error") and len(mine2) == 1, f"{text(pg, 'confirmation-reference')!r} n={len(mine2)}")
    check("UI.F2c", "F2", "both submissions carried the same Idempotency-Key and the same body", len(c.posts) == 2 and c.posts[0][1] and c.posts[0][1] == c.posts[1][1] and json.loads(c.posts[0][2]) == json.loads(c.posts[1][2]), [(k, b) for _, k, b in c.posts])
    pg.fill(S("booking-party-size"), "3")
    pg.click(S("booking-submit"))
    pg.wait_for_timeout(1200)
    newp = c.posts[2:] if len(c.posts) > 2 else []
    check("UI.F3", "F3", "after changing booking-party-size the next submission is a new request (new key, party_size 3 in the body)",
          newp and newp[0][1] and newp[0][1] != c.posts[0][1] and json.loads(newp[0][2]).get("party_size") == 3, [(k, b) for _, k, b in c.posts])
    check("UI.F3b", "F3/R3", "that new request is refused by the server (own booking holds the table): booking-error shown", wait_vis(pg, "booking-error", 4000) and text(pg, "booking-error"), text(pg, "booking-error"))
    shot(pg, "booking-refused-desktop")
    # double click on a fresh selection
    search(pg, "r_anker", 2)
    pg.click(S("slot-t_3-20:30"))
    wait_vis(pg, "booking-form")
    n0 = len(server_list())
    pg.dblclick(S("booking-submit"))
    wait_vis(pg, "confirmation")
    pg.wait_for_timeout(1200)
    n1 = len(server_list())
    check("UI.F4", "F4", "double click on booking-submit leaves exactly one new reservation, a confirmation and no booking-error", n1 == n0 + 1 and vis(pg, "confirmation") and not vis(pg, "booking-error"), f"{n0}->{n1} error={text(pg, 'booking-error')}")
    c.close()


def u_conflict(browser):
    reset()
    c = Ctx(browser)
    pg = c.page
    ui_login(pg)
    search(pg, "r_anker", 3)
    pg.click(S("slot-t_2-19:00"))
    wait_vis(pg, "booking-form")
    r = api_book(BOB, "r_anker", ["t_2"], "19:00", 2)
    pg.click(S("booking-submit"))
    ok = wait_vis(pg, "booking-error")
    refreshed = wait_attr(pg, "slot-t_2-19:00", "data-available", "false")
    check("UI.R2a", "R2", "table taken by another client after the form opened: nonempty booking-error, no confirmation", r.status_code == 201 and ok and text(pg, "booking-error") and not vis(pg, "confirmation"), text(pg, "booking-error"))
    check("UI.R2b", "R2", "availability refreshed: the cell is now data-available=false", refreshed, dict(cells(pg)).get("slot-t_2-19:00"))
    check("UI.R2c", "R2", "form and its inputs preserved (form visible, party size 3, summary still names 19:00)", vis(pg, "booking-form") and pg.input_value(S("booking-party-size")) == "3" and "19:00" in text(pg, "booking-summary"), text(pg, "booking-summary"))
    check("UI.R2d", "R2", "no reservation was created for the diner", [x["reference"] for x in server_list()] == ["PASTREF1"], server_list())
    shot(pg, "conflict-refused-desktop")
    c.close()


def u_race(browser):
    reset()
    c = Ctx(browser)
    pg = c.page
    ui_login(pg)
    pg.goto(BASE + "/")
    held = []

    def handler(route):
        if not held:
            held.append(route)      # search A: answered later
        else:
            route.continue_()
    pg.route(re.compile(r"/availability"), handler)
    search(pg, "r_hafen", 2, wait=False)                 # A
    for _ in range(40):
        if held:
            break
        pg.wait_for_timeout(50)
    shot(pg, "loading-desktop")
    busy = pg.evaluate("() => document.querySelector('[aria-busy=\"true\"]') !== null")
    note("UI.Q2n", "loading state while a search is pending", f"aria-busy element present={busy}; see loading-desktop.png")
    search(pg, "r_anker", 4, goto=False)                 # B
    okb = wait_vis(pg, "slot-t_2-19:00")
    if held:
        held[0].continue_()
    pg.wait_for_timeout(1500)
    got = dict(cells(pg))
    check("UI.R1a", "R1", "search A (Hafenblick) answered after search B (Zum Anker): grid shows B's cells only", bool(held) and okb and "slot-t_2-19:00" in got and not [k for k in got if k.startswith("slot-h_")], list(got)[:6])
    check("UI.R1b", "R1", "search controls still describe B", pg.input_value(S("restaurant-select")) == "r_anker" and pg.input_value(S("party-size-input")) == "4", pg.input_value(S("restaurant-select")))
    pg.unroute(re.compile(r"/availability"))
    pg.click(S("slot-t_2-19:00"))
    wait_vis(pg, "booking-form")
    sm = text(pg, "booking-summary")
    check("UI.R1c", "R1", "booking form opened afterwards describes B (table 2, 19:00, party 4), nothing of A", "19:00" in sm and "Fenster" not in sm and "Garten" not in sm and pg.input_value(S("booking-party-size")) == "4", sm)
    pg.click(S("booking-submit"))
    wait_vis(pg, "confirmation")
    mine = [x for x in server_list() if x["reference"] != "PASTREF1"]
    check("UI.R1d", "R1", "the booking made from that form is for B's restaurant and table", len(mine) == 1 and mine[0]["restaurant_id"] == "r_anker" and mine[0]["table_ids"] == ["t_2"], mine)
    c.close()


def lose_after_commit(route):
    try:
        route.fetch()
    finally:
        route.abort("failed")


def u_lost(browser):
    reset()
    c = Ctx(browser)
    pg = c.page
    ui_login(pg)
    search(pg, "r_anker", 4)
    pg.click(S("slot-t_2-19:00"))
    wait_vis(pg, "booking-form")
    pat = re.compile(r"/reservations$")
    pg.route(pat, lambda route: lose_after_commit(route) if route.request.method == "POST" else route.continue_())
    pg.click(S("booking-submit"))
    ok = wait_vis(pg, "booking-uncertain")
    mine = [x for x in server_list() if x["reference"] != "PASTREF1"]
    check("UI.R3a", "R3", "response lost after commit: nonempty booking-uncertain, no booking-error, no confirmation", ok and text(pg, "booking-uncertain") and not vis(pg, "booking-error") and not vis(pg, "confirmation"),
          f"uncertain={text(pg, 'booking-uncertain')!r} error={vis(pg, 'booking-error')} conf={vis(pg, 'confirmation')}")
    check("UI.R3b", "R3", "the booking did commit on the server exactly once", len(mine) == 1, mine)
    shot(pg, "uncertain-desktop")
    pg.unroute(pat)
    pg.click(S("booking-submit"))
    ok = wait_vis(pg, "confirmation")
    mine2 = [x for x in server_list() if x["reference"] != "PASTREF1"]
    check("UI.R3c", "R3", "retry of the unchanged form shows the original reference; uncertainty and error removed; still one reservation",
          ok and mine and text(pg, "confirmation-reference") == mine[0]["reference"] and not vis(pg, "booking-uncertain") and not vis(pg, "booking-error") and len(mine2) == 1, f"{text(pg, 'confirmation-reference')!r} vs {mine}")
    check("UI.R3d", "R3", "the retry used the same Idempotency-Key and the same body", len(c.posts) == 2 and c.posts[0][1] and c.posts[0][1] == c.posts[1][1] and json.loads(c.posts[0][2]) == json.loads(c.posts[1][2]), [(k, b) for _, k, b in c.posts])
    # lost before commit
    search(pg, "r_anker", 2)
    pg.click(S("slot-t_3-19:00"))
    wait_vis(pg, "booking-form")
    n0 = len(server_list())
    pg.route(pat, lambda route: route.abort("failed") if route.request.method == "POST" else route.continue_())
    pg.click(S("booking-submit"))
    ok = wait_vis(pg, "booking-uncertain")
    check("UI.R3e", "R3", "request lost before commit: booking-uncertain, no confirmation for this selection, nothing new on the server",
          ok and not vis(pg, "booking-error") and not vis(pg, "confirmation") and len(server_list()) == n0, f"conf={vis(pg, 'confirmation')} n={len(server_list())}")
    pg.unroute(pat)
    pg.click(S("booking-submit"))
    ok = wait_vis(pg, "confirmation")
    new = [x for x in server_list() if x["table_ids"] == ["t_3"] and x["reference"] != "PASTREF1"]
    check("UI.R3f", "R3", "retry then succeeds: confirmation with the server's reference, uncertainty removed", ok and len(new) == 1 and text(pg, "confirmation-reference") == new[0]["reference"] and not vis(pg, "booking-uncertain"), new)
    # uncertain, then a confirmed rejection
    search(pg, "r_anker", 2)
    pg.click(S("slot-t_1-21:00"))
    wait_vis(pg, "booking-form")
    pg.route(pat, lambda route: route.abort("failed") if route.request.method == "POST" else route.continue_())
    pg.click(S("booking-submit"))
    wait_vis(pg, "booking-uncertain")
    pg.unroute(pat)
    api_book(BOB, "r_anker", ["t_1"], "21:00", 2)
    pg.click(S("booking-submit"))
    ok = wait_vis(pg, "booking-error")
    check("UI.R3g", "R3", "retry answered by a confirmed rejection (409): booking-error, no confirmation", ok and text(pg, "booking-error") and not vis(pg, "confirmation"), f"error={text(pg, 'booking-error')!r} conf={vis(pg, 'confirmation')}")
    if vis(pg, "booking-uncertain"):
        note("UI.R3n", "booking-uncertain still visible next to booking-error after a confirmed rejection", text(pg, "booking-uncertain"))
    c.close()


def u_combo(browser):
    reset()
    c = Ctx(browser)
    pg = c.page
    ui_login(pg)
    search(pg, "r_hafen", 8)
    got = dict(cells(pg))
    check("UI.UC1h", "UC1", "party 8 at Hafenblick: combination cell slot-h_b+h_a-12:00 available (ids in combinable order), singles unavailable, no slot-h_a+h_b testid",
          got.get("slot-h_b+h_a-12:00") == "true" and got.get("slot-h_a-12:00") == "false" and got.get("slot-h_b-12:00") == "false" and "slot-h_a+h_b-12:00" not in got, got)
    celltext = text(pg, "slot-h_b+h_a-12:00")
    check("UI.Q1a", "Q1", "combination cell text is human-readable (table labels, not raw ids)", "h_b" not in celltext and "h_a" not in celltext, celltext)
    shot(pg, "grid-desktop-combo-hafen")
    pg.click(S("slot-h_b+h_a-12:00"))
    wait_vis(pg, "booking-form")
    sm = text(pg, "booking-summary")
    check("UI.UC2a", "UC2/Q1", "booking-summary names both tables (Garten, Fenster) and 12:00, without raw 'h_b+h_a'", "Garten" in sm and "Fenster" in sm and "12:00" in sm and "h_b+h_a" not in sm and pg.input_value(S("booking-party-size")) == "8", sm)
    pat = re.compile(r"/reservations$")
    pg.route(pat, lambda route: lose_after_commit(route) if route.request.method == "POST" else route.continue_())
    pg.click(S("booking-submit"))
    ok = wait_vis(pg, "booking-uncertain")
    mine = [x for x in server_list() if x["reference"] != "PASTREF1"]
    check("UI.R4a", "R4", "combination booking, response lost after commit: booking-uncertain, no error, no confirmation; one pair booking on the server",
          ok and not vis(pg, "booking-error") and not vis(pg, "confirmation") and len(mine) == 1 and mine[0]["table_ids"] == ["h_b", "h_a"], mine)
    pg.unroute(pat)
    pg.click(S("booking-submit"))
    ok = wait_vis(pg, "confirmation")
    ct, refv = text(pg, "confirmation-tables"), text(pg, "confirmation-reference")
    check("UI.R4b", "R4/UC3", "retry recovers the original reference; same key and body; still one booking", ok and mine and refv == mine[0]["reference"] and len(c.posts) == 2 and c.posts[0][1] == c.posts[1][1]
          and json.loads(c.posts[0][2]) == json.loads(c.posts[1][2]) and len(server_list()) == 2, f"{refv!r} {[(k) for _, k, _ in c.posts]}")
    check("UI.UC2b", "UC2", "confirmation-tables contains every table label (Garten, Fenster); details have restaurant name and time", "Garten" in ct and "Fenster" in ct and "Hafenblick" in text(pg, "confirmation-details") and "12:00" in text(pg, "confirmation-details"), f"{ct!r} / {text(pg, 'confirmation-details')!r}")
    shot(pg, "confirmation-combo-desktop")
    # 409 on a combination
    pg.click(S("slot-h_b+h_a-13:00"))
    wait_vis(pg, "booking-form")
    api_book(BOB, "r_hafen", ["h_a"], "13:00", 2)
    pg.click(S("booking-submit"))
    ok = wait_vis(pg, "booking-error")
    pg.wait_for_timeout(1000)
    after = dict(cells(pg))
    check("UI.R4c", "R4", "combination refused with 409 (a member was taken): booking-error, no new confirmation for it, form kept, cell no longer available",
          ok and vis(pg, "booking-form") and after.get("slot-h_b+h_a-13:00") != "true" and after.get("slot-h_a-13:00") == "false" and len(server_list()) == 2
          and (not vis(pg, "confirmation") or text(pg, "confirmation-reference") == refv), f"cells={after.get('slot-h_b+h_a-13:00')},{after.get('slot-h_a-13:00')} conf={vis(pg, 'confirmation')}")
    # lookup + cancel
    pg.goto(BASE + "/lookup")
    pg.fill(S("lookup-reference-input"), refv)
    pg.click(S("lookup-submit"))
    ok = wait_vis(pg, "reservation-detail")
    rt = text(pg, "reservation-tables")
    check("UI.UC2c", "UC2/UC3", "lookup of the combination: reservation-detail, status exactly 'confirmed', reservation-tables names both tables", ok and text(pg, "reservation-status") == "confirmed" and "Garten" in rt and "Fenster" in rt, f"{text(pg, 'reservation-status')!r} {rt!r}")
    shot(pg, "lookup-combo-desktop")
    pg.click(S("reservation-cancel-button"))
    try:
        pg.wait_for_function("() => { const e = document.querySelector('[data-testid=\"reservation-status\"]'); return e && e.textContent.trim() === 'cancelled'; }", timeout=6000)
    except Exception:
        pass
    s12, _ = api_slot("r_hafen", "12:00", 1)
    check("UI.UC3", "UC3/L2", "cancel of the combination: status exactly 'cancelled', cancel button absent, both tables free on the server",
          text(pg, "reservation-status") == "cancelled" and count(pg, "reservation-cancel-button") == 0 and s12["available_table_ids"] == ["h_a", "h_b"], f"{text(pg, 'reservation-status')!r} btn={count(pg, 'reservation-cancel-button')} {s12['available_table_ids']}")
    c.close()


def u_lookup(browser):
    reset()
    r = api_book(ADA, "r_anker", ["t_2"], "19:00", 4)
    refv = r.json()["reference"]
    other = api_book(BOB, "r_anker", ["t_3"], "19:00", 2).json()["reference"]
    c = Ctx(browser)
    pg = c.page
    ui_login(pg)
    pg.goto(BASE + "/lookup")
    pg.wait_for_selector(S("lookup-submit"))
    check("UI.L1a", "L1", "lookup screen has lookup-reference-input and lookup-submit; no detail or error before a lookup", vis(pg, "lookup-reference-input") and not vis(pg, "reservation-detail") and not vis(pg, "reservation-error"), "")
    shot(pg, "lookup-empty-desktop")
    pg.fill(S("lookup-reference-input"), "ZZZZZZ99")
    pg.click(S("lookup-submit"))
    ok = wait_vis(pg, "reservation-error")
    check("UI.L3a", "L3", "unknown reference: nonempty reservation-error, no reservation-detail", ok and text(pg, "reservation-error") and not vis(pg, "reservation-detail"), text(pg, "reservation-error"))
    shot(pg, "lookup-notfound-desktop")
    pg.fill(S("lookup-reference-input"), other)
    pg.click(S("lookup-submit"))
    pg.wait_for_timeout(800)
    check("UI.L3b", "L3", "another diner's reference: reservation-error, no detail", vis(pg, "reservation-error") and not vis(pg, "reservation-detail"), "")
    pg.fill(S("lookup-reference-input"), refv)
    pg.click(S("lookup-submit"))
    ok = wait_vis(pg, "reservation-detail")
    check("UI.L1b", "L1", "own reference: reservation-detail shown, reservation-status exactly 'confirmed', cancel button present, error gone",
          ok and text(pg, "reservation-status") == "confirmed" and vis(pg, "reservation-cancel-button") and not vis(pg, "reservation-error"), f"{text(pg, 'reservation-status')!r} err={vis(pg, 'reservation-error')}")
    det = text(pg, "reservation-detail")
    check("UI.L1c", "L1/Q1", "detail shows the reference, restaurant name and local time", refv in det and "Zum Anker" in det and "19:00" in det, det[:200])
    if count(pg, "reservation-tables") == 0:
        note("UI.L1n", "reservation-tables absent for a single-table booking", "")
    else:
        check("UI.UC2d", "UC2", "reservation-tables of a single booking contains its label", "2" in text(pg, "reservation-tables"), text(pg, "reservation-tables"))
    shot(pg, "lookup-found-desktop")
    pg.click(S("reservation-cancel-button"))
    try:
        pg.wait_for_function("() => { const e = document.querySelector('[data-testid=\"reservation-status\"]'); return e && e.textContent.trim() === 'cancelled'; }", timeout=6000)
    except Exception:
        pass
    s19, _ = api_slot("r_anker", "19:00", 4)
    check("UI.L2a", "L2", "cancel: status exactly 'cancelled' without reload, cancel button absent, slot free on the server", text(pg, "reservation-status") == "cancelled" and count(pg, "reservation-cancel-button") == 0 and "t_2" in s19["available_table_ids"],
          f"{text(pg, 'reservation-status')!r} btn={count(pg, 'reservation-cancel-button')} {s19['available_table_ids']}")
    pg.goto(BASE + "/lookup")
    pg.fill(S("lookup-reference-input"), refv)
    pg.click(S("lookup-submit"))
    wait_vis(pg, "reservation-detail")
    check("UI.L2b", "L2", "lookup of a cancelled booking: status 'cancelled', no cancel button", text(pg, "reservation-status") == "cancelled" and count(pg, "reservation-cancel-button") == 0, text(pg, "reservation-status"))
    pg.fill(S("lookup-reference-input"), "PASTREF1")
    pg.click(S("lookup-submit"))
    wait_vis(pg, "reservation-detail")
    pg.wait_for_timeout(300)
    if vis(pg, "reservation-cancel-button"):
        pg.click(S("reservation-cancel-button"))
        ok = wait_vis(pg, "reservation-error")
        check("UI.L3c", "L3", "refused cancel (booking already started): nonempty reservation-error, status stays 'confirmed'", ok and text(pg, "reservation-error") and text(pg, "reservation-status") == "confirmed", f"{text(pg, 'reservation-error')!r} {text(pg, 'reservation-status')!r}")
        shot(pg, "lookup-cancel-refused-desktop")
    else:
        check("UI.L3c", "L3", "past booking offers the cancel button (status confirmed) so a refusal can be shown", False, f"status={text(pg, 'reservation-status')!r}")
    c.close()


CONTRAST_JS = r"""
() => {
  const parse = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(',').map(x => parseFloat(x)); return {r:p[0], g:p[1], b:p[2], a:p.length > 3 ? p[3] : 1}; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const bgOf = el => { let e = el; while (e) { const s = getComputedStyle(e); if (s.backgroundImage && s.backgroundImage !== 'none') return null; const c = parse(s.backgroundColor); if (c && c.a >= 0.99) return c; if (c && c.a > 0.01) return null; e = e.parentElement; } return {r:255, g:255, b:255, a:1}; };
  const out = [];
  const els = document.querySelectorAll('[data-testid], label, h1, h2, h3, p, a, button, th, td, legend');
  for (const el of els) {
    if (el.offsetParent === null) continue;
    const own = Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim().length > 0) || ['INPUT', 'SELECT'].includes(el.tagName);
    if (!own) continue;
    const s = getComputedStyle(el); const fg = parse(s.color); const bg = bgOf(el);
    if (!fg || !bg || fg.a < 0.99 || parseFloat(s.opacity) < 0.99) { out.push({el: (el.getAttribute('data-testid') || el.tagName) + ':' + (el.textContent || '').trim().slice(0, 20), ratio: null}); continue; }
    const l1 = lum(fg), l2 = lum(bg); const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const px = parseFloat(s.fontSize); const bold = parseInt(s.fontWeight) >= 700; const large = px >= 24 || (bold && px >= 18.66);
    out.push({el: (el.getAttribute('data-testid') || el.tagName) + ':' + (el.textContent || '').trim().slice(0, 20), ratio: Math.round(ratio * 100) / 100, need: large ? 3 : 4.5, disabled: el.disabled === true || el.getAttribute('aria-disabled') === 'true'});
  }
  return out;
}
"""

LABEL_JS = r"""
ids => ids.map(t => { const e = document.querySelector(`[data-testid="${t}"]`); if (!e) return [t, 'missing'];
  const lab = e.labels && Array.from(e.labels).find(l => l.offsetParent !== null && l.textContent.trim().length > 0);
  return [t, lab ? lab.textContent.trim().slice(0, 30) : null]; })
"""

FOCUS_JS = r"""
t => { const e = document.querySelector(`[data-testid="${t}"]`); const s = getComputedStyle(e);
  return {active: document.activeElement === e, outline: s.outlineStyle + ' ' + s.outlineWidth + ' ' + s.outlineColor, shadow: s.boxShadow, border: s.borderColor}; }
"""


def overflow(page):
    return page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")


def contrast_fail(page):
    res = page.evaluate(CONTRAST_JS)
    bad = [x for x in res if x["ratio"] is not None and x["ratio"] < x["need"] and not x.get("disabled")]
    unknown = [x["el"] for x in res if x["ratio"] is None]
    return bad, unknown


def u_layout(browser):
    navs = {}
    for vw, tag in ((375, "mobile"), (1280, "desktop")):
        reset()
        api_book(BOB, "r_anker", ["t_2"], "19:30", 2)
        c = Ctx(browser, width=vw, height=800)
        pg = c.page
        bad, cbad, unknown = [], [], set()
        for path in ["/", "/signup", "/login", "/lookup"]:
            pg.goto(BASE + path)
            pg.wait_for_timeout(500)
            sw, iw = overflow(pg)
            if sw > iw:
                bad.append(f"{path}: scrollWidth {sw} > {iw}")
            shot(pg, f"route{path.replace('/', '_') or '_'}-{tag}")
            b, u = contrast_fail(pg)
            cbad += [f"{path} {x['el']} {x['ratio']}<{x['need']}" for x in b]
            unknown |= set(u)
            if vw == 1280:
                navs[path] = sorted(set(pg.eval_on_selector_all("nav a[href], header a[href]", "els => els.map(e => new URL(e.href).pathname)")))
        lab = {}
        pg.goto(BASE + "/signup")
        lab.update(dict(pg.evaluate(LABEL_JS, ["signup-email", "signup-password", "signup-display-name"])))
        pg.goto(BASE + "/lookup")
        lab.update(dict(pg.evaluate(LABEL_JS, ["lookup-reference-input"])))
        ui_login(pg)
        lab.update(dict(pg.evaluate(LABEL_JS, [])))
        pg.goto(BASE + "/login")
        search(pg, "r_anker", 2)
        lab.update(dict(pg.evaluate(LABEL_JS, ["restaurant-select", "date-input", "party-size-input"])))
        sw, iw = overflow(pg)
        if sw > iw:
            bad.append(f"/ with grid: {sw} > {iw}")
        shot(pg, f"grid-{tag}")
        b, u = contrast_fail(pg)
        cbad += [f"grid {x['el']} {x['ratio']}<{x['need']}" for x in b]
        search(pg, "r_anker", 6)
        sw, iw = overflow(pg)
        if sw > iw:
            bad.append(f"/ with combination grid: {sw} > {iw}")
        shot(pg, f"grid-combos-{tag}")
        pg.locator(S("slot-t_1+t_2-21:00")).scroll_into_view_if_needed()
        pg.click(S("slot-t_1+t_2-21:00"))
        wait_vis(pg, "booking-form")
        lab.update(dict(pg.evaluate(LABEL_JS, ["booking-party-size"])))
        sw, iw = overflow(pg)
        if sw > iw:
            bad.append(f"/ with form: {sw} > {iw}")
        shot(pg, f"form-selected-{tag}")
        pg.click(S("booking-submit"))
        okc = wait_vis(pg, "confirmation")
        sw, iw = overflow(pg)
        if sw > iw:
            bad.append(f"/ with confirmation: {sw} > {iw}")
        shot(pg, f"confirmation-{tag}")
        b, u = contrast_fail(pg)
        cbad += [f"confirmation {x['el']} {x['ratio']}<{x['need']}" for x in b]
        refv = text(pg, "confirmation-reference")
        pg.goto(BASE + "/lookup")
        pg.fill(S("lookup-reference-input"), refv)
        pg.click(S("lookup-submit"))
        wait_vis(pg, "reservation-detail")
        sw, iw = overflow(pg)
        if sw > iw:
            bad.append(f"/lookup with detail: {sw} > {iw}")
        shot(pg, f"lookup-detail-{tag}")
        b, u = contrast_fail(pg)
        cbad += [f"lookup {x['el']} {x['ratio']}<{x['need']}" for x in b]
        check(f"UI.Q3-{tag}", "Q3", f"{vw}px: no horizontal page scroll on the four routes, populated grid, combination grid, form, confirmation, lookup detail; whole flow completes", not bad and okc, bad)
        nolab = [k for k, v in lab.items() if not v or v == "missing"]
        check(f"UI.Q4a-{tag}", "Q4", f"{vw}px: every required input has a visible label element", not nolab, lab)
        check(f"UI.Q4c-{tag}", "Q4", f"{vw}px: text contrast >= 4.5:1 (3:1 large text) on visible text elements", not cbad, sorted(set(cbad))[:8])
        if unknown:
            note(f"UI.Q4c-{tag}", "contrast not computable (gradient/translucent background) for", sorted(unknown)[:8])
        if vw == 1280:
            pg.goto(BASE + "/")
            pg.wait_for_selector(S("search-button"))
            foc = {}
            for t in ("party-size-input", "search-button"):
                before = pg.evaluate(FOCUS_JS, t)
                for _ in range(40):
                    pg.keyboard.press("Tab")
                    if pg.evaluate(FOCUS_JS, t)["active"]:
                        break
                after = pg.evaluate(FOCUS_JS, t)
                foc[t] = (before, after)
            okf = all(a["active"] and (a["outline"] != b["outline"] or a["shadow"] != b["shadow"] or a["border"] != b["border"]) and not (a["outline"].startswith("none") and a["shadow"] == "none" and a["border"] == b["border"]) for b, a in foc.values())
            check("UI.Q4b", "Q4", "keyboard focus is apparent: focused control reachable by Tab and its outline/shadow/border differs from the unfocused state", okf, foc)
            shot(pg, "focus-desktop")
        c.close()
    vals = list(navs.values())
    check("UI.Q4d", "Q4", "the same navigation links on all four routes, covering search, lookup and sign-in", vals and all(v == vals[0] for v in vals) and {"/", "/lookup"} <= set(vals[0]) and ({"/login"} & set(vals[0])), navs)


def u_upgrade(browser):
    if not S1BASE:
        check("UI.X2", "X2", "stage-1 container available for the upgrade probe", False, "S1BASE not set")
        return
    reset(S1BASE, fixture_s1())
    reset()
    kept = api.post(S1BASE + "/reservations", headers={"Authorization": f"Bearer {token(ADA, S1BASE)}", "Idempotency-Key": "kept-key-1"},
                    json={"restaurant_id": "r_anker", "table_id": "t_3", "starts_at_local": f"{D}T21:00", "party_size": 2}).json()["reference"]
    c = Ctx(browser)
    pg = c.page
    state = {"lose": False}

    def to_stage1(route):
        rq = route.request
        url = S1BASE + urlsplit(rq.url).path + (("?" + urlsplit(rq.url).query) if urlsplit(rq.url).query else "")
        resp = route.fetch(url=url)
        if state["lose"] and rq.method == "POST" and urlsplit(rq.url).path == "/reservations":
            route.abort("failed")
        else:
            route.fulfill(response=resp)
    pat = re.compile(r"/(auth/|reservations|reservation-moves)")
    pg.route(pat, to_stage1)                      # before the upgrade the account/booking API is the stage-1 service
    ok = ui_login(pg)
    check("UI.X2a", "X2", "browser signs in while the stage-1 service is behind the API (token issued by stage 1)", ok and ADA[2] in text(pg, "current-user"), text(pg, "current-user"))
    search(pg, "r_anker", 4)
    pg.click(S("slot-t_2-19:00"))
    wait_vis(pg, "booking-form")
    state["lose"] = True
    pg.click(S("booking-submit"))
    oku = wait_vis(pg, "booking-uncertain")
    s1list = [x for x in server_list(ADA, S1BASE) if x["reference"] not in ("PASTREF1", kept)]
    check("UI.X3a", "X3", "booking sent before the upgrade, response lost: booking-uncertain; stage 1 committed exactly one booking", oku and len(s1list) == 1 and not vis(pg, "confirmation"), s1list)
    E = api.get(S1BASE + "/_test/export").json()
    im = api.post(BASE + "/_test/import", json=E)
    pg.unroute(pat)                               # upgrade done: same origin is now served by stage 2 only
    check("UI.X1", "X1", "stage-2 imports the stage-1 export -> 204", im.status_code == 204, f"{im.status_code} {im.text[:200]}")
    pg.click(S("booking-submit"))
    okc = wait_vis(pg, "confirmation")
    s2list = [x for x in server_list(ADA) if x["reference"] not in ("PASTREF1", kept)]
    check("UI.X3b", "X3", "after the upgrade, without reload, the unchanged form retries and shows the original stage-1 reference; uncertainty removed; still one booking",
          okc and s1list and text(pg, "confirmation-reference") == s1list[0]["reference"] and not vis(pg, "booking-uncertain") and not vis(pg, "booking-error") and len(s2list) == 1, f"{text(pg, 'confirmation-reference')!r} vs {s1list} / {s2list}")
    check("UI.X3c", "X3", "the retry carried the same Idempotency-Key and body as the lost request", len(c.posts) == 2 and c.posts[0][1] and c.posts[0][1] == c.posts[1][1] and json.loads(c.posts[0][2]) == json.loads(c.posts[1][2]), [(k, b) for _, k, b in c.posts])
    det, ctab = text(pg, "confirmation-details"), text(pg, "confirmation-tables")
    check("UI.X3d", "X3/K1", "recovered confirmation still has restaurant name, table label and local start time; confirmation-tables (if shown) has the label",
          all(x in det for x in ("Zum Anker", "2", "19:00")) and (count(pg, "confirmation-tables") == 0 or "2" in ctab), f"{det!r} / {ctab!r}")
    check("UI.X2b", "X2", "still signed in after the upgrade without a reload", vis(pg, "current-user") and ADA[2] in text(pg, "current-user"), text(pg, "current-user"))
    shot(pg, "upgrade-recovered-desktop")
    pg.goto(BASE + "/lookup")
    check("UI.X2c", "X2", "still signed in after navigating (token issued by stage 1 accepted by stage 2)", wait_vis(pg, "current-user", 4000), "")
    pg.fill(S("lookup-reference-input"), kept)
    pg.click(S("lookup-submit"))
    ok = wait_vis(pg, "reservation-detail")
    check("UI.X2d", "X2", "a reference retained from stage 1 opens in lookup with status 'confirmed'", ok and text(pg, "reservation-status") == "confirmed" and not vis(pg, "reservation-error"), text(pg, "reservation-status"))
    check("UI.X2e", "X2/UC2", "lookup of the stage-1-era reservation shows its table label (reservation-tables or detail text)", "3" in (text(pg, "reservation-tables") or text(pg, "reservation-detail")), text(pg, "reservation-tables"))
    c.close()


def main():
    only = set(sys.argv[1:])
    secs = [u_routes, u_auth, u_grid, u_booking, u_conflict, u_race, u_lost, u_combo, u_lookup, u_layout, u_upgrade]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for s in secs:
            if only and s.__name__ not in only:
                continue
            print(f"\n=== {s.__name__} ===", flush=True)
            try:
                s(browser)
            except Exception:
                check(f"CRASH.{s.__name__}", "-", f"section {s.__name__} ran to completion", False, traceback.format_exc()[-700:])
        browser.close()
    print("\n=== final audits ===")
    check("UI.EXT", "S2-D", "no browser request left the service origin during the UI probes", not EXTERNAL, sorted(set(EXTERNAL))[:5])
    if CONSOLE:
        note("UI.CONSOLE", f"{len(CONSOLE)} browser console errors (aborted/4xx fetches are expected)", sorted(set(CONSOLE))[:6])
    fails = [r for r in RESULTS if not r["ok"]]
    print(f"\nTOTAL {len(RESULTS)} checks: {len(RESULTS) - len(fails)} passed, {len(fails)} failed, {len(NOTES)} notes", flush=True)
    for f in fails:
        print(f"  FAIL {f['id']} [{f['row']}] {f['desc']} :: {f['detail']}")
    if OUT:
        with open(OUT, "w") as fh:
            json.dump({"results": RESULTS, "notes": NOTES}, fh, indent=1)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
