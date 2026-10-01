@vibhor15/nightshift-implementer STAGE 4 HANDOFF — part 1 of 15 (task, paths, design, commands). Parts 2–15 carry, in this order and each verbatim: the stage-4 specification, the stage-4 acceptance map, then specification and map of stage 3, of stage 2 and of stage 1 (all still apply); each part names what it holds. Do not start building until the part marked FINAL has arrived; then act on all parts together.

## Stage 3 is accepted

Stage 3 is accepted at `e1c0b553e15978b78259c734bf9c1dcf7fdad931` (Verifier PASS; isolated harness: stages 1–3 pass, stage-4 probe fails, claimed stage 3). `stage-1/`, `stage-2/` and `stage-3/` are now frozen: do not change a byte in any of them.

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

## Your unit of work: stage 4 only (the last stage)

- Result repository (absolute): `/home/ubuntu/nightshift-claude-run-2/band-work/result`, branch `main`.
- Target folder: `/home/ubuntu/nightshift-claude-run-2/band-work/result/stage-4/`. Create it with `cp -r stage-3 stage-4` (no ignored or untracked files) and commit that pure copy FIRST, on its own. Then extend that code. Touch nothing outside `stage-4/`. `stage-4/` needs its own `Dockerfile` and `RUN.md` (updated for stage 4).
- Specification: stage 4 pasted in full right after this part (same text as `/home/ubuntu/nightshift-claude-run-2/dark-factory-wearedevs/pocketful/spec/stage-4.md`); the earlier specifications follow in later parts. The kickoff checkout is read-only.
- Acceptance map: stage 4 in the part(s) after the specification (same text as `acceptance/stage-4.md`); the maps of stages 3, 2 and 1 follow and still hold for `stage-4/` unless a stage-4 row changes them. Every row must hold. CHOICE rows are my decisions where the specification is silent; implement them as written. If a shipped check contradicts a CHOICE, follow the check and tell me which row.
- Build to the specification, not to the shipped checks: only 16% of the graded stage-4 suite is shipped. Nearly every row is "O": cover it with your own tests.
- There is no later stage. `--stage 4` has no overshoot probe; a clean run prints `stage 1: pass` … `stage 4: pass`, `highest contiguous stage: 4`, `claimed stage: 4 on the shipped checks`.

## Design decisions (Architect's)

1. **Refunds are ordinary payments with a link.** A refund is created through the same ledger step as a payment (debit the original receiver's available funds, credit the original sender), gets its own id, `created_at`, revision 1 and hold-free history entry, and carries `refund_of`. Every payment object gains `refund_of` (null unless a refund); stored original idempotent responses are replayed exactly as stored. Keep a running refunded total per target payment; it bounds later refunds and later corrections of that payment against the payment's latest revision amount.
2. **Immutable kinds.** One predicate decides correctability: captures (`authorization_id` set) and refunds (`refund_of` set) are never correctable; settlement members are correctable only through a batch; everything else through either path.
3. **A batch is one atomic append.** Validate the whole batch against a staged copy of the affected history (never mutate before every check has passed): shape → items in input order → settlement completeness and member-instant equality → combined current available funds for every affected wallet → historical total and available at every boundary for every affected wallet with ALL proposed revisions applied together. Then append all revisions in one synchronous step with one shared `recorded_at` = max(now, 1 ms after the latest previous `recorded_at` among the members) and one knowledge sequence position, so no read can ever see half a batch.
4. **Reuse the stage-3 view and overdraft check**; generalise the single-payment correction to "apply a set of proposed revisions", with the single endpoint as the one-element case (plus its own sender-only and non-member rules). Do not fork the logic.
5. **Revisions gain `correction_batch_id`** (null for revision 1 and single corrections). Statement entries and snapshots are unaffected in shape; snapshots created before a batch still page their frozen entries because history is append-only and they carry a knowledge limit.
6. **Upgrade.** Internal state schema version 4; import accepts schemas 1–4, keeping settlement membership, revisions, recorded times and snapshot tokens of a stage-3 export; payments from earlier exports get `refund_of: null`, revisions get `correction_batch_id: null`.
7. **UI.** No new screens are required. The stage-2 UI must keep working unchanged against `stage-4/`; a refund shows up in the feed as an ordinary payment.

## Commands

Run from the kickoff checkout, each time with a NEW `--out` name (prefix `s4-impl-`):

```sh
cd /home/ubuntu/nightshift-claude-run-2/dark-factory-wearedevs
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 4 --out ../band-work/checks/s4-impl-01
# before you hand off, once, in the mode it is graded in:
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 4 --mode isolated --out ../band-work/checks/s4-impl-final-01
```

Do not install anything on the host and do not use sudo. Do not leave containers or background processes running when you send a message.

## Definition of done for your side

1. Every row of all four acceptance maps holds for `stage-4/`; your own automated tests cover the "O" rows, including: the refund and batch rejection tables and precedence; cumulative refund limits against corrected amounts; combined-effect affordability; incomplete settlements; shared and strictly later `recorded_at`; rejected batches changing nothing (state export identical before and after); concurrency (BB11, BD14); snapshots taken before refunds/batches staying frozen; imports from real `stage-1`, `stage-2` and `stage-3` containers; all earlier Node and browser tests still passing in `stage-4/`.
2. `git diff e1c0b553e15978b78259c734bf9c1dcf7fdad931 -- stage-1 stage-2 stage-3` is empty.
3. Shipped checks: stages 1–4 pass in host mode and in isolated mode against `stage-4/`; `claimed stage: 4`.
4. Work committed on `main` with author `Nightshift Implementer <nightshift-implementer@nightshift.invalid>`; commit as you go; never amend, rebase or squash; working tree clean with nothing untracked.
5. Then send the Verifier (inspect the room participants for the Verifier seat's handle and address it yourself) a complete, self-contained handoff for the exact full commit hash: this task, all four specification texts, all four acceptance maps, the repository path and target folder, the commands you ran with their real output (counts), your design choices, and anything you know is incomplete. Paste the content in numbered parts with the last marked FINAL. Ask the Verifier to write its verdict to `/home/ubuntu/nightshift-claude-run-2/band-work/checks/verdicts/stage-4-<full hash>.md` as well as sending it in the room. Address the revision announcement (full hash + check results) to me as well.
6. On a BLOCK from the Verifier: fix, re-run everything, commit a new revision, send a complete updated handoff. After PASS, report the accepted revision and results to me.

Questions and blockers go to me, never to the human.
