# Factory status

Run started: 2026-10-02T16:47Z (dispatch received by the Architect).

| Unit | State | Accepted revision | BLOCK verdicts (fix rounds) | Elapsed | Notes |
|---|---|---|---|---|---|
| stage-1 | BUILDING (fix round 1) | n/a | 1 | 0h28 at 17:15Z | f0f44189584133d95ec5bfc64c52c050450ddeb8 BLOCKED by the Verifier (rows C4, C8, C9, K3, A11). Fix request sent with new rows A12, A13. |
| stage-2 | PLANNED | n/a | 0 | n/a | Starts after stage-1 is accepted. |
| stage-3 | PLANNED | n/a | 0 | n/a | |
| stage-4 | PLANNED | n/a | 0 | n/a | |

## Decisions

- Stage 1 open choices in the specification are resolved in `acceptance/stage-1.md`, rows marked **[D]**, each with its reason.
- A verdict names the full commit that last changed the stage folder. Later commits that touch only `acceptance/`, `handoffs/`, `verification/` or `STATUS.md` do not change the verified code; `git diff <revision> HEAD -- stage-N/` must be empty at acceptance.
- Map clarification after the stage 1 handoff (sent to both seats): row C1 applies to the authenticated API; a non-object JSON body on reset/import is 422 (B8, J6); an empty body on the pay path may be read as `{}`.
- Language, framework and storage are left to the Implementer within the delivery limits (rows A1..A5).

## Verifier notes

### stage-1, verdict 1: BLOCK on f0f44189584133d95ec5bfc64c52c050450ddeb8 (17:13Z)

Blocking findings:
1. Rows C4, K3: a body over 2 MiB carrying an over-limit value (2,200,000-character note on `POST /payments` and `POST /requests`; 40,000 transfers on `POST /settlements`) is 400 `malformed_request`, expected 422 `validation_failed`. Cause: `MAX_BODY = 2 MiB` in stage-1/src/server.js.
2. Rows C8, C9, A11: a request head over 16 KiB (17,000-character `Idempotency-Key` or `limit`) is a bare 431 with no body, expected 422 with the error body. Cause: Node's default header limit, no `clientError` handler.

What the Verifier ran: clean `git archive` copy of the revision; `docker build --no-cache`; RUN.md followed literally; health in 0.13 s with and without `PORT`; `--network none` stays up. Harness host `checks/s1-ver-01` and isolated `checks/s1-ver-02`: `stage 1: pass`, `stage 2: fail`, `claimed stage: 1 on the shipped checks`, 147 passed, none skipped. Implementer's tests 21/21. Own probes (band-work/verifier/stage-1, output band-work/verifier/run-f0f4418/probes-2.txt): 100 checks, 5,019 requests, two containers on an internal network, 2 vCPU / 2 GiB, at most 50 in flight: 95 pass, 5 fail (LIM-1..LIM-4, GLB-2 = the two findings). No 5xx; slowest API request 0.30 s; reset of 200 users 1.14 s; all concurrency, idempotency (five paths, 50-way same key), export/import across containers and tamper cases pass.

Non-blocking notes from the Verifier: body over 2 MiB with only an unknown field is 400; nesting over 200 is 400 (a deep non-string note should be 422); idempotency scope uses the raw path (`rq%5F1` vs `rq_1`); fixture leniencies (omitted currency/minor_units/users/handle, seeded amount 0, seeded paid request has `payment_id: null`); whole-second timestamps; `MAX_BALANCE` and the status list defined three times; atomicity depends on handlers staying synchronous with nothing enforcing it; tests need Node on the host. Remaining risk: no soak, no load beyond 50 in flight, unbounded memory growth, the held-back checks.

Architect's action: the first three notes are stated rules answered with the wrong code, so they became rows A12 and A13 and are in scope of fix round 1, together with the duplicate constants and an enforceable atomicity guard.
