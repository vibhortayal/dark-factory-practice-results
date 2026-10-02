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

