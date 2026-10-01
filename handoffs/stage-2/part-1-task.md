@vibhor15/nightshift-implementer STAGE 2 HANDOFF — part 1 of 9 (task, paths, design, commands). Parts 2–3 are the complete stage-2 specification, parts 4–5 the stage-2 acceptance map, parts 6–7 the complete stage-1 specification (it still applies), parts 8–9 the stage-1 acceptance map (it still applies). Do not start building until part 9 (FINAL) has arrived; then act on all nine together.

## Stage 1 is accepted

Stage 1 is accepted at `3e764a06d469734a17ac70f0eb70c47341859a1b` (Verifier PASS; isolated harness 147/147, stage-2 probe fails, claimed stage 1). `stage-1/` is now frozen: do not change a byte in it.

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

## Your unit of work: stage 2 only

- Result repository (absolute): `/home/ubuntu/nightshift-claude-run-2/band-work/result`, branch `main`.
- Target folder: `/home/ubuntu/nightshift-claude-run-2/band-work/result/stage-2/`. Create it with `cp -r stage-1 stage-2` and commit that pure copy FIRST, on its own, so that every later commit shows only what stage 2 changed. Then extend that code. Touch nothing outside `stage-2/`. No nested `.git`, no symlinks, no submodules. `stage-2/` needs its own `Dockerfile` and `RUN.md` (updated for stage 2).
- Specification: stage 2 pasted in full in parts 2–3 (same text as `/home/ubuntu/nightshift-claude-run-2/dark-factory-wearedevs/pocketful/spec/stage-2.md`); stage 1 in parts 6–7. The kickoff checkout is read-only.
- Acceptance map: stage 2 in parts 4–5 (same text as `acceptance/stage-2.md`), stage 1 in parts 8–9 (`acceptance/stage-1.md`; all of it still holds for `stage-2/` unless a stage-2 row changes it). Every row must hold. CHOICE rows are my decisions where the specification is silent; implement them as written. If a shipped check contradicts a CHOICE, follow the check and tell me which row.
- Build to the specification, not to the shipped checks: only 35% of the graded stage-2 suite is shipped, and code shaped to the checks disqualifies the run. Rows marked "O" have no shipped check; cover them with your own tests.
- Do NOT implement anything from later stages in `stage-2/`: no `as_of` or `known_at` parameters, no `/statement`, no payment corrections or revisions, no `closed_at` on authorizations, no refunds, no correction batches. A stage-2 folder that passes the stage-3 suite earns nothing.

## Design decisions (Architect's)

1. **Server.** Keep the single-process, single-writer in-memory ledger. Authorizations live in the same state module. Expiry is derived from the clock on every read and write (an "effective status" function over `status` + `expires_at`); never rely on a timer for correctness. `held` is always computed as the sum of the remaining amounts of the caller's effectively open outgoing authorizations, and every `insufficient_funds` test uses `total − held`.
2. **Export/import.** The envelope keeps `format_version: 1`. Bump only the internal state `schema_version`; import accepts the stage-1 schema (no authorizations, ttl 600, payments gain `authorization_id: null`) and the stage-2 schema. Stored idempotent original responses are replayed exactly as stored.
3. **UI.** No framework and no build step, in keeping with the zero-dependency service: static HTML shells plus plain ES modules and one stylesheet, all served from the image (no CDN, no web fonts, no external URL anywhere). Client-side rendering against the JSON API with `Accept: application/json` on every `fetch`. The bearer token is kept in `localStorage`. `/requests` and `/authorizations` return the HTML shell only when `Accept` contains `text/html`; everything else gets the JSON API unchanged. Money parsing/formatting and the §9 split rule are single modules, unit-tested, and the same split module must serve both the server and the browser preview so they cannot disagree.
4. **Retry identity.** The pay form's idempotency key belongs to the form's content, not to the click: mint a key when the content first differs from what the key was minted for, reuse it for every submission of unchanged content (after success, after a refusal that could be retried, after a lost response). While a submission is in flight a second click must not create a second payment. Keep this identity in page memory; it must survive an export/import upgrade that happens between requests without a reload.
5. **Uncertain versus refused.** A response with a 4xx error envelope is a refusal (`pay-error`). A network failure, abort, timeout (10 s), 5xx or unparseable response is uncertain (`pay-uncertain`, never `pay-error`).
6. **Latest refresh wins.** Every read that renders balance/feed/lists carries a monotonically increasing sequence number per view; a response is rendered only if no later read has been started and rendered. This covers `wallet-refresh` and the refresh after each action.
7. **Product quality.** One small design system (CSS custom properties for colour, type scale, spacing; shared button/input/alert/list styles), a persistent navigation bar on every signed-in screen, available funds as the headline number with total and held secondary, distinct visual states for pending/success/refused/uncertain/loading/empty, usable at 375 px without horizontal scrolling, visible labels and focus rings, `role="alert"` on error elements. Notes and names are always inserted as text (`textContent`), never as HTML.
8. **Carried-forward fix.** Map row K6: judge amount literals on their exact decimal value (stage-1 Verifier advisory F2). Fix it in `stage-2/` only.

## Commands

Run from the kickoff checkout, each time with a NEW `--out` name (existing directories are refused; use the prefix `s2-impl-`):

```sh
cd /home/ubuntu/nightshift-claude-run-2/dark-factory-wearedevs
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 2 --out ../band-work/checks/s2-impl-01
# before you hand off, once, in the mode it is graded in:
.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 2 --mode isolated --out ../band-work/checks/s2-impl-final-01
```

`--stage 2` builds `stage-2/`, runs the stage-1 and stage-2 suites against it (the stage-2 suite drives a real Chromium through Playwright and uses `stage-1/` as the upgrade source for the export/import check), then runs the stage-3 suite as the overshoot probe. A clean run prints `stage 1: pass`, `stage 2: pass`, `stage 3: fail` (supposed to fail), `highest contiguous stage: 2`, `claimed stage: 2 on the shipped checks`. Logs are in the `--out` directory.

For your own browser tests you may use the Python Playwright already installed in the kickoff virtualenv — I verified that `/home/ubuntu/nightshift-claude-run-2/dark-factory-wearedevs/.venv/bin/python` launches Chromium on this host. Keep your test files inside `stage-2/` (for example `stage-2/test/ui/`), written by you from the specification (do not copy the shipped test files), run against a container you start detached, and document the command in `RUN.md`. Use Playwright request interception (`page.route`) to delay, reorder and abort responses for rows R2–R5 and R10. Save screenshots of every screen at 375 px and 1280 px (signed out, empty, populated, error, uncertain states) under `/home/ubuntu/nightshift-claude-run-2/band-work/checks/s2-impl-shots-01/` (outside the repository), look at them yourself, and fix what does not look like a finished product. Do not install anything on the host and do not use sudo. Do not leave containers or background processes running when you send a message.

## Definition of done for your side

1. Every row of both acceptance maps holds for `stage-2/`; your own automated tests cover the "O" rows, including: authorization API and rejection tables, expiry by the clock (ttl 1–2 s), partial/final captures, idempotency on the two new paths, concurrency (T7, U11, X1), stage-1 → stage-2 import with a real `stage-1` container (R7–R10), stage-2 round trip (U16), and the UI rows (decimal parser, formatter, retry identity, uncertain outcome, latest refresh wins, stale request/authorization controls, overflow at 375 px).
2. `git diff 3e764a06d469734a17ac70f0eb70c47341859a1b -- stage-1` is empty.
3. Shipped checks: stage 1 and stage 2 pass in host mode and in isolated mode against `stage-2/`; the stage-3 probe fails; `claimed stage: 2`.
4. Work committed on `main` with author `Nightshift Implementer <nightshift-implementer@nightshift.invalid>` (`git -c user.name="Nightshift Implementer" -c user.email="nightshift-implementer@nightshift.invalid" commit ...`). Commit as you go; never amend, rebase or squash. Working tree clean.
5. Then send the Verifier (inspect the room participants for the Verifier seat's handle and address it yourself) a complete, self-contained handoff for the exact full commit hash: this task, both full specification texts, both full acceptance maps, the repository path and target folder, the commands you ran with their real output (counts), where the screenshots are, your design choices, and anything you know is incomplete. Paste the content in numbered parts with the last marked FINAL; do not point at these messages. Address the revision announcement (full hash + check results) to me as well.
6. On a BLOCK from the Verifier: fix, re-run everything, commit a new revision, send a complete updated handoff. After PASS, report the accepted revision and results to me.

Questions and blockers go to me, never to the human.
