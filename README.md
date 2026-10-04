<!-- archive-note -->
> **Not a submission run.** This is one of Team Nightshift's practice runs, rehearsals or tests. The submitted run is Run 7, branch `runs/20-2026-10-02-run-7-submitted`.

## 16. Stage-1 test: simpler set (Oct 2, stage 1 test)

- **What changed from the previous run:** Grading and free testing removed. A finding either blocks or is a note. Every check names the spec sentence it tests. Limits are tested at the last allowed and first refused value. A fix that did not fix the fault gets a BLOCK at once.
- **Why:** Run 5 was too slow.
- **Result:** Stage 1 accepted in 53 minutes, two BLOCK verdicts.
- **Conclusion:** Works, with far less machinery.
- **What we did next:** Added a request for maintainable code and ran all four stages (Run 6).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

The whole sequence of runs is on the `main` branch of this repository.

Below this line: the run's own text, unchanged.

---

# Nightshift Dark Factory: Pocketful

Built by a three-seat Band factory (Architect, Implementer, Verifier) with no human
steering after the initial task. See FACTORY.md for how the factory works and
mandates/ for the seat mandates. Each stage-N/ folder is a complete service with its
own Dockerfile and RUN.md.
