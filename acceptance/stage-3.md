# Stage 3 acceptance map

Source: `pocketful/spec/stage-3.md` in the kickoff checkout (section numbers such as §5, §7
refer to `stage-1.md`). `stage-3/` is `stage-2/` copied forward and extended; every row of
`acceptance/stage-1.md` and `acceptance/stage-2.md` continues to hold for `stage-3/` except
where a row below changes it. "S" = at least partly covered by a shipped check (only 9% of
the graded stage-3 suite is shipped); "O" = must be covered by the band's own tests.
**CHOICE** rows resolve points the specification leaves open; if a shipped check contradicts
one, the check wins and the contradiction is reported to the Architect.

Vocabulary used below. A **view** is the pair (`as_of` A, `known_at` K). For a view, each
payment contributes its **selected revision**: the latest revision with `recorded_at` ≤ K,
or nothing when none exists. A selected revision moves `amount` from sender to receiver at
its `effective_at`. The **opening balance** of a wallet is what it held before anything
moved.

## AA. Carry-forward and delivery

| # | Requirement | Check |
|---|---|---|
| AA1 | `stage-3/` is a complete, buildable folder with its own `Dockerfile` and `RUN.md`; `stage-1/` and `stage-2/` are byte-for-byte unchanged | O: `git diff <accepted stage-2 rev> -- stage-1 stage-2` is empty |
| AA2 | All stage-1 and stage-2 behaviour still holds, including the whole browser UI | S: harness `--stage 3` runs suites 1–2 against `stage-3/`; O: earlier own tests still pass in `stage-3/` |
| AA3 | No stage-4 surface: no `/refunds`, no `refund_of` field on payments, no `/correction-batches`, no `correction_batch_id` on revisions, no codes `refund_exceeds_payment`, `invalid_refund_target`, `incomplete_settlement`; settlement members stay uncorrectable | S: overshoot probe `stage 4: fail`, `claimed stage: 3`; O: route and shape review |
| AA4 | Runs in isolation, within the stage-1 resource limits; no 5xx under any input or load | S (isolated) + O |
| AA5 | With no corrections and no temporal parameters, every earlier response is unchanged, except the additive `closed_at` on authorizations (AF7) | S + O |

## AB. Payment timestamps and seeding

| # | Requirement | Check |
|---|---|---|
| AB1 | Every payment's `created_at` is an RFC 3339 instant with offset; every endpoint returning a payment includes it (payments, request pay, capture, settlements members, activity, statement entries) | S + O |
| AB2 | Seeded payments may supply `created_at`; it is stored as that instant and returned (CHOICE: verbatim as seeded, like seeded `expires_at`); omission uses reset time, which is before every subsequently API-created payment | O |
| AB3 | A seeded payment `created_at` in the future → reset 422 `validation_failed`, nothing changes; a seeded `created_at` that is not an RFC 3339 instant with offset → 422 too | O |
| AB4 | Fixture `balance` is still the balance after all seeded payments; loading seeded payments never changes it | S + O |
| AB5 | `GET /activity` keeps newest-first by `created_at`, now honouring seeded `created_at` values | O |
| AB6 | Opening balance of a seeded wallet = seeded `balance` − net effect of the ORIGINAL seeded payments (received − sent); a signup opens at 0. Corrections never change opening balances | O |

## AC. `GET /me` over time

| # | Requirement | Check |
|---|---|---|
| AC1 | Without temporal parameters the response is as in stage 2 (no `as_of`/`known_at` keys) and reports current corrected values | S |
| AC2 | `as_of` must be an RFC 3339 instant with an offset (`Z` or `±hh:mm`, fractional seconds allowed). A naive local time, a bare date, an empty value, garbage → 422 `validation_failed`. Same rule for `known_at`, and for `from`/`to` on statements | S + O: `2026-09-24T13:20:00`, `2026-09-24`, ``, `yesterday`, `2026-13-01T00:00:00Z` |
| AC3 | With `as_of`: `balance` = opening balance + every selected movement with `effective_at` ≤ `as_of` (a payment at exactly `as_of` counts); before the earliest payment → the opening balance; at/after the latest → current balance; future instants allowed | S + O |
| AC4 | The response carries `as_of` back exactly as given (the decoded query string, byte for byte — offset spelling and fractional digits preserved); likewise `known_at` when supplied; neither key is present when not supplied | S + O: `+02:00` offsets, `Z`, microseconds |
| AC5 | `known_at` K selects, per payment, the latest revision recorded at or before K; a payment with no revision recorded by K contributes nothing; omission = everything known when the read begins. K may be in the future | O |
| AC6 | With `as_of` and/or `known_at`, all four money fields describe that same view: `balance = total`, `available = total − held`, `held` per AF. Without `as_of`, A = the instant the request began | O |
| AC7 | CHOICE: `known_at` alone (no `as_of`) → A = now, K as given; `as_of` alone → K = now. Reason: "omission means everything known when the read begins"; "without `as_of`, use the instant the request began" | O |
| AC9 | Instants are compared EXACTLY, not at the service's own clock precision: client instants may carry up to nanosecond fractions and any offset (Python `isoformat()` sends microseconds); `as_of=…00.123400` excludes a movement effective at `…00.123456`. Parse into an exact integer (e.g. BigInt nanoseconds), never through a float or a millisecond-truncating `Date.parse` alone | O |
| AC10 | CHOICE: in the instant query parameters (`as_of`, `known_at`, `from`, `to`) a raw unencoded `+` is taken as a literal plus sign, not as a space (percent-decoding only), and the echo preserves it. Reason: the spec's own example writes the offset as `%2B`, but a client that sends `+00:00` unencoded plainly means an offset; a space can never be part of a valid instant | O: both spellings |
| AC11 | "Everything known when the read begins" is implemented by knowledge order, not by comparing clock readings: a read with no `known_at` sees every revision and hold event committed before it, even one recorded in the same clock tick | O: correct then read at once, 200 times |
| AC12 | Every service-assigned instant (`created_at`, `committed_at`, `recorded_at`, `closed_at`, `expires_at` base, the reset instant, and the service's own "now" for expiry and for `effective_at` ≤ now) is the REAL clock reading at the moment of the event — never ahead of it, under any load. Records created in the same clock tick share the instant; their order comes from sequence numbers (`kseq`, fixed-width ids), not from spacing stamps apart. Only one bump is allowed: a correction's `recorded_at` must exceed that same payment's previous `recorded_at`, by the smallest representable step (CHOICE: 1 microsecond, so stamps carry six fractional digits), never by a millisecond and never through a global counter (stage-3 Verifier finding F1) | O: 50 concurrent payments, then `as_of=<client now>`, `known_at=<client now>`, `statement?to=<client now>` all equal the current balance; 3,000 payments over 50 connections leave no stamp later than the client clock; a hold with a short lifetime created before a burst does not expire early |
| AC8 | The sum of `balance` over all wallets equals the seeded total in every view (any A, any K) | O: property test over random corrections and instants |

## AD. `GET /statement`

| # | Requirement | Check |
|---|---|---|
| AD1 | `GET /statement?from&to&limit&offset&known_at`; authenticated (401 without token); `limit`/`offset` exactly as `GET /requests` (defaults 50/0, plain digits, 1..200, ≥ 0, else 422) | S + O |
| AD2 | Response: `opening_balance`, `entries`, `closing_balance`, `has_more`, `snapshot`; each entry `payment`, `delta`, `balance_after`, `revision`, `effective_at`, `recorded_at` | S + O |
| AD3 | Entries are the payments the caller SENT or RECEIVED whose selected `effective_at` is in the half-open window `[from, to)`; public payments between other people never appear; a private payment appears for both of its parties | S + O |
| AD4 | Order: selected `effective_at` ascending, then payment id ascending (CHOICE: plain code-point string comparison of the id, which is what "id ascending" means for opaque strings; ids generated by `stage-3/` are fixed-width so that this order is also creation order) | S + O: seeded payments sharing reset time; back-to-back API payments |
| AD5 | `from` defaults to the opening of the wallet (so `opening_balance` is the opening balance). `to` defaults to now. CHOICE: an omitted `to` includes every movement effective up to and including the instant the read began — a payment committed in the same clock tick as the read is in the statement and in `closing_balance`. Reason: the shipped check pays and reads at once and expects the payment; an explicit `to` stays strictly half-open | S + O |
| AD6 | `opening_balance` = the view's balance immediately before `from`; `closing_balance` = the view's balance immediately before `to`; `opening_balance + Σ delta over the FULL window = closing_balance` | S + O |
| AD7 | Sent → negative `delta`, received → positive `delta`, magnitude = selected amount; `balance_after` is the running balance after that entry in the full window order | S |
| AD8 | Pagination changes nothing but which entries are listed: `balance_after` of an entry, `opening_balance` and `closing_balance` are identical on every page; `has_more` correct on the final partial page and for offsets beyond the end (empty `entries`, `has_more:false`) | O |
| AD9 | `payment` is the original payment object except `amount`, which is the selected amount for this statement; `created_at`, note, visibility, links are the original's | O |
| AD10 | A zero-amount selected revision still appears as an entry with `delta: 0`; a payment not yet known at `known_at` does not appear; a correction is never counted alongside the revision it replaces | O |
| AD11 | Statements contain money movements only: no entry for authorization creation, release, void or expiry; a capture appears exactly once with `authorization_id` set; settlement members appear with `settlement_id` | O |
| AD12 | A correction can move a payment into or out of a window (its selected `effective_at` decides) | O |
| AD13 | `from` later than `to` (CHOICE: 422 `validation_failed`; `from == to` is an empty window, 200) | O |
| AD15 | CHOICE: a statement echoes `known_at` exactly as given when it was supplied ("Echo supplied `known_at` exactly"), and omits the key otherwise; `as_of` is not a statement parameter and is ignored there like any unknown parameter | O |
| AD14 | With no corrections and no `known_at`, `revision` is 1 and `effective_at = recorded_at = created_at` for every entry | S + O |

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
