# Stage 3 — Verifier check list (Tablekeeper)

Derived from `tablekeeper/spec/stage-3.md` (sections named by their headings) and the stage-3
acceptance map incl. its Decisions, before the implementation was read.
Scripts: `run3.sh`, `probe3.py` (ids P3.*); earlier lists rerun unchanged (`stage-1/probe.py`,
`stage-2/probe2.py`, `stage-2/ui_probe.py`) with `revision` ignored in their equality checks.
"NOTE" = observation where the spec is silent; never blocks.

## Delivery / earlier stages
- D.1 [S3-D] `stage-3/` builds clean from a git export; RUN.md command works; runs under `--cpus 2 --memory 2g` on a no-outbound network; default port.
- D.2 [N3a] `stage-1/` = a8301bb and `stage-2/` = 0d321ce unchanged; stage-4 suite fails on `stage-3/`; `/restaurants/{id}/replans`, `/series/{id}/amend` absent; `restaurant_revision` in no response (P3.N*).
- D.3 [N3b] harness `--stage 3` host and isolated: suites 1–3 pass, none skipped.
- S0 [S3-0] whole stage-1 list (392) and stage-2 API list (98) and browser list (97) against the stage-3 image.

## Availability explanations (P3.EX*)
- EX1 `explain` = `false`, `1`, empty, `TRUE`, `yes` → 422; `true` → 200; absent → no `explain` key in any slot.
- EX3/EX4 every table once in fixture order with `policy_version`, `available`, rules `capacity` then `no_overlap`, each independent (capacity-only, overlap-only, both false, both true); available ids = `available_table_ids`.
- EX5 closed day `slots: []`; party larger than every table: every slot present with full explain, all unavailable.
- EX6 `policy_version` and capacity rule follow the policy selected for the date.

## History and decision (P3.HI*, P3.DE*)
- HI1 owner 200 `{reference, entries}`; other user, manager, no token, unknown reference → 404 `not_found`; cancelled booking keeps history.
- HI2 `seq` 1..n consecutive; `at` RFC 3339 with offset, non-decreasing.
- HI3 `created` has `table_id`, `starts_at_local`, `party_size` in that order, `from: null`.
- HI4 `changed` lists only changed fields in fixed order with from/to; PATCH with current values and `PATCH {}` → 200, no entry, same revision.
- HI5 `cancelled` has `changes: []`; repeated cancel adds nothing.
- HI6 replay of create records nothing.
- HI7 each entry has resulting `revision` and full `accepted_terms`; earlier entries keep earlier terms after an amendment under a new policy.
- HI8 pair creation → `table_ids` null → pair (declared order even when sent reversed); pair↔single change → `table_ids` with complete lists; single→single → `table_id`; reversed same pair is a no-op.
- DE1 decision `{reference, revision, accepted_terms}` current, also after cancel; same 404 rule.

## Policies (P3.PO*)
- PO1 `manager_user_ids` wrong type → 400; absent = none.
- PO2 401 no token; 404 unknown restaurant; 403 `forbidden` non-manager (also restaurant with no managers); key missing 400; replay 200 identical; different body 409; failed key reusable; 20 concurrent identical → one 201.
- PO3 invalid matrix → 422, no version consumed: each field missing; `effective_from` impossible date / wrong format; slot and duration 0, 1441, string, boolean, float; cutoff −1, 10081, boolean; hours duplicate weekday, closes ≤ opens, bad weekday, not a list; capacities missing table, extra table, 0, 101, string, boolean. Boundaries accepted: slot 1 and 1440, duration 1 and 1440, cutoff 0 and 10080, capacity 1 and 100.
- PO4 201 = supplied fields + `policy_version` 1, 2, …; versions gap-free after failures, replays and 20 concurrent distinct publications; unknown fields ignored.
- PO5 `GET …/policies` public, publication order, no policy 0; unknown restaurant 404.
- PO6 restaurant detail unchanged by publications.
- PO7 selection: greatest `effective_from` ≤ date; tie → greatest version; none → 0; later-published earlier-dated policy; past effective date.
- PO8 availability grid/hours/duration/capacities and `available_options` capacity use the selected policy; booking validation (grid, hours, capacity, `ends_at`) too; occupancy uses each booking's stored interval.
- PO9 publication changes no existing booking, `ends_at`, terms, revision, history.
- PO10 manager gets 404 on a diner's reservation, history, decision, series.

## Accepted terms and revisions (P3.TE*)
- TE1 create/get/list/cancel/PATCH/moves/series responses carry `revision` and `accepted_terms` (six fields, no `effective_from`); policy 0 terms from the fixture.
- TE2 seeded booking: revision 1, policy 0; replay returns original revision and terms after an amendment.
- TE3 cancel uses the accepted cutoff (dynamic, near now): booking accepted with cutoff 30 stays cancellable after a cutoff-600 policy; booking accepted with cutoff 600 stays locked after a cutoff-0 policy; cancel +1 revision, repeat +0.
- TE4 real amendment: old accepted cutoff first, then all resulting fields against the resulting date's policy; terms and `ends_at` replaced, revision +1.
- TE5 no-op keeps terms/end/revision; on cancelled → 409 `reservation_cancelled`; past cutoff → 409 `cutoff_passed`.
- TE6 failed amendment (resulting start off the new policy's grid) changes nothing.
- TE7 `expected_revision`: match → 200; mismatch → 409 `stale_revision` (also on a past-cutoff booking and with invalid other fields); 0, −1, string, boolean, float → 422.
- TE8 20 concurrent real PATCHes with one `expected_revision` → exactly one 200, others 409 `stale_revision`.

## Series (P3.SE*)
- SE1 401; key missing 400; replay 200 identical; different body 409; unknown fields ignored.
- SE2 `count` 1, 13, string, boolean, float, missing → 422; `interval_weeks` 0, 5, boolean, missing → 422; 2/12 and 1/4 accepted.
- SE3 unknown / other owner's anchor → 404; cancelled → 409 `reservation_cancelled`; anchor or generated occurrence already in a series → 409 `already_in_series`; past anchor → 409 `cutoff_passed`.
- SE4 occurrence 0 = anchor unchanged (GET, history, create replay); occurrence i on date + i×interval×7 at the same clock time, same party and tables (single and pair).
- SE5 each occurrence takes its date's policy (terms version, `ends_at`); spring-forward gap → 422 `invalid_local_time` for the whole adoption; repeated hour → first occurrence; first failing index decides the error.
- SE6 failed adoption leaves no reservations, no occupancy, key reusable.
- SE7 201 shape, indices in order, distinct references, generated revision 1 with `created` history, listed, occupying.
- SE8 `GET /series/{id}` current state; other user, no token, unknown id → 404.
- SE9 real PATCH → `exception: true` permanent, series revision +1; no-op and failed PATCH change neither.
- SE10 cancel → series revision +1, occurrence kept, not an exception; repeat nothing; anchor cancel leaves siblings.
- SE11 replay → original response after later changes; nothing changes.

## Moves (P3.MO*)
- MO1 per-move `expected_revision` mismatch → 409 `stale_revision`, invalid → 422; change adopts the resulting date's policy.
- MO2 changed booking +1 revision and one `changed` entry; no-op item untouched; failure leaves all unchanged.
- MO3 two occurrences of one series changed in one batch → series revision +1 once, both exceptions; failed batch and replay change nothing.

## Upgrade and export (P3.UP*)
- UP1 exports of accepted stage-1 and stage-2 containers import (204); tokens, logins, references, receipts (replayed unchanged) valid; imported reservations show revision 1, policy-0 terms, history starting with `created`; adoption of an imported reservation works; browser upgrade checks (stage-2 X2/X3) pass stage-1 → stage-3 and stage-2 → stage-3.
- UP2 stage-3 export/import: policies, versions, terms, revisions, histories, series, receipts of all four paths preserved; version and seq counters continue; rejected import changes nothing.

## Concurrency (P3.CC3)
- CC3 4 rounds × 50 in flight (book, PATCH, cancel, series, policy publication): no 5xx, no overlapping confirmed bookings, policy versions 1..n, every history `seq` 1..k with last revision = reservation revision.

## Added while verifying round 1 (same clauses, further cases)
- P3.PO8j [PO8] a policy that drops a weekday closes that weekday from its effective date.
- P3.SE5f [SE5] an occurrence on a day closed by its date's policy rejects the adoption (422 `outside_opening_hours`).
- P3.SE3g [SE3, CC3] 10 concurrent adoptions of one anchor → one 201, nine 409 `already_in_series`.
- P3.EX3c [EX3] a pair booking makes `no_overlap` false on both members.
- P3.HI8e [HI8, MO2] a move from a pair to a single records `table_ids`.
- Stage-1 check P2.3e on stage 3 accepts 400 as well as 404 (stage-3 map decision 2 parses the body before the 404).
