@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier Rows: stage-4 map GG1..JJ3, stage-3 map AA1..ZZ3, stage-2 map M1..V7 with Q11, stage-1 map A1..K10 · Revision: e57b830ffcc4e8716660c93348a830a927836079 (maps and status; accepted: stage-1/ 77409dda43334b784ca1125d2d990ba51478abf6, stage-2/ 88b9223d3e56cd9a668499f3cd5b87575d0ea114, stage-3/ aedbe2c666e7b1b97661ad869d77f002bb103eca; stage-4/ does not exist yet) · Files: acceptance/stage-4.md, stage-3.md, stage-2.md, stage-1.md, STATUS.md · Command: n/a · Expected / actual: stage-4/ to be built / not yet built · Repro: n/a · Next: Implementer builds stage-4/ and reports a committed revision; Verifier prepares its checks now and waits for that revision.

STAGE 4 HANDOFF, in 15 numbered parts. Part 15 is the final part. Do not act until you hold all fifteen.

Stage 1 is accepted at 77409dda43334b784ca1125d2d990ba51478abf6, stage 2 at 88b9223d3e56cd9a668499f3cd5b87575d0ea114 and stage 3 at aedbe2c666e7b1b97661ad869d77f002bb103eca (all Verifier PASS). This handoff starts stage 4, the last unit.

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

- Unit: stage 4.
- Result repository (absolute): /home/ubuntu/nightshift-claude-run-6/band-work/result
- Target folder: /home/ubuntu/nightshift-claude-run-6/band-work/result/stage-4/, created by copying /home/ubuntu/nightshift-claude-run-6/band-work/result/stage-3/ as it is at revision aedbe2c666e7b1b97661ad869d77f002bb103eca and extending the copy. stage-1/, stage-2/ and stage-3/ must not change.
- Read-only reference checkout: /home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs (specifications at pocketful/spec/stage-4.md, stage-3.md, stage-2.md, stage-1.md).
- Contents of this handoff: part 1 = the complete stage-4 specification; part 2 = the complete stage-3 specification; parts 3 and 4 = the complete stage-2 specification; parts 5 to 7 = the complete stage-1 specification; part 8 = the complete stage-4 acceptance map (acceptance/stage-4.md); parts 9 and 10 = the complete stage-3 map; parts 11 to 13 = the complete stage-2 map; parts 14 and 15 = the complete stage-1 map; part 15 ends with what each seat does.
- The supplied checks cover about a sixth of the stage-4 specification. The specifications and the acceptance maps are the contract; build and verify to them, never to the checks.
- No human is available. Do not ask the human anything. Questions about the reading of the specification go to the Architect in this room.

## Commands (run from /home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs)

    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 4 --out ../band-work/checks/<new-name>
    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 4 --mode isolated --out ../band-work/checks/<new-name>
    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --all --mode isolated --out ../band-work/checks/<new-name>

Every run needs a new --out directory (s4-impl-NN for the Implementer, s4-ver-NN for the Verifier). `--stage 4` builds stage-4/ and runs suites 1 to 4 against it with the earlier stage folders as upgrade sources; there is no overshoot probe above stage 4. A correct run prints `stage 1: pass` to `stage 4: pass` and ends `claimed stage: 4 on the shipped checks`. `--all` builds every folder and prints one line per folder; each must claim its own stage. The final check of the stage is run with --mode isolated.

## SPECIFICATION, stage 4, complete text

# Pocketful — Stage 4: refunds and batch corrections

Recipients can refund payments. Settlement operators can correct several payments in
one request, including payments that belong to a settlement. Existing receipts and saved
statements must remain available in their original form.

All requirements from stages 1–3 continue to apply. There are ten idempotent write paths:
stage 1's five, authorizations and captures from stage 2, corrections from stage 3, and refunds and
correction batches in this stage.

## Refunds and corrected history

`POST /payments/{payment_id}/refunds`, body `{"amount": 200}`, requires an idempotency key.
Only the original receiver may refund, else 403 `forbidden`; unknown payment is 404. The
target may be a direct payment, request payment or capture, but never a refund. Invalid amount
is 422 `validation_failed`. Refunds cumulatively may not exceed the payment's current corrected
amount: 422 `refund_exceeds_payment`. Refunds of refunds give 422 `invalid_refund_target`.

A refund is a new payment in the opposite direction, with `refund_of` naming the target,
`request_id: null`, `authorization_id: null`, and the original note/visibility. Return 201
with that payment; replay returns 200 with the original body. It moves existing money from
the receiver's **available** funds, or fails 409 `insufficient_funds`, atomically. Refunds
never reopen a request or authorization or restore a released hold. Other payments have
`refund_of: null`.

Stage-3 corrections remain available for ordinary direct/request payments. Captures and
refund payments cannot themselves be corrected: 422 `linked_payment_immutable`. A correction
cannot reduce a payment below its already-refunded amount: 422 `refund_exceeds_payment`.
Correction debits are checked against available funds.

## Batch corrections

`POST /correction-batches` requires a settlement operator and an idempotency key, with the
same 401/403 rules as settlements. Body:

```json
{"corrections": [{"payment_id": "p_a", "expected_revision": 1, "amount": 0,
                  "effective_at": "2026-09-20T12:00:00+00:00", "reason": "reversal"},
                 {"payment_id": "p_b", "expected_revision": 1, "amount": 0,
                  "effective_at": "2026-09-20T12:00:00+00:00", "reason": "reversal"}]}
```

corrections contains 1..32 objects with distinct payment_ids, else 422 `validation_failed`.
Every item has the ordinary correction fields and validation. Unknown payment is 404;
a stale expected revision is 409 `stale_revision`. The operator may correct ordinary,
request and settlement payments, but captures and refunds remain immutable. Correcting any
settlement member requires including every member of that settlement, else 422
`incomplete_settlement`. Members of one settlement must have identical effective instants
(offset spellings may differ), else 422 `validation_failed`. Ordinary single-payment
corrections remain available for nonmembers. Unknown fields are ignored.

Error precedence is: item errors in input order, settlement completeness, resulting
current available funds, then historical total and available funds at every effective/event
boundary. The existing codes apply: `linked_payment_immutable`, `refund_exceeds_payment`,
`insufficient_funds`, `historical_overdraft`. Affordability is determined by the combined
effect of all proposed revisions. A rejected batch leaves history, balances and idempotency
records unchanged.

Return 201 with `correction_batch_id`, `recorded_at` and `revisions` in input order. All new
revisions share recorded_at, strictly later than the previous recorded_at of every member;
each revision also exposes correction_batch_id. Effective times cannot be later than now.
Original payments and receipts never change. Original payment and settlement retries return
their original bodies. New statements reflect the new revisions; earlier snapshot tokens
continue to page their frozen entries. Replays return the original batch response with 200.
This adds one idempotent write path.

A settlement payment may be refunded under the existing refund rules, but refunds never
change settlement membership. Concurrent corrections sharing any expected payment revision
cannot
both succeed. A stage-4 service must accept exports produced by the same team's stages 1–3,
retaining settlement membership, corrections and snapshots.

(end of the stage-4 specification; end of part 1 of 15)
