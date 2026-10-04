<!-- archive-note -->
> **Not a submission run.** This is one of Team Nightshift's practice runs, rehearsals or tests. The submitted run is Run 7, branch `runs/20-2026-10-02-run-7-submitted`.

## 04. Rehearsal 1 (Oct 1, stage 1 only)

- **What changed from the previous run:** New platform: three Claude Code seats (Architect, Implementer, Verifier) talking in a Band room, with new seat instructions (mandates).
- **Why:** Stronger models and a set-up we could control and repeat.
- **Result:** Stage 1 accepted in 49 minutes, all 147 supplied checks passing. One restart: a background task failed and took the Verifier's verdict with it.
- **Conclusion:** The three seats can deliver a stage on their own. Background tasks can silently lose a message.
- **What we did next:** Added a written rule against background tasks, and told the Architect to wait for replies inside its turn (Run 2).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

The whole sequence of runs is on the `main` branch of this repository.

Below this line: the run's own text, unchanged.

---

# Nightshift dark factory: rehearsal result (not a submission)

Dress rehearsal 1 of the Nightshift three-seat factory on Claude Code seats.
This repository is practice output. See FACTORY.md and mandates/.
