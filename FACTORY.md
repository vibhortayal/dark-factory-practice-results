<!-- archive-note -->
> **Not a submission run.** This is one of Team Nightshift's practice runs, rehearsals or tests. The submitted run is Run 7, branch `runs/20-2026-10-02-run-7-submitted`.

## 22. Background-task test (Oct 3, all four stages)

- **What changed from the previous run:** The rule against background tasks removed from the mandates, and background tasks allowed in the settings.
- **Why:** To see whether background tasks make the factory faster.
- **Result:** All four stages accepted in about 2 hours, one BLOCK. One background task ended in an error after its message had gone out, so nothing was lost this time.
- **Conclusion:** No clear speed gain: most of the time saved came from fewer BLOCK verdicts. The failure that lost messages before is still possible.
- **What we did next:** Kept background tasks off in the submitted factory.
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

The whole sequence of runs is on the `main` branch of this repository.

Below this line: the run's own text, unchanged.

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
