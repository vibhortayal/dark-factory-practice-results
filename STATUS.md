# Status

Run started: 2026-10-02T03:21Z (dispatch received by the Architect).

| Unit | State | Fix rounds (BLOCK verdicts) | Accepted revision | Elapsed |
|---|---|---|---|---|
| stage-1 (Pocketful payments and settlements) | BUILDING (fix round 1) | 1 of 5 | none | 33 min at 03:54Z |

Acceptance map: `acceptance/stage-1.md`. Handoff text: `handoffs/` and
`../checks/architect-handoffs/` (verification handoffs, kept outside the repository so
that HEAD does not move while a revision is under verification).
Check output: `../checks/`. Verifier's check list and scripts: `../verifier/s1/`.

## Log

- 03:21Z dispatch received; spec and supplied tests read.
- 03:25Z acceptance map committed (7ca25ed); handoff sent to Implementer and Verifier.
- 03:32Z Implementer committed dd93fa45a4c6e73f64b586f0262a018e2f574172; handed to Verifier 03:34Z.
- 03:53Z Verifier: BLOCK #1 on dd93fa4. Supplied checks 147/147 in host and isolated mode
  (`../checks/s1-ver-01`, `s1-ver-02`), Verifier list 489/489, two Severity 2 findings from
  hardening, both in import validation (rows H04, A05, D06):
  - F1: import accepts an id counter of 2^53; the next id allocation loops forever and the
    service hangs.
  - F2: import accepts password hashes the service cannot verify (bad scrypt parameters,
    zero-length key); login then gives 400, or 200 for any password.
- 03:55Z findings and note N1 routed to the Implementer.

## Verifier notes (Severity 3 and 4), revision dd93fa4

- N1 (Severity 3, A05/H08): reset costs about 15.6 ms per user (one scrypt hash each);
  passes 10 s at roughly 640 users (50 users: 0.76 s). Routed as work for the fix revision.
- N2 (Severity 4): a login overlapping an in-flight reset gets 401 even when the account is
  the same before and after; a signup overlapping a reset lands in the post-reset state.
- N3 (Severity 4): idempotency scope uses the raw path, so a replay through a
  percent-encoded form of the same path is not recognised as a replay.
- N4 (Severity 4): every RangeError is reported as 400 "request too deeply nested".
- N5 (Severity 4): bodies over 16 MiB give 413 `payload_too_large`, a code outside the
  spec's table.
