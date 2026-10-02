# Status

Run started: 2026-10-02T21:11Z (dispatch). Track: pocketful.

| Unit | State | Accepted revision | BLOCK verdicts | Elapsed | Notes |
|---|---|---|---|---|---|
| stage-1 | BUILDING (fix round 1) | - | 1 | 0h26 | BLOCK #1 on 03b5470f8967245daf840465472e91b6328c7e4f (verdict: `verification/stage-1/VERDICT.md` at 2ed121c): B1 reset 500 on wrong-typed fixture ids; B2 huge `limit` 400 not 422; B3 huge `amount` 400 not 422; B4 65520-char Idempotency-Key 431 HTML. Supplied checks isolated: stage 1 pass 147/147, claimed stage 1 (`../checks/s1-ver-01`). Verifier's own list 89/93. Routed to Implementer. |
| stage-2 | PLANNED | - | 0 | - | |
| stage-3 | PLANNED | - | 0 | - | |
| stage-4 | PLANNED | - | 0 | - | |

## Decisions

- Acceptance maps live in `acceptance/stage-N.md`. Rows marked **[reading]** are Architect
  choices where the specification is open, each with its reason.
- Check output goes to `../checks/<name>` (outside this repository), one new directory per run.
