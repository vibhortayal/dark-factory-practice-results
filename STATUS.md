# Status

Run started: 2026-10-02T19:45Z (dispatch received by Architect).

| Unit | State | Fix rounds (BLOCK verdicts) | Accepted revision | Elapsed |
|---|---|---|---|---|
| stage-1 | DONE | 1 | 76497f32a1e1cf9015d7b696827cfed4dfe81fcd | 42 min (19:45Z → 20:27Z) |

## Log

- 2026-10-02T19:45Z dispatch received: build stage 1 only (track pocketful).
- 2026-10-02T19:50Z acceptance map written: `ACCEPTANCE-MAP-stage-1.md` (rows A–K, decisions L1–L13).
- 2026-10-02T19:50Z handoff (5 parts, `handoffs/stage-1/`) sent to Implementer and Verifier.
- 2026-10-02T19:57Z Implementer committed d2d184df9240e0c25fffbd575b2efaff429c2d82 (stage-1 service).
- 2026-10-02T20:14Z Verifier BLOCK #1 on d2d184d (verification commit 94ac052): reset answers 422 instead of
  400 `malformed_request` for fixture fields of the wrong JSON type (§5; rows C19, D2). Everything else on the
  Verifier's list passed: harness host 147/147, isolated 147/147; own checks 134/135.
- 2026-10-02T20:17Z Architect agrees with the finding (§5 wrong-type rule applies to reset). Map rows C19 and I8
  revised and sent to both seats; fix routed to Implementer (`handoffs/stage-1/fix-round-1.md`).
- 2026-10-02T20:17Z Implementer committed 9f7cba3c0bba5b5b747ea078240a6aeba45c6abc (reset wrong-type → 400; import
  checks container types).
- 2026-10-02T20:20Z Verifier PASS for 9f7cba3 (verification commit b860485): harness host 147/147 (ver-3), isolated
  147/147 (ver-4); own checks 136/136; 7,736 requests, no 5xx; clean no-cache build; healthy in 0.43 s; 2 vCPU / 2 GiB.
- 2026-10-02T20:22Z Architect decision on Verifier note N7 (seeded non-string `note` gives 400 since the fix; seeded
  `visibility`/`amount` give 422): §5 names the three fields, not endpoints, so 422 is required for all three in
  seeded records. Map row C19 revised and sent to both seats (`handoffs/stage-1/change-after-round-2.md`). Not a
  BLOCK; fix-round count stays 1. Acceptance waits for a verdict on the revision that carries this change.
- 2026-10-02T20:23Z Implementer committed 76497f32a1e1cf9015d7b696827cfed4dfe81fcd (seeded `note` must be a string
  of at most 200 characters → 422).
- 2026-10-02T20:25Z Verifier PASS for 76497f3 (verification commit d61bd09): harness host 147/147 (ver-5), isolated
  147/147 (ver-6); own checks 137/137; 7,804 requests, no 5xx; clean no-cache build; healthy in 0.43 s; 2 vCPU / 2 GiB;
  1,500 mixed operations at 50 in flight conserved, no negative balance. N7 closed.
- 2026-10-02T20:26Z Architect final check, isolated mode, HEAD d61bd09 (stage-1/ identical to 76497f3):
  `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --mode isolated --out ../band-work/checks/arch-final-1`
  → stage 1 pass, 147 collected / 147 passed / 0 failed / 0 errors / 0 skipped. (The harness's stage-2 probe fails,
  as expected: stage 2 is not built.)
- 2026-10-02T20:27Z stage-1 ACCEPTED at 76497f32a1e1cf9015d7b696827cfed4dfe81fcd. No blocking finding open.

## Open non-blocking notes at acceptance (Verifier, round 3): N1, N2, N4, N5 below. N3 and N7 closed.

Remaining risk not tested (Verifier): the judge's full check set is larger than the supplied sample; behaviour
above 50 requests in flight and a wall clock stepping backwards; import exercised only with this service's own
states plus the Verifier's mutations of them.

## Verifier notes (round 2 adds N7; N3 closed)

- N7: seeded payment/request with non-string `note` in a reset fixture gives 400 (was 422 before the fix); routed
  as a map change, see log.

## Verifier notes (round 1, non-blocking)

- N1 size: `GET /activity` builds the caller's whole visible list under the global lock; 50 concurrent reads
  take ≤ 0.71 s at 20,000 stored payments and 3.46 s at 100,000 (limit 5 s). Spec sets no record limit.
- N2: no HTTP read timeout; a client sending fewer bytes than `Content-Length` holds one thread.
- N3: import does not check container types of state members (`payments: {}` loads as empty). Architect
  clarified row I8 so that this is rejected with 422; included in fix round 1.
- N4: scrypt N=4096, r=8, p=1 (chosen for reset time; lower than common guidance).
- N5 maintainability: small single-job modules; minor points (unused idempotency `status` and stored `splits`,
  `fixture.build` rebuilds indexes, `handlers_settlements` imports `parse_transfer` from `handlers_payments`,
  one-second timestamps so feed order rests on insertion order).
- N6: map row C19 to say 400 for wrong-typed fixture fields — done.
