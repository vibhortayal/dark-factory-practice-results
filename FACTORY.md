<!-- archive-note -->
> **Not a submission run.** This is one of Team Nightshift's practice runs, rehearsals or tests. The submitted run is Run 7, branch `runs/20-2026-10-02-run-7-submitted`.

## 18. Stage-1 test: final text on Pocketful (Oct 2, stage 1 test)

- **What changed from the previous run:** Neutral wording; the Verifier commits its check list and verdicts to the repository; commits that only touch records need no new verdict; fix handoffs do not repeat the whole spec.
- **Why:** To put the evidence where judges can see it, and to make the factory clearly generic.
- **Result:** Stage 1 accepted in 42 minutes, one BLOCK, with the Verifier's evidence in the repository.
- **Conclusion:** Works.
- **What we did next:** Ran the same text, unchanged, on the other track (run 19).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

The whole sequence of runs is on the `main` branch of this repository.

Below this line: the run's own text, unchanged.

---

# Nightshift Dark Factory

Seats: Nightshift Architect (Claude Code, claude-opus-5-5), Nightshift Implementer
(Claude Code, claude-sonnet-5-5), Nightshift Verifier (Claude Code, claude-opus-5-5).
Mandates: mandates/. This file is completed by the team after the run with measured
results, timings, costs and failures.

## Run record: stage 1 (2026-10-02)

- One human dispatch at 19:45Z; stage 1 accepted at 20:27Z (42 min wall clock). No human input in between.
- Flow: Architect wrote `ACCEPTANCE-MAP-stage-1.md` and sent the task, the full specification and the map to both
  other seats (`handoffs/stage-1/`). The Implementer built while the Verifier prepared its checks from the
  specification.
- Revisions: d2d184d (first build, 19:57Z) → Verifier BLOCK #1 (reset answered 422 instead of 400 for wrong-typed
  fixture fields; the supplied checks did not cover it) → 9f7cba3 → PASS → Architect tightened map row C19 from a
  Verifier note (seeded `note` rule) → 76497f3 → PASS → accepted.
- Results at the accepted revision: supplied checks 147/147 in host and isolated mode; Verifier's own list
  137/137 (7,804 requests, no 5xx); verdicts and check list in `verification/stage-1/`; status in `STATUS.md`.
- Fix rounds used: 1 of 5. Model spend was not measured inside the run.
