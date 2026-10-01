@vibhor15/nightshift-implementer
Rows: all stage-3 rows + stage-1/2 regression · Revision: stage-2 accepted at f8086da438d3fa7dd38c886decd4ed4a2b8c9dd8; base = head of main · Files: stage-3/ (to create) · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer
STAGE-3 HANDOFF PART 4/12 — ACCEPTANCE MAP acceptance/stage-3.md (verbatim)

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
