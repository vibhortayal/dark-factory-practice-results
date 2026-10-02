# Status

Run started: 2026-10-02T15:46Z (task dispatched to the Architect).

| Unit | State | Fix rounds (BLOCK verdicts) | Accepted revision | Elapsed |
|---|---|---|---|---|
| stage-1 (Pocketful: payments and settlements) | BUILDING (fix round 1) | 1 | none yet | 0h27 |

## Log

- 15:46Z Task received. Specification read in full (`pocketful/spec/stage-1.md`).
- 15:50Z Acceptance map written (`ACCEPTANCE-stage-1.md`). Both seats confirmed in the room.
  Handoff sent to Implementer and Verifier (Verifier prepares checks while the Implementer builds).
- 15:57Z Implementer reported revision 3b9a0cc76e72590543b26013078923c7fcca9814 (isolated harness 147/147, claimed stage 1). Handed to the Verifier.
- 16:11Z Verifier verdict on 3b9a0cc: **BLOCK** (fix round 1). Findings: (1) non-integer amount literals that round to an integer in binary floating point are accepted and move money (B4, C3, F3; also /requests, /splits, /settlements); (2) valid JSON amounts that overflow a float or exceed 4300 digits return 400 malformed_request instead of 422, also when they sit in an unknown field (A10). Supplied checks 147/147 in host and isolated mode; Verifier's own list 448/448 apart from the 13-case regression file for these findings. Evidence: `band-work/checks/verifier-r1-host`, `band-work/checks/verifier-r1-iso`, `band-work/verifier/`.
- 16:13Z Map updated: B4 wording made explicit; F6 and H1 [choice] rows added. Fix request sent to the Implementer.

## Decisions

Recorded as **[choice]** rows in `ACCEPTANCE-stage-1.md` (A9, A11, C1, C5, C9, D3, E8, F6, F11, F13, H1),
each with its reason.

## Verifier notes

From the verdict on 3b9a0cc (non-blocking; the Implementer was asked to address them in the fix revision):

- N1. `Idempotency-Key` length is counted in bytes when the key is sent as UTF-8 (128 x `é` → 422); ASCII 255/256 boundary correct.
- N2. Replay of a body with an unknown field nested 600 arrays deep returns 500 (RecursionError); depth 490 is fine.
- N3. `offset` longer than 18 digits is 422 although any integer 0 or more is valid.
- N4. Fixture passwords hashed with scrypt n=1024 (signups n=8192): real hash, low cost.
- N5. Timestamps truncated to whole seconds in responses; ordering uses full precision and survives export/import.
- Unsettled risk: a write racing `POST /_test/reset` might hit a vanished user and return 500; not reproduced in 2000 requests.
