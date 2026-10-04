<!-- archive-note -->
> **Not a submission run.** This is one of Team Nightshift's practice runs, rehearsals or tests. The submitted run is Run 7, branch `runs/20-2026-10-02-run-7-submitted`.

## 06. Run 3 (Oct 1, all four stages)

- **What changed from the previous run:** The Run 2 lessons above, all in the mandates.
- **Why:** To get a clean four-stage run with a stricter check.
- **Result:** All four stages accepted, but the Verifier's stage-3 pass was never posted: a background task failed, despite the written rule. The factory waited 4 h 37 min until the Verifier was restarted.
- **Conclusion:** A written rule is not enforcement. The background-task failure had to be removed at the source.
- **What we did next:** Switched background tasks off in the seats' settings, and tried shorter handoff messages on stage 1 first (runs 07 to 09).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

The whole sequence of runs is on the `main` branch of this repository.

Below this line: the run's own text, unchanged.

---

# Nightshift Dark Factory

Seats: Nightshift Architect (Claude Code, claude-opus-5-5), Nightshift Implementer
(Claude Code, claude-sonnet-5-5), Nightshift Verifier (Claude Code, claude-opus-5-5).
Mandates: mandates/. This file is completed by the team after the run with measured
results, timings, costs and failures.

## How the factory worked in this run

One human message dispatched the run (2026-10-01T06:35Z). No further human input was used.

1. The Architect read each stage specification and wrote an acceptance map
   (`acceptance/stage-N.md`): every requirement, rejection case and boundary with how it is
   checked, plus the Architect's recorded readings where the specification is silent
   (Q1-Q8, S2-1..S2-12, S3-1..S3-13, S4-1..S4-9).
2. The Implementer received the complete task, specification text and map (`handoffs/`),
   built the stage in its own folder, wrote its own tests and a row-by-row `SELFCHECK.md`,
   and committed one revision.
3. The Verifier built that exact revision from `git archive`, derived its own checks from the
   specification, ran the supplied harness in host and isolated mode on a disposable clone,
   and returned PASS, BLOCK or INCONCLUSIVE.
4. The Architect accepted a stage only on a Verifier PASS for the revision at the head of the
   repository and with no behaviour contradicting the specification open; otherwise it sent
   a fix request. Each next stage started from a copy of the accepted folder.

State of each unit: `STATUS.md`. Check outputs: `band-work/checks/` (outside this repository).

## Measured results

| Stage | Accepted revision | Fix rounds | Supplied checks at acceptance (isolated) | Wall-clock |
|---|---|---|---|---|
| 1 | 8e4365295e6a47665793e0b2d7d9f6be6e7ff1eb | 1 | 147/147, `claimed stage: 1` | 0h35 |
| 2 | f8086da438d3fa7dd38c886decd4ed4a2b8c9dd8 | 2 | 147/147 + 35/35, `claimed stage: 2` | 1h14 |
| 3 | c00530dd77a2caff402419f3c01c2a48a0368148 | 1 | 147/147 + 35/35 + 6/6, `claimed stage: 3` | 6h29 (about 5 h of it waiting for a verdict message that did not arrive; the Verifier reran and re-sent) |
| 4 | 3bbde0be36ec1c397ee89f5c9006383c628d1fc6 | 0 | 147/147 + 35/35 + 6/6 + 5/5, `claimed stage: 4` | 0h47 |

Whole submission at 3bbde0b, `harness run --all --mode isolated`
(`band-work/checks/s4-verifier-3bbde0b-all-01`): `stage-1/` claims 1, `stage-2/` claims 2,
`stage-3/` claims 3, `stage-4/` claims 4; no skipped, deselected or errored checks; no overshoot.

The supplied suites are a sample (stage 3: 6 checks, stage 4: 5 checks). Beyond them the
Verifier ran its own specification-derived checks per stage (functional, fuzz, concurrency with
50 requests in flight, export/import across containers, upgrade from real earlier-stage
containers, browser checks at 375 and 1280 px); counts are in the verdict messages summarised
in `STATUS.md`. Total run: 9h05 wall-clock.

## Failures and what they cost

- Stage 1, round 1 (BLOCK): 5xx on malformed input (huge JSON exponents, unknown HTTP methods,
  lone surrogates, bad request target, tampered import state); integral-float fixture amounts
  rejected. Fixed in one round.
- Stage 2, round 1 (BLOCK): wrong error code for capture amounts above 1e9; a select without a
  visible label; Architect readings added mid-round (authorise form on both routes, decimal
  input forms, retry identity as typed text). Three handed-off revisions were superseded
  because fix requests and commits crossed within seconds. Round 2: a zero capture amount in
  exponent spelling returned the wrong code; found by the Verifier as a risk note, treated by
  the Architect as a specification contradiction and fixed before acceptance.
- Stage 3, round 1 (BLOCK): the service could not import its own export above 8 MiB. One
  revision superseded (INCONCLUSIVE, no checks run) for the same crossing reason. One Verifier
  verdict message never reached the room; the run idled about five hours until the rerun.
- Stage 4: accepted on the first revision.

## Known limits (accepted risks, none contradicts the specification at the sizes tested)

- `stage-1/` and `stage-2/` keep an 8 MiB request-body limit; verified importing a
  20000-payment + 20000-request state. `stage-3/` and `stage-4/` accept 512 MiB on the
  test-control endpoints and round-trip 60000 + 60000 inside 10 s.
- Historical reads and corrections cost time linear in the payments of one wallet and requests
  are served one at a time: inside 5 s at 20000 payments with 50 in flight (32-item batches
  3.65 s max), beyond 5 s near 60000 payments in one wallet (measured on stage 3).
- UI lists fetch at most 200 items. Seeded users are hashed with a cheaper scrypt setting than
  signups so that a 5000-user reset stays inside 10 s (S2-6).
- Readings a hidden check could take differently are listed as decisions at the end of each
  acceptance map.

## Costs

Token and money costs were not measured inside the run; no figure is claimed here.
