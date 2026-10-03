<!-- archive-note: added 2026-10-03 by Claude for Team Nightshift's archive -->
> **Archive copy: not a submission run.** This branch keeps Team Nightshift's record of this run (Run 5), for reference only. The submitted run is Run 7 (branch `runs/20-2026-10-02-run-7-submitted` here; public submission repository `vibhortayal/nightshift-pocketful`).
>
> | | |
> |---|---|
> | Run | Run 5. Four-stage run, Claude Code seats |
> | What this run tested | Compared with the `f6fc48a3` test: one more rule, that a value beyond a limit the spec states always blocks. The first four-stage run on the bounded, graded text |
> | Seats | Three Band seats on Claude Code: Architect `claude-opus-5-5`, Implementer `claude-sonnet-5-5`, Verifier `claude-opus-5-5`, running on the team's Chicago VM (from `mandates/`) |
> | When | 2026-10-02, 04:11 to 15:31 UTC |
> | Band room | `Nightshift \| Pocketful \| Stages 1-4 \| Run 5 \| 2026-10-02` (`f83420d7`) |
> | Mandates | PR #52 head `7fc01726` (bounded Verifier, severity grading, 15 minutes of timed hardening) |
> | Result | Clean. All four stages accepted in 11 h 20 min, 6 rejections. The Verifier ran 900 to 1,900 checks of its own per stage |
> | Human input after dispatch | One dispatch, no intervention |
> | Why it was not submitted | Not chosen: Runs 6 and 7 used a simpler mandate set that was four times faster and produced more maintainable code. Run 5 kept its whole service in one file per stage |
> | Room record | the room downloads and whole-room captures are kept by the team outside this repository |
>
> The text below this note is unchanged from the run, unless it is marked as added for the archive.

---

# Nightshift Dark Factory: Pocketful

Built by a three-seat Band factory (Architect, Implementer, Verifier) with no human
steering after the initial task. See FACTORY.md for how the factory works and
mandates/ for the seat mandates. Each stage-N/ folder is a complete service with its
own Dockerfile and RUN.md.
