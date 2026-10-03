<!-- archive-note: added 2026-10-03 by Claude for Team Nightshift's archive -->
> **Archive copy: not a submission run.** This branch keeps Team Nightshift's record of this run (Stage-1 test of PR #53 head 643e2307), for reference only. The submitted run is Run 7 (branch `runs/20-2026-10-02-run-7-submitted` here; public submission repository `vibhortayal/nightshift-pocketful`).
>
> | | |
> |---|---|
> | Run | Stage-1 test of PR #53 head 643e2307. Stage-1 test in a scratch room |
> | What this run tested | Compared with Run 5's text: the simpler set. Severity scale, timed free testing and note routing removed; two kinds of finding (blocking or note); every check names the spec sentence it tests; value limits tested at the last allowed and first refused value; a fix that did not fix the fault is rejected at once |
> | Seats | Three Band seats on Claude Code: Architect `claude-opus-5-5`, Implementer `claude-sonnet-5-5`, Verifier `claude-opus-5-5`, running on the team's Chicago VM (from `mandates/`) |
> | When | 2026-10-02, 15:46 to 16:40 UTC |
> | Band room | scratch room `8c1d7878`, opened by Claude's Team session |
> | Mandates | PR #53 head `643e2307` (simpler set: no severity scale, no free testing, fail fast) |
> | Result | Stage 1 accepted in 53 minutes, 2 rejections |
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
