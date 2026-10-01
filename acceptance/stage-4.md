# Stage 4 acceptance map

Source: `pocketful/spec/stage-4.md` in the kickoff checkout. `stage-4/` is `stage-3/` copied
forward and extended; every row of `acceptance/stage-1.md`, `stage-2.md` and `stage-3.md`
continues to hold for `stage-4/` except where a row below changes it. "S" = at least partly
covered by a shipped check (only 16% of the graded stage-4 suite is shipped); "O" = must be
covered by the band's own tests. **CHOICE** rows resolve points the specification leaves
open; if a shipped check contradicts one, the check wins and the contradiction is reported
to the Architect.

## BA. Carry-forward and delivery

| # | Requirement | Check |
|---|---|---|
| BA1 | `stage-4/` is a complete, buildable folder with its own `Dockerfile` and `RUN.md`; `stage-1/`, `stage-2/`, `stage-3/` are byte-for-byte unchanged | O: `git diff <accepted stage-3 rev> -- stage-1 stage-2 stage-3` is empty |
| BA2 | All behaviour of stages 1–3 still holds, including the browser UI, statements, snapshots and single-payment corrections | S: harness `--stage 4` runs suites 1–3 against `stage-4/`; O: earlier own tests pass in `stage-4/` |
| BA3 | Ten idempotent write paths; §7 rules apply independently to `POST /payments/{id}/refunds` and `POST /correction-batches` (missing key 400, long key 422, 201 first, 200 replay with the original body, 409 reuse on a different body, failed key reusable, concurrent identical → one 201) | S + O |
| BA4 | Runs in isolation within the stage-1 resource limits; no 5xx | S (isolated) + O |
| BA6 | The stage-3 clock rules hold for everything new (stage-3 rows AC11–AC13): a refund's `created_at` and a batch's `recorded_at` are plain real-clock readings, never ahead of the clock; the batch `recorded_at` is `max(real now, latest previous recorded_at among the members + 1 microsecond)`; every item's `effective_at` is judged "not later than now" against the end of the current clock tick, so a client-now instant with microseconds is accepted; default reads see a committed batch or refund at once | O: 200 batches and refunds with client-now instants, read back immediately |
| BA5 | `stage-4` import accepts unchanged exports from this team's stages 1, 2, 3 and 4, retaining settlement membership, corrections (revisions, recorded times), statement snapshots, idempotency records, sessions | O with real containers of each stage |

## BB. Refunds

| # | Requirement | Check |
|---|---|---|
| BB1 | `POST /payments/{payment_id}/refunds`, body `{"amount": N}`, `Idempotency-Key` required; 201 with the refund payment; replay 200 with the original body | S |
| BB2 | Only the original RECEIVER may refund: any other authenticated caller (sender, third party, operator) → 403 `forbidden`; unknown payment → 404; no token → 401 | O |
| BB3 | The target may be a direct payment, a request payment, a capture or a settlement member; a refund payment as target → 422 `invalid_refund_target` | O |
| BB4 | `amount` must be an integer 1..1000000000 (CHOICE: ordinary payment amount rule; missing, 0, negative, fraction, string, boolean, null → 422 `validation_failed`) | O |
| BB5 | Cumulative refunds of one payment may not exceed its CURRENT corrected amount (latest revision): otherwise 422 `refund_exceeds_payment`; exactly reaching it is allowed; a payment corrected to 0 cannot be refunded at all | O |
| BB6 | The refund is a NEW payment in the opposite direction (from the original receiver to the original sender) with `refund_of` = target id, `request_id: null`, `authorization_id: null`, `settlement_id: null`, and the target's note and visibility; it has its own id, `created_at` and revision 1; it appears in the feed by the ordinary visibility rule and in both parties' statements | S + O |
| BB7 | It moves money from the receiver's AVAILABLE funds atomically, or fails 409 `insufficient_funds` changing nothing (held funds cannot fund a refund) | O |
| BB8 | A refund never reopens a request (stays `paid`), never reopens an authorization, never restores a released hold, never changes settlement membership or the target's own payment object apart from nothing at all (the original receipt is unchanged) | O |
| BB9 | Every payment object everywhere now carries `refund_of` (null unless it is a refund), including payments imported from earlier stages; stored original idempotent responses are replayed exactly as stored | S + O |
| BB10 | CHOICE — precedence: 401 → key 400/422 → body parse 400 → claimed-key resolution → `amount` validation 422 → 404 → 403 → 422 `invalid_refund_target` → 422 `refund_exceeds_payment` → 409 `insufficient_funds` | O |
| BB11 | Concurrent refunds of one payment with different keys never exceed the corrected amount in total | O |
| BB12 | Σ totals stays the seeded total in every view after refunds; refunds are effective and recorded at their `created_at` | O |

## BC. Single-payment corrections after stage 4

| # | Requirement | Check |
|---|---|---|
| BC1 | Stage-3 corrections remain available to the original sender for ordinary direct and request payments | S + O |
| BC2 | Captures and refund payments cannot be corrected: 422 `linked_payment_immutable`; settlement members remain uncorrectable through the single-payment endpoint (422 `linked_payment_immutable`) | O |
| BC3 | A correction cannot reduce a payment below its already-refunded amount: 422 `refund_exceeds_payment` (equal to the refunded amount is allowed) | O |
| BC4 | Correction debits are checked against AVAILABLE funds (409 `insufficient_funds`) | O |
| BC5 | Every revision object exposes `correction_batch_id` (CHOICE: null for revision 1 and for single-payment corrections; reason: "each revision also exposes correction_batch_id") | O |

## BD. Correction batches

| # | Requirement | Check |
|---|---|---|
| BD1 | `POST /correction-batches` requires a settlement operator and an idempotency key, with the same 401/403 rules as `POST /settlements` (no token 401; non-operator 403 `forbidden`, before key and body checks as in stage-1 map D10) | S |
| BD2 | Body `{"corrections":[...]}` with 1..32 objects and distinct `payment_id`s; otherwise (missing, not an array, empty, 33+, non-object item, duplicate `payment_id`) → 422 `validation_failed`; unknown fields ignored | O |
| BD3 | Every item: `payment_id` (string), `expected_revision`, `amount`, `effective_at`, `reason` with the ordinary correction validation (stage-3 AE4), `effective_at` not later than now | O |
| BD4 | Item errors: invalid fields 422 `validation_failed`; unknown payment 404 `not_found`; capture or refund payment 422 `linked_payment_immutable`; amount below the already-refunded amount 422 `refund_exceeds_payment`; stale expected revision 409 `stale_revision` | O |
| BD5 | The operator may correct ordinary, request and settlement payments of ANY wallets (not only payments they sent) | S + O |
| BD6 | Correcting any member of a settlement requires every member of that settlement in the same batch, else 422 `incomplete_settlement` | O |
| BD7 | Members of one settlement must carry identical effective instants (different offset spellings of the same instant are equal), else 422 `validation_failed` | O |
| BD8 | Precedence: item errors in input order (the first item with an error decides; within an item CHOICE: validation → 404 → `linked_payment_immutable` → `refund_exceeds_payment` → `stale_revision`), then settlement completeness (CHOICE: then identical member instants), then resulting CURRENT available funds (409 `insufficient_funds`), then historical total and available at every effective/event boundary (409 `historical_overdraft`). CHOICE: batch-shape errors (BD2) come before item errors | O |
| BD9 | Affordability is judged on the COMBINED effect of all proposed revisions: a batch whose net effect leaves every wallet's available ≥ 0 succeeds even if one item alone would not | O |
| BD10 | A rejected batch leaves history, balances, statements, snapshots and idempotency records unchanged (the key stays reusable) | O |
| BD11 | Success: 201 `{correction_batch_id, recorded_at, revisions}` with `revisions` in input order; every new revision shares the batch `recorded_at`, which is strictly later than the previous `recorded_at` of every member; each revision exposes `correction_batch_id`; replays return the original response with 200 | S + O |
| BD12 | Original payments and receipts never change; original payment and settlement retries return their original bodies; settlement membership is unchanged by batches and by refunds | O |
| BD13 | New statements reflect the new revisions; earlier snapshot tokens keep paging their frozen entries | O |
| BD14 | Of concurrent corrections (single or batch) that share any expected payment revision, at most one succeeds | O |
| BD15 | Single-payment corrections remain available for non-members, to the original sender only; an operator has no extra rights on the single-payment endpoint | O |
| BD16 | `GET /payments/{id}/revisions` shows batch revisions with their `correction_batch_id`, still readable only by the two parties | O |
