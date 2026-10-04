<!-- archive-note -->
> **Not a submission run.** This is one of Team Nightshift's practice runs, rehearsals or tests. The submitted run is Run 7, branch `runs/20-2026-10-02-run-7-submitted`.

## 22. Background-task test (Oct 3, all four stages)

- **What changed from the previous run:** The rule against background tasks removed from the mandates, and background tasks allowed in the settings.
- **Why:** To see whether background tasks make the factory faster.
- **Result:** All four stages accepted in about 2 hours, one BLOCK. One background task ended in an error after its message had gone out, so nothing was lost this time.
- **Conclusion:** No clear speed gain: most of the time saved came from fewer BLOCK verdicts. The failure that lost messages before is still possible.
- **What we did next:** Kept background tasks off in the submitted factory.
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

The whole sequence of runs is on the `main` branch of this repository.

Below this line: the run's own text, unchanged.

---

# Nightshift Dark Factory: Pocketful

Built by a three-seat Band factory (Architect, Implementer, Verifier) with no human
steering after the initial task. See FACTORY.md for how the factory works and
mandates/ for the seat mandates. Each stage-N/ folder is a complete service with its
own Dockerfile and RUN.md.
