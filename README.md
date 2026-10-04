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

# Nightshift Dark Factory: Pocketful

Built by a three-seat Band factory (Architect, Implementer, Verifier) with no human
steering after the initial task. See FACTORY.md for how the factory works and
mandates/ for the seat mandates. Each stage-N/ folder is a complete service with its
own Dockerfile and RUN.md.
