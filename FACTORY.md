<!-- archive-note: added 2026-10-03 by Claude for Team Nightshift's archive -->
> **Archive copy: not a submission run.** This branch keeps Team Nightshift's record of this run (Stage-1 test of PR #52 head f6fc48a3), for reference only. The submitted run is Run 7 (branch `runs/20-2026-10-02-run-7-submitted` here; public submission repository `vibhortayal/nightshift-pocketful`).
>
> | | |
> |---|---|
> | Run | Stage-1 test of PR #52 head f6fc48a3. Stage-1 test in a scratch room |
> | What this run tested | Compared with `590afd18`, which let real spec faults pass as notes: hardened grading (any server error or named case blocks; a note must state the size it exceeded), notes fixed during fix rounds, and the Verifier preparing its checks while the Implementer builds |
> | Seats | Three Band seats on Claude Code: Architect `claude-opus-5-5`, Implementer `claude-sonnet-5-5`, Verifier `claude-opus-5-5`, running on the team's Chicago VM (from `mandates/`) |
> | When | 2026-10-02, 03:21 to 04:04 UTC |
> | Band room | scratch room `590851bd`, opened by Claude's Team session |
> | Mandates | PR #52 head `f6fc48a3` (hardened grading, Verifier prepares in parallel) |
> | Result | Stage 1 accepted in 43 minutes, 1 rejection |
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

## Run record: Pocketful stage 1 (2026-10-02)

Flow: the Architect writes an acceptance map from the whole specification, hands the task,
the verbatim specification and the map to both other seats; the Implementer builds and
self-checks; the Verifier prepares its own checks from the specification while the build
runs and then gives one graded verdict per revision. Only a Verifier PASS on the head
revision is accepted.

| Measure | Value |
|---|---|
| Dispatch to accepted PASS | 43 min (03:21Z to 04:04Z) |
| First committed revision | 11 min after dispatch (dd93fa4) |
| Fix rounds (BLOCK verdicts) | 1 of 5 allowed |
| Accepted revision | 6c9781a2d954f9c94e0a3dfca4dc563a93aabf4a |
| Supplied checks, isolated mode | 147 of 147 passed (`../checks/s1-ver-04`) |
| Verifier's own checks | 540 of 540 passed |
| Model spend | not measured in this run |

Failure caught and recovered: the first revision passed all 147 supplied checks and the
Verifier's 489 specification checks, and was still blocked: the Verifier's timed hardening
found that import accepted states the service could not operate on (a hang and a login
bypass). The Implementer fixed the class of fault (whole-state import validation) in one
round. Open notes are listed in `STATUS.md`.

Cost of the design: each revision handoff re-sends the full specification and map (about
54 KB in five messages), and the Architect must not commit while a revision is under
verification, so status updates wait for the verdict.
