# Factory status

Run started: 2026-10-01T06:35Z (human dispatch). Track: pocketful.

| Unit | State | Accepted revision | Fix rounds | Elapsed | Notes |
|---|---|---|---|---|---|
| stage-1 | DONE | 8e4365295e6a47665793e0b2d7d9f6be6e7ff1eb | 1 | 0h35 (06:35Z-07:10Z) | Verifier PASS at head. Supplied checks 147/147, `claimed stage: 1`, isolated: `../checks/s1-verifier-r2-iso-01`. Round 1 BLOCK at 8409993 (5xx on malformed input, fixture float amounts) fixed. Open risk (not a spec contradiction): reset ≈7.4 ms per seeded user, >≈1300 users would pass 10 s; bounded in stage 2 (S2-6). |
| stage-2 | BUILDING | — | 1 | started 07:10Z | Acceptance map: `acceptance/stage-2.md`. Handed to Implementer 07:13Z. Rev 10c60b0 BLOCKED by Verifier 07:50Z (F1 capture error code above 1e9, F2 unlabelled select); S2-8..S2-12 added. Fix round 1 with Implementer. |
| stage-3 | PLANNED | — | 0 | — | Starts only after stage-2 is DONE. |
| stage-4 | PLANNED | — | 0 | — | |

States: PLANNED, BUILDING, VERIFYING, BLOCKED, DONE.
Check outputs: `../checks/` (outside this repository, i.e. `band-work/checks/`).
