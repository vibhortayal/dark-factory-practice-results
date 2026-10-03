# Stage 2 — Verifier verdict, round 2: PASS

Rows: all stage-2 rows S2-0 … N2 · Revision: 0d321ce2763bcfb4f0732d0131fea33c3c4814a6 · Files: stage-2/ (diff since 21475bc: app/web/common.js, search.js, lookup.js, tests/browser_checks.py) · Command: `bash verification/stage-2/run2.sh 0d321ce2763bcfb4f0732d0131fea33c3c4814a6 <evidence-dir>` plus harness host and isolated · Expected / actual: all checks pass / all checks pass · Repro: n/a · Next: Architect

Tree clean, HEAD = 0d321ce; `stage-1/` identical to a8301bb. Image built `--no-cache` from
`git archive` of the revision.

## Round-1 finding
F1 (UI could not render a confirmation recovered from a stage-1 receipt): fixed. UI.X3b passes —
after export from the accepted stage-1 container and import into stage 2, the unchanged form
retries with the same key and body and shows the original reference; uncertainty removed; one
booking. The server still replays the stage-1 receipt unchanged (P2.X1f–g).

## What was run
| What | Result |
|---|---|
| Clean build; internal no-outbound network, `--cpus 2 --memory 2g`; default port | OK, healthy after 0.34 s |
| RUN.md command (run as written in round 1; RUN.md unchanged since) | `GET /` 200 text/html |
| Harness `--stage 2 --mode host` (`checks/verifier-s2-r2-host`) | suite 1: 120 passed; suite 2: 25 passed; stage-3 suite: 1 failed (required) |
| Harness `--stage 2 --mode isolated` (`checks/verifier-s2-r2-isolated`) | suite 1: 120 passed; suite 2: 25 passed; stage-3 suite: 1 failed (required) |
| Implementer's tests | 33 unit tests OK; browser_checks.py 35/35 |
| Whole stage-1 list against the stage-2 image (S2-0) | 392 checks, 392 pass |
| Stage-2 API probes (`probe2.py`) | 98 checks, 98 pass |
| Browser probes (`ui_probe.py`, Chromium) | 95 checks, 95 pass; plus 2 checks added this round for the changed code (UI.X3d, UI.X2e), both pass |
| No request left the service origin; no external URLs in shipped files; nothing on container stderr; no OOM (199 MiB) | pass |

Checks added for the changed code: the recovered confirmation still shows restaurant name, table
label and start time (UI.X3d); lookup of a stage-1-era reservation after the upgrade shows its
table (UI.X2e). The fallback path cannot show a confirmation for a non-2xx answer: it is only
reached from the 200/201 branch, and UI.R2a, UI.R3g, UI.R4c (409 → `booking-error`, no
confirmation) still pass.

## Notes (not blocking)
1. `safeConfirmation` falls back to a bare "You're booked" with the reference if rendering throws;
   with a 2xx body that had no `reference` it would show an empty reference. The server never
   sends such a body.
2. Lookup needs a signed-in user; signed out it shows `reservation-error` with a login link. Spec
   does not say.
3. The UI treats 5xx, non-JSON answers and a 15 s timeout as uncertain; spec only names a lost
   response.
4. `GET /restaurants/{id}` omits `combinable` when the fixture had none; duplicate unordered pairs
   in a fixture are de-duplicated; a pair is stored and returned in `combinable` order whatever
   order the request used. Spec silent.
5. Stage-1 notes still apply (reset time grows with users: about 7.4 s at 1000 users; low scrypt
   work factor n=2^12).
6. Maintainability: 720 lines of plain JS/HTML/CSS with shared helpers; one accessor
   (`TK.tableIds`) now hides the two reservation shapes. Nothing to change.

## Remaining risk not tested
The unshipped part of the judging suite and human judgement of product quality; browsers other
than Chromium; exact cutoff equality; a real 2-vCPU host. The upgrade browser probe simulates
"stage 1 behind the same origin" by answering the browser's account and booking calls from the
stage-1 container until the import.
