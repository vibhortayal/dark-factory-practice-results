# Stage 4 self-check (row by row)

Evidence at the reported revision (`stage-4/tests` against the built image, `docker run --cpus 2 --memory 2g`):
`test_api`, `test_concurrency`, `test_stage2_api`, `test_stage3_api` (the stage-1/2/3 suites, adapted only where stage 4
changes a response shape: payment objects gain `refund_of`, revisions gain `correction_batch_id`), `test_stage4_api`
(21 tests), together 169 tests OK; `test_browser` (34 Playwright tests, UI unchanged) OK. Supplied harness:
`claimed stage: 4`. Real stage-1 (8e43652), stage-2 (f8086da) and stage-3 (c00530d) containers were exported and imported
into stage 4 by hand (below).

| Rows | How checked | Result |
|---|---|---|
| B4.1 | Supplied suites 1-3 pass against stage 4; own stage-1/2/3 suites and browser suite rerun | OK |
| B4.2 B4.3 | Dockerfile/RUN.md; `git diff c00530d -- stage-1 stage-2 stage-3` empty | OK |
| B4.4 | Harness `claimed stage: 4`; `--all` isolated shows each folder claiming its own stage | OK |
| B4.5 | `Fuzz` (odd bodies for both endpoints incl. huge exponents and surrogates, odd paths and methods, every refund/batch field of an export mutated) | OK |
| B4.6 | `Refunds.test_idempotency`, `Refunds.test_concurrent_refunds`, `Batches.test_concurrency`, `Batches.test_success_shape_and_effects` (missing/oversized key, replay, reuse, failed attempt claims no key, 50 concurrent identical -> one 201) | OK |
| RF1-RF3 | `Refunds.test_permissions_and_targets`, `test_amounts_and_limits` (401/403 sender and third party/404/400/422, refund of refund 422 `invalid_refund_target`, invalid amounts, `2e2`, `200.0`) | OK |
| RF4 RF5 | `test_amounts_and_limits` (partial refunds up to the amount then one more unit; corrected to 0 -> nothing refundable; corrected up -> more), `test_shape_and_effects` (opposite direction, `refund_of`, null links, note/visibility, new id and instant) | OK |
| RF6-RF8 | `test_idempotency`, `test_funds_and_holds` (held funds cannot fund a refund), `test_permissions_and_targets` (request stays `paid`, authorization unchanged, no hold restored) | OK |
| RF9 RF10 | `test_shape_and_effects` (activity, statements of both parties with revision 1, `as_of` from `created_at`, private refund hidden from third party) | OK |
| RF11 RF12 | `test_concurrent_refunds` (50 in flight: exactly three 300-refunds of 1000, money conserved), `test_permissions_and_targets` and `Batches.test_settlement_rules` (settlement member refunded, `settlement_id` null, membership and original body unchanged) | OK |
| CR1-CR5 | `Refunds.test_correction_floor_and_immutability`, `test_debits_checked_against_available`; stage-3 corrections suite (single corrections unchanged); `correction_batch_id` null on revision 1 and single corrections | OK |
| CB1 CB2 | `Batches.test_auth_and_shape` (401, 403 non-operator before shape, key rules, non-object body, 11 bad shapes incl. 0/33 items and duplicate ids) | OK |
| CB3 CB7 | `test_item_errors_in_order` (field errors, 404, immutable capture/refund, stale, below refunded total, first failing item decides), `test_settlement_rules` (item errors before completeness), `test_precedence_funds_then_history` | OK |
| CB4 CB10 CB11 CB12 | `test_success_shape_and_effects` (operator not a party, request payment corrected, shared `recorded_at` later than every previous one, `correction_batch_id` on every revision, feed/replays unchanged, new statements, old snapshot frozen, `known_at` on the shared instant) | OK |
| CB5 CB6 | `test_settlement_rules` (incomplete settlement, differing effective instants, same instant in three offset spellings, single endpoint still `linked_payment_immutable`) | OK |
| CB8 CB9 | `test_precedence_funds_then_history` (item alone unaffordable, combined net affordable; historical overdraft; funds before history), `test_rejected_batch_leaves_no_trace` | OK |
| CB13-CB15 | `Batches.test_concurrency` (48 mixed single/batch corrections sharing expected revisions: at most one revision 2 each, all losers `stale_revision`, sums conserved in current and future-`as_of` views; 50 identical on one key -> one 201), `Capacity` | OK |
| UP4.1 UP4.2 | Real stage-1, stage-2 and stage-3 containers imported by hand (output below); `Upgrade.test_older_exports` (synthetic stage-3/2/1 shapes) | OK |
| UP4.3 | `Upgrade.test_round_trip` (refunds, refunded totals, batch ids and shared instants, idempotency records and replies, snapshots, counters; 4 invalid states -> 422 destination unchanged) | OK |
| UP4.4 | `test_browser` upgrade flow against the stage-4 image | OK |
| S4-8 | `Capacity.test_batch_on_a_big_wallet`: 20000-payment wallet, 50 in flight (32-item batches, corrections, refunds, `known_at` reads, statements): wall 1.0 s, max 1.0 s; a 32-item batch alone 0.04 s. Stage-3 capacity tests rerun in the suite: 60000+60000 export 35 MB reset 1.0 s / export 0.7 s / import 2.6 s, 1500 historical reads on 20k payments 1.8 s, 11.6 MB export import 0.8 s | OK |

Real upgrade output (container images: stage-1 8e43652, stage-2 f8086da, stage-3 c00530d; each had a seeded payment, a lost-response
payment (key key-lost), a 2-member settlement; stage 2/3 also an authorization with a non-final capture; stage 3 also a correction and a
statement snapshot): every import 204; lost payment replay 200; settlement replay returns its original body; a refund on the imported
payment 201 with `refund_of` set; imported payments expose `refund_of: null`; a batch correcting both imported settlement members at one
instant 201, a batch with one member only `incomplete_settlement`; stage-3 correction revisions import as `(1, None), (2, None)`; the
stage-3 statement snapshot pages identically after import (apart from the new `refund_of: null` field every payment object now carries).

Design: a refund is an ordinary payment record (`refund_of` set, own revision 1, links null, note/visibility copied) plus a per-target
refunded total; batches validate everything first (shape, items in order, settlement completeness, shared instants, combined current
`available`, historical boundaries for all proposed revisions at once), then append all revisions with one `recorded_at` and one
`correction_batch_id`; one critical section serialises refunds, single corrections and batches (stale revisions decide overlaps).
`historical_overdraft` takes all overrides of a batch at once. Revisions are exported with the batch id as an eighth element; older
exports (7 elements) default it to null. Generated ids stay fixed-width (`cb_0000000001`).

Known incomplete: none. Readings beyond S4-1..S4-9: wrong-typed or missing item fields in a batch are 422 `validation_failed`
(per the ordinary correction rule); a non-string `payment_id` item is a field error, so it is reported in input order with the other
item errors; duplicate-id detection considers string ids only.
