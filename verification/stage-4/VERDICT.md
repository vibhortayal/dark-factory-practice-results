# Verdict — Pocketful stage 4 — PASS

Rows: all of acceptance/stage-4.md (AD1-AH4), stage-3.md (V1-AC6, as amended), stage-2.md (K1-U4), stage-1.md (A1-J6) ·
Revision: 2c6b40aa628740f4762aedf73b2a820eccc6f5c1 · Files: stage-4/ inspected; verification/stage-4/ written ·
Command: deliver4.py (checks4.py + ui.py), refund_ui.py, harness --stage 4 normal and --mode isolated, Implementer's tests,
RUN.md verbatim · Expected / actual: no difference found · Repro: n/a · Next: Implementer reports the revision to the Architect.

**PASS** for revision 2c6b40aa628740f4762aedf73b2a820eccc6f5c1.

## What was run

Tree clean at the revision before and after. `CHECKS.md` was written before any stage-4 revision existed.

| Run | Result |
|---|---|
| deliver4.py delivery checks | 14 of 14 passed: `git diff` against 172a3180 / c59be33b / 9dcc200f empty for stage-1 / 2 / 3; clean `docker build --no-cache`; port 8080 by default and `-e PORT`; `--network none`; healthy within 0.44 s under 2 vCPU / 2 GiB; no OOM |
| checks4.py: stage-1, 2 and 3 lists unchanged + 11 stage-4 checks, limited containers on an internal network, upgrade exports from real stage-1, 2 and 3 containers | 98 of 98 passed, 6226 requests, 0 responses >= 500, 0 transport errors |
| ui.py: stage-2 browser list unchanged against stage-4, 15 checks x 375 and 1280 px | 30 of 30 passed |
| refund_ui.py: wallet feed with a refund payment in it, 375 and 1280 px | refund item rendered newest first with `2.50 EUR`, both handles, balance `92.50 EUR`, no horizontal scroll, no script error |
| Supplied `--stage 4 --out ../band-work/checks/verifier-s4-r1` | stages 1, 2, 3, 4: pass; highest contiguous stage 4 |
| Supplied `--mode isolated --out ../band-work/checks/verifier-s4-r1-isolated` | stages 1, 2, 3, 4: pass; highest contiguous stage 4 |
| Implementer's tests in a `git archive` copy | API 146 OK (1 skipped: browser suite without Playwright); browser 24 OK |
| RUN.md verbatim: `docker build -t pocketful-stage-4 . && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage-4` | built, `/health` ok |

Stage-4 behaviour checked from the specification: refund auth, key and amount rules; cumulative limit against the
corrected amount (remaining ok, remaining + 1 refused); refund payment shape, replay, feed and statements; refunds of
request payments, captures and settlement members without reopening anything; funding from available only;
`invalid_refund_target`; corrections refused below the refunded amount; refund races (20 parallel, refund vs reducing
correction, identical keys); batch auth, shape (1 and 32 ok, 0 and 33 refused, duplicates), item validation, immutables,
settlement completeness and identical instants in two offset spellings; batch response, shared `recorded_at`,
`correction_batch_id` in histories; originals, feed, settlement retry and earlier snapshots unchanged; replay; error
precedence in both orders; combined affordability; batch races against batches and single corrections; import of real
stage-1, 2 and 3 exports (snapshot token, revisions, settlement membership, refundable and batch-correctable); the
stage-4 round trip; 50 in flight with refunds and batches.

Scope: this is the last stage. The only UI change from stage 3 is a "Refund" badge in the feed (`feed.js`, 3 lines).

## Findings

None blocking.

## Notes (do not block)

1. The feed shows a small "Refund" badge on refund payments. The specification asks for no UI change in stage 4 and
   forbids none; the Architect's recorded choice says refunds "render as ordinary payments". All required testids and
   texts are unchanged.
2. Fixtures may carry `refund_of` on seeded payments (Implementer's extension; the specification does not describe it).
3. Carried from stage 3, unchanged: snapshot memory bound of 50 000 snapshots / 600 000 rows (oldest dropped beyond);
   export grows with statement reads; an unencoded `+` in an instant is accepted; statement `from` after `to` is 422;
   legacy voided authorizations import as having held nothing.
4. Carried from stages 1-2, unchanged: settlement entry with a non-string handle 422; `/_test/import` with a non-object
   JSON body 422; zero-amount split request pays as a 0 payment; capture past `expires_at` answers `authorization_expired`.
5. Maintainability: stage-4 additions are small (`handlers/batches.py`, refund handler, shared field parsing with single
   corrections); the batch applies all revisions and sweeps history for the affected wallets, rolling back on failure.
   Historical work stays O(user's payments + all authorizations) per affected wallet; state is in memory.

## Remaining risk I could not test

- The harness ships only part of the judging tests.
- Large histories, many snapshots and long runs were not measured.
- Timing was measured on this host, not the judge's; only Chromium was used for the UI.
