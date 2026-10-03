# Stage 4 — Verifier check list (Tablekeeper)

Derived from `tablekeeper/spec/stage-4.md` (sections "Seating changes after a table closure",
"Amend recurring reservations") and the stage-4 acceptance map incl. Decisions, before the
implementation was read. Scripts: `run4.sh`, `probe4.py` (ids P4.*), `ui4.py` (UI4.*); the earlier
lists are rerun on the stage-4 image (`stage-1` 392, `stage-2/probe2.py` 98, `stage-3/probe3.py`
without its "stage-4 absent" checks, `stage-2/ui_probe.py`). "NOTE" never blocks.

## Delivery / earlier stages
- D.1 [S4-D] clean build from a git export; RUN.md command; `--cpus 2 --memory 2g`, no outbound; default port.
- D.2 [N4a] `stage-1/` = a8301bb, `stage-2/` = 0d321ce, `stage-3/` = fcdb0a2 unchanged.
- D.3 [N4b] harness `--stage 4` host and isolated: suites 1–4 pass, none skipped.
- S0 [S4-0] stage-1, stage-2 (API and browser) and stage-3 lists against the stage-4 image; browser upgrade section from stage-1, stage-2 and stage-3 containers.

## Replan preview (P4.RP*, P4.O*)
- RP1 401 no token; 404 unknown restaurant; 403 non-manager; key missing 400; replay 200 same plan; different body 409.
- RP2 `from >= to`, no offset, garbage, wrong type, missing fields → 422; unknown table / other restaurant's table → 404; `table_id` wrong type → 400; `Z` instants accepted; unknown fields ignored.
- RP3 considered = confirmed bookings overlapping `[from,to)` half-open (ends at `from` / starts at `to` excluded, one minute of overlap included); cancelled and later bookings not considered.
- RP4 capacity under the booking's own accepted terms (policy published later must not be used); past booking still planned and moved (cutoff does not block).
- RP7 201 shape; closure echoed; assignments in reference order; `moved_count`, `unused_seats`; empty interval → empty plan.
- RP8 preview changes nothing (reservations, histories, availability, restaurant revision); infeasible → 409 `no_feasible_plan`, nothing changed, key reusable.
- RP6 at the stated limits (6 tables, 4 pairs, 6 considered) an answer within 5 s; 9 considered → plan or 422 `planning_limit`, within 5 s.
- O1 [RP3–RP5] oracle: 80 randomised scenarios (6 tables, 4 random pairs, 3–9 bookings incl. pairs, policies changing capacities and duration mid-way, cancelled bookings): service result equals my brute-force optimum for (moved, unused seats, rank vector in reference order), or `no_feasible_plan` exactly when infeasible.
- O2 [AP4, AP6] oracle: plans applied in those scenarios put every booking on its assigned tables with unchanged times/party/terms; second closures respect the first.

## Apply (P4.AP*, P4.RR*)
- AP1 401; 403 non-manager; 404 unknown restaurant; key missing 400.
- AP2 201 `{plan_id, restaurant_revision = preview + 1, reservations}` in reference order as ordinary responses.
- AP3 unknown plan / other restaurant's plan → 404; intervening revision → 409 `stale_plan`, nothing changed; replay 200 (also after later changes); other key → 409 `plan_already_applied`.
- AP4 moved booking: revision +1, `reassigned` entry with `table_ids` from/to, `plan_id`, revision, same terms; times identical; unmoved booking untouched; restaurant revision +1 once.
- AP5 closure removes the single and its pairs from exactly the overlapping slots; explain `no_overlap` false; create, pair create, PATCH, moves, series adoption onto it → 409 `table_unavailable`; before, after and other days bookable.
- AP6 a later plan never assigns a closed table.
- AP7 10 concurrent applies of two plans from one revision → one 201; one plan in effect; a write at another restaurant does not invalidate.
- AP8 repair moving series occurrences: each affected series revision +1 once; exception flags, references, dates, terms kept; other occurrences untouched.
- RR1 restaurant revision walk through every write kind, replay, failure, no-op and preview; separate counter per restaurant.
- UI4.AP9 browser: lookup shows the moved booking's new table; grid shows the closed table unavailable in overlapping slots, no combination with it, cell not clickable.

## Series amend (P4.SA*)
- SA1 401; other owner / unknown 404; key missing 400; replay 200 original after further edits and a cancel; different body 409.
- SA2 invalid `expected_revision`, `from_index` (−1, = count, boolean, string), `local_time` (24:00, 8:00, seconds, no colon, number, 19:60), missing fields → 422.
- SA3 mismatch → 409 `stale_revision`, also when the time is off the grid.
- SA4 indices ≥ from_index except cancelled and exception ones; original dates; references, party, tables kept.
- SA5 no-op keeps everything; real change adopts its date's policy (terms, end); off-grid / after-closing → ordinary codes; nonexistent local time → `invalid_local_time`; old accepted cutoff checked (anchor already started → `cutoff_passed`; needs a ~2 min wait).
- SA6 conflict with another booking → 409; non-occupancy error at a later index beats an occupancy conflict at an earlier one; overlap with own old slot allowed; applied closure → 409.
- SA7 failure changes nothing; failed key reusable.
- SA8 201 current series; changed occurrences revision +1 with a `changed` entry (`starts_at_local`); series and restaurant revision +1 once; no exception marks; all-no-op / empty eligible → 201 unchanged.
- SA9 12 concurrent amends from one revision → one 201, rest 409 `stale_revision`.

## Upgrade, export, load
- UP4 imports of real stage-1, stage-2, stage-3 containers: sessions, fields, original retries; stage-3: restaurant revision carried over, series receipt replays, amend on a series with an exception and a cancelled occurrence, replan moving the exception occurrence; stage-1/2: adoption + amend on imported bookings.
- UP5 stage-4 roundtrip: reservations, series, `reassigned` history, closure effects, both restaurant revisions; rejected import changes nothing; replan/apply/amend receipts replay; applied plan stays applied; pending plan applicable after import; second container.
- CC4 4 × 50 in flight (book, PATCH, cancel, series + amend, preview + apply): no 5xx, no overlap, no confirmed booking on a closed table inside its closure; histories seq 1..k = revision.

## Added while verifying round 1
- P4.SA4b [SA4, AP8] a series occurrence moved by a plan stays eligible for a series amend, keeps the plan's tables and its scheduled date.
- O1/O2 rerun with two further seeds, 200 scenarios each.
