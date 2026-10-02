# Stage 4 acceptance map (pocketful)

Source: `pocketful/spec/stage-4.md` (kickoff checkout), which keeps every stage-1, stage-2 and
stage-3 requirement in force. All rows of `acceptance/stage-1.md` (A1-J3), `acceptance/stage-2.md`
(K1-S6) and `acceptance/stage-3.md` (T1-Z2) still apply to `stage-4/` unless a row below changes
them; row AA1 carries them. Rows marked **[reading]** are Architect choices where the specification
is open, with the reason. The supplied checks cover only part of this map.

## AA. Carry-over and delivery

| Row | Requirement | Check |
|---|---|---|
| AA1 | Every row of the stage-1, stage-2 and stage-3 maps holds for `stage-4/`, with the stage-4 changes below (ten idempotent paths; `refund_of` on payments; `correction_batch_id` on revisions; new refusals on corrections). The stage-2 browser UI keeps working; stage 4 requires no new screen. | Harness `--stage 4` runs suites 1-4 against `stage-4/`; Verifier reruns its stage-1, -2 and -3 lists (API and browser) against the stage-4 image |
| AA2 | `stage-4/` is the accepted `stage-3/` (cfff6f7) copied and extended: complete, buildable on its own, own `Dockerfile` and `RUN.md`, no `.git`, symlinks or `__pycache__` inside; `stage-1/`, `stage-2/`, `stage-3/` are not modified. | `git diff` of the three folders empty since their accepted revisions; clean build |
| AA3 | Ten idempotent write paths: the eight of stage 3 plus `POST /payments/{payment_id}/refunds` and `POST /correction-batches`. Every stage-1 F row applies to each new path (key required, replay 200 with the original body even after later changes, reuse 409, failed key reusable, concurrent identical -> one 201, user and path scope, claimed key resolved before validation). | API test on both new paths |
| AA4 | A stage-4 service accepts exports produced by this team's stage-1, stage-2 and stage-3 services and its own, keeping everything earlier stages preserve, including settlement membership, corrections (revision history) and statement snapshots (a snapshot token taken on stage 3 pages the same frozen result after import into stage 4). Refunds, `refund_of` and batches survive a stage-4 export -> import into a fresh container. | API test with real stage-1, -2, -3 containers |
| AA5 | Supplied checks pass: `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 4 --out ../band-work/checks/<new-name>` (suites 1-4); final run with `--mode isolated`. Stage 4 is the last stage: there is no overshoot suite. | Harness output |

## AB. Refunds

| Row | Requirement | Check |
|---|---|---|
| AB1 | `POST /payments/{payment_id}/refunds` body `{"amount": n}`, idempotency key required, token required (401). Only the original receiver may refund: any other authenticated caller (sender, third party, operator) -> 403 `forbidden`; unknown payment -> 404. | API test |
| AB2 | `amount` follows the ordinary payment amount rules (integer 1..1000000000, integral JSON numbers accepted; missing, 0, negative, fraction, string, boolean, null, above 1000000000 -> 422 `validation_failed`). | API test at each boundary |
| AB3 | Target may be a direct payment, a request payment, a capture or a settlement member, never a refund: refunding a refund -> 422 `invalid_refund_target`. | API test |
| AB4 | Cumulative refunds of one payment may not exceed its current corrected amount (latest revision): over -> 422 `refund_exceeds_payment`; exactly equal accepted. A payment corrected to 0 cannot be refunded. A later correction upward raises the cap. | API test: refund in parts up to the amount, one more unit refused; after corrections down/up |
| AB5 | A refund is a new payment in the opposite direction (receiver -> original sender) with `refund_of` = the target's `payment_id`, `request_id: null`, `authorization_id: null`, the target's `note` and `visibility`; 201 with that payment in the ordinary shape; replay 200 with the original body. Every other payment has `refund_of: null`. **[reading]** a refund of a settlement member has `settlement_id: null` (refunds never change settlement membership). | API test on exact key set |
| AB6 | The refund moves existing money from the receiver's **available** funds atomically, or fails 409 `insufficient_funds` and changes nothing (key unused). Held funds cannot fund it. | API test with a hold on the receiver |
| AB7 | Refunds never reopen a request (it stays `paid`) or an authorization (it stays closed, `captured_amount`/`remaining_amount` unchanged) and never restore a released hold. | API test |
| AB8 | A refund is an ordinary money movement everywhere else: it appears in `GET /activity` by the feed rule, in both parties' statements (with its own revision 1, `effective_at = recorded_at = created_at`), in `GET /me?as_of`, and in `GET /payments/{id}/revisions` for its two parties. | API test |
| AB9 | **[reading]** Order of checks on a refund: 401; key header; body parse; claimed-key resolution; amount validation (422); 404; 403; `invalid_refund_target`; `refund_exceeds_payment`; `insufficient_funds`. Follows stage-1 row D8. | API tests on combined-error requests |
| AB10 | Concurrent refunds of one payment never exceed its amount in total; concurrent refunds and payments never make `available` negative. | Concurrent API test, 50 in flight |

## AC. Single corrections in stage 4

| Row | Requirement | Check |
|---|---|---|
| AC1 | Stage-3 single corrections stay available for ordinary direct and request payments (sender only). Captures, refund payments and settlement members cannot be corrected through this path: 422 `linked_payment_immutable`. | API test |
| AC2 | A correction may not reduce a payment below its already-refunded amount: 422 `refund_exceeds_payment` (equal to the refunded total accepted). | API test |
| AC3 | Correction debits are checked against `available` (409 `insufficient_funds`), then history (409 `historical_overdraft`), as in stage 3. Refund payments are part of the history every check walks. | API test |
| AC4 | **[reading]** Order on a single correction: stage-3 row X13 with `refund_exceeds_payment` after `stale_revision` and before `insufficient_funds`: validation 422, 404, 403, `linked_payment_immutable`, `stale_revision`, `refund_exceeds_payment`, `insufficient_funds`, `historical_overdraft`. | API test |
| AC5 | **[reading]** Every revision object (revisions endpoint, single-correction responses) carries `correction_batch_id`: the batch id for a revision written by a batch, `null` otherwise. A replay of a single correction returns its original body. | API test |

## AD. Batch corrections

| Row | Requirement | Check |
|---|---|---|
| AD1 | `POST /correction-batches` requires a settlement operator and an idempotency key, with the settlement rules: no token 401, authenticated non-operator 403 `forbidden` (before the key check, as on `/settlements`). | API test |
| AD2 | Body `{"corrections": [...]}` with 1..32 objects and distinct `payment_id`s; otherwise (missing, not an array, 0 or 33 items, an item that is not an object, a repeated `payment_id`) 422 `validation_failed`. Unknown fields ignored. | API test at 1, 32, 0, 33 |
| AD3 | Each item has `payment_id` plus the ordinary correction fields and validation (stage-3 row X3: `expected_revision`, `amount` 0..1000000000, `effective_at` an RFC 3339 instant with offset not later than now, `reason` 1..200 characters; invalid -> 422 `validation_failed`). Unknown payment 404; stale expected revision 409 `stale_revision`; captures and refunds 422 `linked_payment_immutable`; reducing below the refunded amount 422 `refund_exceeds_payment`. The operator may correct ordinary, request and settlement payments whoever their parties are. | API test |
| AD4 | Correcting any settlement member requires including every member of that settlement in the batch, else 422 `incomplete_settlement`. Members of one settlement must carry identical effective instants (compared as parsed instants: offset spellings may differ, e.g. `12:00:00+00:00` and `14:00:00+02:00`), else 422 `validation_failed`. Ordinary single-payment corrections stay available for non-members. | API test |
| AD5 | Error precedence: item errors in input order (the first item with any error decides; **[reading]** within an item: validation, 404, `linked_payment_immutable`, `stale_revision`, `refund_exceeds_payment`), then settlement completeness (`incomplete_settlement`, then the identical-instant rule), then resulting current available funds (409 `insufficient_funds`), then historical total and available at every effective/event boundary (409 `historical_overdraft`). Affordability uses the combined effect of all proposed revisions. | API tests with two errors of different kinds in both orders |
| AD6 | A rejected batch leaves history, balances and idempotency records unchanged (key unused). | Export compared before/after |
| AD7 | Success: 201 `{correction_batch_id, recorded_at, revisions}` with `revisions` in input order; every new revision has the stage-3 revision fields plus `correction_batch_id`; all share `recorded_at`, strictly later than the previous `recorded_at` of every member; effective times not later than now. Each revision moves the difference between that payment's own two wallets (increase debits its sender, decrease its receiver), all in one atomic step. Replay 200 with the original batch response. | API test |
| AD8 | Original payments, receipts and settlement responses never change: replays of the original `POST /payments` and `POST /settlements` return their original bodies; `GET /activity` shows originals. New statements reflect the new revisions; earlier snapshot tokens keep paging their frozen entries. | API test |
| AD9 | A settlement payment may be refunded under the refund rules; refunds never change settlement membership (a later batch over that settlement still needs exactly the original members, and only them). | API test |
| AD10 | Concurrent corrections sharing any expected payment revision cannot both succeed: batch vs batch and batch vs single correction; exactly one wins, the others get 409 `stale_revision`. Invariants hold at every read under concurrency. | Concurrent API test, 50 in flight |
