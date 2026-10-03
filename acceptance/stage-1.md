# Stage 1 acceptance map (Tablekeeper — reservations)

Source: `dark-factory-wearedevs/tablekeeper/spec/stage-1.md`. Every row is checked by the
Verifier. "H" = harness suite (`--stage 1`), "P" = Verifier probe (curl/script against the
built container), "R" = code/repo review. Folder: `stage-1/`. Stage 1 must NOT implement
stage-2+ features (no UI, no stage-2 endpoints).

| Row | Spec | Requirement | Check |
|---|---|---|---|
| D1 | §2 | `stage-1/Dockerfile` builds; `stage-1/RUN.md` has a single command that builds and starts the service, no manual setup | R + `docker build` |
| D2 | §2 | Runs alone with `-e PORT=<port>` and port mapping; no outbound network at runtime; all deps/seed in image; no compose needed | P: `docker run --network none`-style start, health OK |
| D3 | §2 | Within 2 vCPU / 2 GiB; healthy ≤60 s; 50 concurrent in-flight; each request <5 s (reset <10 s) | P: `docker run --cpus 2 --memory 2g`, time to health, 50-parallel load |
| D4 | §2 | Ephemeral state OK | n/a |
| C1 | §3.1 | Listen 0.0.0.0, `PORT` env, default 8080 | P: run without PORT → 8080 |
| C2 | §3.2 | `GET /health` → 200 `{"status":"ok"}` once ready | H + P |
| C3 | §3.3 | `POST /_test/reset` → 204, replaces all state (users, restaurants, reservations, tokens, idempotency records); repeatable; no auth | H + P: reset twice, old token → 401, old reservations gone |
| C4 | §3.4 | JSON `application/json; charset=utf-8` on all responses | P: check Content-Type |
| C5 | §3.4 | Timestamps RFC 3339 with explicit offset (`+00:00` style, not `Z` required? — use `+HH:MM`) | H + P |
| C6 | §3.4 | Unknown body fields and unknown query params ignored | P |
| C7 | §3.4 | IDs opaque ≤64 chars; fixture IDs >64 chars rejected by reset with 422 `validation_failed` | P |
| M1 | §4 | Fixture: users (id,email,password,display_name), restaurants (id,name,timezone,slot_minutes,reservation_duration_minutes,cancellation_cutoff_minutes,opening_hours[weekday,opens,closes],tables[id,label,capacity]), reservations | H + P |
| M2 | §4 | Seeded users log in immediately with given password | H |
| M3 | §4 | Seeded reservations (POST body + id, reference, user_id) are confirmed, occupy tables, visible to owner, cancellable/patchable | H + P |
| M4 | §4 | Past dates not rejected for booking; cutoff still applies | P |
| M5 | §4 | Closed weekday (no entry) → no slots | H |
| E1 | §5 | Every 4xx/5xx body is `{"error":{"code","message"}}` | P across all error paths, incl. 404 unknown route, 405 |
| E2 | §5 | Unparseable body / wrong JSON type → 400 `malformed_request` (non-object body too) | P |
| E3 | §5 | Correct type but invalid format/range → 422 `validation_failed` (invalid dates, negatives, over-max, lengths) | P |
| E4 | §5 | `party_size` invalid incl. strings/booleans/floats/0/negative → 422 `validation_failed` (not 400) | H + P |
| E5 | §5 | `starts_at_local` not bare `YYYY-MM-DDTHH:MM` (offset, Z, seconds, garbage, non-string?) → 422 `validation_failed` | H + P |
| E6 | §5 | Integer query params must be plain digits: `1e9`, `4.0`, `+4` → 422 | H + P |
| E7 | §5 | `Idempotency-Key` length 1..255; >255 → 422 `validation_failed`; empty → 400 `missing_idempotency_key` | P |
| E8 | §5 | No 5xx ever, including under concurrent load | P load test |
| A1 | §6 | `POST /auth/signup` → 201 `{user_id,display_name,token}` | H |
| A2 | §6 | `POST /auth/login` → 200 same shape | H |
| A3 | §6 | Duplicate email → 409 `email_taken` (decide + document case-insensitivity) | H + P |
| A4 | §6 | Password <8 chars → 422; email not `local@domain` → 422; missing fields → 422; wrong types → 400 | P |
| A5 | §6 | Wrong password / unknown email → 401 `unauthenticated` | H |
| A6 | §6 | All endpoints except /health, /_test/*, /auth/signup, /auth/login, GET /restaurants, GET /restaurants/{id}, GET /availability require bearer; missing/malformed/unknown → 401 | H + P |
| A7 | §6 | Tokens never expire; multiple concurrent tokens per account valid | P |
| A8 | §6 | Passwords hashed with bcrypt/scrypt/Argon2/PBKDF2-equivalent; no plaintext (incl. in export) | R |
| I1 | §7 | Idempotency on `POST /reservations` and `POST /reservation-moves` only | H |
| I2 | §7 | Missing/empty header → 400 `missing_idempotency_key` | H |
| I3 | §7 | Scoped per user; different users same key independent | P |
| I4 | §7 | Replay = same user+method+path+body (JSON-value equality, key order/whitespace irrelevant); same key different path = new request | P |
| I5 | §7 | Order: parse JSON object → auth → idempotency → field validation/resource checks; used key + different (even invalid) body → 409 `idempotency_key_reuse` | P |
| I6 | §7 | First use 201; replay 200 with identical body JSON; diff body 409 | H |
| I7 | §7 | Key reused after original 4xx → treated as first use | H + P |
| I8 | §7 | Concurrent identical unused-key requests → exactly one 201, rest 200 same body, effect once | H + P |
| I9 | §7 | Replay returns original response even after resource cancelled/changed; no state change | P |
| R1 | §8 | `GET /restaurants` public, `{restaurants:[{id,name,timezone}]}` | H |
| R2 | §8 | `GET /restaurants/{id}` public: fixture shape with slot_minutes, reservation_duration_minutes, cancellation_cutoff_minutes, opening_hours, tables; 404 `not_found` | H |
| V1 | §8 | `GET /availability` public; restaurant_id, date, party_size required → 422 when missing | H |
| V2 | §8 | Invalid date format / impossible date → 422; party_size non-digit/0 → 422; unknown restaurant → 404 | P |
| V3 | §8 | Response `{restaurant_id,date,timezone,slots:[{starts_at_local,starts_at,available_table_ids}]}` | H |
| V4 | §8 | Slots every slot_minutes from opens while slot+duration <= closes; empty-table slots still listed; tables capacity>=party, non-overlapping, fixture order | H + P |
| V5 | §8 | Closed day → `slots: []` | H |
| B1 | §8 | `POST /reservations` → 201 with reservation_id, reference, restaurant_id, table_id, party_size, status confirmed, starts_at_local, starts_at, ends_at, created_at | H |
| B2 | §8 | reference 6–12 chars `[A-Z0-9]`, globally unique (incl. vs seeded), immutable | H + P |
| B3 | §8 | Overlap (half-open) → 409 `table_unavailable`; 90-min at 19:00 does not overlap 20:30; cancelled bookings don't block | H + P |
| B4 | §8 | Off-grid → 422 `not_on_slot_grid` | H |
| B5 | §8 | Outside hours / ends after closes → 422 `outside_opening_hours` (incl. closed day) | H |
| B6 | §8 | party > capacity → 422 `party_exceeds_capacity` | H |
| B7 | §8 | Nonexistent local time → 422 `invalid_local_time` | H |
| B8 | §8 | Unknown restaurant/table or table of other restaurant → 404 `not_found` | H |
| B9 | §1 | No double-booking under concurrent requests (exactly one 201 among racing creates for same table/slot) | H + P |
| B10 | — | Error precedence among booking checks: decide and document (recommended: shape 422 → 404 → invalid_local_time → grid → hours → capacity → availability 409) | R |
| L1 | §8 | `GET /reservations` caller's own only, starts_at desc, confirmed+cancelled, `{reservations:[]}` when empty | H + P |
| G1 | §8 | `GET /reservations/{reference}` → own only; other's → 404 | H |
| X1 | §8 | Cancel → 200 status cancelled, full shape; frees slot immediately | H |
| X2 | §8 | Cancel twice → 200 current state | H |
| X3 | §8 | now >= starts_at − cutoff → 409 `cutoff_passed` (including past bookings) | H + P |
| X4 | §8 | Other's reservation → 404 | H |
| P1 | §8 | PATCH any subset of table_id, starts_at_local, party_size; no idempotency key | H |
| P2 | §8 | Same validation as POST; cutoff vs current start → 409 `cutoff_passed`; cancelled → 409 `reservation_cancelled` | H + P |
| P3 | §8 | Atomic release+reserve: may move into own overlapping slot on same table; failed patch leaves original unchanged | P |
| P4 | §8 | reference & reservation_id unchanged; other's → 404 | H + P |
| T1 | §9 | Spring-forward skipped times absent from availability; booking → 422 `invalid_local_time` | H |
| T2 | §9 | Fall-back ambiguous time → first occurrence; appears once in availability | H |
| T3 | §9 | Duration in absolute time; ends_at offset correct (01:30 fall-back +90 → 02:00 local w/ new offset) | H + P |
| T4 | §9 | Correct IANA offsets for Europe/Berlin and America/New_York 2026 transitions (tzdata in image) | P |
| T5 | §8/§9 | Overlap computed on absolute instants | P |
| IE1 | §10 | `GET /_test/export` → 200 `{track:"tablekeeper",format_version:1,state:{...}}`; atomic read-only snapshot | H + P |
| IE2 | §10 | `POST /_test/import` → 204, atomic full replacement (not merge); repeatable | H + P |
| IE3 | §10 | Preserves users + hashed-password login, tokens, fixture config, reservations, references, idempotency records & original responses, batch receipts, IDs, statuses, timestamps; failed keys remain reusable | H + P |
| IE4 | §10 | Invalid JSON → 400; missing fields / wrong track / wrong version / invalid state → 422 `validation_failed` with destination unchanged | P |
| IE5 | §10 | Import into a fresh container works (no dependency on source process); reset clears imported state | H (isolated) + P |
| IE6 | §10 | ID/reference generators continue without collision after import | P |
| MV1 | §11 | `POST /reservation-moves` auth (401) + idempotency (§7) | H + P |
| MV2 | §11 | moves 1..8 objects, distinct string references; bad shape/dup → 422 `validation_failed` | P |
| MV3 | §11 | Unknown/other-owner reference → 404; different restaurants → 422 | P |
| MV4 | §11 | Per item PATCH fields; omitted retain; identity/owner/created_at unchanged | P |
| MV5 | §11 | Cancelled → 409 `reservation_cancelled`; per-booking cutoff → 409 `cutoff_passed`; non-occupancy errors in input order, cutoff before other errors for a booking | P |
| MV6 | §11 | Overlap among results or with unlisted booking → 409 `table_unavailable`; swaps between listed bookings allowed; unchanged listed bookings keep occupancy | H + P |
| MV7 | §11 | All-or-nothing (occupancy, records, retry keys); 201 `{reservations:[...]}` in input order incl. unchanged | H + P |
| MV8 | §11 | Replay 200 original even after later changes; no-op moves keep values; export/import keeps batch receipts | P |
| S1 | guide | `stage-1/` must not pass the stage-2 suite (no early stage-2 features) | H: `--stage 2` run expected to fail stage-2 suite |
| S2 | task | Final stage-1 check run with `--mode isolated` passes | H isolated |

## Amendments

- 2026-10-03 (after round-1 BLOCK): row P2/MV5 order fixed by Architect decision — single PATCH uses
  the same per-booking order as §11 moves: 404 not caller's → non-object body 400 → cancelled 409 →
  cutoff 409 → field validation → semantic checks → occupancy. Row C3/E2: reset fixture fields of the
  wrong JSON type are 400 `malformed_request`; right type but invalid value 422; import invalid state 422.
