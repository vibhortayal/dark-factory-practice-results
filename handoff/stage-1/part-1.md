@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier
STAGE 1 HANDOFF — part 1 of 5: task, paths, commands, working rules
Rows: all (A1–M1) · Revision: base 71417847b61264fa969a23c01b4d8c3c4f147caf plus the Architect commit that adds ACCEPTANCE-stage-1.md (see `git log`) · Files: ACCEPTANCE-stage-1.md, STATUS.md, handoff/stage-1/ (this text), target stage-1/ (does not exist yet) · Command: n/a · Expected / actual: n/a (nothing built yet) · Repro: n/a · Next: Implementer builds stage-1/; Verifier prepares its check list and scripts (no verdict yet)

Do not act until you hold all 5 parts. Parts 2–3 are the complete specification, parts 4–5 the complete acceptance map.

== THE HUMAN'S TASK (verbatim; it is the only human input of this run) ==
"You are the lead seat for our factory. Build stage 1 only, coordinating the other seats.

Workspace root: /home/ubuntu/nightshift-claude-check-tk1
Kickoff checkout (read-only reference): /home/ubuntu/nightshift-claude-check-tk1/dark-factory-wearedevs
Track: tablekeeper
Result repository: /home/ubuntu/nightshift-claude-check-tk1/band-work/result

Read the full spec at /home/ubuntu/nightshift-claude-check-tk1/dark-factory-wearedevs/tablekeeper/spec/stage-1.md and deliver it in /home/ubuntu/nightshift-claude-check-tk1/band-work/result/stage-1/ as a complete, buildable service with its own Dockerfile and RUN.md. Do not implement later stages.

Checks, run from the kickoff checkout: .venv/bin/python -m harness run --track tablekeeper --repo ../band-work/result --stage 1 --out ../band-work/checks/<new-name>. Run the final check with --mode isolated. Every run needs a new --out directory.

This is a dark-factory run: this message is the only input you will get. Finish with one final report."

== PATHS ==
- Result repository (git, branch main): /home/ubuntu/nightshift-claude-check-tk1/band-work/result
- Target folder (the only place implementation code goes): /home/ubuntu/nightshift-claude-check-tk1/band-work/result/stage-1/
- Kickoff checkout, READ-ONLY: /home/ubuntu/nightshift-claude-check-tk1/dark-factory-wearedevs (spec: tablekeeper/spec/stage-1.md; supplied partial checks: tablekeeper/test/stage_1/)
- Check output: /home/ubuntu/nightshift-claude-check-tk1/band-work/checks/<new-name> (outside the repository; a new directory per run)
- Acceptance map in the repository: ACCEPTANCE-stage-1.md. This handoff text: handoff/stage-1/part-1.md … part-5.md (identical to these messages).

== COMMANDS ==
Supplied checks, host mode (while iterating), run from the kickoff checkout:
  cd /home/ubuntu/nightshift-claude-check-tk1/dark-factory-wearedevs
  .venv/bin/python -m harness run --track tablekeeper --repo ../band-work/result --stage 1 --out ../band-work/checks/<new-name>
Final check of a revision, isolated mode (internal network, no outbound access):
  .venv/bin/python -m harness run --track tablekeeper --repo ../band-work/result --stage 1 --mode isolated --out ../band-work/checks/<new-name>
Every run needs a NEW --out directory (an existing one is refused). Name them by seat, e.g. impl-01, impl-final-01, ver-01. The run must print `claimed stage: 1`; the harness also probes the stage-2 suite, which must NOT fully pass.
Manual run under the §2 limits:
  docker build -t tk-stage1 /home/ubuntu/nightshift-claude-check-tk1/band-work/result/stage-1
  docker run -d --rm --name <unique-name> --cpus 2 --memory 2g -e PORT=8080 -p <free-host-port>:8080 tk-stage1
Use a container name and host port of your own (Implementer and Verifier may run at the same time on this machine); stop your containers with `docker stop` before you send a message. No sudo, no host package installs, no push.

== WHAT TO BUILD ==
Stage 1 of Tablekeeper only: the JSON HTTP API in parts 2–3, delivered in stage-1/ with its own Dockerfile and RUN.md (build + start command with no manual setup, and where each module lives). Language, framework and storage are the Implementer's choice within the spec; record the choice and reason. No UI, no stage-2/3/4 features, and do not read the later stage specs to pre-build them. The supplied checks are a partial sample: the specification and the acceptance map are the measure.

== WORKING RULES FOR THIS UNIT ==
- Implementer: build, write your own tests from the spec, self-check every map row (including the 50-in-flight rows under --cpus 2 --memory 2g), commit as "Nightshift Implementer", then send the Verifier a complete self-contained handoff for the exact full revision and tell the Architect the revision.
- Verifier: this message, arriving before any revision exists, is your request to PREPARE: derive your check list and scripts from the spec now; no verdict and no reply until a revision is handed to you. Then exactly one verdict (PASS / BLOCK / INCONCLUSIVE) for the exact full revision, to the Implementer and the Architect, saved under verification/stage-1/.
- At most five BLOCK rounds for this unit. The Architect accepts only on a Verifier PASS for the exact revision that last changed stage-1/.
- "Architect decisions" X1–X10 at the end of part 5 resolve points the spec leaves open. Rows marked (choice) are guidance for the Implementer and not, by themselves, grounds for a blocking finding; if either of you finds a decision contradicts the specification, tell the Architect with the clause.
