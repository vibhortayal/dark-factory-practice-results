# Verdict — Pocketful stage 2 — BLOCK (round 1)

Rows: Q1, Q3, Q4 (finding); all of K1-U4 and A1-J6 checked · Revision: 60a459ae466a2bb3888f3dc1e4d4ecddaaf0b1aa ·
Files: stage-2/app/ui/css/app.css, stage-2/app/ui/js/pages/requests.js, stage-2/app/ui/js/pages/authorizations.js ·
Command: `python measure.py http://<stage-2 container>` (Playwright) · Expected / actual: request and hold cards fill
the content column / cards are 34-264 px wide and the wallet summary sits below-right of the list ·
Repro: sign in as a user with requests or holds, open `/requests` or `/authorizations` at 375 px or 1280 px ·
Next: Implementer.

**BLOCK** for revision 60a459ae466a2bb3888f3dc1e4d4ecddaaf0b1aa. One finding.

## Finding 1 — the Requests and Holds screens are laid out in a collapsed column (rows Q1, Q3, Q4)

Specification, stage-2 "Product and visual direction": "The required flows must remain clear and usable at a 375
CSS-pixel viewport and at conventional desktop widths" and "The browser experience must feel like a coherent,
presentation-ready consumer finance product"; "Payments, requests, splits and authorisations should be easy to scan".

Reproduction (fixtures: `reqfx()` / `authfx()` in ui.py; any user with at least one request or hold shows it):

    python measure.py http://<stage-2 container>      # run-1/measure.txt

| Viewport | Screen | Card width (actual) | Where the wallet summary lands |
|---|---|---|---|
| 375 | /requests | 100 px | x=148, y=2860 (below the list, to the right) |
| 375 | /authorizations | 34 px (list column width 0) | x=48, y=2010 |
| 768 | /authorizations | 100 px | x=148, y=1998 |
| 1280 | /requests | 264 px of a 1048 px content area | x=890, y=1787 |
| 1280 | /authorizations | 144 px | x=560, y=1806 |
| 1920 | /authorizations | 144 px | x=880, y=1806 |

Actual: at 375 px on `/authorizations` every hold card is 34 px wide; "Authorised", the amount, the RFC 3339 expiry and
the button labels ("Cap / ture", "Rele / ase / hold") break mid-word, one letter group per line. At 1280 px the holds are
a 144 px strip on the left, the rest of the row is empty, and the wallet summary and the hold form start about 1800 px
down on the right. `/requests` shows the same pattern (100 px cards at 375 px). Screenshots: `run-1/shots/`.
Expected: the list uses the content column (full width at 375 px; the wider column of the two-column grid on desktop),
with the summary beside or above it, as on `/`.

Likely cause (for the Implementer to confirm): both pages use `grid requests-grid` with children `.area-summary` and
`.area-main`; `.area-summary` carries `grid-area: summary` from the wallet layout, but `.requests-grid` defines no
`grid-template-areas`, so the named area creates implicit tracks and the two children are auto-placed into them.

The Implementer's own browser tests and the supplied suite do not catch this: they assert no horizontal overflow, which
still holds.

## What was run (all of it, before this verdict)

Tree clean at the revision before and after. Check list `CHECKS.md` was written before any stage-2 revision existed.

| Run | Result |
|---|---|
| `deliver2.py` delivery checks (clean build of stage-2, build of stage-1, default port, `-e PORT`, `--network none`, timed start under 2 vCPU / 2 GiB, no OOM, `git diff 172a3180 -- stage-1` empty) | 11 of 11 passed |
| `checks2.py` API list (whole stage-1 list unchanged + 14 stage-2 checks), limited containers on an internal network, stage-1 export taken from a real stage-1 container | 73 of 73 passed, 3907 requests, 0 responses >= 500 |
| `ui.py` browser list, 15 checks x 2 viewports (375, 1280) | 28 of 30 passed in the first run. The 2 failures were my contrast heuristic misreading white text on the dark gradient card (it did not look at ancestors' background images); confirmed by eye and from the CSS (white on #0b6b5f/#0a4f6b), heuristic corrected, `Q2`/`K2` rerun: 4 of 4 passed (`run-1/ui-q2.log`). Not a finding |
| Supplied: `harness run --track pocketful --stage 2 --out ../band-work/checks/verifier-s2-r1` | stage 1: pass, stage 2: pass (stage 3: fail, not built) |
| Supplied, `--mode isolated --out ../band-work/checks/verifier-s2-r1-isolated` | stage 1: pass, stage 2: pass (35 passed) |
| Implementer's tests in a `git archive` copy: `python3 -m unittest discover -s tests -t .` and the browser suite with the kickoff `.venv` | 82 OK (1 skipped: browser suite without Playwright), 23 OK |
| RUN.md verbatim: `docker build -t pocketful-stage-2 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage-2` | built, `/health` ok, `/` serves the HTML shell |
| K4 next-unit check | `/statement`, `/payments/{id}/revisions`, `/payments/{id}/corrections` return 404; no statement/revision/correction/as-of code in stage-2/app |
| K2 | browser requested nothing from another host in any page load; `grep` of app/ui finds only the SVG namespace URL |

Measured: 50 in flight slowest 0.038 s; 50 concurrent logins 0.371 s; reset of 60 users 0.621 s; start 0.4 s.

Everything else on the list held, including: decimal entry without float error for 0/2/3 minor units, unchanged
resubmit sends nothing new, lost response (before and after commit) -> `pay-uncertain` and same-key retry, latest
refresh wins with out-of-order responses, spend-elsewhere refusal, request cancelled elsewhere, split preview equal to
the server's shares, holds/captures/voids/expiry by the clock, seven idempotent paths, concurrency, stage-1 export ->
stage-2 import with the browser staying signed in and the retry recovered.

## Notes (do not block)

1. Carried from stage 1, unchanged: settlement entry with a non-string handle -> 422; `/_test/import` with a non-object
   JSON body -> 422; zero-amount split request pays as a 0 payment.
2. Capture of an authorization that is past `expires_at` or seeded `expired` answers `authorization_expired`; the table
   also lists `authorization_not_open` for "not open". The specification gives both rows; this matches the Architect's
   recorded choice.
3. `authorization-expires-{id}` shows the raw RFC 3339 text with microseconds for API-created holds
   (`2026-10-03T20:36:59.482442+00:00`), as the testid table requires; it is long and wraps in a narrow card.
4. Maintainability: backend additions are small and follow the stage-1 structure (`holds.py`, `handlers/authorizations.py`,
   `web.py`); lazy expiry runs under the global lock on each authenticated request, cost proportional to open holds.
   UI is plain ES modules, one module per screen. The layout defect above comes from reusing wallet-grid area classes
   in a grid without those areas.
5. Load beyond the stated limits was not applied; state is in memory and unpruned.

## Remaining risk I could not test

- The harness ships only part of the judging tests; product-quality judging of the UI is subjective.
- Only Chromium was used; widths 375, 768, 1280, 1920.
