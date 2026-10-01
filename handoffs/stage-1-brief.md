HANDOFF — Pocketful stage 1 — build `stage-1/`

Rows: all rows of the stage-1 acceptance map (D1-D8, R1-R10, M1-M15, I1-I5, E1-E13, A1-A11, K1-K11, P1-P29, S1-S4, X1-X11, N1-N13) · Revision: base is the head of `main` in the result repository at the time you start (contains `acceptance/stage-1.md`, `STATUS.md`, `handoffs/`) · Files: create `stage-1/` only · Command: see "Commands" below · Expected / actual: `stage-1/` does not exist yet / must exist as a complete buildable service meeting the whole stage-1 specification · Repro: n/a · Next: Implementer builds, then hands off to the Verifier.

This handoff comes in numbered parts. Parts carry, in order: (a) this brief, (b) the complete stage-1 specification text, verbatim, (c) the complete acceptance map, verbatim. The last part is marked FINAL. Do not start until you hold every part. The same text is also on disk (same machine) at the absolute paths given below; the pasted text and the files are identical.

## The human's complete task (verbatim, the only human input of this run)

> You are the lead seat for our factory. Build all four stages sequentially, coordinating the other seats and keeping every stage in its own complete, buildable folder.
>
> Workspace root: /home/ubuntu/nightshift-claude-run-3
> Kickoff checkout (read-only reference): /home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs
> Track: pocketful
> Result repository: /home/ubuntu/nightshift-claude-run-3/band-work/result
>
> For stage 1, read the full spec at /home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs/pocketful/spec/stage-1.md and deliver it in /home/ubuntu/nightshift-claude-run-3/band-work/result/stage-1/ as a complete, buildable service with its own Dockerfile and RUN.md. Implement each stage fully, and only then move to the next.
>
> When stage 1 is accepted, continue to stage 2: copy the stage-1 folder to stage-2 and extend that code to the stage-2 spec (pocketful/spec/stage-2.md). Continue the same way to stage 3 and stage 4. At the end there is one folder per stage, each satisfying its own spec and every earlier one, and none implementing a later stage early.
>
> Checks, run from the kickoff checkout: .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage N --out ../band-work/checks/<new-name>. Run the final check of each stage with --mode isolated. Every run needs a new --out directory.
>
> This is a dark-factory run: this message is the only human input. Finish with one final report.

## This unit

- Unit: stage 1 only. Stages 2-4 are not started and must not be implemented early.
- Result repository (absolute): /home/ubuntu/nightshift-claude-run-3/band-work/result (branch `main`; do not push, do not rewrite history).
- Target folder (absolute): /home/ubuntu/nightshift-claude-run-3/band-work/result/stage-1/
- Specification on disk (read-only): /home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs/pocketful/spec/stage-1.md
- Acceptance map on disk: /home/ubuntu/nightshift-claude-run-3/band-work/result/acceptance/stage-1.md
- Supplied checks (a partial sample, read-only): /home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs/pocketful/test/ (conftest.py, fixtures.py, stage_1/). Do not read or use stage-2+ specs or tests to shape stage 1.
- The kickoff checkout is read-only. Write nothing into it. Check output goes to /home/ubuntu/nightshift-claude-run-3/band-work/checks/<new-name> (outside the result repository).

## What to deliver in `stage-1/`

1. The HTTP service source, implementing the whole stage-1 specification: every requirement, rule, rejection case and boundary, not only what the supplied checks ask.
2. A `Dockerfile` that builds the image with all runtime dependencies inside it (outbound network exists only during `docker build`; none at run time). The image must run alone with `docker run -e PORT=<port> -p <port>:<port> <image>` and default to port 8080.
3. A `RUN.md` with the exact command that builds and starts the service with no manual setup.
4. Your own tests written from the specification (inside `stage-1/`), covering the acceptance map including concurrency rows.
5. No nested `.git` directory inside `stage-1/`. No stage-2+ behaviour: no UI screens, no authorization/capture endpoints, no statements, no refunds or corrections. The harness also runs the next stage's suite against the folder; a folder that passes the whole stage-2 suite claims nothing.

Language, framework and storage are your choice. Pick what makes the invariants easy to guarantee under 50 concurrent requests: exact integer arithmetic (balances up to ±2^53, no floats), one atomic critical section or transaction per money movement, and exact control of JSON number parsing (`1000`, `1000.0` and `1e3` are valid amounts; `10.5`, `"10"`, `true` are not) and of byte-for-byte note round-trips.

## Commands

Build and run by hand:

    cd /home/ubuntu/nightshift-claude-run-3/band-work/result/stage-1
    docker build -t pocketful-stage-1 .
    docker run -d --rm --name pocketful-s1 --cpus 2 --memory 2g -e PORT=8080 -p 8080:8080 pocketful-stage-1
    curl -s localhost:8080/health
    docker stop pocketful-s1

Supplied checks, run from the kickoff checkout, each run with a NEW `--out` directory (an existing one is refused):

    cd /home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs
    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/s1-impl-01

Final check of the stage, isolated mode (internal network, no outbound), again a new `--out`:

    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --mode isolated --out ../band-work/checks/s1-impl-final-01

The result you want is `claimed stage: 1`. Do not run long-lived commands as background tasks: start containers detached and stop them with an ordinary command.

## Process

- Commit as `git -c user.name="Nightshift Implementer" -c user.email="nightshift-implementer@nightshift.invalid" commit ...`. Never amend, rebase or squash after reporting a revision.
- Before handing off: go through every acceptance-map row, record how you checked it and the result (put the row-by-row self-check in `stage-1/SELFCHECK.md` and in your handoff), and fix what fails first. The working tree must be clean at the revision you report.
- Then hand off to the Verifier with a self-contained message: evidence header, row-by-row self-check, this complete task, the complete specification, the acceptance map, the repository path, the full commit hash, the commands you ran with their real output, your design choices, and anything incomplete. Paste the requirements; numbered parts are fine.
- Report the committed revision to the Architect as well. Questions and blockers go to the Architect, never to the human.

## Architect decisions where the specification needs a reading (also at the end of the acceptance map)

- Q1 Check order on the five idempotent writes: authentication (401) → `Idempotency-Key` presence (400 `missing_idempotency_key`) and length (422 if over 255) → body parses as a JSON object (400 `malformed_request`) → claimed-key resolution (200 replay / 409 `idempotency_key_reuse`) → permission (403, e.g. non-operator on settlements, non-payer on pay) and field validation → resource checks → funds. Only successful (201) responses claim a key.
- Q2 Inside an endpoint: wrong JSON type (400) and field rules (422) before handle lookup (404) before self-payment/self-request (422) before funds (409). For settlements, apply this per entry in input order; the first failing entry decides; entry errors come before insufficient funds.
- Q3 `amount: null` or a missing `amount` is 422 `validation_failed`.
- Q4 Paying a share-0 request succeeds (201) and creates a payment of amount 0.
- Q5 Seeded payments and requests carry no timestamp in the fixture: assign `created_at` at reset, treating fixture order as oldest-first.
- Q6 Decline/cancel/pay by the wrong party is 403 even when the request is no longer pending (permission before state).
- Every payment object in every response carries `settlement_id` (null for non-members), per §11.

If the specification text contradicts any of these readings, the specification wins: tell the Architect which clause.
