# Factory status

Run started: 2026-10-01T06:35Z (human dispatch). Track: pocketful.

| Unit | State | Accepted revision | Fix rounds | Elapsed | Notes |
|---|---|---|---|---|---|
| stage-1 | DONE | 8e4365295e6a47665793e0b2d7d9f6be6e7ff1eb | 1 | 0h35 (06:35Z-07:10Z) | Verifier PASS at head. Supplied checks 147/147, `claimed stage: 1`, isolated: `../checks/s1-verifier-r2-iso-01`. Round 1 BLOCK at 8409993 (5xx on malformed input, fixture float amounts) fixed. Open risk (not a spec contradiction): reset ≈7.4 ms per seeded user, >≈1300 users would pass 10 s; bounded in stage 2 (S2-6). |
| stage-2 | DONE | f8086da438d3fa7dd38c886decd4ed4a2b8c9dd8 | 2 | 1h14 (07:10Z-08:24Z) | Verifier PASS at head. Supplied checks 147/147 + 35/35, `claimed stage: 2`, isolated: `../checks/s2-verifier-f8086da-iso-01`; stage 1 still `claimed stage: 1` (`../checks/s1-verifier-after-s2-f8086da-iso-01`). Round 1: capture error code above 1e9, unlabelled select, decimal forms, retry identity (10c60b0/aa13a56/78cd092 blocked). Round 2: zero capture amount in exponent form. Accepted risks (no spec contradiction): screens fetch at most 200 items; millisecond authorisation timestamps; scrypt N=512 for seeded users. |
| stage-3 | BUILDING | — | 1 | started 08:24Z | Acceptance map: `acceptance/stage-3.md` (S3-1..S3-13). Handed to Implementer 08:26Z. d5a23ed BLOCKED by Verifier 09:00Z (F1: cannot import its own export above 8 MiB); all else held (147/147, 35/35, 6/6, claimed stage 3). Fix round 1 with Implementer 09:05Z. |
| stage-4 | PLANNED | — | 0 | — | Starts only after stage-3 is DONE. |

States: PLANNED, BUILDING, VERIFYING, BLOCKED, DONE.
Check outputs: `../checks/` (outside this repository, i.e. `band-work/checks/`).
