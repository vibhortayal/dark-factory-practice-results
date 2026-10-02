# Status

Run started: 2026-10-02T15:46Z (task dispatched to the Architect).

| Unit | State | Fix rounds (BLOCK verdicts) | Accepted revision | Elapsed |
|---|---|---|---|---|
| stage-1 (Pocketful: payments and settlements) | BUILDING (fix round 2) | 2 | none yet | 0h58 |

## Log

- 15:46Z Task received. Specification read in full (`pocketful/spec/stage-1.md`).
- 15:50Z Acceptance map written (`ACCEPTANCE-stage-1.md`). Both seats confirmed in the room.
  Handoff sent to Implementer and Verifier (Verifier prepares checks while the Implementer builds).
- 15:57Z Implementer reported revision 3b9a0cc76e72590543b26013078923c7fcca9814 (isolated harness 147/147, claimed stage 1). Handed to the Verifier.
- 16:11Z Verifier verdict on 3b9a0cc: **BLOCK** (fix round 1). Findings: (1) non-integer amount literals that round to an integer in binary floating point are accepted and move money (B4, C3, F3; also /requests, /splits, /settlements); (2) valid JSON amounts that overflow a float or exceed 4300 digits return 400 malformed_request instead of 422, also when they sit in an unknown field (A10). Supplied checks 147/147 in host and isolated mode; Verifier's own list 448/448 apart from the 13-case regression file for these findings. Evidence: `band-work/checks/verifier-r1-host`, `band-work/checks/verifier-r1-iso`, `band-work/verifier/`.
- 16:13Z Map updated: B4 wording made explicit; F6 and H1 [choice] rows added. Fix request sent to the Implementer.
- 16:26Z Implementer reported revision d0f51eb002a64a8aba80651b25c19fab005c20da (exact decimal number parsing; notes N1-N3 and the reset race addressed; isolated harness 147/147). Handed to the Verifier.
- 16:43Z Verifier verdict on d0f51eb: **BLOCK** (fix round 2). Both round-1 findings confirmed fixed. New finding, a regression from the parser change: `POST /_test/reset` and `POST /_test/import` return 500 (OverflowError) for a number literal with an exponent of 10^18 or more in a fixture `balance`, seeded payment `amount`, or imported state (A9, A12, G4); expected 422 with no state change. Supplied checks 147/147 host and isolated; Verifier's saved list 461/461; 34 of 36 new cases pass. Evidence: `band-work/checks/verifier-r2-host`, `band-work/checks/verifier-r2-iso`, `band-work/verifier/out/r2-*.txt`, `band-work/verifier/test_15_round2.py`.
- 16:45Z Fix request (round 2) sent to the Implementer.

## Decisions

Recorded as **[choice]** rows in `ACCEPTANCE-stage-1.md` (A9, A11, C1, C5, C9, D3, E8, F6, F11, F13, H1),
each with its reason.

## Verifier notes

Current as of the verdict on d0f51eb (non-blocking):

- N1 (key length counted in bytes for UTF-8 keys): resolved in d0f51eb.
- N2 (500 on a replayed body nested 600 arrays deep): resolved for 5xx. Remaining: an unknown field nested 3000 or more arrays deep is answered 400 `malformed_request` although valid JSON (depth 2000 works). No ordinary client sends this.
- N3 (`offset` longer than 18 digits rejected): resolved up to 4000 digits.
- N4. Fixture passwords hashed with scrypt n=1024 (signups n=8192): real hash, low cost.
- N5. Response timestamps are whole seconds; ordering uses full precision internally and survives export/import.
- N6. Authenticated handlers parse the body while holding the global lock, so one very large body delays other requests while it parses. Not measurable with ordinary bodies (slowest request at 50 in flight: 0.742 s).
- Reset race risk from round 1: not reproduced; 20 rounds of 49 requests racing reset/import gave no 5xx on d0f51eb.
- Remaining risk: the hidden suite is larger than the shipped one; agreement on points the specification leaves open cannot be proven.
