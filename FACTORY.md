<!-- archive-note: added 2026-10-03 by Claude for Team Nightshift's archive -->
> **Archive copy: not a submission run.** This branch keeps Team Nightshift's record of this run (Stage-1 test of PR #53 head 643e2307), for reference only. The submitted run is Run 7 (branch `runs/20-2026-10-02-run-7-submitted` here; public submission repository `vibhortayal/nightshift-pocketful`).
>
> | | |
> |---|---|
> | Run | Stage-1 test of PR #53 head 643e2307. Stage-1 test in a scratch room |
> | What this run tested | Compared with Run 5's text: the simpler set. Severity scale, timed free testing and note routing removed; two kinds of finding (blocking or note); every check names the spec sentence it tests; value limits tested at the last allowed and first refused value; a fix that did not fix the fault is rejected at once |
> | Seats | Three Band seats on Claude Code: Architect `claude-opus-5-5`, Implementer `claude-sonnet-5-5`, Verifier `claude-opus-5-5`, running on the team's Chicago VM (from `mandates/`) |
> | When | 2026-10-02, 15:46 to 16:40 UTC |
> | Band room | scratch room `8c1d7878`, opened by Claude's Team session |
> | Mandates | PR #53 head `643e2307` (simpler set: no severity scale, no free testing, fail fast) |
> | Result | Stage 1 accepted in 53 minutes, 2 rejections |
> | Human input after dispatch | Dispatched by Claude's Team session, not by the owner |
> | Why it was not submitted | A test of mandate wording, not a four-stage run |
> | Room record | the room downloads and whole-room captures are kept by the team outside this repository |
>
> The text below this note is unchanged from the run, unless it is marked as added for the archive.

---

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
