<!-- archive-note -->
> **This is the run Team Nightshift submitted.** Its public repository is `vibhortayal/nightshift-pocketful`.

## 20. Run 7: the submitted run (Oct 2, all four stages)

- **What changed from the previous run:** Nothing. The text tested in runs 18 and 19.
- **Why:** The entry: one dispatch, no human help.
- **Result:** Clean. All four stages accepted in 2 h 27 min, 4 BLOCK verdicts, about $59.
- **Conclusion:** This is the submitted run.
- **What we did next:** Confirmed the factory on the other track at full length (run 21), and tested background tasks once more (run 22).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

The whole sequence of runs is on the `main` branch of this repository.

Below this line: the run's own text, unchanged.

---

# Nightshift Dark Factory

Seats: Nightshift Architect (Claude Code, claude-opus-5-5), Nightshift Implementer
(Claude Code, claude-sonnet-5-5), Nightshift Verifier (Claude Code, claude-opus-5-5).
Mandates: mandates/.

## How the factory works

- One human dispatch (track pocketful, four stages) and no human input after it.
- The Architect reads each stage specification in full and writes an acceptance map
  (`acceptance/stage-N.md`): every requirement, rejection case and boundary, each with how it
  is checked. Where the specification is open, the map records the Architect's choice as a
  **[reading]** row with its reason.
- The Architect hands the task, every specification in force and every map, verbatim in numbered
  parts, to the Implementer and the Verifier at once. The Implementer builds while the Verifier
  derives its own check list from the specification, before seeing any code.
- The Implementer copies the previous accepted stage folder forward, extends it, self-checks every
  map row, commits, and hands the exact revision to the Verifier.
- The Verifier builds from a clean export, runs the supplied harness in isolated mode, reruns its
  saved lists for every earlier stage, adds checks for changed code, commits its list and verdict
  under `verification/stage-N/`, and returns one verdict: PASS, BLOCK or INCONCLUSIVE.
- The Architect accepts a stage only on PASS for the exact revision that last changed the folder,
  routes BLOCK findings back as fix requests (asking for the class of fault, not the single case),
  and changes the map in one message to both seats when a finding shows a reading was wrong or
  missing. At most five BLOCK rounds per stage. Status in `STATUS.md`.

## Measured results (run of 2026-10-02, 21:11-23:38 UTC, 2 h 27 min)

| Stage | Accepted revision | BLOCK rounds | Time | Supplied checks, isolated | Verifier's own list |
|---|---|---|---|---|---|
| 1 | d02b8f6 | 2 | 42 min | suite 1 147/147; claimed 1 | 94/94 API |
| 2 | 93f0fbd | 1 | 45 min | suites 1-2 147/147, 35/35; claimed 2 | 113/113 API, 22/22 browser |
| 3 | cfff6f7 | 1 | 32 min | suites 1-3 147/147, 35/35, 6/6; claimed 3 | 129/129 API, 22/22 browser |
| 4 | dec2ad6 | 0 | 25 min | suites 1-4 147/147, 35/35, 6/6, 5/5; claimed 4 | 144/144 API, 22/22 browser |

`harness run --all --mode isolated` (Verifier, `s4-ver-all-01`): every folder claims its own stage.
The shipped checks are only part of the judged tests.

## Failures found and how they were handled

- Stage 1, BLOCK 1: four inputs beyond stated limits gave 500/400/431 (wrong-typed fixture ids,
  4301-digit `limit` and `amount`, a 65520-character idempotency key). Fixed by type-checking
  fixture values, bounded number parsing and JSON error bodies for HTTP-layer refusals.
- Stage 1, BLOCK 2: the round-1 fix regressed a malformed absolute request target into a 500.
  Fixed by splitting request handling into a decode phase (any failure is 400) and a dispatch phase.
- Stage 2, BLOCK 1: `expires_at` was one second short about once in 16,000 creations (two clock
  reads, each rounded). The Architect changed the reading (row K6): one clock read per request,
  microsecond fixed-width timestamps, never going backwards.
- Stage 3, BLOCK 1: a hold seeded as `expired` with a future `expires_at` was counted as held in
  historical views; the Architect's own row V7 had been ambiguous and was clarified.
- Twice a fix request crossed with a narrower fix the Implementer had already committed; the
  Architect sent an ordering note so that no revision under verification was replaced.

## Costs

Token and money costs were not measured by the seats during the run; they are available only from
the Band/Claude account usage records.
