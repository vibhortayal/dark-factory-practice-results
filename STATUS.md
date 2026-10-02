# Status

Run started: 2026-10-02T21:11Z (dispatch). Track: pocketful.

| Unit | State | Accepted revision | BLOCK verdicts | Elapsed | Notes |
|---|---|---|---|---|---|
| stage-1 | DONE | d02b8f6b1eb8e0511b9a7e07f0bb02342d8b5a47 | 2 | 0h42 (21:11-21:53Z) | PASS by Verifier on d02b8f6 (`verification/stage-1/VERDICT-round-3.md` at 1b197a6). Supplied checks, isolated (`../checks/s1-ver-03`): stage 1 pass 147/147, stage-2 overshoot fails, `claimed stage: 1`. Verifier's own list 94/94 plus fresh-container import; Implementer's tests 55 OK. BLOCK #1 on 03b5470 (B1-B4), BLOCK #2 on 38f2970 (B5), all fixed. See notes below. |
| stage-2 | DONE | 93f0fbd4e6e0aa2bf5447b080bb99a619542fdaf | 1 | 0h45 (21:53-22:38Z) | PASS by Verifier on 93f0fbd (`verification/stage-2/VERDICT-round-2.md` at 2a99ea0). Supplied checks, isolated (`../checks/s2-ver-02`): stage 1 pass 147/147, stage 2 pass 35/35, stage-3 overshoot fails, `claimed stage: 2`. Verifier's lists: API 113/113, browser 22/22 (375 and 1280 px, incl. upgrade from the stage-1 container), probes 95/95 and 17/17; 20,000 authorizations with exact lifetimes. Implementer's tests 88 OK. BLOCK #1 on 1e2214f (B1 expires_at one second short) fixed via map row K6. |
| stage-3 | BUILDING | - | 0 | started 22:40Z | Handoff sent to Implementer and Verifier; map: `acceptance/stage-3.md` |
| stage-4 | PLANNED | - | 0 | - | |

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
