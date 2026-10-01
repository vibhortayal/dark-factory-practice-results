@vibhor15/nightshift-implementer STAGE 1 HANDOFF — part 1 of 5 (task, paths, commands). Parts 2–3 are the complete specification, parts 4–5 the acceptance map. Do not start building until part 5 (FINAL) has arrived; then act on all five together.

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

## Your unit of work: stage 1 only

- Result repository (absolute): `/home/ubuntu/nightshift-claude-run-2/band-work/result` (branch `main`, current head `26a6807` + the commit that adds these handoff files).
- Target folder: `/home/ubuntu/nightshift-claude-run-2/band-work/result/stage-1/` — source, `Dockerfile`, `RUN.md`, your own tests. Touch nothing outside `stage-1/` (the acceptance map, STATUS.md, mandates and handoffs belong to other seats). No nested `.git`, no symlinks, no submodules.
- Specification: pasted in full in parts 2–3 (same text as `/home/ubuntu/nightshift-claude-run-2/dark-factory-wearedevs/pocketful/spec/stage-1.md`). The kickoff checkout is read-only.
- Acceptance map: pasted in full in parts 4–5 (same text as `acceptance/stage-1.md` in the result repository). Every row must hold. Rows marked CHOICE are decisions I made where the specification is silent; implement them as written. If a shipped check contradicts a CHOICE, follow the check and tell me which row.
- Build to the specification, not to the shipped checks: the shipped checks are 79% of the graded suite and code shaped to the checks disqualifies the run. The acceptance-map rows marked "O" have no shipped check; cover them with your own tests.
- Do NOT implement anything from later stages in `stage-1/`: no browser UI or HTML routes, no payment authorizations/holds/captures, no `total`/`available`/`held` fields, no statements, corrections, revisions, refunds or correction batches. A stage-1 folder that passes the stage-2 suite earns nothing.

## Architecture decision (Architect's, recorded in STATUS.md)

One process; all state in memory; every state transition applied synchronously on a single thread so that each request is serialisable, a balance is never transiently negative, and "exactly one 201" under concurrent identical requests falls out of the design rather than out of locks. Recommended stack: Node.js (current LTS) with TypeScript, compiled in the Docker build, with no or minimal runtime dependencies; password hashing with scrypt from the standard library, run off the main thread (async) so 50 concurrent logins and a reset with a few hundred users stay well inside the 5 s / 10 s limits on 2 vCPU. You may choose another stack if you can give a concrete reason, but the single-writer in-memory ledger is required. Design for extension: stage 2 will copy this folder and add a browser UI and more resources, and later stages add history, so keep the HTTP layer, validation, the ledger/state module, idempotency and export/import as separate modules, and give the export `state` object its own internal schema version field so a later stage can accept this stage's exports unchanged. Raise the HTTP server's maximum header size so a 10 kB `Idempotency-Key` reaches your validation and gets 422 rather than a connection-level error. Parse JSON so that hostile input (deep nesting, `1e400`, invalid UTF-8) yields a 400/422 envelope, never a 5xx or a crash.

## Commands

Run from the kickoff checkout, each time with a NEW `--out` name (existing directories are refused; use the prefix `s1-impl-`):

```sh
cd /home/ubuntu/nightshift-claude-run-2/dark-factory-wearedevs
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/s1-impl-01
# before you hand off, once, in the mode it is graded in:
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --mode isolated --out ../band-work/checks/s1-impl-final-01
```

A clean stage-1 run prints `stage 1: pass`, `stage 2: fail` (the overshoot probe — it is supposed to fail), `highest contiguous stage: 1`, `claimed stage: 1 on the shipped checks`. Per-stage logs are in the `--out` directory. Also follow your own `RUN.md` verbatim once, and run the image once with `docker run --network none` to prove it needs no outbound network. Do not install anything on the host and do not use sudo; build dependencies belong in the Dockerfile. Do not leave containers or background processes running when you send a message.

## Definition of done for your side

1. Every row of the acceptance map holds; your own automated tests (kept in `stage-1/`, runnable with one documented command) cover the "O" rows, including the concurrency rows (F7, G14, H2, J14) and the export/import rows (I1–I12) with a second container.
2. Shipped stage-1 checks all pass in host mode and in isolated mode; the stage-2 probe fails; `claimed stage: 1`.
3. Work committed on `main` with author `Nightshift Implementer <nightshift-implementer@nightshift.invalid>` (`git -c user.name="Nightshift Implementer" -c user.email="nightshift-implementer@nightshift.invalid" commit ...`). Commit as you go; never amend, rebase or squash. Working tree clean (no untracked build output — extend `stage-1/.gitignore`/`.dockerignore` as needed).
4. Then send the Verifier (inspect the room participants for the Verifier seat's handle and address it yourself) a complete, self-contained handoff for the exact full commit hash: this task, the full specification text, the full acceptance map, the repository path and target folder, the commands you ran with their real output (counts), your design choices, and anything you know is incomplete. Paste the content — in numbered parts with the last marked FINAL — do not point at these messages. Address a copy of the revision announcement (full hash + check results) to me as well.
5. On a BLOCK from the Verifier: fix, re-run everything, commit a new revision, send a complete updated handoff. After PASS, report the accepted revision and results to me.

Questions and blockers go to me, never to the human.
