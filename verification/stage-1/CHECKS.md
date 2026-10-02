# Verifier check list — Tablekeeper stage 1

Written before any check was run and before the Implementer's code or tests were read.
Measure: `dark-factory-wearedevs/tablekeeper/spec/stage-1.md` (the handoff parts 2–3 were compared with it: identical text).
Every check names the specification statement or section it tests. Row ids (A1 … M1) refer to `ACCEPTANCE-stage-1.md`;
where a check id equals a row id it covers that row. Architect decisions marked *(choice)* are not used as grounds.

Scripts (outside the repository while running; copied here for the record): `vlib.py` (HTTP client, request log, helpers),
`c_*.py` (checks), `run_checks.py` (runner + global checks), `run_all.sh` (clean clone, build, containers, both runs).

## 1. Delivery and deployment (§2) — commands and reads

- **A1** — §2 "Deliver an HTTP service, a `Dockerfile` and a `RUN.md`" — files present in `stage-1/`; no nested `.git`;
  `docker build --no-cache` of `stage-1/` from a clean clone of the exact revision succeeds using nothing outside the folder.
- **A2** — §2 "`RUN.md` with a command that builds and starts the service without manual setup" — run the RUN.md commands verbatim
  in the clean clone; `/health` answers 200.
- **A3/A4** — §2 "The image must run on its own with `-e PORT=<port>` and a port mapping. Runtime networking has no outbound
  access" — (a) container A: `-e PORT=9321 -p …:9321`; (b) containers C/D on a docker `--internal` network (no route out):
  the whole check list is run again there; (c) supplied harness with `--mode isolated`; (d) read Dockerfile/start-up for
  network use.
- **A5** — §2 limits "CPU 2 vCPU, Memory 2 GiB" — every container runs with `--cpus 2 --memory 2g`; after the runs:
  still running, `OOMKilled=false`, memory use recorded.
- **A6** — §2 / §3.2 "Start to first healthy response 60 s" — time from `docker run` to first 200 `{"status":"ok"}`.
- **A7** — §2 "Concurrent requests up to 50 in flight", "Per-request timeout 5 s (10 s for reset)" — bursts of exactly 50
  (checks H12a–c, F9, E12, A7a, A7b, I15a/b, L16a/b) and global check G-TIME over every request.
- **A8** — §5 "Requests must not produce 5xx responses, including under concurrent load" — global check G-5XX over every
  request of both runs, plus the fuzz checks A8a–c.
- **A9** — §1 "Only the HTTP API is required" / task "Do not implement later stages" — supplied harness prints
  `claimed stage: 1` and the stage-2 suite does not fully pass; read of the folder for stage-2+ features.
- **A10** — §2 "Disk: ephemeral" — read: no volume, host file or external store required.
- **A11** — preamble "Source code, API documentation and schemas from existing products in this domain must not be used" —
  read of sources and dependencies.
- **B1** — §3.1 "Listen on `0.0.0.0` using the `PORT` environment variable, default `8080`" — container A with `PORT=9321`,
  container B without `PORT` (mapped to 8080), and a request to the container's own bridge address (not loopback).
- **E11r** — §6 "Passwords must be stored using a password-hashing function such as bcrypt, scrypt or Argon2" — read of
  the code path that stores and verifies passwords (the black-box part is E11).
- **SUP** — supplied checks: `harness run --track tablekeeper --stage 1` in host mode and in `--mode isolated`, each to a
  new `--out`; a failed, skipped, deselected or errored supplied check is a failure.
- **NEXT** — the folder must not already satisfy stage 2 (harness stage-2 probe); there are no earlier units.
- **MAINT** — one read of the code for maintainability (note only).

## 2. Global checks over the request log of every run

- **G-5XX** — §5 no 5xx — no response ≥ 500 and no transport failure.
- **G-ENVELOPE** — §5 "Every 4xx and 5xx response carries this body" — `{"error":{"code":str,"message":str}}` on every error.
- **G-CTYPE** — §3.4 "responses are `application/json; charset=utf-8`" — on every response that has a body.
- **G-204** — §3.3/§10 "204 No Content" — no body on 204.
- **G-TIME** — §2 per-request limits — 5 s; 10 s for `/_test/*`.

## 3. Black-box checks (run_checks.py), in execution order

- **B2** — §3.2 — GET /health -> 200 {"status":"ok"}
- **B3** — §3.3 — POST /_test/reset -> 204, empty body, no authentication
- **B4** — §3.3 'Replace all service state ... subsequent requests must see only that fixture' — reset drops users, tokens, restaurants, reservations and idempotency records
- **B5** — §3.3 'Repeated resets are supported' — same fixture twice and alternating fixtures; nothing duplicated
- **B6a** — §3.4 'IDs ... at most 64 characters ... also applies to IDs supplied in reset fixtures' + §5 exceeding a stated length -> 422 — 65-character fixture ids (user, restaurant, table, reservation) -> 422 validation_failed; previous state kept
- **B6b** — §5 malformed_request — reset with unparseable body -> 400 malformed_request; state kept
- **B6c** — §8 'reference is 6 to 12 characters of A-Z0-9, unique across all reservations' + §5 invalid format -> 422 — seeded reference of wrong length/alphabet, or duplicated -> 422 validation_failed
- **B11** — §3.4 IDs at most 64 characters — 64-character fixture ids accepted and usable; service ids are strings <= 64
- **B9r** — §3.4 'Unknown fields in a request body are ignored' — unknown fields in the reset fixture are ignored
- **C2** — §4 fixture format / §8 GET /restaurants/{id} 'in the fixture's shape' — restaurant returned with fixture values
- **C5** — §4 'Seeded users must be able to log in with the given password immediately' — seeded login; user_id and display_name from fixture
- **C6** — §4 'reservations may seed confirmed bookings ... plus id, reference and user_id' — seeded booking is confirmed, owned, occupies its table, and behaves like an API-made one
- **C7** — §4 'A booking must not be rejected solely because its start is in the past' — create, seed and PATCH-target in the past succeed
- **C8** — §4 'the cancellation and amendment cutoff rules still apply' / §8 cancel 'or later' — cancel and PATCH of a past booking -> 409 cutoff_passed
- **B10** — §3.4 'Unknown query parameters are ignored' — extra query parameters on GET endpoints
- **A7r** — §2 per-request timeout 10 s for POST /_test/reset — reset with an ordinary-size fixture (30 users, 4 restaurants x 12 tables, 120 bookings) < 10 s
- **E1** — §6 POST /auth/signup — 201 {user_id, display_name, token}; token usable at once
- **E2** — §6 POST /auth/login — 200 {user_id, display_name, token} for a signed-up account
- **E3** — §6 'Email already registered -> 409 email_taken' — duplicate of a signed-up and of a seeded email
- **E4** — §6 'Password shorter than 8 characters -> 422' — 7 characters rejected, 8 accepted, empty rejected
- **E5** — §6 'email not of the form local@domain -> 422' — no @, empty local part, empty domain, empty string
- **E6** — §5 validation_failed 'A required field ... is missing' / malformed_request 'a field of the wrong JSON type' — signup/login: missing field -> 422; wrong JSON type -> 400; unparseable -> 400
- **E7** — §6 'Wrong password or unknown email on login -> 401 unauthenticated' — both cases
- **E8** — §6 exceptions list / §8 'public - no bearer token' — public endpoints answer without a token
- **E9** — §5 401 'Missing, malformed or unknown bearer token' / §6 'Every other endpoint requires a bearer token' — each protected endpoint x {missing, wrong scheme, no token after Bearer, unknown token} -> 401 unauthenticated
- **E10** — §6 'Tokens do not expire. An account may have multiple valid tokens and concurrent sessions' — several tokens valid together
- **E11** — §6 'Plaintext password storage is not permitted' — no plaintext password in the export document (code read covers the hash function)
- **B9a** — §3.4 'Unknown fields in a request body are ignored' — signup and login with extra fields
- **D6** — §5 404 not_found / every 4xx carries the envelope — unknown resources -> 404 not_found; unknown routes and methods answer 4xx with the envelope
- **D3** — §5/§7 'Header absent or empty -> 400 missing_idempotency_key' — POST /reservations and /reservation-moves without / with empty key
- **D12** — §5 shared ranges 'Idempotency-Key 1 to 255 characters, otherwise 422' / §7 — 1 and 255 accepted, 256 -> 422, on both keyed paths
- **F1F2** — §7 'First use -> 201' / 'Replay: same key, same body -> 200, body identical ... as a JSON value' — replay returns the original and changes nothing
- **F3** — §7 '"Same body" means the same JSON value after parsing - key order and whitespace do not matter' — reordered / re-spaced body is a replay
- **F4** — §7 'Same key, different body -> 409 idempotency_key_reuse' / 'even when that new body would otherwise be invalid' — different valid body, invalid bodies, wrong types, unknown ids, extra unknown field
- **F5** — §7 'The key is scoped to the authenticated user ... no interaction between them' — two users, one key string
- **F6** — §7 'The same key with the same body on a different path is a different request, not a replay, and must succeed normally' — one key and one body on POST /reservations then POST /reservation-moves
- **F7** — §7 'Key reused after the original request failed with 4xx -> Treated as a first use' — after 422, 404 and 409 failures; same and different body
- **F8** — §7 'A successful replay returns the original response, even after the resource changes or is cancelled. It makes no further state changes' — replay after PATCH and after cancel
- **F10** — §7 'After the body has been parsed as a JSON object and the caller authenticated, idempotency is resolved before endpoint-specific field validation' — unparseable body with a used key is 400, unauthenticated is 401, otherwise 409
- **F11** — §1 'Retries and rejected requests must not create duplicate or partial bookings' — reservation count after a mix of failures and replays
- **G1** — §8 GET /restaurants — list of {id, name, timezone}; public
- **G2** — §8 GET /restaurants/{id} '404 if unknown' — known restaurant has all configuration fields; unknown -> 404 not_found
- **G3** — §8 'All three parameters are required; a missing one is 422 validation_failed' — each parameter missing, and all missing
- **G4** — §5 'invalid format or out-of-range value gives 422 ... This includes invalid dates' — date not a real YYYY-MM-DD -> 422
- **D11** — §5 'An integer-valued query parameter is written as plain decimal digits: 1e9, 4.0 and +4 are 422' / 'negative counts' — party_size query values
- **G5** — §5 404 not_found 'No such resource' — availability for an unknown restaurant -> 404 not_found
- **G6G7** — §8 'A slot appears for every slot_minutes step from opens such that slot + reservation_duration_minutes <= closes' — response shape, slot grid and both ends of the window
- **G8** — §8 'available_table_ids lists the tables of that restaurant with capacity >= party_size ... in fixture order' — capacity boundary, fixture order, only this restaurant's tables
- **G9** — §8 'A slot with no available table still appears, with an empty list' — party larger than every table; all tables booked
- **G10** — §8 'A closed day returns "slots": []' / §4 'A day with no entry is closed' — weekday without opening hours
- **G11** — §1 'Occupancy is the half-open interval [starts_at, starts_at + reservation_duration)' / §8 'no overlapping confirmed reservation' — a 90-minute booking hides its table from every overlapping slot and not from adjacent ones
- **G12** — §8 cancel 'Frees the table immediately: the next GET /availability must offer that slot again' — cancelled reservations do not occupy
- **E8b** — §8 'public - no bearer token' — NOTE-level: a stale/garbage Authorization header on public endpoints is not an error
- **H1H2** — §8 POST /reservations 201 body / 'reservation_duration_minutes' — response fields, types, offsets, ends_at = starts_at + duration, created_at now
- **H3** — §8 'reference is 6 to 12 characters of A-Z0-9, unique across all reservations' — 280 creations next to 40 seeded references: format and uniqueness of references and ids
- **H4** — §8 'The table is taken for an overlapping interval -> 409 table_unavailable' / §1 half-open interval — every overlapping start refused; adjacent starts and other tables accepted
- **H5** — §8 'starts_at_local is not on the slot grid -> 422 not_on_slot_grid' / §4 'grid of this many minutes from opening time' — off-grid starts inside opening hours
- **H6** — §8 'Slot outside opening hours, or the reservation would end after closes -> 422 outside_opening_hours' — before opens, at/after closes, ending after closes, closed weekday; last allowed start accepted
- **H7** — §8 'party_size exceeds the table's capacity -> 422 party_exceeds_capacity' — capacity + 1 refused, capacity accepted, 1 accepted
- **H8** — §8 'party_size below 1, or not an integer -> 422 validation_failed' / §5 'invalid party_size values (including strings and booleans)' — 0, negative, fraction, string, boolean, null, array, object
- **H10** — §8 'Unknown restaurant, unknown table, or the table belongs to another restaurant -> 404 not_found' — three cases
- **H11** — §5 422 'A required field ... is missing' — each of the four create fields missing; empty object
- **D2** — §5 400 malformed_request 'Unparseable body, or a field of the wrong JSON type' — create/PATCH: unparseable, non-object, wrong-typed string fields
- **D10** — §5 'starts_at_local strings that are not a bare local YYYY-MM-DDTHH:MM are 422 validation_failed' / §8 'with no offset and no Z' — offset, Z, seconds, space separator, impossible dates and times - create and PATCH
- **B9b** — §3.4 'Unknown fields in a request body are ignored, never an error' — create and PATCH with extra fields; they cannot set protected values
- **I1** — §8 GET /reservations 'The caller's reservations, starts_at descending, confirmed and cancelled alike' — empty list, ownership, ordering by instant across zones, cancelled included, entry shape
- **I2** — §8 GET /reservations/{reference} '404 if it is not the caller's' — own -> 200 same body as create; other user's and unknown -> 404 not_found
- **I3I4** — §8 cancel '200 {reference, status: cancelled, ...}' / 'Already cancelled -> 200 with the current state' — cancel, table free and bookable, second cancel 200
- **I5** — §8 cancel 'Now is within cancellation_cutoff_minutes of starts_at, or later -> 409 cutoff_passed' / §4 cancellation_cutoff_minutes — both sides of the cutoff, about one minute from the boundary; state unchanged on refusal
- **I4b** — §8 'Already cancelled -> 200 with the current state - cancelling twice is not an error' — cancel repeated five more times: 200 with the same state each time
- **I6** — §8 cancel 'Not the caller's reservation -> 404 not_found' — other user's and unknown reference; booking stays confirmed
- **I7** — §8 PATCH 'Change the time, the table or the party size. Any subset ... No idempotency key is required' — each single field, pairs, all three; identity and created_at kept; times recomputed
- **I8** — §8 PATCH 'Validation is identical to POST /reservations' — every create error code through PATCH, judged on merged values; booking unchanged after each
- **I9** — §8 PATCH 'the same cutoff rule as cancel applies (409 cutoff_passed), measured against the current start time' — past booking cannot be moved to the future; future booking can be moved into the past, after which it is locked
- **I10** — §8 PATCH 'A cancelled reservation is 409 reservation_cancelled' — any PATCH of a cancelled booking
- **I11** — §8 GET/PATCH ownership, §5 not_found 'not visible to this caller' — PATCH of another user's or unknown booking -> 404; target unchanged
- **I12** — §8 PATCH 'A successful amendment releases the old slot and reserves the new one together' — old slot free, new slot taken; moving onto an interval overlapping its own old one succeeds
- **I16** — §8 PATCH 'Any subset of table_id, starts_at_local, party_size' (the empty subset) / §3.4 unknown fields ignored — PATCH {} and unknown-only fields -> 200, nothing changed
- **J1** — §9 'Offsets must follow the IANA rules for the specified zone and date' / §3.4 timestamps with explicit offset — standard and summer offsets for Berlin, New York and two further IANA zones
- **J2a** — §9 Spring forward 'never appear in availability, and booking one is 422 invalid_local_time' (Europe/Berlin 2026-03-29) — availability skips 02:00-02:59, offsets switch, gap bookings refused via create and PATCH, neighbours fine
- **J2b** — §9 Spring forward (America/New_York 2026-03-08) — availability skips 02:00-02:59, offsets -05:00 -> -04:00, gap booking refused
- **J3a** — §9 Fall back 'Always resolve to the first occurrence ... The slot appears once in availability' (Europe/Berlin 2026-10-25) — repeated hour listed once with +02:00; 03:00 has +01:00; bookings in the repeated hour take the first occurrence
- **J4** — §9 'A 90-minute reservation starting at 01:30 on a fall-back night ends 90 real minutes later, and its local ends_at will read 02:00, not 03:00' — Berlin 2026-10-25 01:30 + 90 min
- **J3b** — §9 Fall back (America/New_York 2026-11-01, 02:00 -> 01:00) — 01:00/01:30 listed once with -04:00; 02:00 has -05:00; absolute duration
- **J5a** — §9 'reservation_duration_minutes is absolute time, not wall-clock' / §1 occupancy interval - fall back — occupancy across the repeated hour uses instants: no false overlap, no false clearance
- **J5b** — §9 absolute duration / §1 occupancy interval - spring forward — a 90-minute booking at 01:30 before the gap occupies until 04:00 local
- **L12** — §11 'On success return 201 with {"reservations": [...]} in input order, including unchanged items' + the §11 example (swap) — swap two tables; rotation of three; order and shape of the response
- **L1** — §11 'requires authentication and an idempotency key' / 'No token gives 401' — 401 without token; 400 without key; body must be a JSON object
- **L2** — §11 'moves contains 1..8 objects with distinct string references. Invalid shape or duplicate references gives 422 validation_failed' — 0 and 9 items refused, 1 and 8 accepted; non-array, missing, non-object item, bad reference, duplicates
- **L3** — §11 'Unknown/another owner's reference gives 404 not_found' — unknown, other owner's, and mixed with valid items; nothing moves
- **L4** — §11 'Every booking must belong to the caller and the same restaurant ... different restaurants give 422 validation_failed' — two restaurants in one batch
- **L5** — §11 'Each item accepts the ordinary PATCH fields ...; omitted fields retain their current values and unknown fields are ignored' — party only, table only, time only, all three, unknown fields; times recomputed
- **L6** — §11 'Cancelled bookings give 409 reservation_cancelled' — a cancelled booking anywhere in the batch
- **L7L8** — §11 'Each booking's existing cutoff applies. Non-occupancy errors use ordinary amendment codes and take precedence in input order, with cutoff errors preceding other changes for that booking' — cutoff; amendment codes; first failing item decides; cutoff before that booking's other errors; non-occupancy before occupancy
- **L9L10** — §11 'An overlap among resulting bookings or with an unlisted booking gives 409 table_unavailable. Unchanged listed bookings retain their occupancy' — unlisted booking, two items onto one table, unchanged listed item; nothing moves
- **L11** — §11 'Either every move commits or nothing changes: occupancy, reservation records and retry keys' — failed batch leaves records and occupancy alone and does not consume its key
- **L13** — §11 'Replays return that original response with 200, even after amendments or cancellations' / §7 — replay, replay after PATCH and cancel, different body 409 (also invalid), per-user scope
- **L14** — §11 'The booking's identity, owner and creation time never change' / 'No-op moves retain all existing values' — no-op batch returns current values; moved bookings keep id, reference, created_at and owner
- **K1** — §10 'Return 200 from export with a JSON object containing track: "tablekeeper", format_version: 1 and state (an implementation-defined JSON object)' — export document shape; unauthenticated; read-only
- **K2K4K9** — §10 'Import takes that entire object and atomically replaces the service's state, returning 204 ... No dependency on the source process' / 'Preserve accounts and hashed-password login, existing bearer tokens, fixture configuration, reservations, references' — export from container A, import into container B: tokens, logins, restaurants, availability and every reservation identical
- **K8** — §10 'Export is an atomic, read-only snapshot; subsequent source writes do not change it' / 'Reset continues to clear all state, including imported state' — writes after export, then import of the earlier export restores the earlier state on the same container; reset afterwards clears it
- **K7** — §10 'Invalid JSON follows §5; missing fields, wrong track/version or an invalid state give 422 validation_failed without changing the destination' — each invalid import leaves tokens, restaurants, reservations and keys as they were
- **H12a** — §1 'Two confirmed reservations must never occupy the same table at overlapping times, including during concurrent requests' — 50 clients race for one table and slot: exactly one 201, 49 x 409 table_unavailable
- **H12b** — §1 invariant under concurrency — 50 clients race for mutually overlapping slots on one table: exactly one wins
- **H12c** — §1 invariant under concurrency / §8 reference 'unique across all reservations' — 50 clients over five start times of one table: successes never overlap; 50 distinct tables all succeed with distinct references
- **F9** — §7 'For concurrent identical requests with an unused key, exactly one returns 201. The others return 200 with the same body. The operation takes effect only once' — 50 identical POST /reservations with one key
- **E12** — §6 'Email already registered -> 409 email_taken' under concurrency / §2 per-request 5 s — 50 concurrent signups with one email: one 201, 49 x 409
- **A7a** — §2 'Concurrent requests: up to 50 in flight' / 'Per-request timeout 5 s' — 50 concurrent logins, 50 concurrent distinct signups, 50 concurrent availability reads, each under 5 s
- **I15a** — §8 PATCH 'releases the old slot and reserves the new one together' / §1 invariant under concurrency — 50 bookings PATCH onto one free table at once: exactly one 200, 49 x 409
- **I15b** — §8 cancel 'Frees the table immediately' / §1 invariant under concurrency — one cancel racing 49 creates for the same table and slot: never two confirmed
- **L16a** — §7 concurrent identical requests / §11 replays — 50 identical batches with one key: one 201, 49 x 200 with the same body
- **L16b** — §11 'An overlap among resulting bookings or with an unlisted booking gives 409 table_unavailable' / §1 invariant under concurrency — 50 conflicting batches onto one free table: one 201; then 25 batches against 25 creates: one success in total
- **A7b** — §2 '50 in flight' / §5 'Requests must not produce 5xx responses, including under concurrent load' — 50 mixed requests at once (reads, creates, PATCH, cancel, moves, login, export): no 5xx, each under its limit, invariant holds
- **A8a** — §5 no 5xx / envelope — every field of every JSON endpoint replaced by junk values of each JSON type
- **A8b** — §5 no 5xx / envelope — raw bodies, odd headers, odd paths, methods and query strings
- **A8c** — §5 no 5xx / envelope; §3.3 reset — fixtures with wrong types or impossible values: no 5xx at reset or on the requests that follow

## 4. Deliberately not checked (no statement in the specification decides them)

- Order between 401 and a missing `Idempotency-Key`; order among several simultaneous validation errors other than the
  orders §7 and §11 state; the doubly-wrong grid/hours case (decision X2, *choice*).
- `party_size: 4.0` in a body, a lower-case `t` in `starts_at_local`, leading zeros in query integers, e-mail case folding.
- Reset fixtures with duplicate ids, unknown references, overlapping seeds, or invalid opening hours: only "no 5xx, error
  envelope, and whatever is accepted stays servable" is asserted (A8c). 65-character ids and bad/duplicate seeded
  references are asserted as 422 (B6a, B6c) because §3.4, §5 and §8 state them.
- Cancelling or no-op moving a booking that is both cancelled and past its cutoff.
- Inputs sized to exhaust memory, CPU or time; more than 50 requests in flight.
- **E8b** is note-level: the specification says the endpoints are public but does not say a stale header must be ignored.
