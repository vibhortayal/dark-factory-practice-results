<!-- archive-note -->
> **Not a submission run.** This is one of Team Nightshift's practice runs, rehearsals or tests. The submitted run is Run 7, branch `runs/20-2026-10-02-run-7-submitted`.

## 12. Stage-1 test: bounded Verifier (Oct 2, stage 1 test)

- **What changed from the previous run:** The Verifier tests at the sizes and loads the spec states and not beyond, writes its check list first, and reports every finding in one verdict. A fix round is one BLOCK verdict, and a build under review cannot be withdrawn.
- **Why:** Runs 4 and 4b never converged.
- **Result:** Stage 1 accepted in 30 minutes, with one BLOCK that listed all four findings at once.
- **Conclusion:** Bounding the Verifier works.
- **What we did next:** Tried a more lenient check: graded findings plus a short window of free testing (run 13).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

The whole sequence of runs is on the `main` branch of this repository.

Below this line: the run's own text, unchanged.

---

# Stage-1 check (rehearsal, not a submission)
