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
