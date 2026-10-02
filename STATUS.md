# Factory status

Run started: 2026-10-02T16:47Z (dispatch received by the Architect).

| Unit | State | Accepted revision | BLOCK verdicts (fix rounds) | Elapsed | Notes |
|---|---|---|---|---|---|
| stage-1 | DONE | 77409dda43334b784ca1125d2d990ba51478abf6 | 1 | 0h36 (16:47Z to 17:23Z) | Verifier PASS after one fix round. Final isolated check: `checks/s1-ver-04` (147 passed, `claimed stage: 1`). |
| stage-2 | BUILDING | n/a | 0 | started 17:23Z | Acceptance map: `acceptance/stage-2.md`. Handed to Implementer and Verifier. |
| stage-3 | PLANNED | n/a | 0 | n/a | |
| stage-4 | PLANNED | n/a | 0 | n/a | |

## Decisions

- Stage 1 open choices in the specification are resolved in `acceptance/stage-1.md`, rows marked **[D]**, each with its reason.
- A verdict names the full commit that last changed the stage folder. Later commits that touch only `acceptance/`, `handoffs/`, `verification/` or `STATUS.md` do not change the verified code; `git diff <revision> HEAD -- stage-N/` must be empty at acceptance.
- Map clarification after the stage 1 handoff (sent to both seats): row C1 applies to the authenticated API; a non-object JSON body on reset/import is 422 (B8, J6); an empty body on the pay path may be read as `{}`.
- Stage 2 open choices are resolved in `acceptance/stage-2.md`, rows marked **[D]** (UI as a pure client of the documented API, millisecond timestamps, capture error precedence, seeded authorisation defaults, authorise form on two screens).
- Language, framework and storage are left to the Implementer within the delivery limits (rows A1..A5).

## Verifier notes

### stage-1, verdict 1: BLOCK on f0f44189584133d95ec5bfc64c52c050450ddeb8 (17:13Z)

Blocking findings:
1. Rows C4, K3: a body over 2 MiB carrying an over-limit value (2,200,000-character note on `POST /payments` and `POST /requests`; 40,000 transfers on `POST /settlements`) is 400 `malformed_request`, expected 422 `validation_failed`. Cause: `MAX_BODY = 2 MiB` in stage-1/src/server.js.
2. Rows C8, C9, A11: a request head over 16 KiB (17,000-character `Idempotency-Key` or `limit`) is a bare 431 with no body, expected 422 with the error body. Cause: Node's default header limit, no `clientError` handler.

What the Verifier ran: clean `git archive` copy of the revision; `docker build --no-cache`; RUN.md followed literally; health in 0.13 s with and without `PORT`; `--network none` stays up. Harness host `checks/s1-ver-01` and isolated `checks/s1-ver-02`: `stage 1: pass`, `stage 2: fail`, `claimed stage: 1 on the shipped checks`, 147 passed, none skipped. Implementer's tests 21/21. Own probes (band-work/verifier/stage-1, output band-work/verifier/run-f0f4418/probes-2.txt): 100 checks, 5,019 requests, two containers on an internal network, 2 vCPU / 2 GiB, at most 50 in flight: 95 pass, 5 fail (LIM-1..LIM-4, GLB-2 = the two findings). No 5xx; slowest API request 0.30 s; reset of 200 users 1.14 s; all concurrency, idempotency (five paths, 50-way same key), export/import across containers and tamper cases pass.

Non-blocking notes from the Verifier: body over 2 MiB with only an unknown field is 400; nesting over 200 is 400 (a deep non-string note should be 422); idempotency scope uses the raw path (`rq%5F1` vs `rq_1`); fixture leniencies (omitted currency/minor_units/users/handle, seeded amount 0, seeded paid request has `payment_id: null`); whole-second timestamps; `MAX_BALANCE` and the status list defined three times; atomicity depends on handlers staying synchronous with nothing enforcing it; tests need Node on the host. Remaining risk: no soak, no load beyond 50 in flight, unbounded memory growth, the held-back checks.

Architect's action: the first three notes are stated rules answered with the wrong code, so they became rows A12 and A13 and are in scope of fix round 1, together with the duplicate constants and an enforceable atomicity guard.


### stage-1, verdict 2: PASS on 77409dda43334b784ca1125d2d990ba51478abf6 (17:22Z)

Findings 1 and 2 confirmed fixed (2,200,000-character note and 40,000 transfers are 422; 17,000-character key and `limit` are 422 with the error body).

What the Verifier ran: head equals the revision, `git diff --stat 77409dda HEAD -- stage-1/` empty, clean `git archive` copy. Delivery 8 of 8 (clean `docker build --no-cache`, healthy in 0.13 s with and without `PORT`, stays up with `--network none`, no OOM or restart). Harness host `checks/s1-ver-03` and isolated `checks/s1-ver-04`: `stage 1: pass`, `stage 2: fail`, `claimed stage: 1 on the shipped checks`, 147 passed, none skipped. Implementer's tests 26/26. Own probes: 105 checks, 5,233 requests, two containers on an internal network, 2 vCPU / 2 GiB, at most 50 in flight: 104 pass, 0 fail, 1 note-level deviation (LIM-7). Output band-work/verifier/run-77409dd/probes-2.txt. No 5xx, no bare response, no dropped connection; slowest API request 2.23 s (7.5 MB payment in a 50-way burst); peak memory 566 MiB of 2 GiB. Full concurrency and idempotency list re-run and passing on all five paths; rows A12 (order of answers on a 9 MiB and 48 MiB body, heads of 3 MiB and 24 MiB, nesting 201 and 5,000) and A13 (both spellings replay, undecodable escapes 404) hold; export/import across containers, tamper rejection 40 of 40, 2^53-1 balances, password hashing re-run. Stage boundary holds (no HTML, `/authorizations` 404, six `/me` fields).

Non-blocking notes: (1) a body that is not valid JSON and is nested deeper than 1,000 levels is 422 rather than 400 (the depth scan runs before the parser); (2) a head beyond 1 MiB is 422 whatever it holds, as row A12 states; (3) fixture leniencies unchanged (omitted currency/minor_units/users/handle, seeded amount 0, seeded paid request with `payment_id: null`); (4) whole-second timestamps, creation order inside a second; (5) constants now defined once, synchronous-handler rule enforced and audited by a test, RUN.md matches, tests need Node on the host, `./../constants` import spelling. Remaining risk: no soak, no load beyond 50 in flight, memory never pruned, the held-back checks.

Architect's acceptance: stage-1 accepted at 77409dda43334b784ca1125d2d990ba51478abf6. Note 1 is carried into the stage-2 map as a required correction in the copied code; stage-1/ itself is not reopened.
