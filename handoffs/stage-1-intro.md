Rows: all of acceptance/stage-1.md (A01 to I10) · Revision: 02d6b04 base plus the Architect's map commit at HEAD (no stage code yet) · Files: stage-1/ (to be created), acceptance/stage-1.md, STATUS.md · Command: n/a · Expected / actual: stage-1/ does not exist yet / must become a complete service meeting every map row · Repro: n/a · Next: Implementer builds; Verifier prepares its checks from the specification and gives no verdict until a committed revision is handed over.

STAGE 1 HANDOFF. This handoff has {N} numbered parts; it is complete only when you have the part marked FINAL. Parts 1 to 4 carry the task and the complete specification verbatim; the remaining parts carry the acceptance map verbatim.

== The human's task, verbatim ==
"You are the lead seat for our factory. Build stage 1 only, coordinating the other seats.

Workspace root: /home/ubuntu/nightshift-claude-check-s1f
Kickoff checkout (read-only reference): /home/ubuntu/nightshift-claude-check-s1f/dark-factory-wearedevs
Track: pocketful
Result repository: /home/ubuntu/nightshift-claude-check-s1f/band-work/result

Read the full spec at /home/ubuntu/nightshift-claude-check-s1f/dark-factory-wearedevs/pocketful/spec/stage-1.md and deliver it in /home/ubuntu/nightshift-claude-check-s1f/band-work/result/stage-1/ as a complete, buildable service with its own Dockerfile and RUN.md. Do not implement later stages.

Checks, run from the kickoff checkout: .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/<new-name>. Run the final check with --mode isolated. Every run needs a new --out directory.

This is a dark-factory run: this message is the only input you will get. Finish with one final report."

== Paths ==
- Result repository (shared, one git repo, branch main): /home/ubuntu/nightshift-claude-check-s1f/band-work/result
- Target folder: /home/ubuntu/nightshift-claude-check-s1f/band-work/result/stage-1/ (complete service, Dockerfile, RUN.md, your tests; no nested .git; nothing outside this folder except that the Architect owns STATUS.md, acceptance/ and handoffs/)
- Kickoff checkout, read-only: /home/ubuntu/nightshift-claude-check-s1f/dark-factory-wearedevs (spec: pocketful/spec/stage-1.md; supplied sample tests: pocketful/test/stage_1/, pocketful/test/conftest.py, pocketful/test/fixtures.py)
- Acceptance map file: /home/ubuntu/nightshift-claude-check-s1f/band-work/result/acceptance/stage-1.md (same text as pasted below)
- Check output directories: /home/ubuntu/nightshift-claude-check-s1f/band-work/checks/<new-name> (must not exist before the run)

== Commands ==
Supplied checks, run from /home/ubuntu/nightshift-claude-check-s1f/dark-factory-wearedevs :
  .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/<new-name>
Final check of a revision adds: --mode isolated (internal network, no outbound access; this is the graded mode). Suggested names: Implementer s1-impl-01, s1-impl-02, ...; Verifier s1-ver-01, ...
Manual run under the stated limits:
  docker build -t pocketful-s1 /home/ubuntu/nightshift-claude-check-s1f/band-work/result/stage-1
  docker run -d --rm --name pocketful-s1 --cpus 2 --memory 2g -e PORT=8080 -p 18080:8080 pocketful-s1
  docker stop pocketful-s1
The harness builds from the repository working tree, so commit before the run you report and report the full commit hash.

== Rules for this unit ==
- Implement the whole specification and every acceptance-map row, not only what the supplied checks ask; the supplied checks are a sample of the graded suite.
- Stage 1 only: HTTP API only, no UI and nothing from later stages. Do not read later-stage specs to build ahead.
- Language, framework and storage are the Implementer's choice. Architect's recommendation (not a requirement): a single process holding all state in memory, every state transition (money movement, request status change, idempotency claim, reset, import, export snapshot) serialised under one lock or one event loop so that invariants B01 to B03, E08 and H01 hold by construction; password hashing done outside that critical section so it cannot stall other requests; ids generated so they cannot collide with fixture or imported ids.
- Where the specification is silent, follow the "Choices" at the end of the acceptance map; if you find specification text that contradicts a choice, tell the Architect with the quote instead of silently diverging.
- Implementer: commit as "Nightshift Implementer" <nightshift-implementer@nightshift.invalid>, then hand the exact full revision to the Verifier with your row-by-row self-check, and report to the Architect. Verifier: verdict (PASS, BLOCK or INCONCLUSIVE) for the exact full revision at HEAD, to the Implementer and the Architect. A unit gets at most five BLOCK rounds.

== Specification: pocketful/spec/stage-1.md, verbatim, starts here and continues in the next parts ==
