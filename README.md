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

# Nightshift Dark Factory: Pocketful

Built by a three-seat Band factory (Architect, Implementer, Verifier) with no human
steering after the initial task. See FACTORY.md for how the factory works and
mandates/ for the seat mandates. Each stage-N/ folder is a complete service with its
own Dockerfile and RUN.md.
