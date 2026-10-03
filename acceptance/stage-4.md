# Acceptance map — Pocketful stage 4

Source: `dark-factory-wearedevs/pocketful/spec/stage-4.md` (complete) plus all of `stage-1.md`,
`stage-2.md` and `stage-3.md` (still apply; maps `acceptance/stage-1.md` A1–J6, `stage-2.md`
K1–U4, `stage-3.md` V1–AC6 remain in force for `stage-4/`). Target: `stage-4/`, started as a copy
of the accepted `stage-3/` (revision 9dcc200f). `stage-1/`, `stage-2/`, `stage-3/` must not change. "Supplied" =
harness `--stage 4` (runs all four suites against `stage-4/`). "Own" = tests written from the spec
by the Implementer and independently by the Verifier.

## AD. Regression and delivery

| Row | Requirement | Check |
|---|---|---|
| AD1 | All rows of the stage-1, 2 and 3 maps hold for `stage-4/` (UI included), with the stated changes only: payments gain `refund_of`, revisions gain `correction_batch_id`, ten idempotent paths | Supplied suites 1–3 against stage-4; earlier own lists rerun |
| AD2 | `stage-4/` self-contained: own Dockerfile + RUN.md (module map updated), clean build, isolated run, limits (2 vCPU / 2 GiB, 50 in flight, 5 s per request, 10 s control calls, 60 s start), no 5xx | Build, isolated run, load run incl. refunds and batches |
| AD3 | `stage-1/`, `stage-2/`, `stage-3/` identical to their accepted revisions | `git diff` empty for each |
| AD4 | Ten idempotent write paths; §7 rules apply independently to refunds and correction batches (missing key 400, length 1..255 else 422, replay 200 same body, different body 409 `idempotency_key_reuse`, concurrent identical one 201, failed key reusable, per-user scope, claimed key resolved before validation) | Own ×2 |

## AE. Refunds

| Row | Requirement | Check |
|---|---|---|
| AE1 | `POST /payments/{id}/refunds` body `{"amount": N}`; no token 401; unknown payment 404; caller not the original receiver (sender or third party) 403 `forbidden`; idempotency key required | Own |
| AE2 | Target may be a direct payment, request payment, capture, or settlement member; a refund payment as target ⇒ 422 `invalid_refund_target` | Own, each kind |
| AE3 | Invalid `amount` (missing, 0, negative, fractional, string, boolean, null, > 1000000000) ⇒ 422 `validation_failed`; `1`, integral floats (`200.0`, `2e2`) accepted | Own matrix |
| AE4 | Cumulative refunds may not exceed the payment's current corrected amount: exactly the remaining amount ok, remaining + 1 ⇒ 422 `refund_exceeds_payment`; several partial refunds add up; after a correction the corrected amount is the limit | Own |
| AE5 | Success 201: a new payment in the opposite direction (from = original receiver, to = original sender) in the full payment shape, `refund_of` = target id, `request_id: null`, `authorization_id: null`, `settlement_id: null`, note and visibility copied from the original, own `payment_id` and `created_at`; replay 200 with the original body | Own |
| AE6 | Money moves atomically from the receiver's **available** funds; available < amount ⇒ 409 `insufficient_funds`, nothing changes; held funds cannot fund a refund; sum of totals unchanged | Own incl. receiver with a hold |
| AE7 | A refund never reopens a request (stays `paid`), never reopens an authorization or restores a released hold; never changes settlement membership (settlement replay body unchanged; the refund has `settlement_id: null`) | Own |
| AE8 | Every non-refund payment exposes `refund_of: null` on every endpoint returning payments (payments, pay, capture, settlement members, activity, statement); original idempotent responses stored before the upgrade are returned unchanged | Own |
| AE9 | A refund is an ordinary feed/statement item: `/activity` by the visibility rule, statements of both parties with correct sign, revision 1 at its `created_at` | Own |
| AE10 | Concurrent refunds on one payment never exceed the corrected amount (N parallel, different keys); concurrent refund + reducing correction serialise: never refunded > corrected amount | Own race |

## AF. Corrections with refunds

| Row | Requirement | Check |
|---|---|---|
| AF1 | Single corrections remain for ordinary direct/request payments (all stage-3 Z rows) | Stage-3 list |
| AF2 | Captures and refund payments cannot be corrected: 422 `linked_payment_immutable` (single and batch); settlement members still 422 `linked_payment_immutable` on the single endpoint | Own |
| AF3 | A correction cannot reduce a payment below its already-refunded amount: 422 `refund_exceeds_payment` (amount = refunded total ok; one less fails), single and batch | Own |
| AF4 | Correction debits are checked against available funds (409 `insufficient_funds`) | Own |

## AG. Correction batches

| Row | Requirement | Check |
|---|---|---|
| AG1 | `POST /correction-batches`: no token 401; authenticated non-operator 403 `forbidden`; idempotency key required — same rules and order as `POST /settlements` | Own |
| AG2 | `corrections` holds 1..32 objects with distinct `payment_id`s; missing/non-array/empty/33 items/non-object item/duplicate id ⇒ 422 `validation_failed`; 1 and 32 ok; unknown fields ignored | Own |
| AG3 | Every item has the ordinary correction fields and validation (`payment_id`, `expected_revision` positive integer, `amount` integer 0..1e9, `effective_at` RFC 3339 with offset not later than now, `reason` 1..200 chars) ⇒ 422 `validation_failed` otherwise; unknown payment 404; stale expected revision 409 `stale_revision` | Own matrix |
| AG4 | The operator may correct ordinary, request and settlement payments it is not a party to; captures and refunds ⇒ 422 `linked_payment_immutable` | Own |
| AG5 | Correcting any settlement member requires every member of that settlement in the batch, else 422 `incomplete_settlement`; members of one settlement must have identical effective instants (different offset spellings of the same instant are fine), else 422 `validation_failed` | Own |
| AG6 | Error precedence: item errors in input order (validation, 404, linked immutable, stale revision, refund_exceeds_payment — the first failing item decides) → settlement completeness (`incomplete_settlement`, then identical instants) → resulting current available funds (409 `insufficient_funds`) → historical total and available at every effective/event boundary (409 `historical_overdraft`) | Own: batches combining two error kinds in both orders |
| AG7 | Affordability uses the combined effect of all proposed revisions (a batch whose items offset each other for a wallet succeeds although one item alone would fail; and vice versa) | Own |
| AG8 | A rejected batch leaves history, balances, statements and idempotency records unchanged (key reusable) | Own |
| AG9 | Success 201 `{correction_batch_id, recorded_at, revisions}` with `revisions` in input order, each a revision object (`payment_id, revision, amount, effective_at, recorded_at, reason, correction_batch_id`); all share one `recorded_at`, strictly later than the previous `recorded_at` of every member; atomic (all or none) | Own |
| AG10 | Every revision exposes `correction_batch_id` (the batch id for batch revisions, null otherwise) in `GET /payments/{id}/revisions` and in single-correction responses | Own |
| AG11 | Original payments and receipts never change; original payment and settlement retries return their original bodies; `/activity` unchanged; new statements and `/me` views reflect the new revisions; earlier snapshot tokens keep paging their frozen entries | Own |
| AG12 | Replay returns the original batch response with 200, also after newer revisions | Own |
| AG13 | Concurrent corrections (single or batch) sharing any expected payment revision cannot both succeed; sums of balances conserved in every historical view | Own race: batch vs batch, batch vs single |
| AG14 | Ordinary single-payment corrections remain available for non-members; a settlement payment may be refunded under the refund rules | Own |

## AH. Export / import across stages

| Row | Requirement | Check |
|---|---|---|
| AH1 | Stage-4 accepts exports produced by this repo's stage-1, stage-2 and stage-3 services (204), retaining settlement membership, corrections (revisions, correction idempotency records) and statement snapshots (a stage-3 token pages the same frozen result on stage-4) | Export from real stage-1/2/3 containers → import into stage-4 |
| AH2 | Imported payments expose `refund_of: null`, imported revisions `correction_batch_id: null`; imported payments are refundable and batch-correctable; settlement completeness works on imported settlements | Own |
| AH3 | Stage-4 export/import round-trips refunds (links and cumulative refunded amounts), batches (ids, shared recorded_at), both new idempotent paths' records and snapshots | Own |
| AH4 | Browser upgrade rows R2–R4 still hold on stage-4 | Browser |

## Supplied checks

From `/home/ubuntu/nightshift-claude-bg-test/dark-factory-wearedevs`:

    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 4 --out ../band-work/checks/<new-name>

Final run adds `--mode isolated`. Every run needs a new `--out` directory.

## Recorded choices

- No new UI is specified for stage 4; the existing UI must keep working and must not break on
  refund payments in the feed (they render as ordinary payments).
- Refund precedence: 401 → body parse 400 → key missing/length → claimed-key resolution (§7) → 404 →
  403 → `invalid_refund_target` 422 → amount validation 422 → `refund_exceeds_payment` 422 →
  `insufficient_funds` 409. Reason for target-before-amount: the spec names the target rule first;
  it is otherwise silent, so this is a choice.
- Refund `amount` range is 1..1000000000 like any payment amount.
- "Current corrected amount" = the amount of the latest revision of the target payment.
- A refund is "a new payment", so it has its own revision 1; it is immutable for corrections and
  cannot itself be refunded.
- Refunds do not create a historical-overdraft check: they move money now, like payments.
- In a batch, per-item checks run for item 1 fully, then item 2, and so on (validation → 404 →
  immutable → stale → refund floor), because the spec says "item errors in input order". Shape
  errors of the batch itself (count, duplicates, non-object item) come before item errors.
- `historical_overdraft` for a batch is evaluated with all proposed revisions applied together.
