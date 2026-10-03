# Stage 4 — Verifier verdict, round 1: PASS

Rows: all stage-4 rows S4-0 … N4b · Revision: 5b21fe642ab1ee1d9e6b7892e050eda00f477225 · Files: stage-4/ (whole folder) · Command: `bash verification/stage-4/run4.sh 5b21fe642ab1ee1d9e6b7892e050eda00f477225 <evidence-dir>` plus harness host, isolated and `--all` · Expected / actual: all checks pass / all checks pass · Repro: n/a · Next: Architect

Tree clean; HEAD c6dc880 differs from 5b21fe6 only in STATUS.md. `stage-1/` = a8301bb,
`stage-2/` = 0d321ce, `stage-3/` = fcdb0a2 unchanged. Image built `--no-cache` from `git archive`.

## What was run
| What | Result |
|---|---|
| Clean build; internal no-outbound network, `--cpus 2 --memory 2g`; default port | OK, healthy after 0.33 s |
| RUN.md command as written | `GET /` 200 text/html, `/health` ok |
| Harness `--stage 4 --mode host` (`checks/verifier-s4-r1-host`) | suites 1/2/3/4: 120 / 25 / 7 / 6 passed, none skipped |
| Harness `--stage 4 --mode isolated` (`checks/verifier-s4-r1-isolated`) | suites 1/2/3/4: 120 / 25 / 7 / 6 passed |
| Harness `--all --mode isolated` (`checks/verifier-all-final`) | each of stage-1/ … stage-4/ claims its own stage; highest contiguous stage 4 |
| Implementer's tests | 69 unit tests OK; browser_checks.py 35/35 |
| Stage-1 list on the stage-4 image | 392 checks, 392 pass |
| Stage-2 API list on the stage-4 image | 98 checks, 98 pass |
| Stage-3 list on the stage-4 image (its "stage-4 absent" checks left out) | 171 checks, 171 pass |
| Stage-4 list `probe4.py` | 99 checks, 99 pass, plus 1 added while verifying (P4.SA4b), pass |
| Planner against my own brute-force oracle through the HTTP API | 480 randomised scenarios with three seeds: 641 plans identical to the optimum (assignments, changed flags, moved_count, unused_seats), 32 infeasible cases answered `no_feasible_plan`; 311 of the plans applied and checked booking by booking |
| Browser: screens after an applied plan (`ui4.py`) | 4 checks, 4 pass |
| Browser list (Chromium), upgrade source stage-1 container | 97 checks, 97 pass |
| Browser upgrade section with stage-2 and with stage-3 containers as source | 11 + 11 checks, all pass |
| No request left the service origin; empty container stderr; no OOM (117 MiB) | pass |

Oracle scenarios: 6 tables, 4 random declared pairs, 3–9 bookings on singles and pairs, in half of
them a policy changing capacities and duration published between bookings (so capacities come
from each booking's own accepted terms), cancelled bookings, fixed bookings outside the window,
and in 40% a second closure after applying the first. Up to 8 considered bookings occurred and
were answered correctly; `planning_limit` never appeared. At the limits a request takes well
under 0.1 s under `--cpus 2`.

Architect's points: (a) above. (b) preview changes nothing; failed key reusable. (c) revision
walk over every write kind, replay, failure, no-op, preview, other restaurant: exact.
(d) 404s, `plan_already_applied`, `stale_plan` after a write at the same restaurant and not after
one at another, replay after later changes, `reassigned` entry shape, unmoved bookings, 10
concurrent applies → one 201; no current-revision plan was ever rejected in 311 applications.
(e) closure seen by availability, options, explain, create, pair create, PATCH, moves, series
adoption and series amend; half-open at both ends. (f) an eligible occurrence's current date is
its scheduled date: only an individual PATCH or a move changes a date and both mark an
exception; a plan changes tables only (P4.SA4b); imported series behave the same (P4.UP4s3d).
(g) AP8 pass. (h) real containers a8301bb, 0d321ce, fcdb0a2 → stage 4 incl. an imported series
with an exception and a cancelled occurrence, receipts, sessions, browser recovery; stage-4
roundtrip with pending and applied plans. (i) lookup shows the new table, grid shows the closed
table unavailable. (j) all earlier lists pass. (k) 4 × 50 in flight: no 5xx, no overlap, nothing
on a closed table inside its closure.

## Notes (not blocking)
1. Beyond the stated limits the planner still answers (9 considered: 201 in 0.05 s); the limit is
   a node budget of 150 000, so `planning_limit` depends on search effort, not on counts.
2. Restaurants imported from stage-1/2 exports have no managers, so nobody can replan them; the
   spec gives no way to add managers after import.
3. The confirmation screen shows the response of the booking request; it is not refreshed after
   a later plan (no polling is required by stage 2). Lookup and grid reflect the plan.
4. PATCH with an unparseable body on an unknown reference: 400 here and in stage 3, 404 in
   stages 1–2 (map decisions differ; spec silent).
5. Earlier notes still apply: reset time grows with fixture users (about 7.4 s at 1000);
   scrypt n=2^12; history `at` in `+00:00`; lookup screen needs a signed-in user; UI treats
   5xx/timeouts as uncertain.
6. Maintainability: `planner.py` (110 lines) is a clear exact search with a documented argument
   for solving independent components separately; `replans.py`, `series.py` are small; one
   `table_free` covers bookings and closures. Nothing to change.

## Remaining risk not tested
The shipped stage-4 sample is a small part of the graded suite; exact cutoff equality; browsers
other than Chromium; a real 2-vCPU host; planner inputs far beyond the stated limits.
