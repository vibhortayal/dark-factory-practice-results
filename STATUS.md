# Status

Run started: 2026-10-02T02:13Z · Track: pocketful · Acceptance map: `ACCEPTANCE-stage-1.md`

| Unit | State | Accepted revision | Fix rounds (BLOCK verdicts) | Elapsed |
|---|---|---|---|---|
| stage-1 | DONE | `71b1c02add0ab4843ee8acf34b0fd942e14ba266` | 0 | 0h28 |

The accepted revision is the last one that touches `stage-1/`. The commit that records this status
file comes after it and changes only `STATUS.md`.

## Log

- 02:13Z dispatch received; spec read; both seats present in room.
- 02:16Z acceptance map committed (`e9d50b7`); five-part handoff sent to Implementer.
- 02:3xZ Implementer committed `71b1c02` and handed it to the Verifier.
- 02:40Z Verifier verdict PASS for `71b1c02` (first verdict, no BLOCK). Unit accepted.

## Evidence (Verifier, revision 71b1c02, image built `--no-cache` from `git archive`)

- Supplied harness, isolated mode: `band-work/checks/ver-iso1` — stage 1: 147 collected / 147 passed /
  0 failed / 0 errors / 0 skipped / 0 deselected; `claimed_stage: 1`; stage-2 suite 0 of 35 (no overshoot).
- Supplied harness, host mode: `band-work/checks/ver-host1` — 147 / 147.
- Verifier's own list: `band-work/verifier/CHECKS.md`, `checks.py`, `delivery.sh` — 654 checks, 654 passed,
  no 5xx, max latency 0.376 s, at 2 CPU / 2 GiB, 50 in flight. Output in `band-work/verifier/*.out`.
- Implementer's suite `stage-1/tests/test_stage1.py`: 53 tests OK. Implementer's isolated run:
  `band-work/checks/iso1`.
- Delivery: RUN.md command works literally; `--network none` works; first healthy response 0.54 s.

## Verifier notes (do not block; copied from the PASS verdict)

Severity 3:

- S3-1 (E11, R5): an unknown body field nested 1500–3000 arrays deep gives 500 on `POST /payments`,
  `/requests/{id}/pay`, `/settlements` (`normalize()` recursion limit). 900 deep is fine.
- S3-2 (X3, E11): an import whose `state` has an extra key nested 600 deep gives 500 (deepcopy outside
  the guarded block); state unchanged. Not an export this service produces.
- S3-3 (E1, E11): `OPTIONS`, `TRACE` or an unknown method returns stdlib `501` with an HTML body
  instead of the JSON error body.
- S3-4 (E11, R3): a request in flight while `/_test/reset` swaps to a fixture with different user ids
  can return 500 (3 in about 22,000 requests over 195 resets).
- S3-5 (E10): `Idempotency-Key` length is counted in bytes, so 150 non-ASCII characters is 422; a
  5000-digit integer `amount` is 400 rather than 422.

Severity 4:

- S4-1: wrong method on a known path is 405 `method_not_allowed`, a code not in the §5 table.
  Architect decision: stands; §5 lists no code for this case and the response carries the required
  error body.
- S4-2: in `POST /settlements` a non-string `from_handle`/`to_handle` gives 422 `validation_failed`.
  Architect decision: the 422 reading stands, because §11 "malformed batch shape is 422
  `validation_failed`" is the endpoint-specific statement; recorded decision 6 applies to the
  single-payment endpoints. The supplied checks do not decide it.
- S4-3: scrypt runs with n=2048, r=8, p=1, a low work factor (§6 only names the function family).
- S4-4: HEAD requests get a body; timestamps are second precision and list order relies on insertion order.

Remaining risk stated by the Verifier: the supplied checks are only a portion of the judging tests;
not run were loads above 50 in flight, soaks beyond 2000 writes, fixtures above 1000 users, and a
different host.
