@vibhor15/nightshift-implementer @vibhor15/nightshift-architect
Rows: N2, V6, V7, X8 (blocking); T1, Y5, Z1, J3 (notes) · Revision: 0f569d9b19e0c5e8cb69fb30150c8ed6eea9c9c0 · Files: stage-3/pocketful/holds.py, stage-3/pocketful/fixture.py (read only) · Command: `BASE_URL=http://127.0.0.1:<port> python3 /home/ubuntu/nightshift-claude-run-7/band-work/verifier/stage-3/main.py api HS-15` · Expected / actual: a seeded `expired` hold holds nothing in any view / it holds its full amount in every view before its `expires_at` and causes a false `historical_overdraft` · Repro: B1 below · Next: Implementer

# VERDICT: BLOCK — stage 3, revision 0f569d9b19e0c5e8cb69fb30150c8ed6eea9c9c0

One blocking finding. Everything else I ran passes: the supplied checks, my stage-1 and stage-2 lists (API and browser) against the stage-3 image, and all 14 stage-3 checks I derived before the run.

## Blocking finding

**B1 — a seeded hold with status `expired` and an `expires_at` still in the future is counted as held in every historical view.** Map rows N2, V6, V7, X8.
Specification, stage 2, Model: "Seeded `status` is `open`, `captured`, `voided` or `expired`. Only `open` holds anything."
Specification, stage 3, Historical holds: "For `GET /me?as_of=T&known_at=K`, all four money fields describe that same view: `balance = total`, `available = total - held`." and "A correction is rejected with 409 `historical_overdraft` if it makes either total or available negative at any past effective/event boundary".
Repro (HS-15 in my list): reset with users ada 3500, bob 0, cy 0 and one authorization `{"id": "a_exp", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 3000, "note": "deposit", "visibility": "public", "status": "expired", "expires_at": <now + 2 h>}` -> 204. Then as ada:
- `GET /me` -> `held: 0, available: 3500` (correct).
- `GET /me?as_of=<now>` -> `held: 3000, available: 500`; the same at now + 30 min. Expected `held: 0, available: 3500`.
- `POST /payments {"to_handle": "bob", "amount": 1000}` -> 201, then `POST /payments/<id>/corrections {"expected_revision": 1, "amount": 1000, "effective_at": <its created_at>, "reason": "no change"}` -> `409 historical_overdraft`. Expected 201: nothing was ever held, and the correction changes no amount.
Seeded `captured` and `voided` holds hold nothing in any view (checked with expiry two hours in the future and in the past), and an `expired` hold whose `expires_at` is in the past holds nothing either. Cause: for a seeded `expired` hold, `fixture.py` sets `closed_at = expires_at`, and `holds.release_time` uses `closed_at` only for `captured`/`voided`, so the hold counts from its creation (the reset time) until `expires_at` in `held_at` and `hold_steps`.

## What I ran

1. Tree clean at 0f569d9b19e0c5e8cb69fb30150c8ed6eea9c9c0 before and after. `stage-1/` and `stage-2/` unchanged since d02b8f6 and 93f0fbd. `stage-3/` has no .git, symlink, submodule or `__pycache__`.
2. Clean `--no-cache` build of `stage-3/` -> exit 0. Healthy after 0.34 s on the default port, 0.34 s with `-e PORT=9123`, under 0.1 s on the internal no-outbound network with `--cpus 2 --memory 2g`. After the run: 157 MiB, no restart, no OOM.
3. RUN.md command exactly as written, from the clean export -> `/health` 200.
4. Supplied checks, isolated: `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 3 --mode isolated --out ../band-work/checks/s3-ver-01` -> `stage 1: pass` (147 passed), `stage 2: pass` (35 passed), `stage 3: pass` (6 passed), none skipped or deselected, `stage 4: fail` (KeyError `refund_of`), `claimed stage: 3 on the shipped checks`.
5. My list, on the internal network under the limits, with the stage-2 and stage-1 images as previous services:
   - API: **127 checks, 127 pass, 0 fail, 0 error, 0 notes**, 12,730 HTTP requests. That is the stage-1 list (idempotency now over eight paths, corrections included), the stage-2 API list, and 14 stage-3 checks: seeded and API payment timestamps; `GET /me?as_of` with instants between payments, at a payment's exact `created_at` and 1 µs before it, other offsets, eight invalid forms; statements with half-open windows at exact instants, opening/closing arithmetic, paging a 7-entry window with limits 1, 3, 7, 8 and offsets 0-9; holds, captures and settlement members in statements; corrections (shape, every input boundary, permissions, stale revisions, 50 concurrent corrections, replays after newer revisions, linked payments); the four `historical_overdraft` cases (spend before funding, increase funded exactly, two movements at one instant, a past hold); `known_at` before, at and after a correction's `recorded_at`; historical holds around creation, partial capture, void, final capture and expiry; `closed_at`; snapshots after payments, corrections, captures and voids and during four concurrent writers; upgrades from the stage-1 and stage-2 services (with an imported voided hold); 2,000 payments on one wallet (statement page 7 ms, historical `/me` 5 ms) with 50 mixed requests in flight. Cross-cutting over every response: no 5xx, nothing over 5 s, every 4xx with the error body.
   - Browser (Chromium, 375 px and 1280 px): 22 checks. In the run with all containers, 21 passed and UI-01 errored once: the very first page load did not show the login form within 6 s. I could not reproduce it: UI-01 passed in three runs on its own and the whole list passed in a second run (UI-17, the upgrade, needs the previous-stage container and passed in the first run). Login forms loaded in 0.08-0.11 s.
   - After the code read: HS-15 **fails** (B1); `probes6.py`, 12 probes, 11 pass (the failing one is B1): seeded captured/voided holds, snapshots with a future `to` and a future `known_at`, a correction of a seeded payment to before its original time (opening balance and sums unchanged).
6. Screens: unchanged from stage 2; looked at again at 375 px with holds.
7. Implementer's own tests from the clean export: `python3 -m unittest discover -s tests -t .` -> Ran 125 tests, OK.
8. Stage boundary: the stage-4 supplied checks fail at their first test (`refund_of`); nothing beyond stage 3 found.

## Notes (do not block)

- **N1** Every Architect [reading] row I checked is met: `from` after `to` 422; wrong-typed correction fields 422; `effective_at` echoed as sent; request payments correctable; empty `snapshot=` 404; snapshots survive export/import and repeat their token; T6 for an imported voided hold (500 + 50 held at the third hold's creation).
- **N2** (UI-01 above) a single cold-start timeout of the first browser page load; not reproduced.
- **N3** Every first statement read stores a snapshot until reset: 2,000 reads took 1.7 s and grew the export to 0.47 MB. No weakness at that figure; the store has no bound other than reset.
- **N4** Stage-2 carry-overs are addressed: reset and import use the one instant of the operation (`store.locked()` begins it), and handlers can no longer forget to begin an operation.
- **N5** Maintainability: one history module (`history.py`, 88 lines) serves `/me?as_of`, `/statement` and the overdraft check, and the hold history lives in `holds.py`; corrections and statements have one handler each; `stateupgrade.py` holds the older-export rules. `fixture.py` (219 lines) and `statecheck.py` (176 lines) are the largest modules.
- **N6** scrypt cost unchanged (N=4096, r=8, p=1).

## Remaining risk I could not test

- The judged test set is larger than the shipped checks; the stage-3 rules leave many view combinations, and I tested the boundaries the specification names.
- I do not know how the hidden upgrade check moves a browser between services; I used request interception as map row L5 describes.
- Latency was measured with the client on the same 4-core host as the 2-vCPU container.

## Where things are

- `verification/stage-3/CHECKLIST.md` and this file, in the commit named in the room message.
- Scripts and logs outside the repository: `/home/ubuntu/nightshift-claude-run-7/band-work/verifier/stage-3/` (`run.sh`, `main.py`, `checks_a.py`, `checks_b.py`, `checks_c.py`, `checks_d.py`, `ui.py`, `probes6.py`, `runs/r1-api.log`, `runs/r1-ui.log`, `runs/r2-ui.log`, `runs/probes6-r1.log`, `runs/hs15-r1.log`). Harness output: `/home/ubuntu/nightshift-claude-run-7/band-work/checks/s3-ver-01/`.
