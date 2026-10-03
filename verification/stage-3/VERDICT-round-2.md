# Verdict — Pocketful stage 3 — PASS (after the map amendment of rows AA4 / AB4)

Rows: AA4 (amended), AB4 (new); all of V1-AC6, K1-U4, A1-J6 rerun · Revision: 9dcc200f61001f800d2aa8248df03da636f36c0f ·
Files: stage-3/app/handlers/statement.py, stage-3/app/snapshot.py, stage-3/app/store.py, stage-3/RUN.md,
stage-3/tests/test_corrections.py inspected (diff from 3a39ddf); verification/stage-3/ written ·
Command: deliver3.py (checks3.py incl. AB4-snapshots-survive-import, ui.py), harness --stage 3 normal and --mode isolated,
Implementer's tests · Expected / actual: no difference found · Repro: n/a · Next: Implementer reports the revision to the Architect.

**PASS** for revision 9dcc200f61001f800d2aa8248df03da636f36c0f. The earlier PASS on 3a39ddf was given against a map
row (AA4) the Architect has since corrected; this verdict replaces it.

## The amended requirement — met

Check `AB4-snapshots-survive-import` (added to my list when the amendment arrived, before this revision existed): a
snapshot token issued before `GET /_test/export`, followed by a later payment and a correction, pages the identical
frozen result (entries, opening, closing, has_more, page by page; also a windowed snapshot) after `POST /_test/import`
— in the same container after its state was replaced, after a repeated import, after a re-export and import, after a
rejected import, and in a second stage-3 container. A token issued on the source after the export, and a token issued
on the destination before the import, answer 404; another user's imported token answers 404 and works for its owner;
`from`/`to` with an imported token is 422; a reset clears imported tokens; export and import took well under 10 s.
Result: passed.

## Regression run on this revision

Tree clean at the revision before and after. Diff from 3a39ddf read: snapshots exported as `state.statement_snapshots`
and validated on import; entries stored as compact rows; memory bound raised; one comment; RUN.md; new tests. No other
code changed, UI untouched.

| Run | Result |
|---|---|
| deliver3.py delivery checks | 13 of 13 passed (`git diff 172a3180 -- stage-1` and `git diff c59be33b -- stage-2` empty) |
| checks3.py (stage-1 + stage-2 lists + 14 stage-3 checks) | 87 of 87 passed, 5123 requests, 0 responses >= 500 |
| ui.py at 375 and 1280 px | 30 of 30 passed |
| Supplied `--stage 3 --out ../band-work/checks/verifier-s3-r2` | stages 1, 2, 3: pass (stage 4: fail, not built) |
| Supplied `--mode isolated --out ../band-work/checks/verifier-s3-r2-isolated` | stages 1, 2, 3: pass |
| Implementer's tests in a `git archive` copy | API 120 OK (1 skipped); browser 24 OK |

Import of real stage-1 and stage-2 exports (no snapshots) still passes (AB1). V4 unchanged: no refund or batch code.

## Notes (do not block)

1. Snapshot memory bound is now 50 000 snapshots or 600 000 stored rows; beyond it the oldest tokens are dropped and
   would answer 404. The specification states no limit on stored records. Figure: more than 50 000 statement reads, or
   600 000 frozen rows, between two resets.
2. Export now carries every live snapshot, so its size grows with statement reads; the Implementer measured 400 000
   rows at 0.71 s export / 0.99 s import. I did not measure sizes beyond my list (tens of snapshots).
3. Unchanged from the first verdict: unencoded `+` in an instant accepted; statement `from` after `to` is 422;
   legacy voided authorizations import as having held nothing; stage-1/2 carry-overs; historical reads are
   O(user's payments + all authorizations).

## Remaining risk I could not test

- The harness ships only part of the judging tests.
- Large histories, many snapshots and long runs were not measured by me.
- Timing was measured on this host, not the judge's.
