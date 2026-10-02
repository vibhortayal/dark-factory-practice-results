# Acceptance map: stage 3 (Pocketful: statements and payment corrections)

Source: `dark-factory-wearedevs/pocketful/spec/stage-3.md` (sha256 70a42853…98ebf94) on top of
`stage-1.md` and `stage-2.md`. Target folder: `stage-3/`, created as a copy of the accepted
`stage-2/` (revision 4a9c357) and extended. "Harness" = supplied checks (`harness run --track
pocketful --stage 3`: suites 1, 2 and 3 against `stage-3/`; the stage-3 sample is about 9% of the
graded suite, so nearly every row needs an own check). "Own" = checks the Implementer and the
Verifier each write from the specification.

Terms used below. T = the `as_of` instant (default: the instant the request began). K = the
`known_at` instant (default: everything known when the read begins). A payment's *selected
revision* under K is its latest revision with `recorded_at <= K`; a payment with none contributes
nothing. `total(u, T, K)` = opening balance of u + sum of selected amounts received − sent over
payments whose selected `effective_at <= T`.

## L. Carry-forward and delivery

| Row | Requirement | Check |
|---|---|---|
| L1 | `stage-3/` is `stage-2/` copied forward and extended: complete on its own (source, UI, `Dockerfile`, `RUN.md`, tests), no nested `.git`, builds from a clean clone. `stage-1/` and `stage-2/` are not modified. | Own: `git diff 4a9c357 -- stage-1 stage-2` empty; clean build |
| L2 | Every row of `acceptance/stage-1.md` and `acceptance/stage-2.md` still holds for `stage-3/` (API, UI, upgrade, limits, no 5xx), with only the changes this map states. With no corrections and no temporal parameters, every earlier behaviour is unchanged. | Harness suites 1 and 2 on stage-3; Own: the stage-1 and stage-2 lists re-run against stage-3, incl. the browser suite |
| L3 | Nothing from stage 4 is implemented. | Harness stage-4 probe must not be a full pass; route review |
| L4 | Limits unchanged (2 vCPU, 2 GiB, 50 in flight, 5 s per request, 10 s test-control calls, healthy ≤ 60 s, no outbound). Historical reads, statements and the overdraft check stay within 5 s with a few thousand payments and a few hundred revisions. | Own: timed reads/corrections on a seeded history of 5,000 payments |
| L5 | A stage-3 service accepts exports of this team's stage-1 (43ecb3c) and stage-2 (4a9c357) services and its own; the ledger accounts for imported payments, authorisations and captures (revision 1 for every payment; opening balances derived; captures linked). Stage-2 rows M1-M4 hold with stage-3 as the destination. Own exports preserve revisions, correction idempotency records, snapshots and hold event times. | Harness (`previous_api`); Own: stage-1 → stage-3, stage-2 → stage-3, stage-3 → stage-3 with before/after comparison of `/me` (with `as_of`/`known_at`), `/statement`, `/revisions` |

## T. Payment timestamps

| Row | Requirement | Check |
|---|---|---|
| T1 | Every payment's `created_at` is an RFC 3339 instant with an offset, present on every endpoint returning a payment (payments, pay, capture, settlements, activity, statement entries, replays). `GET /activity` keeps ordering by it, newest first. | Harness; Own |
| T2 | Seeded payments may supply `created_at`; omission uses reset time, which is before every later API-created payment. A seeded `created_at` in the future → 422 `validation_failed` from reset, no state change. A malformed one → 422. | Own |
| T3 | A fixture's `balance` is still the balance after all seeded payments; loading them does not change it. | Own |

## A. `GET /me` as of an instant

| Row | Requirement | Check |
|---|---|---|
| A1 | Without `as_of` and `known_at` the response has the existing fields with current corrected values and no `as_of` / `known_at` member. | Harness |
| A2 | `as_of` must be an RFC 3339 instant with an offset; a naive local time, a bare date, an empty value, garbage → 422 `validation_failed`. Same for `known_at`. Future instants are valid for both. | Own |
| A3 | With `as_of`: `balance` = balance after every payment of the caller with effective time at or before `as_of` and before every later one; a payment at exactly `as_of` counts. `as_of` ≥ latest payment → current balance; `as_of` before the earliest payment → opening balance (seeded balance minus the net effect of the original seeded payments; 0 for signed-up accounts). | Harness (future); Own: instants before, at and after each payment, incl. seeded ones |
| A4 | The response carries `as_of` back exactly as given (same characters); a supplied `known_at` is echoed exactly too. | Harness; Own with `Z`, `+02:00`, fractional seconds |
| A5 | The sum over all users of `balance` at any (`as_of`, `known_at`) equals the seeded total. | Own: sweep over all boundaries |

## S. `GET /statement`

| Row | Requirement | Check |
|---|---|---|
| S1 | `from`, `to` optional instants (invalid/empty → 422); `from` defaults to the opening of the wallet, `to` to now; `limit`/`offset` exactly as `GET /requests` (defaults 50/0, 1..200, ≥ 0, 422 otherwise). | Own |
| S2 | Entries: the payments the caller sent or received whose selected effective time lies in `[from, to)` (from inclusive, to exclusive), oldest first: by selected `effective_at` ascending, then payment id ascending for ties. Only the caller's own payments, whatever their visibility; other people's public payments never appear. | Harness (partly); Own |
| S3 | Each entry: `payment` (the payment object, with `amount` = the selected amount), `delta` (negative when sent, positive when received), `balance_after`, and the selected `revision`, `effective_at`, `recorded_at`. Zero-amount revisions still appear, with delta 0. A corrected payment appears once (never alongside the revision it replaces). | Harness; Own |
| S4 | `opening_balance` = balance immediately before `from`; `closing_balance` = balance immediately before `to`; `opening_balance + Σ delta over the FULL window = closing_balance`; `balance_after` walks forward from `opening_balance`. | Harness; Own |
| S5 | Pagination changes neither an entry's `balance_after` nor the opening/closing balances (they describe the full window for every `limit`/`offset`); `has_more` correct on the last partial page and for offsets beyond the end (empty `entries`, `has_more: false`). | Own |
| S6 | Response shape `{opening_balance, entries, closing_balance, has_more, snapshot}`. Statements contain money movements only: authorisation, release and expiry are not entries; a capture appears exactly once with `authorization_id` set; settlement members appear with `settlement_id`. | Own |

## C. Corrections: `POST /payments/{payment_id}/corrections`

| Row | Requirement | Check |
|---|---|---|
| C1 | Requires an idempotency key (eighth idempotent write path; all stage-1 F-rows apply) and the original sender. No token → 401; authenticated non-sender (receiver or third party) → 403 `forbidden`; unknown payment → 404. | Harness; Own |
| C2 | Body `{expected_revision, amount, effective_at, reason}`, all required: `expected_revision` positive integer; `amount` integer 0..1000000000 (0 reverses the whole payment); `reason` string of 1..200 characters; `effective_at` RFC 3339 instant with offset, not later than now. Any invalid input → 422 `validation_failed`. | Own: each field missing, wrong type, out of range, boundary values |
| C3 | Success → 201 `{payment_id, revision, amount, effective_at, recorded_at, reason}`; appends an immutable revision (`revision` = previous + 1); `recorded_at` is server-assigned and strictly increasing within one payment; parties and visibility never change. | Harness; Own |
| C4 | `expected_revision` not equal to the current latest revision → 409 `stale_revision`. Concurrent corrections with the same expected revision: exactly one succeeds. | Own: 50-way burst, distinct keys |
| C5 | Replay of a successful correction (same key, same body) → 200 with that original revision even after newer revisions exist; same key, different body → 409 `idempotency_key_reuse`; a failed correction claims no key. | Own |
| C6 | The difference from the previous amount moves between the same two wallets in the same atomic step: an increase debits the original sender, a decrease debits the original receiver; current balances (`/me`) reflect it at once; totals conserved. | Harness; Own |
| C7 | A currently unaffordable debit (against `available`) → 409 `insufficient_funds`. Otherwise, if any user's corrected `total` or `available` would be negative at any past effective-time / hold-event boundary (all movements at one instant combined; latest known revisions) → 409 `historical_overdraft`. `insufficient_funds` takes precedence. Either failure leaves balances, revision history, statements, snapshots and idempotency state untouched. | Own |
| C8 | The original payment and every original idempotent response stay unchanged (replay of the original `POST /payments` returns the original body); `GET /activity` keeps showing the original payment (original amount) and corrections never appear as feed payments. | Own |
| C9 | Settlement members and captures are immutable linked payments: correcting one → 422 `linked_payment_immutable`. A payment made by paying a request is an ordinary payment and can be corrected. | Own |

## R. `GET /payments/{payment_id}/revisions`

| Row | Requirement | Check |
|---|---|---|
| R1 | → 200 `{"revisions": [...]}` in revision order, including revision 1 (`reason: ""`, `amount` as originally paid, `effective_at = recorded_at = created_at`); each element has `payment_id, revision, amount, effective_at, recorded_at, reason`. | Own |
| R2 | Only the two parties may read it; a third party (also a settlement operator) → 404 `not_found`, even for a public payment; unknown payment → 404; no token → 401. Settlement members: revision 1 has `effective_at = recorded_at = committed_at`. | Own |

## K. Recorded time: `known_at`

| Row | Requirement | Check |
|---|---|---|
| K1 | `GET /me` and `GET /statement` accept `known_at`: for each payment select its latest revision recorded at or before `known_at`; a payment with no revision recorded by then contributes nothing; then apply the selected revisions by their effective times. Omission = everything known when the read begins. | Own: grid of (as_of, known_at) over a history with several corrections, compared with an independent model |
| K2 | `as_of` stays inclusive; the statement window stays half-open; both instants may be in the future; with `known_at` in the future the result equals everything known now. | Own |
| K3 | A correction may move a payment into or out of a statement window (by changing `effective_at`) and changes ordering accordingly. | Own |

## N. Stable statement pagination (snapshots)

| Row | Requirement | Check |
|---|---|---|
| N1 | Every first `GET /statement` response (no `snapshot` parameter) returns an opaque `snapshot` token that freezes the caller's selected revisions, window, balances, entries and the default `to` of that read. | Own |
| N2 | `GET /statement?snapshot=<token>&limit=&offset=` pages exactly that result, also after later payments, corrections, captures, voids, expiry; old snapshots are unchanged by any of them, also while those run concurrently. | Own: take snapshot, mutate heavily, page and compare with the first read |
| N3 | Only `limit` and `offset` may accompany `snapshot`: `from`, `to` or `known_at` with it → 422 `validation_failed`. Unknown token, another user's token, a token from before the last reset → 404 `not_found`. Tokens last until reset. Unrecognised query parameters are still ignored. | Own |

## H. Settlement history, captures, earlier exports

| Row | Requirement | Check |
|---|---|---|
| H1 | Stage-1 settlements keep their original receipts and privacy rules; each member's revision 1 uses the shared `committed_at` as effective and recorded time. | Own |
| H2 | Imported stage-1/stage-2 state: every payment gets revision 1 from its `created_at`; opening balances = imported balance minus the net effect of all imported payments; statements and `as_of` reads work on imported history; captures stay linked and immutable; imported authorisations are accounted in historical holds. | Own |

## O. Historical holds

| Row | Requirement | Check |
|---|---|---|
| O1 | For `GET /me?as_of=T&known_at=K` all four money fields describe the same view: `balance = total`, `available = total − held`. | Own: model comparison |
| O2 | A hold starts at authorisation creation; a non-final capture reduces it at capture time; a final capture, void or expiry releases the remainder at that event's time; expiry takes effect at `expires_at`. | Own |
| O3 | Knowledge: events other than clock expiry are known at their server-assigned event time (so with `known_at` before a void or capture, that event is not applied); once the creation is known, the expiry deadline is known too. For query instants beyond now, an open hold expires at its deadline. Without `as_of`, T is the instant the request began. | Own |
| O4 | Authorisations expose `closed_at`: null while open; the event time when closed (final capture, void, or `expires_at` for expiry). | Own |
| O5 | Seeded open holds are assumed created at reset unless `created_at` is supplied; seeded closed holds need no reconstructed lifecycle (they hold nothing at any instant). | Own |
| O6 | Captures are payments: they move `total` at capture time and appear once in statements with their links. | Own |

## X. Concurrency and robustness

| Row | Requirement | Check |
|---|---|---|
| X1 | Corrections racing payments, captures, voids, settlements, other corrections and statement reads: results equal some serial order; totals conserved in every historical view; no negative current `available`; no 5xx. | Own: 50-in-flight mixed bursts with a model check afterwards |
| X2 | Stage-1 lessons apply to all new inputs: instants with extreme years/offsets/fractions, huge numbers, wrong types, deep bodies, odd ids in the path, mutation of the new fixture/import members → 4xx with the error body, never 5xx; own export always re-imports. | Own: fuzz + mutation sweep extended to revisions, snapshots, hold event times |

## Decisions on points the specification leaves open (change only via the Architect)

- G-1 Instant grammar (query instants, `effective_at`, seeded `created_at`/`expires_at`): `YYYY-MM-DDThh:mm:ss[.fraction](Z|±hh:mm)` with `T` and `Z` in upper or lower case, a real calendar date and time (seconds 00-59), offset hours 00-23 and minutes 00-59. Anything else (space separator, missing offset, bare date, empty, week dates, 24:00, leap second `:60`) → 422. Query values are decoded the standard way, so a raw `+` in the query string is a space and therefore invalid; clients send `%2B`. Fractions of any length are compared exactly (no rounding, no truncation); an instant whose UTC value falls outside years 0001-9999 → 422. Never 5xx.
- G-2 Service clock: every server-assigned event time (payment `created_at`, `committed_at`, revision `recorded_at`, authorisation `created_at`, capture/void times, snapshot read instants) comes from one monotonic clock under the lock, strictly increasing at microsecond resolution (`max(now, last + 1µs)`), written with a `+00:00` offset. After reset or import the clock continues after the latest instant in the state. So API-created payments never tie, a correction is always recorded after everything that existed before it, and a snapshot's knowledge cut is exact. Supplied instants (seeded `created_at`, `expires_at`, `effective_at`, `as_of`, `known_at`) are echoed exactly as given.
- G-3 Seeded payments without `created_at` all take the one reset instant (the spec's wording replaces stage-1 decision D-9 for stage 3); among equal instants `/activity` keeps fixture order as oldest → newest and statements order by payment id.
- G-4 "Payment id ascending" compares ids as strings by Unicode code point.
- G-5 `effective_at` and `as_of`/`known_at`/`from`/`to` responses: echo exactly as supplied (`effective_at` in the correction response, in `/revisions` and in statement entries is the supplied string; revision 1 uses the payment's `created_at` string).
- G-6 Correction check order (extends D-1): 401 → key present/length → body parse (unparseable or non-object → 400) → claimed key (replay 200 / 409 reuse) → field validation, where every missing, wrongly typed or out-of-range field of this endpoint is 422 `validation_failed` (the endpoint's own sentence "Invalid input is 422" outranks the general wrong-type rule) → 404 unknown payment → 403 not the sender → 422 `linked_payment_immutable` → 409 `stale_revision` → 409 `insufficient_funds` → 409 `historical_overdraft`.
- G-7 A correction with an unchanged amount (only `effective_at`/`reason` differ) is valid: it moves no money now but re-times the payment and is subject to the historical check.
- G-8 Historical check scope: evaluated for the sender and the receiver under the latest revisions including the new one, at every instant ≤ now where their `total` or `held` changes; movements at the same instant are combined before the test. A payment re-timed to before a signed-up account existed is judged against that account's opening balance of 0.
- G-9 Statement window with `from` later than `to` → 422 `validation_failed` (rule 3 could not hold); `from == to` → empty window with equal opening and closing balances.
- G-10 Snapshots: the token is an opaque string of at most 200 characters bound to the caller. Because revisions are append-only and the service clock is strictly increasing (G-2), a snapshot is fully determined by (user, `from`, resolved `to`, knowledge cut = min(supplied `known_at`, read instant)); the service may store exactly that, or issue a signed token whose secret changes on reset and travels in the export. No copy of the entries is needed and memory must not grow with the entries of each read. Snapshot responses repeat the `snapshot` token. With both a forbidden parameter and an unknown token → 422. An empty `snapshot=` → 404. Snapshots survive an export/import of this service's own export; importing replaces them (tokens of the previous destination state → 404).
- G-11 `/me` members: `as_of` and `known_at` appear only when supplied. With `known_at` alone, T is the request instant.
- G-12 Imported stage-2 authorisations: `closed_at` = time of the final capture for `captured`, `expires_at` for `expired`; a `voided` one whose void time the stage-2 export does not carry is treated as released at its last capture time, or at its creation if never captured (it then never holds historically; this avoids inventing historical overdrafts). Seeded closed holds: `closed_at` = `expires_at` for `expired` when that is not in the future, otherwise the reset instant. Stage-3 records the real event time of every void and capture and exports it.
- G-13 The historical `held` of a seeded or imported open hold starts at its `created_at` (reset instant when not supplied); a seeded authorisation `created_at` in the future → 422.
- G-14 No new screen is required by stage 3; the stage-2 UI keeps working unchanged against stage-3 (the feed shows original payments; wallet numbers are the current corrected values).
- G-15 Operators get no extra read access: `/revisions` of a settlement member is readable only by its two parties.
