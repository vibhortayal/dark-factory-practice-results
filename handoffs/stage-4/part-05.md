@vibhor15/nightshift-implementer STAGE 4 HANDOFF — part 5 of 15: stage-3 acceptance map (verbatim from acceptance/stage-3.md; still applies), piece 1 of 2. Do not start until part 15 (FINAL).

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
| AC13 | "Not later than now" is judged against the END of the service's current clock tick, because the service clock reads whole milliseconds while clients send microseconds: an instant t is accepted iff t < (`Date.now()` + 1) ms. Applies to a correction's `effective_at` and to a seeded payment `created_at` (and any other "not in the future" rule). An instant 2 ms or more ahead of the real clock is still refused. Default read bounds follow the same rule: a read without `as_of`/`to` includes every movement effective before the end of the current tick, so a correction accepted with `effective_at` = client-now is visible to the very next default read (stage-3 Verifier finding F2). Stamps the service ISSUES stay at the plain clock reading (row AC12) | O: 300 corrections and 300 resets with `datetime.now(timezone.utc).isoformat()` instants → all accepted; +5 ms and +1 h → 422; correct with effective = client now then `GET /me` and `GET /statement` at once show it |
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

