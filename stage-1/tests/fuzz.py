"""Hostile-input fuzz: no endpoint may answer 5xx. Needs a running service."""
import itertools, os, random, sys
sys.path.insert(0, os.path.dirname(__file__))
from client import call, fixture, key, reset, login

reset(fixture(settlement_operator_ids=["u_ada"]))
ada = login("ada")
rnd = random.Random(1)
vals = [None, True, False, 0, -1, 1, 1.5, 1e400, 10**30, "", "x", "ada", "bob", "\ud800", "a" * 300, [], [1], ["bob"], {}, {"a": 1},
        "1e9999999999999999999", [[]], [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]]
raws = ['1e99999999999999999999', '-1e-99999999999999999999', '1E400', '0e0', '-0', '1e-5', '123456789012345678901234567890e5']
fields = ["to_handle", "payer_handle", "amount", "note", "visibility", "participant_handles", "transfers", "email", "password",
          "display_name", "from_handle", "balance", "users", "currency", "minor_units", "state", "track", "format_version"]
paths = ["/payments", "/requests", "/splits", "/settlements", "/auth/signup", "/auth/login", "/requests/x/pay", "/requests/x/decline",
         "/requests/x/cancel", "/_test/import"]
bad = 0
for i in range(3000):
    body = {rnd.choice(fields): rnd.choice(vals) for _ in range(rnd.randint(0, 6))}
    path = rnd.choice(paths)
    try:
        import json
        raw = json.dumps(body)
        if rnd.random() < .3:
            raw = raw.replace("1", rnd.choice(raws), 1)
        s, b, _ = call("POST", path, token=ada, idem=key(), raw=raw)
    except UnicodeEncodeError:
        continue
    if s >= 500:
        bad += 1
        print("5xx", path, raw[:200], s)
for qs in ("limit=" + "9" * 5000, "offset=" + "9" * 5000, "limit=%FF", "direction=%00", "x=%"):
    for p in ("/requests", "/activity"):
        s, _, _ = call("GET", p + "?" + qs, token=ada)
        if s >= 500:
            bad += 1
            print("5xx", p, qs[:30], s)
print("fuzz done, 5xx count", bad)
sys.exit(1 if bad else 0)
