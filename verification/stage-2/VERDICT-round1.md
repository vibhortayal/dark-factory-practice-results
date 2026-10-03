# Stage 2 — Verifier verdict, round 1: BLOCK

Rows: X3 (F1); all other rows S2-0 … N2 pass · Revision: 21475bce83bbe00c825c5795a1764fbe46bed467 · Files: stage-2/app/web/common.js:92 (`ids.map`), stage-2/app/web/search.js (confirmation rendering) · Command: `bash verification/stage-2/run2.sh 21475bce83bbe00c825c5795a1764fbe46bed467 <evidence-dir>` · Expected / actual: after a stage-1 → stage-2 upgrade the retried booking shows the original confirmation / the page throws and shows nothing · Repro: F1 below · Next: Implementer

Tree clean, HEAD = 21475bc; `stage-1/` identical to a8301bb. Image built `--no-cache` from
`git archive` of the revision.

## Blocking finding

### F1 — UI cannot show a confirmation recovered from a stage-1 receipt (row X3; spec "Existing clients after an upgrade")
Spec: "A booking whose response was lost before export remains retryable after import with the
same body and key; the UI must recover the original confirmation." and (stage-1 §7) a replay
returns "body identical to the original response".

Repro (`ui_probe.py u_upgrade`; containers: accepted stage-1 image a8301bb and this stage-2 image,
both reset with the same fixture):
1. Browser on the stage-2 origin; its `/auth/*` and `/reservations*` calls are answered by the
   stage-1 service (the service behind the origin before the upgrade). Log in, search, open
   `slot-t_2-19:00`, submit; the `POST /reservations` response is dropped after stage 1 commits.
   → `booking-uncertain` shown (correct).
2. `GET /_test/export` on stage 1 → `POST /_test/import` on stage 2 → 204. Stop redirecting.
3. Click `booking-submit` again (no reload).

Actual: the browser sends the same key and body; stage 2 answers `200` with the original
stage-1 receipt (`{"reservation_id":"res_1","reference":"U5F5QOKC",…,"table_id":"t_2",…}`, no
`table_ids`, as §7/§10 require). The page throws `Cannot read properties of undefined (reading
'map')` (common.js:92, `ids.map` on the missing `table_ids`); `booking-uncertain` disappears and
neither `confirmation` nor `booking-error` is shown.
Expected: `confirmation` with `confirmation-reference` = the original reference
(evidence-r1/upgrade-debug.txt, ui.log check UI.X3b). The server side of the upgrade is correct
(P2.X1a–m pass); the same key and body were sent (UI.X3c passes); the browser stays signed in and
the retained reference opens in lookup (UI.X2a–d pass).

## What was run
| What | Result |
|---|---|
| Clean build; start on an internal no-outbound network, `--cpus 2 --memory 2g`; default port | OK, healthy after 0.33 s |
| RUN.md command as written | `GET /` 200 text/html, `/health` ok |
| Harness `--stage 2 --mode host` (`checks/verifier-s2-r1-host`) | suite 1: 120 passed; suite 2: 25 passed; stage-3 suite: fail (required) |
| Harness `--stage 2 --mode isolated` (`checks/verifier-s2-r1-isolated`) | suite 1: 120 passed; suite 2: 25 passed; stage-3 suite: fail (required) |
| Implementer's tests | 33 unit tests OK; `tests/browser_checks.py` 34/34 |
| Whole stage-1 list against the stage-2 image (row S2-0) | 392 checks, 392 pass |
| Stage-2 API probes `probe2.py` (combinable, options, create/PATCH/cancel/moves with `table_ids`, seeded, export/import, stage-1 → stage-2 upgrade with a real a8301bb container, concurrency) | 98 checks, 98 pass |
| Browser probes `ui_probe.py` (Chromium) | 90 checks: 89 pass, 1 fail (UI.X3b = F1). The layout section first stopped on a fault of my own probe (stale booking between viewports); fixed in the probe and rerun: 9/9 pass (ui-layout-rerun.log) |
| No request left the service origin in any browser probe; no external URLs in shipped files | pass |
| `stage-1/` unchanged since a8301bb; no stage-3 endpoints (stage-3 suite: `POST /restaurant…` → 404) | pass |

Architect's points: (a) signed-out lookup shows `reservation-error` "Please log in…" with a link —
no required flow breaks; (b) see note 2; (c) R1 and R2 pass (form kept with its input after the
409 refresh; a later search replaces grid and form); (d) see note 3; (e) R3 with loss before and
after commit, and R4 with a combination (loss after commit, retry, 409) pass; (f) X1/X2 pass, X3
fails (F1); (g) `auth-error`, `booking-error`, `booking-uncertain`, `confirmation`,
`reservation-error`, `reservation-detail`, `no-slots`, `current-user`,
`reservation-cancel-button` are absent from the DOM when not applicable (presence.txt);
(h) screenshots at 375 px and 1280 px reviewed: coherent warm palette, clear hierarchy, labelled
inputs, distinct free / unavailable / selected / uncertain / refused / success states, combos read
"Tables 1 + 2 · seats 6"; no horizontal scroll; measured contrast ≥ 4.5:1 on all visible text;
focus outline changes on Tab; same nav on all routes; (i) CC1 passes; (j) 392/392; (k) fails as
required.

## Notes (not blocking)
1. Lookup needs a signed-in user; signed out it shows `reservation-error` with a login link. The
   spec does not say which.
2. The UI treats 5xx, non-JSON answers and a 15 s timeout as "uncertain". Spec only names a lost
   response.
3. `GET /restaurants/{id}` omits `combinable` when the fixture had none; duplicate unordered pairs
   in a fixture are de-duplicated. Spec is silent on both.
4. A pair is stored and returned in `combinable` order whatever order the request used.
5. No `aria-busy` while a search is pending (a spinner is drawn; loading-desktop.png).
6. Maintainability: UI is 700 lines of plain JS/HTML/CSS in `app/web/`, shared helpers in
   `common.js`; rendering assumes `table_ids` on every reservation object (root of F1).

## Remaining risk not tested
The unshipped part of the judging suite (25% judged on product quality by people); exact cutoff
equality; browsers other than Chromium; a real 2-vCPU host.
