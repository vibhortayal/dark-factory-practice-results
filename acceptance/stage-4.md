# Stage 4 acceptance map (Tablekeeper — seating changes and recurring amendments)

Source: `dark-factory-wearedevs/tablekeeper/spec/stage-4.md` (stage-1..3 specs still apply).
Folder: `stage-4/` = copy of accepted `stage-3/` (rev fcdb0a2), extended.
"H" = harness (`--stage 4`, runs suites 1–4), "P" = Verifier HTTP probe, "B" = browser probe,
"R" = review, "O" = independent oracle (Verifier's own brute-force planner compared with the service).

| Row | Requirement | Check |
|---|---|---|
| S4-0 | All stage-1, stage-2 and stage-3 acceptance rows still hold for `stage-4/` (suites 1–3 pass; UI works) | H + rerun stage-1/2/3 probe sets and browser probes on the stage-4 image |
| S4-D | `stage-4/` own Dockerfile + RUN.md, clean build, `-e PORT`, no outbound network, stage-1 §2 limits (each request < 5 s incl. planning at the stated limits under --cpus 2) | build + run + timing |
| RP1 | `POST /restaurants/{id}/replans`: no token 401; unknown restaurant 404; non-manager 403; idempotency key required with §7 rules (missing 400, replay 200 original body, different body 409, failed key reusable) | H + P |
| RP2 | Body `{table_id, from, to}`; `from`/`to` are instants with explicit offsets (`Z` or `±HH:MM`; no bare local), `from < to`; invalid → 422 `validation_failed`; unknown table (or table of another restaurant) → 404; unknown fields ignored | P |
| RP3 | Considered = every confirmed booking at this restaurant whose `[starts_at, ends_at)` overlaps `[from, to)` (half-open, on any table); other bookings are fixed; cancelled bookings ignored | P + O |
| RP4 | Each considered booking keeps reference, owner, party size, start, end, accepted terms; is assigned a single or a declared pair with enough capacity under ITS OWN accepted terms (pair = sum); no conflict with fixed bookings, other assignments, previously applied closures or the proposed closure; diner cutoffs do not block; nothing cancelled or dropped | P + O |
| RP5 | Optimal plan minimises lexicographically: (1) number of bookings whose table set changes, (2) total unused seats over considered bookings, (3) vector of option ranks in ascending reference order (singles in fixture order from 0, then pairs in declared order) | O on randomised scenarios within limits |
| RP6 | Supports at least 6 tables, 4 pairs, 6 considered bookings within 5 s; larger inputs may return 422 `planning_limit` (never 5xx or timeout) | P timing |
| RP7 | 201 `{plan_id, restaurant_revision, closure:{table_id, from, to}, assignments:[{reference, table_ids, changed}], moved_count, unused_seats}`; assignments = every considered booking in ascending reference order; `moved_count` = number changed; `unused_seats` = total | H + P |
| RP8 | Preview stores only a plan: no closure, occupancy, reservation revision, history, series or restaurant revision change. No feasible plan → 409 `no_feasible_plan`, nothing changes, key reusable | P |
| RR1 | Restaurant revision: 0 after reset; +1 per successful new booking, real amendment, cancellation, policy publication, plan application; once per whole moves batch, series adoption, series amendment (if anything changed); no-ops, failures, previews, replays never; per restaurant | P (observe via preview `restaurant_revision`) |
| AP1 | `POST /restaurants/{id}/replans/{plan_id}/apply` body `{}`: manager only (401/404/403 as RP1), idempotency key required | H + P |
| AP2 | 201 `{plan_id, restaurant_revision (new), reservations:[ordinary responses of every considered booking in reference order]}` | H + P |
| AP3 | Unknown plan or plan of another restaurant → 404; any intervening restaurant revision → 409 `stale_plan`, nothing changes; plan already applied under a different key → 409 `plan_already_applied`; replay of the successful key → 200 original response even after later changes | P |
| AP4 | Atomic: closure + all assignments together. Each moved booking: revision +1 once, one history entry `event: "reassigned"` with a `table_ids` change (complete before/after lists) and `plan_id`, plus resulting `revision` and unchanged `accepted_terms`; times and terms identical. Unmoved bookings gain nothing. Restaurant revision +1 once for the whole plan | P |
| AP5 | After apply the closure excludes singles and pairs containing the table from availability for overlapping slots (`available_table_ids`, `available_options`); `explain` reports `no_overlap: false`; creates, PATCHes, moves, series adoption/amend onto it → 409 `table_unavailable`; outside `[from,to)` the table is bookable | P |
| AP6 | Later plans respect previously applied closures | P + O |
| AP7 | Concurrent applications never leave partially moved bookings; of two concurrent applies of plans from one revision exactly one succeeds (other `stale_plan`); a closure/write at another restaurant does not invalidate this plan | P |
| AP8 | Seating repairs may move series occurrences: exception flags, scheduled dates, identities, terms preserved; each affected series revision +1 once per application if at least one member moved | P |
| AP9 | Existing availability, confirmation and lookup screens reflect an applied plan (lookup shows new table labels; grid shows closed table unavailable) | B |
| SA1 | `POST /series/{series_id}/amend`: owner-only idempotent write; no token 401; unknown / other owner's series 404; key rules of §7; replay 200 original even after later edits/cancels | H + P |
| SA2 | Body `{expected_revision, from_index, local_time}`: revision positive integer; from_index integer 0..count-1; local_time exactly `HH:MM` 00:00..23:59; booleans invalid; missing/invalid → 422; unknown fields ignored | P |
| SA3 | Mismatched series revision → 409 `stale_revision` before any occurrence's cutoff or booking validation | P |
| SA4 | Considers indices >= from_index, excluding cancelled and exception occurrences; changes clock time on each occurrence's original scheduled local date; keeps reference, owner, party size, current table selection | P |
| SA5 | Identical resulting fields = no-op (keeps terms, revision, history). Each real change: old accepted cutoff first, then adopts the policy of the resulting start date (grid, hours, duration, capacity, DST rules) | P |
| SA6 | Result must not conflict with unchanged occurrences, other bookings or applied closures; changed occurrences may take each other's old slots. Non-occupancy errors take precedence in occurrence-index order; otherwise `table_unavailable` | P |
| SA7 | On failure nothing changes: histories, idempotency records, all revisions | P |
| SA8 | Success 201 with current series response; each changed occurrence +1 reservation revision and one ordinary `changed` history entry (`starts_at_local`); series and restaurant revisions +1 once for the whole operation if anything changed; no exception marks; all-no-op or empty eligible set → 201 without revision changes | H + P |
| SA9 | Two concurrent amendments from the same expected revision cannot both make a real change | P |
| UP4 | Stage-4 import accepts exports from accepted stage-1 (a8301bb), stage-2 (0d321ce), stage-3 (fcdb0a2) and its own; replans and series amend work on imported data incl. imported series with moved (exception) and cancelled occurrences; earlier booking/series receipts, histories, sessions and retries remain valid; restaurant revision taken from a stage-3 export, 0 when absent | P + B |
| UP5 | Stage-4 export/import roundtrip preserves plans (applied and pending), closures, restaurant revisions, replan/apply/amend receipts; rejected import leaves state unchanged | P |
| CC4 | 50 in flight mixing bookings, applies, amends: serializable, no 5xx, no overlapping confirmed bookings, no booking on a closed table inside its closure, gap-free counters | P load |
| N4a | `stage-1/`, `stage-2/`, `stage-3/` unchanged (a8301bb, 0d321ce, fcdb0a2) | git diff |
| N4b | Final check `--stage 4 --mode isolated`: suites 1–4 pass | H |

## Decisions (Architect) where the spec is silent

1. Order for replans preview and apply: unparseable/non-object body 400 → 401 → 404 unknown restaurant →
   403 non-manager → idempotency key presence/length → replay/reuse → then
   preview: 422 field validation → 404 unknown table → 422 `planning_limit` → 409 `no_feasible_plan`;
   apply: 404 unknown plan / other restaurant's plan → 409 `plan_already_applied` → 409 `stale_plan`.
   (An applied plan is always also stale, so `plan_already_applied` must win.)
2. Order for series amend: body 400 → 401 → key → 404 series (unknown/other owner) → replay/reuse → 422
   shape (incl. from_index range) → 409 `stale_revision` → per eligible occurrence in index order:
   `cutoff_passed`, then `invalid_local_time` / `not_on_slot_grid` / `outside_opening_hours` /
   `party_exceeds_capacity` → finally occupancy `table_unavailable`.
3. `from`/`to` wrong JSON type → 422 (endpoint says "invalid interval is 422"); `table_id` wrong JSON type → 400.
   `closure` in the response echoes `table_id` and the `from`/`to` strings as supplied.
4. A preview with zero considered bookings is feasible: 201 with empty `assignments`, `moved_count` 0,
   `unused_seats` 0; applying it records the closure and increments the restaurant revision.
5. "Table set changes" compares sets; `table_ids` in assignments use fixture order for singles and declared
   order for pairs. An unchanged booking keeps its current set (which must itself be a valid option).
6. `planning_limit`: the planner must be exact for the stated limits; beyond them it may still answer if
   it finishes within a fixed work budget, otherwise 422 `planning_limit` — never a wrong plan, 5xx or timeout.
7. A considered booking currently on a table closed by an earlier closure cannot exist (apply moved it);
   bookings wholly outside `[from,to)` are fixed even if they sit on the closed table.
8. Imported stage-1/2 exports: restaurant revision 0, no closures/plans.
9. PATCH with an unparseable body on an unknown reference: keep the stage-3 behaviour (400).
