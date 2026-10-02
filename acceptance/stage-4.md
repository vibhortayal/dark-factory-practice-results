# Acceptance map: stage 4 (Pocketful: refunds and batch corrections)

Source: `dark-factory-wearedevs/pocketful/spec/stage-4.md` (sha256 ff79140f…5e9a48) on top of
`stage-1.md`, `stage-2.md` and `stage-3.md`. Target folder: `stage-4/`, created as a copy of the
accepted `stage-3/` (revision 532accd) and extended. "Harness" = supplied checks (`harness run
--track pocketful --stage 4`: suites 1-4 against `stage-4/`; the stage-4 sample is 5 checks, about
16% of the graded suite). "Own" = checks the Implementer and the Verifier each write from the
specification.

## M. Carry-forward and delivery

| Row | Requirement | Check |
|---|---|---|
| M1 | `stage-4/` is `stage-3/` copied forward and extended: complete on its own (source, UI, `Dockerfile`, `RUN.md`, tests), no nested `.git`, builds from a clean clone. `stage-1/`, `stage-2/`, `stage-3/` are not modified. | Own: `git diff 532accd -- stage-1 stage-2 stage-3` empty; clean build |
| M2 | Every row of `acceptance/stage-1.md`, `stage-2.md` and `stage-3.md` still holds for `stage-4/` (API, UI, upgrade, limits, no 5xx), with only the changes this map states. | Harness suites 1-3 on stage-4; Own: the earlier lists (incl. browser suite and the brute-force model) re-run against stage-4 |
| M3 | Limits unchanged (2 vCPU, 2 GiB, 50 in flight, 5 s per request, 10 s test-control calls, healthy ≤ 60 s, no outbound). A 32-item batch over a history of several thousand payments stays well within 5 s. | Own: timed |
| M4 | A stage-4 service accepts exports of this team's stage-1 (43ecb3c), stage-2 (4a9c357) and stage-3 (532accd) services and its own, retaining settlement membership, corrections (revisions, their idempotency records) and snapshots (stage-3 snapshot tokens keep paging their frozen entries after import into stage 4). Own exports preserve refunds, batch ids and the two new idempotent paths. | Harness (`previous_api`); Own: 1→4, 2→4, 3→4, 4→4 with before/after comparison |
| M5 | Ten idempotent write paths: all stage-1 F-rows apply independently to `POST /payments/{id}/refunds` and `POST /correction-batches` as well. | Own |

## F. Refunds: `POST /payments/{payment_id}/refunds`

| Row | Requirement | Check |
|---|---|---|
| F1 | Body `{"amount": n}`; idempotency key required (400 when missing, 422 over 255). No token → 401. Only the original receiver may refund, else 403 `forbidden` (sender, third party, operator who is not the receiver); unknown payment → 404. | Harness; Own |
| F2 | Target may be a direct payment, a request payment, a capture or a settlement member, never a refund: refunding a refund → 422 `invalid_refund_target`. | Own |
| F3 | Invalid amount (missing, not an integer, < 1, > 1000000000, string, boolean, null) → 422 `validation_failed`. | Own |
| F4 | Cumulative refunds may not exceed the payment's current corrected amount (latest revision): otherwise 422 `refund_exceeds_payment`. Refunding exactly the remainder succeeds; a zero-amount (fully reversed) payment cannot be refunded at all. | Own |
| F5 | Success → 201 with a new payment in the opposite direction (from the original receiver to the original sender), full payment shape, `refund_of` = target payment id, `request_id: null`, `authorization_id: null`, `settlement_id: null`, note and visibility copied from the original, own `payment_id` and `created_at`. Replay → 200 with the original body; same key, different body → 409. | Harness; Own |
| F6 | The refund moves existing money from the receiver's `available` funds atomically; `available` below the amount → 409 `insufficient_funds`, nothing changes. Totals conserved; held funds cannot fund a refund. | Harness; Own |
| F7 | Refunds never reopen a request (stays `paid`) or an authorisation (stays `captured`, `captured_amount` unchanged), never restore a released hold, never change settlement membership (the settlement's payments and receipts are unchanged). | Own |
| F8 | Every payment object everywhere (payments, pay, capture, settlements, activity, statement entries) carries `refund_of` (null unless a refund). Original stored responses replay unchanged. | Harness; Own |
| F9 | A refund is an ordinary ledger payment: it appears in `/activity` by the feed rule, in both parties' statements (once, with its link), has revision 1 (`/revisions` readable by its two parties), and counts in `as_of`/`known_at` views from its `created_at`. | Own |
| F10 | Concurrent refunds of one payment (50 in flight, distinct keys) never exceed the corrected amount in sum; same key → one 201, others 200. Refund racing a correction that lowers the amount: the result equals some serial order (never refunded sum > current amount). | Own |

## G. Corrections with refunds (single corrections of stage 3)

| Row | Requirement | Check |
|---|---|---|
| G1 | Stage-3 single corrections remain available for ordinary direct and request payments. Captures and refund payments → 422 `linked_payment_immutable`; settlement members via the single endpoint → 422 `linked_payment_immutable` (unchanged from stage 3). | Own |
| G2 | A correction cannot reduce a payment below its already-refunded amount → 422 `refund_exceeds_payment` (equal to the refunded amount is allowed). | Own |
| G3 | Correction debits are checked against `available` funds (409 `insufficient_funds`), then history (409 `historical_overdraft`). | Own |

## B. Batch corrections: `POST /correction-batches`

| Row | Requirement | Check |
|---|---|---|
| B1 | Requires a settlement operator and an idempotency key with the same 401/403 rules as settlements: no token → 401; authenticated non-operator → 403 `forbidden`; key missing → 400, over 255 → 422. | Harness; Own |
| B2 | Body `{"corrections": [...]}` with 1..32 objects with distinct `payment_id`s; otherwise (missing, not an array, 0 or 33 items, non-object item, duplicate id) → 422 `validation_failed`. Unknown fields ignored at both levels. | Own |
| B3 | Every item has the ordinary correction fields and validation (`payment_id`, `expected_revision` positive integer, `amount` integer 0..1000000000, `effective_at` instant not later than now, `reason` string 1..200) → 422 `validation_failed`; unknown payment → 404; stale expected revision → 409 `stale_revision`. | Own |
| B4 | The operator may correct ordinary, request and settlement payments of any users (need not be a party); captures and refunds → 422 `linked_payment_immutable`; below the refunded amount → 422 `refund_exceeds_payment`. | Harness; Own |
| B5 | Correcting any settlement member requires every member of that settlement in the batch, else 422 `incomplete_settlement`. Members of one settlement must have identical effective instants (offset spellings may differ), else 422 `validation_failed`. | Own |
| B6 | Error precedence: item errors in input order (the first item with an error decides) → settlement completeness → resulting current available funds (409 `insufficient_funds`) → historical total and available at every effective/event boundary (409 `historical_overdraft`). Affordability is the combined effect of all proposed revisions (per-wallet net). | Own: batches built to trigger two errors at once, for each adjacent pair |
| B7 | A rejected batch leaves history, balances, statements, snapshots and idempotency records unchanged (all or nothing; the key stays reusable). | Own |
| B8 | Success → 201 `{correction_batch_id, recorded_at, revisions}` with `revisions` in input order; all new revisions share one `recorded_at`, strictly later than the previous `recorded_at` of every member; each revision exposes `correction_batch_id`; money for every changed amount moves in the same atomic step; totals conserved. | Harness; Own |
| B9 | Original payments and receipts never change; original payment and settlement retries return their original bodies; `/activity` shows original payments; new statements reflect the new revisions; earlier snapshot tokens keep paging their frozen entries. | Own |
| B10 | Replay → 200 with the original batch response; same key, different body → 409 `idempotency_key_reuse`. | Own |
| B11 | Concurrent corrections (single or batch, any mix) sharing any expected payment revision cannot both succeed: exactly one wins, the others get 409 `stale_revision` (or 200 as a replay of the same key). | Own: 50-way bursts of overlapping batches |
| B12 | A settlement payment may be refunded under the ordinary refund rules (F-rows); a corrected settlement keeps its membership and `/revisions` of each member shows the batch revision. | Own |

## Y. Robustness

| Row | Requirement | Check |
|---|---|---|
| Y1 | The brute-force model of stage 3 extended with refunds and batches predicts every outcome on randomised histories; `/me` and `/statement` agree with it on a grid of (`as_of`, `known_at`); balances sum to the seeded total in every view. | Own |
| Y2 | New inputs fuzzed and mutated as before (bodies, numbers, instants, ids in the path, import/reset members for refunds and batches): 4xx with the error body, never 5xx; own export always re-imports. | Own |

## Decisions on points the specification leaves open (change only via the Architect)

- H-1 Refund check order (extends D-1): 401 → key present/length → body parse → claimed key (replay 200 / 409 reuse) → amount validation 422 → 404 unknown payment → 422 `invalid_refund_target` when the target is itself a refund (whoever asks) → 403 not the original receiver → 422 `refund_exceeds_payment` → 409 `insufficient_funds`. Reason: "refunds of refunds give 422" is stated without a caller condition.
- H-2 Refund amount follows the ordinary payment amount rule (integer 1..1000000000). "Refunded amount" of a payment = sum of the amounts of all refund payments naming it; refunds are immutable, so it never shrinks.
- H-3 A refund of a settlement member has `settlement_id: null` (it is not a member); a refund of a capture has `authorization_id: null`; a refund of a request payment has `request_id: null`.
- H-4 Every revision object everywhere (`/revisions`, single-correction responses, batch responses) carries `correction_batch_id`: the batch id for batch revisions, `null` for revision 1 and single corrections. Stored responses of earlier requests replay exactly as stored.
- H-5 Single-correction check order (extends G-6): … → 404 → 403 → 422 `linked_payment_immutable` → 409 `stale_revision` → 422 `refund_exceeds_payment` → 409 `insufficient_funds` → 409 `historical_overdraft`.
- H-6 Batch check order: 401 → 403 non-operator → key → body parse → claimed key → batch shape (B2) 422 → for each item in input order, the first item with an error decides, and within one item: field validation 422 → 404 → 422 `linked_payment_immutable` → 409 `stale_revision` → 422 `refund_exceeds_payment` → then 422 `incomplete_settlement` → 422 `validation_failed` for members of one settlement with different effective instants → 409 `insufficient_funds` (per-wallet net of all items against `available`) → 409 `historical_overdraft`.
- H-7 The historical check of a batch covers every user touched by any item, under the latest revisions including all proposed ones, at every boundary ≤ now, for `total` and `available`.
- H-8 A batch item that changes nothing in amount (re-timing or reason only) is valid. A batch may mix settlement members (complete sets, possibly several settlements) and ordinary payments.
- H-9 The operator permission gives write access through batches only; it gives no read access to `/revisions`, requests or private activity of others (G-15 stands).
- H-10 Refunds check only current `available` (they are new payments at the current instant); they cannot create a historical overdraft.
- H-11 No new screen is required by stage 4; the UI keeps working unchanged (refunds are payments and appear in the feed by the ordinary rule).
- H-12 Stage-3 snapshot registry note S3-1 is kept as it is.
