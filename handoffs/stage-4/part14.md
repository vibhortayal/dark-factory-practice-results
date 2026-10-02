@vibhor15/nightshift-implementer @vibhor15/nightshift-verifier Rows: stage-4 map GG1..JJ3, stage-3 map AA1..ZZ3, stage-2 map M1..V7 with Q11, stage-1 map A1..K10 · Revision: e57b830ffcc4e8716660c93348a830a927836079 (maps and status; accepted: stage-1/ 77409dda43334b784ca1125d2d990ba51478abf6, stage-2/ 88b9223d3e56cd9a668499f3cd5b87575d0ea114, stage-3/ aedbe2c666e7b1b97661ad869d77f002bb103eca; stage-4/ does not exist yet) · Files: acceptance/stage-4.md, stage-3.md, stage-2.md, stage-1.md, STATUS.md · Command: n/a · Expected / actual: stage-4/ to be built / not yet built · Repro: n/a · Next: Implementer builds stage-4/ and reports a committed revision; Verifier prepares its checks now and waits for that revision.

STAGE 4 HANDOFF, part 14 of 15. ACCEPTANCE MAP, stage 1, as it stands (part 1 of 2: sections A to F). It continues to apply to stage-4/, except row L1.

# Acceptance map: stage 1

Source: `pocketful/spec/stage-1.md` in the kickoff checkout (§ numbers below refer to it).
Target folder: `stage-1/`. Every row must hold; the supplied checks cover only some rows.
"Check" says how the Verifier establishes the row: `H` = supplied harness run,
`P` = the Verifier's own HTTP probe against the built image, `I` = inspection of source or image.

Rows marked **[D]** record a decision the Architect made where the specification leaves a
choice open; the reason is given so the choice can be re-examined, not waived.

## A. Delivery and runtime (§2, §3)

| Row | Requirement | Check |
|---|---|---|
| A1 | `stage-1/` holds source, a `Dockerfile` and a `RUN.md` whose command builds and starts the service with no manual setup. No `.git`, submodule or symlink inside the folder. | I, P: follow RUN.md literally from a clean build |
| A2 | The image runs alone with `-e PORT=<port>` and a port mapping; listens on `0.0.0.0:$PORT`, default `8080` when `PORT` is unset. | P: run with and without `PORT` |
| A3 | No outbound network at run time; all dependencies, initialisation and seed data inside the one container; Compose is not needed to start. | H `--mode isolated`; P: `docker run --network none` plus exec probe, or internal network |
| A4 | Healthy within 60 s of container start: `GET /health` -> 200 `{"status":"ok"}`. | P: time from `docker run` to first 200 |
| A5 | Works within 2 vCPU / 2 GiB with up to 50 requests in flight; each request < 5 s (reset, export, import < 10 s). | P: run with `--cpus 2 --memory 2g`, 50-way bursts, record max latency |
| A6 | No request produces a 5xx, including under concurrent load and with hostile input (huge numbers, deep or huge bodies, wrong types, non-UTF-8 bytes, unknown routes and methods). | P: fuzz table + bursts, assert no status >= 500 |
| A7 | Requests and responses are `application/json; charset=utf-8`; a request without or with a different `Content-Type` but a parseable JSON body must not 5xx. | P: header check on success and error responses |
| A8 | Every timestamp in a response is RFC 3339 with an explicit numeric offset (`+00:00` form, not a bare local time). | P: regex over every `created_at` / `committed_at` |
| A9 | Unknown body fields are ignored; unknown query parameters are ignored. | H, P |
| A10 | Every ID is an opaque string of at most 64 characters, including seeded IDs returned unchanged. | P |
| A11 | Every 4xx/5xx body is `{"error":{"code":..., "message":...}}`, including 404 for an unknown route and 405-style cases. Unknown route is 404 `not_found` (after auth where the route family needs it). | P |
| A12 | **[D]** (added after BLOCK 1) The service's own size caps never produce a bare or mislabelled answer. (a) Request head: accepted up to at least 1 MiB, so an over-long `Idempotency-Key`, query value or bearer token reaches the service's own rules (422 for the key or `limit`/`offset`, 401 for an unknown token). A head beyond the cap is answered 422 `validation_failed` with the standard error body. (b) Request body: any body the service declines to read or process because of its own size or nesting cap is 422 `validation_failed` (a body within the stated field limits cannot be that large, so some stated or implied limit is exceeded); 400 `malformed_request` stays reserved for bytes that are not valid JSON and for wrong JSON types. Authentication is still answered first (401) where the route needs it. The body cap is at least 8 MiB on API routes and large enough on reset/import for any state the service can export. (c) A valid-JSON body nested deeper than the service can compare or validate is 422, not 400; a non-string `note` is 422 at any depth the service parses. Reason: §5 gives 422 for "values exceeding a stated maximum or length" and reserves 400 for a body that does not parse; every 4xx must carry the error body. | P: 17,000-char key and `limit`; 2,200,000-char note; 40,000 transfers; 2 MiB-plus head; deep nesting |
| A13 | **[D]** (added after BLOCK 1) Path parameters are compared after percent-decoding, so `/requests/rq%5F1/pay` and `/requests/rq_1/pay` are the same resource and the same idempotency scope. An undecodable escape is 404 `not_found`. | P |

## B. Reset, fixture, model (§3.3, §4)

| Row | Requirement | Check |
|---|---|---|
| B1 | `POST /_test/reset` with a fixture -> 204, no auth; afterwards only that fixture is visible: earlier users, tokens, payments, requests, idempotency records, settlements and operator grants are gone. Repeated resets work. | H, P: reset twice with different fixtures, old token -> 401 |
| B2 | Seeded users can log in at once with the fixture password; seeded `id`, `handle`, `display_name`, `balance` are returned unchanged. | H, P |
| B3 | Seeded `balance` is final: seeded payments are not replayed against it. | P: fixture with a seeded payment, balances equal fixture values |
| B4 | Seeded payments appear in the feed under the feed contract with their seeded `id`, parties, `amount`, `note`, `visibility`; `request_id` and `settlement_id` null; a server-assigned `created_at`. | H, P |
| B5 | Seeded requests appear to their two parties only, keep `id`, `amount`, `note`, `status`; a pending one can be paid, declined, cancelled; a non-pending one behaves as that status. | H, P |
| B6 | A fixture with a `balance` below zero -> 422 `validation_failed` and the previous state is untouched (same tokens, balances, records). | H, P |
| B7 | `minor_units` 0, 2 or 3 with `currency` from the fixture are reported by `GET /me` and on every payment/request/split. One currency per service. | H, P for EUR, JPY, BHD |
| B8 | `payments`, `requests`, `settlement_operator_ids` are optional in the fixture and default to empty. Unparseable reset body -> 400 `malformed_request`, state untouched. **[D]** Any other structurally invalid fixture (not an object, `users` not an array, duplicate user id/handle/email, a record naming an unknown user, `minor_units` outside 0/2/3, non-integer balance) -> 422 `validation_failed`, state untouched. Reason: reset must be all-or-nothing and must not 5xx. | P |
| B9 | Invariant 1: the sum of all wallet balances equals the seeded total after every operation, burst and retry. | H, P: sum `GET /me` over all users after each burst |
| B10 | Invariant 2: no balance is ever negative, even transiently (no debit-then-check ordering that a concurrent reader could observe). | P: concurrent readers during a drain burst; I: debit is guarded in the same atomic step |
| B11 | Invariant 3: a payment request moves money at most once (concurrent pay attempts with different keys: exactly one 201). | P: 50-way burst |
| B12 | Amounts are exact integers end to end; balances up to ±2^53 are exact; responses print amounts as JSON integers, never `1000.0` or exponent form. | P: seed a balance near 2^53, move 1 unit, read back |
| B13 | Handles match `^[a-z0-9_]{1,20}$`, are unique and never change. | P, I |

## C. Errors and input rules (§5, §4 amounts)

| Row | Requirement | Check |
|---|---|---|
| C1 | Unparseable body -> 400 `malformed_request`. **[D]** A body that parses but is not a JSON object (array, string, number, null) -> 400 `malformed_request` (wrong JSON type). An empty body on an endpoint that needs a body is unparseable -> 400. C1 governs the authenticated API endpoints; for `POST /_test/reset` and `POST /_test/import` a body that parses as JSON but is not an object is a structurally invalid fixture/export -> 422 (rows B8, J6). An empty or absent body on `POST /requests/{id}/pay`, whose body is entirely optional, may be treated as `{}`. | H, P |
| C2 | A field of the wrong JSON type -> 400 `malformed_request`, except the endpoint-specific rules in C3..C5. Applies e.g. to `to_handle`, `payer_handle`, `from_handle` as number/null/array, `participant_handles` not an array or holding a non-string, `email`/`password`/`display_name` not strings. | P |
| C3 | `amount`: valid iff a JSON number with integral value in 1..1000000000. `1000`, `1000.0`, `1e3` are the same valid amount. Strings, booleans, `null`, fractions, 0, negatives, above the maximum, and numbers too large to represent (`1e400`) -> 422 `validation_failed`. | H, P |
| C4 | `note`: optional, default `""`. Any non-string including `null` -> 422. More than 200 characters (Unicode code points, not bytes or UTF-16 units) -> 422. Exactly 200 is accepted. Stored and returned verbatim, byte for byte, no trimming, escaping or normalisation. | H, P |
| C5 | `visibility`: optional, default `"public"`. Anything other than exactly `"public"` or `"private"` (including `null`, `""`, `"Public"`, numbers) -> 422. | H, P |
| C6 | A missing required field or required query parameter -> 422 `validation_failed`. | H, P |
| C7 | A value of the right type but invalid format or out of range -> 422 unless the endpoint names another error. **[D]** A string handle that matches no user, including one that cannot match the handle pattern (`""`, `"ADA"`, `"@ada"`), is 404 `not_found`: the endpoint tables name 404 for "no user has that handle", and §5 lets an endpoint-specific error win. | H (accepts 404 or 422), P |
| C8 | `Idempotency-Key` absent or empty -> 400 `missing_idempotency_key`; longer than 255 characters -> 422 `validation_failed`; 1..255 accepted (255 exactly passes, 256 fails). | H, P |
| C9 | `limit`: plain decimal digits, 1..200, default 50. `offset`: plain decimal digits, >= 0, default 0. `0`, `201`, `-5`, `abc`, `1e2`, `4.0`, `+4`, empty string -> 422. Enforced on `GET /requests` and `GET /activity`. An offset beyond the end returns an empty page with `has_more: false`, not an error. | H, P |
| C10 | 401 `unauthenticated` for a missing, malformed or unknown bearer token on every endpoint except `/health`, `/_test/*`, `/auth/signup`, `/auth/login`. | P: no header, `Bearer`, `Basic x`, unknown token, on each route |
| C11 | **[D]** Order of checks on an idempotent write: (1) authentication 401; (2) for settlements, operator permission 403; (3) `Idempotency-Key` presence 400 and length 422; (4) body parses as a JSON object, else 400; (5) an already-claimed key for this caller, method and path: same body -> 200 replay, different body -> 409 `idempotency_key_reuse`; (6) field validation: wrong types 400, rule violations 422; (7) resource checks in the order of D/E/F/H rows; (8) funds 409. Steps 5-before-6-and-7 are stated by §7; the rest are the least surprising order and are recorded so both seats test the same thing. | P |

## D. Authentication (§6, §4 handles)

| Row | Requirement | Check |
|---|---|---|
| D1 | `POST /auth/signup` `{email,password,display_name}` -> 201 `{user_id,display_name,token}`; new balance 0; the user can receive money and be asked for money at once. | H, P |
| D2 | Derived handle: local part of the email, lowercased, every character outside `[a-z0-9_]` replaced by `_`, truncated to 20 characters. No `handle` field is read from the body. | H, P: `Dee.Ann+tag@…` -> `dee_ann_tag`; 30 chars -> 20; non-ASCII local part |
| D3 | Email already registered -> 409 `email_taken`. Derived handle already taken (by a seeded or a signed-up user) -> 409 `handle_taken` and no account is created (login with that email is 401). **[D]** `email_taken` is tested before `handle_taken` (table order); emails compare exactly as given. | H, P |
| D4 | Password shorter than 8 characters -> 422. `email` not of the form `local@domain` (missing `@`, empty local part, empty domain) -> 422. Missing field -> 422; wrong type -> 400. | P |
| D5 | `POST /auth/login` -> 200 `{user_id,display_name,token}`; wrong password or unknown email -> 401 `unauthenticated`. | H, P |
| D6 | Tokens never expire; an account may hold several valid tokens at once (each login issues a working token and does not invalidate earlier ones). | P |
| D7 | Passwords are stored only as a salted password hash (bcrypt, scrypt, Argon2 or equivalent); never in plaintext, in memory, in the export or in logs. Passwords longer than the hash function's native input limit must not be silently truncated into collisions. | I; P: export contains no fixture password string |
| D8 | Hashing cost fits the limits: reset of a fixture with 200 users returns in < 10 s, and 50 concurrent logins each return in < 5 s, on 2 vCPU. Concurrent signups for the same email or the same derived handle create exactly one account. | P |
| D9 | `GET /me` -> `{user_id,display_name,handle,balance,currency,minor_units}`. | H, P |

## E. Payments (§8)

| Row | Requirement | Check |
|---|---|---|
| E1 | `POST /payments` `{to_handle,amount,note?,visibility?}` -> 201 with exactly `payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id (null), settlement_id (null), created_at`. | H, P |
| E2 | Debit and credit are one atomic step; a failed payment leaves no trace in either wallet or in any feed. | H, P |
| E3 | Balance below `amount` -> 409 `insufficient_funds`; paying exactly the balance succeeds and leaves 0. | H, P |
| E4 | `to_handle` is the caller's own -> 422 `self_payment`. No user has the handle -> 404 `not_found`. | H, P |
| E5 | Amount, note, visibility rules C3..C5. **[D]** Precedence: field validation (400/422) -> unknown handle 404 -> `self_payment` -> `insufficient_funds`. | P |
| E6 | Concurrency: N clients each sending the whole balance -> exactly one 201, the rest 409, balance 0; draining in parts never overdraws; a three-wallet cycle of concurrent payments conserves the total and never deadlocks or 5xxs. | H, P at 50 in flight |

## F. Requests (§4, §8)

| Row | Requirement | Check |
|---|---|---|
| F1 | `POST /requests` `{payer_handle,amount,note?}` -> 201 with exactly `request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status "pending", payment_id null, created_at`. Caller is the requester. | H, P |
| F2 | The payer's balance is not checked at creation; a request above it is created and stays pending. A request carries no visibility. | H, P |
| F3 | `payer_handle` is the caller's own -> 422 `self_request`; unknown -> 404; amount and note rules C3, C4. | H, P |
| F4 | `POST /requests/{id}/pay` body `{visibility?}` -> 201 with the created payment (E1 shape) and `request_id` set; the request becomes `paid` and carries `payment_id`; money moves payer -> requester atomically with the status change. | H, P |
| F5 | Pay errors: unknown request 404; caller is not the payer 403 `forbidden` (the requester and any third party alike **[D]**: the pay/decline/cancel tables name 403 for "not the payer/requester"); not pending 409 `request_not_pending`; payer short 409 `insufficient_funds` and nothing changes, the request stays pending and becomes payable once money arrives. **[D]** Precedence: visibility validation -> 404 -> 403 -> not pending -> funds. | H, P |
| F6 | Replaying a successful pay (same key, same body) -> 200 with the original payment even though the request is now `paid`; never 409 `request_not_pending`; no more money moves. `{}` and `{"visibility":"public"}` are different bodies -> 409 `idempotency_key_reuse`. | H, P |
| F7 | `POST /requests/{id}/decline`: payer only, no key needed. 200 with the request `declined`; declining an already declined request is 200 with the current state; `paid` or `cancelled` -> 409 `request_not_pending`; not the payer 403; unknown 404. A body is not required and is ignored. | H, P |
| F8 | `POST /requests/{id}/cancel`: requester only, no key needed. 200 `cancelled`; again on a cancelled one 200; `paid` or `declined` -> 409; not the requester 403; unknown 404. | H, P |
| F9 | A request is `pending` and then exactly one of `paid`, `declined`, `cancelled`; races between pay, decline and cancel resolve to exactly one final state, and money moved iff the final state is `paid`. | P: concurrent pay+decline+cancel bursts |
| F10 | `GET /requests`: only requests where the caller is requester or payer; newest first by `created_at`; `direction` = `incoming` (caller is payer) / `outgoing` (caller is requester) / absent for both; `status` one of the four or absent; unknown `direction` or `status` (including empty) -> 422; `limit`/`offset` per C9; body `{requests:[…], has_more}` with `has_more` true iff items exist past the last returned. | H, P |
| F11 | Requests never appear in `GET /activity`; nobody but the two parties can read a request under any filter, including a settlement operator. | H, P |

(end of part 14 of 15)
