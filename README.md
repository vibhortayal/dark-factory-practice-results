<!-- archive-note: added 2026-10-03 by Claude for Team Nightshift's archive -->
> **Archive copy: not a submission run.** This branch keeps Team Nightshift's record of this run (Background-task test), for reference only. The submitted run is Run 7 (branch `nightshift-run-7-2026-10-02` here; public submission repository `vibhortayal/nightshift-pocketful`).
>
> | | |
> |---|---|
> | Run | Background-task test. Four-stage test run in a scratch room |
> | What this run tested | Compared with Run 7: the mandates' paragraph against background tasks removed from all three seats, and the setting that switches background tasks off removed from the seats. Nothing else changed. It tested whether allowing background tasks makes the factory faster |
> | When | 2026-10-03, 19:43 to 21:38 UTC |
> | Band room | scratch room `2d54a4fe`, opened by Claude's Team session |
> | Mandates | Run 7's set minus its paragraph against background tasks, with background tasks allowed in the seats' settings. Used for this test only |
> | Result | All four stages accepted in about 2 hours, 1 rejection. One background task ended in an error after its message had gone out; nothing was lost. Most of the time saved against Run 7 came from fewer rejections, so a speed gain from background tasks is not shown |
> | Human input after dispatch | Dispatched by Claude's Team session on the owner's request, not by the owner |
> | Why it was not submitted | A test of one setting, run for comparison. The submitted factory keeps background tasks off |
> | Room record | the room downloads and whole-room captures are kept by the team outside this repository |
>
> The text below this note is unchanged from the run, unless it is marked as added for the archive.

---

# Nightshift Dark Factory: Pocketful

Built by a three-seat Band factory (Architect, Implementer, Verifier) with no human
steering after the initial task. See FACTORY.md for how the factory works and
mandates/ for the seat mandates. Each stage-N/ folder is a complete service with its
own Dockerfile and RUN.md.
