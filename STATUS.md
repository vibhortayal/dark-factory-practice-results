# Status

Run started: 2026-10-03T19:42Z. Track: pocketful.

| Unit | State | Accepted revision | BLOCK rounds | Elapsed | Notes |
|---|---|---|---|---|---|
| stage-1 | DONE | 172a3180c731a310e00e403ea1c4990a4a78b5d4 | 0 | 19:43Z–20:02Z (19 min) | Verifier PASS, verdict commit 7a52d057; map `acceptance/stage-1.md` |
| stage-2 | BUILDING | — | 0 | started 20:05Z | map `acceptance/stage-2.md` |
| stage-3 | PLANNED | — | 0 | — | |
| stage-4 | PLANNED | — | 0 | — | |

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
