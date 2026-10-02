@vibhor15/nightshift-implementer @vibhor15/nightshift-architect
Rows: all rows T1-Z2 of acceptance/stage-3.md (at c6a4ca0, V7 changed) and, through T1, K1-S6 and A1-J3 · Revision: cfff6f7b46744123d0e1a59fd3983e815518fbfb · Files: stage-3/ (the 4 changed files read) · Command: `band-work/verifier/stage-3/run.sh cfff6f7b46744123d0e1a59fd3983e815518fbfb <out> all` and the harness `--stage 3 --mode isolated --out ../band-work/checks/s3-ver-02` · Expected / actual: no difference found · Repro: n/a · Next: Architect

# VERDICT: PASS — stage 3, fix round 1, revision cfff6f7b46744123d0e1a59fd3983e815518fbfb

B1 is fixed. The supplied checks and my whole saved list (API and browser) pass with no failure and no note.

## B1 first

- HS-15 (the reproduction): `GET /me?as_of=<now>` and at now + 30 min -> `held: 0, available: 3500`; the unchanged correction -> 201. Fixed.
- HS-16 (added for the changed row V7): seeded `captured`, `voided` and `expired` holds, each with `expires_at` two hours in the past and in the future, hold nothing in six views (plain `/me`; `as_of` now, before and after `expires_at`, with `known_at` before the reset, an hour ahead); an unchanged correction and one using the whole wallet both succeed; `closed_at` is never in the future; a seeded open hold still holds and still gives `insufficient_funds`. Pass.
- Code: `holds.release_time` returns the creation instant for a hold flagged `seeded_closed`, so `held_at` and `hold_steps` count nothing; the flag is set only by the fixture loader and removed from API views. `fixture._closed_at` keeps `expires_at` only when it is at or before the reset time.
- The flag survives a stage-3 export -> import into a second container: for all three closed statuses the imported service shows `held: 0` as of now and accepts the unchanged correction.

## What I ran

1. Tree clean at cfff6f7b46744123d0e1a59fd3983e815518fbfb before and after; `stage-3/` differs from 0f569d9 in 4 files (60 insertions, 3 deletions), all read; `stage-1/` and `stage-2/` unchanged since their accepted revisions; no .git, symlink, submodule or `__pycache__` in `stage-3/`.
2. Clean `--no-cache` build -> exit 0; healthy on the default port, with `-e PORT`, and on the internal no-outbound network with `--cpus 2 --memory 2g`; 159 MiB after the run, no restart, no OOM.
3. Supplied checks, isolated: `.venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 3 --mode isolated --out ../band-work/checks/s3-ver-02` -> `stage 1: pass` (147 passed), `stage 2: pass` (35 passed), `stage 3: pass` (6 passed), `stage 4: fail`, `claimed stage: 3 on the shipped checks`.
4. My whole saved list with the stage-2 and stage-1 images as previous services: API **129 checks, 129 pass, 0 fail, 0 error, 0 notes** (12,813 HTTP requests: the stage-1 list over eight idempotent paths, the stage-2 API list, HS-01..HS-16); browser **22 checks, 22 pass, 0 notes** at 375 px and 1280 px, including the upgrade. Cross-cutting over every response: no 5xx, nothing over 5 s, every 4xx with the error body.
5. Implementer's own tests from the clean export: Ran 127 tests, OK.
6. Stage boundary: the stage-4 supplied checks fail (`refund_of`); nothing beyond stage 3 found.

## Notes (do not block)

- **N1** Every Architect [reading] row I checked is met, V7 as changed included.
- **N3** Every first statement read stores a snapshot until reset (2,000 reads: 1.7 s, export 0.47 MB at the previous round); no bound other than reset.
- **N5** Maintainability as at the previous round; the closed-hold decision now sits in `holds.release_time`, one place, as the Architect asked.
- **N6** scrypt cost unchanged (N=4096, r=8, p=1).
- The cold-start timeout of the first browser page load seen once at the previous round did not occur.

## Remaining risk I could not test

- The judged test set is larger than the shipped checks; the stage-3 rules leave many view combinations, and I tested the boundaries the specification names.
- I do not know how the hidden upgrade check moves a browser between services; I used request interception as map row L5 describes.
- Latency was measured with the client on the same 4-core host as the 2-vCPU container.

## Where things are

- `verification/stage-3/CHECKLIST.md` (updated: HS-15, HS-16) and this file, in the commit named in the room message.
- Scripts and logs outside the repository: `/home/ubuntu/nightshift-claude-run-7/band-work/verifier/stage-3/` (`runs/f1-all.log`). Harness output: `/home/ubuntu/nightshift-claude-run-7/band-work/checks/s3-ver-02/`.
