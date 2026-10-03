<!-- archive-note: added 2026-10-03 by Claude for Team Nightshift's archive -->
> **Archive copy: not a submission run.** This branch keeps Team Nightshift's record of this run (Stage-1 test of PR #52 head f6fc48a3), for reference only. The submitted run is Run 7 (branch `runs/20-2026-10-02-run-7-submitted` here; public submission repository `vibhortayal/nightshift-pocketful`).
>
> | | |
> |---|---|
> | Run | Stage-1 test of PR #52 head f6fc48a3. Stage-1 test in a scratch room |
> | What this run tested | Compared with `590afd18`, which let real spec faults pass as notes: hardened grading (any server error or named case blocks; a note must state the size it exceeded), notes fixed during fix rounds, and the Verifier preparing its checks while the Implementer builds |
> | Seats | Three Band seats on Claude Code: Architect `claude-opus-5-5`, Implementer `claude-sonnet-5-5`, Verifier `claude-opus-5-5`, running on the team's Chicago VM (from `mandates/`) |
> | When | 2026-10-02, 03:21 to 04:04 UTC |
> | Band room | scratch room `590851bd`, opened by Claude's Team session |
> | Mandates | PR #52 head `f6fc48a3` (hardened grading, Verifier prepares in parallel) |
> | Result | Stage 1 accepted in 43 minutes, 1 rejection |
> | Human input after dispatch | Dispatched by Claude's Team session, not by the owner |
> | Why it was not submitted | A test of mandate wording, not a four-stage run |
> | Room record | the room downloads and whole-room captures are kept by the team outside this repository |
>
> The text below this note is unchanged from the run, unless it is marked as added for the archive.

---

# Nightshift Dark Factory: Pocketful

Built by a three-seat Band factory (Architect, Implementer, Verifier) with no human
steering after the initial task. See FACTORY.md for how the factory works and
mandates/ for the seat mandates. Each stage-N/ folder is a complete service with its
own Dockerfile and RUN.md.
