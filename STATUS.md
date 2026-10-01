# Status

Run started: 2026-10-01T01:02Z (dispatch received). Track: pocketful.

| Unit | State | Accepted revision | Elapsed | Notes |
|---|---|---|---|---|
| Stage 1 — payments and settlements (`stage-1/`) | DONE | `506c9b1599075237f13e70488f0e1f38c0dcfa5f` | 0h49m | Verifier PASS on the exact revision. Shipped checks 147/147 in isolated mode, `claimed stage: 1`. One fix round. |

Stages 2–4 are out of scope for this dispatch.

Commits after the accepted revision touch only this file; `stage-1/` is unchanged from `506c9b1`.

## Evidence

- Acceptance map: `ACCEPTANCE-stage-1.md`.
- Final isolated check (Verifier, on `506c9b1`): `band-work/checks/s1-verify-iso-03/report.json` — stage 1 pass, 147 collected, 147 passed, 0 failed/errors/skipped/deselected; stage 2 overshoot suite 0/35; `claimed stage: 1 on the shipped checks`.
- Verifier's own checks on `506c9b1`: `band-work/verify/run3/` — 863/863 spec-derived checks, 36/36 async-race checks, no 5xx.
- Implementer's runs on `506c9b1`: `band-work/checks/s1-impl-02` (host), `band-work/checks/s1-impl-iso-03` (isolated), both 147/147.
- Blocked revision `e414c22`: `band-work/checks/s1-verify-iso-02`, `band-work/verify/run2/`.
- Handoff messages as sent: `band-work/handoff/`.

## Residual risk (Verifier notes on the accepted revision, not findings)

- The shipped suite is only part of the judged suite; the hidden part is untested.
- Login or signup sent while a large distinct-password reset is hashing waits for it (4.2 s at 3000 users, 7.1 s at 5000), which can exceed the 5 s per-request limit; other endpoints stay fast.
- A login in flight across a reset/import state swap returns 401 even with credentials valid in both states.
- Reset of more than roughly 7000 distinct passwords would exceed 10 s under 2 vCPU.
- Fixture users sharing a password share one salt and hash within a reset; scrypt cost is N=1024.

## Log

- 2026-10-01T01:02Z dispatch received; spec read in full.
- 2026-10-01T01:06Z acceptance map committed; six-part handoff to Implementer.
- 2026-10-01T01:11Z Implementer reported `e414c2211a118cf61d5697e73ba9a78aa77ea551` (shipped checks 147/147 host and isolated); handed to Verifier.
- Between 01:11Z and 01:45Z (time not clocked) Verifier BLOCK on `e414c22`: F1 500 on deeply nested unknown field on keyed writes, F2 500 on targets `//`, `/\`, F3 bare 431 on >16 kB headers, F4 derived handle counted UTF-16 units; own checks 859/866. Routed to Implementer with two notes (key length in characters, non-blocking password hashing on reset).
- 2026-10-01T01:45Z Implementer reported `506c9b1599075237f13e70488f0e1f38c0dcfa5f`; handed to Verifier in full.
- 2026-10-01T01:51Z Verifier PASS on `506c9b1`; stage 1 accepted.
