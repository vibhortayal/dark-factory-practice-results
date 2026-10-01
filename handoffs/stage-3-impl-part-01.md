@vibhor15/nightshift-implementer
Rows: all stage-3 rows + stage-1/2 regression · Revision: stage-2 accepted at f8086da438d3fa7dd38c886decd4ed4a2b8c9dd8; base = head of main · Files: stage-3/ (to create) · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer
STAGE-3 HANDOFF PART 1/12 — BRIEF

HANDOFF — Pocketful stage 3 — build `stage-3/` from the accepted `stage-2/`

Rows: all rows of the stage-3 acceptance map (B3, PT, ME, ST, CO, KA, SN, HH, UP, decisions S3-1..S3-11) plus every stage-1 and stage-2 row as regression (B3.1) · Revision: stage 2 is ACCEPTED at f8086da438d3fa7dd38c886decd4ed4a2b8c9dd8 (Verifier PASS; supplied checks 147/147 and 35/35, claimed stage 2 isolated); stage 1 accepted at 8e4365295e6a47665793e0b2d7d9f6be6e7ff1eb; base your work on the current head of `main` · Files: create `stage-3/` only; `stage-1/` and `stage-2/` must stay byte-identical · Command: see "Commands" · Expected / actual: `stage-3/` does not exist yet / must be a complete buildable service meeting the stage-3, stage-2 and stage-1 specifications · Repro: n/a · Next: Implementer builds, then hands off to the Verifier.

This handoff comes in numbered parts, in order: (a) this brief, (b) the complete stage-3 specification, verbatim, (c) the complete stage-3 acceptance map, verbatim, (d) the complete stage-2 specification, (e) the complete stage-2 acceptance map, (f) the complete stage-1 specification, (g) the complete stage-1 acceptance map. The last part is marked FINAL. Do not start until you hold every part. The same text is on disk at the paths below.

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

- Unit: stage 3 only. Stages 1 and 2 are accepted and frozen. Stage 4 is not started and must not be implemented early.
- Result repository (absolute): /home/ubuntu/nightshift-claude-run-3/band-work/result (branch `main`; no push, no history rewrite).
- Source folder to copy: /home/ubuntu/nightshift-claude-run-3/band-work/result/stage-2/ at revision f8086da438d3fa7dd38c886decd4ed4a2b8c9dd8. Copy it to `stage-3/` (without `__pycache__`), then extend the copy. `git diff f8086da -- stage-1 stage-2` must stay empty.
- Target folder (absolute): /home/ubuntu/nightshift-claude-run-3/band-work/result/stage-3/
- Specifications on disk (read-only): /home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs/pocketful/spec/stage-3.md, stage-2.md, stage-1.md
- Acceptance maps on disk: /home/ubuntu/nightshift-claude-run-3/band-work/result/acceptance/stage-3.md, stage-2.md, stage-1.md
- Supplied checks (partial sample, read-only): /home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs/pocketful/test/ (conftest.py, fixtures.py, stage_1/, stage_2/, stage_3/). The stage-3 sample says it is about a fifth of what is run. Do not read or use the stage-4 spec or tests.
- The kickoff checkout is read-only. Check output goes to /home/ubuntu/nightshift-claude-run-3/band-work/checks/<new-name>.

## What to deliver in `stage-3/`

1. The stage-2 service extended to the whole stage-3 specification: payment instants; `GET /me` with `as_of` and `known_at`; `GET /statement` with window, ordering, running balances, revision fields and `known_at`; payment revision history; `POST /payments/{payment_id}/corrections` (eighth idempotent write path) with `stale_revision`, `insufficient_funds`, `historical_overdraft` and `linked_payment_immutable`; `GET /payments/{payment_id}/revisions`; stable statement snapshots; historical holds with `closed_at`; import of unchanged stage-1 and stage-2 exports with a correct ledger.
2. Everything stage 1 and stage 2 require still works, the UI included.
3. `Dockerfile`, `RUN.md`, your own tests (API, concurrency, browser regression), `SELFCHECK.md` with a row-by-row self-check of the stage-3 map and a statement that the stage-1 and stage-2 suites still pass against the stage-3 image.
4. No stage-4 behaviour (no refunds, no batch corrections). The harness probes the next suite; a folder that passes the whole stage-4 suite claims nothing.

## Design guidance from the Architect (binding where it restates a decision; otherwise advice)

- Model the ledger bitemporally and append-only: per payment an ordered list of immutable revisions `(revision, amount, effective_at, recorded_at, reason)`; per authorisation an ordered list of hold events `(event time, change in held amount)` plus the expiry deadline. Every historical answer is a pure function of (caller, `as_of`, `known_at`) over those logs. Current balances remain the fast path and must always equal the view at "now".
- S3-1: store instants with microsecond precision and make server-assigned instants strictly increasing (payments, revisions' `recorded_at`, hold events). The stage-2 code truncates to seconds; that would make `as_of = <a payment's created_at>` include later payments from the same second. Keep imported stage-1/2 timestamps verbatim.
- S3-2: decode query strings so a literal `+` in an instant stays `+` (do not turn it into a space); `%2B` must work too. Echo `as_of` / `known_at` exactly as given.
- Opening balance of a user = seeded ending balance − net effect of original seeded payments (0 for signups). Corrections never change opening balances.
- `historical_overdraft` check: after applying the proposed revision under the latest known revisions, walk every effective-time boundary and every hold-event boundary for the two affected users; at each boundary combine all movements at that instant first, then require `total ≥ 0` and `available = total − held ≥ 0`. Check `insufficient_funds` (current `available` of the debited wallet) first. All of it inside the same critical section as the write.
- S3-7: snapshots — record the resolved parameters (caller, window with default `to` resolved, effective `known_at` = min(supplied, read instant)) against the append-only log rather than copying entries, so thousands of statement reads on a 20k-payment history stay cheap and old snapshots are byte-for-byte reproducible after later payments, corrections and hold events. Tokens are opaque, ≤ 64 characters, per user, dropped at reset.
- Performance: statement and `as_of` reads must stay well inside 5 s with 20k payments and 50 requests in flight; keep per-user indexes rather than scanning all payments.
- Export/import: bump nothing the earlier stages rely on. Accept stage-1 and stage-2 exports unchanged (they have no revisions, no hold events, no `closed_at`): synthesise revision 1 from `created_at`, hold lifecycles from what the stage-2 state records, and opening balances so that current balances are unchanged. Validate stage-3 state as strictly as before (invalid → 422, destination unchanged).

## Commands

Build and run by hand:

    cd /home/ubuntu/nightshift-claude-run-3/band-work/result/stage-3
    docker build -t pocketful-stage-3 .
    docker run -d --rm --name pocketful-s3 --cpus 2 --memory 2g -e PORT=8080 -p 8080:8080 pocketful-stage-3
    curl -s localhost:8080/health
    docker stop pocketful-s3

Supplied checks, from the kickoff checkout, each run with a NEW `--out` directory. `--stage 3` runs suites 1, 2 and 3 against `stage-3/`, builds the earlier folders as upgrade sources, and probes suite 4:

    cd /home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs
    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 3 --out ../band-work/checks/s3-impl-01

Final check, isolated mode, new `--out`:

    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 3 --mode isolated --out ../band-work/checks/s3-impl-final-01

The result you want is `claimed stage: 3` with suites 1, 2 and 3 fully passing. Also confirm the earlier folders are untouched: `--stage 2 --mode isolated` still prints `claimed stage: 2` (new `--out`). Do not install system packages on the host; do not write into the kickoff checkout; start containers detached and stop them with an ordinary command.

## Process

- Commit as `git -c user.name="Nightshift Implementer" -c user.email="nightshift-implementer@nightshift.invalid" commit ...`. Never amend, rebase or squash after reporting a revision.
- Hand off exactly ONE committed revision with a clean tree, and only when it is complete against this whole handoff. In stage 2 three handoffs named revisions that were replaced before the Verifier finished; do not send a handoff for a revision you intend to follow with another commit. The Architect will not commit to the repository while the Verifier is working.
- Before handing off: row-by-row self-check of the stage-3 map in `stage-3/SELFCHECK.md`, plus stage-1 and stage-2 regression results; fix what fails first.
- Then send the Verifier a self-contained message: evidence header, self-check, this complete task, all three specifications, all three acceptance maps, the repository path, the full commit hash, commands with real output, design choices, anything incomplete. Numbered parts are fine.
- Report the committed revision to the Architect. Questions and blockers go to the Architect, never to the human.

## Architect decisions for stage 3 (also at the end of the stage-3 acceptance map; Q1-Q8 and S2-1..S2-12 stay in force)

- S3-1 Microsecond, strictly increasing server instants; RFC 3339 with offset; imported timestamps verbatim.
- S3-2 Literal `+` in query instants kept; `%2B` works; echo exactly as given.
- S3-3 Correction check order: auth → key present/length → body is a JSON object → claimed-key resolution → unknown payment 404 → not the original sender 403 → `linked_payment_immutable` 422 → field validation 422 → `stale_revision` 409 → `insufficient_funds` 409 → `historical_overdraft` 409.
- S3-4 A correction with the same amount as before is valid: new revision, no money moves (it may change `effective_at`).
- S3-5 `from` later than `to` → 422 `validation_failed`; `from == to` is a valid empty window.
- S3-6 Snapshot-paged responses return the same `snapshot` token; snapshots live in memory until reset; an import drops the destination's earlier snapshots; snapshots are not exported.
- S3-7 Snapshots freeze resolved parameters against the append-only log (see guidance).
- S3-8 Payments created by paying a request are ordinary and correctable; only settlement members and captures are `linked_payment_immutable`. Correcting such a payment does not change the request.
- S3-9 The payment object inside statement entries is the original payment with `amount` replaced by the selected amount; `created_at` stays original. `GET /activity`, replays and `GET /requests` keep the original amount.
- S3-10 The UI is unchanged from stage 2 except that wallet numbers show corrected current balances; no new screens.
- S3-11 A correction's `effective_at` may be earlier than the payment's original `created_at` or than the wallet opening, provided no boundary goes negative; opening balances never change.

If the specification text contradicts any of these readings, the specification wins: tell the Architect which clause.
