<!-- archive-note: added 2026-10-03 by Claude for Team Nightshift's archive -->
> **Archive copy: not a submission run.** This branch keeps Team Nightshift's record of Stage-1 test of PR #54 on Pocketful, for reference only. The submitted run is Run 7 (branch `nightshift-run-7-2026-10-02` here; public submission repository `vibhortayal/nightshift-pocketful`).
>
> | | |
> |---|---|
> | Run | Stage-1 test of PR #54 on Pocketful. Stage-1 test in a scratch room |
> | When | 2026-10-02, 19:45 to 20:27 UTC |
> | Band room | scratch room `127d2fcc`, opened by Claude's Team session |
> | Mandates | PR #54 head `91b753b3`, merged to `main` of `nightshift-factory` as `ee236a1` (the submitted set) |
> | Result | Stage 1 accepted in 42 minutes, 1 rejection. The Verifier's commits touched only `verification/` |
> | Human input after dispatch | Dispatched by Claude's Team session, not by the owner |
> | Why it was not submitted | The stage-1 test of the text Run 7 then ran |
> | Room record | the room downloads and whole-room captures are kept by the team outside this repository |
>
> The text below this note is unchanged from the run, unless it is marked as added for the archive.

---

# Nightshift Dark Factory

Seats: Nightshift Architect (Claude Code, claude-opus-5-5), Nightshift Implementer
(Claude Code, claude-sonnet-5-5), Nightshift Verifier (Claude Code, claude-opus-5-5).
Mandates: mandates/. This file is completed by the team after the run with measured
results, timings, costs and failures.

## Run record: stage 1 (2026-10-02)

- One human dispatch at 19:45Z; stage 1 accepted at 20:27Z (42 min wall clock). No human input in between.
- Flow: Architect wrote `ACCEPTANCE-MAP-stage-1.md` and sent the task, the full specification and the map to both
  other seats (`handoffs/stage-1/`). The Implementer built while the Verifier prepared its checks from the
  specification.
- Revisions: d2d184d (first build, 19:57Z) → Verifier BLOCK #1 (reset answered 422 instead of 400 for wrong-typed
  fixture fields; the supplied checks did not cover it) → 9f7cba3 → PASS → Architect tightened map row C19 from a
  Verifier note (seeded `note` rule) → 76497f3 → PASS → accepted.
- Results at the accepted revision: supplied checks 147/147 in host and isolated mode; Verifier's own list
  137/137 (7,804 requests, no 5xx); verdicts and check list in `verification/stage-1/`; status in `STATUS.md`.
- Fix rounds used: 1 of 5. Model spend was not measured inside the run.
