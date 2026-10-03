#!/usr/bin/env python3
"""Stage-4 browser probe (row AP9): existing screens reflect an applied plan. Usage: BASE=.. SHOTS=.. python ui4.py"""
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "stage-2"))
import ui_probe as u  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

MGR = ("mgr@example.com", "manager secret", "Manager")


def fixture():
    f = u.fixture()
    f["users"].append({"id": "u_mgr", "email": MGR[0], "password": MGR[1], "display_name": MGR[2]})
    f["restaurants"][0]["manager_user_ids"] = ["u_mgr"]
    return f


def main():
    u.reset(fx=fixture())
    hdr = {"Authorization": f"Bearer {u.token(MGR)}"}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        c = u.Ctx(b)
        pg = c.page
        u.ui_login(pg)
        u.search(pg, "r_anker", 2)
        pg.click(u.S("slot-t_2-19:00"))
        u.wait_vis(pg, "booking-form")
        pg.click(u.S("booking-submit"))
        u.wait_vis(pg, "confirmation")
        refv = u.text(pg, "confirmation-reference")
        frm, to = f"{u.D}T19:00:00+02:00", f"{u.D}T20:30:00+02:00"
        off = u.api.get(u.BASE + f"/availability?restaurant_id=r_anker&date={u.D}&party_size=2").json()["slots"][0]["starts_at"][-6:]
        frm, to = frm[:-6] + off, to[:-6] + off
        pv = u.api.post(u.BASE + "/restaurants/r_anker/replans", headers=dict(hdr, **{"Idempotency-Key": os.urandom(8).hex()}), json={"table_id": "t_2", "from": frm, "to": to})
        ap = u.api.post(u.BASE + f"/restaurants/r_anker/replans/{pv.json().get('plan_id')}/apply", headers=dict(hdr, **{"Idempotency-Key": os.urandom(8).hex()}), json={})
        moved = [x for x in ap.json().get("reservations", []) if x["reference"] == refv]
        u.check("UI4.AP9a", "AP9", "plan previewed and applied by the manager; the diner's booking moved off t_2 to table 1 (party 2, no unused seat)", pv.status_code == 201 and ap.status_code == 201 and moved and moved[0]["table_ids"] == ["t_1"], f"{pv.status_code} {ap.status_code} {moved}")
        pg.goto(u.BASE + "/lookup")
        pg.fill(u.S("lookup-reference-input"), refv)
        pg.click(u.S("lookup-submit"))
        ok = u.wait_vis(pg, "reservation-detail")
        rt = u.text(pg, "reservation-tables") or u.text(pg, "reservation-detail")
        u.check("UI4.AP9b", "AP9", "lookup shows the booking with its new table (label 1, no longer 2), still confirmed", ok and u.text(pg, "reservation-status") == "confirmed" and "1" in u.text(pg, "reservation-tables") and "2" not in u.text(pg, "reservation-tables"), rt)
        u.shot(pg, "lookup-after-plan")
        u.search(pg, "r_anker", 2)
        cells = dict(u.cells(pg))
        want_closed = all(cells.get(f"slot-t_2-{h}") == "false" for h in ("18:00", "18:30", "19:00", "19:30", "20:00")) and cells.get("slot-t_2-20:30") == "true"
        combos = [k for k, v in cells.items() if "+" in k and "t_2" in k and k[-5:] in ("18:00", "18:30", "19:00", "19:30", "20:00") and v == "true"]
        u.check("UI4.AP9c", "AP9", "availability grid shows the closed table unavailable in every overlapping slot (and bookable again at 20:30); no combination with it is offered there; table 1 is taken at 19:00", want_closed and not combos and cells.get("slot-t_1-19:00") == "false", {k: v for k, v in cells.items() if "t_2" in k})
        u.shot(pg, "grid-after-plan")
        pg.click(u.S("slot-t_2-19:00"), force=True, timeout=3000)
        pg.wait_for_timeout(400)
        u.check("UI4.AP9d", "AP9", "the closed cell cannot be opened for booking", not u.vis(pg, "booking-form"), "")
        c.close()
        b.close()
    fails = [r for r in u.RESULTS if not r["ok"]]
    print(f"\nTOTAL {len(u.RESULTS)} checks: {len(u.RESULTS) - len(fails)} passed, {len(fails)} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
