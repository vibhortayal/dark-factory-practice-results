# Status

Run started: 2026-10-02T21:11Z (dispatch). Track: pocketful.

| Unit | State | Accepted revision | BLOCK verdicts | Elapsed | Notes |
|---|---|---|---|---|---|
| stage-1 | BUILDING (fix round 2) | - | 2 | 1h05 | BLOCK #1 on 03b5470f8967245daf840465472e91b6328c7e4f (`verification/stage-1/VERDICT.md`): B1 reset 500 on wrong-typed fixture ids; B2 huge `limit` 400; B3 huge `amount` 400; B4 65520-char key 431 HTML - all confirmed fixed in 38f2970. BLOCK #2 on 38f2970c0c1395ee1338ef6326948332609a45de (`verification/stage-1/VERDICT-round-2.md` at 39d831d): B5 absolute request target with malformed host (`http://[bad/health`) gives 500 (regression of the fix). Supplied checks isolated on 38f2970: stage 1 pass 147/147, claimed stage 1 (`../checks/s1-ver-02`); Verifier's list 93/94. Routed to Implementer. |
| stage-2 | PLANNED | - | 0 | - | |
| stage-3 | PLANNED | - | 0 | - | |
| stage-4 | PLANNED | - | 0 | - | |

## Decisions

- Acceptance maps live in `acceptance/stage-N.md`. Rows marked **[reading]** are Architect
  choices where the specification is open, each with its reason.
- Check output goes to `../checks/<name>` (outside this repository), one new directory per run.
