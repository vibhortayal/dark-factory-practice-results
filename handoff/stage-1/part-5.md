@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier
STAGE 1 HANDOFF — part 5 of 5 (FINAL PART): ACCEPTANCE MAP rows G–M and Architect decisions X1–X10 (end of handoff)
Rows: all (A1–M1) · Revision: base 71417847b61264fa969a23c01b4d8c3c4f147caf plus the Architect commit that adds ACCEPTANCE-stage-1.md (see `git log`) · Files: ACCEPTANCE-stage-1.md, STATUS.md, handoff/stage-1/ (this text), target stage-1/ (does not exist yet) · Command: n/a · Expected / actual: n/a (nothing built yet) · Repro: n/a · Next: Implementer builds stage-1/; Verifier prepares its check list and scripts (no verdict yet)

## G. Restaurants and availability (§8)

| Row | Requirement | Check |
|---|---|---|
| G1 | `GET /restaurants` → `{"restaurants":[{id,name,timezone}]}` | H, V |
| G2 | `GET /restaurants/{id}` → restaurant incl. `slot_minutes, reservation_duration_minutes, cancellation_cutoff_minutes, opening_hours, tables` in fixture shape; unknown → 404 | H, V |
| G3 | `GET /availability` requires `restaurant_id`, `date`, `party_size`; any missing → 422 | H, V |
| G4 | `date` must be a real `YYYY-MM-DD` (`2026-02-30`, `not-a-date`, `24-09-2026` → 422); it is the local date at the restaurant | H, V |
| G5 | Unknown `restaurant_id` (other params valid) → 404 | H, V |
| G6 | Response `{restaurant_id, date, timezone, slots:[{starts_at_local, starts_at, available_table_ids}]}` | H, V |
| G7 | One slot for every `slot_minutes` step from `opens` while `slot + duration <= closes`; boundary: last slot ends exactly at `closes` is present, next one absent | H, V |
| G8 | `available_table_ids`: that restaurant's tables with `capacity >= party_size` (boundary: equal included) and no overlapping confirmed reservation, in fixture order | H, V |
| G9 | A slot with no available table still appears with `[]` | H, V |
| G10 | Closed day → `"slots": []` | H, V |
| G11 | Overlap is half-open `[start, start+duration)`: a booking hides its table from every overlapping slot, not from adjacent ones (with 30-min slots, a 90-min booking at 19:00 hides its table at 18:00, 18:30, 19:00, 19:30 and 20:00; 20:30 stays free) | H, V |
| G12 | Cancelled reservations do not occupy | H, V |

## H. Create reservation (§8)

| Row | Requirement | Check |
|---|---|---|
| H1 | `POST /reservations` → 201 with `reservation_id, reference, restaurant_id, table_id, party_size, status:"confirmed", starts_at_local, starts_at, ends_at, created_at` | H, V |
| H2 | `ends_at = starts_at + reservation_duration_minutes` (absolute) | H, V |
| H3 | `reference`: 6–12 chars `A-Z0-9`, unique across all reservations (also versus seeded references), never changes | H, V: 500 creations + seeded collision |
| H4 | Table taken for an overlapping interval → 409 `table_unavailable`; adjacent (ends when the other starts) succeeds; other table same time succeeds | H, V |
| H5 | Not on the slot grid → 422 `not_on_slot_grid` | H, V |
| H6 | Before `opens`, at/after `closes`, would end after `closes`, or closed weekday → 422 `outside_opening_hours` | H, V |
| H7 | `party_size` > capacity → 422 `party_exceeds_capacity`; equal to capacity accepted | H, V |
| H8 | `party_size` < 1 or not an integer → 422 `validation_failed` | H, V |
| H9 | Non-existent local time (spring-forward gap) → 422 `invalid_local_time` | H, V |
| H10 | Unknown restaurant, unknown table, or table of another restaurant → 404 `not_found` | H, V |
| H11 | Missing required field → 422 `validation_failed` | V |
| H12 | Concurrency: N clients racing for one table+slot → exactly one 201, the rest 409, zero 5xx, one confirmed row; same for overlapping-but-different slots | H (10), V (50) |
| H13 | A rejected create leaves no reservation and no occupancy | V |

## I. Read, list, cancel, amend (§8)

| Row | Requirement | Check |
|---|---|---|
| I1 | `GET /reservations` → 200 `{"reservations":[...]}`, caller's only, confirmed and cancelled, `starts_at` descending (by instant), entries in create-response shape; empty → `[]` | H, V |
| I2 | `GET /reservations/{reference}` → the reservation; unknown or someone else's → 404 | H, V |
| I3 | Cancel → 200 full reservation with `status:"cancelled"`; table free at once in availability and bookable | H, V |
| I4 | Cancel twice → 200 with current state (also when the cutoff has since passed) | H, V |
| I5 | Cancel when `now >= starts_at − cancellation_cutoff_minutes` (incl. already started) → 409 `cutoff_passed`, state unchanged | H, V |
| I6 | Cancel someone else's / unknown → 404 | H, V |
| I7 | `PATCH /reservations/{reference}` accepts any subset of `table_id, starts_at_local, party_size`; no idempotency key needed; returns 200 with the updated reservation | H, V |
| I8 | PATCH validation identical to create: every H4–H10 code reachable through PATCH, judged against the merged (current + patch) values | H, V |
| I9 | PATCH cutoff measured against the **current** start → 409 `cutoff_passed` | H, V |
| I10 | PATCH a cancelled reservation → 409 `reservation_cancelled` | H, V |
| I11 | PATCH someone else's / unknown → 404 | H, V |
| I12 | Successful PATCH releases old slot and reserves new one atomically; `starts_at/ends_at/starts_at_local` recomputed; a reservation does not conflict with itself (shift by one slot onto own interval succeeds) | H, V |
| I13 | Failed PATCH leaves booking and occupancy unchanged | V |
| I14 | `reference`, `reservation_id`, `created_at`, owner survive PATCH | H, V |
| I15 | Concurrency: N PATCHes onto one free table → exactly one success; cancel-and-rebook races never double-book; no 5xx | V (50) |
| I16 | Empty PATCH `{}` (or only unknown fields) → 200, nothing changed | V |

## J. Time and DST (§9)

| Row | Requirement | Check |
|---|---|---|
| J1 | Offsets follow IANA rules for the zone and date (Berlin +01:00/+02:00, New York −05:00/−04:00); tz database shipped in the image | H, V |
| J2 | Spring forward: skipped local times never appear in availability (Berlin 2026-03-29 02:00–02:59, New York 2026-03-08 02:00–02:59); booking one → 422 `invalid_local_time` (create and PATCH and moves) | H, V |
| J3 | Fall back: repeated local times appear once in availability (Berlin 2026-10-25 02:00–02:59, New York 2026-11-01 01:00–01:59) and resolve to the first occurrence (Berlin +02:00, New York −04:00); the second occurrence cannot be booked | H, V |
| J4 | Duration is absolute: Berlin 2026-10-25 01:30 + 90 min → `ends_at` reads `02:00` local, not `03:00`: the instant 90 real minutes later rendered with the offset valid at that instant, `2026-10-25T02:00:00+01:00` | H, V |
| J5 | Occupancy/overlap uses absolute instants across a transition (a booking in the first 02:00 hour and one at 03:00 after fall-back do not falsely overlap or falsely clear) | V |
| J6 | Same instant from two zones compares equal (Berlin 18:00 CET = New York 12:00 EST on 2026-12-01) | H, V |

## K. Export / import (§10)

| Row | Requirement | Check |
|---|---|---|
| K1 | `GET /_test/export` → 200 `{track:"tablekeeper", format_version:1, state:{...}}`, unauthenticated | H, V |
| K2 | `POST /_test/import` with an unchanged export → 204; replaces state atomically; unauthenticated | H, V |
| K3 | Import is replacement, not merge: prior destination users, tokens, restaurants, reservations, keys are gone; importing twice duplicates nothing | V |
| K4 | Preserved through export→reset→import and export→fresh container→import: accounts + hashed-password login, existing bearer tokens, fixture configuration, reservations (ids, references, statuses incl. cancelled, `created_at`, all timestamps byte-identical in responses) | H, V (second container) |
| K5 | Preserved: completed idempotent requests and their original responses for both keyed paths — replay after import → 200 original body; different body → 409 | V |
| K6 | Failed request keys remain reusable after import | V |
| K7 | Invalid JSON → 400 `malformed_request`; missing `track`/`format_version`/`state`, wrong track, wrong version, invalid/garbled state → 422 `validation_failed`; destination state unchanged in every failure case | V |
| K8 | Export is an atomic read-only snapshot: writes after export do not alter the exported document; export changes nothing | V |
| K9 | No dependency on source process, files, volume, port or address: export from container A imports into fresh container B | V |
| K10 | Reset after import clears everything, including imported tokens and keys | V |
| K11 | Export/import/reset each complete < 10 s | V |

## L. Atomic reservation moves (§11)

| Row | Requirement | Check |
|---|---|---|
| L1 | `POST /reservation-moves` requires bearer token (401) and `Idempotency-Key` (400 / 422 length) | V |
| L2 | `moves`: 1..8 objects with distinct string `reference`; 0 items, 9 items, non-array, missing, non-object item, non-string/missing reference, duplicate references → 422 `validation_failed`; 1 and 8 accepted | V |
| L3 | Unknown reference or another owner's → 404 `not_found` | V |
| L4 | Bookings of different restaurants in one batch → 422 `validation_failed` | V |
| L5 | Item fields `table_id, starts_at_local, party_size`; omitted keep current values; unknown fields ignored | H, V |
| L6 | Any cancelled booking listed → 409 `reservation_cancelled` | V |
| L7 | Each booking's cutoff applies (against its current start) → 409 `cutoff_passed` | V |
| L8 | Non-occupancy errors use the PATCH codes and take precedence in input order; within one booking, cutoff precedes that booking's other errors | V |
| L9 | Overlap among resulting bookings or with an unlisted confirmed booking → 409 `table_unavailable`; evaluated on the final state, so a swap of two tables (the §11 example) and a rotation of three succeed | V |
| L10 | Unchanged listed bookings keep their occupancy (another item cannot move onto them) | V |
| L11 | All-or-nothing: on any failure no reservation, no occupancy and no retry key changes | V |
| L12 | Success → 201 `{"reservations":[...]}` in input order, including unchanged items, each in create-response shape | H, V |
| L13 | Replay → 200 original response, even after later amendments/cancellations; different body → 409; failed batch key reusable | V |
| L14 | Identity, owner, `created_at`, `reference` never change; a no-op move keeps every value | V |
| L15 | Export/import preserves successful batch receipts and resulting bookings | V |
| L16 | Concurrent conflicting batches / batch vs. create never double-book; identical concurrent batches → one 201, rest 200 | V |

## M. Core invariant (§1)

| Row | Requirement | Check |
|---|---|---|
| M1 | At no time do two `confirmed` reservations occupy the same table at overlapping half-open intervals — across create, PATCH, moves, reset seeds and import, sequential and concurrent | V: after every concurrent scenario, dump all reservations (via each user's list / export) and assert pairwise non-overlap |

## Architect decisions (where the spec is silent or ambiguous)

These resolve open choices; they are part of the handoff. A Verifier check may rely on a
decision only where it restates the specification; rows marked *(choice)* are not grounds
for a blocking finding by themselves.

- **X1 Validation order, `POST /reservations`** *(choice except the F10 clause)*: 401 auth →
  `Idempotency-Key` presence (400) and length (422) → body must parse as a JSON object (400) →
  idempotency resolution (replay 200 / reuse 409) → field types (400) and required/format
  (422, `party_size` always 422) → 404 restaurant/table → `invalid_local_time` →
  `not_on_slot_grid` → `outside_opening_hours` → `party_exceeds_capacity` → `table_unavailable`.
- **X2 Grid vs. hours** *(choice for the doubly-wrong case)*: grid membership is
  `(minutes_of_day − opens) mod slot_minutes == 0` on a weekday that is open; it is tested
  before the hours window, following the order of the §8 table. So 18:01 and 19:15 →
  `not_on_slot_grid`; 17:00, 22:00, 23:30 → `outside_opening_hours`; a closed weekday →
  `outside_opening_hours`. These five outcomes are fixed by the supplied checks.
- **X3 `slot + duration <= closes`** is evaluated in local wall-clock minutes of the day for
  both availability and booking; occupancy and `ends_at` use absolute time (§9).
- **X4 PATCH order** *(choice)*: 401 → body JSON object (400) → 404 → `reservation_cancelled`
  → `cutoff_passed` → field validation as X1 on merged values → `table_unavailable`.
- **X5 Moves order** *(choice beyond §11's stated precedence)*: 401 → key → body JSON object
  (400) → idempotency resolution → shape/duplicates (422) → every reference resolved (first
  unknown/foreign in input order → 404) → different restaurants (422) → per item in input
  order: cancelled → cutoff → field/validation codes → finally occupancy on the resulting
  state (409 `table_unavailable`).
- **X6 Cutoff**: refused when `now >= starts_at − cancellation_cutoff_minutes`; `now` is the
  server's real clock. Cancelling an already-cancelled booking returns 200 before the cutoff
  is considered.
- **X7 Reset validation** *(choice beyond B6)*: seeded reservations are not checked against
  grid, hours or capacity (the fixture is authoritative), but two overlapping seeded
  confirmed bookings on one table are rejected with 422 (M1). Missing top-level arrays are
  treated as empty. Seeded reservations get `status: confirmed` and `created_at` = reset time.
- **X8 Idempotency record key** is (user, method, path, key). Only successful (201)
  responses are recorded.
- **X9 Unknown routes** → 404 `not_found` with the error envelope.
- **X10 Storage**: in-process memory is acceptable (state is ephemeral); whatever is chosen,
  every mutation must be atomic with respect to occupancy and idempotency records, and
  password hashing must be tuned so 50 concurrent logins finish within the 5 s request
  budget on 2 vCPU and a reset seeding a few dozen users finishes within 10 s.
