<!-- archive-note -->
> **Not a submission run.** This is one of Team Nightshift's practice runs, rehearsals or tests. The submitted run is Run 7, branch `runs/20-2026-10-02-run-7-submitted`.

## 14. Stage-1 test: tightened grading (Oct 2, stage 1 test)

- **What changed from the previous run:** Any server error or any case the spec names blocks; a minor finding must state the size it exceeded. The Verifier prepares its checks while the Implementer builds.
- **Why:** Run 13 passed real faults.
- **Result:** Stage 1 accepted in 43 minutes, one BLOCK, and real faults got a BLOCK.
- **Conclusion:** Ready for a full run.
- **What we did next:** Added one rule (a value over a stated limit always blocks) and ran all four stages (Run 5).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

The whole sequence of runs is on the `main` branch of this repository.

Below this line: the run's own text, unchanged.

---

# Nightshift Dark Factory: Pocketful

Built by a three-seat Band factory (Architect, Implementer, Verifier) with no human
steering after the initial task. See FACTORY.md for how the factory works and
mandates/ for the seat mandates. Each stage-N/ folder is a complete service with its
own Dockerfile and RUN.md.
