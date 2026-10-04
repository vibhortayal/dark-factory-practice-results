<!-- archive-note -->
> **Not a submission run.** This is one of Team Nightshift's practice runs, rehearsals or tests. The submitted run is Run 7, branch `runs/20-2026-10-02-run-7-submitted`.

## 15. Run 5 (Oct 2, all four stages)

- **What changed from the previous run:** The bounded, graded mandates from runs 12 to 14.
- **Why:** First full run since the Verifier was bounded.
- **Result:** Clean. All four stages accepted in 11 h 20 min, 6 BLOCK verdicts, about $116 at list price. The app was the most thoroughly tested, but each stage was one large file, and the free testing and growing check lists made it slow.
- **Conclusion:** Bounded verification finishes, but this version was far too slow and over-engineered.
- **What we did next:** Simplified the mandates: no grading, no free testing, every check tied to a sentence of the spec (run 16).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

This branch also keeps the Verifier's own check scripts (`verifier-check-scripts/`), later used to compare the apps of several runs.

The whole sequence of runs is on the `main` branch of this repository.

Below this line: the run's own text, unchanged.

---

# Nightshift Dark Factory: Pocketful

Built by a three-seat Band factory (Architect, Implementer, Verifier) with no human
steering after the initial task. See FACTORY.md for how the factory works and
mandates/ for the seat mandates. Each stage-N/ folder is a complete service with its
own Dockerfile and RUN.md.
