# Acceptance map — Pocketful stage 3

Source: `dark-factory-wearedevs/pocketful/spec/stage-3.md` (complete) plus all of `stage-1.md`
and `stage-2.md` (still apply; `acceptance/stage-1.md` rows A1–J6 and `acceptance/stage-2.md`
rows K1–U4 remain in force for `stage-3/`). Target: `stage-3/`, started as a copy of the accepted
`stage-2/` (revision c59be33b). `stage-1/` and `stage-2/` must not change. "Supplied" = harness
`--stage 3` (runs the stage 1, 2 and 3 suites against `stage-3/`). "Own" = tests written from the
spec by the Implementer and independently by the Verifier.

Terms: T = `as_of`, K = `known_at`. "Selected revision" of a payment under K = its latest revision
with `recorded_at` ≤ K (none ⇒ the payment contributes nothing).

## V. Regression and delivery

| Row | Requirement | Check |
|---|---|---|
| V1 | All stage-1 rows A1–J6 and stage-2 rows K1–U4 hold for `stage-3/` (UI included; with no corrections and no temporal parameters all earlier behaviour is unchanged) | Supplied stage-1 + stage-2 suites against stage-3; own earlier check lists rerun |
| V2 | `stage-3/` self-contained: own Dockerfile + RUN.md (module map updated), clean build, isolated run, limits (2 vCPU / 2 GiB, 50 in flight, 5 s per request, 60 s start), no 5xx | Build, isolated run, load run incl. statement/correction mix |
| V3 | `stage-1/` identical to 172a3180 and `stage-2/` identical to c59be33b | `git diff` empty for both |
| V4 | No stage-4 features implemented early | Verifier step 5 against the stage-4 spec |

## W. Payment timestamps and fixture

| Row | Requirement | Check |
|---|---|---|
| W1 | Every payment returned by any endpoint (payments, pay, capture, settlements, activity, statement) carries `created_at` as RFC 3339 with offset = the instant it moved money; `/activity` still ordered by it, newest first | Own |
| W2 | Seeded payments may supply `created_at` (kept exactly as the same instant); omitted ⇒ reset time, earlier than any later API-created payment | Own |
| W3 | Seeded `created_at` in the future ⇒ 422 `validation_failed` from reset, no state change | Own |
| W4 | Fixture `balance` stays the balance after all seeded payments; loading them does not change it | Own |
| W5 | Opening balance = seeded ending balance − net effect of original seeded payments; never changed by corrections; new (signup) accounts open at 0 | Own: `as_of` before earliest payment, before and after a correction |

## X. `GET /me` with `as_of` / `known_at`

| Row | Requirement | Check |
|---|---|---|
| X1 | Without temporal parameters: existing fields, current corrected values | Own |
| X2 | `as_of` must be RFC 3339 with offset (`Z` or `±hh:mm`); naive local time, bare date, empty value, garbage ⇒ 422; same for `known_at` | Own matrix, incl. `%2B` encoding and fractional seconds |
| X3 | With `as_of`: balance after every payment of the caller effective at or before T and before every later one; payment exactly at T counts | Own boundary test (T = created_at, T − 1 µs/1 s) |
| X4 | T at/after latest payment ⇒ current balance; T before earliest ⇒ opening balance; future T allowed | Own |
| X5 | Response echoes `as_of` exactly as given (string-identical after URL decoding); `known_at` echoed exactly when supplied; absent when not supplied (not invented) | Own |
| X6 | `known_at`: for each payment use the latest revision recorded ≤ K, none ⇒ contributes nothing; omitted ⇒ everything known when the read begins; then apply by effective time; K may be in the future | Own: K before payment recorded, between revisions, after |
| X7 | All four money fields describe the same (T, K) view: `balance = total`, `available = total − held`; `held` from hold history (see AC rows) | Own |

## Y. `GET /statement`

| Row | Requirement | Check |
|---|---|---|
| Y1 | Requires auth (401 otherwise). `from`, `to` optional RFC 3339 with offset (else 422); `from` defaults to wallet opening, `to` to now; `limit`/`offset` exactly as `GET /requests` (D8/D9) | Own |
| Y2 | Returns only payments the caller sent or received (even private ones; never others' public ones) in the half-open window `[from, to)`: effective time = `from` included, = `to` excluded | Own boundary |
| Y3 | Shape `{opening_balance, entries:[{payment, delta, balance_after, revision, effective_at, recorded_at}], closing_balance, has_more, snapshot}`; `payment` is the full payment shape with `payment.amount` = selected amount | Own |
| Y4 | Order: selected `effective_at` ascending, then payment id ascending for ties (oldest first) | Own with tied timestamps (settlement members, seeded equal times) |
| Y5 | `opening_balance` = balance immediately before `from`; `closing_balance` = balance immediately before `to`; opening + Σ all deltas in the full window = closing; sent ⇒ negative delta, received ⇒ positive | Own |
| Y6 | Pagination never changes an entry's `balance_after`, nor opening/closing; these describe the full window for any `limit`/`offset`; `has_more` right on the final partial page and for offsets beyond the end (empty entries, `has_more: false`) | Own: page-by-page equals one-shot |
| Y7 | `known_at` on statements: selected revisions as X6; zero-amount selected revisions still appear with `delta: 0`; a correction is never counted alongside the revision it replaces; `known_at` echoed exactly when supplied | Own |
| Y8 | With no corrections and no `known_at`, ordering/values equal the plain `created_at` statement | Own |
| Y9 | Statements contain money movements only: authorizations, releases, voids and expiries are not entries; a capture appears exactly once with its `authorization_id` link; settlement members appear with `settlement_id` | Own |
| Y10 | Unrecognised query parameters ignored | Own |

## Z. Corrections and revisions

| Row | Requirement | Check |
|---|---|---|
| Z1 | Every payment has revision 1: original `amount`, `effective_at = recorded_at = created_at`, `reason: ""`; seeded payments use supplied `created_at` or reset time; settlement members use `committed_at` | Own via `/revisions` |
| Z2 | `POST /payments/{id}/corrections`: idempotency key required (§7 rules: missing 400, length, replay, reuse, concurrency, failed key reusable — eighth idempotent path); no token 401; unknown payment 404; authenticated non-sender (receiver or third party) 403 | Own |
| Z3 | Body: all four fields required (missing ⇒ 422); `expected_revision` positive integer; `amount` integer 0..1000000000 (0 ok, 1e9 ok, −1 and 1e9+1 ⇒ 422); `reason` string 1..200 chars (empty and 201 ⇒ 422); `effective_at` RFC 3339 with offset, not later than now (future ⇒ 422); every invalid input ⇒ 422 `validation_failed` | Own matrix |
| Z4 | Success: 201 `{payment_id, revision, amount, effective_at, recorded_at, reason}`; revision = previous + 1; `recorded_at` server-assigned and strictly increasing per payment; revisions immutable; parties and visibility unchanged | Own |
| Z5 | Stale `expected_revision` ⇒ 409 `stale_revision`; concurrent corrections with the same expected revision: exactly one succeeds | 20-way concurrent, different keys |
| Z6 | Replay of a successful correction ⇒ 200 with that original revision even after newer revisions; same key + different body ⇒ 409 `idempotency_key_reuse` | Own |
| Z7 | The difference from the previous amount moves between the same two wallets atomically: increase debits the original sender, decrease debits the original receiver; amount 0 reverses the whole payment; sum of balances unchanged | Own |
| Z8 | Currently unaffordable debit (against `available`) ⇒ 409 `insufficient_funds`; takes precedence over `historical_overdraft` | Own |
| Z9 | Otherwise, any user's corrected balance (total or available) negative at any effective-time / hold-event boundary, under latest known revisions ⇒ 409 `historical_overdraft`; boundary balances combine all movements at the same instant | Own: back-date an increase before the funding payment; same-instant in+out is fine |
| Z10 | Either failure (and 422/403/404/stale) preserves balances, revision history, statements and idempotency state (key not claimed) | Own |
| Z11 | Sum of balances equals the seeded total in every historical view (any T, K) | Own: sum of `/me?as_of&known_at` over all users at many instants |
| Z12 | Original payment object and every original idempotent response unchanged after correction (replay of `POST /payments` returns the original amount); `/activity` shows the original payment; corrections add no feed items | Own |
| Z13 | `GET /payments/{id}/revisions` ⇒ `{"revisions":[...]}` in revision order incl. revision 1; only the two parties; third party ⇒ 404 even for a public payment; unknown ⇒ 404; no token ⇒ 401 | Own |
| Z14 | Settlement members and captures are immutable linked payments: correction ⇒ 422 `linked_payment_immutable`; their receipts and privacy unchanged. (Request-paid payments are ordinary and correctable.) | Own |
| Z15 | A correction changing `effective_at` moves a payment into or out of a statement window and changes historical `as_of` balances accordingly | Own |

## AA. Statement snapshots

| Row | Requirement | Check |
|---|---|---|
| AA1 | Every first (non-snapshot) `GET /statement` response carries an opaque `snapshot` token freezing the caller's selected revisions, window, balances, entries and default `to` | Own |
| AA2 | `GET /statement?snapshot=<token>&limit&offset` pages exactly that result, unchanged after later payments, corrections or hold lifecycle actions, including under concurrency | Own: snapshot, mutate, page; compare to pre-mutation one-shot |
| AA3 | Only `limit` and `offset` may accompany `snapshot`: `from`, `to` or `known_at` with it ⇒ 422; unrecognised parameters still ignored | Own |
| AA4 | Unknown token, another user's token, or a token from before a reset ⇒ 404 `not_found`; tokens last until reset; need not survive a restart. (Amended 21:15Z: import is not reset — see AB4.) | Own |
| AA5 | Snapshot paging: `has_more` correct on final partial page and beyond the end; `limit`/`offset` validation still applies | Own |

## AB. Export / import across stages

| Row | Requirement | Check |
|---|---|---|
| AB1 | Stage-3 accepts exports from this repo's stage-1 and stage-2 services (204); the ledger accounts for imported payments, settlements, authorizations and captures: revision 1 for every imported payment, opening balances derived, statements and `as_of` consistent with imported balances | Export from real stage-1 and stage-2 containers → import into stage-3 |
| AB2 | Stage-3 export/import round-trips revisions, correction idempotency records, hold event history (`created_at`, `closed_at`), opening balances | Own |
| AB4 | (Added 21:15Z.) Statement snapshots are part of the exported state: `GET /_test/export` carries every live snapshot (token, owner, frozen window, balances, entries), and `POST /_test/import` restores them, so a token issued before the export pages the identical frozen result after import into the same or another stage-3 container; a token that is not in the imported state (issued on the destination before the import, or after the export was taken) ⇒ 404. Export size/time stays within the 10 s control-call limit. Importing a stage-1/2 export (no snapshots) still works | Own: snapshot, mutate, export, import into a fresh container, page with the old token and compare |
| AB3 | Stage-2 upgrade rows R2–R4 still hold on stage-3 (signed-in browser, pending request payable, lost payment retry) | Browser |

## AC. Historical holds

| Row | Requirement | Check |
|---|---|---|
| AC1 | Authorizations expose `closed_at`: null while open; the event time when captured-final / voided / expired (expiry ⇒ `expires_at`) | Own |
| AC2 | `GET /me?as_of=T&known_at=K`: hold starts at authorization creation; a nonfinal capture reduces it at capture time; final capture, void or expiry releases the remainder at that event's time; expiry takes effect at `expires_at` | Own timeline test at each boundary |
| AC3 | Knowledge: non-expiry events are known at their server-assigned event time; once creation is known the expiry deadline is known; for T beyond now an open hold expires at its deadline; without `as_of` the view instant is when the request began | Own: K before a void ⇒ hold still counted up to its deadline; future T ⇒ released |
| AC4 | Seeded open holds are assumed created at reset unless `created_at` is supplied; seeded closed holds need no reconstructed lifecycle (hold nothing) | Own |
| AC5 | Correction that makes `available` (total − held) negative at any past boundary ⇒ 409 `historical_overdraft`; current shortfall still `insufficient_funds` first | Own |
| AC6 | Old snapshots unchanged after any hold lifecycle action or correction | Own |

## Supplied checks

From `/home/ubuntu/nightshift-claude-bg-test/dark-factory-wearedevs`:

    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 3 --out ../band-work/checks/<new-name>

Final run adds `--mode isolated`. Every run needs a new `--out` directory.

## Recorded choices

- Amendment 21:15Z (Architect's own error, found when reading stage 4): the first map said a
  snapshot token is invalid after import. The stage-3 spec only says "a token from before reset
  gives 404" and "Tokens last until reset"; §10 says import "atomically replaces the service's
  state" with the exported state and that "existing receipts, tokens and retries must remain valid
  after import"; and stage 4 requires that a later service accept this stage's exports "retaining
  settlement membership, corrections and snapshots". So snapshots belong in the export and must
  survive import. Rows AA4 and AB4 now say so.

- No new UI is specified for stage 3; the stage-2 UI must keep working unchanged. No statement or
  correction screen is required, and none should be added beyond what the spec asks.
- "Not later than now" for `effective_at`: equal to the request's own instant is allowed.
- Balance of the corrected wallet "currently unaffordable" is evaluated against `available`
  (stage-2 rule for every `insufficient_funds`).
- Correction precedence: 401 → body parse 400 → key missing/length → claimed-key resolution (§7) →
  404 → 403 → field validation 422 → `linked_payment_immutable` 422 → `stale_revision` 409 →
  `insufficient_funds` 409 → `historical_overdraft` 409. (404/403 are resource checks and so come
  after key resolution per §7; the spec orders nothing else, so this follows the stage-2 capture order.)
- A correction whose amount and `effective_at` equal the current revision is still a valid new revision.
- `/me` without `known_at`/`as_of` does not echo those fields.
- Instants are compared as instants (offset-aware), echoed as strings exactly as supplied.
- Timestamps need sub-second precision so that `recorded_at` strictly increases and ties are rare;
  microsecond RFC 3339 output is acceptable.
