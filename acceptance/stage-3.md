# Stage 3 acceptance map (pocketful)

Source: `pocketful/spec/stage-3.md` (kickoff checkout), which keeps every stage-1 and stage-2
requirement in force. All rows of `acceptance/stage-1.md` (A1-J3) and `acceptance/stage-2.md`
(K1-S6) still apply to `stage-3/` unless a row below changes them; row T1 carries them.
"API test" is a black-box HTTP check against the running container. Rows marked **[reading]**
are Architect choices where the specification is open, with the reason. The supplied checks
cover only part of this map.

Terms used below. A payment has **revisions** `1..n`, each with `amount`, `effective_at`,
`recorded_at`, `reason`. A **view** is a pair (T, K): K = `known_at` (default: the instant the
request began), T = `as_of` (default: the instant the request began). In a view, each payment
contributes its latest revision with `recorded_at <= K` (nothing if none), as one movement of that
revision's `amount` at that revision's `effective_at`; it counts toward a balance at T when
`effective_at <= T`.

## T. Carry-over and delivery

| Row | Requirement | Check |
|---|---|---|
| T1 | Every row of the stage-1 map (A1-J3) and the stage-2 map (K1-S6) holds for `stage-3/`, with the stage-3 changes below (eight idempotent paths; new fields; stage boundary row T4 replaces K4). The browser UI of stage 2 keeps working unchanged; stage 3 requires no new screen. | Harness `--stage 3` runs suites 1, 2 and 3 against `stage-3/`; Verifier reruns its stage-1 and stage-2 lists (API and browser) against the stage-3 image |
| T2 | `stage-3/` is the accepted `stage-2/` (93f0fbd) copied and extended: complete, buildable on its own, own `Dockerfile` and `RUN.md`, no `.git`, symlinks or `__pycache__` inside; `stage-1/` and `stage-2/` are not modified. | `git diff` of `stage-1/` and `stage-2/` empty since their accepted revisions; clean build |
| T3 | A stage-3 service accepts exports produced by this team's stage-1 and stage-2 services and its own. Everything stage-1 §10 and stage-2 list as preserved is preserved; the ledger imports and accounts for authorizations and captures. Export still reports `track: "pocketful"`, `format_version: 1`. Revisions, opening balances, `closed_at` and idempotent correction responses survive a stage-3 export -> import into a fresh container. | API test: export from stage-1 and stage-2 containers with payments, holds, captures, a settlement; import into stage 3; check `/me`, `/statement`, revisions, replays, corrections |
| T4 | `stage-3/` implements stage 3 only, nothing from stage 4. | Harness `--stage 3` prints `claimed stage: 3 on the shipped checks`; its stage-4 overshoot line fails |
| T5 | Supplied checks pass: `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 3 --out ../band-work/checks/<new-name>` (suites 1, 2, 3); final run with `--mode isolated`. | Harness output |
| T6 | **[reading]** For history built from imported older exports: every imported payment gets revision 1 with `effective_at = recorded_at = created_at`; each user's opening balance is their imported balance minus the net effect of all imported payments; an imported hold closed by a final capture is closed at that capture's time, an expired one at `expires_at`, and a voided one whose void time the export does not carry is treated as closed at its last capture's time, or at its creation if it has none. Reason: the export of an earlier stage has no close time for a void; assuming the earliest possible release never invents held money in a past view, so it cannot cause a false `historical_overdraft`. | API test on an imported stage-2 export containing a voided hold |

## U. Payment timestamps and fixture (spec "Payment timestamps")

| Row | Requirement | Check |
|---|---|---|
| U1 | Every payment's `created_at` is an RFC 3339 instant with an offset saying when it moved money; every endpoint returning a payment includes it; `GET /activity` keeps ordering by it (newest first). | API test over all payment-returning endpoints |
| U2 | Seeded payments may supply `created_at` (kept exactly as given); omission uses the reset time, which is before every later API-created payment. A seeded `created_at` in the future -> 422 `validation_failed` from reset, nothing changed. **[reading]** an unparseable seeded `created_at` or one without an offset is also 422; the same rules apply to a `created_at` supplied on a seeded authorization. | API test |
| U3 | A fixture's `balance` is still the balance after all seeded payments; loading them does not change it. | API test |

## V. `GET /me` as of an instant

| Row | Requirement | Check |
|---|---|---|
| V1 | Without temporal parameters the response keeps the stage-2 fields exactly (no `as_of` or `known_at` key) and reports current corrected values. | API test (supplied) |
| V2 | `as_of` is an RFC 3339 instant with an offset (`Z` or `+hh:mm`/`-hh:mm`, optional fractional seconds). A naive local time, a bare date, an empty value, an impossible date or any other text is 422 `validation_failed`. The response echoes `as_of` exactly as given (the decoded query value, character for character). It may be in the future. | API test: valid forms; each invalid form |
| V3 | With `as_of = T`: `balance` is the caller's balance after every payment of theirs effective at or before T and before every later one; a payment at exactly T counts. T at or after the latest payment -> current balance; T before the earliest -> the opening balance. | API test with instants taken between payments, at a payment's exact `created_at`, one microsecond before it |
| V4 | Opening balance = seeded ending balance minus the net effect of the original seeded payments; a signed-up account opens at zero; corrections never change opening balances. The sum of all users' balances equals the seeded total in every view (T, K). | API test: sum over users at many (T, K) |
| V5 | `known_at = K` (optional, RFC 3339 with offset; invalid or empty -> 422; echoed exactly; may be in the future): each payment contributes its latest revision recorded at or before K, nothing if none was recorded yet; revisions apply at their effective times; `as_of` stays inclusive. Omitted K = everything known when the read begins. `known_at` without `as_of` uses T = the instant the request began. | API test: correct a payment, read with K before and after the correction's `recorded_at`, and exactly at it |
| V6 | Historical holds: for `GET /me?as_of=T&known_at=K` all four money fields describe the same view: `balance = total`, `available = total - held`. A hold starts at authorization creation; a non-final capture reduces it at capture time; a final capture, void or expiry releases the remainder at that event's time; expiry takes effect at `expires_at`. Events other than clock expiry are known at their own server-assigned time; once creation is known the expiry deadline is known too (so a view whose K is before a void but whose T is after `expires_at` shows the hold released by expiry). For T beyond now an open hold expires at its deadline. Without `as_of`, T is the instant the request began. | API test: create, partial capture, void/final capture/expiry, reading `held` at instants around each event and with K before/after each event |
| V7 | Authorizations expose `closed_at`: null while open; the event time when closed (final-capture time, void time, or `expires_at` for expiry). Seeded open holds are assumed created at reset unless `created_at` is supplied; seeded closed holds need not reconstruct a lifecycle. **[reading]** a seeded closed hold holds nothing in any view; its `closed_at` is a supplied `closed_at` if present, else `expires_at` when `expired`, else the reset time. | API test |

## W. `GET /statement`

| Row | Requirement | Check |
|---|---|---|
| W1 | `GET /statement?from=&to=&limit=&offset=` -> `{opening_balance, entries, closing_balance, has_more, snapshot}`; requires a token (401 otherwise). `from` and `to` optional RFC 3339 instants with offset (invalid or empty -> 422); `from` defaults to the opening of the wallet, `to` to now (the instant the request began, so a payment just made is included). `limit`/`offset` exactly as `GET /requests` (stage-1 row D7). **[reading]** `from` later than `to` is 422 `validation_failed`, because requirement 3 (opening plus deltas equals closing) cannot hold for an inverted window; `from == to` is an empty window with `opening_balance == closing_balance`. | API test |
| W2 | Entries are the payments the caller sent or received whose selected revision's `effective_at` is in the half-open window `[from, to)` (a payment at exactly `from` is in, at exactly `to` is out), oldest first: ordered by selected `effective_at` ascending, then payment id ascending for ties. **[reading]** ids compare as plain strings (code-point order), and instants compare as parsed instants, never as strings. | API test incl. settlement members (equal instants) and seeded payments sharing the reset time |
| W3 | Each entry: `payment` (the ordinary payment object, with `amount` = the selected revision's amount), `delta` (negative for a sent payment, positive for a received one), `balance_after` (caller's balance immediately after it), plus the selected `revision`, `effective_at`, `recorded_at`. A zero-amount revision still appears with `delta` 0. No correction is counted alongside the revision it replaces: one entry per payment. With no corrections and no `known_at` the result equals plain history by `created_at`. | API test |
| W4 | `opening_balance` = balance immediately before `from`; `closing_balance` = balance immediately before `to`; `opening_balance` + all deltas of the full window = `closing_balance`. Pagination changes neither an entry's `balance_after` nor opening/closing: they describe the whole window whatever `limit` and `offset` are. `has_more` is right on a final partial page, an exact page end and offsets beyond the end (empty `entries`, `has_more: false`). | API test paging a 7-entry window with limits 1, 3, 7, 8 and offsets up to 9 |
| W5 | Only payments the caller sent or received appear, even when other payments are public; feed visibility rules do not apply (the caller's own private payments appear). Money movements only: authorization, release and expiry are not entries; a capture appears exactly once with its `authorization_id`; settlement members appear with their `settlement_id`. | API test |
| W6 | `known_at` on a statement selects revisions as in V5 and is echoed exactly; the window stays half-open. | API test: a correction that moves a payment into / out of the window, read with K before and after |

## X. Corrections

| Row | Requirement | Check |
|---|---|---|
| X1 | Every payment has a revision history. Revision 1 has the original `amount` and `effective_at = recorded_at = created_at`, `reason: ""`. For a seeded payment the supplied `created_at` (or the reset time) is that time. For a settlement member it is the shared `committed_at`. | API test via revisions endpoint |
| X2 | `POST /payments/{payment_id}/corrections` is the eighth idempotent write path: key required (400 `missing_idempotency_key`, over-long 422), all stage-1 F rows apply (201 first, replay 200 same body even after newer revisions, different body 409 `idempotency_key_reuse`, failed key reusable, concurrent identical -> one 201). No token 401. | API test |
| X3 | Body `{expected_revision, amount, effective_at, reason}`, all required. `expected_revision` a positive integer; `amount` an integer 0..1000000000 (0 reverses the whole payment; integral JSON numbers as in stage 1); `reason` a string of 1..200 characters; `effective_at` an RFC 3339 instant with offset, not later than now. Invalid input is 422 `validation_failed`. **[reading]** "invalid input" includes a missing field and a wrong JSON type for any of the four fields (422, not 400), because this endpoint states one error for all invalid input. Boundaries: amount 0 and 1000000000 accepted, -1 and 1000000001 refused; reason 1 and 200 characters accepted, empty and 201 refused; `effective_at` equal to an instant just passed accepted, one in the future refused. | API test |
| X4 | Only the original sender may correct: any other authenticated caller (receiver, third party, operator) gets 403 `forbidden`; unknown payment 404. | API test |
| X5 | Success: 201 `{payment_id, revision, amount, effective_at, recorded_at, reason}`; appends an immutable revision numbered previous + 1; parties and visibility unchanged; `recorded_at` server-assigned and strictly increasing within a payment. **[reading]** `effective_at` is returned exactly as supplied. A correction that changes nothing (same amount and time) is accepted and appends a revision. | API test |
| X6 | `expected_revision` not equal to the payment's current revision -> 409 `stale_revision`. Concurrent corrections with the same expected revision (different keys) cannot both succeed: exactly one 201, the rest 409 `stale_revision`. | Concurrent API test, 50 in flight |
| X7 | Money: the difference from the previous amount moves between the same two wallets in the same atomic step; an increase debits the original sender, a decrease debits the original receiver. A debit the debited party cannot currently afford (judged against `available`, stage 2) -> 409 `insufficient_funds`. Sum of balances unchanged. | API test |
| X8 | Otherwise, if under the latest revisions (including the new one) either party's total or `available` (total minus held at that time) is negative at any past effective-time or hold-event boundary -> 409 `historical_overdraft`. A boundary includes the combined effect of all movements at that same instant. `insufficient_funds` takes precedence when both apply. | API test: move a payment's effective time before the money that funded it arrived; increase a payment that was funded exactly; a case passing only because two movements share an instant; a case failing only on `available` because of a hold |
| X9 | Either failure (and any other refusal) preserves balances, revision history, statements and idempotency state (the key stays unused). | API test comparing export before/after a refused correction |
| X10 | The original payment and every original idempotent response stay unchanged (replaying the original `POST /payments` still returns the original amount); `GET /activity` keeps showing the original payment; corrections are not feed items. | API test |
| X11 | `GET /payments/{payment_id}/revisions` -> `{"revisions": [...]}` in revision order including revision 1, each `{payment_id, revision, amount, effective_at, recorded_at, reason}`. Only the two parties may read it; a third party gets 404 even for a public payment (operators included); unknown payment 404; no token 401. | API test |
| X12 | Settlement members and captures are immutable linked payments: a correction of either gives 422 `linked_payment_immutable`. Settlement receipts and privacy rules are unchanged. **[reading]** payments made by paying a request are not named as immutable and stay correctable. | API test |
| X13 | **[reading]** Order of checks on a correction: 401; key header; body parse; claimed-key resolution; body validation (422 `validation_failed`); 404; 403; `linked_payment_immutable`; `stale_revision`; `insufficient_funds`; `historical_overdraft`. The last two are ordered by the spec; the rest follows stage-1 row D8. | API tests on combined-error requests |

## Y. Stable statement pagination

| Row | Requirement | Check |
|---|---|---|
| Y1 | Every first `GET /statement` response (one without a `snapshot` parameter) returns an opaque `snapshot` token. It freezes the caller's selected revisions, window, balances, entries and default `to` at that read. | API test |
| Y2 | `GET /statement?snapshot=<token>&limit=&offset=` pages exactly that result, unchanged by later payments, corrections, captures, voids or expiries, including ones concurrent with the paging. | API test: take a snapshot, then pay, correct (moving payments into and out of the window), page through and compare with the first read; concurrent writers while paging |
| Y3 | Only `limit` and `offset` may accompany `snapshot`: supplying `from`, `to` or `known_at` with it -> 422 `validation_failed`. Unrecognised query parameters stay ignored. Bad `limit`/`offset` -> 422. | API test |
| Y4 | Unknown token, another user's token, or a token from before a reset -> 404 `not_found`. Tokens last until reset; survival across a container restart is not required. **[reading]** an empty `snapshot=` value is an unknown token (404). The 422 of row Y3 is checked before the token lookup. | API test |
| Y5 | **[reading]** Snapshot responses carry the same top-level fields as the first read (`opening_balance`, `closing_balance`, the `known_at` echo if one was given, and the same `snapshot` token), with `entries`/`has_more` for the requested page. Snapshots are part of the service state: they survive export -> import into a stage-3 service and are cleared by reset; importing an older-stage export leaves none. Reason: "Tokens last until reset". | API test |

## Z. Concurrency and limits

| Row | Requirement | Check |
|---|---|---|
| Z1 | All stage-1/2 invariants hold with corrections in the mix: balances sum to the seeded total in every view, `available` never negative at any read, no 5xx, every request under 5 s with 50 in flight (statements and historical `/me` included, on a wallet with a few thousand payments). | Concurrent burst mixing payments, corrections, captures, statements and snapshots; timing |
| Z2 | Timestamps keep the stage-2 row K6 reading: one clock read per request, microsecond fixed-width server timestamps, never going backwards; supplied instants (`as_of`, `known_at`, `from`, `to`, `effective_at`, seeded `created_at`) are compared as parsed instants at full precision and echoed or stored exactly as given. | API test with instants in other offsets (`+02:00`, `Z`) and fractional seconds |
