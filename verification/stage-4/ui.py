#!/usr/bin/env python3
"""Nightshift Verifier - Pocketful stage 2 - browser checks (Playwright, Chromium).

ui.py --list
ui.py --base http://h:p --out DIR [--only PREFIX,...] [--s1base http://h:p]

Every check runs at 375x740 and at 1280x800 in a fresh browser context. The API (checks1.Sess)
is used as the "other client" side channel. Screenshots go to DIR for the product-quality read.
"""
import argparse
import json
import os
import re
import sys
import time
import traceback
import urllib.parse

import checks1 as c1
from checks1 import HS, OTHERFX, PW, T, basefx, k, user
from checks2 import auth_by_id, auths, authfx, iso, me3

UI = []
VIEWPORTS = [("375", 375, 740), ("1280", 1280, 800)]
EXTERNAL = set()
PAGE_ERRORS = []


def ui(cid, clause, row, desc):
    def deco(fn):
        UI.append(dict(id=cid, clause=clause, row=row, desc=desc, fn=fn))
        return fn
    return deco


class Ctx:
    def __init__(self, browser, base, vp, out, S):
        self.browser, self.base, self.vp, self.out, self.S = browser, base, vp, out, S
        self.contexts = []
        self.host = urllib.parse.urlparse(base).netloc

    def page(self):
        name, w, h = self.vp
        c = self.browser.new_context(viewport={"width": w, "height": h})
        c.set_default_timeout(6000)
        c.on("request", lambda r: EXTERNAL.add(r.url) if urllib.parse.urlparse(r.url).scheme in ("http", "https")
             and urllib.parse.urlparse(r.url).netloc != self.host else None)
        self.contexts.append(c)
        p = c.new_page()
        p.on("pageerror", lambda e: PAGE_ERRORS.append(str(e)[:200]))
        return p

    def shot(self, page, name):
        try:
            page.screenshot(path=os.path.join(self.out, f"{name}-{self.vp[0]}.png"), full_page=True)
        except Exception:
            pass

    def close(self):
        for c in self.contexts:
            try:
                c.close()
            except Exception:
                pass


def q(tid):
    return f'[data-testid="{tid}"]'


def count(page, tid):
    return page.locator(q(tid)).count()


def visible(page, tid):
    loc = page.locator(q(tid))
    return loc.count() > 0 and loc.first.is_visible()


def text(page, tid):
    loc = page.locator(q(tid))
    return loc.first.inner_text().strip() if loc.count() else None


def attr(page, tid, name):
    loc = page.locator(q(tid))
    return loc.first.get_attribute(name) if loc.count() else None


def wait(page, cond, timeout=6000):
    """Poll a Python predicate while letting the page run."""
    end = time.monotonic() + timeout / 1000
    while time.monotonic() < end:
        try:
            if cond():
                return True
        except Exception:
            pass
        page.wait_for_timeout(100)
    return False


def wait_amount(page, tid, minor, timeout=6000):
    return wait(page, lambda: attr(page, tid, "data-amount") == str(minor), timeout)


def settle(page, ms=700):
    try:
        page.wait_for_load_state("networkidle", timeout=4000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


def login(t, cx, page, handle, pw=PW, path="/"):
    page.goto(cx.base + "/login")
    page.locator(q("login-email")).fill(f"{handle}@example.com")
    page.locator(q("login-password")).fill(pw)
    page.locator(q("login-submit")).click()
    ok = wait(page, lambda: visible(page, "current-user"))
    t.ok(ok, f"login as {handle} through the UI: current-user did not appear")
    if path != "/" or not wait(page, lambda: count(page, "wallet-balance") > 0, 1500):
        page.goto(cx.base + path)
    settle(page, 300)
    return ok


def fill_pay(page, handle, amount, note=None, vis=None, prefix="pay"):
    page.locator(q(f"{prefix}-handle")).fill(handle)
    page.locator(q(f"{prefix}-amount")).fill(amount)
    if note is not None:
        page.locator(q(f"{prefix}-note")).fill(note)
    if vis is not None:
        page.locator(q(f"{prefix}-visibility")).select_option(vis)


def posts(page, path_re):
    """Record POST requests whose path matches; returns the live list of (key, body)."""
    seen = []
    rx = re.compile(path_re)

    def on(r):
        if r.method == "POST" and rx.search(urllib.parse.urlparse(r.url).path):
            seen.append((r.headers.get("idempotency-key"), r.post_data))
    page.on("request", on)
    return seen


def child_ids(page, list_tid, prefix):
    return page.eval_on_selector_all(
        f'{q(list_tid)} [data-testid^="{prefix}"]',
        "(els, p) => els.map(e => e.getAttribute('data-testid')).filter(x => /^[^ ]+$/.test(x)).map(x => x.slice(p.length))", prefix)


def no_hscroll(page):
    return page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")


ROUTES = ["/", "/requests", "/split", "/authorizations"]


# --------------------------------------------------------------------------- M auth
@ui("M1-signup-login", "stage-2 Signup and login", "M1,M2,M3,M4,L1,L3", "Signup and login forms work; auth-error present only on error; current-user contains the display name and current-handle is exactly the handle on every screen; logout-button signs out; screens reachable by URL and through navigation")
def u_auth(t, cx):
    S = cx.S
    S.reset(basefx())
    page = cx.page()
    page.goto(cx.base + "/signup")
    for tid in ("signup-email", "signup-password", "signup-display-name", "signup-submit"):
        t.ok(visible(page, tid), f"/signup lacks visible {tid}")
    t.eq(count(page, "auth-error"), 0, "auth-error on a fresh /signup")
    t.ok(not visible(page, "current-user"), "current-user while signed out")
    cx.shot(page, "signup-empty")
    page.locator(q("signup-email")).fill("ada@example.com")
    page.locator(q("signup-password")).fill("longenough")
    page.locator(q("signup-display-name")).fill("Dup")
    page.locator(q("signup-submit")).click()
    t.ok(wait(page, lambda: visible(page, "auth-error") and text(page, "auth-error")), "signup with a registered email: auth-error not shown")
    cx.shot(page, "signup-error")
    page.locator(q("signup-email")).fill("Nina.Ricci@example.com")
    page.locator(q("signup-password")).fill("short")
    page.locator(q("signup-submit")).click()
    t.ok(wait(page, lambda: visible(page, "auth-error")), "signup with a 5-character password: auth-error not shown")
    t.ok(not visible(page, "current-user"), "signed in despite a refused signup")
    page.locator(q("signup-password")).fill("longenough")
    page.locator(q("signup-display-name")).fill("Nina Ricci")
    page.locator(q("signup-submit")).click()
    t.ok(wait(page, lambda: visible(page, "current-user")), "signup success: current-user did not appear")
    t.ok("Nina Ricci" in (text(page, "current-user") or ""), f"current-user text lacks the display name: {text(page, 'current-user')!r}")
    t.eq(text(page, "current-handle"), "nina_ricci", "current-handle after signup")
    t.eq(count(page, "auth-error"), 0, "auth-error after a successful signup")
    settle(page)
    for r in ROUTES:
        page.goto(cx.base + r)
        settle(page, 300)
        t.ok(visible(page, "current-user") and "Nina Ricci" in (text(page, "current-user") or ""), f"{r}: current-user missing or without the display name")
        t.eq(text(page, "current-handle"), "nina_ricci", f"{r}: current-handle")
        t.ok(visible(page, "logout-button"), f"{r}: logout-button not visible")
        t.ok(no_hscroll(page), f"{r}: horizontal page scroll at {cx.vp[1]} px")
        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => new URL(e.href).pathname)")
        for other in ROUTES:
            t.probe(other in hrefs, f"{r}: no link to {other} found among anchors (navigation consistency; check screenshots)")
    t.ok(wait(page, lambda: count(page, "empty-authorizations") > 0 or count(page, "authorization-list") > 0), "/authorizations screen did not render")
    page.goto(cx.base + "/")
    settle(page)
    t.eq(text(page, "wallet-balance"), "0.00 EUR", "new user's wallet-balance")
    t.ok(visible(page, "empty-activity") or count(page, "activity-list") > 0, "feed area missing for a new user")
    page.locator(q("logout-button")).click()
    t.ok(wait(page, lambda: not visible(page, "current-user")), "logout: current-user still visible")
    page.goto(cx.base + "/")
    settle(page)
    t.ok(not visible(page, "current-user"), "signed out but current-user visible on /")
    t.probe(not visible(page, "wallet-balance"), "signed out but wallet-balance visible on /")
    t.probe(visible(page, "login-email"), "signed-out visit to / does not show the login form")
    page.goto(cx.base + "/login")
    for tid in ("login-email", "login-password", "login-submit"):
        t.ok(visible(page, tid), f"/login lacks visible {tid}")
    t.eq(count(page, "auth-error"), 0, "auth-error on a fresh /login")
    cx.shot(page, "login-empty")
    page.locator(q("login-email")).fill("ada@example.com")
    page.locator(q("login-password")).fill("wrong horse")
    page.locator(q("login-submit")).click()
    t.ok(wait(page, lambda: visible(page, "auth-error") and text(page, "auth-error")), "wrong password: auth-error not shown")
    t.ok(not visible(page, "current-user"), "signed in with a wrong password")
    cx.shot(page, "login-error")
    page.locator(q("login-password")).fill(PW)
    page.locator(q("login-submit")).click()
    t.ok(wait(page, lambda: visible(page, "current-user")), "login success: current-user did not appear")
    t.ok("Ada" in (text(page, "current-user") or ""), "current-user lacks the display name after login")
    t.eq(text(page, "current-handle"), "ada", "current-handle after login")
    t.eq(count(page, "auth-error"), 0, "auth-error after a successful login")


# --------------------------------------------------------------------------- N wallet
@ui("N1-format", "stage-2 Balance and pay (formatted amount); UI table for holds", "N1,N2,N3,N4,U4", "wallet-balance / wallet-available text is exactly the formatted amount with data-amount, for EUR, JPY and BHD; wallet-held absent when zero and shown with a seeded hold; available is the headline number")
def u_format(t, cx):
    S = cx.S
    for cur, mu, bal, shown in (("EUR", 2, 10000, "100.00 EUR"), ("JPY", 0, 1200, "1200 JPY"), ("BHD", 3, 1500, "1.500 BHD"), ("EUR", 2, 123456789, "1234567.89 EUR"), ("EUR", 2, 5, "0.05 EUR")):
        fx = basefx(currency=cur, minor_units=mu, payments=[], requests=[])
        fx["users"][0]["balance"] = bal
        S.reset(fx)
        page = cx.page()
        login(t, cx, page, "ada")
        t.ok(wait(page, lambda: text(page, "wallet-balance") == shown), f"{cur}/{mu} wallet-balance: expected {shown!r}, got {text(page, 'wallet-balance')!r}")
        t.eq(attr(page, "wallet-balance", "data-amount"), str(bal), f"{cur} wallet-balance data-amount")
        t.eq(text(page, "wallet-available"), shown, f"{cur} wallet-available")
        t.eq(attr(page, "wallet-available", "data-amount"), str(bal), f"{cur} wallet-available data-amount")
        t.eq(count(page, "wallet-held"), 0, f"{cur} wallet-held with no holds")
        t.ok(no_hscroll(page), f"/ ({cur}): horizontal page scroll at {cx.vp[1]} px")
    S.reset(authfx())
    page = cx.page()
    login(t, cx, page, "ada")
    t.ok(wait(page, lambda: text(page, "wallet-available") == "80.00 EUR"), f"wallet-available right after reset with a seeded hold: {text(page, 'wallet-available')!r}")
    t.eq(attr(page, "wallet-available", "data-amount"), "8000", "wallet-available data-amount")
    t.eq(text(page, "wallet-balance"), "100.00 EUR", "wallet-balance (total) with a hold")
    t.eq(attr(page, "wallet-balance", "data-amount"), "10000", "wallet-balance data-amount")
    t.ok(visible(page, "wallet-held"), "wallet-held not visible with a seeded hold")
    t.eq(text(page, "wallet-held"), "20.00 EUR", "wallet-held")
    t.eq(attr(page, "wallet-held", "data-amount"), "2000", "wallet-held data-amount")
    sizes = page.evaluate("""() => Object.fromEntries(['wallet-available','wallet-balance','wallet-held'].map(id => {
        const e = document.querySelector(`[data-testid="${id}"]`); const s = getComputedStyle(e);
        return [id, [parseFloat(s.fontSize), parseInt(s.fontWeight)]]; }))""")
    t.ok(sizes["wallet-available"][0] > sizes["wallet-balance"][0] and sizes["wallet-available"][0] > sizes["wallet-held"][0],
         f"available is not the headline number: font sizes {sizes}")
    cx.shot(page, "wallet-with-hold")


@ui("N5-pay", "stage-2 Balance and pay; Activity feed", "N5,N7,N8,N10,N11", "Pay form works; values kept after success; an unchanged resubmission sends no second payment; a changed field makes a new payment; feed item shows parties, formatted amount, exact note and visibility; pay-error on refusals only")
def u_pay(t, cx):
    S = cx.S
    S.reset(basefx(payments=[], requests=[]))
    page = cx.page()
    login(t, cx, page, "ada")
    for tid in ("pay-handle", "pay-amount", "pay-note", "pay-visibility", "pay-submit", "wallet-refresh", "request-handle", "request-amount", "request-note", "request-submit"):
        t.ok(visible(page, tid), f"/ lacks visible {tid}")
    t.eq(sorted(page.eval_on_selector_all(q("pay-visibility") + " option", "els => els.map(e => e.value)")), ["private", "public"], "pay-visibility option values")
    t.ok(visible(page, "empty-activity"), "empty-activity not shown with nothing visible")
    t.eq(count(page, "pay-error"), 0, "pay-error before any submission")
    cx.shot(page, "wallet-empty")
    sent = posts(page, r"^/payments$")
    note = '<b>café</b> & "tea" \U0001F375  x'
    fill_pay(page, "bob", "15.00", note, "private")
    page.locator(q("pay-submit")).click()
    t.ok(wait_amount(page, "wallet-balance", 8500), f"balance after paying 15.00: {attr(page, 'wallet-balance', 'data-amount')}")
    t.eq(text(page, "wallet-balance"), "85.00 EUR", "wallet-balance text after payment")
    t.eq(attr(page, "wallet-available", "data-amount"), "8500", "wallet-available after payment")
    mine = S.acts("ada")
    t.eq(len(mine), 1, "payments recorded after the first submit")
    pid = mine[0]["payment_id"] if mine else "x"
    t.eq((mine[0].get("amount"), mine[0].get("note"), mine[0].get("visibility"), mine[0].get("to_handle")) if mine else None, (1500, note, "private", "bob"), "payment as recorded by the API")
    t.ok(wait(page, lambda: count(page, f"activity-item-{pid}") == 1), "new payment not in the feed without reload")
    t.eq(attr(page, f"activity-item-{pid}", "data-visibility"), "private", "activity item data-visibility")
    parties = text(page, f"activity-parties-{pid}") or ""
    t.ok("ada" in parties and "bob" in parties, f"activity-parties lacks both handles: {parties!r}")
    t.eq(text(page, f"activity-amount-{pid}"), "15.00 EUR", "activity-amount text")
    t.eq(page.locator(q(f"activity-note-{pid}")).first.text_content(), note, "activity-note text (verbatim)")
    t.ok(not visible(page, "empty-activity"), "empty-activity while the feed has items")
    t.eq((page.locator(q("pay-handle")).input_value(), page.locator(q("pay-amount")).input_value(), page.locator(q("pay-note")).input_value(),
          page.locator(q("pay-visibility")).input_value()), ("bob", "15.00", note, "private"), "pay form values kept after success")
    t.eq(count(page, "pay-error"), 0, "pay-error after a successful payment")
    cx.shot(page, "wallet-after-pay")
    page.locator(q("pay-submit")).click()
    settle(page, 900)
    t.eq(attr(page, "wallet-balance", "data-amount"), "8500", "balance after resubmitting the unchanged form (must fall once)")
    t.eq(len(S.acts("ada")), 1, "payments recorded after resubmitting the unchanged form")
    t.eq(page.locator(f'[data-testid^="activity-item-"]').count(), 1, "feed items after resubmitting the unchanged form")
    t.eq(count(page, "pay-error"), 0, "pay-error after resubmitting the unchanged form")
    t.ok(len(sent) >= 1 and len({s[0] for s in sent}) == 1, f"resubmission must reuse the same Idempotency-Key (keys seen: {len({s[0] for s in sent})})")
    page.locator(q("pay-note")).fill("")
    page.locator(q("pay-submit")).click()
    t.ok(wait_amount(page, "wallet-balance", 7000), "changing a field must make the next submission a new payment")
    t.eq(len({s[0] for s in sent}), 2, "a changed form must use a new Idempotency-Key")
    two = S.acts("ada")
    empty = [p for p in two if p.get("note") == ""]
    if t.ok(len(two) == 2 and len(empty) == 1, f"two payments, one with an empty note: {[(p.get('amount'), p.get('note')) for p in two]}"):
        t.eq(count(page, f"activity-note-{empty[0]['payment_id']}"), 1, "activity-note element present for an empty note")
        t.eq(page.locator(q(f"activity-note-{empty[0]['payment_id']}")).first.text_content().strip(), "", "activity-note text for an empty note")
    page.locator(q("pay-amount")).fill("15.5")
    page.locator(q("pay-visibility")).select_option("public")
    page.locator(q("pay-submit")).click()
    t.ok(wait_amount(page, "wallet-balance", 5450), "15.5 must submit 1550")
    page.locator(q("pay-amount")).fill("15")
    page.locator(q("pay-submit")).click()
    t.ok(wait_amount(page, "wallet-balance", 3950), "15 must submit 1500")
    newest = S.acts("ada")
    t.eq(sorted(p["amount"] for p in newest), [1500, 1500, 1500, 1550], "amounts recorded by the API")
    # refusals
    for handle, amount, why in (("bob", "1000.00", "insufficient funds"), ("nobody_here", "1.00", "unknown handle"), ("ada", "1.00", "self payment")):
        fill_pay(page, handle, amount)
        page.locator(q("pay-submit")).click()
        t.ok(wait(page, lambda: visible(page, "pay-error") and text(page, "pay-error")), f"pay-error not shown for {why}")
        t.eq(page.locator(q("pay-handle")).input_value(), handle, f"pay-handle preserved after refusal ({why})")
        t.ok(not visible(page, "pay-uncertain"), f"pay-uncertain shown for a confirmed refusal ({why})")
    cx.shot(page, "wallet-pay-error")
    t.eq(len(S.acts("ada")), 4, "refused payments recorded nothing")
    fill_pay(page, "bob", "1.00")
    page.locator(q("pay-submit")).click()
    t.ok(wait_amount(page, "wallet-balance", 3850), "payment after refusals")
    t.eq(count(page, "pay-error"), 0, "pay-error still shown after a later success")
    t.ok(no_hscroll(page), f"/: horizontal page scroll at {cx.vp[1]} px")


@ui("N6-decimals", "stage-2 Balance and pay (decimal input)", "N6", "Decimal input: exact conversion to minor units without float error; nonnumeric input or more than minor_units decimals shows the form's error element and sends no request; holds for 0, 2 and 3 minor units")
def u_decimals(t, cx):
    S = cx.S
    for cur, mu, good, bad in (("EUR", 2, [("0.29", 29), ("1.15", 115), ("4.35", 435), ("0.57", 57), ("8.2", 820), ("0.01", 1)], ["15.005", "abc", "1.2.3", "12,50x", "0.001"]),
                               ("JPY", 0, [("1200", 1200), ("7", 7)], ["15.5", "1.0", "abc"]),
                               ("BHD", 3, [("1.500", 1500), ("0.001", 1), ("2.05", 2050)], ["1.5005", "abc"])):
        fx = basefx(currency=cur, minor_units=mu, payments=[], requests=[])
        fx["users"][0]["balance"] = 1000000
        S.reset(fx)
        page = cx.page()
        login(t, cx, page, "ada")
        sent = posts(page, r"^/payments$")
        spent = 0
        for i, (txt, minor) in enumerate(good):
            fill_pay(page, "bob", txt, f"n{i}")
            page.locator(q("pay-submit")).click()
            spent += minor
            t.ok(wait_amount(page, "wallet-balance", 1000000 - spent), f"{cur}: '{txt}' must submit {minor} minor units (balance {attr(page, 'wallet-balance', 'data-amount')}, expected {1000000 - spent})")
            spent = 1000000 - int(attr(page, "wallet-balance", "data-amount") or 0)
        n = len(sent)
        for txt in bad:
            fill_pay(page, "bob", txt, "bad " + txt)
            page.locator(q("pay-submit")).click()
            t.ok(wait(page, lambda: visible(page, "pay-error")), f"{cur}: '{txt}' must show pay-error")
            page.wait_for_timeout(300)
            t.eq(len(sent), n, f"{cur}: '{txt}' must not send a request")
        t.eq(S.bal("ada"), 1000000 - spent, f"{cur}: balance unchanged by rejected inputs")
        if cur == "EUR":
            rs = posts(page, r"^/requests$")
            page.locator(q("request-handle")).fill("bob")
            page.locator(q("request-amount")).fill("15.005")
            page.locator(q("request-submit")).click()
            t.ok(wait(page, lambda: visible(page, "request-error")), "request-amount 15.005 must show request-error")
            page.wait_for_timeout(300)
            t.eq(len(rs), 0, "request-amount 15.005 must not send a request")


@ui("N9-request-form", "stage-2 Balance and pay (request form)", "N9,N11", "Request form creates a request with the typed amount and note; request-error when refused")
def u_reqform(t, cx):
    S = cx.S
    S.reset(basefx(payments=[], requests=[]))
    page = cx.page()
    login(t, cx, page, "bob")
    t.ok(not visible(page, "request-error"), "request-error before any submission")
    page.locator(q("request-handle")).fill("ada")
    page.locator(q("request-amount")).fill("12.34")
    page.locator(q("request-note")).fill("taxi \U0001F695")
    page.locator(q("request-submit")).click()
    t.ok(wait(page, lambda: len(S.reqs("ada")) == 1), "request not created")
    rq = (S.reqs("ada") or [{}])[0]
    t.eq((rq.get("amount"), rq.get("note"), rq.get("requester_handle"), rq.get("payer_handle")), (1234, "taxi \U0001F695", "bob", "ada"), "request as recorded by the API")
    t.ok(not visible(page, "request-error"), "request-error after a successful request")
    for handle, why in (("bob", "self request"), ("nobody_here", "unknown handle")):
        page.locator(q("request-handle")).fill(handle)
        page.locator(q("request-amount")).fill("1.00")
        page.locator(q("request-submit")).click()
        t.ok(wait(page, lambda: visible(page, "request-error") and text(page, "request-error")), f"request-error not shown for {why}")
    t.eq(len(S.reqs("bob")), 1, "refused requests created nothing")
    page.goto(cx.base + "/requests")
    t.ok(wait(page, lambda: count(page, f"request-item-{rq.get('request_id')}") == 1), "the new request is not listed on /requests")


@ui("N10-feed", "stage-2 Activity feed", "N10,Q1", "activity-list children are newest first; one item per visible payment and none for hidden ones; long notes do not cause horizontal scroll")
def u_feed(t, cx):
    S = cx.S
    S.reset(basefx(payments=[], requests=[]))
    made = []
    long_note = "W" * 200
    for frm, to, vis, note in (("ada", "bob", "public", "first"), ("bob", "cy", "private", "hidden from ada"), ("cy", "ada", "private", long_note), ("dan", "bob", "public", "last one with spaces " * 9)):
        if frm == "cy":
            S.call("POST", "/payments", {"to_handle": "cy", "amount": 50}, as_="dan", key=k())
            time.sleep(1.1)
        r = S.call("POST", "/payments", {"to_handle": to, "amount": 7, "visibility": vis, "note": note[:200]}, as_=frm, key=k())
        made.append((r.j or {}).get("payment_id"))
        time.sleep(1.1)
    page = cx.page()
    login(t, cx, page, "ada")
    api = [p["payment_id"] for p in S.acts("ada")]
    t.ok(wait(page, lambda: len(child_ids(page, "activity-list", "activity-item-")) == len(api)), f"feed item count: expected {len(api)}, got {len(child_ids(page, 'activity-list', 'activity-item-'))}")
    t.eq(child_ids(page, "activity-list", "activity-item-"), api, "DOM order of activity items (newest first, as GET /activity)")
    t.eq(count(page, f"activity-item-{made[1]}"), 0, "a private payment between two other users is shown")
    t.eq(attr(page, f"activity-item-{made[2]}", "data-visibility"), "private", "data-visibility of a private payment received")
    t.eq(attr(page, f"activity-item-{made[0]}", "data-visibility"), "public", "data-visibility of a public payment")
    t.eq(page.locator(q(f"activity-note-{made[2]}")).first.text_content(), long_note, "200-character note shown in full")
    t.ok(no_hscroll(page), f"/ with a 200-character unbroken note: horizontal page scroll at {cx.vp[1]} px")
    cx.shot(page, "wallet-feed")


@ui("N12-refresh", "stage-2 Competing clients and uncertain outcomes", "N12,N13,N14,U4", "wallet-refresh updates balance, available, held and feed without clearing the pay form; latest refresh wins when responses arrive out of order; a payment refused because another client spent the money shows pay-error, refreshes the numbers and keeps the inputs")
def u_refresh(t, cx):
    S = cx.S
    S.reset(basefx(payments=[], requests=[]))
    page = cx.page()
    login(t, cx, page, "ada")
    fill_pay(page, "bob", "50.00", "keep me", "private")
    S.call("POST", "/payments", {"to_handle": "ada", "amount": 100, "note": "from bob"}, as_="bob", key=k())
    S.call("POST", "/authorizations", {"to_handle": "cy", "amount": 300}, as_="ada", key=k())
    page.wait_for_timeout(500)
    page.locator(q("wallet-refresh")).click()
    t.ok(wait_amount(page, "wallet-balance", 10100), "wallet-refresh did not update the balance")
    t.ok(wait_amount(page, "wallet-available", 9800), "wallet-refresh did not update available")
    t.ok(wait(page, lambda: attr(page, "wallet-held", "data-amount") == "300" and text(page, "wallet-held") == "3.00 EUR"), "wallet-refresh did not show the new hold")
    t.ok(wait(page, lambda: page.locator('[data-testid^="activity-item-"]').count() == 1), "wallet-refresh did not update the feed")
    t.eq((page.locator(q("pay-handle")).input_value(), page.locator(q("pay-amount")).input_value(), page.locator(q("pay-note")).input_value(),
          page.locator(q("pay-visibility")).input_value()), ("bob", "50.00", "keep me", "private"), "pay form cleared by wallet-refresh")
    # latest refresh wins
    held, mode = [], {"hold": True}

    def h(route):
        rq = route.request
        if rq.method == "GET" and mode["hold"] and rq.resource_type in ("fetch", "xhr"):
            try:
                held.append((route, route.fetch()))
            except Exception:
                pass
            return
        route.continue_()
    page.route("**/*", h)
    page.locator(q("wallet-refresh")).click()
    got = wait(page, lambda: len(held) >= 1, 3000)
    page.wait_for_timeout(400)
    mode["hold"] = False
    S.call("POST", "/payments", {"to_handle": "ada", "amount": 23, "note": "later"}, as_="bob", key=k())
    if not got:
        t.note("wallet-refresh issues no fetch/XHR GET (full navigation?); out-of-order responses could not be simulated")
    try:
        page.locator(q("wallet-refresh")).click(timeout=2500)
        second = True
    except Exception:
        second = False
        t.note("wallet-refresh could not be clicked while the first refresh was pending (button blocked); reordering impossible by construction")
    if second:
        t.ok(wait_amount(page, "wallet-balance", 10123), "second refresh did not show the newer balance while the first was still pending")
    for route, resp in held:
        try:
            route.fulfill(response=resp)
        except Exception:
            pass
    page.wait_for_timeout(900)
    if not second:
        page.locator(q("wallet-refresh")).click()
        wait_amount(page, "wallet-balance", 10123)
    t.eq(attr(page, "wallet-balance", "data-amount"), "10123", "a delayed earlier read overwrote the later refresh (balance)")
    t.eq(attr(page, "wallet-available", "data-amount"), "9823", "a delayed earlier read overwrote the later refresh (available)")
    t.eq(page.locator('[data-testid^="activity-item-"]').count(), 2, "a delayed earlier read overwrote the later refresh (feed)")
    page.unroute("**/*", h)
    # another client spends the money
    S.call("POST", "/payments", {"to_handle": "dan", "amount": 9800}, as_="ada", key=k())
    page.locator(q("pay-submit")).click()
    t.ok(wait(page, lambda: visible(page, "pay-error") and text(page, "pay-error")), "payment refused after another client spent the balance: pay-error not shown")
    t.ok(wait_amount(page, "wallet-balance", 323), f"balance not refreshed after the refusal: {attr(page, 'wallet-balance', 'data-amount')}")
    t.eq(attr(page, "wallet-available", "data-amount"), "23", "available not refreshed after the refusal")
    t.eq(page.locator('[data-testid^="activity-item-"]').count(), 3, "feed not refreshed after the refusal")
    t.eq((page.locator(q("pay-handle")).input_value(), page.locator(q("pay-amount")).input_value(), page.locator(q("pay-note")).input_value(),
          page.locator(q("pay-visibility")).input_value()), ("bob", "50.00", "keep me", "private"), "pay inputs not preserved after the refusal")
    t.ok(not visible(page, "pay-uncertain"), "pay-uncertain shown for a confirmed refusal")
    cx.shot(page, "wallet-refused")


def lose_first_post(page, path_re, commit, log):
    state = {"n": 0}
    rx = re.compile(path_re)

    def h(route):
        rq = route.request
        if rq.method != "POST" or not rx.search(urllib.parse.urlparse(rq.url).path):
            return route.continue_()
        state["n"] += 1
        log.append((rq.headers.get("idempotency-key"), rq.post_data))
        if state["n"] == 1:
            if commit:
                try:
                    route.fetch()
                except Exception:
                    pass
            return route.abort("connectionreset")
        route.continue_()
    page.route("**/*", h)
    return h


@ui("N15-lost-response", "stage-2 Competing clients and uncertain outcomes", "N15", "A lost POST /payments response (before or after commit) shows pay-uncertain with text, not pay-error; the unchanged form retries with the same key and body; a successful retry clears both elements, refreshes balance and feed, and money moves exactly once")
def u_lost(t, cx):
    S = cx.S
    for commit in (True, False):
        label = "lost after commit" if commit else "lost before reaching the server"
        S.reset(basefx(payments=[], requests=[]))
        page = cx.page()
        login(t, cx, page, "ada")
        log = []
        lose_first_post(page, r"^/payments$", commit, log)
        fill_pay(page, "bob", "25.00", "rent")
        page.locator(q("pay-submit")).click()
        t.ok(wait(page, lambda: visible(page, "pay-uncertain") and text(page, "pay-uncertain")), f"{label}: pay-uncertain with text not shown")
        t.eq(count(page, "pay-error"), 0, f"{label}: pay-error shown for an unknown outcome")
        t.eq(len(S.acts("ada")), 1 if commit else 0, f"{label}: payments on the server before the retry")
        t.eq((page.locator(q("pay-handle")).input_value(), page.locator(q("pay-amount")).input_value(), page.locator(q("pay-note")).input_value()), ("bob", "25.00", "rent"), f"{label}: form values kept")
        cx.shot(page, "wallet-uncertain")
        page.locator(q("pay-submit")).click()
        t.ok(wait(page, lambda: not visible(page, "pay-uncertain") and attr(page, "wallet-balance", "data-amount") == "7500"), f"{label}: retry did not clear pay-uncertain and refresh the balance (balance {attr(page, 'wallet-balance', 'data-amount')})")
        t.eq(count(page, "pay-error"), 0, f"{label}: pay-error after a successful retry")
        t.eq(len(S.acts("ada")), 1, f"{label}: money must move exactly once")
        t.eq(S.bal("ada"), 7500, f"{label}: balance on the server")
        t.eq(page.locator('[data-testid^="activity-item-"]').count(), 1, f"{label}: feed after the retry")
        t.ok(len(log) >= 2 and log[0][0] and log[0] == log[1], f"{label}: retry must send the same key and body: {log[:2]}")


# --------------------------------------------------------------------------- O requests screen
def reqfx():
    fx = basefx(payments=[])
    fx["requests"] = [
        {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
        {"id": "rq_2", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 300, "note": "tea", "status": "pending"},
        {"id": "rq_big", "requester_id": "u_cy", "payer_id": "u_ada", "amount": 5000000, "note": "too much", "status": "pending"},
        {"id": "rq_x", "requester_id": "u_cy", "payer_id": "u_ada", "amount": 77, "note": "race", "status": "pending"},
        {"id": "rq_o", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 450, "note": "mine", "status": "pending"},
        {"id": "rq_d", "requester_id": "u_dan", "payer_id": "u_ada", "amount": 70, "note": "d", "status": "declined"},
        {"id": "rq_c", "requester_id": "u_ada", "payer_id": "u_dan", "amount": 80, "note": "c", "status": "cancelled"}]
    return fx


@ui("O1-requests", "stage-2 Requests screen; Competing clients", "O1,O2,O3,O4,N11,R3", "Incoming and outgoing lists; items carry data-status and the formatted amount; pay/decline only on pending incoming, cancel only on pending outgoing; each works and the list updates; request-error on refusal; a request cancelled elsewhere shows request-error and loses its stale pay button; empty-requests when both lists are empty")
def u_requests(t, cx):
    S = cx.S
    S.reset(reqfx())
    page = cx.page()
    login(t, cx, page, "ada", path="/requests")
    t.ok(wait(page, lambda: count(page, "request-item-rq_1") == 1), "/requests did not list rq_1")
    t.ok(count(page, "incoming-list") == 1 and count(page, "outgoing-list") == 1, "incoming-list / outgoing-list containers missing")
    inc = sorted(child_ids(page, "incoming-list", "request-item-"))
    out = sorted(child_ids(page, "outgoing-list", "request-item-"))
    t.eq(inc, ["rq_1", "rq_2", "rq_big", "rq_d", "rq_x"], "incoming-list items")
    t.eq(out, ["rq_c", "rq_o"], "outgoing-list items")
    for rid, st, amt in (("rq_1", "pending", "12.00 EUR"), ("rq_big", "pending", "50000.00 EUR"), ("rq_o", "pending", "4.50 EUR"), ("rq_d", "declined", "0.70 EUR"), ("rq_c", "cancelled", "0.80 EUR")):
        t.eq(attr(page, f"request-item-{rid}", "data-status"), st, f"{rid} data-status")
        t.eq(text(page, f"request-amount-{rid}"), amt, f"{rid} formatted amount")
    for rid, pay, dec, can in (("rq_1", 1, 1, 0), ("rq_o", 0, 0, 1), ("rq_d", 0, 0, 0), ("rq_c", 0, 0, 0)):
        t.eq((count(page, f"request-pay-{rid}"), count(page, f"request-decline-{rid}"), count(page, f"request-cancel-{rid}")), (pay, dec, can), f"{rid} buttons (pay, decline, cancel)")
    t.ok(not visible(page, "request-error"), "request-error before any action")
    t.ok(not visible(page, "empty-requests"), "empty-requests while lists have items")
    t.ok(no_hscroll(page), f"/requests: horizontal page scroll at {cx.vp[1]} px")
    cx.shot(page, "requests")
    page.locator(q("request-pay-rq_1")).click()
    t.ok(wait(page, lambda: attr(page, "request-item-rq_1", "data-status") == "paid"), "pay rq_1: item did not become paid without reload")
    t.eq((count(page, "request-pay-rq_1"), count(page, "request-decline-rq_1")), (0, 0), "buttons remain on a paid request")
    t.eq(S.bal("ada"), 8800, "balance after paying rq_1 through the screen")
    page.locator(q("request-decline-rq_2")).click()
    t.ok(wait(page, lambda: attr(page, "request-item-rq_2", "data-status") == "declined"), "decline rq_2: item did not become declined")
    page.locator(q("request-cancel-rq_o")).click()
    t.ok(wait(page, lambda: attr(page, "request-item-rq_o", "data-status") == "cancelled"), "cancel rq_o: item did not become cancelled")
    t.eq(count(page, "request-cancel-rq_o"), 0, "cancel button remains on a cancelled request")
    t.ok(not visible(page, "request-error"), "request-error after successful actions")
    page.locator(q("request-pay-rq_big")).click()
    t.ok(wait(page, lambda: visible(page, "request-error") and text(page, "request-error")), "pay with insufficient funds: request-error not shown")
    t.eq(attr(page, "request-item-rq_big", "data-status"), "pending", "rq_big must stay pending after insufficient funds")
    cx.shot(page, "requests-error")
    S.call("POST", "/requests/rq_x/cancel", as_="cy")
    page.locator(q("request-pay-rq_x")).click()
    t.ok(wait(page, lambda: visible(page, "request-error")), "pay a request cancelled elsewhere: request-error not shown")
    t.ok(wait(page, lambda: count(page, "request-pay-rq_x") == 0), "stale pay button did not disappear after the refused pay")
    t.eq(attr(page, "request-item-rq_x", "data-status"), "cancelled", "rq_x data-status after the list refresh")
    t.eq(S.bal("ada"), 8800, "nothing moved by refused pays")
    p2 = cx.page()
    login(t, cx, p2, "op", path="/requests")
    t.ok(wait(p2, lambda: visible(p2, "empty-requests")), "empty-requests not shown for a user without requests")
    cx.shot(p2, "requests-empty")


# --------------------------------------------------------------------------- P split
@ui("P1-split", "stage-2 Split; stage-1 §9", "P1,P2,P3", "Split form; split-preview shows one split-share-{handle} per participant with the formatted share before anything is posted; preview and submitted split are identical; split-error when refused")
def u_split(t, cx):
    S = cx.S
    S.reset(basefx(payments=[], requests=[]))
    page = cx.page()
    login(t, cx, page, "ada", path="/split")
    for tid in ("split-amount", "split-handles", "split-note", "split-submit"):
        t.ok(visible(page, tid), f"/split lacks visible {tid}")
    sent = posts(page, r"^/splits$")
    cx.shot(page, "split-empty")

    def preview(amount, handles, exp):
        page.locator(q("split-amount")).fill(amount)
        page.locator(q("split-handles")).fill(handles)
        ok = wait(page, lambda: all(text(page, f"split-share-{h}") == v for h, v in exp.items()), 3000)
        got = {h: text(page, f"split-share-{h}") for h in exp}
        t.ok(ok, f"preview of {amount} among '{handles}': expected {exp}, got {got}")
        t.eq(page.locator(q("split-preview") + ' [data-testid^="split-share-"]').count(), len(exp), f"split-share count for '{handles}'")
    preview("10.00", "ada,bob,cy", {"ada": "3.34 EUR", "bob": "3.33 EUR", "cy": "3.33 EUR"})
    preview("10.00", "cy,bob,ada", {"cy": "3.34 EUR", "bob": "3.33 EUR", "ada": "3.33 EUR"})
    preview("0.01", "ada,bob,cy", {"ada": "0.01 EUR", "bob": "0.00 EUR", "cy": "0.00 EUR"})
    preview("0.10", "bob,cy,dan", {"bob": "0.04 EUR", "cy": "0.03 EUR", "dan": "0.03 EUR"})
    preview("9.99", "ada,bob,cy", {"ada": "3.33 EUR", "bob": "3.33 EUR", "cy": "3.33 EUR"})
    preview("10", "bob,cy", {"bob": "5.00 EUR", "cy": "5.00 EUR"})
    t.eq(len(sent), 0, "something was posted while only previewing")
    t.ok(not visible(page, "split-error"), "split-error while previewing valid input")
    preview("10.00", "bob,ada,cy", {"bob": "3.34 EUR", "ada": "3.33 EUR", "cy": "3.33 EUR"})
    cx.shot(page, "split-preview")
    page.locator(q("split-note")).fill("dinner")
    page.locator(q("split-submit")).click()
    t.ok(wait(page, lambda: len(S.reqs("ada")) == 2), "split not created")
    got = sorted((r["payer_handle"], r["amount"], r["note"]) for r in S.reqs("ada"))
    t.eq(got, [("bob", 334, "dinner"), ("cy", 333, "dinner")], "submitted split requests equal the preview")
    t.ok(not visible(page, "split-error"), "split-error after a successful split")
    settle(page)
    cx.shot(page, "split-done")
    n = len(sent)
    for amount, handles, why, local in (("10.00", "bob,nobody_here", "unknown handle", False), ("10.00", "bob,bob", "duplicate handle", False), ("10.005", "bob,cy", "too many decimals", True), ("abc", "bob,cy", "nonnumeric amount", True), ("10.00", "", "no handles", False)):
        page.locator(q("split-amount")).fill(amount)
        page.locator(q("split-handles")).fill(handles)
        page.locator(q("split-note")).fill(why)
        before = len(sent)
        page.locator(q("split-submit")).click()
        t.ok(wait(page, lambda: visible(page, "split-error") and text(page, "split-error")), f"split-error not shown for {why}")
        page.wait_for_timeout(300)
        if local:
            t.eq(len(sent), before, f"{why}: a request was sent")
    t.eq(len(S.reqs("ada")), 2, "refused splits created nothing")
    page.locator(q("split-amount")).fill("3.00")
    page.locator(q("split-handles")).fill("bob, cy , dan")
    ok = wait(page, lambda: text(page, "split-share-cy") == "1.00 EUR", 2000)
    t.probe(ok, "handles typed with spaces around commas ('bob, cy , dan') are not previewed")
    t.ok(no_hscroll(page), f"/split: horizontal page scroll at {cx.vp[1]} px")


# --------------------------------------------------------------------------- U authorizations UI
def find_authorize(t, cx, page):
    for path in ("/", "/authorizations"):
        page.goto(cx.base + path)
        if wait(page, lambda: count(page, "authorize-submit") > 0, 2500):
            return path
    t.ok(False, "authorize form (authorize-submit) not found on / or /authorizations")
    return None


@ui("U1-authorize-form", "stage-2 UI table (authorise form, wallet numbers)", "U1,U4,N6", "Authorize form with the pay form's input rules creates a hold; available falls and held appears; authorize-error on refusal including insufficient available funds and bad decimals (no request sent)")
def u_authorize(t, cx):
    S = cx.S
    S.reset(basefx(payments=[], requests=[]))
    page = cx.page()
    login(t, cx, page, "ada")
    where = find_authorize(t, cx, page)
    if not where:
        return
    for tid in ("authorize-handle", "authorize-amount", "authorize-note", "authorize-visibility", "authorize-submit"):
        t.ok(visible(page, tid), f"{where} lacks visible {tid}")
    t.eq(sorted(page.eval_on_selector_all(q("authorize-visibility") + " option", "els => els.map(e => e.value)")), ["private", "public"], "authorize-visibility option values")
    t.ok(not visible(page, "authorize-error"), "authorize-error before any submission")
    sent = posts(page, r"^/authorizations$")
    fill_pay(page, "bob", "20.5", "deposit", "private", prefix="authorize")
    page.locator(q("authorize-submit")).click()
    t.ok(wait(page, lambda: me3(S, "ada") == (10000, 7950, 2050)), f"hold not created with 2050 minor units: {me3(S, 'ada')}")
    a = (auths(S, "ada") or [{}])[0]
    t.eq((a.get("amount"), a.get("note"), a.get("visibility"), a.get("to_handle"), a.get("status")), (2050, "deposit", "private", "bob", "open"), "authorization as recorded by the API")
    t.ok(not visible(page, "authorize-error"), "authorize-error after success")
    if count(page, "wallet-available"):
        t.ok(wait_amount(page, "wallet-available", 7950), "wallet-available not refreshed after authorizing")
        t.ok(wait(page, lambda: text(page, "wallet-held") == "20.50 EUR"), f"wallet-held after authorizing: {text(page, 'wallet-held')!r}")
        t.eq(attr(page, "wallet-balance", "data-amount"), "10000", "wallet-balance (total) unchanged by a hold")
    if count(page, "authorization-list") or where == "/authorizations":
        t.ok(wait(page, lambda: count(page, f"authorization-item-{a.get('authorization_id')}") == 1), "new authorization not listed without reload")
    n = len(sent)
    for handle, amount, why, local in (("bob", "80.00", "insufficient available funds (79.50 available)", False), ("nobody_here", "1.00", "unknown handle", False),
                                       ("ada", "1.00", "self", False), ("bob", "15.005", "too many decimals", True), ("bob", "abc", "nonnumeric", True)):
        before = len(sent)
        fill_pay(page, handle, amount, why[:20], prefix="authorize")
        page.locator(q("authorize-submit")).click()
        t.ok(wait(page, lambda: visible(page, "authorize-error") and text(page, "authorize-error")), f"authorize-error not shown for {why}")
        page.wait_for_timeout(300)
        if local:
            t.eq(len(sent), before, f"authorize {why}: a request was sent")
    t.eq(me3(S, "ada"), (10000, 7950, 2050), "refused authorizations hold nothing")
    cx.shot(page, "authorize-error")
    page.goto(cx.base + "/")
    t.ok(wait(page, lambda: text(page, "wallet-available") == "79.50 EUR" and text(page, "wallet-held") == "20.50 EUR"), f"/ after authorizing: available {text(page, 'wallet-available')!r} held {text(page, 'wallet-held')!r}")
    fill_pay(page, "bob", "79.51")
    page.locator(q("pay-submit")).click()
    t.ok(wait(page, lambda: visible(page, "pay-error")), "paying more than available (held funds) must show pay-error")


@ui("U2-authorizations-screen", "stage-2 UI table (/authorizations)", "U2,U3,U4", "authorization-list newest first; items with data-status, formatted amount, RFC 3339 expires_at, captured amount only when captured; capture input (pre-filled with the remainder) and button only on incoming open, void only on outgoing open; capture and void work and refresh the list; authorization-error on refusal; empty-authorizations")
def u_auths(t, cx):
    S = cx.S
    fx = authfx(payments=[], requests=[])
    S.reset(fx)
    made = []
    for amt in (1100, 1200):
        r = S.call("POST", "/authorizations", {"to_handle": "bob", "amount": amt, "note": f"n{amt}"}, as_="ada", key=k())
        made.append((r.j or {}).get("authorization_id"))
        time.sleep(1.1)
    r = S.call("POST", "/authorizations", {"to_handle": "ada", "amount": 900}, as_="bob", key=k())
    inc = (r.j or {}).get("authorization_id")
    page = cx.page()
    login(t, cx, page, "ada", path="/authorizations")
    api = [a["authorization_id"] for a in auths(S, "ada")]
    t.ok(wait(page, lambda: len(child_ids(page, "authorization-list", "authorization-item-")) == len(api)), f"authorization item count: expected {len(api)}")
    t.eq(child_ids(page, "authorization-list", "authorization-item-"), api, "DOM order of authorizations (newest first, as GET /authorizations)")
    apimap = {a["authorization_id"]: a for a in auths(S, "ada")}
    for aid, st, amt in (("a_1", "open", "20.00 EUR"), ("a_3", "captured", "1.00 EUR"), ("a_4", "voided", "0.50 EUR"), ("a_5", "expired", "0.60 EUR"), (inc, "open", "9.00 EUR")):
        t.eq(attr(page, f"authorization-item-{aid}", "data-status"), st, f"{aid} data-status")
        t.eq(text(page, f"authorization-amount-{aid}"), amt, f"{aid} formatted amount")
        t.eq(text(page, f"authorization-expires-{aid}"), apimap[aid]["expires_at"], f"{aid} expires text (RFC 3339 expires_at)")
        t.eq(count(page, f"authorization-captured-{aid}"), 1 if st == "captured" else 0, f"{aid} authorization-captured presence")
    for aid, capn, voidn in (("a_1", 0, 1), (inc, 1, 0), ("a_3", 0, 0), ("a_4", 0, 0), ("a_5", 0, 0)):
        t.eq((count(page, f"authorization-capture-amount-{aid}"), count(page, f"authorization-capture-{aid}"), count(page, f"authorization-void-{aid}")), (capn, capn, voidn), f"{aid} controls (capture input, capture, void)")
    val = page.locator(q(f"authorization-capture-amount-{inc}")).input_value() if count(page, f"authorization-capture-amount-{inc}") else None
    t.ok(val in ("9.00", "9"), f"capture input must be pre-filled with the remaining amount 9.00, got {val!r}")
    t.ok(not visible(page, "authorization-error"), "authorization-error before any action")
    t.ok(not visible(page, "empty-authorizations"), "empty-authorizations while the list has items")
    t.ok(no_hscroll(page), f"/authorizations: horizontal page scroll at {cx.vp[1]} px")
    cx.shot(page, "authorizations")
    sent = posts(page, r"/capture$")
    page.locator(q(f"authorization-capture-amount-{inc}")).fill("9.005")
    page.locator(q(f"authorization-capture-{inc}")).click()
    t.ok(wait(page, lambda: visible(page, "authorization-error")), "capture amount 9.005 must show authorization-error")
    page.wait_for_timeout(300)
    t.eq(len(sent), 0, "capture amount 9.005 must not send a request")
    page.locator(q(f"authorization-capture-amount-{inc}")).fill("9.50")
    page.locator(q(f"authorization-capture-{inc}")).click()
    t.ok(wait(page, lambda: visible(page, "authorization-error") and text(page, "authorization-error")), "capture above the authorization: authorization-error not shown")
    t.eq((auth_by_id(S, "ada", inc) or {}).get("status"), "open", "refused capture must leave the authorization open")
    cx.shot(page, "authorizations-error")
    page.locator(q(f"authorization-capture-amount-{inc}")).fill("6.5")
    page.locator(q(f"authorization-capture-{inc}")).click()
    t.ok(wait(page, lambda: attr(page, f"authorization-item-{inc}", "data-status") == "captured"), "capture 6.5: item did not become captured without reload")
    t.eq(text(page, f"authorization-captured-{inc}"), "6.50 EUR", "authorization-captured text")
    t.eq((count(page, f"authorization-capture-{inc}"), count(page, f"authorization-capture-amount-{inc}")), (0, 0), "capture controls remain on a captured authorization")
    a = auth_by_id(S, "ada", inc) or {}
    t.eq((a.get("status"), a.get("captured_amount"), a.get("remaining_amount")), ("captured", 650, 0), "capture as recorded by the API (final capture)")
    t.eq(me3(S, "bob")[0], 2500 - 650, "payer's total after the UI capture")
    if count(page, "wallet-available"):
        t.ok(wait_amount(page, "wallet-available", S.me("ada")["available"]), "wallet-available not refreshed after capture")
    page.locator(q(f"authorization-void-{made[0]}")).click()
    t.ok(wait(page, lambda: attr(page, f"authorization-item-{made[0]}", "data-status") == "voided"), "void: item did not become voided without reload")
    t.eq(count(page, f"authorization-void-{made[0]}"), 0, "void button remains on a voided authorization")
    t.eq((auth_by_id(S, "ada", made[0]) or {}).get("status"), "voided", "void as recorded by the API")
    S.call("POST", f"/authorizations/{made[1]}/capture", {}, as_="bob", key=k())
    page.locator(q(f"authorization-void-{made[1]}")).click()
    t.ok(wait(page, lambda: visible(page, "authorization-error")), "void of an authorization captured elsewhere: authorization-error not shown")
    t.ok(wait(page, lambda: attr(page, f"authorization-item-{made[1]}", "data-status") == "captured" and count(page, f"authorization-void-{made[1]}") == 0), "list not refreshed after the refused void")
    p2 = cx.page()
    login(t, cx, p2, "op", path="/authorizations")
    t.ok(wait(p2, lambda: visible(p2, "empty-authorizations")), "empty-authorizations not shown for a user without authorizations")
    cx.shot(p2, "authorizations-empty")


# --------------------------------------------------------------------------- R upgrade through the browser
@ui("R2-upgrade-browser", "stage-2 Existing clients after an upgrade", "R2,R3,R4", "With import completing between browser requests: the browser stays signed in, a payment whose response was lost before the export is retried with the same key and body and recovers the original payment, the imported balance is shown, and pending requests stay payable on the request screen - without a page reload")
def u_upgrade(t, cx):
    S = cx.S
    S.reset(basefx(payments=[]))
    page = cx.page()
    login(t, cx, page, "ada")
    log = []
    lose_first_post(page, r"^/payments$", True, log)
    fill_pay(page, "bob", "25.00", "before upgrade")
    page.locator(q("pay-submit")).click()
    t.ok(wait(page, lambda: visible(page, "pay-uncertain")), "pay-uncertain not shown for the lost response")
    exp = S.call("GET", "/_test/export").j
    S.call("POST", "/payments", {"to_handle": "ada", "amount": 1}, as_="bob", key=k())
    S.reset(OTHERFX)
    r = S.call("POST", "/_test/import", exp)
    t.st(r, 204, "import between browser requests")
    S.tok = {}
    page.locator(q("pay-submit")).click()
    t.ok(wait(page, lambda: not visible(page, "pay-uncertain") and attr(page, "wallet-balance", "data-amount") == "7500"), f"retry after import did not recover the payment and show the imported balance (balance {attr(page, 'wallet-balance', 'data-amount')}, uncertain {count(page, 'pay-uncertain')})")
    t.eq(count(page, "pay-error"), 0, "pay-error after the recovered retry")
    t.ok(len(log) >= 2 and log[0][0] and log[0] == log[1], f"retry after import must send the same key and body: {log[:2]}")
    t.eq(len(S.acts("ada")), 1, "money must have moved exactly once across the upgrade")
    t.eq(page.locator('[data-testid^="activity-item-"]').count(), 1, "feed after the recovered retry")
    t.ok(visible(page, "current-user"), "browser no longer signed in after import")
    link = page.locator('a[href="/requests"]')
    if link.count():
        link.first.click()
    else:
        page.goto(cx.base + "/requests")
    t.ok(wait(page, lambda: count(page, "request-pay-rq_1") == 1), "pending request not offered on the request screen after import")
    t.ok(visible(page, "current-user"), "not signed in on /requests after import")
    page.locator(q("request-pay-rq_1")).click()
    t.ok(wait(page, lambda: attr(page, "request-item-rq_1", "data-status") == "paid"), "pending request not payable through the screen after import")
    t.eq(S.bal("ada"), 6300, "balance after paying the imported request")
    base1 = os.environ.get("S1BASE")
    if not base1:
        t.ok(False, "stage-1 export part not run: needs S1BASE")
        return
    S1 = c1.Sess(base1)
    S1.reset(basefx(payments=[]))
    e1 = S1.call("GET", "/_test/export").j
    t.st(S.call("POST", "/_test/import", e1), 204, "import of a stage-1 export")
    S.tok = {}
    p2 = cx.page()
    login(t, cx, p2, "ada", path="/requests")
    t.ok(wait(p2, lambda: count(p2, "request-pay-rq_2") == 1), "pending request from a stage-1 export not offered on the request screen")
    p2.locator(q("request-pay-rq_2")).click()
    t.ok(wait(p2, lambda: attr(p2, "request-item-rq_2", "data-status") == "paid"), "pending request from a stage-1 export not payable through the screen")
    p2.goto(cx.base + "/")
    t.ok(wait(p2, lambda: text(p2, "wallet-available") == "97.00 EUR" and count(p2, "wallet-held") == 0), f"wallet after a stage-1 import: available {text(p2, 'wallet-available')!r}")


# --------------------------------------------------------------------------- Q quality probes
@ui("Q2-labels-focus", "stage-2 Product and visual direction", "Q1,Q2,Q3,Q4", "Every input has a visible label; keyboard focus is apparent; text contrast is sufficient; no horizontal page scroll on any required route; screenshots of every route and state are saved for the product-quality read")
def u_quality(t, cx):
    S = cx.S
    fx = authfx()
    S.reset(fx)
    S.call("POST", "/authorizations", {"to_handle": "ada", "amount": 900, "note": "incoming hold"}, as_="bob", key=k())
    page = cx.page()
    for r in ("/login", "/signup"):
        page.goto(cx.base + r)
        settle(page, 200)
        _quality(t, cx, page, r)
    login(t, cx, page, "ada")
    for r in ROUTES:
        page.goto(cx.base + r)
        settle(page, 400)
        _quality(t, cx, page, r)
        cx.shot(page, "route" + r.replace("/", "_"))


def _quality(t, cx, page, r):
    t.ok(no_hscroll(page), f"{r}: horizontal page scroll at {cx.vp[1]} px")
    res = page.evaluate("""() => {
      const vis = e => { const b = e.getBoundingClientRect(); const s = getComputedStyle(e); return b.width > 0 && b.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
      const out = {unlabelled: [], n: 0};
      for (const e of document.querySelectorAll('input:not([type=hidden]), select, textarea')) {
        if (!vis(e)) continue; out.n++;
        const labs = [...(e.labels || [])].filter(l => vis(l) && l.textContent.trim().length > 0);
        if (!labs.length) out.unlabelled.push(e.getAttribute('data-testid') || e.name || e.id || e.outerHTML.slice(0, 60));
      }
      return out; }""")
    t.ok(not res["unlabelled"], f"{r}: inputs without a visible <label>: {res['unlabelled']}")
    focus = page.evaluate("""() => {
      const els = [...document.querySelectorAll('input:not([type=hidden]), select, button, a[href]')].filter(e => e.getBoundingClientRect().width > 0);
      const bad = [];
      for (const e of els.slice(0, 40)) {
        const before = getComputedStyle(e); const b = [before.outlineStyle, before.outlineWidth, before.boxShadow, before.borderColor, before.backgroundColor].join('|');
        e.focus({focusVisible: true}); const a0 = getComputedStyle(e);
        const a = [a0.outlineStyle, a0.outlineWidth, a0.boxShadow, a0.borderColor, a0.backgroundColor].join('|');
        const outlined = a0.outlineStyle !== 'none' && parseFloat(a0.outlineWidth) > 0;
        if (!outlined && a === b) bad.push(e.getAttribute('data-testid') || e.textContent.trim().slice(0, 20) || e.tagName);
        e.blur();
      }
      return bad; }""")
    t.ok(not focus, f"{r}: controls with no visible focus indication: {focus[:8]}")
    low = page.evaluate("""() => {
      const lum = c => { const v = c.map(x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }); return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
      const parse = s => { const m = s.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(',').map(parseFloat); return {rgb: p.slice(0, 3), a: p.length > 3 ? p[3] : 1}; };
      const bg = e => { for (let n = e; n; n = n.parentElement) { if (getComputedStyle(n).backgroundImage !== 'none') return null; const c = parse(getComputedStyle(n).backgroundColor); if (c && c.a >= 0.99) return c.rgb; if (c && c.a > 0) return null; } return [255, 255, 255]; };
      const bad = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const seen = new Set();
      while (walker.nextNode()) {
        const n = walker.currentNode; if (!n.textContent.trim()) continue; const e = n.parentElement; if (!e || seen.has(e)) continue; seen.add(e);
        const s = getComputedStyle(e); const b = e.getBoundingClientRect(); if (!b.width || s.visibility === 'hidden' || s.display === 'none' || parseFloat(s.opacity) < 1) continue;
        if (getComputedStyle(e).backgroundImage !== 'none') continue;
        const fg = parse(s.color), back = bg(e); if (!fg || fg.a < 0.99 || !back) continue;
        const l1 = lum(fg.rgb), l2 = lum(back); const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
        const big = parseFloat(s.fontSize) >= 24 || (parseFloat(s.fontSize) >= 18.66 && parseInt(s.fontWeight) >= 700);
        if (ratio < (big ? 3 : 4.5)) bad.push(n.textContent.trim().slice(0, 24) + ' ' + ratio.toFixed(2));
      }
      return bad; }""")
    t.ok(not low, f"{r}: text below WCAG AA contrast (4.5:1, large 3:1): {low[:8]}")


@ui("K2-no-external-requests", "stage-1 §2 (no outbound network; runtime assets in the image)", "K2", "Across every page load of this run the browser requested nothing from another host, and no page raised a script error")
def u_external(t, cx):
    t.ok(not EXTERNAL, f"requests to other hosts: {sorted(EXTERNAL)[:6]}")
    t.ok(not PAGE_ERRORS, f"uncaught script errors in pages: {PAGE_ERRORS[:4]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base")
    ap.add_argument("--out")
    ap.add_argument("--only")
    ap.add_argument("--s1base")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        print("| Check | Spec | Map rows | What it checks (each at 375 px and 1280 px) |\n|---|---|---|---|")
        for c in UI:
            print(f"| {c['id']} | {c['clause']} | {c['row']} | {c['desc']} |")
        return 0
    if a.s1base:
        os.environ["S1BASE"] = a.s1base
    os.makedirs(a.out, exist_ok=True)
    from playwright.sync_api import sync_playwright
    only = a.only.split(",") if a.only else None
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for vp in VIEWPORTS:
            for c in UI:
                if only and not any(c["id"].startswith(p) for p in only):
                    continue
                t = T()
                cx = Ctx(browser, a.base, vp, a.out, c1.Sess(a.base))
                t0 = time.monotonic()
                try:
                    c["fn"](t, cx)
                except Exception as ex:
                    t.fails.append(f"ERROR {type(ex).__name__}: {str(ex)[:400]}\n{traceback.format_exc(limit=4)}")
                finally:
                    cx.close()
                status = "FAIL" if t.fails else "PASS"
                results.append(dict(id=c["id"], viewport=vp[0], clause=c["clause"], row=c["row"], status=status, fails=t.fails, notes=t.notes))
                print(f"[{status}] {c['id']} @{vp[0]} ({c['clause']}; rows {c['row']}) {time.monotonic() - t0:.1f}s", flush=True)
                for f in t.fails:
                    print(f"    FAIL: {f}", flush=True)
                for n in t.notes:
                    print(f"    note: {n}", flush=True)
        browser.close()
    bad5 = [x for x in c1.AUDIT if x[2] >= 500 or x[2] == 0]
    npass = sum(r["status"] == "PASS" for r in results)
    print(f"\nUI TOTAL {len(results)} checks: {npass} passed, {len(results) - npass} failed; side-channel 5xx/transport errors: {len(bad5)}")
    with open(os.path.join(a.out, "ui.json"), "w") as f:
        json.dump(results, f, indent=1)
    return 0 if npass == len(results) and not bad5 else 1


if __name__ == "__main__":
    sys.exit(main())
