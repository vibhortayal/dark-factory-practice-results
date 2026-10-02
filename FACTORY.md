# Nightshift Dark Factory

Seats: Nightshift Architect (Claude Code, claude-opus-5-5), Nightshift Implementer
(Claude Code, claude-sonnet-5-5), Nightshift Verifier (Claude Code, claude-opus-5-5).
Mandates: mandates/. This file is completed by the team after the run with measured
results, timings, costs and failures.

## How the factory worked in this run

One human message started the run (2026-10-02T04:11Z); no further human input was used.

1. The Architect read each stage's specification, wrote an acceptance map
   (`acceptance/stage-N.md`: every requirement, rejection and boundary with how it is checked,
   plus recorded decisions where the specification is silent) and handed the unit to both other
   seats with the complete task, specifications and maps pasted into the room.
2. The Implementer built the stage folder (copying the previous accepted folder forward), wrote
   its own tests from the specification, ran them and the supplied checks, committed, and handed
   over the exact revision.
3. The Verifier prepared its own check list from the specification before the revision existed,
   then ran the supplied checks in isolated mode, a clean-clone build, its own list under the
   stated limits (2 vCPU, 2 GiB, 50 in flight, no outbound network) and one timed hardening pass,
   and returned PASS or BLOCK for that exact revision.
4. On BLOCK the Architect routed the findings back with direction to fix the kind of fault, and
   the loop repeated (at most five rounds per unit). A unit was accepted only on a Verifier PASS
   for the head revision with no Blocker, Severity 1 or Severity 2 finding open.

State, verdicts, notes and times are in `STATUS.md`. Check outputs are outside this repository in
`../checks/` (`sN-impl-*` by the Implementer, `sN-ver-*` by the Verifier).

## Measured results

| Stage | Accepted revision | BLOCK verdicts | Elapsed | Supplied checks, isolated, at acceptance | Verifier's own checks at acceptance |
|---|---|---|---|---|---|
| 1 | 43ecb3c9d24e89b47ea00c98828bf3999bb0a5cc | 3 | 1 h 46 min | 147/147 (`s1-ver-04`) | 900/900 |
| 2 | 4a9c357bc8cc5c71df5634b15dd9527f145be2d5 | 2 | 3 h 46 min | 147/147, 35/35 (`s2-ver-03`) | 1,441/1,441 |
| 3 | 532accd6430b55a8e3ebce7b02752bfbed4e641b | 0 | 1 h 59 min | 147/147, 35/35, 6/6 (`s3-ver-01`) | 1,689/1,689 |
| 4 | 3df8b93d1e3de4b31ccb837f6f253d676dfd6b00 | 1 | 3 h 48 min | 147/147, 35/35, 6/6, 5/5 (`s4-ver-02`) | 1,902/1,902 |

Whole submission at 3df8b93, `harness run --all --mode isolated` (`../checks/s4-ver-all-02`):
`stage-1/` claims stage 1, `stage-2/` claims stage 2, `stage-3/` claims stage 3, `stage-4/` claims
stage 4; each earlier folder fails the next stage's probe. Total elapsed 11 h 19 min
(04:11Z to 15:30Z). The supplied checks are a sample of the graded suites (stage 1 about 79%,
stage 2 about 35%, stage 3 about 9%, stage 4 about 16%), so these results do not predict the
graded outcome.

Costs: token and money costs were not measured by the seats and are not recorded here.

## Failures during the run (all fixed before acceptance)

- Stage 1, BLOCK 1 (8 findings): HTML 501 on HEAD/OPTIONS, 500s on very long numbers, deep
  bodies and malformed targets, non-integral amounts such as 0.99999999999999999999 accepted,
  import accepting invalid state.
- Stage 1, BLOCK 2 (4 findings in the code changed by round 1): 500 on 19-digit exponents, replay
  lost after export/import for non-integer numbers in ignored fields, own export refused after a
  deeply nested body, control characters accepted in emails.
- Stage 1, BLOCK 3 (1 finding): import accepted a stored response holding a non-integer number,
  after which export returned 500.
- Stage 2, BLOCK 1 (1 finding): the pages threw a script error when answered by the stage-1
  service (the pre-upgrade situation).
- Stage 2, BLOCK 2 (1 finding): a delayed page-load read overwrote a later refresh.
- Stage 4, BLOCK 1 (1 finding): import accepted a stored batch response with an invalid batch id.

Pattern: four of the six blocks concerned state entering through import or reads the client did
not control; each was closed by replacing the mechanism (lexical number handling, whitelisted
plain state proven by a round trip, one stamped gate for reads, one id rule tied to the ledger)
and adding a sweep that tests the kind of fault.

## Known limits of the result

- Severity 4 notes left open by decision are listed in `STATUS.md` (N5, N8, N10, T1, T6, T7, S3-1,
  as-stored replays of earlier-stage requests).
- Where a specification is silent, the services follow the decisions recorded at the end of each
  acceptance map; a graded check that reads such a point differently would fail.
- Every service is one process with in-memory state behind one lock; it was measured up to 5,000
  payments and 50 requests in flight, not beyond, and not over long runs.
- `harness check` reports one problem at the end of the run: `room.json` is missing (a whole-room
  download that the human adds at submission).
