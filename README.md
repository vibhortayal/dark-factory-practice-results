<!-- archive-note: added 2026-10-03 by Claude for Team Nightshift's archive -->
> **Archive copy: not a submission run.** This branch keeps Team Nightshift's record of this run (Run 4b), for reference only. The submitted run is Run 7 (branch `runs/20-2026-10-02-run-7-submitted` here; public submission repository `vibhortayal/nightshift-pocketful`).
>
> | | |
> |---|---|
> | Run | Run 4b. Four-stage run, Claude Code seats |
> | What this run tested | Compared with Run 4: nothing changed. Same text, same settings. It repeated Run 4 to see whether Run 4's block at stage 1 was chance |
> | Seats | Three Band seats on Claude Code: Architect `claude-opus-5-5`, Implementer `claude-sonnet-5-5`, Verifier `claude-opus-5-5`, running on the team's Chicago VM (from `mandates/`) |
> | When | 2026-10-01 21:14 to 2026-10-02 00:25 UTC |
> | Band room | `Nightshift \| Pocketful \| Stages 1-4 \| Run 4b \| 2026-10-01` (`afb80351`) |
> | Mandates | the Run 3 set (team repo `nightshift-factory`, commit `f3cbc34`), unchanged from Run 4 |
> | Result | Clean, but stage 1 was recorded BLOCKED after 10 rejections. Nothing accepted. 3 h 11 min. The Verifier's findings moved from real faults to extreme inputs, which led to the bounded mandates |
> | Human input after dispatch | One dispatch, no intervention |
> | Why it was not submitted | Stopped at stage 1 |
> | Room record | the room downloads and whole-room captures are kept by the team outside this repository |
>
> The text below this note is unchanged from the run, unless it is marked as added for the archive.

---

# Nightshift Dark Factory: Pocketful

Built by a three-seat Band factory (Architect, Implementer, Verifier) with no human
steering after the initial task. See FACTORY.md for how the factory works and
mandates/ for the seat mandates. Each stage-N/ folder is a complete service with its
own Dockerfile and RUN.md.
