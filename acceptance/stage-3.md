# Stage 3 acceptance map (Tablekeeper — policies, history, recurring reservations)

Source: `dark-factory-wearedevs/tablekeeper/spec/stage-3.md` (stage-1.md and stage-2.md still
apply). Folder: `stage-3/` = copy of accepted `stage-2/` (rev 0d321ce), extended.
"H" = harness (`--stage 3`, runs suites 1–3), "P" = Verifier HTTP probe, "B" = browser probe,
"R" = review. Stage 3 must NOT implement stage-4 features (no `/replans`, no `/series/{id}/amend`,
no closures, no `reassigned` history, no `restaurant_revision` in any response).

| Row | Requirement | Check |
|---|---|---|
| S3-0 | All stage-1 and stage-2 acceptance rows still hold for `stage-3/` (suites 1 and 2 pass; UI unchanged and working; grid follows stage-2 rules) | H + rerun stage-1/stage-2 probe sets (API + browser) against stage-3 image; differences only where stage 3 adds fields (`revision`, `accepted_terms`) |
| S3-D | `stage-3/` own Dockerfile + RUN.md, clean build, `-e PORT`, no outbound network, limits of stage-1 §2 | build + run probes |
| EX1 | `GET /availability` `explain` optional; only value `true`; `false`, `1`, empty string, `TRUE`, anything else → 422 `validation_failed` | P |
| EX2 | Without `explain`: no `explain` field in any slot (stage-1/2 shape) | H |
| EX3 | With `explain=true`: every slot has `explain` with every table of the restaurant exactly once, fixture order, `{table_id, policy_version, available, rules:[{rule:"capacity",holds},{rule:"no_overlap",holds}]}`; both rules always reported in that order, each evaluated independently (table excluded by both shows both false) | H + P |
| EX4 | `available` true iff both hold; the available `table_id`s equal `available_table_ids` in order | H + P |
| EX5 | Closed day → `slots: []`; slot with no available table still appears with full explain | P |
| EX6 | `policy_version` in explain = policy selected for that date (0 when none); capacity rule uses the selected policy's capacities | P |
| HI1 | `GET /reservations/{reference}/history` → `{reference, entries:[...]}` oldest first; owner only; other user, manager, or no token → 404 `not_found` (not 401); cancelled reservation keeps history | H + P |
| HI2 | `seq` starts at 1, +1 each, total order; `at` RFC 3339 with offset, non-decreasing | H + P |
| HI3 | `created` names `table_id`, `starts_at_local`, `party_size` (that order) with `from: null` | H |
| HI4 | `changed` names only fields that actually changed, order `table_id`, `starts_at_local`, `party_size`, with old and new values; a PATCH setting current values succeeds (200) and records no entry | H + P |
| HI5 | `cancelled` has `changes: []`; nothing follows it (repeat cancel adds nothing) | P |
| HI6 | Idempotent replay of `POST /reservations` (and moves, series) records nothing | P |
| HI7 | Every entry carries resulting `revision` and complete `accepted_terms` as of that entry; old entries never acquire newer terms | P |
| HI8 | Combined tables: pair creation uses `table_ids` (null → pair) instead of `table_id`; a change where either side is a pair uses `table_ids` with complete before/after lists; single→single keeps `table_id`; set order = declared combination order; reversed input pair is the same set, not an amendment | P |
| DE1 | `GET /reservations/{reference}/decision` → `{reference, revision, accepted_terms}` current, incl. after cancel; owner-only 404, also 404 without token | H + P |
| PO1 | Fixture `manager_user_ids` on restaurant (default `[]`); wrong JSON type → 400, per §5 | P |
| PO2 | `POST /restaurants/{id}/policies`: no token 401; unknown restaurant 404; authenticated non-manager 403 `forbidden`; idempotency key required with §7 rules (missing 400, replay 200 same body, different body 409, failed key reusable, concurrent identical → one 201) | H + P |
| PO3 | Complete policy required: `effective_from` (real `YYYY-MM-DD`), `slot_minutes` 1..1440 int, `reservation_duration_minutes` 1..1440 int, `cancellation_cutoff_minutes` 0..10080 int, `opening_hours` (stage-1 format, closes > opens, no duplicate weekdays), `capacities` exactly the restaurant's table ids → int 1..100; booleans not integers; any missing/invalid field → 422 `validation_failed`, no version allocated, no state change; unknown fields ignored | P (matrix of invalid values) |
| PO4 | 201 returns supplied policy + `policy_version` (1, 2, … per restaurant; failed writes and replays allocate none); policies immutable | H + P |
| PO5 | `GET /restaurants/{id}/policies` public → `{policies:[...]}` publication order, without policy 0; unknown restaurant 404 | P |
| PO6 | `GET /restaurants/{id}` still returns original fixture configuration after publications | P |
| PO7 | Selection: for a booking's local start date, greatest `effective_from` <= date; ties → greatest `policy_version`; none → policy 0 (fixture rules); publication order may differ from effective order; past effective dates allowed | P |
| PO8 | Availability (slots grid, hours, duration, capacities, `available_options` capacities) and booking validation (grid, hours, capacity, duration/`ends_at`) use the selected policy; occupancy uses each existing booking's own actual interval | H + P |
| PO9 | Publication never changes existing bookings, their `ends_at`, terms, revision or history | P |
| PO10 | Managers gain no access to other diners' reservations, history, decision or series | P |
| TE1 | Every reservation response (create, get, list, cancel, patch, moves, series) carries `revision` (1 at creation) and `accepted_terms` = `{policy_version, slot_minutes, reservation_duration_minutes, cancellation_cutoff_minutes, opening_hours, capacities}` — snapshot of the whole selected policy without `effective_from`; policy 0 terms built from the fixture (capacities from table capacities) | H + P |
| TE2 | Seeded bookings: revision 1 under policy 0. Old idempotency receipts replay the original body incl. original revision and terms (stage-1/2 receipts replay unchanged, without the new fields) | P |
| TE3 | Cancel checks the accepted cutoff vs current start; increments revision once; repeat cancel does not | P |
| TE4 | Real amendment: old accepted cutoff first, then ALL resulting fields validated against the policy of the resulting start date; atomically replaces terms and `ends_at`, revision +1 once | P |
| TE5 | No-op amendment: keeps terms, end, revision, no history; still requires confirmed (409 `reservation_cancelled`) and editable (409 `cutoff_passed`) booking | P |
| TE6 | Failed amendment changes nothing | P |
| TE7 | PATCH `expected_revision` optional: positive integer; wrong type / boolean / <1 → 422; mismatch → 409 `stale_revision` before cutoff/validation; omitted = stage-1 semantics; unknown fields ignored | P |
| TE8 | Two concurrent real amendments with the same `expected_revision`: at most one succeeds | P |
| SE1 | `POST /series`: 401 without token; idempotency key required (§7 rules; a new idempotent path); body `{anchor_reference, count, interval_weeks}`; unknown fields ignored | H + P |
| SE2 | `count` int 2..12, `interval_weeks` int 1..4; invalid incl. booleans → 422 | P |
| SE3 | Anchor unknown / other owner → 404; cancelled → 409 `reservation_cancelled`; already in a series (anchor or generated occurrence) → 409 `already_in_series`; anchor must satisfy its accepted cutoff → 409 `cutoff_passed` | P |
| SE4 | Occurrence 0 = anchor unchanged (reference, id, revision, terms, history, timestamps, original receipt). Occurrence i at anchor local date + i × interval_weeks × 7 days, same local clock time; same party size and table selection (single or pair) | H + P |
| SE5 | Each generated occurrence selects its own date's policy (duration, capacity, grid, hours), obeys DST (nonexistent local time → whole adoption 422 `invalid_local_time`; repeated time → first occurrence) and occupancy; first failing occurrence in index order gives the ordinary booking error | P |
| SE6 | Failure leaves nothing: no series, reservations, histories, counters, references consumed observably, or idempotency claim (key reusable) | P |
| SE7 | 201 `{series_id, revision: 1, interval_weeks, occurrences:[{index, reference, exception:false, reservation:{ordinary response}}]}`, all `count` in index order, distinct references; generated occurrences have revision 1, `created` history, appear in `GET /reservations`, occupy tables | H + P |
| SE8 | `GET /series/{series_id}` same shape with current states and current series revision; owner only; other user or no token → 404 | P |
| SE9 | Real individual PATCH of an occurrence: `exception: true` permanently, series revision +1; no-op or failure changes neither | P |
| SE10 | Cancel of an occurrence: series revision +1, occurrence retained (status cancelled), not an exception; repeat cancel nothing; cancelling the anchor does not cancel siblings; ordinary cutoff/revision checks apply | P |
| SE11 | Replay returns original series response (200) even after later changes; no counter changes | P |
| SE12 | Restaurant revision (internal counter, not exposed in stage 3): +1 once per adoption, per moves batch, per booking, real amendment, cancel, policy publication; kept in state/export for stage 4 | R |
| MO1 | `POST /reservation-moves` under policies: each real change checks old accepted cutoff then adopts the resulting date's policy; per-move `expected_revision` optional with PATCH validation (422) and `stale_revision` (409) rules | P |
| MO2 | No-op move keeps terms/history/revision; each changed booking +1 revision and one `changed` history entry; failure leaves everything unchanged | P |
| MO3 | Each affected series revision +1 once per batch; each changed series occurrence becomes exception; failed batch or replay changes no revisions, histories or flags | P |
| UP1 | Stage-3 import accepts exports from accepted stage-1 (a8301bb) and stage-2 (0d321ce) services and its own; imported reservations get revision 1, policy-0 terms and a history (see decisions); adoption works on imported reservations; sessions, references, original receipts and retries remain valid; UI upgrade behaviour of stage 2 (X2/X3) still holds stage-2 → stage-3 | P + B |
| UP2 | Stage-3 export/import roundtrip preserves policies, versions, terms, revisions, histories, series (ids, revisions, exception flags), all four kinds of idempotent receipts; rejected import leaves state unchanged | P |
| CC3 | Concurrency: 50 in flight across bookings/patches/series/policies → serializable results, no 5xx, no overlapping confirmed bookings, version/seq/revision counters gap-free | P load |
| N3a | `stage-3/` must not pass the stage-4 suite; `stage-1/` and `stage-2/` unchanged (a8301bb, 0d321ce) | H + git diff |
| N3b | Final check `--stage 3 --mode isolated`: suites 1, 2, 3 pass | H |

## Decisions (Architect) where the spec is silent

1. Order for `POST /restaurants/{id}/policies`: unparseable/non-object body 400 → 401 → 404 unknown
   restaurant → 403 non-manager → idempotency key presence/length → replay/reuse → 422 validation.
   Every invalid policy field value, including a wrong JSON type, is 422 ("Invalid policy is 422").
2. Order for PATCH: body 400 → 404 → `expected_revision` shape 422 → `stale_revision` 409 →
   `reservation_cancelled` → `cutoff_passed` (accepted cutoff) → field validation → policy checks → occupancy.
3. Order for `POST /series`: body 400 → 401 → key → replay/reuse → 422 shape (`anchor_reference` must be a
   string; count; interval_weeks) → 404 anchor → `reservation_cancelled` → `already_in_series` →
   `cutoff_passed` → occurrences 1..count-1 in index order, each with ordinary booking precedence.
4. Seeded and imported (stage-1/2 export) reservations: revision 1, policy-0 terms, `ends_at` as stored,
   history = one `created` entry (seq 1, `at` = created_at, current field values, revision 1). A seeded or
   imported reservation that is already cancelled also has revision 1 and only the `created` entry.
5. History `at` and other new timestamps: RFC 3339 with explicit offset (any offset is acceptable; use the
   same convention as `created_at`).
6. `manager_user_ids` naming an unknown user id is accepted (no cross-check); echoed in
   `GET /restaurants/{id}` only if present in the fixture (same rule as `combinable`).
7. `explain` covers single tables only; `available_options` (stage 2) is unchanged in shape and uses the
   selected policy's capacities.
8. Restaurant revision is tracked internally and exported, never returned in stage 3.
