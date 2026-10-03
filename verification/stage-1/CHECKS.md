# Stage 1 — Verifier check list (Tablekeeper)

Derived from `tablekeeper/spec/stage-1.md` clause by clause, before any implementation
or supplied test was read. Each check names the spec section and the acceptance-map row.
Scripts: `run.sh` (build, containers, harness) and `probe.py` (HTTP checks, ids below).
"NOTE" items are observations where the spec is silent or ambiguous; they never block.

## §2 Delivery / resource limits (run.sh)
- D1.1 [D1 §2] `stage-1/Dockerfile` builds from a clean export of the revision with `--no-cache`.
- D1.2 [D1 §2] `RUN.md` exists and contains a command that builds and starts the service; that command works as written.
- D1.3 [D1 §2] folder is self-contained (no nested `.git`, no reference outside the folder in the Dockerfile).
- D2.1 [D2 §2] image runs alone with `-e PORT=<port>` + `-p` mapping → `/health` 200.
- D2.2 [D2 §2] runs on an `--internal` docker network (no outbound) → all probes pass there.
- D3.1 [D3 §2] with `--cpus 2 --memory 2g`: start → first healthy response ≤ 60 s.
- D3.2 [D3 §2] 50 requests in flight: every request < 5 s, reset/export/import < 10 s (probe LOAD.*).
- D3.3 [D3 §2] container not OOM-killed / still running after the whole probe run.
- C1.1 [C1 §3.1] started without `PORT` → listens on 8080 on 0.0.0.0 (reached via container IP).

## §3 Runtime contract
- C2.1 [C2 §3.2] `GET /health` → 200 `{"status":"ok"}`.
- C3.1 [C3 §3.3] reset → 204, empty body, no auth needed.
- C3.2 [C3 §3.3] after reset only the fixture is visible: earlier signup cannot log in, earlier tokens 401, earlier reservations gone, earlier restaurants gone, earlier idempotency keys are fresh.
- C3.3 [C3 §3.3] repeated resets supported (same fixture twice, then a different one).
- C3.4 [C3/E2 §3.3/§5] reset with unparseable body → 400 `malformed_request`; wrong JSON type for a field (users, restaurants, slot_minutes, restaurant id, user email) → 400 `malformed_request`.
- C4.1 [C4 §3.4] every response with a body has `Content-Type: application/json; charset=utf-8` (checked on every probe response).
- C5.1 [C5 §3.4] `starts_at`, `ends_at`, `created_at` are RFC 3339 with explicit offset (every reservation body seen).
- C6.1 [C6 §3.4] unknown body fields ignored (signup, login, POST /reservations, PATCH, moves item).
- C6.2 [C6 §3.4] unknown query parameters ignored (`/restaurants`, `/restaurants/{id}`, `/availability`, `/reservations`).
- C7.1 [C7 §3.4] fixture IDs of exactly 64 chars accepted and usable (user, restaurant, table, reservation id).
- C7.2 [C7 §3.4/§5] fixture ID of 65 chars (user / restaurant / table / reservation) → 422 `validation_failed`.
- C7.3 [C7 §3.4] generated IDs (`user_id`, `reservation_id`) are strings ≤ 64 chars.

## §4 Model / fixture
- M1.1 [M1 §4] spec's example fixture accepted verbatim.
- M2.1 [M2 §4] seeded user logs in immediately; `user_id` equals fixture id, `display_name` matches.
- M3.1 [M3 §4] seeded reservation: owner sees it by reference and in list; `reservation_id` = fixture `id`, `reference` kept, status `confirmed`, correct `starts_at`/`ends_at`.
- M3.2 [M3 §4] seeded reservation occupies its table (availability + 409 on overlap); other user → 404.
- M3.3 [M3 §4] seeded reservation can be amended and cancelled by owner.
- M4.1 [M4 §4] booking with a past start (2020) → 201.
- M4.2 [M4 §4] past booking: cancel → 409 `cutoff_passed`; PATCH → 409 `cutoff_passed`.
- M5.1 [M5 §4] weekday without entry → `slots: []`.

## §5 Errors
- E1.1 [E1 §5] every 4xx/5xx seen has `{"error":{"code":str,"message":str}}` (checked on every probe response), incl. unknown route and wrong method.
- E2.1 [E2 §5] unparseable body → 400 `malformed_request` on signup, login, POST /reservations, PATCH, moves, import, reset.
- E2.2 [E2 §5] body that is not a JSON object → 400 `malformed_request`.
- E2.3 [E2 §5] wrong JSON type for `restaurant_id`, `table_id`, `starts_at_local` (non-string), `email`, `password` → 400 `malformed_request`.
- E3.1 [E3 §5] invalid dates (`2026-02-30`, month 13) → 422 `validation_failed`.
- E4.1 [E4 §5/§8] `party_size` 0, -1, "4", true, 2.5, null, missing → 422 `validation_failed` (POST and PATCH).
- E5.1 [E5 §5/§8] `starts_at_local` with seconds, offset, `Z`, space separator, garbage, impossible date/hour → 422 `validation_failed`.
- E6.1 [E6 §5] availability `party_size` = `1e9`, `4.0`, `+4`, `abc`, `-1`, `0`, empty → 422 `validation_failed`.
- E7.1 [E7 §5] `Idempotency-Key` 255 chars → accepted (201); 256 chars → 422 `validation_failed`; 1 char → 201 (both write paths).
- E7.2 [E7/I2 §5/§7] absent / empty key → 400 `missing_idempotency_key` (both write paths), also when the body would fail field validation (§7 order).
- E8.1 [E8 §5] no 5xx in any probe response, including load.

## §6 Authentication
- A1.1 [A1] signup → 201 `{user_id, display_name, token}`; token works.
- A2.1 [A2] login → 200 same shape, same `user_id`.
- A3.1 [A3] duplicate email (signup twice; and seeded email) → 409 `email_taken`.
- A4.1 [A4] password of 7 chars → 422; 8 chars → 201.
- A4.2 [A4] email `nodomain`, `@x.com`, `a@`, `` → 422 `validation_failed`.
- A4.3 [A4/§5] missing `email` / `password` → 422; NOTE: missing display_name, `x@localhost`, email case.
- A5.1 [A5] wrong password / unknown email → 401 `unauthenticated`.
- A6.1 [A6] protected endpoints without token, with malformed header, with unknown token → 401 `unauthenticated` (GET /reservations, GET /reservations/{ref}, cancel, PATCH, POST /reservations, POST /reservation-moves).
- A6.2 [A6] public endpoints work without token: /health, /restaurants, /restaurants/{id}, /availability.
- A7.1 [A7] several logins → every token issued (signup + each login) stays valid concurrently.
- A8.1 [A8] export contains no plaintext password; code review confirms a password-hashing function.

## §7 Idempotency
- I6.1 first use 201; replay 200 with identical JSON; no second reservation.
- I4.1 replay with reordered keys + whitespace → 200 identical.
- I6.2 same key, different body → 409 `idempotency_key_reuse` (incl. body differing only by an extra unknown field: different JSON value).
- I5.1 used key + different invalid body (bad party_size / unknown restaurant) → 409 `idempotency_key_reuse`.
- I3.1 different users, same key, → independent 201s.
- I4.2 same key + same body on the other write path → succeeds normally (201), not a replay.
- I7.1 key whose first request failed 4xx (422, 409, 404) → next use is a first use (201).
- I8.1 20 concurrent identical requests, unused key → exactly one 201, others 200, identical body, one reservation.
- I9.1 replay after cancel and after PATCH → 200 with the original body; state not changed by replay.
- I1.1 PATCH and cancel need no key.

## §8 API
- R1.1 `GET /restaurants` lists every fixture restaurant with id, name, timezone.
- R2.1 `GET /restaurants/{id}` returns slot_minutes, reservation_duration_minutes, cancellation_cutoff_minutes, opening_hours, tables equal to the fixture; unknown → 404 `not_found`.
- V1.1 each of the three availability params missing → 422 `validation_failed`.
- V2.1 bad date formats → 422; unknown restaurant → 404 `not_found`.
- V3.1 response shape and values: restaurant_id, date, timezone, slots[starts_at_local, starts_at, available_table_ids].
- V4.1 slots: Thu 18:00–23:00/30/90 → 18:00…21:30 (8); Fri closes 23:30 → …22:00 (9); odd grid 18:15/20/45/20:00 → 18:15,18:35,18:55,19:15.
- V4.2 capacity filter incl. boundary (party = capacity listed; capacity+1 not); slot with no table still listed with `[]`; tables in fixture order (ids not sorted).
- V4.3 confirmed reservation removes its table from every overlapping slot and only those (half-open).
- V5.1 closed day → `slots: []`.
- B1.1 create → 201 with all ten fields, correct values.
- B2.1 reference matches `^[A-Z0-9]{6,12}$`, unique over many bookings and vs seeded references.
- B3.1 same table same slot → 409 `table_unavailable`; overlapping earlier/later slot → 409; 19:00 then 20:30 → 201; cancelled booking does not block.
- B4.1 off-grid → 422 `not_on_slot_grid` (incl. grid measured from `opens`, not from the hour).
- B5.1 ends after closes → 422 `outside_opening_hours`; last slot ending exactly at closes → 201; closed day → 422 `outside_opening_hours`. NOTE: before-opening code.
- B6.1 party = capacity → 201; capacity + 1 → 422 `party_exceeds_capacity`.
- B7.1 see T1.
- B8.1 unknown restaurant / unknown table / other restaurant's table → 404 `not_found`.
- B9.1 50 concurrent creates (different users, different keys) for one table+slot → exactly one 201, others 409 `table_unavailable`.
- B9.2 50 concurrent creates over overlapping slots on one table → confirmed set has no overlap.
- L1.1 list: only caller's; `starts_at` descending by instant (two zones); includes cancelled; empty → `{"reservations": []}`; entries have the create shape.
- G1.1 GET by reference: own → 200 equal to create body; other's → 404; unknown → 404.
- X1.1 cancel → 200, status `cancelled`, other fields unchanged; slot offered again in next availability; table bookable again.
- X2.1 cancel twice → 200 cancelled.
- X3.1 start within cutoff (dynamic, ~1 h ahead with 600 min cutoff) → 409 `cutoff_passed`; start beyond cutoff (~1 h ahead with 30 min cutoff; ~11 h ahead with 600) → 200.
- X4.1 other's reservation → 404; unknown → 404.
- P1.1 PATCH party_size only / table_id only / starts_at_local only / all three → 200 with updated values, ends_at recomputed, no idempotency key.
- P2.1 PATCH validation: not_on_slot_grid, outside_opening_hours, party_exceeds_capacity (via party and via smaller table), invalid_local_time, 404 table, 422 party/starts format, 400 wrong type, 409 table_unavailable.
- P2.2 cancelled → 409 `reservation_cancelled`; cutoff by current start → 409 `cutoff_passed`; a booking beyond cutoff may be moved into the past/near time (cutoff measured against current start), after which it is locked.
- P3.1 move to an overlapping slot on the same table (19:00 → 19:30) → 200; old slot released, new one occupied.
- P3.2 every failed PATCH leaves the booking and availability unchanged.
- P4.1 reference, reservation_id, created_at unchanged after PATCH; other's → 404; no token → 401.

## §9 Time and DST
- T1.1 Berlin 2026-03-29 and New York 2026-03-08: 02:00, 02:30 absent from availability; booking them → 422 `invalid_local_time`; offsets before/after correct.
- T2.1 Berlin 2026-10-25 (02:xx repeated) and New York 2026-11-01 (01:xx repeated): each local slot appears once, with the first-occurrence offset; booking resolves to the first occurrence.
- T3.1 duration absolute: NY 01:30 fall-back → ends `02:00-05:00`; Berlin 01:30 fall-back → `02:00+01:00`; Berlin 01:30 spring → `04:00+02:00`.
- T4.1 ordinary offsets: Berlin summer +02:00, winter +01:00; New York summer −04:00, winter −05:00.
- T5.1 overlap on instants: fall-back booking 02:30 (first) does not block 03:00; spring booking 01:30 blocks 03:00 and 03:30 but not 04:00; availability agrees.

## §10 Export / import
- IE1.1 export → 200 with `track`, `format_version: 1`, `state` object; unauthenticated.
- IE1.2 export is read-only (state identical before/after) and a snapshot (later writes do not appear after importing it).
- IE2.1 import of unchanged export → 204; replaces (later-created user, token, reservation gone); repeat import → no duplicates.
- IE3.1 after import: login with password, existing tokens, restaurants config, reservations (full bodies incl. cancelled status, created_at), references preserved.
- IE3.2 after import: replay of completed create and moves keys → 200 original bodies; different body on used key → 409; key that failed before export is still a first use.
- IE4.1 invalid JSON → 400 `malformed_request`; missing track / format_version / state, wrong track, wrong version, corrupted state → 422 `validation_failed`; destination unchanged each time.
- IE5.1 import into a second, fresh container: same assertions as IE3; then reset there clears it.
- IE6.1 after import: new reservations/users get ids and references that do not collide with imported ones.
- IE7.1 export/import each < 10 s.

## §11 Reservation moves
- MV1.1 no token → 401; missing key → 400; key rules as §7 (replay 200, different body 409, 256-char key 422).
- MV2.1 `moves` missing / empty / 9 items / duplicate references / item without reference → 422 `validation_failed`; 8 items → 201; 1 item → 201. NOTE: non-array / non-object / non-string reference (400 or 422).
- MV3.1 unknown reference → 404; other owner's → 404; bookings from two restaurants → 422 `validation_failed`.
- MV4.1 per-item table_id / starts_at_local / party_size applied; omitted retained; unknown item fields ignored; reservation_id, reference, created_at unchanged.
- MV5.1 cancelled listed → 409 `reservation_cancelled`; past-cutoff listed → 409 `cutoff_passed`; item codes not_on_slot_grid / outside_opening_hours / party_exceeds_capacity / invalid party → ordinary codes.
- MV5.2 precedence: first failing item in input order wins; cutoff before other errors of the same booking; non-occupancy error wins over an occupancy conflict. Includes value errors (invalid party_size): cutoff of the same booking first (MV5.2e); earlier item's cutoff before a later item's invalid value (MV5.2f).
- MV6.1 swap of two listed bookings' tables → 201; target occupied by unlisted booking → 409 `table_unavailable`; two results on one table → 409; unchanged listed booking keeps occupancy → 409.
- MV7.1 failure changes nothing (all listed bookings and availability identical); key of failed request reusable; success body `{"reservations":[…]}` in input order incl. unchanged.
- MV8.1 replay → 200 original, also after later PATCH/cancel; no-op move returns current values unchanged; receipt survives export/import (IE3.2).
- MV9.1 20 concurrent identical moves, unused key → one 201, rest 200 identical.

## Load (§2, §5, §1)
- LOAD.1 50 concurrent signups, then 50 concurrent logins: all succeed, each < 5 s, no 5xx.
- LOAD.2 50 in-flight mixed requests (availability, create, list, cancel, patch) for several rounds: no 5xx, each < 5 s; afterwards no two confirmed reservations overlap on a table.

## Stage boundaries / supplied checks (run.sh)
- H1 [S2] harness `--stage 1` host mode and `--mode isolated`: all pass, none skipped.
- S1.1 [S1] harness `--stage 2` against stage-1 does not pass; stage-2 only features absent (`/` UI, `/lookup`, `table_ids` combined tables).
- R.1 code read once for maintainability (note only).
