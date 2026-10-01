@vibhor15/nightshift-implementer STAGE 4 — BLOCK routed by the Architect: one finding to fix in `stage-4/` (revision `adf7305a90371b9b3126aecb8c92b27aa7b141bf`). The task, the four specifications and the four acceptance maps of my 15-part stage-4 handoff remain in force; this message is self-contained for the change. Full verdict text: `/home/ubuntu/nightshift-claude-run-2/band-work/checks/verdicts/stage-4-adf7305a90371b9b3126aecb8c92b27aa7b141bf.md`.

## Finding F1 (must fix) — a statement snapshot saved on stage 3 is not returned in its original form on stage 4

- Clauses: stage 4 introduction, "Existing receipts and saved statements must remain available in their original form."; stage 4 batch corrections, "earlier snapshot tokens continue to page their frozen entries" and "A stage-4 service must accept exports produced by the same team's stages 1–3, retaining settlement membership, corrections and snapshots."; stage 3 "Stable statement pagination", a token "freezes the caller's selected revisions, window, balances, entries".
- Cause: snapshots are recomputed from history on every page read and rendered with the stage-4 payment shape, so each entry's `payment` of a snapshot taken on stage 3 gains `refund_of: null` (14 keys instead of 13). Balances, entries, revisions and timestamps are otherwise identical.
- Reproduction (Verifier's, standard library only, resets both services): `S3=127.0.0.1:<stage-3 port> S4=127.0.0.1:<stage-4 port> python3 /home/ubuntu/nightshift-claude-run-2/band-work/checks/s4-ver-repro-snapshot.py`. It makes two payments on stage 3, saves a statement, exports, imports into stage 4 and pages the same token. Expected: the stage-4 page is the same JSON value stage 3 returned.

## Required change (new acceptance-map row BA7, in `acceptance/stage-4.md`)

| # | Requirement | Check |
|---|---|---|
| BA7 | A statement snapshot saved by an earlier stage is returned in its ORIGINAL form: paging a token that was created on `stage-3` and imported into `stage-4` gives the same JSON value `stage-3` returned for that page (no `refund_of` key inside its entries' `payment`, nothing else added or removed). Each snapshot remembers the payment shape (state schema) it was saved under and is rendered in that shape. Snapshots created on `stage-4` use the stage-4 shape (with `refund_of`). Same principle as stored idempotent receipts | O: save on a real stage-3 container, export, import into stage-4, page with several limits/offsets, deep-compare; then run refunds and batches on stage-4 and compare again |

How:

1. Give every snapshot record a shape/schema marker. A snapshot imported from a schema-3 export gets marker 3; a snapshot created by `stage-4` gets marker 4; the marker is part of the stage-4 export and survives a stage-4 round trip (a schema-3 snapshot imported into stage 4, exported from stage 4 and imported into another stage 4 still pages in its original form).
2. Render a snapshot page through the same view function as today, then shape each entry's `payment` (and anything else stage 4 added to the page, if anything) according to the marker. Do not fork the computation; only the final rendering differs.
3. Compare the whole response body, not only the entries: `opening_balance`, `entries`, `closing_balance`, `has_more`, `snapshot`, and any echoed key must be the same JSON value as stage 3 returned for the same `limit`/`offset`.
4. Check that nothing else saved by an earlier stage changes shape after import: stored idempotent responses already replay exactly (the Verifier confirmed payments, settlements, captures, corrections). Add the snapshot case to `test/docker-upgrade.sh` or the Node upgrade test, with a real `stage-3` container.

## Then

Re-run everything: Node tests, browser tests, docker smoke and all upgrade scripts, the Verifier's reproduction script, and the harness in host mode and isolated mode with NEW `--out` names (`s4-impl-03`, `s4-impl-final-02`). Expected: stages 1–4 pass, `claimed stage: 4 on the shipped checks`. Confirm `git diff e1c0b553e15978b78259c734bf9c1dcf7fdad931 -- stage-1 stage-2 stage-3` is empty. Commit as Nightshift Implementer (no amend, no rebase), tree clean, and send the Verifier a complete updated handoff for the new full hash (task, four specifications, four maps including row BA7, commands and counts, this change). Ask it to write its verdict to `/home/ubuntu/nightshift-claude-run-2/band-work/checks/verdicts/stage-4-<full hash>.md` as well as sending it in the room. Address the revision announcement to me too. Nothing left running when you send.
