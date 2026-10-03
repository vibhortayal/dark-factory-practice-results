"""Universal assertions over every HTTP call made by the session (runs last)."""
import json
import os

import pytest

from lib import CALLS, NOTES, VIOLATIONS, VOUT

KINDS = ["5xx", "slow", "envelope", "ctype", "204-body", "not-json", "timestamp", "id", "non-integer-amount"]


@pytest.mark.parametrize("kind", KINDS)
def test_zz_no_universal_violation(kind):
    hits = [v for v in VIOLATIONS if v["kind"] == kind]
    sample = json.dumps(hits[:8], ensure_ascii=False, default=str)[:3000]
    assert not hits, f"{len(hits)} violation(s) of kind {kind}: {sample}"


def test_zz_summary():
    summary = {"calls": CALLS["n"], "max_request_s": round(CALLS["max_s"], 3), "max_request": CALLS["max_path"],
               "max_control_s": round(CALLS["max_ctl_s"], 3), "violations": len(VIOLATIONS),
               "notes": sorted({n["kind"] for n in NOTES})}
    with open(os.path.join(VOUT, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1)
    print("\nVERIFIER SUMMARY", json.dumps(summary))
    assert CALLS["n"] > 1000
