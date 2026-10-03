<!-- archive-note: added 2026-10-03 by Claude for Team Nightshift's archive -->
> **Archive copy: not a submission run.** This branch keeps Team Nightshift's record of Run 4b, for reference only. The submitted run is Run 7 (branch `nightshift-run-7-2026-10-02` here; public submission repository `vibhortayal/nightshift-pocketful`).
>
> | | |
> |---|---|
> | Run | Run 4b. Four-stage run, Claude Code seats |
> | When | 2026-10-01 21:14 to 2026-10-02 00:25 UTC |
> | Band room | `Nightshift \| Pocketful \| Stages 1-4 \| Run 4b \| 2026-10-01` (`afb80351`) |
> | Mandates | the Run 3 set (team repo `nightshift-factory`, commit `f3cbc34`), unchanged from Run 4 |
> | Result | Clean, but stage 1 was recorded BLOCKED after 10 rejections. Nothing accepted. 3 h 11 min. The Verifier's findings moved from real faults to extreme inputs, which led to the bounded mandates |
> | Human input after dispatch | One dispatch, no intervention |
> | Why it was not submitted | Stopped at stage 1 |
> | Room record | the room downloads and whole-room captures are kept by the team outside this repository |
>
> The text below this note is unchanged from the run, unless it is marked as added for the archive.

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
