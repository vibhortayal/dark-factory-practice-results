# Status

Run started: 2026-10-02T21:11Z (dispatch). Finished: 2026-10-02T23:38Z (2h27). Track: pocketful. Outcome: all four stages DONE; 4 BLOCK verdicts in total, all fixed; nothing blocked.

| Unit | State | Accepted revision | BLOCK verdicts | Elapsed | Notes |
|---|---|---|---|---|---|
| stage-1 | DONE | d02b8f6b1eb8e0511b9a7e07f0bb02342d8b5a47 | 2 | 0h42 (21:11-21:53Z) | PASS by Verifier on d02b8f6 (`verification/stage-1/VERDICT-round-3.md` at 1b197a6). Supplied checks, isolated (`../checks/s1-ver-03`): stage 1 pass 147/147, stage-2 overshoot fails, `claimed stage: 1`. Verifier's own list 94/94 plus fresh-container import; Implementer's tests 55 OK. BLOCK #1 on 03b5470 (B1-B4), BLOCK #2 on 38f2970 (B5), all fixed. See notes below. |
| stage-2 | DONE | 93f0fbd4e6e0aa2bf5447b080bb99a619542fdaf | 1 | 0h45 (21:53-22:38Z) | PASS by Verifier on 93f0fbd (`verification/stage-2/VERDICT-round-2.md` at 2a99ea0). Supplied checks, isolated (`../checks/s2-ver-02`): stage 1 pass 147/147, stage 2 pass 35/35, stage-3 overshoot fails, `claimed stage: 2`. Verifier's lists: API 113/113, browser 22/22 (375 and 1280 px, incl. upgrade from the stage-1 container), probes 95/95 and 17/17; 20,000 authorizations with exact lifetimes. Implementer's tests 88 OK. BLOCK #1 on 1e2214f (B1 expires_at one second short) fixed via map row K6. |
| stage-3 | DONE | cfff6f7b46744123d0e1a59fd3983e815518fbfb | 1 | 0h32 (22:40-23:12Z) | PASS by Verifier on cfff6f7 (`verification/stage-3/VERDICT-round-2.md` at 3a56a43). Supplied checks, isolated (`../checks/s3-ver-02`): stages 1/2/3 pass 147/35/6, stage-4 overshoot fails, `claimed stage: 3`. Verifier's lists: API 129/129, browser 22/22 incl. upgrade. Implementer's tests 127 OK. BLOCK #1 on 0f569d9 (seeded expired hold with future expires_at counted as held) fixed after map row V7 was clarified. |
| stage-4 | DONE | dec2ad67348efaf4e4440f6a85c12983458bf029 | 0 | 0h25 (23:13-23:38Z) | PASS by Verifier on dec2ad6 at first verdict (`verification/stage-4/VERDICT.md` at d4863d3). Supplied checks, isolated (`../checks/s4-ver-01`): stages 1/2/3/4 pass 147/35/6/5, `claimed stage: 4`. `--all --mode isolated` (`../checks/s4-ver-all-01/summary.json`): each of stage-1..4 claims its own stage, share 1.0. Verifier's lists: API 144/144 (13,962 requests), browser 22/22 incl. upgrade; 40 refund-vs-correction races clean. Implementer's tests 144 OK. |

## Decisions

- Acceptance maps live in `acceptance/stage-N.md`. Rows marked **[reading]** are Architect
  choices where the specification is open, each with its reason.
- Check output goes to `../checks/<name>` (outside this repository), one new directory per run.

## Stage 1 - Verifier's notes on the accepted revision (non-blocking, copied from the PASS verdict)

- N3: scrypt cost N=4096, r=8, p=1 - a password-hashing function, so §6 is met; low by current guidance. No plaintext password in an export.
- N4: with 20,000 stored payments `GET /activity` 7 ms, export 0.33 s (14.4 MB), import 0.47 s, memory 143 MiB; one global lock and list scans; no weakness at that figure.
- N8: `HEAD` on any path gives 405 with headers only; the specification does not speak to HEAD.
- N11: the server closes a connection idle for 30 s; a client idle longer must reconnect. To remember in stage 2 for browsers.
- N12: a two-word request line (`GET /me`) is served as an ordinary request; the specification does not speak to it.
- N7 (maintainability): small one-job modules, RUN.md matches the code; `statecodec.py` (256 lines) has two jobs and is the place to split in stage 2; phase 1 of `server.py` reports any decoding exception as 400; feed/request order relies on insertion order rather than sorting by `created_at`.
- Remaining risk: hidden judged tests are larger than the shipped set; latencies on a slower judge host unmeasured; abrupt restart untested (state need not survive); open points follow the Architect's [reading] rows and could be read differently by hidden tests (order of checks with two errors; shares when the caller is omitted from a split).

## Stage 2 - Verifier's notes on the accepted revision (non-blocking, copied from the PASS verdict)

- N1: every Architect [reading] row checked is met, K6 included.
- N3: `statecheck.py` reads the wall clock directly for the seeded-hold balance rule and the fixture stamp is a separate tick, so a reset uses three instants rather than one; no behaviour found that depends on it.
- N4: funds checks scan every open hold; with 4,000 open holds a payment takes 2 ms; no weakness at that figure.
- N5: contrast measurement skips text on the gradient wallet card (dark text on a pale background by eye); nothing else under 4.5:1.
- N6: untracked, ignored `__pycache__` folders in the working tree of `stage-1/` and `stage-2/`; in neither the revision nor the image.
- N8 (maintainability): one clock module and one entry point (`operation.begin`); every locked handler must call it by convention, not enforced; RUN.md names both.
- N9: scrypt cost unchanged (N=4096, r=8, p=1).
- Remaining risk: hidden tests larger than the shipped set; the hidden upgrade check's mechanism for moving a signed-in browser is unknown (request interception per row L5 was used); timestamps now have six fractional digits (valid RFC 3339, but a hidden check comparing whole-second strings would fail); visual quality judged from Chromium screenshots; latency measured on the same host.

## Stage 3 - Verifier's notes on the accepted revision (non-blocking, copied from the PASS verdict)

- N1: every Architect [reading] row checked is met, V7 as changed included.
- N3: every first statement read stores a snapshot until reset (2,000 reads: 1.7 s, export 0.47 MB); no bound other than reset.
- N5 (maintainability): one history module serves `/me?as_of`, `/statement` and the overdraft check; the closed-hold decision sits in `holds.release_time`; `fixture.py` (219 lines) and `statecheck.py` (176 lines) are the largest modules.
- N6: scrypt cost unchanged (N=4096, r=8, p=1).
- A single cold-start timeout of the first browser page load was seen once in round 1 and not reproduced; it did not occur in round 2.
- Remaining risk: hidden tests larger than the shipped set and many view combinations untested beyond the named boundaries; hidden upgrade-check mechanism unknown; latency measured on the same host.

## Stage 4 - Verifier's notes on the accepted revision (non-blocking, copied from the PASS verdict)

- N1: every Architect [reading] row checked is met (refund of a settlement member has `settlement_id: null`; non-operators get 403 before the key check on batches; `correction_batch_id` null on single corrections; refund and correction check orders).
- N2: a stage-3 snapshot keeps its original payment shape after the upgrade (no `refund_of`), so it pages exactly the frozen stage-3 result; stage-4 snapshots carry `refund_of`.
- N3: two harness service containers from the Implementer's interrupted `--all` run were left running on the host; not part of the result. At acceptance (23:38Z) `docker ps` showed no running containers.
- N4: every first statement read still stores a snapshot until reset; scrypt cost unchanged (N=4096, r=8, p=1).
- N5 (maintainability): one module per new endpoint; corrections and batches share `parse_fields`, `check_target` and `new_revision`, so item rules cannot drift apart.
- Remaining risk: hidden tests larger than the shipped set; hidden upgrade-check mechanism unknown (request interception per row L5 used); latency measured on the same host.
