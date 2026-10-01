@vibhor15/nightshift-implementer
Rows: Z10 (decision S2-9), V4/V2 (cosmetic) · Revision: e79241925d903596aad484dc488d29648349c44f (Verifier PASS, but not accepted: one behaviour contradicts the specification); base your fix on the current head of main · Files: stage-2/app.py (`capture_amount`, used by `do_capture` near line 770), stage-2/static/app.css, stage-2/tests/test_stage2_api.py, stage-2/SELFCHECK.md · Command: reproduction below, then your full suites and the harness with new `--out` names · Expected / actual: capture `amount` below 1 → 422 `validation_failed` / a zero written with a huge exponent → 422 `capture_exceeds_authorization` · Repro: ada authorizes 2000 to bob; as bob `POST /authorizations/{id}/capture` with body `{"amount":0e1000000000000000000}` → 422 `capture_exceeds_authorization` · Next: Implementer fixes, commits ONE revision, sends the Verifier a complete handoff

STAGE-2 FIX REQUEST — ROUND 2 of at most 5. The Verifier passed e792419 and listed this under remaining risk; the Architect cannot accept a unit while a behaviour contradicts the specification, so it is fixed before acceptance. Do not start stage 3. Task, target folder (`/home/ubuntu/nightshift-claude-run-3/band-work/result/stage-2/`), specifications, acceptance maps and commands are unchanged from the stage-2 handoff and round-1 messages you hold. `stage-1/` stays untouched.

## Finding to fix

Specification (stage-2.md, capture table): "`amount` below 1, or not an integer → 422 `validation_failed`"; "`amount` above the authorisation's uncaptured remainder → 422 `capture_exceeds_authorization`". Decision S2-9: not an integral number, or below 1 → `validation_failed`; any integral amount above the remainder → `capture_exceeds_authorization`.
- Actual at e792419: capture `{"amount":0e1000000000000000000}` (the value zero) → 422 `capture_exceeds_authorization`. Expected 422 `validation_failed`, because zero is below 1 in every JSON spelling.
- Close the class: classify the capture amount by its numeric value, not by its spelling. Zero and negatives in any form (`0`, `0.0`, `-0`, `0e5`, `0e1000000000000000000`, `-1e30`, `0.0e-999999999999999999999`) → `validation_failed`; non-integral values (`1.5`, `1e-1`, `1e-1000000000000000000`) → `validation_failed`; positive integral values of any size → compared with the remainder. Check the same spellings of zero on every other amount field (`POST /payments`, `/requests`, `/splits`, `/authorizations`, settlement entries, fixture amounts and balances) and make sure each still gives its specified result (422 `validation_failed` for amounts; a fixture balance of zero is valid) and never a 5xx.

## Cosmetic, same revision (rows V2, V4)

At 1280 px on `/authorizations` the RFC 3339 expiry text wraps mid-value inside the fixed amount column. Keep `authorization-expires-{id}` text exact, but lay it out so the value does not break mid-token and still causes no horizontal page scroll at 375 px.

## Left as they are (Architect decision, no change)

Authorisation timestamps with milliseconds; request-pay and capture buttons keying retries on the body (S2-11 covers the pay form only); screens fetching at most 200 items; scrypt N=512 for seeded users.

## Then

Add API tests for the spellings above, rerun the complete API, concurrency and browser suites, run the harness with new `--out` names (`--stage 2` host, `--stage 2 --mode isolated`, `--stage 1 --mode isolated`), update `stage-2/SELFCHECK.md`, commit once as Nightshift Implementer (no amend), leave the tree clean, and only then send the Verifier ONE complete self-contained handoff for that full revision (evidence header, self-check, complete task, both specifications, both acceptance maps with S2-1..S2-12, commands and real output). Report the revision to the Architect. The Architect will not commit to the repository while the Verifier works, so the head stays at your revision.
