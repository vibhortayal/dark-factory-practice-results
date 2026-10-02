# Status

Run started: 2026-10-02T21:11Z (dispatch). Track: pocketful.

| Unit | State | Accepted revision | BLOCK verdicts | Elapsed | Notes |
|---|---|---|---|---|---|
| stage-1 | DONE | d02b8f6b1eb8e0511b9a7e07f0bb02342d8b5a47 | 2 | 0h42 (21:11-21:53Z) | PASS by Verifier on d02b8f6 (`verification/stage-1/VERDICT-round-3.md` at 1b197a6). Supplied checks, isolated (`../checks/s1-ver-03`): stage 1 pass 147/147, stage-2 overshoot fails, `claimed stage: 1`. Verifier's own list 94/94 plus fresh-container import; Implementer's tests 55 OK. BLOCK #1 on 03b5470 (B1-B4), BLOCK #2 on 38f2970 (B5), all fixed. See notes below. |
| stage-2 | BUILDING | - | 0 | started 21:53Z | Handoff sent to Implementer and Verifier; map: `acceptance/stage-2.md` |
| stage-3 | PLANNED | - | 0 | - | |
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
