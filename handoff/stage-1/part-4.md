@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier
STAGE 1 HANDOFF — part 4 of 5: ACCEPTANCE MAP rows A–F
Rows: all (A1–M1) · Revision: base 71417847b61264fa969a23c01b4d8c3c4f147caf plus the Architect commit that adds ACCEPTANCE-stage-1.md (see `git log`) · Files: ACCEPTANCE-stage-1.md, STATUS.md, handoff/stage-1/ (this text), target stage-1/ (does not exist yet) · Command: n/a · Expected / actual: n/a (nothing built yet) · Repro: n/a · Next: Implementer builds stage-1/; Verifier prepares its check list and scripts (no verdict yet)

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

