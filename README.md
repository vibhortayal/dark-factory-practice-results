# Nightshift Factory: every run, and what each one taught us

This repository keeps every run Team Nightshift made while building its Dark Factory for the Band hackathon (Pocketful track). There is one branch per run, numbered in the order the runs happened. **Run 7 (branch `runs/20-2026-10-02-run-7-submitted`) is the run we submitted**; its public repository is `vibhortayal/nightshift-pocketful`. Every other branch is a practice run, a rehearsal or a test.

Each run changed one thing in the factory (its seat instructions, a setting, or the track) and watched what happened. Below, every run is told the same way: what changed, why, what happened, what we concluded, and what we did next. The same text opens each branch's `README.md` and `FACTORY.md`; below it, the branch keeps the run's own files and history unchanged.

## The runs at a glance

| # | Date | Run | Scope | Outcome |
|---|---|---|---|---|
| [01](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/01-2026-09-28-practice-r1) | Sep 28 | [Practice run R1](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/01-2026-09-28-practice-r1) | Stage 1 only, practice | Stage 1 built, with human corrections |
| [02](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/02-2026-09-29-practice-r2) | Sep 29 | [Practice run R2](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/02-2026-09-29-practice-r2) | Stage 1 only, practice | Stage 1 built, with outside help |
| [03](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/03-2026-09-29-practice-r3) | Sep 29 | [Practice run R3](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/03-2026-09-29-practice-r3) | Preflight, practice | Blocked early |
| [04](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/04-2026-10-01-rehearsal-1) | Oct 1 | [Rehearsal 1](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/04-2026-10-01-rehearsal-1) | Stage 1 only | Stage 1 accepted in 49 min; one restart |
| [05](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/05-2026-10-01-run-2) | Oct 1 | [Run 2](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/05-2026-10-01-run-2) | All four stages | 4 stages in 4 h 08; one restart |
| [06](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/06-2026-10-01-run-3) | Oct 1 | [Run 3](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/06-2026-10-01-run-3) | All four stages | 4 stages; 4 h 37 stall, one restart |
| [07](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/07-2026-10-01-stage1-test-run3-text) | Oct 1 | [Stage-1 test on the Run 3 text](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/07-2026-10-01-stage1-test-run3-text) | Stage 1 test | Stopped after first BLOCK |
| [08](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/08-2026-10-01-stage1-test-candidate-a) | Oct 1 | [Stage-1 test: fewer, larger messages](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/08-2026-10-01-stage1-test-candidate-a) | Stage 1 test | Spec left out of handoff; withdrawn |
| [09](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/09-2026-10-01-stage1-test-full-text-parts) | Oct 1 | [Stage-1 test: fewer parts, full text kept](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/09-2026-10-01-stage1-test-full-text-parts) | Stage 1 test | Stopped before a verdict |
| [10](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/10-2026-10-01-run-4) | Oct 1 | [Run 4](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/10-2026-10-01-run-4) | All four stages | Clean; stage 1 never accepted (6 BLOCK verdicts) |
| [11](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/11-2026-10-01-run-4b) | Oct 1 | [Run 4b](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/11-2026-10-01-run-4b) | All four stages | Clean; stage 1 never accepted (10 BLOCK verdicts) |
| [12](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/12-2026-10-02-stage1-test-pr52-28df31b9) | Oct 2 | [Stage-1 test: bounded Verifier](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/12-2026-10-02-stage1-test-pr52-28df31b9) | Stage 1 test | Stage 1 in 30 min, 1 BLOCK |
| [13](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/13-2026-10-02-stage1-test-pr52-590afd18) | Oct 2 | [Stage-1 test: graded findings](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/13-2026-10-02-stage1-test-pr52-590afd18) | Stage 1 test | Stage 1 in 28 min; real faults let through |
| [14](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/14-2026-10-02-stage1-test-pr52-f6fc48a3) | Oct 2 | [Stage-1 test: tightened grading](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/14-2026-10-02-stage1-test-pr52-f6fc48a3) | Stage 1 test | Stage 1 in 43 min, 1 BLOCK |
| [15](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/15-2026-10-02-run-5) | Oct 2 | [Run 5](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/15-2026-10-02-run-5) | All four stages | Clean; 4 stages in 11 h 20, 6 BLOCK verdicts |
| [16](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/16-2026-10-02-stage1-test-pr53-643e2307) | Oct 2 | [Stage-1 test: simpler set](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/16-2026-10-02-stage1-test-pr53-643e2307) | Stage 1 test | Stage 1 in 53 min, 2 BLOCK verdicts |
| [17](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/17-2026-10-02-run-6) | Oct 2 | [Run 6](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/17-2026-10-02-run-6) | All four stages | Clean; 4 stages in 2 h 33, 2 BLOCK verdicts |
| [18](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/18-2026-10-02-stage1-test-pr54-pocketful) | Oct 2 | [Stage-1 test: final text on Pocketful](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/18-2026-10-02-stage1-test-pr54-pocketful) | Stage 1 test | Stage 1 in 42 min, 1 BLOCK |
| [19](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/19-2026-10-02-stage1-test-pr54-tablekeeper) | Oct 2 | [Stage-1 test: final text on Tablekeeper](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/19-2026-10-02-stage1-test-pr54-tablekeeper) | Stage 1 test, other track | Stage 1 in 33 min, 0 BLOCK verdicts |
| [20](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/20-2026-10-02-run-7-submitted) | Oct 2 | [Run 7: the submitted run](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/20-2026-10-02-run-7-submitted) | All four stages | **Submitted.** Clean; 4 stages in 2 h 27, 4 BLOCK verdicts |
| [21](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/21-2026-10-03-tablekeeper-four-stages) | Oct 3 | [Tablekeeper, all four stages](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/21-2026-10-03-tablekeeper-four-stages) | All four stages, other track | 4 stages in about 1 h 37, 3 BLOCK verdicts |
| [22](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/22-2026-10-03-bgtasks-test) | Oct 3 | [Background-task test](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/22-2026-10-03-bgtasks-test) | All four stages | 4 stages in about 2 h, 1 BLOCK |

## How the factory changed, run by run

### [01. Practice run R1](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/01-2026-09-28-practice-r1) (Sep 28, stage 1 only, practice)

- **What changed from the previous run:** First attempt. A small band of agent seats was given Pocketful stage 1 with early practice instructions.
- **Why:** To find out whether agent seats could build anything useful at all.
- **Result:** Stage 1 was built, but only with several human corrections along the way. They are listed in `PRACTICE-LEARNINGS.md` in this run.
- **Conclusion:** Seats can build the service, but this set-up needed a person to keep it on track.
- **What we did next:** Started again on a fresh repository with stricter validation rules (R2).
- **Seats:** Early practice seats (not recorded in the branch).

### [02. Practice run R2](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/02-2026-09-29-practice-r2) (Sep 29, stage 1 only, practice)

- **What changed from the previous run:** A fresh repository, three seats on OpenCode, and stricter rules for money values and imported data.
- **Why:** R1 showed the band could build, but let invalid data through and needed help.
- **Result:** Stage 1 was built after fixes for failing checks, with outside help again.
- **Conclusion:** Better results, but still not a run that worked on its own.
- **What we did next:** A short preflight of the next set-up (R3).
- **Seats:** Three seats on OpenCode, each on Claude Haiku.

### [03. Practice run R3](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/03-2026-09-29-practice-r3) (Sep 29, preflight, practice)

- **What changed from the previous run:** A preflight of the next practice set-up.
- **Why:** To check the set-up before committing to a longer run.
- **Result:** Blocked early. One commit.
- **Conclusion:** The practice set-up was not going to give a clean, unattended run.
- **What we did next:** Moved to three Claude Code seats in Band, on a dedicated cloud server (Rehearsal 1).
- **Seats:** Early practice seats (not recorded in the branch).

### [04. Rehearsal 1](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/04-2026-10-01-rehearsal-1) (Oct 1, stage 1 only)

- **What changed from the previous run:** New platform: three Claude Code seats (Architect, Implementer, Verifier) talking in a Band room, with new seat instructions (mandates).
- **Why:** Stronger models and a set-up we could control and repeat.
- **Result:** Stage 1 accepted in 49 minutes, all 147 supplied checks passing. One restart: a background task failed and took the Verifier's verdict with it.
- **Conclusion:** The three seats can deliver a stage on their own. Background tasks can silently lose a message.
- **What we did next:** Added a written rule against background tasks, and told the Architect to wait for replies inside its turn (Run 2).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [05. Run 2](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/05-2026-10-01-run-2) (Oct 1, all four stages)

- **What changed from the previous run:** All four stages for the first time. The mandates gained a rule against background tasks and an instruction for the Architect to wait for replies inside its turn.
- **Why:** To fix Rehearsal 1's lost verdict and attempt the whole task.
- **Result:** All four stages accepted in 4 h 08 min, but with one restart: while waiting inside its turn, the Architect could not see the Verifier's pass. Stage 1 was also accepted with a known small spec fault marked "advisory".
- **Conclusion:** A seat only sees new messages between turns, so waiting inside a turn blinds it. Letting faults through as "advisory" weakens the check.
- **What we did next:** Seats end their turn after every handoff; no waivers, any contradiction of the spec blocks; at most five fix rounds per stage; a self-check by the Implementer; an evidence header on every message (Run 3).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [06. Run 3](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/06-2026-10-01-run-3) (Oct 1, all four stages)

- **What changed from the previous run:** The Run 2 lessons above, all in the mandates.
- **Why:** To get a clean four-stage run with a stricter check.
- **Result:** All four stages accepted, but the Verifier's stage-3 pass was never posted: a background task failed, despite the written rule. The factory waited 4 h 37 min until the Verifier was restarted.
- **Conclusion:** A written rule is not enforcement. The background-task failure had to be removed at the source.
- **What we did next:** Switched background tasks off in the seats' settings, and tried shorter handoff messages on stage 1 first (runs 07 to 09).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [07. Stage-1 test on the Run 3 text](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/07-2026-10-01-stage1-test-run3-text) (Oct 1, stage 1 test)

- **What changed from the previous run:** Nothing in the mandates. A short check on stage 1 after Run 3.
- **Why:** To see the unchanged text on stage 1 before trying changes.
- **Result:** Stopped by the team after the first BLOCK.
- **Conclusion:** Not conclusive.
- **What we did next:** Tested a change to handoff size (run 08).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [08. Stage-1 test: fewer, larger messages](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/08-2026-10-01-stage1-test-candidate-a) (Oct 1, stage 1 test)

- **What changed from the previous run:** One added sentence asking seats to send fewer, larger handoff messages.
- **Why:** In Run 3 each handoff went out in 12 to 31 parts, and every part woke the other seat.
- **Result:** The Implementer read the sentence as permission to leave the specification out of its handoff. Stopped after the first BLOCK.
- **Conclusion:** One loose sentence can invite a shortcut. Withdrawn.
- **What we did next:** Tried the same idea with the full text still required (run 09).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [09. Stage-1 test: fewer parts, full text kept](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/09-2026-10-01-stage1-test-full-text-parts) (Oct 1, stage 1 test)

- **What changed from the previous run:** Fewer handoff parts, but each must still carry the full task and specification.
- **Why:** To keep the benefit of run 08 without its failure.
- **Result:** Stopped before a verdict.
- **Conclusion:** Not enough evidence to risk it in the clean attempt.
- **What we did next:** Ran the clean attempt on the unchanged Run 3 text, with background tasks off (Run 4).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [10. Run 4](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/10-2026-10-01-run-4) (Oct 1, all four stages)

- **What changed from the previous run:** Same mandates as Run 3. Background tasks switched off in the seats' settings.
- **Why:** To remove the failure that had cost Rehearsal 1 and Run 3 a message, and get a clean run.
- **Result:** Clean, with no human help, but stage 1 was never accepted: 6 BLOCK verdicts in 1 h 37 min. Each fix round the Verifier found one or two new, ever more unusual problems.
- **Conclusion:** The background fix held. But a Verifier with no limit on how deep it tests never finishes.
- **What we did next:** Repeated the run unchanged to rule out chance (Run 4b).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [11. Run 4b](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/11-2026-10-01-run-4b) (Oct 1, all four stages)

- **What changed from the previous run:** Nothing. Same mandates, same settings as Run 4.
- **Why:** To see whether Run 4's result was bad luck.
- **Result:** Clean, but stage 1 was never accepted: 10 BLOCK verdicts in 3 h 11 min. The findings moved to extreme inputs, such as a 60-million-digit number.
- **Conclusion:** Not luck. The mandates had to say how far the Verifier tests.
- **What we did next:** Bounded the Verifier and tried it on stage 1 (run 12).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [12. Stage-1 test: bounded Verifier](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/12-2026-10-02-stage1-test-pr52-28df31b9) (Oct 2, stage 1 test)

- **What changed from the previous run:** The Verifier tests at the sizes and loads the spec states and not beyond, writes its check list first, and reports every finding in one verdict. A fix round is one BLOCK verdict, and a build under review cannot be withdrawn.
- **Why:** Runs 4 and 4b never converged.
- **Result:** Stage 1 accepted in 30 minutes, with one BLOCK that listed all four findings at once.
- **Conclusion:** Bounding the Verifier works.
- **What we did next:** Tried a more lenient check: graded findings plus a short window of free testing (run 13).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [13. Stage-1 test: graded findings](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/13-2026-10-02-stage1-test-pr52-590afd18) (Oct 2, stage 1 test)

- **What changed from the previous run:** Findings graded on five levels, with only the top three blocking; 15 minutes of free testing on a stage's first build; later builds get a shorter fix check.
- **Why:** To keep the factory moving on minor issues and still catch real ones.
- **Result:** Stage 1 accepted in 28 minutes with no BLOCK, but real spec faults were graded as minor and let through.
- **Conclusion:** Too lenient.
- **What we did next:** Tightened the grading (run 14).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [14. Stage-1 test: tightened grading](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/14-2026-10-02-stage1-test-pr52-f6fc48a3) (Oct 2, stage 1 test)

- **What changed from the previous run:** Any server error or any case the spec names blocks; a minor finding must state the size it exceeded. The Verifier prepares its checks while the Implementer builds.
- **Why:** Run 13 passed real faults.
- **Result:** Stage 1 accepted in 43 minutes, one BLOCK, and real faults got a BLOCK.
- **Conclusion:** Ready for a full run.
- **What we did next:** Added one rule (a value over a stated limit always blocks) and ran all four stages (Run 5).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [15. Run 5](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/15-2026-10-02-run-5) (Oct 2, all four stages)

- **What changed from the previous run:** The bounded, graded mandates from runs 12 to 14.
- **Why:** First full run since the Verifier was bounded.
- **Result:** Clean. All four stages accepted in 11 h 20 min, 6 BLOCK verdicts, about $116 at list price. The app was the most thoroughly tested, but each stage was one large file, and the free testing and growing check lists made it slow.
- **Conclusion:** Bounded verification finishes, but this version was far too slow and over-engineered.
- **What we did next:** Simplified the mandates: no grading, no free testing, every check tied to a sentence of the spec (run 16).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

This branch also keeps the Verifier's own check scripts (`verifier-check-scripts/`), later used to compare the apps of several runs.

### [16. Stage-1 test: simpler set](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/16-2026-10-02-stage1-test-pr53-643e2307) (Oct 2, stage 1 test)

- **What changed from the previous run:** Grading and free testing removed. A finding either blocks or is a note. Every check names the spec sentence it tests. Limits are tested at the last allowed and first refused value. A fix that did not fix the fault gets a BLOCK at once.
- **Why:** Run 5 was too slow.
- **Result:** Stage 1 accepted in 53 minutes, two BLOCK verdicts.
- **Conclusion:** Works, with far less machinery.
- **What we did next:** Added a request for maintainable code and ran all four stages (Run 6).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [17. Run 6](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/17-2026-10-02-run-6) (Oct 2, all four stages)

- **What changed from the previous run:** The simpler set, plus one sentence asking the Implementer to split code into small modules.
- **Why:** Speed, and code another developer could maintain.
- **Result:** Clean. All four stages accepted in 2 h 33 min, 2 BLOCK verdicts, about $53. The code came out in small modules. A few edge cases slipped through, for example an amount like 1.00000000000000000001 read as 1.
- **Conclusion:** Four times faster than Run 5 and easier to maintain. But the Verifier's evidence stayed outside the repository, and the wording still read as written for a web service.
- **What we did next:** Neutral wording, the Verifier committing its evidence, and lighter fix handoffs, tried on stage 1 (run 18).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [18. Stage-1 test: final text on Pocketful](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/18-2026-10-02-stage1-test-pr54-pocketful) (Oct 2, stage 1 test)

- **What changed from the previous run:** Neutral wording; the Verifier commits its check list and verdicts to the repository; commits that only touch records need no new verdict; fix handoffs do not repeat the whole spec.
- **Why:** To put the evidence where judges can see it, and to make the factory clearly generic.
- **Result:** Stage 1 accepted in 42 minutes, one BLOCK, with the Verifier's evidence in the repository.
- **Conclusion:** Works.
- **What we did next:** Ran the same text, unchanged, on the other track (run 19).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [19. Stage-1 test: final text on Tablekeeper](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/19-2026-10-02-stage1-test-pr54-tablekeeper) (Oct 2, stage 1 test, other track)

- **What changed from the previous run:** Nothing in the mandates. Only the track changed, to Tablekeeper.
- **Why:** To show the factory is generic, not tuned to Pocketful.
- **Result:** Stage 1 accepted in 33 minutes with no BLOCK, all 120 supplied checks passing.
- **Conclusion:** The same factory builds a different app.
- **What we did next:** Ran all four Pocketful stages as the entry (Run 7).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [20. Run 7: the submitted run](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/20-2026-10-02-run-7-submitted) (Oct 2, all four stages)

- **What changed from the previous run:** Nothing. The text tested in runs 18 and 19.
- **Why:** The entry: one dispatch, no human help.
- **Result:** Clean. All four stages accepted in 2 h 27 min, 4 BLOCK verdicts, about $59.
- **Conclusion:** This is the submitted run.
- **What we did next:** Confirmed the factory on the other track at full length (run 21), and tested background tasks once more (run 22).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [21. Tablekeeper, all four stages](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/21-2026-10-03-tablekeeper-four-stages) (Oct 3, all four stages, other track)

- **What changed from the previous run:** Nothing in the mandates. All four stages of Tablekeeper.
- **Why:** Run 19 covered stage 1 only.
- **Result:** All four stages accepted in about 1 h 37 min, 3 BLOCK verdicts.
- **Conclusion:** The factory carries a second, unseen app through every stage.
- **What we did next:** Tested whether background tasks would make it faster (run 22).
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

### [22. Background-task test](https://github.com/vibhortayal/dark-factory-practice-results/tree/runs/22-2026-10-03-bgtasks-test) (Oct 3, all four stages)

- **What changed from the previous run:** The rule against background tasks removed from the mandates, and background tasks allowed in the settings.
- **Why:** To see whether background tasks make the factory faster.
- **Result:** All four stages accepted in about 2 hours, one BLOCK. One background task ended in an error after its message had gone out, so nothing was lost this time.
- **Conclusion:** No clear speed gain: most of the time saved came from fewer BLOCK verdicts. The failure that lost messages before is still possible.
- **What we did next:** Kept background tasks off in the submitted factory.
- **Seats:** Three Claude Code seats: Architect and Verifier on Claude Opus, Implementer on Claude Sonnet.

## What the whole sequence shows

- **Settings beat sentences.** Twice a written rule against background tasks was broken; switching them off in the settings fixed it for good (runs 04, 06, 10).
- **A checker needs a stated limit.** With no limit on how deep it tests, the Verifier never finished (runs 10, 11). Tying every check to a sentence of the spec fixed that without letting faults through (runs 12, 16).
- **Simpler was faster and no worse.** The graded, free-testing version took 11 h 20 min (run 15); the simpler set took 2 h 33 min and 2 h 27 min (runs 17, 20).
- **The factory is generic.** The submitted mandates, unchanged, built the other track's app through all four stages (runs 19, 21).

The `video-demo/` folder on this branch is an early draft for the video, not run evidence.
