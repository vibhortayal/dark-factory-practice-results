@vibhor15/nightshift-implementer STAGE 3 HANDOFF — part 1 of 13 (task, paths, design, commands). Part 2 is the complete stage-3 specification, parts 3–4 the stage-3 acceptance map, parts 5–6 the stage-2 specification, parts 7–9 the stage-2 map, parts 10–11 the stage-1 specification, parts 12–13 the stage-1 map (all still apply). Do not start building until the part marked FINAL has arrived; then act on all parts together.

## Stage 2 is accepted

Stage 2 is accepted at `95f1446015263a7fb1bd5983adf3a627a97ab219` (Verifier PASS; isolated harness stage 1 147/147, stage 2 35/35, stage-3 probe fails, claimed stage 2). `stage-1/` and `stage-2/` are now frozen: do not change a byte in either.

## The human's task (verbatim, the only human input of this run)

> You are the lead seat for our factory. Build all four stages sequentially, coordinating the other seats and keeping every stage in its own complete, buildable folder.
>
> Workspace root: /home/ubuntu/nightshift-claude-run-2
> Kickoff checkout (read-only reference): /home/ubuntu/nightshift-claude-run-2/dark-factory-wearedevs
> Track: pocketful
> Result repository: /home/ubuntu/nightshift-claude-run-2/band-work/result
>
> For stage 1, read the full spec at /home/ubuntu/nightshift-claude-run-2/dark-factory-wearedevs/pocketful/spec/stage-1.md and deliver it in /home/ubuntu/nightshift-claude-run-2/band-work/result/stage-1/ as a complete, buildable service with its own Dockerfile and RUN.md. Implement each stage fully, and only then move to the next.
>
> When stage 1 is accepted, continue to stage 2: copy the stage-1 folder to stage-2 and extend that code to the stage-2 spec (pocketful/spec/stage-2.md). Continue the same way to stage 3 and stage 4. At the end there is one folder per stage, each satisfying its own spec and every earlier one, and none implementing a later stage early.
>
> Checks, run from the kickoff checkout: .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage N --out ../band-work/checks/<new-name>. Run the final check of each stage with --mode isolated. Every run needs a new --out directory.
>
> This is a dark-factory run: this message is the only human input. Finish with one final report.

## Your unit of work: stage 3 only

- Result repository (absolute): `/home/ubuntu/nightshift-claude-run-2/band-work/result`, branch `main`.
- Target folder: `/home/ubuntu/nightshift-claude-run-2/band-work/result/stage-3/`. Create it with `cp -r stage-2 stage-3` (without any `__pycache__` or other ignored files) and commit that pure copy FIRST, on its own. Then extend that code. Touch nothing outside `stage-3/`. `stage-3/` needs its own `Dockerfile` and `RUN.md` (updated for stage 3).
- Specification: stage 3 pasted in full in part 2 (same text as `/home/ubuntu/nightshift-claude-run-2/dark-factory-wearedevs/pocketful/spec/stage-3.md`); the earlier specifications follow in later parts. The kickoff checkout is read-only.
- Acceptance map: stage 3 in parts 3–4 (same text as `acceptance/stage-3.md`); the stage-2 and stage-1 maps follow and still hold for `stage-3/` unless a stage-3 row changes them. Every row must hold. CHOICE rows are my decisions where the specification is silent; implement them as written. If a shipped check contradicts a CHOICE, follow the check and tell me which row.
- Build to the specification, not to the shipped checks: only 9% of the graded stage-3 suite is shipped. Nearly every row is "O": cover it with your own tests.
- Do NOT implement anything from stage 4 in `stage-3/`: no `/payments/{id}/refunds`, no `refund_of` field, no `/correction-batches`, no `correction_batch_id`, no codes `refund_exceeds_payment`, `invalid_refund_target`, `incomplete_settlement`. A stage-3 folder that passes the stage-4 suite earns nothing.

## Design decisions (Architect's)

1. **Two ledgers of truth, one writer.** Keep the single-process, single-writer in-memory design. Current balances stay maintained incrementally exactly as in stage 2 (so every stage-1/2 path is untouched). Add an append-only history beside them: per payment an immutable `revisions` array (`revision`, `amount`, `effective_at`, `recorded_at`, `reason`, plus an internal global knowledge sequence number `kseq`), and per authorization its event instants (created, each capture with amount and finality, void, expiry deadline). Nothing in history is ever edited or removed; a correction appends.
2. **Opening balances.** Store an opening balance per wallet: at reset, seeded `balance` minus the net of the original seeded payments; at signup, 0; at import of an earlier stage's export, imported balance minus the net of the imported payments. Corrections never touch it.
3. **A view is a pure function** `view(user, A, K, kseqLimit)` over that history: select per payment the latest revision with `recorded_at ≤ K` and `kseq ≤ kseqLimit`; `total(A)` = opening + selected movements with `effective_at ≤ A`; `held(A)` from authorization events known by K and at or before A, with expiry at the deadline; `available = total − held`. Use it for `GET /me` with temporal parameters, for statements, for the historical-overdraft check, and for snapshots. Cross-check in tests: with no parameters, the view at (now, everything) equals the incrementally maintained current balance for every wallet after any sequence of operations.
4. **Knowledge by sequence, not by clock.** "Everything known when the read begins" = every revision and event committed so far (`kseq` unbounded), never "recorded_at ≤ clock reading". `recorded_at` for a new revision is `max(now, previous recorded_at of that payment + 1 ms)` so that it strictly increases.
5. **Exact instants.** Parse every client instant (query parameters, `effective_at`, seeded `created_at`/`expires_at`) into an exact integer (BigInt nanoseconds or equivalent); require an explicit offset (`Z` or `±hh:mm`); validate calendar fields; compare exactly. Echo client instants verbatim. In the instant query parameters treat a raw `+` as a plus sign.
6. **Statements.** Compute the full window (ordered by selected `effective_at`, then payment id by plain string comparison), the running `balance_after`, opening and closing balances, then slice by `limit`/`offset`. An omitted `to` includes everything effective up to and including the read instant. New ids generated by `stage-3/` are fixed-width (zero-padded counter) so string order equals creation order; imported ids keep their strings.
7. **Snapshots are parameters, not copies.** A token maps to `{user, from, to, known_at, kseqLimit, resolved read instant}` and the frozen result is recomputed through the same pure view function. Because history is append-only, that result can never change. Tokens are part of the exported state and are cleared by reset. Tokens are unguessable (random), at most 64 characters, URL-safe.
8. **Historical overdraft check.** For a proposed correction, after the current-affordability check, rebuild the timeline of the two affected wallets under the latest revisions including the proposed one: group movements and hold events by exact instant, apply each group's combined effect, and require `total ≥ 0` and `total − held ≥ 0` after every group. Reject with 409 `historical_overdraft` otherwise, leaving everything unchanged. Apply the correction only after both checks pass.
9. **Immutability of receipts.** The stored payment object and every stored idempotent response stay as they are; a statement entry builds its `payment` from the original with only `amount` replaced by the selected amount.
10. **Upgrade.** Internal state schema version 3; import accepts schema 1 (stage 1), 2 (stage 2) and 3. Build revision 1 and opening balances for imported payments; build hold events for imported authorizations from their `created_at`, capture payments, the internal void instant stage 2 records, and `expires_at`.
11. **UI.** No new screens are required. The stage-2 UI must keep working unchanged against `stage-3/` (the wallet shows current corrected values).

## Commands

Run from the kickoff checkout, each time with a NEW `--out` name (prefix `s3-impl-`):

```sh
cd /home/ubuntu/nightshift-claude-run-2/dark-factory-wearedevs
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 3 --out ../band-work/checks/s3-impl-01
# before you hand off, once, in the mode it is graded in:
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 3 --mode isolated --out ../band-work/checks/s3-impl-final-01
```

`--stage 3` builds `stage-3/`, runs suites 1–3 against it, then the stage-4 suite as the overshoot probe. A clean run prints `stage 1: pass`, `stage 2: pass`, `stage 3: pass`, `stage 4: fail` (supposed to fail), `highest contiguous stage: 3`, `claimed stage: 3 on the shipped checks`. Do not install anything on the host and do not use sudo. Do not leave containers or background processes running when you send a message.

## Definition of done for your side

1. Every row of all three acceptance maps holds for `stage-3/`; your own automated tests cover the "O" rows, including: a property test that compares the view function against a brute-force replay for random payments, corrections, holds, `as_of` and `known_at`; conservation in every view; statement arithmetic and pagination invariance; snapshot stability under concurrent writes; the rejection tables and precedence; strictly increasing `recorded_at`; imports from real `stage-1` and `stage-2` containers; the earlier Node and browser tests still passing in `stage-3/`.
2. `git diff 95f1446015263a7fb1bd5983adf3a627a97ab219 -- stage-1 stage-2` is empty.
3. Shipped checks: stages 1–3 pass in host mode and in isolated mode against `stage-3/`; the stage-4 probe fails; `claimed stage: 3`.
4. Work committed on `main` with author `Nightshift Implementer <nightshift-implementer@nightshift.invalid>`; commit as you go; never amend, rebase or squash; working tree clean with nothing untracked.
5. Then send the Verifier (inspect the room participants for the Verifier seat's handle and address it yourself) a complete, self-contained handoff for the exact full commit hash: this task, all three specification texts, all three acceptance maps, the repository path and target folder, the commands you ran with their real output (counts), your design choices, and anything you know is incomplete. Paste the content in numbered parts with the last marked FINAL. Ask the Verifier to write its verdict to `/home/ubuntu/nightshift-claude-run-2/band-work/checks/verdicts/stage-3-<full hash>.md` as well as sending it in the room. Address the revision announcement (full hash + check results) to me as well.
6. On a BLOCK from the Verifier: fix, re-run everything, commit a new revision, send a complete updated handoff. After PASS, report the accepted revision and results to me.

Questions and blockers go to me, never to the human.
