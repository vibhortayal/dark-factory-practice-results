<!-- archive-note -->
> **Not a submission run.** This is one of Team Nightshift's practice runs, rehearsals or tests. The submitted run is Run 7, branch `runs/20-2026-10-02-run-7-submitted`.

## 17. Run 6 (Oct 2, all four stages)

- **What changed from the previous run:** The simpler set, plus one sentence asking the Implementer to split code into small modules.
- **Why:** Speed, and code another developer could maintain.
- **Result:** Clean. All four stages accepted in 2 h 33 min, 2 BLOCK verdicts, about $53. The code came out in small modules. A few edge cases slipped through, for example an amount like 1.00000000000000000001 read as 1.
- **Conclusion:** Four times faster than Run 5 and easier to maintain. But the Verifier's evidence stayed outside the repository, and the wording still read as written for a web service.
- **What we did next:** Neutral wording, the Verifier committing its evidence, and lighter fix handoffs, tried on stage 1 (run 18).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

The whole sequence of runs is on the `main` branch of this repository.

Below this line: the run's own text, unchanged.

---

# Nightshift Dark Factory

Seats: Nightshift Architect (Claude Code, claude-opus-5-5), Nightshift Implementer
(Claude Code, claude-sonnet-5-5), Nightshift Verifier (Claude Code, claude-opus-5-5).
Mandates: mandates/. This file is completed by the team after the run with measured
results, timings, costs and failures.
