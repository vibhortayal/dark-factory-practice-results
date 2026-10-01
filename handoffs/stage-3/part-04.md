@vibhor15/nightshift-implementer STAGE 3 HANDOFF — part 4 of 13: stage-3 acceptance map (verbatim from acceptance/stage-3.md), piece 2 of 2. Do not start until part 13 (FINAL).

## AE. Corrections and revisions

| # | Requirement | Check |
|---|---|---|
| AE1 | Every payment has a revision history. Revision 1: original amount, `effective_at = recorded_at = created_at`, `reason: ""`; seeded payments use their supplied `created_at` or reset time; settlement members use `committed_at` | O |
| AE2 | `POST /payments/{payment_id}/corrections`: the eighth idempotent write path (§7 rules: missing key 400, long key 422, 201 first, 200 replay with the original revision even after newer revisions, 409 `idempotency_key_reuse` on a different body, failed key reusable, concurrent identical → one 201) | S + O |
| AE3 | Caller must be the original sender: any other authenticated caller (receiver, third party, operator) → 403 `forbidden`; unknown payment → 404; no token → 401 | O |
| AE4 | Body, all required: `expected_revision` positive integer; `amount` integer 0..1000000000 (0 reverses the payment); `reason` string of 1..200 characters; `effective_at` RFC 3339 instant with offset, not later than now. CHOICE: every missing or invalid field, including a wrong JSON type, is 422 `validation_failed` ("Invalid input is 422"); only an unparseable or non-object body is 400 | O |
| AE5 | Success: 201 `{payment_id, revision, amount, effective_at, recorded_at, reason}`; `revision` = previous + 1; `recorded_at` server-assigned and STRICTLY greater than the payment's previous `recorded_at` (also when two corrections land in the same clock tick); `effective_at` echoed (CHOICE: verbatim as supplied) | S + O |
| AE6 | `expected_revision` ≠ the payment's latest revision → 409 `stale_revision`; of two concurrent corrections with the same expected revision exactly one succeeds | O |
| AE7 | Money: the difference to the previous (latest) amount moves between the same two wallets in the same atomic step — an increase debits the original sender, a decrease debits the original receiver; parties and visibility never change | S + O |
| AE8 | A debit the debited wallet cannot currently afford → 409 `insufficient_funds` (CHOICE: measured against current `available`, as every stage-2 `insufficient_funds`); otherwise, if any wallet's `total` or `available` would be negative at any effective-time or hold-event boundary under the latest revisions → 409 `historical_overdraft`. `insufficient_funds` takes precedence. Balances at a boundary include the combined effect of all movements at that instant | O |
| AE9 | A failed correction changes nothing: balances, revision history, statements, snapshots, idempotency state (the key stays reusable) | O |
| AE10 | Settlement members and captures → 422 `linked_payment_immutable`; ordinary direct payments and request payments are correctable | O |
| AE11 | CHOICE — precedence: 401 → key 400/422 → body parse 400 → claimed-key resolution → field validation 422 → 404 → 403 → 422 `linked_payment_immutable` → 409 `stale_revision` → 409 `insufficient_funds` → 409 `historical_overdraft` | O |
| AE12 | The original payment object and every original idempotent response never change: `GET /activity`, `POST /payments` replay, request `payment_id` lookups all show the original amount; corrections are not feed items | O |
| AE13 | `GET /payments/{payment_id}/revisions` → `{"revisions":[...]}` in revision order including revision 1; each item `{payment_id, revision, amount, effective_at, recorded_at, reason}`; only the two parties; a third party gets 404 even for a public payment (operators too); unknown 404; no token 401 | O |
| AE14 | A correction with `amount` equal to the previous amount and only a new `effective_at` is valid: no money moves now, history shifts (and is checked for historical overdraft) | O |
| AE15 | Current `GET /me` (no parameters) reflects corrections at once; Σ totals stays the seeded total | S |

## AF. Historical holds

| # | Requirement | Check |
|---|---|---|
| AF1 | A hold starts at authorization `created_at`; a nonfinal capture reduces it at capture time; a final capture, void or expiry releases the remainder at that event's time; expiry takes effect at `expires_at` | O |
| AF2 | Knowledge: creation, captures and voids are known at their server-assigned event time; once creation is known the expiry deadline is known too. So for a view (A, K): an authorization counts only if `created_at` ≤ K and ≤ A; captures/voids count only if their time ≤ K and ≤ A; the hold is released if `expires_at` ≤ A | O: void after K but before A still shows held unless the deadline passed |
| AF3 | For `as_of` beyond now, a still-open hold expires at its deadline (held 0 from `expires_at` on) | O |
| AF4 | Historical `total` follows AC3/AC5; `available = total − held` in the same view | O |
| AF5 | Seeded open holds are created at reset time unless `created_at` is supplied; seeded closed holds (captured/voided/expired) hold nothing at any instant | O |
| AF6 | A correction that makes `total` or `available` negative at any past effective/event boundary → 409 `historical_overdraft` (AE8) | O |
| AF7 | Authorizations expose `closed_at`: null while open; the event time when closed — final capture time, void time, or `expires_at` for expiry by the clock. CHOICE for seeded closed holds: supplied `closed_at` if any, else `expires_at` when status is `expired`, else the reset time | O |
| AF8 | Lifecycle actions and corrections never change an existing statement snapshot | O |

## AG. Stable statement pagination

| # | Requirement | Check |
|---|---|---|
| AG1 | Every `GET /statement` without `snapshot` returns an opaque `snapshot` token (≤ 64 chars, URL-safe) that freezes the caller's selected revisions, window, balances, entries and the default `to` at that read | O |
| AG2 | `GET /statement?snapshot=<token>&limit&offset` pages exactly that result, unchanged by later payments, corrections, captures, voids or expiry; CHOICE: such responses echo the same `snapshot` token | O |
| AG3 | Only `limit` and `offset` may accompany `snapshot`: `from`, `to` or `known_at` with it → 422 `validation_failed` (checked before the token lookup); unrecognised parameters are still ignored | O |
| AG4 | Unknown token, another user's token, a token from before the last reset → 404 `not_found`; an empty `snapshot=` → CHOICE 404 | O |
| AG5 | Tokens last until reset; many tokens can coexist; design: a token records the caller, the resolved window, the resolved `known_at` and the service's knowledge position at the read, and the frozen result is recomputed from immutable revision and event history — so memory per token is constant and tokens survive export/import | O |
| AG6 | Snapshots stay unchanged while payments and corrections run concurrently | O |

## AH. Upgrade and persistence

| # | Requirement | Check |
|---|---|---|
| AH1 | `stage-3` import accepts unchanged exports from this team's `stage-1`, `stage-2` and `stage-3` services (envelope `format_version: 1`, internal schema versions 1, 2, 3) | S + O with real containers of each stage |
| AH2 | Imported payments get revision 1 from their stored `created_at`; opening balances = imported balance − net of imported payments; imported authorizations, captures and (stage-2) void instants feed the historical hold view; captures and settlement members are immutable after import | O |
| AH3 | Stage-3 → stage-3 round trip preserves revisions, recorded times, correction idempotency records and statement snapshot tokens; reset clears all of it | O |
| AH4 | Sessions, pending requests, pending retries and the UI keep working across a stage-2 → stage-3 import (stage-2 rows R7–R10 against `stage-3/`) | O |

## AJ. Concurrency

| # | Requirement | Check |
|---|---|---|
| AJ1 | Mixed concurrent payments, corrections, captures, voids, settlements and statement reads are serialisable: Σ total constant in every view, no negative `total`/`available` at any boundary, strictly increasing `recorded_at` per payment, no 5xx | O: 50-way burst with invariant reads |
