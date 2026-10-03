#!/usr/bin/env python3
"""Derive the stage-1 list for a stage-3 image from stage-1/probe.py (same checks; table_ids-aware
equality; P2.3e accepts the stage-3 map decision 2 order for PATCH: body 400 before 404)."""
import os
here = os.path.dirname(os.path.abspath(__file__))
s = open(os.path.join(here, "..", "stage-1", "probe.py")).read()
helper = '''

def wt(d, tid):
    """Expected body after a table change: stage 2 adds table_ids next to table_id."""
    d2 = dict(d, table_id=tid)
    if isinstance(d, dict) and "table_ids" in d:
        d2["table_ids"] = [tid]
    return d2

'''
a = "# ---------------------------------------------------------------- sections"
assert a in s; s = s.replace(a, helper + a, 1)
for old, new in [('j == dict(r0, party_size=2, table_id="t_1")', 'j == wt(dict(r0, party_size=2), "t_1")'),
                 ('js[0] == dict(J(A), table_id="t_2") and js[1] == dict(J(B), table_id="t_1")', 'js[0] == wt(J(A), "t_2") and js[1] == wt(J(B), "t_1")'),
                 ('''"PATCH unknown reference with unparseable body: 404 first (map amendment 1)", req("PATCH", "/reservations/ZZZZZZ99", token=ta, raw="{x"), 404, "not_found")''',
                  '''"PATCH unknown reference with unparseable body: 404 (stage-1 map amendment 1) or 400 (stage-3 map decision 2)", req("PATCH", "/reservations/ZZZZZZ99", token=ta, raw="{x"), (404, 400), ("not_found", "malformed_request"))''')]:
    assert old in s, old; s = s.replace(old, new, 1)
open(os.path.join(here, "probe1_on_stage3.py"), "w").write(s)
