# Status

Run started: 2026-10-01T16:26Z (dispatch received by Architect).

| Unit | State | Accepted revision | Fix rounds | Elapsed |
|---|---|---|---|---|
| stage-1 (pocketful) | BUILDING (fix round 1) | — | 1 / 5 | 0h32 |

## Log

- 16:26Z dispatch received; spec read in full; both seats confirmed in room.
- 16:30Z acceptance map committed (8b1e88d); 6-part handoff sent to Implementer.
- 16:40Z Implementer reported 03d8b1959082e0f2417eb8b35e544985c5bb7897; harness isolated 147/147 (`../checks/impl-03-isolated`).
- 16:55Z Verifier PASS for 03d8b19 (harness isolated 147/147 in `../checks/verifier-01-isolated`, 824 own checks in `../checks/verifier-01-own`), with notes.
- 16:58Z Architect did NOT accept: four of the Verifier's notes contradict spec sentences and cannot be waived. Fix round 1 sent to Implementer:
  - FR1-1 (§5 E7): Idempotency-Key longer than ~64 kB → 400 `malformed_request`; spec says any key outside 1..255 chars → 422 `validation_failed`.
  - FR1-2 (§5 E1/E3): body over 1 MiB → HTTP 413; 413 is not a specified status, and an over-long `note` must be 422 `validation_failed`.
  - FR1-3 (§7 I2/I6): replay through an equivalent percent-encoded path (`/requests/rq%5F1/pay`) → 409 `request_not_pending` instead of 200 replay.
  - FR1-4 (§10 X4): import accepts tampered/invalid `state` with 204; spec says an invalid state → 422, destination unchanged.

Evidence: harness outputs go to `../checks/<name>` (outside this repository, per the task).
