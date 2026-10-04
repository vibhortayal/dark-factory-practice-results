<!-- archive-note -->
> **Not a submission run.** This is one of Team Nightshift's practice runs, rehearsals or tests. The submitted run is Run 7, branch `runs/20-2026-10-02-run-7-submitted`.

## 11. Run 4b (Oct 1, all four stages)

- **What changed from the previous run:** Nothing. Same mandates, same settings as Run 4.
- **Why:** To see whether Run 4's result was bad luck.
- **Result:** Clean, but stage 1 was never accepted: 10 BLOCK verdicts in 3 h 11 min. The findings moved to extreme inputs, such as a 60-million-digit number.
- **Conclusion:** Not luck. The mandates had to say how far the Verifier tests.
- **What we did next:** Bounded the Verifier and tried it on stage 1 (run 12).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

The whole sequence of runs is on the `main` branch of this repository.

Below this line: the run's own text, unchanged.

---

# Nightshift Dark Factory: Pocketful

Built by a three-seat Band factory (Architect, Implementer, Verifier) with no human
steering after the initial task. See FACTORY.md for how the factory works and
mandates/ for the seat mandates. Each stage-N/ folder is a complete service with its
own Dockerfile and RUN.md.
