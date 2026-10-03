<!-- archive-note: added 2026-10-03 by Claude for Team Nightshift's archive -->
> **Archive copy: not a submission run.** This branch keeps Team Nightshift's record of this run (Run 3), for reference only. The submitted run is Run 7 (branch `nightshift-run-7-2026-10-02` here; public submission repository `vibhortayal/nightshift-pocketful`).
>
> | | |
> |---|---|
> | Run | Run 3. Four-stage run, Claude Code seats |
> | What this run tested | Compared with Run 2: the Run 3 set. No waivers (any contradiction of the spec blocks), at most five fix rounds per stage, an Implementer self-check against every requirement, an evidence header on every message, and seats ending their turn after each handoff instead of waiting inside it |
> | When | 2026-10-01, 06:35 to 15:40 UTC |
> | Band room | `Nightshift \| Pocketful \| Stages 1-4 \| Run 3 \| 2026-09-30` (`b352896e`) |
> | Mandates | the Run 3 set (team repo `nightshift-factory`, commit `f3cbc34`) |
> | Result | All four stages accepted. About 4.5 hours of work plus a 4 h 37 min stall. 4 rejections |
> | Human input after dispatch | One intervention: the Verifier was restarted at 14:29 UTC on the owner's word. Its stage-3 PASS, decided at 09:52, was never posted (a failed background task dropped the message) |
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
