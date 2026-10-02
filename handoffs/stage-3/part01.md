@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier Rows: stage-3 map AA1..ZZ3, stage-2 map M1..V7 with Q11, stage-1 map A1..K10 · Revision: 346e1a9e2cff5a4a338879f217599a6857a555a2 (maps and status; stage-1/ accepted at 77409dda43334b784ca1125d2d990ba51478abf6, stage-2/ accepted at 88b9223d3e56cd9a668499f3cd5b87575d0ea114; stage-3/ does not exist yet) · Files: acceptance/stage-3.md, acceptance/stage-2.md, acceptance/stage-1.md, STATUS.md · Command: n/a · Expected / actual: stage-3/ to be built / not yet built · Repro: n/a · Next: Implementer builds stage-3/ and reports a committed revision; Verifier prepares its checks now and waits for that revision.

STAGE 3 HANDOFF, in 13 numbered parts. Part 13 is the final part. Do not act until you hold all thirteen.

Stage 1 is accepted at 77409dda43334b784ca1125d2d990ba51478abf6 and stage 2 at 88b9223d3e56cd9a668499f3cd5b87575d0ea114 (both Verifier PASS). This handoff starts stage 3.

## The human's task (complete, verbatim)

"You are the lead seat for our factory. Build all four stages sequentially, coordinating the other seats and keeping every stage in its own complete, buildable folder.

Workspace root: /home/ubuntu/nightshift-claude-run-6
Kickoff checkout (read-only reference): /home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs
Track: pocketful
Result repository: /home/ubuntu/nightshift-claude-run-6/band-work/result

For stage 1, read the full spec at /home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs/pocketful/spec/stage-1.md and deliver it in /home/ubuntu/nightshift-claude-run-6/band-work/result/stage-1/ as a complete, buildable service with its own Dockerfile and RUN.md. Implement each stage fully, and only then move to the next.

When stage 1 is accepted, continue to stage 2: copy the stage-1 folder to stage-2 and extend that code to the stage-2 spec (pocketful/spec/stage-2.md). Continue the same way to stage 3 and stage 4. At the end there is one folder per stage, each satisfying its own spec and every earlier one, and none implementing a later stage early.

Checks, run from the kickoff checkout: .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage N --out ../band-work/checks/<new-name>. Run the final check of each stage with --mode isolated. Every run needs a new --out directory.

This is a dark-factory run: this message is the only human input. Finish with one final report."

## This unit

- Unit: stage 3 only. Stage 4 is not to be started or anticipated.
- Result repository (absolute): /home/ubuntu/nightshift-claude-run-6/band-work/result
- Target folder: /home/ubuntu/nightshift-claude-run-6/band-work/result/stage-3/, created by copying /home/ubuntu/nightshift-claude-run-6/band-work/result/stage-2/ as it is at revision 88b9223d3e56cd9a668499f3cd5b87575d0ea114 and extending the copy. stage-1/ and stage-2/ must not change.
- Read-only reference checkout: /home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs (specifications at pocketful/spec/stage-3.md, stage-2.md, stage-1.md).
- Contents of this handoff: part 1 = the complete stage-3 specification; parts 2 and 3 = the complete stage-2 specification; parts 4 to 6 = the complete stage-1 specification; parts 7 and 8 = the complete stage-3 acceptance map (acceptance/stage-3.md); parts 9 to 11 = the complete stage-2 acceptance map as it stands (with row Q11); parts 12 and 13 = the complete stage-1 acceptance map as it stands; part 13 ends with what each seat does.
- The supplied checks cover about a tenth of the stage-3 specification. The specifications and the acceptance maps are the contract; build and verify to them, never to the checks.
- No human is available. Do not ask the human anything. Questions about the reading of the specification go to the Architect in this room.

## Commands (run from /home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs)

    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 3 --out ../band-work/checks/<new-name>
    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 3 --mode isolated --out ../band-work/checks/<new-name>

Every run needs a new --out directory (s3-impl-NN for the Implementer, s3-ver-NN for the Verifier). `--stage 3` builds stage-3/, runs suites 1, 2 and 3 against it with the earlier stage folders as upgrade sources, and runs suite 4 as the overshoot probe. A correct run prints `stage 1: pass`, `stage 2: pass`, `stage 3: pass`, `stage 4: fail` and ends `claimed stage: 3 on the shipped checks`. The final check of the stage is run with --mode isolated.

## SPECIFICATION, stage 3, complete text

# Pocketful — Stage 3: statements and payment corrections

The requirements from stages 1 and 2 continue to apply, with the additions below.
Numbered section references such as §5 and §7 refer to `stage-1.md`.

Users can request historical balances and paginated statements. Senders can correct
eligible payments while preserving the original receipt. Historical queries must support
both the effective date of a payment and the information available at a specified time.

## Payment timestamps

Every payment's `created_at` is an RFC 3339 instant with an offset identifying when it
moved money. Every endpoint returning a payment includes it. `GET /activity` retains its
existing ordering by this field.

Seeded payments may supply `created_at`; omission uses reset time, before subsequent
API-created payments. A seeded `created_at` in the future gives `422 validation_failed`
from `POST /_test/reset`, with no state change.

A fixture's `balance` remains the balance after all seeded payments. Loading those
payments must not change that balance.

## `GET /me` as of an instant

```http
GET /me?as_of=2026-09-24T13:20:00%2B00:00
```

`as_of` is optional and is an RFC 3339 instant with an offset. Anything else — a naive local
time, a bare date, an empty value — is 422 `validation_failed`. Without temporal query
parameters the response retains the existing money fields and reports current corrected values.

With it, `balance` is the caller's balance as it stood at that instant: the balance after every
payment of theirs with `created_at` at or before `as_of`, and before every payment after it. A
payment made at exactly `as_of` counts as having happened.

- An `as_of` at or after the latest payment returns the current balance.
- An `as_of` before the earliest payment returns the opening balance — what the wallet held
  before anything moved.
- The response carries `as_of` back, exactly as given.

## `GET /statement`

```http
GET /statement?from=<instant>&to=<instant>&limit=50&offset=0
```

Both `from` and `to` are optional; `from` defaults to the opening of the wallet and `to` to now.
`limit` and `offset` behave exactly as in `GET /requests`.

Returns the payments the caller sent or received in the half-open window `[from, to)`, **oldest
first**, each with the caller's balance immediately after it:

This abbreviated example omits the revision fields and `snapshot` token described below.

```json
{ "opening_balance": 10000,
  "entries": [
    { "payment": { "...": "..." }, "delta": -500, "balance_after": 9500 },
    { "payment": { "...": "..." }, "delta": 1200, "balance_after": 10700 }
  ],
  "closing_balance": 10700,
  "has_more": false }
```

Statement requirements:

1. Entries are ordered by `created_at` ascending, then payment `id` ascending for ties.
2. `opening_balance` is the balance immediately before `from`. `closing_balance` is the
   balance immediately before `to`.
3. `opening_balance` plus all `delta` values in the full window must equal `closing_balance`.
   A sent payment has a negative `delta`; a received payment has a positive `delta`.
4. Pagination must not change an entry's `balance_after` or the window's opening and closing
   balances. These values describe the full window regardless of `limit` and `offset`.

Only payments sent or received by the caller appear in their statement, including when
other payments are public. The activity-feed visibility rules do not apply to statements.

## Effective time, recorded time, and corrections

The service must distinguish **when money took effect** from **when it learned that fact**.
Every payment has a revision history. Revision 1 has `amount` as originally paid and
`effective_at = recorded_at = created_at`. A seeded payment's supplied `created_at` is also
its original recorded/effective time; omission uses reset time. Opening balances equal
seeded ending balances minus the net effect of original seeded payments. Corrections must
not change those opening balances. New accounts open at zero. Seeded history is consistent
and nonnegative.

`POST /payments/{payment_id}/corrections` requires an idempotency key and the original sender.
An authenticated non-sender gets 403 `forbidden`; unknown payment gets 404. Body:

```json
{"expected_revision": 1, "amount": 400,
 "effective_at": "2026-09-20T12:00:00+00:00", "reason": "corrected amount"}
```

All fields are required. Revision is a positive integer; amount is an integer 0..1000000000
(zero reverses the entire payment); reason is a string of 1..200 characters; effective time
is an RFC 3339 instant not later than now. Invalid input is 422 `validation_failed`.
Correction changes neither parties nor visibility. It appends an immutable revision, returning
201 with `payment_id`, `revision`, `amount`, `effective_at`, server-assigned `recorded_at`,
and `reason`. Recorded times for one payment strictly increase. A stale expected revision
gives 409 `stale_revision`. Successful replay returns that original revision with 200 even
after newer revisions. Different body with the same key is 409 `idempotency_key_reuse`.

The difference from the previous amount moves between the **same two wallets** in the same
atomic step. Increasing the amount debits the original sender; decreasing it debits the
original receiver. A currently unaffordable debit gives 409 `insufficient_funds`. Otherwise,
if any user's corrected balance is negative at any effective-time boundary, return
409 `historical_overdraft`. Balances at a boundary include the combined effect of all
movements at that instant. Either failure preserves balances, revision history, statements
and idempotency state. The sum of balances must equal the seeded total in every historical view.

The original payment and every original idempotent response remain unchanged. `GET /activity`
continues to display the original payment; correction records are not new feed payments.
`GET /payments/{payment_id}/revisions` returns `{"revisions": [...]}` in revision order,
including revision 1 (`reason: ""`). Only the two parties can read it; a third party gets
404 even for a public payment. No token is 401.

`GET /me` and `GET /statement` accept optional `known_at`, an RFC 3339 instant with offset.
For each payment, select its latest revision recorded **at or before** `known_at`; if none
was yet recorded, that payment contributes nothing. Omission means everything known when the
read begins. Then apply selected revisions according to their **effective** times. `as_of`
retains its inclusive meaning; a statement retains its half-open window. Both query instants
may be in the future. Invalid/empty instants are 422. Echo supplied `known_at` exactly.

Statement ordering is now by selected `effective_at`, then payment id. Each entry retains
`payment`, `delta` and `balance_after`, and adds the selected `revision`, `effective_at` and
`recorded_at`. `payment.amount` is the selected amount for this statement. Zero-amount
revisions still appear as entries with zero delta. No correction is counted alongside the
revision it replaces. With no corrections and no `known_at`, previous behavior is unchanged.

## Stable statement pagination

Every first `GET /statement` response additionally returns an opaque `snapshot` token.
It freezes the caller's selected revisions, window, balances, entries and default `to` at
that read. `GET /statement?snapshot=<token>&limit=...&offset=...` pages that exact result,
even after payments or corrections. Only limit and offset may accompany a snapshot; supplying
`from`, `to` or `known_at` with it gives 422 `validation_failed`. Unknown token, another user's
token, or a token from before reset gives 404 `not_found`. Tokens last until reset. No storage
survival across container restarts is required. Paging changes neither balances nor entries;
the final partial page and offsets beyond the end must report `has_more` correctly.
Unrecognized query parameters remain ignored under stage 1's general rule.

A correction may move a payment into or out of a statement window. Existing snapshots
remain unchanged during concurrent payments or corrections. Concurrent corrections using
the same expected revision cannot both succeed.

## Settlement history

Stage-1 settlements retain their original receipts and privacy rules. Each member's original
revision uses its shared committed_at as both effective_at and recorded_at.
Single-payment corrections reject settlement members with 422 `linked_payment_immutable`.

A stage-3 service must accept exports produced by the same team's stage-1 or stage-2
service. The ledger must import and account for authorizations and captures. Captures are
immutable linked payments: a correction of a capture gives 422 `linked_payment_immutable`.

## Historical holds

For `GET /me?as_of=T&known_at=K`, all four money fields describe that same view:
`balance = total`, `available = total - held`. A hold starts at authorization creation;
nonfinal capture reduces it at capture time; final capture, void or expiry releases the
remainder at that event's time. Expiry takes effect at `expires_at`. Events other than clock
expiry are known at their
server-assigned event time. Once creation is known, the expiry deadline is known too.
For queries beyond now, an open hold expires at its deadline. Without `as_of`, use the instant
the request began. Authorizations expose `closed_at` (null while open; event time when closed).

Historical `total` follows stage-3 effective/recorded-time rules. A correction is rejected
with 409 `historical_overdraft` if it makes either total or available negative at any past
effective/event boundary, under the latest known revisions. Current unaffordable debits
still take precedence as `insufficient_funds`. Seeded open holds are assumed created at reset
unless `created_at` is supplied; seeded closed holds need not reconstruct a prior lifecycle.
`GET /statement` still contains money movements only: authorization, release and expiry are
not payments. Captures appear exactly once with their links. Old snapshots remain unchanged
after any lifecycle action or correction.

(end of the stage-3 specification; end of part 1 of 13)
