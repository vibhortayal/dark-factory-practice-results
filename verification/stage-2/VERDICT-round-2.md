@vibhor15/nightshift-implementer @vibhor15/nightshift-architect
Rows: all rows K1-S6 of acceptance/stage-2.md (at 5968fd7, with K6) and A1-J3 of acceptance/stage-1.md through K1 · Revision: 93f0fbd4e6e0aa2bf5447b080bb99a619542fdaf · Files: stage-2/ (whole folder; the 16 changed files read) · Command: `band-work/verifier/stage-2/run.sh 93f0fbd4e6e0aa2bf5447b080bb99a619542fdaf <out> all` and the harness `--stage 2 --mode isolated --out ../band-work/checks/s2-ver-02` · Expected / actual: no difference found · Repro: n/a · Next: Architect

# VERDICT: PASS — stage 2, fix round 1, revision 93f0fbd4e6e0aa2bf5447b080bb99a619542fdaf

B1 is fixed. The supplied checks and my whole saved list pass with no failure and no note.

## B1 first

- Code: `handlers/authorizations.py` now takes both `created_at` and `expires_at` from `store.stamp()`, which formats the one instant read by `operation.begin()` at the start of the locked operation. The functions with the two rounded clock reads are gone. The only clock reads left in `stage-2/pocketful` are `clock.tick()` (called by `operation.begin()` and once by reset for the fixture stamp) and one wall-clock read in `statecheck.py` (note N3).
- Stepped clock inside the image (two instants 6 µs apart, either side of a second boundary, `clock.tick` replaced): one clock read in the operation, `expires_at 2026-10-02T22:30:58.999999+00:00`, `created_at 2026-10-02T22:20:58.999999+00:00`, lifetime 600.0 s.
- Over HTTP: `repro_b1.py 20000` -> 20,000 authorizations, 0 with a lifetime other than 600 s. AZ-18 (4,000 more) passes. B1 is fixed.

## What I ran

1. Tree clean at 93f0fbd4e6e0aa2bf5447b080bb99a619542fdaf before and after. `stage-2/` differs from 1e2214f in 16 files (157 insertions, 49 deletions), all read. `git diff d02b8f6..93f0fbd -- stage-1` is empty.
2. Clean build of `stage-2/` (`git archive` + `docker build --no-cache`) -> exit 0. Healthy after 0.34 s on the default port, 0.34 s with `-e PORT=9123`, under 0.2 s on the internal no-outbound network with `--cpus 2 --memory 2g`. After the run: 167 MiB, no restart, no OOM.
3. RUN.md command exactly as written, from the clean export -> `/health` 200.
4. Supplied checks, isolated: `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 2 --mode isolated --out ../band-work/checks/s2-ver-02` -> `stage 1: pass` (147 passed), `stage 2: pass` (35 passed), none skipped or deselected, `stage 3: fail`, `claimed stage: 2 on the shipped checks`.
5. My whole saved list, on the internal network under the limits, with the stage-1 image as the previous service:
   - API: **113 checks, 113 pass, 0 fail, 0 error, 0 notes**, 9,668 HTTP requests: the stage-1 list (94) rerun against the stage-2 image, the 17 stage-2 checks, AZ-18 (B1) and AZ-19 (row K6). Cross-cutting over every response: no 5xx, nothing over 5 s (10 s for `/_test/*`), every 4xx with the error body, every JSON body `application/json; charset=utf-8`, ids at most 64 characters, every timestamp RFC 3339 with a numeric offset.
   - Browser (Chromium, 375 px and 1280 px): **22 checks, 22 pass, 0 notes**, including the upgrade from the stage-1 container and no horizontal scrolling with the longer timestamps.
6. Checks for the changed code:
   - AZ-19: a ttl-1 hold is captured 0.5 s before its `expires_at`; 0.1 s after it `held` is 0, capture is 409 `authorization_expired`, void is 409 `authorization_not_open`, and all three holds list as `expired`. Timestamps of 121 successive writes (payments, requests, authorizations, a settlement) never go backwards and are all distinct. All of row K6's reading holds: six fractional digits, `created_at` equal to the request instant (0.000 s from my clock), a capture's payment not before its authorization, a seeded `+02:00` timestamp returned exactly as given.
   - `probes5.py` again: 95 probes, 95 pass (wrong-typed authorization values in fixtures and imports, values far beyond stated limits on the new paths, `/static/` paths, expiry around the deadline over repeated reads, 4,000 creations, latency with 4,000 open holds: payment 2 ms, `/me` 2 ms, export 0.08 s).
   - `ui_probes.py` again: 17 probes, 17 pass (double submits on the other forms, markup in names and notes, signed-out visits, refresh ordering).
   - Seeded payments without a timestamp get the reset instant; the feed stays newest first across seeded and new payments.
7. Screens: the authorizations screen at 375 px looked at again; dates render and `authorization-expires-{id}` shows the API's `expires_at`.
8. Implementer's own tests from the clean export: `python3 -m unittest discover -s tests -t .` -> Ran 88 tests, OK.
9. Stage boundary: the stage-3 supplied checks fail at `test_as_of_in_the_future_is_the_current_balance` (KeyError `as_of`). `stage-1/` is unchanged, and its own supplied checks passed in isolated mode at the previous round (`s2-ver-01-stage1`).

## Notes (do not block)

- **N1** Every Architect [reading] row I checked is met, K6 included.
- **N3** (new) `statecheck.py` reads the wall clock directly when it decides which seeded or imported holds are unexpired for the balance rule, and the fixture stamp is a separate `clock.tick()`; a reset therefore uses three instants, not the one K6 asks for. I found no behaviour that depends on it.
- **N4** Funds checks scan every open hold; with 4,000 open holds a payment takes 2 ms. No weakness at that figure.
- **N5** My contrast measurement skips text on the gradient wallet card; by eye it is dark text on a pale background. Elsewhere nothing measured under 4.5:1.
- **N6** Untracked, ignored `__pycache__` folders remain in the working tree of `stage-1/` and `stage-2/`; they are in neither the revision nor the image.
- **N8** Maintainability: the clock is now one small module (`clock.py`, 21 lines) and one entry point (`operation.begin`, 13 lines); every locked handler has to remember to call it, which is a convention and not enforced. `store.now` is shared state set under the lock. RUN.md's map names both files.
- **N9** scrypt cost unchanged (N=4096, r=8, p=1).
- Earlier notes N2 (rounded-up `created_at`) and the void/expiry window are resolved by this revision.

## Remaining risk I could not test

- The judged test set is larger than the shipped checks. I do not know how the hidden upgrade check moves a signed-in browser from the stage-1 to the stage-2 service; I used request interception as map row L5 describes.
- Timestamps now carry six fractional digits. That is valid RFC 3339 and the supplied checks pass, but a hidden check that compared timestamps as whole-second strings would not.
- Visual quality is my judgement of screenshots; only Chromium was used.
- Latency was measured with the client on the same 4-core host as the 2-vCPU container.

## Where things are

- `verification/stage-2/CHECKLIST.md` (updated: AZ-18, AZ-19) and this file, in the commit named in the room message.
- Scripts, logs and screenshots outside the repository: `/home/ubuntu/nightshift-claude-run-7/band-work/verifier/stage-2/` (`runs/f1-all.log`, `runs/f1-repro-b1.log`, `runs/f1-probes5.log`, `runs/f1-ui-probes.log`, `runs/f1/shots/`). Harness output: `/home/ubuntu/nightshift-claude-run-7/band-work/checks/s2-ver-02/`.
