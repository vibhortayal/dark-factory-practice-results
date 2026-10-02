# Acceptance map: stage 4

Sources: `pocketful/spec/stage-4.md` ("S4"), `stage-3.md` ("S3"), `stage-2.md` ("S2") and
`stage-1.md` (§ numbers) in the kickoff checkout. Target folder: `stage-4/`, created by copying
the accepted `stage-3/` (revision aedbe2c666e7b1b97661ad869d77f002bb103eca) and extending that code.
Every row of `acceptance/stage-1.md` (A1..K10 with A12, A13), `acceptance/stage-2.md` (M1..V7 with
Q11) and `acceptance/stage-3.md` (AA1..FF12, ZZ2, ZZ3) continues to apply to `stage-4/` except
where a row here says it changes; rows L1, Z1 and ZZ1 are replaced by JJ1.
"Check": `H` = supplied harness run, `P` = the Verifier's own HTTP probe, `B` = browser probe,
`I` = inspection. Rows marked **[D]** are the Architect's resolution of an open choice, with the reason.

## GG. Carry-over and upgrade

| Row | Requirement | Check |
|---|---|---|
| GG1 | `stage-4/` is a complete, buildable folder of its own (source, `Dockerfile`, `RUN.md`), copied from `stage-3/` and extended; `stage-1/`, `stage-2/`, `stage-3/` are not modified. No `.git`, symlink or submodule inside; everything needed at run time is in the image. | I; H isolated |
| GG2 | Every stage-1, stage-2 and stage-3 row still holds on `stage-4/`: suites 1, 2 and 3 pass; the Verifier's earlier API probes, browser probes and historical model pass, with the changes stated here (`refund_of` on payments, `correction_batch_id` on revisions, ten idempotent paths). The browser product keeps working; S4 requires no new screen. | H, P, B |
| GG3 | A stage-4 service accepts an unchanged export produced by the stage-1, stage-2 and stage-3 services (`format_version: 1`), retaining everything those stages preserved, and in particular settlement membership, corrections (every revision) and statement snapshot tokens. | H, P: exports from real stage-1, stage-2, stage-3 containers with rich state |
| GG4 | Existing receipts and saved statements stay available in their original form. (a) Every idempotent replay recorded before an upgrade returns the body exactly as originally recorded. (b) A snapshot token taken before an upgrade pages a result equal, as a JSON value, to what the earlier stage returned for it: same entries, same fields inside each entry and each payment (no field added by this stage appears in it), same balances. (c) After refunds or batch corrections, earlier snapshot tokens still page their frozen entries. **[D]** (b) is read strictly: a snapshot remembers the layout it was taken under and is rendered in that layout. Reason: S4 says "in their original form"; an added `refund_of` key would make the saved statement differ from what the user was given. | P: page a stage-3 token on stage 3, export, import into stage 4, page again, compare for equality |
| GG5 | Stage-4 export/import (§10) also preserves refunds and their links, refunded totals, correction batches (id, shared `recorded_at`, member revisions), snapshots with their layout, and the idempotency records of all ten write paths. Tampered or inconsistent states are 422 with the destination unchanged; no 5xx. | P |

## HH. Refunds (S4 "Refunds and corrected history")

| Row | Requirement | Check |
|---|---|---|
| HH1 | `POST /payments/{payment_id}/refunds` body `{"amount": n}` is the ninth idempotent write path (all §7 rules). 201 with the created payment; replay 200 with the original body. | H, P |
| HH2 | The refund is a new payment in the opposite direction (from the original receiver to the original sender) in exactly the payment shape, with `refund_of` = the target's id, `request_id: null`, `authorization_id: null`, `settlement_id: null`, and the target's original `note` and `visibility`; `amount` = the refunded amount; its own `payment_id` and `created_at`. Every other payment, on every endpoint, carries `refund_of: null`. | H, P |
| HH3 | Only the original receiver may refund: any other authenticated caller (the sender, a third party, an operator) -> 403 `forbidden`; unknown payment -> 404; no token -> 401. | P |
| HH4 | The target may be a direct payment, a request payment, a capture or a settlement member. A refund payment is never a valid target -> 422 `invalid_refund_target`. | P |
| HH5 | `amount` must be an integer 1..1000000000 (row C3 forms); missing or invalid -> 422 `validation_failed`. The sum of all refunds of a payment may not exceed the payment's current corrected amount (latest revision) -> 422 `refund_exceeds_payment`; refunding exactly up to it is allowed; a payment corrected to 0 cannot be refunded. | P: boundary at exactly the remaining refundable amount and one above |
| HH6 | The refund moves existing money from the receiver's `available` funds atomically; `available` below `amount` -> 409 `insufficient_funds`, nothing changes. Held funds cannot fund a refund. | P |
| HH7 | **[D]** Precedence: 401 -> key -> body -> replay/reuse -> field validation 422 -> 404 -> 403 -> `invalid_refund_target` -> `refund_exceeds_payment` -> `insufficient_funds`. Reason: same order as rows E5, F5, O6, FF3. | P |
| HH8 | A refund never reopens a request or an authorisation, never restores a released hold and never changes settlement membership (a refund of a settlement member is not a member). The target payment, its receipts and its revisions are unchanged by a refund. | P |
| HH9 | A refund is an ordinary payment for every read: it appears in `GET /activity` by the visibility rule, in both parties' statements and historical views at its `created_at`, with revision 1 like any payment; totals still sum to the seeded total in every view. | P, model |
| HH10 | Captures and refund payments cannot be corrected, by the single endpoint or in a batch: 422 `linked_payment_immutable`. Stage-3 single corrections stay available for ordinary direct and request payments (and still refuse settlement members with `linked_payment_immutable`). | P |
| HH11 | A correction (single or in a batch) may not reduce a payment below its already-refunded total: 422 `refund_exceeds_payment`; reducing to exactly the refunded total is allowed. **[D]** In the single-correction precedence of row FF3 it sits after `stale_revision` and before `insufficient_funds`. Reason: it is a rule about the payment's state, judged before funds. | P |
| HH12 | Correction debits are checked against `available` funds (as row FF4). | P |
| HH13 | Concurrency: concurrent refunds of one payment never exceed its corrected amount in total; concurrent refunds and corrections of one payment leave refunded total <= corrected amount; identical same-key refunds give one 201 and replays. | P at 50 in flight |

## II. Batch corrections (S4 "Batch corrections")

| Row | Requirement | Check |
|---|---|---|
| II1 | `POST /correction-batches` is the tenth idempotent write path. It requires a settlement operator: no token 401; authenticated non-operator 403 `forbidden` (same rules and order as `POST /settlements`, row C11). | H, P |
| II2 | Body `{"corrections":[{payment_id, expected_revision, amount, effective_at, reason}, …]}` with 1..32 objects and distinct `payment_id`s; `corrections` missing, not an array, empty, over 32, holding a non-object, or holding a repeated `payment_id` -> 422 `validation_failed`. Unknown fields are ignored. | P: 0, 1, 32, 33 items; duplicates |
| II3 | Every item has the ordinary correction fields and validation (row FF2: all required; every invalid field 422 `validation_failed`; `effective_at` not later than now). Unknown payment -> 404; `expected_revision` not the latest -> 409 `stale_revision`; a capture or a refund payment -> 422 `linked_payment_immutable`; an amount below the item's already-refunded total -> 422 `refund_exceeds_payment`. | P |
| II4 | The operator may correct ordinary, request and settlement payments, whoever the parties are. | H, P |
| II5 | Correcting any member of a settlement requires every member of that settlement in the same batch, else 422 `incomplete_settlement`. The members of one settlement must carry identical effective instants, compared as instants (offset spellings may differ), else 422 `validation_failed`. Members' amounts may differ from each other. | P |
| II6 | Precedence: (1) batch shape (II2); (2) item errors in input order, the first item with an error decides; **[D]** inside one item: field validation -> unknown payment -> `linked_payment_immutable` -> `stale_revision` -> `refund_exceeds_payment`; (3) settlement completeness: `incomplete_settlement`, then **[D]** differing effective instants within a settlement; (4) resulting current `available` funds -> 409 `insufficient_funds`; (5) historical `total` and `available` at every effective/event boundary -> 409 `historical_overdraft`. Reason for the [D] parts: S4 orders the four groups; inside them the order follows rows FF3 and K4, and the instants rule needs settlement membership so it belongs to group 3. | P |
| II7 | Affordability is judged on the combined effect of all proposed revisions: current funds by each wallet's net change across the whole batch (a wallet may be debited by one item and credited by another); history by applying all proposed revisions together (row FF5's rule, for every affected user). | P: a batch whose items are unaffordable one by one but affordable together, and the reverse |
| II8 | 201 with `correction_batch_id`, `recorded_at` and `revisions` in input order; each revision has the fields of row FF1 plus `correction_batch_id`. All new revisions share one `recorded_at`, strictly later than the previous `recorded_at` of every corrected payment. The money differences of all items move in the same atomic step. | H, P |
| II9 | Every revision exposes `correction_batch_id` in `GET /payments/{id}/revisions` and in new single-correction responses: the batch id for batch revisions, null otherwise. Statement entries and payments are otherwise as in stage 3. | P |
| II10 | A rejected batch leaves history, balances, snapshots and idempotency records unchanged (the key stays free). Replays return the original batch response with 200; the same key with a different body is 409. | P |
| II11 | Original payments and receipts never change: the feed, original payment replays and original settlement replays return their original bodies after a batch. New statements and views reflect the new revisions; earlier snapshot tokens keep paging their frozen entries. | P, model |
| II12 | Concurrent corrections (single or batch) that share any expected payment revision cannot both succeed: exactly one 201, the others 409 `stale_revision` (or a replay if same key and body). Concurrent batches, refunds, payments and reads equal some one-at-a-time order; all invariants hold at every read. | P at 50 in flight |

## JJ. Stage boundary and quality

| Row | Requirement | Check |
|---|---|---|
| JJ1 | `stage-4/` implements stages 1 to 4. The harness run for stage 4 ends `claimed stage: 4 on the shipped checks` with stages 1 to 4 `pass`. `--all` shows every folder claiming its own stage: `stage-1/` 1, `stage-2/` 2, `stage-3/` 3, `stage-4/` 4. | H |
| JJ2 | Written to the specification, not to the supplied checks (which cover about a sixth of S4). | I |
| JJ3 | Maintainable: refunds and batches reuse the stage-3 historical ledger (one place for selection, views, boundary walk) rather than duplicating it; the single correction and the batch share one validation and one commit path; the synchronous-commit rule and per-request clock are kept; the independent-model test is extended to refunds and batches; RUN.md describes the stage-4 design. | I |

## Commands

From `/home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs`:

```sh
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 4 --out ../band-work/checks/<new-name>
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 4 --mode isolated --out ../band-work/checks/<new-name>
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --all --mode isolated --out ../band-work/checks/<new-name>
```

Every run needs a new `--out` directory. The final check of the stage is the isolated one.
