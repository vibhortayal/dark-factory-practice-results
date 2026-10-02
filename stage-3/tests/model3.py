"""An independent brute-force model of the stage-3 ledger, written from the specification for the tests.

It is fed only with what a client observes (API answers), never with the service's internal state, and it
answers the same questions the service does: total / held / available at (as_of, known_at), statements, and
whether a correction would overdraw somebody. Instants are exact datetimes (the service clock is microseconds).
"""
from datetime import datetime, timezone

INF = datetime.max.replace(tzinfo=timezone.utc)
NEG = datetime.min.replace(tzinfo=timezone.utc)


def dt(text):
    t = text.replace("Z", "+00:00").replace("z", "+00:00")
    return datetime.fromisoformat(t)


class Model:
    def __init__(self, openings):
        self.opening = dict(openings)      # user id -> balance before anything moved
        self.payments = {}                 # payment id -> dict(from, to, revs=[(n, amount, eff, rec, eff_text, rec_text)])
        self.auths = {}                    # authorization id -> dict
        self.order = []                    # payment ids in creation order

    # ---- feeding
    def add_payment(self, p):
        created = dt(p["created_at"])
        self.payments[p["payment_id"]] = {"from": p["from_user_id"], "to": p["to_user_id"], "linked": bool(p.get("authorization_id") or p.get("settlement_id")),
                                          "revs": [(1, p["amount"], created, created, p["created_at"], p["created_at"])], "view": p}
        self.order.append(p["payment_id"])

    def add_correction(self, c):
        self.payments[c["payment_id"]]["revs"].append((c["revision"], c["amount"], dt(c["effective_at"]), dt(c["recorded_at"]),
                                                      c["effective_at"], c["recorded_at"]))

    def add_auth(self, a):
        self.auths[a["authorization_id"]] = {"from": a["from_user_id"], "amount": a["amount"], "created": dt(a["created_at"]),
                                             "expires": dt(a["expires_at"]), "caps": [], "void": None, "final_idx": None}

    def add_capture(self, aid, pay, closing):
        a = self.auths[aid]
        a["caps"].append((dt(pay["created_at"]), pay["amount"]))
        if closing:
            a["final_idx"] = len(a["caps"]) - 1

    def add_void(self, aid, when):
        self.auths[aid]["void"] = dt(when)

    # ---- the views
    def select(self, pid, K):
        best = None
        for r in self.payments[pid]["revs"]:
            if r[3] <= K:
                best = r  # revisions are in recorded order
        return best

    def total(self, u, T, K, override=None):
        bal = self.opening[u]
        for pid, p in self.payments.items():
            if u not in (p["from"], p["to"]):
                continue
            r = override[1] if override and override[0] == pid else self.select(pid, K)
            if r is None or r[2] > T:
                continue
            bal += r[1] if p["to"] == u else -r[1]
        return bal

    def hold_of(self, a, T, K):
        if not (a["created"] <= T and a["created"] <= K):
            return 0
        events = []
        for i, (t, amount) in enumerate(a["caps"]):
            events.append((t, 1, "cap", amount, i == a["final_idx"]))
        if a["void"] is not None:
            events.append((a["void"], 2, "void", 0, True))
        events.append((a["expires"], 3, "expiry", 0, True))
        events.sort(key=lambda e: (e[0], e[1]))
        remaining = a["amount"]
        for t, _, kind, amount, closing in events:
            if t > T:
                break
            if kind != "expiry" and t > K:
                continue
            remaining = 0 if closing else remaining - amount
        return max(remaining, 0)

    def held(self, u, T, K):
        return sum(self.hold_of(a, T, K) for a in self.auths.values() if a["from"] == u)

    def view(self, u, T, K):
        total = self.total(u, T, K)
        held = self.held(u, T, K)
        return {"balance": total, "total": total, "available": total - held, "held": held}

    def statement(self, u, frm, to, K):
        frm = NEG if frm is None else frm
        entries = []
        before = self.opening[u]
        for pid, p in self.payments.items():
            if u not in (p["from"], p["to"]):
                continue
            r = self.select(pid, K)
            if r is None or r[2] >= to:
                continue
            d = r[1] if p["to"] == u else -r[1]
            if r[2] < frm:
                before += d
            else:
                entries.append((r[2], pid, r, d))
        entries.sort(key=lambda e: (e[0], e[1]))
        run = before
        out = []
        for eff, pid, r, d in entries:
            run += d
            out.append({"payment_id": pid, "delta": d, "balance_after": run, "revision": r[0], "effective_at": r[4],
                        "recorded_at": r[5], "amount": r[1]})
        return before, out, run

    def would_overdraw(self, u, pid, new_rev, now):
        """Would user u be negative (total or available) at some boundary <= now with this revision added?"""
        times = set()
        for q, p in self.payments.items():
            if u in (p["from"], p["to"]):
                for r in p["revs"]:
                    times.add(r[2])
                if q == pid:
                    times.add(new_rev[2])
        for a in self.auths.values():
            if a["from"] == u:
                times.add(a["created"])
                for t, _ in a["caps"]:
                    times.add(t)
                if a["void"] is not None:
                    times.add(a["void"])
                times.add(a["expires"])
        for t in sorted(times):
            if t > now:
                continue
            # latest known revisions, the candidate included
            total = self.total(u, t, INF, override=(pid, new_rev))
            held = self.held(u, t, INF)
            if total < 0 or total - held < 0:
                return True
        return False
