# Acceptance map: stage 3

Sources: `pocketful/spec/stage-3.md` ("S3"), `stage-2.md` ("S2") and `stage-1.md` (§ numbers)
in the kickoff checkout. Target folder: `stage-3/`, created by copying the accepted `stage-2/`
(revision 88b9223d3e56cd9a668499f3cd5b87575d0ea114) and extending that code.
Every row of `acceptance/stage-1.md` (A1..K10 with A12, A13) and `acceptance/stage-2.md`
(M1..V7 with Q11) continues to apply to `stage-3/` except where a row here says it changes;
rows L1 and Z1 are replaced by ZZ1.
"Check": `H` = supplied harness run, `P` = the Verifier's own HTTP probe, `B` = browser probe,
`I` = inspection. Rows marked **[D]** are the Architect's resolution of an open choice, with the reason.

Vocabulary used below. A payment's **selected revision** in a view with knowledge instant K is its
latest revision whose `recorded_at` is at or before K (with no `known_at`: its latest revision at
the moment the read begins); a payment with no such revision is absent from the view. A payment's
**movement** in a view is one transfer of the selected revision's `amount` from sender to receiver
at the selected revision's `effective_at`. A **boundary** is any instant at which a movement or a
hold event takes place.

## AA. Carry-over and upgrade

| Row | Requirement | Check |
|---|---|---|
| AA1 | `stage-3/` is a complete, buildable folder of its own (source, `Dockerfile`, `RUN.md`), copied from `stage-2/` and extended; `stage-1/` and `stage-2/` are not modified. No `.git`, symlink or submodule inside; everything needed at run time is in the image. | I; H isolated |
| AA2 | Every stage-1 and stage-2 row still holds on `stage-3/`: suites 1 and 2 pass, the Verifier's stage-1 and stage-2 API and browser probes pass. The browser product is unchanged in behaviour and keeps working against the corrected ledger (the wallet shows current corrected values; the feed shows original payments). No new screen is required by S3. | H, P, B |
| AA3 | A stage-3 service accepts an unchanged export produced by the stage-1 service and by the stage-2 service (`format_version: 1`). Everything those stages preserved is preserved (accounts, logins, tokens, balances, payments, requests, settlements, operator grants, authorisations, captures, lifetime setting, idempotency records). In addition the ledger accounts for them historically: every imported payment has revision 1 with `effective_at = recorded_at = created_at` (settlement members: their `committed_at`); opening balances are derived so that every historical view sums to the seeded total; holds and captures take part in historical `held` and `available` by their recorded times. | H, P: export from real stage-1 and stage-2 containers with rich state |
| AA4 | **[D]** An imported authorisation that is closed but carries no close time (stage-2 states) gets `closed_at`: the `expires_at` if `expired`; the time of its last capture if it has captures; otherwise its `created_at`. Reason: S3 lets seeded closed holds skip reconstructing a lifecycle; the earliest consistent time means such a hold never inflates historical `held`. | P |
| AA5 | Stage-3 export/import (§10) also preserves every revision of every payment (amounts, effective and recorded times, reasons), `closed_at`, statement snapshot tokens (they keep paging the same frozen result after import), and the idempotency records of all eight write paths. The export keeps `track: "pocketful"`, `format_version: 1`; state layouts of stages 1, 2 and 3 are told apart inside `state`. Tampered or inconsistent states are 422 with the destination unchanged; no 5xx. | P |
| AA6 | After reset and after import the service's clock never runs behind the state: every timestamp it issues is strictly later than the reset instant and not earlier than any instant already recorded in the imported state. | P |

## BB. Instants

| Row | Requirement | Check |
|---|---|---|
| BB1 | An instant parameter or field (`as_of`, `known_at`, `from`, `to`, `effective_at`, seeded `created_at`) is valid iff it is an RFC 3339 date-time with an explicit offset: `YYYY-MM-DDTHH:MM:SS`, optional fraction of any length, then `Z` or `±HH:MM`, naming a real calendar date and time. A naive local time, a bare date, an empty value, an impossible date (`2026-02-30`), hour 24, a number, anything else -> 422 `validation_failed`. **[D]** `t` and `z` in lower case are accepted; a seconds value of 60 is rejected. | P |
| BB2 | Instants are compared exactly as instants at whatever fractional precision they were given (microseconds from a client must not be truncated or rounded into an equal or different instant); different spellings of one instant (offsets, `Z`, trailing zeros) are equal. | P: instants one microsecond either side of a payment's `created_at` |
| BB3 | A supplied instant that the service returns is returned exactly as given: `as_of` and `known_at` echoes, a correction's `effective_at`, a seeded `created_at`. Echo fields are present only when the parameter was supplied (`GET /me` without `as_of` has no `as_of` key). | H, P |
| BB4 | **[D]** In a query string an instant written with a raw `+` (which URL decoding turns into a space) is read as that `+` offset and echoed with `+`. Reason: the instant is unambiguous and the specification's own example needs `%2B` only because of this decoding. | P |
| BB5 | **[D]** "Not later than now" for `effective_at` is judged to the service's clock tick: an instant inside the current millisecond is not in the future. Reason: clients send microsecond instants taken a fraction of a millisecond before the service reads its millisecond clock. | P |

## CC. Payment timestamps, seeding, opening balances (S3 "Payment timestamps", "Effective time…")

| Row | Requirement | Check |
|---|---|---|
| CC1 | Every payment on every endpoint carries `created_at`, an RFC 3339 instant with offset naming when it moved money. `GET /activity` keeps ordering newest first by it and keeps showing the original payment (original amount) after any correction. | H, P |
| CC2 | A seeded payment may supply `created_at` (returned as given); omitted means the reset instant, which is strictly before every payment later created through the API. A seeded `created_at` in the future, or not a valid instant, makes reset 422 `validation_failed` with no state change. | P |
| CC3 | The fixture `balance` is still the balance after all seeded payments; loading them changes no balance. Opening balance of a seeded user = seeded balance minus the net effect of the original seeded payments; of a signed-up user = 0. Corrections never change an opening balance. Opening balances sum to the seeded total. | P |
| CC4 | Revision 1 of every payment has the original `amount`, `effective_at = recorded_at = created_at`, `reason: ""`. For a settlement member all three equal the shared `committed_at`. | P |

## DD. Historical `GET /me` (S3 "GET /me as of an instant", "known_at", "Historical holds")

| Row | Requirement | Check |
|---|---|---|
| DD1 | Without `as_of` and `known_at`, `GET /me` is as in stage 2 and reports current corrected values (the effect of every latest revision). | H, P |
| DD2 | `GET /me?as_of=T`: `balance` = opening balance plus every movement of the caller with effective time at or before T (a payment at exactly T counts). T at or after the latest movement gives the current balance; T before the earliest gives the opening balance; T may be in the future. The response echoes `as_of`. | H, P |
| DD3 | `known_at=K` selects revisions as in the vocabulary: revisions recorded after K are ignored, payments first recorded after K contribute nothing; then the selected revisions apply by their effective times. K may be in the future. Without `as_of`, the view instant is the instant the request began. The response echoes `known_at`. | P |
| DD4 | In every such view all four money fields describe the same view: `balance = total`, `available = total − held`, `held` = holds standing at T as known at K. A hold starts at the authorisation's `created_at`; a non-final capture reduces it at the capture's time; a final capture, a void or expiry releases the remainder at that event's time; expiry takes effect at `expires_at` (at T equal to `expires_at` the hold is released). Creation, captures and voids are known from their event time; once creation is known, the expiry deadline is known too. For T beyond now an open hold is released at its deadline. | P: views before, between and after each event, with K before and after it |
| DD5 | Seeded open holds start at the reset instant unless the fixture supplies `created_at`. Seeded closed holds (and seeded `open` ones already past `expires_at` at reset) contribute no historical hold. | P |
| DD6 | Every authorisation response carries `closed_at`: null while open; the event time when closed (final or completing capture time, void time, `expires_at` for expiry). | P |
| DD7 | In every historical view (any T, any K) the sum of all users' `total` equals the seeded total, and no user's `total` or `available` is negative at any boundary. | P: sweep T and K over all boundaries after a sequence of payments, holds and corrections |

## EE. Statements (S3 "GET /statement", "known_at", "Stable statement pagination")

| Row | Requirement | Check |
|---|---|---|
| EE1 | `GET /statement?from&to&limit&offset&known_at` requires a token (401 otherwise) and returns `{opening_balance, entries, closing_balance, has_more, snapshot}` plus the `known_at` echo when supplied. Entries are the caller's own sent or received payments only (private ones included, other people's public ones excluded) whose movement falls in the half-open window `[from, to)`. | H, P |
| EE2 | Each entry: `payment` (the payment object, with `amount` replaced by the selected amount for this statement; all other fields, including `created_at`, original), `delta` (negative for sent, positive for received, 0 for a zero-amount revision, which still appears), `balance_after`, and the selected `revision`, `effective_at`, `recorded_at`. A corrected payment appears once, by its selected revision only. Captures appear exactly once with `authorization_id`; authorisation, release and expiry are not entries. | H, P |
| EE3 | Order: selected `effective_at` ascending, then payment id ascending. **[D]** Ids compare as strings by code point (the literal reading; `p_10` sorts before `p_9`). Reason: the specification says "payment id ascending" and ids are opaque strings. | P with tied instants |
| EE4 | `opening_balance` = balance immediately before `from`; `closing_balance` = balance immediately before `to`; `opening_balance` + sum of every `delta` in the full window = `closing_balance`. `balance_after` is the running balance in entry order over the full window. Pagination changes none of these: every page reports the same opening and closing balances and each entry the same `balance_after`. | H, P |
| EE5 | `from` defaults to the opening of the wallet (so `opening_balance` is the wallet's opening balance). `to` defaults to now. **[D]** The default `to` lies just after everything that has already taken effect when the read begins, so a payment made immediately before the read (same clock tick) is inside the window and `closing_balance` is the current balance. Reason: with a half-open window and millisecond stamps, "now" taken literally would drop a payment made in the same millisecond. | H, P: pay then read at once, repeatedly |
| EE6 | `from`, `to`, `known_at` invalid or empty -> 422. **[D]** `from` later than `to` -> 422 `validation_failed` (the arithmetic of EE4 cannot hold); `from` equal to `to` is an empty window with `opening_balance = closing_balance`. `limit` and `offset` as in row C9. Unknown query parameters are ignored. | P |
| EE7 | Every first read returns an opaque `snapshot` token that freezes that read: the selected revisions, the window (including the resolved default `to`), balances and entries. `GET /statement?snapshot=<token>&limit&offset` pages exactly that result (same token returned, same `known_at` echo as the first read) whatever payments, corrections or hold events happen later. The final partial page and offsets beyond the end report `has_more` correctly. | P |
| EE8 | With `snapshot`, only `limit` and `offset` may accompany it: `from`, `to` or `known_at` present -> 422 `validation_failed`. Unknown token, another user's token, a token from before a reset -> 404 `not_found`. Tokens last until reset; they are not guessable from one another. | P |
| EE9 | A correction may move a payment into or out of a window in new reads; existing snapshots are unchanged, including while payments and corrections run concurrently. | P bursts |
| EE10 | With no corrections and no `known_at`, statements behave exactly as the first half of S3 describes (ordering by `created_at`, then id). | H, P |

## FF. Corrections (S3 "Effective time, recorded time, and corrections", "Settlement history")

| Row | Requirement | Check |
|---|---|---|
| FF1 | `POST /payments/{payment_id}/corrections` is the eighth idempotent write path (all §7 rules). Body `{expected_revision, amount, effective_at, reason}`, all required. 201 with `payment_id, revision, amount, effective_at, recorded_at, reason`. It appends an immutable revision; parties and visibility never change. | H, P |
| FF2 | Validation: `expected_revision` a positive integer; `amount` an integer 0..1000000000 (0 reverses the payment); `reason` a string of 1..200 characters (code points); `effective_at` a valid instant not later than now. **[D]** Every invalid or missing field on this endpoint, including a wrong JSON type, is 422 `validation_failed` (S3: "Invalid input is 422"); 400 stays for a body that is not a JSON object. Integral JSON numbers (`1.0`, `4e2`) are valid integers as in row C3. | P |
| FF3 | Unknown payment -> 404. Any authenticated caller who is not the original sender (the receiver, a third party, an operator) -> 403 `forbidden`. A settlement member or a capture payment -> 422 `linked_payment_immutable`. `expected_revision` not equal to the payment's latest revision number -> 409 `stale_revision`. **[D]** Precedence: 401 -> key -> body -> replay/reuse -> field validation 422 -> 404 -> 403 -> `linked_payment_immutable` -> `stale_revision` -> `insufficient_funds` -> `historical_overdraft`. Reason: same order as rows E5, F5, O6; the last two are ordered by S3. | P |
| FF4 | Money: the difference from the previous amount moves between the same two wallets in the same atomic step as the revision: an increase debits the original sender, a decrease debits the original receiver. The debited wallet's current `available` below the difference -> 409 `insufficient_funds`. A correction that changes only `effective_at` or `reason` moves no current money. | H, P |
| FF5 | Otherwise, if under the latest revisions including the proposed one either party's `total` or `available` would be negative at any boundary up to now (movements and hold events at one instant are combined before judging) -> 409 `historical_overdraft`. **[D]** A boundary that was already negative before the correction and is not made lower by it does not reject the correction. Reason: S3 says "makes … negative" and assumes seeded history is consistent; a fixture that is not must not freeze every later correction. | P: raise a past payment beyond what the sender then held; move a received payment later than the spend it funded; with a hold standing at the boundary |
| FF6 | Either failure, and every other refusal, leaves balances, revision history, statements, snapshots and idempotency state unchanged (the key stays free). | P |
| FF7 | `recorded_at` is assigned by the service and strictly increases along one payment's revisions, also when two corrections land in the same clock tick. | P |
| FF8 | A successful replay returns the original revision with 200 even after newer revisions; the same key with a different body is 409 `idempotency_key_reuse`. Concurrent corrections with the same `expected_revision` and different keys: exactly one 201, the others 409 `stale_revision`. | P at 50 in flight |
| FF9 | The original payment and every original idempotent response stay unchanged: `GET /activity`, the replay of the original `POST /payments`, of a request payment, of a capture and of a settlement return the original amounts. A correction is not a feed item. | P |
| FF10 | `GET /payments/{payment_id}/revisions` -> `{"revisions":[…]}` in revision order including revision 1 (`reason: ""`), each with `payment_id, revision, amount, effective_at, recorded_at, reason`. Only the two parties may read it; a third party gets 404 even for a public payment (an operator who is not a party included); unknown payment 404; no token 401. | P |
| FF11 | After any sequence of corrections, current balances sum to the seeded total, `available` is never negative, and requests, authorisations and settlements keep their recorded state (a corrected request payment leaves the request `paid` with its original amount). | P |
| FF12 | Concurrent payments, holds, captures, corrections and statement reads give results equal to some one-at-a-time order; every row holds at every read. | P at 50 in flight |

## ZZ. Stage boundary

| Row | Requirement | Check |
|---|---|---|
| ZZ1 | `stage-3/` implements stages 1 to 3 only: nothing from stage 4. The harness run for stage 3 ends `claimed stage: 3 on the shipped checks` with stages 1, 2 and 3 `pass` and the stage-4 overshoot line `fail`. | H, I |
| ZZ2 | Written to the specification, not to the supplied checks (which cover about a tenth of S3). | I |
| ZZ3 | Maintainable: the historical ledger (revisions, views, statements, snapshots) lives in its own modules with unit tests; instants have one parser and one comparison; the synchronous-commit rule and the per-request clock from stage 2 are kept; RUN.md describes the stage-3 design. | I |

## Commands

From `/home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs`:

```sh
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 3 --out ../band-work/checks/<new-name>
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 3 --mode isolated --out ../band-work/checks/<new-name>
```

Every run needs a new `--out` directory. The final check of the stage is the isolated one.
