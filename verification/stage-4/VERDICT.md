@vibhor15/nightshift-implementer @vibhor15/nightshift-architect
Rows: all rows AA1-AD10 of acceptance/stage-4.md and, through AA1, all rows of the stage-3, stage-2 and stage-1 maps · Revision: dec2ad67348efaf4e4440f6a85c12983458bf029 · Files: stage-4/ (refunds.py, batches.py, corrections.py, statement.py and RUN.md read) · Command: `band-work/verifier/stage-4/run.sh dec2ad67348efaf4e4440f6a85c12983458bf029 <out> all`; harness `--stage 4 --mode isolated --out ../band-work/checks/s4-ver-01` and `--all --mode isolated --out ../band-work/checks/s4-ver-all-01` · Expected / actual: no difference found · Repro: n/a · Next: Architect

# VERDICT: PASS — stage 4, revision dec2ad67348efaf4e4440f6a85c12983458bf029

The supplied checks (stage 4 and all four folders together) and my whole saved list (stage-1, -2, -3 and -4 API lists and the browser list) pass with no failure and no note.

## What I ran

1. Tree clean at dec2ad67348efaf4e4440f6a85c12983458bf029 before and after. `stage-1/`, `stage-2/` and `stage-3/` unchanged since d02b8f6, 93f0fbd and cfff6f7. `stage-4/` has no .git, symlink, submodule or `__pycache__`.
2. Clean `--no-cache` build of `stage-4/` -> exit 0; healthy on the default port, with `-e PORT`, and on the internal no-outbound network with `--cpus 2 --memory 2g`; 172 MiB after the run, no restart, no OOM. RUN.md command run as written -> `/health` 200.
3. Supplied checks, isolated: `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 4 --mode isolated --out ../band-work/checks/s4-ver-01` -> stage 1 pass (147 passed), stage 2 pass (35), stage 3 pass (6), stage 4 pass (5), none skipped or deselected, `claimed stage: 4 on the shipped checks`. `--all --mode isolated --out ../band-work/checks/s4-ver-all-01` -> `stage-1/: claims stage 1`, `stage-2/: claims stage 2`, `stage-3/: claims stage 3`, `stage-4/: claims stage 4 on the shipped checks`.
4. My whole saved list, with the stage-3, stage-2 and stage-1 images as previous services:
   - API: **144 checks, 144 pass, 0 fail, 0 error, 0 notes** (13,962 HTTP requests in the full run). That is the stage-1 list (idempotency over all ten write paths), the stage-2 API list, the stage-3 list (HS-01..HS-16) and 15 stage-4 checks: refund shape, replay and money; receiver-only access; amount boundaries; targets (direct, request payment, capture, settlement member; a refund of a refund refused); the cumulative cap with corrections down, equal and up and a payment corrected to 0; available funds with a hold; no reopening of requests or authorizations; 50-way concurrent refunds and refunds against payments; single corrections of captures, refunds and settlement members refused; refunds in the historical check; batch access, shape (1, 32, 0, 33 items), item rules, settlement completeness and the same-instant rule in two offset spellings; precedence in both orders; combined affordability; a rejected batch changing nothing; success shape with one shared `recorded_at`; originals, settlement replays and old snapshots unchanged; batch-against-batch (50) and batch-against-single races; a stage-3 export imported with its snapshot token, revisions, correction replay and settlement membership; a stage-4 export into a fresh container. In the first full run four checks failed through my own scripts (a wrong expected balance in RF-01, and my upgrade comparison not ignoring the new `refund_of` field); corrected and rerun, all four pass.
   - Browser (Chromium, 375 px and 1280 px): **22 checks, 22 pass, 0 notes**, including the upgrade.
   - Probe after the code read: 40 races of a refund of 600 against a correction of the same payment down to 500 -> never both succeeded, the refunded total never exceeded the corrected amount, balances summed to the seeded total, no 5xx.
5. Implementer's own tests from the clean export: Ran 144 tests, OK.
6. RUN.md lists the error precedence per endpoint; the lists match map rows AB9, AC4 and AD5.

## Notes (do not block)

- **N1** Every Architect [reading] row I checked is met: a refund of a settlement member has `settlement_id: null`; non-operators get 403 before the key check on batches; `correction_batch_id` is null on single corrections; the refund and correction orders of checks.
- **N2** A stage-3 snapshot keeps its original payment shape after the upgrade (no `refund_of` field), so it pages exactly the frozen stage-3 result; snapshots made by stage 4 carry `refund_of`.
- **N3** Two harness service containers from the Implementer's interrupted `--all` run (`s4-impl-all`, started 23:22 UTC) are still running on the host (`df-svc-932a131a643f`, `df-svc-fef2a699fd89`). They are not part of the result.
- **N4** Every first statement read still stores a snapshot until reset; scrypt cost unchanged (N=4096, r=8, p=1).
- **N5** Maintainability: one module per new endpoint; corrections and batches share `parse_fields`, `check_target` and `new_revision`, so the item rules cannot drift apart.

## Remaining risk I could not test

- The judged test set is larger than the shipped checks.
- I do not know how the hidden upgrade check moves a browser between services; I used request interception as map row L5 describes.
- Latency was measured with the client on the same 4-core host as the 2-vCPU container.

## Where things are

- `verification/stage-4/CHECKLIST.md` and this file, in the commit named in the room message.
- Scripts and logs outside the repository: `/home/ubuntu/nightshift-claude-run-7/band-work/verifier/stage-4/` (`run.sh`, `main.py`, `checks_a.py` ... `checks_e.py`, `ui.py`, `runs/r1-all.log`, `runs/r2-api.log`, `runs/probes7.log`, `runs/harness-s4-ver-all-01.log`). Harness output: `/home/ubuntu/nightshift-claude-run-7/band-work/checks/s4-ver-01/` and `s4-ver-all-01/`.
