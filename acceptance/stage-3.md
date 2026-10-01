# Acceptance map — Pocketful stage 3

Sources: `dark-factory-wearedevs/pocketful/spec/stage-3.md` (whole file) on top of
`stage-2.md` and `stage-1.md` (both still in force). Target folder: `stage-3/`, created as a
copy of the accepted `stage-2/` (revision f8086da438d3fa7dd38c886decd4ed4a2b8c9dd8) and extended. `stage-1/` and `stage-2/` must not change.

Check codes: `H` = supplied harness suites (partial sample; a stage-3 run executes suites 1, 2
and 3), `T` = own black-box HTTP test against the built container, `C` = concurrency test,
`B` = browser test, `I` = inspection. A row is accepted only on Verifier evidence for the head
revision.

Terms used below. A payment has revisions 1..n. Each revision has `amount`, `effective_at`,
`recorded_at`, `reason`. A **view** is defined by `known_at` K (default: the instant the read
begins) and, for `/me`, `as_of` T (default: the instant the read begins): for each payment take
its latest revision with `recorded_at` ≤ K (none → the payment contributes nothing), then apply
the selected revisions at their `effective_at`.

## B3 — Carry-over and delivery

| Row | Requirement | Check |
|---|---|---|
| B3.1 | Every row of `acceptance/stage-1.md` and `acceptance/stage-2.md` (with decisions Q1-Q8, S2-1..S2-12) still holds for `stage-3/`, except where this map states a stage-3 change. With no corrections and no temporal parameters, all earlier behaviour is unchanged (the UI included). | H suites 1+2, earlier own tests rerun against the stage-3 image, T, B |
| B3.2 | `stage-3/` is a complete buildable service (source, `Dockerfile`, `RUN.md`, own tests, no nested `.git`), runs alone with `-e PORT`, no outbound network at run time, resource limits of stage-1 §2. | I + H `--mode isolated` |
| B3.3 | `stage-1/` and `stage-2/` are byte-identical to their accepted revisions. | I: `git diff <accepted> -- stage-1 stage-2` empty |
| B3.4 | `stage-3/` implements stage 3 only: no refunds, no batch corrections, no other stage-4 surface. Harness prints `claimed stage: 3`. | H + T |
| B3.5 | No request yields a 5xx or a non-§5 error body (Q8), including every new endpoint and query parameter with odd input. | T fuzz |
| B3.6 | Historical reads stay inside the 5 s request limit with large histories (20k payments, hundreds of corrections) and 50 requests in flight. | C |

## PT — Payment timestamps

| Row | Requirement | Check |
|---|---|---|
| PT1 | Every payment's `created_at` is an RFC 3339 instant with an offset; every endpoint returning a payment includes it; `GET /activity` still orders newest first by it. | T/H |
| PT2 | Seeded payments may supply `created_at` (kept verbatim as the instant; any offset accepted); omitted → reset time, earlier than every later API-created payment. | T |
| PT3 | A seeded `created_at` in the future → reset 422 `validation_failed`, no state change. A seeded `created_at` that is not an RFC 3339 instant with offset → 422, no state change. | T |
| PT4 | Fixture `balance` stays the balance after all seeded payments; loading them does not change it. | T/H |
| PT5 | API-created payments get strictly increasing instants with sub-second precision, so `as_of = <a payment's created_at>` includes that payment and excludes every payment created after it, even within the same second. | T: two payments back to back, as_of at the first |

## ME — `GET /me` as of an instant

| Row | Requirement | Check |
|---|---|---|
| ME1 | Without temporal query parameters the response keeps the existing fields, reports current corrected values, and has no `as_of` / `known_at` key. | T/H |
| ME2 | `as_of` is an RFC 3339 instant with an offset (`Z` or `±hh:mm`, fractional seconds allowed). A naive local time, a bare date, an empty value, or any other text → 422 `validation_failed`. | T |
| ME3 | With `as_of`, `balance` is the balance after every payment of the caller effective at or before `as_of` and before every later one; a payment at exactly `as_of` counts. | T |
| ME4 | `as_of` at or after the latest payment → current balance; `as_of` in the future is accepted. | T/H |
| ME5 | `as_of` before the earliest payment → the opening balance (seeded ending balance minus the net effect of original seeded payments; 0 for accounts created by signup). | T |
| ME6 | The response carries `as_of` back exactly as given (same string, including offset form and precision). | T/H |
| ME7 | `known_at` (optional, RFC 3339 with offset; invalid or empty → 422; may be in the future) selects revisions as defined above; supplied `known_at` is echoed exactly. May be combined with `as_of`. | T |
| ME8 | Sum over all users of `balance` equals the seeded total in every historical view (any `as_of`, any `known_at`). | T + C |

## ST — `GET /statement`

| Row | Requirement | Check |
|---|---|---|
| ST1 | `GET /statement?from=&to=&limit=&offset=&known_at=` requires auth; returns `{opening_balance, entries, closing_balance, has_more, snapshot}` (+ echoed `known_at` when supplied). `from` defaults to the opening of the wallet, `to` to now. `limit`/`offset` exactly as `GET /requests` (default 50, 1..200, digits only, 422 otherwise). | T/H |
| ST2 | Entries are the payments the caller sent or received whose selected `effective_at` lies in `[from, to)` — `from` inclusive, `to` exclusive — oldest first: selected `effective_at` ascending, then payment id ascending for ties. | T |
| ST3 | Each entry: `payment` (the payment object; `payment.amount` is the selected revision's amount), `delta` (negative when the caller sent, positive when received), `balance_after` (caller's balance immediately after it in this view), `revision`, `effective_at`, `recorded_at` of the selected revision. | T/H |
| ST4 | `opening_balance` is the balance immediately before `from`; `closing_balance` the balance immediately before `to`; `opening_balance + Σ delta over the whole window == closing_balance`. | T/H |
| ST5 | Pagination never changes an entry's `balance_after`, nor `opening_balance`/`closing_balance`: they describe the full window on every page, including page 2+, the final partial page and offsets beyond the end (`entries: []`, `has_more: false`). | T |
| ST6 | Only payments the caller sent or received appear, even when other payments are public; feed visibility rules do not apply (the caller's own private payments appear). | T |
| ST7 | `from`/`to` invalid or empty → 422. Both may be in the future. | T |
| ST8 | Zero-amount revisions still appear as entries with `delta` 0. A payment is counted once: never both a correction and the revision it replaces. A payment with no revision recorded at or before `known_at` does not appear. | T |
| ST9 | With no corrections and no `known_at`, entries are ordered by `created_at` then id, as before corrections existed. | T/H |
| ST10 | Statements contain money movements only: authorisations, releases and expiries are not entries; a capture appears exactly once, with its `authorization_id` link; request and settlement payments keep their links. | T |

## CO — Corrections

| Row | Requirement | Check |
|---|---|---|
| CO1 | Every payment has a revision history; revision 1 has the original amount, `effective_at = recorded_at = created_at`, `reason: ""`. Seeded payments: their supplied `created_at` (or reset time). Settlement members: the shared `committed_at`. | T |
| CO2 | `POST /payments/{payment_id}/corrections` requires auth (401), an `Idempotency-Key` (§7: missing → 400, > 255 → 422) and the original sender: authenticated non-sender (receiver or third party) → 403 `forbidden`; unknown payment → 404 `not_found`. | T |
| CO3 | Body `{expected_revision, amount, effective_at, reason}`, all required: `expected_revision` positive integer; `amount` integer 0..1000000000 (0 reverses the whole payment; integral forms `400.0`, `4e2` valid); `reason` string of 1..200 characters; `effective_at` RFC 3339 instant with offset, not later than now. Missing or invalid → 422 `validation_failed`. | T: each boundary (0, 1000000000, 1000000001, reason 0/1/200/201 chars, effective_at now+1h, naive time) |
| CO4 | Success → 201 `{payment_id, revision, amount, effective_at, recorded_at, reason}`; `revision` = previous + 1; `recorded_at` server-assigned; recorded times of one payment strictly increase. Revisions are immutable and append-only. Parties and visibility never change. | T/H |
| CO5 | `expected_revision` not equal to the payment's latest revision → 409 `stale_revision`, nothing changes. | T |
| CO6 | Idempotency (eighth idempotent path, full §7 rules): replay → 200 with that original revision even after newer revisions exist; same key with a different body → 409 `idempotency_key_reuse`; failed attempts claim no key; key resolution happens before validation and before the stale check. | T |
| CO7 | The difference from the previous amount moves between the same two wallets in the same atomic step: increase debits the original sender and credits the receiver; decrease debits the receiver and credits the sender. Current `GET /me` reflects it at once. | T/H |
| CO8 | A debit the debited wallet cannot currently afford (against `available`) → 409 `insufficient_funds`; this takes precedence over `historical_overdraft`. | T |
| CO9 | Otherwise, if any user's corrected `total` or `available` would be negative at any past effective-time or hold-event boundary under the latest known revisions → 409 `historical_overdraft`. Balances at a boundary include the combined effect of all movements at that instant. | T: move a payment's `effective_at` before the funds that covered it arrived |
| CO10 | Either failure (and `stale_revision`, validation errors) preserves balances, revision history, statements, snapshots and idempotency state. | T |
| CO11 | The original payment and every original idempotent response stay unchanged: replays of `POST /payments`, `/requests/{id}/pay`, captures and settlements return the original body; `GET /activity` keeps showing the original payment (original amount, original `created_at`); corrections are not new feed payments and create no new payment ids. | T |
| CO12 | `GET /payments/{payment_id}/revisions` → `{"revisions": [...]}` in revision order including revision 1 (`reason: ""`), each `{payment_id, revision, amount, effective_at, recorded_at, reason}`. Only the two parties may read it: a third party gets 404 even for a public payment; unknown payment 404; no token 401. | T |
| CO13 | Settlement members and captures are immutable linked payments: a correction → 422 `linked_payment_immutable`. Their revision 1 is still readable by the parties. | T |
| CO14 | Concurrent corrections with the same `expected_revision` (different keys): exactly one 201, the others 409 `stale_revision`. Concurrent identical requests on one key: one 201, the rest 200 with the same body. | C |
| CO15 | Sum of balances equals the seeded total in every historical view after any sequence of corrections; no wallet's current `total` or `available` ever negative. | C |

## KA — `known_at` views

| Row | Requirement | Check |
|---|---|---|
| KA1 | A read with `known_at` before a correction's `recorded_at` shows the previous revision (amount and effective time); at or after it shows the correction — on `/me` and on `/statement` (entry `revision`, `effective_at`, `recorded_at`, `payment.amount`, `delta`, ordering, window membership). | T |
| KA2 | `known_at` before a payment's first `recorded_at` → the payment contributes nothing to balances and does not appear in the statement. | T |
| KA3 | `known_at` at exactly a revision's `recorded_at` selects that revision (inclusive). `as_of` stays inclusive; the statement window stays half-open. | T |
| KA4 | A correction may move a payment into or out of a statement window; new reads reflect it, old snapshots do not. | T |

## SN — Stable statement pagination

| Row | Requirement | Check |
|---|---|---|
| SN1 | Every first `GET /statement` response (one without `snapshot`) returns an opaque `snapshot` token (≤ 64 chars) freezing the caller's selected revisions, window, balances, entries and default `to` at that read. | T |
| SN2 | `GET /statement?snapshot=<token>&limit=&offset=` pages that exact result even after later payments, corrections or authorisation lifecycle actions: identical entries, `balance_after`, opening and closing balances. | T + C |
| SN3 | Only `limit` and `offset` may accompany `snapshot`: supplying `from`, `to` or `known_at` with it → 422 `validation_failed`. Unrecognised query parameters stay ignored. | T |
| SN4 | Unknown token, another user's token, or a token from before a reset → 404 `not_found`. Tokens last until reset. | T |
| SN5 | `has_more` is correct on every page, including the final partial page and offsets beyond the end. | T |
| SN6 | Snapshots stay unchanged during concurrent payments or corrections; creating snapshots must not exhaust memory or slow requests under load (thousands of statement reads on a 20k-payment history). | C |

## HH — Historical holds

| Row | Requirement | Check |
|---|---|---|
| HH1 | For `GET /me?as_of=T&known_at=K` all four money fields describe the same view: `balance = total`, `available = total − held`, `held` = holds open at T as known at K. Without `as_of`, T is the instant the request began. | T |
| HH2 | A hold starts at authorisation creation; a non-final capture reduces it at capture time; a final capture, void or expiry releases the remainder at that event's time; expiry takes effect at `expires_at`. | T: timeline of create / partial capture / final capture / void, probed between events |
| HH3 | Events other than clock expiry are known at their server-assigned event time (a `known_at` before the event does not see it). Once creation is known, the expiry deadline is known too: for `as_of` beyond the deadline (also beyond now) an open hold has expired. | T |
| HH4 | Authorisations expose `closed_at`: null while open; the event time when closed (final/complete capture, void, or `expires_at` for expiry) — in every authorisation response. | T |
| HH5 | Seeded open holds are assumed created at reset unless the fixture supplies `created_at`; seeded closed holds need no reconstructed lifecycle (they hold nothing in any view; `closed_at` non-null). | T |
| HH6 | Corrections are rejected with 409 `historical_overdraft` when they make `available` negative at any past boundary because of a hold, even if `total` stays non-negative; `insufficient_funds` still takes precedence for a currently unaffordable debit. | T |
| HH7 | Old snapshots remain unchanged after any lifecycle action (capture, void, expiry) or correction. | T |

## UP — Upgrade

| Row | Requirement | Check |
|---|---|---|
| UP1 | The stage-3 service accepts an unchanged export from the stage-1 service and from the stage-2 service (accepted revisions): 204, everything those stages preserve still preserved (accounts, logins, tokens, balances, payments, requests, operators, idempotency records, authorisations, holds, ttl). | H (`previous_api`) + T with real stage-1 and stage-2 containers |
| UP2 | After such an import the ledger accounts for every imported payment, authorisation and capture: each payment has revision 1 (`effective_at = recorded_at = created_at`), statements and `as_of` views work, opening balances are derived so that the current balances are unchanged, captures and settlement members are immutable. | T |
| UP3 | Stage-3's own export → import round trip preserves revisions, correction idempotency records and replies, `closed_at`, hold event times, and all earlier state; historical views are identical before and after. Invalid state → 422, destination unchanged. | T |
| UP4 | The stage-2 browser upgrade rows (G2-G4) still hold against the stage-3 service. | B/H |

## Decisions recorded by the Architect

| # | Choice | Reason |
|---|---|---|
| S3-1 | Instants are stored with microsecond precision; API-created payments, revisions and hold events get strictly increasing server instants. Responses keep RFC 3339 with offset. Imported stage-1/2 timestamps are kept verbatim. | PT5: "a payment made at exactly `as_of` counts as having happened … before every payment after it" is only checkable with distinguishable instants. |
| S3-2 | Query strings are decoded so that a literal `+` in an instant is kept as `+` (not turned into a space), and `%2B` also works; the echoed `as_of`/`known_at` is the decoded value exactly as given. | The spec example uses `%2B`; clients also send raw `+`. |
| S3-3 | Correction check order: auth → key present/length → body is a JSON object → claimed-key resolution → unknown payment 404 → not the original sender 403 → `linked_payment_immutable` 422 → field validation 422 → `stale_revision` 409 → `insufficient_funds` 409 → `historical_overdraft` 409. | Follows Q1/Q6 and the spec's stated precedence of `insufficient_funds` over `historical_overdraft`. |
| S3-4 | A correction whose amount equals the previous amount is valid: it appends a revision (possibly with a new `effective_at`) and moves no money. | Nothing forbids it; `effective_at` is a correctable attribute. |
| S3-5 | `from` later than `to` → 422 `validation_failed`; `from == to` is a valid empty window. | With `from > to` the required identity opening + Σdelta = closing cannot hold. |
| S3-6 | Responses that page a snapshot return the same `snapshot` token again. Snapshots are in-memory until reset; an import replaces all state and therefore drops the destination's earlier snapshots; snapshots are not part of the export. | "Tokens last until reset. No storage survival across container restarts is required." |
| S3-7 | A snapshot freezes the view by recording the resolved parameters (caller, window with the default `to` resolved, effective `known_at` = min(supplied, read instant)) against the append-only revision and event log, rather than copying entries; results must be byte-for-byte reproducible. Any equivalent design that meets SN2/SN6 is acceptable. | Revisions are immutable and recorded times strictly increase, so the frozen view is reproducible cheaply. |
| S3-8 | Payments created by paying a request are ordinary payments and can be corrected; only settlement members and captures are `linked_payment_immutable`. Correcting a paid request's payment does not change the request. | The spec names exactly those two linked kinds. |
| S3-9 | The payment object inside statement entries is the original payment object with `amount` replaced by the selected amount; `created_at` stays the original instant. `GET /activity`, replays and `GET /requests` keep the original amount. | "`payment.amount` is the selected amount for this statement"; "The original payment … remain unchanged". |
| S3-10 | The UI is unchanged from stage 2 except that wallet numbers reflect corrected current balances; no new screens are required in stage 3. | Stage-3 specification adds no UI requirement. |
| S3-11 | `effective_at` of a correction earlier than the payment's original `created_at`, or earlier than the wallet opening, is allowed provided no boundary goes negative; opening balances never change. | "Corrections must not change those opening balances"; only "not later than now" bounds it. |
