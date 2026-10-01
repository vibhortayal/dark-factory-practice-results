# Acceptance map — Pocketful stage 4

Sources: `dark-factory-wearedevs/pocketful/spec/stage-4.md` (whole file) on top of
`stage-3.md`, `stage-2.md` and `stage-1.md` (all still in force). Target folder: `stage-4/`,
created as a copy of the accepted `stage-3/` (revision c00530dd77a2caff402419f3c01c2a48a0368148) and extended. `stage-1/`,
`stage-2/` and `stage-3/` must not change.

Check codes: `H` = supplied harness suites (partial sample; a stage-4 run executes suites 1-4),
`T` = own black-box HTTP test against the built container, `C` = concurrency test,
`B` = browser test, `I` = inspection. A row is accepted only on Verifier evidence for the head
revision.

## B4 — Carry-over and delivery

| Row | Requirement | Check |
|---|---|---|
| B4.1 | Every row of `acceptance/stage-1.md`, `stage-2.md` and `stage-3.md` (with decisions Q1-Q8, S2-1..S2-12, S3-1..S3-13) still holds for `stage-4/`, except where this map states a stage-4 change. | H suites 1-3, earlier own tests rerun against the stage-4 image, T, B |
| B4.2 | `stage-4/` is a complete buildable service (source, `Dockerfile`, `RUN.md`, own tests, no nested `.git`), runs alone with `-e PORT`, no outbound network at run time, resource limits of stage-1 §2. | I + H `--mode isolated` |
| B4.3 | `stage-1/`, `stage-2/`, `stage-3/` are byte-identical to their accepted revisions. | I: `git diff <accepted> -- stage-1 stage-2 stage-3` empty |
| B4.4 | Harness prints `claimed stage: 4`; `--all` shows every folder claiming its own stage. | H |
| B4.5 | No request yields a 5xx or a non-§5 error body (Q8), including the two new endpoints with odd input. | T fuzz |
| B4.6 | Ten idempotent write paths, each with the full stage-1 §7 rules independently (K1-K11 for refunds and correction batches). | T + C |

## RF — Refunds

| Row | Requirement | Check |
|---|---|---|
| RF1 | `POST /payments/{payment_id}/refunds` body `{"amount": n}` requires auth (401) and an `Idempotency-Key` (missing → 400, > 255 → 422). Only the original receiver may refund: any other authenticated caller (sender or third party) → 403 `forbidden`; unknown payment → 404 `not_found`. | T/H |
| RF2 | Target may be a direct payment, a request payment, a capture or a settlement member; never a refund: refund of a refund → 422 `invalid_refund_target`. | T |
| RF3 | Invalid `amount` (missing, non-integral, below 1, above 1000000000, string, boolean, null) → 422 `validation_failed`. Integral forms (`200.0`, `2e2`) are valid. | T |
| RF4 | Cumulative refunds may not exceed the payment's current corrected amount (latest revision): otherwise 422 `refund_exceeds_payment`. Refunding exactly up to the amount succeeds; a payment corrected to 0 cannot be refunded at all. | T: partial refunds summing to the amount, then one more unit |
| RF5 | Success → 201 with a new payment in the opposite direction (`from` = original receiver, `to` = original sender), `refund_of` = target payment id, `request_id: null`, `authorization_id: null`, `settlement_id: null`, original `note` and `visibility`, new `payment_id` and `created_at`, in the ordinary payment shape. | T/H |
| RF6 | Replay → 200 with the original body; same key different body → 409 `idempotency_key_reuse`; failed attempts claim no key; concurrent identical → one 201. | T + C |
| RF7 | The refund moves existing money from the receiver's `available` funds atomically, or fails 409 `insufficient_funds` with nothing changed (held funds cannot fund a refund). | T |
| RF8 | Refunds never reopen a request (stays `paid`, same `payment_id`) or an authorisation (status, `captured_amount`, `remaining_amount`, `payment_ids` unchanged) and never restore a released hold. | T |
| RF9 | Every payment object in every response carries `refund_of` (null for non-refunds): payments, pay, capture, settlement members, activity, statement entries, replays of responses created in stage 4. | T/H |
| RF10 | A refund payment is an ordinary feed item under the visibility rule, appears in both parties' statements as a movement with its own revision 1, and counts in `as_of` views from its `created_at`. | T |
| RF11 | Concurrent refunds on one payment with different keys never exceed the payment's corrected amount in total; money conserved. | C |
| RF12 | A settlement member may be refunded under the same rules; the refund has `settlement_id: null` and settlement membership (and the settlement's original response) never changes. | T |

## CR — Corrections with refunds

| Row | Requirement | Check |
|---|---|---|
| CR1 | Stage-3 single corrections remain available for ordinary direct and request payments. | T/H suite 3 |
| CR2 | Captures and refund payments cannot be corrected (single or batch): 422 `linked_payment_immutable`. Settlement members still cannot be corrected by the single-payment endpoint: 422 `linked_payment_immutable`. | T |
| CR3 | A correction (single or batch) cannot reduce a payment below its already-refunded total: 422 `refund_exceeds_payment`, nothing changes. Reducing exactly to the refunded total succeeds. | T |
| CR4 | Correction debits are checked against `available` funds (409 `insufficient_funds`). | T |
| CR5 | Each revision in `GET /payments/{id}/revisions` and in correction responses exposes `correction_batch_id` (null for revision 1 and for single corrections). | T |

## CB — Correction batches

| Row | Requirement | Check |
|---|---|---|
| CB1 | `POST /correction-batches` requires a settlement operator and an idempotency key, with the settlement rules: no token → 401; authenticated non-operator → 403 `forbidden`. | T/H |
| CB2 | Body `{"corrections": [{payment_id, expected_revision, amount, effective_at, reason}, ...]}`: 1..32 objects with distinct `payment_id`s, otherwise 422 `validation_failed` (missing/non-array `corrections`, non-object item, 0 or 33 items, duplicate id). Unknown fields ignored. | T |
| CB3 | Every item has the ordinary correction fields and validation (stage-3 CO3): invalid → 422 `validation_failed`; unknown payment → 404; stale `expected_revision` → 409 `stale_revision`; capture or refund → 422 `linked_payment_immutable`; below refunded total → 422 `refund_exceeds_payment`. Effective times cannot be later than now. | T |
| CB4 | The operator may correct ordinary, request and settlement payments, including payments the operator is not a party to. | T/H |
| CB5 | Correcting any settlement member requires every member of that settlement in the batch, otherwise 422 `incomplete_settlement`. | T |
| CB6 | Members of one settlement must carry identical effective instants (different offset spellings of the same instant are equal), otherwise 422 `validation_failed`. | T |
| CB7 | Error precedence: item errors in input order (first failing item decides) → settlement completeness → resulting current `available` funds (409 `insufficient_funds`) → historical `total` and `available` at every effective/event boundary (409 `historical_overdraft`). | T: batches combining two error kinds |
| CB8 | Affordability is the combined (net) effect of all proposed revisions: a batch is affordable when every wallet's resulting `available` is non-negative, even if one item alone would not be. | T |
| CB9 | A rejected batch leaves history, balances, statements, snapshots and idempotency records unchanged (all-or-nothing). | T |
| CB10 | Success → 201 `{correction_batch_id, recorded_at, revisions}` with `revisions` in input order; each revision has the stage-3 revision shape plus `correction_batch_id`. All new revisions share one `recorded_at`, strictly later than the previous `recorded_at` of every member. | T/H |
| CB11 | Original payments and receipts never change: `GET /activity`, original payment replays and the original settlement replay return their original bodies after a batch. | T |
| CB12 | New statements and `/me` views reflect the new revisions (with `known_at` semantics on the shared `recorded_at`); earlier snapshot tokens keep paging their frozen entries. | T |
| CB13 | Replay → 200 with the original batch response; same key different body → 409; concurrent identical → one 201. | T + C |
| CB14 | Concurrent corrections (single or batch, any mix) sharing any expected payment revision cannot both succeed: exactly one wins, others 409 `stale_revision`. | C |
| CB15 | Sum of balances equals the seeded total in every historical view after batches and refunds; current `total`/`available` never negative. | C |

## UP4 — Upgrade

| Row | Requirement | Check |
|---|---|---|
| UP4.1 | The stage-4 service accepts unchanged exports from the stage-1, stage-2 and stage-3 services (accepted revisions): 204, retaining everything those stages preserve — including settlement membership, corrections (revisions, their idempotency records) and statement snapshot tokens. | H (`previous_api`) + T with real containers of all three |
| UP4.2 | After such an import, refunds and batches work on imported payments and settlements; imported payments expose `refund_of: null` and revisions `correction_batch_id: null`. | T |
| UP4.3 | Stage-4's own export → import round trip preserves refunds (`refund_of`, refunded totals), batches (`correction_batch_id`, shared `recorded_at`), their idempotency records and replies, and snapshots. Invalid state → 422, destination unchanged. | T |
| UP4.4 | The stage-2 browser upgrade rows (G2-G4) still hold against the stage-4 service. | B/H |

## Decisions recorded by the Architect

| # | Choice | Reason |
|---|---|---|
| S4-1 | Refund check order: auth → key present/length → body is a JSON object → claimed-key resolution → unknown payment 404 → caller is not the original receiver 403 → target is a refund 422 `invalid_refund_target` → amount validation 422 → `refund_exceeds_payment` 422 → `insufficient_funds` 409. | Mirrors S3-3; the spec lists the cases without an order. |
| S4-2 | Batch check order: auth → key → body is a JSON object → claimed-key resolution → non-operator 403 → batch shape (422) → per item in input order: field validation 422, unknown payment 404, `linked_payment_immutable` 422, `stale_revision` 409, `refund_exceeds_payment` 422 → duplicate ids are a shape error → `incomplete_settlement` 422 → members' differing effective instants 422 → `insufficient_funds` → `historical_overdraft`. | "Error precedence is: item errors in input order, settlement completeness, resulting current available funds, then historical". |
| S4-3 | Refund amount range is the payment amount rule 1..1000000000 integral; above the refundable remainder (but valid) → `refund_exceeds_payment`. | "Invalid amount is 422 `validation_failed`" and the separate exceed rule. |
| S4-4 | A refund payment has its own revision 1 and can itself not be corrected or refunded. Its `effective_at = recorded_at = created_at` = the refund instant. | Spec: refunds are new payments; "never a refund"; "refund payments cannot themselves be corrected". |
| S4-5 | The refunded total of a payment counts all its refunds at their full amounts (refunds are immutable). | Refunds cannot be corrected. |
| S4-6 | Single correction responses and all revisions expose `correction_batch_id` (null when not from a batch). | "each revision also exposes correction_batch_id". |
| S4-7 | The UI is unchanged; refund payments show in the feed as ordinary payments. | Stage 4 adds no UI requirement. |
| S4-8 | Capacity carried from stage 3 (S3-12, B3.6): bodies up to 512 MiB on `/_test/import` and `/_test/reset`, readable 413 over the limit, 60000 + 60000 state exported/imported/reset inside 10 s, 20000-payment histories with 50 requests in flight inside 5 s. Refunds and batches must not make these worse: a 32-item batch on a 20000-payment wallet stays inside 5 s with 50 requests in flight. | Stage-1 §2 limits; the Verifier measured stage 3 at 2.43 s for 50 concurrent corrections on a 20000-payment wallet. |
| S4-9 | Generated ids for refunds and correction batches are fixed-width like every other generated id (S3-13); `correction_batch_id` ≤ 64 characters. | Consistency with S3-13. |
