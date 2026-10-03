# Nightshift practice archive

Private archival evidence. This is not the submission repository and does not certify a clean autonomous run or hidden-test coverage.

| Run | Dated branch | Original name | Exact archived HEAD | Classification |
| --- | --- | --- | --- | --- |
| R1 | practice-r1-2026-09-28 | `r1/stage-1` in `nightshift-practice-r1` | c91817f42a50c0ffb1f8ac2709849c251ae3bb82 | Intervened development evidence |
| R2 | practice-r2-2026-09-29 | run2 | fa201f49880987f92e391d12db0db26dfb617291 | Intervened development evidence |
| R3 | practice-r3-2026-09-29 | run3 | ab8b9bbfbea9d2d8ba075e7ce1f2ec30b2fab03c | Blocked preflight evidence |

These are the September 28-29 practice runs. They are not the later "Run 2" and "Run 3" on Claude Code seats; those are archived separately below under the `nightshift-` branch names. R2 and R3 were first archived under the branch names `run2` and `run3`. Those names were removed on 2026-10-01 (UTC) on Vibhor's word in BAND Bridge 54830dd7-3477-48a5-8f6f-a9fc340e83bb; the commits are unchanged under the dated names. The source repository `nightshift-practice-r1` was archived read-only at the same time.

R1's own `PRACTICE-LEARNINGS.md` catalogues its development interventions. R2 includes outside operator intervention, and its shipped-check pass does not prove clean autonomy or hidden-check coverage. R3 stopped at blocked preflight and was not rescued or reused. The run branches preserve their original histories; this main branch holds the index, plus one retained private draft folder, `video-demo/` (a narration audio file and a shot list added on 2026-09-30), which is not run evidence.

Approved by Vibhor in BAND Team ef50a509-0237-4007-9097-678b2fffdf1b, responding to proposal bc609d55-de9b-4994-802c-f504c8486cb4. Archive key destination confirmed in owner post 92a59f08-1220-4488-9bb5-afe85f2a5b0c. Archived September 29, 2026 PDT.

R1 was imported on 2026-10-01 (UTC) from `nightshift-practice-r1` with its history unchanged (15 commits, tree 65e3806d6a90841767c0215e04d658edd241bbea), on Vibhor's go in BAND Bridge 5092000f-fbb0-468d-aef8-f25f2ccfb47f.

## Runs on Claude Code seats, September 30 to October 1, 2026

Four result repositories from the Chicago VM, each pushed with its full history unchanged. Every commit is authored by a seat or by the human setup commit. Rooms are the BAND rooms the runs happened in.

| Run | Dated branch | Exact archived HEAD | Commits | Classification |
| --- | --- | --- | --- | --- |
| Rehearsal 1 | nightshift-rehearsal-1-2026-09-30 | 1ecf73b130f84bb0e0e38a999dc8b728c42c949d | 12 | Rehearsal. Stage 1 only, accepted. One intervention (a seat restart) |
| Run 2 | nightshift-run-2-2026-09-30 | 93c895aed67b92da60726a84c8eb896ccce7ce6c | 29 | Rehearsal. Four stages accepted. One intervention (a seat restart) |
| Run 3 | nightshift-run-3-2026-09-30 | 62da9bc8e240f587d50601da13852eb7081c8910 | 27 | Rehearsal. Four stages accepted. One intervention: the Verifier was restarted after its verdict was lost and the run sat idle for about four and a half hours |
| Run 4 | nightshift-run-4-2026-10-01 | 6ffea910a471fe152188cc07fc5811e22df343f0 | 13 | Clean run, no intervention, but nothing accepted. Stage 1 was blocked when the fix-round limit was reached after six rejections; later stages never started |

None of these is the submission. Run 3 completed but is not a no-steering run. Run 4 is a no-steering run but did not complete a stage.

Sources for the classifications: Run 3 and Run 4 from the room records (one human message each, the dispatch; the Run 4 final report). Rehearsal 1 and Run 2 from the run log `docs/handover-claude-2026-09-30.md` in the private `nightshift-factory` repository.

Archived on 2026-10-01 (UTC) on Vibhor's go in BAND Bridge f12d772d-d1c3-4b6f-b4a3-fc7bd6f2cfd3 ("Go - all 4"). Before the push the complete history of all four was scanned for credentials, key files, real email addresses and network addresses, by Claude and independently by Instinct (BAND Bridge 8c4416b5-9010-4f33-a6e3-5a2c41f9b15a): none found. Run 2 and Run 3 contain `/home/ubuntu/...` workspace paths, which is acceptable in this private repository and should be reviewed before anything from them is made public.

Left out because they were never committed: an untracked `room.json` in the Rehearsal 1 workspace, and uncommitted edits to `stage-1/server.py` and its tests in the Run 4 workspace. Room exports are not in this repository.

Apart from that draft folder, only the result histories listed above and this index are meant to be here. VM credentials, room exports, private team records and other runtime evidence are not included. When R2 and R3 were archived on September 29, their source workspaces were recorded as having no remotes; that has not been re-checked since. R1's source is the GitHub repository `nightshift-practice-r1`, now archived read-only.

## Every run, as of 2026-10-03

One branch per run, named `runs/NN-YYYY-MM-DD-name`: `NN` is the order the runs started in and the date is the UTC day of the dispatch, so the branch list reads in time order. Each branch starts its `README.md` and `FACTORY.md` with a note that says what the run tested compared with the run before, and gives the seats' harness and models, its date, room, mandate version, result, human input, and why it was not submitted. The run's own history and files are unchanged below that note. **Only Run 7 is the submitted run**; its public repository is `vibhortayal/nightshift-pocketful`.

| Run | Branch | Kind | When | Result | Status |
|---|---|---|---|---|---|
| Practice run R1 | `runs/01-2026-09-28-practice-r1` | Practice run, stage 1 only, before the Claude Code seats | 2026-09-28 to 09-29 | Stage 1 built. Classified in the archive index as intervened development evidence | Not submitted |
| Practice run R2 | `runs/02-2026-09-29-practice-r2` | Practice run, stage 1 only, before the Claude Code seats | 2026-09-29 | Stage 1 built, with fixes after harness failures. Classified as intervened development evidence | Not submitted |
| Practice run R3 | `runs/03-2026-09-29-practice-r3` | Practice preflight, stage 1, before the Claude Code seats | 2026-09-29 | One commit with a stage-1 implementation. Classified as blocked preflight evidence | Not submitted |
| Rehearsal 1 | `runs/04-2026-10-01-rehearsal-1` | Rehearsal, stage 1 only, Claude Code seats | 2026-10-01, 00:55 to 01:51 UTC | Stage 1 accepted in 49 minutes. Supplied checks 147 of 147 | Not submitted |
| Run 2 | `runs/05-2026-10-01-run-2` | Four-stage run, Claude Code seats | 2026-10-01, 02:08 to 06:17 UTC | All four stages accepted in 4 h 08 min. 4 rejections | Not submitted |
| Run 3 | `runs/06-2026-10-01-run-3` | Four-stage run, Claude Code seats | 2026-10-01, 06:35 to 15:40 UTC | All four stages accepted. About 4.5 hours of work plus a 4 h 37 min stall. 4 rejections | Not submitted |
| Stage-1 test on the Run 3 set | `runs/07-2026-10-01-stage1-test-run3-text` | Stage-1 test in a scratch room | 2026-10-01, 16:26 to 16:56 UTC | Stopped by the team after the first rejection, with stage 1 in fix round 1. Nothing accepted | Not submitted |
| Stage-1 test of mandate candidate A | `runs/08-2026-10-01-stage1-test-candidate-a` | Stage-1 test in a scratch room | 2026-10-01, 17:32 to 17:57 UTC | Stopped after the first rejection. The Implementer read the new sentence as leave to drop the spec from its handoff, so the candidate was withdrawn | Not submitted |
| Stage-1 test: fewer parts, full text kept | `runs/09-2026-10-01-stage1-test-full-text-parts` | Stage-1 test in a scratch room | 2026-10-01, 18:10 to 18:35 UTC | Stopped before a verdict. Run 4 went ahead on the Run 3 text instead | Not submitted |
| Run 4 | `runs/10-2026-10-01-run-4` | Four-stage run, Claude Code seats | 2026-10-01, 19:05 to 20:42 UTC | Clean, but stage 1 was recorded BLOCKED after 6 rejections (five fix rounds used). Nothing accepted. 1 h 37 min | Not submitted |
| Run 4b | `runs/11-2026-10-01-run-4b` | Four-stage run, Claude Code seats | 2026-10-01 21:14 to 2026-10-02 00:25 UTC | Clean, but stage 1 was recorded BLOCKED after 10 rejections. Nothing accepted. 3 h 11 min. The Verifier's findings moved from real faults to extreme inputs, which led to the bounded mandates | Not submitted |
| Stage-1 test of PR #52 head 28df31b9 | `runs/12-2026-10-02-stage1-test-pr52-28df31b9` | Stage-1 test in a scratch room | 2026-10-02, 01:36 to 02:07 UTC | Stage 1 accepted in 30 minutes, 1 rejection | Not submitted |
| Stage-1 test of PR #52 head 590afd18 | `runs/13-2026-10-02-stage1-test-pr52-590afd18` | Stage-1 test in a scratch room | 2026-10-02, 02:13 to 02:41 UTC | Stage 1 accepted in 28 minutes, 0 rejections. Real spec faults were graded as notes and passed, so the grading was hardened afterwards | Not submitted |
| Stage-1 test of PR #52 head f6fc48a3 | `runs/14-2026-10-02-stage1-test-pr52-f6fc48a3` | Stage-1 test in a scratch room | 2026-10-02, 03:21 to 04:04 UTC | Stage 1 accepted in 43 minutes, 1 rejection | Not submitted |
| Run 5 | `runs/15-2026-10-02-run-5` | Four-stage run, Claude Code seats | 2026-10-02, 04:11 to 15:31 UTC | Clean. All four stages accepted in 11 h 20 min, 6 rejections. The Verifier ran 900 to 1,900 checks of its own per stage | Not submitted |
| Stage-1 test of PR #53 head 643e2307 | `runs/16-2026-10-02-stage1-test-pr53-643e2307` | Stage-1 test in a scratch room | 2026-10-02, 15:46 to 16:40 UTC | Stage 1 accepted in 53 minutes, 2 rejections | Not submitted |
| Run 6 | `runs/17-2026-10-02-run-6` | Four-stage run, Claude Code seats | 2026-10-02, 16:47 to 19:20 UTC | Clean. All four stages accepted in 2 h 33 min, 2 rejections | Not submitted |
| Stage-1 test of PR #54 on Pocketful | `runs/18-2026-10-02-stage1-test-pr54-pocketful` | Stage-1 test in a scratch room | 2026-10-02, 19:45 to 20:27 UTC | Stage 1 accepted in 42 minutes, 1 rejection. The Verifier's commits touched only `verification/` | Not submitted |
| Stage-1 test of PR #54 on Tablekeeper | `runs/19-2026-10-02-stage1-test-pr54-tablekeeper` | Stage-1 test on the other track, in a scratch room | 2026-10-02, 20:27 to 21:00 UTC | Stage 1 of the Tablekeeper track accepted in 33 minutes, 0 rejections. Supplied checks 120 of 120 | Not submitted |
| Run 7 | `runs/20-2026-10-02-run-7-submitted` | Four-stage run, Claude Code seats | 2026-10-02, 21:11 to 23:38 UTC | Clean. All four stages accepted in 2 h 27 min, 4 rejections | **Submitted run** |
| Tablekeeper four-stage run | `runs/21-2026-10-03-tablekeeper-four-stages` | Four-stage run on the other track, in a scratch room | 2026-10-03, 10:23 to 12:00 UTC | All four Tablekeeper stages accepted in about 96 minutes, 3 rejections. Supplied checks 120, 25, 7 and 6, all passing | Not submitted |
| Background-task test | `runs/22-2026-10-03-bgtasks-test` | Four-stage test run in a scratch room | 2026-10-03, 19:43 to 21:38 UTC | All four stages accepted in about 2 hours, 1 rejection. One background task ended in an error after its message had gone out; nothing was lost. A speed gain from background tasks is not shown | Not submitted |

Not archived, on purpose: "Run 4c" was staged on 2026-10-02 but never dispatched, so it contains no run.

Nothing else lives in a branch of its own. Run 5's Verifier check scripts are in that run's branch, in `verifier-check-scripts/`. The script used to compare the apps on the demo VM sits beside them, in `verifier-check-scripts/demo-compare/`.
