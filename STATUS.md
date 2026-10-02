# Status

Run started: 2026-10-02T03:21Z (dispatch received by the Architect).

| Unit | State | Fix rounds (BLOCK verdicts) | Accepted revision | Elapsed |
|---|---|---|---|---|
| stage-1 (Pocketful payments and settlements) | DONE | 1 of 5 | 6c9781a2d954f9c94e0a3dfca4dc563a93aabf4a | 43 min (03:21Z to PASS at 04:04Z) |

Later stages were not requested and are not started.

Commits after the accepted revision touch only `STATUS.md` and `FACTORY.md`;
`git diff 6c9781a2d954f9c94e0a3dfca4dc563a93aabf4a..HEAD -- stage-1` is empty.

Acceptance map: `acceptance/stage-1.md`. Handoff text: `handoffs/` and
`../checks/architect-handoffs/` (verification handoffs and the fix request, kept outside the
repository so that HEAD does not move while a revision is under verification).
Check output: `../checks/`. Verifier's check list, scripts and logs: `../verifier/`.

## Log

- 03:21Z dispatch received; spec and supplied tests read.
- 03:25Z acceptance map committed (7ca25ed); handoff sent to Implementer and Verifier.
- 03:32Z Implementer committed dd93fa45a4c6e73f64b586f0262a018e2f574172; handed to Verifier 03:34Z.
- 03:53Z Verifier: BLOCK #1 on dd93fa4. Supplied checks 147/147 in host and isolated mode
  (`../checks/s1-ver-01`, `s1-ver-02`), Verifier list 489/489, two Severity 2 findings from
  hardening, both in import validation (rows H04, A05, D06):
  - F1: import accepted an id counter of 2^53; the next id allocation looped forever and
    the service hung.
  - F2: import accepted password hashes the service could not verify (bad scrypt
    parameters, zero-length key); login then gave 400, or 200 for any password.
- 03:55Z findings and note N1 routed to the Implementer.
- 03:56Z Implementer committed 6c9781a2d954f9c94e0a3dfca4dc563a93aabf4a; handed to Verifier 03:59Z.
- 04:04Z Verifier: PASS on 6c9781a (HEAD, tree clean). Supplied checks 147/147 in host mode
  (`../checks/s1-ver-03`) and isolated mode (`../checks/s1-ver-04`); Verifier list 540/540
  (489 from round 1 plus 51 for the changed code), two containers under 2 vCPU / 2 GiB on an
  internal network; F1 and F2 reproductions now give 422 and the service stays healthy;
  Implementer's suite 18/18 on a clean clone without network. Unit accepted.

## Verifier notes (Severity 3 and 4) at the accepted revision

Open:
- N1 (Severity 3, rows A05/H08): reset time on large fixtures. Improved, still open at larger
  sizes: 600 users sharing a password 0.06 s; 600 users with distinct passwords 2.30 s;
  2000 distinct 7.88 s; it would pass the 10 s limit near 2500 distinct passwords (supplied
  fixtures have 4 users, row A05 uses 50). Work for the next unit's folder if one is built.
- N2 (Severity 4), remainder: a signup overlapping a reset lands in the post-reset state
  (the login case is fixed). The spec does not speak to it.
- N5 (Severity 4): bodies over 16 MiB give 413 `payload_too_large`, a code outside the
  spec's table.
- N6 (Severity 4): within one reset, users sharing a password share the scrypt salt, which
  is visible in the export, so the export shows which accounts have equal passwords; scrypt
  cost dropped from N=8192 to N=2048. Stored values differ per user; no plaintext.
- N7 (Severity 4): `newId` throws (a 500) if a counter passes 2×10^15; import caps counters
  at 10^15, so it is not reachable through accepted input.

Fixed in 6c9781a: N2 for login, N3 (percent-encoded path on replay), N4 (every RangeError
reported as "too deeply nested").

## Remaining risk stated by the Verifier

The graded suite is larger than the supplied sample. Nothing was tested above 50 requests
in flight or over long runs. Tampered-import checks were added only for the two root causes
and the changed code. Rows marked *(choice)* in the acceptance map pass as the Architect
wrote them; the specification does not confirm those readings.
