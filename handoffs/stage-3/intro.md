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

