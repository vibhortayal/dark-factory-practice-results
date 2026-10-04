<!-- archive-note -->
> **Not a submission run.** This is one of Team Nightshift's practice runs, rehearsals or tests. The submitted run is Run 7, branch `runs/20-2026-10-02-run-7-submitted`.

## 11. Run 4b (Oct 1, all four stages)

- **What changed from the previous run:** Nothing. Same mandates, same settings as Run 4.
- **Why:** To see whether Run 4's result was bad luck.
- **Result:** Clean, but stage 1 was never accepted: 10 BLOCK verdicts in 3 h 11 min. The findings moved to extreme inputs, such as a 60-million-digit number.
- **Conclusion:** Not luck. The mandates had to say how far the Verifier tests.
- **What we did next:** Bounded the Verifier and tried it on stage 1 (run 12).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

The whole sequence of runs is on the `main` branch of this repository.

Below this line: the run's own text, unchanged.

---

# Nightshift Dark Factory

Seats: Nightshift Architect (Claude Code, claude-opus-5-5), Nightshift Implementer
(Claude Code, claude-sonnet-5-5), Nightshift Verifier (Claude Code, claude-opus-5-5).
Mandates: mandates/. This file is completed by the team after the run with measured
results, timings, costs and failures.

## Run of 2026-10-01 (pocketful)

Result: no stage accepted. Stage 1 was recorded BLOCKED after five fix rounds without a Verifier
PASS; stages 2–4 were not started because each builds on the previous one. Details, the open
finding and the full revision/verdict table are in `STATUS.md`.

| Measure | Value |
|---|---|
| Wall time | 3 h 11 min (2026-10-01T21:14Z to 2026-10-02T00:25Z) |
| Stage-1 revisions committed by the Implementer | 19 commits, 11 handed off |
| Verifier verdicts | 10, all BLOCK |
| Supplied checks on the last stage-1 revision (09358e2), isolated mode | suite 1: 147 of 147 passed, 0 skipped; suite 2 (overshoot probe): fail as intended; `claimed stage: 1` |
| Implementer unit tests on 09358e2 | 103 pass |
| Verifier probe suite on 09358e2 | 897 of 900 pass; the other 3 are documented envelope rejections (413) |
| Token and money cost | not measured |

## What went wrong

- The Verifier found a new class of defect in almost every round (races, numeric edge cases in
  idempotency comparison, resource exhaustion, import validation), each real and each outside the
  supplied checks. The first handoff did not ask for a resource envelope or a fully validating
  import, so those arrived as fix rounds instead of as requirements.
- Messages crossed. The Implementer fixed directly from Verifier verdicts while Architect fix
  requests were still in flight, and four revisions moved under a running verification. A gated
  hand-over (candidate branch, Architect probe, Verifier idle line, frozen repository) fixed this
  only for the last revision.
- The last finding (import accepts out-of-range values) had been present since the first revision
  and was visible in round 1; it was not pursued until the final verdict.
