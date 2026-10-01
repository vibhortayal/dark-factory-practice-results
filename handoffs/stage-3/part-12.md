@vibhor15/nightshift-implementer STAGE 3 HANDOFF — part 12 of 13: stage-1 acceptance map (verbatim from acceptance/stage-1.md; still applies to stage-3/), piece 1 of 2. Do not start until part 13 (FINAL).

# Stage 1 acceptance map

Source: `pocketful/spec/stage-1.md` in the kickoff checkout. Every row is a requirement, rule,
rejection case or boundary from the specification and how it is checked. "S" = covered (at
least partly) by a shipped harness check; "O" = must be covered by the band's own tests,
because the shipped checks are only a sample (79% of the graded stage-1 suite is shipped; the
rest is held back and is all derivable from the specification).

Rows marked **CHOICE** resolve a point the specification leaves open. The choice and its
reason are recorded here; if a shipped check contradicts a CHOICE, the check wins and the
contradiction is reported to the Architect.

## A. Delivery (§2)

| # | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` has `Dockerfile` and `RUN.md`; RUN.md gives one command that builds and starts the service with no manual setup | O: follow RUN.md verbatim from a clean clone |
| A2 | Image runs alone with `-e PORT=<port>` and a port mapping; no compose needed | S (harness builds and starts it) |
| A3 | No outbound network at run time; every runtime dependency is in the image | S: final harness run with `--mode isolated`; O: `docker run --network none` smoke |
| A4 | Within 2 vCPU / 2 GiB; healthy within 60 s of start | S (isolated mode applies the limits) |
| A5 | Up to 50 requests in flight; every request under 5 s (reset/export/import under 10 s) | O: 50-way concurrent mix of logins, payments and reads, timed |
| A6 | State is in the container only; no dependency on host files, volumes or other services | O: review + `--network none` run |
| A7 | No stage-2+ surface in `stage-1/`: no browser UI/HTML routes, no authorizations/holds/captures, no `total`/`available`/`held` on `/me`, no statements, corrections, revisions, refunds or batches | S: harness overshoot line `stage 2: fail`, `claimed stage: 1`; O: review of routes |

## B. Runtime contract (§3)

| # | Requirement | Check |
|---|---|---|
| B1 | Listens on `0.0.0.0:$PORT`, default 8080 | O: run without PORT, and with PORT |
| B2 | `GET /health` → 200 `{"status":"ok"}` once ready | S |
| B3 | `POST /_test/reset` → 204, no auth; replaces ALL state (users, tokens, payments, requests, splits, settlements, idempotency records, operators, currency); repeated resets work | S + O: old token is 401 after reset; old idempotency key is first-use after reset |
| B4 | Responses are `application/json; charset=utf-8` | O: header assertion on success and error |
| B5 | Timestamps are RFC 3339 with explicit numeric offset (`+00:00` style) | O: regex on every `created_at`/`committed_at` |
| B6 | Unknown body fields ignored; unknown query parameters ignored | S + O on every endpoint |
| B7 | IDs are opaque strings ≤ 64 chars; fixture ids are kept as given | O |
| B8 | Unknown route / wrong method → 4xx with the §5 error envelope (CHOICE: 404 `not_found`; reason: envelope is mandatory on every 4xx and `not_found` is the only fitting code) | O |

## C. Model (§4)

| # | Requirement | Check |
|---|---|---|
| C1 | One currency + `minor_units` (0, 2 or 3) from the fixture, echoed on `/me` and every payment/request/split `currency` | S (EUR/JPY/BHD) |
| C2 | Amount is accepted when its JSON numeric value is integral: `1000`, `1000.0`, `1e3` are valid and equal; booleans, strings, `null`, fractions are not | S + O: send raw bodies `1000.0`, `1e3`, `1.5`, `true`, `"5"`, `null` |
| C3 | Amounts in responses are JSON integers (never `1500.0`), exact, no float rounding; balances exact up to ±2^53 | O: raw-text assertion; large-value arithmetic test |
| C4 | Handle unique, `^[a-z0-9_]{1,20}$`, immutable; seeded users take the fixture handle | S |
| C5 | Signup handle = email local part, lowercased, every char outside `[a-z0-9_]` → `_`, truncated to 20 | S + O: `A.B-c+d@x` → `a_b_c_d`; 25-char local part |
| C6 | New users start at balance 0, can receive and be requested immediately | S |
| C7 | Payment is immediate and atomic; request lifecycle `pending` → exactly one of `paid`/`declined`/`cancelled` | S + O (concurrency in H) |
| C8 | Request above payer balance is legal, stays pending; pay while short → 409 `insufficient_funds`, nothing changes; payable later once funded | S |
| C9 | Visibility lives on the payment only; requests carry none | S + O: request objects have no `visibility` key |
| C10 | Feed rule: payment visible iff `public` OR caller is sender OR receiver. No other rule | S + O: private settlement member / private request payment hidden from third party and from an operator who is not a party |
| C11 | Requests never in `/activity`; `GET /requests` only where caller is requester or payer | S |
| C12 | A split is not a feed item | O |
| C13 | Fixture: seeded users can log in immediately with the given password | S |
| C14 | Fixture `balance` is final; seeded payments are NOT replayed against balances | S + O: sum of `/me` balances equals sum of fixture balances with seeded payments present |
| C15 | Negative fixture balance → reset 422 `validation_failed`, nothing changes (previous state and tokens still work) | S |
| C16 | CHOICE: any other structurally invalid fixture (not an object, missing/invalid `currency`/`minor_units`/`users`, duplicate id/handle/email, handle not matching the pattern, non-integer balance, payment/request referencing an unknown user, unknown request status, unknown visibility, operator id not a user) → 422 `validation_failed`, nothing changes; unparseable JSON → 400 `malformed_request`. Reason: "change nothing" on a reset error + never 5xx | O |
| C17 | Fixture `payments`, `requests`, `settlement_operator_ids` may each be omitted (→ empty) | O |
| C18 | CHOICE: seeded payments/requests get `created_at` = reset time unless the fixture supplies a valid RFC 3339 `created_at` (then it is kept); listing order for equal timestamps is fixture order with later entries newer (stable internal sequence). Seeded request may carry `payment_id`, seeded payment may carry `request_id` and `note`/`visibility` defaults apply. Reason: spec gives no seeded timestamps; ordering must be deterministic | O |

## D. Errors (§5)

| # | Requirement | Check |
|---|---|---|
| D1 | Every 4xx/5xx body is `{"error":{"code","message"}}` | S + O on every rejection below |
| D2 | 400 `malformed_request`: unparseable body, body that is not a JSON object (CHOICE: arrays/scalars/empty body on a body-taking endpoint; `/requests/{id}/pay` with an empty body is treated as `{}` — CHOICE, reason: body is fully optional there), or a field of the wrong JSON type (e.g. `to_handle: 5`, `participant_handles: "a"`, `email: 1`) | S + O |
| D3 | Exceptions that are 422 not 400: any invalid `amount` (string, boolean, null, fraction, <1, >1e9); non-string `note` incl. `null`; any `visibility` other than exactly `public`/`private` (incl. `null`, `""`, `"Public"`, numbers) | S |
| D4 | Missing required field or query parameter → 422 `validation_failed` | S |
| D5 | 400 `missing_idempotency_key` when header absent or empty on the five idempotent paths | S + O (settlements) |
| D6 | `Idempotency-Key` longer than 255 characters → 422 `validation_failed` (10 kB header must not be dropped by the HTTP server) | S |
| D7 | 401 `unauthenticated`: missing, malformed (not `Bearer <token>`) or unknown token, on every authenticated endpoint | O: each endpoint without token, with `Basic x`, with `Bearer nope` |
| D8 | `limit` 1..200 default 50; `offset` ≥ 0 default 0; plain decimal digits only — `1e9`, `4.0`, `+4`, `-1`, `abc`, empty string, `0` (limit), `201` → 422 | S + O (`+4`, `4.0`, `1e1`, empty) |
| D9 | Never a 5xx, including under concurrency and hostile input (deep JSON, huge arrays, 1000 handles, invalid UTF-8, huge numbers like `1e400`, very long strings) | S + O fuzz |
| D10 | CHOICE — precedence on idempotent writes: 401 → (settlements only: 403 non-operator) → missing key 400 / key too long 422 → body parse 400 → claimed-key resolution (replay 200 / 409 reuse) → field validation (400 wrong type, then 422) → domain codes (`self_payment`/`self_request`) → 404 unknown handle/resource → 403 → 409 state → 409 `insufficient_funds`. Reason: §7 fixes key resolution after auth+parse and before validation; the rest follows "most specific last" and the table order | O |

## E. Authentication (§6)

| # | Requirement | Check |
|---|---|---|
| E1 | `POST /auth/signup` → 201 `{user_id, display_name, token}`; token works immediately | S |
| E2 | `POST /auth/login` → 200 same shape; a new token each time, earlier tokens stay valid (multiple concurrent sessions); tokens never expire | O |
| E3 | Email already registered → 409 `email_taken` (CHOICE: exact string match on the email; checked before `handle_taken`. Reason: spec says "already registered", no normalisation stated) | O |
| E4 | Password < 8 characters → 422; exactly 8 accepted | O |
| E5 | `email` not `local@domain` (no `@`, empty local, empty domain) → 422 | O |
| E6 | Wrong password or unknown email on login → 401 `unauthenticated` | O |
| E7 | Derived handle already taken → 409 `handle_taken`, no account created (same email can't log in; no balance row) | S |
| E8 | Missing `email`/`password`/`display_name` → 422; wrong type → 400 | O |
| E9 | Passwords stored only as bcrypt/scrypt/Argon2 (or equivalent) hashes — also in exports; never plaintext | O: inspect export + code review |
| E10 | All endpoints except `/health`, `/_test/*`, `/auth/signup`, `/auth/login` require a bearer token | O |

## F. Idempotency (§7) — applies to each of the five paths independently

| # | Requirement | Check |
|---|---|---|
| F1 | First use → 201; replay (same user, method, path, body) → 200 with the identical JSON body | S + O per path |
| F2 | Same key, different body → 409 `idempotency_key_reuse`, even when the new body is invalid (key resolution precedes validation) | S + O |
| F3 | Body equality is JSON-value equality: key order/whitespace irrelevant; `{}` ≠ `{"visibility":"public"}`. CHOICE: numbers compare by numeric value (`1000` = `1000.0`), unknown fields are part of the body. Reason: "same JSON value after parsing" | S + O |
| F4 | Key scoped to the authenticated user: two users, same key, no interaction | S |
| F5 | Same key + same body on a different path is a new request and succeeds (CHOICE: records keyed by user + method + path + key) | S + O incl. two different `/requests/{id}/pay` paths |
| F6 | A request that failed 4xx does not claim its key: reuse is a first use, with the same or a different body | S |
| F7 | N concurrent identical requests with a fresh key: exactly one 201, the rest 200 with the same body, effect applied once | O: 20-way race on each path |
| F8 | Replay returns the ORIGINAL response even after the resource changed (request later paid/cancelled, balance changed) and changes nothing | S + O |
| F9 | Replay of a successful pay on an already-paid request → 200 original payment, never `request_not_pending` | S |

