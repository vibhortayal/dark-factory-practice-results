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
