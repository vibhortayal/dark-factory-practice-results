# Factory status

Run started: 2026-10-03 (architect dispatch).

| Unit | State | Accepted revision | Fix rounds (BLOCK count) | Notes |
|---|---|---|---|---|
| stage-1 | DONE | a8301bb9379977851db1c64ff468cbddc30011ff | 2 | Verifier PASS round 3 (verdict commit 9b3c5b8). Harness stage 1: 120 passed host + isolated; stage-2 suite fails on stage-1 (required); 392/392 verifier probes. Started 10:24 UTC, accepted 10:54 UTC (~30 min) |
| stage-2 | BUILDING | — | 0 | Map: acceptance/stage-2.md. Started 10:57 UTC |
| stage-3 | PLANNED | — | 0 | |
| stage-4 | PLANNED | — | 0 | |

## Verifier notes

### stage-1 (PASS on a8301bb, evidence verification/stage-1/)
- Round 1 BLOCK (228f8d1): F1 reset wrong-type fields returned 422 not 400; F2 moves reported field errors ahead of cutoff. Round 2 BLOCK (0487a51): F3 seeded party_size wrong type returned 400 not 422. All fixed.
- Non-blocking: reset time grows with fixture users (1000 users 7.37 s under --cpus 2; limit 10 s, would be passed near 1350 users; spec states no fixture size). scrypt n=2^12,r=8,p=1 (low work factor chosen for reset speed). Rejected reset leaves previous state. Spec-silent behaviours: signup without display_name 422; x@localhost accepted; emails case-insensitive; PATCH {} 200 unchanged; 405 method_not_allowed; body > 8 MiB 400; unparseable body without token 401. PATCH order follows the amended map.
- Not tested: exact cutoff equality; unshipped part of judging suite; real 2-vCPU host.
