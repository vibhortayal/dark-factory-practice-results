<!-- archive-note -->
> **Not a submission run.** This is one of Team Nightshift's practice runs, rehearsals or tests. The submitted run is Run 7, branch `runs/20-2026-10-02-run-7-submitted`.

## 10. Run 4 (Oct 1, all four stages)

- **What changed from the previous run:** Same mandates as Run 3. Background tasks switched off in the seats' settings.
- **Why:** To remove the failure that had cost Rehearsal 1 and Run 3 a message, and get a clean run.
- **Result:** Clean, with no human help, but stage 1 was never accepted: 6 BLOCK verdicts in 1 h 37 min. Each fix round the Verifier found one or two new, ever more unusual problems.
- **Conclusion:** The background fix held. But a Verifier with no limit on how deep it tests never finishes.
- **What we did next:** Repeated the run unchanged to rule out chance (Run 4b).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

The whole sequence of runs is on the `main` branch of this repository.

Below this line: the run's own text, unchanged.

---

# Nightshift Dark Factory: Pocketful

Built by a three-seat Band factory (Architect, Implementer, Verifier) with no human
steering after the initial task. See FACTORY.md for how the factory works and
mandates/ for the seat mandates. Each stage-N/ folder is a complete service with its
own Dockerfile and RUN.md.
