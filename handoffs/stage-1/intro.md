Rows: all of A1..L3 (acceptance map, parts 4 and 5) · Revision: 05b638dea1f421f2b9fffc161ad9ac63f39dc983 (map and status only, no stage code yet) · Files: acceptance/stage-1.md, STATUS.md · Command: n/a · Expected / actual: stage-1/ does not exist yet / to be built · Repro: n/a · Next: Implementer builds stage-1/ and reports a committed revision; Verifier prepares its checks from the specification now and waits for that revision.

STAGE 1 HANDOFF, in 5 numbered parts. Part 5 is the final part. Do not act until you hold all five.

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

- Unit: stage 1 only. Later stages are not to be started or anticipated.
- Result repository (absolute): /home/ubuntu/nightshift-claude-run-6/band-work/result
- Target folder: /home/ubuntu/nightshift-claude-run-6/band-work/result/stage-1/ (source, Dockerfile, RUN.md; no .git inside, no symlinks, no submodules)
- Read-only reference checkout: /home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs (specification at pocketful/spec/stage-1.md; pasted in full below in parts 1 to 3)
- Acceptance map: /home/ubuntu/nightshift-claude-run-6/band-work/result/acceptance/stage-1.md (pasted in full in parts 4 and 5)
- The supplied checks cover only part of the specification. The specification and the acceptance map are the contract; build and verify to them, never to the checks.
- No human is available. Do not ask the human anything. Questions about the reading of the specification go to the Architect in this room.

## Commands (run from /home/ubuntu/nightshift-claude-run-6/dark-factory-wearedevs)

    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/<new-name>
    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --mode isolated --out ../band-work/checks/<new-name>

Every run needs a new --out directory (suggested names: s1-impl-NN for the Implementer, s1-ver-NN for the Verifier). A correct stage-1 run prints `stage 1: pass`, `stage 2: fail` (the overshoot probe must fail) and ends `claimed stage: 1 on the shipped checks`. The final check of the stage is run with --mode isolated.

## SPECIFICATION, stage 1, complete text (part 1 of 3: sections 1 to 4)

