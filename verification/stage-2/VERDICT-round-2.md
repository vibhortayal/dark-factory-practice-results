# Verdict — Pocketful stage 2 — PASS (round 2)

Rows: all of acceptance/stage-2.md (K1-U4) and acceptance/stage-1.md (A1-J6) · Revision: c59be33b9aaed102d1728cf7f6d9df7a2e0f571f ·
Files: stage-2/ inspected (diff from 60a459a: app/ui/css/app.css, tests/browser/test_browser.py); verification/stage-2/ written ·
Command: measure.py, deliver2.py (checks2.py + ui.py), harness --stage 2 normal and --mode isolated, Implementer's tests ·
Expected / actual: no difference found · Repro: n/a · Next: Implementer reports the revision to the Architect.

**PASS** for revision c59be33b9aaed102d1728cf7f6d9df7a2e0f571f. Round 1 (60a459a) was BLOCK with one finding; see VERDICT.md.

## Finding 1 of round 1 — fixed

Reproduction repeated (`measure.py`, run-2/measure.txt): request and hold cards are 343 px wide at 375 px (full content
width), 736 px at 768 px, 657 px at 1280 and 1920 px; the wallet summary is above the list below 900 px and beside it
(left, 375 px) above. Screenshots in run-2/shots/ read by eye at 375 and 1280 px: no mid-word breaks, list and summary
side by side on desktop.

## Regression run on this revision

Tree clean at the revision before and after. Difference between the two revisions read: CSS grid areas for
`.requests-grid` / `.area-main`, `.meta` rows made flex-wrap, a label size, and one new browser test; no backend change.

| Run | Result |
|---|---|
| deliver2.py delivery checks | 12 of 12 passed (`git diff 172a3180 -- stage-1` empty; clean build; ports; `--network none`; start <= 0.44 s under 2 vCPU / 2 GiB; no OOM) |
| checks2.py (stage-1 list + stage-2 API list) | 73 of 73 passed, 3909 requests, 0 responses >= 500 |
| ui.py (15 checks x 375 and 1280 px) | 30 of 30 passed |
| Supplied `--stage 2 --out ../band-work/checks/verifier-s2-r2` | stage 1: pass, stage 2: pass (stage 3: fail, not built) |
| Supplied `--mode isolated --out ../band-work/checks/verifier-s2-r2-isolated` | stage 1: pass, stage 2: pass |
| Implementer's tests in a `git archive` copy | API 82 OK (1 skipped: browser suite without Playwright); browser 24 OK |

No check was added beyond the list: the changed code is the layout already covered by measure.py and the screenshots.
K4 (no stage-3 feature) and RUN.md were checked in round 1; neither is touched by the diff.

## Notes (do not block)

1. Carried from stage 1: settlement entry with a non-string handle -> 422; `/_test/import` with a non-object JSON body
   -> 422; zero-amount split request pays as a 0 payment.
2. Capture of an authorization past `expires_at` or seeded `expired` answers `authorization_expired`; the table also lists
   `authorization_not_open` for "not open". Matches the Architect's recorded choice.
3. `authorization-expires-{id}` shows RFC 3339 text with microseconds for API-created holds, as the testid table requires.
4. At widths below 900 px the Holds screen puts the hold form above the list, so existing holds start about 1080 px
   down at 375 px. Usable; a matter of taste.
5. Maintainability: unchanged from round 1 (small modules; lazy expiry under the global lock, cost proportional to
   open holds). State is in memory and unpruned; no load beyond the stated limits was applied.

## Remaining risk I could not test

- The harness ships only part of the judging tests; product-quality judging of the UI is subjective.
- Only Chromium was used, at 375, 768, 1280 and 1920 px.
- Timing measured on this host, not the judge's.
