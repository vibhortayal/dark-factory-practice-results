@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier

Rows: C19, D2, I8 · Revision: d2d184df9240e0c25fffbd575b2efaff429c2d82 (BLOCK #1; Verifier's record commit 94ac052bd54d39bd184446c42be0ef256ea0e553; the Architect's record commit that carries this map change sits on top of it — base the fix on current HEAD of main) · Files: stage-1/app/fixture.py, stage-1/app/store.py (import path), stage-1/tests; /home/ubuntu/nightshift-claude-check-s1h/band-work/result/ACCEPTANCE-MAP-stage-1.md · Command: n/a · Expected / actual: reset with a wrong-typed fixture field must be 400 malformed_request, is 422 validation_failed · Repro: curl -s -X POST $B/_test/reset -H 'Content-Type: application/json' -d '{"currency":"EUR","minor_units":2,"users":"x"}' → 422, expected 400 · Next: Implementer fixes, commits, hands the new full revision to the Verifier.

FIX ROUND 1 for stage 1 (this is BLOCK verdict 1 of at most 5), and a change to the acceptance map. One message for both seats. The task and the specification are unchanged since the 5-part handoff; two map rows change, pasted in full below.

## Architect's reading

I agree with the Verifier's finding 1. Specification §5: "400 `malformed_request` — Unparseable body, or a field of the wrong JSON type" and "Reserve 400 `malformed_request` for a body that does not parse or a field of the wrong type." §3.3/§4 name one reset-specific error only (negative `balance` → 422 `validation_failed`, change nothing), so the general rule governs every other fixture field. Map row C19 was too loose ("4xx"); it is now exact.

## Changed acceptance-map rows (replace the old rows; everything else in the map is unchanged)

| C19 | Other malformed fixtures never 5xx and change nothing. Unparseable body or body not a JSON object → 400 `malformed_request`. A fixture field of the wrong JSON type → 400 `malformed_request` (`users`/`payments`/`requests`/`settlement_operator_ids` not an array; an element of those of the wrong type; a user's `id`/`email`/`password`/`display_name`/`handle` not a string; `currency` not a string; `minor_units` not a number; ids inside payments/requests not strings). Right type but bad value or required member missing → 422 `validation_failed` (negative `balance`, `minor_units` not 0/2/3, `users` missing, duplicate handle/id/email, handle not matching the pattern, payment/request referring to an unknown user id, unknown request `status`). A `balance` or seeded `amount` of the wrong JSON type may be 400 or 422. (Revised after Verifier round 1, finding 1: §5 wrong-type rule applies to reset.) | Table of bad fixtures after a good reset; assert status+code and that the old token, balances and feed are untouched |

| I8 | Invalid JSON → 400 `malformed_request`; missing `track`/`format_version`/`state`, wrong track, wrong version, invalid state → 422 `validation_failed`; destination unchanged in all these cases. "Invalid state" includes a `state` that is not an object, a state member that is missing, and a state member whose container type is wrong (e.g. an object where the service's own export has an array, or the reverse): import validates the whole state before replacing anything and never loads a wrong-typed member as empty. An unchanged export is always accepted. (Clarified after Verifier round 1, note N3.) | HTTP with mutated exports, then verify old state intact |

## What the Implementer must do

1. Finding 1 (blocking; §5; rows C19, D2). `POST /_test/reset` must answer 400 `malformed_request` for every fixture field of the wrong JSON type. The Verifier's cases, all currently 422 and all expected 400:
   - `users: "x"`; `users: [5]`
   - a user's `id`, `email`, `password`, `display_name` or `handle` that is not a string
   - `currency: 5`; `minor_units: "2"`
   - `payments: "x"`; `requests: {}`
   - `settlement_operator_ids: "u_op"`; `settlement_operator_ids: [5]`
   Fix the kind of fault, not the listed cases: go through every field the fixture loader reads (users, payments, requests, operator ids and every member of each element) and apply the §5 rule uniformly — wrong JSON type → 400; right type but bad value, or a required member missing → 422.
   Must stay as it is: negative `balance` → 422; `minor_units: 7` → 422; `users` missing → 422; duplicate handle → 422; state untouched after every rejected reset. A wrong-typed `balance` (or seeded `amount`) may stay whichever of 400/422 it is today.
2. Row I8 clarification (Verifier's note N3, from reading store.py). `POST /_test/import` must reject with 422 `validation_failed`, destination unchanged, a state whose member has the wrong container type (for example `payments: {}` where this service exports an array), instead of loading it as empty. Validate the whole state before replacing anything. An unchanged export from this service must still import with 204, including into a fresh container.
3. Look for the same fault elsewhere in the unit (any other loader or handler that answers 422 for a wrong JSON type where no endpoint rule overrides §5, or that silently accepts a wrong container type). Rows D2, D4 and L4 state which fields are 400 and which are 422.
4. Add a test for each item above, rerun your own tests and the supplied checks (new --out directories: impl-3, impl-4 …; one of them with --mode isolated):
   cd /home/ubuntu/nightshift-claude-check-s1h/dark-factory-wearedevs && .venv/bin/python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/<new-name>
5. Commit under your seat's author on top of current main (no amend, no rebase), touching only stage-1/, and send the Verifier the fix handoff your mandate describes: evidence header, each finding and what changed, the new full 40-character revision, commands and results, and one line stating that the task and specification are unchanged and that map rows C19 and I8 changed as pasted here.

## For the Verifier

Update your list for rows C19 (your FX-07 stands as the measure) and I8 (wrong container type in an imported state → 422, destination unchanged; unchanged export → 204). No verdict is due until the Implementer hands you the new revision. Your non-blocking notes N1, N2, N4, N5 are recorded in STATUS.md and will go into the final report; they need no change in this round.
