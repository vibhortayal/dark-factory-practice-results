# Stage 1 — Verifier verdict, round 2: BLOCK

Rows: C3/E4 (F3); F1 (C3/E2) and F2 (MV5) fixed; all other rows pass · Revision: 0487a51e7158739a7bb4e4a0c593528b6bc1fdd0 · Files: stage-1/app/snapshot.py (`_posint`, `_seed_reservation`) · Command: `bash verification/stage-1/run.sh 0487a51e7158739a7bb4e4a0c593528b6bc1fdd0 <evidence-dir>` then `probe.py` · Expected / actual: 392 own checks pass / 390 pass, 2 fail (one finding) · Repro: F3 below · Next: Implementer

Tree clean; HEAD = 0487a51. Image built `--no-cache` from `git archive` of the revision.

## Round-1 findings
- F1 fixed: reset with wrong-typed `users`, `restaurants`, `slot_minutes`, restaurant `id`, user `email` → 400 `malformed_request` (C3.4b–f pass); right-type invalid values still 422 (C7.2a–d, harness).
- F2 fixed: moves `[{P, party_size:0}]` and `[{P},{H, party_size:0}]` → 409 `cutoff_passed` (MV5.2e–f pass).

## Blocking finding

### F3 — reset: seeded reservation `party_size` of a wrong type gives 400 (rows C3, E4; spec §5, §4; map amendment 2)
Spec §5: "Endpoint-specific field rules take precedence: invalid `party_size` values (including
strings and booleans) … are 422 `validation_failed`." §4: seeded reservations have "the same fields
as a `POST /reservations` body plus `id`, `reference` and `user_id`."

Repro: `POST /_test/reset` with a valid fixture whose `reservations` is
`[{"id":"x1","reference":"ABCDEF","user_id":"u_ada","restaurant_id":"r_anker","table_id":"t_1","starts_at_local":"2027-09-23T19:00","party_size":"4"}]`
Actual: `400 {"error":{"code":"malformed_request","message":"party_size must be an integer"}}`
Expected: `422 validation_failed`. Same with `"party_size": true` (checks C3.5a, C3.5b).
`party_size: 0` and `starts_at_local` with seconds are correctly 422 (C3.5c–d); wrong-typed
`restaurant_id` / `table_id` / `starts_at_local` are correctly 400 (C3.5e–g). The Implementer
reported this deviation itself for this revision.

## What was run
| What | Result |
|---|---|
| Clean build, start under `--cpus 2 --memory 2g` on an internal network, default port, port mapping | OK; healthy after 0.34 s; no outbound |
| Harness `--stage 1 --mode host` (`checks/verifier-s1-r2-host`) | stage 1: 120 passed; stage-2 suite: fail (as required) |
| Harness `--stage 1 --mode isolated` (`checks/verifier-s1-r2-isolated`) | stage 1: 120 passed; stage-2 suite: fail (as required) |
| Implementer's tests | 23 OK |
| Own probes, whole saved list + 19 round-2 checks for the changed code and the map amendment | 392 checks: 390 pass, 2 fail (F3) |

Round-2 checks that pass: PATCH order per the amended map (404 → unparseable 400 → cancelled →
cutoff → field validation: P2.3a–e); reset hashing outside the lock — 20 concurrent resets with
150 concurrent reads only ever show one complete fixture, reset racing 96 bookings and 20 signups
gives no 5xx and leaves exactly the fixture after it returns (C3.6a–e); last of 502 seeded users
can log in at once (C3.6f). Container not OOM-killed, nothing on stderr.

## Notes (not blocking)
1. Reset with 502 users took 7.56 s under `--cpus 2` (limit 10 s; spec states no fixture size). At
   about 15 ms per user the limit would be passed near 650 users.
2. `from_fixture` hashes all users before it validates restaurants and reservations, so a rejected
   large fixture still pays the full hashing time.
3. After a rejected reset the previous state stays in place (spec does not say).
4. Unchanged from round 1: signup without `display_name` → 422; `x@localhost` accepted; emails
   case-insensitive; `PATCH {}` → 200 unchanged; 405 `method_not_allowed`; body over 8 MiB → 400;
   unparseable body without a token → 401.
5. Maintainability: `_posint` now decides both type and range; the party_size exemption needs its
   own path (the request-side `validate.party_size` already encodes the rule).

## Remaining risk not tested
Exact cutoff equality; the hidden part of the judging suite; a real 2-vCPU host.
