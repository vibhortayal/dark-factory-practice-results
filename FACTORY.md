<!-- archive-note: added 2026-10-03 by Claude for Team Nightshift's archive -->
> **Archive copy: not a submission run.** This branch keeps Team Nightshift's record of Tablekeeper four-stage run, for reference only. The submitted run is Run 7 (branch `nightshift-run-7-2026-10-02` here; public submission repository `vibhortayal/nightshift-pocketful`).
>
> | | |
> |---|---|
> | Run | Tablekeeper four-stage run. Four-stage run on the other track, in a scratch room |
> | When | 2026-10-03, 10:23 to 12:00 UTC |
> | Band room | scratch room `7ee2d49e`, opened by Claude's Team session |
> | Mandates | PR #54 head `91b753b3`, merged to `main` of `nightshift-factory` as `ee236a1` (the submitted set), unchanged from Run 7 |
> | Result | All four Tablekeeper stages accepted in about 96 minutes, 3 rejections. Supplied checks 120, 25, 7 and 6, all passing |
> | Human input after dispatch | Dispatched by Claude's Team session, not by the owner. The band's own FACTORY.md below says "one human message"; that message came from Claude's session |
> | Why it was not submitted | Evidence that the mandates are generic. Tablekeeper is not the submitted track |
> | Room record | the room downloads and whole-room captures are kept by the team outside this repository |
>
> The text below this note is unchanged from the run, unless it is marked as added for the archive.

---

# Nightshift Dark Factory

Seats: Nightshift Architect (Claude Code, claude-opus-5-5), Nightshift Implementer
(Claude Code, claude-sonnet-5-5), Nightshift Verifier (Claude Code, claude-opus-5-5).
Mandates: mandates/. This file is completed by the team after the run with measured
results, timings, costs and failures.

## Run results (2026-10-03, 10:24–12:00 UTC, ~96 min, one human message)

| Stage | Accepted revision | BLOCK rounds | Harness (isolated) | Verifier evidence |
|---|---|---|---|---|
| 1 | a8301bb9379977851db1c64ff468cbddc30011ff | 2 | suite 1: 120 passed | verification/stage-1/ |
| 2 | 0d321ce2763bcfb4f0732d0131fea33c3c4814a6 | 1 | suites 1/2: 120/25 | verification/stage-2/ |
| 3 | fcdb0a2b3d4257c041607cdad6e77c91e2187e76 | 0 | suites 1/2/3: 120/25/7 | verification/stage-3/ |
| 4 | 5b21fe642ab1ee1d9e6b7892e050eda00f477225 | 0 | suites 1/2/3/4: 120/25/7/6 | verification/stage-4/ |

`harness run --all --mode isolated` (checks/verifier-all-final): every folder claims its own
stage; highest contiguous stage 4. Failures caught by the Verifier beyond the supplied checks:
stage 1 F1 (reset wrong-type fields 422 instead of 400), F2 (moves cutoff precedence), F3 (seeded
party_size type); stage 2 F1 (UI crash on a stage-1 receipt after upgrade). Acceptance maps:
acceptance/. State and notes per stage: STATUS.md. Costs were not measured.
