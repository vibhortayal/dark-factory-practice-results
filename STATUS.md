# Status

Run started: 2026-10-03T19:42Z. Track: pocketful.

| Unit | State | Accepted revision | BLOCK rounds | Elapsed | Notes |
|---|---|---|---|---|---|
| stage-1 | DONE | 172a3180c731a310e00e403ea1c4990a4a78b5d4 | 0 | 19:43Z–20:02Z (19 min) | Verifier PASS, verdict commit 7a52d057; map `acceptance/stage-1.md` |
| stage-2 | DONE | c59be33b9aaed102d1728cf7f6d9df7a2e0f571f | 1 | 20:05Z–20:47Z (42 min) | BLOCK #1 on 60a459ae (verdict commit 0c88a232, collapsed Requests/Holds layout, rows Q1/Q3/Q4); PASS on c59be33b (verdict commit 65ec9d11); map `acceptance/stage-2.md` |
| stage-3 | DONE | 9dcc200f61001f800d2aa8248df03da636f36c0f | 0 | 20:50Z–21:37Z (47 min) | PASS on 3a39ddfe (verdict commit f17eadc9) superseded after the Architect amended map rows AA4/AB4 (snapshots must survive export/import); PASS on 9dcc200f (verdict commit 3d12cdd2); map `acceptance/stage-3.md` |
| stage-4 | DONE | 2c6b40aa628740f4762aedf73b2a820eccc6f5c1 | 0 | 21:38Z–21:43Z handoff to PASS (see commit times) | PASS on 2c6b40aa (verdict commit c5bfb0ad); map `acceptance/stage-4.md` |

Run finished 2026-10-03T21:43Z (about 2 h 1 min after the 19:42Z dispatch). Nothing blocked. Final check by the
Architect: `harness run --track pocketful --repo ../band-work/result --all --mode isolated --out
../band-work/checks/architect-final-all-isolated` → every folder claims its stage, highest contiguous stage 4.

## Stage 1 — Verifier verdict (PASS, revision 172a3180)

Evidence: `verification/stage-1/` (CHECKS.md, checks.py, deliver.py, VERDICT.md, run-1/), harness
output in `../checks/verifier-s1-r1` and `../checks/verifier-s1-r1-isolated`.

- Own delivery checks 10/10; own HTTP checks 58/58 (2883 requests, 0 responses ≥ 500), under
  2 vCPU / 2 GiB on an internal network; 50 in flight, slowest 0.393 s.
- Supplied checks: stage 1 pass, 147/147, host mode and `--mode isolated`.
- Implementer's tests: 60 OK. RUN.md command verified verbatim.
- No stage-2 endpoints present.

Notes (non-blocking), copied from the verdict:

1. Settlement entry with a non-string handle gives 422, not 400; §5 and §11 both fit.
2. `POST /_test/import` with a non-object JSON body gives 422 while other POSTs give 400; both fit §10.
3. Paying a zero-amount split request returns 201 with an `amount: 0` payment (spec silent; recorded choice).
4. Unspecified but consistent: case-insensitive emails; wrong method → 405 `method_not_allowed`;
   non-operator on settlements gets 403 before body/key checks; signup without display_name → 422.
5. Maintainability: small modules, stdlib only. (a) idempotency claim uses the raw path, so `/payments/`
   is a separate claim from `/payments`; (b) scrypt n=4096 is low for production; (c) local
   `__pycache__` can be copied into an image built from the working folder.
6. State and idempotency records are in memory and never pruned; no load beyond stated limits applied.

Remaining risk: hidden judging tests may read the open choices in notes 1, 2, 4 differently; timing
measured on this host only; long-run memory growth not measured.

## Stage 2 — Verifier verdict (PASS, revision c59be33b; round 1 BLOCK on 60a459ae)

Evidence: `verification/stage-2/` (check lists, scripts, VERDICT files, run-1/, run-2/ with measurements
and screenshots), harness output in `../checks/verifier-s2-r2` and `../checks/verifier-s2-r2-isolated`.

- Round-1 finding (request and hold cards 34–264 px wide, summary below the list) fixed: cards 343 px at
  375 px, 657 px at 1280/1920 px; summary above the list on mobile, beside it on desktop.
- Delivery checks 12/12; API list 73/73 (3909 requests, 0 responses ≥ 500); browser list 30/30 at 375 and 1280 px.
- Supplied checks: stage 1 pass, stage 2 pass, host mode and `--mode isolated`.
- Implementer's tests: API 82 OK (1 skipped), browser 24 OK. `git diff 172a3180 -- stage-1` empty.

Notes (non-blocking), copied from the verdict:

1. Carried from stage 1: settlement entry with a non-string handle → 422; import with a non-object body → 422;
   zero-amount split request pays as a 0 payment.
2. Capture of an authorization past `expires_at` or seeded `expired` answers `authorization_expired`
   (the table also lists `authorization_not_open`); matches the recorded choice.
3. `authorization-expires-{id}` shows RFC 3339 text with microseconds for API-created holds.
4. Below 900 px the Holds screen puts the hold form above the list (holds start ~1080 px down at 375 px).
5. Lazy expiry under the global lock, cost proportional to open holds; state in memory and unpruned.

Remaining risk: hidden judging tests; UI quality judging is subjective; only Chromium at 375/768/1280/1920 px;
timing measured on this host.

## Stage 3 — Verifier verdict (PASS, revision 9dcc200f; replaces the PASS on 3a39ddfe)

Evidence: `verification/stage-3/` (CHECKS.md, checks1/2/3.py, ui.py, deliver3.py, VERDICT.md,
VERDICT-round-2.md, run-1/, run-2/), harness output in `../checks/verifier-s3-r2` and
`../checks/verifier-s3-r2-isolated`.

- Amended rows AA4/AB4 met: a snapshot token issued before export pages the identical frozen result after
  import (same container, repeated import, re-export, second container); foreign/late tokens 404.
- Delivery checks 13/13; API list 87/87 (5123 requests, 0 responses ≥ 500), with real stage-1 and stage-2
  exports imported; browser list 30/30 at 375 and 1280 px.
- Supplied checks: stages 1, 2, 3 pass, host mode and `--mode isolated`.
- Implementer's tests: API 120 OK (1 skipped), browser 24 OK. No refund or batch code in stage-3.

Notes (non-blocking), copied from the verdict:

1. Snapshot memory bound 50 000 snapshots or 600 000 stored rows; beyond it the oldest tokens are dropped (404).
2. Export carries every live snapshot, so it grows with statement reads (Implementer measured 400 000 rows:
   0.71 s export, 0.99 s import).
3. An unencoded `+` in an instant is accepted; statement `from` after `to` is 422; legacy voided authorizations
   import as having held nothing; stage-1/2 carry-overs; historical reads cost O(user's payments + all authorizations).

Remaining risk: hidden judging tests; large histories, many snapshots and long runs not measured; host timing only.

## Stage 4 — Verifier verdict (PASS, revision 2c6b40aa)

Evidence: `verification/stage-4/` (CHECKS.md, checks1-4.py, ui.py, deliver4.py, refund_ui.py, VERDICT.md, run-1/),
harness output in `../checks/verifier-s4-r1` and `../checks/verifier-s4-r1-isolated`.

- Delivery checks 14/14 (stage-1/2/3 folders identical to their accepted revisions); API list 98/98
  (6226 requests, 0 responses ≥ 500) with real stage-1/2/3 exports imported; browser list 30/30 at 375 and 1280 px;
  feed with a refund renders cleanly at both widths.
- Supplied checks: stages 1–4 pass, host mode and `--mode isolated`.
- Implementer's tests: API 146 OK (1 skipped), browser 24 OK. RUN.md command verified verbatim.

Notes (non-blocking), copied from the verdict:

1. The feed shows a small "Refund" badge on refund payments (the only UI change from stage 3); the spec asks for
   no UI change and forbids none; required testids and texts unchanged.
2. Fixtures may carry `refund_of` on seeded payments — an extension the spec does not describe.
3. Carried from stage 3: snapshot memory bound 50 000 / 600 000 rows; export grows with statement reads; unencoded
   `+` in an instant accepted; statement `from` after `to` is 422; legacy voided authorizations import as held nothing.
4. Carried from stages 1–2: settlement entry with a non-string handle 422; import with a non-object body 422;
   zero-amount split request pays as a 0 payment; capture past `expires_at` answers `authorization_expired`.
5. Historical work is O(user's payments + all authorizations) per affected wallet; state is in memory.

Remaining risk: hidden judging tests; large histories, many snapshots and long runs not measured; host timing only;
Chromium only for the UI.
