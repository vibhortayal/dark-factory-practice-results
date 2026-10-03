<!-- archive-note: added 2026-10-03 by Claude for Team Nightshift's archive -->
> **Archive copy: not a submission run.** This branch keeps Team Nightshift's record of this run (Run 6), for reference only. The submitted run is Run 7 (branch `runs/20-2026-10-02-run-7-submitted` here; public submission repository `vibhortayal/nightshift-pocketful`).
>
> | | |
> |---|---|
> | Run | Run 6. Four-stage run, Claude Code seats |
> | What this run tested | Compared with the `643e2307` test: one added sentence asking the Implementer to split code into small modules with one job each, and the Verifier to note maintainability without blocking. The first four-stage run on the simpler set |
> | Seats | Three Band seats on Claude Code: Architect `claude-opus-5-5`, Implementer `claude-sonnet-5-5`, Verifier `claude-opus-5-5`, running on the team's Chicago VM (from `mandates/`) |
> | When | 2026-10-02, 16:47 to 19:20 UTC |
> | Band room | `Nightshift \| Pocketful \| Stages 1-4 \| Run 6 \| 2026-10-02` (`45f01f4e`) |
> | Mandates | PR #53 head `674112d0` (the simpler set plus a maintainability sentence) |
> | Result | Clean. All four stages accepted in 2 h 33 min, 2 rejections |
> | Human input after dispatch | One dispatch, no intervention |
> | Why it was not submitted | Not chosen: Run 7 ran the same factory with neutral wording and with the Verifier's evidence committed to the repository |
> | Room record | the room downloads and whole-room captures are kept by the team outside this repository |
>
> The text below this note is unchanged from the run, unless it is marked as added for the archive.

---

# Nightshift Dark Factory: Pocketful

Built by a three-seat Band factory (Architect, Implementer, Verifier) with no human
steering after the initial task. See FACTORY.md for how the factory works and
mandates/ for the seat mandates. Each stage-N/ folder is a complete service with its
own Dockerfile and RUN.md.
