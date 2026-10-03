# Stage 3 — Verifier verdict, round 1: PASS

Rows: all stage-3 rows S3-0 … N3b · Revision: fcdb0a2b3d4257c041607cdad6e77c91e2187e76 · Files: stage-3/ (whole folder) · Command: `bash verification/stage-3/run3.sh fcdb0a2b3d4257c041607cdad6e77c91e2187e76 <evidence-dir>` plus harness host and isolated · Expected / actual: all checks pass / all checks pass · Repro: n/a · Next: Architect

Tree clean, HEAD = fcdb0a2; `stage-1/` identical to a8301bb, `stage-2/` identical to 0d321ce.
Image built `--no-cache` from `git archive` of the revision.

## What was run
| What | Result |
|---|---|
| Clean build; internal no-outbound network, `--cpus 2 --memory 2g`; default port | OK, healthy after 0.34 s |
| RUN.md command as written | `GET /` 200 text/html, `/health` ok |
| Harness `--stage 3 --mode host` (`checks/verifier-s3-r1-host`) | suites 1/2/3: 120 / 25 / 7 passed; stage-4 suite: 1 failed, 4 passed (fails, as required) |
| Harness `--stage 3 --mode isolated` (`checks/verifier-s3-r1-isolated`) | suites 1/2/3: 120 / 25 / 7 passed; stage-4 suite: 1 failed, 4 passed |
| Implementer's tests | 53 unit tests OK; browser_checks.py 35/35 |
| Stage-1 list on the stage-3 image | 392 checks, 392 pass (see note 7) |
| Stage-2 API list on the stage-3 image (upgrade source: real a8301bb container) | 98 checks, 98 pass |
| Stage-3 list `probe3.py` | 169 checks, 169 pass; plus 5 further cases added while verifying (closed-weekday policy, adoption onto a closed day, 10 racing adoptions of one anchor, pair in explain, pair→single move history), all pass |
| Browser list (Chromium), upgrade source stage-1 container | 97 checks, 97 pass |
| Browser upgrade section with the stage-2 container (0d321ce) as source | 11 checks, 11 pass |
| No request left the service origin; no external URLs; empty container stderr; no OOM (164 MiB) | pass |
| Stage-4 features | `POST …/replans`, `…/closures`, `/series/{id}/amend` → 404; `restaurant_revision` in no response (only inside the export state as `restaurant_revisions`) |

The stage-3 list covers: explain value matrix, shape, independent rules, policy_version;
history and decision (owner / other user / manager / anonymous, seq, revisions, terms per entry,
no-ops, replay, repeat cancel, pair shapes, reversed pair); policy permissions, key rules,
45 invalid policies and the boundary values, gap-free versions under 20 concurrent
publications; selection (tie, later-published earlier date, past date); availability, options,
explain and booking under a policy that changes grid, hours, duration and capacities; occupancy
from stored intervals; amendments across a policy boundary; accepted cutoff for cancel and
amendment measured around the current time; `expected_revision` matrix and 24 concurrent
amendments on one revision; series bounds, anchor errors, per-occurrence policy, DST gap and
repeated hour, first failing index, nothing left after failure, exceptions, cancels, replay,
owner-only GET, pair anchors; moves with revisions and series; stage-3 export/import of all four
receipt kinds; upgrades from real stage-1 and stage-2 containers incl. adoption of an imported
booking; 4 × 50 in-flight mixed load with gap-free counters and no overlap.

## Notes (not blocking)
1. PATCH with an unparseable body on an unknown reference answers 400 in stage 3 (stage-3 map
   decision 2: body before 404) while stage 1 and 2 answer 404 (stage-1 map amendment 1). The
   spec states no order; the two map entries disagree with each other.
2. History `at` uses `+00:00`; the spec example shows a local offset but only requires RFC 3339
   order.
3. Seeded and imported reservations get one `created` entry at `created_at` with their current
   values (map decision 4); the spec does not describe history for them.
4. Not probed because the spec does not say: a policy with an empty `opening_hours`; whether
   unknown fields are echoed in the 201 policy body.
5. Earlier notes still apply: reset time grows with fixture users (about 7.4 s at 1000);
   scrypt n=2^12; lookup screen needs a signed-in user; UI treats 5xx/timeouts as uncertain.
6. Maintainability: new modules are small and single-purpose (`policies.py`, `records.py`,
   `history.py`, `series.py`); one selection function and a "rules view" keep the scheduling code
   unchanged. `restaurant_revisions` is kept in state for stage 4. Nothing to change.
7. My first run of the stage-1 list used a stale derived script that did not ignore `revision`
   (7 false failures: 6 equality checks, and the case in note 1). I regenerated it
   (`gen_probe1.py`) and reran the list: 392/392. `run.log` shows the first run, `probe1.log`
   the rerun.

## Remaining risk not tested
The shipped stage-3 sample is about a fifth of the graded suite; exact cutoff equality;
browsers other than Chromium; a real 2-vCPU host.
