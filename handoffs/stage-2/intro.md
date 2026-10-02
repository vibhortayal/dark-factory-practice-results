STAGE 2 HANDOFF, in 10 numbered parts. Part 10 is the final part. Do not act until you hold all ten.

Stage 1 is accepted at revision 77409dda43334b784ca1125d2d990ba51478abf6 (Verifier PASS after one fix round). This handoff starts stage 2.

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

- Unit: stage 2 only. Stage 3 and stage 4 are not to be started or anticipated.
- Result repository (absolute): /home/ubuntu/nightshift-claude-run-6/band-work/result
- Target folder: /home/ubuntu/nightshift-claude-run-6/band-work/result/stage-2/, created by copying /home/ubuntu/nightshift-claude-run-6/band-work/result/stage-1/ as it is at revision 77409dda43334b784ca1125d2d990ba51478abf6 and extending the copy. stage-1/ itself must not change.
- Read-only reference checkout: /home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs (specifications at pocketful/spec/stage-2.md and pocketful/spec/stage-1.md).
- Contents of this handoff: parts 1 and 2 = the complete stage-2 specification; parts 3 to 5 = the complete stage-1 specification, which stage 2 incorporates; parts 6 to 8 = the complete stage-2 acceptance map (acceptance/stage-2.md); parts 9 and 10 = the complete stage-1 acceptance map as it stands (acceptance/stage-1.md, with C1 clarified and rows A12, A13), which continues to apply; part 10 ends with what each seat does.
- The supplied checks cover roughly a third of the stage-2 specification. The specifications and the acceptance maps are the contract; build and verify to them, never to the checks.
- No human is available. Do not ask the human anything. Questions about the reading of the specification go to the Architect in this room.

## Commands (run from /home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs)

    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 2 --out ../band-work/checks/<new-name>
    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 2 --mode isolated --out ../band-work/checks/<new-name>

Every run needs a new --out directory (s2-impl-NN for the Implementer, s2-ver-NN for the Verifier). `--stage 2` builds stage-2/, runs suites 1 and 2 against it, uses stage-1/ as the upgrade source, and runs suite 3 as the overshoot probe. A correct run prints `stage 1: pass`, `stage 2: pass`, `stage 3: fail` and ends `claimed stage: 2 on the shipped checks`. The browser checks use Playwright with Chromium from the kickoff checkout's .venv. The final check of the stage is run with --mode isolated.

## SPECIFICATION, stage 2, complete text (part 1 of 2: from the start up to "Existing clients after an upgrade")

