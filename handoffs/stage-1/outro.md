
## What each seat does now

Implementer:
1. Build the service in /home/ubuntu/nightshift-claude-run-6/band-work/result/stage-1/ to the specification (parts 1 to 3) and every row of the acceptance map (parts 4 and 5). Language, framework and storage are your choice within rows A1..A5; state need not survive a restart, so an in-process store with one atomic commit point is acceptable and makes rows B9..B11, I7, K5, K6 and J1..J3 straightforward. Record the choice and its reason in RUN.md.
2. Rows marked [D] are the Architect's resolution of an open choice. Implement them as written. If you find evidence in the specification that a [D] row is wrong, say so in your report with the section and line; do not silently diverge.
3. Write automated tests for the rows the supplied checks do not reach (concurrency at 50 in flight, idempotency ordering, export/import across containers, settlements, precedence of errors) and run them. Run the harness command above in host mode and in isolated mode.
4. Commit under your own seat identity in the result repository on branch main. Do not rewrite history and do not push.
5. Report in this room to both the Architect and the Verifier, starting with the evidence header: the full commit hash, files touched, each command you ran with its result (harness --out directory and final lines), any row you could not satisfy, and any [D] row you dispute.

Verifier:
1. While the Implementer builds, prepare your checks from the specification and the acceptance map: a probe plan (and scripts, if you want them, outside stage-1/, for example under /home/ubuntu/nightshift-claude-run-6/band-work/result/verification/stage-1/) for every row marked P or I. Do not edit anything under stage-1/.
2. When the Implementer reports a committed revision, verify that exact full revision at the head of the repository: build from a clean image by following RUN.md, run the harness in host mode and in isolated mode with new --out directories, run your own probes, and inspect the source for rows marked I.
3. Report a verdict to the Architect and the Implementer, starting with the evidence header: PASS, BLOCK or INCONCLUSIVE for that full revision, with every command and its result, and for each finding the row, expected and actual, and the smallest reproduction. Any unmet row is blocking unless you show the specification does not require it.

END OF STAGE 1 HANDOFF (part 5 of 5, final).
