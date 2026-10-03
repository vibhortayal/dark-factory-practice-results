<!-- archive-note: added 2026-10-03 by Claude for Team Nightshift's archive -->
> **Archive copy: not a submission run.** This branch keeps Team Nightshift's record of this run (Background-task test), for reference only. The submitted run is Run 7 (branch `runs/20-2026-10-02-run-7-submitted` here; public submission repository `vibhortayal/nightshift-pocketful`).
>
> | | |
> |---|---|
> | Run | Background-task test. Four-stage test run in a scratch room |
> | What this run tested | Compared with Run 7: the mandates' paragraph against background tasks removed from all three seats, and the setting that switches background tasks off removed from the seats. Nothing else changed. It tested whether allowing background tasks makes the factory faster |
> | Seats | Three Band seats on Claude Code: Architect `claude-opus-5-5`, Implementer `claude-sonnet-5-5`, Verifier `claude-opus-5-5`, running on the team's Chicago VM (from `mandates/`) |
> | When | 2026-10-03, 19:43 to 21:38 UTC |
> | Band room | scratch room `2d54a4fe`, opened by Claude's Team session |
> | Mandates | Run 7's set minus its paragraph against background tasks, with background tasks allowed in the seats' settings. Used for this test only |
> | Result | All four stages accepted in about 2 hours, 1 rejection. One background task ended in an error after its message had gone out; nothing was lost. Most of the time saved against Run 7 came from fewer rejections, so a speed gain from background tasks is not shown |
> | Human input after dispatch | Dispatched by Claude's Team session on the owner's request, not by the owner |
> | Why it was not submitted | A test of one setting, run for comparison. The submitted factory keeps background tasks off |
> | Room record | the room downloads and whole-room captures are kept by the team outside this repository |
>
> The text below this note is unchanged from the run, unless it is marked as added for the archive.

---

# Nightshift Dark Factory

Seats: Nightshift Architect (Claude Code, claude-opus-5-5), Nightshift Implementer
(Claude Code, claude-sonnet-5-5), Nightshift Verifier (Claude Code, claude-opus-5-5).
Mandates: mandates/. This file is completed by the team after the run with measured
results, timings, costs and failures.

## Run record (2026-10-03, track pocketful)

Dispatch 19:42Z, last verdict 21:41Z, final cross-stage check 21:43Z (about 2 h). No human input after dispatch.

| Stage | Accepted revision | BLOCK rounds | Supplied checks (isolated) | Verifier's own checks |
|---|---|---|---|---|
| 1 | 172a3180 | 0 | stage 1 pass (147 tests) | delivery 10/10, API 58/58 |
| 2 | c59be33b | 1 | stages 1–2 pass | delivery 12/12, API 73/73, browser 30/30 |
| 3 | 9dcc200f | 0 | stages 1–3 pass | delivery 13/13, API 87/87, browser 30/30 |
| 4 | 2c6b40aa | 0 | stages 1–4 pass | delivery 14/14, API 98/98, browser 30/30 |

How it worked: the Architect wrote an acceptance map per stage (`acceptance/`) and handed the task, spec and map
to both seats; the Implementer built and self-checked each row; the Verifier prepared its checks from the spec
while the build ran and gave one verdict per revision (`verification/`). State per stage is in `STATUS.md`.

Failures and corrections:

- Stage 2, round 1: BLOCK — Requests and Holds screens were laid out in a collapsed grid column. The supplied
  checks and the Implementer's tests were green; the Verifier's measurement caught it. Fixed in one round.
- Stage 3: the Architect's map wrongly said statement snapshot tokens die on import. Found by the Architect when
  reading the stage-4 spec, after a PASS on 3a39ddfe. Stage 3 was reopened, fixed (9dcc200f) and verified again
  before stage 4 started.

Costs (tokens, money) were not measured by the seats. The supplied checks are only part of the judging tests.
