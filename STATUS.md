# Factory status

Run started: 2026-10-01T06:35Z (human dispatch). Track: pocketful.

| Unit | State | Accepted revision | Fix rounds | Elapsed | Notes |
|---|---|---|---|---|---|
| stage-1 | DONE | 8e4365295e6a47665793e0b2d7d9f6be6e7ff1eb | 1 | 0h35 (06:35Z-07:10Z) | Verifier PASS at head. Supplied checks 147/147, `claimed stage: 1`, isolated: `../checks/s1-verifier-r2-iso-01`. Round 1 BLOCK at 8409993 (5xx on malformed input, fixture float amounts) fixed. Open risk (not a spec contradiction): reset ≈7.4 ms per seeded user, >≈1300 users would pass 10 s; bounded in stage 2 (S2-6). |
| stage-2 | DONE | f8086da438d3fa7dd38c886decd4ed4a2b8c9dd8 | 2 | 1h14 (07:10Z-08:24Z) | Verifier PASS at head. Supplied checks 147/147 + 35/35, `claimed stage: 2`, isolated: `../checks/s2-verifier-f8086da-iso-01`; stage 1 still `claimed stage: 1` (`../checks/s1-verifier-after-s2-f8086da-iso-01`). Round 1: capture error code above 1e9, unlabelled select, decimal forms, retry identity (10c60b0/aa13a56/78cd092 blocked). Round 2: zero capture amount in exponent form. Accepted risks (no spec contradiction): screens fetch at most 200 items; millisecond authorisation timestamps; scrypt N=512 for seeded users. |
| stage-3 | DONE | c00530dd77a2caff402419f3c01c2a48a0368148 | 1 | 6h29 (08:24Z-14:53Z; the Verifier's first verdict message of 09:52Z never reached the room, the rerun verdict arrived 14:50Z) | Verifier PASS at head. Supplied checks 147/147 + 35/35 + 6/6, `claimed stage: 3`, isolated: `../checks/s3-verifier-c00530d-iso-02`; stage 2 and stage 1 folders still claim their stages (`../checks/s2-verifier-after-s3-c00530d-iso-02`, `../checks/s1-verifier-after-s3-c00530d-iso-02`). Round 1: d5a23ed blocked (own export above 8 MiB not importable), 15af6a2 superseded (INCONCLUSIVE), S3-12/S3-13 added. Accepted risks (no spec contradiction at stated sizes): per-wallet latency grows linearly, 50 heavy historical requests pass 5 s above about 50000 payments in one wallet; the 8 MiB body limit remains in stage-1/stage-2 (verified at 20000 + 20000). |
| stage-4 | BUILDING | — | 0 | started 14:53Z | Acceptance map: `acceptance/stage-4.md` (S4-1..S4-9). Handed to Implementer 14:58Z. |

States: PLANNED, BUILDING, VERIFYING, BLOCKED, DONE.
Check outputs: `../checks/` (outside this repository, i.e. `band-work/checks/`).
