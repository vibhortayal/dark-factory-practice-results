# Factory status

Run started: 2026-10-03 (architect dispatch).

| Unit | State | Accepted revision | Fix rounds (BLOCK count) | Notes |
|---|---|---|---|---|
| stage-1 | DONE | a8301bb9379977851db1c64ff468cbddc30011ff | 2 | Verifier PASS round 3 (verdict commit 9b3c5b8). Harness stage 1: 120 passed host + isolated; stage-2 suite fails on stage-1 (required); 392/392 verifier probes. Started 10:24 UTC, accepted 10:54 UTC (~30 min) |
| stage-2 | DONE | 0d321ce2763bcfb4f0732d0131fea33c3c4814a6 | 1 | Verifier PASS round 2 (verdict commit cbd829e). Suite 1 120 + suite 2 25 passed host + isolated; stage-3 suite fails on stage-2 (required); 392 + 98 API probes, 97 browser probes. Started 10:57 UTC, accepted 11:18 UTC (~21 min) |
| stage-3 | DONE | fcdb0a2b3d4257c041607cdad6e77c91e2187e76 | 0 | Verifier PASS round 1 (verdict commit 56e3be9). Suites 1/2/3 = 120/25/7 passed host + isolated; stage-4 suite fails on stage-3 (required); 392 + 98 + 174 API probes, 108 browser probes. Started 11:24 UTC, accepted 11:36 UTC (~12 min) |
| stage-4 | BUILDING | — | 0 | Map: acceptance/stage-4.md. Started 11:37 UTC |

## Verifier notes

### stage-1 (PASS on a8301bb, evidence verification/stage-1/)
- Round 1 BLOCK (228f8d1): F1 reset wrong-type fields returned 422 not 400; F2 moves reported field errors ahead of cutoff. Round 2 BLOCK (0487a51): F3 seeded party_size wrong type returned 400 not 422. All fixed.
- Non-blocking: reset time grows with fixture users (1000 users 7.37 s under --cpus 2; limit 10 s, would be passed near 1350 users; spec states no fixture size). scrypt n=2^12,r=8,p=1 (low work factor chosen for reset speed). Rejected reset leaves previous state. Spec-silent behaviours: signup without display_name 422; x@localhost accepted; emails case-insensitive; PATCH {} 200 unchanged; 405 method_not_allowed; body > 8 MiB 400; unparseable body without token 401. PATCH order follows the amended map.
- Not tested: exact cutoff equality; unshipped part of judging suite; real 2-vCPU host.

### stage-2 (PASS on 0d321ce, evidence verification/stage-2/)
- Round 1 BLOCK (21475bc): F1 UI threw on a replayed stage-1 receipt without table_ids after upgrade (row X3). Fixed (TK.tableIds helper, safe confirmation rendering).
- Non-blocking: safeConfirmation falls back to a bare confirmation with the reference if rendering throws. Lookup needs a signed-in user (signed out: reservation-error with login link). UI treats 5xx, non-JSON and a 15 s timeout as uncertain. GET /restaurants/{id} omits combinable when the fixture had none; duplicate unordered pairs de-duplicated; pairs stored/returned in combinable order. Stage-1 notes still apply (reset ~7.4 s at 1000 users; scrypt n=2^12).
- Not tested: unshipped part of the judging suite and human judgement of product quality; browsers other than Chromium; exact cutoff equality; real 2-vCPU host. Upgrade browser probe simulates "stage 1 behind the same origin" by answering the browser's calls from the stage-1 container until import.

### stage-3 (PASS on fcdb0a2, evidence verification/stage-3/)
- No BLOCK rounds.
- Non-blocking: (1) PATCH with an unparseable body on an unknown reference answers 400 in stage 3 (map decision 2) while stages 1–2 answer 404 (stage-1 amendment); spec states no order. (2) History "at" uses +00:00. (3) Seeded/imported reservations get one created entry at created_at (map decision 4). (4) Not probed (spec silent): policy with empty opening_hours; echo of unknown fields in the 201 policy body. (5) Earlier notes still apply (reset time, scrypt n=2^12, lookup needs sign-in, UI treats 5xx/timeouts as uncertain). (7) Verifier's first stage-1 list run used a stale derived script (7 false failures); regenerated and rerun 392/392.
- Not tested: shipped stage-3 sample is about a fifth of the graded suite; exact cutoff equality; browsers other than Chromium; real 2-vCPU host.
