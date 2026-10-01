@vibhor15/nightshift-implementer
Rows: all stage-4 rows + stage-1/2/3 regression · Revision: stage-3 accepted at c00530dd77a2caff402419f3c01c2a48a0368148; base = head of main · Files: stage-4/ (to create) · Command: n/a · Expected / actual: n/a · Repro: n/a · Next: Implementer
STAGE-4 HANDOFF PART 1/14 — BRIEF

HANDOFF — Pocketful stage 4 — build `stage-4/` from the accepted `stage-3/`

Rows: all rows of the stage-4 acceptance map (B4, RF, CR, CB, UP4, decisions S4-1..S4-9) plus every stage-1, stage-2 and stage-3 row as regression (B4.1) · Revision: stage 3 is ACCEPTED at c00530dd77a2caff402419f3c01c2a48a0368148 (Verifier PASS; supplied checks 147/147, 35/35, 6/6, claimed stage 3 isolated); stage 2 accepted at f8086da438d3fa7dd38c886decd4ed4a2b8c9dd8; stage 1 accepted at 8e4365295e6a47665793e0b2d7d9f6be6e7ff1eb; base your work on the current head of `main` · Files: create `stage-4/` only; `stage-1/`, `stage-2/`, `stage-3/` must stay byte-identical · Command: see "Commands" · Expected / actual: `stage-4/` does not exist yet / must be a complete buildable service meeting all four specifications · Repro: n/a · Next: Implementer builds, then hands off to the Verifier.

This handoff comes in numbered parts, in order: (a) this brief, (b) the complete stage-4 specification, verbatim, (c) the complete stage-4 acceptance map, verbatim, (d) stage-3 specification, (e) stage-3 acceptance map, (f) stage-2 specification, (g) stage-2 acceptance map, (h) stage-1 specification, (i) stage-1 acceptance map. The last part is marked FINAL. Do not start until you hold every part. The same text is on disk at the paths below.

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

- Unit: stage 4, the last one. Stages 1-3 are accepted and frozen.
- Result repository (absolute): /home/ubuntu/nightshift-claude-run-3/band-work/result (branch `main`; no push, no history rewrite).
- Source folder to copy: /home/ubuntu/nightshift-claude-run-3/band-work/result/stage-3/ at revision c00530dd77a2caff402419f3c01c2a48a0368148. Copy it to `stage-4/` (without `__pycache__`), then extend the copy. `git diff c00530d -- stage-1 stage-2 stage-3` must stay empty.
- Target folder (absolute): /home/ubuntu/nightshift-claude-run-3/band-work/result/stage-4/
- Specifications on disk (read-only): /home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs/pocketful/spec/stage-4.md, stage-3.md, stage-2.md, stage-1.md
- Acceptance maps on disk: /home/ubuntu/nightshift-claude-run-3/band-work/result/acceptance/stage-4.md, stage-3.md, stage-2.md, stage-1.md
- Supplied checks (partial sample, read-only): /home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs/pocketful/test/ (conftest.py, fixtures.py, stage_1/ .. stage_4/). The stage-4 sample has 5 checks; almost all stage-4 behaviour rests on your tests and the Verifier's.
- The kickoff checkout is read-only. Check output goes to /home/ubuntu/nightshift-claude-run-3/band-work/checks/<new-name>.

## What to deliver in `stage-4/`

1. The stage-3 service extended to the whole stage-4 specification: `POST /payments/{payment_id}/refunds` (ninth idempotent path), `refund_of` on every payment, the refund/correction interaction rules, `POST /correction-batches` (tenth idempotent path) with settlement completeness, shared effective instants, the stated error precedence, combined affordability and all-or-nothing behaviour, `correction_batch_id` on revisions, and import of unchanged stage-1, stage-2 and stage-3 exports retaining settlement membership, corrections and snapshots.
2. Everything stages 1-3 require still works, the UI included.
3. `Dockerfile`, `RUN.md`, your own tests (API, concurrency, browser regression), `SELFCHECK.md` with a row-by-row self-check of the stage-4 map and a statement that the stage-1, stage-2 and stage-3 suites still pass against the stage-4 image.

## Design guidance from the Architect (binding where it restates a decision; otherwise advice)

- A refund is a new ordinary payment record (own id, own revision 1 at its `created_at`, `refund_of` set, all other links null, note and visibility copied from the target) plus a per-target refunded total. It is immutable: no corrections, no refunds of it. It funds from the refunder's current `available`.
- The refundable remainder of a payment is its latest revision amount minus the sum of its refunds. A correction (single or batch) that would put the amount below the refunded sum is `refund_exceeds_payment`.
- Do refunds and batches inside the same critical section as every other write so that refund-vs-refund, refund-vs-correction and batch-vs-single-correction races are serial; `stale_revision` decides overlapping corrections.
- Batch = one atomic append of N revisions with one shared `recorded_at` (strictly later than every member's previous `recorded_at`, and consistent with the strictly increasing server clock of S3-1) and one `correction_batch_id`. Evaluate in this order and stop at the first failure: batch shape → items in input order (each item: field validation, unknown payment, immutable target, stale revision, below refunded total) → settlement completeness → members' effective instants equal → combined current `available` of every affected wallet → historical `total` and `available` at every effective/event boundary under the proposed revisions. Nothing is written, and no key is claimed, unless all pass.
- Settlement members are correctable only through a batch that contains every member of that settlement; the single-payment endpoint keeps answering `linked_payment_immutable` for them. Captures and refunds are immutable everywhere.
- Statement snapshots taken before a refund or batch keep paging their frozen entries; new reads see refund payments as entries and batch revisions by the `known_at` rules on the shared `recorded_at`.
- Export/import: accept stage-1, stage-2 and stage-3 exports unchanged (stage-3 exports carry revisions, snapshots and the clock; none carry refunds or batch ids). Default `refund_of` and `correction_batch_id` to null for imported records. Keep import validation strict and linear; keep the S3-12 capacity (512 MiB test bodies, readable 413, 60000 + 60000 state inside 10 s).
- Performance (S4-8): do not make per-wallet historical work worse. The Verifier measured stage 3 at 1.7 s (50 `known_at` reads in flight) and 2.4 s (50 corrections in flight) on a 20000-payment wallet; a 32-item batch on such a wallet must stay inside 5 s with 50 requests in flight. If you can cheaply cache per-wallet timelines for repeated reads without risking correctness, do so; correctness and the frozen behaviour of earlier stages come first.

## Commands

Build and run by hand:

    cd /home/ubuntu/nightshift-claude-run-3/band-work/result/stage-4
    docker build -t pocketful-stage-4 .
    docker run -d --rm --name pocketful-s4 --cpus 2 --memory 2g -e PORT=8080 -p 8080:8080 pocketful-stage-4
    curl -s localhost:8080/health
    docker stop pocketful-s4

Supplied checks, from the kickoff checkout, each run with a NEW `--out` directory. `--stage 4` runs suites 1-4 against `stage-4/` and builds the earlier folders as upgrade sources:

    cd /home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs
    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 4 --out ../band-work/checks/s4-impl-01

Final check, isolated mode, new `--out`:

    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 4 --mode isolated --out ../band-work/checks/s4-impl-final-01

The result you want is `claimed stage: 4` with suites 1-4 fully passing. Also run the whole submission once, isolated, new `--out`:

    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --all --mode isolated --out ../band-work/checks/s4-impl-all-01

Every folder must claim its own stage. Do not install system packages on the host; do not write into the kickoff checkout; start containers detached and stop them with an ordinary command.

## Process

- Commit as `git -c user.name="Nightshift Implementer" -c user.email="nightshift-implementer@nightshift.invalid" commit ...`. Never amend, rebase or squash after reporting a revision.
- Hand off exactly ONE committed revision with a clean tree, complete against this whole handoff. If a message from the Architect arrives while you are finishing, read it before you commit and hand off — in stages 2 and 3 a revision was handed off seconds after a fix request and had to be superseded. The Architect will not commit to the repository while the Verifier is working, and you must not edit the tree until the verdict is out.
- Before handing off: row-by-row self-check of the stage-4 map in `stage-4/SELFCHECK.md`, plus stage-1/2/3 regression results; fix what fails first.
- Then send the Verifier a self-contained message: evidence header, self-check, this complete task, all four specifications, all four acceptance maps, the repository path, the full commit hash, commands with real output, design choices, anything incomplete. Numbered parts are fine.
- Report the committed revision to the Architect. Questions and blockers go to the Architect, never to the human.

## Architect decisions for stage 4 (also at the end of the stage-4 acceptance map; Q1-Q8, S2-1..S2-12, S3-1..S3-13 stay in force)

- S4-1 Refund check order: auth → key present/length → body is a JSON object → claimed-key resolution → unknown payment 404 → caller is not the original receiver 403 → target is a refund 422 `invalid_refund_target` → amount validation 422 → `refund_exceeds_payment` 422 → `insufficient_funds` 409.
- S4-2 Batch check order: auth → key → body is a JSON object → claimed-key resolution → non-operator 403 → batch shape 422 (missing/non-array `corrections`, non-object item, 0 or more than 32 items, duplicate `payment_id`) → per item in input order: field validation 422, unknown payment 404, `linked_payment_immutable` 422, `stale_revision` 409, `refund_exceeds_payment` 422 → `incomplete_settlement` 422 → members' differing effective instants 422 `validation_failed` → `insufficient_funds` 409 → `historical_overdraft` 409.
- S4-3 Refund amount follows the payment amount rule (integral, 1..1000000000) → otherwise 422 `validation_failed`; a valid amount above the refundable remainder → 422 `refund_exceeds_payment`.
- S4-4 A refund payment has its own revision 1 (`effective_at = recorded_at = created_at`), and can be neither corrected (`linked_payment_immutable`) nor refunded (`invalid_refund_target`).
- S4-5 The refunded total of a payment is the sum of its refunds (refunds are immutable).
- S4-6 Single-correction responses and every revision in `GET /payments/{id}/revisions` expose `correction_batch_id` (null when not from a batch).
- S4-7 The UI is unchanged; refund payments show in the feed as ordinary payments.
- S4-8 Capacity and latency targets carried from stage 3 (see guidance).
- S4-9 Generated ids for refunds (payment ids) and correction batches are fixed-width like every other generated id (S3-13); at most 64 characters.

If the specification text contradicts any of these readings, the specification wins: tell the Architect which clause.
