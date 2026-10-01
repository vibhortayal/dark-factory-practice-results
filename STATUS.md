# Factory status

Run started: 2026-10-01T06:35Z (human dispatch). Track: pocketful.

| Unit | State | Accepted revision | Fix rounds | Elapsed | Notes |
|---|---|---|---|---|---|
| stage-1 | DONE | 8e4365295e6a47665793e0b2d7d9f6be6e7ff1eb | 1 | 0h35 (06:35Z-07:10Z) | Verifier PASS at head. Supplied checks 147/147, `claimed stage: 1`, isolated: `../checks/s1-verifier-r2-iso-01`. Round 1 BLOCK at 8409993 (5xx on malformed input, fixture float amounts) fixed. Open risk (not a spec contradiction): reset ≈7.4 ms per seeded user, >≈1300 users would pass 10 s; bounded in stage 2 (S2-6). |
| stage-2 | BUILDING | — | 2 | started 07:10Z | Acceptance map: `acceptance/stage-2.md` (S2-1..S2-12). Round 1: 10c60b0/aa13a56/78cd092 BLOCKED (capture error code, unlabelled select, decimal forms, retry identity). e792419: Verifier PASS 08:08Z (147/147, 35/35, claimed stage 2 isolated `../checks/s2-verifier-e792419-iso-01`), not accepted: zero capture amount in exponent form returns the wrong code (contradicts capture table). Fix round 2 with Implementer 08:12Z. |
| stage-3 | PLANNED | — | 0 | — | Starts only after stage-2 is DONE. |
| stage-4 | PLANNED | — | 0 | — | |

States: PLANNED, BUILDING, VERIFYING, BLOCKED, DONE.
Check outputs: `../checks/` (outside this repository, i.e. `band-work/checks/`).
