@vibhor15/nightshift-implementer @vibhor15/nightshift-architect
VERDICT stage 1: **PASS** for revision eb1de488e1d191439f3607f1589d17e4fd0b1d5d

Rows: all A1–M1 · Revision: eb1de488e1d191439f3607f1589d17e4fd0b1d5d · Files: stage-1/{Dockerfile,.dockerignore,RUN.md,app/*.py} inspected; tests/test_api.py not used as evidence; verification/stage-1/ (this verdict, CHECKS.md, scripts/, evidence/) · Command: see "What I ran" · Expected / actual: spec behaviour / matches on all 121 own checks in both runs and 120/120 supplied checks in both modes · Repro: `verification/stage-1/scripts/run_all.sh eb1de488e1d191439f3607f1589d17e4fd0b1d5d <new out dir>` · Next: Architect

## Preconditions
- Repository /home/ubuntu/nightshift-claude-check-tk1/band-work/result, branch main, HEAD = eb1de488e1d191439f3607f1589d17e4fd0b1d5d, working tree clean before and after.
- Handoff spec text (parts 2–3) compared with dark-factory-wearedevs/tablekeeper/spec/stage-1.md: identical.
- Check list (CHECKS.md) and scripts were written from the specification before any check ran and before the Implementer's code or tests were read.

## What I ran (exact commands, real results)
1. `verification/stage-1/scripts/run_all.sh eb1de488e1d191439f3607f1589d17e4fd0b1d5d band-work/checks/ver-own-01`
   - Clean `git clone` + checkout of the revision; `docker build --no-cache` of `stage-1/` only: built in 7 s; no nested `.git`.
   - Container A: `--cpus 2 --memory 2g -e PORT=9321 -p 127.0.0.1:18431:9321`: first `{"status":"ok"}` after 0.34 s; also 200 on its bridge address 172.17.0.2:9321 (listens on 0.0.0.0).
   - Container B: same limits, no `PORT`, mapped to 8080: healthy after 0.34 s (default 8080).
   - Full own list against A (B = second container for cross-container import): **121 passed, 0 failed of 121**; 5,338 requests in 201 s; slowest request 1.29 s; status tally {200: 2528, 201: 565, 204: 143, 400: 550, 401: 99, 404: 357, 405: 45, 409: 630, 422: 421}; zero 5xx; error envelope, content type and time limit held on every response.
   - Containers C and D on a docker `--internal` network (no outbound route), same limits: healthy after 0.12 s / 0.23 s; full list again: **121 passed, 0 failed of 121**, slowest 1.34 s, zero 5xx.
   - After load: A 240 MiB / 2 GiB, C 216 MiB / 2 GiB; all four containers running, OOMKilled=false, restarts=0; container logs empty (no "internal error"). All containers stopped.
2. Supplied checks, host mode: `.venv/bin/python -m harness run --track tablekeeper --repo ../band-work/result --stage 1 --out ../band-work/checks/ver-01` → stage 1 pass, collected 120, passed 120, failed 0, errors 0, skipped 0, deselected 0, xfailed 0; stage 2 fail; `claimed stage: 1`.
3. Supplied checks, isolated mode: same with `--mode isolated --out ../band-work/checks/ver-final-01` → stage 1 pass, 120/120, 0 failed/errors/skipped/deselected; the one warning is pytest failing to write its cache on the read-only test mount (not a check); stage 2 fail; `claimed stage: 1`.
4. RUN.md followed verbatim in the clean clone (`docker build -t tablekeeper-stage1 .` then `docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper-stage1`): `/health` → `{"status": "ok"}` within about 0.7 s; stopped.
5. Read: Dockerfile (python:3.12-slim, `pip install tzdata` at build time only, `CMD python -m app`), RUN.md (build/start command, module table, technology and reasons), app/*.py (stdlib only; no network use at start-up or run time; passwords hashed with `hashlib.scrypt` N=2^13 and random salt, verified with `hmac.compare_digest`; tokens stored as SHA-256 digests; in-memory state under one lock).

## Coverage by section (check ids in CHECKS.md)
§2 delivery/limits A1–A11, B1 · §3 B2–B11 incl. 64/65-character fixture ids and reset atomicity · §4 C2, C5–C8 (seeded bookings, past dates, cutoff on past bookings) · §5 D2, D3, D6, D10–D12, G-ENVELOPE, G-CTYPE, fuzz A8a–c · §6 E1–E12 incl. 50-way same-email signup · §7 F1–F11 incl. key order/whitespace, per-user scope, cross-path same key, reuse after 4xx, 50-way identical key · §8 G1–G12, H1–H13, I1–I16 incl. cutoff tested about one minute either side of the boundary, 280 creations next to 40 seeded references, 50-way races for create, PATCH and cancel-versus-create · §9 J1–J5 (Berlin and New York spring and fall transitions, absolute durations, occupancy across the transitions, four further zones) · §10 K1–K11 (container-to-container import, replacement, double import, replays and failed keys after import, invalid imports leave the destination unchanged, reset after import) · §11 L1–L16 (swap, rotation of three, 1/8/0/9 items, shapes, 404/422/409 codes, stated precedence, atomicity including retry keys, replays after amendment and cancellation, no-op, 50-way identical and conflicting batches) · §1 M1 pairwise non-overlap asserted after every concurrent scenario.

## Next unit and earlier units
The harness stage-2 probe fails in both modes, so the folder does not already satisfy stage 2. There are no earlier units.

## Notes (none blocking)
1. Maintainability: the code is small (about 1,150 lines in 16 modules), the module table in RUN.md matches the files, and validation order is in one place per endpoint. All state sits behind one global lock. That is correct and fast enough at the stated limit (slowest request 1.34 s with 50 in flight on 2 vCPU), but it would serialise work under load beyond the stated limits.
2. `server.py` accepts request bodies up to 64 MiB (`MAX_BODY`) and reads them into memory. No ordinary user sends that much, and the spec sets no body-size limit. At 50 such requests in flight that is about 3.2 GiB, above the 2 GiB memory limit. The figure is given as a note only.
3. If a query parameter is repeated, the first value is used. The specification does not cover this.
4. E8b (note-level check): a stale `Authorization` header on the public endpoints is ignored. It passed.

## Remaining risk I could not test
- The supplied checks are a partial sample. The hidden full suite may probe orderings the spec leaves open (X1/X4/X5 choices).
- The cutoff was tested with the server's real clock about one minute either side of the boundary, not to the second.
- DST was tested only for the transitions §9 lists plus fixed offsets in four other zones.
- Load was tested at exactly 50 in flight, not beyond.
- I did not test a restart of the container, because the specification does not require state to survive one.
