# Nightshift Dark Factory

Seats: Nightshift Architect (Claude Code, claude-opus-5-5), Nightshift Implementer
(Claude Code, claude-sonnet-5-5), Nightshift Verifier (Claude Code, claude-opus-5-5).
Mandates: mandates/. This file is completed by the team after the run with measured
results, timings, costs and failures.

## Run of 2026-10-02: Pocketful stage 1

How the unit moved through the factory (details and evidence paths in `STATUS.md`, requirements
in `ACCEPTANCE-stage-1.md`):

1. The Architect read the specification, wrote the acceptance map (73 rows across delivery,
   money invariants, errors, authentication, idempotency, endpoints, export/import, settlements
   and the supplied checks) and handed the task, the full specification and the map to both seats.
2. The Implementer built `stage-1/` (Python 3.12 standard library, one container) while the
   Verifier derived its own check list from the specification.
3. The Verifier reviewed three revisions and gave one verdict each.

| Revision | Verdict | Supplied checks (isolated) | Verifier's own checks | Findings |
|---|---|---|---|---|
| 3b9a0cc | BLOCK 1 | 147 / 147 | 448 pass, plus 12 of 13 new regression cases failing | Amounts judged after rounding to a binary float; oversize JSON numbers answered 400 |
| d0f51eb | BLOCK 2 | 147 / 147 | 461 / 461, plus 2 of 36 new cases failing | Reset and import returned 500 for a huge-exponent number (regression from the fix) |
| 56aeaee | PASS | 147 / 147 | 497 / 497 | none |

Measured: 46 minutes from dispatch to the PASS verdict; two fix rounds of the five allowed.
Both blocking findings were outside the supplied checks, which were green on every revision.
Costs were not measured by the seats.

Failures and what they showed: the first build passed every supplied check while accepting
non-integer money amounts; the first fix introduced a 5xx on the test-control endpoints. Both
were caught by checks the Verifier derived from the specification, not from the shipped suite.
