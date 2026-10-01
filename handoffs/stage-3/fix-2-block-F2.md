@vibhor15/nightshift-implementer STAGE 3 — second BLOCK routed by the Architect: one finding to fix in `stage-3/` (revision `1c4e50af9dc62cbc5c04cff621e4169b07b42151`). F1 is confirmed fixed. The task, the three specifications and the three acceptance maps of my 13-part stage-3 handoff (plus row AC12) remain in force; this message is self-contained for the change. Full verdict text: `/home/ubuntu/nightshift-claude-run-2/band-work/checks/verdicts/stage-3-1c4e50af9dc62cbc5c04cff621e4169b07b42151.md`.

## Finding F2 (must fix) — an instant equal to the client's current time is refused as "in the future"

- Clauses: stage 3 corrections, "effective time is an RFC 3339 instant not later than now. Invalid input is 422"; stage 3 "Payment timestamps", only "a seeded `created_at` in the future gives 422".
- Cause: "now" comes from `Date.now()`, truncated to whole milliseconds, and is compared exactly with a client instant that carries microseconds. A request that arrives in the same millisecond its timestamp was taken is judged up to 1 ms in the future. Places: `stage-3/src/ledger.js:325` (`effNs > msToNs(clockMs(s))`) and `stage-3/src/fixture.js:143` (`ns > resetNs`).
- Reproduction (Verifier's, standard library only, resets state): `BASE=127.0.0.1:<port> python3 /home/ubuntu/nightshift-claude-run-2/band-work/checks/s3-ver-repro-now.py`. With `datetime.now(timezone.utc).isoformat()` instants: `POST /payments/{id}/corrections` with `effective_at` = client now — 54 accepted, 46 refused 422 of 100; `POST /_test/reset` with a seeded payment `created_at` = client now — 56 accepted, 44 refused of 100. Expected: 100 accepted each. The same instants truncated to whole milliseconds are all accepted.

## Required change (new acceptance-map row AC13, in `acceptance/stage-3.md`)

| # | Requirement | Check |
|---|---|---|
| AC13 | "Not later than now" is judged against the END of the service's current clock tick, because the service clock reads whole milliseconds while clients send microseconds: an instant t is accepted iff t < (`Date.now()` + 1) ms. Applies to a correction's `effective_at` and to a seeded payment `created_at` (and any other "not in the future" rule). An instant 2 ms or more ahead of the real clock is still refused. Default read bounds follow the same rule: a read without `as_of`/`to` includes every movement effective before the end of the current tick, so a correction accepted with `effective_at` = client-now is visible to the very next default read. Stamps the service ISSUES stay at the plain clock reading (row AC12) | O: 300 corrections and 300 resets with `datetime.now(timezone.utc).isoformat()` instants → all accepted; +5 ms and +1 h → 422; correct with effective = client now then `GET /me` and `GET /statement` at once show it |

How:

1. One helper for the upper bound, e.g. `nowBoundNs() = (Date.now() + 1) ms in ns`, and the rule `t < nowBoundNs()` for "not later than now". Use it at `ledger.js:325` and for the seeded `created_at` check in `fixture.js` (take the bound from the clock at validation time, not from the reset stamp).
2. Check every other place that compares a client-supplied or stored instant with the service's "now" and make it consistent: the default `as_of` (when only `known_at` is given), the default `to` of a statement and the instant a snapshot freezes for it, and the boundary set of the historical-overdraft check. A revision accepted under rule 1 may have `effective_at` up to just under 1 ms after its own `recorded_at`; no default read may miss it for that reason, and a snapshot taken after it must contain it. Reads with no `known_at` remain ordered by `kseq` (row AC11).
3. Hold expiry keeps the plain reading: expired iff `expires_at` ≤ `Date.now()`.
4. Stamps issued by the service are unchanged from `1c4e50a` (row AC12).
5. Add tests for row AC13 (its Check column) and re-run both of the Verifier's reproduction scripts (`s3-ver-repro-now.py`, `s3-ver-repro-clock.py`).

## Then

Re-run everything: Node tests, browser tests, docker smoke and both upgrade scripts, and the harness in host mode and isolated mode with NEW `--out` names (`s3-impl-04`, `s3-impl-final-03`). Expected: stages 1–3 pass, `stage 4: fail`, `claimed stage: 3 on the shipped checks`. Confirm `git diff 95f1446015263a7fb1bd5983adf3a627a97ab219 -- stage-1 stage-2` is empty. Commit as Nightshift Implementer (no amend, no rebase), tree clean, and send the Verifier a complete updated handoff for the new full hash (task, three specifications, three maps including rows AC12 and AC13, commands and counts, this change). Ask it to write its verdict to `/home/ubuntu/nightshift-claude-run-2/band-work/checks/verdicts/stage-3-<full hash>.md` as well as sending it in the room. Address the revision announcement to me too. Nothing left running when you send.
