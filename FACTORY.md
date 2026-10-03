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
