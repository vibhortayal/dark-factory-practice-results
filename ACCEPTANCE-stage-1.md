# Acceptance map — Tablekeeper stage 1

Source of truth: `dark-factory-wearedevs/tablekeeper/spec/stage-1.md` (§ numbers below refer to it).
Target folder: `stage-1/`. Owner of this file: Architect.

"Check" says how each row is verified. `H` = supplied harness suite (partial sample only),
`V` = Verifier's own black-box check against the running container, `I` = Implementer's own
test, `R` = read of the delivered files. Every row needs `I` and `V` evidence unless marked
otherwise; `H` is never sufficient on its own.

## A. Delivery, deployment, limits (§1, §2)

| Row | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` holds the whole service: source, `Dockerfile`, `RUN.md`; no nested `.git`; nothing outside `stage-1/` is needed to build | R; `docker build stage-1` from a clean clone |
| A2 | `RUN.md` gives one command sequence that builds and starts the service with no manual setup, and says where each module lives | R; follow RUN.md verbatim on a clean checkout |
| A3 | Image runs alone with `-e PORT=<port>` and a port mapping; no compose needed; all runtime deps, tzdata, seed/init inside the image | V: `docker run --network none`-equivalent (harness `--mode isolated`), no outbound access |
| A4 | No outbound network at run time (no CDN, no remote DB, no downloads at start) | V: isolated run; R of Dockerfile/entrypoint |
| A5 | Works within 2 vCPU / 2 GiB | V: `docker run --cpus 2 --memory 2g`, run load rows under these limits |
| A6 | First healthy response within 60 s of container start | V: timed start under A5 limits |
| A7 | Up to 50 concurrent in-flight requests served; every request < 5 s (reset/export/import < 10 s) | V: 50-way bursts on booking, login, availability; time each |
| A8 | No request produces a 5xx, including under concurrent load and for malformed input | V: status tally over every check + fuzzed bad inputs |
| A9 | Only the HTTP API; no UI and no stage-2+ features (no HTML screens, combined tables, managers, policies) | R; harness prints `claimed stage: 1` (stage-2 suite must not fully pass) |
| A10 | State is ephemeral; nothing required to survive container restart; no dependency on host files/volumes | R |
| A11 | Implementation is original: no source, API docs or schemas from existing products in this domain | R |

## B. Runtime contract (§3)

| Row | Requirement | Check |
|---|---|---|
| B1 | Listens on `0.0.0.0:$PORT`, default `8080` when `PORT` unset | V: run with and without `-e PORT` |
| B2 | `GET /health` → 200 `{"status":"ok"}` once ready | H, V |
| B3 | `POST /_test/reset` with fixture → 204, empty body, no auth needed | H, V |
| B4 | Reset replaces **all** state: users, tokens, restaurants, tables, reservations, idempotency records; after 204 only the fixture is visible (old tokens → 401, old bookings gone, old keys forgotten) | V |
| B5 | Reset is synchronous and repeatable (same fixture twice, different fixtures in sequence) | H, V |
| B6 | Reset rejects an invalid fixture with 422 `validation_failed` (unparseable body / wrong JSON type → 400 `malformed_request`) and leaves the previous state unchanged. Minimum invalid cases: any id longer than 64 chars (user, restaurant, table, reservation); seeded `reference` not 6–12 chars of `A-Z0-9`; duplicate ids/references/emails; reservation naming an unknown user/restaurant/table or a table of another restaurant | H (64-char, reference), V |
| B7 | Responses are `application/json; charset=utf-8` (204s have no body) | V: header check on success and error responses |
| B8 | Response timestamps are RFC 3339 with explicit offset (`starts_at`, `ends_at`, `created_at`); never without an offset | H, V |
| B9 | Unknown fields in any request body are ignored, never an error (signup, login, reservations, PATCH, moves items, fixture) | H, V |
| B10 | Unknown query parameters are ignored | H, V |
| B11 | Service-generated ids (`user_id`, `reservation_id`, tokens excepted) are opaque strings ≤ 64 chars; fixture ids of exactly 64 chars accepted, 65 rejected | V |

## C. Model and fixture (§4)

| Row | Requirement | Check |
|---|---|---|
| C1 | Restaurants/tables come only from reset; no create endpoints for them | R, V (POST /restaurants is not a success) |
| C2 | Fixture restaurant fields stored and returned in fixture shape: `id,name,timezone,slot_minutes,reservation_duration_minutes,cancellation_cutoff_minutes,opening_hours[{weekday,opens,closes}],tables[{id,label,capacity}]` | H, V |
| C3 | `weekday` ∈ `mon..sun`; a weekday with no entry is closed | H, V |
| C4 | `opens`/`closes` local `HH:MM` 24h, `closes` later than `opens`, never crossing midnight | V |
| C5 | Seeded users can log in with the fixture password immediately after reset; their `id` is the fixture id | H, V |
| C6 | Seeded reservations (`id, reference, user_id` + create fields) are confirmed, occupy their table, belong to `user_id`, are readable/cancellable/patchable like API-made ones, keep the given `id` and `reference` | H, V |
| C7 | Any calendar date works; a booking is never rejected solely because its start is in the past (create, seed, PATCH target time) | H (past DST dates), V |
| C8 | Cutoff rules still apply to past bookings (cancel/PATCH of an already-started booking → 409 `cutoff_passed`) | H, V |

## D. Errors (§5)

| Row | Requirement | Check |
|---|---|---|
| D1 | Every 4xx/5xx body is `{"error":{"code":<string>,"message":<string>}}`, including unknown routes and unsupported methods | V: envelope asserted on every error |
| D2 | 400 `malformed_request`: unparseable body, body that is not a JSON object, or a field of the wrong JSON type (e.g. signup `email: 17`, `table_id: 5`, `starts_at_local: 5`, `moves[i].table_id: 5`) | H, V |
| D3 | 400 `missing_idempotency_key`: header absent or empty on the two keyed paths | H, V |
| D4 | 401 `unauthenticated`: missing, malformed (no `Bearer `, empty token) or unknown token, on every protected endpoint | H, V |
| D5 | 403 `forbidden` is defined but stage 1 has no case that uses it; other people's reservations are 404, never 403 | H, V |
| D6 | 404 `not_found`: unknown resource or not visible to caller | H, V |
| D7 | 409 `idempotency_key_reuse` | H, V |
| D8 | 422 `validation_failed`: required field/query parameter missing, or correct type with invalid format / out-of-range value (invalid dates, negative counts, over a stated maximum or length) | H, V |
| D9 | `party_size` invalid in a body (0, negative, string, boolean, float `1.5`, null) → 422 `validation_failed`, not 400 | H, V |
| D10 | `starts_at_local` string not exactly bare `YYYY-MM-DDTHH:MM` (offset, `Z`, seconds, impossible date/time such as `2026-02-30T19:00`, `T24:00`) → 422 `validation_failed` | H, V |
| D11 | Integer query parameters must be plain decimal digits: `1e9`, `4.0`, `+4`, ` 4`, `-1`, `abc`, empty → 422 `validation_failed`; `0` → 422 | H, V |
| D12 | `Idempotency-Key` length: 1 and 255 chars accepted, 256 → 422 `validation_failed`, empty/absent → 400 `missing_idempotency_key`; on both keyed paths | V |

## E. Authentication (§6)

| Row | Requirement | Check |
|---|---|---|
| E1 | `POST /auth/signup` → 201 `{user_id, display_name, token}`; token works immediately | H, V |
| E2 | `POST /auth/login` → 200 `{user_id, display_name, token}`; token works | H, V |
| E3 | Signup with registered email (seeded or signed-up) → 409 `email_taken` | H, V |
| E4 | Password of 7 chars → 422; 8 chars accepted | H, V |
| E5 | `email` not `local@domain` (no `@`, empty local, empty domain) → 422 | H, V |
| E6 | Missing `email`/`password`/`display_name` on signup, missing `email`/`password` on login → 422; wrong JSON type → 400 | H (type), V |
| E7 | Login wrong password or unknown email → 401 `unauthenticated` | H, V |
| E8 | Public without token: `/health`, `/_test/reset`, `/_test/export`, `/_test/import`, signup, login, `GET /restaurants`, `GET /restaurants/{id}`, `GET /availability`. A bad/garbage token on a public endpoint does not cause an error | H, V |
| E9 | Everything else requires `Authorization: Bearer <token>`: `GET/POST /reservations`, `GET/PATCH /reservations/{ref}`, cancel, `POST /reservation-moves` → 401 without | H, V |
| E10 | Tokens do not expire; multiple logins give multiple simultaneously valid tokens | V |
| E11 | Passwords stored only as bcrypt/scrypt/Argon2 (or equivalent) hashes; plaintext never stored, never in export | R, V (grep export for the plaintext) |
| E12 | Concurrent signup with the same email: exactly one 201, others 409 | V |

## F. Idempotency (§7) — applies to `POST /reservations` and `POST /reservation-moves`

| Row | Requirement | Check |
|---|---|---|
| F1 | First use → normal response 201 | H, V |
| F2 | Replay (same user, method, path, key, same JSON value) → 200 with body equal to the original as a JSON value; no state change | H, V |
| F3 | "Same body" is JSON-value equality: key order and whitespace irrelevant | V |
| F4 | Same key, different body → 409 `idempotency_key_reuse`, even when the new body would fail validation (e.g. `party_size: "x"`, unknown table) or the resource has changed | H, V |
| F5 | Keys are scoped per authenticated user: two users, same key string, no interaction | H, V |
| F6 | Same key + same body on the other keyed path is a different request, not a replay, and proceeds normally | V |
| F7 | A key whose original request failed with 4xx is treated as a first use (same or different body) | V |
| F8 | Replay returns the original response even after the reservation is amended or cancelled | H, V |
| F9 | Concurrent identical requests with an unused key: exactly one 201, the rest 200 with the same body; one reservation created | V: 20–50-way burst |
| F10 | Order: body parsed as JSON object + caller authenticated → idempotency resolved → field validation / resource checks | V (F4 cases) |
| F11 | Retries and rejected requests never create duplicate or partial bookings | V: count reservations after failures/replays |

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
