# Status

Run started: 2026-10-02T15:46Z (task dispatched to the Architect). All times UTC, taken from
commit times and check-output directories.

| Unit | State | Fix rounds (BLOCK verdicts) | Accepted revision | Elapsed |
|---|---|---|---|---|
| stage-1 (Pocketful: payments and settlements) | DONE | 2 | 56aeaee584ce3559add3c3f3953e7075a5b0c92a (`stage-1/` tree c4dc34cbeb8b049de4085145736c760b13e471d4) | 0h46 (15:46 to Verifier PASS at about 16:32) |

No later unit was dispatched; stage 2 and beyond are not started.

## Log

- 15:46 Task received. Specification read in full (`pocketful/spec/stage-1.md`).
- 15:48 Acceptance map committed (`ACCEPTANCE-stage-1.md`, 158e4e3). Both seats confirmed in the
  room. Six-part handoff (task, full specification, full map, paths, commands) sent to the
  Implementer and the Verifier; the Verifier prepared its checks while the Implementer built.
- 15:56 Implementer committed 3b9a0cc76e72590543b26013078923c7fcca9814 (isolated harness 147/147,
  claimed stage 1). Handed to the Verifier.
- 16:11 Verifier verdict on 3b9a0cc: **BLOCK 1**. (1) Non-integer amount literals that round to
  an integer in binary floating point were accepted and moved money (B4, C3, F3; also /requests,
  /splits, /settlements). (2) Valid JSON amounts that overflow a float or exceed 4300 digits
  returned 400 instead of 422, also inside an unknown field (A10). Supplied checks 147/147 host
  and isolated; Verifier list 448/448 apart from these.
- 16:12 Map clarified (7eced58): B4 exact-decimal wording; F6 and H1 [choice] rows. Fix request sent.
- 16:17 Implementer committed d0f51eb002a64a8aba80651b25c19fab005c20da (exact decimal parsing;
  notes N1 to N3 and the reset race addressed). Handed to the Verifier.
- 16:24 Verifier verdict on d0f51eb: **BLOCK 2**. Round-1 findings fixed. New finding, a
  regression from the parser change: `POST /_test/reset` and `POST /_test/import` returned 500
  (OverflowError) for a number literal with an exponent of 10^18 or more in a fixture balance,
  seeded payment amount or imported state (A9, A12, G4). Supplied checks 147/147; Verifier list
  461/461; 34 of 36 new cases. Fix request sent (9b90306 records it).
- 16:26 Implementer committed 56aeaee584ce3559add3c3f3953e7075a5b0c92a (non-finite numbers in
  fixture/import are 422; any build failure in reset/import is 422 with the state untouched).
  Handed to the Verifier.
- 16:32 Verifier verdict on 56aeaee: **PASS**, no findings. Unit accepted.

## Accepted revision: evidence (Verifier, on 56aeaee)

- Supplied checks, host mode (`band-work/checks/verifier-r3-host`): `claimed stage: 1 on the
  shipped checks`; 147 collected, 147 passed, 0 failed, 0 errors, 0 skipped, 0 deselected.
- Supplied checks, isolated mode (`band-work/checks/verifier-r3-iso`): same counts; stage 2 fails
  as wanted (the folder does not implement stage 2).
- Verifier's own list (`band-work/verifier/CHECKS.md`, output `band-work/verifier/out/r3-pytest.txt`):
  497 passed, 0 failed, 0 skipped (448 original, 13 round-1 regression, 36 round-2), including
  export from one container and import into a second, and every [choice] row.
- Container level (`band-work/verifier/out/r3-docker.txt`): `docker build --no-cache` OK; no
  symlinks, nested `.git` or submodules; PORT unset healthy on 8080 in 0.34 s; `PORT=9123` 0.34 s;
  internal network, `--cpus 2 --memory 2g`. `RUN.md` followed verbatim on 3b9a0cc (unchanged since).
- Limits (2 vCPU, 2 GiB, 50 in flight): 1500 mixed requests in 2.0 s, slowest 0.412 s, no 5xx,
  balances sum to the seeded total, none negative; 50-way bursts on each idempotent path give one
  201 and 49 x 200; overdraft race: exactly the affordable 10 of 50; 50 concurrent logins each
  under 5 s; reset with 200 users 0.29 s; export and import 0.01 s or less; 20 rounds of 49
  requests racing reset/import: no 5xx; memory 204 MiB.
- Implementer's own suite `stage-1/tests/test_stage1.py`: 38 tests OK.
- Reproduction of the round-2 finding: `band-work/verifier/out/r3-repro.txt` (all 422, state untouched).
- Final isolated check by the Architect on the head of the repository:
  `band-work/checks/s1-final/` (result in the final report).

## Decisions

Recorded as **[choice]** rows in `ACCEPTANCE-stage-1.md` (A9, A11, C1, C5, C9, D3, E8, F6, F11, F13, H1),
each with its reason. Implementer choices outside the map: wrong method on a known path is 405
with the error envelope; an empty `display_name` is accepted.

## Verifier notes (from the PASS verdict; none blocks)

- N2. A body with an unknown field nested 3000 or more arrays deep is answered 400
  `malformed_request` although it is valid JSON; depth 2000 works (201, replay 200). No ordinary
  client sends this, and it is never a 5xx (tested to depth 100000).
- N4. Fixture passwords are hashed with scrypt n=1024 (signups n=8192): a real password hash, low cost.
- N5. Response timestamps are whole seconds (RFC 3339 with offset); ordering uses full precision
  internally and survives export/import.
- N6. Authenticated handlers parse the body while holding the global lock, so one very large body
  delays other requests while it parses. Not measurable with ordinary bodies.
- N7. Reset and import answer 422 for any internal error while building the state, so a genuine
  defect there would show as 422 rather than 5xx. None seen: every valid fixture and export in the
  list was accepted.
- Resolved in earlier rounds: N1 (idempotency-key length counted in bytes), N3 (long `offset`
  rejected), the 500 on a deeply nested replay, and the reset-race risk (not reproducible).

## Remaining risk (Verifier)

- The hidden suite is larger than the shipped one. Where the specification is open the build
  follows the map's [choice] rows (precedence order, non-object bodies are 400, impossible handle
  strings are 404, e-mail case-insensitivity, 0-amount request payable, pay copies the request
  note, 405 on a wrong method); a hidden check could read those differently.
- Tested on one host with Docker's CPU and memory limits; a slower grading host changes absolute
  timings (largest observed: 0.74 s against the 5 s limit).
