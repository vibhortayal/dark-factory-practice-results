# Final report: Pocketful, four stages

Run: 2026-10-02, 16:47Z to 19:19Z (2h32). One human dispatch, no further human input.
Outcome: all four stages accepted, each on a Verifier PASS for the exact revision. Nothing is blocked.

## What was accepted

| Stage | Folder | Accepted revision (last commit touching the folder) | Fix rounds (BLOCK verdicts) | Time | Final isolated check |
|---|---|---|---|---|---|
| 1 | `stage-1/` | 77409dda43334b784ca1125d2d990ba51478abf6 | 1 | 0h36 | `checks/s1-ver-04`: 147 passed, `claimed stage: 1` |
| 2 | `stage-2/` | 88b9223d3e56cd9a668499f3cd5b87575d0ea114 | 1 | 0h53 | `checks/s2-ver-04`: 147 + 35 passed, `claimed stage: 2` |
| 3 | `stage-3/` | aedbe2c666e7b1b97661ad869d77f002bb103eca | 0 | 0h33 | `checks/s3-ver-02`: 147 + 35 + 6 passed, `claimed stage: 3` |
| 4 | `stage-4/` | 9ea6024167915ce49bd8be08cd4f2c2bc145beb4 | 0 | 0h30 | `checks/s4-ver-02`: 147 + 35 + 6 + 5 passed, `claimed stage: 4` |

`--all --mode isolated` (`checks/s4-ver-03`): `stage-1/` claims stage 1, `stage-2/` 2, `stage-3/` 3, `stage-4/` 4. Each lower folder fails the next stage's suite, as it must. The `checks/` directories are in `/home/ubuntu/nightshift-claude-run-6/band-work/checks/`, outside this repository.

Each stage folder is a copy of the previous accepted folder, extended; no earlier folder was changed after its acceptance (confirmed by the Verifier with `git diff --stat <accepted revision> HEAD -- stage-N/` at every later verdict).

## What the factory caught

- Stage 1, BLOCK on f0f44189584133d95ec5bfc64c52c050450ddeb8: over-limit values got the wrong answer once large (400 past 2 MiB of body, a bare 431 past 16 KiB of request head) where the specification says 422 with the error body. Fixed as a class (rows A12, A13), not as the reported cases.
- Stage 2, BLOCK on 427730e1c2d1d84edfc66233b81ceab77885c07b: a UI element the Implementer added used a test id inside a specified family (`request-pay-{request_id}`), so a request with that id made the specified pay button ambiguous. Fixed as a class (row Q11, with an automated scan of every test id the UI can emit). The same round corrected list ordering by stored time, one clock instant per request, typed import leaves, loading states and a narrow-screen layout fault, all raised by the Verifier.
- Stages 3 and 4 passed on their first revision. For both, the Verifier wrote an independent model of the historical ledger from the specification alone and compared it with the service over generated histories (about 3,000 balance views and 72 statements per history, five histories per stage), because the supplied suites for those stages are 6 and 5 checks.

None of these findings was reachable by the supplied checks: both blocked revisions already passed them.

## What failed or remains open

Nothing is blocked and no blocking finding is open. Open, non-blocking, recorded by the Verifier:

- Nothing is pruned (payments, revisions, refunds, batches, statement snapshots, idempotency records); no soak test was run; load was tested up to the stated 50 requests in flight only.
- Browser checks ran in Chromium only. The first-load screen is a plain spinner.
- An older-stage export gives no history to a hold that was already closed without capture records; free-form string leaves of an import are not integrity-checked; a batch rejected late consumes a batch number.
- Where the specification leaves a choice open, the Architect resolved it in the acceptance maps (rows marked [D]) and the Verifier's model follows the same reading: default statement window, tie order by id, error precedence inside one item, boundaries already negative before a correction. The held-back checks may read these differently.
- The supplied checks are a part of the graded ones (79%, 35%, 9%, 16% by stage); a green run on them is not proof of a stage.

## Where the evidence is

- `STATUS.md`: state of each unit, accepted revisions, fix-round counts, times, and every Verifier verdict copied with its notes.
- `acceptance/stage-1.md` to `stage-4.md`: every requirement with how it is checked; decisions marked [D] with reasons.
- `handoffs/stage-N/`: every handoff, fix request and verification handoff exactly as sent in the room.
- `/home/ubuntu/nightshift-claude-run-6/band-work/checks/`: harness outputs (`s<N>-impl-*` from the Implementer, `s<N>-ver-*` from the Verifier).
- `/home/ubuntu/nightshift-claude-run-6/band-work/verifier/`: the Verifier's probes, model and run outputs (outside this repository; the Verifier made no commits).
- Git history: 14 commits by the Implementer (all under `stage-N/`), the rest by the Architect (maps, status, handoff records); no history was rewritten and nothing was pushed.

## Left for the human

- `room.json` is not in the repository: `harness check` reports that as its only problem. It is downloaded from Band by a person.
- `FACTORY.md` and `README.md` are as the human set them up; measured times and fix rounds for `FACTORY.md` are in the table above. Model spend was not measurable from inside the run.
