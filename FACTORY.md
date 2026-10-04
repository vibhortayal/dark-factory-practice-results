<!-- archive-note -->
> **Not a submission run.** This is one of Team Nightshift's practice runs, rehearsals or tests. The submitted run is Run 7, branch `runs/20-2026-10-02-run-7-submitted`.

## 05. Run 2 (Oct 1, all four stages)

- **What changed from the previous run:** All four stages for the first time. The mandates gained a rule against background tasks and an instruction for the Architect to wait for replies inside its turn.
- **Why:** To fix Rehearsal 1's lost verdict and attempt the whole task.
- **Result:** All four stages accepted in 4 h 08 min, but with one restart: while waiting inside its turn, the Architect could not see the Verifier's pass. Stage 1 was also accepted with a known small spec fault marked "advisory".
- **Conclusion:** A seat only sees new messages between turns, so waiting inside a turn blinds it. Letting faults through as "advisory" weakens the check.
- **What we did next:** Seats end their turn after every handoff; no waivers, any contradiction of the spec blocks; at most five fix rounds per stage; a self-check by the Implementer; an evidence header on every message (Run 3).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

The whole sequence of runs is on the `main` branch of this repository.

Below this line: the run's own text, unchanged.

---

# Nightshift Dark Factory

Seats: Nightshift Architect (Claude Code, claude-opus-5-5), Nightshift Implementer
(Claude Code, claude-sonnet-5-5), Nightshift Verifier (Claude Code, claude-opus-5-5).
Mandates: mandates/. This file is completed by the team after the run with measured
results, timings, costs and failures.
