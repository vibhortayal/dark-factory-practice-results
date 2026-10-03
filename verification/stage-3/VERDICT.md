# Verdict — Pocketful stage 3 — PASS

Rows: all of acceptance/stage-3.md (V1-AC6), acceptance/stage-2.md (K1-U4) and acceptance/stage-1.md (A1-J6) ·
Revision: 3a39ddfe0133dcd7549962943c8fa4c53fa07315 · Files: stage-3/ inspected; verification/stage-3/ written ·
Command: deliver3.py (checks3.py + ui.py), harness --stage 3 normal and --mode isolated, Implementer's tests, RUN.md verbatim ·
Expected / actual: no difference found · Repro: n/a · Next: Implementer reports the revision to the Architect.

**PASS** for revision 3a39ddfe0133dcd7549962943c8fa4c53fa07315.

## What was run

Tree clean at the revision before and after. `CHECKS.md` was written before any stage-3 revision existed.

| Run | Result |
|---|---|
| deliver3.py delivery checks | 13 of 13 passed: `git diff 172a3180 -- stage-1` and `git diff c59be33b -- stage-2` empty; clean `docker build --no-cache`; port 8080 by default and `-e PORT`; `--network none`; healthy within 0.44 s under 2 vCPU / 2 GiB; no OOM |
| checks3.py: stage-1 list + stage-2 API list unchanged + 13 stage-3 checks, limited containers on an internal network, upgrade exports taken from real stage-1 and stage-2 containers | 86 of 86 passed, 5048 requests, 0 responses >= 500, 0 transport errors |
| ui.py: stage-2 browser list unchanged against stage-3, 15 checks x 375 and 1280 px | 30 of 30 passed |
| Supplied `--stage 3 --out ../band-work/checks/verifier-s3-r1` | stage 1, 2, 3: pass (stage 4: fail, not built) |
| Supplied `--mode isolated --out ../band-work/checks/verifier-s3-r1-isolated` | stage 1, 2, 3: pass |
| Implementer's tests in a `git archive` copy | API 116 OK (1 skipped: browser suite without Playwright); browser 24 OK |
| RUN.md verbatim: `docker build -t pocketful-stage-3 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage-3` | built, `/health` ok |

Measured at the stated limits: 50 in flight mixing statements, historical `/me`, revisions, corrections and payments —
slowest 0.037 s; reset of 60 users 0.587 s.

Stage-3 behaviour checked from the specification: seeded and API `created_at`; future seeded `created_at` 422;
opening balances; `as_of` boundaries (exactly at, 1 s / 1 µs before), offsets and echo; `known_at` selection before,
between and after revisions; statement window `[from, to)`, order, ties by payment id, balances, paging against the
one-shot result; snapshot tokens after later payments, corrections and hold actions, and their 404/422 cases;
correction rules, validation boundaries, effects on the two wallets, replay, stale revision, 20-way races;
`insufficient_funds` before `historical_overdraft`, same-instant boundaries, overdraft through hold history; linked
payments immutable; `closed_at` and the hold timeline under (T, K); import of real stage-1 and stage-2 exports and the
stage-3 round trip; sums equal to the seeded total in every view tried.

V4 next-unit check: the stage-4 endpoints (`POST /payments/{id}/refunds`, `POST /correction-batches`) do not exist in
`app/router.py`, and no refund or batch code exists in stage-3/app. The UI files are identical to stage-2's.

## Findings

None blocking.

## Notes (do not block)

1. Snapshot tokens are kept in memory with a bound: the oldest are dropped beyond 5000 snapshots or 300 000 stored
   entries (`handlers/statement.py`). The specification says tokens last until reset and states no limit on stored
   records; a dropped token would answer 404. Figure: more than 5000 statement reads between two resets.
2. An instant written with an unencoded `+` (which a query string decodes to a space) is accepted and treated as the
   offset sign; the specification's example uses `%2B`. Lenient reading, not specified.
3. `GET /statement` with `from` after `to` is 422 (Implementer's choice; the specification is silent).
4. On import of a stage-1/2 export a voided authorization has no recorded void time and is reconstructed as having held
   nothing; the specification says closed holds "need not reconstruct a prior lifecycle" for seeds and is silent for imports.
5. Carried from earlier stages, unchanged: settlement entry with a non-string handle 422; `/_test/import` with a
   non-object JSON body 422; zero-amount split request pays as a 0 payment; capture past `expires_at` answers
   `authorization_expired`.
6. Maintainability: `history.py` is a small, well-described module (views over opening balance + selected revisions;
   hold reconstruction). Historical reads cost O(user's payments + all authorizations) per request and the overdraft
   check walks boundaries; fine at the sizes tested (40-60 payments per user), not measured beyond. State stays in memory.

## Remaining risk I could not test

- The harness ships only part of the judging tests.
- Histories larger than a few hundred payments per user and long runs were not measured.
- Timing was measured on this host, not the judge's.
