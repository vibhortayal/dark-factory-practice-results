# Status

Run started: 2026-10-02T01:36Z (dispatch received by Architect).

| Unit | State | Fix rounds (BLOCK verdicts) | Accepted revision | Elapsed |
|---|---|---|---|---|
| stage-1 (pocketful: payments and settlements) | DONE | 1 | 29fbb347f0902fcfa16983c1d0d8f027036af02b | 0h30 |

Later stages: not in scope for this run (stage 1 only).

## Log

- 01:36Z dispatch received; spec `pocketful/spec/stage-1.md` read in full.
- 01:46Z acceptance map written (`acceptance/stage-1.md`); both seats confirmed in the room;
  stage-1 handed to the Implementer.
- 01:48Z Implementer committed a3e78912c0db2886188becb57f3e88410d355f0b; harness isolated 147/147
  (`../checks/impl-02-isolated`); handed to the Verifier.
- 02:00Z Verifier verdict on a3e7891: BLOCK (round 1 of at most 5). Harness isolated 147/147
  (`../checks/ver-01-isolated`), but four findings contradict the spec: F1 500 on huge-exponent JSON
  number (§5 no 5xx; rows A13/D4/G5); F2 framework errors (TRACE etc.) return 501/HTML, not the
  envelope (§5; D1/A13); F3 `limit=4%0A` accepted (§5 plain digits; D5/G20); F4 empty-body reset
  returns 204 and wipes state (§5/§3.3; C11/D2). Routed to the Implementer.
- 02:03Z Implementer committed fix revision 29fbb347f0902fcfa16983c1d0d8f027036af02b (F1-F4);
  harness isolated 147/147 (`../checks/impl-03-isolated`); handed to the Verifier.
- 02:05Z Verifier verdict on 29fbb34 (repository head at the time): PASS. Clean no-cache build,
  harness isolated 147/147 (`../checks/ver-02-isolated`), 70/70 own functional checks, 17/17 load
  checks at 50 in flight under 2 vCPU / 2 GiB, all four round-1 findings rechecked fixed. No open
  finding contradicts the specification.
- 02:06Z Architect final check on 29fbb34, `--mode isolated`: stage 1 pass, 147 collected / 147
  passed / 0 failed, errors, skipped, deselected (`../checks/arch-final-isolated/report.json`);
  stage-2 probe fails as required (no later-stage surface). Unit accepted: DONE.
  Commits after 29fbb34 change only this status file.

## Remaining risk (Verifier notes, not findings)

- The supplied suite is only part of the judging suite; recorded choices 1-10 in
  `acceptance/stage-1.md` could be read differently by hidden tests.
- An `Idempotency-Key` too long for the HTTP layer (70 kB) gets 431 with the envelope, not 422
  (255 / 256 / 10 kB behave as specified).
- Not tested beyond the stated limits (50 in flight, a few hundred seeded users, 16 MiB bodies).
