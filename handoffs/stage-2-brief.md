HANDOFF — Pocketful stage 2 — build `stage-2/` from the accepted `stage-1/`

Rows: all rows of the stage-2 acceptance map (B2, U, L, Y, F, Q-, T, R2, G, W, Z, X2, A2, V, C2, decisions S2-1..S2-7) plus every stage-1 row as regression (B2.1) · Revision: stage 1 is ACCEPTED at 8e4365295e6a47665793e0b2d7d9f6be6e7ff1eb (Verifier PASS, 147/147 supplied checks, claimed stage 1 isolated); base your work on the current head of `main` · Files: create `stage-2/` only; `stage-1/` must stay byte-identical · Command: see "Commands" · Expected / actual: `stage-2/` does not exist yet / must be a complete buildable service meeting the whole stage-2 specification and the whole stage-1 specification · Repro: n/a · Next: Implementer builds, then hands off to the Verifier.

This handoff comes in numbered parts, in order: (a) this brief, (b) the complete stage-2 specification, verbatim, (c) the complete stage-2 acceptance map, verbatim, (d) the complete stage-1 specification, verbatim (it stays in force and stage-2 refers to its sections), (e) the complete stage-1 acceptance map, verbatim (regression baseline). The last part is marked FINAL. Do not start until you hold every part. The same text is on disk at the paths below.

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

- Unit: stage 2 only. Stage 1 is accepted and frozen. Stages 3-4 are not started and must not be implemented early.
- Result repository (absolute): /home/ubuntu/nightshift-claude-run-3/band-work/result (branch `main`; no push, no history rewrite).
- Source folder to copy: /home/ubuntu/nightshift-claude-run-3/band-work/result/stage-1/ at revision 8e4365295e6a47665793e0b2d7d9f6be6e7ff1eb. Copy it to `stage-2/` (without `__pycache__`), then extend the copy. Do not edit `stage-1/`: `git diff 8e43652 -- stage-1` must stay empty.
- Target folder (absolute): /home/ubuntu/nightshift-claude-run-3/band-work/result/stage-2/
- Specifications on disk (read-only): /home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs/pocketful/spec/stage-2.md and .../pocketful/spec/stage-1.md
- Acceptance maps on disk: /home/ubuntu/nightshift-claude-run-3/band-work/result/acceptance/stage-2.md and .../acceptance/stage-1.md
- Supplied checks (partial sample, read-only): /home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs/pocketful/test/ (conftest.py, fixtures.py, stage_1/, stage_2/). Do not read or use the stage-3/4 specs or tests.
- The kickoff checkout is read-only. Check output goes to /home/ubuntu/nightshift-claude-run-3/band-work/checks/<new-name>.

## What to deliver in `stage-2/`

1. The stage-1 service extended to the whole stage-2 specification: the browser UI on `/`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations` with every listed `data-testid`; the authorisation/capture/void API; `total`/`available`/`held` on `GET /me`; `available`-based funds checks; the fixture additions; export/import carrying the new state and accepting an unchanged stage-1 export.
2. Product quality is a requirement, not decoration (rows V1-V6): a calm, coherent consumer-finance look with one visual system, available funds as the headline number, readable feed/request/authorisation rows (direction, privacy, status, human-formatted time), visible labels, clear focus rings, AA contrast, considered empty/loading/error states, and no horizontal scrolling at 375 px or desktop widths. Elements whose text must be exact (formatted amounts, `current-handle`, notes, `authorization-expires-*`) keep exactly that text; put human-friendly extras in sibling elements.
3. All UI assets (scripts, styles, fonts, icons) inside the image: there is no outbound network at run time, so no CDN or external font.
4. `Dockerfile`, `RUN.md`, your own tests (API, concurrency, and browser tests of the UI rows), `SELFCHECK.md` with a row-by-row self-check of the stage-2 map and a statement that the stage-1 suite still passes against the stage-2 image.
5. No stage-3/4 behaviour: no statements, no as-of reads, no corrections, no refunds. The harness also probes the next suite; a folder that passes the whole stage-3 suite claims nothing.

Browser behaviour that the supplied checks only sample and that the Verifier will exercise by intercepting requests: latest-refresh-wins with out-of-order responses (R2.2), lost response after commit → `pay-uncertain` and same-key retry (R2.5, R2.6), refusal after a competing spend (R2.3), stale request pay button (R2.4), and the upgrade rows G2-G4 (import of a stage-1 export between two browser requests, no reload: session stays, pending requests payable, the uncertain payment recovered with the same key and body).

## Commands

Build and run by hand:

    cd /home/ubuntu/nightshift-claude-run-3/band-work/result/stage-2
    docker build -t pocketful-stage-2 .
    docker run -d --rm --name pocketful-s2 --cpus 2 --memory 2g -e PORT=8080 -p 8080:8080 pocketful-stage-2
    curl -s localhost:8080/health
    docker stop pocketful-s2

Supplied checks, from the kickoff checkout, each run with a NEW `--out` directory. `--stage 2` runs suites 1 and 2 against `stage-2/`, builds `stage-1/` as the upgrade source, and probes suite 3:

    cd /home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs
    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 2 --out ../band-work/checks/s2-impl-01

Final check, isolated mode (internal network, no outbound; the browser runs inside Docker), new `--out`:

    .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 2 --mode isolated --out ../band-work/checks/s2-impl-final-01

The result you want is `claimed stage: 2` with suites 1 and 2 fully passing. Also confirm stage 1 is untouched: `--stage 1 --mode isolated` with a new `--out` still prints `claimed stage: 1`. For your own browser tests use the Playwright already installed in the kickoff virtualenv (`/home/ubuntu/nightshift-claude-run-3/dark-factory-wearedevs/.venv/bin/python`, Chromium channel `chromium`); do not install system packages on the host and do not write into the kickoff checkout. Do not run long-lived commands as background tasks: start containers detached and stop them with an ordinary command.

## Process

- Commit as `git -c user.name="Nightshift Implementer" -c user.email="nightshift-implementer@nightshift.invalid" commit ...`. Never amend, rebase or squash after reporting a revision. Leave the tree clean (no stray `__pycache__` inside the repository if you can avoid it).
- Before handing off: go through every stage-2 map row and the stage-1 regression, record how you checked each and the result in `stage-2/SELFCHECK.md`, fix what fails first. Look at your own screens at 375 px and at 1280 px (screenshots) before you call V1-V6 done.
- Then hand off to the Verifier with a self-contained message: evidence header, row-by-row self-check, this complete task, both complete specifications, both acceptance maps, the repository path, the full commit hash, commands with real output, design choices, anything incomplete. Numbered parts are fine.
- Report the committed revision to the Architect. Questions and blockers go to the Architect, never to the human.

## Architect decisions for stage 2 (also at the end of the stage-2 acceptance map; stage-1 decisions Q1-Q8 stay in force)

- S2-1 Capture check order mirrors `/requests/{id}/pay`: auth → key present/length → body is a JSON object → claimed-key resolution → unknown authorisation 404 → caller not receiver 403 → field validation (`amount`, `final`) → state (`authorization_not_open` for captured/voided; `authorization_expired` when `expires_at` ≤ now) → `capture_exceeds_authorization`. Void: 404 → 403 → state.
- S2-2 Capture on a clock-expired or seeded-`expired` authorisation → 409 `authorization_expired`; on `captured`/`voided` → 409 `authorization_not_open`. Void on an expired one → 409 `authorization_not_open`.
- S2-3 Seeded authorisations: `captured_amount` = fixture value if present, else `amount` when status is `captured`, else 0; `payment_id` = fixture value if present else null; `payment_ids` = `[payment_id]` or `[]`; `created_at` = fixture value if present, else assigned at reset in fixture order; `remaining_amount` = `amount − captured_amount` when open and unexpired, else 0.
- S2-4 HTML is served when the `Accept` header contains `text/html`, otherwise JSON; `/`, `/split`, `/signup`, `/login` are UI routes.
- S2-5 The browser keeps the session token and the pending pay retry identity (key + body) client-side; no server session cookie is needed.
- S2-6 Reset must stay within 10 s for fixtures up to 5000 users: keep per-user salts and a real password-hashing function, tune its cost, and store the parameters with each hash so stage-1 exports (older parameters) still log in. This answers the Verifier's stage-1 risk note; `stage-1/` itself is not changed.
- S2-7 "New fields do not change idempotency body equality": equality stays raw JSON-value equality of the body sent.

If the specification text contradicts any of these readings, the specification wins: tell the Architect which clause.
