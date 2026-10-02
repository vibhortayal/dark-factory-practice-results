# Verdict, round 1 — Pocketful stage 1

Rows: C19, D2 (finding); all rows A–L exercised · Revision: d2d184df9240e0c25fffbd575b2efaff429c2d82 · Files: stage-1/app/fixture.py (finding); whole of stage-1/ inspected · Command: `verify.sh up|checks|down` (Verifier scripts, band-work/verifier/stage-1) and the supplied harness in host and isolated mode · Expected / actual: reset with a wrong-typed fixture field must be 400 `malformed_request`, is 422 `validation_failed` · Repro: see finding 1 · Next: Implementer.

## BLOCK for revision d2d184df9240e0c25fffbd575b2efaff429c2d82

One blocking finding. Everything else on the list passed.

### Finding 1 (blocking) — reset answers 422 for a fixture field of the wrong JSON type

- Specification §5: "400 `malformed_request` — Unparseable body, or a field of the wrong JSON type" and "Reserve 400 `malformed_request` for a body that does not parse or a field of the wrong type." §5 also says "Use the specified HTTP status and `code`"; §3.3/§4 name only one reset-specific error (negative `balance` -> 422), so the general rule applies to every other fixture field.
- Acceptance map: C19 (and D2). C19 as written accepts any 4xx; the specification is stricter and is the measure.
- Reproduction (service on $B):
  `curl -s -X POST $B/_test/reset -H 'Content-Type: application/json' -d '{"currency":"EUR","minor_units":2,"users":"x"}'`
  actual: `422 {"error":{"code":"validation_failed","message":"users must be an array"}}`
  expected: `400` with code `malformed_request`.
- Same result (422, expected 400) for: `users: [5]`; a user's `id`, `email`, `password`, `display_name` or `handle` that is not a string; `currency: 5`; `minor_units: "2"`; `payments: "x"`; `requests: {}`; `settlement_operator_ids: "u_op"` and `settlement_operator_ids: [5]`.
- Not part of the finding, and must stay as they are: right type but bad value stays 422 (`balance` below zero, `minor_units: 7`, `users` missing, duplicate handle); state stays untouched after every rejected reset (it does today). A `balance` of the wrong JSON type is accepted as either 400 or 422, because §5's `amount` rule can be read to cover it.
- Check: FX-07 in the check list. It was added after the first run of the list, when re-reading §5 against the reset endpoint; the earlier check FX-04 only asked for "a 4xx".

### What was run

1. Repository: HEAD = d2d184df9240e0c25fffbd575b2efaff429c2d82, tree clean before and after.
2. Supplied checks, from the kickoff checkout:
   - `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/ver-1` -> stage 1 pass, 147 collected, 147 passed, 0 failed, 0 errors, 0 skipped, 0 deselected.
   - same with `--out ../band-work/checks/ver-2 --mode isolated` -> stage 1 pass, 147 passed.
   - The harness's stage-2 probe against this folder fails (no UI), as it should: stage 1 does not already satisfy stage 2.
3. Delivery (verify.sh up/down, on a clean `git archive` export of the revision):
   - `docker build --no-cache` succeeds; image 43 MB; `Dockerfile` and `RUN.md` present; no nested repository.
   - RUN.md command run exactly as written (`docker build -t pocketful-stage-1 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-1`): `/health` 200, signup 201.
   - `-e PORT=9123 -p ...:9123`: healthy after 0.43 s (limit 60 s). No `PORT`: healthy on 8080.
   - `--network none`: container stays up. The whole HTTP suite ran against two containers on a docker `--internal` network (outbound connect from that network fails), each with `--cpus 2 --memory 2g`.
   - After the suite: no OOM kill, no restart, 193 MiB / 2 GiB used, no traceback in the logs. `docker restart`: healthy after 0.43 s, reset and login work.
4. Own checks (`verify.sh checks`): 135 checks = 128 scripted + 7 whole-run assertions; 134 pass, 1 fail (FX-07, finding 1), 0 non-blocking failures; 7,615 requests; no 5xx; every error body well-formed; every response `application/json; charset=utf-8`; slowest ordinary request 0.34 s (login, 50 concurrent), slowest test-control request 1.50 s (reset with 200 users and 500 payments). 1,500 mixed operations at 50 in flight: sum of balances conserved, no negative balance observed, slowest request 0.05 s.
5. Source read once (stage-1/app, 1,097 lines): scrypt with a 16-byte random salt per password and constant-time compare; no plaintext password in the export; no later-stage code; stage 2–4 routes answer 404 (NX-01).

### Notes (do not block)

- N1, size: `GET /activity` builds the caller's whole visible list under the global lock on every call. With 20,000 stored payments, 50 concurrent feed reads took at most 0.71 s; with 100,000 stored payments, 3.46 s (limit 5 s). The specification sets no limit on stored records.
- N2: the HTTP server sets no read timeout; a client that sends fewer bytes than its `Content-Length` keeps one thread waiting indefinitely. No statement in the specification covers it.
- N3, by reading `store.py`: import iterates state members without checking their container type, so `payments: {}` in place of an array loads as "no payments". The state format is the service's own, so this is not provably "an invalid state"; removing a member or replacing it with a scalar is rejected with 422 (EX-08 passes).
- N4: scrypt cost is N=4096, r=8, p=1, lower than common guidance, chosen for reset time. The specification names the function, not a cost.
- N5, maintainability: small modules with one job each, and RUN.md's module table matches the code. Minor: the idempotency record's `status` and the stored `splits` are written but never read outside export; `fixture.build` reserves user indexes and then clears and rebuilds them; `handlers_settlements` imports `parse_transfer` from `handlers_payments`; timestamps have one-second resolution, so feed order rests on insertion order.
- N6: map row C19 should say 400 `malformed_request` for wrong-typed fixture fields (Architect).

### Remaining risk not tested

- The judge's full check set is larger than the supplied sample.
- Behaviour above 50 requests in flight, and a wall clock that steps backwards.
- Import was exercised only with states this service produced, plus the mutations in EX-05/EX-08.

Verification commit: the commit that adds this file (only `verification/stage-1/CHECKLIST.md` and this file).
