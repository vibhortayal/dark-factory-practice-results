<!-- archive-note: added 2026-10-03 by Claude for Team Nightshift's archive -->
> **Archive copy: not a submission run.** This branch keeps Team Nightshift's record of this run (Run 2), for reference only. The submitted run is Run 7 (branch `nightshift-run-7-2026-10-02` here; public submission repository `vibhortayal/nightshift-pocketful`).
>
> | | |
> |---|---|
> | Run | Run 2. Four-stage run, Claude Code seats |
> | What this run tested | Compared with Rehearsal 1: all four stages for the first time, on the v2 mandates. v2 added two things: a written rule for all seats against background tasks, after Rehearsal 1 lost a verdict to a failed background task; and an Architect rule to wait inside its turn for replies. The second rule turned out to blind it |
> | When | 2026-10-01, 02:08 to 06:17 UTC |
> | Band room | `Nightshift \| Pocketful \| Stages 1-4 \| Run 2 \| 2026-09-30` (`45cd862d`) |
> | Mandates | the v2 set (team repo `nightshift-factory`, commit `8d87824`) |
> | Result | All four stages accepted in 4 h 08 min. 4 rejections |
> | Human input after dispatch | One intervention: the Architect was restarted at about 03:10 UTC. Its mandate told it to wait inside its turn, so it never saw the Verifier's pass |
> | Why it was not submitted | Not clean: one intervention |
> | Room record | the room downloads and whole-room captures are kept by the team outside this repository |
>
> The text below this note is unchanged from the run, unless it is marked as added for the archive.

---

# Nightshift Dark Factory: Pocketful

Built by a three-seat Band factory (Architect, Implementer, Verifier) with no human
steering after the initial task. See FACTORY.md for how the factory works and
mandates/ for the seat mandates. Each stage-N/ folder is a complete service with its
own Dockerfile and RUN.md.
